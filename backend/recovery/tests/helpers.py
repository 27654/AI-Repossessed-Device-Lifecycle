from datetime import timedelta

from django.utils import timezone

from recovery import services


def recovery_fields(**overrides):
    fields = {
        "recovered_at": timezone.now() - timedelta(hours=2),
        "recovery_location": "Nyarugenge, Kigali",
        "recovery_method": "FIELD_COLLECTION",
        "outcome": "RECOVERED",
        "condition_notes": "Screen scratched, powers on.",
        "notes": "",
    }
    fields.update(overrides)
    return fields


def recovery_payload(device, **overrides):
    """JSON body for POST /api/recoveries/."""
    payload = recovery_fields(**overrides)
    if hasattr(payload["recovered_at"], "isoformat"):
        payload["recovered_at"] = payload["recovered_at"].isoformat()
    return {"device": device.pk, **payload}


def make_recovery(device, officer, **overrides):
    return services.create_recovery(actor=officer, device=device, **recovery_fields(**overrides))
