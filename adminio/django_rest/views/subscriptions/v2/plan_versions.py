from rest_framework import response, status, views
from rest_framework.generics import ListAPIView, get_object_or_404

from adminio.django_rest.serializers.entitlements import (
    AdminPlanVersionSerializer,
    AdminSubscriptionModuleSerializer,
)
from adminio.mixins import IsSuperAdmin
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination

from subscriptionio.models import PlanVersion, Subscription, SubscriptionModule
from subscriptionio.services.admin_plan_catalog_service import AdminPlanCatalogService
from subscriptionio.services.plan_version_service import PlanVersionService


class AdminSubscriptionFeatureCatalogList(ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionModuleSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        return SubscriptionModule.objects.filter(is_active=True).prefetch_related(
            "features"
        )


class AdminSubscriptionPlanVersionList(ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminPlanVersionSerializer
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        subscription = get_object_or_404(
            Subscription.objects.all(),
            uid=self.kwargs["uid"],
        )
        return PlanVersion.objects.filter(subscription=subscription).prefetch_related(
            "limits", "plan_features__feature"
        )


class AdminSubscriptionPlanVersionPublish(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid, version_uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        plan_version = get_object_or_404(
            PlanVersion.objects.filter(subscription=subscription),
            uid=version_uid,
        )
        published = PlanVersionService.publish(plan_version)
        return response.Response(
            AdminPlanVersionSerializer(published).data,
            status=status.HTTP_200_OK,
        )


class AdminSubscriptionPlanVersionClone(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid, version_uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        source_version = get_object_or_404(
            PlanVersion.objects.filter(subscription=subscription),
            uid=version_uid,
        )
        cloned = PlanVersionService.clone(source_version)
        return response.Response(
            AdminPlanVersionSerializer(cloned).data,
            status=status.HTTP_201_CREATED,
        )


class AdminSubscriptionPlanVersionCreateDraft(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        draft = PlanVersionService.create_draft_version(subscription)
        return response.Response(
            AdminPlanVersionSerializer(draft).data,
            status=status.HTTP_201_CREATED,
        )


class AdminSubscriptionPlanVersionUpdateDraft(views.APIView):
    permission_classes = [IsSuperAdmin]

    def patch(self, request, uid, version_uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        plan_version = get_object_or_404(
            PlanVersion.objects.filter(subscription=subscription),
            uid=version_uid,
        )
        try:
            updated = PlanVersionService.update_draft_version(
                plan_version,
                plan_features=request.data.get("plan_features"),
                limits=request.data.get("limits"),
                notes=request.data.get("notes"),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        updated = PlanVersion.objects.prefetch_related(
            "limits", "plan_features__feature"
        ).get(pk=updated.pk)
        return response.Response(AdminPlanVersionSerializer(updated).data)


class AdminSubscriptionPlanVersionAddOns(views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, uid, version_uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        plan_version = get_object_or_404(
            PlanVersion.objects.filter(subscription=subscription),
            uid=version_uid,
        )
        return response.Response(
            {"addons": AdminPlanCatalogService.get_plan_version_addons(plan_version)}
        )

    def put(self, request, uid, version_uid):
        subscription = get_object_or_404(Subscription.objects.all(), uid=uid)
        plan_version = get_object_or_404(
            PlanVersion.objects.filter(subscription=subscription),
            uid=version_uid,
        )
        try:
            addons = AdminPlanCatalogService.sync_plan_version_addons(
                plan_version,
                request.data.get("addons", []),
            )
        except ValueError as exc:
            return response.Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return response.Response({"addons": addons})
