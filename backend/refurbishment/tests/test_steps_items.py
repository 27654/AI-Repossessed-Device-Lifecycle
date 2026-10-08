from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import Attachment
from devices.tests.helpers import TempMediaMixin
from refurbishment import services
from refurbishment.models import RefurbishmentItem, StepStatus

from .helpers import make_work_order, ready_to_complete, started_work_order

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def step_url(step):
    return reverse("work-order-step-detail", args=[step.pk])


def item_url(item):
    return reverse("work-order-item-detail", args=[item.pk])


class StepTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = started_work_order(technician=self.technician)
        self.steps_url = reverse("work-order-steps", args=[self.work_order.pk])

    def add(self, step_type="CLEANING", **extra):
        return self.client.post(self.steps_url, {"step_type": step_type, **extra}, format="json")

    def test_add_step(self):
        response = self.add(description="Clean housing and ports")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["step_type_label"]), ("PENDING", "Cleaning"))
        self.assertIsNone(body["started_at"])
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_STEP_CREATED)
        self.assertEqual(entry.new_values["step_type"], "CLEANING")

    def test_invalid_step_type(self):
        self.assertEqual(self.add(step_type="PAINTING").status_code, 400)

    def test_step_lifecycle_sets_timestamps_and_performer(self):
        step_id = self.add().json()["id"]
        url = reverse("work-order-step-detail", args=[step_id])

        started = self.client.patch(url, {"status": "IN_PROGRESS"}, format="json").json()
        self.assertEqual(started["status"], "IN_PROGRESS")
        self.assertIsNotNone(started["started_at"])
        self.assertIsNone(started["completed_at"])

        done = self.client.patch(url, {"status": "COMPLETED", "notes": "Cleaned."}, format="json").json()
        self.assertEqual(done["status"], "COMPLETED")
        self.assertIsNotNone(done["completed_at"])
        self.assertGreaterEqual(done["completed_at"], done["started_at"])
        self.assertEqual(done["performed_by"]["id"], self.technician.pk)
        entries = AuditLog.objects.filter(action=AuditAction.REFURBISHMENT_STEP_UPDATED).order_by("id")
        self.assertEqual([e.new_values["status"] for e in entries], ["IN_PROGRESS", "COMPLETED"])

    def test_pending_can_complete_directly(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="SOFTWARE_RESET")
        body = self.client.patch(step_url(step), {"status": "COMPLETED"}, format="json").json()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertIsNotNone(body["started_at"])

    def test_skip_requires_reason(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="PORT_REPAIR")
        response = self.client.patch(step_url(step), {"status": "SKIPPED"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("notes", response.json())

        body = self.client.patch(step_url(step), {"status": "SKIPPED", "notes": "Port works after cleaning."},
                                 format="json").json()
        self.assertEqual(body["status"], "SKIPPED")

    def test_finished_steps_are_final(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="CLEANING")
        services.update_step(step, actor=self.technician, changes={"status": StepStatus.COMPLETED})
        for change in ({"status": "PENDING"}, {"status": "IN_PROGRESS"}, {"notes": "rewrite"}, {"description": "x"}):
            with self.subTest(change=change):
                self.assertEqual(self.client.patch(step_url(step), change, format="json").status_code, 400)

    def test_invalid_status_value(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="CLEANING")
        self.assertEqual(self.client.patch(step_url(step), {"status": "DONE"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(step_url(step), {"status": "PENDING"}, format="json").status_code, 200)

    def test_progress_requires_started_work_order(self):
        work_order = make_work_order(technician=self.technician)  # OPEN
        step = services.add_step(work_order, actor=self.technician, step_type="CLEANING")  # planning is allowed
        response = self.client.patch(step_url(step), {"status": "IN_PROGRESS"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())

    def test_no_steps_on_closed_work_order(self):
        services.cancel_work_order(self.work_order, actor=self.technician, reason="Wrong device")
        self.assertEqual(self.add().status_code, 400)

    def test_step_update_requires_permission(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="CLEANING")
        self.assertEqual(APIClient().patch(step_url(step), {"status": "COMPLETED"}, format="json").status_code, 401)
        client = logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR))
        self.assertEqual(client.patch(step_url(step), {"status": "COMPLETED"}, format="json").status_code, 403)


class ItemTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = started_work_order(technician=self.technician)
        self.items_url = reverse("work-order-items", args=[self.work_order.pk])

    def add(self, **fields):
        payload = {"item_name": "Battery", "part_number": "BL-5C", "quantity": 2, "unit_cost_rwf": 7_500,
                   "supplier": "Kigali Parts Ltd", **fields}
        return self.client.post(self.items_url, payload, format="json")

    def test_add_item_calculates_total(self):
        response = self.add()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["total_cost_rwf"], 15_000)
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_ITEM_CREATED)
        self.assertEqual(entry.new_values["total_cost_rwf"], 15_000)

    def test_client_cannot_set_total(self):
        self.assertEqual(self.add(total_cost_rwf=1).json()["total_cost_rwf"], 15_000)

    def test_quantity_and_cost_validation(self):
        for field, value in (("quantity", 0), ("quantity", -1), ("quantity", 1.5), ("unit_cost_rwf", -1),
                             ("unit_cost_rwf", 9.99), ("unit_cost_rwf", 100_000_001), ("item_name", "  ")):
            with self.subTest(field=field, value=value):
                response = self.add(**{field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertFalse(RefurbishmentItem.objects.exists())

    def test_update_item_recalculates_and_audits(self):
        item_id = self.add().json()["id"]
        response = self.client.patch(reverse("work-order-item-detail", args=[item_id]), {"quantity": 3}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["total_cost_rwf"], 22_500)
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_ITEM_UPDATED)
        self.assertEqual(entry.previous_values, {"quantity": 2, "total_cost_rwf": 15_000})
        self.assertEqual(entry.new_values, {"quantity": 3, "total_cost_rwf": 22_500})

    def test_work_order_totals(self):
        self.add()
        self.add(item_name="Screen", quantity=1, unit_cost_rwf=20_000)
        services.update_work_order(self.work_order, actor=self.technician, changes={"labour_cost_rwf": 4_000})
        body = self.client.get(reverse("work-order-detail", args=[self.work_order.pk])).json()
        self.assertEqual(body["parts_cost_rwf"], 35_000)
        self.assertEqual(body["total_cost_rwf"], 39_000)

    def test_items_frozen_after_closure(self):
        item = services.add_item(self.work_order, actor=self.technician, item_name="Glue", quantity=1, unit_cost_rwf=300)
        services.cancel_work_order(self.work_order, actor=self.technician, reason="Duplicate")
        self.assertEqual(self.client.patch(item_url(item), {"quantity": 5}, format="json").status_code, 400)
        self.assertEqual(self.add().status_code, 400)


class EvidenceTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = started_work_order(technician=self.technician)
        self.url = reverse("work-order-attachments", args=[self.work_order.pk])

    def post(self, client=None, name="after.png", content=PNG):
        file = SimpleUploadedFile(name, content, content_type="image/png")
        return (client or self.client).post(self.url, {"file": file, "description": "After repair"}, format="multipart")

    def test_upload_evidence(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["refurbishment"], body["refurbishment_reference"]),
                         (self.work_order.pk, self.work_order.reference))
        self.assertIsNone(body["assessment"])
        entry = AuditLog.objects.get(action=AuditAction.ATTACHMENT_UPLOADED)
        self.assertEqual(entry.new_values["work_order_reference"], self.work_order.reference)

    def test_evidence_preserved_after_completion(self):
        work_order, technician = ready_to_complete()
        client = logged_in_client(technician)
        url = reverse("work-order-attachments", args=[work_order.pk])
        upload = client.post(url, {"file": SimpleUploadedFile("qc.pdf", b"%PDF-1.4\n" + b"0" * 40)}, format="multipart")
        self.assertEqual(upload.status_code, 201)
        services.complete_work_order(work_order, actor=technician)

        listed = client.get(url).json()
        self.assertEqual(len(listed), 1)
        reader = logged_in_client(make_user(RoleCode.SALES_OFFICER))
        self.assertEqual(reader.get(listed[0]["download_url"]).status_code, 200)
        self.assertEqual(APIClient().get(listed[0]["download_url"]).status_code, 401)
        # Closed: no new evidence on the work order.
        late = client.post(url, {"file": SimpleUploadedFile("late.png", PNG)}, format="multipart")
        self.assertEqual(late.status_code, 400)

    def test_file_checks_still_apply(self):
        self.assertEqual(self.post(name="x.exe", content=b"MZ" + b"\0" * 40).status_code, 400)
        self.assertEqual(self.post(name="x.pdf").status_code, 400)
        self.assertFalse(Attachment.objects.exists())

    def test_evidence_permissions(self):
        for role in (RoleCode.DEVICE_ASSESSOR, RoleCode.OPERATIONS_MANAGER, RoleCode.SYSTEM_ADMIN):
            with self.subTest(role=role):
                self.assertEqual(self.post(client=logged_in_client(make_user(role))).status_code, 403)
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR)).get(self.url).status_code, 200)

    def test_evidence_cannot_link_two_records(self):
        from rest_framework.exceptions import ValidationError

        from assessments.tests.helpers import recovered_device
        from devices import services as device_services

        with self.assertRaises(ValidationError):
            device_services.add_attachment(
                recovered_device(),
                actor=self.technician,
                upload=SimpleUploadedFile("x.png", PNG),
                mime_type="image/png",
                original_name="x.png",
                refurbishment=self.work_order,
            )
