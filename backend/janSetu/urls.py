from django.urls import path
from .views import (
    hello_api, email_request_otp, email_verify_otp, register_user, user_profile,
    issue_list_create, issue_detail, upvote_issue, verify_issue, update_issue_status,
    comment_list_create, notification_list, mark_notification_read, mark_all_notifications_read,
    CookieTokenObtainPairView, cookie_refresh, logout_view,analyze_issue_image
)
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("hello/", hello_api, name="hello_api"),
    
    # Authentication routes
    path("auth/login/", CookieTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/register/", register_user, name="register_user"),
    path("auth/profile/", user_profile, name="user_profile"),
    path("auth/login/request-otp/", email_request_otp, name="email_request_otp"),
    path("auth/login/verify-otp/", email_verify_otp, name="email_verify_otp"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/refresh/cookie/", cookie_refresh, name="token_refresh_cookie"),
    path("auth/logout/", logout_view, name="auth_logout"),
    #Posting route
    path('issues/analyze-image/', analyze_issue_image, name='analyze_issue_image'),
        
    
    # Issues routes
    path("issues/", issue_list_create, name="issue_list_create"),
    path("issues/<str:pk>/", issue_detail, name="issue_detail"),
    path("issues/<str:pk>/upvote/", upvote_issue, name="upvote_issue"),
    path("issues/<str:pk>/verify/", verify_issue, name="verify_issue"),
    path("issues/<str:pk>/status/", update_issue_status, name="update_issue_status"),
    path("issues/<str:pk>/comments/", comment_list_create, name="comment_list_create"),
    
    # Notifications routes
    path("notifications/", notification_list, name="notification_list"),
    path("notifications/<int:pk>/read/", mark_notification_read, name="mark_notification_read"),
    path("notifications/read-all/", mark_all_notifications_read, name="mark_all_notifications_read"),
    ]