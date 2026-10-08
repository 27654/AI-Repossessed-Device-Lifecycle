from django.conf import settings
from django.db import connection, models
from django.db.models import F, Q
from django.utils import timezone

from devices.models import Device

WORK_ORDER_REFERENCE_SEQUENCE = "refurbishment_workorder_reference_seq"


class WorkOrderStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


ACTIVE_WORK_ORDER_STATUSES = (WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS)


class WorkOrderOutcome(models.TextChoices):
    """How a COMPLETED work order ended."""

    REPAIRED = "REPAIRED", "Repaired"
    UNABLE_TO_REPAIR = "UNABLE_TO_REPAIR", "Unable to repair"


class StepType(models.TextChoices):
    DIAGNOSIS = "DIAGNOSIS", "Diagnosis"
    CLEANING = "CLEANING", "Cleaning"
    SCREEN_REPAIR = "SCREEN_REPAIR", "Screen repair"
    BATTERY_REPLACEMENT = "BATTERY_REPLACEMENT", "Battery replacement"
    SOFTWARE_RESET = "SOFTWARE_RESET", "Software reset"
    SOFTWARE_REPAIR = "SOFTWARE_REPAIR", "Software repair"
    HOUSING_REPAIR = "HOUSING_REPAIR", "Housing repair"
    PORT_REPAIR = "PORT_REPAIR", "Port repair"
    FUNCTIONAL_TEST = "FUNCTIONAL_TEST", "Functional test"
    QUALITY_CHECK = "QUALITY_CHECK", "Quality check"
    OTHER = "OTHER", "Other"


# Checks that must be COMPLETED (not skipped) before a device can be declared repaired.
REQUIRED_CHECK_TYPES = (StepType.FUNCTIONAL_TEST, StepType.QUALITY_CHECK)


class StepStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    SKIPPED = "SKIPPED", "Skipped"


FINISHED_STEP_STATUSES = (StepStatus.COMPLETED, StepStatus.SKIPPED)


class RefurbishmentWorkOrder(models.Model):
    """A refurbishment job for a device in REFURBISHING.

    OPEN (planned) -> IN_PROGRESS (started) -> COMPLETED (outcome REPAIRED or
    UNABLE_TO_REPAIR) or CANCELLED. Completing moves the device on through
    devices.services.transition_device; cancelling leaves it in REFURBISHING
    so a new work order can be opened. Closed work orders are history.
    """

    reference = models.CharField(max_length=20, unique=True, editable=False)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="work_orders")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders_assigned"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(
        max_length=20, choices=WorkOrderStatus.choices, default=WorkOrderStatus.OPEN, editable=False, db_index=True
    )
    outcome = models.CharField(max_length=20, choices=WorkOrderOutcome.choices, blank=True, editable=False)

    diagnosis = models.TextField(blank=True)
    work_summary = models.TextField(blank=True)
    # Whole Rwandan francs.
    estimated_cost_rwf = models.PositiveBigIntegerField(default=0)
    labour_cost_rwf = models.PositiveBigIntegerField(null=True, blank=True)
    # Frozen at closure: parts total (sum of items) + labour.
    actual_cost_rwf = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    # Why the work order was closed as Unable to repair or Cancelled.
    closure_reason = models.TextField(blank=True, editable=False)

    started_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=WorkOrderStatus.values), name="workorder_status_valid"),
            models.CheckConstraint(
                condition=Q(outcome="") | Q(outcome__in=WorkOrderOutcome.values), name="workorder_outcome_valid"
            ),
            # Only a COMPLETED work order has an outcome, and then it has cost, time and who.
            models.CheckConstraint(
                condition=(~Q(status=WorkOrderStatus.COMPLETED) & Q(outcome=""))
                | (
                    Q(status=WorkOrderStatus.COMPLETED)
                    & ~Q(outcome="")
                    & Q(actual_cost_rwf__isnull=False)
                    & Q(completed_at__isnull=False)
                    & Q(completed_by__isnull=False)
                ),
                name="workorder_completed_is_complete",
            ),
            # Unable to repair and cancellation always record why.
            models.CheckConstraint(
                condition=~(Q(outcome=WorkOrderOutcome.UNABLE_TO_REPAIR) | Q(status=WorkOrderStatus.CANCELLED))
                | ~Q(closure_reason=""),
                name="workorder_closure_has_reason",
            ),
            # A repaired device has a work summary and a labour cost.
            models.CheckConstraint(
                condition=~Q(outcome=WorkOrderOutcome.REPAIRED)
                | (~Q(work_summary="") & Q(labour_cost_rwf__isnull=False)),
                name="workorder_repaired_has_summary_and_labour",
            ),
            models.CheckConstraint(
                condition=Q(started_at__isnull=True) | Q(completed_at__isnull=True) | Q(completed_at__gte=F("started_at")),
                name="workorder_completed_after_started",
            ),
            # One active (open or in progress) work order per device.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status__in=ACTIVE_WORK_ORDER_STATUSES),
                name="workorder_one_active_per_device",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.device_id})"

    @property
    def is_active(self):
        return self.status in ACTIVE_WORK_ORDER_STATUSES

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._next_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_reference():
        # A database sequence gives unique numbers even under concurrent inserts.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [WORK_ORDER_REFERENCE_SEQUENCE])
            number = cursor.fetchone()[0]
        return f"REF-{timezone.localdate().year}-{number:05d}"


class RefurbishmentStep(models.Model):
    """One piece of work or check on a work order.

    PENDING -> IN_PROGRESS -> COMPLETED, or PENDING/IN_PROGRESS -> SKIPPED (with
    a reason in `notes`). COMPLETED and SKIPPED are final.
    """

    work_order = models.ForeignKey(RefurbishmentWorkOrder, on_delete=models.PROTECT, related_name="steps")
    step_type = models.CharField(max_length=30, choices=StepType.choices)
    description = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=StepStatus.choices, default=StepStatus.PENDING, editable=False)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(step_type__in=StepType.values), name="step_type_valid"),
            models.CheckConstraint(condition=Q(status__in=StepStatus.values), name="step_status_valid"),
            # Timestamps follow the status.
            models.CheckConstraint(
                condition=(Q(status=StepStatus.PENDING) & Q(started_at__isnull=True) & Q(completed_at__isnull=True))
                | (Q(status=StepStatus.IN_PROGRESS) & Q(started_at__isnull=False) & Q(completed_at__isnull=True))
                | (
                    Q(status=StepStatus.COMPLETED)
                    & Q(started_at__isnull=False)
                    & Q(completed_at__isnull=False)
                    & Q(completed_at__gte=F("started_at"))
                    & Q(performed_by__isnull=False)
                )
                | (Q(status=StepStatus.SKIPPED) & Q(completed_at__isnull=False)),
                name="step_timestamps_match_status",
            ),
            models.CheckConstraint(
                condition=~Q(status=StepStatus.SKIPPED) | ~Q(notes=""), name="step_skipped_has_reason"
            ),
        ]

    def __str__(self):
        return f"{self.work_order_id}: {self.step_type} ({self.status})"

    @property
    def is_finished(self):
        return self.status in FINISHED_STEP_STATUSES


class RefurbishmentItem(models.Model):
    """A part or material used. total_cost_rwf = quantity x unit_cost_rwf (enforced by the database)."""

    work_order = models.ForeignKey(RefurbishmentWorkOrder, on_delete=models.PROTECT, related_name="items")
    item_name = models.CharField(max_length=120)
    part_number = models.CharField(max_length=60, blank=True)
    quantity = models.PositiveIntegerField()
    unit_cost_rwf = models.PositiveBigIntegerField()
    total_cost_rwf = models.PositiveBigIntegerField(editable=False)
    supplier = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="item_quantity_positive"),
            models.CheckConstraint(
                condition=Q(total_cost_rwf=F("quantity") * F("unit_cost_rwf")), name="item_total_is_quantity_x_unit"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.item_name}"

    def save(self, *args, **kwargs):
        self.total_cost_rwf = self.quantity * self.unit_cost_rwf
        super().save(*args, **kwargs)
