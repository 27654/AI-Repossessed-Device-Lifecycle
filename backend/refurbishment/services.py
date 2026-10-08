"""Refurbishment services: work orders, steps, parts, completion.

Business rules live here, not in views or the frontend. Device status changes
go only through devices.services.transition_device: completing a work order
moves the device REFURBISHING -> READY_FOR_DISPOSITION, and "unable to repair"
moves it REFURBISHING -> UNABLE_TO_REPAIR. AI output never reaches here.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.rbac import Perm
from audit.models import AuditAction
from audit.services import log_action
from devices.models import Device, DeviceStatus
from devices.services import transition_device

from .models import (
    REQUIRED_CHECK_TYPES,
    RefurbishmentItem,
    RefurbishmentStep,
    RefurbishmentWorkOrder,
    StepStatus,
    StepType,
    WorkOrderOutcome,
    WorkOrderStatus,
)

WORK_ORDER_FIELDS = ["assigned_to", "diagnosis", "work_summary", "estimated_cost_rwf", "labour_cost_rwf"]
STEP_FIELDS = ["status", "description", "notes"]
ITEM_FIELDS = ["item_name", "part_number", "quantity", "unit_cost_rwf", "supplier", "notes"]

# Step status changes a technician may make. COMPLETED and SKIPPED are final.
STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.IN_PROGRESS, StepStatus.COMPLETED, StepStatus.SKIPPED},
    StepStatus.IN_PROGRESS: {StepStatus.COMPLETED, StepStatus.SKIPPED},
    StepStatus.COMPLETED: set(),
    StepStatus.SKIPPED: set(),
}


# --- helpers -----------------------------------------------------------------


def technicians():
    """Active users whose role may manage refurbishment (possible assignees)."""
    return (
        get_user_model()
        .objects.filter(account_status=User.Status.ACTIVE, role__permissions__code=Perm.REFURBISHMENT_MANAGE)
        .distinct()
        .order_by("full_name")
    )


def _check_assignee(user):
    if user is not None and not (user.is_active and user.has_permission_code(Perm.REFURBISHMENT_MANAGE)):
        raise ValidationError({"assigned_to": "Assign the work order to an active member of the refurbishment team."})


def _value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, User):
        return {"id": value.pk, "full_name": value.full_name}
    return value


def _snapshot(obj, fields):
    return {field: _value(getattr(obj, field)) for field in fields}


def _changed(before, after):
    return [field for field in before if before[field] != after[field]]


def _lock(work_order):
    return RefurbishmentWorkOrder.objects.select_for_update().select_related("device").get(pk=work_order.pk)


def _require_active(work_order):
    if not work_order.is_active:
        raise ValidationError(
            {"detail": f"Work order {work_order.reference} is {work_order.get_status_display().lower()} and can no "
             "longer be changed."}
        )


def _require_device_refurbishing(device):
    if device.status != DeviceStatus.REFURBISHING:
        raise ValidationError(
            {"device": f"Only devices that are Refurbishing can have refurbishment work. This device is "
             f"{device.get_status_display()}."}
        )


def parts_total(work_order):
    """Sum of the recorded parts and materials, in whole RWF."""
    return work_order.items.aggregate(total=Sum("total_cost_rwf"))["total"] or 0


# --- work orders -------------------------------------------------------------


@transaction.atomic
def create_work_order(*, actor, device, assigned_to=None, diagnosis="", estimated_cost_rwf=0, request=None):
    """Open a work order for a device in REFURBISHING. One active work order per device."""
    device = Device.objects.select_for_update().get(pk=device.pk)
    _require_device_refurbishing(device)
    _check_assignee(assigned_to)
    if device.work_orders.filter(status__in=(WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS)).exists():
        raise ValidationError({"device": "This device already has an active work order. Continue that one instead."})

    try:
        with transaction.atomic():
            work_order = RefurbishmentWorkOrder.objects.create(
                device=device,
                created_by=actor,
                assigned_to=assigned_to,
                diagnosis=diagnosis,
                estimated_cost_rwf=estimated_cost_rwf,
            )
    except IntegrityError as exc:  # partial unique index: a concurrent request won the race
        raise ValidationError({"device": "This device already has an active work order."}) from exc

    log_action(
        AuditAction.REFURBISHMENT_CREATED,
        request=request,
        user=actor,
        entity=work_order,
        entity_type="work_order",
        description=f"Opened work order {work_order.reference} for {device.device_code}.",
        new_values={
            "reference": work_order.reference,
            "device_code": device.device_code,
            **_snapshot(work_order, WORK_ORDER_FIELDS),
        },
    )
    return work_order


@transaction.atomic
def update_work_order(work_order, *, actor, changes, request=None):
    """Edit an active work order (assignee, diagnosis, summary, costs) and audit the changes."""
    unknown = set(changes) - set(WORK_ORDER_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be edited." for field in unknown})
    work_order = _lock(work_order)
    _require_active(work_order)
    if "assigned_to" in changes:
        _check_assignee(changes["assigned_to"])

    before = _snapshot(work_order, WORK_ORDER_FIELDS)
    for field, value in changes.items():
        setattr(work_order, field, value)
    work_order.save()
    after = _snapshot(work_order, WORK_ORDER_FIELDS)

    changed = _changed(before, after)
    if changed:
        log_action(
            AuditAction.REFURBISHMENT_UPDATED,
            request=request,
            user=actor,
            entity=work_order,
            entity_type="work_order",
            description=f"Updated {', '.join(changed)} of work order {work_order.reference}.",
            previous_values={f: before[f] for f in changed},
            new_values={f: after[f] for f in changed},
        )
    return work_order


@transaction.atomic
def start_work_order(work_order, *, actor, request=None):
    """OPEN -> IN_PROGRESS. Unassigned work is assigned to whoever starts it."""
    work_order = _lock(work_order)
    if work_order.status != WorkOrderStatus.OPEN:
        raise ValidationError({"detail": f"Only an Open work order can be started. {work_order.reference} is "
                               f"{work_order.get_status_display()}."})
    _require_device_refurbishing(work_order.device)

    work_order.status = WorkOrderStatus.IN_PROGRESS
    work_order.started_at = timezone.now()
    if work_order.assigned_to_id is None:
        work_order.assigned_to = actor
    work_order.save(update_fields=["status", "started_at", "assigned_to", "updated_at"])
    log_action(
        AuditAction.REFURBISHMENT_STARTED,
        request=request,
        user=actor,
        entity=work_order,
        entity_type="work_order",
        description=f"Started work order {work_order.reference} ({work_order.device.device_code}).",
        previous_values={"status": WorkOrderStatus.OPEN},
        new_values={"status": WorkOrderStatus.IN_PROGRESS, "assigned_to": _value(work_order.assigned_to)},
    )
    return work_order


def completion_errors(work_order):
    """What still blocks completing the work order as repaired, as {field: message}."""
    errors = {}
    if not work_order.work_summary.strip():
        errors["work_summary"] = "Describe the work carried out."
    if work_order.labour_cost_rwf is None:
        errors["labour_cost_rwf"] = "Enter the labour cost (0 if none)."
    steps = list(work_order.steps.all())
    unfinished = [step for step in steps if not step.is_finished]
    if unfinished:
        names = ", ".join(step.get_step_type_display() for step in unfinished)
        errors["steps"] = f"Finish or skip (with a reason) every step first: {names}."
    missing = [
        StepType(check).label
        for check in REQUIRED_CHECK_TYPES
        if not any(step.step_type == check and step.status == StepStatus.COMPLETED for step in steps)
    ]
    if missing:
        errors["checks"] = f"These checks must be completed before the device is ready: {', '.join(missing)}."
    return errors


def _close(work_order, *, actor, status, outcome="", reason=""):
    work_order.status = status
    work_order.outcome = outcome
    work_order.closure_reason = reason
    work_order.completed_at = timezone.now()
    work_order.completed_by = actor
    fields = ["status", "outcome", "closure_reason", "completed_at", "completed_by", "updated_at"]
    if status == WorkOrderStatus.COMPLETED:
        work_order.actual_cost_rwf = parts_total(work_order) + (work_order.labour_cost_rwf or 0)
        fields.append("actual_cost_rwf")
    work_order.save(update_fields=fields)


@transaction.atomic
def complete_work_order(work_order, *, actor, work_summary=None, labour_cost_rwf=None, request=None):
    """Close the work order as repaired and move the device REFURBISHING -> READY_FOR_DISPOSITION.

    The actual cost is calculated here (parts total + labour) and frozen.
    One transaction with the work order and device rows locked: a second,
    concurrent completion finds the work order already closed.
    """
    work_order = _lock(work_order)
    _require_active(work_order)
    final_values = {}
    if work_summary is not None:
        final_values["work_summary"] = work_summary.strip()
    if labour_cost_rwf is not None:
        final_values["labour_cost_rwf"] = labour_cost_rwf
    for field, value in final_values.items():
        setattr(work_order, field, value)

    errors = completion_errors(work_order)
    if errors:
        raise ValidationError(errors)
    device = work_order.device
    _require_device_refurbishing(device)

    if final_values:
        work_order.save(update_fields=[*final_values, "updated_at"])
    _close(work_order, actor=actor, status=WorkOrderStatus.COMPLETED, outcome=WorkOrderOutcome.REPAIRED)
    log_action(
        AuditAction.REFURBISHMENT_COMPLETED,
        request=request,
        user=actor,
        entity=work_order,
        entity_type="work_order",
        description=f"Completed work order {work_order.reference} for {device.device_code}: repaired.",
        previous_values={"status": WorkOrderStatus.IN_PROGRESS},
        new_values={
            "status": WorkOrderStatus.COMPLETED,
            "outcome": WorkOrderOutcome.REPAIRED,
            "work_summary": work_order.work_summary,
            "parts_cost_rwf": parts_total(work_order),
            "labour_cost_rwf": work_order.labour_cost_rwf,
            "actual_cost_rwf": work_order.actual_cost_rwf,
            "device_code": device.device_code,
        },
    )
    transition_device(
        device,
        DeviceStatus.READY_FOR_DISPOSITION,
        actor=actor,
        reason=f"Refurbishment {work_order.reference} completed.",
        source_type="refurbishment",
        source_id=work_order.pk,
        request=request,
    )
    return work_order


@transaction.atomic
def mark_unable_to_repair(work_order, *, actor, reason, request=None):
    """Close the work order as unable to repair and move the device REFURBISHING -> UNABLE_TO_REPAIR."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Explain why the device cannot be repaired."})
    work_order = _lock(work_order)
    _require_active(work_order)
    device = work_order.device
    _require_device_refurbishing(device)

    previous_status = work_order.status
    _close(
        work_order,
        actor=actor,
        status=WorkOrderStatus.COMPLETED,
        outcome=WorkOrderOutcome.UNABLE_TO_REPAIR,
        reason=reason,
    )
    log_action(
        AuditAction.REFURBISHMENT_UNABLE_TO_REPAIR,
        request=request,
        user=actor,
        entity=work_order,
        entity_type="work_order",
        description=f"Closed work order {work_order.reference} for {device.device_code}: unable to repair.",
        previous_values={"status": previous_status},
        new_values={
            "status": WorkOrderStatus.COMPLETED,
            "outcome": WorkOrderOutcome.UNABLE_TO_REPAIR,
            "reason": reason,
            "actual_cost_rwf": work_order.actual_cost_rwf,
            "device_code": device.device_code,
        },
    )
    transition_device(
        device,
        DeviceStatus.UNABLE_TO_REPAIR,
        actor=actor,
        reason=f"Refurbishment {work_order.reference}: unable to repair. {reason}"[:255],
        source_type="refurbishment",
        source_id=work_order.pk,
        request=request,
    )
    return work_order


@transaction.atomic
def cancel_work_order(work_order, *, actor, reason, request=None):
    """Close a work order opened in error. The device stays REFURBISHING so a new one can be opened."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Explain why the work order is cancelled."})
    work_order = _lock(work_order)
    _require_active(work_order)
    previous_status = work_order.status
    _close(work_order, actor=actor, status=WorkOrderStatus.CANCELLED, reason=reason)
    log_action(
        AuditAction.REFURBISHMENT_CANCELLED,
        request=request,
        user=actor,
        entity=work_order,
        entity_type="work_order",
        description=f"Cancelled work order {work_order.reference} ({work_order.device.device_code}).",
        previous_values={"status": previous_status},
        new_values={"status": WorkOrderStatus.CANCELLED, "reason": reason},
    )
    return work_order


# --- steps -------------------------------------------------------------------


@transaction.atomic
def add_step(work_order, *, actor, step_type, description="", notes="", request=None):
    work_order = _lock(work_order)
    _require_active(work_order)
    step = RefurbishmentStep.objects.create(
        work_order=work_order, step_type=step_type, description=description, notes=notes
    )
    log_action(
        AuditAction.REFURBISHMENT_STEP_CREATED,
        request=request,
        user=actor,
        entity=step,
        entity_type="work_order_step",
        description=f"Added step {step.get_step_type_display()} to {work_order.reference}.",
        new_values={"work_order": work_order.reference, "step_type": step_type, "description": description},
    )
    return step


@transaction.atomic
def update_step(step, *, actor, changes, request=None):
    """Edit a step or move it along PENDING -> IN_PROGRESS -> COMPLETED / SKIPPED.

    Progress requires a started work order. Skipping requires a reason in
    `notes`. Finished steps (completed or skipped) are history and cannot change.
    """
    unknown = set(changes) - set(STEP_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be edited." for field in unknown})
    work_order = _lock(step.work_order)
    _require_active(work_order)
    step = RefurbishmentStep.objects.select_for_update().get(pk=step.pk)
    if step.is_finished:
        raise ValidationError({"detail": f"This step is {step.get_status_display().lower()} and can no longer change."})

    before = _snapshot(step, STEP_FIELDS)
    new_status = changes.get("status", step.status)
    if new_status != step.status:
        if new_status not in STEP_TRANSITIONS[step.status]:
            raise ValidationError(
                {"status": f"A step cannot move from {step.get_status_display()} to {StepStatus(new_status).label}."}
            )
        if work_order.status != WorkOrderStatus.IN_PROGRESS:
            raise ValidationError({"status": "Start the work order before working on its steps."})

    for field in ("description", "notes"):
        if field in changes:
            setattr(step, field, changes[field].strip() if field == "notes" else changes[field])

    if new_status != step.status:
        now = timezone.now()
        if new_status == StepStatus.SKIPPED and not step.notes:
            raise ValidationError({"notes": "Give a reason for skipping this step."})
        if new_status in (StepStatus.IN_PROGRESS, StepStatus.COMPLETED) and step.started_at is None:
            step.started_at = now
        if new_status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
            step.completed_at = now
        step.performed_by = actor
        step.status = new_status
    step.save()

    after = _snapshot(step, STEP_FIELDS)
    changed = _changed(before, after)
    if changed:
        log_action(
            AuditAction.REFURBISHMENT_STEP_UPDATED,
            request=request,
            user=actor,
            entity=step,
            entity_type="work_order_step",
            description=f"Updated step {step.get_step_type_display()} of {work_order.reference}: {', '.join(changed)}.",
            previous_values={f: before[f] for f in changed},
            new_values={f: after[f] for f in changed},
        )
    return step


# --- parts and materials -----------------------------------------------------


@transaction.atomic
def add_item(work_order, *, actor, request=None, **fields):
    unknown = set(fields) - set(ITEM_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be set." for field in unknown})
    work_order = _lock(work_order)
    _require_active(work_order)
    item = RefurbishmentItem.objects.create(work_order=work_order, created_by=actor, **fields)
    log_action(
        AuditAction.REFURBISHMENT_ITEM_CREATED,
        request=request,
        user=actor,
        entity=item,
        entity_type="work_order_item",
        description=f"Added {item.quantity} x {item.item_name} to {work_order.reference}.",
        new_values={"work_order": work_order.reference, **_snapshot(item, ITEM_FIELDS),
                    "total_cost_rwf": item.total_cost_rwf},
    )
    return item


@transaction.atomic
def update_item(item, *, actor, changes, request=None):
    unknown = set(changes) - set(ITEM_FIELDS)
    if unknown:
        raise ValidationError({field: "This field cannot be edited." for field in unknown})
    work_order = _lock(item.work_order)
    _require_active(work_order)
    item = RefurbishmentItem.objects.select_for_update().get(pk=item.pk)

    fields = [*ITEM_FIELDS, "total_cost_rwf"]
    before = _snapshot(item, fields)
    for field, value in changes.items():
        setattr(item, field, value)
    item.save()
    after = _snapshot(item, fields)
    changed = _changed(before, after)
    if changed:
        log_action(
            AuditAction.REFURBISHMENT_ITEM_UPDATED,
            request=request,
            user=actor,
            entity=item,
            entity_type="work_order_item",
            description=f"Updated part {item.item_name} on {work_order.reference}: {', '.join(changed)}.",
            previous_values={f: before[f] for f in changed},
            new_values={f: after[f] for f in changed},
        )
    return item
