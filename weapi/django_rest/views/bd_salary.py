"""The salary profile API (docs/backend/salary-profile.md §6), mounted at
/api/v1/we: the salary list, the structure in force, its history, and the
three writes -- assign/reassign/revise, override, cancel.

Write access to a salary lives here and nowhere else (salary profile §1.1):
the employee profile reads the same structures and does not write them.

Masking is server-side (§7): without `view_salary_figures` a response
carries no amounts at all. Reading one employee's salary is audited, masked
or not.

Tenancy: every employee is resolved with `company=` beside `code=`, and a
structure by uid with `employee__company=` beside it.
"""

from datetime import date

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from common import clock
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination
from common.money import ZERO, money_str
from employeeio.choices import GradeChoices, SalaryAuditActionChoices
from employeeio.models import Employee, EmployeeSalaryStructure
from employeeio.services import salary
from employeeio.services.periods import month_start, next_unprocessed_period
from employeeio.services.salary_access import can_write
from rulebookio.book import RuleBookError, rule_book

from ..serializers.bd_employees import ui_errors
from ..serializers.bd_salary import SalaryCancelSerializer, SalaryOverrideSerializer, SalaryStructureWriteSerializer
from .bd_employees import BDEmployeeView

LIST_FILTERS = ("ALL", "ASSIGNED", "NONE", "FLOOR", "OVERRIDE")


def _forbidden(message):
    return Response({"errors": [{"field": "salary", "path": "salary", "messages": [message]}]},
                    status=status.HTTP_403_FORBIDDEN)


class SalaryView(BDEmployeeView):
    def write_refused(self):
        """None when the caller may write a salary; the 403 otherwise. Writing
        needs the figures too: a save's preview states them."""
        if can_write(self.request.user, self.company()) and self.salary_figures():
            return None
        return _forbidden("Changing a salary needs the 'write salary' and 'view salary figures' permissions.")

    def idempotency_key(self, data):
        return (self.request.headers.get("Idempotency-Key") or data.get("idempotencyKey") or "").strip()[:80]


# ----------------------------------------------------------------- the list


class SalaryProfileList(SalaryView):
    """Who has a structure, what it is built on, and whether basic still
    clears the gazetted floor (§9). Floor position is not confidential;
    amounts are."""

    def get(self, request):
        kind = (request.query_params.get("filter") or "ALL").upper()
        if kind not in LIST_FILTERS:
            return Response({"errors": [{"field": "filter", "path": "filter",
                                         "messages": [f"filter must be one of {', '.join(LIST_FILTERS)}."]}]},
                            status=status.HTTP_400_BAD_REQUEST)
        company, today, figures = self.company(), clock.today(), self.salary_figures()
        employees = list(Employee.objects.filter(company=company).select_related("designation", "department"))
        in_force, scheduled = {}, {}
        live = EmployeeSalaryStructure.objects.filter(employee__company=company).live().prefetch_related("components")
        for s in live.in_force_on(today).order_by("effective_from"):
            in_force[s.employee_id] = s
        for s in live.filter(effective_from__gt=today).order_by("-effective_from"):
            scheduled[s.employee_id] = s
        try:
            book = rule_book(today)
        except RuleBookError:
            book = None

        rows = [self._row(e, in_force.get(e.pk), scheduled.get(e.pk), book, today, figures) for e in employees]
        q = (request.query_params.get("q") or "").strip().lower()
        if q:
            rows = [r for r in rows if any(q in (v or "").lower() for v in (
                r["code"], r["nameEn"], r["nameBn"], r["designation"], r["templateName"], r["template"]))]
        counts = {k: sum(1 for r in rows if self._matches(r, k)) for k in LIST_FILTERS}
        assigned = [r for r in rows if r["hasStructure"]]
        stats = {
            "withStructure": len(assigned),
            "noStructure": counts["NONE"],
            "belowFloor": counts["FLOOR"],
            "overridden": counts["OVERRIDE"],
            "monthlyGrossTotal": money_str(sum((r["_gross"] for r in assigned), ZERO)) if figures else None,
        }
        rows = [r for r in rows if self._matches(r, kind)]
        for r in rows:
            r.pop("_gross")
        paginator = CustomPageNumberPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        response = paginator.get_paginated_response(page)
        response.data.update({"stats": stats, "counts": counts, "masked": not figures, "asOf": today.isoformat()})
        return response

    @staticmethod
    def _matches(row, kind):
        return {
            "ALL": True,
            "ASSIGNED": row["hasStructure"],
            "NONE": not row["hasStructure"],
            "FLOOR": row["floorStatus"] == "BELOW",
            "OVERRIDE": row["overrideCount"] > 0,
        }[kind]

    @staticmethod
    def _row(employee, structure, scheduled, book, today, figures):
        lines = list(structure.components.all()) if structure else []
        gross = sum((c.amount for c in lines), ZERO)
        basic = sum((c.amount for c in lines if c.code == "BASIC"), ZERO)
        floor = None
        floor_status = "NONE"
        if book is not None:
            (floor, _), _, _ = salary.grade_floor_rules(employee.grade, book)
            if structure is not None:
                floor_status = "CLEARS" if basic >= floor else "BELOW"
        return {
            "code": employee.code,
            "nameEn": employee.name_en,
            "nameBn": employee.name_bn,
            "designation": employee.designation.title if employee.designation else None,
            "department": employee.department.title if employee.department else None,
            "grade": employee.grade or None,
            "gradeLabel": GradeChoices(employee.grade).label if employee.grade in GradeChoices.values else None,
            "fresh": employee.created_at.date() == today,
            "hasStructure": structure is not None,
            "template": structure.template if structure else None,
            "templateName": salary.template_label(structure.template) if structure else None,
            "effectiveFrom": structure.effective_from.isoformat() if structure else None,
            "gross": money_str(gross) if structure and figures else None,
            "basic": money_str(basic) if structure and figures else None,
            "floor": money_str(floor),
            "floorStatus": floor_status,
            "overrideCount": sum(1 for c in lines if c.is_overridden),
            "scheduledFrom": scheduled.effective_from.isoformat() if scheduled else None,
            "masked": not figures,
            "_gross": gross,
        }


class SalaryTemplateList(SalaryView):
    def get(self, request):
        return Response({"templates": salary.templates_out(self.company())})


# ------------------------------------------------------ one employee's salary


def _as_of(request):
    raw = request.query_params.get("asOf")
    return date.fromisoformat(raw) if raw else None


class EmployeeSalaryStructures(SalaryView):
    def get(self, request, code):
        """The structure in force on `asOf` (default today), with its floor
        position, employer cost and any scheduled change (§6.3)."""
        employee = self.get_employee()
        try:
            as_of = _as_of(request) or clock.today()
        except ValueError:
            return Response({"errors": [{"field": "asOf", "path": "asOf",
                                         "messages": ["asOf must be a date, YYYY-MM-DD."]}]},
                            status=status.HTTP_400_BAD_REQUEST)
        today = clock.today()
        figures = self.salary_figures()
        structure = salary.structure_in_force(employee, as_of)
        scheduled = salary.scheduled_structure(employee, today)
        latest = salary.latest_structure(employee)
        out = salary.structure_out if figures else salary.masked_structure_out
        body = {
            "asOf": as_of.isoformat(),
            "masked": not figures,
            "canWrite": figures and can_write(request.user, self.company()),
            "employee": {
                "code": employee.code, "nameEn": employee.name_en, "nameBn": employee.name_bn,
                "designation": employee.designation.title if employee.designation else None,
                "department": employee.department.title if employee.department else None,
                "grade": employee.grade or None, "gradeLabel": salary.grade_label(employee.grade),
                "classification": employee.classification or None,
                "dateOfJoining": employee.doj.isoformat() if employee.doj else None,
                "etinOnFile": bool(getattr(getattr(employee, "tax_profile", None), "etin", "")),
            },
            "structure": out(structure, today),
            "scheduled": out(scheduled, today) if scheduled and scheduled != structure else None,
            "latest": str(latest.uid) if latest else None,
            "floor": None,
            "employerCost": None,
            "templates": salary.templates_out(employee.company),
            "defaults": {
                "joiningDate": employee.doj.isoformat() if employee.doj else None,
                "currentPeriodStart": month_start(today).isoformat(),
                "nextPeriodStart": next_unprocessed_period(employee.company, today).isoformat(),
                "revision": salary.revision_default(employee, latest, today).isoformat() if latest else None,
            },
        }
        if structure is not None:
            try:
                book = rule_book(as_of)
                position = salary.floor_position(employee.grade, structure.basic, book)
                if not figures:
                    position = {k: position[k] for k in ("floor", "totalFloor", "clears", "grade", "gradeLabel",
                                                         "rule", "citation", "confidence")}
                    position["note"] = (f"Basic {'clears' if position['clears'] else 'is below'} the gazetted "
                                        f"minimum for {position['gradeLabel']}.")
                body["floor"] = position
                if figures:
                    body["employerCost"] = salary.employer_cost(employee, structure, as_of, book)
            except RuleBookError as exc:
                body["floor"] = {"available": False, "reason": str(exc)}
        if figures and scheduled is not None and structure is not None and scheduled != structure:
            body["scheduledDelta"] = {
                "pct": salary.pct_text(salary.pct(scheduled.gross - structure.gross, structure.gross)),
                "amount": money_str(scheduled.gross - structure.gross),
            }
        salary.audit(employee,
                     SalaryAuditActionChoices.VIEWED_FULL if figures else SalaryAuditActionChoices.VIEWED_MASKED,
                     request.user, structure=structure)
        return Response(body)

    def post(self, request, code):
        """Assign, reassign or revise (§6.1). `preview: true` computes it --
        components, floors, arrears, employer cost -- without saving."""
        refused = self.write_refused()
        if refused:
            return refused
        employee = self.get_employee()
        serializer = SalaryStructureWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        key = "" if data["preview"] else self.idempotency_key(data)
        replayed = salary.replay(employee, key)
        if replayed is not None:
            return Response(salary.replayed_outcome(employee, replayed), status=status.HTTP_201_CREATED)
        latest = salary.latest_structure(employee)
        if latest is not None and "expectedStructure" not in request.data:
            return Response(ui_errors({"expectedStructure": [
                "Name the structure this change is based on (its uid), so a change made meanwhile is caught."]}),
                status=status.HTTP_400_BAD_REQUEST)
        expected = str(data["expectedStructure"]) if data.get("expectedStructure") else None
        common = dict(effective_from=data.get("effectiveFrom"), arrears_run=data.get("arrearsRun"),
                      user=request.user, preview=data["preview"], expected=expected, idempotency_key=key)
        try:
            if data.get("method"):
                value = data.get("value")
                if value is None and data.get("gross") is not None:
                    value = str(data["gross"])
                outcome = salary.revise(
                    employee, method=data["method"], value=value, reason=data["reason"],
                    template=data.get("templateCode"), rounding=data["rounding"],
                    revision_type=data.get("revisionType"), **common)
            else:
                outcome = salary.reassign(
                    employee, template=data["templateCode"], amount=data.get("gross"), reason=data["reason"],
                    revision_type=data.get("revisionType"), **common)
        except salary.SalaryRefused as exc:
            return self.refused(exc)
        return Response(outcome, status=status.HTTP_200_OK if data["preview"] else status.HTTP_201_CREATED)


class EmployeeSalaryHistory(SalaryView):
    def get(self, request, code):
        """Every structure, newest first (§6.4). Read-only: there is no
        endpoint that rewrites history."""
        employee = self.get_employee()
        figures = self.salary_figures()
        rows = salary.history_rows(employee)
        if not figures:
            rows = [{**{k: r[k] for k in ("uid", "status", "effectiveFrom", "effectiveTo", "template", "templateName",
                                         "revisionType", "revisionTypeLabel", "typeLabel", "reason", "approvedBy",
                                         "cancelledAt", "clearsFloor")},
                     "masked": True, "floorThen": {"clears": r["floorThen"].get("clears"),
                                                   "floor": r["floorThen"].get("floor")}}
                    for r in rows]
        return Response({
            "structures": rows,
            "masked": not figures,
            "empty": not rows,
            "message": None if rows else "No salary structure has been assigned.",
            "grade": employee.grade or None,
        })


# --------------------------------------------------- a structure, by its uid


class SalaryStructureAction(SalaryView):
    def get_structure(self):
        return get_object_or_404(
            EmployeeSalaryStructure.objects.select_related("employee", "employee__company")
            .prefetch_related("components", "overrides"),
            uid=self.kwargs["uid"],
            employee__company=self.company(),
        )


class SalaryStructureOverrides(SalaryStructureAction):
    def post(self, request, uid):
        """Component overrides (§6.2): a new structure from the next
        unprocessed period, never an edit of this one."""
        refused = self.write_refused()
        if refused:
            return refused
        structure = self.get_structure()
        employee = structure.employee
        serializer = SalaryOverrideSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        key = "" if data["preview"] else self.idempotency_key(data)
        replayed = salary.replay(employee, key)
        if replayed is not None:
            return Response(salary.replayed_outcome(employee, replayed), status=status.HTTP_201_CREATED)
        try:
            outcome = salary.override(
                employee, structure, rows=[dict(r) for r in data["rows"]], mode=data["mode"], reason=data["reason"],
                effective_from=data.get("effectiveFrom"), arrears_run=data.get("arrearsRun"), user=request.user,
                preview=data["preview"], idempotency_key=key)
        except salary.SalaryRefused as exc:
            return self.refused(exc)
        return Response(outcome, status=status.HTTP_200_OK if data["preview"] else status.HTTP_201_CREATED)


class SalaryStructureCancel(SalaryStructureAction):
    def post(self, request, uid):
        """Cancel a scheduled change (§6.5)."""
        refused = self.write_refused()
        if refused:
            return refused
        structure = self.get_structure()
        serializer = SalaryCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        employee = structure.employee
        try:
            cancelled = salary.cancel(employee, structure, reason=serializer.validated_data["reason"],
                                      user=request.user)
        except salary.SalaryRefused as exc:
            return self.refused(exc)
        out = salary.structure_out if self.salary_figures() else salary.masked_structure_out
        return Response({
            "cancelled": out(cancelled),
            "inForce": out(salary.structure_in_force(employee)),
        })


__all__ = [
    "EmployeeSalaryHistory", "EmployeeSalaryStructures", "SalaryProfileList", "SalaryStructureCancel",
    "SalaryStructureOverrides", "SalaryTemplateList",
]
