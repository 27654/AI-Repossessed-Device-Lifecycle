"""AI decision-support services: generate a recommendation, record the human decision and feedback.

The rule engine (ai_engine.rules) only recommends. The device moves on only
when a user with `ai.decide` records a final decision, and then through
devices.services.transition_device with the HUMAN decision as the source.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from assessments.models import Assessment, AssessmentStatus
from audit.models import AuditAction
from audit.services import log_action
from devices.models import DeviceStatus
from devices.services import transition_device

from . import rules
from .models import AIFeedback, AIRecommendation, Recommendation

# The lifecycle status each final decision moves the device to.
DECISION_TO_STATUS = {
    Recommendation.REFURBISH: DeviceStatus.REFURBISHING,
    Recommendation.READY_FOR_DISPOSITION: DeviceStatus.READY_FOR_DISPOSITION,
    Recommendation.UNABLE_TO_REPAIR: DeviceStatus.UNABLE_TO_REPAIR,
}


def inputs_from_assessment(assessment):
    return rules.AssessmentInputs(
        functional_status=assessment.functional_status,
        physical_condition=assessment.physical_condition,
        screen_condition=assessment.screen_condition,
        battery_condition=assessment.battery_condition,
        cosmetic_condition=assessment.cosmetic_condition,
        accessories_condition=assessment.accessories_condition,
        defects=tuple(assessment.defects),
        estimated_repair_cost_rwf=assessment.estimated_repair_cost_rwf,
        estimated_market_value_rwf=assessment.estimated_market_value_rwf,
    )


@transaction.atomic
def generate_recommendation(assessment, *, actor, request=None):
    """Run the rules on a submitted assessment. Returns (recommendation, created).

    A submitted assessment never changes and the rules are deterministic, so a
    second request returns the existing recommendation instead of a new one.
    The device is not touched.
    """
    assessment = Assessment.objects.select_for_update().select_related("device").get(pk=assessment.pk)
    if assessment.status != AssessmentStatus.SUBMITTED:
        raise ValidationError({"detail": "Submit the assessment before requesting an AI recommendation."})
    existing = AIRecommendation.objects.filter(assessment=assessment).first()
    if existing is not None:
        return existing, False

    result = rules.evaluate(inputs_from_assessment(assessment))
    recommendation = AIRecommendation.objects.create(
        assessment=assessment,
        recommendation=result.recommendation,
        score=result.score,
        confidence=Decimal(str(result.confidence)),
        reasons=result.reasons,
        factors=result.factors,
        rule=result.rule,
        rule_version=result.rule_version,
        requested_by=actor,
    )
    log_action(
        AuditAction.AI_RECOMMENDATION_GENERATED,
        request=request,
        user=actor,
        entity=recommendation,
        entity_type="ai_recommendation",
        description=f"AI recommended {recommendation.get_recommendation_display()} for {assessment.reference} "
        f"({assessment.device.device_code}).",
        new_values={
            "assessment": assessment.reference,
            "device_code": assessment.device.device_code,
            "recommendation": result.recommendation,
            "score": result.score,
            "confidence": result.confidence,
            "rule": result.rule,
            "rule_version": result.rule_version,
        },
    )
    return recommendation, True


@transaction.atomic
def record_decision(assessment, *, actor, final_decision, reason="", request=None):
    """Record the human final decision and move the device accordingly.

    The decision may differ from the AI recommendation (an override); a
    reason is then required. The AI recommendation itself is never changed.
    """
    if final_decision not in Recommendation.values:
        raise ValidationError({"final_decision": f"Unknown decision '{final_decision}'."})
    reason = (reason or "").strip()

    recommendation = (
        AIRecommendation.objects.select_for_update()
        .select_related("assessment__device")
        .filter(assessment_id=assessment.pk)
        .first()
    )
    if recommendation is None:
        raise ValidationError({"detail": "Request the AI recommendation before making the final decision."})
    if recommendation.is_decided:
        raise ValidationError({"detail": "A final decision has already been recorded for this assessment."})
    overridden = final_decision != recommendation.recommendation
    if overridden and not reason:
        raise ValidationError({"reason": "Explain why you are overriding the AI recommendation."})

    device = recommendation.assessment.device
    if device.status != DeviceStatus.ASSESSED:
        raise ValidationError(
            {"detail": f"A final decision can only be made for an Assessed device. This device is "
             f"{device.get_status_display()}."}
        )

    recommendation.final_decision = final_decision
    recommendation.final_decision_by = actor
    recommendation.final_decision_at = timezone.now()
    recommendation.final_decision_reason = reason
    recommendation.save(
        update_fields=["final_decision", "final_decision_by", "final_decision_at", "final_decision_reason"]
    )

    label = Recommendation(final_decision).label
    log_action(
        AuditAction.AI_DECISION_MADE,
        request=request,
        user=actor,
        entity=recommendation,
        entity_type="ai_recommendation",
        description=(
            f"{'Overrode' if overridden else 'Accepted'} AI recommendation for "
            f"{recommendation.assessment.reference} ({device.device_code}): final decision {label}."
        ),
        previous_values={"final_decision": None, "ai_recommendation": recommendation.recommendation},
        new_values={
            "final_decision": final_decision,
            "outcome": recommendation.decision_outcome,
            "reason": reason,
            "assessment": recommendation.assessment.reference,
            "device_code": device.device_code,
        },
    )
    # The HUMAN decision moves the device; the source is the decision, never the AI.
    history_reason = f"Final decision on {recommendation.assessment.reference}: {label}. " + (
        f"Overrides AI recommendation ({recommendation.get_recommendation_display()}): {reason}"
        if overridden
        else "AI recommendation accepted."
    )
    transition_device(
        device,
        DECISION_TO_STATUS[final_decision],
        actor=actor,
        # Status history holds 255 characters; the full reason is on the decision and in the audit log.
        reason=history_reason[:255],
        source_type="assessment_decision",
        source_id=recommendation.pk,
        request=request,
    )
    return recommendation


@transaction.atomic
def record_feedback(assessment, *, actor, verdict, comment="", request=None):
    """Record one user's verdict on the AI recommendation (accept / override) with an optional comment."""
    recommendation = AIRecommendation.objects.filter(assessment_id=assessment.pk).first()
    if recommendation is None:
        raise ValidationError({"detail": "There is no AI recommendation to give feedback on yet."})
    if AIFeedback.objects.filter(recommendation=recommendation, user=actor).exists():
        raise ValidationError({"detail": "You have already given feedback on this recommendation."})
    try:
        with transaction.atomic():
            feedback = AIFeedback.objects.create(
                recommendation=recommendation, user=actor, verdict=verdict, comment=(comment or "").strip()
            )
    except IntegrityError as exc:
        raise ValidationError({"detail": "You have already given feedback on this recommendation."}) from exc

    log_action(
        AuditAction.AI_FEEDBACK_RECORDED,
        request=request,
        user=actor,
        entity=recommendation,
        entity_type="ai_recommendation",
        description=f"Feedback on AI recommendation for {assessment.reference}: {feedback.get_verdict_display()}.",
        new_values={"verdict": verdict, "comment": feedback.comment, "ai_recommendation": recommendation.recommendation},
    )
    return feedback
