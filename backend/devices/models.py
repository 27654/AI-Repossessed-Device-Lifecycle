import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, models
from django.db.models import Q
from django.utils import timezone

from .validators import ALLOWED_FILE_TYPES

DEVICE_CODE_SEQUENCE = "devices_device_code_seq"


class DeviceStatus(models.TextChoices):
    IN_RECOVERY = "IN_RECOVERY", "In recovery"
    RECOVERED = "RECOVERED", "Recovered"
    ASSESSED = "ASSESSED", "Assessed"
    REFURBISHING = "REFURBISHING", "Refurbishing"
    READY_FOR_DISPOSITION = "READY_FOR_DISPOSITION", "Ready for disposition"
    REALLOCATED = "REALLOCATED", "Reallocated"
    RESOLD = "RESOLD", "Resold"
    UNABLE_TO_REPAIR = "UNABLE_TO_REPAIR", "Unable to repair"


# Lifecycle stage shown in the UI, derived from status (docs/architecture.md section 6).
LIFECYCLE_STAGES = {
    DeviceStatus.IN_RECOVERY: "Recovery",
    DeviceStatus.RECOVERED: "Recovery",
    DeviceStatus.ASSESSED: "Condition Assessment",
    DeviceStatus.REFURBISHING: "Refurbishment",
    DeviceStatus.READY_FOR_DISPOSITION: "Reallocation/Resale",
    DeviceStatus.REALLOCATED: "Closed",
    DeviceStatus.RESOLD: "Closed",
    DeviceStatus.UNABLE_TO_REPAIR: "Exception",
}


class DeviceCondition(models.TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    POOR = "POOR", "Poor"


class DeviceType(models.TextChoices):
    SMARTPHONE = "SMARTPHONE", "Smartphone"
    FEATURE_PHONE = "FEATURE_PHONE", "Feature phone"
    TABLET = "TABLET", "Tablet"
    LAPTOP = "LAPTOP", "Laptop"
    TELEVISION = "TELEVISION", "Television"
    SOLAR_HOME_SYSTEM = "SOLAR_HOME_SYSTEM", "Solar home system"
    OTHER = "OTHER", "Other"


class Device(models.Model):
    """One physical repossessed device: the hub of the lifecycle.

    `status` and `current_condition` are cached values written only by
    lifecycle services (devices.services), never directly through the API.
    """

    device_code = models.CharField(max_length=20, unique=True, editable=False)
    imei = models.CharField(
        max_length=15, unique=True, null=True, blank=True,
        error_messages={"unique": "A device with this IMEI already exists."},
    )
    serial_number = models.CharField(
        max_length=80, unique=True, null=True, blank=True,
        error_messages={"unique": "A device with this serial number already exists."},
    )
    make = models.CharField(max_length=60, db_index=True)
    model = models.CharField(max_length=80, db_index=True)
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    color = models.CharField(max_length=40, blank=True)
    storage_capacity_gb = models.PositiveIntegerField(null=True, blank=True)
    operating_system = models.CharField(max_length=60, blank=True)

    status = models.CharField(max_length=30, choices=DeviceStatus.choices, db_index=True, editable=False)
    current_condition = models.CharField(max_length=20, choices=DeviceCondition.choices, null=True, blank=True)
    condition_summary = models.TextField(blank=True)
    current_location = models.CharField(max_length=200, blank=True)

    # Repossession case / acquisition reference and the date the device was recovered.
    recovery_reference = models.CharField(max_length=60, blank=True)
    recovery_date = models.DateField(null=True, blank=True, db_index=True)
    # Pseudonymous Yellow account reference only. Never a name or national ID.
    previous_owner_ref = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="devices_created")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(imei__isnull=False) | Q(serial_number__isnull=False),
                name="device_has_imei_or_serial",
            ),
            models.CheckConstraint(
                condition=Q(imei__isnull=True) | Q(imei__regex=r"^[0-9]{15}$"),
                name="device_imei_15_digits",
            ),
            models.CheckConstraint(condition=Q(status__in=DeviceStatus.values), name="device_status_valid"),
        ]

    def __str__(self):
        return f"{self.device_code} {self.make} {self.model}"

    @property
    def lifecycle_stage(self):
        return LIFECYCLE_STAGES.get(self.status, "")

    def save(self, *args, **kwargs):
        if not self.device_code:
            self.device_code = self._next_device_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_device_code():
        # A database sequence gives unique numbers even under concurrent inserts.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [DEVICE_CODE_SEQUENCE])
            number = cursor.fetchone()[0]
        return f"YRW-{timezone.localdate().year}-{number:05d}"


class DeviceStatusChange(models.Model):
    """One lifecycle transition. Append-only (model guard + PostgreSQL trigger)."""

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="status_changes")
    from_status = models.CharField(max_length=30, choices=DeviceStatus.choices, null=True, blank=True)
    to_status = models.CharField(max_length=30, choices=DeviceStatus.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=255, blank=True)
    # The record that caused the change, e.g. ("recovery", 12). Empty for manual registration.
    source_type = models.CharField(max_length=50, blank=True)
    source_id = models.BigIntegerField(null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.device_id}: {self.from_status or '-'} -> {self.to_status}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Status history cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Status history cannot be deleted.")


def attachment_upload_to(instance, filename):
    """Random storage name; the uploader's file name is kept only in `original_name`."""
    extension = ALLOWED_FILE_TYPES[instance.mime_type][0]
    return f"attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class Attachment(models.Model):
    """Photo or document about a device. Served only through the authenticated download endpoint."""

    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="attachments")
    file = models.FileField(upload_to=attachment_upload_to, max_length=200)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=50, choices=[(t, t) for t in ALLOWED_FILE_TYPES])
    size_bytes = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.original_name
