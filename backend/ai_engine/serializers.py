from rest_framework import serializers

from devices.serializers import DeviceLabelField, UserLabelField

from .models import AIFeedback, AIRecommendation, FeedbackVerdict, Recommendation


class AIFeedbackSerializer(serializers.ModelSerializer):
    user = UserLabelField(read_only=True)
    verdict_label = serializers.CharField(source="get_verdict_display", read_only=True)

    class Meta:
        model = AIFeedback
        fields = ["id", "user", "verdict", "verdict_label", "comment", "created_at"]
        read_only_fields = fields


class AIRecommendationSerializer(serializers.ModelSerializer):
    """The AI recommendation and, separately, the human final decision on it."""

    assessment_reference = serializers.CharField(source="assessment.reference", read_only=True)
    device_summary = DeviceLabelField(source="assessment.device", read_only=True)
    recommendation_label = serializers.CharField(source="get_recommendation_display", read_only=True)
    confidence = serializers.FloatField(read_only=True)
    requested_by = UserLabelField(read_only=True)
    final_decision_label = serializers.SerializerMethodField()
    final_decision_by = UserLabelField(read_only=True)
    decision_outcome = serializers.CharField(read_only=True)
    feedback = AIFeedbackSerializer(many=True, read_only=True)
    method = serializers.SerializerMethodField()

    class Meta:
        model = AIRecommendation
        fields = [
            "id",
            "assessment",
            "assessment_reference",
            "device_summary",
            "recommendation",
            "recommendation_label",
            "score",
            "confidence",
            "reasons",
            "factors",
            "rule_version",
            "method",
            "requested_by",
            "generated_at",
            "final_decision",
            "final_decision_label",
            "final_decision_by",
            "final_decision_at",
            "final_decision_reason",
            "decision_outcome",
            "feedback",
        ]
        read_only_fields = fields

    def to_representation(self, recommendation):
        data = super().to_representation(recommendation)
        # No decision yet is null, not an empty string.
        data["final_decision"] = data["final_decision"] or None
        return data

    def get_final_decision_label(self, recommendation):
        return recommendation.get_final_decision_display() if recommendation.final_decision else None

    def get_method(self, recommendation):
        return "Explainable rule-based decision support (not machine learning)"


class DecisionSerializer(serializers.Serializer):
    final_decision = serializers.ChoiceField(choices=Recommendation.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class FeedbackSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=FeedbackVerdict.choices)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)
