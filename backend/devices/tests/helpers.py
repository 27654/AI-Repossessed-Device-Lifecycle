import itertools
import shutil
import tempfile

from django.test import override_settings

from accounts.rbac import RoleCode
from accounts.tests.helpers import make_user
from devices import services
from devices.validators import luhn_valid

_serials = itertools.count(1)
_imei_bodies = itertools.count(35_000_000_000_000)


def valid_imei():
    """A fresh 15-digit IMEI with a correct Luhn check digit."""
    body = str(next(_imei_bodies))
    return next(body + d for d in "0123456789" if luhn_valid(body + d))


def device_payload(**overrides):
    payload = {
        "imei": valid_imei(),
        "serial_number": f"SN{next(_serials):06d}",
        "make": "Tecno",
        "model": "Spark 10",
        "device_type": "SMARTPHONE",
        "color": "Black",
        "storage_capacity_gb": 128,
        "operating_system": "Android 13",
        "current_location": "Kigali warehouse",
        "recovery_reference": "REC-2026-001",
        "recovery_date": "2026-09-15",
        "previous_owner_ref": "YA-0012345",
    }
    payload.update(overrides)
    return payload


def make_device(actor=None, initial_status="IN_RECOVERY", **overrides):
    actor = actor or make_user(RoleCode.RECOVERY_OFFICER)
    data = device_payload(**overrides)
    data.pop("recovery_date", None)
    return services.register_device(actor=actor, initial_status=initial_status, **data)


class TempMediaMixin:
    """Store uploads in a throwaway directory for the test class."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix="device-attachments-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
