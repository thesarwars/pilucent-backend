"""Economic Nexus read + on-demand recompute endpoints (Phase 1).

Reads the pre-computed ``NexusStateStatus`` rows (populated by the nightly
recompute or the on-demand recalculate action) and merges each with its in-force
rule for the dashboard/detail payload. Monitoring only — no accounting here.
"""

from datetime import date

from django.utils import timezone

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView, get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination
from common.django_rest.permissions.company_subscription import HaveSubscription

from nexusio.choices import NexusCombinationLogicChoices
from nexusio.models import NexusAgencyRegistration, NexusAlertLog, NexusStateStatus
from nexusio.services import registration as registration_service
from nexusio.services.recompute import recompute_company
from nexusio.services.rules import rule_in_force, rules_in_force

from weapi.django_rest.serializers.nexus import (
    PrivateWeNexusAlertSerializer,
    PrivateWeNexusRegistrationInputSerializer,
    PrivateWeNexusSettingsSerializer,
)

NEXUS_FEATURE = "is_agency_tax"


def _require_taxable_state(code):
    """The in-force rule for a taxable state; 404/400 for unknown / no-sales-tax."""
    rule = rule_in_force(code, date.today())
    if rule is None:
        raise NotFound(f"Unknown state {code}.")
    if not rule.has_sales_tax or rule.combination_logic == NexusCombinationLogicChoices.NONE:
        raise ValidationError(
            {"state_code": f"{code} has no statewide sales tax; nexus does not apply."}
        )
    return rule


def _registration_fields(reg):
    if reg is None:
        return {
            "registration_type": None,
            "registration_status": "NOT_STARTED",
            "sales_tax_permit_number": None,
            "filing_frequency": None,
            "collection_start_date": None,
            "tax_agency_uid": None,
        }
    return {
        "registration_type": reg.registration_type,
        "registration_status": reg.registration_status,
        "sales_tax_permit_number": reg.sales_tax_permit_number,
        "filing_frequency": reg.filing_frequency,
        "collection_start_date": reg.collection_start_date,
        "tax_agency_uid": str(reg.tax_agency.uid) if reg.tax_agency_id else None,
    }


def _rule_fields(rule):
    if rule is None:
        return {
            "state_name": None,
            "has_sales_tax": None,
            "sales_threshold": None,
            "txn_threshold": None,
            "combination_logic": None,
            "includable_sales_basis": None,
            "measurement_period_type": None,
        }
    return {
        "state_name": rule.state_name,
        "has_sales_tax": rule.has_sales_tax,
        "sales_threshold": float(rule.sales_threshold) if rule.sales_threshold is not None else None,
        "txn_threshold": rule.txn_threshold,
        "combination_logic": rule.combination_logic,
        "includable_sales_basis": rule.includable_sales_basis,
        "measurement_period_type": rule.measurement_period_type,
    }


def _status_fields(status):
    return {
        "state_code": status.state_code,
        "window_start": status.window_start,
        "window_end": status.window_end,
        "sales_amount": float(status.sales_amount or 0),
        "taxable_sales_amount": float(status.taxable_sales_amount or 0),
        "txn_count": status.txn_count,
        "pct_of_sales_threshold": (
            float(status.pct_of_sales_threshold)
            if status.pct_of_sales_threshold is not None
            else None
        ),
        "pct_of_txn_threshold": (
            float(status.pct_of_txn_threshold)
            if status.pct_of_txn_threshold is not None
            else None
        ),
        "threshold_met": status.threshold_met,
        "status": status.status,
        "threshold_met_date": status.threshold_met_date,
        "last_evaluated_at": status.last_evaluated_at,
    }


# Status sort priority: settled/at-risk first, then the rest, then not-applicable.
_STATUS_ORDER = {
    "REGISTERED": 0,
    "MET": 1,
    "APPROACHING": 2,
    "NOT_APPROACHING": 3,
    "NOT_APPLICABLE": 4,
}


class PrivateWeNexusDashboardView(APIView):
    """GET /nexus/dashboard — one row per tracked state with verdict + rule."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()  # lets IsGroupPermission resolve perms

    def get(self, request):
        company = request.user.get_active_company()
        rules = rules_in_force(date.today())
        statuses = NexusStateStatus.objects.filter(company=company)
        registrations = {
            reg.state_code: reg
            for reg in NexusAgencyRegistration.objects.filter(
                company=company
            ).select_related("tax_agency")
        }

        rows = []
        for status in statuses:
            rule = rules.get(status.state_code)
            rows.append(
                {
                    **_rule_fields(rule),
                    **_status_fields(status),
                    **_registration_fields(registrations.get(status.state_code)),
                }
            )

        rows.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9), r["state_code"]))
        return Response({"rows": rows, "count": len(rows)})


class PrivateWeNexusStateDetailView(APIView):
    """GET /nexus/state/{state_code} — one state's rule + measured activity."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()

    def get(self, request, state_code):
        company = request.user.get_active_company()
        code = (state_code or "").upper()
        status = NexusStateStatus.objects.filter(
            company=company, state_code=code
        ).first()
        if status is None:
            raise NotFound(
                f"No nexus status for {code}. Run a recalculation to populate it."
            )
        rule = rule_in_force(code, date.today())
        reg = NexusAgencyRegistration.objects.filter(
            company=company, state_code=code
        ).select_related("tax_agency").first()
        return Response(
            {**_rule_fields(rule), **_status_fields(status), **_registration_fields(reg)}
        )


class PrivateWeNexusRecalculateView(APIView):
    """POST /nexus/recalculate — recompute the active company's nexus now."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()

    def post(self, request):
        company = request.user.get_active_company()
        result = recompute_company(company)
        return Response(
            {
                "detail": "Nexus recalculated.",
                "evaluated_states": result["evaluated_states"],
                "unattributed_sales": float(result["unattributed"]["gross"] or 0),
            }
        )


class PrivateWeNexusMarkNexusView(APIView):
    """POST /nexus/state/{code}/mark-nexus — mark physical (manual) nexus.

    DELETE removes the mark/registration (de-register).
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()

    def post(self, request, state_code):
        company = request.user.get_active_company()
        code = (state_code or "").upper()
        _require_taxable_state(code)
        payload = PrivateWeNexusRegistrationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        vd = payload.validated_data
        reg = registration_service.mark_physical_nexus(
            company,
            code,
            collection_start_date=vd.get("collection_start_date"),
            filing_frequency=vd.get("filing_frequency"),
            permit=vd.get("sales_tax_permit_number"),
        )
        # Recompute so the status row reflects the mark consistently (single
        # source of truth — avoids a hand-flipped field diverging from recompute).
        recompute_company(company)
        return Response(
            {"detail": f"{code} marked as having nexus.", **_registration_fields(reg)}
        )

    def delete(self, request, state_code):
        company = request.user.get_active_company()
        code = (state_code or "").upper()
        registration_service.remove_registration(company, code)
        recompute_company(company)  # restore the true numeric status immediately
        return Response(status=204)


class PrivateWeNexusStartAgencySetupView(APIView):
    """POST /nexus/state/{code}/start-agency-setup — record the handoff to Sales Tax.

    Stores the economic-nexus registration intent (and links an existing agency
    for the state if one is found), then returns a ``resume_url`` for the Sales
    Tax agency screen where the agency + tax rates are actually created.
    """

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()

    def post(self, request, state_code):
        company = request.user.get_active_company()
        code = (state_code or "").upper()
        rule = _require_taxable_state(code)
        payload = PrivateWeNexusRegistrationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        vd = payload.validated_data

        agency = registration_service.find_existing_agency(
            company, code, rule.state_name
        )
        reg = registration_service.start_agency_setup(
            company,
            code,
            collection_start_date=vd.get("collection_start_date"),
            filing_frequency=vd.get("filing_frequency"),
            permit=vd.get("sales_tax_permit_number"),
            tax_agency=agency,
            mark_registered=vd.get("mark_registered", False),
        )
        recompute_company(company)  # keep the status row consistent
        return Response(
            {
                "detail": "Agency setup started.",
                "resume_url": f"/sales-tax/agencies?state={code}",
                **_registration_fields(reg),
            }
        )


class PrivateWeNexusAlertListView(ListAPIView):
    """GET /nexus/alerts — approaching/crossed alerts for the company.

    ``?acknowledged=false`` filters to the open worklist.
    """

    serializer_class = PrivateWeNexusAlertSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        qs = NexusAlertLog.objects.filter(
            company=self.request.user.get_active_company()
        )
        ack = self.request.query_params.get("acknowledged")
        if ack == "false":
            qs = qs.filter(acknowledged_at__isnull=True)
        elif ack == "true":
            qs = qs.filter(acknowledged_at__isnull=False)
        return qs


class PrivateWeNexusAlertAcknowledgeView(APIView):
    """POST /nexus/alerts/{uid}/acknowledge — record acknowledgement."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusAlertLog.objects.all()

    def post(self, request, uid):
        alert = get_object_or_404(
            NexusAlertLog,
            uid=uid,
            company=request.user.get_active_company(),
        )
        if alert.acknowledged_at is None:
            alert.acknowledged_by = request.user
            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=["acknowledged_by", "acknowledged_at", "updated_at"])
        return Response(PrivateWeNexusAlertSerializer(alert).data)


class PrivateWeNexusSettingsView(APIView):
    """GET / PATCH /nexus/settings — per-company nexus configuration."""

    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = NEXUS_FEATURE
    queryset = NexusStateStatus.objects.all()

    def get(self, request):
        settings = registration_service.get_or_create_settings(
            request.user.get_active_company()
        )
        return Response(PrivateWeNexusSettingsSerializer(settings).data)

    def patch(self, request):
        settings = registration_service.get_or_create_settings(
            request.user.get_active_company()
        )
        serializer = PrivateWeNexusSettingsSerializer(
            settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
