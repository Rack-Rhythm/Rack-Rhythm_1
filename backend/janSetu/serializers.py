from rest_framework import serializers
from .models import CustomUser, CivicIssue, Comment, NotificationItem, State, City, Ward, Profile, OTPRecord, Announcement, BudgetAllocation, ConsensusPoll, WardBudgetProposal

class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ['id', 'name']

class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ['id', 'name', 'state']

class WardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ward
        fields = ['id', 'name', 'ward_number', 'city', 'pincode']

class ProfileSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source='state.name', read_only=True)
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Profile
        fields = ['public_username', 'full_name', 'state', 'state_name', 'city', 'city_name', 'pincode', 'is_email_verified', 'number']

class CustomUserSerializer(serializers.ModelSerializer):
    stats = serializers.JSONField(read_only=True)
    badges = serializers.JSONField(read_only=True)
    profile = ProfileSerializer(read_only=True)
    ward_details = WardSerializer(source='ward', read_only=True)
    civicCitizenXP = serializers.IntegerField(source='civic_citizen_xp', read_only=True)
    levelTitle = serializers.CharField(source='level_title', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'phone_number', 'role', 'avatar', 
            'ward', 'ward_details', 'civic_citizen_xp', 'civicCitizenXP', 'level', 'level_title', 'levelTitle',
            'verified_citizen', 'aadhaar_linked', 'stats', 'badges', 'profile',
            'gender', 'pin_code', 'state', 'city'
        ]

class OTPRequestSerializer(serializers.Serializer):
    target = serializers.CharField(max_length=255)
    channel = serializers.ChoiceField(choices=['email', 'sms'])

class OTPVerifySerializer(serializers.Serializer):
    target = serializers.CharField(max_length=255)
    otp_code = serializers.CharField(max_length=6)

class RegisterSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    public_username = serializers.CharField(max_length=150, required=False)
    full_name = serializers.CharField(max_length=255, required=False)
    gender = serializers.CharField(max_length=20, required=False, allow_blank=True)
    role = serializers.CharField(max_length=15, required=False, default='citizen')
    department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True)
    identifier = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

class ReporterSerializer(serializers.ModelSerializer):
    isVerified = serializers.BooleanField(source='verified_citizen')
    karma = serializers.IntegerField(source='civic_citizen_xp')
    id = serializers.IntegerField()

    class Meta:
        model = CustomUser
        fields = ['id', 'isVerified', 'karma']

class OfficerSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['name', 'role', 'avatar', 'phone']

    def get_name(self, obj):
        if not obj:
            return "Lead Officer"
        if hasattr(obj, 'profile') and obj.profile and obj.profile.full_name:
            return obj.profile.full_name
        full_name = obj.get_full_name() if hasattr(obj, 'get_full_name') else ""
        return full_name if full_name.strip() else (obj.username or "Lead Officer")

    def get_role(self, obj):
        if not obj:
            return "Lead Officer"
        return obj.level_title or ("Lead Officer" if getattr(obj, 'role', '') == 'officer' else "Municipal Authority")

    def get_phone(self, obj):
        if not obj:
            return ""
        return obj.phone_number or ""

    def get_avatar(self, obj):
        if not obj:
            return "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=400&auto=format&fit=crop&q=80"
        return obj.avatar or "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=400&auto=format&fit=crop&q=80"

class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_username = serializers.CharField(source='author.username', read_only=True)
    author_avatar = serializers.URLField(source='author.avatar', read_only=True)
    author_role = serializers.CharField(source='author.role', read_only=True)
    is_officer = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'issue', 'author', 'author_name', 'author_username', 'author_avatar', 'author_role', 'is_officer', 'text', 'created_at', 'timestamp']
        read_only_fields = ['author', 'issue', 'created_at', 'timestamp']

    def get_author_name(self, obj):
        if obj.author:
            if hasattr(obj.author, 'profile') and obj.author.profile.full_name:
                return obj.author.profile.full_name
            full_name = obj.author.get_full_name()
            return full_name if full_name.strip() else obj.author.username
        return "Citizen"

    def get_is_officer(self, obj):
        return bool(obj.author and obj.author.role in ['officer', 'corporator'])

class CivicIssueSerializer(serializers.ModelSerializer):
    reporter = ReporterSerializer(read_only=True)
    assignedOfficer = OfficerSerializer(source='assigned_officer', read_only=True)
    isUpvoted = serializers.SerializerMethodField()
    commentsCount = serializers.IntegerField(source='comments_count', read_only=True)
    verificationVotes = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    aiAnalysis = serializers.JSONField(source='ai_analysis', required=False, allow_null=True)
    assignedDepartment = serializers.CharField(source='assigned_department', required=False, allow_blank=True, allow_null=True)
    timesReported = serializers.IntegerField(source='times_reported', required=False, default=1)
    mergedTicketIds = serializers.JSONField(source='merged_ticket_ids', required=False, default=list)
    pincode = serializers.CharField(source='pin_code', read_only=True)
    isInnovation = serializers.SerializerMethodField()
    innovationTheme = serializers.SerializerMethodField()
    communityBenefit = serializers.SerializerMethodField()
    estimatedBudget = serializers.SerializerMethodField()
    officerVerdict = serializers.SerializerMethodField()
    officerFeedback = serializers.SerializerMethodField()

    class Meta:
        model = CivicIssue
        fields = [
            'id', 'title', 'description', 'category', 'status', 'urgency',
            'location', 'pin_code', 'pincode', 'reporter', 'images', 'aiAnalysis', 'assignedDepartment',
            'assignedOfficer', 'timeline', 'upvotes', 'isUpvoted', 'commentsCount',
            'verificationVotes', 'is_hidden_from_map', 'times_reported', 'timesReported',
            'merged_ticket_ids', 'mergedTicketIds', 'createdAt', 'updatedAt',
            'isInnovation', 'innovationTheme', 'communityBenefit', 'estimatedBudget', 'officerVerdict', 'officerFeedback'
        ]

    def get_isInnovation(self, obj):
        ai = obj.ai_analysis or {}
        return obj.category == 'Innovation' or bool(ai.get('is_innovation')) or bool(ai.get('isInnovation'))

    def get_innovationTheme(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('innovation_theme') or ai.get('innovationTheme') or (obj.category if obj.category == 'Innovation' else None)

    def get_communityBenefit(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('community_benefit') or ai.get('communityBenefit') or ''

    def get_estimatedBudget(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('estimated_budget') or ai.get('estimatedBudget') or ''

    def get_officerVerdict(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('officer_verdict') or ai.get('officerVerdict') or (obj.status if obj.status in ['Under Review', 'Feasibility Approved', 'Pilot Scheduled', 'Budget Allocated'] else None)

    def get_officerFeedback(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('officer_feedback') or ai.get('officerFeedback') or ''

    def get_isUpvoted(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user_upvoted_ids = self.context.get('user_upvoted_ids')
        if user_upvoted_ids is not None:
            return obj.id in user_upvoted_ids
        if hasattr(obj, '_prefetched_objects_cache') and 'upvoted_users' in obj._prefetched_objects_cache:
            return any(user.id == request.user.id for user in obj.upvoted_users.all())
        return obj.upvoted_users.filter(id=request.user.id).exists()

    def get_verificationVotes(self, obj):
        votes = obj.verification_votes or {"yes": 0, "no": 0, "users": {}}
        yes_count = votes.get("yes", 0)
        no_count = votes.get("no", 0)
        user_voted = None
        
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            users_dict = votes.get("users", {})
            user_voted = users_dict.get(str(request.user.id))
            
        return {
            "yes": yes_count,
            "no": no_count,
            "userVoted": user_voted
        }

class CivicIssueFeedSerializer(serializers.ModelSerializer):
    reporter = ReporterSerializer(read_only=True)
    assignedOfficer = OfficerSerializer(source='assigned_officer', read_only=True)
    isUpvoted = serializers.SerializerMethodField()
    commentsCount = serializers.IntegerField(source='comments_count', read_only=True)
    verificationVotes = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)
    assignedDepartment = serializers.CharField(source='assigned_department', required=False, allow_blank=True, allow_null=True)
    timesReported = serializers.IntegerField(source='times_reported', required=False, default=1)
    mergedTicketIds = serializers.JSONField(source='merged_ticket_ids', required=False, default=list)
    pincode = serializers.CharField(source='pin_code', read_only=True)
    images = serializers.SerializerMethodField()
    aiAnalysis = serializers.SerializerMethodField()
    isInnovation = serializers.SerializerMethodField()
    innovationTheme = serializers.SerializerMethodField()
    communityBenefit = serializers.SerializerMethodField()
    estimatedBudget = serializers.SerializerMethodField()
    officerVerdict = serializers.SerializerMethodField()
    officerFeedback = serializers.SerializerMethodField()

    class Meta:
        model = CivicIssue
        fields = [
            'id', 'title', 'description', 'category', 'status', 'urgency',
            'location', 'pin_code', 'pincode', 'reporter', 'images', 'aiAnalysis',
            'assignedDepartment', 'assignedOfficer', 'timeline', 'upvotes', 'isUpvoted',
            'commentsCount', 'verificationVotes', 'times_reported', 'timesReported',
            'merged_ticket_ids', 'mergedTicketIds', 'createdAt', 'updatedAt',
            'isInnovation', 'innovationTheme', 'communityBenefit', 'estimatedBudget', 'officerVerdict', 'officerFeedback'
        ]

    def get_isInnovation(self, obj):
        ai = obj.ai_analysis or {}
        return obj.category == 'Innovation' or bool(ai.get('is_innovation')) or bool(ai.get('isInnovation'))

    def get_innovationTheme(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('innovation_theme') or ai.get('innovationTheme') or (obj.category if obj.category == 'Innovation' else None)

    def get_communityBenefit(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('community_benefit') or ai.get('communityBenefit') or ''

    def get_estimatedBudget(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('estimated_budget') or ai.get('estimatedBudget') or ''

    def get_officerVerdict(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('officer_verdict') or ai.get('officerVerdict') or (obj.status if obj.status in ['Under Review', 'Feasibility Approved', 'Pilot Scheduled', 'Budget Allocated'] else None)

    def get_officerFeedback(self, obj):
        ai = obj.ai_analysis or {}
        return ai.get('officer_feedback') or ai.get('officerFeedback') or ''

    def get_isUpvoted(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        user_upvoted_ids = self.context.get('user_upvoted_ids')
        if user_upvoted_ids is not None:
            return obj.id in user_upvoted_ids
        if hasattr(obj, '_prefetched_objects_cache') and 'upvoted_users' in obj._prefetched_objects_cache:
            return any(user.id == request.user.id for user in obj.upvoted_users.all())
        return obj.upvoted_users.filter(id=request.user.id).exists()

    def get_verificationVotes(self, obj):
        votes = obj.verification_votes or {"yes": 0, "no": 0, "users": {}}
        yes_count = votes.get("yes", 0)
        no_count = votes.get("no", 0)
        user_voted = None
        
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            users_dict = votes.get("users", {})
            user_voted = users_dict.get(str(request.user.id))
            
        return {
            "yes": yes_count,
            "no": no_count,
            "userVoted": user_voted
        }

    def get_images(self, obj):
        imgs = obj.images or {}
        if isinstance(imgs, dict):
            return {
                "reported": imgs.get('reported') or imgs.get('thumbnail') or "",
                "resolved": imgs.get('resolved') or imgs.get('resolved_thumbnail') or ""
            }
        return {"reported": "", "resolved": ""}

    def get_aiAnalysis(self, obj):
        ai = obj.ai_analysis or {}
        return {
            **ai,
            "detectedObject": ai.get("detectedObject") or ai.get("innovation_theme") or "Civic Defect",
            "confidence": ai.get("confidence", 90),
            "summary": ai.get("summary", "Civic issue reported.")
        }

class NotificationSerializer(serializers.ModelSerializer):
    issueId = serializers.CharField(source='issue_id', required=False, allow_null=True)
    actionUrl = serializers.CharField(source='action_url', required=False, allow_null=True)

    class Meta:
        model = NotificationItem
        fields = ['id', 'title', 'message', 'notification_type', 'timestamp', 'read', 'issueId', 'actionUrl']

class AnnouncementSerializer(serializers.ModelSerializer):
    authorName = serializers.CharField(source='author_name', required=False, allow_null=True)
    authorRole = serializers.CharField(source='author_role', required=False, default='officer')
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    expiresAt = serializers.DateTimeField(source='expires_at', required=False, allow_null=True)
    actionUrl = serializers.CharField(source='action_url', required=False, allow_null=True)
    isActive = serializers.BooleanField(source='is_active', default=True)

    class Meta:
        model = Announcement
        fields = [
            'id', 'title', 'message', 'department', 'pincodes', 'urgency',
            'category', 'authorName', 'authorRole', 'createdAt', 'expiresAt',
            'actionUrl', 'isActive'
        ]

class BudgetAllocationSerializer(serializers.ModelSerializer):
    allocatedAmount = serializers.DecimalField(source='allocated_amount', max_digits=12, decimal_places=2)
    spentAmount = serializers.DecimalField(source='spent_amount', max_digits=12, decimal_places=2)
    communityVotes = serializers.IntegerField(source='community_votes', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = BudgetAllocation
        fields = [
            'id', 'title', 'description', 'category', 'ward_name', 'pincode',
            'allocated_amount', 'allocatedAmount', 'spent_amount', 'spentAmount',
            'status', 'community_votes', 'communityVotes', 'created_at', 'createdAt',
            'updated_at', 'updatedAt'
        ]

class ConsensusPollSerializer(serializers.ModelSerializer):
    yesVotes = serializers.IntegerField(source='yes_votes', required=False, default=0)
    noVotes = serializers.IntegerField(source='no_votes', required=False, default=0)
    daysLeft = serializers.IntegerField(source='days_left', required=False, default=14)
    budgetEstimate = serializers.CharField(source='budget_estimate', required=False, default='₹ 45.0 Lakhs')
    createdByName = serializers.CharField(source='created_by_name', required=False, allow_null=True, allow_blank=True)
    votedUsers = serializers.JSONField(source='voted_users', required=False, default=dict)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = ConsensusPoll
        fields = [
            'id', 'title', 'department', 'ward', 'description',
            'yesVotes', 'noVotes', 'status', 'daysLeft',
            'budgetEstimate', 'createdByName', 'votedUsers',
            'createdAt', 'updatedAt'
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'status': {'required': False},
        }

    def to_internal_value(self, data):
        data_copy = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'yes_votes' in data_copy and 'yesVotes' not in data_copy:
            data_copy['yesVotes'] = data_copy['yes_votes']
        if 'no_votes' in data_copy and 'noVotes' not in data_copy:
            data_copy['noVotes'] = data_copy['no_votes']
        if 'days_left' in data_copy and 'daysLeft' not in data_copy:
            data_copy['daysLeft'] = data_copy['days_left']
        if 'budget_estimate' in data_copy and 'budgetEstimate' not in data_copy:
            data_copy['budgetEstimate'] = data_copy['budget_estimate']
        if 'createdBy' in data_copy and 'createdByName' not in data_copy:
            data_copy['createdByName'] = data_copy['createdBy']
        if 'created_by_name' in data_copy and 'createdByName' not in data_copy:
            data_copy['createdByName'] = data_copy['created_by_name']
        return super().to_internal_value(data_copy)


class WardBudgetProposalSerializer(serializers.ModelSerializer):
    requiredBudget = serializers.DecimalField(source='required_budget', max_digits=14, decimal_places=2, required=False)
    currentVotes = serializers.IntegerField(source='current_votes', required=False, default=0)
    wardPin = serializers.CharField(source='ward_pin', required=False, default='751024')
    createdBy = serializers.CharField(source='created_by_name', required=False, allow_null=True, allow_blank=True)
    createdByName = serializers.CharField(source='created_by_name', required=False, allow_null=True, allow_blank=True)
    votedUsers = serializers.JSONField(source='voted_users', required=False, default=list)
    linkedPollId = serializers.CharField(source='linked_poll_id', required=False, allow_null=True, allow_blank=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = WardBudgetProposal
        fields = [
            'id', 'title', 'category', 'description',
            'requiredBudget', 'currentVotes', 'status',
            'wardPin', 'createdBy', 'createdByName', 'votedUsers',
            'linkedPollId', 'createdAt', 'updatedAt'
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'status': {'required': False},
        }

    def to_internal_value(self, data):
        data_copy = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'required_budget' in data_copy and 'requiredBudget' not in data_copy:
            data_copy['requiredBudget'] = data_copy['required_budget']
        if 'current_votes' in data_copy and 'currentVotes' not in data_copy:
            data_copy['currentVotes'] = data_copy['current_votes']
        if 'ward_pin' in data_copy and 'wardPin' not in data_copy:
            data_copy['wardPin'] = data_copy['ward_pin']
        if 'pincode' in data_copy and 'wardPin' not in data_copy:
            data_copy['wardPin'] = data_copy['pincode']
        if 'createdBy' in data_copy and 'createdByName' not in data_copy:
            data_copy['createdByName'] = data_copy['createdBy']
        if 'created_by_name' in data_copy and 'createdByName' not in data_copy:
            data_copy['createdByName'] = data_copy['created_by_name']
        return super().to_internal_value(data_copy)


