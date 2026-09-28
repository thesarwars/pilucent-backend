"""Every delete guard could be walked around with a PATCH.

`perform_destroy` is where the reconciliation check, the per-document refusals,
the ledger reversal, the inventory restore and the allocation unwind all live.
None of it runs on a `PATCH` — and `status` is in `fields` on all six detail
serializers and in `read_only_fields` on none of them.

So `PATCH {"status": "REMOVED"}` retired the document by writing the column
directly. It vanished from every list while its legs stayed PUBLISHED and its
balances stayed moved, which is the exact defect those delete paths were written
to fix. The guards shipped in §2 and §3 were not protecting anything a client
could not simply route around.

The tracking document found this on two endpoints. It is all six.
"""

from decimal import Decimal

from django.test import TestCase

from common.django_rest.helpers.retire_guard import (
    RETIRED,
    RetireViaPatchRefused,
    assert_not_retiring_by_patch,
)


class Doc:
    def __init__(self, status):
        self.status = status


class TheGuardRefusesTheTransitionTests(TestCase):
    def test_a_patch_to_removed_is_refused(self):
        with self.assertRaises(RetireViaPatchRefused) as caught:
            assert_not_retiring_by_patch(
                Doc("OPEN"), {"status": "REMOVED"}, document="bill"
            )

        detail = str(caught.exception)
        self.assertIn("DELETE", detail)
        self.assertIn("bill", detail)

    def test_the_error_carries_a_machine_readable_code(self):
        with self.assertRaises(RetireViaPatchRefused) as caught:
            assert_not_retiring_by_patch(
                Doc("OPEN"), {"status": "REMOVED"}, document="sale"
            )
        self.assertIn("RETIRE-VIA-DELETE", str(caught.exception))

    def test_every_other_status_change_is_untouched(self):
        for status in ("OPEN", "PAID", "CLOSED", "DRAFT", "PENDING"):
            assert_not_retiring_by_patch(
                Doc("DRAFT"), {"status": status}, document="bill"
            )

    def test_a_payload_with_no_status_is_untouched(self):
        assert_not_retiring_by_patch(Doc("OPEN"), {"total": "5"}, document="bill")

    def test_echoing_an_already_removed_status_back_is_not_an_error(self):
        """A client replaying a GET payload is not trying to retire anything."""
        assert_not_retiring_by_patch(
            Doc("REMOVED"), {"status": "REMOVED"}, document="bill"
        )

    def test_the_comparison_is_case_insensitive(self):
        with self.assertRaises(RetireViaPatchRefused):
            assert_not_retiring_by_patch(
                Doc("OPEN"), {"status": "removed"}, document="bill"
            )

    def test_the_retired_value_is_the_one_every_enum_uses(self):
        """One helper covers six documents only because they all agree."""
        from creditnoteio.choices import CreditNoteStatusChoices
        from purchaseio.choices import PurchasePaymentStatusChoices, PurchaseStatus
        from salesio.choices import (
            SalePaymentReceiveStatusChoices,
            SalesStatusChoices,
        )
        from stockio.choices import StockAdjustmentStatusChoices

        for choices in (
            PurchaseStatus, PurchasePaymentStatusChoices, CreditNoteStatusChoices,
            StockAdjustmentStatusChoices, SalesStatusChoices,
            SalePaymentReceiveStatusChoices,
        ):
            self.assertEqual(choices.REMOVED, RETIRED)


class EverySerializerCarriesItTests(TestCase):
    """If a seventh document gets a guarded delete, it belongs on this list."""

    def test_all_six_detail_serializers_call_the_guard(self):
        import inspect

        from weapi.django_rest.serializers.creditnotes import (
            PrivateWeCreditNoteDetailsSerializer,
        )
        from weapi.django_rest.serializers.purchases import (
            PrivateWePurchaseDetailsSerializer,
            PrivateWePurchasePaymentDetailsSerializer,
        )
        from weapi.django_rest.serializers.sales import (
            PrivateWeSaleDetailsSerializer,
            PrivateWeSalePaymentReceiveDetailsSerializer,
        )
        from weapi.django_rest.serializers.stock import (
            PrivateWeStockAdjustmentDetailSerializer,
        )

        for serializer in (
            PrivateWePurchaseDetailsSerializer,
            PrivateWePurchasePaymentDetailsSerializer,
            PrivateWeCreditNoteDetailsSerializer,
            PrivateWeStockAdjustmentDetailSerializer,
            PrivateWeSaleDetailsSerializer,
            PrivateWeSalePaymentReceiveDetailsSerializer,
        ):
            source = inspect.getsource(serializer.update)
            self.assertIn(
                "assert_not_retiring_by_patch", source,
                f"{serializer.__name__}.update does not refuse a retiring PATCH",
            )
