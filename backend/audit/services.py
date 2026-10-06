from .models import AuditLog


def get_client_ip(request):
    """Client IP from the socket address.

    X-Forwarded-For is ignored: without a trusted proxy in front of Django it
    can be forged by the client.
    """
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def get_user_agent(request):
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:255]


def log_action(
    action,
    *,
    request=None,
    user=None,
    user_label="",
    entity=None,
    entity_type="",
    entity_id="",
    description="",
    previous_values=None,
    new_values=None,
):
    """Write one audit log entry.

    `user` defaults to the request's authenticated user. `entity` (a model
    instance) fills `entity_type` and `entity_id`. Never pass passwords, MFA
    secrets or session data in the value dictionaries.
    """
    if user is None and request is not None and request.user.is_authenticated:
        user = request.user
    if entity is not None:
        entity_type = entity_type or entity._meta.model_name
        entity_id = entity_id or entity.pk

    return AuditLog.objects.create(
        user=user,
        user_label=user_label or (user.email if user else ""),
        action=action,
        entity_type=entity_type,
        entity_id="" if entity_id in (None, "") else str(entity_id),
        previous_values=previous_values,
        new_values=new_values,
        description=description[:255],
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
