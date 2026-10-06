"""Seed the six staff roles and the default permission matrix (docs/architecture.md section 5).

The matrix is copied here, not imported, so this migration keeps producing the
same result if the application code changes later.
"""

from django.db import migrations

PERMISSIONS = {
    "device.view": "View devices",
    "device.create": "Register devices",
    "device.update": "Update device records",
    "recovery.manage": "Record and update recoveries",
    "assessment.create": "Create condition assessments",
    "refurbishment.manage": "Manage refurbishment work orders",
    "disposition.create": "Record reallocations and resales",
    "ai.request": "Request AI recommendations",
    "ai.view": "View AI recommendations",
    "ai.decide": "Accept or override AI recommendations",
    "ai.feedback": "Rate AI recommendations",
    "analytics.view": "View analytics and reports",
    "user.manage": "Manage user accounts",
    "role.manage": "Manage roles and permissions",
    "audit.view": "View the audit log",
    "config.manage": "Manage reference prices and settings",
}

AI_USER = ["ai.request", "ai.view", "ai.feedback"]

ROLES = [
    ("RECOVERY_OFFICER", "Recovery Officer", "Registers devices and records recoveries.",
     ["device.view", "device.create", "device.update", "recovery.manage"]),
    ("DEVICE_ASSESSOR", "Device Assessor", "Assesses the condition of recovered devices.",
     ["device.view", "assessment.create", *AI_USER]),
    ("REFURBISHMENT_STAFF", "Refurbishment Staff", "Carries out refurbishment work orders.",
     ["device.view", "refurbishment.manage", *AI_USER]),
    ("SALES_OFFICER", "Reallocation/Sales Officer", "Records reallocations and resales.",
     ["device.view", "disposition.create", *AI_USER]),
    ("OPERATIONS_MANAGER", "Operations Manager", "Oversees operations and decides on AI recommendations.",
     ["device.view", "device.update", *AI_USER, "ai.decide", "analytics.view"]),
    ("SYSTEM_ADMIN", "System Administrator", "Manages users, roles, configuration and the audit log.",
     ["device.view", "analytics.view", "user.manage", "role.manage", "audit.view", "config.manage"]),
]


def seed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perms = {
        code: Permission.objects.update_or_create(code=code, defaults={"description": desc})[0]
        for code, desc in PERMISSIONS.items()
    }
    for code, name, description, perm_codes in ROLES:
        role, created = Role.objects.get_or_create(code=code, defaults={"name": name, "description": description})
        if created:
            role.permissions.set([perms[c] for c in perm_codes])


def unseed(apps, schema_editor):
    apps.get_model("accounts", "Role").objects.filter(code__in=[r[0] for r in ROLES], users__isnull=True).delete()
    apps.get_model("accounts", "Permission").objects.filter(code__in=PERMISSIONS, roles__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_staff_user_rbac_login_attempts")]

    operations = [migrations.RunPython(seed, unseed)]
