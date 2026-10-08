from django.urls import path

from . import views

urlpatterns = [
    path("assessments/", views.AssessmentListCreateView.as_view(), name="assessment-list"),
    path("assessments/<int:pk>/", views.AssessmentDetailView.as_view(), name="assessment-detail"),
    path("assessments/<int:pk>/submit/", views.submit_assessment, name="assessment-submit"),
    path(
        "assessments/<int:pk>/attachments/",
        views.AssessmentAttachmentListCreateView.as_view(),
        name="assessment-attachments",
    ),
]
