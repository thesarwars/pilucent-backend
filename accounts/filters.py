from django_filters import BaseInFilter, CharFilter, FilterSet
from accounts.models import ChartOfAccount


class CharInFilter(BaseInFilter, CharFilter):
    pass


class ChartOfAccountFilter(FilterSet):
    account_type__title = CharInFilter(field_name="account_type__title", lookup_expr="in")
    
    class Meta:
        model = ChartOfAccount
        fields = [
            "status",
            "title",
            "account_type__title",
            "account_type__slug",
            "account_type__uid",
            "detail_type__uid",
            "detail_type__slug",
            "kind",
        ]