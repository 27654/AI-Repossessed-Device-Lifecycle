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
from .models import Recovery, RecoveryOutcome, RecoveryStatus
from .serializers import RecoverySerializer

SEARCH_FIELDS = ["reference", "device__device_code", "device__imei", "device__serial_number", "recovery_location"]


def recovery_queryset():
    return Recovery.objects.select_related("device", "recovery_officer", "completed_by").prefetch_related(
        Prefetch("attachments", queryset=Attachment.objects.select_related("uploaded_by", "recovery", "assessment", "refurbishment", "disposition"))
    )


class RecoveryListCreateView(generics.ListCreateAPIView):
    """List recovery records, or open one for a device that is In recovery.

    Filters: device (id), status, outcome, search (reference, device code, IMEI,
    serial number, location).
    """

    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.RECOVERY_MANAGE)]
    serializer_class = RecoverySerializer

    def get_queryset(self):
        qs = recovery_queryset()
        params = self.request.query_params
        if (device := params.get("device", "")).isdigit():
            qs = qs.filter(device_id=int(device))
        if params.get("status") in RecoveryStatus.values:
            qs = qs.filter(status=params["status"])
        if params.get("outcome") in RecoveryOutcome.values:
            qs = qs.filter(outcome=params["outcome"])
        if search := params.get("search", "").strip():
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            qs = qs.filter(query)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        device = data.pop("device")
        serializer.instance = services.create_recovery(
            actor=self.request.user, device=device, request=self.request, **data
        )


class RecoveryDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, PATCH=Perm.RECOVERY_MANAGE)]
    serializer_class = RecoverySerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return recovery_queryset()

    def perform_update(self, serializer):
        services.update_recovery(
            serializer.instance,
            actor=self.request.user,
            changes=dict(serializer.validated_data),
            request=self.request,
        )
        serializer.instance = recovery_queryset().get(pk=serializer.instance.pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.RECOVERY_MANAGE)])
def complete_recovery(request, pk):
    """Complete a recovery. A successful outcome moves the device to Recovered."""
    recovery = get_object_or_404(Recovery, pk=pk)
    services.complete_recovery(recovery, actor=request.user, request=request)
    return Response(RecoverySerializer(recovery_queryset().get(pk=pk)).data, status=status.HTTP_200_OK)


class RecoveryAttachmentListCreateView(generics.ListCreateAPIView):
    """Evidence files for a recovery. Uploads reuse the device attachment checks and storage."""

    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.RECOVERY_MANAGE)]
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_recovery(self):
        return get_object_or_404(Recovery.objects.select_related("device"), pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_recovery().attachments.select_related("uploaded_by", "recovery", "assessment", "refurbishment", "disposition")

    def perform_create(self, serializer):
        recovery = self.get_recovery()
        if not recovery.is_open:
            raise ValidationError(
                {"detail": "Evidence can only be added while the recovery is in progress. "
                 "Add later files to the device instead."}
            )
        data = serializer.validated_data
        serializer.instance = device_services.add_attachment(
            recovery.device,
            actor=self.request.user,
            upload=data["file"],
            mime_type=data["mime_type"],
            original_name=data["original_name"],
            description=data.get("description", ""),
            recovery=recovery,
            request=self.request,
        )
