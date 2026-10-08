"""Recovery services: record, update and complete a device recovery.

Business rules live here, not in views or the frontend. Device status changes
go only through devices.services.transition_device.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import AuditAction
from audit.services import log_action
from devices.models import Device, DeviceStatus
from devices.services import transition_device, update_device

from .models import SUCCESSFUL_OUTCOMES, Recovery, RecoveryOutcome, RecoveryStatus

# Fields an officer may set while the record is In progress (also its audited fields).
EDITABLE_FIELDS = ["recovered_at", "recovery_location", "recovery_method", "outcome", "condition_notes", "notes"]

# Small allowance for clock differences between a phone/laptop and the server.
FUTURE_TOLERANCE = timedelta(minutes=5)


def _snapshot(recovery):
    values = {}
    for field in EDITABLE_FIELDS:
        value = getattr(recovery, field)
        values[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return values


def _check_recovered_at(value):
    if value and value > timezone.now() + FUTURE_TOLERANCE:
        raise ValidationError({"recovered_at": "The recovery date and time cannot be in the future."})


def _check_device_awaits_recovery(device):
    if device.status != DeviceStatus.IN_RECOVERY:
        raise ValidationError(
            {"device": f"Only devices that are In recovery can be recovered. This device is {device.get_status_display()}."}
        )


@transaction.atomic
def create_recovery(*, actor, device, request=None, **fields):
    """Open a recovery record for a device that is In recovery. The actor is the recovery officer."""
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be set." for field in unknown})

    # Lock the device so two officers cannot open records for it at the same time.
    device = Device.objects.select_for_update().get(pk=device.pk)
    _check_device_awaits_recovery(device)
    if device.recoveries.filter(status=RecoveryStatus.IN_PROGRESS).exists():
        raise ValidationError({"device": "This device already has a recovery in progress. Update or complete it instead."})
    _check_recovered_at(fields.get("recovered_at"))

    try:
        with transaction.atomic():
            recovery = Recovery.objects.create(device=device, recovery_officer=actor, **fields)
    except IntegrityError as exc:  # partial unique index: a concurrent request won the race
        raise ValidationError({"device": "This device already has a recovery in progress."}) from exc

    log_action(
        AuditAction.RECOVERY_CREATED,
        request=request,
        user=actor,
        entity=recovery,
        description=f"Recorded recovery {recovery.reference} for {device.device_code}.",
        new_values={"reference": recovery.reference, "device_code": device.device_code, **_snapshot(recovery)},
    )
    return recovery


@transaction.atomic
def update_recovery(recovery, *, actor, changes, request=None):
    """Change an In progress record and audit the changed fields. Completed records are history."""
    forbidden = set(changes) - set(EDITABLE_FIELDS)
    if forbidden:
        raise ValidationError({field: "This field cannot be edited." for field in forbidden})

    recovery = Recovery.objects.select_for_update().get(pk=recovery.pk)
    if not recovery.is_open:
        raise ValidationError({"detail": "A completed recovery is a historical record and cannot be changed."})
    _check_recovered_at(changes.get("recovered_at"))

    before = _snapshot(recovery)
    for field, value in changes.items():
        setattr(recovery, field, value)
    recovery.save()
    after = _snapshot(recovery)

    changed = [field for field in EDITABLE_FIELDS if before[field] != after[field]]
    if changed:
        log_action(
            AuditAction.RECOVERY_UPDATED,
            request=request,
            user=actor,
            entity=recovery,
            description=f"Updated {', '.join(changed)} of recovery {recovery.reference}.",
            previous_values={field: before[field] for field in changed},
            new_values={field: after[field] for field in changed},
        )
    return recovery


def _completion_errors(recovery):
    """Required information before a record can be completed, as {field: message}."""
    errors = {}
    if not recovery.outcome:
        errors["outcome"] = "Choose the recovery outcome before completing."
    if not recovery.recovery_location.strip():
        errors["recovery_location"] = "Enter where the recovery took place."
    if recovery.outcome == RecoveryOutcome.RECOVERED_WITH_ISSUES and not recovery.notes.strip():
        errors["notes"] = "Describe the issues found during recovery."
    if recovery.outcome == RecoveryOutcome.NOT_RECOVERED and not recovery.notes.strip():
        errors["notes"] = "Explain why the device was not recovered."
    return errors


@transaction.atomic
def complete_recovery(recovery, *, actor, request=None):
    """Lock the record and, for a successful outcome, move the device IN_RECOVERY -> RECOVERED.

    One transaction: if the status change or audit fails, the record stays In progress.
    """
    recovery = Recovery.objects.select_for_update().select_related("device").get(pk=recovery.pk)
    if not recovery.is_open:
        raise ValidationError({"detail": f"Recovery {recovery.reference} has already been completed."})
    errors = _completion_errors(recovery)
    if errors:
        raise ValidationError(errors)

    device = recovery.device
    successful = recovery.outcome in SUCCESSFUL_OUTCOMES
    if successful:
        _check_device_awaits_recovery(device)

    recovery.status = RecoveryStatus.COMPLETED
    recovery.completed_by = actor
    recovery.completed_at = timezone.now()
    recovery.save(update_fields=["status", "completed_by", "completed_at", "updated_at"])

    log_action(
        AuditAction.RECOVERY_COMPLETED,
        request=request,
        user=actor,
        entity=recovery,
        description=f"Completed recovery {recovery.reference} for {device.device_code}: {recovery.get_outcome_display()}.",
        previous_values={"status": RecoveryStatus.IN_PROGRESS},
        new_values={"status": RecoveryStatus.COMPLETED, "outcome": recovery.outcome, "device_code": device.device_code},
    )

    if successful:
        transition_device(
            device,
            DeviceStatus.RECOVERED,
            actor=actor,
            reason=f"Recovery {recovery.reference} completed: {recovery.get_outcome_display()}.",
            source_type="recovery",
            source_id=recovery.pk,
            request=request,
        )
        # Keep the device's recovery date (used by device filters) in step with the record.
        recovered_on = timezone.localdate(recovery.recovered_at)
        changes = {"recovery_date": recovered_on}
        if not device.recovery_reference:
            changes["recovery_reference"] = recovery.reference
        device.refresh_from_db()
        if any(getattr(device, field) != value for field, value in changes.items()):
            update_device(device, actor=actor, changes=changes, request=request)

    return recovery
