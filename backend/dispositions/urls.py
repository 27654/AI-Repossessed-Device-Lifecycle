from django.urls import path

from . import views

urlpatterns = [
    path("dispositions/", views.DispositionListCreateView.as_view(), name="disposition-list"),
    path("dispositions/<int:pk>/", views.DispositionDetailView.as_view(), name="disposition-detail"),
    path("dispositions/<int:pk>/confirm/", views.confirm, name="disposition-confirm"),
    path(
        "dispositions/<int:pk>/attachments/",
        views.DispositionAttachmentListCreateView.as_view(),
        name="disposition-attachments",
    ),
]
