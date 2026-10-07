from unittest import mock

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices import services
from devices.models import Device, DeviceStatus, DeviceStatusChange
from devices.services import InvalidTransition, transition_device

from .helpers import make_device

S = DeviceStatus


class TransitionTests(TestCase):
    def setUp(self):
        self.actor = make_user(RoleCode.OPERATIONS_MANAGER)
        self.device = make_device()

    def test_full_lifecycle_path_records_history_and_audit(self):
        path = [S.RECOVERED, S.ASSESSED, S.REFURBISHING, S.READY_FOR_DISPOSITION, S.RESOLD]
        for status in path:
            transition_device(self.device, status, actor=self.actor, reason=f"to {status}")

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, S.RESOLD)
        history = list(self.device.status_changes.order_by("id").values_list("from_status", "to_status"))
        self.assertEqual(history[0], (None, S.IN_RECOVERY))
        self.assertEqual(history[1:], list(zip([S.IN_RECOVERY, *path[:-1]], path)))
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.DEVICE_STATUS_CHANGED).count(), len(path))

    def test_status_change_audit_has_before_and_after(self):
        transition_device(self.device, S.RECOVERED, actor=self.actor, source_type="recovery", source_id=7)

        entry = AuditLog.objects.get(action=AuditAction.DEVICE_STATUS_CHANGED)
        self.assertEqual(entry.user, self.actor)
        self.assertEqual(entry.previous_values, {"status": "IN_RECOVERY"})
        self.assertEqual(entry.new_values, {"status": "RECOVERED", "source_type": "recovery", "source_id": 7})
        change = self.device.status_changes.get(to_status=S.RECOVERED)
        self.assertEqual((change.source_type, change.source_id, change.changed_by), ("recovery", 7, self.actor))

    def test_invalid_transition_is_rejected_without_side_effects(self):
        for target in (S.RESOLD, S.ASSESSED, S.IN_RECOVERY):
            with self.subTest(target=target), self.assertRaises(InvalidTransition):
                transition_device(self.device, target, actor=self.actor)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, S.IN_RECOVERY)
        self.assertEqual(self.device.status_changes.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DEVICE_STATUS_CHANGED).exists())

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(InvalidTransition):
            transition_device(self.device, "LOST", actor=self.actor)

    def test_closed_devices_cannot_move(self):
        for status in (S.RECOVERED, S.ASSESSED, S.UNABLE_TO_REPAIR):
            transition_device(self.device, status, actor=self.actor)
        with self.assertRaises(InvalidTransition):
            transition_device(self.device, S.REFURBISHING, actor=self.actor)

    def test_ai_cannot_change_status(self):
        with self.assertRaises(InvalidTransition):
            transition_device(self.device, S.RECOVERED, actor=self.actor, source_type="ai_recommendation", source_id=1)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, S.IN_RECOVERY)

    def test_a_human_active_actor_is_required(self):
        inactive = make_user(account_status=User.Status.SUSPENDED)
        for actor in (None, inactive):
            with self.subTest(actor=actor), self.assertRaises(InvalidTransition):
                transition_device(self.device, S.RECOVERED, actor=actor)

    def test_transition_is_atomic(self):
        with mock.patch("devices.services.log_action", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                transition_device(self.device, S.RECOVERED, actor=self.actor)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, S.IN_RECOVERY)
        self.assertEqual(self.device.status_changes.count(), 1)

    def test_registration_is_atomic(self):
        with mock.patch("devices.services.log_action", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                make_device(actor=self.actor)
        self.assertEqual(Device.objects.count(), 1)


class StatusHistoryTests(TestCase):
    def setUp(self):
        self.device = make_device()
        self.change = self.device.status_changes.get()

    def test_history_cannot_be_changed_through_the_model(self):
        self.change.reason = "rewritten"
        with self.assertRaises(PermissionDenied):
            self.change.save()
        with self.assertRaises(PermissionDenied):
            self.change.delete()

    def test_database_rejects_history_update_and_delete(self):
        for sql in (
            "UPDATE devices_devicestatuschange SET reason = 'x' WHERE id = %s",
            "DELETE FROM devices_devicestatuschange WHERE id = %s",
        ):
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [self.change.pk])
        self.assertTrue(DeviceStatusChange.objects.filter(pk=self.change.pk, reason="Device registered.").exists())

    def test_device_with_history_cannot_be_deleted(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.device.delete()

    def test_database_rejects_malformed_imei(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Device.objects.filter(pk=self.device.pk).update(imei="12345")

    def test_history_endpoint_lists_newest_first(self):
        actor = make_user(RoleCode.OPERATIONS_MANAGER)
        transition_device(self.device, S.RECOVERED, actor=actor, reason="Received at depot")
        client = logged_in_client(make_user(RoleCode.SALES_OFFICER))

        response = client.get(reverse("device-history", args=[self.device.pk]))

        self.assertEqual(response.status_code, 200)
        entries = response.json()
        self.assertEqual([e["to_status"] for e in entries], ["RECOVERED", "IN_RECOVERY"])
        self.assertEqual(entries[0]["reason"], "Received at depot")
        self.assertEqual(entries[0]["changed_by"]["full_name"], actor.full_name)
        self.assertIsNone(entries[1]["from_status"])

    def test_history_endpoint_is_read_only(self):
        client = logged_in_client(make_user(RoleCode.RECOVERY_OFFICER))
        url = reverse("device-history", args=[self.device.pk])
        self.assertEqual(client.post(url, {"to_status": "RESOLD"}, format="json").status_code, 405)

    def test_update_service_refuses_status(self):
        with self.assertRaises(ValidationError):
            services.update_device(self.device, actor=make_user(), changes={"status": S.RESOLD})
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, S.IN_RECOVERY)
