from django.db import IntegrityError
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser

from accounts.permissions import require_permission, require_permission_by_method
from accounts.rbac import Perm

from . import services
from .models import Attachment, Device, DeviceCondition, DeviceStatus
from .serializers import AttachmentSerializer, DeviceListSerializer, DeviceSerializer, DeviceStatusChangeSerializer

SEARCH_FIELDS = ["device_code", "imei", "serial_number", "make", "model", "previous_owner_ref", "recovery_reference"]


def _parse_date(value):
    try:
        return parse_date(value or "")
    except ValueError:
        return None


def _save_or_conflict(save):
    """Turn a uniqueness race that slipped past validation into a 400, not a 500."""
    try:
        return save()
    except IntegrityError as exc:
        raise ValidationError({"detail": "A device with this IMEI or serial number already exists."}) from exc


class DeviceListCreateView(generics.ListCreateAPIView):
    """List with search/filters, or register a device.

    Filters: search, status (comma-separated), make, model, device_type,
    condition, recovered_from, recovered_to (YYYY-MM-DD, on recovery_date).
    """

    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.DEVICE_CREATE)]

    def get_serializer_class(self):
        return DeviceSerializer if self.request.method == "POST" else DeviceListSerializer

    def get_queryset(self):
        qs = Device.objects.all()
        params = self.request.query_params

        if search := params.get("search", "").strip():
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            qs = qs.filter(query)
        if statuses := [s for s in params.get("status", "").split(",") if s in DeviceStatus.values]:
            qs = qs.filter(status__in=statuses)
        if params.get("condition") in DeviceCondition.values:
            qs = qs.filter(current_condition=params["condition"])
        for field in ("make", "model", "device_type"):
            if value := params.get(field, "").strip():
                qs = qs.filter(**{f"{field}__iexact": value})
        if date_from := _parse_date(params.get("recovered_from")):
            qs = qs.filter(recovery_date__gte=date_from)
        if date_to := _parse_date(params.get("recovered_to")):
            qs = qs.filter(recovery_date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        initial_status = data.pop("initial_status")
        serializer.instance = _save_or_conflict(
            lambda: services.register_device(
                actor=self.request.user, initial_status=initial_status, request=self.request, **data
            )
        )


class DeviceDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, PATCH=Perm.DEVICE_UPDATE)]
    serializer_class = DeviceSerializer
    queryset = Device.objects.select_related("created_by")
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        serializer.instance = _save_or_conflict(
            lambda: services.update_device(
                serializer.instance,
                actor=self.request.user,
                changes=dict(serializer.validated_data),
                request=self.request,
            )
        )


class DeviceHistoryView(generics.ListAPIView):
    """Lifecycle history, newest first. Read-only: entries are never changed."""

    permission_classes = [require_permission(Perm.DEVICE_VIEW)]
    serializer_class = DeviceStatusChangeSerializer
    pagination_class = None

    def get_queryset(self):
        device = get_object_or_404(Device, pk=self.kwargs["pk"])
        return device.status_changes.select_related("changed_by")


class DeviceAttachmentListCreateView(generics.ListCreateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.DEVICE_UPDATE)]
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_device(self):
        return get_object_or_404(Device, pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_device().attachments.select_related("uploaded_by", "recovery")

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.add_attachment(
            self.get_device(),
            actor=self.request.user,
            upload=data["file"],
            mime_type=data["mime_type"],
            original_name=data["original_name"],
            description=data.get("description", ""),
            request=self.request,
        )


@api_view(["GET"])
@permission_classes([require_permission(Perm.DEVICE_VIEW)])
def attachment_download(request, pk, attachment_id):
    """Stream an attachment to a user allowed to view the device. Files are never served publicly."""
    attachment = get_object_or_404(Attachment, pk=attachment_id, device_id=pk)
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("File not found.") from exc
    response = FileResponse(handle, content_type=attachment.mime_type, filename=attachment.original_name)
    response["Content-Disposition"] = response["Content-Disposition"].replace("attachment", "inline", 1)
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, no-store"
    return response
