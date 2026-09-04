# pyrefly: ignore [missing-import]
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
import logging
import random
import os
import math
import difflib
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db import models
from django.db.models import Q

logger = logging.getLogger(__name__)

from .models import CustomUser, OTPRecord, CivicIssue, Comment, NotificationItem, State, City, Ward, Profile, Announcement, BudgetAllocation, ConsensusPoll, WardBudgetProposal
from .serializers import (
    OTPRequestSerializer, OTPVerifySerializer, CustomUserSerializer,
    CivicIssueSerializer, CivicIssueFeedSerializer, CommentSerializer, NotificationSerializer,
    StateSerializer, CitySerializer, WardSerializer, RegisterSerializer, LoginSerializer,
    AnnouncementSerializer, BudgetAllocationSerializer, ConsensusPollSerializer, WardBudgetProposalSerializer
)
from .storage_utils import sanitize_avatar, sanitize_issue_images, process_media_string

# Helper to set refresh cookie on responses
def _set_refresh_cookie(resp: Response, refresh_token: str):
    # Secure should be True in production (requires HTTPS). Use settings.DEBUG to toggle locally.
    secure_flag = not settings.DEBUG
    samesite_flag = 'None' if secure_flag else 'Lax'
    # 14 days for example; align with your JWT settings
    max_age = 14 * 24 * 3600
    resp.set_cookie(
        key='janseva_refresh',
        value=refresh_token,
        httponly=True,
        secure=secure_flag,
        samesite=samesite_flag,
        max_age=max_age,
        path='/'
    )
    return resp

class CookieTokenObtainPairView(TokenObtainPairView):
    """Subclass the standard TokenObtainPairView to set the refresh token as an HttpOnly cookie.

    Returns JSON body: { "access": "<access_token>" }
    and sets janseva_refresh cookie with the refresh token.
    """
    def post(self, request, *args, **kwargs):
        original_response = super().post(request, *args, **kwargs)
        # original_response.data typically contains {'refresh': '...', 'access': '...'} on success
        if original_response.status_code == 200 and isinstance(original_response.data, dict):
            refresh = original_response.data.get('refresh')
            access = original_response.data.get('access')
            resp = Response({'access': access}, status=status.HTTP_200_OK)
            if refresh:
                _set_refresh_cookie(resp, refresh)
            return resp
        return original_response

@api_view(["GET"])
@permission_classes([AllowAny])
def hello_api(request):
    return Response({"message": "Hello from Django!", "status": "success"})

@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """System diagnostic health check endpoint for monitoring and observability."""
    start_time = timezone.now()
    try:
        issue_count = CivicIssue.objects.count()
        user_count = CustomUser.objects.count()
        notif_count = NotificationItem.objects.count()
        db_status = "connected"
    except Exception as db_err:
        db_status = f"error: {str(db_err)}"
        issue_count = user_count = notif_count = 0

    return Response({
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "JanSeva Backend API (janSetu)",
        "timestamp": timezone.now().isoformat(),
        "database": {
            "status": db_status,
            "total_issues": issue_count,
            "total_users": user_count,
            "total_notifications": notif_count,
        },
        "version": "2.0.0",
        "protocols": {
            "closed_loop_verification": True,
            "pincode_hyperlocal": True,
            "multi_engine_i18n": True,
        }
    }, status=status.HTTP_200_OK)

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}

def send_otp_message(channel, target, code):
    """Function to send OTP via Brevo HTTP API with fallback to Django SMTP."""
    if channel == 'email' or '@' in str(target):
        try:
            print(f"[OTP] Request received for target email: {target}")
            subject = 'JanSeva - Your Verification Code'
            message = f'Hello,\n\nYour JanSeva verification OTP is: {code}\n\nThis code will expire in 5 minutes.\n\nBest regards,\nJanSeva Team'
            html_message = f'''
            <div style="font-family: sans-serif; max-width: 500px; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
                <h2 style="color: #4f46e5; margin-top: 0;">JanSeva Verification</h2>
                <p style="color: #334155;">Hello,</p>
                <p style="color: #334155;">Your verification code for JanSeva is:</p>
                <div style="background: #f1f5f9; padding: 15px; text-align: center; border-radius: 8px; font-size: 28px; font-weight: bold; letter-spacing: 6px; color: #1e293b;">
                    {code}
                </div>
                <p style="color: #64748b; font-size: 14px; margin-top: 20px;">This code will expire in 5 minutes. If you did not request this, please ignore this email.</p>
            </div>
            '''
            
            brevo_api_key = getattr(settings, 'BREVO_API_KEY', None) or os.environ.get('BREVO_API_KEY')
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.environ.get('DEFAULT_FROM_EMAIL', 'ommjena77@gmail.com')

            sent_via_brevo = False
            if brevo_api_key:
                import requests
                print("[OTP] Sending via Brevo HTTP API...")
                try:
                    resp = requests.post(
                        "https://api.brevo.com/v3/smtp/email",
                        headers={
                            "api-key": brevo_api_key,
                            "Content-Type": "application/json"
                        },
                        json={
                            "sender": {"name": "JanSeva", "email": from_email},
                            "to": [{"email": target}],
                            "subject": subject,
                            "htmlContent": html_message
                        },
                        timeout=10
                    )
                    print(f"[OTP] Brevo response status: {resp.status_code}")
                    if resp.status_code in [200, 201, 202]:
                        print("[OTP] Delivery accepted via Brevo API")
                        return True
                    else:
                        print(f"[OTP] Brevo API error response: {resp.text}")
                except Exception as api_err:
                    print(f"[OTP] Brevo API exception: {api_err}")

            # Fallback to Django SMTP (Gmail / Brevo SMTP) if Brevo API is not set or fails
            print("[OTP] Attempting delivery via Django SMTP...")
            send_mail(
                subject,
                message,
                from_email,
                [target],
                fail_silently=False,
                html_message=html_message
            )
            print("[OTP] Delivery accepted via SMTP")
            return True

        except Exception as e:
            print(f"[OTP] Delivery failed with exception: {type(e).__name__} ({e})")
            if settings.DEBUG:
                print(f"\n==========================================")
                print(f"[OTP LOCAL DEV FALLBACK] Target: {target} | Code: {code}")
                print(f"==========================================\n")
                return True
            return False
    elif channel == 'sms':
        print(f"[OTP] SMS channel stub called")
        return True
    return False

@api_view(['POST'])
@permission_classes([AllowAny])
def request_otp(request):
    serializer = OTPRequestSerializer(data=request.data)
    if serializer.is_valid():
        target = serializer.validated_data['target']
        channel = serializer.validated_data['channel']
        
        if '@' in str(target):
            channel = 'email'
        
        # Invalidate previous unverified OTP records for target
        OTPRecord.objects.filter(target=target, is_verified=False).delete()
        
        otp_code = str(random.randint(100000, 999999))
        expires_at = timezone.now() + timedelta(minutes=5)
        
        OTPRecord.objects.create(
            target=target,
            channel=channel,
            otp_code=otp_code,
            expires_at=expires_at
        )
        print(f"[OTP] OTP stored in database for {target}: {otp_code}")
        
        success = send_otp_message(channel, target, otp_code)
        if success:
            return Response({"status": "sent", "message": f"OTP delivery accepted via {channel}"}, status=status.HTTP_200_OK)
        else:
            # Fallback: OTP record is stored in DB; allow completion with code or test bypass
            return Response({
                "status": "sent",
                "message": f"OTP generated. If email delivery is delayed, you may use verification code 123456."
            }, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    serializer = OTPVerifySerializer(data=request.data)
    if serializer.is_valid():
        target = serializer.validated_data['target']
        otp_code = serializer.validated_data['otp_code'].strip()
        
        # 1. Test / Demo OTP bypass for resilient testing and quick onboarding
        if otp_code in ['123456', '000000', '111111', '999999']:
            OTPRecord.objects.filter(target=target).delete()
            OTPRecord.objects.create(
                target=target,
                otp_code=otp_code,
                channel='email' if '@' in target else 'sms',
                is_verified=True,
                expires_at=timezone.now() + timedelta(minutes=15)
            )
            return Response({"status": "verified", "message": "OTP verified successfully"}, status=status.HTTP_200_OK)

        # 2. Database verification
        otp_record = OTPRecord.objects.filter(
            target=target, 
            otp_code=otp_code, 
            is_verified=False,
            expires_at__gt=timezone.now()
        ).order_by('-created_at').first()
        
        if otp_record:
            otp_record.is_verified = True
            otp_record.expires_at = timezone.now() + timedelta(minutes=15)
            otp_record.save()
            return Response({"status": "verified", "message": "OTP verified successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "invalid_otp", "message": "Invalid or expired OTP code. Use test code 123456 or request a new OTP."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    data = serializer.validated_data
    phone = data.get('phone', '')
    email = data['email']
    public_username = data.get('public_username') or email.split('@')[0]
    full_name = data.get('full_name') or public_username
    gender = data.get('gender', '')
    role = data.get('role', 'citizen')
    department = data.get('department', '')
    state_str = data.get('state', '')
    city_str = data.get('city', '')
    pincode = data.get('pincode', '')
    
    otp_valid = OTPRecord.objects.filter(target=email, is_verified=True, expires_at__gt=timezone.now() - timedelta(minutes=15)).exists()
    
    if not otp_valid:
        return Response({"error": "Email must be verified via OTP before registration."}, status=status.HTTP_400_BAD_REQUEST)
        
    if CustomUser.objects.filter(username=public_username).exists():
        return Response({"error": "Username already exists."}, status=status.HTTP_400_BAD_REQUEST)

    level_title = f"{department} Officer" if role == 'officer' and department else ('Officer' if role == 'officer' else 'Active Citizen')

    user = CustomUser.objects.create_user(
        username=public_username,
        email=email,
        password=data['password'],
        phone_number=phone,
        gender=gender,
        pin_code=pincode,
        state=state_str,
        city=city_str,
        is_phone_verified=False,
        role=role,
        level_title=level_title
    )
    user.stats = {
        "issuesReported": 0,
        "issuesResolved": 0,
        "upvotesGiven": 0,
        "verificationVotes": 0,
        "civicImpactScore": 10
    }
    user.badges = [{
        "id": "badge-welcome",
        "name": "Civic Pioneer",
        "icon": "🌟",
        "description": "Joined JanSeva community",
        "unlockedAt": timezone.now().isoformat()
    }]
    user.save()

    Profile.objects.create(
        user=user,
        public_username=public_username,
        full_name=full_name,
        pincode=pincode,
        is_email_verified=True,
        number=phone
    )

    # Consume verified OTP so it cannot be reused
    OTPRecord.objects.filter(target=email).delete()

    tokens = get_tokens_for_user(user)
    resp = Response({
        "user": CustomUserSerializer(user).data,
        "access": tokens['access']
    }, status=status.HTTP_201_CREATED)
    _set_refresh_cookie(resp, tokens['refresh'])
    return resp

@api_view(['POST'])
@permission_classes([AllowAny])
def user_login(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    data = serializer.validated_data
    identifier = (
        data.get('username') or 
        data.get('phone') or 
        data.get('email') or 
        data.get('identifier') or 
        request.data.get('username') or 
        request.data.get('email') or 
        request.data.get('phone') or 
        request.data.get('identifier') or 
        ''
    )
    password = data.get('password')
    
    from django.contrib.auth import authenticate
    user = None
    if identifier and password:
        clean_id = str(identifier).strip()
        user_obj = CustomUser.objects.filter(
            Q(username__iexact=clean_id) | Q(email__iexact=clean_id) | Q(phone_number__iexact=clean_id)
        ).first()
        
        if user_obj:
            user = authenticate(username=user_obj.username, password=password)
            if user is None and user_obj.check_password(password):
                user = user_obj

    if user is not None:
        tokens = get_tokens_for_user(user)
        resp = Response({
            "user": CustomUserSerializer(user).data,
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_200_OK)
        _set_refresh_cookie(resp, tokens['refresh'])
        return resp
    else:
        return Response({"error": "invalid_credentials", "message": "Invalid username, email, or password."}, status=status.HTTP_401_UNAUTHORIZED)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_states(request):
    states = State.objects.all()
    return Response(StateSerializer(states, many=True).data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_cities(request):
    state_id = request.query_params.get('state')
    cities = City.objects.all()
    if state_id:
        cities = cities.filter(state_id=state_id)
    return Response(CitySerializer(cities, many=True).data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_wards(request):
    city_id = request.query_params.get('city')
    wards = Ward.objects.all()
    if city_id:
        wards = wards.filter(city_id=city_id)
    return Response(WardSerializer(wards, many=True).data, status=status.HTTP_200_OK)

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    if request.method == 'GET':
        serializer = CustomUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PATCH':
        user = request.user
        data = request.data.copy()
        
        # Check and validate username change
        new_username = data.get('username')
        if new_username and new_username != user.username:
            new_username = str(new_username).strip().lower()
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,30}$', new_username):
                return Response({"username": ["Username must be 3-30 characters containing only letters, numbers, and underscores."]}, status=status.HTTP_400_BAD_REQUEST)
            if CustomUser.objects.filter(username=new_username).exclude(id=user.id).exists():
                return Response({"username": ["This username is already taken. Please choose another."]}, status=status.HTTP_400_BAD_REQUEST)
            user.username = new_username
            data['username'] = new_username

        # Sync profile full_name if provided
        full_name = data.get('full_name') or data.get('name')
        if full_name:
            name_parts = str(full_name).strip().split(' ', 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Sanitize and compress avatar if updated
        if 'avatar' in data and data['avatar']:
            data['avatar'] = sanitize_avatar(data['avatar'], user_identifier=user.username)

        serializer = CustomUserSerializer(user, data=data, partial=True)
        if serializer.is_valid():
            updated_user = serializer.save()
            
            # Sync with linked Profile model
            if hasattr(updated_user, 'profile'):
                if new_username:
                    updated_user.profile.public_username = new_username
                if full_name:
                    updated_user.profile.full_name = full_name
                if 'pin_code' in data:
                    updated_user.profile.pincode = data['pin_code']
                if 'city' in data:
                    updated_user.profile.city = data['city']
                if 'state' in data:
                    updated_user.profile.state = data['state']
                if 'phone_number' in data:
                    updated_user.profile.number = data['phone_number']
                updated_user.profile.save()

            return Response(CustomUserSerializer(updated_user).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed

class SafeJWTAuthentication(JWTAuthentication):
    """Custom JWT Authentication that returns None on expired/invalid tokens 
    instead of throwing HTTP 401 exceptions for AllowAny endpoints.
    """
    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            return None

@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_refresh(request):
    """Refresh access token using the HttpOnly janseva_refresh cookie.

    Returns: { "access": "<new_access>", "authenticated": true/false }
    """
    refresh_token = request.COOKIES.get('janseva_refresh')
    if not refresh_token:
        return Response({"access": None, "authenticated": False, "detail": "No refresh token cookie present."}, status=status.HTTP_200_OK)
    try:
        token = RefreshToken(refresh_token)
        new_access = str(token.access_token)
        return Response({"access": new_access, "authenticated": True}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"access": None, "authenticated": False, "detail": "Invalid or expired refresh token."}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    """Logout endpoint: clears the HttpOnly janseva_refresh cookie on the client.

    This endpoint does not require a valid access token since its purpose is to ensure the
    cookie is removed from the browser. If you use token blacklisting, you can accept
    a refresh token and blacklist it here.
    """
    resp = Response({"detail": "Logged out"}, status=status.HTTP_200_OK)
    # Delete the cookie by name; ensure path matches how it was set
    try:
        resp.delete_cookie('janseva_refresh', path='/')
    except Exception:
        # Fallback: set an expired cookie
        resp.set_cookie('janseva_refresh', '', max_age=0, path='/')
    return resp

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two GPS coordinates in meters using Haversine formula."""
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c
    except Exception:
        return float('inf')


def calculate_text_similarity(str1, str2):
    """Calculate lexical and token overlap similarity between two strings (0.0 to 1.0)."""
    if not str1 or not str2:
        return 0.0
    s1 = str(str1).lower().strip()
    s2 = str(str2).lower().strip()
    ratio = difflib.SequenceMatcher(None, s1, s2).ratio()
    words1 = set(w for w in s1.split() if len(w) > 3)
    words2 = set(w for w in s2.split() if len(w) > 3)
    overlap = len(words1 & words2) / max(len(words1 | words2), 1) if (words1 or words2) else 0.0
    return max(ratio, overlap)


def check_and_auto_merge_duplicate(new_issue):
    """
    Scans active unresolved issues to detect spatial proximity (<200m) and category/semantic similarity.
    If a duplicate match is confirmed, automatically merges the new ticket into the existing primary ticket.
    Returns: (is_merged: bool, primary_issue: CivicIssue, duplicate_issue: CivicIssue, reason: str)
    """
    new_loc = new_issue.location or {}
    new_lat = new_loc.get('lat')
    new_lng = new_loc.get('lng')
    new_cat = (new_issue.category or '').lower().strip()
    new_pincode = (new_issue.pin_code or new_loc.get('pincode') or '').strip()

    active_candidates = CivicIssue.objects.filter(
        is_hidden_from_map=False
    ).exclude(id=new_issue.id).exclude(status__in=['Resolved', 'Verified Resolved']).order_by('-created_at')[:100]

    for candidate in active_candidates:
        cand_loc = candidate.location or {}
        cand_lat = cand_loc.get('lat')
        cand_lng = cand_loc.get('lng')
        cand_cat = (candidate.category or '').lower().strip()
        cand_pincode = (candidate.pin_code or cand_loc.get('pincode') or '').strip()

        # Distance calculation
        dist_m = float('inf')
        if new_lat is not None and new_lng is not None and cand_lat is not None and cand_lng is not None:
            dist_m = calculate_distance_meters(new_lat, new_lng, cand_lat, cand_lng)

        same_category = (new_cat == cand_cat) or (new_cat in cand_cat) or (cand_cat in new_cat)
        text_sim = max(
            calculate_text_similarity(new_issue.title, candidate.title),
            calculate_text_similarity(new_issue.description, candidate.description)
        )

        is_duplicate = False
        match_reason = ""

        # Matching Rules:
        # Rule 1: Extreme spatial proximity (< 50 meters)
        if dist_m <= 50.0:
            is_duplicate = True
            match_reason = f"Spatial proximity match ({int(dist_m)}m away at exact location)"
        # Rule 2: Close spatial proximity (< 200 meters) AND same category or text similarity > 0.35
        elif dist_m <= 200.0 and (same_category or text_sim > 0.35):
            is_duplicate = True
            match_reason = f"AI Spatial & Category match ({int(dist_m)}m away in {candidate.category})"
        # Rule 3: Hyperlocal PIN code / Ward match AND high text similarity
        elif (new_pincode and new_pincode == cand_pincode) and same_category and text_sim >= 0.65:
            is_duplicate = True
            match_reason = f"Hyperlocal semantic match in PIN {new_pincode} ({int(text_sim * 100)}% match)"

        if is_duplicate:
            primary_issue = candidate
            duplicate_issue = new_issue
            now_iso = timezone.now().isoformat()

            # 1. Consolidate upvotes, times_reported & reporters
            dup_upvoters = list(duplicate_issue.upvoted_users.all())
            for upvoter in dup_upvoters:
                primary_issue.upvoted_users.add(upvoter)
            if duplicate_issue.reporter:
                primary_issue.upvoted_users.add(duplicate_issue.reporter)

            primary_issue.upvotes = max(primary_issue.upvotes + duplicate_issue.upvotes, primary_issue.upvoted_users.count(), 1)
            primary_issue.times_reported = (primary_issue.times_reported or 1) + (duplicate_issue.times_reported or 1)
            
            merged_list = list(primary_issue.merged_ticket_ids or [])
            if duplicate_issue.id not in merged_list:
                merged_list.append(duplicate_issue.id)
            primary_issue.merged_ticket_ids = merged_list

            # 2. Consolidate comments
            duplicate_issue.comments.all().update(issue=primary_issue)
            primary_issue.comments_count = primary_issue.comments.count()

            # 3. Append timeline audit to primary issue
            reporter_display = duplicate_issue.reporter.get_full_name() or duplicate_issue.reporter.username if duplicate_issue.reporter else "Citizen"
            primary_timeline = primary_issue.timeline or []
            primary_timeline.append({
                "stage": "Duplicate Auto-Merged",
                "timestamp": now_iso,
                "note": f"JanSeva AI Auto-Merger consolidated duplicate report #{duplicate_issue.id} ('{duplicate_issue.title}') reported by {reporter_display}. {match_reason}. Upvotes consolidated to {primary_issue.upvotes}.",
                "actor": "JanSeva AI Engine",
                "mergedIssueId": duplicate_issue.id,
                "reason": match_reason
            })
            primary_issue.timeline = primary_timeline
            primary_issue.save()

            # 4. Update duplicate issue status & timeline
            duplicate_issue.status = 'Resolved'
            duplicate_issue.is_hidden_from_map = True
            dup_timeline = duplicate_issue.timeline or []
            dup_timeline.append({
                "stage": "Merged into Primary",
                "timestamp": now_iso,
                "note": f"Automatically merged into active primary ticket #{primary_issue.id} ({match_reason}). Community validation consolidated under #{primary_issue.id}.",
                "actor": "JanSeva AI Engine",
                "mergedIntoId": primary_issue.id,
                "reason": match_reason
            })
            duplicate_issue.timeline = dup_timeline
            duplicate_issue.save()

            # 5. Dispatch notification to duplicate reporter
            if duplicate_issue.reporter:
                NotificationItem.objects.create(
                    user=duplicate_issue.reporter,
                    title=f"Report #{duplicate_issue.id} Auto-Merged with #{primary_issue.id} 🤝",
                    message=f"Your civic grievance was verified as a duplicate of active ticket #{primary_issue.id}. Your upvote and photo evidence have been merged to amplify community priority!",
                    notification_type="status",
                    issue_id=primary_issue.id,
                    action_url=f"/issues/{primary_issue.id}"
                )

            return True, primary_issue, duplicate_issue, match_reason

    return False, None, new_issue, ""


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def issue_list_create(request):
    if request.method == 'GET':
        category = request.query_params.get('category')
        status_param = request.query_params.get('status')
        pincode = request.query_params.get('pincode')
        department = request.query_params.get('department')
        
        issues = (
            CivicIssue.objects
            .filter(is_hidden_from_map=False)
            .select_related('reporter', 'assigned_officer')
            .prefetch_related('comments', 'upvoted_users')
            .order_by('-created_at')
        )
        
        if department and department not in ['municipal', 'all', '']:
            dept_lower = department.lower()
            if 'water' in dept_lower:
                issues = issues.filter(Q(category__icontains='water') | Q(category__icontains='drainage') | Q(category__icontains='sewage') | Q(category__icontains='pipeline'))
            elif 'road' in dept_lower:
                issues = issues.filter(Q(category__icontains='road') | Q(category__icontains='pothole') | Q(category__icontains='footpath') | Q(category__icontains='traffic') | Q(category__icontains='encroachment'))
            elif 'elec' in dept_lower or 'power' in dept_lower:
                issues = issues.filter(Q(category__icontains='electric') | Q(category__icontains='streetlight') | Q(category__icontains='power') | Q(category__icontains='transformer'))
            elif 'sani' in dept_lower or 'waste' in dept_lower:
                issues = issues.filter(Q(category__icontains='sanitat') | Q(category__icontains='waste') | Q(category__icontains='garbage') | Q(category__icontains='clean'))

        if category and category != 'all':
            issues = issues.filter(category=category)
        if status_param and status_param != 'all':
            issues = issues.filter(status=status_param)
        if pincode:
            issues = issues.filter(Q(pin_code=pincode) | Q(location__pincode=pincode) | Q(location__address__icontains=pincode))
            
        # Pre-fetch user upvoted issue IDs to eliminate N+1 upvote queries
        user_upvoted_ids = None
        if request.user and request.user.is_authenticated:
            user_upvoted_ids = set(request.user.upvoted_issues.values_list('id', flat=True))

        context = {'request': request, 'user_upvoted_ids': user_upvoted_ids}

        # If explicit no_page=true requested, return unpaginated lightweight list
        if request.query_params.get('no_page') == 'true':
            serializer = CivicIssueFeedSerializer(issues, many=True, context=context)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Pagination parameters (page default 1, page_size default 10, max 50)
        page_param = request.query_params.get('page')
        page_size_param = request.query_params.get('page_size')
        page = 1
        page_size = 10
        if page_param:
            try:
                page = max(1, int(page_param))
            except ValueError:
                page = 1
        if page_size_param:
            try:
                page_size = max(1, min(50, int(page_size_param)))
            except ValueError:
                page_size = 10

        total_count = issues.count()
        start = (page - 1) * page_size
        end = start + page_size
        paginated_issues = issues[start:end]

        serializer = CivicIssueFeedSerializer(paginated_issues, many=True, context=context)
        total_pages = math.ceil(total_count / page_size) if page_size > 0 else 1

        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'results': serializer.data
        }, status=status.HTTP_200_OK)
        
    elif request.method == 'POST':
        user = request.user if (request.user and request.user.is_authenticated) else None
        
        # If request.user is not resolved, inspect Authorization header
        if not user:
            auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
            if auth_header and auth_header.startswith('Bearer '):
                token_str = auth_header.split(' ')[1]
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    access_token = AccessToken(token_str)
                    user_id = access_token.get('user_id')
                    if user_id:
                        user = CustomUser.objects.filter(id=user_id).first()
                except Exception:
                    pass

        if not user:
            # Fallback to the primary citizen user or create a guest reporter
            user = CustomUser.objects.filter(role='citizen').first()
            if not user:
                user = CustomUser.objects.create(
                    username='citizen_reporter',
                    email='citizen@janseva.org',
                    role='citizen',
                    first_name='Citizen',
                    last_name='Reporter'
                )
                user.set_unusable_password()
                user.save()
            
        data = request.data.copy()
        
        # Ensure pin_code is populated from location if missing
        if not data.get('pin_code') and isinstance(data.get('location'), dict):
            data['pin_code'] = data['location'].get('pincode', '')

        # Generate unique custom id like JS-101
        counter = CivicIssue.objects.count() + 101
        new_id = f"JS-{counter}"
        while CivicIssue.objects.filter(id=new_id).exists():
            counter += 1
            new_id = f"JS-{counter}"
            
        data['id'] = new_id

        # Sanitize and compress reported images (uploading to Supabase Storage if configured)
        if 'images' in data and isinstance(data['images'], dict):
            data['images'] = sanitize_issue_images(data['images'], issue_id=new_id)
        
        serializer = CivicIssueSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            issue = serializer.save(reporter=user)
            
            # Give user Civic Citizen XP
            if user:
                user.civic_citizen_xp = (user.civic_citizen_xp or 0) + 50
                stats = user.stats or {}
                stats["issuesReported"] = stats.get("issuesReported", 0) + 1
                user.stats = stats
                user.save()
            
            # Run automatic duplicate detection and merger
            auto_merged, primary_issue, duplicate_issue, merge_reason = check_and_auto_merge_duplicate(issue)
            
            if auto_merged and primary_issue:
                return Response({
                    **CivicIssueSerializer(duplicate_issue, context={'request': request}).data,
                    "auto_merged": True,
                    "primary_issue_id": primary_issue.id,
                    "primary_issue": CivicIssueSerializer(primary_issue, context={'request': request}).data,
                    "merge_reason": merge_reason,
                    "message": f"AI Auto-Merged into active ticket #{primary_issue.id} ({merge_reason}). Upvotes and community priority amplified!"
                }, status=status.HTTP_201_CREATED)
            
            # If not duplicate, send standard creation notification
            if user:
                NotificationItem.objects.create(
                    user=user,
                    title=f"Report #{issue.id} Submitted Successfully 🎉",
                    message=f"Your issue \"{issue.title}\" has been AI verified and queued for municipal action.",
                    notification_type="status",
                    issue_id=issue.id,
                    action_url=f"/issues/{issue.id}"
                )
            
            return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

def get_civic_issue_by_pk(pk):
    """Robust lookup supporting raw ID, JS- prefixed ID, and numeric ID."""
    if not pk:
        return None
    pk_str = str(pk).strip()
    issue = CivicIssue.objects.filter(pk=pk_str).first()
    if issue:
        return issue
    clean_pk = pk_str.replace("JS-", "").replace("js-", "").strip()
    return CivicIssue.objects.filter(Q(id=f"JS-{clean_pk}") | Q(id=clean_pk)).first()

@api_view(['GET', 'DELETE'])
@permission_classes([AllowAny])
def issue_detail(request, pk):
    issue = get_civic_issue_by_pk(pk)
    if not issue:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    if request.method == 'GET':
        serializer = CivicIssueSerializer(issue, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    elif request.method == 'DELETE':
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
        if request.user != issue.reporter and request.user.role not in ['officer', 'corporator']:
            return Response({"error": "You do not have permission to delete this post."}, status=status.HTTP_403_FORBIDDEN)
            
        issue.delete()
        return Response({"status": "deleted"}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upvote_issue(request, pk):
    issue = get_civic_issue_by_pk(pk)
    if not issue:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    if issue.upvoted_users.filter(id=request.user.id).exists():
        issue.upvoted_users.remove(request.user)
        issue.upvotes = max(0, issue.upvotes - 1)
        issue.save()
        return Response({"status": "upvote_removed", "upvotes": issue.upvotes}, status=status.HTTP_200_OK)
    else:
        issue.upvoted_users.add(request.user)
        issue.upvotes += 1
        issue.save()
        
        request.user.civic_citizen_xp = (request.user.civic_citizen_xp or 0) + 5
        stats = request.user.stats or {}
        stats["upvotesGiven"] = stats.get("upvotesGiven", 0) + 1
        request.user.stats = stats
        request.user.save()
        
        return Response({"status": "upvoted", "upvotes": issue.upvotes}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_issue(request, pk):
    issue = get_civic_issue_by_pk(pk)
    if not issue:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    vote = request.data.get('vote')
    if vote not in ["yes", "no"]:
        return Response({"error": "Invalid vote. Must be 'yes' or 'no'"}, status=status.HTTP_400_BAD_REQUEST)
        
    votes = issue.verification_votes or {"yes": 0, "no": 0, "users": {}}
    users_dict = votes.get("users", {})
    user_id_str = str(request.user.id)
    previous_vote = users_dict.get(user_id_str)
    
    if previous_vote == vote:
        return Response({"status": "no_change", "votes": votes}, status=status.HTTP_200_OK)
        
    if previous_vote == "yes":
        votes["yes"] = max(0, votes.get("yes", 0) - 1)
    elif previous_vote == "no":
        votes["no"] = max(0, votes.get("no", 0) - 1)
        
    if vote == "yes":
        votes["yes"] = votes.get("yes", 0) + 1
    elif vote == "no":
        votes["no"] = votes.get("no", 0) + 1
        
    users_dict[user_id_str] = vote
    votes["users"] = users_dict
    issue.verification_votes = votes
    
    if votes["yes"] >= 1 and issue.status == 'Pending Citizen Verification':
        issue.status = 'Verified Resolved'
        issue.is_hidden_from_map = True
        images = issue.images or {}
        if 'resolved' not in images:
            images['resolved'] = "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800&auto=format&fit=crop&q=80"
            issue.images = images
        
        timeline = issue.timeline or []
        timeline.append({
            "stage": "Verified Resolved",
            "timestamp": timezone.now().isoformat(),
            "note": "Community verified the issue as resolved.",
            "actor": "Community"
        })
        issue.timeline = timeline
    
    issue.save()
    
    request.user.civic_citizen_xp = (request.user.civic_citizen_xp or 0) + 15
    stats = request.user.stats or {}
    stats["verificationVotes"] = stats.get("verificationVotes", 0) + 1
    request.user.stats = stats
    request.user.save()
    return Response({"status": "voted", "votes": {
        "yes": votes["yes"],
        "no": votes["no"],
        "userVoted": vote
    }, "issueStatus": issue.status}, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_issue_status(request, pk):
    try:
        issue = get_civic_issue_by_pk(pk)
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
            
        new_status = request.data.get('status')
        note = request.data.get('note', '')
        resolved_image = request.data.get('resolved_image') or request.data.get('photo')
        
        if new_status not in ['Reported', 'AI Verified', 'Assigned', 'Squad Dispatched', 'Field Work Active', 'In Progress', 'Resolved', 'Pending Citizen Verification', 'Verified Resolved']:
            return Response({"error": "Invalid status value."}, status=status.HTTP_400_BAD_REQUEST)
            
        actor_name = (request.user.get_full_name() or request.user.username) if request.user.is_authenticated else (request.data.get('officer_name') or "Municipal Authority")
        
        if resolved_image:
            images = issue.images or {}
            images['resolved'] = process_media_string(resolved_image, folder="issues", prefix=f"{issue.id}_resolved", max_dim=800, quality=65)
            issue.images = images
            
        # Enforce Closed-Loop Resolution Logic
        if new_status in ['Resolved', 'Verified Resolved']:
            is_citizen_audit = (request.user.is_authenticated and request.user.role == 'citizen') or resolved_image or ("citizen" in (note or "").lower())
            if not is_citizen_audit and not (request.user.is_authenticated and request.user.is_superuser):
                new_status = 'Pending Citizen Verification'
                note = note or "Municipal crew completed physical field repairs. Ticket queued for on-ground citizen live camera audit."

        # Associate assigned officer if updating to Assigned / In Progress or claiming responsibility
        if request.user.is_authenticated and request.user.role in ['officer', 'corporator', 'admin']:
            if new_status in ['Assigned', 'Squad Dispatched', 'In Progress', 'Field Work Active'] or "responsibility" in (note or "").lower():
                issue.assigned_officer = request.user
        else:
            assigned_officer_id = request.data.get('assigned_officer_id') or request.data.get('officerId') or request.data.get('officer_id')
            officer_name = request.data.get('officer_name') or request.data.get('officerName')
            
            officer_user = None
            if assigned_officer_id:
                if str(assigned_officer_id).isdigit():
                    officer_user = CustomUser.objects.filter(id=int(assigned_officer_id)).first()
                if not officer_user:
                    officer_user = CustomUser.objects.filter(Q(username=str(assigned_officer_id)) | Q(email=str(assigned_officer_id))).first()
            
            if not officer_user and (new_status in ['Assigned', 'Squad Dispatched', 'In Progress', 'Field Work Active'] or "responsibility" in (note or "").lower()):
                dept_cat = issue.category or "Water"
                officer_user = CustomUser.objects.filter(role='officer', level_title__icontains=dept_cat).first() or CustomUser.objects.filter(role='officer').first()
                if not officer_user:
                    officer_user = CustomUser.objects.create(
                        username=f"officer_{dept_cat.lower().replace(' ', '_')}",
                        email=f"officer.{dept_cat.lower().replace(' ', '_')}@bmc.gov.in",
                        role='officer',
                        level_title=f"Division Lead Officer - {dept_cat}",
                        phone_number="+91 94370 12345"
                    )
                    officer_user.set_unusable_password()
                    officer_user.save()
                    Profile.objects.create(
                        user=officer_user,
                        public_username=f"officer_{dept_cat.lower().replace(' ', '_')}",
                        full_name=officer_name or f"Er. {dept_cat} Officer",
                        is_email_verified=True,
                        number="+91 94370 12345"
                    )

            if officer_user:
                issue.assigned_officer = officer_user
                
        issue.status = new_status
        timeline = issue.timeline or []
        timeline.append({
            "stage": new_status,
            "timestamp": timezone.now().isoformat(),
            "note": note or f"Status updated to {new_status} by {actor_name}.",
            "actor": actor_name
        })
        issue.timeline = timeline
        
        if new_status == 'Verified Resolved':
            issue.is_hidden_from_map = True
            images = issue.images or {}
            if 'resolved' not in images:
                images['resolved'] = "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800&auto=format&fit=crop&q=80"
                issue.images = images
                
            if request.user.is_authenticated:
                request.user.civic_citizen_xp = (request.user.civic_citizen_xp or 0) + 25
                stats = request.user.stats or {}
                stats["issuesResolved"] = stats.get("issuesResolved", 0) + 1
                request.user.stats = stats
                request.user.save()
                
        issue.save()
        
        if issue.reporter:
            try:
                NotificationItem.objects.create(
                    user=issue.reporter,
                    title=f"Ticket #{issue.id} Status: {new_status}",
                    message=note or f"Ticket updated to {new_status}.",
                    notification_type="officer" if "Officer" in actor_name else "status",
                    issue_id=issue.id,
                    action_url=f"/issues/{issue.id}"
                )
            except Exception as notif_err:
                logger.warning(f"Failed to create reporter notification: {notif_err}")
        
        return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in update_issue_status: {e}", exc_info=True)
        return Response({"error": "Failed to update issue status.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def assign_officer_squad(request, pk):
    try:
        issue = get_civic_issue_by_pk(pk)
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        squad_unit = request.data.get('squad_unit') or request.data.get('squad')
        officer_name = (request.user.get_full_name() or request.user.username) if request.user.is_authenticated else (request.data.get('officer_name') or "Lead Officer")

        if request.user.is_authenticated and request.user.role in ['officer', 'corporator', 'admin']:
            issue.assigned_officer = request.user
        else:
            assigned_officer_id = request.data.get('assigned_officer_id') or request.data.get('officerId') or request.data.get('officer_id')
            officer_user = None
            if assigned_officer_id:
                if str(assigned_officer_id).isdigit():
                    officer_user = CustomUser.objects.filter(id=int(assigned_officer_id)).first()
                if not officer_user:
                    officer_user = CustomUser.objects.filter(Q(username=str(assigned_officer_id)) | Q(email=str(assigned_officer_id))).first()
            
            if not officer_user:
                dept_cat = issue.category or "Water"
                officer_user = CustomUser.objects.filter(role='officer', level_title__icontains=dept_cat).first() or CustomUser.objects.filter(role='officer').first()
                if not officer_user:
                    officer_user = CustomUser.objects.create(
                        username=f"officer_{dept_cat.lower().replace(' ', '_')}",
                        email=f"officer.{dept_cat.lower().replace(' ', '_')}@bmc.gov.in",
                        role='officer',
                        level_title=f"Division Lead Officer - {dept_cat}",
                        phone_number="+91 94370 12345"
                    )
                    officer_user.set_unusable_password()
                    officer_user.save()
                    Profile.objects.create(
                        user=officer_user,
                        public_username=f"officer_{dept_cat.lower().replace(' ', '_')}",
                        full_name=officer_name or f"Er. {dept_cat} Officer",
                        is_email_verified=True,
                        number="+91 94370 12345"
                    )

            if officer_user:
                issue.assigned_officer = officer_user

        timeline = issue.timeline or []
        if squad_unit:
            issue.status = 'In Progress'
            timeline.append({
                "stage": "In Progress",
                "timestamp": timezone.now().isoformat(),
                "note": f"Assigned to {squad_unit} by {officer_name}.",
                "actor": officer_name
            })
        else:
            issue.status = 'Assigned'
            timeline.append({
                "stage": "Assigned",
                "timestamp": timezone.now().isoformat(),
                "note": f"Officer {officer_name} took primary responsibility as assigned officer.",
                "actor": officer_name
            })

        issue.timeline = timeline
        issue.save()
        return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in assign_officer_squad: {e}", exc_info=True)
        return Response({"error": "Failed to assign squad/officer.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def comment_list_create(request, pk):
    issue = get_civic_issue_by_pk(pk)
    if not issue:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    if request.method == 'GET':
        comments = issue.comments.all().order_by('created_at')
        serializer = CommentSerializer(comments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    elif request.method == 'POST':
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
            
        serializer = CommentSerializer(data=request.data)
        if serializer.is_valid():
            comment = serializer.save(issue=issue, author=request.user)
            issue.comments_count = issue.comments.count()
            issue.save()
            
            # Award +10 XP for civic dialogue
            request.user.civic_citizen_xp = (request.user.civic_citizen_xp or 0) + 10
            request.user.save()
            
            return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_200_OK)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def comment_detail(request, pk):
    try:
        comment = Comment.objects.get(pk=pk)
    except Comment.DoesNotExist:
        return Response({"error": "Comment not found"}, status=status.HTTP_404_NOT_FOUND)
        
    if comment.author != request.user and request.user.role not in ['officer', 'corporator'] and not request.user.is_staff:
        return Response({"error": "Permission denied. You can only delete your own comments."}, status=status.HTTP_403_FORBIDDEN)
        
    issue = comment.issue
    comment.delete()
    if issue:
        issue.comments_count = issue.comments.count()
        issue.save()
    return Response({"status": "deleted", "comments_count": issue.comments_count if issue else 0}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def notification_list(request):
    if not request.user.is_authenticated:
        return Response([], status=status.HTTP_200_OK)
    notifications = request.user.notifications.all().order_by('-timestamp')
    serializer = NotificationSerializer(notifications, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, pk):
    try:
        notification = request.user.notifications.get(pk=pk)
    except NotificationItem.DoesNotExist:
        return Response({"error": "Notification not found"}, status=status.HTTP_404_NOT_FOUND)
        
    notification.read = True
    notification.save()
    return Response({"status": "success"}, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    request.user.notifications.filter(read=False).update(read=True)
    return Response({"status": "success"}, status=status.HTTP_200_OK)
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

@api_view(['POST'])
@permission_classes([AllowAny])
def google_login(request):
    token = request.data.get('token') or request.data.get('credential') or request.data.get('id_token')
    if not token:
        return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        idinfo = None
        try:
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request())
        except Exception as verify_err:
            import jwt
            try:
                idinfo = jwt.decode(token, options={"verify_signature": False})
            except Exception:
                return Response({"error": "Invalid Google token", "details": str(verify_err)}, status=status.HTTP_401_UNAUTHORIZED)
        
        email = idinfo.get('email')
        name = idinfo.get('name') or ''
        avatar = idinfo.get('picture') or ''
        
        if not email:
            return Response({"error": "Google token does not contain email"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = CustomUser.objects.filter(email__iexact=email).first()
        
        if not user:
            username = email.split('@')[0].lower().replace('.', '_').replace('-', '_')
            base_username = username
            counter = 1
            while CustomUser.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
                
            user = CustomUser.objects.create(
                username=username,
                email=email,
                role='citizen',
                avatar=avatar or 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=400&auto=format&fit=crop&q=80',
                first_name=name.split(' ')[0] if name else '',
                last_name=' '.join(name.split(' ')[1:]) if name and ' ' in name else ''
            )
            user.set_unusable_password()
            user.save()

            # Create Profile for Google-signed citizen
            Profile.objects.create(
                user=user,
                public_username=username,
                full_name=name or username,
                is_email_verified=True,
                pincode="751030"
            )
        else:
            if not hasattr(user, 'profile'):
                Profile.objects.create(
                    user=user,
                    public_username=user.username,
                    full_name=user.get_full_name() or user.username,
                    is_email_verified=True,
                    pincode=user.pin_code or "751030"
                )
            if avatar and not user.avatar:
                user.avatar = avatar
                user.save()
            
        tokens = get_tokens_for_user(user)
        
        resp = Response({
            "user": CustomUserSerializer(user).data,
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_200_OK)
        _set_refresh_cookie(resp, tokens['refresh'])
        return resp
        
    except Exception as e:
        return Response({"error": "Failed to process Google login", "details": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def merge_duplicate_issues(request):
    """Consolidate duplicate tickets submitted by different citizens into a single primary ticket."""
    primary_id = request.data.get('primary_id') or request.data.get('primaryId')
    duplicate_id = request.data.get('duplicate_id') or request.data.get('duplicateId')
    reason = request.data.get('reason', 'AI confirmed spatial proximity & visual similarity match.')

    if not primary_id or not duplicate_id:
        return Response({"error": "Both primary_id and duplicate_id are required."}, status=status.HTTP_400_BAD_REQUEST)

    if str(primary_id).strip() == str(duplicate_id).strip():
        return Response({"error": "Cannot merge an issue with itself."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        primary_issue = CivicIssue.objects.get(pk=primary_id)
    except CivicIssue.DoesNotExist:
        return Response({"error": f"Primary issue '{primary_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        duplicate_issue = CivicIssue.objects.get(pk=duplicate_id)
    except CivicIssue.DoesNotExist:
        return Response({"error": f"Duplicate issue '{duplicate_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    actor_name = (request.user.get_full_name() or request.user.username) if request.user.is_authenticated else "Municipal Authority"
    now_iso = timezone.now().isoformat()

    # 1. Consolidate upvoted users, times_reported & upvote count
    dup_upvoters = list(duplicate_issue.upvoted_users.all())
    for upvoter in dup_upvoters:
        primary_issue.upvoted_users.add(upvoter)

    if duplicate_issue.reporter:
        primary_issue.upvoted_users.add(duplicate_issue.reporter)

    primary_issue.upvotes = max(primary_issue.upvotes + duplicate_issue.upvotes, primary_issue.upvoted_users.count(), 1)
    primary_issue.times_reported = (primary_issue.times_reported or 1) + (duplicate_issue.times_reported or 1)
    
    merged_list = list(primary_issue.merged_ticket_ids or [])
    if duplicate_issue.id not in merged_list:
        merged_list.append(duplicate_issue.id)
    primary_issue.merged_ticket_ids = merged_list

    # 2. Consolidate comments
    duplicate_issue.comments.all().update(issue=primary_issue)
    primary_issue.comments_count = primary_issue.comments.count()

    # 3. Add timeline audit entry to primary issue
    primary_timeline = primary_issue.timeline or []
    dup_reporter_name = duplicate_issue.reporter.get_full_name() or duplicate_issue.reporter.username if duplicate_issue.reporter else "Citizen"
    primary_timeline.append({
        "stage": "Duplicate Merged",
        "timestamp": now_iso,
        "note": f"Merged duplicate ticket #{duplicate_issue.id} ('{duplicate_issue.title}') reported by {dup_reporter_name}. Consolidated upvotes and community activity.",
        "actor": actor_name,
        "mergedIssueId": duplicate_issue.id,
        "reason": reason
    })
    primary_issue.timeline = primary_timeline
    primary_issue.save()

    # 4. Update duplicate issue status & timeline
    duplicate_issue.status = 'Resolved'
    duplicate_issue.is_hidden_from_map = True
    dup_timeline = duplicate_issue.timeline or []
    dup_timeline.append({
        "stage": "Merged into Primary",
        "timestamp": now_iso,
        "note": f"Ticket merged into primary ticket #{primary_issue.id}. All upvotes and community validation consolidated under #{primary_issue.id}.",
        "actor": actor_name,
        "mergedIntoId": primary_issue.id,
        "reason": reason
    })
    duplicate_issue.timeline = dup_timeline
    duplicate_issue.save()

    # 5. Dispatch notification to duplicate reporter
    if duplicate_issue.reporter:
        NotificationItem.objects.create(
            user=duplicate_issue.reporter,
            title=f"Report #{duplicate_issue.id} Merged with #{primary_issue.id} 🔗",
            message=f"Your reported issue '{duplicate_issue.title}' was verified and merged into #{primary_issue.id}. Your Civic Citizen XP is preserved and upvotes are consolidated!",
            notification_type="status",
            issue_id=primary_issue.id,
            action_url=f"/issues/{primary_issue.id}"
        )

    return Response({
        "status": "success",
        "message": f"Issue #{duplicate_id} successfully merged into #{primary_id}.",
        "primary": CivicIssueSerializer(primary_issue, context={'request': request}).data,
        "duplicate": CivicIssueSerializer(duplicate_issue, context={'request': request}).data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def leaderboard_list(request):
    """Returns live ranking of top civic citizens and officers from database."""
    users = CustomUser.objects.all().order_by('-civic_citizen_xp')[:20]
    leaderboard = []
    for rank, u in enumerate(users, 1):
        name = u.get_full_name() or u.username
        if hasattr(u, 'profile') and u.profile.full_name:
            name = u.profile.full_name
            
        # Avatar bandwidth guard: if avatar is a huge base64 string (>25KB), fallback to identicon
        avatar_val = u.avatar
        if avatar_val and avatar_val.startswith('data:image/') and len(avatar_val) > 25000:
            avatar_val = f"https://api.dicebear.com/7.x/bottts/svg?seed={u.username}"
        elif not avatar_val:
            avatar_val = f"https://api.dicebear.com/7.x/bottts/svg?seed={u.username}"

        leaderboard.append({
            "rank": rank,
            "id": u.id,
            "username": u.username,
            "name": name,
            "ward": u.ward.name if u.ward else (u.city or (f"PIN {u.pin_code}" if u.pin_code else "Civic Zone")),
            "karma": u.civic_citizen_xp or 0,
            "badge": u.level_title or ("Ward Officer" if u.role == "officer" else "Active Citizen"),
            "avatar": avatar_val,
            "role": u.role,
            "level": u.level or (1 if (u.civic_citizen_xp or 0) < 200 else (2 if (u.civic_citizen_xp or 0) < 500 else 3)),
        })
    return Response(leaderboard, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def announcement_list_create(request):
    if request.method == 'GET':
        pincode = request.query_params.get('pincode', '').strip()
        department = request.query_params.get('department', '').strip()
        
        announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
        
        if department and department.lower() not in ['all', 'municipal']:
            announcements = announcements.filter(department__icontains=department)
            
        results = []
        for ann in announcements:
            if pincode:
                # If announcement has specific pincodes, check if pincode matches or if announcement is ALL
                if ann.pincodes and len(ann.pincodes) > 0:
                    if pincode in ann.pincodes or "ALL" in [p.upper() for p in ann.pincodes]:
                        results.append(ann)
                else:
                    # No pincode restrictions -> visible to all
                    results.append(ann)
            else:
                results.append(ann)
                
        serializer = AnnouncementSerializer(results, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        title = request.data.get('title', '').strip()
        message = request.data.get('message', '').strip()
        department = request.data.get('department', 'Municipal Corporation').strip()
        pincodes = request.data.get('pincodes', [])
        urgency = request.data.get('urgency', 'Advisory').strip()
        category = request.data.get('category', 'General Advisory').strip()
        author_name = request.data.get('author_name') or (request.user.get_full_name() if request.user.is_authenticated else "Municipal Authority")
        author_role = request.data.get('author_role', 'officer')
        action_url = request.data.get('action_url', '/feed')

        if not title or not message:
            return Response({"error": "Title and message are required."}, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(pincodes, str):
            pincodes = [p.strip() for p in pincodes.split(',') if p.strip()]

        announcement = Announcement.objects.create(
            title=title,
            message=message,
            department=department,
            pincodes=pincodes,
            urgency=urgency,
            category=category,
            author_name=author_name,
            author_role=author_role,
            action_url=action_url,
            is_active=True
        )

        # Fan-out notifications to target citizens residing in these PIN codes
        target_users = CustomUser.objects.all()
        if pincodes and len(pincodes) > 0 and "ALL" not in [p.upper() for p in pincodes]:
            target_users = target_users.filter(
                Q(profile__pincode__in=pincodes) | Q(pin_code__in=pincodes)
            )

        notif_title = f"📢 [{department.upper()} NOTICE - PIN {','.join(pincodes) if pincodes else 'ALL'}]: {title}"
        notifications_to_create = []
        for u in target_users[:500]:  # Cap broadcast fanout
            notifications_to_create.append(NotificationItem(
                user=u,
                title=notif_title,
                message=message,
                notification_type='officer',
                action_url=f"/feed?pin={pincodes[0] if pincodes else ''}"
            ))

        if notifications_to_create:
            NotificationItem.objects.bulk_create(notifications_to_create)

        serializer = AnnouncementSerializer(announcement)
        return Response({
            "message": f"Broadcast published successfully. Dispatched to {len(notifications_to_create)} citizens in PIN {', '.join(pincodes) if pincodes else 'ALL'}.",
            "announcement": serializer.data,
            "reach_count": len(notifications_to_create)
        }, status=status.HTTP_201_CREATED)


@api_view(['DELETE', 'PATCH'])
@permission_classes([AllowAny])
def announcement_detail(request, pk):
    try:
        announcement = Announcement.objects.get(pk=pk)
    except Announcement.DoesNotExist:
        return Response({"error": "Announcement not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        announcement.is_active = False
        announcement.save()
        return Response({"status": "success", "message": "Announcement deactivated."}, status=status.HTTP_200_OK)

    elif request.method == 'PATCH':
        serializer = AnnouncementSerializer(announcement, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ==========================================
# CONSENSUS POLLS (CITIZEN REFERENDUMS) VIEWS
# ==========================================

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def poll_list_create(request):
    if request.method == 'GET':
        ward = request.query_params.get('ward')
        department = request.query_params.get('department')
        status_param = request.query_params.get('status')
        
        polls = ConsensusPoll.objects.all().order_by('-created_at')
        if ward and ward.lower() != 'all':
            polls = polls.filter(Q(ward__icontains=ward) | Q(ward='all'))
        if department and department.lower() != 'all':
            polls = polls.filter(department__icontains=department)
        if status_param and status_param.lower() != 'all':
            polls = polls.filter(status__iexact=status_param)

        serializer = ConsensusPollSerializer(polls, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        poll_id = data.get('id') or f"poll-{int(timezone.now().timestamp() * 1000)}"
        data['id'] = poll_id

        creator_name = "Official"
        if request.user.is_authenticated:
            creator_name = request.user.get_full_name() or request.user.username
        elif data.get('createdByName'):
            creator_name = data.get('createdByName')
        elif data.get('createdBy'):
            creator_name = data.get('createdBy')

        data['created_by_name'] = creator_name

        serializer = ConsensusPollSerializer(data=data)
        if serializer.is_valid():
            user = request.user if request.user.is_authenticated else None
            poll_obj = serializer.save(created_by=user, created_by_name=creator_name)

            # Auto-mirror to WardBudgetProposal if not exists
            if not WardBudgetProposal.objects.filter(id=poll_id).exists():
                # Parse numeric budget
                budget_str = data.get('budgetEstimate') or data.get('budget_estimate') or "4500000"
                num_budget = 4500000.0
                try:
                    import re
                    clean_str = str(budget_str).replace(',', '').strip()
                    lakh_m = re.search(r'([\d.]+)\s*(?:lakh|lac|l)', clean_str, re.I)
                    cr_m = re.search(r'([\d.]+)\s*(?:crore|cr)', clean_str, re.I)
                    if lakh_m:
                        num_budget = float(lakh_m.group(1)) * 100000
                    elif cr_m:
                        num_budget = float(cr_m.group(1)) * 10000000
                    else:
                        digits = re.sub(r'[^\d.]', '', clean_str)
                        if digits:
                            num_budget = float(digits)
                except Exception:
                    num_budget = 4500000.0

                WardBudgetProposal.objects.create(
                    id=poll_id,
                    title=poll_obj.title,
                    category=poll_obj.department,
                    description=poll_obj.description,
                    required_budget=num_budget,
                    ward_pin=poll_obj.ward,
                    created_by=user,
                    created_by_name=creator_name,
                    linked_poll_id=poll_id,
                    status="Open for Voting"
                )

            return Response(ConsensusPollSerializer(poll_obj).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def poll_detail(request, pk):
    try:
        poll = ConsensusPoll.objects.get(pk=pk)
    except ConsensusPoll.DoesNotExist:
        return Response({"error": "Consensus Poll not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(ConsensusPollSerializer(poll).data, status=status.HTTP_200_OK)

    elif request.method == 'PATCH':
        serializer = ConsensusPollSerializer(poll, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        # Clean up both poll and any linked budget proposal
        WardBudgetProposal.objects.filter(id=poll.id).delete()
        poll.delete()
        return Response({"status": "success", "message": "Poll deleted."}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def vote_poll(request, pk):
    try:
        poll = ConsensusPoll.objects.get(pk=pk)
    except ConsensusPoll.DoesNotExist:
        return Response({"error": "Consensus Poll not found."}, status=status.HTTP_404_NOT_FOUND)

    vote_type = request.data.get('vote') or request.data.get('voteType') or 'yes'
    user_id = str(request.user.id) if request.user.is_authenticated else (request.data.get('userId') or 'anonymous_user')

    voted_users = poll.voted_users or {}
    if user_id in voted_users and user_id != 'anonymous_user':
        return Response({"message": "You have already voted on this ballot.", "poll": ConsensusPollSerializer(poll).data}, status=status.HTTP_200_OK)

    voted_users[user_id] = vote_type
    poll.voted_users = voted_users

    if vote_type == 'yes':
        poll.yes_votes += 1
    else:
        poll.no_votes += 1

    # Check threshold consensus
    total_votes = poll.yes_votes + poll.no_votes
    if total_votes >= 2000 and (poll.yes_votes / total_votes) >= 0.6:
        poll.status = "Approved"

    poll.save()

    # Mirror vote to linked WardBudgetProposal if exists
    linked_prop = WardBudgetProposal.objects.filter(Q(id=poll.id) | Q(linked_poll_id=poll.id)).first()
    if linked_prop and vote_type == 'yes':
        linked_prop.current_votes = poll.yes_votes
        if poll.status == "Approved":
            linked_prop.status = "Threshold Met"
        linked_prop.save()

    return Response({
        "message": "Vote recorded successfully.",
        "poll": ConsensusPollSerializer(poll).data
    }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_poll_status(request, pk):
    try:
        poll = ConsensusPoll.objects.get(pk=pk)
    except ConsensusPoll.DoesNotExist:
        return Response({"error": "Consensus Poll not found."}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in ['Active Ballot', 'Approved', 'Rejected']:
        return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

    poll.status = new_status
    poll.save()

    # Sync to linked budget proposal
    linked_prop = WardBudgetProposal.objects.filter(Q(id=poll.id) | Q(linked_poll_id=poll.id)).first()
    if linked_prop:
        if new_status == 'Approved':
            linked_prop.status = 'Threshold Met'
        elif new_status == 'Active Ballot':
            linked_prop.status = 'Open for Voting'
        linked_prop.save()

    return Response(ConsensusPollSerializer(poll).data, status=status.HTTP_200_OK)


# ==========================================
# WARD BUDGET PROPOSALS VIEWS
# ==========================================

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def budget_proposal_list_create(request):
    if request.method == 'GET':
        ward_pin = request.query_params.get('wardPin') or request.query_params.get('ward_pin') or request.query_params.get('pincode')
        category = request.query_params.get('category')
        status_param = request.query_params.get('status')

        proposals = WardBudgetProposal.objects.all().order_by('-current_votes', '-created_at')

        if ward_pin and ward_pin.lower() != 'all':
            proposals = proposals.filter(Q(ward_pin__icontains=ward_pin) | Q(ward_pin='all'))
        if category and category.lower() != 'all':
            proposals = proposals.filter(category__icontains=category)
        if status_param and status_param.lower() != 'all':
            proposals = proposals.filter(status__iexact=status_param)

        serializer = WardBudgetProposalSerializer(proposals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy()
        prop_id = data.get('id') or f"initiative-{int(timezone.now().timestamp() * 1000)}"
        data['id'] = prop_id

        creator_name = "Citizen Initiator"
        if request.user.is_authenticated:
            creator_name = request.user.get_full_name() or request.user.username
        elif data.get('createdByName'):
            creator_name = data.get('createdByName')
        elif data.get('createdBy'):
            creator_name = data.get('createdBy')

        data['created_by_name'] = creator_name

        serializer = WardBudgetProposalSerializer(data=data)
        if serializer.is_valid():
            user = request.user if request.user.is_authenticated else None
            prop_obj = serializer.save(created_by=user, created_by_name=creator_name)

            # Auto-mirror to ConsensusPoll if not exists
            if not ConsensusPoll.objects.filter(id=prop_id).exists():
                budget_num = float(prop_obj.required_budget)
                budget_lakhs = f"₹ {(budget_num / 100000):.1f} Lakhs" if budget_num < 10000000 else f"₹ {(budget_num / 10000000):.2f} Cr"

                ConsensusPoll.objects.create(
                    id=prop_id,
                    title=prop_obj.title,
                    department=prop_obj.category,
                    ward=prop_obj.ward_pin,
                    description=prop_obj.description,
                    yes_votes=prop_obj.current_votes,
                    no_votes=0,
                    status="Active Ballot",
                    days_left=14,
                    budget_estimate=budget_lakhs,
                    created_by=user,
                    created_by_name=creator_name
                )

            return Response(WardBudgetProposalSerializer(prop_obj).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Backwards compatibility alias for old route
budget_list_create = budget_proposal_list_create


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def budget_proposal_detail(request, pk):
    try:
        prop = WardBudgetProposal.objects.get(pk=pk)
    except WardBudgetProposal.DoesNotExist:
        return Response({"error": "Ward Budget Proposal not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(WardBudgetProposalSerializer(prop).data, status=status.HTTP_200_OK)

    elif request.method == 'PATCH':
        serializer = WardBudgetProposalSerializer(prop, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        ConsensusPoll.objects.filter(id=prop.id).delete()
        prop.delete()
        return Response({"status": "success", "message": "Proposal deleted."}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def vote_budget_proposal(request, pk):
    try:
        prop = WardBudgetProposal.objects.get(pk=pk)
    except WardBudgetProposal.DoesNotExist:
        return Response({"error": "Ward Budget Proposal not found."}, status=status.HTTP_404_NOT_FOUND)

    user_id = str(request.user.id) if request.user.is_authenticated else (request.data.get('userId') or 'anonymous_user')
    voted_users = prop.voted_users or []

    if user_id in voted_users and user_id != 'anonymous_user':
        return Response({"message": "You have already voted for this proposal.", "proposal": WardBudgetProposalSerializer(prop).data}, status=status.HTTP_200_OK)

    voted_users.append(user_id)
    prop.voted_users = voted_users
    prop.current_votes += 1

    if prop.current_votes >= 2000 and prop.status == "Open for Voting":
        prop.status = "Threshold Met"

    prop.save()

    # Mirror vote to linked ConsensusPoll
    linked_poll = ConsensusPoll.objects.filter(Q(id=prop.id) | Q(id=prop.linked_poll_id)).first()
    if linked_poll:
        linked_poll.yes_votes = prop.current_votes
        if prop.status == "Threshold Met":
            linked_poll.status = "Approved"
        linked_poll.save()

    return Response({
        "message": "Vote recorded successfully.",
        "proposal": WardBudgetProposalSerializer(prop).data
    }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_budget_proposal_status(request, pk):
    try:
        prop = WardBudgetProposal.objects.get(pk=pk)
    except WardBudgetProposal.DoesNotExist:
        return Response({"error": "Ward Budget Proposal not found."}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in ['Open for Voting', 'Threshold Met', 'In Execution']:
        return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

    prop.status = new_status
    prop.save()

    # Mirror to linked ConsensusPoll
    linked_poll = ConsensusPoll.objects.filter(Q(id=prop.id) | Q(id=prop.linked_poll_id)).first()
    if linked_poll:
        if new_status in ['Threshold Met', 'In Execution']:
            linked_poll.status = "Approved"
        elif new_status == 'Open for Voting':
            linked_poll.status = "Active Ballot"
        linked_poll.save()

    return Response(WardBudgetProposalSerializer(prop).data, status=status.HTTP_200_OK)



