"""The P1 items left outside Phase 6. BR-23, BR-24, BR-25.

None is in the reconciliation engine; they are the rest of the module's
surface -- the deposit serializer, the Plaid demo, and the rule-assign
serializer.
"""

from decimal import Decimal

from django.test import TestCase

from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount, User

from companyio.models import Company, CompanyUser


class _Req:
    def __init__(self, user):
        self.user = user


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Remaining Co")
        cls.other = Company.objects.create(name="Someone Else")
        cls.user = User.objects.create_user(
            name="R", email="remaining@example.com", password="pass1234!"
        )
        CompanyUser.objects.create(user=cls.user, company=cls.company)

    def account(self, company, title, code):
        return ChartOfAccount.objects.create(
            company=company, title=title, code=code,
            kind=ChartOfAccountKindChoices.ASSETS,
            status=ChartOfAccountStatusChoices.ACTIVE, opening_balance=Decimal("0"),
        )


class BR23_DepositStatusTests(Base):
    """`BankDeposit.status` was client-writable with no update or delete path.

    A deposit could be POSTed straight to COMPLETED or CANCELLED, skipping
    whatever the status is supposed to mean -- and since nothing else can change
    it afterwards, the value a client chose at creation is the value it keeps.
    """

    def test_status_is_read_only(self):
        from weapi.django_rest.serializers.transactions.bank_deposits import (
            PrivateWeBankDepositListCreateSerializer as S,
        )

        fields = S(context={"request": _Req(self.user)}).fields
        self.assertIn("status", fields)
        self.assertTrue(
            fields["status"].read_only,
            "a client can choose the status a deposit is created in, and no "
            "path exists to change it afterwards",
        )


class BR24_PlaidDemoTests(TestCase):
    """The demo surface: unauthenticated, and pointing at nothing."""

    def test_the_unauthenticated_demo_route_is_gone(self):
        from django.urls import get_resolver

        routes = []

        def walk(patterns, prefix=""):
            for p in patterns:
                if hasattr(p, "url_patterns"):
                    walk(p.url_patterns, prefix + str(p.pattern))
                else:
                    routes.append(prefix + str(p.pattern))

        walk(get_resolver().url_patterns)
        demo = [r for r in routes if "plaid-test" in r]
        self.assertEqual(
            demo, [],
            f"the unauthenticated Plaid demo page is still routed at {demo}. It "
            f"renders a template that fetches /create_link_token and "
            f"/exchange_public_token at the root, neither of which is routed, "
            f"so it cannot work -- it is an open door onto nothing",
        )

    def test_the_plaid_environment_is_not_hardcoded_to_production(self):
        import inspect

        from weapi.django_rest.views.transactions import pdf_transactions

        source = inspect.getsource(pdf_transactions)
        pinned = "PLAID_ENV = plaid.Environment.Production" in source
        self.assertFalse(
            pinned,
            "the Plaid host is pinned to Production in source, so every "
            "environment that sets PLAID_CLIENT_ID talks to the real thing",
        )


class BR25_NestedMixinTests(Base):
    """`CompanyScopedRelatedFieldsMixin` is inert on a nested serializer.

    The mixin narrows querysets in `__init__`. A nested serializer is
    instantiated at class-definition time, when there is no request and
    therefore no company, so `company_scoped` returns the queryset untouched and
    the mixin does nothing at all.

    The same shape as `.fields` versus `get_fields()`: the scoping happens once,
    somewhere that does not see the request.
    """

    def test_the_nested_assign_serializer_is_scoped(self):
        from weapi.django_rest.serializers.transactions.rules import (
            TransactionRuleCreateSerializer,
        )

        mine = self.account(self.company, "Mine", "1000")
        theirs = self.account(self.other, "Theirs", "1000")

        parent = TransactionRuleCreateSerializer(
            context={"request": _Req(self.user)}
        )
        assign = parent.fields["assign"]
        uids = set(
            assign.fields["chart_of_account"].queryset.values_list("uid", flat=True)
        )
        self.assertIn(mine.uid, uids)
        self.assertNotIn(
            theirs.uid, uids,
            "the nested rule-assign serializer resolves another tenant's "
            "accounts -- the mixin ran before the request existed",
        )


class BR26_AuditCoverageTests(TestCase):
    """BR-26. Field-level history on the banking models.

    Asserted against the app registry, not a hardcoded list, so a model added to
    `transactionio` later fails this until somebody decides. A test naming eight
    known models would stay green through exactly the omission that left the app
    at 0/8 while every peer was at 100%.
    """

    def test_every_transactionio_model_is_registered(self):
        from auditlog.registry import auditlog
        from django.apps import apps

        registered = {m.__name__ for m in auditlog.get_models()}
        missing = [
            m.__name__
            for m in apps.get_app_config("transactionio").get_models()
            if m.__name__ not in registered
        ]
        self.assertEqual(
            missing, [],
            f"these banking models have no field-level audit: {missing}. Every "
            f"comparable app registers its whole surface -- journalio 2/2, "
            f"salesio 6/6, purchaseio 9/9 -- and this app holds reconciliation "
            f"sessions and statement lines",
        )

    def test_the_peer_apps_are_still_fully_covered(self):
        """If a peer drops below 100%, the argument above stops holding."""
        from auditlog.registry import auditlog
        from django.apps import apps

        registered = {m.__name__ for m in auditlog.get_models()}
        gaps = {}
        for label in ("journalio", "salesio", "purchaseio", "accounts", "customerio"):
            names = [m.__name__ for m in apps.get_app_config(label).get_models()]
            missing = [n for n in names if n not in registered]
            if missing:
                gaps[label] = missing
        self.assertEqual(gaps, {}, f"peer apps are no longer fully audited: {gaps}")


class AdminSearchTests(TestCase):
    """Every admin search must resolve, because a search term is `icontains`.

    A `search_fields` entry naming a field that does not exist, or naming a
    ForeignKey rather than a column on the far side of one, is a `FieldError` --
    a 500 on every query typed into that changelist, and invisible until
    somebody types one.

    This matters more here than it looks: the Django admin stands in for a
    database GUI in this project (see `15c78456`), so a broken search is a
    broken tool rather than a cosmetic fault.
    """

    def test_every_transactionio_admin_search_resolves(self):
        from django.contrib import admin as dj

        broken = []
        for model, model_admin in dj.site._registry.items():
            if model._meta.app_label != "transactionio":
                continue
            if not getattr(model_admin, "search_fields", None):
                continue
            try:
                queryset, _ = model_admin.get_search_results(
                    None, model.objects.all(), "x"
                )
                str(queryset.query)
            except Exception as exc:
                broken.append(
                    f"{model.__name__}: {list(model_admin.search_fields)} "
                    f"-> {type(exc).__name__}"
                )
        self.assertEqual(broken, [], "admin searches that 500:\n  " + "\n  ".join(broken))
