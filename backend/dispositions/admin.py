from django.contrib import admin

from devices.admin import ReadOnlyAdmin

from .models import Disposition


@admin.register(Disposition)
class DispositionAdmin(ReadOnlyAdmin):
    """Read-only: dispositions change only through dispositions.services."""

    list_display = ["reference", "device", "disposition_type", "status", "disposition_date", "sale_price_rwf", "responsible_user"]
    list_filter = ["disposition_type", "status"]
    search_fields = ["reference", "device__device_code", "buyer_reference", "recipient_reference"]
