from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from accounts.rbac import Perm, RoleCode

from .helpers import logged_in_client, make_user


class SeededRoleTests(TestCase):
    def test_all_six_roles_are_seeded(self):
        self.assertEqual(set(Role.objects.values_list("code", flat=True)), set(RoleCode.values))

    def test_default_matrix_separates_duties(self):
        admin = make_user(RoleCode.SYSTEM_ADMIN)
        manager = make_user(RoleCode.OPERATIONS_MANAGER)
        officer = make_user(RoleCode.RECOVERY_OFFICER)

        self.assertTrue(admin.has_permission_code(Perm.USER_MANAGE, Perm.AUDIT_VIEW))
        self.assertFalse(admin.has_permission_code(Perm.DEVICE_CREATE))
        self.assertTrue(manager.has_permission_code(Perm.AI_DECIDE))
        self.assertFalse(manager.has_permission_code(Perm.USER_MANAGE))
        self.assertTrue(officer.has_permission_code(Perm.RECOVERY_MANAGE))
        self.assertFalse(officer.has_permission_code(Perm.AI_VIEW))

    def test_me_lists_role_permissions(self):
        client = logged_in_client(make_user(RoleCode.DEVICE_ASSESSOR))

        permissions = client.get(reverse("auth-me")).json()["permissions"]

        self.assertIn(Perm.ASSESSMENT_CREATE, permissions)
        self.assertNotIn(Perm.USER_MANAGE, permissions)


class EndpointAuthorizationTests(TestCase):
    ADMIN_ONLY = ["user-list", "role-list", "audit-log-list"]

    def test_correct_role_is_allowed(self):
        client = logged_in_client(make_user(RoleCode.SYSTEM_ADMIN))
        for name in self.ADMIN_ONLY + ["permission-list"]:
            with self.subTest(endpoint=name):
                self.assertEqual(client.get(reverse(name)).status_code, 200)

    def test_other_roles_are_forbidden(self):
        for role in RoleCode.values:
            if role == RoleCode.SYSTEM_ADMIN:
                continue
            client = logged_in_client(make_user(role))
            for name in self.ADMIN_ONLY:
                with self.subTest(role=role, endpoint=name):
                    self.assertEqual(client.get(reverse(name)).status_code, 403)

    def test_forbidden_role_cannot_write(self):
        target = make_user(RoleCode.SALES_OFFICER)
        client = logged_in_client(make_user(RoleCode.OPERATIONS_MANAGER))
        role = Role.objects.get(code=RoleCode.SALES_OFFICER)

        self.assertEqual(
            client.patch(reverse("user-detail", args=[target.pk]), {"role": "SYSTEM_ADMIN"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            client.patch(reverse("role-detail", args=[role.pk]), {"permissions": ["user.manage"]}, format="json").status_code,
            403,
        )
        target.refresh_from_db()
        self.assertEqual(target.role.code, RoleCode.SALES_OFFICER)

    def test_user_without_role_has_no_permissions(self):
        client = logged_in_client(make_user(role_code=None))

        self.assertEqual(client.get(reverse("auth-me")).json()["permissions"], [])
        self.assertEqual(client.get(reverse("user-list")).status_code, 403)
