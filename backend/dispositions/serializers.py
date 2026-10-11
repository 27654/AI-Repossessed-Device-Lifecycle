from rest_framework import serializers

from devices.models import Device
from devices.serializers import AttachmentSerializer, DeviceLabelField, UserLabelField
from devices.validators import CUSTOMER_REF_PATTERN

from .models import Disposition

# Upper bound for a sale price typed by hand, to catch typing errors (100 million RWF).
MAX_PRICE_RWF = 100_000_000


def _pseudonymous_reference(value, what):
    """Buyers and recipients are recorded by reference only (no names or ID numbers)."""
    value = value.strip()
    if value and not CUSTOMER_REF_PATTERN.match(value):
        raise serializers.ValidationError(
            f"Use a {what} reference only (3-60 letters, digits, '-', '_' or '/'). "
            "Do not enter names or ID numbers."
        )
    return value


class DispositionSerializer(serializers.ModelSerializer):
    """Create and update draft dispositions. Status and confirmation are owned by dispositions.services."""

    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    device_summary = DeviceLabelField(source="device", read_only=True)
    responsible_user = UserLabelField(read_only=True)
    confirmed_by = UserLabelField(read_only=True)
    disposition_type_label = serializers.CharField(source="get_disposition_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    sale_price_rwf = serializers.IntegerField(min_value=0, max_value=MAX_PRICE_RWF, required=False, allow_null=True)
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Disposition
        fields = [
            "id",
            "reference",
            "device",
            "device_summary",
            "disposition_type",
            "disposition_type_label",
            "status",
            "status_label",
            "disposition_date",
            "responsible_user",
            "destination",
            "recipient_reference",
            "sale_price_rwf",
            "buyer_reference",
            "notes",
            "confirmed_by",
            "confirmed_at",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["reference", "status", "confirmed_at", "created_at", "updated_at"]

    def validate_buyer_reference(self, value):
        return _pseudonymous_reference(value, "buyer")

    def validate_recipient_reference(self, value):
        return _pseudonymous_reference(value, "recipient")

    def validate_destination(self, value):
        return value.strip()

    def validate(self, attrs):
        if self.instance is not None and "device" in attrs and attrs["device"].pk != self.instance.device_id:
            raise serializers.ValidationError({"device": "The device of a disposition cannot be changed."})
        if self.instance is not None:
            attrs.pop("device", None)
        return attrs
