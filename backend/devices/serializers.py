from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Attachment, Device, DeviceStatus, DeviceStatusChange
from .services import INITIAL_STATUSES
from .validators import (
    clean_original_name,
    normalize_imei,
    normalize_serial,
    validate_attachment,
    validate_customer_ref,
    validate_imei,
)


def _django_errors(func, value):
    """Run a Django validator and re-raise its errors as DRF validation errors."""
    try:
        return func(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc


class UserLabelField(serializers.Field):
    def to_representation(self, user):
        return {"id": user.pk, "full_name": user.full_name}


class DeviceLabelField(serializers.Field):
    """Short device summary embedded in lifecycle records (recovery, assessment, AI)."""

    def to_representation(self, device):
        return {
            "id": device.pk,
            "device_code": device.device_code,
            "make": device.make,
            "model": device.model,
            "status": device.status,
            "status_label": device.get_status_display(),
        }


class DeviceListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    device_type_label = serializers.CharField(source="get_device_type_display", read_only=True)
    lifecycle_stage = serializers.CharField(read_only=True)

    class Meta:
        model = Device
        fields = [
            "id",
            "device_code",
            "imei",
            "serial_number",
            "make",
            "model",
            "device_type",
            "device_type_label",
            "status",
            "status_label",
            "lifecycle_stage",
            "current_condition",
            "current_location",
            "recovery_date",
            "created_at",
        ]
        read_only_fields = fields


class DeviceSerializer(serializers.ModelSerializer):
    """Create and edit devices. Status and condition are read-only: lifecycle services own them."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    device_type_label = serializers.CharField(source="get_device_type_display", read_only=True)
    lifecycle_stage = serializers.CharField(read_only=True)
    created_by = UserLabelField(read_only=True)
    attachment_count = serializers.IntegerField(source="attachments.count", read_only=True)
    initial_status = serializers.ChoiceField(
        choices=[(s, DeviceStatus(s).label) for s in INITIAL_STATUSES],
        default=DeviceStatus.IN_RECOVERY,
        write_only=True,
    )

    class Meta:
        model = Device
        fields = [
            "id",
            "device_code",
            "imei",
            "serial_number",
            "make",
            "model",
            "device_type",
            "device_type_label",
            "color",
            "storage_capacity_gb",
            "operating_system",
            "status",
            "status_label",
            "lifecycle_stage",
            "initial_status",
            "current_condition",
            "condition_summary",
            "current_location",
            "recovery_reference",
            "recovery_date",
            "previous_owner_ref",
            "notes",
            "created_by",
            "attachment_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["device_code", "status", "current_condition", "created_at", "updated_at"]
        # Uniqueness is checked after normalisation in validate_imei / validate_serial_number.
        # Input limits allow spaces/dashes, which are stripped before the stored 15-digit check.
        extra_kwargs = {
            "imei": {"validators": [], "max_length": 32},
            "serial_number": {"validators": [], "max_length": 100},
        }

    def _unique(self, field, value, message):
        qs = Device.objects.filter(**{field: value})
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(message)

    def validate_imei(self, value):
        value = normalize_imei(value)
        if not value:
            return None
        _django_errors(validate_imei, value)
        self._unique("imei", value, "A device with this IMEI already exists.")
        return value

    def validate_serial_number(self, value):
        value = normalize_serial(value)
        if not value:
            return None
        self._unique("serial_number", value, "A device with this serial number already exists.")
        return value

    def validate_previous_owner_ref(self, value):
        value = value.strip()
        _django_errors(validate_customer_ref, value)
        return value

    def validate_make(self, value):
        return value.strip()

    def validate_model(self, value):
        return value.strip()

    def validate(self, attrs):
        imei = attrs.get("imei", getattr(self.instance, "imei", None))
        serial = attrs.get("serial_number", getattr(self.instance, "serial_number", None))
        if not imei and not serial:
            raise serializers.ValidationError({"imei": "Enter an IMEI or a serial number to identify the device."})
        if self.instance is not None:
            attrs.pop("initial_status", None)
        return attrs


class DeviceStatusChangeSerializer(serializers.ModelSerializer):
    from_status_label = serializers.SerializerMethodField()
    to_status_label = serializers.CharField(source="get_to_status_display", read_only=True)
    changed_by = UserLabelField(read_only=True)

    class Meta:
        model = DeviceStatusChange
        fields = [
            "id",
            "from_status",
            "from_status_label",
            "to_status",
            "to_status_label",
            "changed_by",
            "changed_at",
            "reason",
            "source_type",
            "source_id",
        ]
        read_only_fields = fields

    def get_from_status_label(self, change):
        return change.get_from_status_display() if change.from_status else None


class AttachmentSerializer(serializers.ModelSerializer):
    """Upload and list attachments. The storage path is never returned; files download through the API."""

    file = serializers.FileField(write_only=True)
    uploaded_by = UserLabelField(read_only=True)
    download_url = serializers.SerializerMethodField()
    # Set when the file is evidence for a recovery record; linked only through the recovery endpoint.
    recovery_reference = serializers.CharField(source="recovery.reference", read_only=True, default=None)
    # Set when the file is evidence for an assessment; linked only through the assessment endpoint.
    assessment_reference = serializers.CharField(source="assessment.reference", read_only=True, default=None)
    # Set when the file is evidence for a refurbishment work order.
    refurbishment_reference = serializers.CharField(source="refurbishment.reference", read_only=True, default=None)

    class Meta:
        model = Attachment
        fields = [
            "id",
            "file",
            "original_name",
            "mime_type",
            "size_bytes",
            "description",
            "uploaded_by",
            "created_at",
            "download_url",
            "recovery",
            "recovery_reference",
            "assessment",
            "assessment_reference",
            "refurbishment",
            "refurbishment_reference",
        ]
        read_only_fields = [
            "original_name", "mime_type", "size_bytes", "created_at", "recovery", "assessment", "refurbishment"
        ]

    def validate_file(self, upload):
        self._mime_type = _django_errors(validate_attachment, upload)
        return upload

    def validate(self, attrs):
        attrs["mime_type"] = self._mime_type
        attrs["original_name"] = clean_original_name(attrs["file"].name)
        return attrs

    def get_download_url(self, attachment):
        return f"/api/devices/{attachment.device_id}/attachments/{attachment.pk}/download/"
