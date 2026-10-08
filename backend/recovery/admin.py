from django.contrib import admin

from devices.admin import ReadOnlyAdmin

from .models import Recovery


@admin.register(Recovery)
class RecoveryAdmin(ReadOnlyAdmin):
    """Read-only: recoveries change only through recovery.services."""

    list_display = ["reference", "device", "recovered_at", "recovery_method", "outcome", "status", "recovery_officer"]
    list_filter = ["status", "outcome", "recovery_method"]
    search_fields = ["reference", "device__device_code", "recovery_location"]
