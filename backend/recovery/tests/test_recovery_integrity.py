"""Transactions, database constraints and the history trigger for recoveries."""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import Attachment, DeviceStatus
from devices.services import add_attachment
from devices.tests.helpers import TempMediaMixin, make_device
from recovery import services
from recovery.models import Recovery, RecoveryStatus

from .helpers import make_recovery, recovery_fields

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class RecoveryTransactionTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.device = make_device(actor=self.officer)
        self.recovery = make_recovery(self.device, self.officer)

    def test_failed_status_change_rolls_back_completion(self):
        with mock.patch("recovery.services.transition_device", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.complete_recovery(self.recovery, actor=self.officer)

        self.recovery.refresh_from_db()
        self.device.refresh_from_db()
        self.assertEqual(self.recovery.status, RecoveryStatus.IN_PROGRESS)
        self.assertIsNone(self.recovery.completed_at)
        self.assertEqual(self.device.status, DeviceStatus.IN_RECOVERY)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.RECOVERY_COMPLETED).exists())

    def test_failed_audit_rolls_back_status_change(self):
        with mock.patch("devices.services.log_action", side_effect=DatabaseError("audit down")):
            with self.assertRaises(DatabaseError):
                services.complete_recovery(self.recovery, actor=self.officer)

        self.recovery.refresh_from_db()
        self.device.refresh_from_db()
        self.assertEqual(self.recovery.status, RecoveryStatus.IN_PROGRESS)
        self.assertEqual(self.device.status, DeviceStatus.IN_RECOVERY)
        self.assertEqual(self.device.status_changes.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.RECOVERY_COMPLETED).exists())

    def test_failed_audit_rolls_back_creation(self):
        other = make_device(actor=self.officer)
        with mock.patch("recovery.services.log_action", side_effect=DatabaseError("audit down")):
            with self.assertRaises(DatabaseError):
                services.create_recovery(actor=self.officer, device=other, **recovery_fields())
        self.assertFalse(other.recoveries.exists())

    def test_service_rejects_unknown_fields(self):
        other = make_device(actor=self.officer)
        with self.assertRaises(ValidationError):
            services.create_recovery(actor=self.officer, device=other, status="COMPLETED", **recovery_fields())
        with self.assertRaises(ValidationError):
            services.update_recovery(self.recovery, actor=self.officer, changes={"completed_at": None})


class RecoveryDatabaseConstraintTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.device = make_device(actor=self.officer)

    def test_database_allows_only_one_open_recovery_per_device(self):
        make_recovery(self.device, self.officer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Recovery.objects.create(device=self.device, recovery_officer=self.officer, **recovery_fields())

    def test_database_allows_only_one_successful_recovery_per_device(self):
        services.complete_recovery(make_recovery(self.device, self.officer), actor=self.officer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Recovery.objects.create(
                device=self.device,
                recovery_officer=self.officer,
                status=RecoveryStatus.COMPLETED,
                completed_by=self.officer,
                completed_at=self.device.created_at,
                **recovery_fields(),
            )

    def test_completed_record_needs_outcome(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Recovery.objects.create(
                device=self.device,
                recovery_officer=self.officer,
                status=RecoveryStatus.COMPLETED,
                **recovery_fields(outcome=""),
            )

    def test_completed_recovery_is_immutable_in_the_database(self):
        recovery = make_recovery(self.device, self.officer)
        services.complete_recovery(recovery, actor=self.officer)

        with self.assertRaises(DatabaseError), transaction.atomic():
            Recovery.objects.filter(pk=recovery.pk).update(recovery_location="Tampered")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Recovery.objects.filter(pk=recovery.pk).delete()

        recovery.refresh_from_db()
        self.assertEqual(recovery.recovery_location, "Nyarugenge, Kigali")

    def test_recoveries_cannot_be_deleted_even_when_open(self):
        recovery = make_recovery(self.device, self.officer)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Recovery.objects.filter(pk=recovery.pk).delete()


class RecoveryEvidenceTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer)
        self.recovery = make_recovery(self.device, self.officer)
        self.url = reverse("recovery-attachments", args=[self.recovery.pk])

    def post(self, client=None, name="evidence.png", content=PNG):
        file = SimpleUploadedFile(name, content, content_type="image/png")
        return (client or self.client).post(self.url, {"file": file, "description": "At pickup"}, format="multipart")

    def test_upload_evidence_to_open_recovery(self):
        response = self.post()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["recovery"], self.recovery.pk)
        self.assertEqual(body["recovery_reference"], self.recovery.reference)
        attachment = Attachment.objects.get(pk=body["id"])
        self.assertEqual((attachment.device, attachment.recovery), (self.device, self.recovery))

        entry = AuditLog.objects.get(action=AuditAction.ATTACHMENT_UPLOADED)
        self.assertEqual(entry.new_values["recovery_id"], self.recovery.pk)
        self.assertIn(self.recovery.reference, entry.description)

    def test_evidence_appears_on_recovery_and_device(self):
        attachment_id = self.post().json()["id"]

        detail = self.client.get(reverse("recovery-detail", args=[self.recovery.pk])).json()
        self.assertEqual([a["id"] for a in detail["attachments"]], [attachment_id])
        self.assertEqual([a["id"] for a in self.client.get(self.url).json()], [attachment_id])

        device_files = self.client.get(reverse("device-attachments", args=[self.device.pk])).json()
        self.assertEqual(device_files[0]["recovery_reference"], self.recovery.reference)
        download = self.client.get(device_files[0]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), PNG)

    def test_plain_device_attachments_are_unchanged(self):
        url = reverse("device-attachments", args=[self.device.pk])
        file = SimpleUploadedFile("plain.png", PNG, content_type="image/png")
        body = self.client.post(url, {"file": file}, format="multipart").json()
        self.assertIsNone(body["recovery"])
        self.assertIsNone(body["recovery_reference"])

    def test_existing_file_checks_still_apply(self):
        response = self.post(name="evidence.exe", content=b"MZ" + b"\x00" * 64)
        self.assertEqual(response.status_code, 400)
        response = self.post(name="evidence.pdf")  # PNG bytes with a PDF name
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attachment.objects.exists())

    def test_no_evidence_after_completion(self):
        services.complete_recovery(self.recovery, actor=self.officer)
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attachment.objects.exists())

    def test_upload_requires_recovery_manage(self):
        for role in (RoleCode.DEVICE_ASSESSOR, RoleCode.OPERATIONS_MANAGER):
            with self.subTest(role=role):
                self.assertEqual(self.post(client=logged_in_client(make_user(role))).status_code, 403)
        self.assertEqual(
            logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR)).get(self.url).status_code, 200
        )

    def test_evidence_must_match_the_device(self):
        other_device = make_device(actor=self.officer)
        upload = SimpleUploadedFile("x.png", PNG, content_type="image/png")
        with self.assertRaises(ValidationError):
            add_attachment(
                other_device,
                actor=self.officer,
                upload=upload,
                mime_type="image/png",
                original_name="x.png",
                recovery=self.recovery,
            )
