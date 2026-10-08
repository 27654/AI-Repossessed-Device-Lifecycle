from django.urls import path

from . import views

urlpatterns = [
    path("recoveries/", views.RecoveryListCreateView.as_view(), name="recovery-list"),
    path("recoveries/<int:pk>/", views.RecoveryDetailView.as_view(), name="recovery-detail"),
    path("recoveries/<int:pk>/complete/", views.complete_recovery, name="recovery-complete"),
    path("recoveries/<int:pk>/attachments/", views.RecoveryAttachmentListCreateView.as_view(), name="recovery-attachments"),
]
