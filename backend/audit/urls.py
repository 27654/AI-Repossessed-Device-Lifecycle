from django.urls import path

from . import views

urlpatterns = [
    path("audit-logs/", views.AuditLogListView.as_view(), name="audit-log-list"),
]
