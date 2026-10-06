from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LoginAttempt, Permission, Role, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["full_name"]
    list_display = ["email", "full_name", "employee_id", "role", "account_status", "mfa_enabled"]
    list_filter = ["role", "account_status", "mfa_enabled"]
    search_fields = ["email", "full_name", "employee_id"]
    readonly_fields = ["last_login", "created_at", "updated_at", "mfa_enabled", "failed_login_count", "locked_until"]
    filter_horizontal = []
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Staff details", {"fields": ["full_name", "phone", "employee_id", "role", "account_status"]}),
        ("Security", {"fields": ["mfa_enabled", "failed_login_count", "locked_until"]}),
        ("Django admin access", {"fields": ["is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["last_login", "created_at", "updated_at"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "full_name", "employee_id", "role", "password1", "password2"]}),
    ]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    filter_horizontal = ["permissions"]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["code", "description"]


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ["created_at", "email_attempted", "success", "failure_reason", "ip_address"]
    list_filter = ["success", "failure_reason"]
    search_fields = ["email_attempted"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
