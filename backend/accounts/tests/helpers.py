import itertools

import pyotp
from rest_framework.test import APIClient

from accounts import mfa
from accounts.models import Role, User
from accounts.rbac import RoleCode

PASSWORD = "Str0ng-Pass-123!"

_employee_numbers = itertools.count(1)


def make_user(role_code=RoleCode.RECOVERY_OFFICER, email=None, password=PASSWORD, **fields):
    number = next(_employee_numbers)
    fields.setdefault("full_name", f"Test User {number}")
    fields.setdefault("employee_id", f"EMP-{number:04d}")
    role = Role.objects.get(code=role_code) if role_code else None
    return User.objects.create_user(email=email or f"user{number}@yellow.test", password=password, role=role, **fields)


def enable_mfa(user):
    """Enrol the user in MFA directly and return the plaintext secret for generating codes."""
    secret = mfa.generate_secret()
    user.mfa_secret = mfa.encrypt_secret(secret)
    user.mfa_enabled = True
    user.save()
    return secret


def current_code(secret):
    return pyotp.TOTP(secret).now()


def logged_in_client(user):
    client = APIClient()
    client.force_login(user)
    return client
