from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: the audit log is append-only."""

    list_display = ["created_at", "user_label", "action", "entity_type", "entity_id", "ip_address"]
    list_filter = ["action", "entity_type"]
    search_fields = ["user_label", "entity_id", "description"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
