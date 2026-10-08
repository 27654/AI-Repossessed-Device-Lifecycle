from django.contrib import admin

from devices.admin import ReadOnlyAdmin

from .models import Assessment


@admin.register(Assessment)
class AssessmentAdmin(ReadOnlyAdmin):
    """Read-only: assessments change only through assessments.services."""

    list_display = ["reference", "device", "assessment_date", "physical_condition", "functional_status", "status", "assessor"]
    list_filter = ["status", "physical_condition", "functional_status"]
    search_fields = ["reference", "device__device_code"]
