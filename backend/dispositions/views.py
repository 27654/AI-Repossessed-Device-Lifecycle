from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
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
from .models import Disposition, DispositionStatus, DispositionType
from .serializers import DispositionSerializer

READ_OR_WRITE = require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.DISPOSITION_CREATE)
SEARCH_FIELDS = [
    "reference",
    "device__device_code",
    "device__imei",
    "device__serial_number",
    "buyer_reference",
    "recipient_reference",
    "destination",
]
ATTACHMENT_LINKS = ("uploaded_by", "recovery", "assessment", "refurbishment", "disposition")


def _date(value):
    try:
        return parse_date(value or "")
    except ValueError:
        return None


def disposition_queryset():
    return Disposition.objects.select_related("device", "responsible_user", "confirmed_by").prefetch_related(
        Prefetch("attachments", queryset=Attachment.objects.select_related(*ATTACHMENT_LINKS))
    )


class DispositionListCreateView(generics.ListCreateAPIView):
    """List dispositions, or draft one for a device that is Ready for disposition.

    Filters: device (id), type, status, search (reference, device code/IMEI/serial,
    buyer/recipient reference, destination), date_from, date_to (YYYY-MM-DD).
    """

    permission_classes = [READ_OR_WRITE]
    serializer_class = DispositionSerializer

    def get_queryset(self):
        qs = disposition_queryset()
        params = self.request.query_params
        if (device := params.get("device", "")).isdigit():
            qs = qs.filter(device_id=int(device))
        if params.get("type") in DispositionType.values:
            qs = qs.filter(disposition_type=params["type"])
        if params.get("status") in DispositionStatus.values:
            qs = qs.filter(status=params["status"])
        if date_from := _date(params.get("date_from")):
            qs = qs.filter(disposition_date__gte=date_from)
        if date_to := _date(params.get("date_to")):
            qs = qs.filter(disposition_date__lte=date_to)
        if search := params.get("search", "").strip():
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            qs = qs.filter(query)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        device = data.pop("device")
        created = services.create_disposition(actor=self.request.user, device=device, request=self.request, **data)
        serializer.instance = disposition_queryset().get(pk=created.pk)


class DispositionDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, PATCH=Perm.DISPOSITION_CREATE)]
    serializer_class = DispositionSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return disposition_queryset()

    def perform_update(self, serializer):
        services.update_disposition(
            serializer.instance, actor=self.request.user, changes=dict(serializer.validated_data), request=self.request
        )
        serializer.instance = disposition_queryset().get(pk=serializer.instance.pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.DISPOSITION_CREATE)])
def confirm(request, pk):
    """Confirm a draft. The device moves to Reallocated or Resold and the record becomes read-only."""
    disposition = get_object_or_404(Disposition, pk=pk)
    services.confirm_disposition(disposition, actor=request.user, request=request)
    return Response(DispositionSerializer(disposition_queryset().get(pk=pk)).data, status=status.HTTP_200_OK)


class DispositionAttachmentListCreateView(generics.ListCreateAPIView):
    """Evidence files for a disposition (receipts, handover forms). Uploads reuse the device attachment checks."""

    permission_classes = [READ_OR_WRITE]
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_disposition(self):
        return get_object_or_404(Disposition.objects.select_related("device"), pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_disposition().attachments.select_related(*ATTACHMENT_LINKS)

    def perform_create(self, serializer):
        disposition = self.get_disposition()
        if not disposition.is_draft:
            raise ValidationError(
                {"detail": "Evidence can only be added while the disposition is a draft. "
                 "Add later files to the device instead."}
            )
        data = serializer.validated_data
        serializer.instance = device_services.add_attachment(
            disposition.device,
            actor=self.request.user,
            upload=data["file"],
            mime_type=data["mime_type"],
            original_name=data["original_name"],
            description=data.get("description", ""),
            disposition=disposition,
            request=self.request,
        )
