from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.permissions import require_permission, require_permission_by_method
from accounts.rbac import Perm
from assessments.models import Assessment

from . import services
from .models import AIFeedback, AIRecommendation, Recommendation
from .serializers import AIFeedbackSerializer, AIRecommendationSerializer, DecisionSerializer, FeedbackSerializer


def recommendation_queryset():
    return AIRecommendation.objects.select_related(
        "assessment__device", "requested_by", "final_decision_by"
    ).prefetch_related("feedback__user")


def _recommendation_response(assessment_id, http_status=status.HTTP_200_OK):
    recommendation = recommendation_queryset().get(assessment_id=assessment_id)
    return Response(AIRecommendationSerializer(recommendation).data, status=http_status)


@api_view(["GET", "POST"])
@permission_classes([require_permission_by_method(GET=Perm.AI_VIEW, POST=Perm.AI_REQUEST)])
def ai_recommendation(request, pk):
    """GET: the recommendation for an assessment (404 if none yet).

    POST: generate it from the submitted assessment (201), or return the
    existing one (200). Never changes the device.
    """
    assessment = get_object_or_404(Assessment, pk=pk)
    if request.method == "GET":
        if not AIRecommendation.objects.filter(assessment=assessment).exists():
            raise NotFound("No AI recommendation has been requested for this assessment yet.")
        return _recommendation_response(pk)

    _, created = services.generate_recommendation(assessment, actor=request.user, request=request)
    return _recommendation_response(pk, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([require_permission(Perm.AI_DECIDE)])
def decision(request, pk):
    """Record the human final decision (accept or override). The device moves to the decided status."""
    assessment = get_object_or_404(Assessment, pk=pk)
    serializer = DecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.record_decision(
        assessment,
        actor=request.user,
        final_decision=serializer.validated_data["final_decision"],
        reason=serializer.validated_data.get("reason", ""),
        request=request,
    )
    return _recommendation_response(pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.AI_FEEDBACK)])
def feedback(request, pk):
    """Record the signed-in user's verdict (accept / override) on the recommendation."""
    assessment = get_object_or_404(Assessment, pk=pk)
    serializer = FeedbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    created = services.record_feedback(
        assessment,
        actor=request.user,
        verdict=serializer.validated_data["verdict"],
        comment=serializer.validated_data.get("comment", ""),
        request=request,
    )
    return Response(AIFeedbackSerializer(AIFeedback.objects.select_related("user").get(pk=created.pk)).data,
                    status=status.HTTP_201_CREATED)


class AIRecommendationListView(generics.ListAPIView):
    """AI recommendation history.

    Filters: decision=pending|decided, recommendation, outcome=ACCEPTED|OVERRIDDEN,
    search (assessment reference, device code).
    """

    permission_classes = [require_permission(Perm.AI_VIEW)]
    serializer_class = AIRecommendationSerializer

    def get_queryset(self):
        qs = recommendation_queryset()
        params = self.request.query_params
        if params.get("decision") == "pending":
            qs = qs.filter(final_decision="")
        elif params.get("decision") == "decided":
            qs = qs.exclude(final_decision="")
        if params.get("recommendation") in Recommendation.values:
            qs = qs.filter(recommendation=params["recommendation"])
        if params.get("outcome") == "ACCEPTED":
            qs = qs.exclude(final_decision="").filter(final_decision=F("recommendation"))
        elif params.get("outcome") == "OVERRIDDEN":
            qs = qs.exclude(final_decision="").exclude(final_decision=F("recommendation"))
        if search := params.get("search", "").strip():
            qs = qs.filter(
                Q(assessment__reference__icontains=search) | Q(assessment__device__device_code__icontains=search)
            )
        return qs
