from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import ListAPIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter
from common.django_rest.permissions.company_subscription import HaveSubscription

from journalio.models import JournalEntryConnector
from common.django_rest.helpers.ledger_balances import annotate_running_balance

from ...serializers.reports.general_ledgers import PrivateWeGeneralLadgerListSerializer


class PrivateWeGeneralLadgerList(ListAPIView):
    serializer_class = PrivateWeGeneralLadgerListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, DateFromToRangeFilter]
    filterset_fields = ["kind", "account__uid", "created_at"]
    search_fields = filterset_fields + ["uid", "title"]

    def get_queryset(self):
        """Every journal line for THIS company, in ledger order.

        Two defects here, both load-bearing.

        The company filter was applied only inside the `if start_date and
        end_date` branch, so a request without a date range returned
        `JournalEntryConnector.objects.filter()` -- every tenant's journal
        lines. RLS does not catch it: `journalio_journalentryconnector` is not
        in `RLS_TABLES` (companyio migration 0023) and has no `company_id`
        column, so the tenant policy cannot apply to it at all.

        And the date filter itself was on `journalentryconnector__created_at`,
        the reverse of this model's own `parent` self-FK -- so it matched
        against a line's CHILDREN, inner-joining away every line that has none.
        It is now the line's own transaction date, so a backdated document
        reports in the period it belongs to.
        """
        company = self.request.user.get_active_company()
        queryset = JournalEntryConnector.objects.filter(journal__company=company)

        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        if start_date and end_date:
            queryset = queryset.filter(date__range=[start_date, end_date])

        return annotate_running_balance(queryset.select_related("account"))
