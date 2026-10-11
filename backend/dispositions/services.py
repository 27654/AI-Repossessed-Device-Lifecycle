"""Disposition services: draft, update and confirm a reallocation or resale.

Business rules live here, not in views or the frontend. Confirming moves the
device READY_FOR_DISPOSITION -> REALLOCATED / RESOLD, only through
devices.services.transition_device. No AI code path calls these services.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.models import AuditAction
from audit.services import log_action
from devices.models import Device, DeviceStatus
from devices.services import transition_device

from .models import DEVICE_STATUS_FOR_TYPE, Disposition, DispositionStatus, DispositionType

EDITABLE_FIELDS = [
    "disposition_type",
    "disposition_date",
    "destination",
    "recipient_reference",
    "sale_price_rwf",
    "buyer_reference",
    "notes",
]

# Fields that belong to only one type; they are cleared when the type changes.
REALLOCATION_ONLY = ("destination", "recipient_reference")
RESALE_ONLY = ("sale_price_rwf", "buyer_reference")


def _snapshot(disposition):
    values = {}
    for field in EDITABLE_FIELDS:
        value = getattr(disposition, field)
        values[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return values


def type_errors(disposition):
    """Fields required (or not allowed) for the disposition's type, as {field: message}."""
    errors = {}
    if disposition.disposition_type == DispositionType.RESALE:
        if not disposition.sale_price_rwf:
            errors["sale_price_rwf"] = "Enter the sale price (a whole RWF amount above 0)."
        if not disposition.buyer_reference:
            errors["buyer_reference"] = "Enter the buyer reference."
    elif disposition.disposition_type == DispositionType.REALLOCATION:
        if not disposition.destination.strip():
            errors["destination"] = "Enter the receiving department, branch or partner."
    else:
        errors["disposition_type"] = "Choose reallocation or resale."
    if disposition.disposition_date and disposition.disposition_date > timezone.localdate():
        errors["disposition_date"] = "The disposition date cannot be in the future."
    return errors


def _apply(disposition, fields):
    """Set fields and keep the record to one type.

    A value sent for the other type's field is an error; values left over from
    before a type change are cleared.
    """
    new_type = fields.get("disposition_type", disposition.disposition_type)
    other = RESALE_ONLY if new_type == DispositionType.REALLOCATION else REALLOCATION_ONLY
    label = "resale" if new_type == DispositionType.REALLOCATION else "reallocation"
    wrong = {field: f"Only used for a {label}." for field in other if fields.get(field) not in (None, "")}
    if wrong:
        raise ValidationError(wrong)
    for field, value in fields.items():
        setattr(disposition, field, value)
    for field in other:
        setattr(disposition, field, None if field == "sale_price_rwf" else "")
    errors = type_errors(disposition)
    if errors:
        raise ValidationError(errors)


def _violated_constraint(exc):
    """Name of the PostgreSQL constraint behind an IntegrityError, if known."""
    return getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)


def _check_device_ready(device):
    if device.status != DeviceStatus.READY_FOR_DISPOSITION:
        raise ValidationError(
            {"device": f"Only devices that are Ready for disposition can be reallocated or resold. This device is "
             f"{device.get_status_display()}."}
        )


@transaction.atomic
def create_disposition(*, actor, device, request=None, **fields):
    """Draft a disposition for a device that is Ready for disposition. The actor is the responsible user."""
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be set." for field in unknown})

    device = Device.objects.select_for_update().get(pk=device.pk)
    _check_device_ready(device)
    if device.dispositions.filter(status=DispositionStatus.DRAFT).exists():
        raise ValidationError({"device": "This device already has a draft disposition. Continue that one instead."})

    disposition = Disposition(device=device, responsible_user=actor)
    _apply(disposition, fields)
    try:
        with transaction.atomic():
            disposition.save()
    except IntegrityError as exc:
        # Partial unique index: a concurrent request opened a draft first. Other errors are real.
        if _violated_constraint(exc) != "disposition_one_draft_per_device":
            raise
        raise ValidationError({"device": "This device already has a draft disposition."}) from exc

    log_action(
        AuditAction.DISPOSITION_CREATED,
        request=request,
        user=actor,
        entity=disposition,
        description=f"Drafted {disposition.get_disposition_type_display().lower()} {disposition.reference} "
        f"for {device.device_code}.",
        new_values={"reference": disposition.reference, "device_code": device.device_code, **_snapshot(disposition)},
    )
    return disposition


@transaction.atomic
def update_disposition(disposition, *, actor, changes, request=None):
    """Change a draft and audit the changed fields. Confirmed dispositions are history."""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be edited." for field in unknown})
    disposition = Disposition.objects.select_for_update().select_related("device").get(pk=disposition.pk)
    if not disposition.is_draft:
        raise ValidationError({"detail": "A confirmed disposition is a historical record and cannot be changed."})

    before = _snapshot(disposition)
    _apply(disposition, changes)
    disposition.save()
    after = _snapshot(disposition)

    changed = [field for field in EDITABLE_FIELDS if before[field] != after[field]]
    if changed:
        log_action(
            AuditAction.DISPOSITION_UPDATED,
            request=request,
            user=actor,
            entity=disposition,
            description=f"Updated {', '.join(changed)} of disposition {disposition.reference}.",
            previous_values={f: before[f] for f in changed},
            new_values={f: after[f] for f in changed},
        )
    return disposition


@transaction.atomic
def confirm_disposition(disposition, *, actor, request=None):
    """Confirm a draft: it becomes immutable and the device moves to REALLOCATED or RESOLD.

    One transaction with the disposition and device rows locked; a second,
    concurrent confirmation finds the record already confirmed, and the
    partial unique index allows only one confirmed disposition per device.
    """
    if actor is None or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise ValidationError({"detail": "A signed-in, active staff member must confirm a disposition."})
    disposition = Disposition.objects.select_for_update().select_related("device").get(pk=disposition.pk)
    if not disposition.is_draft:
        raise ValidationError({"detail": f"Disposition {disposition.reference} has already been confirmed."})
    errors = type_errors(disposition)
    if errors:
        raise ValidationError(errors)
    device = disposition.device
    _check_device_ready(device)

    disposition.status = DispositionStatus.CONFIRMED
    disposition.confirmed_by = actor
    disposition.confirmed_at = timezone.now()
    try:
        with transaction.atomic():
            disposition.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    except IntegrityError as exc:
        # Only the one-confirmed-per-device index means "already disposed"; anything else is a real error.
        if _violated_constraint(exc) != "disposition_one_confirmed_per_device":
            raise
        raise ValidationError({"detail": "This device already has a confirmed disposition."}) from exc

    target = DEVICE_STATUS_FOR_TYPE[disposition.disposition_type]
    log_action(
        AuditAction.DISPOSITION_CONFIRMED,
        request=request,
        user=actor,
        entity=disposition,
        description=f"Confirmed {disposition.get_disposition_type_display().lower()} {disposition.reference} "
        f"for {device.device_code}.",
        previous_values={"status": DispositionStatus.DRAFT},
        new_values={"status": DispositionStatus.CONFIRMED, "device_code": device.device_code, **_snapshot(disposition)},
    )
    transition_device(
        device,
        target,
        actor=actor,
        reason=f"{disposition.get_disposition_type_display()} {disposition.reference} confirmed.",
        source_type="disposition",
        source_id=disposition.pk,
        request=request,
    )
    return disposition
