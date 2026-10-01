"""The BD employee API, mounted at /api/v1/we/employees (doc §9).

Lookups key on the business code (`EMP-0142`), not the uid (§2.1).

Tenancy: the employeeio tables have no RLS, so the company filter written
here is the only protection. The employee is always resolved with
`company=` beside `code=`, and every sub-record query carries
`employee__code=` with `employee__company=` on the next line -- the pairing
employeeio/tests_employee_tenant_scoping.py checks by reading this source.
"""

from datetime import date

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from common import clock
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination
from common.django_rest.permissions.admin import IsActiveCompanyAdmin
from common.django_rest.permissions.company_subscription import HaveSubscription
from employeeio.choices import (
    ClassificationChoices,
    DocumentKindChoices,
    TrackedFieldChoices,
    WorkerCategoryChoices,
)
from employeeio.models import (
    Employee,
    EmployeeFieldHistory,
    EmployeeInvestment,
    EmployeeNominee,
    EmployeePaymentProfile,
    EmployeeStatutory,
    EmployeeTaxProfile,
)
from employeeio.services import documents, gated, salary
from employeeio.services.access import NoLinkedLogin, set_login_access
from employeeio.services.compliance import evaluate
from employeeio.services.salary import structure_in_force
from employeeio.services.statutory import derived
from employeeio.services.tax import project
from employeeio.services.withholding import deadlines
from rulebookio.book import RuleBookError, rule_book

from ..serializers.bd_employees import (
    ClassificationChangeSerializer,
    EmployeeCreateSerializer,
    EmployeeProfileSerializer,
    EmployeeRosterSerializer,
    EmploymentSerializer,
    InvestmentListSerializer,
    NomineeListSerializer,
    PaymentSerializer,
    PersonalSerializer,
    SalaryAssignSerializer,
    SalaryReviseSerializer,
    SeparationSerializer,
    access_out,
    StatutorySerializer,
    TaxProfileSerializer,
    history_out,
    investment_out,
    nominee_out,
    structure_out,
    ui_errors,
)

ROSTER_FILTERS = ("ALL", "WORKER", "NON_WORKER", "PROBATION", "BLOCKED")


class BDEmployeeView(APIView):
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def company(self):
        return self.request.user.get_active_company()

    def context(self):
        return {"request": self.request, "company": self.company(), "view": self}

    def get_employee(self):
        return get_object_or_404(
            Employee.objects.select_related("designation", "department", "section", "shift", "manager"),
            code=self.kwargs["code"],
            company=self.company(),
        )

    def invalid(self, serializer):
        return Response(ui_errors(serializer.errors), status=status.HTTP_400_BAD_REQUEST)

    def refused(self, exc):
        """A refused gated operation: the errors, and what it would have done."""
        body = ui_errors(exc.errors)
        if exc.consequence is not None:
            body["consequence"] = exc.consequence
        return Response(body, status=exc.status)

    def handle_exception(self, exc):
        # A missing or unpublished rule set is a configuration gap, not a crash:
        # say which one, so it can be seeded or published.
        if isinstance(exc, RuleBookError):
            return Response({"error": True, "message": str(exc)}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


# ------------------------------------------------------------------- roster


class BDEmployeeListCreate(BDEmployeeView):
    def get(self, request):
        kind = (request.query_params.get("filter") or "ALL").upper()
        if kind not in ROSTER_FILTERS:
            return Response(
                {"errors": [{"field": "filter", "path": "filter",
                             "messages": [f"filter must be one of {', '.join(ROSTER_FILTERS)}."]}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        employees = Employee.objects.filter(company=self.company()).select_related("designation", "department")
        q = (request.query_params.get("q") or "").strip()
        if q:
            employees = employees.filter(Q(code__icontains=q) | Q(name_en__icontains=q) | Q(name_bn__icontains=q))
        if kind == "WORKER":
            employees = employees.filter(classification=ClassificationChoices.WORKER)
        elif kind == "NON_WORKER":
            employees = employees.filter(classification=ClassificationChoices.NON_WORKER)
        elif kind == "PROBATION":
            employees = employees.filter(
                Q(worker_category=WorkerCategoryChoices.PROBATIONER) | Q(confirmation__isnull=True)
            )

        today = clock.today()
        compliance = {}
        if kind == "BLOCKED":
            kept = []
            for employee in employees:
                result = evaluate(employee, as_of=today)
                if result.blocks:
                    compliance[employee.pk] = result
                    kept.append(employee)
            employees = kept

        paginator = CustomPageNumberPagination()
        page = paginator.paginate_queryset(employees, request, view=self)
        rows = [EmployeeRosterSerializer(e, context={**self.context(), "compliance": compliance}).data for e in page]
        return paginator.get_paginated_response(rows)

    def post(self, request):
        serializer = EmployeeCreateSerializer(data=request.data, context=self.context())
        if not serializer.is_valid():
            return self.invalid(serializer)
        employee = serializer.save()
        return Response(
            EmployeeProfileSerializer(employee, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )


# ------------------------------------------------------------------ profile


class BDEmployeeDetail(BDEmployeeView):
    def get(self, request, code):
        return Response(EmployeeProfileSerializer(self.get_employee(), context=self.context()).data)


class BDEmployeeSection(BDEmployeeView):
    """PATCH one section of the profile."""

    serializer_class = None

    def target(self):
        raise NotImplementedError

    def patch(self, request, code):
        instance = self.target()
        serializer = self.serializer_class(instance, data=request.data, partial=True, context=self.context())
        if not serializer.is_valid():
            return self.invalid(serializer)
        serializer.save()
        return Response(self.serializer_class(instance, context=self.context()).data)


class BDEmployeePersonal(BDEmployeeSection):
    serializer_class = PersonalSerializer

    def target(self):
        return self.get_employee()


class BDEmployeeEmployment(BDEmployeeSection):
    serializer_class = EmploymentSerializer

    def target(self):
        return self.get_employee()


class BDEmployeeStatutory(BDEmployeeSection):
    serializer_class = StatutorySerializer

    def target(self):
        return get_object_or_404(
            EmployeeStatutory.objects.select_related("employee"),
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )


class BDEmployeeTaxProfile(BDEmployeeSection):
    serializer_class = TaxProfileSerializer

    def target(self):
        return get_object_or_404(
            EmployeeTaxProfile.objects.select_related("employee"),
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )


class BDEmployeePayment(BDEmployeeSection):
    serializer_class = PaymentSerializer

    def target(self):
        return get_object_or_404(
            EmployeePaymentProfile.objects.select_related("employee"),
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )


class BDEmployeeAccess(BDEmployeeView):
    """Grant or revoke the linked login's access (account behaviour carried
    over from the US employee API). Granting sends the invitation email.

    Only an admin of the active company may call it -- tighter than the US
    API, which let any subscribed member of the company toggle it, and
    deliberately not `IsCompanyAdmin`, whose global `is_admin` flag every
    self-signup carries into companies it was only invited to."""

    permission_classes = [HaveSubscription, IsActiveCompanyAdmin]

    def patch(self, request, code):
        employee = self.get_employee()
        data = request.data if isinstance(request.data, dict) else {}
        enabled = data.get("isAccessEnabled")
        if not isinstance(enabled, bool):
            return Response(
                {"errors": [{"field": "isAccessEnabled", "path": "isAccessEnabled",
                             "messages": ["isAccessEnabled must be true or false."]}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            invited = set_login_access(employee, enabled)
        except NoLinkedLogin as exc:
            return Response({"error": True, "message": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({**access_out(employee), "invitationSent": invited})


# --------------------------------------------------------------- computed


class BDEmployeeCompliance(BDEmployeeView):
    def get(self, request, code):
        return Response(evaluate(self.get_employee()).as_dict())


class BDEmployeeTaxProjection(BDEmployeeView):
    def get(self, request, code):
        today = clock.today()
        book = rule_book(today)
        body = project(self.get_employee(), as_of=today, book=book).as_dict()
        # §7.6: when this month's deduction has to be deposited, and what
        # missing the date costs.
        try:
            body["withholding"] = {"available": True, **deadlines(today, book)}
        except RuleBookError as exc:
            body["withholding"] = {"available": False, "reason": str(exc)}
        return Response(body)


# ------------------------------------------------------- replaced sub-records


class BDEmployeeNominees(BDEmployeeView):
    def rows(self):
        return EmployeeNominee.objects.filter(
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )

    def get(self, request, code):
        self.get_employee()
        return Response({"nominees": [nominee_out(n) for n in self.rows()]})

    @transaction.atomic
    def put(self, request, code):
        """Full replace (§9). The list sent is the list kept."""
        employee = self.get_employee()
        serializer = NomineeListSerializer(data=request.data, context=self.context())
        if not serializer.is_valid():
            return self.invalid(serializer)
        self.rows().delete()
        for position, row in enumerate(serializer.validated_data["nominees"]):
            EmployeeNominee.objects.create(employee=employee, position=position, **row)
        return Response({"nominees": [nominee_out(n) for n in self.rows()]})


class BDEmployeeInvestments(BDEmployeeView):
    def rows(self):
        return EmployeeInvestment.objects.filter(
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )

    def get(self, request, code):
        self.get_employee()
        return Response({"investments": [investment_out(i) for i in self.rows()]})

    @transaction.atomic
    def put(self, request, code):
        employee = self.get_employee()
        serializer = InvestmentListSerializer(data=request.data, context=self.context())
        if not serializer.is_valid():
            return self.invalid(serializer)
        self.rows().delete()
        for position, row in enumerate(serializer.validated_data["investments"]):
            EmployeeInvestment.objects.create(employee=employee, position=position, **row)
        return Response({"investments": [investment_out(i) for i in self.rows()]})


class BDEmployeeHistory(BDEmployeeView):
    def get(self, request, code):
        self.get_employee()
        field = request.query_params.get("field") or "ALL"
        entries = EmployeeFieldHistory.objects.filter(
            employee__code=self.kwargs["code"],
            employee__company=self.company(),
        )
        if field != "ALL":
            if field not in TrackedFieldChoices.values:
                return Response(
                    {"errors": [{"field": "field", "path": "field",
                                 "messages": [f"field must be ALL or one of {', '.join(TrackedFieldChoices.values)}."]}]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            entries = entries.filter(field=field)
        rows = [history_out(h) for h in entries]
        # A field with no entries is an explicit empty result, not a silent blank (§8).
        return Response({
            "field": field,
            "entries": rows,
            "empty": not rows,
            "message": None if rows else (
                "No changes recorded." if field == "ALL" else f"No {field} changes recorded."
            ),
        })


class GatedWriteMixin:
    """The gated writes (salary, classification, separation) are open only to
    an admin of the active company; reading stays with the profile."""

    write_methods = ("POST",)

    def get_permissions(self):
        if self.request.method in self.write_methods:
            return [HaveSubscription(), IsActiveCompanyAdmin()]
        return super().get_permissions()


def _date_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    return date.fromisoformat(raw)


class BDEmployeeSalary(GatedWriteMixin, BDEmployeeView):
    def get(self, request, code):
        employee = self.get_employee()
        try:
            on = _date_param(request, "on") or clock.today()
        except ValueError:
            return Response(
                {"errors": [{"field": "on", "path": "on", "messages": ["on must be a date, YYYY-MM-DD."]}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        structure = structure_in_force(employee, on)
        body = {
            "on": on.isoformat(),
            "structure": structure_out(structure),
            "message": None if structure else f"No salary structure is in force on {on.isoformat()}.",
            "templates": salary.templates_out(),
            "revisionDefault": salary.revision_default(
                employee, salary.latest_structure(employee)).isoformat(),
            "derived": None,
            "floors": None,
        }
        if structure is not None:
            # The structure on file reads whatever the rule book holds; the
            # figures it drives say so when the rules for `on` are missing.
            book = rule_book(on)
            for key, compute in (
                ("derived", lambda: derived(employee, structure, on, book)),
                ("floors", lambda: salary.floor_checks(employee.grade, structure.basic, structure.gross, book)),
            ):
                try:
                    body[key] = compute()
                except RuleBookError as exc:
                    body[key] = {"available": False, "reason": str(exc)}
        return Response(body)

    def post(self, request, code):
        """Assign the first structure (§5.2). `preview: true` computes it --
        floors, warnings, periods and arrears -- without saving."""
        employee = self.get_employee()
        serializer = SalaryAssignSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        try:
            outcome = salary.assign(
                employee, template=data["template"], amount=data.get("amount"),
                effective_from=data.get("effectiveFrom"), arrears_run=data.get("arrearsRun"),
                user=request.user, preview=data["preview"],
            )
        except salary.SalaryRefused as exc:
            return self.refused(exc)
        return Response(outcome, status=status.HTTP_200_OK if data["preview"] else status.HTTP_201_CREATED)


class BDEmployeeSalaryRevise(GatedWriteMixin, BDEmployeeView):
    def post(self, request, code):
        """§5.2 / §6.2. The effective date defaults to the start of the next
        unprocessed period; a backdated revision needs a reason, and a refusal
        still states the periods it would reopen and the arrears."""
        employee = self.get_employee()
        serializer = SalaryReviseSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        try:
            outcome = salary.revise(
                employee, method=data["method"], value=data.get("value"),
                effective_from=data.get("effectiveFrom"), reason=data["reason"], template=data.get("template"),
                rounding=data["rounding"], revision_type=data.get("type"), arrears_run=data.get("arrearsRun"),
                user=request.user, preview=data["preview"],
            )
        except salary.SalaryRefused as exc:
            return self.refused(exc)
        return Response(outcome, status=status.HTTP_200_OK if data["preview"] else status.HTTP_201_CREATED)


class BDEmployeeSalaryHistory(BDEmployeeView):
    def get(self, request, code):
        structures = salary.history(self.get_employee())
        return Response({
            "structures": structures,
            "empty": not structures,
            "message": None if structures else "No salary structure has been assigned.",
        })


class BDEmployeeClassification(GatedWriteMixin, BDEmployeeView):
    def post(self, request, code):
        """§6.1: WORKER <-> NON_WORKER, with an effective date and a reason of
        at least 10 characters. Writes one `classification` history entry."""
        employee = self.get_employee()
        serializer = ClassificationChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        try:
            result = gated.change_classification(
                employee, to=data["to"], effective=data["effective"], reason=data["reason"], user=request.user)
        except gated.GatedRefused as exc:
            return self.refused(exc)
        return Response({**result, "history": history_out(result["history"])})


class BDEmployeeSeparation(GatedWriteMixin, BDEmployeeView):
    def post(self, request, code):
        """§6.3: records the separation; the employee stays a hard block on
        payroll until the final settlement runs. `preview: true` returns the
        entitlement without recording anything."""
        employee = self.get_employee()
        serializer = SeparationSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid(serializer)
        data = serializer.validated_data
        if data["preview"]:
            return Response(gated.separation_preview(
                employee, data["type"], data["date"], data["grossMisconduct"]))
        try:
            result = gated.separate(
                employee, separation_type=data["type"], on=data["date"], reason=data["reason"],
                gross_misconduct=data["grossMisconduct"], user=request.user)
        except gated.GatedRefused as exc:
            return self.refused(exc)
        return Response({**result, "history": history_out(result["history"])}, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- documents

DOCUMENT_KINDS = {
    "service-book": DocumentKindChoices.SERVICE_BOOK,
    "appointment-letter": DocumentKindChoices.APPOINTMENT_LETTER,
    "id-card": DocumentKindChoices.ID_CARD,
}


class BDEmployeeDocuments(BDEmployeeView):
    def get(self, request, code):
        return Response(documents.documents_out(self.get_employee()))


class BDEmployeeDocumentIssue(BDEmployeeView):
    def post(self, request, code, kind):
        """Issue (or reissue) a document, frozen as issued."""
        if kind not in DOCUMENT_KINDS:
            return Response({"error": True, "message": f"No document {kind!r}."}, status=status.HTTP_404_NOT_FOUND)
        employee = self.get_employee()
        try:
            document = documents.issue(employee, DOCUMENT_KINDS[kind], user=request.user)
        except documents.DocumentRefused as exc:
            return Response(exc.as_errors(), status=status.HTTP_400_BAD_REQUEST)
        return Response(documents.document_out(document), status=status.HTTP_201_CREATED)
