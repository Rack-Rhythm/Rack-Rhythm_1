from rest_framework.decorators import api_view, permission_classes,parser_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
import random
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from rest_framework.parsers import MultiPartParser, FormParser
from .gemini_vision import analyze_civic_image

from .models import CustomUser, OTPRecord, CivicIssue, Comment, NotificationItem
from .serializers import (
    OTPRequestSerializer, OTPVerifySerializer, CustomUserSerializer,
    CivicIssueSerializer, CommentSerializer, NotificationSerializer
)
import logging
logger = logging.getLogger(__name__)
# Helper to set refresh cookie on responses
def _set_refresh_cookie(resp: Response, refresh_token: str):
    # Secure should be True in production (requires HTTPS). Use settings.DEBUG to toggle locally.
    secure_flag = not settings.DEBUG
    # 14 days for example; align with your JWT settings
    max_age = 14 * 24 * 3600
    resp.set_cookie(
        key='janseva_refresh',
        value=refresh_token,
        httponly=True,
        secure=secure_flag,
        samesite='Lax',
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
def hello_api(request):
    return Response({"message": "Hello from Django!", "status": "success"})

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}

@api_view(['POST'])
@permission_classes([AllowAny])
def email_request_otp(request):
    serializer = OTPRequestSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        phone_number = serializer.validated_data['phone_number']
        
        otp_code = str(random.randint(100000, 999999))
        OTPRecord.objects.create(email=email, otp_code=otp_code)
        
        try:
            send_mail(
                'Your Login OTP',
                f'Your verification code is {otp_code}. It expires in 10 minutes.',
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            return Response({"message": "OTP sent to email"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": "Failed to send email", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def email_verify_otp(request):
    serializer = OTPVerifySerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        phone_number = serializer.validated_data['phone_number']
        otp_code = serializer.validated_data['otp_code']
        time_threshold = timezone.now() - timedelta(minutes=10)
        
        otp_record = OTPRecord.objects.filter(
            email=email, otp_code=otp_code, is_verified=False, created_at__gte=time_threshold
        ).last()
        
        if otp_record:
            otp_record.is_verified = True
            otp_record.save()
            
            user, created = CustomUser.objects.get_or_create(username=email, defaults={'email': email, 'phone_number': phone_number})
            
            if not created and user.phone_number != phone_number:
                user.phone_number = phone_number
                user.save()
                
            tokens = get_tokens_for_user(user)
            # Set refresh token as HttpOnly cookie, return access in body
            resp = Response({'access': tokens['access']}, status=status.HTTP_200_OK)
            _set_refresh_cookie(resp, tokens['refresh'])
            return resp
        else:
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    full_name = request.data.get('fullName', '')
    role = request.data.get('role', 'citizen')
    ward = request.data.get('ward', 'Shanti Nagar')
    ward_number = request.data.get('wardNumber', 42)
    phone_number = request.data.get('phone_number')

    if not username or not password:
        return Response({"error": "Username and password are required."}, status=status.HTTP_400_BAD_REQUEST)

    if CustomUser.objects.filter(username=username).exists():
        return Response({"error": "Username already exists."}, status=status.HTTP_400_BAD_REQUEST)

    first_name = ''
    last_name = ''
    if full_name:
        parts = full_name.split(' ', 1)
        first_name = parts[0]
        if len(parts) > 1:
            last_name = parts[1]

    user = CustomUser.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=role,
        ward=ward,
        ward_number=ward_number,
        phone_number=phone_number
    )
    user.stats = {
        "issuesReported": 0,
        "issuesResolved": 0,
        "upvotesGiven": 0,
        "verificationVotes": 0,
        "civicImpactScore": 10
    }
    user.badges = [
        {
            "id": "badge-welcome",
            "name": "Civic Pioneer",
            "icon": "🌟",
            "description": "Joined JanSeva community",
            "unlockedAt": timezone.now().isoformat()
        }
    ]
    user.save()

    tokens = get_tokens_for_user(user)
    # Set refresh token cookie and return access + user
    resp = Response({
        "user": CustomUserSerializer(user).data,
        "access": tokens['access']
    }, status=status.HTTP_201_CREATED)
    _set_refresh_cookie(resp, tokens['refresh'])
    return resp

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    serializer = CustomUserSerializer(request.user)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_refresh(request):
    """Refresh access token using the HttpOnly janseva_refresh cookie.

    Returns: { "access": "<new_access>" }
    """
    refresh_token = request.COOKIES.get('janseva_refresh')
    if not refresh_token:
        return Response({"detail": "No refresh token cookie present."}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        token = RefreshToken(refresh_token)
        new_access = str(token.access_token)
        # Optionally: rotate refresh token here by issuing a new RefreshToken.for_user(user)
        return Response({"access": new_access}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_401_UNAUTHORIZED)


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

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def issue_list_create(request):
    if request.method == 'GET':
        category = request.query_params.get('category')
        status_param = request.query_params.get('status')
        issues = CivicIssue.objects.all().order_by('-created_at')
        if category and category != 'all':
            issues = issues.filter(category=category)
        if status_param and status_param != 'all':
            issues = issues.filter(status=status_param)
            
        serializer = CivicIssueSerializer(issues, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    elif request.method == 'POST':
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
            
        data = request.data.copy()
        
        # Generate custom id like JS-101
        last_issue = CivicIssue.objects.all().order_by('-created_at').first()
        if last_issue and last_issue.id.startswith('JS-'):
            try:
                num = int(last_issue.id.split('-')[1])
                new_id = f"JS-{num + 1}"
            except ValueError:
                new_id = f"JS-{random.randint(100, 999)}"
        else:
            new_id = f"JS-101"
            
        data['id'] = new_id
        
        serializer = CivicIssueSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            issue = serializer.save(reporter=request.user)
            
            # Give user Karma XP
            request.user.karma_xp += 50
            stats = request.user.stats or {}
            stats["issuesReported"] = stats.get("issuesReported", 0) + 1
            request.user.stats = stats
            request.user.save()
            
            # Send Notification
            NotificationItem.objects.create(
                user=request.user,
                title=f"Report #{issue.id} Submitted Successfully 🎉",
                message=f"Your issue \"{issue.title}\" has been AI verified and queued for municipal action.",
                notification_type="status",
                issue_id=issue.id,
                action_url=f"/issues/{issue.id}"
            )
            
            return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([AllowAny])
def issue_detail(request, pk):
    try:
        issue = CivicIssue.objects.get(pk=pk)
    except CivicIssue.DoesNotExist:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    serializer = CivicIssueSerializer(issue, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upvote_issue(request, pk):
    try:
        issue = CivicIssue.objects.get(pk=pk)
    except CivicIssue.DoesNotExist:
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
        
        request.user.karma_xp += 5
        stats = request.user.stats or {}
        stats["upvotesGiven"] = stats.get("upvotesGiven", 0) + 1
        request.user.stats = stats
        request.user.save()
        
        return Response({"status": "upvoted", "upvotes": issue.upvotes}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_issue(request, pk):
    try:
        issue = CivicIssue.objects.get(pk=pk)
    except CivicIssue.DoesNotExist:
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
    issue.save()
    
    request.user.karma_xp += 15
    stats = request.user.stats or {}
    stats["verificationVotes"] = stats.get("verificationVotes", 0) + 1
    request.user.stats = stats
    request.user.save()
    
    return Response({"status": "voted", "votes": {
        "yes": votes["yes"],
        "no": votes["no"],
        "userVoted": vote
    }}, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_issue_status(request, pk):
    if request.user.role not in ['officer', 'corporator']:
        return Response({"error": "Only officers or corporators can update issue status."}, status=status.HTTP_403_FORBIDDEN)
        
    try:
        issue = CivicIssue.objects.get(pk=pk)
    except CivicIssue.DoesNotExist:
        return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        
    new_status = request.data.get('status')
    note = request.data.get('note', '')
    
    if new_status not in ['Reported', 'AI Verified', 'Assigned', 'In Progress', 'Resolved']:
        return Response({"error": "Invalid status value."}, status=status.HTTP_400_BAD_REQUEST)
        
    issue.status = new_status
    timeline = issue.timeline or []
    timeline.append({
        "stage": new_status,
        "timestamp": timezone.now().isoformat(),
        "note": note or f"Status updated to {new_status} by {request.user.get_full_name() or request.user.username}.",
        "actor": request.user.get_full_name() or request.user.username
    })
    issue.timeline = timeline
    
    if new_status == 'Resolved':
        images = issue.images or {}
        if 'resolved' not in images:
            images['resolved'] = "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800&auto=format&fit=crop&q=80"
            issue.images = images
            
    issue.save()
    
    NotificationItem.objects.create(
        user=issue.reporter,
        title=f"Ticket #{issue.id} Status: {new_status}",
        message=note or f"Officer {request.user.username} transitioned ticket to {new_status}.",
        notification_type="officer",
        issue_id=issue.id,
        action_url=f"/issues/{issue.id}"
    )
    
    return Response(CivicIssueSerializer(issue, context={'request': request}).data, status=status.HTTP_200_OK)

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def comment_list_create(request, pk):
    try:
        issue = CivicIssue.objects.get(pk=pk)
    except CivicIssue.DoesNotExist:
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
            return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
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
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def analyze_issue_image(request):
    image_file = request.FILES.get('image')

    if not image_file:
        return Response(
            {"error": "Image is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    allowed_types = {
        'image/jpeg',
        'image/png',
        'image/webp',
    }

    if image_file.content_type not in allowed_types:
        return Response(
            {"error": "Only JPEG, PNG, and WebP images are supported."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        analysis = analyze_civic_image(image_file)

        return Response(
            {
                "analysis": analysis
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("Image analysis failed")

        return Response(
            {
                "error": "Image analysis failed.",
                "detail": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )