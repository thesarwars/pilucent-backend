from rest_framework import response, status, views
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateAPIView, get_object_or_404

from adminio.django_rest.serializers.enterprise import (
    AdminManualInvoiceCreateSerializer,
    AdminPlanMigrationJobSerializer,
    AdminPlanMigrationRecordSerializer,
    AdminSubscriptionContractSerializer,
    AdminSubscriptionPriceCurrencySerializer,
)
from adminio.mixins import IsSuperAdmin
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination

from companyio.models import Company
from subscriptionio.models import PlanMigrationJob, PlanMigrationRecord, SubscriptionContract, SubscriptionPrice
from subscriptionio.services.manual_invoice_service import ManualInvoiceService
from subscriptionio.services.plan_migration_service import PlanMigrationService


class AdminSubscriptionPriceCurrencyListCreate(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionPriceCurrencySerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        qs = SubscriptionPrice.objects.select_related("subscription").order_by(
            "subscription__title", "billing_frequency", "currency"
        )
        currency = self.request.query_params.get("currency")
        plan_uid = self.request.query_params.get("plan_uid")
        if currency:
            qs = qs.filter(currency=currency)
        if plan_uid:
            qs = qs.filter(subscription__uid=plan_uid)
        return qs


class AdminSubscriptionPriceCurrencyDetail(RetrieveUpdateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionPriceCurrencySerializer
    lookup_field = "uid"

    def get_queryset(self):
        return SubscriptionPrice.objects.select_related("subscription")


class AdminSubscriptionContractListCreate(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionContractSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        return SubscriptionContract.objects.select_related(
            "company", "subscription_price", "plan_version"
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.get_employee())


class AdminSubscriptionContractDetail(RetrieveUpdateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionContractSerializer
    lookup_field = "uid"

    def get_queryset(self):
        return SubscriptionContract.objects.select_related(
            "company", "subscription_price", "plan_version"
        )


class AdminPlanMigrationJobListCreate(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminPlanMigrationJobSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        return PlanMigrationJob.objects.select_related(
            "source_subscription",
            "target_subscription",
            "source_plan_version",
            "target_plan_version",
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.get_employee())


class AdminPlanMigrationJobDetail(RetrieveUpdateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminPlanMigrationJobSerializer
    lookup_field = "uid"

    def get_queryset(self):
        return PlanMigrationJob.objects.all()


class AdminPlanMigrationJobPreview(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid):
        job = get_object_or_404(PlanMigrationJob, uid=uid)
        return response.Response(PlanMigrationService.preview_job(job))


class AdminPlanMigrationJobExecute(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid):
        job = get_object_or_404(PlanMigrationJob, uid=uid)
        try:
            job = PlanMigrationService.execute_job(job)
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response(AdminPlanMigrationJobSerializer(job).data)


class AdminPlanMigrationRecordList(ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminPlanMigrationRecordSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        job = get_object_or_404(PlanMigrationJob, uid=self.kwargs["uid"])
        return PlanMigrationRecord.objects.filter(job=job).select_related("company")


class AdminManualSubscriptionInvoiceCreate(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, *args, **kwargs):
        serializer = AdminManualInvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        company = get_object_or_404(Company, uid=data["company_uid"])
        try:
            invoice = ManualInvoiceService.create_invoice(
                company=company,
                lines=data["lines"],
                currency=data["currency"],
                notes=data.get("notes", ""),
                mark_paid=data.get("mark_paid", False),
                actor=request.user.get_employee(),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return response.Response(
            {
                "uid": str(invoice.uid),
                "status": invoice.status,
                "total": str(invoice.total),
                "currency": invoice.currency,
                "is_manual": invoice.is_manual,
            },
            status=status.HTTP_201_CREATED,
        )
