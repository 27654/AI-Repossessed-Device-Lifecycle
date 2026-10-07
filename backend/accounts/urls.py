from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.csrf, name="auth-csrf"),
    path("auth/login/", views.login, name="auth-login"),
    path("auth/mfa/verify/", views.mfa_verify, name="auth-mfa-verify"),
    path("auth/logout/", views.logout, name="auth-logout"),
    path("auth/me/", views.me, name="auth-me"),
    path("auth/change-password/", views.change_password, name="auth-change-password"),
    path("auth/mfa/setup/", views.mfa_setup, name="auth-mfa-setup"),
    path("auth/mfa/confirm/", views.mfa_confirm, name="auth-mfa-confirm"),
    path("auth/mfa/disable/", views.mfa_disable, name="auth-mfa-disable"),
    path("users/", views.UserListCreateView.as_view(), name="user-list"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user-reset-password"),
    path("users/<int:pk>/reset-mfa/", views.user_reset_mfa, name="user-reset-mfa"),
    path("users/<int:pk>/unlock/", views.user_unlock, name="user-unlock"),
    path("login-attempts/", views.LoginAttemptListView.as_view(), name="login-attempt-list"),
    path("roles/", views.RoleListView.as_view(), name="role-list"),
    path("roles/<int:pk>/", views.RoleDetailView.as_view(), name="role-detail"),
    path("permissions/", views.PermissionListView.as_view(), name="permission-list"),
]
