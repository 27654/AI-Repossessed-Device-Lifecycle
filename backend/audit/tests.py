from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.rbac import RoleCode
from accounts.tests.helpers import PASSWORD, logged_in_client, make_user

from .models import AuditAction, AuditLog
from .services import log_action


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.entry = log_action(AuditAction.LOGOUT, user=self.user, entity=self.user, description="Signed out.")

    def test_single_entry_cannot_be_changed_or_deleted(self):
        self.entry.description = "tampered"
        with self.assertRaises(PermissionDenied):
            self.entry.save()
        with self.assertRaises(PermissionDenied):
            self.entry.delete()

    def test_bulk_update_and_delete_are_blocked(self):
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.filter(pk=self.entry.pk).update(description="tampered")
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.all().delete()

    def test_database_rejects_raw_update_and_delete(self):
        for sql in (
            "UPDATE audit_auditlog SET description = 'tampered' WHERE id = %s",
            "DELETE FROM audit_auditlog WHERE id = %s",
        ):
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [self.entry.pk])
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.description, "Signed out.")

    def test_deleting_a_user_keeps_their_audit_trail(self):
        email = self.user.email
        self.user.delete()

        self.entry.refresh_from_db()
        self.assertIsNone(self.entry.user)
        self.assertEqual(self.entry.user_label, email)


class AuditContentTests(TestCase):
    def test_entries_record_ip_and_user_agent(self):
        user = make_user(email="agent@yellow.test")
        client = APIClient(HTTP_USER_AGENT="TestBrowser/1.0")
        client.post(reverse("auth-login"), {"email": "agent@yellow.test", "password": PASSWORD}, format="json")

        entry = AuditLog.objects.get(action=AuditAction.LOGIN, user=user)
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertEqual(entry.user_agent, "TestBrowser/1.0")

    def test_passwords_never_reach_the_log(self):
        make_user(email="secret@yellow.test")
        client = APIClient()
        client.post(reverse("auth-login"), {"email": "secret@yellow.test", "password": "Wr0ng-Guess-xyz"}, format="json")
        client.post(reverse("auth-login"), {"email": "secret@yellow.test", "password": PASSWORD}, format="json")

        for entry in AuditLog.objects.all():
            text = f"{entry.description} {entry.previous_values} {entry.new_values}"
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn("Wr0ng-Guess-xyz", text)

    def test_failed_login_is_not_attributed_to_signed_in_user(self):
        signed_in = make_user()
        client = logged_in_client(signed_in)

        client.post(reverse("auth-login"), {"email": "ghost@yellow.test", "password": "x"}, format="json")

        entry = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
        self.assertIsNone(entry.user)
        self.assertEqual(entry.user_label, "ghost@yellow.test")


class AuditLogApiTests(TestCase):
    def test_audit_log_can_be_filtered(self):
        client = logged_in_client(make_user(RoleCode.SYSTEM_ADMIN))
        client.post(
            reverse("auth-change-password"),
            {"current_password": "wrong", "new_password": "An0ther-Str0ng-Pass"},
            format="json",
        )

        response = client.get(reverse("audit-log-list"), {"action": "PASSWORD_CHANGE_FAILED", "from": "2026-02-30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_audit_log_requires_audit_view(self):
        self.assertEqual(APIClient().get(reverse("audit-log-list")).status_code, 401)
        manager = logged_in_client(make_user(RoleCode.OPERATIONS_MANAGER))
        self.assertEqual(manager.get(reverse("audit-log-list")).status_code, 403)

    def test_audit_log_api_is_read_only(self):
        client = logged_in_client(make_user(RoleCode.SYSTEM_ADMIN))
        self.assertEqual(client.post(reverse("audit-log-list"), {}, format="json").status_code, 405)
