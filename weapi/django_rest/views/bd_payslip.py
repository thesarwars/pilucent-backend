"""Payslip and compliance API (docs/backend/payslip-compliance-done.md §6),
under /api/v1/we: payslips, their findings and the wages register.

Permissions (§7), app `payslipio`: view_all_payslips, generate_payslips,
resolve_payslip_finding, read_wages_register. Issuing is `release_payslips`
(app `payrunio`), the run's own release. An employee reads their own issued
slips with no permission at all.

Tenancy: every record is resolved with `company=`.
"""

from django.http import HttpResponse
from rest_framework import status
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from employeeio.services.salary_access import has_company_permission
from payrunio.models import PayrollRun
from payrunio.services.ops import RunRefused
from payslipio.choices import LOCKED, AuditActionChoices
from payslipio.models import PayslipAudit, PayslipDocument
from payslipio.services import ops as P
from payslipio.services import pdf
from payslipio.services.present import document_out, register_out, roster

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP, RUN_APP = "payslipio", "payrunio"
READ_ALL, GENERATE, RESOLVE, REGISTER, RELEASE = ("view_all_payslips", "generate_payslips", "resolve_payslip_finding",
                                                  "read_wages_register", "release_payslips")
NEEDS = {
    READ_ALL: "Reading another employee's payslip needs the 'view all payslips' permission.",
    GENERATE: "Generating payslips needs the 'generate payslips' permission.",
    RESOLVE: "Resolving a finding needs the 'resolve payslip finding' permission.",
    REGISTER: "The wages register needs the 'read wages register' permission.",
    RELEASE: "Issuing payslips needs the 'release payslips' permission.",
}


class SlipView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, RunRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["detail"] = exc.detail
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename,
                                      RUN_APP if codename == RELEASE else APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise RunRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def can(self):
        return {"readAll": self.may(READ_ALL), "generate": self.may(GENERATE), "resolve": self.may(RESOLVE),
                "register": self.may(REGISTER), "release": self.may(RELEASE)}

    def run(self, uid):
        return get_object_or_404(PayrollRun.objects.select_related("company", "site", "rule_set", "tax_card"),
                                 uid=uid, company=self.company())

    def document(self, uid, *, reading=True):
        doc = get_object_or_404(
            PayslipDocument.objects.select_related("company", "run", "employee", "rule_set", "tax_card", "superseded_by"),
            uid=uid, company=self.company())
        if reading and not self.may(READ_ALL):
            # §6.5. Their own, once it is a document; anyone else's is not there.
            if doc.employee.user_id != self.request.user.pk or doc.state not in LOCKED:
                raise RunRefused({"permission": [NEEDS[READ_ALL]]}, status=status.HTTP_403_FORBIDDEN)
        return doc


class PsRoster(SlipView):
    def get(self, request):
        data = roster(self.company(), run_uid=request.query_params.get("run"), user=request.user,
                      read_all=self.may(READ_ALL))
        return Response({**data, "can": self.can()})


class PsGenerate(SlipView):
    def post(self, request, uid):
        self.refuse_unless(GENERATE)
        return Response(P.generate(self.run(uid), user=request.user))


class PsRelease(SlipView):
    def post(self, request, uid):
        self.refuse_unless(RELEASE)
        run = P.release(self.run(uid), user=request.user)
        return Response({"state": run.state, "released": PayslipDocument.objects.filter(run=run,
                                                                                         state__in=LOCKED).count()})


class FormatIsOurs(DefaultContentNegotiation):
    """`?format=pdf` picks the document's form here, not a DRF renderer."""

    def filter_renderers(self, renderers, format):
        return renderers


class PsDocument(SlipView):
    content_negotiation_class = FormatIsOurs

    def get(self, request, uid):
        doc = self.document(uid)
        P.audit(doc.company, AuditActionChoices.VIEWED, request.user, doc=doc)
        if request.query_params.get("format") == "pdf":
            lang = request.query_params.get("lang") or doc.language
            if lang not in pdf.T:
                raise RunRefused({"lang": ["lang is en or bn."]}, status=400)
            body = HttpResponse(pdf.render(doc, lang), content_type="application/pdf")
            body["Content-Disposition"] = f'attachment; filename="{doc.document_no}.pdf"'
            return body
        return Response({**document_out(doc), "can": self.can()})


class PsPrinted(SlipView):
    """§3.7: who printed a slip is a fact an access review asks for."""

    def post(self, request, uid):
        doc = self.document(uid)
        P.audit(doc.company, AuditActionChoices.PRINTED, request.user, doc=doc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PsResolve(SlipView):
    def post(self, request, uid, finding):
        self.refuse_unless(RESOLVE)
        doc = P.resolve(self.document(uid, reading=False), finding, resolution=request.data.get("resolution"),
                        reason=request.data.get("reason"), user=request.user)
        return Response({**document_out(PayslipDocument.objects.get(pk=doc.pk)), "can": self.can()})


class PsSupersede(SlipView):
    def post(self, request, uid):
        self.refuse_unless(RELEASE)
        new_run = request.data.get("newRunId")
        if not new_run:
            raise RunRefused({"newRunId": ["Name the adjustment run the correction comes from."]}, status=400)
        new = P.supersede(self.document(uid, reading=False), new_run=self.run(new_run),
                          reason=request.data.get("reason"), user=request.user)
        return Response({**document_out(new), "can": self.can()}, status=status.HTTP_201_CREATED)


class PsDeliver(SlipView):
    def post(self, request, uid):
        self.refuse_unless(RELEASE)
        doc = P.deliver(self.document(uid, reading=False), channel=request.data.get("channel"),
                        destination=request.data.get("destination"), user=request.user)
        return Response({**document_out(PayslipDocument.objects.get(pk=doc.pk)), "can": self.can()},
                        status=status.HTTP_201_CREATED)


class WrRegister(SlipView):
    def get(self, request, uid):
        self.refuse_unless(REGISTER)
        run = self.run(uid)
        data = register_out(run)
        if data["issued"] and not PayslipAudit.objects.filter(run_uid=run.uid, payslip_uid__isnull=True,
                                                              action=AuditActionChoices.REGISTER_GENERATED).exists():
            P.audit(run.company, AuditActionChoices.REGISTER_GENERATED, request.user, run=run)
        return Response({**data, "can": self.can()})
