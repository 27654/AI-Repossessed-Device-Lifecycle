from django.conf import settings
from django.db import connection, models
from django.db.models import Q
from django.utils import timezone

from devices.models import Device

RECOVERY_REFERENCE_SEQUENCE = "recovery_recovery_reference_seq"


class RecoveryStatus(models.TextChoices):
    """State of the recovery record itself (not of the device)."""

    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"


class RecoveryOutcome(models.TextChoices):
    RECOVERED = "RECOVERED", "Recovered"
    RECOVERED_WITH_ISSUES = "RECOVERED_WITH_ISSUES", "Recovered with issues"
    NOT_RECOVERED = "NOT_RECOVERED", "Not recovered"


# Outcomes that put the device in Yellow's hands, so completion moves it to RECOVERED.
SUCCESSFUL_OUTCOMES = (RecoveryOutcome.RECOVERED, RecoveryOutcome.RECOVERED_WITH_ISSUES)


class RecoveryMethod(models.TextChoices):
    FIELD_COLLECTION = "FIELD_COLLECTION", "Field collection"
    CUSTOMER_SURRENDER = "CUSTOMER_SURRENDER", "Customer surrender"
    AGENT_DROP_OFF = "AGENT_DROP_OFF", "Agent drop-off"
    OTHER = "OTHER", "Other"


class Recovery(models.Model):
    """One attempt to repossess a device, kept as historical evidence.

    A record is edited while In progress. Completing it locks it; a successful
    outcome moves the device IN_RECOVERY -> RECOVERED through
    devices.services.transition_device. A Not recovered attempt leaves the
    device In recovery so a new attempt can be recorded.
    """

    reference = models.CharField(max_length=20, unique=True, editable=False)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="recoveries")
    recovery_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recoveries_recorded"
    )
    recovered_at = models.DateTimeField(help_text="When the device was recovered, or the attempt was made.")
    recovery_location = models.CharField(max_length=200)
    recovery_method = models.CharField(max_length=30, choices=RecoveryMethod.choices)
    outcome = models.CharField(max_length=30, choices=RecoveryOutcome.choices, blank=True)
    condition_notes = models.TextField(blank=True, help_text="Visible condition of the device at collection.")
    notes = models.TextField(blank=True, help_text="Recovery notes: issues, or why the device was not recovered.")

    status = models.CharField(
        max_length=20, choices=RecoveryStatus.choices, default=RecoveryStatus.IN_PROGRESS, editable=False
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "recoveries"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=RecoveryStatus.values), name="recovery_status_valid"),
            models.CheckConstraint(
                condition=Q(outcome="") | Q(outcome__in=RecoveryOutcome.values), name="recovery_outcome_valid"
            ),
            # A completed record always has its outcome and who/when completed it.
            models.CheckConstraint(
                condition=Q(status=RecoveryStatus.IN_PROGRESS)
                | (~Q(outcome="") & Q(completed_by__isnull=False) & Q(completed_at__isnull=False)),
                name="recovery_completed_is_complete",
            ),
            # At most one open attempt per device.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status=RecoveryStatus.IN_PROGRESS),
                name="recovery_one_open_per_device",
            ),
            # A device is successfully recovered at most once.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status=RecoveryStatus.COMPLETED, outcome__in=SUCCESSFUL_OUTCOMES),
                name="recovery_one_success_per_device",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.device_id})"

    @property
    def is_open(self):
        return self.status == RecoveryStatus.IN_PROGRESS

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._next_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_reference():
        # A database sequence gives unique numbers even under concurrent inserts.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [RECOVERY_REFERENCE_SEQUENCE])
            number = cursor.fetchone()[0]
        return f"RCV-{timezone.localdate().year}-{number:05d}"
