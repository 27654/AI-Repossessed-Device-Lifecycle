from accounts.rbac import RoleCode
from accounts.tests.helpers import make_user
from assessments import services
from devices.models import DeviceStatus
from devices.tests.helpers import make_device


def recovered_device(actor=None, **overrides):
    actor = actor or make_user(RoleCode.RECOVERY_OFFICER)
    return make_device(actor=actor, initial_status=DeviceStatus.RECOVERED, **overrides)


def assessment_fields(**overrides):
    """A complete, valid assessment: partially working phone with a damaged screen (rules: REFURBISH)."""
    fields = {
        "physical_condition": "GOOD",
        "cosmetic_condition": "GOOD",
        "screen_condition": "MAJOR_DAMAGE",
        "battery_condition": "FAIR",
        "functional_status": "PARTIALLY_FUNCTIONAL",
        "accessories_condition": "PARTIAL",
        "defects": [],
        "assessment_notes": "Screen cracked across the top; touch works.",
        "estimated_repair_cost_rwf": 18_000,
        "estimated_market_value_rwf": 85_000,
    }
    fields.update(overrides)
    return fields


def assessment_payload(device, **overrides):
    """JSON body for POST /api/assessments/."""
    return {"device": device.pk, **assessment_fields(**overrides)}


def make_assessment(device, assessor, **overrides):
    return services.create_assessment(actor=assessor, device=device, **assessment_fields(**overrides))


def submitted_assessment(device=None, assessor=None, **overrides):
    """A Recovered device with a submitted assessment (device is then ASSESSED)."""
    assessor = assessor or make_user(RoleCode.DEVICE_ASSESSOR)
    device = device or recovered_device()
    assessment = make_assessment(device, assessor, **overrides)
    return services.submit_assessment(assessment, actor=assessor)
