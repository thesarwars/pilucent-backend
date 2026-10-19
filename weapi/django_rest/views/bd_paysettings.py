"""The payroll settings API (docs/backend/payroll-settings-done.md §6), mounted
at /api/v1/we/payroll-settings: the seven elections with their consequence
previews, proposals and approval, the pay schedule, the four statutory
schemes and their GL mapping, scheme participation, run readiness and the
changelog.

Permissions (§7), app `paysetio`: view_payroll_settings,
preview_payroll_election, write_payroll_election, approve_payroll_election
(never on a proposal of one's own), write_payroll_scheme, write_pay_schedule,
map_payroll_gl. A company admin holds them all; the separation of proposer
and approver still binds an admin.

Tenancy: every record is resolved with `company=`.
"""

from datetime import date

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from accounts.models import ChartOfAccount
from common import clock
from employeeio.models import Employee, Site
from employeeio.services.salary_access import has_company_permission
from employeeio.services.sites import sites_of
from paysetio.choices import ELECTIONS, PARTICIPATION_SCHEMES, SCHEMES
from paysetio.models import PayrollElection, SchemeParticipation
from paysetio.services import ops as S
from paysetio.services.consequence import Roster, preview
from paysetio.services.ops import SettingsRefused
from paysetio.services.resolve import ElectionUnanswered, elections_for

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "paysetio"
READ, PREVIEW, WRITE, APPROVE, SCHEME, SCHEDULE, GL = (
    "view_payroll_settings", "preview_payroll_election", "write_payroll_election", "approve_payroll_election",
    "write_payroll_scheme", "write_pay_schedule", "map_payroll_gl")
NEEDS = {
    READ: "Viewing payroll settings needs the 'view payroll settings' permission.",
    PREVIEW: "A consequence preview needs the 'preview payroll election' permission.",
    WRITE: "Electing needs the 'write payroll election' permission.",
    APPROVE: "Approving needs the 'approve payroll election' permission.",
    SCHEME: "Configuring a scheme needs the 'write payroll scheme' permission.",
    SCHEDULE: "Changing the pay schedule needs the 'write pay schedule' permission.",
    GL: "Mapping GL accounts needs the 'map payroll GL' permission.",
}


def _month(value):
    if not value:
        return clock.today().replace(day=1)
    try:
        y, m = (int(x) for x in str(value).split("-")[:2])
        return date(y, m, 1)
    except ValueError:
        raise SettingsRefused({"period": ["period is YYYY-MM."]}, status=400) from None


class SettingsView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, SettingsRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["detail"] = exc.detail
            return Response(body, status=exc.status)
        if isinstance(exc, ElectionUnanswered):
            return Response({**ui_errors({"settings": [exc.message]}), "unanswered": exc.key},
                            status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise SettingsRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.user and request.user.is_authenticated and self.company() is not None:
            self.refuse_unless(READ)

    def can(self):
        return {"preview": self.may(PREVIEW), "elect": self.may(WRITE), "approve": self.may(APPROVE),
                "scheme": self.may(SCHEME), "schedule": self.may(SCHEDULE), "gl": self.may(GL),
                "figures": self.salary_figures(), "me": str(self.request.user.uid)}

    def site(self, value=None):
        uid = value if value is not None else (self.request.query_params.get("site") or
                                               (self.request.data.get("site") if hasattr(self.request, "data") and
                                                isinstance(self.request.data, dict) else None))
        if not uid:
            return None
        return get_object_or_404(Site, uid=uid, company=self.company())

    def as_of(self):
        raw = self.request.query_params.get("asOf")
        return S._date(raw, "asOf", clock.today())


def _meta(key):
    m = ELECTIONS[key]
    return {"key": key, "label": m["label"], "bn": m["bn"], "question": m["question"], "governs": m["governs"],
            "options": [{"value": v, "label": label} for v, label in m["options"]],
            "flags": [{"key": f, "label": label} for f, label in m.get("flags", [])],
            "preset": m["preset"], "noDefault": m["preset"] is None}


def elections_out(company, site, on):
    resolved = elections_for(company, site, on)
    drafts = {p.election_key: p for p in S.pending(company, site=site)}
    return [{**_meta(k), "resolved": r.as_dict(),
             "pending": S.election_out(drafts[k]) if k in drafts else None} for k, r in resolved.items()]


class PsSummary(SettingsView):
    """Everything the screen opens on. The org profile is derived from the
    roster on every read (§1.10)."""

    def get(self, request):
        company = self.company()
        S.ensure_settings(company)
        site, on = self.site(), self.as_of()
        elections = elections_out(company, site, on)
        answered = sum(1 for e in elections if e["resolved"]["answered"])
        return Response({
            "asOf": on.isoformat(), "site": S._site_out(site),
            "sites": [S._site_out(s) | {"isDefault": s.is_default} for s in sites_of(company)],
            "elections": elections, "answered": answered, "total": len(elections),
            "pendingAll": [S.election_out(p) for p in S.pending(company, any_scope=True)],
            "schedule": S.schedule_out(S.schedule_in_force(company, site, on)),
            "schemes": [S.scheme_out(S.scheme_in_force(company, c, on)) for c in SCHEMES],
            "readiness": S.readiness(company, site, on.replace(day=1)),
            "org": Roster(company, site, on).profile(),
            "can": self.can(),
        })


class PsElections(SettingsView):
    """§6.3: the resolved set, per key answered or unanswered."""

    def get(self, request):
        return Response({"asOf": self.as_of().isoformat(),
                         "elections": elections_out(self.company(), self.site(), self.as_of())})


class PsElection(SettingsView):
    def get(self, request, key):
        if key not in ELECTIONS:
            return Response({"message": f"Unknown election {key}."}, status=status.HTTP_404_NOT_FOUND)
        return Response({**_meta(key), "history": S.history(self.company(), key, self.site())})

    def post(self, request, key):
        """§6.2: elect, or propose a change."""
        self.refuse_unless(WRITE)
        row = S.elect(self.company(), key, request.data, user=request.user, site=self.site())
        return Response(S.election_out(row), status=status.HTTP_201_CREATED)


class PsElectionPreview(SettingsView):
    def post(self, request, key):
        self.refuse_unless(PREVIEW)
        if key not in ELECTIONS:
            return Response({"message": f"Unknown election {key}."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data
        value, js, hours = (d.get("value"), d.get("data"), d.get("standardMonthHours"))
        if value is not None or key == "days_worked_basis":
            value, js, hours = S.clean_value(key, value, js, hours)
        on = S._date(d.get("effectiveFrom"), default=clock.today())
        return Response(preview(self.company(), key, value, js or d.get("data"), hours=hours, site=self.site(),
                                on=on, params=d.get("params") or {}))


class PsProposal(SettingsView):
    def post(self, request, uid, action):
        company = self.company()
        row = get_object_or_404(PayrollElection.objects.select_related("site", "rule_set"), uid=uid, company=company)
        if action == "approve":
            self.refuse_unless(APPROVE)
            return Response(S.election_out(S.approve(company, row, user=request.user)))
        if action == "reject":
            if not (self.may(APPROVE) or row.decided_by_id == request.user.pk):
                self.refuse_unless(APPROVE)
            return Response(S.election_out(S.reject(company, row, reason=request.data.get("reason"),
                                                    user=request.user)))
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class PsSchedule(SettingsView):
    def get(self, request):
        company, site = self.company(), self.site()
        s = S.schedule_in_force(company, site, self.as_of())
        out = {"schedule": S.schedule_out(s), "can": self.can()}
        if s is not None and s.frequency == "MONTHLY":
            checked, unchecked = S.deadline_check(company, site, s.payment_day)
            out.update(deadlines=checked, unchecked=unchecked)
        return Response(out)

    def put(self, request):
        self.refuse_unless(SCHEDULE)
        s, check = S.set_schedule(self.company(), request.data, user=request.user, site=self.site())
        return Response({"schedule": S.schedule_out(s), "deadlines": check["checked"], "unchecked": check["unchecked"]})


class PsScheduleCheck(SettingsView):
    """The s.123 deadline for a payment day, month by month, before saving."""

    def post(self, request):
        try:
            day = int(request.data.get("paymentDay"))
        except (TypeError, ValueError):
            raise SettingsRefused({"paymentDay": ["paymentDay is a whole number."]}, status=400) from None
        checked, unchecked = S.deadline_check(self.company(), self.site(), day,
                                              S._date(request.data.get("effectiveFrom"), default=clock.today()))
        return Response({"deadlines": checked, "unchecked": unchecked,
                         "late": [c for c in checked if c["late"]]})


class PsSchemes(SettingsView):
    def get(self, request):
        company = self.company()
        S.ensure_settings(company)
        on = self.as_of()
        return Response({"schemes": [S.scheme_out(S.scheme_in_force(company, c, on)) for c in SCHEMES],
                         "readiness": S.readiness(company, None, on.replace(day=1)), "can": self.can()})


class PsScheme(SettingsView):
    def get(self, request, code):
        from paysetio.models import StatutoryScheme

        if code not in SCHEMES:
            return Response({"message": f"Unknown scheme {code}."}, status=status.HTTP_404_NOT_FOUND)
        rows = (StatutoryScheme.objects.filter(company=self.company(), scheme_code=code)
                .select_related("expense_account", "liability_account").order_by("-effective_from", "-created_at"))
        return Response({"current": S.scheme_out(S.scheme_in_force(self.company(), code)),
                         "history": [S.scheme_out(r) | {"status": r.status} for r in rows]})

    def patch(self, request, code):
        self.refuse_unless(SCHEME)
        s = S.update_scheme(self.company(), code, request.data, user=request.user)
        return Response(S.scheme_out(s))


class PsSchemeGl(SettingsView):
    def post(self, request, code):
        self.refuse_unless(GL)
        company = self.company()
        d = request.data

        def acc(field):
            uid = d.get(field)
            return get_object_or_404(ChartOfAccount, uid=uid, company=company) if uid else None

        fields = tuple(f for f, k in (("expense", "expenseUid"), ("liability", "liabilityUid")) if k in d)
        s = S.map_scheme_gl(company, code, expense=acc("expenseUid"), liability=acc("liabilityUid"), fields=fields,
                            user=request.user)
        return Response({**S.scheme_out(s), "readiness": S.readiness(company)})


class PsSchemeAccounts(SettingsView):
    def post(self, request):
        self.refuse_unless(GL)
        company = self.company()
        out = S.create_scheme_accounts(company, request.data.get("codes"), user=request.user)
        return Response({**out, "readiness": S.readiness(company)})


class PsGlAccounts(SettingsView):
    def get(self, request):
        from paylibio.services.library import gl_out

        rows = (ChartOfAccount.objects.filter(company=self.company()).exclude(status__in=("REMOVED", "INACTIVE"))
                .order_by("kind", "code", "title"))
        return Response({"accounts": [gl_out(a) for a in rows]})


class PsParticipants(SettingsView):
    """Who is in a scheme today, and -- for PF -- who is eligible and not."""

    def get(self, request, code):
        if code not in PARTICIPATION_SCHEMES:
            return Response({"message": f"{code} has no per-employee enrolment."}, status=status.HTTP_404_NOT_FOUND)
        company, on = self.company(), self.as_of()
        cfg = S.scheme_config(company, code, on)
        rows = {p.employee_id: p for p in SchemeParticipation.objects.filter(company=company, scheme_code=code)
                .order_by("enrolled_on")}
        out = []
        for e in (Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
                  .exclude(separated_on__lt=on).order_by("code")):
            p = rows.get(e.pk)
            eligible_from = S.pf_eligible_from(e, cfg) if code == "PF" else None
            out.append({"code": e.code, "nameEn": e.name_en, "workerCategory": e.worker_category or None,
                        "classification": e.classification or None,
                        "member": bool(p and p.in_force_on(on)), "participation": S.participation_out(p) if p else None,
                        "eligibleFrom": eligible_from.isoformat() if eligible_from else None})
        members = sum(1 for r in out if r["member"])
        return Response({"scheme": code, "members": members, "employees": out,
                         "autoEnrol": S.auto_enrol(company, on=on) if code == "PF" else None})


class PsAutoEnrol(SettingsView):
    def post(self, request):
        self.refuse_unless(SCHEME)
        return Response(S.auto_enrol(self.company(), apply=bool(request.data.get("apply")), user=request.user))


class PsReadiness(SettingsView):
    """§6.4."""

    def get(self, request):
        return Response(S.readiness(self.company(), self.site(), _month(request.query_params.get("period"))))


class PsChangelog(SettingsView):
    def get(self, request):
        p = request.query_params
        return Response({"changelog": S.changelog(self.company(), key=p.get("key"), scheme=p.get("scheme"))})
