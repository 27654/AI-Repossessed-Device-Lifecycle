from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

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

    def test_role_details_change_is_audited(self):
        role = Role.objects.get(code=RoleCode.SALES_OFFICER)

        self.client.patch(reverse("role-detail", args=[role.pk]), {"description": "Sells devices."}, format="json")

        entry = AuditLog.objects.get(action=AuditAction.ROLE_UPDATED)
        self.assertEqual(entry.new_values, {"description": "Sells devices."})

    def test_admin_can_unlock_account(self):
        user = make_user(locked_until=timezone.now() + timedelta(minutes=10), failed_login_count=0)

        response = self.client.post(reverse("user-unlock", args=[user.pk]))

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_locked)
        entry = AuditLog.objects.get(action=AuditAction.ACCOUNT_UNLOCKED)
        self.assertIsNotNone(entry.previous_values["locked_until"])
        self.assertEqual(
            APIClient().post(reverse("auth-login"), {"email": user.email, "password": PASSWORD}, format="json").status_code,
            200,
        )

    def test_admin_mfa_reset_is_audited(self):
        user = make_user(mfa_enabled=True)

        self.client.post(reverse("user-reset-mfa", args=[user.pk]))

        entry = AuditLog.objects.get(action=AuditAction.MFA_DISABLED)
        self.assertEqual(entry.previous_values, {"mfa_enabled": True})
        self.assertEqual(entry.user, self.admin)

    def test_non_admin_cannot_use_admin_security_actions(self):
        user = make_user()
        client = logged_in_client(make_user(RoleCode.OPERATIONS_MANAGER))
        for name in ("user-unlock", "user-reset-mfa", "user-reset-password"):
            with self.subTest(endpoint=name):
                self.assertEqual(client.post(reverse(name, args=[user.pk]), {}, format="json").status_code, 403)


class LoginAttemptApiTests(TestCase):
    def test_login_attempts_are_listed_for_audit_viewers(self):
        make_user(email="tracked@yellow.test")
        APIClient().post(reverse("auth-login"), {"email": "tracked@yellow.test", "password": "nope"}, format="json")
        client = logged_in_client(make_user(RoleCode.SYSTEM_ADMIN))

        response = client.get(reverse("login-attempt-list"), {"email": "tracked@yellow.test", "success": "false"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["failure_reason"], "BAD_CREDENTIALS")

    def test_login_attempts_are_protected(self):
        self.assertEqual(APIClient().get(reverse("login-attempt-list")).status_code, 401)
        client = logged_in_client(make_user(RoleCode.RECOVERY_OFFICER))
        self.assertEqual(client.get(reverse("login-attempt-list")).status_code, 403)
