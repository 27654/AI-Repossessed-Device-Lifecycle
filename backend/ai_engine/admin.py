from django.contrib import admin

from devices.admin import ReadOnlyAdmin

from .models import AIFeedback, AIRecommendation


@admin.register(AIRecommendation)
class AIRecommendationAdmin(ReadOnlyAdmin):
    """Read-only: recommendations and decisions change only through ai_engine.services."""

    list_display = ["assessment", "recommendation", "score", "confidence", "rule_version", "final_decision", "generated_at"]
    list_filter = ["recommendation", "final_decision", "rule_version"]


@admin.register(AIFeedback)
class AIFeedbackAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "recommendation", "user", "verdict"]
    list_filter = ["verdict"]
