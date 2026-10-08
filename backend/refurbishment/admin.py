from django.contrib import admin

from devices.admin import ReadOnlyAdmin

from .models import RefurbishmentItem, RefurbishmentStep, RefurbishmentWorkOrder


@admin.register(RefurbishmentWorkOrder)
class WorkOrderAdmin(ReadOnlyAdmin):
    """Read-only: work orders change only through refurbishment.services."""

    list_display = ["reference", "device", "status", "outcome", "assigned_to", "actual_cost_rwf", "created_at"]
    list_filter = ["status", "outcome"]
    search_fields = ["reference", "device__device_code"]


@admin.register(RefurbishmentStep)
class StepAdmin(ReadOnlyAdmin):
    list_display = ["work_order", "step_type", "status", "performed_by", "completed_at"]
    list_filter = ["step_type", "status"]


@admin.register(RefurbishmentItem)
class ItemAdmin(ReadOnlyAdmin):
    list_display = ["work_order", "item_name", "quantity", "unit_cost_rwf", "total_cost_rwf"]
