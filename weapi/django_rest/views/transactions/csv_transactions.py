from rest_framework import generics, response, status, views
from transactionio.models import TransactionInformation
from ...serializers.transactions.csv_transactions import (
    UpsertCSVTransactionsSerializer,
    TransactionWrapperSerializer,
    TransactionSummarySerializer,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from common.django_rest.helpers.date_range_filters import (
    DateFromToRangeFilter,
    WeekMonthYearRangeFilter,
)

# from django.db.models import Sum, Q, Count


class UpsertCSVTransactionsView(generics.CreateAPIView):
    """
    View to handle the upload of CSV transactions and process them.
    """
    queryset = TransactionInformation.objects.all()
    serializer_class = UpsertCSVTransactionsSerializer
    permission_classes = [IsGroupPermission]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(
            {
                "company": self.request.user.get_active_company(),
            }
        )
        return context


class TransactionListView(generics.ListAPIView):
    """
    # def post(self, request, *args, **kwargs):
    #"""

    serializer_class = TransactionWrapperSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
        WeekMonthYearRangeFilter,
    ]
    search_fields = ["description", "check_number", "received", "spent"]
    filterset_fields = [
        "transaction_status",
        "chart_of_account__uid",
        "category",
        "payee",
        "is_spam",
        "received",
        "spent",
    ]

    def get_queryset(self):
        return TransactionInformation.objects.filter(
            company=self.request.user.get_active_company()
        ).order_by("-date")

    # (self, request, *args, **kwargs):

    #     serializer = self.get_serializer(queryset, many=True)
    #     return response.Response(serializer.data, status=status.HTTP_200_OK)


class TransactionSummaryView(generics.ListAPIView):
    """
    View to handle the summary of transactions.
    """

    serializer_class = TransactionSummarySerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["chart_of_account__uid"]

    def get_queryset(self):
        return TransactionInformation.objects.filter(
            company=self.request.user.get_active_company()
        ).order_by("chart_of_account__title")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().distinct("chart_of_account__title")
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data, status=status.HTTP_200_OK)


class TransactionDataUpdateView(views.APIView):
    """
    View to handle the update of transaction data.
    """
    queryset = TransactionInformation.objects.all()
    serializer_class = UpsertCSVTransactionsSerializer
    permission_classes = [IsGroupPermission]
    # lookup_field = "uid"

    # def get_queryset(self):
    #     queryset = self.queryset.get_status_review().filter(
    #         company=self.request.user.get_active_company()
    #     )
    #     return queryset
    def patch(self, request, *args, **kwargs):
        """
        Handle the update of transaction data.
        """
        serializer = self.serializer_class(
            data=request.data,
            context={"company": self.request.user.get_active_company()},
            partial=True,
        )
        # print('serializer', serializer)
        serializer.is_valid(raise_exception=True)

        updated_objects = serializer.update(None, serializer.validated_data)
        return response.Response(
            {"message": f"{len(updated_objects)} transactions updated."},
            status=status.HTTP_200_OK,
        )
