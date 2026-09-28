"""Related fields and manual lookups, narrowed to the requesting company.

`CompanyScopedRelatedFieldsMixin` has existed since the supplier work and closes
this for DECLARED serializer fields. It cannot reach two other shapes, and both
were open across the ledger serializers:

* **Classes that simply never got the mixin.** Fourteen of them declared
  `queryset=Model.objects.all()` on a writable related field, so any tenant's uid
  validated.
* **Manual lookups inside `create()`/`update()`.** A `JSONField` is not a related
  field, so the mixin walks straight past it in `get_fields` — present in the
  class declaration and inert for exactly the field that needed it. Those
  resolve through `get_object_or_404(Model.objects.filter(uid=...))` and are now
  wrapped in `company_scoped`.

**This is defence in depth, not the only control.** Eleven tables carry a
row-level-security policy (`companyio` migrations 0023, 0025, 0026) and
`TenantContextMiddleware` sets `app.company_id` per request, so on Postgres the
database already refuses a cross-tenant row. But RLS is bypassed by a superuser
role, its GUC set fails open, and SQLite has none — so the codebase's stated
policy is two layers covering each other, and this is the second one.

The structural tests below matter more than the behavioural one: a new serializer
that forgets the mixin is the way this comes back.
"""

import inspect
import re
from pathlib import Path

from django.test import TestCase


SCOPED_CLASSES = {
    "weapi/django_rest/serializers/creditnotes.py": [
        "PrivateCreditNoteItemListSerializer",
        "PrivateCreditNoteItemDetailsSerializer",
    ],
    "weapi/django_rest/serializers/purchases.py": [
        "PrivateWePurchaseDetailsSerializer",
        "PrivateWePurchaseItemListSerializer",
        "PrivateWePurchaseItemDetailsSerializer",
        "PrivateWePurchasePaymentItemListSerializer",
        "PrivateWePurchasePaymentItemsDetailsSerializer",
    ],
    "weapi/django_rest/serializers/sales.py": [
        "PrivateWeSaleListSerializer",
        "PrivateWeSaleDetailsSerializer",
        "PrivateWeSalePaymentReceiveListSerializer",
        "PrivateWeSalePaymentReceiveDetailsSerializer",
        "PrivateWeSaleSettingDetailsSerializer",
        "PrivateWeSalesTaxListCreateSerializer",
    ],
    "weapi/django_rest/serializers/stock.py": [
        "PrivateWeStockAdjustmentSerializer",
        "PrivateWeStockAdjustmentDetailSerializer",
    ],
}

# Manual lookups scoped by something narrower than the company, each with a
# reason. The list cannot quietly absorb a real miss.
ALLOWED_UNSCOPED = {
    # Scoped to its parent adjustment, which is already tenant-scoped by the
    # view's `get_object` — and which also blocks rewriting a different
    # adjustment of the same company. See `dfe958e7`.
    "stock.py": ["StockAdjustmentItem.objects.filter"],
}


class EveryFlaggedClassCarriesTheMixinTests(TestCase):
    """A new serializer that forgets it is how this comes back."""

    def test_all_fourteen_declare_the_mixin(self):
        missing = []
        for path, classes in SCOPED_CLASSES.items():
            source = Path(path).read_text()
            for cls in classes:
                match = re.search(r"^class %s\(([^)]*)\):" % re.escape(cls), source, re.M)
                if match is None:
                    missing.append(f"{cls} no longer exists in {path}")
                elif "CompanyScopedRelatedFieldsMixin" not in match.group(1):
                    missing.append(f"{cls} in {path}")
        self.assertEqual(
            missing, [],
            "these declare writable related fields with a global queryset and "
            "no company scoping:\n  " + "\n  ".join(missing),
        )

    def test_the_mixin_comes_before_the_serializer_base(self):
        """MRO order is load-bearing — `get_fields` must resolve to the mixin."""
        for path, classes in SCOPED_CLASSES.items():
            source = Path(path).read_text()
            for cls in classes:
                bases = re.search(
                    r"^class %s\(([^)]*)\):" % re.escape(cls), source, re.M
                ).group(1)
                names = [b.strip() for b in bases.split(",")]
                self.assertLess(
                    names.index("CompanyScopedRelatedFieldsMixin"),
                    max(i for i, n in enumerate(names) if "Serializer" in n),
                    f"{cls} must mix in ahead of its serializer base",
                )


class NoManualLookupResolvesByUidAloneTests(TestCase):
    """The shape the mixin cannot reach, swept for directly."""

    def unscoped(self):
        found = []
        for path in sorted(Path("weapi/django_rest/serializers").glob("*.py")):
            source = path.read_text()
            for match in re.finditer(
                r"get_object_or_404\(\s*([\s\S]{0,300}?)\n\s*\)", source
            ):
                block = match.group(1)
                if "uid=" not in block:
                    continue
                if "company" in block:  # covers company= and company_scoped(
                    continue
                allowed = ALLOWED_UNSCOPED.get(path.name, [])
                if any(prefix in block for prefix in allowed):
                    continue
                found.append(
                    f"{path.name}:{source[: match.start()].count(chr(10)) + 1}"
                    f"  {' '.join(block.split())[:70]}"
                )
        return found

    def test_none_remain(self):
        self.assertEqual(
            self.unscoped(), [],
            "these resolve a record by uid with no tenant filter:\n  "
            + "\n  ".join(self.unscoped()),
        )

    def test_the_sweep_can_still_see_call_sites(self):
        """Guards the guard: a broken regex would pass the test above silently."""
        source = Path("weapi/django_rest/serializers/sales.py").read_text()
        self.assertIn("get_object_or_404(", source)
        self.assertGreater(
            len(re.findall(r"get_object_or_404\(", source)), 3,
            "the sweep should be finding several call sites in this file",
        )


class TheHelperRefusesToGuessTests(TestCase):
    """`company_scoped`'s own contract, since 31 sites now depend on it."""

    def test_it_returns_the_queryset_untouched_without_a_request(self):
        from common.django_rest.helpers.serializer_scoping import company_scoped
        from productio.models import Product

        class NoContext:
            context = {}

        queryset = Product.objects.all()
        self.assertIs(company_scoped(queryset, NoContext()), queryset)

    def test_it_returns_the_queryset_untouched_when_the_model_has_no_company(self):
        """`StockAdjustmentItem` has none — the helper must not invent one."""
        from common.django_rest.helpers.serializer_scoping import company_scoped
        from stockio.models import StockAdjustmentItem

        class NoContext:
            context = {}

        queryset = StockAdjustmentItem.objects.all()
        self.assertIs(company_scoped(queryset, NoContext()), queryset)
