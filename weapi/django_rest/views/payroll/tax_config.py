"""Statutory payroll tax config endpoints (reference data, year x jurisdiction).

Reads assemble FEDERAL + the requested states into one CONFIG-shaped document
(gated to payroll subscribers). Writes/publish are Pilucent-staff only — this
is not tenant data, so there is no company scoping here.
"""

from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from common.django_rest.permissions.company_subscription import HaveSubscription

from payrollio.choicess import PayrollTaxConfigStatusChoices
from payrollio.models import PayrollTaxConfig
from payrollio.django_rest.helpers.tax_config import (
    assemble_tax_config,
    parse_states_param,
    resolve_year,
)

from weapi.django_rest.serializers.payroll.tax_config import (
    PayrollTaxConfigMetaSerializer,
    PayrollTaxConfigWriteSerializer,
)


class PayrollTaxConfigReadView(APIView):
    """GET /payroll/tax-config/current | /{year}  (?states=CA,NY)."""

    permission_classes = [HaveSubscription]
    required_feature = "is_payroll"

    def get(self, request, year=None):
        resolved_year = resolve_year(year)
        states = parse_states_param(request.query_params.get("states"))
        result = assemble_tax_config(resolved_year, states)
        return Response({"success": True, **result})


class PayrollTaxConfigListView(ListAPIView):
    """GET /payroll/tax-config — available (year, jurisdiction) rows + metadata."""

    permission_classes = [HaveSubscription]
    required_feature = "is_payroll"
    serializer_class = PayrollTaxConfigMetaSerializer
    pagination_class = None
    queryset = PayrollTaxConfig.objects.all()


class PayrollTaxConfigAdminWriteView(APIView):
    """PUT /payroll/tax-config/{year}/{jurisdiction} — staff upsert one document."""

    permission_classes = [permissions.IsAdminUser]

    def put(self, request, year, jurisdiction):
        serializer = PayrollTaxConfigWriteSerializer(
            data=request.data, context={"jurisdiction": jurisdiction}
        )
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        normalized = vd["jurisdiction"]

        existing = PayrollTaxConfig.objects.filter(
            year=year, jurisdiction=normalized
        ).first()
        if existing:
            if existing.data != vd["data"]:
                existing.version += 1
            existing.data = vd["data"]
            existing.source_notes = vd.get("source_notes", existing.source_notes)
            existing.effective_from = vd.get("effective_from", existing.effective_from)
            existing.effective_to = vd.get("effective_to", existing.effective_to)
            existing.save()
            obj, created = existing, False
        else:
            obj = PayrollTaxConfig.objects.create(
                year=year,
                jurisdiction=normalized,
                status=PayrollTaxConfigStatusChoices.DRAFT,
                data=vd["data"],
                source_notes=vd.get("source_notes", ""),
                effective_from=vd.get("effective_from"),
                effective_to=vd.get("effective_to"),
            )
            created = True

        return Response(
            {"success": True, **PayrollTaxConfigMetaSerializer(obj).data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PayrollTaxConfigPublishView(APIView):
    """POST /payroll/tax-config/{year}/{jurisdiction}/publish — staff publish."""

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, year, jurisdiction):
        from payrollio.django_rest.helpers.tax_config import normalize_jurisdiction

        normalized = normalize_jurisdiction(jurisdiction)
        obj = PayrollTaxConfig.objects.filter(
            year=year, jurisdiction=normalized
        ).first()
        if not obj:
            raise NotFound(f"No tax config for {year} {jurisdiction}")
        obj.status = PayrollTaxConfigStatusChoices.PUBLISHED
        obj.save(update_fields=["status", "updated_at"])
        return Response({"success": True, **PayrollTaxConfigMetaSerializer(obj).data})
