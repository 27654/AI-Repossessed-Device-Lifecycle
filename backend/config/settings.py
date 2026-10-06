"""
Django settings for the Repossessed Device Lifecycle Management System.

All secrets and environment-specific values come from environment variables,
loaded from the repository-root `.env` file (see `.env.example`).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "corsheaders",
    # Project apps
    "accounts",
    "devices",
    "recovery",
    "assessments",
    "refurbishment",
    "dispositions",
    "ai_engine",
    "notifications",
    "audit",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.SessionTimeoutMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# PostgreSQL is the only supported database, for development and tests alike.
# `manage.py test` creates a separate `test_repossessed_devices` database.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "repossessed_devices"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}


# Authentication
# Staff log in with email + password, then a TOTP code if MFA is enabled.
# Application permissions come from the user's role (accounts.rbac).

AUTH_USER_MODEL = "accounts.User"

# Lock an account for LOGIN_LOCKOUT_MINUTES after this many consecutive failures.
LOGIN_LOCKOUT_THRESHOLD = int(os.environ.get("LOGIN_LOCKOUT_THRESHOLD", 5))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", 15))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Sessions and CSRF
# Session cookie auth: the browser holds an HttpOnly session cookie; the
# frontend sends the CSRF token header on unsafe requests.

SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", 60 * 60 * 8))  # maximum session length: one working day
SESSION_IDLE_TIMEOUT = int(os.environ.get("SESSION_IDLE_TIMEOUT", 60 * 30))  # sign out after 30 idle minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# CORS: in development the Vite dev server proxies /api to Django, so requests
# are same-origin. These settings cover direct cross-origin access.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True


# Django REST Framework
# Deny by default: every endpoint requires an authenticated user unless it
# explicitly opts out (e.g. login, health check). Not logged in -> 401;
# logged in without the role permission -> 403.

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")


# Internationalization
# Yellow Rwanda: Kigali time zone, amounts in Rwandan Francs.

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kigali"
USE_I18N = True
USE_TZ = True

DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "RWF")


# Static and uploaded files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", 5))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# MFA (TOTP)

MFA_ISSUER_NAME = os.environ.get("MFA_ISSUER_NAME", "Yellow Device Lifecycle")
# Fernet key for encrypting TOTP secrets at rest. If empty, a key is derived from DJANGO_SECRET_KEY.
MFA_ENCRYPTION_KEY = os.environ.get("MFA_ENCRYPTION_KEY", "")
# Seconds a user has to enter the TOTP code after a correct password.
MFA_PENDING_TIMEOUT = int(os.environ.get("MFA_PENDING_TIMEOUT", 300))
