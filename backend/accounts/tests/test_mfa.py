import time

import pyotp
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts import mfa
from accounts.services import MFA_PENDING_AT_KEY
from audit.models import AuditAction, AuditLog

from .helpers import PASSWORD, current_code, enable_mfa, logged_in_client, make_user


class MfaLoginTests(TestCase):
    def setUp(self):
        self.user = make_user(email="assessor@yellow.test")
        self.secret = enable_mfa(self.user)
        self.client = APIClient()

    def login(self):
        return self.client.post(
            reverse("auth-login"), {"email": "assessor@yellow.test", "password": PASSWORD}, format="json"
        )

    def verify(self, code):
        return self.client.post(reverse("auth-mfa-verify"), {"code": code}, format="json")

    def test_password_alone_does_not_authenticate(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mfa_required": True})
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)
        self.assertFalse(AuditLog.objects.filter(action=AuditAction.LOGIN).exists())

    def test_valid_code_completes_login(self):
        self.login()

        response = self.verify(current_code(self.secret))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "assessor@yellow.test")
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.MFA_VERIFIED, user=self.user).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.LOGIN, user=self.user).exists())

    def test_invalid_code_is_rejected_and_audited(self):
        self.login()

        response = self.verify("000000" if current_code(self.secret) != "000000" else "111111")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.MFA_FAILED, user=self.user).exists())

    def test_code_cannot_be_replayed(self):
        code = current_code(self.secret)
        self.login()
        self.assertEqual(self.verify(code).status_code, 200)
        self.client.post(reverse("auth-logout"))

        self.login()
        self.assertEqual(self.verify(code).status_code, 401)

    def test_verify_without_password_step_is_rejected(self):
        response = self.verify(current_code(self.secret))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "mfa_not_pending")

    def test_pending_verification_expires(self):
        self.login()
        session = self.client.session
        session[MFA_PENDING_AT_KEY] = time.time() - 600
        session.save()

        self.assertEqual(self.verify(current_code(self.secret)).status_code, 401)

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=2)
    def test_repeated_bad_codes_lock_the_account(self):
        self.login()
        self.verify("000001")
        response = self.verify("000002")

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)


class MfaEnrolmentTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = logged_in_client(self.user)

    def test_setup_and_confirm_enables_mfa(self):
        setup = self.client.post(reverse("auth-mfa-setup"))
        self.assertEqual(setup.status_code, 200)
        secret = setup.json()["secret"]
        self.assertTrue(setup.json()["otpauth_uri"].startswith("otpauth://totp/"))

        response = self.client.post(reverse("auth-mfa-confirm"), {"code": pyotp.TOTP(secret).now()}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["mfa_enabled"])
        entry = AuditLog.objects.get(action=AuditAction.MFA_ENABLED, user=self.user)
        self.assertEqual(entry.new_values, {"mfa_enabled": True})

    def test_secret_is_encrypted_at_rest_and_never_returned(self):
        secret = self.client.post(reverse("auth-mfa-setup")).json()["secret"]

        self.user.refresh_from_db()
        self.assertNotIn(secret, self.user.mfa_secret)
        self.assertEqual(mfa.decrypt_secret(self.user.mfa_secret), secret)
        self.assertNotIn(secret, self.client.get(reverse("auth-me")).content.decode())
        for entry in AuditLog.objects.all():
            self.assertNotIn(secret, str(entry.new_values) + entry.description)

    def test_wrong_code_does_not_enable_mfa(self):
        self.client.post(reverse("auth-mfa-setup"))

        response = self.client.post(reverse("auth-mfa-confirm"), {"code": "12345"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)

    def test_disable_requires_password_and_code(self):
        secret = enable_mfa(self.user)
        url = reverse("auth-mfa-disable")

        self.assertEqual(
            self.client.post(url, {"password": "wrong", "code": current_code(secret)}, format="json").status_code, 400
        )
        response = self.client.post(url, {"password": PASSWORD, "code": current_code(secret)}, format="json")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        self.assertEqual(self.user.mfa_secret, "")
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.MFA_DISABLED, user=self.user).exists())
