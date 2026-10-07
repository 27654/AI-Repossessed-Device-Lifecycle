import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import Attachment

from .helpers import TempMediaMixin, make_device

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


def upload(name, content, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class AttachmentTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer)
        self.url = reverse("device-attachments", args=[self.device.pk])

    def post(self, file, **extra):
        return self.client.post(self.url, {"file": file, **extra}, format="multipart")

    def test_upload_image(self):
        response = self.post(upload("front.png", PNG, "image/png"), description="Front of device")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["original_name"], "front.png")
        self.assertEqual(body["mime_type"], "image/png")
        self.assertEqual(body["size_bytes"], len(PNG))
        self.assertEqual(body["description"], "Front of device")
        self.assertEqual(body["uploaded_by"]["id"], self.officer.pk)

    def test_all_allowed_types_are_accepted(self):
        for name, content, mime in (
            ("a.jpg", JPEG, "image/jpeg"),
            ("b.JPEG", JPEG, "image/jpeg"),
            ("c.png", PNG, "image/png"),
            ("d.webp", WEBP, "image/webp"),
            ("e.pdf", PDF, "application/pdf"),
        ):
            with self.subTest(name=name):
                response = self.post(upload(name, content))
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()["mime_type"], mime)

    def test_storage_name_is_random_and_path_is_not_exposed(self):
        response = self.post(upload("customer-receipt.pdf", PDF))

        attachment = Attachment.objects.get()
        stored = os.path.basename(attachment.file.name)
        self.assertNotIn("customer-receipt", stored)
        self.assertRegex(stored, r"^[0-9a-f]{32}\.pdf$")
        self.assertNotIn("file", response.json())
        self.assertNotIn(attachment.file.name, response.content.decode())
        self.assertNotIn(str(settings.MEDIA_ROOT), response.content.decode())

    def test_upload_is_audited_without_file_contents(self):
        self.post(upload("front.png", PNG))

        entry = AuditLog.objects.get(action=AuditAction.ATTACHMENT_UPLOADED)
        self.assertEqual(entry.entity_type, "device")
        self.assertEqual(entry.entity_id, str(self.device.pk))
        self.assertEqual(entry.new_values["original_name"], "front.png")
        self.assertEqual(entry.new_values["size_bytes"], len(PNG))
        self.assertNotIn("attachments/", str(entry.new_values))

    def test_disallowed_types_are_rejected(self):
        for name, content in (
            ("notes.txt", b"plain text"),
            ("script.html", b"<html><script>alert(1)</script>"),
            ("photo.png", b"MZ\x90\x00 executable pretending to be png"),
            ("anim.gif", b"GIF89a" + b"\x00" * 20),
        ):
            with self.subTest(name=name):
                response = self.post(upload(name, content, "image/png"))
                self.assertEqual(response.status_code, 400)
                self.assertIn("file", response.json())
        self.assertFalse(Attachment.objects.exists())

    def test_extension_must_match_content(self):
        response = self.post(upload("report.pdf", PNG))
        self.assertEqual(response.status_code, 400)

    def test_file_size_limit(self):
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        at_limit = PNG + b"\x00" * (limit - len(PNG))

        self.assertEqual(self.post(upload("ok.png", at_limit)).status_code, 201)
        response = self.post(upload("big.png", at_limit + b"\x00"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("larger than", response.json()["file"][0])

    def test_empty_file_is_rejected(self):
        response = self.post(upload("empty.png", b""))
        self.assertEqual(response.status_code, 400)

    def test_original_name_is_sanitised(self):
        response = self.post(upload("../../etc/evil.png", PNG))
        self.assertEqual(response.json()["original_name"], "evil.png")

    def test_list_and_download(self):
        self.post(upload("front.png", PNG))
        viewer = logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR))

        listed = viewer.get(self.url).json()
        self.assertEqual(len(listed), 1)
        response = viewer.get(listed[0]["download_url"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        self.assertEqual(b"".join(response.streaming_content), PNG)

    def test_download_requires_permission_and_matching_device(self):
        self.post(upload("front.png", PNG))
        attachment = Attachment.objects.get()
        url = reverse("device-attachment-download", args=[self.device.pk, attachment.pk])

        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(logged_in_client(make_user(role_code=None)).get(url).status_code, 403)
        other = make_device(actor=self.officer)
        wrong_device = reverse("device-attachment-download", args=[other.pk, attachment.pk])
        self.assertEqual(self.client.get(wrong_device).status_code, 404)

    def test_media_is_not_served_publicly(self):
        self.post(upload("front.png", PNG))
        path = Attachment.objects.get().file.name
        self.assertEqual(APIClient().get(f"/media/{path}").status_code, 404)

    def test_upload_requires_device_update(self):
        for role, expected in ((RoleCode.DEVICE_ASSESSOR, 403), (RoleCode.OPERATIONS_MANAGER, 201)):
            client = logged_in_client(make_user(role))
            with self.subTest(role=role):
                response = client.post(self.url, {"file": upload("x.png", PNG)}, format="multipart")
                self.assertEqual(response.status_code, expected)
        self.assertEqual(APIClient().post(self.url, {"file": upload("x.png", PNG)}, format="multipart").status_code, 401)

    def test_upload_to_unknown_device_returns_404(self):
        url = reverse("device-attachments", args=[999999])
        self.assertEqual(self.client.post(url, {"file": upload("x.png", PNG)}, format="multipart").status_code, 404)
