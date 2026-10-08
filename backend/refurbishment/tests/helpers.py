from accounts.rbac import RoleCode
from accounts.tests.helpers import make_user
from assessments.tests.helpers import recovered_device
from devices.models import DeviceStatus
from devices.services import transition_device
from refurbishment import services
from refurbishment.models import StepStatus


def device_in(status, actor=None):
    """A device moved along the lifecycle to `status` (RECOVERED .. REFURBISHING)."""
    actor = actor or make_user(RoleCode.OPERATIONS_MANAGER)
    device = recovered_device()
    path = [DeviceStatus.ASSESSED, DeviceStatus.REFURBISHING]
    for step in path[: path.index(status) + 1] if status in path else []:
        transition_device(device, step, actor=actor)
    device.refresh_from_db()
    return device


def refurbishing_device():
    return device_in(DeviceStatus.REFURBISHING)


def make_work_order(device=None, technician=None, **fields):
    technician = technician or make_user(RoleCode.REFURBISHMENT_STAFF)
    device = device or refurbishing_device()
    fields.setdefault("diagnosis", "Cracked screen, weak battery.")
    fields.setdefault("estimated_cost_rwf", 30_000)
    return services.create_work_order(actor=technician, device=device, **fields)


def started_work_order(technician=None, **fields):
    technician = technician or make_user(RoleCode.REFURBISHMENT_STAFF)
    work_order = make_work_order(technician=technician, **fields)
    return services.start_work_order(work_order, actor=technician)


def finish_required_checks(work_order, technician):
    """Add and complete the functional test and quality check."""
    for step_type in ("FUNCTIONAL_TEST", "QUALITY_CHECK"):
        step = services.add_step(work_order, actor=technician, step_type=step_type)
        services.update_step(step, actor=technician, changes={"status": StepStatus.COMPLETED})


def ready_to_complete(technician=None):
    """A started work order with a part, the required checks done, summary and labour set."""
    technician = technician or make_user(RoleCode.REFURBISHMENT_STAFF)
    work_order = started_work_order(technician=technician)
    services.add_item(work_order, actor=technician, item_name="Screen assembly", quantity=1, unit_cost_rwf=15_000)
    services.add_item(work_order, actor=technician, item_name="Adhesive strip", quantity=2, unit_cost_rwf=500)
    finish_required_checks(work_order, technician)
    services.update_work_order(
        work_order, actor=technician, changes={"work_summary": "Replaced screen; tested.", "labour_cost_rwf": 5_000}
    )
    return work_order, technician
