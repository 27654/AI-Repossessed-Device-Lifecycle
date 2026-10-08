"""Device lifecycle services.

`transition_device` is the ONLY way any module may change a device's status.
Lifecycle modules (recovery, assessments, refurbishment, dispositions) call it
from inside their own transaction, passing the record that caused the change.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.models import AuditAction
from audit.services import log_action

from .models import Attachment, Device, DeviceStatus, DeviceStatusChange

# Allowed lifecycle transitions (docs/architecture.md section 6).
ALLOWED_TRANSITIONS = {
    DeviceStatus.IN_RECOVERY: {DeviceStatus.RECOVERED},
    DeviceStatus.RECOVERED: {DeviceStatus.ASSESSED},
    DeviceStatus.ASSESSED: {
        DeviceStatus.REFURBISHING,
        DeviceStatus.READY_FOR_DISPOSITION,
        DeviceStatus.UNABLE_TO_REPAIR,
    },
    DeviceStatus.REFURBISHING: {DeviceStatus.READY_FOR_DISPOSITION, DeviceStatus.UNABLE_TO_REPAIR},
    DeviceStatus.READY_FOR_DISPOSITION: {DeviceStatus.REALLOCATED, DeviceStatus.RESOLD},
    DeviceStatus.REALLOCATED: set(),
    DeviceStatus.RESOLD: set(),
    DeviceStatus.UNABLE_TO_REPAIR: set(),
}

# A device is registered either while recovery is still under way or once it is in hand.
INITIAL_STATUSES = (DeviceStatus.IN_RECOVERY, DeviceStatus.RECOVERED)

# Sources that may never move a device: AI output is advice, a human decides.
FORBIDDEN_SOURCE_TYPES = {"ai_recommendation", "ai_engine"}

# Fields recorded in audit before/after values for device edits.
AUDITED_FIELDS = [
    "imei",
    "serial_number",
    "make",
    "model",
    "device_type",
    "color",
    "storage_capacity_gb",
    "operating_system",
    "condition_summary",
    "current_location",
    "recovery_reference",
    "recovery_date",
    "previous_owner_ref",
    "notes",
]


class InvalidTransition(ValidationError):
    """A requested status change breaks the lifecycle rules. Views answer 400."""


def _snapshot(device, fields=AUDITED_FIELDS):
    values = {}
    for field in fields:
        value = getattr(device, field)
        values[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return values


def _clean_identifiers(fields):
    """Blank IMEI/serial means "none" (NULL), so the unique constraints ignore it."""
    for field in ("imei", "serial_number"):
        if field in fields and not fields[field]:
            fields[field] = None
    return fields


def _check_actor(actor):
    if actor is None or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise InvalidTransition({"detail": "A signed-in, active staff member must make status changes."})


@transaction.atomic
def register_device(*, actor, initial_status=DeviceStatus.IN_RECOVERY, reason="", request=None, **fields):
    """Create a device, its first history entry and the audit record in one transaction."""
    _check_actor(actor)
    if initial_status not in INITIAL_STATUSES:
        raise InvalidTransition({"initial_status": "A new device must start as In recovery or Recovered."})

    device = Device.objects.create(status=initial_status, created_by=actor, **_clean_identifiers(fields))
    DeviceStatusChange.objects.create(
        device=device,
        from_status=None,
        to_status=initial_status,
        changed_by=actor,
        reason=reason or "Device registered.",
        source_type="device_registration",
    )
    log_action(
        AuditAction.DEVICE_CREATED,
        request=request,
        user=actor,
        entity=device,
        description=f"Registered device {device.device_code} ({device.make} {device.model}).",
        new_values={"device_code": device.device_code, "status": initial_status, **_snapshot(device)},
    )
    return device


@transaction.atomic
def update_device(device, *, actor, changes, request=None):
    """Apply descriptive field changes (never status) and audit what changed."""
    forbidden = {"status", "current_condition", "device_code", "created_by"} & set(changes)
    if forbidden:
        raise ValidationError({field: "This field cannot be edited directly." for field in forbidden})

    device = Device.objects.select_for_update().get(pk=device.pk)
    before = _snapshot(device)
    for field, value in _clean_identifiers(dict(changes)).items():
        setattr(device, field, value)
    device.save()
    after = _snapshot(device)

    changed = [field for field in AUDITED_FIELDS if before[field] != after[field]]
    if changed:
        log_action(
            AuditAction.DEVICE_UPDATED,
            request=request,
            user=actor,
            entity=device,
            description=f"Updated {', '.join(changed)} of {device.device_code}.",
            previous_values={field: before[field] for field in changed},
            new_values={field: after[field] for field in changed},
        )
    return device


@transaction.atomic
def transition_device(device, to_status, *, actor, reason="", source_type="", source_id=None, request=None):
    """Move a device to a new lifecycle status.

    Locks the device row, checks the transition is allowed, then writes the
    status, a DeviceStatusChange and an AuditLog entry together. Raises
    InvalidTransition (HTTP 400 when raised in a view) if any rule fails.
    """
    _check_actor(actor)
    if source_type in FORBIDDEN_SOURCE_TYPES:
        raise InvalidTransition({"detail": "AI recommendations cannot change a device's status."})
    if to_status not in DeviceStatus.values:
        raise InvalidTransition({"status": f"Unknown device status '{to_status}'."})

    device = Device.objects.select_for_update().get(pk=device.pk)
    from_status = device.status
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidTransition(
            {
                "status": f"A device cannot move from {DeviceStatus(from_status).label} "
                f"to {DeviceStatus(to_status).label}."
            }
        )

    device.status = to_status
    device.save(update_fields=["status", "updated_at"])
    change = DeviceStatusChange.objects.create(
        device=device,
        from_status=from_status,
        to_status=to_status,
        changed_by=actor,
        reason=reason,
        source_type=source_type,
        source_id=source_id,
    )
    log_action(
        AuditAction.DEVICE_STATUS_CHANGED,
        request=request,
        user=actor,
        entity=device,
        description=f"{device.device_code}: {DeviceStatus(from_status).label} -> {DeviceStatus(to_status).label}."
        + (f" {reason}" if reason else ""),
        previous_values={"status": from_status},
        new_values={"status": to_status, "source_type": source_type, "source_id": source_id},
    )
    return change


@transaction.atomic
def add_attachment(device, *, actor, upload, mime_type, original_name, description="", recovery=None, request=None):
    """Store an already validated upload and audit it (file metadata only).

    `recovery` optionally links the file as evidence for a recovery record of the same device.
    """
    if recovery is not None and recovery.device_id != device.pk:
        raise ValidationError({"detail": "Evidence must belong to the same device as the recovery."})
    attachment = Attachment(
        device=device,
        recovery=recovery,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=upload.size,
        description=description,
        uploaded_by=actor,
    )
    attachment.file.save("upload", upload, save=False)  # name comes from attachment_upload_to
    attachment.save()
    log_action(
        AuditAction.ATTACHMENT_UPLOADED,
        request=request,
        user=actor,
        entity=device,
        description=f"Uploaded {original_name} to {device.device_code}"
        + (f" as evidence for {recovery.reference}." if recovery else "."),
        new_values={
            "attachment_id": attachment.pk,
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": attachment.size_bytes,
            **({"recovery_id": recovery.pk, "recovery_reference": recovery.reference} if recovery else {}),
        },
    )
    return attachment
