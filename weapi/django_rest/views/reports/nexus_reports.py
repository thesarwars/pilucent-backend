"""Economic Nexus reports: Exposure, Approaching-Risk, Threshold-History.

Read-only over the computed nexus data; same report conventions (overview /
is_pdf) as the other standard reports.
"""

from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.permissions.company_subscription import HaveSubscription

from nexusio.models import NexusStateStatus

from weapi.django_rest.helpers.reports.nexus_reports import (
    nexus_approaching_risk,
    nexus_exposure,
    nexus_threshold_history,
)

from ...serializers.reports.nexus_reports import (
    PrivateWeNexusExposureRowSerializer,
    PrivateWeNexusThresholdHistoryRowSerializer,
)


class _BaseNexusReportView(ListAPIView):
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_permissions = ["view_reports"]
    required_feature = "is_standard_report"

    builder = None
    pdf_label = None
    pdf_title = None
    pdf_template = None
    pdf_fields = []

    def get_queryset(self):
        return NexusStateStatus.objects.filter(
            company=self.request.user.get_active_company()
        )

    def list(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        report = type(self).builder(company)

        if request.query_params.get("keywords") == "overview":
            return Response({"as_of": report["as_of"], "total": report["total"]})

        if request.query_params.get("is_pdf") == "true":
            pdf = get_pdf(
                self,
                True,
                {
                    "report_as_of": report["as_of"],
                    "data": report["rows"],
                    "overview": report["total"],
                    "fields": self.pdf_fields,
                    "label": self.pdf_label,
                    "template": self.pdf_template,
                    "is_report": True,
                    "title": self.pdf_title,
                },
            )
            return Response({"file_uid": pdf.uid, "url": pdf.file.url})

        return Response(report)


class PrivateWeNexusExposureReportView(_BaseNexusReportView):
    serializer_class = PrivateWeNexusExposureRowSerializer
    builder = staticmethod(nexus_exposure)
    pdf_label = "nexus_exposure"
    pdf_title = "Economic Nexus Exposure"
    pdf_template = "reports/nexus_exposure.html"
    pdf_fields = ["STATE", "WINDOW", "SALES", "% $", "TXNS", "% TXN", "STATUS"]


class PrivateWeNexusApproachingRiskReportView(_BaseNexusReportView):
    serializer_class = PrivateWeNexusExposureRowSerializer
    builder = staticmethod(nexus_approaching_risk)
    pdf_label = "nexus_approaching_risk"
    pdf_title = "Economic Nexus — Approaching Risk"
    pdf_template = "reports/nexus_exposure.html"
    pdf_fields = ["STATE", "WINDOW", "SALES", "% $", "TXNS", "% TXN", "STATUS"]


class PrivateWeNexusThresholdHistoryReportView(_BaseNexusReportView):
    serializer_class = PrivateWeNexusThresholdHistoryRowSerializer
    builder = staticmethod(nexus_threshold_history)
    pdf_label = "nexus_threshold_history"
    pdf_title = "Economic Nexus — Threshold History"
    pdf_template = "reports/nexus_threshold_history.html"
    pdf_fields = ["STATE", "ALERT", "% AT ALERT", "TRIGGERED", "ACKNOWLEDGED"]
