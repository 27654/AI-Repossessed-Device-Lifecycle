from rest_framework import serializers

from devices.models import Device
from devices.serializers import AttachmentSerializer, DeviceLabelField, UserLabelField

from .models import Assessment, Defect

# Upper bound for amounts entered by hand, to catch typing errors (100 million RWF).
MAX_AMOUNT_RWF = 100_000_000


class AssessmentSerializer(serializers.ModelSerializer):
    """Create and update Draft assessments. Status and submission are owned by assessments.services."""

    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    device_summary = DeviceLabelField(source="device", read_only=True)
    assessor = UserLabelField(read_only=True)
    defects = serializers.ListField(
        child=serializers.ChoiceField(choices=Defect.choices), required=False, allow_empty=True, max_length=len(Defect)
    )
    defect_labels = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    physical_condition_label = serializers.CharField(source="get_physical_condition_display", read_only=True)
    cosmetic_condition_label = serializers.CharField(source="get_cosmetic_condition_display", read_only=True)
    screen_condition_label = serializers.CharField(source="get_screen_condition_display", read_only=True)
    battery_condition_label = serializers.CharField(source="get_battery_condition_display", read_only=True)
    functional_status_label = serializers.CharField(source="get_functional_status_display", read_only=True)
    accessories_condition_label = serializers.CharField(source="get_accessories_condition_display", read_only=True)
    estimated_repair_cost_rwf = serializers.IntegerField(
        min_value=0, max_value=MAX_AMOUNT_RWF, required=False, allow_null=True
    )
    estimated_market_value_rwf = serializers.IntegerField(
        min_value=0, max_value=MAX_AMOUNT_RWF, required=False, allow_null=True
    )
    attachments = AttachmentSerializer(many=True, read_only=True)
    has_ai_recommendation = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id",
            "reference",
            "device",
            "device_summary",
            "assessor",
            "assessment_date",
            "physical_condition",
            "physical_condition_label",
            "cosmetic_condition",
            "cosmetic_condition_label",
            "screen_condition",
            "screen_condition_label",
            "battery_condition",
            "battery_condition_label",
            "functional_status",
            "functional_status_label",
            "accessories_condition",
            "accessories_condition_label",
            "defects",
            "defect_labels",
            "assessment_notes",
            "estimated_repair_cost_rwf",
            "estimated_market_value_rwf",
            "status",
            "status_label",
            "submitted_at",
            "has_ai_recommendation",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["reference", "status", "submitted_at", "created_at", "updated_at"]

    def get_defect_labels(self, assessment):
        return [Defect(code).label for code in assessment.defects]

    def get_has_ai_recommendation(self, assessment):
        return hasattr(assessment, "ai_recommendation")

    def validate(self, attrs):
        # The device of an assessment never changes once it is created.
        if self.instance is not None and "device" in attrs and attrs["device"].pk != self.instance.device_id:
            raise serializers.ValidationError({"device": "The device of an assessment cannot be changed."})
        if self.instance is not None:
            attrs.pop("device", None)
        return attrs
