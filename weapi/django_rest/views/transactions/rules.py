from rest_framework import generics, response, status
from transactionio.models import (
    TransactionRules,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from ...serializers.transactions.rules import (
    TransactionRuleCreateSerializer,
    TransactionRuleListSerializer,
)


class TransactionRuleCreateView(generics.ListCreateAPIView):
    serializer_class = TransactionRuleListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return TransactionRules.objects.filter(
            company=self.request.user.get_active_company()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TransactionRuleCreateSerializer
        return TransactionRuleListSerializer

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(
                data=request.data, context={"request": self.request}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return response.Response(
                {"message": "success", "error": False}, status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return response.Response(
                {"message": str(e), "error": True}, status=status.HTTP_400_BAD_REQUEST
            )


class TransactionRuleListView(generics.ListAPIView):
    serializer_class = TransactionRuleListSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return TransactionRules.objects.filter(
            company=self.request.user.get_active_company()
        )

    # def get(self, request, *args, **kwargs):
    #     try:
    #         queryset = self.get_queryset()
    #         serializer = self.get_serializer(queryset, many=True)
    #         return response.Response(
    #             {"message": "success", "error": False, "data": serializer.data}, status=status.HTTP_200_OK
    #         )
    #     except Exception as e:
    #         return response.Response(
    #             {"message": str(e), "error": True}, status=status.HTTP_400_BAD_REQUEST
    #         )
