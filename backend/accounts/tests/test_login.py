import time

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.middleware import SESSION_LAST_ACTIVITY_KEY
from accounts.models import LoginAttempt, User
from audit.models import AuditAction, AuditLog

from .helpers import PASSWORD, logged_in_client, make_user


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user(email="officer@yellow.test")

    def login(self, email="officer@yellow.test", password=PASSWORD):
        return self.client.post(reverse("auth-login"), {"email": email, "password": password}, format="json")

    def test_successful_login_creates_session(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["mfa_required"])
        self.assertEqual(response.json()["user"]["email"], "officer@yellow.test")
        me = self.client.get(reverse("auth-me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"]["code"], "RECOVERY_OFFICER")

    def test_email_is_case_insensitive(self):
        self.assertEqual(self.login(email="  Officer@Yellow.TEST ").status_code, 200)

    def test_successful_login_is_audited_and_tracked(self):
        self.login()

        entry = AuditLog.objects.get(action=AuditAction.LOGIN)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.entity_type, "user")
        self.assertEqual(entry.entity_id, str(self.user.pk))
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertTrue(LoginAttempt.objects.get(user=self.user).success)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_invalid_password_is_rejected(self):
        response = self.login(password="wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 1)

    def test_failed_login_is_audited_and_tracked(self):
        self.login(password="wrong-password")

        entry = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.user_label, "officer@yellow.test")
        attempt = LoginAttempt.objects.get()
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.failure_reason, LoginAttempt.FailureReason.BAD_CREDENTIALS)

    def test_unknown_email_gets_same_response_and_is_audited(self):
        response = self.login(email="nobody@yellow.test")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")
        entry = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
        self.assertIsNone(entry.user)
        self.assertEqual(entry.user_label, "nobody@yellow.test")

    def test_inactive_user_cannot_log_in(self):
        for status in (User.Status.SUSPENDED, User.Status.DEACTIVATED):
            self.user.account_status = status
            self.user.save()

            response = self.login()

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "inactive")
            self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=3)
    def test_account_locks_after_repeated_failures(self):
        for _ in range(2):
            self.assertEqual(self.login(password="wrong-password").status_code, 401)
        self.assertEqual(self.login(password="wrong-password").status_code, 403)

        response = self.login()  # correct password, but locked

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "locked")
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.ACCOUNT_LOCKED, user=self.user).exists())

    def test_login_requires_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        data = {"email": "officer@yellow.test", "password": PASSWORD}

        self.assertEqual(client.post(reverse("auth-login"), data, format="json").status_code, 403)

        client.get(reverse("auth-csrf"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("auth-login"), data, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    def test_passwords_are_hashed(self):
        self.assertNotEqual(self.user.password, PASSWORD)
        self.assertTrue(self.user.password.startswith("pbkdf2_sha256$"))


class LogoutAndSessionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = logged_in_client(self.user)

    def test_logout_ends_session_and_is_audited(self):
        response = self.client.post(reverse("auth-logout"))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.LOGOUT, user=self.user).exists())

    def test_logout_requires_authentication(self):
        self.assertEqual(APIClient().post(reverse("auth-logout")).status_code, 401)

    def test_protected_endpoints_return_401_without_authentication(self):
        client = APIClient()
        for name in ("auth-me", "user-list", "role-list", "audit-log-list"):
            with self.subTest(endpoint=name):
                self.assertEqual(client.get(reverse(name)).status_code, 401)

    def test_idle_session_expires(self):
        self.client.get(reverse("auth-me"))  # starts the session clock
        session = self.client.session
        session[SESSION_LAST_ACTIVITY_KEY] = time.time() - 31 * 60
        session.save()

        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.SESSION_EXPIRED, user=self.user).exists())

    def test_suspending_a_user_ends_their_session(self):
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 200)
        self.user.account_status = User.Status.SUSPENDED
        self.user.save()

        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)


class ChangePasswordTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = logged_in_client(self.user)
        self.url = reverse("auth-change-password")

    def test_change_password_keeps_current_session(self):
        response = self.client.post(
            self.url, {"current_password": PASSWORD, "new_password": "An0ther-Str0ng-Pass"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("An0ther-Str0ng-Pass"))
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.PASSWORD_CHANGED, user=self.user).exists())

    def test_wrong_current_password_is_rejected_and_audited(self):
        response = self.client.post(
            self.url, {"current_password": "wrong", "new_password": "An0ther-Str0ng-Pass"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.PASSWORD_CHANGE_FAILED, user=self.user).exists())

    def test_weak_new_password_is_rejected(self):
        response = self.client.post(self.url, {"current_password": PASSWORD, "new_password": "password"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.json())
