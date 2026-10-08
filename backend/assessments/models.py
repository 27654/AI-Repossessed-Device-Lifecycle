from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import connection, models
from django.db.models import Q
from django.utils import timezone

from devices.models import Device

ASSESSMENT_REFERENCE_SEQUENCE = "assessments_assessment_reference_seq"


class AssessmentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"


class PhysicalCondition(models.TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    POOR = "POOR", "Poor"
    CRITICAL = "CRITICAL", "Critical"


class CosmeticCondition(models.TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    POOR = "POOR", "Poor"


class ScreenCondition(models.TextChoices):
    INTACT = "INTACT", "Intact"
    MINOR_DAMAGE = "MINOR_DAMAGE", "Minor damage"
    MAJOR_DAMAGE = "MAJOR_DAMAGE", "Major damage"
    BROKEN = "BROKEN", "Broken"


class BatteryCondition(models.TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    POOR = "POOR", "Poor"
    FAILED = "FAILED", "Failed"


class FunctionalStatus(models.TextChoices):
    FULLY_FUNCTIONAL = "FULLY_FUNCTIONAL", "Fully functional"
    PARTIALLY_FUNCTIONAL = "PARTIALLY_FUNCTIONAL", "Partially functional"
    NON_FUNCTIONAL = "NON_FUNCTIONAL", "Non-functional"


class AccessoriesCondition(models.TextChoices):
    COMPLETE = "COMPLETE", "Complete"
    PARTIAL = "PARTIAL", "Partial"
    NONE = "NONE", "None"


class Defect(models.TextChoices):
    """Specific faults found. A checklist, so findings are comparable across devices."""

    CAMERA_FAULT = "CAMERA_FAULT", "Camera fault"
    CHARGING_PORT_FAULT = "CHARGING_PORT_FAULT", "Charging port fault"
    SPEAKER_OR_MICROPHONE_FAULT = "SPEAKER_OR_MICROPHONE_FAULT", "Speaker or microphone fault"
    BUTTON_FAULT = "BUTTON_FAULT", "Button fault"
    NETWORK_OR_SIM_FAULT = "NETWORK_OR_SIM_FAULT", "Network or SIM fault"
    SOFTWARE_ISSUE = "SOFTWARE_ISSUE", "Software issue"
    ACCOUNT_OR_DEVICE_LOCK = "ACCOUNT_OR_DEVICE_LOCK", "Account or device lock"
    WATER_DAMAGE = "WATER_DAMAGE", "Water damage"
    HOUSING_DAMAGE = "HOUSING_DAMAGE", "Housing or back cover damage"
    OTHER = "OTHER", "Other (describe in notes)"


# Fields that must be filled in before an assessment can be submitted.
REQUIRED_FOR_SUBMISSION = [
    "physical_condition",
    "cosmetic_condition",
    "screen_condition",
    "battery_condition",
    "functional_status",
    "accessories_condition",
    "estimated_repair_cost_rwf",
    "estimated_market_value_rwf",
]


def _choice_check(field, choices):
    return models.CheckConstraint(
        condition=Q(**{field: ""}) | Q(**{f"{field}__in": choices.values}),
        name=f"assessment_{field}_valid",
    )


class Assessment(models.Model):
    """A structured condition assessment of a recovered device.

    A Draft is edited by the assessor. Submitting it makes it immutable and
    moves the device RECOVERED -> ASSESSED through devices.services.transition_device.
    Condition fields may be blank only while the assessment is a Draft.
    """

    reference = models.CharField(max_length=20, unique=True, editable=False)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="assessments")
    assessor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assessments")
    assessment_date = models.DateField(default=timezone.localdate)

    physical_condition = models.CharField(max_length=20, choices=PhysicalCondition.choices, blank=True)
    cosmetic_condition = models.CharField(max_length=20, choices=CosmeticCondition.choices, blank=True)
    screen_condition = models.CharField(max_length=20, choices=ScreenCondition.choices, blank=True)
    battery_condition = models.CharField(max_length=20, choices=BatteryCondition.choices, blank=True)
    functional_status = models.CharField(max_length=30, choices=FunctionalStatus.choices, blank=True)
    accessories_condition = models.CharField(max_length=20, choices=AccessoriesCondition.choices, blank=True)
    defects = ArrayField(models.CharField(max_length=40, choices=Defect.choices), default=list, blank=True)
    assessment_notes = models.TextField(blank=True)

    # Whole Rwandan francs. No decimals: RWF has no minor unit in practice.
    estimated_repair_cost_rwf = models.PositiveBigIntegerField(null=True, blank=True)
    estimated_market_value_rwf = models.PositiveBigIntegerField(null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=AssessmentStatus.choices, default=AssessmentStatus.DRAFT, editable=False
    )
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=AssessmentStatus.values), name="assessment_status_valid"),
            _choice_check("physical_condition", PhysicalCondition),
            _choice_check("cosmetic_condition", CosmeticCondition),
            _choice_check("screen_condition", ScreenCondition),
            _choice_check("battery_condition", BatteryCondition),
            _choice_check("functional_status", FunctionalStatus),
            _choice_check("accessories_condition", AccessoriesCondition),
            models.CheckConstraint(
                condition=Q(defects__contained_by=Defect.values), name="assessment_defects_valid"
            ),
            # A submitted assessment is complete: every required field is set.
            models.CheckConstraint(
                condition=Q(status=AssessmentStatus.DRAFT)
                | (
                    ~Q(physical_condition="")
                    & ~Q(cosmetic_condition="")
                    & ~Q(screen_condition="")
                    & ~Q(battery_condition="")
                    & ~Q(functional_status="")
                    & ~Q(accessories_condition="")
                    & Q(estimated_repair_cost_rwf__isnull=False)
                    & Q(estimated_market_value_rwf__gt=0)
                    & Q(submitted_at__isnull=False)
                ),
                name="assessment_submitted_is_complete",
            ),
            # One draft at a time per device.
            models.UniqueConstraint(
                fields=["device"], condition=Q(status=AssessmentStatus.DRAFT), name="assessment_one_draft_per_device"
            ),
            # One active submitted assessment per device.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status=AssessmentStatus.SUBMITTED),
                name="assessment_one_submitted_per_device",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.device_id})"

    @property
    def is_draft(self):
        return self.status == AssessmentStatus.DRAFT

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._next_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_reference():
        # A database sequence gives unique numbers even under concurrent inserts.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [ASSESSMENT_REFERENCE_SEQUENCE])
            number = cursor.fetchone()[0]
        return f"ASS-{timezone.localdate().year}-{number:05d}"
