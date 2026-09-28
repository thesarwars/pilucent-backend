from rest_framework import generics, response

from payrollio.models import DeductionAndContributions

from ...serializers.payroll.deduction_and_contribution import (
    DeductionAndContributionSlimSerializer,
    DedConDetailsSerializer,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


class DeductionAndContributionView(generics.ListCreateAPIView):
    serializer_class = DeductionAndContributionSlimSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_queryset(self):
        return DeductionAndContributions.objects.filter(
            company=self.request.user.get_active_company()
        )

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={"company": self.request.user.get_active_company()},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response({"success": True, "message": "created"}, status=201)


class DedConUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DedConDetailsSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        return generics.get_object_or_404(
            DeductionAndContributions.objects.all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return response.Response({"success": True, "message": "deleted"}, status=200)



class DeductionAndContributionListView(generics.ListAPIView):
    serializer_class = DeductionAndContributionSlimSerializer
    pagination_class = None

    def get_queryset(self):
        return DeductionAndContributions.objects.filter(
            company=self.request.user.get_active_company()
        )
 