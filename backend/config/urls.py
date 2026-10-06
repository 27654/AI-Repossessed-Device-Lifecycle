from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("api/health/", views.health, name="health"),
    path("api/", include("accounts.urls")),
    path("api/", include("audit.urls")),
    # Lifecycle module routes (api/devices/, ...) are added phase by phase.
]

if settings.DEBUG:
    # The Django admin signs in with a password only (no MFA, no audit), so it
    # is a development tool and is not mounted outside DEBUG.
    urlpatterns.append(path("admin/", admin.site.urls))
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
