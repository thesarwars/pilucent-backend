"""Phase 0 of BANK_REGISTER_FIX_PLAN.md — the reachable holes.

Six findings from BANK_REGISTER_GAPS.md, none of which need the module designed:

  BR-2   two live endpoints are a 403 and a 500 for every ordinary user
  BR-3   `is_closed` is client-writable at create, so a session can be born closed
  BR-7   a router-registered ModelViewSet exposes every reconciliation field, unguarded
  BR-8   `read_only_fields` is inert on declared fields, so `journal_entry`/`uid` stay writable
  BR-9   rule `create_or_update` writes another tenant's rows by uid
  BR-10  bank-deposit money legs are not company-scoped

BR-2 must land WITH BR-3 and BR-7, never before them: today the guarded close path is
unreachable and the unguarded ones are the only way through, so opening the door first is
strictly worse than the status quo. The three are asserted together here for that reason.

Every assertion reads the built serializer fields or calls the permission resolver directly.
Nothing here trusts a docstring or a `read_only_fields` list -- BR-8 exists precisely because
that list can be a statement of intent that DRF ignores.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from adminio.django_rest.helpers.group_permissions import (
    _resolve_required_permissions,
)

from companyio.models import Company, CompanyUser


class _Req:
    def __init__(self, method="GET", user=None):
        self.method = method
        self.user = user


class Phase0Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Phase0 Co")
        cls.other = Company.objects.create(name="Someone Else")
        cls.user = User.objects.create_user(
            name="P", email="phase0@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def _account(self, company, title, code):
        return ChartOfAccount.objects.create(
            company=company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE,
            opening_balance=Decimal("0"),
        )


class BR2_EndpointsAreReachable(Phase0Base):
    """The permission resolver must return a real permission, and must not raise."""

    def test_the_complete_endpoint_resolves_a_permission(self):
        from weapi.django_rest.views.transactions.bank_reconcile import (
            PrivateWeReconcileTransactionsView,
        )

        resolved = _resolve_required_permissions(
            PrivateWeReconcileTransactionsView(), _Req("POST", self.user)
        )
        self.assertTrue(
            resolved,
            "POST /reconcile/complete resolves to no permission at all, so "
            "has_permission() fails closed and every non-admin user gets a 403 -- "
            "which is where the entire zero-difference guard currently lives",
        )

    def test_the_summary_endpoint_does_not_raise(self):
        from weapi.django_rest.views.transactions.bank_reconcile import (
            PrivateWeBankReconciliationSummaryView,
        )

        try:
            resolved = _resolve_required_permissions(
                PrivateWeBankReconciliationSummaryView(), _Req("GET", self.user)
            )
        except AttributeError as exc:
            self.fail(
                f"GET /reconcile/summary/<uid>/ raises inside the permission check "
                f"({exc}), so it 500s before the view body runs for every user who "
                f"is not a superuser or is_admin"
            )
        self.assertTrue(resolved, "the summary endpoint resolves to no permission")


class BR3_SessionCannotBeBornClosed(Phase0Base):
    def test_status_is_read_only(self):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            BankReconciliationListCreateSerializer as S,
        )

        fields = S().get_fields()
        self.assertIn("status", fields)
        self.assertTrue(
            fields["status"].read_only,
            "a client can POST status=CLOSED and get a closed reconciliation that "
            "never passed the difference gate -- no reason, no discrepancy posting",
        )

    def test_beginning_balance_is_read_only(self):
        """BR-4, closed by Phase 3 on 2026-08-25.

        This test used to assert the opposite. It was written in Phase 0 to pin
        `beginning_balance` as writable and make changing that a conscious act
        rather than a silent one, with the note that the frontend question was
        still open. Phase 3 answered it: the 2026-08-25 cleanup left zero
        reconciliations, so no live form posts the field, and it is now derived
        from the prior closed session.

        The flip is the whole point of having pinned it -- so the assertion is
        inverted rather than deleted.
        """
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            BankReconciliationListCreateSerializer as S,
        )

        self.assertTrue(
            S().get_fields()["beginning_balance"].read_only,
            "a client can still type the beginning balance, which makes the "
            "difference a formula with a free variable on both sides",
        )


class BR7_TransactionViewSetIsGuarded(Phase0Base):
    SERVER_OWNED = ("is_matched", "journal_entry", "matched_rule")

    def _serializer(self):
        from weapi.django_rest.serializers.transactions.pdf_transactions import (
            PrivateTransactionInformationSerializer as S,
        )

        return S()

    def test_server_owned_fields_are_read_only(self):
        fields = self._serializer().get_fields()
        writable = [f for f in self.SERVER_OWNED
                    if f in fields and not fields[f].read_only]
        self.assertEqual(
            writable, [],
            f"{writable} are PATCH-writable on /transactions/<pk>/, so a client can "
            f"tick lines directly and then close a reconciliation with an empty "
            f"transaction_ids list",
        )

    def test_the_viewset_carries_a_company_permission(self):
        from weapi.django_rest.views.transactions.pdf_transactions import (
            TransactionInformationViewSet,
        )

        names = [c.__name__ for c in TransactionInformationViewSet.permission_classes]
        self.assertIn(
            "HasCompanyPermission", names,
            f"the viewset's permission_classes are {names} -- every sibling view in "
            f"this module declares HaveSubscription + IsGroupPermission",
        )

    def test_chart_of_account_is_company_scoped(self):
        mine = self._account(self.company, "Mine", "1000")
        theirs = self._account(self.other, "Theirs", "1000")
        from weapi.django_rest.serializers.transactions.pdf_transactions import (
            PrivateTransactionInformationSerializer as S,
        )

        # `.fields`, not `get_fields()`: the scoping mixin narrows the querysets
        # on the built field map in __init__, and get_fields() rebuilds from
        # scratch -- reading it would test the unscoped class definition and pass
        # or fail for the wrong reason.
        s = S(context={"request": _Req("POST", self.user)})
        qs = s.fields["chart_of_account"].queryset
        uids = set(qs.values_list("uid", flat=True))
        self.assertIn(mine.uid, uids)
        self.assertNotIn(
            theirs.uid, uids,
            "chart_of_account resolves against every company's accounts",
        )


class BR8_DeclaredFieldsAreActuallyReadOnly(Phase0Base):
    def test_declared_read_only_fields_take_effect(self):
        from weapi.django_rest.serializers.transactions.csv_transactions import (
            TransactionWrapperSerializer as S,
        )

        fields = S().get_fields()
        declared = getattr(S.Meta, "read_only_fields", [])
        violations = {f: fields[f].read_only for f in declared
                      if f in fields and not fields[f].read_only}
        self.assertEqual(
            violations, {},
            f"{sorted(violations)} are listed in read_only_fields but are still "
            f"writable: DRF short-circuits explicitly declared fields before "
            f"extra_kwargs, so the list never reaches them",
        )


class BR10_DepositMoneyLegsAreScoped(Phase0Base):
    def test_bank_and_cashback_accounts_are_company_scoped(self):
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer as S,
        )

        mine = self._account(self.company, "Ops", "1010")
        theirs = self._account(self.other, "Their Ops", "1010")
        s = S(context={"request": _Req("POST", self.user)})
        fields = s.fields  # see the note in BR7 -- get_fields() bypasses the mixin
        for name in ("bank_chart_of_account_uid", "cash_back_account_uid"):
            uids = set(fields[name].queryset.values_list("uid", flat=True))
            self.assertIn(mine.uid, uids, f"{name} lost its own company's accounts")
            self.assertNotIn(
                theirs.uid, uids,
                f"{name} resolves against another tenant's chart of accounts, and "
                f"create() calls update_opening_balance on whatever it returns",
            )


class BR9_RuleChildrenAreScoped(Phase0Base):
    """A rule's params and assignment may only be rewritten through their own rule."""

    def _rule(self, company, title="R"):
        from transactionio.models import TransactionRuleParams, TransactionRules

        rule = TransactionRules.objects.create(
            company=company, title=title, transaction_type="DEPOSIT"
        )
        param = TransactionRuleParams.objects.create(
            rule=rule, field="DESCRIPTION", operation="CONTAINS", value="theirs"
        )
        return rule, param

    def test_another_tenants_param_is_not_resolved(self):
        from transactionio.models import TransactionRuleParams

        from weapi.django_rest.serializers.transactions.rules import (
            TransactionRuleCreateSerializer,
        )

        mine, _ = self._rule(self.company, "Mine")
        _, theirs = self._rule(self.other, "Theirs")

        s = TransactionRuleCreateSerializer()
        resolved = s.create_or_update(
            TransactionRuleParams, mine,
            {"uid": str(theirs.uid), "field": "DESCRIPTION",
             "operation": "CONTAINS", "value": "hijacked"},
        )

        theirs.refresh_from_db()
        self.assertEqual(
            theirs.value, "theirs",
            "another tenant's rule param was rewritten by uid -- their bank "
            "feed now categorises against a rule they did not write",
        )
        self.assertNotEqual(resolved.pk, theirs.pk)
        self.assertEqual(
            resolved.rule_id, mine.pk,
            "the fallback create must attach to the caller's own rule",
        )
