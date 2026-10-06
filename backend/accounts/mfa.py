"""TOTP multi-factor authentication helpers (authenticator apps, no SMS).

Secrets are stored Fernet-encrypted. The key comes from MFA_ENCRYPTION_KEY,
or is derived from DJANGO_SECRET_KEY when that is not set (changing the
secret key then invalidates every enrolled authenticator).
"""

import base64
import hashlib
import hmac
from datetime import datetime, timezone

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

# Accept the previous and next 30-second step to tolerate clock drift.
VALID_WINDOW = 1


def _fernet():
    key = settings.MFA_ENCRYPTION_KEY
    if not key:
        digest = hashlib.sha256(b"mfa-secret-encryption:" + settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def generate_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, email):
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.MFA_ISSUER_NAME)


def verify_code(user, code):
    """Check a TOTP code against the user's stored secret.

    Returns the matched time step, or None. A step at or before
    `user.mfa_last_used_step` is rejected so a code cannot be replayed.
    """
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6) or not user.mfa_secret:
        return None
    secret = decrypt_secret(user.mfa_secret)
    if secret is None:
        return None

    totp = pyotp.TOTP(secret)
    current_step = totp.timecode(datetime.now(timezone.utc))
    for offset in range(-VALID_WINDOW, VALID_WINDOW + 1):
        step = current_step + offset
        if hmac.compare_digest(totp.generate_otp(step), code):
            if user.mfa_last_used_step is not None and step <= user.mfa_last_used_step:
                return None
            return step
    return None
