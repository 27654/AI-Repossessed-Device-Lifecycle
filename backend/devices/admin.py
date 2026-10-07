from django.contrib import admin

from .models import Attachment, Device, DeviceStatusChange


class ReadOnlyAdmin(admin.ModelAdmin):
    """Lifecycle records change only through devices.services, so the admin is read-only."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Device)
class DeviceAdmin(ReadOnlyAdmin):
    list_display = ["device_code", "make", "model", "imei", "serial_number", "status", "current_condition"]
    list_filter = ["status", "device_type", "current_condition"]
    search_fields = ["device_code", "imei", "serial_number", "make", "model"]


@admin.register(DeviceStatusChange)
class DeviceStatusChangeAdmin(ReadOnlyAdmin):
    list_display = ["changed_at", "device", "from_status", "to_status", "changed_by"]
    list_filter = ["to_status"]


@admin.register(Attachment)
class AttachmentAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "device", "original_name", "mime_type", "size_bytes"]
    exclude = ["file"]
