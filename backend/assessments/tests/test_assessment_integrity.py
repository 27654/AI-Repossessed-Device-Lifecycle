"""Transactions, database constraints and the history trigger for assessments."""

from unittest import mock

from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.rbac import RoleCode
from accounts.tests.helpers import make_user
from assessments import services
from assessments.models import Assessment, AssessmentStatus
from audit.models import AuditAction, AuditLog
from devices.models import DeviceStatus

from .helpers import assessment_fields, make_assessment, recovered_device


class AssessmentTransactionTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.device = recovered_device()
        self.assessment = make_assessment(self.device, self.assessor)

    def test_failed_status_change_rolls_back_submission(self):
        with mock.patch("assessments.services.transition_device", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.submit_assessment(self.assessment, actor=self.assessor)

        self.assessment.refresh_from_db()
        self.device.refresh_from_db()
        self.assertEqual(self.assessment.status, AssessmentStatus.DRAFT)
        self.assertIsNone(self.assessment.submitted_at)
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.ASSESSMENT_SUBMITTED).exists())

    def test_failed_condition_update_rolls_back_everything(self):
        with mock.patch("assessments.services.record_condition", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                services.submit_assessment(self.assessment, actor=self.assessor)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.RECOVERED)
        self.assertEqual(self.device.status_changes.count(), 1)

    def test_service_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            services.create_assessment(actor=self.assessor, device=recovered_device(), status="SUBMITTED")
        with self.assertRaises(ValidationError):
            services.update_assessment(self.assessment, actor=self.assessor, changes={"submitted_at": None})


class AssessmentDatabaseConstraintTests(TestCase):
    def setUp(self):
        self.assessor = make_user(RoleCode.DEVICE_ASSESSOR)
        self.device = recovered_device()

    def create(self, **extra):
        return Assessment.objects.create(device=self.device, assessor=self.assessor, **assessment_fields(), **extra)

    def test_database_allows_one_draft_per_device(self):
        self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create()

    def test_database_allows_one_submitted_per_device(self):
        self.create(status=AssessmentStatus.SUBMITTED, submitted_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create(status=AssessmentStatus.SUBMITTED, submitted_at=timezone.now())

    def test_submitted_row_must_be_complete(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assessment.objects.create(
                device=self.device,
                assessor=self.assessor,
                status=AssessmentStatus.SUBMITTED,
                submitted_at=timezone.now(),
                **assessment_fields(screen_condition=""),
            )

    def test_invalid_choice_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assessment.objects.create(device=self.device, assessor=self.assessor, battery_condition="DEAD")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assessment.objects.create(device=self.device, assessor=self.assessor, defects=["NOT_A_DEFECT"])

    def test_submitted_assessment_is_immutable_in_the_database(self):
        assessment = services.submit_assessment(make_assessment(self.device, self.assessor), actor=self.assessor)

        with self.assertRaises(DatabaseError), transaction.atomic():
            Assessment.objects.filter(pk=assessment.pk).update(battery_condition="EXCELLENT")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Assessment.objects.filter(pk=assessment.pk).delete()
        assessment.refresh_from_db()
        self.assertEqual(assessment.battery_condition, "FAIR")

    def test_drafts_cannot_be_deleted(self):
        assessment = make_assessment(self.device, self.assessor)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Assessment.objects.filter(pk=assessment.pk).delete()
