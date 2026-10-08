from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import require_permission, require_permission_by_method
from accounts.rbac import Perm
from devices import services as device_services
from devices.models import Attachment
from devices.serializers import AttachmentSerializer

from . import services
from .models import Assessment, AssessmentStatus
from .serializers import AssessmentSerializer

SEARCH_FIELDS = ["reference", "device__device_code", "device__imei", "device__serial_number", "device__make", "device__model"]


def assessment_queryset():
    return Assessment.objects.select_related("device", "assessor", "ai_recommendation").prefetch_related(
        Prefetch("attachments", queryset=Attachment.objects.select_related("uploaded_by", "recovery", "assessment"))
    )


class AssessmentListCreateView(generics.ListCreateAPIView):
    """List assessments, or start a Draft for a Recovered device.

    Filters: device (id), status, search (reference, device code, IMEI, serial, make, model).
    """

    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.ASSESSMENT_CREATE)]
    serializer_class = AssessmentSerializer

    def get_queryset(self):
        qs = assessment_queryset()
        params = self.request.query_params
        if (device := params.get("device", "")).isdigit():
            qs = qs.filter(device_id=int(device))
        if params.get("status") in AssessmentStatus.values:
            qs = qs.filter(status=params["status"])
        if search := params.get("search", "").strip():
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            qs = qs.filter(query)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        device = data.pop("device")
        created = services.create_assessment(actor=self.request.user, device=device, request=self.request, **data)
        serializer.instance = assessment_queryset().get(pk=created.pk)


class AssessmentDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, PATCH=Perm.ASSESSMENT_CREATE)]
    serializer_class = AssessmentSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return assessment_queryset()

    def perform_update(self, serializer):
        services.update_assessment(
            serializer.instance,
            actor=self.request.user,
            changes=dict(serializer.validated_data),
            request=self.request,
        )
        serializer.instance = assessment_queryset().get(pk=serializer.instance.pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.ASSESSMENT_CREATE)])
def submit_assessment(request, pk):
    """Submit a Draft. The device moves RECOVERED -> ASSESSED and the assessment becomes read-only."""
    assessment = get_object_or_404(Assessment, pk=pk)
    services.submit_assessment(assessment, actor=request.user, request=request)
    return Response(AssessmentSerializer(assessment_queryset().get(pk=pk)).data, status=status.HTTP_200_OK)


class AssessmentAttachmentListCreateView(generics.ListCreateAPIView):
    """Evidence files for an assessment. Uploads reuse the device attachment checks and storage."""

    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.ASSESSMENT_CREATE)]
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_assessment(self):
        return get_object_or_404(Assessment.objects.select_related("device"), pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_assessment().attachments.select_related("uploaded_by", "recovery", "assessment")

    def perform_create(self, serializer):
        assessment = self.get_assessment()
        if not assessment.is_draft:
            raise ValidationError(
                {"detail": "Evidence can only be added while the assessment is a draft. "
                 "Add later files to the device instead."}
            )
        data = serializer.validated_data
        serializer.instance = device_services.add_attachment(
            assessment.device,
            actor=self.request.user,
            upload=data["file"],
            mime_type=data["mime_type"],
            original_name=data["original_name"],
            description=data.get("description", ""),
            assessment=assessment,
            request=self.request,
        )
