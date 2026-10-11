from django.conf import settings
from django.db import connection, models
from django.db.models import Q
from django.utils import timezone

from devices.models import Device, DeviceStatus

DISPOSITION_REFERENCE_SEQUENCE = "dispositions_disposition_reference_seq"


class DispositionType(models.TextChoices):
    REALLOCATION = "REALLOCATION", "Reallocation"
    RESALE = "RESALE", "Resale"


class DispositionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    CONFIRMED = "CONFIRMED", "Confirmed"


# The lifecycle status a confirmed disposition moves the device to.
DEVICE_STATUS_FOR_TYPE = {
    DispositionType.REALLOCATION: DeviceStatus.REALLOCATED,
    DispositionType.RESALE: DeviceStatus.RESOLD,
}


class Disposition(models.Model):
    """The final reallocation or resale of a device that is Ready for disposition.

    A Draft is edited by a Reallocation/Sales Officer. Confirming it is final:
    the record becomes immutable and the device moves to REALLOCATED or RESOLD
    through devices.services.transition_device.

    People are recorded only by pseudonymous references (buyer_reference,
    recipient_reference), never by name or identity document.
    """

    reference = models.CharField(max_length=20, unique=True, editable=False)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="dispositions")
    disposition_type = models.CharField(max_length=20, choices=DispositionType.choices)
    status = models.CharField(
        max_length=20, choices=DispositionStatus.choices, default=DispositionStatus.DRAFT, editable=False, db_index=True
    )
    disposition_date = models.DateField(default=timezone.localdate, db_index=True)
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispositions_responsible"
    )

    # Reallocation: where the device goes (department, branch, partner) and, optionally, to whom.
    destination = models.CharField(max_length=150, blank=True)
    recipient_reference = models.CharField(max_length=60, blank=True)
    # Resale: the price and a pseudonymous buyer reference.
    sale_price_rwf = models.PositiveBigIntegerField(null=True, blank=True)
    buyer_reference = models.CharField(max_length=60, blank=True)

    notes = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(disposition_type__in=DispositionType.values), name="disposition_type_valid"
            ),
            models.CheckConstraint(condition=Q(status__in=DispositionStatus.values), name="disposition_status_valid"),
            # Fields match the type: a resale has a positive price and a buyer and no destination;
            # a reallocation has a destination and no price or buyer.
            models.CheckConstraint(
                condition=(
                    Q(disposition_type=DispositionType.RESALE)
                    & Q(sale_price_rwf__gt=0)
                    & ~Q(buyer_reference="")
                    & Q(destination="")
                    & Q(recipient_reference="")
                )
                | (
                    Q(disposition_type=DispositionType.REALLOCATION)
                    & ~Q(destination="")
                    & Q(sale_price_rwf__isnull=True)
                    & Q(buyer_reference="")
                ),
                name="disposition_fields_match_type",
            ),
            models.CheckConstraint(
                condition=Q(status=DispositionStatus.DRAFT, confirmed_by__isnull=True, confirmed_at__isnull=True)
                | Q(status=DispositionStatus.CONFIRMED, confirmed_by__isnull=False, confirmed_at__isnull=False),
                name="disposition_confirmation_complete",
            ),
            # One draft at a time, and a device is disposed of at most once.
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status=DispositionStatus.DRAFT),
                name="disposition_one_draft_per_device",
            ),
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(status=DispositionStatus.CONFIRMED),
                name="disposition_one_confirmed_per_device",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.device_id})"

    @property
    def is_draft(self):
        return self.status == DispositionStatus.DRAFT

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._next_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_reference():
        # A database sequence gives unique numbers even under concurrent inserts.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [DISPOSITION_REFERENCE_SEQUENCE])
            number = cursor.fetchone()[0]
        return f"DSP-{timezone.localdate().year}-{number:05d}"
