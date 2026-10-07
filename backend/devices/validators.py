"""Validation for device identifiers and uploaded attachments."""

import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError

# Pseudonymous Yellow account reference (e.g. "YA-0012345"): letters, digits and
# - _ / only. Rejecting spaces keeps names and free text out of this field.
CUSTOMER_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]{2,59}$")


def normalize_imei(value):
    return re.sub(r"[\s-]", "", value or "")


def normalize_serial(value):
    return re.sub(r"\s", "", value or "").upper()


def luhn_valid(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_imei(value):
    if not (len(value) == 15 and value.isdigit()):
        raise ValidationError("IMEI must be exactly 15 digits.")
    if not luhn_valid(value):
        raise ValidationError("IMEI check digit is invalid. Check the number for typing errors.")


def validate_customer_ref(value):
    if value and not CUSTOMER_REF_PATTERN.match(value):
        raise ValidationError(
            "Use the Yellow account reference only (3-60 letters, digits, '-', '_' or '/'). "
            "Do not enter customer names or ID numbers."
        )


# --- Attachments ------------------------------------------------------------

# Detected type -> (stored extension, extensions accepted from the uploader).
ALLOWED_FILE_TYPES = {
    "image/jpeg": (".jpg", {".jpg", ".jpeg"}),
    "image/png": (".png", {".png"}),
    "image/webp": (".webp", {".webp"}),
    "application/pdf": (".pdf", {".pdf"}),
}


def detect_file_type(head):
    """MIME type from the file's leading bytes (its signature), or None."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def validate_attachment(upload):
    """Check size, signature and extension of an uploaded file. Returns the detected MIME type.

    The client-supplied Content-Type is ignored: only the file's own bytes decide its type.
    """
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if upload.size == 0:
        raise ValidationError("The file is empty.")
    if upload.size > max_bytes:
        raise ValidationError(f"The file is larger than {settings.MAX_UPLOAD_SIZE_MB} MB.")

    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    mime_type = detect_file_type(head)
    if mime_type is None:
        raise ValidationError("Only JPEG, PNG, WebP and PDF files are allowed.")

    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in ALLOWED_FILE_TYPES[mime_type][1]:
        raise ValidationError("The file extension does not match its content.")
    return mime_type


def clean_original_name(name):
    """Base name only, without control characters, at most 255 characters."""
    name = os.path.basename(name.replace("\\", "/"))
    name = "".join(ch for ch in name if ch.isprintable())
    return name[-255:] or "file"
