from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import Device, DeviceStatus

from .helpers import device_payload, make_device, valid_imei

LIST_URL = reverse("device-list")


class DeviceCreateTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)

    def create(self, **overrides):
        return self.client.post(LIST_URL, device_payload(**overrides), format="json")

    def test_create_device(self):
        response = self.create(make="Samsung", model="Galaxy A14")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertRegex(body["device_code"], r"^YRW-\d{4}-\d{5}$")
        self.assertEqual(body["status"], "IN_RECOVERY")
        self.assertEqual(body["lifecycle_stage"], "Recovery")
        self.assertEqual(body["created_by"]["id"], self.officer.pk)
        device = Device.objects.get(pk=body["id"])
        self.assertEqual(device.make, "Samsung")
        self.assertEqual(device.status_changes.count(), 1)

    def test_creation_is_audited(self):
        body = self.create().json()

        entry = AuditLog.objects.get(action=AuditAction.DEVICE_CREATED)
        self.assertEqual(entry.user, self.officer)
        self.assertEqual(entry.entity_type, "device")
        self.assertEqual(entry.entity_id, str(body["id"]))
        self.assertEqual(entry.new_values["device_code"], body["device_code"])
        self.assertEqual(entry.new_values["status"], "IN_RECOVERY")

    def test_device_codes_are_unique(self):
        codes = {self.create().json()["device_code"] for _ in range(3)}
        self.assertEqual(len(codes), 3)

    def test_initial_status_can_be_recovered(self):
        self.assertEqual(self.create(initial_status="RECOVERED").json()["status"], "RECOVERED")

    def test_initial_status_cannot_skip_the_lifecycle(self):
        response = self.create(initial_status="RESOLD")
        self.assertEqual(response.status_code, 400)
        self.assertIn("initial_status", response.json())

    def test_status_and_condition_cannot_be_set_directly(self):
        body = self.create(status="RESOLD", current_condition="EXCELLENT").json()
        self.assertEqual(body["status"], "IN_RECOVERY")
        self.assertIsNone(body["current_condition"])

    def test_duplicate_imei_is_rejected(self):
        imei = valid_imei()
        self.create(imei=imei)

        response = self.create(imei=f"{imei[:5]} {imei[5:]}")  # same IMEI typed with a space

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["imei"], ["A device with this IMEI already exists."])

    def test_duplicate_serial_number_is_rejected_case_insensitively(self):
        self.create(serial_number="ab123x")

        response = self.create(serial_number=" AB123X ")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["serial_number"], ["A device with this serial number already exists."])

    def test_imei_must_be_valid(self):
        for imei in ("12345", "35000000000000A", "350000000000001"):  # short, letters, bad check digit
            with self.subTest(imei=imei):
                self.assertEqual(self.create(imei=imei).status_code, 400)

    def test_imei_or_serial_is_required(self):
        response = self.create(imei="", serial_number="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("imei", response.json())

    def test_device_without_imei_is_allowed(self):
        response = self.create(imei="", device_type="SOLAR_HOME_SYSTEM")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["imei"])

    def test_required_fields(self):
        response = self.client.post(LIST_URL, {"imei": valid_imei()}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue({"make", "model", "device_type"} <= set(response.json()))

    def test_customer_reference_must_be_pseudonymous(self):
        for ref in ("Jean Claude Uwimana", "1 1990 8 0012345 0 12"):
            with self.subTest(ref=ref):
                response = self.create(previous_owner_ref=ref)
                self.assertEqual(response.status_code, 400)
                self.assertIn("previous_owner_ref", response.json())


class DeviceReadUpdateTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer, current_location="Kigali")
        self.url = reverse("device-detail", args=[self.device.pk])

    def test_retrieve_device(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["device_code"], self.device.device_code)
        self.assertEqual(response.json()["status_label"], "In recovery")

    def test_unknown_device_returns_404(self):
        self.assertEqual(self.client.get(reverse("device-detail", args=[999999])).status_code, 404)

    def test_update_device_is_audited_with_changes(self):
        response = self.client.patch(self.url, {"current_location": "Musanze depot", "color": "Blue"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_location"], "Musanze depot")
        entry = AuditLog.objects.get(action=AuditAction.DEVICE_UPDATED)
        self.assertEqual(entry.previous_values, {"color": "Black", "current_location": "Kigali"})
        self.assertEqual(entry.new_values, {"color": "Blue", "current_location": "Musanze depot"})

    def test_update_without_changes_is_not_audited(self):
        self.client.patch(self.url, {"current_location": "Kigali"}, format="json")
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DEVICE_UPDATED).exists())

    def test_update_cannot_change_status(self):
        self.client.patch(self.url, {"status": "RESOLD", "device_code": "HACKED"}, format="json")

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.IN_RECOVERY)
        self.assertNotEqual(self.device.device_code, "HACKED")

    def test_update_to_duplicate_imei_is_rejected(self):
        other = make_device(actor=self.officer)
        response = self.client.patch(self.url, {"imei": other.imei}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_update_cannot_remove_both_identifiers(self):
        response = self.client.patch(self.url, {"imei": "", "serial_number": ""}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_put_and_delete_are_not_available(self):
        self.assertIn(self.client.delete(self.url).status_code, (403, 405))
        self.assertIn(self.client.put(self.url, device_payload(), format="json").status_code, (403, 405))
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())


class DevicePermissionTests(TestCase):
    def setUp(self):
        self.device = make_device()
        self.detail = reverse("device-detail", args=[self.device.pk])

    def test_unauthenticated_requests_get_401(self):
        client = APIClient()
        for url in (
            LIST_URL,
            self.detail,
            reverse("device-history", args=[self.device.pk]),
            reverse("device-attachments", args=[self.device.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(client.post(LIST_URL, device_payload(), format="json").status_code, 401)

    def test_every_role_with_device_view_can_read(self):
        for role in RoleCode.values:
            client = logged_in_client(make_user(role))
            with self.subTest(role=role):
                self.assertEqual(client.get(LIST_URL).status_code, 200)
                self.assertEqual(client.get(self.detail).status_code, 200)

    def test_user_without_device_view_is_forbidden(self):
        client = logged_in_client(make_user(role_code=None))
        self.assertEqual(client.get(LIST_URL).status_code, 403)
        self.assertEqual(client.get(self.detail).status_code, 403)

    def test_only_device_create_can_register(self):
        for role, expected in (
            (RoleCode.RECOVERY_OFFICER, 201),
            (RoleCode.DEVICE_ASSESSOR, 403),
            (RoleCode.OPERATIONS_MANAGER, 403),
            (RoleCode.SYSTEM_ADMIN, 403),
        ):
            client = logged_in_client(make_user(role))
            with self.subTest(role=role):
                self.assertEqual(client.post(LIST_URL, device_payload(), format="json").status_code, expected)

    def test_only_device_update_can_edit(self):
        for role, expected in (
            (RoleCode.RECOVERY_OFFICER, 200),
            (RoleCode.OPERATIONS_MANAGER, 200),
            (RoleCode.DEVICE_ASSESSOR, 403),
            (RoleCode.SALES_OFFICER, 403),
            (RoleCode.SYSTEM_ADMIN, 403),
        ):
            client = logged_in_client(make_user(role))
            with self.subTest(role=role):
                response = client.patch(self.detail, {"notes": f"edited by {role}"}, format="json")
                self.assertEqual(response.status_code, expected)


class DeviceListFilterTests(TestCase):
    def setUp(self):
        self.client = logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR))
        officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.tecno = make_device(actor=officer, make="Tecno", model="Spark 10")
        self.samsung = make_device(actor=officer, make="Samsung", model="Galaxy A14", initial_status="RECOVERED")
        self.solar = make_device(actor=officer, make="SunKing", model="Home 400", device_type="SOLAR_HOME_SYSTEM", imei="")
        Device.objects.filter(pk=self.tecno.pk).update(recovery_date="2026-08-01", current_condition="GOOD")
        Device.objects.filter(pk=self.samsung.pk).update(recovery_date="2026-09-20")

    def codes(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return {item["device_code"] for item in response.json()["results"]}

    def test_search_matches_identifiers_and_names(self):
        self.assertEqual(self.codes(search=self.tecno.imei[-6:]), {self.tecno.device_code})
        self.assertEqual(self.codes(search="galaxy"), {self.samsung.device_code})
        self.assertEqual(self.codes(search=self.solar.device_code), {self.solar.device_code})

    def test_status_filter_accepts_several_values(self):
        self.assertEqual(self.codes(status="RECOVERED"), {self.samsung.device_code})
        self.assertEqual(len(self.codes(status="RECOVERED,IN_RECOVERY")), 3)

    def test_make_condition_and_type_filters(self):
        self.assertEqual(self.codes(make="tecno"), {self.tecno.device_code})
        self.assertEqual(self.codes(condition="GOOD"), {self.tecno.device_code})
        self.assertEqual(self.codes(device_type="SOLAR_HOME_SYSTEM"), {self.solar.device_code})

    def test_recovery_date_range(self):
        self.assertEqual(self.codes(recovered_from="2026-09-01"), {self.samsung.device_code})
        self.assertEqual(self.codes(recovered_to="2026-08-31"), {self.tecno.device_code})
        self.assertEqual(len(self.codes(recovered_from="2026-02-30")), 3)  # invalid date is ignored

    def test_list_is_paginated(self):
        officer = make_user(RoleCode.RECOVERY_OFFICER)
        for _ in range(22):
            make_device(actor=officer)

        first = self.client.get(LIST_URL).json()
        second = self.client.get(LIST_URL, {"page": 2}).json()

        self.assertEqual(first["count"], 25)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(len(second["results"]), 5)
        self.assertIsNotNone(first["next"])
