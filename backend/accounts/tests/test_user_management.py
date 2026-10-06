from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from accounts.rbac import RoleCode
from audit.models import AuditAction, AuditLog

from .helpers import PASSWORD, logged_in_client, make_user


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user(RoleCode.SYSTEM_ADMIN)
        self.client = logged_in_client(self.admin)

    def test_create_user_hashes_password_and_is_audited(self):
        response = self.client.post(
            reverse("user-list"),
            {
                "full_name": "Aline Uwase",
                "email": "Aline@Yellow.test",
                "phone": "+250788000000",
                "employee_id": "YRW-001",
                "role": "DEVICE_ASSESSOR",
                "password": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.json())
        user = User.objects.get(email="aline@yellow.test")
        self.assertTrue(user.check_password(PASSWORD))
        entry = AuditLog.objects.get(action=AuditAction.USER_CREATED)
        self.assertEqual(entry.user, self.admin)
        self.assertEqual(entry.entity_id, str(user.pk))
        self.assertEqual(entry.new_values["role"], "DEVICE_ASSESSOR")
        self.assertNotIn("password", entry.new_values)

    def test_create_user_rejects_weak_password(self):
        response = self.client.post(
            reverse("user-list"),
            {"full_name": "A B", "email": "a@yellow.test", "employee_id": "X1", "role": "SALES_OFFICER", "password": "12345678"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())

    def test_update_user_is_audited_with_changed_values(self):
        user = make_user(RoleCode.SALES_OFFICER, phone="+250700000001")

        self.client.patch(
            reverse("user-detail", args=[user.pk]),
            {"phone": "+250700000002", "account_status": "SUSPENDED"},
            format="json",
        )

        entry = AuditLog.objects.get(action=AuditAction.USER_UPDATED)
        self.assertEqual(entry.previous_values, {"phone": "+250700000001", "account_status": "ACTIVE"})
        self.assertEqual(entry.new_values, {"phone": "+250700000002", "account_status": "SUSPENDED"})

    def test_role_change_is_audited(self):
        user = make_user(RoleCode.SALES_OFFICER)

        response = self.client.patch(reverse("user-detail", args=[user.pk]), {"role": "OPERATIONS_MANAGER"}, format="json")

        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.get(action=AuditAction.USER_ROLE_CHANGED)
        self.assertEqual(entry.previous_values, {"role": "SALES_OFFICER"})
        self.assertEqual(entry.new_values, {"role": "OPERATIONS_MANAGER"})

    def test_admin_cannot_demote_or_deactivate_self(self):
        url = reverse("user-detail", args=[self.admin.pk])
        self.assertEqual(self.client.patch(url, {"account_status": "SUSPENDED"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"role": "SALES_OFFICER"}, format="json").status_code, 400)

    def test_password_reset_is_audited_and_ends_sessions(self):
        user = make_user()
        user_client = logged_in_client(user)

        response = self.client.post(
            reverse("user-reset-password", args=[user.pk]), {"new_password": "Temp0rary-Pass-99"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(user_client.get(reverse("auth-me")).status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.PASSWORD_RESET, entity_id=str(user.pk)).exists())

    def test_role_permission_change_is_audited(self):
        role = Role.objects.get(code=RoleCode.SALES_OFFICER)

        response = self.client.patch(
            reverse("role-detail", args=[role.pk]), {"permissions": ["device.view", "analytics.view"]}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.get(action=AuditAction.ROLE_PERMISSIONS_CHANGED)
        self.assertEqual(entry.new_values, {"permissions": ["analytics.view", "device.view"]})
        self.assertIn("disposition.create", entry.previous_values["permissions"])

    def test_admin_role_keeps_access_management(self):
        role = Role.objects.get(code=RoleCode.SYSTEM_ADMIN)

        response = self.client.patch(reverse("role-detail", args=[role.pk]), {"permissions": ["audit.view"]}, format="json")

        self.assertEqual(response.status_code, 400)


class AuditLogTests(TestCase):
    def test_entries_cannot_be_changed_or_deleted(self):
        make_user()
        logged_in_client(make_user()).post(reverse("auth-logout"))
        entry = AuditLog.objects.get(action=AuditAction.LOGOUT)

        entry.description = "tampered"
        with self.assertRaises(PermissionDenied):
            entry.save()
        with self.assertRaises(PermissionDenied):
            entry.delete()

    def test_audit_log_can_be_filtered(self):
        admin = make_user(RoleCode.SYSTEM_ADMIN)
        client = logged_in_client(admin)
        client.post(reverse("auth-change-password"), {"current_password": "wrong", "new_password": "An0ther-Str0ng-Pass"}, format="json")

        response = client.get(reverse("audit-log-list"), {"action": "PASSWORD_CHANGE_FAILED", "from": "2026-02-30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
