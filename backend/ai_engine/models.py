from django.conf import settings
from django.db import models
from django.db.models import Q

from assessments.models import Assessment

from . import rules


class Recommendation(models.TextChoices):
    REFURBISH = rules.REFURBISH, "Refurbish"
    READY_FOR_DISPOSITION = rules.READY_FOR_DISPOSITION, "Ready for disposition"
    UNABLE_TO_REPAIR = rules.UNABLE_TO_REPAIR, "Unable to repair"


class AIRecommendation(models.Model):
    """The rule engine's recommendation for one submitted assessment, and the human decision on it.

    The AI part (recommendation .. generated_at) is written once and never
    changed. The human part (final_decision ..) is written once by a user with
    `ai.decide`. They are separate fields so an override never overwrites what
    the AI recommended. A PostgreSQL trigger enforces both rules.
    """

    assessment = models.OneToOneField(Assessment, on_delete=models.PROTECT, related_name="ai_recommendation")

    # --- AI output (immutable) ---
    recommendation = models.CharField(max_length=30, choices=Recommendation.choices)
    score = models.PositiveSmallIntegerField()
    confidence = models.DecimalField(max_digits=3, decimal_places=2)
    reasons = models.JSONField(default=list)
    factors = models.JSONField(default=dict)
    rule = models.CharField(max_length=40, help_text="Which rule produced the recommendation.")
    rule_version = models.CharField(max_length=20)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    generated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # --- Human decision (write-once) ---
    final_decision = models.CharField(max_length=30, choices=Recommendation.choices, blank=True)
    final_decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    final_decision_at = models.DateTimeField(null=True, blank=True)
    final_decision_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-generated_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(recommendation__in=Recommendation.values), name="ai_recommendation_valid"
            ),
            models.CheckConstraint(condition=Q(score__lte=100), name="ai_score_0_100"),
            models.CheckConstraint(condition=Q(confidence__gte=0) & Q(confidence__lte=1), name="ai_confidence_0_1"),
            models.CheckConstraint(
                condition=Q(final_decision="") | Q(final_decision__in=Recommendation.values),
                name="ai_final_decision_valid",
            ),
            # A decision records who and when; an override records why.
            models.CheckConstraint(
                condition=Q(final_decision="", final_decision_by__isnull=True, final_decision_at__isnull=True)
                | (~Q(final_decision="") & Q(final_decision_by__isnull=False) & Q(final_decision_at__isnull=False)),
                name="ai_final_decision_complete",
            ),
            models.CheckConstraint(
                condition=Q(final_decision="")
                | Q(final_decision=models.F("recommendation"))
                | ~Q(final_decision_reason=""),
                name="ai_override_has_reason",
            ),
        ]

    def __str__(self):
        return f"{self.assessment_id}: {self.recommendation}"

    @property
    def is_decided(self):
        return bool(self.final_decision)

    @property
    def decision_outcome(self):
        """ACCEPTED or OVERRIDDEN once decided, else None."""
        if not self.final_decision:
            return None
        return "ACCEPTED" if self.final_decision == self.recommendation else "OVERRIDDEN"


class FeedbackVerdict(models.TextChoices):
    ACCEPTED = "ACCEPTED", "Accepted"
    OVERRIDDEN = "OVERRIDDEN", "Overridden"


class AIFeedback(models.Model):
    """A staff member's view of a recommendation: would they accept or override it, and why.

    One per user per recommendation; kept as given (no edits) for the AI
    effectiveness record.
    """

    recommendation = models.ForeignKey(AIRecommendation, on_delete=models.PROTECT, related_name="feedback")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    verdict = models.CharField(max_length=20, choices=FeedbackVerdict.choices)
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["recommendation", "user"], name="ai_feedback_one_per_user"),
            models.CheckConstraint(condition=Q(verdict__in=FeedbackVerdict.values), name="ai_feedback_verdict_valid"),
        ]

    def __str__(self):
        return f"{self.recommendation_id} {self.verdict} by {self.user_id}"
