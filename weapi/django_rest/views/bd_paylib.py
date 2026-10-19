"""The pay library API (docs/backend/components-n-structures-backend-done.md §6),
mounted at /api/v1/we/pay-library: components and their base flags, GL
mapping, structure templates, the minimum wage, bulk revision and journal
readiness.

Permissions (§7): edit_pay_components, change_component_flags (the sharpest:
one toggle moves every payslip), edit_structure_templates,
publish_structure_templates, preview_bulk_revision, apply_bulk_revision
(distinct from preview), map_gl_accounts, manage_payroll_policy. Reading the
library needs the employees feature; anything showing an employee's pay
needs the salary figures permission.

Tenancy: every record is resolved with `company=`.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from accounts.models import ChartOfAccount
from common import clock
from employeeio.services.salary_access import has_company_permission
from paylibio.choices import BASES
from paylibio.models import BulkRevision, PayComponent, StructureTemplate
from paylibio.services import library as L
from paylibio.services.library import LibraryRefused
from paylibio.services.seed import ensure_library

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "paylibio"
EDIT, FLAGS, T_EDIT, T_PUBLISH, B_PREVIEW, B_APPLY, GL, POLICY = (
    "edit_pay_components", "change_component_flags", "edit_structure_templates", "publish_structure_templates",
    "preview_bulk_revision", "apply_bulk_revision", "map_gl_accounts", "manage_payroll_policy")
NEEDS = {
    EDIT: "Editing a component needs the 'edit pay components' permission.",
    FLAGS: "Changing a base flag needs the 'change component flags' permission: one toggle moves every payslip.",
    T_EDIT: "Drafting a template needs the 'edit structure templates' permission.",
    T_PUBLISH: "Publishing a template needs the 'publish structure templates' permission.",
    B_PREVIEW: "A bulk revision preview needs the 'preview bulk revision' permission.",
    B_APPLY: "Applying a bulk revision needs the 'apply bulk revision' permission, which is separate from previewing.",
    GL: "Mapping GL accounts needs the 'map GL accounts' permission.",
    POLICY: "The company floor and provident fund rates need the 'manage payroll policy' permission.",
}


def _date(value, field, default=None):
    if value in (None, ""):
        return default
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise LibraryRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


def _amount(value, field="amount", default=None):
    if value in (None, ""):
        return default
    try:
        v = Decimal(str(value))
    except InvalidOperation:
        raise LibraryRefused({field: [f"{field} must be a number."]}, status=400) from None
    if v <= 0 or v > Decimal("100000000"):
        raise LibraryRefused({field: [f"{field} is above zero."]}, status=400)
    return v


class LibraryView(BDEmployeeView):
    def handle_exception(self, exc):
        from employeeio.services.salary import SalaryRefused

        if isinstance(exc, LibraryRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["consequence"] = exc.detail
            return Response(body, status=exc.status)
        if isinstance(exc, SalaryRefused):
            return Response(ui_errors(exc.errors), status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise LibraryRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def figures_or_refuse(self):
        if not self.salary_figures():
            raise LibraryRefused({"permission": ["Showing employees' pay needs the salary figures permission."]},
                                 status=status.HTTP_403_FORBIDDEN)

    def can(self):
        return {"edit": self.may(EDIT), "flags": self.may(FLAGS), "editTemplates": self.may(T_EDIT),
                "publish": self.may(T_PUBLISH), "preview": self.may(B_PREVIEW), "apply": self.may(B_APPLY),
                "gl": self.may(GL), "policy": self.may(POLICY), "figures": self.salary_figures()}

    def component(self, uid=None):
        return get_object_or_404(PayComponent.objects.select_related("gl_account"), uid=uid or self.kwargs["uid"],
                                 company=self.company())

    def template(self, uid=None):
        return get_object_or_404(StructureTemplate.objects.prefetch_related("rows"), uid=uid or self.kwargs["uid"],
                                 company=self.company())


BASES_META = [{"field": f, "key": k, "label": label, "governs": governs, "index": i}
              for i, (f, k, label, governs) in enumerate(BASES)]


class LibSummary(LibraryView):
    """The component library tab: every current component with its flags,
    usage, the effects panel and journal readiness."""

    def get(self, request):
        company = self.company()
        ensure_library(company)
        usage = L.component_usage(company)
        p = request.query_params
        return Response({
            "bases": BASES_META,
            "components": [L.component_out(c, usage.get(c.code, 0)) for c in L.current_components(company)],
            "effects": L.effects(company, _amount(p.get("gross"), "gross", Decimal("50000")),
                                 p.get("template") or "officer"),
            "readiness": L.readiness(company), "can": self.can(),
        })


class LibComponents(LibraryView):
    def post(self, request):
        self.refuse_unless(EDIT)
        c = L.create_component(self.company(), request.data, user=request.user)
        return Response(L.component_out(c), status=status.HTTP_201_CREATED)


class LibComponent(LibraryView):
    def get(self, request, uid):
        company = self.company()
        c = self.component(uid)
        versions = PayComponent.objects.filter(company=company, code=c.code).order_by("-version")
        return Response({**L.component_out(c), "versions": [L.component_out(v) for v in versions],
                         "audit": [a for a in L.library_audit(company, 200) if a["code"] == c.code][:40]})

    def patch(self, request, uid):
        self.refuse_unless(EDIT)
        return Response(L.component_out(L.edit_component(self.company(), self.component(uid), request.data,
                                                         user=request.user)))


class LibComponentFlags(LibraryView):
    """§6.1. A locked flag unset is 422; anything else makes version n+1."""

    def post(self, request, uid):
        self.refuse_unless(FLAGS)
        d = request.data
        c = L.change_flags(self.company(), self.component(uid), d.get("changes") or {},
                           effective_from=_date(d.get("effectiveFrom"), "effectiveFrom", clock.today()),
                           reason=d.get("reason"), user=request.user)
        return Response(L.component_out(c))


class LibComponentGl(LibraryView):
    def post(self, request, uid):
        self.refuse_unless(GL)
        company = self.company()
        account = None
        if request.data.get("accountUid"):
            account = get_object_or_404(ChartOfAccount, uid=request.data["accountUid"], company=company)
        c = L.map_gl(company, self.component(uid), account, user=request.user)
        return Response({**L.component_out(c), "readiness": L.readiness(company)})


class LibGlAccounts(LibraryView):
    """The company's accounts, for the mapping picker."""

    def get(self, request):
        rows = (ChartOfAccount.objects.filter(company=self.company()).exclude(status__in=("REMOVED", "INACTIVE"))
                .order_by("kind", "code", "title"))
        return Response({"accounts": [L.gl_out(a) for a in rows]})

    def post(self, request):
        """Create the payroll accounts that are missing, and map them."""
        self.refuse_unless(GL)
        company = self.company()
        out = L.create_payroll_accounts(company, request.data.get("codes"), user=request.user)
        return Response({**out, "readiness": L.readiness(company)})


class LibReadiness(LibraryView):
    def get(self, request):
        return Response(L.readiness(self.company()))


class LibEffects(LibraryView):
    def get(self, request):
        p = request.query_params
        return Response(L.effects(self.company(), _amount(p.get("gross"), "gross", Decimal("50000")),
                                  p.get("template") or "officer"))


class LibTemplates(LibraryView):
    def get(self, request):
        return Response({"templates": L.templates(self.company()), "can": self.can()})

    def post(self, request):
        self.refuse_unless(T_EDIT)
        t = L.save_template(self.company(), request.data, user=request.user)
        return Response(L.template_out(t), status=status.HTTP_201_CREATED)


class LibTemplate(LibraryView):
    def get(self, request, uid):
        t = self.template(uid)
        versions = StructureTemplate.objects.filter(company=self.company(), code=t.code).order_by("-version")
        return Response({**L.template_out(t, L.template_usage(self.company()).get(t.code, 0)),
                         "versions": [L.template_out(v) for v in versions]})

    def patch(self, request, uid):
        """A draft saves in place; a published version becomes the next draft."""
        self.refuse_unless(T_EDIT)
        return Response(L.template_out(L.save_template(self.company(), request.data, template=self.template(uid),
                                                       user=request.user)))


class LibTemplateAction(LibraryView):
    def post(self, request, uid, action):
        company = self.company()
        t = self.template(uid)
        if action == "publish":
            self.refuse_unless(T_PUBLISH)
            return Response(L.template_out(L.publish_template(company, t, user=request.user)))
        if action == "archive":
            self.refuse_unless(T_PUBLISH)
            return Response(L.template_out(L.archive_template(company, t, user=request.user)))
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class LibTemplatePreview(LibraryView):
    def get(self, request, uid):
        t = self.template(uid)
        p = request.query_params
        amount = _amount(p.get("amount"), "amount", None if t.gazette else Decimal("50000"))
        return Response(L.preview_template(self.company(), t, amount, grade=p.get("grade") or "",
                                           on=_date(p.get("on"), "on")))


class LibFloors(LibraryView):
    def get(self, request):
        out = L.floors(self.company())
        if not self.salary_figures():
            # Who is below the floor is a pay figure: counted, not listed.
            out = {**out, "breaches": [], "breachCount": len(out["breaches"]), "masked": True}
        else:
            out["breachCount"] = len(out["breaches"])
        return Response({**out, "can": self.can()})

    def patch(self, request):
        self.refuse_unless(POLICY)
        L.set_policy(self.company(), request.data, user=request.user)
        return self.get(request)


class LibBulk(LibraryView):
    def get(self, request):
        rows = BulkRevision.objects.filter(company=self.company()).select_related("target_template")[:100]
        return Response({"revisions": [L.bulk_out(b) for b in rows], "can": self.can()})

    def post(self, request):
        self.refuse_unless(B_PREVIEW)
        b = L.create_bulk(self.company(), request.data, user=request.user)
        return Response(L.bulk_out(b, detail=True), status=status.HTTP_201_CREATED)


class LibBulkOne(LibraryView):
    def get(self, request, uid):
        self.figures_or_refuse()
        b = get_object_or_404(BulkRevision.objects.select_related("target_template"), uid=uid, company=self.company())
        return Response(L.bulk_out(b, detail=True))


class LibBulkAction(LibraryView):
    def post(self, request, uid, action):
        company = self.company()
        b = get_object_or_404(BulkRevision.objects.select_related("target_template"), uid=uid, company=company)
        self.figures_or_refuse()
        if action == "preview":
            self.refuse_unless(B_PREVIEW)
            return Response(L.bulk_out(L.preview_bulk(company, b, user=request.user), detail=True))
        if action == "apply":
            self.refuse_unless(B_APPLY)
            return Response(L.bulk_out(L.apply_bulk(company, b, user=request.user), detail=True))
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class LibAudit(LibraryView):
    def get(self, request):
        return Response({"audit": L.library_audit(self.company())})
