from django.db import transaction

from rest_framework import generics, response, filters, serializers, status, views

from ...serializers.payroll.salary_process import (
    PayrollSalaryProcessSerializer,
    PayrollSalaryProcessDetailsSerializer,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.admin import IsCompanyAdmin

from weapi.django_rest.helpers.salary_process_journal_entry import (
    unwind_existing_payroll_posting,
)

from payrollio.django_rest.helpers.void_payroll import reverse_payroll_entries
from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.models import PayrollSalaryProcess

from weapi.django_rest.helpers.payroll.payment_tab_counts import (
    payment_tab_transfer_counts,
)
from weapi.django_rest.helpers.payroll.salary_payout import (
    PayoutError,
    pay_salary_run,
)

from django_filters.rest_framework import DjangoFilterBackend

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


class PayrollPaymentTabCountsView(views.APIView):
    """Badge counts for the payment screen tabs.

    Each tab is counted from the source that tab actually renders: **On process**
    is unpaid salary runs (``is_salary_done=False``, a purely local concept),
    while **Pending** and **Cancel** are counted from Moov — because those tabs
    list live Moov transfers, not the local mirror. History has no count. Always
    returns a number (0 when empty); the frontend decides whether to show it.
    """

    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    queryset = PayrollSalaryProcess.objects.all()  # lets IsGroupPermission resolve

    def get(self, request):
        company = request.user.get_active_company()

        on_process = PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=company,
            is_salary_done=False,
        ).count()

        pending, canceled = payment_tab_transfer_counts(company)

        return response.Response(
            {
                "error": False,
                "data": {
                    "on_process": on_process,
                    "pending": pending,
                    "canceled": canceled,
                },
            },
            status=status.HTTP_200_OK,
        )


class PayrollSalaryProcessListCreateView(generics.ListCreateAPIView):
    serializer_class = PayrollSalaryProcessSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = [
        "title",
        "schedule_name",
        "pay_period",
        "pay_date",
        "employee__user__name",
    ]
    filterset_fields = ["schedule_name", "pay_period", "pay_date", "is_salary_done"]

    def get_queryset(self):
        return PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=self.request.user.get_active_company()
        )

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={"company": self.request.user.get_active_company()},
        )
        # serializer = self.serializer_class(data=request.data, context={"company": self.request.user.get_active_company()})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response({"success": True, "message": "created"}, status=201)


class PayrollSalaryProcessDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = PayrollSalaryProcessDetailsSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    lookup_field = "uid"

    def get_queryset(self):
        return PayrollSalaryProcess.objects.filter(
            employee__user__companyuser__company=self.request.user.get_active_company()
        )

    def perform_destroy(self, instance):
        """Never leave a run's journal entries behind unattached.

        `JournalEntry.payroll_salary` is `SET_NULL` (journalio/models.py:86), so
        deleting a run does not take its entries with it: they stay, still
        balanced into the accounts, with nothing left to say what created them.
        Production carries two such orphans -- journals 2697 and 2698,
        byte-identical to each other, `payroll_salary` NULL on both, each moving
        140,966.12 of wages and taxes that no payroll run claims.

        Finalized runs are refused outright and sent to
        `PayrollSalaryProcessVoidView`, which reverses through
        `reverse_payroll_entries`: a finalized run counts toward year-to-date
        totals and wage caps, so its reversal has to be recorded rather than
        erased.

        Anything else unwinds its entries here and then deletes. Note a DRAFT
        run HAS posted -- `post_payroll_entries` writes an entry on create and
        DRAFT is the model default -- so "it never posted, let it go" is not a
        case that exists.
        """
        if instance.status == PayrollSalaryProcessStatusChoices.FINALIZED:
            raise serializers.ValidationError(
                {
                    "message": (
                        "This payroll run is finalized and counts toward "
                        "year-to-date totals. Void it instead of deleting it, "
                        "so its journal entries are reversed rather than left "
                        "behind unattached."
                    )
                }
            )

        # A DRAFT run has posted too -- `post_payroll_entries` writes a journal
        # entry on create, and DRAFT is the model's default -- so deleting it
        # still has to unwind what it wrote. Refusing outright, which is what
        # this guard did when first written, left a draft neither deletable
        # (here) nor voidable (`void_payroll` raises unless FINALIZED). That
        # dead-end is why this branch exists rather than a blanket refusal.
        #
        # The undo direction comes from each connector's stored `kind` rather
        # than being assumed, so a row written before the side fixes unwinds
        # the way it actually posted.
        with transaction.atomic():
            unwind_existing_payroll_posting(instance)
            instance.delete()


class VoidPayrollSerializer(serializers.Serializer):
    """Optional human-readable reason logged with the void event."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PayrollSalaryProcessPayView(views.APIView):
    """Pay a payroll run's net pay to the employee via Moov — one atomic action.

    Fixes the split-brain the two-call frontend flow produced (money moved, then
    the payroll call 400'd). Everything is validated BEFORE money moves; the Moov
    transfer uses a stable idempotency key so retries can't double-pay; and on
    success the run is marked paid, the transfer is linked to it, and a receipt
    PDF is generated server-side. Admin-only — it moves money.
    """

    permission_classes = [IsCompanyAdmin]

    def post(self, request, uid):
        active_company = request.user.get_active_company()
        if active_company is None:
            return response.Response(
                {"error": "No active company for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            run = PayrollSalaryProcess.objects.get(
                uid=uid,
                employee__user__companyuser__company=active_company,
            )
        except PayrollSalaryProcess.DoesNotExist:
            return response.Response(
                {"error": "Payroll run not found in your company."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = pay_salary_run(self, run, request.user)
        except PayoutError as exc:
            return response.Response(
                {"error": True, "message": exc.message},
                status=exc.status_code,
            )

        return response.Response({"error": False, **result}, status=status.HTTP_200_OK)


class PayrollSalaryProcessVoidView(views.APIView):
    """Reverse a finalized payroll run.

    Wraps `reverse_payroll_entries` in an atomic transaction so partial
    failures roll back. Restricted to `IsCompanyAdmin` because voiding
    rewrites GL balances and YTD totals.
    """

    permission_classes = [IsCompanyAdmin]

    def post(self, request, uid):
        active_company = request.user.get_active_company()
        if active_company is None:
            return response.Response(
                {"error": "No active company for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payroll_instance = PayrollSalaryProcess.objects.get(
                uid=uid,
                employee__user__companyuser__company=active_company,
            )
        except PayrollSalaryProcess.DoesNotExist:
            return response.Response(
                {"error": "Payroll run not found in your company."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = VoidPayrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                result = reverse_payroll_entries(
                    payroll_instance,
                    actor=request.user,
                    reason=serializer.validated_data.get("reason") or None,
                )
        except ValueError as exc:
            return response.Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return response.Response(
            {
                "success": True,
                "message": (
                    "Payroll run voided. YTD and account balances have been "
                    "reversed; original journal items remain in the GL with "
                    "offsetting reversal items for audit."
                ),
                **result,
            },
            status=status.HTTP_200_OK,
        )
