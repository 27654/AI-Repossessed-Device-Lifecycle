import threading
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from ai_engine import services as ai_services
from assessments.tests.helpers import submitted_assessment
from audit.models import AuditAction, AuditLog
from devices import services as device_services
from devices.models import Attachment, DeviceStatus
from devices.services import InvalidTransition, transition_device
from devices.tests.helpers import TempMediaMixin
from dispositions import services
from dispositions.models import Disposition, DispositionStatus

from .helpers import make_disposition, ready_device, reallocation_fields, resale_fields

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def url(name, disposition):
    return reverse(name, args=[disposition.pk])


class ConfirmTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)
        self.client = logged_in_client(self.officer)

    def test_confirm_reallocation(self):
        disposition = make_disposition(officer=self.officer, **reallocation_fields())
        response = self.client.post(url("disposition-confirm", disposition))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], "CONFIRMED")
        self.assertEqual(body["confirmed_by"]["id"], self.officer.pk)
        self.assertIsNotNone(body["confirmed_at"])
        self.assertEqual(body["device_summary"]["status"], DeviceStatus.REALLOCATED)
        device = disposition.device
        device.refresh_from_db()
        self.assertEqual(device.status, DeviceStatus.REALLOCATED)
        change = device.status_changes.get(to_status=DeviceStatus.REALLOCATED)
        self.assertEqual(change.from_status, DeviceStatus.READY_FOR_DISPOSITION)
        self.assertEqual((change.source_type, change.source_id), ("disposition", disposition.pk))
        self.assertEqual(change.reason, f"Reallocation {disposition.reference} confirmed.")

    def test_confirm_resale(self):
        disposition = make_disposition(officer=self.officer)
        self.assertEqual(self.client.post(url("disposition-confirm", disposition)).status_code, 200)
        device = disposition.device
        device.refresh_from_db()
        self.assertEqual(device.status, DeviceStatus.RESOLD)
        change = device.status_changes.get(to_status=DeviceStatus.RESOLD)
        self.assertEqual((change.from_status, change.source_type), (DeviceStatus.READY_FOR_DISPOSITION, "disposition"))

    def test_confirmation_is_audited(self):
        disposition = make_disposition(officer=self.officer)
        self.client.post(url("disposition-confirm", disposition))

        entry = AuditLog.objects.get(action=AuditAction.DISPOSITION_CONFIRMED)
        self.assertEqual(entry.user, self.officer)
        self.assertEqual(entry.previous_values, {"status": "DRAFT"})
        self.assertEqual(entry.new_values["status"], "CONFIRMED")
        self.assertEqual(entry.new_values["sale_price_rwf"], 65_000)
        status_entry = AuditLog.objects.get(action=AuditAction.DEVICE_STATUS_CHANGED, new_values__status="RESOLD")
        self.assertEqual(status_entry.new_values["source_type"], "disposition")

    def test_duplicate_confirmation_rejected(self):
        disposition = make_disposition(officer=self.officer)
        self.assertEqual(self.client.post(url("disposition-confirm", disposition)).status_code, 200)
        self.assertEqual(self.client.post(url("disposition-confirm", disposition)).status_code, 400)
        self.assertEqual(disposition.device.status_changes.filter(to_status=DeviceStatus.RESOLD).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.DISPOSITION_CONFIRMED).count(), 1)

    def test_confirmed_disposition_cannot_be_edited(self):
        disposition = make_disposition(officer=self.officer)
        self.client.post(url("disposition-confirm", disposition))
        response = self.client.patch(url("disposition-detail", disposition), {"sale_price_rwf": 1}, format="json")
        self.assertEqual(response.status_code, 400)
        disposition.refresh_from_db()
        self.assertEqual(disposition.sale_price_rwf, 65_000)

    def test_disposed_device_cannot_get_another_disposition(self):
        disposition = make_disposition(officer=self.officer)
        self.client.post(url("disposition-confirm", disposition))
        response = self.client.post(
            reverse("disposition-list"), {"device": disposition.device_id, **reallocation_fields()}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Disposition.objects.filter(device=disposition.device).count(), 1)

    def test_device_that_left_ready_cannot_be_confirmed(self):
        disposition = make_disposition(officer=self.officer)
        transition_device(disposition.device, DeviceStatus.REALLOCATED, actor=make_user(RoleCode.OPERATIONS_MANAGER))
        response = self.client.post(url("disposition-confirm", disposition))
        self.assertEqual(response.status_code, 400)
        disposition.refresh_from_db()
        self.assertEqual(disposition.status, DispositionStatus.DRAFT)

    def test_failed_transition_rolls_back_confirmation(self):
        disposition = make_disposition(officer=self.officer)
        with mock.patch("dispositions.services.transition_device", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.confirm_disposition(disposition, actor=self.officer)
        disposition.refresh_from_db()
        self.assertEqual(disposition.status, DispositionStatus.DRAFT)
        self.assertIsNone(disposition.confirmed_at)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DISPOSITION_CONFIRMED).exists())

    def test_confirmation_needs_a_human_actor(self):
        disposition = make_disposition(officer=self.officer)
        for actor in (None, make_user(RoleCode.SALES_OFFICER, account_status="SUSPENDED")):
            with self.subTest(actor=actor), self.assertRaises(ValidationError):
                services.confirm_disposition(disposition, actor=actor)
        disposition.refresh_from_db()
        self.assertEqual(disposition.status, DispositionStatus.DRAFT)

    def test_ai_never_creates_or_confirms_dispositions(self):
        manager = make_user(RoleCode.OPERATIONS_MANAGER)
        assessment = submitted_assessment(physical_condition="EXCELLENT", cosmetic_condition="EXCELLENT",
                                          screen_condition="INTACT", battery_condition="GOOD",
                                          functional_status="FULLY_FUNCTIONAL", accessories_condition="COMPLETE",
                                          estimated_repair_cost_rwf=0)
        recommendation, _ = ai_services.generate_recommendation(assessment, actor=manager)
        self.assertEqual(recommendation.recommendation, "READY_FOR_DISPOSITION")
        ai_services.record_decision(assessment, actor=manager, final_decision="READY_FOR_DISPOSITION")
        self.assertFalse(Disposition.objects.filter(device=assessment.device).exists())
        with self.assertRaises(InvalidTransition):
            transition_device(assessment.device, DeviceStatus.RESOLD, actor=manager, source_type="ai_recommendation")


class DatabaseProtectionTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)

    def test_one_confirmed_disposition_per_device(self):
        disposition = make_disposition(officer=self.officer)
        services.confirm_disposition(disposition, actor=self.officer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Disposition.objects.create(
                device=disposition.device, responsible_user=self.officer, status=DispositionStatus.CONFIRMED,
                confirmed_by=self.officer, confirmed_at=timezone.now(), **resale_fields(),
            )

    def test_fields_must_match_type(self):
        device = ready_device()
        for fields in (resale_fields(sale_price_rwf=0), resale_fields(buyer_reference=""),
                       reallocation_fields(destination=""), reallocation_fields(sale_price_rwf=5)):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Disposition.objects.create(device=device, responsible_user=self.officer, **fields)

    def test_confirmed_disposition_is_immutable(self):
        disposition = make_disposition(officer=self.officer)
        services.confirm_disposition(disposition, actor=self.officer)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Disposition.objects.filter(pk=disposition.pk).update(sale_price_rwf=1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Disposition.objects.filter(pk=disposition.pk).delete()

    def test_drafts_cannot_be_deleted(self):
        disposition = make_disposition(officer=self.officer)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Disposition.objects.filter(pk=disposition.pk).delete()

    def test_services_reject_unknown_fields(self):
        disposition = make_disposition(officer=self.officer)
        with self.assertRaises(ValidationError):
            services.update_disposition(disposition, actor=self.officer, changes={"status": "CONFIRMED"})


class EvidenceTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)
        self.client = logged_in_client(self.officer)
        self.disposition = make_disposition(officer=self.officer)
        self.url = reverse("disposition-attachments", args=[self.disposition.pk])

    def post(self, client=None, name="receipt.png", content=PNG):
        file = SimpleUploadedFile(name, content, content_type="image/png")
        return (client or self.client).post(self.url, {"file": file, "description": "Sales receipt"}, format="multipart")

    def test_upload_evidence(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["disposition"], body["disposition_reference"]),
                         (self.disposition.pk, self.disposition.reference))
        attachment = Attachment.objects.get(pk=body["id"])
        self.assertEqual(attachment.device_id, self.disposition.device_id)
        entry = AuditLog.objects.get(action=AuditAction.ATTACHMENT_UPLOADED)
        self.assertEqual(entry.new_values["disposition_reference"], self.disposition.reference)

    def test_evidence_kept_after_confirmation(self):
        attachment_id = self.post().json()["id"]
        services.confirm_disposition(self.disposition, actor=self.officer)

        self.assertEqual(self.post().status_code, 400)  # no new evidence on a confirmed record
        listed = self.client.get(self.url).json()
        self.assertEqual([a["id"] for a in listed], [attachment_id])
        reader = logged_in_client(make_user(RoleCode.OPERATIONS_MANAGER))
        self.assertEqual(reader.get(listed[0]["download_url"]).status_code, 200)
        self.assertEqual(APIClient().get(listed[0]["download_url"]).status_code, 401)

    def test_file_checks_and_permissions(self):
        self.assertEqual(self.post(name="x.exe", content=b"MZ" + b"\0" * 40).status_code, 400)
        self.assertEqual(self.post(name="x.pdf").status_code, 400)
        for role in (RoleCode.OPERATIONS_MANAGER, RoleCode.REFURBISHMENT_STAFF, RoleCode.SYSTEM_ADMIN):
            with self.subTest(role=role):
                self.assertEqual(self.post(client=logged_in_client(make_user(role))).status_code, 403)
        self.assertEqual(logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR)).get(self.url).status_code, 200)
        self.assertFalse(Attachment.objects.exists())

    def test_attachment_must_belong_to_the_same_device_and_one_record(self):
        with self.assertRaises(ValidationError):
            device_services.add_attachment(
                ready_device(), actor=self.officer, upload=SimpleUploadedFile("x.png", PNG), mime_type="image/png",
                original_name="x.png", disposition=self.disposition,
            )
        with self.assertRaises(ValidationError):
            device_services.add_attachment(
                self.disposition.device, actor=self.officer, upload=SimpleUploadedFile("x.png", PNG),
                mime_type="image/png", original_name="x.png", disposition=self.disposition,
                recovery=mock.Mock(device_id=self.disposition.device_id, reference="RCV"),
            )
        self.assertFalse(Attachment.objects.exists())


class ConcurrentConfirmationTests(TransactionTestCase):
    """Two officers confirm the same draft at the same moment: exactly one succeeds."""

    serialized_rollback = True  # keep the roles seeded by migrations for later tests

    def test_only_one_confirmation_wins(self):
        disposition = make_disposition()
        officers = [make_user(RoleCode.SALES_OFFICER), make_user(RoleCode.SALES_OFFICER)]
        barrier = threading.Barrier(2)
        results = []

        def confirm(actor):
            try:
                barrier.wait()
                services.confirm_disposition(Disposition.objects.get(pk=disposition.pk), actor=actor)
                results.append("ok")
            except ValidationError:
                results.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=confirm, args=(officer,)) for officer in officers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(results), ["ok", "rejected"])
        self.assertEqual(disposition.device.status_changes.filter(to_status=DeviceStatus.RESOLD).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.DISPOSITION_CONFIRMED).count(), 1)
