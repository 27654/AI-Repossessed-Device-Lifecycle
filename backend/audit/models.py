from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class AuditAction(models.TextChoices):
    """Audited actions. Stored as plain text so new modules can add codes without a migration."""

    LOGIN = "LOGIN", "Login"
    LOGIN_FAILED = "LOGIN_FAILED", "Failed login"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED", "Account locked"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED", "Account unlocked"
    LOGOUT = "LOGOUT", "Logout"
    SESSION_EXPIRED = "SESSION_EXPIRED", "Session expired"
    PASSWORD_CHANGED = "PASSWORD_CHANGED", "Password changed"
    PASSWORD_CHANGE_FAILED = "PASSWORD_CHANGE_FAILED", "Password change failed"
    PASSWORD_RESET = "PASSWORD_RESET", "Password reset by administrator"
    MFA_SETUP_STARTED = "MFA_SETUP_STARTED", "MFA setup started"
    MFA_ENABLED = "MFA_ENABLED", "MFA enabled"
    MFA_DISABLED = "MFA_DISABLED", "MFA disabled"
    MFA_VERIFIED = "MFA_VERIFIED", "MFA verified"
    MFA_FAILED = "MFA_FAILED", "MFA verification failed"
    USER_CREATED = "USER_CREATED", "User created"
    USER_UPDATED = "USER_UPDATED", "User updated"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED", "User role changed"
    ROLE_PERMISSIONS_CHANGED = "ROLE_PERMISSIONS_CHANGED", "Role permissions changed"
    ROLE_UPDATED = "ROLE_UPDATED", "Role details updated"
    DEVICE_CREATED = "DEVICE_CREATED", "Device created"
    DEVICE_UPDATED = "DEVICE_UPDATED", "Device updated"
    DEVICE_STATUS_CHANGED = "DEVICE_STATUS_CHANGED", "Device status changed"
    ATTACHMENT_UPLOADED = "ATTACHMENT_UPLOADED", "Attachment uploaded"


class AuditLogQuerySet(models.QuerySet):
    """Blocks bulk changes. The database trigger (migration 0002) blocks everything else."""

    def update(self, **kwargs):
        raise PermissionDenied("Audit log entries cannot be modified.")

    def delete(self):
        raise PermissionDenied("Audit log entries cannot be deleted.")


class AuditLog(models.Model):
    """Append-only record of an important action. Written through audit.services.log_action.

    Append-only is enforced three ways: this model, its queryset, and a
    PostgreSQL trigger that rejects UPDATE and DELETE from any client.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    user_label = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.CharField(max_length=40, blank=True)
    previous_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_label or '-'} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit log entries cannot be deleted.")
