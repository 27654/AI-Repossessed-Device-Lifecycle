from django.urls import path

from . import views

urlpatterns = [
    path("refurbishments/", views.WorkOrderListCreateView.as_view(), name="work-order-list"),
    path("refurbishments/technicians/", views.TechnicianListView.as_view(), name="work-order-technicians"),
    path("refurbishments/<int:pk>/", views.WorkOrderDetailView.as_view(), name="work-order-detail"),
    path("refurbishments/<int:pk>/start/", views.start, name="work-order-start"),
    path("refurbishments/<int:pk>/complete/", views.complete, name="work-order-complete"),
    path("refurbishments/<int:pk>/unable-to-repair/", views.unable_to_repair, name="work-order-unable-to-repair"),
    path("refurbishments/<int:pk>/cancel/", views.cancel, name="work-order-cancel"),
    path("refurbishments/<int:pk>/steps/", views.StepListCreateView.as_view(), name="work-order-steps"),
    path("refurbishments/<int:pk>/items/", views.ItemListCreateView.as_view(), name="work-order-items"),
    path(
        "refurbishments/<int:pk>/attachments/",
        views.WorkOrderAttachmentListCreateView.as_view(),
        name="work-order-attachments",
    ),
    path("refurbishment-steps/<int:pk>/", views.update_step, name="work-order-step-detail"),
    path("refurbishment-items/<int:pk>/", views.update_item, name="work-order-item-detail"),
]
