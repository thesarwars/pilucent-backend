"""Every employee sub-resource resolved by the employee's `uid` alone.

Found by the sweep P0.1 called for, and worse than the reconciliation leak that
prompted it.

Sixteen views -- a list and a detail for each of education, work experience,
banking information, tax, earnings, deductions, garnishments and documents --
filtered on `employee__uid` taken from the URL and the child row's own uid, with
no company anywhere. Eight serializer `create()` paths resolved the employee the
same way. The detail views are `RetrieveUpdateDestroy`, so the exposure was
read, write **and** delete across tenants, over banking information, tax records
and wage garnishments.

Two things meant nothing else caught it:

* these child models have **no `company` field**, so `IsGroupPermission`'s
  object-level check could not have scoped them -- it compares `obj.company`
  "when both are present", and here it never is;
* and it was not applied anyway. All sixteen carry `permission_classes =
  [HaveSubscription]`, which asks only whether the caller pays for the feature.

The fix follows the precedent already in the same file:
`PrivateWeCompanyGarnishmentList` scopes with
`employee__company=self.request.user.get_active_company()`.

Not part of `COA_FIX_PLAN_V3.md` P0.1 -- that covered bank reconciliation. This
is the same defect shape in a different module, found by the sweep.
"""

from datetime import date

from django.test import TestCase

from accounts.models import User

from companyio.models import Company, CompanyUser

from employeeio.models import (
    Employee,
    EmployeeBankingInformation,
    EmployeeEducation,
    EmployeeGarnishment,
)


class FakeView:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeRequest:
    def __init__(self, user):
        self.user = user


class EmployeeSubResourceScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Acme Books")
        cls.company_b = Company.objects.create(name="Beta Ledger")

        cls.user_a = User.objects.create_user(
            name="A", email="a@example.com", password="pass1234!"
        )
        cls.user_b = User.objects.create_user(
            name="B", email="b@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user_a, company=cls.company_a)
        CompanyUser.objects.create(user=cls.user_b, company=cls.company_b)

        cls.emp_a = Employee.objects.create(
            company=cls.company_a, user=cls.user_a, first_name="Ada", last_name="A"
        )
        cls.emp_b = Employee.objects.create(
            company=cls.company_b, user=cls.user_b, first_name="Bo", last_name="B"
        )

    # ------------------------------------------------------------ the models

    def test_the_child_models_have_no_company_field(self):
        """Why the object-level permission check could never have helped."""
        for model in (
            EmployeeEducation,
            EmployeeBankingInformation,
            EmployeeGarnishment,
        ):
            fields = {f.name for f in model._meta.get_fields()}
            with self.subTest(model=model.__name__):
                self.assertNotIn("company", fields)
                self.assertIn("employee", fields)

    # ------------------------------------------------------------ list views

    def view_queryset(self, view_class, user, employee, **extra):
        view = view_class()
        view.kwargs = {"uid": str(employee.uid), **extra}
        view.request = FakeRequest(user)
        return view.get_queryset()

    def test_b_cannot_list_as_employee_education(self):
        from weapi.django_rest.views.employees import (
            PrivateWeEmployeeEducationList,
        )

        EmployeeEducation.objects.create(
            employee=self.emp_a, institute_name="A University"
        )

        theirs = self.view_queryset(
            PrivateWeEmployeeEducationList, self.user_b, self.emp_a
        )
        mine = self.view_queryset(
            PrivateWeEmployeeEducationList, self.user_a, self.emp_a
        )

        self.assertEqual(theirs.count(), 0, "B listed A's employee records")
        self.assertEqual(mine.count(), 1, "A can still see their own")

    def test_b_cannot_list_as_garnishments(self):
        """Wage garnishment is among the most sensitive rows we hold."""
        from weapi.django_rest.views.employees import (
            PrivateWeEmployeeGarnishmentList,
        )

        EmployeeGarnishment.objects.create(employee=self.emp_a)

        self.assertEqual(
            self.view_queryset(
                PrivateWeEmployeeGarnishmentList, self.user_b, self.emp_a
            ).count(),
            0,
        )
        self.assertEqual(
            self.view_queryset(
                PrivateWeEmployeeGarnishmentList, self.user_a, self.emp_a
            ).count(),
            1,
        )

    # ---------------------------------------------------------- detail views

    def test_b_cannot_fetch_as_banking_information(self):
        from django.http import Http404

        from weapi.django_rest.views.employees import (
            PrivateWeEmployeeBankingInformationDetails,
        )

        banking = EmployeeBankingInformation.objects.create(employee=self.emp_a)

        def fetch(user):
            view = PrivateWeEmployeeBankingInformationDetails()
            view.kwargs = {
                "uid": str(self.emp_a.uid),
                "banking_information_uid": str(banking.uid),
            }
            view.request = FakeRequest(user)
            return view.get_object()

        with self.assertRaises(Http404):
            fetch(self.user_b)
        self.assertEqual(fetch(self.user_a).pk, banking.pk)

    def test_b_cannot_delete_as_education(self):
        """The detail views are RetrieveUpdateDestroy, so this was a delete too."""
        from django.http import Http404

        from weapi.django_rest.views.employees import (
            PrivateWeEmployeeEducationDetails,
        )

        row = EmployeeEducation.objects.create(
            employee=self.emp_a, institute_name="A University"
        )

        view = PrivateWeEmployeeEducationDetails()
        view.kwargs = {"uid": str(self.emp_a.uid), "education_uid": str(row.uid)}
        view.request = FakeRequest(self.user_b)

        with self.assertRaises(Http404):
            view.get_object()
        self.assertTrue(EmployeeEducation.objects.filter(pk=row.pk).exists())

    # ----------------------------------------------------------- create path

    def test_b_cannot_create_a_row_against_as_employee(self):
        from django.http import Http404

        from weapi.django_rest.serializers.employees import (
            PrivateWeEmployeeEducationListSerializer,
        )

        serializer = PrivateWeEmployeeEducationListSerializer(
            data={"institute_name": "Injected"},
            context={
                "request": FakeRequest(self.user_b),
                "view": FakeView(uid=str(self.emp_a.uid)),
            },
        )
        serializer.is_valid(raise_exception=True)

        with self.assertRaises(Http404):
            serializer.save()
        self.assertEqual(
            EmployeeEducation.objects.filter(employee=self.emp_a).count(), 0
        )

    def test_a_can_still_create_against_their_own_employee(self):
        from weapi.django_rest.serializers.employees import (
            PrivateWeEmployeeEducationListSerializer,
        )

        serializer = PrivateWeEmployeeEducationListSerializer(
            data={"institute_name": "A University"},
            context={
                "request": FakeRequest(self.user_a),
                "view": FakeView(uid=str(self.emp_a.uid)),
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self.assertEqual(
            EmployeeEducation.objects.filter(employee=self.emp_a).count(), 1
        )


class CallSiteTests(TestCase):
    """Guards against a new sub-resource being added without scoping."""

    def source(self):
        import inspect

        from weapi.django_rest.views import employees

        return inspect.getsource(employees)

    def test_every_employee_uid_filter_is_paired_with_a_company_filter(self):
        source = self.source()
        lines = source.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith(("employee__uid=", "fileitemconnector__employee__uid=")):
                continue
            if stripped.startswith("#"):
                continue
            window = "\n".join(lines[i : i + 2])
            with self.subTest(line=i + 1):
                self.assertIn(
                    "employee__company=",
                    window,
                    f"line {i + 1} filters by employee uid with no company scope",
                )

    def test_the_document_views_scope_through_the_connector(self):
        """`FileItem` has no `employee` relation -- it is reached via the connector.

        The first cut of this fix used `employee__company=` on both FileItem
        querysets. That is a FieldError at query time, which compiles clean and
        only fails on request.
        """
        source = self.source()

        self.assertNotIn(
            'fileitemconnector__employee__uid=self.kwargs.get("uid", None),\n'
            "                employee__company=",
            source,
        )
        self.assertEqual(
            source.count("fileitemconnector__employee__company="), 2
        )

    def test_no_unscoped_employee_lookup_remains_in_the_serializers(self):
        import inspect

        from weapi.django_rest.serializers import employees

        self.assertNotIn(
            'Employee.objects.filter(uid=self.context["view"].kwargs.get("uid"))',
            inspect.getsource(employees),
        )
