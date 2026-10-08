"""Condition assessment services: create, update and submit an assessment.

Business rules live here, not in views or the frontend. Device status changes
go only through devices.services.transition_device.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import AuditAction
from audit.services import log_action
from devices.models import Device, DeviceCondition, DeviceStatus
from devices.services import record_condition, transition_device

from .models import REQUIRED_FOR_SUBMISSION, Assessment, AssessmentStatus

# Fields an assessor may set while the assessment is a Draft (also its audited fields).
EDITABLE_FIELDS = [
    "assessment_date",
    "physical_condition",
    "cosmetic_condition",
    "screen_condition",
    "battery_condition",
    "functional_status",
    "accessories_condition",
    "defects",
    "assessment_notes",
    "estimated_repair_cost_rwf",
    "estimated_market_value_rwf",
]

# The device's 4-level condition rating, taken from the assessor's physical condition.
DEVICE_CONDITION_FROM_PHYSICAL = {
    "EXCELLENT": DeviceCondition.EXCELLENT,
    "GOOD": DeviceCondition.GOOD,
    "FAIR": DeviceCondition.FAIR,
    "POOR": DeviceCondition.POOR,
    "CRITICAL": DeviceCondition.POOR,
}


def _snapshot(assessment):
    values = {}
    for field in EDITABLE_FIELDS:
        value = getattr(assessment, field)
        values[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return values


def _clean(fields):
    """Normalise inputs: defects are stored once each, in a stable order."""
    if "defects" in fields:
        fields["defects"] = sorted(set(fields["defects"] or []))
    return fields


def _check_date(value):
    if value and value > timezone.localdate():
        raise ValidationError({"assessment_date": "The assessment date cannot be in the future."})


def _check_device_recovered(device):
    if device.status != DeviceStatus.RECOVERED:
        raise ValidationError(
            {"device": f"Only Recovered devices can be assessed. This device is {device.get_status_display()}."}
        )


@transaction.atomic
def create_assessment(*, actor, device, request=None, **fields):
    """Open a Draft assessment for a Recovered device. The actor is the assessor."""
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be set." for field in unknown})

    # Lock the device so two assessors cannot open drafts for it at the same time.
    device = Device.objects.select_for_update().get(pk=device.pk)
    _check_device_recovered(device)
    if device.assessments.filter(status=AssessmentStatus.DRAFT).exists():
        raise ValidationError({"device": "This device already has a draft assessment. Continue that one instead."})
    if device.assessments.filter(status=AssessmentStatus.SUBMITTED).exists():
        raise ValidationError({"device": "This device already has a submitted assessment."})
    _check_date(fields.get("assessment_date"))

    try:
        with transaction.atomic():
            assessment = Assessment.objects.create(device=device, assessor=actor, **_clean(fields))
    except IntegrityError as exc:  # partial unique index: a concurrent request won the race
        raise ValidationError({"device": "This device already has a draft assessment."}) from exc

    log_action(
        AuditAction.ASSESSMENT_CREATED,
        request=request,
        user=actor,
        entity=assessment,
        description=f"Started assessment {assessment.reference} for {device.device_code}.",
        new_values={"reference": assessment.reference, "device_code": device.device_code, **_snapshot(assessment)},
    )
    return assessment


@transaction.atomic
def update_assessment(assessment, *, actor, changes, request=None):
    """Change a Draft and audit the changed fields. Submitted assessments are history."""
    forbidden = set(changes) - set(EDITABLE_FIELDS)
    if forbidden:
        raise ValidationError({field: "This field cannot be edited." for field in forbidden})

    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    if not assessment.is_draft:
        raise ValidationError({"detail": "A submitted assessment is a historical record and cannot be changed."})
    _check_date(changes.get("assessment_date"))

    before = _snapshot(assessment)
    for field, value in _clean(dict(changes)).items():
        setattr(assessment, field, value)
    assessment.save()
    after = _snapshot(assessment)

    changed = [field for field in EDITABLE_FIELDS if before[field] != after[field]]
    if changed:
        log_action(
            AuditAction.ASSESSMENT_UPDATED,
            request=request,
            user=actor,
            entity=assessment,
            description=f"Updated {', '.join(changed)} of assessment {assessment.reference}.",
            previous_values={field: before[field] for field in changed},
            new_values={field: after[field] for field in changed},
        )
    return assessment


def submission_errors(assessment):
    """Required information before submission, as {field: message}."""
    errors = {}
    for field in REQUIRED_FOR_SUBMISSION:
        value = getattr(assessment, field)
        if value in ("", None):
            errors[field] = "This field is required before submitting."
    if assessment.estimated_market_value_rwf == 0:
        errors["estimated_market_value_rwf"] = "The estimated market value must be greater than 0 RWF."
    return errors


@transaction.atomic
def submit_assessment(assessment, *, actor, request=None):
    """Lock the assessment, mark it Submitted and move the device RECOVERED -> ASSESSED.

    One transaction: if the status change or audit fails, the assessment stays a Draft.
    """
    assessment = Assessment.objects.select_for_update().select_related("device").get(pk=assessment.pk)
    if not assessment.is_draft:
        raise ValidationError({"detail": f"Assessment {assessment.reference} has already been submitted."})
    errors = submission_errors(assessment)
    if errors:
        raise ValidationError(errors)
    device = assessment.device
    _check_device_recovered(device)

    assessment.status = AssessmentStatus.SUBMITTED
    assessment.submitted_at = timezone.now()
    try:
        with transaction.atomic():
            assessment.save(update_fields=["status", "submitted_at", "updated_at"])
    except IntegrityError as exc:  # another assessment for this device was submitted first
        raise ValidationError({"detail": "This device already has a submitted assessment."}) from exc

    log_action(
        AuditAction.ASSESSMENT_SUBMITTED,
        request=request,
        user=actor,
        entity=assessment,
        description=f"Submitted assessment {assessment.reference} for {device.device_code}.",
        previous_values={"status": AssessmentStatus.DRAFT},
        new_values={"status": AssessmentStatus.SUBMITTED, "device_code": device.device_code, **_snapshot(assessment)},
    )
    transition_device(
        device,
        DeviceStatus.ASSESSED,
        actor=actor,
        reason=f"Condition assessment {assessment.reference} submitted.",
        source_type="assessment",
        source_id=assessment.pk,
        request=request,
    )
    record_condition(
        device,
        DEVICE_CONDITION_FROM_PHYSICAL[assessment.physical_condition],
        actor=actor,
        source_reference=assessment.reference,
        request=request,
    )
    return assessment
