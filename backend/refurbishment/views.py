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
from .models import RefurbishmentItem, RefurbishmentStep, RefurbishmentWorkOrder, WorkOrderStatus
from .serializers import (
    CompleteSerializer,
    ReasonSerializer,
    RefurbishmentItemSerializer,
    RefurbishmentStepSerializer,
    StepUpdateSerializer,
    TechnicianSerializer,
    WorkOrderSerializer,
)

READ_OR_MANAGE = require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.REFURBISHMENT_MANAGE)
SEARCH_FIELDS = ["reference", "device__device_code", "device__imei", "device__serial_number", "device__make", "device__model"]


def work_order_queryset():
    return RefurbishmentWorkOrder.objects.select_related(
        "device", "assigned_to", "created_by", "completed_by"
    ).prefetch_related(
        Prefetch("steps", queryset=RefurbishmentStep.objects.select_related("performed_by")),
        Prefetch("items", queryset=RefurbishmentItem.objects.select_related("created_by")),
        Prefetch(
            "attachments",
            queryset=Attachment.objects.select_related("uploaded_by", "recovery", "assessment", "refurbishment"),
        ),
    )


def _work_order_response(pk, http_status=status.HTTP_200_OK):
    return Response(WorkOrderSerializer(work_order_queryset().get(pk=pk)).data, status=http_status)


class WorkOrderListCreateView(generics.ListCreateAPIView):
    """List work orders, or open one for a device that is Refurbishing.

    Filters: device (id), status, assigned_to (user id, or "me"), search
    (reference, device code, IMEI, serial, make, model).
    """

    permission_classes = [READ_OR_MANAGE]
    serializer_class = WorkOrderSerializer

    def get_queryset(self):
        qs = work_order_queryset()
        params = self.request.query_params
        if (device := params.get("device", "")).isdigit():
            qs = qs.filter(device_id=int(device))
        if params.get("status") in WorkOrderStatus.values:
            qs = qs.filter(status=params["status"])
        elif params.get("status") == "ACTIVE":
            qs = qs.filter(status__in=(WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS))
        assigned = params.get("assigned_to", "")
        if assigned == "me":
            qs = qs.filter(assigned_to=self.request.user)
        elif assigned.isdigit():
            qs = qs.filter(assigned_to_id=int(assigned))
        if search := params.get("search", "").strip():
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            qs = qs.filter(query)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        created = services.create_work_order(actor=self.request.user, request=self.request, **data)
        serializer.instance = work_order_queryset().get(pk=created.pk)


class WorkOrderDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission_by_method(GET=Perm.DEVICE_VIEW, PATCH=Perm.REFURBISHMENT_MANAGE)]
    serializer_class = WorkOrderSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return work_order_queryset()

    def perform_update(self, serializer):
        services.update_work_order(
            serializer.instance, actor=self.request.user, changes=dict(serializer.validated_data), request=self.request
        )
        serializer.instance = work_order_queryset().get(pk=serializer.instance.pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def start(request, pk):
    services.start_work_order(get_object_or_404(RefurbishmentWorkOrder, pk=pk), actor=request.user, request=request)
    return _work_order_response(pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def complete(request, pk):
    """Complete as repaired: the device moves to Ready for disposition."""
    work_order = get_object_or_404(RefurbishmentWorkOrder, pk=pk)
    serializer = CompleteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.complete_work_order(work_order, actor=request.user, request=request, **serializer.validated_data)
    return _work_order_response(pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def unable_to_repair(request, pk):
    """Close as unable to repair (reason required): the device moves to Unable to repair."""
    work_order = get_object_or_404(RefurbishmentWorkOrder, pk=pk)
    serializer = ReasonSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.mark_unable_to_repair(work_order, actor=request.user, reason=serializer.validated_data["reason"],
                                   request=request)
    return _work_order_response(pk)


@api_view(["POST"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def cancel(request, pk):
    """Cancel a work order opened in error (reason required). The device stays Refurbishing."""
    work_order = get_object_or_404(RefurbishmentWorkOrder, pk=pk)
    serializer = ReasonSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.cancel_work_order(work_order, actor=request.user, reason=serializer.validated_data["reason"],
                               request=request)
    return _work_order_response(pk)


class StepListCreateView(generics.ListCreateAPIView):
    permission_classes = [READ_OR_MANAGE]
    serializer_class = RefurbishmentStepSerializer
    pagination_class = None

    def get_work_order(self):
        return get_object_or_404(RefurbishmentWorkOrder, pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_work_order().steps.select_related("performed_by")

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.add_step(
            self.get_work_order(),
            actor=self.request.user,
            step_type=data["step_type"],
            description=data.get("description", ""),
            notes=data.get("notes", ""),
            request=self.request,
        )


@api_view(["PATCH"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def update_step(request, pk):
    step = get_object_or_404(RefurbishmentStep.objects.select_related("work_order"), pk=pk)
    serializer = StepUpdateSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    step = services.update_step(step, actor=request.user, changes=dict(serializer.validated_data), request=request)
    step = RefurbishmentStep.objects.select_related("performed_by").get(pk=step.pk)
    return Response(RefurbishmentStepSerializer(step).data)


class ItemListCreateView(generics.ListCreateAPIView):
    permission_classes = [READ_OR_MANAGE]
    serializer_class = RefurbishmentItemSerializer
    pagination_class = None

    def get_work_order(self):
        return get_object_or_404(RefurbishmentWorkOrder, pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_work_order().items.select_related("created_by")

    def perform_create(self, serializer):
        serializer.instance = services.add_item(
            self.get_work_order(), actor=self.request.user, request=self.request, **serializer.validated_data
        )


@api_view(["PATCH"])
@permission_classes([require_permission(Perm.REFURBISHMENT_MANAGE)])
def update_item(request, pk):
    item = get_object_or_404(RefurbishmentItem.objects.select_related("work_order"), pk=pk)
    serializer = RefurbishmentItemSerializer(item, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    item = services.update_item(item, actor=request.user, changes=dict(serializer.validated_data), request=request)
    return Response(RefurbishmentItemSerializer(RefurbishmentItem.objects.select_related("created_by").get(pk=item.pk)).data)


class WorkOrderAttachmentListCreateView(generics.ListCreateAPIView):
    """Evidence files for a work order. Uploads reuse the device attachment checks and storage."""

    permission_classes = [READ_OR_MANAGE]
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_work_order(self):
        return get_object_or_404(RefurbishmentWorkOrder.objects.select_related("device"), pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_work_order().attachments.select_related("uploaded_by", "recovery", "assessment", "refurbishment")

    def perform_create(self, serializer):
        work_order = self.get_work_order()
        if not work_order.is_active:
            raise ValidationError(
                {"detail": "Evidence can only be added while the work order is active. "
                 "Add later files to the device instead."}
            )
        data = serializer.validated_data
        serializer.instance = device_services.add_attachment(
            work_order.device,
            actor=self.request.user,
            upload=data["file"],
            mime_type=data["mime_type"],
            original_name=data["original_name"],
            description=data.get("description", ""),
            refurbishment=work_order,
            request=self.request,
        )


class TechnicianListView(generics.ListAPIView):
    """Users who may be assigned refurbishment work (id and name only)."""

    permission_classes = [require_permission(Perm.REFURBISHMENT_MANAGE)]
    serializer_class = TechnicianSerializer
    pagination_class = None

    def get_queryset(self):
        return services.technicians()
