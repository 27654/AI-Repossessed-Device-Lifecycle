"""Role and permission codes used across the backend.

Roles and their default permissions are stored in the database (seeded by
migration `0002_seed_roles_and_permissions`) so an administrator can change
them later. Code refers to permissions only through these constants.
"""

from django.db import models


class RoleCode(models.TextChoices):
    RECOVERY_OFFICER = "RECOVERY_OFFICER", "Recovery Officer"
    DEVICE_ASSESSOR = "DEVICE_ASSESSOR", "Device Assessor"
    REFURBISHMENT_STAFF = "REFURBISHMENT_STAFF", "Refurbishment Staff"
    SALES_OFFICER = "SALES_OFFICER", "Reallocation/Sales Officer"
    OPERATIONS_MANAGER = "OPERATIONS_MANAGER", "Operations Manager"
    SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Administrator"


class Perm:
    DEVICE_VIEW = "device.view"
    DEVICE_CREATE = "device.create"
    DEVICE_UPDATE = "device.update"
    RECOVERY_MANAGE = "recovery.manage"
    ASSESSMENT_CREATE = "assessment.create"
    REFURBISHMENT_MANAGE = "refurbishment.manage"
    DISPOSITION_CREATE = "disposition.create"
    AI_REQUEST = "ai.request"
    AI_VIEW = "ai.view"
    AI_DECIDE = "ai.decide"
    AI_FEEDBACK = "ai.feedback"
    ANALYTICS_VIEW = "analytics.view"
    USER_MANAGE = "user.manage"
    ROLE_MANAGE = "role.manage"
    AUDIT_VIEW = "audit.view"
    CONFIG_MANAGE = "config.manage"
