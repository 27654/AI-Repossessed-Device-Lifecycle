from django.utils.dateparse import parse_date
from rest_framework import generics

from accounts.permissions import require_permission
from accounts.rbac import Perm

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(generics.ListAPIView):
    """Read-only audit trail. Filters: user, action, entity_type, entity_id, from, to (YYYY-MM-DD)."""

    permission_classes = [require_permission(Perm.AUDIT_VIEW)]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.all()
        params = self.request.query_params
        if params.get("user", "").isdigit():
            qs = qs.filter(user_id=params["user"])
        for field in ("action", "entity_type", "entity_id"):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        if date_from := _parse_date(params.get("from")):
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to := _parse_date(params.get("to")):
            qs = qs.filter(created_at__date__lte=date_to)
        return qs


def _parse_date(value):
    try:
        return parse_date(value or "")
    except ValueError:  # well-formed but impossible, e.g. 2026-02-30
        return None
