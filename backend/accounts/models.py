from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from .rbac import RoleCode


class Permission(models.Model):
    """An RBAC permission code such as `device.create` (see accounts.rbac.Perm)."""

    code = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Role(models.Model):
    """A named set of permissions. Each user has exactly one role."""

    code = models.CharField(max_length=40, unique=True, choices=RoleCode.choices)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Used by `createsuperuser`: a System Administrator with Django admin access."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if "role" not in extra_fields:
            extra_fields["role"] = Role.objects.filter(code=RoleCode.SYSTEM_ADMIN).first()
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    """Internal staff account. Email is the login identifier."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    employee_id = models.CharField(max_length=30, unique=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    account_status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # TOTP secret, Fernet-encrypted (accounts.mfa). Never serialized or logged.
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=255, blank=True, editable=False)
    # Last accepted TOTP time step, so a code cannot be replayed.
    mfa_last_used_step = models.BigIntegerField(null=True, blank=True, editable=False)

    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Django admin access only; application permissions come from the role.
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name", "employee_id"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        # Django's ModelBackend and session lookup reject inactive users, so
        # suspending or deactivating an account also ends its sessions.
        return self.account_status == self.Status.ACTIVE

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email

    def get_permission_codes(self):
        """Permission codes granted by the user's role, cached per instance."""
        if not hasattr(self, "_permission_codes"):
            if self.role_id is None or not self.is_active:
                self._permission_codes = frozenset()
            else:
                self._permission_codes = frozenset(self.role.permissions.values_list("code", flat=True))
        return self._permission_codes

    def has_permission_code(self, *codes):
        """True if the user's role grants every given permission code."""
        granted = self.get_permission_codes()
        return all(code in granted for code in codes)


class LoginAttempt(models.Model):
    """Every login attempt, successful or not."""

    class FailureReason(models.TextChoices):
        BAD_CREDENTIALS = "BAD_CREDENTIALS", "Bad credentials"
        LOCKED = "LOCKED", "Account locked"
        INACTIVE = "INACTIVE", "Account not active"
        BAD_MFA_CODE = "BAD_MFA_CODE", "Bad MFA code"

    email_attempted = models.CharField(max_length=254)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_attempts")
    success = models.BooleanField()
    failure_reason = models.CharField(max_length=20, choices=FailureReason.choices, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        outcome = "success" if self.success else self.failure_reason
        return f"{self.email_attempted} ({outcome})"
