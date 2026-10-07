from django.urls import path

from . import views

urlpatterns = [
    path("devices/", views.DeviceListCreateView.as_view(), name="device-list"),
    path("devices/<int:pk>/", views.DeviceDetailView.as_view(), name="device-detail"),
    path("devices/<int:pk>/history/", views.DeviceHistoryView.as_view(), name="device-history"),
    path("devices/<int:pk>/attachments/", views.DeviceAttachmentListCreateView.as_view(), name="device-attachments"),
    path(
        "devices/<int:pk>/attachments/<int:attachment_id>/download/",
        views.attachment_download,
        name="device-attachment-download",
    ),
]
