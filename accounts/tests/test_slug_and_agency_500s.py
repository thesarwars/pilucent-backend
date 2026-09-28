"""Two production 500s from `docs/updated-prompts/issues.md`, and their fixes.

Both were unhandled exceptions escaping as `Internal Server Error` rather than
a message the client could act on.

**`POST /me/daily-time-trackings`** -- `AttributeError: 'NoneType' object has no
attribute 'shift'`. `user.get_employee()` returns None when the signed-in user
has no employee record for the active company, which is reachable because
employees are per-company. `employee.shift` was the first statement in
`validate()`, so it ran *before* the two guards that were already there and
already correct.

**`POST /we/agencies`** -- `duplicate key value violates unique constraint
"accounts_chartofaccount_slug_key"`, registering a New York agency.

It is a CROSS-COMPANY collision, which is worth stating because the obvious
reading is wrong: a second agency for the same state *within* one company is
already refused by `validate()` -- *"Only one agency per state is allowed"* --
so the 500 cannot have come from that.

`AutoSlugField` crops to 50 characters and the slug was `f"{title}-{uid8}"`.
"New York State Department of Taxation and Finance" is 49 characters, so the uid
was cropped off entirely and the slug became a pure function of the title.
Measured before the fix, two companies with that title produced:

    new-york-state-department-of-taxation-and-finance
    new-york-state-department-of-taxation-and-financ-2

-- neither carrying a uid, differing only because autoslug de-duplicated. And
that constraint is GLOBAL rather than per-company, while the title is not a
user's invention: it comes from `agencies_chart_of_account.py`, so every company
registering a New York agency generates the same one.

A second, secondary cause is fixed alongside it: the serializer created the
state accounts unconditionally, so any route that reached it twice would collide
on the per-company title index instead.

The slug fix is the load-bearing one: `AutoSlugField(unique=True)` does append
`-2` in a plain test, but it cannot be relied on here. `ChartOfAccount` is under
forced row-level security, so its uniqueness query sees one company's rows while
the constraint spans all of them, and it is a read-then-write with no lock.
Budgeting the title so the uid always survives makes the slug unique by
construction and removes the need to de-duplicate at all.
"""

from datetime import date

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
)
from accounts.django_rest.helpers.slug_helpers import (
    SLUG_MAX_LENGTH,
    get_chart_of_account_slug,
)
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser

from rest_framework.exceptions import ValidationError


NY_TITLE = "New York State Department of Taxation and Finance"


class FakeRequest:
    def __init__(self, user):
        self.user = user


# ----------------------------------------------------------------- the slug


class SlugKeepsItsUidTests(TestCase):
    """The uid has to survive cropping, because it is what makes it unique."""

    def _account(self, company, title):
        return ChartOfAccount.objects.create(
            company=company, title=title, code="27000",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

    def test_a_long_title_still_leaves_the_uid_in_the_slug(self):
        """The exact title from the production traceback."""
        company = Company.objects.create(name="Slug Co")
        account = self._account(company, NY_TITLE)

        uid_segment = str(account.uid).split("-")[0]

        self.assertLessEqual(len(account.slug), SLUG_MAX_LENGTH)
        self.assertIn(
            uid_segment, account.slug,
            f"the uid was cropped off {account.slug!r} -- the slug is now a "
            f"pure function of the title and collides across companies",
        )

    def test_the_same_title_in_two_companies_gets_two_slugs(self):
        """The production case: the constraint is global, the title is shared.

        Before the fix both rows generated the identical cropped slug, and the
        second insert violated `accounts_chartofaccount_slug_key`.
        """
        first = self._account(Company.objects.create(name="Co A"), NY_TITLE)
        second = self._account(Company.objects.create(name="Co B"), NY_TITLE)

        self.assertNotEqual(first.slug, second.slug)

    def test_the_generator_never_exceeds_the_field(self):
        """Budgeted on the raw length; slugify only ever shortens."""
        class Stub:
            uid = "abcdef12-3456-7890-abcd-ef1234567890"
            title = "X" * 300

        self.assertLessEqual(len(get_chart_of_account_slug(Stub())), SLUG_MAX_LENGTH)

    def test_a_missing_title_does_not_raise(self):
        """`title` is nullable on the base model."""
        class Stub:
            uid = "abcdef12-3456-7890-abcd-ef1234567890"
            title = None

        self.assertIn("abcdef12", get_chart_of_account_slug(Stub()))

    def test_short_titles_are_untouched(self):
        """The common case must not change shape."""
        company = Company.objects.create(name="Short Co")
        account = self._account(company, "Sales Tax Payable")

        self.assertIn(str(account.uid).split("-")[0], account.slug)
        self.assertTrue(account.slug.startswith("sales-tax-payable"))


# ------------------------------------------------------- the agency creates


class AgencyAccountsAreIdempotentTests(TestCase):
    """A second agency for a state the company already has must not 500."""

    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)

    def setUp(self):
        self.company = Company.objects.create(name="Agency Co", kind="ECOMMERCE")
        self.user = User.objects.create_user(
            name="A", email="agency@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=self.user, company=self.company)

    def create_agency(self, title):
        from weapi.django_rest.serializers.agencies import (
            PrivateWeAgencyListSerializer,
        )

        serializer = PrivateWeAgencyListSerializer(
            data={
                "title": title,
                "filling_frequency": "QUARTERLY",
                "start_of_period": "January",
                "date": "2027-01-01",
                "reporting_method": "ACCRUAL",
                "state": "NY",
            },
            context={"request": FakeRequest(self.user)},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_two_companies_can_each_register_a_new_york_agency(self):
        """The production case, and it is CROSS-COMPANY.

        A second agency for the same state within one company is already
        refused by `validate()` -- *"Only one agency per state is allowed"* --
        so the 500 could not have come from that. It came from two different
        companies each generating the same cropped slug for the same
        config-supplied title, against a constraint that spans all companies.

        This is the test that would have failed before the slug fix.
        """
        self.create_agency("New York State Department of Taxation and Finance")

        other = Company.objects.create(name="Agency Co 2", kind="ECOMMERCE")
        other_user = User.objects.create_user(
            name="B", email="agency2@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=other_user, company=other)

        from weapi.django_rest.serializers.agencies import (
            PrivateWeAgencyListSerializer,
        )

        serializer = PrivateWeAgencyListSerializer(
            data={
                "title": "NYC Department of Taxation and Finance",
                "filling_frequency": "QUARTERLY",
                "start_of_period": "January",
                "date": "2027-01-01",
                "reporting_method": "ACCRUAL",
                "state": "NY",
            },
            context={"request": FakeRequest(other_user)},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Both companies got their own copy, with distinct slugs.
        rows = ChartOfAccount.objects.filter(title__iexact="New York State")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(len({r.slug for r in rows}), 2, "slugs collided")

    def test_the_state_accounts_are_not_duplicated_within_a_company(self):
        """The idempotency half, exercised directly.

        Secondary to the slug fix -- the one-agency-per-state rule already
        stops the common route in -- but the state accounts can exist for other
        reasons, and creating them again would collide on the title index.
        """
        from weapi.django_rest.serializers.agencies import (
            get_or_create_agency_account,
        )

        self.create_agency("New York State Department of Taxation and Finance")

        for title in ("New York State", "MCTD", "Local"):
            with self.subTest(title=title):
                get_or_create_agency_account(
                    self.company, title,
                    code="27001",
                    kind=ChartOfAccountKindChoices.LIABILITIES,
                    status=ChartOfAccountStatusChoices.ACTIVE,
                )
                self.assertEqual(
                    ChartOfAccount.objects.filter(
                        company=self.company, title__iexact=title
                    ).count(),
                    1,
                    f"{title!r} was created more than once",
                )

    def test_the_helper_matches_case_insensitively(self):
        """The DB index is on `Upper(title)`, so the lookup must agree with it.

        A case-sensitive lookup would miss the existing row and then collide
        with it, which is the same 500 by a different route.
        """
        from weapi.django_rest.serializers.agencies import (
            get_or_create_agency_account,
        )

        first = ChartOfAccount.objects.create(
            company=self.company, title="New York State", code="27001",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )
        again = get_or_create_agency_account(
            self.company, "NEW YORK STATE",
            code="27001", kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

        self.assertEqual(first.pk, again.pk)

    def test_a_retired_account_is_recreated_not_resurrected(self):
        """REMOVED is excluded, so the tenant's retirement is respected."""
        from weapi.django_rest.serializers.agencies import (
            get_or_create_agency_account,
        )

        retired = ChartOfAccount.objects.create(
            company=self.company, title="MCTD", code="27002",
            kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.REMOVED,
        )
        fresh = get_or_create_agency_account(
            self.company, "MCTD",
            code="27002", kind=ChartOfAccountKindChoices.LIABILITIES,
            status=ChartOfAccountStatusChoices.ACTIVE,
        )

        self.assertNotEqual(retired.pk, fresh.pk)
        self.assertEqual(fresh.status, ChartOfAccountStatusChoices.ACTIVE)


# ------------------------------------------------------------- attendance


class AttendanceWithoutAnEmployeeRecordTests(TestCase):
    """A user with no employee record gets a message, not a 500."""

    def setUp(self):
        self.company = Company.objects.create(name="Attend Co")
        self.user = User.objects.create_user(
            name="A", email="attend@example.com", password="pass1234!"
        )

    def serializer(self):
        from meapi.django_rest.serializer.attendances import (
            PrivateMeDailyTimeTrackingListSerializer,
        )

        return PrivateMeDailyTimeTrackingListSerializer(
            data={}, context={"request": FakeRequest(self.user)}
        )

    def test_no_company_membership_is_refused_first(self):
        """The permission check must run before anything dereferences."""
        with self.assertRaises(ValidationError) as caught:
            self.serializer().is_valid(raise_exception=True)

        self.assertIn("permission", str(caught.exception).lower())

    def test_a_company_member_with_no_employee_record_gets_a_message(self):
        """The production traceback: AttributeError on None.shift.

        Reachable because employees are per-company -- a user can belong to a
        company without having an employee record in it.
        """
        CompanyUser.objects.create(user=self.user, company=self.company)

        with self.assertRaises(ValidationError) as caught:
            self.serializer().is_valid(raise_exception=True)

        message = str(caught.exception).lower()
        self.assertIn("employee", message)
        self.assertNotIn("nonetype", message)
