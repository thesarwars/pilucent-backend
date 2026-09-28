from rest_framework import response, status
from rest_framework.generics import ListCreateAPIView, RetrieveDestroyAPIView

from adminio.django_rest.serializers.subscriptions import AdminSubscriptionSerializer
from adminio.mixins import IsSuperAdmin

from subscriptionio.models import Subscription


class AdminSubscriptionPlanList(ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionSerializer
    queryset = Subscription.objects.all()
    lookup_field = "uid"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(
            {"message": "success", "error": False}, status.HTTP_201_CREATED
        )


class AdminSubscriptionPlanUpdate(RetrieveDestroyAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionSerializer
    queryset = Subscription.objects.all()
    lookup_field = "uid"

    def delete(self, request, *args, **kwargs):
        qs = self.get_object()
        qs.delete()
        return response.Response(True, status.HTTP_200_OK)
