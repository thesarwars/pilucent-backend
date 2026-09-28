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
from common.django_rest.permissions.company_subscription import HaveSubscription
from employeeio.choices import ClassificationChoices, TrackedFieldChoices, WorkerCategoryChoices
from employeeio.models import (
    Employee,
    EmployeeFieldHistory,
    EmployeeInvestment,
    EmployeeNominee,
    EmployeePaymentProfile,
    EmployeeStatutory,
    EmployeeTaxProfile,
)
from employeeio.services.compliance import evaluate
from employeeio.services.salary import structure_in_force
from employeeio.services.tax import project
from rulebookio.book import RuleBookError

from ..serializers.bd_employees import (
    EmployeeCreateSerializer,
    EmployeeProfileSerializer,
    EmployeeRosterSerializer,
    EmploymentSerializer,
    InvestmentListSerializer,
    NomineeListSerializer,
    PaymentSerializer,
    PersonalSerializer,
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


# --------------------------------------------------------------- computed


class BDEmployeeCompliance(BDEmployeeView):
    def get(self, request, code):
        return Response(evaluate(self.get_employee()).as_dict())


class BDEmployeeTaxProjection(BDEmployeeView):
    def get(self, request, code):
        return Response(project(self.get_employee()).as_dict())


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


class BDEmployeeSalary(BDEmployeeView):
    def get(self, request, code):
        employee = self.get_employee()
        raw = request.query_params.get("on")
        try:
            on = date.fromisoformat(raw) if raw else clock.today()
        except ValueError:
            return Response(
                {"errors": [{"field": "on", "path": "on", "messages": ["on must be a date, YYYY-MM-DD."]}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        structure = structure_in_force(employee, on)
        return Response({
            "on": on.isoformat(),
            "structure": structure_out(structure),
            "message": None if structure else f"No salary structure is in force on {on.isoformat()}.",
        })
