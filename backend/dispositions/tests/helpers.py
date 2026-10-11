from accounts.rbac import RoleCode
from accounts.tests.helpers import make_user
from devices.models import DeviceStatus
from devices.services import transition_device
from dispositions import services
from refurbishment.tests.helpers import device_in


def ready_device():
    """A device that is Ready for disposition (assessed, then decided ready as-is)."""
    device = device_in(DeviceStatus.ASSESSED)
    transition_device(device, DeviceStatus.READY_FOR_DISPOSITION, actor=make_user(RoleCode.OPERATIONS_MANAGER))
    device.refresh_from_db()
    return device


def reallocation_fields(**overrides):
    fields = {
        "disposition_type": "REALLOCATION",
        "destination": "Musanze branch - field sales team",
        "recipient_reference": "EMP-0451",
        "notes": "Replacement handset for field agent.",
    }
    fields.update(overrides)
    return fields


def resale_fields(**overrides):
    fields = {
        "disposition_type": "RESALE",
        "sale_price_rwf": 65_000,
        "buyer_reference": "BUY-2026-0042",
        "notes": "Sold through Kigali showroom.",
    }
    fields.update(overrides)
    return fields


def make_disposition(device=None, officer=None, **fields):
    officer = officer or make_user(RoleCode.SALES_OFFICER)
    device = device or ready_device()
    return services.create_disposition(actor=officer, device=device, **(fields or resale_fields()))
