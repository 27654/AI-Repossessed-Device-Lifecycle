from django.urls import path

from . import views

urlpatterns = [
    path("assessments/<int:pk>/ai-recommendation/", views.ai_recommendation, name="assessment-ai-recommendation"),
    path("assessments/<int:pk>/decision/", views.decision, name="assessment-decision"),
    path("assessments/<int:pk>/ai-feedback/", views.feedback, name="assessment-ai-feedback"),
    path("ai-recommendations/", views.AIRecommendationListView.as_view(), name="ai-recommendation-list"),
]
