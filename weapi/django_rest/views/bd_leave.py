"""The leave API (docs/backend/leave-backend.md §7), mounted at
/api/v1/we/leave: balances, applications, approvals, who is away, the
ledger, grants, the accrual run, the year-end close, encashment, maternity
and the policy in force.

Every availability figure comes from `spendable()`. Requests are entered by
HR for the employee and audited as on their behalf (§3.11); nobody approves
their own leave.

Permissions (§8): apply_leave, approve_leave, grant_leave,
approve_encashment, close_leave_year, read_maternity_restricted. Amounts in
an encashment are masked without `view_salary_figures`.

Tenancy: every employee and record is resolved with `company=`.
"""

from datetime import date

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from common import clock
from employeeio.models import Employee
from employeeio.services.salary_access import has_company_permission
from leaveledgerio.models import LedgerEntry
from leaveledgerio.services import ops, reads
from leaveledgerio.services.core import LeaveRefused, days_str, position_sentence, reverse_entry

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "leaveledgerio"
APPLY, APPROVE, GRANT, ENCASH, CLOSE, MATERNITY = (
    "apply_leave", "approve_leave", "grant_leave", "approve_encashment", "close_leave_year",
    "read_maternity_restricted")
NEEDS = {
    APPLY: "Entering leave for an employee needs the 'apply leave' permission.",
    APPROVE: "Deciding leave needs the 'approve leave' permission.",
    GRANT: "Granting, debiting or correcting leave needs the 'grant leave' permission.",
    ENCASH: "Approving or paying an encashment needs the 'approve encashment' permission.",
    CLOSE: "Posting accruals and closing the leave year needs the 'close leave year' permission.",
}


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise LeaveRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


def _month(value):
    try:
        y, m = (int(x) for x in str(value).split("-")[:2])
        return date(y, m, 1)
    except (TypeError, ValueError):
        raise LeaveRefused({"month": ["month must be YYYY-MM."]}, status=400) from None


class LeaveView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, LeaveRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["consequence"] = exc.detail
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise LeaveRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def can(self):
        return {"apply": self.may(APPLY), "approve": self.may(APPROVE), "grant": self.may(GRANT),
                "encash": self.may(ENCASH), "close": self.may(CLOSE), "maternity": self.may(MATERNITY),
                "figures": self.salary_figures()}

    def employee(self, code=None):
        code = code or self.kwargs.get("code") or self.request.data.get("employeeCode")
        return get_object_or_404(Employee.objects.select_related("company", "department", "site"),
                                 code=str(code or "").strip(), company=self.company())

    def employees(self, codes=None):
        qs = reads.roster(self.company())
        if codes:
            qs = qs.filter(code__in=[str(c).strip() for c in codes])
        return list(qs)


# ---------------------------------------------------------------------- reads


class LeaveSummary(LeaveView):
    def get(self, request):
        return Response({**reads.summary(self.company()), "can": self.can()})


class LeaveBalances(LeaveView):
    def get(self, request):
        flt = (request.query_params.get("filter") or "ALL").upper()
        if flt not in reads.FILTERS:
            raise LeaveRefused({"filter": [f"filter must be one of {', '.join(reads.FILTERS)}."]}, status=400)
        return Response(reads.balances(self.company(), q=request.query_params.get("q") or "", flt=flt,
                                       as_of=_date(request.query_params.get("asOf"), "asOf")))


class LeaveApplications(LeaveView):
    def get(self, request):
        p = request.query_params
        return Response(reads.applications(self.company(), status=(p.get("status") or "ALL").upper(),
                                           q=(p.get("q") or "").strip(), code=p.get("type") or ""))

    def post(self, request):
        self.refuse_unless(APPLY)
        d = request.data
        req = ops.submit_request(
            self.company(), self.employee(), d.get("type"), d.get("from"), d.get("to"),
            start_half=d.get("startHalf") or "FULL", end_half=d.get("endHalf") or "FULL", note=d.get("note") or "",
            contact=d.get("contact") or "", cover_code=d.get("coverCode") or "", evidence=d.get("evidence") or "",
            is_advance=bool(d.get("advance")), user=request.user)
        return Response(reads.request_out(req), status=status.HTTP_201_CREATED)


class LeavePreview(LeaveView):
    """The apply drawer's live line: the breakdown and the position the
    submission will be tested against."""

    def post(self, request):
        d = request.data
        employee = self.employee()
        ltype, cycle, breakdown, p, _ = ops.preview_request(
            self.company(), employee, d.get("type"), d.get("from"), d.get("to"),
            start_half=d.get("startHalf") or "FULL", end_half=d.get("endHalf") or "FULL")
        asked = breakdown["consumed"]
        from leaveledgerio.services.core import d4

        short = d4(asked) > p.spendable and not ltype.allow_negative_balance
        return Response({"breakdown": breakdown, "position": p.out(),
                         "positionSentence": position_sentence(p, ltype), "asked": asked, "short": short,
                         "advanceAllowed": ltype.advance_allowed})


class LeaveRequestAction(LeaveView):
    ACTIONS = {"approve": APPROVE, "decline": APPROVE, "withdraw": APPLY, "cancel": APPLY}

    def post(self, request, reference, action):
        if action not in self.ACTIONS:
            raise LeaveRefused({"action": [f"Unknown action {action!r}."]}, status=404)
        self.refuse_unless(self.ACTIONS[action])
        reason = request.data.get("reason") or ""
        fn = {"approve": lambda: ops.approve_request(self.company(), reference, user=request.user),
              "decline": lambda: ops.decline_request(self.company(), reference, reason=reason, user=request.user),
              "withdraw": lambda: ops.withdraw_request(self.company(), reference, reason=reason, user=request.user),
              "cancel": lambda: ops.cancel_request(self.company(), reference, reason=reason, user=request.user)}
        return Response(reads.request_out(fn[action]()))


class LeaveApprovals(LeaveView):
    def get(self, request):
        return Response({**reads.approvals(self.company(), request.user), "can": self.can()})


class LeaveAway(LeaveView):
    def get(self, request):
        raw = request.query_params.get("month")
        month = _month(raw) if raw else reads.nearest_month_with_absence(self.company(), clock.today())
        return Response(reads.away_month(self.company(), month, dept=request.query_params.get("dept") or None))


class LeaveEmployee(LeaveView):
    def get(self, request, code):
        return Response({**reads.history(self.company(), self.employee(code),
                                         (request.query_params.get("type") or "ALL").upper()), "can": self.can()})


class LeaveTypes(LeaveView):
    def get(self, request):
        from leaveledgerio.services.core import Book, ensure_types

        rules = Book().rules(clock.today())
        return Response({"rows": [reads.type_out(t, rules) for t in ensure_types(self.company()).values()],
                         "can": self.can()})


# --------------------------------------------------------------------- writes


class LeaveGrants(LeaveView):
    def post(self, request):
        self.refuse_unless(GRANT)
        d = request.data
        entry = ops.grant(self.company(), self.employee(), d.get("type"), d.get("days"), reason=d.get("reason"),
                          effective=d.get("effective") or None, user=request.user)
        return Response(reads.entry_out(entry), status=status.HTTP_201_CREATED)


class LeaveBulkGrants(LeaveView):
    def post(self, request):
        d = request.data
        commit = bool(d.get("commit"))
        if commit:
            self.refuse_unless(GRANT)
        codes = d.get("employeeCodes") or None
        employees = self.employees(codes)
        if not employees:
            raise LeaveRefused({"employeeCodes": ["Choose at least one employee."]}, status=400)
        return Response(ops.bulk_grant(self.company(), employees, d.get("type"), d.get("days"),
                                       reason=d.get("reason") or "", effective=d.get("effective") or None,
                                       commit=commit, user=request.user))


class LeaveReverse(LeaveView):
    def post(self, request, uid):
        self.refuse_unless(GRANT)
        entry = get_object_or_404(LedgerEntry, uid=uid, company=self.company())
        reason = ops._reason(request.data.get("reason"), "the reason for the correction")
        replacement = request.data.get("replacementDays")
        reversal, repl = reverse_entry(entry, reason=reason,
                                       replacement_days=None if replacement in (None, "") else replacement,
                                       user=request.user)
        return Response({"reversal": reversal.reference, "replacement": repl.reference if repl else None})


class LeaveAccrualRun(LeaveView):
    def post(self, request):
        d = request.data
        commit = bool(d.get("commit"))
        if commit:
            self.refuse_unless(CLOSE)
        as_of = _date(d.get("asOf"), "asOf") or clock.today()
        return Response(ops.accrual_run(self.company(), self.employees(d.get("employeeCodes") or None), as_of,
                                        days_worked=d.get("daysWorked") or {}, commit=commit, user=request.user))


class LeaveYearEnd(LeaveView):
    def post(self, request):
        d = request.data
        commit = bool(d.get("commit"))
        if commit:
            self.refuse_unless(CLOSE)
        as_of = _date(d.get("asOf"), "asOf") or clock.today()
        return Response(ops.year_end_close(self.company(), self.employees(d.get("employeeCodes") or None), as_of,
                                           commit=commit, confirm=bool(d.get("confirm")), user=request.user))


class LeaveEncashments(LeaveView):
    def get(self, request):
        return Response({**reads.encashments(self.company(), self.salary_figures()), "can": self.can()})

    def post(self, request):
        self.refuse_unless(APPLY)
        enc = ops.request_encashment(self.company(), self.employee(), request.data.get("days"), user=request.user)
        return Response(reads.encashment_out(enc, self.salary_figures()), status=status.HTTP_201_CREATED)


class LeaveEncashmentPreview(LeaveView):
    """The encash drawer's line: free to encash, and the statutory ceiling."""

    def get(self, request, code):
        from leaveledgerio.services.core import Book, cycle_for, ensure_types

        employee = self.employee(code)
        ltype = ensure_types(self.company())["EARNED"]
        book = Book()
        rules = book.rules(clock.today())
        cycle = cycle_for(employee, ltype, clock.today(), book)
        if cycle is None:
            raise LeaveRefused({"employee": [f"{employee.name_en} has no earned-leave year open."]})
        p, ceiling = ops._encash_limits(employee, ltype, cycle, rules, book)
        return Response({"position": p.out(), "ceiling": days_str(ceiling),
                         "sentence": f"{position_sentence(p, ltype, 'free to encash')}; at most {days_str(ceiling)} "
                                     "encashable",
                         "fraction": days_str(rules.encash_fraction), "divisor": rules.day_wage_divisor})


class LeaveEncashmentAction(LeaveView):
    def post(self, request, reference, action):
        if action not in ("approve", "decline", "mark-paid"):
            raise LeaveRefused({"action": [f"Unknown action {action!r}."]}, status=404)
        self.refuse_unless(ENCASH)
        c, u = self.company(), request.user
        enc = {"approve": lambda: ops.approve_encashment(c, reference, user=u),
               "decline": lambda: ops.decline_encashment(c, reference, reason=request.data.get("reason"), user=u),
               "mark-paid": lambda: ops.mark_encashment_paid(c, reference, payment_month=request.data.get("paymentMonth"),
                                                             user=u)}[action]()
        return Response(reads.encashment_out(enc, self.salary_figures()))


class LeaveMaternity(LeaveView):
    def get(self, request):
        return Response({**reads.maternity_cases(self.company()), "can": self.can()})

    def post(self, request):
        self.refuse_unless(APPLY)
        d = request.data
        case = ops.open_maternity_case(
            self.company(), self.employee(), notice_date=d.get("noticeDate"), notice_method=d.get("noticeMethod"),
            expected_delivery=d.get("expectedDelivery"), surviving_children=d.get("survivingChildren"),
            leave_from=d.get("leaveFrom") or None, user=request.user)
        return Response(reads.maternity_out(case), status=status.HTTP_201_CREATED)


class LeaveMaternityDelivery(LeaveView):
    def post(self, request, reference):
        self.refuse_unless(APPLY)
        case = ops.record_delivery(self.company(), reference, actual_delivery=request.data.get("actualDelivery"),
                                   user=request.user)
        return Response(reads.maternity_out(case))


class LeaveMaternityRestricted(LeaveView):
    def get(self, request, reference):
        return Response(ops.read_restricted(self.company(), reference, user=request.user,
                                            allowed=self.may(MATERNITY)))


class LeavePolicy(LeaveView):
    def get(self, request):
        return Response(reads.policy(self.company()))
