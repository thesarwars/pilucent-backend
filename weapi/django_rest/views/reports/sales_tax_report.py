from django.db.models import Sum, Q

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.response import Response
from rest_framework.generics import ListAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

# from ...serializers.reports.profit_loss_reports import ...


class PrivateWeSalesTaxList(ListAPIView):
    serializer_class = ...
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    filterset_fields = [
        "title",
        "status",
        "kind",
        "account_type__title",
        "detail_type__title",
    ]
    search_fields = filterset_fields + ["uid"]
