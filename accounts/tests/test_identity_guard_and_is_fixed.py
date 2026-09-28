"""Two small holes that only matter once seeded accounts become editable.

Both were dormant: `is_fixed` covers nearly the whole chart today, so almost no
account could reach either path. They are prerequisites 3 and 4 of #33, and each
is a defect on its own terms.

**`is_fixed` was writable on the details serializer.** It says whether the ledger
binds to an account -- a fact about the posting engine, not something a request
may assert. Setting it is one-way: `validate()` then refuses every subsequent
modification and the DELETE view refuses to remove the account, so a client could
freeze one permanently, by intent or by replaying a GET payload back as a PUT,
with no route in the API to undo it. The list serializer has always had it
read-only; the details one did not.

**The rename guard disagreed with the database.** `unique_title_per_company_ci`
is on `Upper(title)`, but `assert_account_identity_is_free` compared with a plain
`=`. So renaming onto "OFFICE SUPPLIES" while "Office Supplies" was live passed
validation and died at the constraint -- and `IntegrityError` is not converted by
the exception handler (only `ProtectedError` is), so the client got a bare 500
instead of a 400 naming the field.
"""

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices as Status,
)
from accounts.models import ChartOfAccount

from common.django_rest.helpers.chart_of_account_helpers import (
    assert_account_identity_is_free,
)

from companyio.choices import CompanyKindChoices
from companyio.models import Company

from rest_framework.exceptions import ValidationError


class IdentityGuardIsCaseInsensitiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme Books")

    _seq = 0

    def account(self, title, status=Status.ACTIVE):
        type(self)._seq += 1
        return ChartOfAccount.objects.create(
            company=self.company, title=title, code=f"69{type(self)._seq:02d}",
            kind=ChartOfAccountKindChoices.EXPENSES, status=status,
        )

    def test_an_exact_duplicate_is_refused(self):
        self.account("Office Supplies")

        with self.assertRaises(ValidationError) as caught:
            assert_account_identity_is_free(self.company, title="Office Supplies")

        self.assertIn("title", caught.exception.detail)

    def test_a_differently_cased_duplicate_is_refused(self):
        """What the database enforces, and the guard did not.

        Passing here previously meant the write reached the constraint and
        raised IntegrityError, which surfaces as a 500 rather than a 400.
        """
        self.account("Office Supplies")

        for attempt in ("OFFICE SUPPLIES", "office supplies", "OfFiCe SuPpLiEs"):
            with self.subTest(title=attempt):
                with self.assertRaises(ValidationError):
                    assert_account_identity_is_free(self.company, title=attempt)

    def test_the_guard_agrees_with_the_database(self):
        """The two must decide the same cases, or one produces a 500."""
        self.account("Office Supplies")

        guard_refused = True
        try:
            assert_account_identity_is_free(self.company, title="OFFICE SUPPLIES")
            guard_refused = False
        except ValidationError:
            pass

        from django.db import IntegrityError, transaction

        db_refused = True
        try:
            with transaction.atomic():
                self.account("OFFICE SUPPLIES")
            db_refused = False
        except IntegrityError:
            pass

        self.assertEqual(
            guard_refused, db_refused,
            "the application guard and the unique index disagree, so one path "
            "produces an unhandled 500",
        )

    def test_a_removed_account_does_not_block_the_title(self):
        """The constraint excludes REMOVED; the guard must too."""
        self.account("Retired Name", status=Status.REMOVED)

        assert_account_identity_is_free(self.company, title="retired name")

    def test_an_account_keeping_its_own_title_is_not_a_collision(self):
        account = self.account("Office Supplies")

        assert_account_identity_is_free(
            self.company, title="OFFICE SUPPLIES", exclude_pk=account.pk
        )

    def test_another_company_is_not_a_collision(self):
        other = Company.objects.create(name="Beta Ledger")
        ChartOfAccount.objects.create(
            company=other, title="Office Supplies", code="6999",
            kind=ChartOfAccountKindChoices.EXPENSES, status=Status.ACTIVE,
        )

        assert_account_identity_is_free(self.company, title="Office Supplies")

    def test_the_code_check_still_works(self):
        self.account("Something")
        existing = ChartOfAccount.objects.filter(company=self.company).first()

        with self.assertRaises(ValidationError) as caught:
            assert_account_identity_is_free(self.company, code=existing.code)

        self.assertIn("code", caught.exception.detail)


class IsFixedIsReadOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_chart_of_account_category", verbosity=0)
        cls.company = Company.objects.create(
            name="Acme Books", kind=CompanyKindChoices.ECOMMERCE
        )

    def test_the_details_serializer_will_not_accept_it(self):
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )

        field = S().fields["is_fixed"]

        self.assertTrue(
            field.read_only,
            "a request could assert that the ledger binds to this account",
        )

    def test_the_list_serializer_agrees(self):
        """It always did. The two must not disagree about the same field."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountListSerializer as S,
        )

        self.assertTrue(S().fields["is_fixed"].read_only)

    def test_it_is_still_returned(self):
        """Read-only, not removed -- the frontend gates its controls on it."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )

        self.assertIn("is_fixed", S().fields)

    def test_a_patch_cannot_freeze_an_account(self):
        """The one-way trapdoor: set it, and nothing can unset it."""
        from weapi.django_rest.serializers.chart_of_accounts import (
            PrivateWeChartOfAccountDetailsSerializer as S,
        )

        account = ChartOfAccount.objects.create(
            company=self.company, title="My Own Account", code="6995",
            kind=ChartOfAccountKindChoices.EXPENSES, status=Status.ACTIVE,
            is_fixed=False,
        )

        serializer = S(instance=account, data={"is_fixed": True}, partial=True)
        serializer.is_valid(raise_exception=True)

        self.assertNotIn("is_fixed", serializer.validated_data)
