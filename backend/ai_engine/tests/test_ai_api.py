from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from ai_engine import rules, services
from ai_engine.models import AIFeedback, AIRecommendation
from assessments.tests.helpers import make_assessment, recovered_device, submitted_assessment
from audit.models import AuditAction, AuditLog
from devices.models import DeviceStatus
from devices.services import transition_device

AI_ROLES = [RoleCode.DEVICE_ASSESSOR, RoleCode.REFURBISHMENT_STAFF, RoleCode.SALES_OFFICER, RoleCode.OPERATIONS_MANAGER]
NO_AI_ROLES = [RoleCode.RECOVERY_OFFICER, RoleCode.SYSTEM_ADMIN]


def ai_url(assessment):
    return reverse("assessment-ai-recommendation", args=[assessment.pk])


def decision_url(assessment):
    return reverse("assessment-decision", args=[assessment.pk])


def feedback_url(assessment):
    return reverse("assessment-ai-feedback", args=[assessment.pk])


class RecommendationTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.assessment = submitted_assessment(assessor=self.assessor)
        self.device = self.assessment.device

    def test_generate_recommendation(self):
        response = self.client.post(ai_url(self.assessment))

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["recommendation"], "REFURBISH")
        self.assertEqual(body["recommendation_label"], "Refurbish")
        self.assertEqual(body["score"], 58)
        self.assertGreater(body["confidence"], 0)
        self.assertLessEqual(body["confidence"], 1)
        self.assertTrue(any("18,000 RWF" in reason for reason in body["reasons"]))
        self.assertEqual(body["rule_version"], rules.RULE_VERSION)
        self.assertIn("rule-based", body["method"])
        self.assertEqual(body["assessment_reference"], self.assessment.reference)
        self.assertEqual(body["requested_by"]["id"], self.assessor.pk)
        self.assertIsNotNone(body["generated_at"])
        self.assertIsNone(body["final_decision"])
        self.assertIsNone(body["decision_outcome"])

    def test_generation_is_audited(self):
        response = self.client.post(ai_url(self.assessment))
        entry = AuditLog.objects.get(action=AuditAction.AI_RECOMMENDATION_GENERATED)
        self.assertEqual(entry.user, self.assessor)
        self.assertEqual((entry.entity_type, entry.entity_id), ("ai_recommendation", str(response.json()["id"])))
        self.assertEqual(entry.new_values["recommendation"], "REFURBISH")
        self.assertEqual(entry.new_values["rule_version"], rules.RULE_VERSION)

    def test_ai_never_changes_device_status(self):
        changes_before = self.device.status_changes.count()
        self.client.post(ai_url(self.assessment))

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.ASSESSED)
        self.assertEqual(self.device.status_changes.count(), changes_before)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DEVICE_STATUS_CHANGED, user=None).exists())

    def test_requires_submitted_assessment(self):
        draft = make_assessment(recovered_device(), self.assessor)
        response = self.client.post(ai_url(draft))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AIRecommendation.objects.exists())

    def test_second_request_returns_same_recommendation(self):
        first = self.client.post(ai_url(self.assessment))
        second = self.client.post(ai_url(self.assessment))

        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(AIRecommendation.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.AI_RECOMMENDATION_GENERATED).count(), 1)

    def test_same_inputs_give_same_recommendation(self):
        other = submitted_assessment(assessor=self.assessor)
        a = self.client.post(ai_url(self.assessment)).json()
        b = self.client.post(ai_url(other)).json()
        for field in ("recommendation", "score", "confidence", "reasons", "factors", "rule_version"):
            self.assertEqual(a[field], b[field], field)

    def test_get_before_and_after_generation(self):
        self.assertEqual(self.client.get(ai_url(self.assessment)).status_code, 404)
        self.client.post(ai_url(self.assessment))
        response = self.client.get(ai_url(self.assessment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendation"], "REFURBISH")

    def test_unknown_assessment_is_404(self):
        self.assertEqual(self.client.post(reverse("assessment-ai-recommendation", args=[999999])).status_code, 404)

    def test_permissions(self):
        self.assertEqual(APIClient().post(ai_url(self.assessment)).status_code, 401)
        self.assertEqual(APIClient().get(ai_url(self.assessment)).status_code, 401)
        for role in NO_AI_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.post(ai_url(self.assessment)).status_code, 403)
                self.assertEqual(client.get(ai_url(self.assessment)).status_code, 403)
        self.assertFalse(AIRecommendation.objects.exists())
        for role in AI_ROLES:
            with self.subTest(role=role):
                self.assertIn(logged_in_client(make_user(role)).post(ai_url(self.assessment)).status_code, (200, 201))


class DecisionTests(TestCase):
    def setUp(self):
        self.manager = make_user(RoleCode.OPERATIONS_MANAGER)
        self.client = logged_in_client(self.manager)

    def recommended(self, **overrides):
        assessment = submitted_assessment(**overrides)
        services.generate_recommendation(assessment, actor=self.manager)
        return assessment

    def test_accept_moves_device_per_decision(self):
        cases = (
            ({}, "REFURBISH", DeviceStatus.REFURBISHING),
            (
                {"functional_status": "FULLY_FUNCTIONAL", "screen_condition": "INTACT", "battery_condition": "GOOD",
                 "physical_condition": "EXCELLENT", "cosmetic_condition": "EXCELLENT", "accessories_condition": "COMPLETE",
                 "estimated_repair_cost_rwf": 0},
                "READY_FOR_DISPOSITION",
                DeviceStatus.READY_FOR_DISPOSITION,
            ),
            ({"physical_condition": "CRITICAL"}, "UNABLE_TO_REPAIR", DeviceStatus.UNABLE_TO_REPAIR),
        )
        for overrides, decision, status in cases:
            with self.subTest(decision=decision):
                assessment = self.recommended(**overrides)
                self.assertEqual(assessment.ai_recommendation.recommendation, decision)
                response = self.client.post(decision_url(assessment), {"final_decision": decision}, format="json")

                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["decision_outcome"], "ACCEPTED")
                device = assessment.device
                device.refresh_from_db()
                self.assertEqual(device.status, status)
                change = device.status_changes.get(to_status=status)
                self.assertEqual(change.from_status, DeviceStatus.ASSESSED)
                self.assertEqual(change.source_type, "assessment_decision")
                self.assertEqual(change.changed_by, self.manager)
                self.assertIn("AI recommendation accepted", change.reason)

    def test_override_requires_reason(self):
        assessment = self.recommended()
        for reason in ("", "   "):
            response = self.client.post(
                decision_url(assessment), {"final_decision": "READY_FOR_DISPOSITION", "reason": reason}, format="json"
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("reason", response.json())
        assessment.device.refresh_from_db()
        self.assertEqual(assessment.device.status, DeviceStatus.ASSESSED)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.AI_DECISION_MADE).exists())

    def test_override_keeps_ai_recommendation(self):
        assessment = self.recommended()
        response = self.client.post(
            decision_url(assessment),
            {"final_decision": "READY_FOR_DISPOSITION", "reason": "Buyer accepts the cracked screen at a discount."},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["recommendation"], "REFURBISH")
        self.assertEqual(body["final_decision"], "READY_FOR_DISPOSITION")
        self.assertEqual(body["decision_outcome"], "OVERRIDDEN")
        self.assertEqual(body["final_decision_by"]["id"], self.manager.pk)
        self.assertEqual(body["final_decision_reason"], "Buyer accepts the cracked screen at a discount.")
        recommendation = AIRecommendation.objects.get(assessment=assessment)
        self.assertEqual(recommendation.recommendation, "REFURBISH")
        assessment.device.refresh_from_db()
        self.assertEqual(assessment.device.status, DeviceStatus.READY_FOR_DISPOSITION)

    def test_decision_is_audited(self):
        assessment = self.recommended()
        self.client.post(
            decision_url(assessment), {"final_decision": "UNABLE_TO_REPAIR", "reason": "Board corrosion found."}, format="json"
        )
        entry = AuditLog.objects.get(action=AuditAction.AI_DECISION_MADE)
        self.assertEqual(entry.user, self.manager)
        self.assertEqual(entry.previous_values, {"final_decision": None, "ai_recommendation": "REFURBISH"})
        self.assertEqual(entry.new_values["final_decision"], "UNABLE_TO_REPAIR")
        self.assertEqual(entry.new_values["outcome"], "OVERRIDDEN")
        self.assertEqual(entry.new_values["reason"], "Board corrosion found.")
        self.assertEqual(entry.new_values["assessment"], assessment.reference)
        self.assertEqual(entry.new_values["device_code"], assessment.device.device_code)
        self.assertIn("Overrode", entry.description)

    def test_long_override_reason_fits_status_history(self):
        assessment = self.recommended()
        reason = "x" * 900
        response = self.client.post(
            decision_url(assessment), {"final_decision": "UNABLE_TO_REPAIR", "reason": reason}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["final_decision_reason"], reason)

    def test_decision_requires_recommendation(self):
        assessment = submitted_assessment()
        response = self.client.post(decision_url(assessment), {"final_decision": "REFURBISH"}, format="json")
        self.assertEqual(response.status_code, 400)
        assessment.device.refresh_from_db()
        self.assertEqual(assessment.device.status, DeviceStatus.ASSESSED)

    def test_decision_is_made_once(self):
        assessment = self.recommended()
        self.client.post(decision_url(assessment), {"final_decision": "REFURBISH"}, format="json")
        response = self.client.post(
            decision_url(assessment), {"final_decision": "UNABLE_TO_REPAIR", "reason": "Changed my mind"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AIRecommendation.objects.get(assessment=assessment).final_decision, "REFURBISH")
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.AI_DECISION_MADE).count(), 1)

    def test_device_must_still_be_assessed(self):
        assessment = self.recommended()
        transition_device(assessment.device, DeviceStatus.REFURBISHING, actor=self.manager)
        response = self.client.post(decision_url(assessment), {"final_decision": "REFURBISH"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AIRecommendation.objects.get(assessment=assessment).final_decision, "")

    def test_invalid_decision_value(self):
        assessment = self.recommended()
        response = self.client.post(decision_url(assessment), {"final_decision": "RESOLD"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("final_decision", response.json())

    def test_only_ai_decide_may_decide(self):
        assessment = self.recommended()
        self.assertEqual(APIClient().post(decision_url(assessment), {"final_decision": "REFURBISH"}).status_code, 401)
        for role in (RoleCode.DEVICE_ASSESSOR, RoleCode.REFURBISHMENT_STAFF, RoleCode.SALES_OFFICER,
                     RoleCode.RECOVERY_OFFICER, RoleCode.SYSTEM_ADMIN):
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                response = client.post(decision_url(assessment), {"final_decision": "REFURBISH"}, format="json")
                self.assertEqual(response.status_code, 403)
        assessment.device.refresh_from_db()
        self.assertEqual(assessment.device.status, DeviceStatus.ASSESSED)

    def test_failed_transition_rolls_back_decision(self):
        assessment = self.recommended()
        with mock.patch("ai_engine.services.transition_device", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.record_decision(assessment, actor=self.manager, final_decision="REFURBISH")
        self.assertEqual(AIRecommendation.objects.get(assessment=assessment).final_decision, "")
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.AI_DECISION_MADE).exists())


class FeedbackTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.assessment = submitted_assessment(assessor=self.assessor)
        services.generate_recommendation(self.assessment, actor=self.assessor)

    def test_record_feedback(self):
        response = self.client.post(
            feedback_url(self.assessment), {"verdict": "OVERRIDDEN", "comment": "Screen repair is cheaper locally."},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["verdict"], "OVERRIDDEN")
        self.assertEqual(response.json()["user"]["id"], self.assessor.pk)
        listed = self.client.get(ai_url(self.assessment)).json()["feedback"]
        self.assertEqual([f["verdict"] for f in listed], ["OVERRIDDEN"])
        entry = AuditLog.objects.get(action=AuditAction.AI_FEEDBACK_RECORDED)
        self.assertEqual(entry.new_values["verdict"], "OVERRIDDEN")
        self.assertEqual(entry.user, self.assessor)

    def test_feedback_does_not_change_anything_else(self):
        self.client.post(feedback_url(self.assessment), {"verdict": "OVERRIDDEN"}, format="json")
        recommendation = AIRecommendation.objects.get(assessment=self.assessment)
        self.assertEqual((recommendation.recommendation, recommendation.final_decision), ("REFURBISH", ""))
        self.assessment.device.refresh_from_db()
        self.assertEqual(self.assessment.device.status, DeviceStatus.ASSESSED)

    def test_one_feedback_per_user(self):
        self.client.post(feedback_url(self.assessment), {"verdict": "ACCEPTED"}, format="json")
        response = self.client.post(feedback_url(self.assessment), {"verdict": "OVERRIDDEN"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AIFeedback.objects.count(), 1)

    def test_invalid_verdict(self):
        response = self.client.post(feedback_url(self.assessment), {"verdict": "HELPFUL"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_feedback_requires_recommendation(self):
        other = submitted_assessment(assessor=self.assessor)
        response = self.client.post(feedback_url(other), {"verdict": "ACCEPTED"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_feedback_permissions(self):
        self.assertEqual(APIClient().post(feedback_url(self.assessment), {"verdict": "ACCEPTED"}).status_code, 401)
        for role in NO_AI_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(
                    client.post(feedback_url(self.assessment), {"verdict": "ACCEPTED"}, format="json").status_code, 403
                )
        for role in AI_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(
                    client.post(feedback_url(self.assessment), {"verdict": "ACCEPTED"}, format="json").status_code, 201
                )


class RecommendationListTests(TestCase):
    def setUp(self):
        self.manager = make_user(RoleCode.OPERATIONS_MANAGER)
        self.client = logged_in_client(self.manager)
        self.pending = submitted_assessment()
        services.generate_recommendation(self.pending, actor=self.manager)
        self.overridden = submitted_assessment()
        services.generate_recommendation(self.overridden, actor=self.manager)
        services.record_decision(self.overridden, actor=self.manager, final_decision="UNABLE_TO_REPAIR", reason="Corroded")

    def refs(self, **params):
        response = self.client.get(reverse("ai-recommendation-list"), params)
        self.assertEqual(response.status_code, 200)
        return {item["assessment_reference"] for item in response.json()["results"]}

    def test_filters(self):
        self.assertEqual(self.refs(), {self.pending.reference, self.overridden.reference})
        self.assertEqual(self.refs(decision="pending"), {self.pending.reference})
        self.assertEqual(self.refs(decision="decided"), {self.overridden.reference})
        self.assertEqual(self.refs(outcome="OVERRIDDEN"), {self.overridden.reference})
        self.assertEqual(self.refs(outcome="ACCEPTED"), set())
        self.assertEqual(self.refs(search=self.pending.device.device_code), {self.pending.reference})

    def test_list_requires_ai_view(self):
        url = reverse("ai-recommendation-list")
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(logged_in_client(make_user(RoleCode.SYSTEM_ADMIN)).get(url).status_code, 403)
        self.assertEqual(logged_in_client(make_user(RoleCode.SALES_OFFICER)).get(url).status_code, 200)


class AIRecordIntegrityTests(TestCase):
    """The database keeps the AI output immutable and the human decision write-once."""

    def setUp(self):
        self.manager = make_user(RoleCode.OPERATIONS_MANAGER)
        self.assessment = submitted_assessment()
        self.recommendation, _ = services.generate_recommendation(self.assessment, actor=self.manager)

    def test_ai_output_cannot_be_changed(self):
        for field, value in (("recommendation", "UNABLE_TO_REPAIR"), ("score", 99), ("rule_version", "hacked")):
            with self.subTest(field=field), self.assertRaises(DatabaseError), transaction.atomic():
                AIRecommendation.objects.filter(pk=self.recommendation.pk).update(**{field: value})

    def test_decision_cannot_be_rewritten(self):
        services.record_decision(self.assessment, actor=self.manager, final_decision="REFURBISH")
        with self.assertRaises(DatabaseError), transaction.atomic():
            AIRecommendation.objects.filter(pk=self.recommendation.pk).update(
                final_decision="UNABLE_TO_REPAIR", final_decision_reason="rewrite"
            )
        self.assertEqual(AIRecommendation.objects.get(pk=self.recommendation.pk).final_decision, "REFURBISH")

    def test_override_without_reason_rejected_by_database(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            AIRecommendation.objects.filter(pk=self.recommendation.pk).update(
                final_decision="UNABLE_TO_REPAIR", final_decision_by=self.manager, final_decision_at=timezone.now()
            )

    def test_records_cannot_be_deleted(self):
        feedback = services.record_feedback(self.assessment, actor=self.manager, verdict="ACCEPTED")
        with self.assertRaises(DatabaseError), transaction.atomic():
            AIFeedback.objects.filter(pk=feedback.pk).update(verdict="OVERRIDDEN")
        with self.assertRaises(DatabaseError), transaction.atomic():
            AIFeedback.objects.filter(pk=feedback.pk).delete()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AIRecommendation.objects.filter(pk=self.recommendation.pk).delete()

    def test_ai_source_still_cannot_move_device(self):
        from devices.services import InvalidTransition

        with self.assertRaises(InvalidTransition):
            transition_device(
                self.assessment.device,
                DeviceStatus.REFURBISHING,
                actor=self.manager,
                source_type="ai_recommendation",
                source_id=self.recommendation.pk,
            )
