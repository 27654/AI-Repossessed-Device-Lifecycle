from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from assessments.models import Assessment, AssessmentStatus
from audit.models import AuditAction, AuditLog
from devices import services as device_services
from devices.models import Attachment, DeviceStatus
from devices.tests.helpers import TempMediaMixin, make_device

from .helpers import assessment_payload, make_assessment, recovered_device

LIST_URL = reverse("assessment-list")
NON_ASSESSOR_ROLES = [
    RoleCode.RECOVERY_OFFICER,
    RoleCode.REFURBISHMENT_STAFF,
    RoleCode.SALES_OFFICER,
    RoleCode.OPERATIONS_MANAGER,
    RoleCode.SYSTEM_ADMIN,
]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def detail_url(assessment):
    return reverse("assessment-detail", args=[assessment.pk])


def submit_url(assessment):
    return reverse("assessment-submit", args=[assessment.pk])


class AssessmentCreateTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.device = recovered_device()

    def test_assessor_creates_draft(self):
        response = self.client.post(LIST_URL, assessment_payload(self.device), format="json")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertRegex(body["reference"], r"^ASS-\d{4}-\d{5}$")
        self.assertEqual(body["status"], AssessmentStatus.DRAFT)
        self.assertEqual(body["assessor"]["id"], self.assessor.pk)
        self.assertEqual(body["estimated_repair_cost_rwf"], 18_000)
        self.assertEqual(body["screen_condition_label"], "Major damage")
        self.assertEqual(body["assessment_date"], timezone.localdate().isoformat())
        self.assertIsNone(body["submitted_at"])
        # Starting an assessment does not move the device; submitting it does.
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)

    def test_creation_is_audited(self):
        response = self.client.post(LIST_URL, assessment_payload(self.device), format="json")

        entry = AuditLog.objects.get(action=AuditAction.ASSESSMENT_CREATED)
        self.assertEqual(entry.user, self.assessor)
        self.assertEqual((entry.entity_type, entry.entity_id), ("assessment", str(response.json()["id"])))
        self.assertEqual(entry.new_values["device_code"], self.device.device_code)
        self.assertEqual(entry.new_values["estimated_market_value_rwf"], 85_000)

    def test_draft_may_start_with_device_only(self):
        response = self.client.post(LIST_URL, {"device": self.device.pk}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["physical_condition"], "")
        self.assertEqual(response.json()["defects"], [])

    def test_device_is_required(self):
        response = self.client.post(LIST_URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("device", response.json())

    def test_device_must_be_recovered(self):
        officer = make_user(RoleCode.RECOVERY_OFFICER)
        in_recovery = make_device(actor=officer)
        assessed = recovered_device()
        device_services.transition_device(assessed, DeviceStatus.ASSESSED, actor=officer)

        for device in (in_recovery, assessed):
            with self.subTest(status=device.status):
                response = self.client.post(LIST_URL, assessment_payload(device), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("device", response.json())
        self.assertFalse(Assessment.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.ASSESSMENT_CREATED).exists())

    def test_controlled_choices_are_enforced(self):
        for field, value in (
            ("physical_condition", "SHINY"),
            ("cosmetic_condition", "CRITICAL"),  # not a cosmetic option
            ("screen_condition", "CRACKED"),
            ("battery_condition", "DEAD"),
            ("functional_status", "WORKS"),
            ("accessories_condition", "SOME"),
            ("defects", ["CAMERA_FAULT", "ALIEN_INVASION"]),
        ):
            with self.subTest(field=field):
                response = self.client.post(LIST_URL, assessment_payload(self.device, **{field: value}), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_money_is_whole_non_negative_rwf(self):
        for field in ("estimated_repair_cost_rwf", "estimated_market_value_rwf"):
            for value in (-1, 12.5, "abc", 100_000_001):
                with self.subTest(field=field, value=value):
                    response = self.client.post(
                        LIST_URL, assessment_payload(self.device, **{field: value}), format="json"
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json())

    def test_future_assessment_date_is_rejected(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        response = self.client.post(LIST_URL, assessment_payload(self.device, assessment_date=future), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assessment_date", response.json())

    def test_only_one_draft_per_device(self):
        make_assessment(self.device, self.assessor)
        response = self.client.post(LIST_URL, assessment_payload(self.device), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.assessments.count(), 1)

    def test_defects_are_deduplicated(self):
        payload = assessment_payload(self.device, defects=["WATER_DAMAGE", "CAMERA_FAULT", "WATER_DAMAGE"])
        response = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(response.json()["defects"], ["CAMERA_FAULT", "WATER_DAMAGE"])
        self.assertEqual(response.json()["defect_labels"], ["Camera fault", "Water damage"])

    def test_references_are_unique(self):
        other = recovered_device()
        first = self.client.post(LIST_URL, assessment_payload(self.device), format="json").json()["reference"]
        second = self.client.post(LIST_URL, assessment_payload(other), format="json").json()["reference"]
        self.assertNotEqual(first, second)
        self.assertEqual(Assessment.objects.filter(reference=first).count(), 1)

    def test_read_only_fields_are_ignored(self):
        payload = assessment_payload(self.device, status="SUBMITTED", reference="ASS-FAKE", submitted_at="2026-01-01T00:00Z")
        response = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], AssessmentStatus.DRAFT)
        self.assertNotEqual(response.json()["reference"], "ASS-FAKE")


class AssessmentUpdateTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.device = recovered_device()
        self.assessment = make_assessment(self.device, self.assessor)

    def test_draft_can_be_edited_and_changes_are_audited(self):
        response = self.client.patch(
            detail_url(self.assessment),
            {"battery_condition": "POOR", "estimated_repair_cost_rwf": 25_000, "physical_condition": "GOOD"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["battery_condition"], "POOR")
        entry = AuditLog.objects.get(action=AuditAction.ASSESSMENT_UPDATED)
        self.assertEqual(entry.previous_values, {"battery_condition": "FAIR", "estimated_repair_cost_rwf": 18_000})
        self.assertEqual(entry.new_values, {"battery_condition": "POOR", "estimated_repair_cost_rwf": 25_000})

    def test_unchanged_update_writes_no_audit(self):
        self.client.patch(detail_url(self.assessment), {"physical_condition": "GOOD"}, format="json")
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.ASSESSMENT_UPDATED).exists())

    def test_device_cannot_be_changed(self):
        response = self.client.patch(detail_url(self.assessment), {"device": recovered_device().pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_submitted_assessment_cannot_be_edited(self):
        self.assertEqual(self.client.post(submit_url(self.assessment)).status_code, 200)
        response = self.client.patch(detail_url(self.assessment), {"battery_condition": "POOR"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.battery_condition, "FAIR")

    def test_put_and_delete_are_refused(self):
        self.assertIn(self.client.put(detail_url(self.assessment), {}, format="json").status_code, (403, 405))
        self.assertIn(self.client.delete(detail_url(self.assessment)).status_code, (403, 405))
        self.assertTrue(Assessment.objects.filter(pk=self.assessment.pk).exists())


class AssessmentSubmitTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.device = recovered_device()

    def test_submission_moves_device_to_assessed(self):
        assessment = make_assessment(self.device, self.assessor)
        response = self.client.post(submit_url(assessment))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], AssessmentStatus.SUBMITTED)
        self.assertIsNotNone(response.json()["submitted_at"])
        self.assertEqual(response.json()["device_summary"]["status"], DeviceStatus.ASSESSED)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.ASSESSED)

    def test_submission_uses_transition_device(self):
        assessment = make_assessment(self.device, self.assessor)
        with mock.patch(
            "assessments.services.transition_device", wraps=device_services.transition_device
        ) as transition:
            self.client.post(submit_url(assessment))

        transition.assert_called_once()
        args, kwargs = transition.call_args
        self.assertEqual(args[1], DeviceStatus.ASSESSED)
        self.assertEqual((kwargs["source_type"], kwargs["source_id"]), ("assessment", assessment.pk))

    def test_status_history_identifies_the_assessment(self):
        assessment = make_assessment(self.device, self.assessor)
        self.client.post(submit_url(assessment))

        change = self.device.status_changes.get(to_status=DeviceStatus.ASSESSED)
        self.assertEqual(change.from_status, DeviceStatus.RECOVERED)
        self.assertEqual((change.source_type, change.source_id), ("assessment", assessment.pk))
        self.assertEqual(change.reason, f"Condition assessment {assessment.reference} submitted.")
        self.assertEqual(change.changed_by, self.assessor)

    def test_submission_is_audited(self):
        assessment = make_assessment(self.device, self.assessor)
        self.client.post(submit_url(assessment))

        entry = AuditLog.objects.get(action=AuditAction.ASSESSMENT_SUBMITTED)
        self.assertEqual(entry.user, self.assessor)
        self.assertEqual(entry.entity_id, str(assessment.pk))
        self.assertEqual(entry.previous_values, {"status": "DRAFT"})
        self.assertEqual(entry.new_values["status"], "SUBMITTED")
        self.assertEqual(entry.new_values["screen_condition"], "MAJOR_DAMAGE")
        status_entry = AuditLog.objects.get(action=AuditAction.DEVICE_STATUS_CHANGED)
        self.assertEqual(status_entry.new_values["source_type"], "assessment")

    def test_submission_sets_device_condition(self):
        for physical, expected in (("GOOD", "GOOD"), ("CRITICAL", "POOR")):
            with self.subTest(physical=physical):
                device = recovered_device()
                self.client.post(submit_url(make_assessment(device, self.assessor, physical_condition=physical)))
                device.refresh_from_db()
                self.assertEqual(device.current_condition, expected)
        entry = AuditLog.objects.filter(action=AuditAction.DEVICE_UPDATED).latest("id")
        self.assertEqual(entry.new_values["current_condition"], "POOR")

    def test_required_fields_for_submission(self):
        assessment = make_assessment(
            self.device,
            self.assessor,
            screen_condition="",
            functional_status="",
            estimated_market_value_rwf=None,
        )
        response = self.client.post(submit_url(assessment))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()), {"screen_condition", "functional_status", "estimated_market_value_rwf"}
        )
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, AssessmentStatus.DRAFT)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)

    def test_market_value_must_be_positive(self):
        assessment = make_assessment(self.device, self.assessor, estimated_market_value_rwf=0)
        response = self.client.post(submit_url(assessment))
        self.assertEqual(response.status_code, 400)
        self.assertIn("estimated_market_value_rwf", response.json())

    def test_duplicate_submission_is_rejected(self):
        assessment = make_assessment(self.device, self.assessor)
        self.assertEqual(self.client.post(submit_url(assessment)).status_code, 200)

        response = self.client.post(submit_url(assessment))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.status_changes.filter(to_status=DeviceStatus.ASSESSED).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.ASSESSMENT_SUBMITTED).count(), 1)

    def test_no_new_assessment_after_submission(self):
        self.client.post(submit_url(make_assessment(self.device, self.assessor)))
        response = self.client.post(LIST_URL, assessment_payload(self.device), format="json")
        self.assertEqual(response.status_code, 400)

    def test_device_that_left_recovered_cannot_be_submitted(self):
        assessment = make_assessment(self.device, self.assessor)
        device_services.transition_device(self.device, DeviceStatus.ASSESSED, actor=make_user(RoleCode.OPERATIONS_MANAGER))

        response = self.client.post(submit_url(assessment))
        self.assertEqual(response.status_code, 400)
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, AssessmentStatus.DRAFT)

    def test_unknown_assessment_is_404(self):
        self.assertEqual(self.client.post(reverse("assessment-submit", args=[999999])).status_code, 404)


class AssessmentPermissionTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.device = recovered_device()
        self.assessment = make_assessment(self.device, self.assessor)

    def test_unauthenticated_requests_get_401(self):
        client = APIClient()
        self.assertEqual(client.get(LIST_URL).status_code, 401)
        self.assertEqual(client.post(LIST_URL, assessment_payload(recovered_device()), format="json").status_code, 401)
        self.assertEqual(client.get(detail_url(self.assessment)).status_code, 401)
        self.assertEqual(client.patch(detail_url(self.assessment), {"assessment_notes": "x"}, format="json").status_code, 401)
        self.assertEqual(client.post(submit_url(self.assessment)).status_code, 401)

    def test_other_roles_cannot_create_update_or_submit(self):
        other_device = recovered_device()
        for role in NON_ASSESSOR_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.post(LIST_URL, assessment_payload(other_device), format="json").status_code, 403)
                self.assertEqual(
                    client.patch(detail_url(self.assessment), {"assessment_notes": "x"}, format="json").status_code, 403
                )
                self.assertEqual(client.post(submit_url(self.assessment)).status_code, 403)

        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, AssessmentStatus.DRAFT)
        self.assertFalse(other_device.assessments.exists())

    def test_roles_with_device_view_can_read(self):
        for role in NON_ASSESSOR_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.get(LIST_URL).status_code, 200)
                self.assertEqual(client.get(detail_url(self.assessment)).status_code, 200)

    def test_user_without_role_cannot_read(self):
        client = logged_in_client(make_user(role_code=None))
        self.assertEqual(client.get(LIST_URL).status_code, 403)


class AssessmentListTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.device_a = recovered_device(make="Nokia")
        self.device_b = recovered_device()
        self.draft = make_assessment(self.device_a, self.assessor)
        self.submitted = make_assessment(self.device_b, self.assessor)
        self.client.post(submit_url(self.submitted))

    def ids(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.json()["results"]}

    def test_filters(self):
        self.assertEqual(self.ids(), {self.draft.pk, self.submitted.pk})
        self.assertEqual(self.ids(device=self.device_a.pk), {self.draft.pk})
        self.assertEqual(self.ids(status="SUBMITTED"), {self.submitted.pk})
        self.assertEqual(self.ids(search="nokia"), {self.draft.pk})
        self.assertEqual(self.ids(search=self.submitted.reference), {self.submitted.pk})
        self.assertEqual(self.ids(status="BOGUS", device="x"), {self.draft.pk, self.submitted.pk})


class AssessmentEvidenceTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.client = logged_in_client(self.assessor)
        self.device = recovered_device()
        self.assessment = make_assessment(self.device, self.assessor)
        self.url = reverse("assessment-attachments", args=[self.assessment.pk])

    def post(self, client=None, name="screen.png", content=PNG):
        file = SimpleUploadedFile(name, content, content_type="image/png")
        return (client or self.client).post(self.url, {"file": file, "description": "Screen damage"}, format="multipart")

    def test_upload_evidence_to_draft(self):
        response = self.post()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["assessment"], body["assessment_reference"]), (self.assessment.pk, self.assessment.reference))
        self.assertIsNone(body["recovery"])
        attachment = Attachment.objects.get(pk=body["id"])
        self.assertEqual((attachment.device, attachment.assessment), (self.device, self.assessment))
        entry = AuditLog.objects.get(action=AuditAction.ATTACHMENT_UPLOADED)
        self.assertEqual(entry.new_values["assessment_id"], self.assessment.pk)

    def test_evidence_stays_accessible_after_submission(self):
        attachment_id = self.post().json()["id"]
        self.client.post(submit_url(self.assessment))

        detail = self.client.get(detail_url(self.assessment)).json()
        self.assertEqual([a["id"] for a in detail["attachments"]], [attachment_id])
        self.assertEqual([a["id"] for a in self.client.get(self.url).json()], [attachment_id])
        reader = logged_in_client(make_user(RoleCode.OPERATIONS_MANAGER))
        download = reader.get(detail["attachments"][0]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), PNG)
        self.assertEqual(APIClient().get(detail["attachments"][0]["download_url"]).status_code, 401)

    def test_no_evidence_after_submission(self):
        self.client.post(submit_url(self.assessment))
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attachment.objects.exists())

    def test_existing_file_checks_still_apply(self):
        self.assertEqual(self.post(name="report.exe", content=b"MZ" + b"\0" * 64).status_code, 400)
        self.assertEqual(self.post(name="screen.pdf").status_code, 400)  # PNG bytes, PDF name

    def test_upload_requires_assessment_create(self):
        for role in (RoleCode.RECOVERY_OFFICER, RoleCode.OPERATIONS_MANAGER, RoleCode.SYSTEM_ADMIN):
            with self.subTest(role=role):
                self.assertEqual(self.post(client=logged_in_client(make_user(role))).status_code, 403)
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(logged_in_client(make_user(RoleCode.SALES_OFFICER)).get(self.url).status_code, 200)

    def test_file_cannot_be_evidence_for_two_records(self):
        from rest_framework.exceptions import ValidationError

        recovery_device = make_device(actor=make_user(RoleCode.RECOVERY_OFFICER))
        with self.assertRaises(ValidationError):
            device_services.add_attachment(
                self.device,
                actor=self.assessor,
                upload=SimpleUploadedFile("x.png", PNG),
                mime_type="image/png",
                original_name="x.png",
                assessment=self.assessment,
                recovery=mock.Mock(device_id=self.device.pk, reference="RCV"),
            )
        with self.assertRaises(ValidationError):
            device_services.add_attachment(
                recovery_device,
                actor=self.assessor,
                upload=SimpleUploadedFile("x.png", PNG),
                mime_type="image/png",
                original_name="x.png",
                assessment=self.assessment,
            )
