from rest_framework import serializers

from accounts.models import User
from devices.models import Device
from devices.serializers import AttachmentSerializer, DeviceLabelField, UserLabelField

from .models import RefurbishmentItem, RefurbishmentStep, RefurbishmentWorkOrder, StepStatus

# Upper bounds for amounts typed by hand, to catch typing errors.
MAX_AMOUNT_RWF = 100_000_000
MAX_QUANTITY = 1_000


def rwf_field(**kwargs):
    return serializers.IntegerField(min_value=0, max_value=MAX_AMOUNT_RWF, **kwargs)


class RefurbishmentStepSerializer(serializers.ModelSerializer):
    step_type_label = serializers.CharField(source="get_step_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    performed_by = UserLabelField(read_only=True)

    class Meta:
        model = RefurbishmentStep
        fields = [
            "id",
            "work_order",
            "step_type",
            "step_type_label",
            "description",
            "status",
            "status_label",
            "performed_by",
            "started_at",
            "completed_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["work_order", "status", "started_at", "completed_at", "created_at", "updated_at"]


class StepUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=StepStatus.choices, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RefurbishmentItemSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)
    unit_cost_rwf = rwf_field()
    created_by = UserLabelField(read_only=True)

    class Meta:
        model = RefurbishmentItem
        fields = [
            "id",
            "work_order",
            "item_name",
            "part_number",
            "quantity",
            "unit_cost_rwf",
            "total_cost_rwf",
            "supplier",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["work_order", "total_cost_rwf", "created_at", "updated_at"]

    def validate_item_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Enter the part or material name.")
        return value.strip()


class AssigneeField(serializers.PrimaryKeyRelatedField):
    """Assignee by user id; shown as {id, full_name}. Eligibility is checked in the service."""

    def to_representation(self, value):
        user = value if isinstance(value, User) else User.objects.get(pk=value.pk)
        return {"id": user.pk, "full_name": user.full_name}

    def use_pk_only_optimization(self):
        return False


class WorkOrderSerializer(serializers.ModelSerializer):
    """Create and edit work orders. Status, outcome, costs at closure and timestamps belong to the services."""

    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    device_summary = DeviceLabelField(source="device", read_only=True)
    assigned_to = AssigneeField(queryset=User.objects.all(), required=False, allow_null=True)
    created_by = UserLabelField(read_only=True)
    completed_by = UserLabelField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    outcome_label = serializers.SerializerMethodField()
    estimated_cost_rwf = rwf_field(required=False)
    labour_cost_rwf = rwf_field(required=False, allow_null=True)
    parts_cost_rwf = serializers.SerializerMethodField()
    total_cost_rwf = serializers.SerializerMethodField()
    steps = RefurbishmentStepSerializer(many=True, read_only=True)
    items = RefurbishmentItemSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = RefurbishmentWorkOrder
        fields = [
            "id",
            "reference",
            "device",
            "device_summary",
            "assigned_to",
            "created_by",
            "status",
            "status_label",
            "outcome",
            "outcome_label",
            "diagnosis",
            "work_summary",
            "estimated_cost_rwf",
            "labour_cost_rwf",
            "parts_cost_rwf",
            "total_cost_rwf",
            "actual_cost_rwf",
            "closure_reason",
            "started_at",
            "completed_at",
            "completed_by",
            "steps",
            "items",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "reference",
            "status",
            "outcome",
            "actual_cost_rwf",
            "closure_reason",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]

    def get_outcome_label(self, work_order):
        return work_order.get_outcome_display() if work_order.outcome else None

    def get_parts_cost_rwf(self, work_order):
        # Items are prefetched by the views; summing in Python avoids a query per row.
        return sum(item.total_cost_rwf for item in work_order.items.all())

    def get_total_cost_rwf(self, work_order):
        """Actual cost once closed; until then parts so far plus labour entered so far."""
        if work_order.actual_cost_rwf is not None:
            return work_order.actual_cost_rwf
        return self.get_parts_cost_rwf(work_order) + (work_order.labour_cost_rwf or 0)

    def validate(self, attrs):
        if self.instance is not None and "device" in attrs and attrs["device"].pk != self.instance.device_id:
            raise serializers.ValidationError({"device": "The device of a work order cannot be changed."})
        if self.instance is not None:
            attrs.pop("device", None)
        else:
            # Only planning fields are set at creation; the summary and labour come later.
            for field in ("work_summary", "labour_cost_rwf"):
                attrs.pop(field, None)
        return attrs


class CompleteSerializer(serializers.Serializer):
    work_summary = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    labour_cost_rwf = rwf_field(required=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, max_length=2000)


class TechnicianSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name"]
