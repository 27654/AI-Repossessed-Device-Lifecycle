from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from ai_engine import services as ai_services
from assessments.tests.helpers import submitted_assessment
from audit.models import AuditAction, AuditLog
from devices.models import DeviceStatus
from devices.tests.helpers import make_device
from refurbishment.models import RefurbishmentWorkOrder, WorkOrderStatus

from .helpers import device_in, make_work_order, refurbishing_device

LIST_URL = reverse("work-order-list")
NON_REFURB_ROLES = [
    RoleCode.RECOVERY_OFFICER,
    RoleCode.DEVICE_ASSESSOR,
    RoleCode.SALES_OFFICER,
    RoleCode.OPERATIONS_MANAGER,
    RoleCode.SYSTEM_ADMIN,
]


def url(name, work_order):
    return reverse(name, args=[work_order.pk])


class WorkOrderCreateTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.device = refurbishing_device()

    def post(self, **extra):
        return self.client.post(
            LIST_URL,
            {"device": self.device.pk, "diagnosis": "Cracked screen.", "estimated_cost_rwf": 25_000, **extra},
            format="json",
        )

    def test_create_for_refurbishing_device(self):
        response = self.post()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertRegex(body["reference"], r"^REF-\d{4}-\d{5}$")
        self.assertEqual(body["status"], WorkOrderStatus.OPEN)
        self.assertEqual(body["created_by"]["id"], self.technician.pk)
        self.assertIsNone(body["assigned_to"])
        self.assertEqual((body["estimated_cost_rwf"], body["parts_cost_rwf"], body["total_cost_rwf"]), (25_000, 0, 0))
        self.assertIsNone(body["actual_cost_rwf"])
        self.assertEqual((body["steps"], body["items"], body["attachments"]), ([], [], []))
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.REFURBISHING)  # creating does not move the device

    def test_creation_is_audited(self):
        response = self.post()
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_CREATED)
        self.assertEqual(entry.user, self.technician)
        self.assertEqual((entry.entity_type, entry.entity_id), ("work_order", str(response.json()["id"])))
        self.assertEqual(entry.new_values["device_code"], self.device.device_code)

    def test_references_are_unique(self):
        first = self.post().json()["reference"]
        other = make_work_order()
        self.assertNotEqual(first, other.reference)

    def test_wrong_lifecycle_status_rejected(self):
        officer = make_user(RoleCode.RECOVERY_OFFICER)
        devices = [
            make_device(actor=officer),  # IN_RECOVERY
            device_in(DeviceStatus.RECOVERED),
            device_in(DeviceStatus.ASSESSED),
        ]
        manager = make_user(RoleCode.OPERATIONS_MANAGER)
        from devices.services import transition_device

        for target in (DeviceStatus.READY_FOR_DISPOSITION, DeviceStatus.UNABLE_TO_REPAIR):
            device = device_in(DeviceStatus.ASSESSED)
            transition_device(device, target, actor=manager)
            devices.append(device)
        resold = device_in(DeviceStatus.ASSESSED)
        transition_device(resold, DeviceStatus.READY_FOR_DISPOSITION, actor=manager)
        transition_device(resold, DeviceStatus.RESOLD, actor=manager)
        devices.append(resold)

        for device in devices:
            with self.subTest(status=device.status):
                device.refresh_from_db()
                response = self.client.post(LIST_URL, {"device": device.pk}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("device", response.json())
        self.assertFalse(RefurbishmentWorkOrder.objects.exists())

    def test_one_active_work_order_per_device(self):
        self.assertEqual(self.post().status_code, 201)
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.work_orders.count(), 1)

    def test_assignee_must_be_refurbishment_staff(self):
        colleague = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.assertEqual(self.post(assigned_to=colleague.pk).json()["assigned_to"]["id"], colleague.pk)

        other_device = refurbishing_device()
        for assignee in (make_user(RoleCode.SALES_OFFICER), make_user(RoleCode.REFURBISHMENT_STAFF,
                                                                     account_status=User.Status.SUSPENDED)):
            with self.subTest(assignee=assignee.email):
                response = self.client.post(LIST_URL, {"device": other_device.pk, "assigned_to": assignee.pk}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("assigned_to", response.json())

    def test_money_validation(self):
        for value in (-1, 2.5, 100_000_001):
            with self.subTest(value=value):
                self.assertEqual(self.post(estimated_cost_rwf=value).status_code, 400)

    def test_closure_fields_cannot_be_set_on_create(self):
        response = self.post(status="COMPLETED", actual_cost_rwf=1, labour_cost_rwf=9, work_summary="x")
        body = response.json()
        self.assertEqual(body["status"], "OPEN")
        self.assertIsNone(body["actual_cost_rwf"])
        self.assertIsNone(body["labour_cost_rwf"])
        self.assertEqual(body["work_summary"], "")

    def test_ai_does_not_create_work_orders(self):
        """The AI recommends REFURBISH; only a human decision and a human-created work order follow."""
        manager = make_user(RoleCode.OPERATIONS_MANAGER)
        assessment = submitted_assessment()
        recommendation, _ = ai_services.generate_recommendation(assessment, actor=manager)
        self.assertEqual(recommendation.recommendation, "REFURBISH")
        self.assertFalse(RefurbishmentWorkOrder.objects.filter(device=assessment.device).exists())

        ai_services.record_decision(assessment, actor=manager, final_decision="REFURBISH")
        assessment.device.refresh_from_db()
        self.assertEqual(assessment.device.status, DeviceStatus.REFURBISHING)
        self.assertFalse(RefurbishmentWorkOrder.objects.filter(device=assessment.device).exists())


class WorkOrderUpdateAndStartTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = make_work_order(technician=self.technician)

    def test_update_active_work_order_audits_changes(self):
        response = self.client.patch(
            url("work-order-detail", self.work_order),
            {"diagnosis": "Screen and charging port.", "estimated_cost_rwf": 40_000, "labour_cost_rwf": 6_000},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["total_cost_rwf"], 6_000)
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_UPDATED)
        self.assertEqual(entry.previous_values["estimated_cost_rwf"], 30_000)
        self.assertEqual(entry.new_values["labour_cost_rwf"], 6_000)
        self.assertEqual(set(entry.new_values), {"diagnosis", "estimated_cost_rwf", "labour_cost_rwf"})

    def test_reassign(self):
        colleague = make_user(RoleCode.REFURBISHMENT_STAFF)
        response = self.client.patch(url("work-order-detail", self.work_order), {"assigned_to": colleague.pk}, format="json")
        self.assertEqual(response.json()["assigned_to"], {"id": colleague.pk, "full_name": colleague.full_name})
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_UPDATED)
        self.assertEqual(entry.new_values["assigned_to"]["id"], colleague.pk)

    def test_device_cannot_change(self):
        response = self.client.patch(
            url("work-order-detail", self.work_order), {"device": refurbishing_device().pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_start(self):
        response = self.client.post(url("work-order-start", self.work_order))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], WorkOrderStatus.IN_PROGRESS)
        self.assertIsNotNone(body["started_at"])
        self.assertEqual(body["assigned_to"]["id"], self.technician.pk)  # unassigned work goes to the starter
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_STARTED)
        self.assertEqual(entry.new_values["status"], "IN_PROGRESS")

    def test_start_twice_rejected(self):
        self.client.post(url("work-order-start", self.work_order))
        self.assertEqual(self.client.post(url("work-order-start", self.work_order)).status_code, 400)

    def test_start_keeps_existing_assignee(self):
        colleague = make_user(RoleCode.REFURBISHMENT_STAFF)
        work_order = make_work_order(technician=self.technician, assigned_to=colleague)
        body = self.client.post(url("work-order-start", work_order)).json()
        self.assertEqual(body["assigned_to"]["id"], colleague.pk)


class WorkOrderPermissionTests(TestCase):
    def setUp(self):
        self.work_order = make_work_order()

    def test_unauthenticated_get_401(self):
        client = APIClient()
        for method, name in (("get", "work-order-list"), ("get", "work-order-detail"), ("post", "work-order-start"),
                             ("post", "work-order-complete"), ("post", "work-order-unable-to-repair"),
                             ("post", "work-order-cancel"), ("get", "work-order-steps"), ("get", "work-order-items")):
            with self.subTest(name=name):
                target = reverse(name) if name == "work-order-list" else url(name, self.work_order)
                self.assertEqual(getattr(client, method)(target).status_code, 401)

    def test_other_roles_cannot_manage(self):
        device = refurbishing_device()
        for role in NON_REFURB_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.post(LIST_URL, {"device": device.pk}, format="json").status_code, 403)
                self.assertEqual(
                    client.patch(url("work-order-detail", self.work_order), {"diagnosis": "x"}, format="json").status_code,
                    403,
                )
                for name in ("work-order-start", "work-order-complete", "work-order-unable-to-repair", "work-order-cancel"):
                    self.assertEqual(client.post(url(name, self.work_order), {"reason": "x"}, format="json").status_code, 403)
                self.assertEqual(
                    client.post(url("work-order-steps", self.work_order), {"step_type": "CLEANING"}, format="json").status_code,
                    403,
                )
                self.assertEqual(
                    client.post(
                        url("work-order-items", self.work_order),
                        {"item_name": "Glue", "quantity": 1, "unit_cost_rwf": 100},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(client.get(reverse("work-order-technicians")).status_code, 403)
        self.work_order.refresh_from_db()
        self.assertEqual(self.work_order.status, WorkOrderStatus.OPEN)
        self.assertFalse(device.work_orders.exists())

    def test_device_view_roles_can_read(self):
        for role in NON_REFURB_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.get(LIST_URL).status_code, 200)
                self.assertEqual(client.get(url("work-order-detail", self.work_order)).status_code, 200)
                self.assertEqual(client.get(url("work-order-steps", self.work_order)).status_code, 200)

    def test_user_without_role_cannot_read(self):
        self.assertEqual(logged_in_client(make_user(role_code=None)).get(LIST_URL).status_code, 403)


class WorkOrderListTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.mine = make_work_order(technician=self.technician, assigned_to=self.technician)
        self.other = make_work_order()
        from refurbishment import services

        services.cancel_work_order(self.other, actor=self.technician, reason="Opened by mistake")

    def ids(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.json()["results"]}

    def test_filters(self):
        self.assertEqual(self.ids(), {self.mine.pk, self.other.pk})
        self.assertEqual(self.ids(device=self.mine.device_id), {self.mine.pk})
        self.assertEqual(self.ids(status="OPEN"), {self.mine.pk})
        self.assertEqual(self.ids(status="ACTIVE"), {self.mine.pk})
        self.assertEqual(self.ids(status="CANCELLED"), {self.other.pk})
        self.assertEqual(self.ids(assigned_to="me"), {self.mine.pk})
        self.assertEqual(self.ids(assigned_to=self.technician.pk), {self.mine.pk})
        self.assertEqual(self.ids(search=self.other.reference), {self.other.pk})
        self.assertEqual(self.ids(status="BOGUS", device="x"), {self.mine.pk, self.other.pk})

    def test_technicians_list(self):
        make_user(RoleCode.SALES_OFFICER)
        suspended = make_user(RoleCode.REFURBISHMENT_STAFF, account_status=User.Status.SUSPENDED)
        names = {t["id"] for t in self.client.get(reverse("work-order-technicians")).json()}
        self.assertIn(self.technician.pk, names)
        self.assertNotIn(suspended.pk, names)
        self.assertTrue(all(User.objects.get(pk=pk).role.code == RoleCode.REFURBISHMENT_STAFF for pk in names))
