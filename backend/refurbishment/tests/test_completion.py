import threading
from unittest import mock

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from accounts.rbac import RoleCode
from accounts.tests.helpers import logged_in_client, make_user
from audit.models import AuditAction, AuditLog
from devices.models import DeviceStatus
from devices.services import transition_device
from refurbishment import services
from refurbishment.models import (
    RefurbishmentItem,
    RefurbishmentStep,
    RefurbishmentWorkOrder,
    StepStatus,
    WorkOrderOutcome,
    WorkOrderStatus,
)

from .helpers import finish_required_checks, make_work_order, ready_to_complete, started_work_order


def url(name, work_order):
    return reverse(name, args=[work_order.pk])


class CompletionTests(TestCase):
    def setUp(self):
        self.work_order, self.technician = ready_to_complete()
        self.client = logged_in_client(self.technician)
        self.device = self.work_order.device

    def test_complete_moves_device_to_ready(self):
        response = self.client.post(url("work-order-complete", self.work_order))

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["outcome"]), ("COMPLETED", "REPAIRED"))
        # 15,000 screen + 2 x 500 adhesive + 5,000 labour
        self.assertEqual(body["actual_cost_rwf"], 21_000)
        self.assertEqual(body["total_cost_rwf"], 21_000)
        self.assertEqual(body["completed_by"]["id"], self.technician.pk)
        self.assertEqual(body["device_summary"]["status"], DeviceStatus.READY_FOR_DISPOSITION)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.READY_FOR_DISPOSITION)

    def test_completion_writes_history_and_audit(self):
        self.client.post(url("work-order-complete", self.work_order))

        change = self.device.status_changes.get(to_status=DeviceStatus.READY_FOR_DISPOSITION)
        self.assertEqual(change.from_status, DeviceStatus.REFURBISHING)
        self.assertEqual((change.source_type, change.source_id), ("refurbishment", self.work_order.pk))
        self.assertIn(self.work_order.reference, change.reason)
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_COMPLETED)
        self.assertEqual(entry.user, self.technician)
        self.assertEqual(entry.new_values["actual_cost_rwf"], 21_000)
        self.assertEqual(entry.new_values["parts_cost_rwf"], 16_000)
        status_entry = AuditLog.objects.get(action=AuditAction.DEVICE_STATUS_CHANGED, entity_id=str(self.device.pk),
                                            new_values__status="READY_FOR_DISPOSITION")
        self.assertEqual(status_entry.new_values["source_type"], "refurbishment")

    def test_summary_and_labour_can_be_given_at_completion(self):
        work_order = started_work_order(technician=self.technician)
        finish_required_checks(work_order, self.technician)
        response = self.client.post(
            url("work-order-complete", work_order), {"work_summary": "Cleaned, reset.", "labour_cost_rwf": 2_000},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["actual_cost_rwf"], 2_000)

    def test_completion_requirements(self):
        work_order = started_work_order(technician=self.technician)
        services.add_step(work_order, actor=self.technician, step_type="SCREEN_REPAIR")
        response = self.client.post(url("work-order-complete", work_order))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"work_summary", "labour_cost_rwf", "steps", "checks"})
        work_order.refresh_from_db()
        self.assertEqual(work_order.status, WorkOrderStatus.IN_PROGRESS)
        work_order.device.refresh_from_db()
        self.assertEqual(work_order.device.status, DeviceStatus.REFURBISHING)

    def test_unfinished_step_blocks_completion(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="BATTERY_REPLACEMENT")
        response = self.client.post(url("work-order-complete", self.work_order))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Battery replacement", response.json()["steps"])

        services.update_step(step, actor=self.technician, changes={"status": "SKIPPED", "notes": "Battery fine."})
        self.assertEqual(self.client.post(url("work-order-complete", self.work_order)).status_code, 200)

    def test_skipped_check_does_not_count(self):
        work_order = started_work_order(technician=self.technician)
        for step_type in ("FUNCTIONAL_TEST", "QUALITY_CHECK"):
            step = services.add_step(work_order, actor=self.technician, step_type=step_type)
            services.update_step(step, actor=self.technician, changes={"status": "SKIPPED", "notes": "No time"})
        response = self.client.post(
            url("work-order-complete", work_order), {"work_summary": "x", "labour_cost_rwf": 0}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("checks", response.json())

    def test_duplicate_completion_rejected(self):
        self.assertEqual(self.client.post(url("work-order-complete", self.work_order)).status_code, 200)
        response = self.client.post(url("work-order-complete", self.work_order))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.device.status_changes.filter(to_status=DeviceStatus.READY_FOR_DISPOSITION).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.REFURBISHMENT_COMPLETED).count(), 1)

    def test_device_must_still_be_refurbishing(self):
        transition_device(self.device, DeviceStatus.UNABLE_TO_REPAIR, actor=make_user(RoleCode.OPERATIONS_MANAGER))
        response = self.client.post(url("work-order-complete", self.work_order))
        self.assertEqual(response.status_code, 400)
        self.work_order.refresh_from_db()
        self.assertEqual(self.work_order.status, WorkOrderStatus.IN_PROGRESS)

    def test_closed_work_order_cannot_be_edited(self):
        self.client.post(url("work-order-complete", self.work_order))
        response = self.client.patch(url("work-order-detail", self.work_order), {"diagnosis": "rewrite"}, format="json")
        self.assertEqual(response.status_code, 400)
        for name in ("work-order-start", "work-order-unable-to-repair", "work-order-cancel"):
            self.assertEqual(self.client.post(url(name, self.work_order), {"reason": "x"}, format="json").status_code, 400)

    def test_failed_transition_rolls_back(self):
        with mock.patch("refurbishment.services.transition_device", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.complete_work_order(self.work_order, actor=self.technician)
        self.work_order.refresh_from_db()
        self.assertEqual(self.work_order.status, WorkOrderStatus.IN_PROGRESS)
        self.assertIsNone(self.work_order.actual_cost_rwf)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.REFURBISHMENT_COMPLETED).exists())


class UnableToRepairTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = started_work_order(technician=self.technician)
        services.add_item(self.work_order, actor=self.technician, item_name="Test cable", quantity=1, unit_cost_rwf=800)

    def test_reason_required(self):
        for body in ({}, {"reason": ""}, {"reason": "   "}):
            response = self.client.post(url("work-order-unable-to-repair", self.work_order), body, format="json")
            self.assertEqual(response.status_code, 400)
        self.work_order.device.refresh_from_db()
        self.assertEqual(self.work_order.device.status, DeviceStatus.REFURBISHING)

    def test_unable_to_repair_moves_device(self):
        response = self.client.post(
            url("work-order-unable-to-repair", self.work_order),
            {"reason": "Motherboard corrosion; replacement board unavailable."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["outcome"]), ("COMPLETED", "UNABLE_TO_REPAIR"))
        self.assertEqual(body["closure_reason"], "Motherboard corrosion; replacement board unavailable.")
        self.assertEqual(body["actual_cost_rwf"], 800)  # parts used so far; no labour recorded

        device = self.work_order.device
        device.refresh_from_db()
        self.assertEqual(device.status, DeviceStatus.UNABLE_TO_REPAIR)
        change = device.status_changes.get(to_status=DeviceStatus.UNABLE_TO_REPAIR)
        self.assertEqual((change.from_status, change.source_type), (DeviceStatus.REFURBISHING, "refurbishment"))
        self.assertIn("Motherboard corrosion", change.reason)
        entry = AuditLog.objects.get(action=AuditAction.REFURBISHMENT_UNABLE_TO_REPAIR)
        self.assertEqual(entry.new_values["reason"], "Motherboard corrosion; replacement board unavailable.")

    def test_works_from_open_work_order(self):
        work_order = make_work_order(technician=self.technician)
        response = self.client.post(url("work-order-unable-to-repair", work_order), {"reason": "Water damage"},
                                    format="json")
        self.assertEqual(response.status_code, 200)


class CancelTests(TestCase):
    def setUp(self):
        self.technician = make_user(RoleCode.REFURBISHMENT_STAFF)
        self.client = logged_in_client(self.technician)
        self.work_order = make_work_order(technician=self.technician)

    def test_cancel_keeps_device_refurbishing_and_allows_new_work_order(self):
        self.assertEqual(self.client.post(url("work-order-cancel", self.work_order), {}, format="json").status_code, 400)
        response = self.client.post(url("work-order-cancel", self.work_order), {"reason": "Opened twice"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["status"], response.json()["outcome"]), ("CANCELLED", ""))
        device = self.work_order.device
        device.refresh_from_db()
        self.assertEqual(device.status, DeviceStatus.REFURBISHING)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.DEVICE_STATUS_CHANGED, entity_id=str(device.pk),
                                                 new_values__source_type="refurbishment").exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.REFURBISHMENT_CANCELLED).exists())
        second = make_work_order(device=device, technician=self.technician)
        self.assertEqual(device.work_orders.count(), 2)
        self.assertNotEqual(second.reference, self.work_order.reference)


class DatabaseProtectionTests(TestCase):
    def setUp(self):
        self.work_order, self.technician = ready_to_complete()

    def test_one_active_work_order_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefurbishmentWorkOrder.objects.create(device=self.work_order.device, created_by=self.technician)

    def test_item_total_enforced_by_database(self):
        item = self.work_order.items.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefurbishmentItem.objects.filter(pk=item.pk).update(total_cost_rwf=1)

    def test_skipped_step_needs_reason_in_database(self):
        step = services.add_step(self.work_order, actor=self.technician, step_type="CLEANING")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefurbishmentStep.objects.filter(pk=step.pk).update(status=StepStatus.SKIPPED, completed_at=step.created_at)

    def test_completed_work_order_is_immutable(self):
        services.complete_work_order(self.work_order, actor=self.technician)
        with self.assertRaises(DatabaseError), transaction.atomic():
            RefurbishmentWorkOrder.objects.filter(pk=self.work_order.pk).update(actual_cost_rwf=1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            RefurbishmentItem.objects.filter(work_order=self.work_order).update(unit_cost_rwf=1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            RefurbishmentStep.objects.filter(work_order=self.work_order).update(notes="rewrite")

    def test_finished_step_is_immutable_while_work_order_open(self):
        step = self.work_order.steps.filter(status=StepStatus.COMPLETED).first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            RefurbishmentStep.objects.filter(pk=step.pk).update(notes="rewrite")

    def test_nothing_can_be_deleted(self):
        for model, qs in (
            (RefurbishmentItem, RefurbishmentItem.objects.filter(work_order=self.work_order)),
            (RefurbishmentStep, RefurbishmentStep.objects.filter(work_order=self.work_order)),
            (RefurbishmentWorkOrder, RefurbishmentWorkOrder.objects.filter(pk=self.work_order.pk)),
        ):
            with self.subTest(model=model.__name__), self.assertRaises(DatabaseError), transaction.atomic():
                qs.delete()

    def test_completed_without_cost_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefurbishmentWorkOrder.objects.filter(pk=self.work_order.pk).update(
                status=WorkOrderStatus.COMPLETED, outcome=WorkOrderOutcome.REPAIRED
            )

    def test_services_reject_unknown_fields(self):
        with self.assertRaises(ValidationError):
            services.update_work_order(self.work_order, actor=self.technician, changes={"status": "COMPLETED"})
        with self.assertRaises(ValidationError):
            services.add_item(self.work_order, actor=self.technician, item_name="x", quantity=1, unit_cost_rwf=1,
                              total_cost_rwf=5)


class ConcurrentCompletionTests(TransactionTestCase):
    """Two technicians complete the same work order at the same moment: exactly one succeeds."""

    serialized_rollback = True  # keep the roles seeded by migrations for later tests

    def test_only_one_completion_wins(self):
        work_order, technician = ready_to_complete()
        other = make_user(RoleCode.REFURBISHMENT_STAFF)
        barrier = threading.Barrier(2)
        results = []

        def complete(actor):
            try:
                barrier.wait()
                services.complete_work_order(RefurbishmentWorkOrder.objects.get(pk=work_order.pk), actor=actor)
                results.append("ok")
            except ValidationError:
                results.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=complete, args=(actor,)) for actor in (technician, other)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(results), ["ok", "rejected"])
        device = work_order.device
        self.assertEqual(device.status_changes.filter(to_status=DeviceStatus.READY_FOR_DISPOSITION).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.REFURBISHMENT_COMPLETED).count(), 1)
