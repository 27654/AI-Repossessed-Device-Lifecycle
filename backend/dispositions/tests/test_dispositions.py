from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import DeviceStatus
from devices.services import transition_device
from devices.tests.helpers import make_device
from dispositions.models import Disposition, DispositionStatus
from refurbishment.tests.helpers import device_in

from .helpers import make_disposition, ready_device, reallocation_fields, resale_fields

LIST_URL = reverse("disposition-list")
NON_SALES_ROLES = [
    RoleCode.RECOVERY_OFFICER,
    RoleCode.DEVICE_ASSESSOR,
    RoleCode.REFURBISHMENT_STAFF,
    RoleCode.OPERATIONS_MANAGER,
    RoleCode.SYSTEM_ADMIN,
]


def url(name, disposition):
    return reverse(name, args=[disposition.pk])


class CreateDraftTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = ready_device()

    def post(self, fields):
        return self.client.post(LIST_URL, {"device": self.device.pk, **fields}, format="json")

    def test_create_reallocation_draft(self):
        response = self.post(reallocation_fields())

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertRegex(body["reference"], r"^DSP-\d{4}-\d{5}$")
        self.assertEqual((body["disposition_type"], body["status"]), ("REALLOCATION", "DRAFT"))
        self.assertEqual(body["destination"], "Musanze branch - field sales team")
        self.assertEqual(body["recipient_reference"], "EMP-0451")
        self.assertIsNone(body["sale_price_rwf"])
        self.assertEqual(body["responsible_user"]["id"], self.officer.pk)
        self.assertEqual(body["disposition_date"], timezone.localdate().isoformat())
        self.assertIsNone(body["confirmed_at"])
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.READY_FOR_DISPOSITION)  # a draft never moves the device

    def test_create_resale_draft(self):
        response = self.post(resale_fields())

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["disposition_type"], body["sale_price_rwf"], body["buyer_reference"]),
                         ("RESALE", 65_000, "BUY-2026-0042"))
        self.assertEqual(body["destination"], "")

    def test_creation_is_audited(self):
        response = self.post(resale_fields())
        entry = AuditLog.objects.get(action=AuditAction.DISPOSITION_CREATED)
        self.assertEqual(entry.user, self.officer)
        self.assertEqual((entry.entity_type, entry.entity_id), ("disposition", str(response.json()["id"])))
        self.assertEqual(entry.new_values["sale_price_rwf"], 65_000)
        self.assertEqual(entry.new_values["device_code"], self.device.device_code)

    def test_required_fields(self):
        self.assertIn("disposition_type", self.post({}).json())
        self.assertIn("device", self.client.post(LIST_URL, resale_fields(), format="json").json())

        response = self.post({"disposition_type": "REALLOCATION"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("destination", response.json())

        response = self.post({"disposition_type": "RESALE"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"sale_price_rwf", "buyer_reference"})
        self.assertFalse(Disposition.objects.exists())

    def test_invalid_sale_prices(self):
        for price in (-1, 0, 12.5, "abc", 100_000_001):
            with self.subTest(price=price):
                response = self.post(resale_fields(sale_price_rwf=price))
                self.assertEqual(response.status_code, 400)
                self.assertIn("sale_price_rwf", response.json())

    def test_fields_of_the_other_type_are_rejected(self):
        response = self.post(reallocation_fields(sale_price_rwf=10_000))
        self.assertEqual(response.status_code, 400)
        self.assertIn("sale_price_rwf", response.json())
        response = self.post(resale_fields(destination="Head office"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("destination", response.json())

    def test_people_are_recorded_by_reference_only(self):
        for field, fields in (("buyer_reference", resale_fields(buyer_reference="Jean Bosco Mugisha")),
                              ("recipient_reference", reallocation_fields(recipient_reference="1199880012345678 ID"))):
            with self.subTest(field=field):
                response = self.post(fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_invalid_type_and_future_date(self):
        self.assertIn("disposition_type", self.post(resale_fields(disposition_type="DONATION")).json())
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        response = self.post(resale_fields(disposition_date=tomorrow))
        self.assertEqual(response.status_code, 400)
        self.assertIn("disposition_date", response.json())

    def test_devices_in_other_statuses_are_rejected(self):
        manager = make_user(RoleCode.OPERATIONS_MANAGER)
        devices = [make_device(), device_in(DeviceStatus.RECOVERED), device_in(DeviceStatus.ASSESSED),
                   device_in(DeviceStatus.REFURBISHING)]
        unable = device_in(DeviceStatus.ASSESSED)
        transition_device(unable, DeviceStatus.UNABLE_TO_REPAIR, actor=manager)
        devices.append(unable)
        for final in (DeviceStatus.REALLOCATED, DeviceStatus.RESOLD):
            done = ready_device()
            transition_device(done, final, actor=manager)
            devices.append(done)

        for device in devices:
            device.refresh_from_db()
            with self.subTest(status=device.status):
                response = self.client.post(LIST_URL, {"device": device.pk, **resale_fields()}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("device", response.json())
        self.assertFalse(Disposition.objects.exists())

    def test_one_draft_per_device(self):
        self.assertEqual(self.post(resale_fields()).status_code, 201)
        self.assertEqual(self.post(reallocation_fields()).status_code, 400)

    def test_read_only_fields_are_ignored(self):
        response = self.post(resale_fields(status="CONFIRMED", reference="DSP-FAKE", confirmed_at="2026-01-01T00:00Z"))
        body = response.json()
        self.assertEqual(body["status"], "DRAFT")
        self.assertNotEqual(body["reference"], "DSP-FAKE")
        self.assertIsNone(body["confirmed_at"])


class UpdateDraftTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)
        self.client = logged_in_client(self.officer)
        self.disposition = make_disposition(officer=self.officer)

    def test_update_draft_audits_changes(self):
        response = self.client.patch(url("disposition-detail", self.disposition), {"sale_price_rwf": 70_000},
                                     format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["sale_price_rwf"], 70_000)
        entry = AuditLog.objects.get(action=AuditAction.DISPOSITION_UPDATED)
        self.assertEqual((entry.previous_values, entry.new_values), ({"sale_price_rwf": 65_000}, {"sale_price_rwf": 70_000}))

    def test_switch_type_clears_old_fields(self):
        response = self.client.patch(
            url("disposition-detail", self.disposition),
            {"disposition_type": "REALLOCATION", "destination": "Huye branch"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["disposition_type"], body["destination"]), ("REALLOCATION", "Huye branch"))
        self.assertIsNone(body["sale_price_rwf"])
        self.assertEqual(body["buyer_reference"], "")

    def test_switch_type_requires_new_fields(self):
        response = self.client.patch(url("disposition-detail", self.disposition), {"disposition_type": "REALLOCATION"},
                                     format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("destination", response.json())
        self.disposition.refresh_from_db()
        self.assertEqual(self.disposition.disposition_type, "RESALE")

    def test_retrieve(self):
        for role in (RoleCode.SALES_OFFICER, RoleCode.OPERATIONS_MANAGER, RoleCode.SYSTEM_ADMIN):
            with self.subTest(role=role):
                response = logged_in_client(make_user(role)).get(url("disposition-detail", self.disposition))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["reference"], self.disposition.reference)

    def test_device_cannot_change(self):
        response = self.client.patch(url("disposition-detail", self.disposition), {"device": ready_device().pk},
                                     format="json")
        self.assertEqual(response.status_code, 400)

    def test_put_and_delete_are_refused(self):
        self.assertIn(self.client.put(url("disposition-detail", self.disposition), {}, format="json").status_code,
                      (403, 405))
        self.assertIn(self.client.delete(url("disposition-detail", self.disposition)).status_code, (403, 405))
        self.assertTrue(Disposition.objects.filter(pk=self.disposition.pk).exists())


class PermissionTests(TestCase):
    def setUp(self):
        self.disposition = make_disposition()

    def test_unauthenticated_requests_get_401(self):
        client = APIClient()
        self.assertEqual(client.get(LIST_URL).status_code, 401)
        self.assertEqual(client.post(LIST_URL, {"device": ready_device().pk, **resale_fields()}, format="json").status_code, 401)
        self.assertEqual(client.get(url("disposition-detail", self.disposition)).status_code, 401)
        self.assertEqual(client.patch(url("disposition-detail", self.disposition), {"notes": "x"}, format="json").status_code, 401)
        self.assertEqual(client.post(url("disposition-confirm", self.disposition)).status_code, 401)
        self.assertEqual(client.get(url("disposition-attachments", self.disposition)).status_code, 401)

    def test_only_disposition_create_may_write(self):
        device = ready_device()
        for role in NON_SALES_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.post(LIST_URL, {"device": device.pk, **resale_fields()}, format="json").status_code, 403)
                self.assertEqual(
                    client.patch(url("disposition-detail", self.disposition), {"notes": "x"}, format="json").status_code, 403
                )
                self.assertEqual(client.post(url("disposition-confirm", self.disposition)).status_code, 403)
        self.disposition.refresh_from_db()
        self.assertEqual(self.disposition.status, DispositionStatus.DRAFT)
        self.assertFalse(device.dispositions.exists())

    def test_device_view_roles_can_read(self):
        for role in NON_SALES_ROLES:
            with self.subTest(role=role):
                self.assertEqual(logged_in_client(make_user(role)).get(LIST_URL).status_code, 200)

    def test_user_without_role_cannot_read(self):
        self.assertEqual(logged_in_client(make_user(role_code=None)).get(LIST_URL).status_code, 403)


class ListTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.SALES_OFFICER)
        self.client = logged_in_client(self.officer)
        self.resale = make_disposition(officer=self.officer)
        self.reallocation = make_disposition(officer=self.officer, **reallocation_fields(
            disposition_date=timezone.localdate() - timedelta(days=10)))

    def ids(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.json()["results"]}

    def test_filters(self):
        both = {self.resale.pk, self.reallocation.pk}
        self.assertEqual(self.ids(), both)
        self.assertEqual(self.ids(type="RESALE"), {self.resale.pk})
        self.assertEqual(self.ids(status="DRAFT"), both)
        self.assertEqual(self.ids(status="CONFIRMED"), set())
        self.assertEqual(self.ids(device=self.resale.device_id), {self.resale.pk})
        self.assertEqual(self.ids(search=self.reallocation.device.device_code), {self.reallocation.pk})
        self.assertEqual(self.ids(search="BUY-2026"), {self.resale.pk})
        self.assertEqual(self.ids(date_from=timezone.localdate().isoformat()), {self.resale.pk})
        self.assertEqual(self.ids(date_to=(timezone.localdate() - timedelta(days=5)).isoformat()), {self.reallocation.pk})
        self.assertEqual(self.ids(type="GIFT", status="x", date_from="nonsense"), both)
