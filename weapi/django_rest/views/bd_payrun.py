"""The run payroll API (docs/backend/run-payroll-done.md §6), mounted at
/api/v1/we/payroll-runs: the schedule overview, a run through its five
stages, the payment files and the wage register.

Permissions (§7), app `payrunio`: view_payroll_run, create_payroll_run,
compute_payroll_run, exclude_payroll_employee, override_payroll_ot,
approve_payroll_run (never a run one created), instruct_payroll_payment,
mark_payroll_paid, release_payslips. A company admin holds them all; the
separation of creator and approver still binds an admin.

Tenancy: every record is resolved with `company=`.
"""

from datetime import date

from django.http import HttpResponse
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from common import clock
from employeeio.models import Site
from employeeio.services.salary_access import has_company_permission
from payrunio.models import PaymentInstruction, PayrollException, PayrollRun, PayrollRunLine
from payrunio.services import bankfiles
from payrunio.services import ops as R
from payrunio.services.ops import RunRefused
from payrunio.services.present import overview, register, run_head, run_out

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "payrunio"
READ, CREATE, COMPUTE, EXCLUDE, OT, APPROVE, INSTRUCT, PAID, RELEASE = (
    "view_payroll_run", "create_payroll_run", "compute_payroll_run", "exclude_payroll_employee",
    "override_payroll_ot", "approve_payroll_run", "instruct_payroll_payment", "mark_payroll_paid", "release_payslips")
NEEDS = {
    READ: "Viewing payroll runs needs the 'view payroll run' permission.",
    CREATE: "Opening a run needs the 'create payroll run' permission.",
    COMPUTE: "Computing needs the 'compute payroll run' permission.",
    EXCLUDE: "Excluding an employee needs the 'exclude payroll employee' permission.",
    OT: "Typing over attendance overtime needs the 'override payroll OT' permission.",
    APPROVE: "Approving needs the 'approve payroll run' permission.",
    INSTRUCT: "Generating a payment file needs the 'instruct payroll payment' permission.",
    PAID: "Marking a payment needs the 'mark payroll paid' permission.",
    RELEASE: "Releasing payslips needs the 'release payslips' permission.",
}


def _month(value):
    if not value:
        t = clock.today()
        return date(t.year - (t.month == 1), (t.month - 2) % 12 + 1, 1)  # the month just ended
    try:
        y, m = (int(x) for x in str(value).split("-")[:2])
        return date(y, m, 1)
    except ValueError:
        raise RunRefused({"period": ["period is YYYY-MM."]}, status=400) from None


class RunView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, RunRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["detail"] = exc.detail
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise RunRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.user and request.user.is_authenticated and self.company() is not None:
            self.refuse_unless(READ)

    def can(self):
        return {"create": self.may(CREATE), "compute": self.may(COMPUTE), "exclude": self.may(EXCLUDE),
                "overrideOt": self.may(OT), "approve": self.may(APPROVE), "instruct": self.may(INSTRUCT),
                "markPaid": self.may(PAID), "release": self.may(RELEASE), "me": str(self.request.user.uid),
                "meName": getattr(self.request.user, "name", "") or self.request.user.email}

    def run(self, uid):
        return get_object_or_404(PayrollRun.objects.select_related("company", "site", "schedule", "rule_set",
                                                                   "tax_card", "created_by"),
                                 uid=uid, company=self.company())

    def out(self, run, code=status.HTTP_200_OK):
        run.refresh_from_db()
        return Response({**run_out(run, me=self.request.user), "can": self.can()}, status=code)


class PrOverview(RunView):
    """Stage 1: which payroll is due."""

    def get(self, request):
        period = _month(request.query_params.get("period"))
        return Response({**overview(self.company(), period), "can": self.can()})


class PrRuns(RunView):
    def get(self, request):
        qs = PayrollRun.objects.filter(company=self.company()).select_related("site").order_by("-period_start")
        if request.query_params.get("period"):
            qs = qs.filter(period_start=_month(request.query_params["period"]))
        return Response({"runs": [{**run_head(r), "site": r.site.name} for r in qs[:100]]})

    def post(self, request):
        """§6.1."""
        self.refuse_unless(CREATE)
        d = request.data
        site = get_object_or_404(Site, uid=d.get("site"), company=self.company()) if d.get("site") else None
        run, created = R.create_run(self.company(), site, _month(d.get("period")), user=request.user,
                                    idempotency_key=str(d.get("idempotencyKey") or ""))
        return self.out(run, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PrRun(RunView):
    def get(self, request, uid):
        return self.out(self.run(uid))


class PrLine(RunView):
    """Stage 2: exclude or include, or override overtime, for this run only."""

    def post(self, request, uid, line):
        run = self.run(uid)
        ln = get_object_or_404(PayrollRunLine, uid=line, run=run)
        d = request.data
        R.set_line(run, ln, user=request.user, included=d.get("included"), reason=d.get("reason", ""),
                   ot_hours=d["otHours"] if "otHours" in d else ..., can_exclude=self.may(EXCLUDE),
                   can_override=self.may(OT))
        return self.out(run)


class PrIncludeAll(RunView):
    def post(self, request, uid):
        self.refuse_unless(EXCLUDE)
        run = self.run(uid)
        R.include_all(run, user=request.user)
        return self.out(run)


class PrCompute(RunView):
    """§6.2."""

    def post(self, request, uid):
        self.refuse_unless(COMPUTE)
        run, _ = R.compute(self.run(uid), user=request.user)
        return self.out(run)


class PrException(RunView):
    """§6.3."""

    def post(self, request, uid, exc):
        run = self.run(uid)
        x = get_object_or_404(PayrollException, uid=exc, run=run)
        resolution = request.data.get("resolution")
        if resolution == "FIXED_UPSTREAM":
            self.refuse_unless(COMPUTE)
        elif resolution == "ACCEPTED":
            self.refuse_unless(COMPUTE)
        R.resolve_exception(run, x, resolution=resolution, reason=request.data.get("reason", ""),
                            user=request.user, can_exclude=self.may(EXCLUDE))
        return self.out(run)


class PrApprove(RunView):
    """§6.4."""

    def post(self, request, uid):
        self.refuse_unless(APPROVE)
        return self.out(R.approve(self.run(uid), user=request.user))


class PrCancel(RunView):
    def post(self, request, uid):
        self.refuse_unless(CREATE)
        return self.out(R.cancel(self.run(uid), reason=request.data.get("reason", ""), user=request.user))


class PrInstruct(RunView):
    """§6.5."""

    def post(self, request, uid):
        self.refuse_unless(INSTRUCT)
        run = self.run(uid)
        ins, created = R.instruct(run, request.data.get("profile"),
                                  idempotency_key=str(request.data.get("idempotencyKey") or ""), user=request.user)
        resp = self.out(run, status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        resp.data["instruction"] = {"uid": str(ins.uid), "fileName": ins.file_name, "hash": ins.file_hash,
                                    "rows": ins.row_count, "replayed": not created}
        return resp


class PrInstructionFile(RunView):
    """The stored bytes, exactly as hashed."""

    def get(self, request, uid, ins):
        run = self.run(uid)
        i = get_object_or_404(PaymentInstruction, uid=ins, run=run)
        resp = HttpResponse(R.instruction_bytes(i), content_type=f"text/plain; charset={i.encoding}")
        resp["Content-Disposition"] = f'attachment; filename="{i.file_name}"'
        resp["X-File-Hash"] = i.file_hash
        return resp


class PrMarkPaid(RunView):
    """§6.6: one line, several, or every instructed line."""

    def post(self, request, uid):
        self.refuse_unless(PAID)
        run = self.run(uid)
        uids = request.data.get("lines")
        qs = run.lines.filter(included=True, payment_status="INSTRUCTED")
        lines = list(qs if uids in (None, "all") else run.lines.filter(uid__in=list(uids)))
        if not lines:
            raise RunRefused({"lines": ["No instructed payment to mark paid."]}, status=409)
        R.mark_paid(run, lines, user=request.user)
        return self.out(run)


class PrMarkFailed(RunView):
    def post(self, request, uid, line):
        self.refuse_unless(PAID)
        run = self.run(uid)
        R.mark_failed(run, get_object_or_404(PayrollRunLine, uid=line, run=run),
                      reason=request.data.get("reason", ""), user=request.user)
        return self.out(run)


class PrRelease(RunView):
    """§6.7."""

    def post(self, request, uid):
        self.refuse_unless(RELEASE)
        return self.out(R.release(self.run(uid), user=request.user))


class PrRegister(RunView):
    """§10.1, the s.123 wage register."""

    def get(self, request, uid):
        run = self.run(uid)
        return Response({**run_head(run), "site": run.site.name, "rows": register(run)})


class PrProfiles(RunView):
    def get(self, request):
        return Response({"profiles": [bankfiles.profile_out(p, R.corporate_account(self.company(), p["code"]))
                                      for p in bankfiles.PROFILES]})

    def put(self, request):
        self.refuse_unless(INSTRUCT)
        R.set_corporate_account(self.company(), request.data.get("profile"), request.data.get("account"),
                                user=request.user)
        return self.get(request)
