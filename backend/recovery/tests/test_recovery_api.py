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
from recovery.models import Recovery, RecoveryStatus

from .helpers import make_recovery, recovery_payload

LIST_URL = reverse("recovery-list")
NON_RECOVERY_ROLES = [
    RoleCode.DEVICE_ASSESSOR,
    RoleCode.REFURBISHMENT_STAFF,
    RoleCode.SALES_OFFICER,
    RoleCode.OPERATIONS_MANAGER,
    RoleCode.SYSTEM_ADMIN,
]


def detail_url(recovery):
    return reverse("recovery-detail", args=[recovery.pk])


def complete_url(recovery):
    return reverse("recovery-complete", args=[recovery.pk])


class RecoveryCreateTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer)

    def test_officer_records_recovery(self):
        response = self.client.post(LIST_URL, recovery_payload(self.device), format="json")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertRegex(body["reference"], r"^RCV-\d{4}-\d{5}$")
        self.assertEqual(body["status"], RecoveryStatus.IN_PROGRESS)
        self.assertEqual(body["recovery_officer"]["id"], self.officer.pk)
        self.assertEqual(body["device_summary"]["device_code"], self.device.device_code)
        self.assertEqual(body["outcome"], "RECOVERED")
        self.assertIsNone(body["completed_at"])
        # Recording a recovery does not move the device; completing it does.
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.IN_RECOVERY)

    def test_creation_is_audited(self):
        response = self.client.post(LIST_URL, recovery_payload(self.device), format="json")

        entry = AuditLog.objects.get(action=AuditAction.RECOVERY_CREATED)
        self.assertEqual(entry.user, self.officer)
        self.assertEqual((entry.entity_type, entry.entity_id), ("recovery", str(response.json()["id"])))
        self.assertEqual(entry.new_values["recovery_location"], "Nyarugenge, Kigali")
        self.assertEqual(entry.new_values["device_code"], self.device.device_code)

    def test_outcome_may_be_left_for_later(self):
        payload = recovery_payload(self.device)
        payload.pop("outcome")
        response = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["outcome"], "")

    def test_required_fields(self):
        response = self.client.post(LIST_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()), {"device", "recovered_at", "recovery_location", "recovery_method"}
        )
        self.assertFalse(Recovery.objects.exists())

    def test_blank_location_and_invalid_choices_are_rejected(self):
        for field, value in (
            ("recovery_location", "   "),
            ("recovery_method", "TELEPORT"),
            ("outcome", "LOST"),
            ("recovered_at", "not-a-date"),
        ):
            with self.subTest(field=field):
                response = self.client.post(LIST_URL, recovery_payload(self.device, **{field: value}), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_future_recovery_time_is_rejected(self):
        future = timezone.now() + timedelta(days=1)
        response = self.client.post(LIST_URL, recovery_payload(self.device, recovered_at=future), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("recovered_at", response.json())

    def test_unknown_device_is_rejected(self):
        payload = recovery_payload(self.device)
        payload["device"] = 999999
        response = self.client.post(LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("device", response.json())

    def test_device_must_be_in_recovery(self):
        recovered = make_device(actor=self.officer, initial_status=DeviceStatus.RECOVERED)
        response = self.client.post(LIST_URL, recovery_payload(recovered), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("device", response.json())
        self.assertFalse(Recovery.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.RECOVERY_CREATED).exists())

    def test_only_one_open_recovery_per_device(self):
        make_recovery(self.device, self.officer)
        response = self.client.post(LIST_URL, recovery_payload(self.device), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.recoveries.count(), 1)

    def test_read_only_fields_are_ignored(self):
        payload = recovery_payload(self.device, status="COMPLETED", reference="RCV-FAKE", completed_at="2026-01-01T00:00Z")
        response = self.client.post(LIST_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], RecoveryStatus.IN_PROGRESS)
        self.assertNotEqual(response.json()["reference"], "RCV-FAKE")
        self.assertIsNone(response.json()["completed_at"])


class RecoveryUpdateTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer)
        self.recovery = make_recovery(self.device, self.officer)

    def test_update_open_recovery_audits_changed_fields_only(self):
        response = self.client.patch(
            detail_url(self.recovery),
            {"recovery_location": "Musanze", "notes": "Customer was cooperative.", "recovery_method": "FIELD_COLLECTION"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["recovery_location"], "Musanze")
        entry = AuditLog.objects.get(action=AuditAction.RECOVERY_UPDATED)
        self.assertEqual(entry.previous_values, {"recovery_location": "Nyarugenge, Kigali", "notes": ""})
        self.assertEqual(entry.new_values, {"recovery_location": "Musanze", "notes": "Customer was cooperative."})

    def test_unchanged_update_writes_no_audit(self):
        response = self.client.patch(detail_url(self.recovery), {"recovery_location": "Nyarugenge, Kigali"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.RECOVERY_UPDATED).exists())

    def test_device_cannot_be_changed(self):
        other = make_device(actor=self.officer)
        response = self.client.patch(detail_url(self.recovery), {"device": other.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.recovery.refresh_from_db()
        self.assertEqual(self.recovery.device, self.device)

    def test_status_cannot_be_set_through_update(self):
        response = self.client.patch(detail_url(self.recovery), {"status": "COMPLETED"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.recovery.refresh_from_db()
        self.assertEqual(self.recovery.status, RecoveryStatus.IN_PROGRESS)

    def test_completed_recovery_cannot_be_edited(self):
        self.client.post(complete_url(self.recovery))
        response = self.client.patch(detail_url(self.recovery), {"recovery_location": "Elsewhere"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.recovery.refresh_from_db()
        self.assertEqual(self.recovery.recovery_location, "Nyarugenge, Kigali")

    def test_put_and_delete_are_refused(self):
        # Methods without a permission mapping are denied (403) before the 405 check.
        self.assertIn(self.client.put(detail_url(self.recovery), {}, format="json").status_code, (403, 405))
        self.assertIn(self.client.delete(detail_url(self.recovery)).status_code, (403, 405))
        self.assertTrue(Recovery.objects.filter(pk=self.recovery.pk).exists())


class RecoveryCompletionTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device = make_device(actor=self.officer, recovery_reference="")

    def complete(self, recovery):
        return self.client.post(complete_url(recovery))

    def test_successful_recovery_moves_device_to_recovered(self):
        recovery = make_recovery(self.device, self.officer)
        response = self.complete(recovery)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], RecoveryStatus.COMPLETED)
        self.assertEqual(body["completed_by"]["id"], self.officer.pk)
        self.assertIsNotNone(body["completed_at"])
        self.assertEqual(body["device_summary"]["status"], DeviceStatus.RECOVERED)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)
        change = self.device.status_changes.get(to_status=DeviceStatus.RECOVERED)
        self.assertEqual(change.from_status, DeviceStatus.IN_RECOVERY)
        self.assertEqual((change.source_type, change.source_id), ("recovery", recovery.pk))
        self.assertEqual(change.changed_by, self.officer)
        self.assertIn(recovery.reference, change.reason)

    def test_completion_is_audited_with_status_change(self):
        recovery = make_recovery(self.device, self.officer)
        self.complete(recovery)

        completed = AuditLog.objects.get(action=AuditAction.RECOVERY_COMPLETED)
        self.assertEqual(completed.user, self.officer)
        self.assertEqual(completed.entity_id, str(recovery.pk))
        self.assertEqual(completed.previous_values, {"status": "IN_PROGRESS"})
        self.assertEqual(completed.new_values["outcome"], "RECOVERED")
        status_entry = AuditLog.objects.get(action=AuditAction.DEVICE_STATUS_CHANGED)
        self.assertEqual(status_entry.new_values, {"status": "RECOVERED", "source_type": "recovery", "source_id": recovery.pk})

    def test_completion_syncs_device_recovery_date_and_reference(self):
        recovered_at = timezone.now() - timedelta(days=3)
        recovery = make_recovery(self.device, self.officer, recovered_at=recovered_at)
        self.complete(recovery)

        self.device.refresh_from_db()
        self.assertEqual(self.device.recovery_date, timezone.localdate(recovered_at))
        self.assertEqual(self.device.recovery_reference, recovery.reference)
        update = AuditLog.objects.get(action=AuditAction.DEVICE_UPDATED)
        self.assertIn("recovery_date", update.new_values)

    def test_existing_case_reference_is_kept(self):
        device = make_device(actor=self.officer, recovery_reference="CASE-77")
        recovery = make_recovery(device, self.officer)
        self.complete(recovery)
        device.refresh_from_db()
        self.assertEqual(device.recovery_reference, "CASE-77")

    def test_recovered_with_issues_requires_notes(self):
        recovery = make_recovery(self.device, self.officer, outcome="RECOVERED_WITH_ISSUES", notes="")
        response = self.complete(recovery)
        self.assertEqual(response.status_code, 400)
        self.assertIn("notes", response.json())

        self.client.patch(detail_url(recovery), {"notes": "Charger and SIM tray missing."}, format="json")
        response = self.complete(recovery)
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)

    def test_outcome_is_required_to_complete(self):
        recovery = make_recovery(self.device, self.officer, outcome="")
        response = self.complete(recovery)

        self.assertEqual(response.status_code, 400)
        self.assertIn("outcome", response.json())
        recovery.refresh_from_db()
        self.assertEqual(recovery.status, RecoveryStatus.IN_PROGRESS)

    def test_not_recovered_closes_attempt_and_keeps_device_in_recovery(self):
        recovery = make_recovery(self.device, self.officer, outcome="NOT_RECOVERED", notes="")
        self.assertEqual(self.complete(recovery).status_code, 400)  # a reason is required

        self.client.patch(detail_url(recovery), {"notes": "Customer not at the address."}, format="json")
        response = self.complete(recovery)

        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.IN_RECOVERY)
        self.assertFalse(self.device.status_changes.filter(to_status=DeviceStatus.RECOVERED).exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DEVICE_STATUS_CHANGED).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.RECOVERY_COMPLETED).exists())

    def test_new_attempt_after_failed_one(self):
        failed = make_recovery(self.device, self.officer, outcome="NOT_RECOVERED", notes="Phone switched off.")
        self.complete(failed)

        response = self.client.post(LIST_URL, recovery_payload(self.device), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        second = Recovery.objects.get(pk=response.json()["id"])
        self.assertEqual(self.complete(second).status_code, 200)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)
        self.assertEqual(self.device.recoveries.count(), 2)  # both attempts are kept as history

    def test_duplicate_completion_is_rejected(self):
        recovery = make_recovery(self.device, self.officer)
        self.assertEqual(self.complete(recovery).status_code, 200)

        response = self.complete(recovery)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.status_changes.filter(to_status=DeviceStatus.RECOVERED).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.RECOVERY_COMPLETED).count(), 1)

    def test_recovered_device_cannot_get_a_new_recovery(self):
        recovery = make_recovery(self.device, self.officer)
        self.complete(recovery)
        response = self.client.post(LIST_URL, recovery_payload(self.device), format="json")
        self.assertEqual(response.status_code, 400)

    def test_device_that_left_in_recovery_cannot_be_completed(self):
        recovery = make_recovery(self.device, self.officer)
        # The device was moved on by another path in the meantime.
        transition_device(self.device, DeviceStatus.RECOVERED, actor=make_user(RoleCode.OPERATIONS_MANAGER))

        response = self.complete(recovery)
        self.assertEqual(response.status_code, 400)
        recovery.refresh_from_db()
        self.assertEqual(recovery.status, RecoveryStatus.IN_PROGRESS)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.RECOVERY_COMPLETED).exists())

    def test_unknown_recovery_is_404(self):
        self.assertEqual(self.client.post(reverse("recovery-complete", args=[999999])).status_code, 404)


class RecoveryPermissionTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.device = make_device(actor=self.officer)
        self.recovery = make_recovery(self.device, self.officer)

    def test_unauthenticated_requests_get_401(self):
        client = APIClient()
        self.assertEqual(client.get(LIST_URL).status_code, 401)
        self.assertEqual(client.post(LIST_URL, recovery_payload(self.device), format="json").status_code, 401)
        self.assertEqual(client.get(detail_url(self.recovery)).status_code, 401)
        self.assertEqual(client.patch(detail_url(self.recovery), {"notes": "x"}, format="json").status_code, 401)
        self.assertEqual(client.post(complete_url(self.recovery)).status_code, 401)

    def test_other_roles_cannot_create_update_or_complete(self):
        other_device = make_device(actor=self.officer)
        for role in NON_RECOVERY_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.post(LIST_URL, recovery_payload(other_device), format="json").status_code, 403)
                self.assertEqual(client.patch(detail_url(self.recovery), {"notes": "x"}, format="json").status_code, 403)
                self.assertEqual(client.post(complete_url(self.recovery)).status_code, 403)

        self.recovery.refresh_from_db()
        self.assertEqual(self.recovery.status, RecoveryStatus.IN_PROGRESS)
        self.assertEqual(self.recovery.notes, "")
        self.assertFalse(other_device.recoveries.exists())

    def test_roles_with_device_view_can_read_recoveries(self):
        for role in NON_RECOVERY_ROLES:
            with self.subTest(role=role):
                client = logged_in_client(make_user(role))
                self.assertEqual(client.get(LIST_URL).status_code, 200)
                self.assertEqual(client.get(detail_url(self.recovery)).status_code, 200)

    def test_user_without_role_cannot_read(self):
        client = logged_in_client(make_user(role_code=None))
        self.assertEqual(client.get(LIST_URL).status_code, 403)
        self.assertEqual(client.get(detail_url(self.recovery)).status_code, 403)


class RecoveryListTests(TestCase):
    def setUp(self):
        self.officer = make_user(RoleCode.RECOVERY_OFFICER)
        self.client = logged_in_client(self.officer)
        self.device_a = make_device(actor=self.officer)
        self.device_b = make_device(actor=self.officer)
        self.open = make_recovery(self.device_a, self.officer, recovery_location="Huye")
        failed = make_recovery(self.device_b, self.officer, outcome="NOT_RECOVERED", notes="Not home.")
        self.client.post(complete_url(failed))
        self.failed = failed

    def ids(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.json()["results"]}

    def test_filters(self):
        self.assertEqual(self.ids(), {self.open.pk, self.failed.pk})
        self.assertEqual(self.ids(device=self.device_a.pk), {self.open.pk})
        self.assertEqual(self.ids(status="IN_PROGRESS"), {self.open.pk})
        self.assertEqual(self.ids(status="COMPLETED"), {self.failed.pk})
        self.assertEqual(self.ids(outcome="NOT_RECOVERED"), {self.failed.pk})
        self.assertEqual(self.ids(search="huye"), {self.open.pk})
        self.assertEqual(self.ids(search=self.device_b.device_code), {self.failed.pk})
        self.assertEqual(self.ids(search=self.open.reference), {self.open.pk})

    def test_invalid_filter_values_are_ignored(self):
        self.assertEqual(self.ids(status="BOGUS", device="abc"), {self.open.pk, self.failed.pk})
