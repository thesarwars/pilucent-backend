"""Recurring Transaction template endpoints (Phase 1: Bill).

CRUD + two row actions from the spec (section 9.4):

* **Duplicate** — an independent "Copy of …" with empty run history.
* **Use** — generate a real bill from the template now (posts to A/P and links
  back via ``source_template``).

Delete is a soft delete (``status = REMOVED``) so history and audit links
survive; the list view hides removed templates.
"""

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from recurringio.choices import (
    RecurringTemplateStatusChoices,
    RecurringTxnTypeChoices,
)
from recurringio.models import RecurringTemplate
from recurringio.services import runner, scheduling
from recurringio.services.generation import generate_from_template

from ..serializers.recurring_transactions import (
    PrivateWeRecurringTemplateListSerializer,
    PrivateWeRecurringTemplateSerializer,
    PrivateWeRecurringTemplateUseSerializer,
)

RECURRING_FEATURE = "is_expense"


class PrivateWeRecurringTemplateList(ListCreateAPIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = RECURRING_FEATURE
    # Declared so the permission layer has a model to work from. This view
    # overrides both `get_queryset()` and `get_serializer_class()`, and DRF's
    # GenericAPIView defines `serializer_class = None` as a class attribute --
    # so the resolver took the serializer branch, hit `None.Meta`, and raised
    # AttributeError. A 500, not a 403, for every non-admin caller.
    #
    # A `queryset` rather than `required_permissions` because this is genuine
    # CRUD: the model plus METHOD_PERMISSION_MAP gives `view` on GET and `add`
    # on POST, where a single explicit codename would have to govern both. The
    # rows served still come from `get_queryset()` below; this is never queried.
    queryset = RecurringTemplate.objects.none()
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = ["name", "supplier__display_name", "customer__display_name"]
    ordering_fields = ["created_at", "next_run_date", "name", "total_amount"]
    filterset_fields = ["txn_type", "template_type", "status"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PrivateWeRecurringTemplateSerializer
        return PrivateWeRecurringTemplateListSerializer

    def get_queryset(self):
        return (
            RecurringTemplate.objects.filter(
                company=self.request.user.get_active_company()
            )
            .exclude(status=RecurringTemplateStatusChoices.REMOVED)
            .select_related("supplier", "customer", "payment_account")
            .prefetch_related("lines__customer", "lines__supplier")
        )


class PrivateWeRecurringTemplateDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeRecurringTemplateSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = RECURRING_FEATURE

    def get_object(self):
        return get_object_or_404(
            RecurringTemplate.objects.exclude(
                status=RecurringTemplateStatusChoices.REMOVED
            ).prefetch_related("lines"),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        # Soft delete: stop future generation, keep already-generated bills.
        instance.status = RecurringTemplateStatusChoices.REMOVED
        instance.next_run_date = None
        instance.save(update_fields=["status", "next_run_date", "updated_at"])


class PrivateWeRecurringTemplateDuplicate(APIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = RECURRING_FEATURE
    queryset = RecurringTemplate.objects.all()  # lets IsGroupPermission resolve perms

    def post(self, request, uid):
        company = request.user.get_active_company()
        source = get_object_or_404(
            RecurringTemplate.objects.exclude(
                status=RecurringTemplateStatusChoices.REMOVED
            ).prefetch_related("lines"),
            company=company,
            uid=uid,
        )

        lines = list(source.lines.all())
        source.pk = None
        source.id = None
        source.uid = None
        source.name = f"Copy of {source.name}"[:100]
        source.status = RecurringTemplateStatusChoices.ACTIVE
        # Empty run history on the copy.
        source.previous_run_date = None
        source.occurrences_generated = 0
        source._state.adding = True
        source.save()

        for line in lines:
            line.pk = None
            line.id = None
            line.uid = None
            line.template = source
            line._state.adding = True
        for line in lines:
            line.save()

        # Reseed the schedule for the fresh copy.
        from recurringio.services import scheduling

        source.next_run_date = scheduling.compute_first_run_date(source)
        source.save(update_fields=["next_run_date", "updated_at"])

        serializer = PrivateWeRecurringTemplateSerializer(source, context={"request": request})
        return Response(serializer.data, status=201)


class PrivateWeRecurringTemplateUse(APIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = RECURRING_FEATURE
    queryset = RecurringTemplate.objects.all()

    def post(self, request, uid):
        company = request.user.get_active_company()
        template = get_object_or_404(
            RecurringTemplate.objects.exclude(
                status=RecurringTemplateStatusChoices.REMOVED
            ).prefetch_related("lines"),
            company=company,
            uid=uid,
        )

        payload = PrivateWeRecurringTemplateUseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        result = generate_from_template(
            template,
            request.user,
            company,
            transaction_date=payload.validated_data.get("bill_date"),
            send_email=payload.validated_data.get("send_email", False),
        )

        if template.txn_type == RecurringTxnTypeChoices.EXPENSE:
            body = {
                "detail": "Expense created from template.",
                "template_uid": str(template.uid),
                "txn_type": template.txn_type,
                "expense_uid": str(result.uid),
                "date": result.date,
                "total": result.total,
                "total_tax": result.total_tax,
            }
        elif template.txn_type == RecurringTxnTypeChoices.CHEQUE:
            body = {
                "detail": "Cheque created from template.",
                "template_uid": str(template.uid),
                "txn_type": template.txn_type,
                "cheque_uid": str(result.uid),
                "purchase_id": result.purchase_id,
                "cheque_number": result.cheque_number,
                "date": result.date,
                "total": result.total,
                "total_tax": result.total_tax,
                "print_later": template.print_later,
            }
        elif template.txn_type == RecurringTxnTypeChoices.ESTIMATE:
            body = {
                "detail": "Estimate created from template.",
                "template_uid": str(template.uid),
                "txn_type": template.txn_type,
                "estimate_uid": str(result.uid),
                "estimate_id": result.invoice_id,
                "reference_number": result.reference_number,
                "date": result.date,
                "expiry_date": result.expired_date,
                "total": result.total,
                "total_tax": result.total_tax,
            }
        else:
            body = {
                "detail": "Bill created from template.",
                "template_uid": str(template.uid),
                "txn_type": template.txn_type,
                "bill_uid": str(result.uid),
                "purchase_id": result.purchase_id,
                "bill_date": result.bill_date,
                "due_date": result.due_date,
                "total": result.total,
                "total_tax": result.total_tax,
                "due_total": result.due_total,
            }
        return Response(body, status=201)


class PrivateWeRecurringTemplatePauseResume(APIView):
    """Stop a template firing, or start it again.

    Exposed as two endpoints rather than a writable ``status`` so a client can
    only ever move between ACTIVE and PAUSED — never into ENDED (which belongs
    to the generation job) or REMOVED (which is the delete flow).
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    queryset = RecurringTemplate.objects.all()
    required_feature = RECURRING_FEATURE

    #: Set per-URL: the status this endpoint moves the template into.
    target_status = None

    def post(self, request, uid):
        company = request.user.get_active_company()
        template = get_object_or_404(
            RecurringTemplate.objects.filter(company=company), uid=uid
        )

        if self.target_status == RecurringTemplateStatusChoices.PAUSED:
            if template.status != RecurringTemplateStatusChoices.ACTIVE:
                return Response(
                    {"detail": "Only an active template can be paused."}, status=400
                )
            template.status = RecurringTemplateStatusChoices.PAUSED
            # next_run_date is left as it is: pausing does not rewrite the
            # schedule, it just stops the job acting on it.
            template.save(update_fields=["status", "updated_at"])
        else:
            if template.status != RecurringTemplateStatusChoices.PAUSED:
                return Response(
                    {"detail": "Only a paused template can be resumed."}, status=400
                )
            template.status = RecurringTemplateStatusChoices.ACTIVE
            # Roll forward instead of back-filling: the occurrences that fell
            # due during the pause are precisely the ones it was meant to skip.
            template.next_run_date = scheduling.next_on_or_after(
                template, runner.company_today(company)
            )
            if template.next_run_date is None:
                template.status = RecurringTemplateStatusChoices.ENDED
            template.save(update_fields=["status", "next_run_date", "updated_at"])

        return Response(
            {
                "detail": f"Template {template.status.lower()}.",
                "uid": str(template.uid),
                "status": template.status,
                "next_run_date": template.next_run_date,
            }
        )
