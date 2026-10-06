from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Internal staff user.

    Defined at project start because Django requires the custom user model to
    exist before the first migration. Staff fields (employee ID, phone, role,
    account status, MFA) are added in the authentication phase.
    """
