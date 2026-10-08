from rest_framework import serializers

from devices.models import Device
from devices.serializers import AttachmentSerializer, UserLabelField

from .models import Recovery


class DeviceLabelField(serializers.Field):
    def to_representation(self, device):
        return {
            "id": device.pk,
            "device_code": device.device_code,
            "make": device.make,
            "model": device.model,
            "status": device.status,
            "status_label": device.get_status_display(),
        }


class RecoverySerializer(serializers.ModelSerializer):
    """Create and update recovery records. Status and completion fields are owned by recovery.services."""

    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    device_summary = DeviceLabelField(source="device", read_only=True)
    recovery_officer = UserLabelField(read_only=True)
    completed_by = UserLabelField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    outcome_label = serializers.CharField(source="get_outcome_display", read_only=True)
    recovery_method_label = serializers.CharField(source="get_recovery_method_display", read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Recovery
        fields = [
            "id",
            "reference",
            "device",
            "device_summary",
            "recovery_officer",
            "recovered_at",
            "recovery_location",
            "recovery_method",
            "recovery_method_label",
            "outcome",
            "outcome_label",
            "condition_notes",
            "notes",
            "status",
            "status_label",
            "completed_by",
            "completed_at",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["reference", "status", "completed_at", "created_at", "updated_at"]
        extra_kwargs = {
            "recovery_location": {"trim_whitespace": True},
            "outcome": {"required": False},
        }

    def validate_recovery_location(self, value):
        if not value.strip():
            raise serializers.ValidationError("Enter where the recovery took place.")
        return value

    def validate(self, attrs):
        # The device of a recovery record never changes once it is created.
        if self.instance is not None and "device" in attrs and attrs["device"].pk != self.instance.device_id:
            raise serializers.ValidationError({"device": "The device of a recovery record cannot be changed."})
        if self.instance is not None:
            attrs.pop("device", None)
        return attrs
