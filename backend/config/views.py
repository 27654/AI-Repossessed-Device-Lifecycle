from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Liveness check used by the frontend and the README startup steps."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:
        database = "unavailable"

    return Response(
        {
            "status": "ok" if database == "ok" else "degraded",
            "database": database,
            "database_engine": connection.vendor,
            "currency": settings.DEFAULT_CURRENCY,
        },
        status=200 if database == "ok" else 503,
    )
