"""DB-backed tests for the template write serializer.

Exercises validation, nested-line persistence, cached-total recomputation, and
first Next Date seeding through the real serializer (auth stack stubbed).
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from accounts.models import ChartOfAccount
from companyio.models import Company
from customerio.models import Customer
from paymentio.models import PaymentMethod
from productio.models import Product
from supplierio.models import Supplier
from termio.models import Term
from wirehouseio.models import Warehouse

from recurringio.choices import (
    RecurringEndTypeChoices,
    RecurringTemplateTypeChoices,
)
from recurringio.models import RecurringTemplate
from weapi.django_rest.serializers.recurring_transactions import (
    PrivateWeRecurringTemplateSerializer,
)


class _FakeUser:
    def __init__(self, company):
        self._company = company

    def get_active_company(self):
        return self._company

    def get_employee(self):
        return None


class TemplateSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="Landlord", display_name="Landlord LLC", company=cls.company
        )
        cls.account = ChartOfAccount.objects.create(
            code="6000", title="Rent Expense", company=cls.company
        )
        cls.customer = Customer.objects.create(
            first_name="Acme", display_name="Acme Corp", company=cls.company
        )
        # A BILL needs both: terms derive the due date, the store locates stock.
        cls.term = Term.objects.create(title="Net 15", days=15, company=cls.company)
        cls.warehouse = Warehouse.objects.create(
            title="Main Store", company=cls.company
        )
        # An expense needs an ACTIVE payment method (model default is DRAFT).
        cls.payment_method = PaymentMethod.objects.create(
            title="Card", company=cls.company, status="ACTIVE",
        )
        # Sales-side types are product-only.
        cls.product = Product.objects.create(
            title="Consulting", sku="CON-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _base_payload(self, **overrides):
        payload = {
            "name": "Monthly Rent",
            "txn_type": "BILL",
            "template_type": RecurringTemplateTypeChoices.SCHEDULED,
            "currency_code": "USD",
            "supplier": str(self.supplier.uid),
            "terms": str(self.term.uid),
            "warehouse": str(self.warehouse.uid),
            "frequency": "MONTHLY",
            "interval_count": 1,
            "day_mode": "DAY_OF_MONTH",
            "day_of_month": 1,
            "start_date": "2026-01-01",
            "end_type": RecurringEndTypeChoices.NONE,
            "lines": [
                {
                    "line_type": "CATEGORY",
                    "amount": "1000.00",
                    "charter_account": str(self.account.uid),
                    "description": "Office rent",
                }
            ],
        }
        payload.update(overrides)
        return payload

    def _save(self, payload):
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_create_persists_lines_total_and_next_date(self):
        template = self._save(self._base_payload())

        self.assertEqual(template.company, self.company)
        self.assertEqual(template.lines.count(), 1)
        self.assertEqual(template.total_amount, Decimal("1000.000"))
        # First occurrence on/after the 2026-01-01 start on day-of-month 1.
        self.assertEqual(template.next_run_date, date(2026, 1, 1))

    def test_unscheduled_has_no_next_date(self):
        payload = self._base_payload(
            template_type=RecurringTemplateTypeChoices.UNSCHEDULED,
        )
        payload.pop("frequency")
        payload.pop("start_date")
        template = self._save(payload)
        self.assertIsNone(template.next_run_date)

    def test_scheduled_requires_frequency(self):
        payload = self._base_payload()
        payload.pop("frequency")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("frequency", serializer.errors)

    def test_by_date_end_requires_end_date(self):
        payload = self._base_payload(end_type=RecurringEndTypeChoices.BY_DATE)
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("end_date", serializer.errors)

    def test_category_line_requires_account(self):
        payload = self._base_payload(
            lines=[{"line_type": "CATEGORY", "amount": "10.00"}]
        )
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_empty_lines_rejected(self):
        payload = self._base_payload(lines=[])
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_expense_requires_payment_account(self):
        payload = self._base_payload(txn_type="EXPENSE")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_account", serializer.errors)

    def test_expense_with_payment_account_persists(self):
        payload = self._base_payload(
            txn_type="EXPENSE",
            payment_account=str(self.account.uid),
            payment_method=str(self.payment_method.uid),
        )
        template = self._save(payload)
        self.assertEqual(template.txn_type, "EXPENSE")
        self.assertEqual(template.payment_account, self.account)

    def _expense_payload(self, **overrides):
        defaults = dict(
            txn_type="EXPENSE",
            payment_account=str(self.account.uid),
            payment_method=str(self.payment_method.uid),
        )
        defaults.update(overrides)
        return self._base_payload(**defaults)

    def test_expense_requires_a_payment_method(self):
        # The real expense screen hard-requires one, so a template without it
        # cannot produce a valid expense.
        payload = self._expense_payload()
        payload.pop("payment_method")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_method", serializer.errors)

    def test_expense_rejects_an_inactive_payment_method(self):
        # The model default is DRAFT, so this is the common case, not an edge one.
        draft = PaymentMethod.objects.create(title="Old card", company=self.company)
        serializer = PrivateWeRecurringTemplateSerializer(
            data=self._expense_payload(payment_method=str(draft.uid)),
            context=self._context(),
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_method", serializer.errors)

    def test_expense_accepts_a_credit_card_account(self):
        from categoryio.models import Category

        card = ChartOfAccount.objects.create(
            code="2100", title="Company Card", company=self.company,
            account_type=Category.objects.create(
                title="Credit Card", company=self.company
            ),
        )
        template = self._save(self._expense_payload(payment_account=str(card.uid)))
        self.assertEqual(template.payment_account, card)

    def test_expense_rejects_a_non_settlement_account(self):
        from categoryio.models import Category

        expense_account = ChartOfAccount.objects.create(
            code="6100", title="Utilities", company=self.company,
            account_type=Category.objects.create(
                title="Expenses", company=self.company
            ),
        )
        serializer = PrivateWeRecurringTemplateSerializer(
            data=self._expense_payload(payment_account=str(expense_account.uid)),
            context=self._context(),
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_account", serializer.errors)

    def test_cheque_requires_bank_account(self):
        payload = self._base_payload(txn_type="CHEQUE")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_account", serializer.errors)

    def test_warehouse_and_payment_method_read_as_bare_uids(self):
        from paymentio.models import PaymentMethod
        from wirehouseio.models import Warehouse

        warehouse = Warehouse.objects.create(title="Main WH", company=self.company)
        method = PaymentMethod.objects.create(
            title="Wire", company=self.company, status="ACTIVE",
        )

        payload = self._base_payload(
            txn_type="EXPENSE",
            payment_account=str(self.account.uid),
            warehouse=str(warehouse.uid),        # written as uid strings...
            payment_method=str(method.uid),
        )
        template = self._save(payload)

        data = PrivateWeRecurringTemplateSerializer(
            template, context=self._context()
        ).data
        # ...and read back as BARE UIDS, never nested objects: the client feeds
        # these straight into `GET /we/warehouses/{uid}`, where an object would
        # 404 silently and the field would just fail to hydrate.
        self.assertEqual(str(data["warehouse"]), str(warehouse.uid))
        self.assertEqual(str(data["payment_method"]), str(method.uid))
        # Titles ride alongside so the client needn't re-fetch them.
        self.assertEqual(data["warehouse_title"], "Main WH")
        self.assertEqual(data["payment_method_title"], "Wire")

    def test_relation_titles_are_null_when_relation_unset(self):
        # A CHEQUE carries neither a warehouse nor a payment method (the cheque
        # IS the instrument); both keys must still be present and null.
        payload = self._base_payload(
            txn_type="CHEQUE", payment_account=str(self.account.uid)
        )
        payload.pop("terms")
        payload.pop("warehouse")
        template = self._save(payload)

        data = PrivateWeRecurringTemplateSerializer(
            template, context=self._context()
        ).data
        self.assertIsNone(data["warehouse"])
        self.assertIsNone(data["warehouse_title"])
        self.assertIsNone(data["payment_method"])
        self.assertIsNone(data["payment_method_title"])

    def test_bill_terms_and_warehouse_read_back_as_bare_uids_with_titles(self):
        template = self._save(self._base_payload())  # BILL
        data = PrivateWeRecurringTemplateSerializer(
            template, context=self._context()
        ).data

        self.assertEqual(str(data["terms"]), str(self.term.uid))
        self.assertEqual(str(data["warehouse"]), str(self.warehouse.uid))
        self.assertEqual(data["terms_title"], "Net 15")
        self.assertEqual(data["warehouse_title"], "Main Store")

    def test_bill_json_wire_contract(self):
        """§6.1: uids must reach the client as bare JSON *strings*.

        Asserted after real JSON rendering, not on ``.data`` — the client feeds
        `terms` / `warehouse` straight into a URL, so anything other than a
        string there breaks hydration.
        """
        import json

        from rest_framework.renderers import JSONRenderer

        template = self._save(self._base_payload(permit_number="TX-PRM-994120"))
        wire = json.loads(
            JSONRenderer().render(
                PrivateWeRecurringTemplateSerializer(
                    template, context=self._context()
                ).data
            )
        )

        for key in ("supplier", "terms", "warehouse"):
            self.assertIsInstance(wire[key], str, f"{key} must be a bare uid string")
        self.assertEqual(wire["terms"], str(self.term.uid))
        self.assertEqual(wire["warehouse"], str(self.warehouse.uid))
        # Denormalized names hydration needs (§6.1) + the round-tripped permit.
        self.assertEqual(wire["supplier_name"], "Landlord LLC")
        self.assertEqual(wire["permit_number"], "TX-PRM-994120")
        self.assertEqual(wire["lines"][0]["charter_account_title"], "Rent Expense")
        # Derived list-row fields (§8).
        self.assertIsNotNone(wire["total_amount"])
        self.assertIsNotNone(wire["next_run_date"])
        self.assertIsNotNone(wire["interval_display"])

    # ---- §11 range validation (all txn types) ----------------------------

    def _assert_rejects(self, field, **overrides):
        serializer = PrivateWeRecurringTemplateSerializer(
            data=self._base_payload(**overrides), context=self._context()
        )
        self.assertFalse(serializer.is_valid(), f"expected {field} to be rejected")
        self.assertIn(field, serializer.errors)

    def test_interval_count_must_be_at_least_one(self):
        # `Number(x) || 1` on the client lets 0 through.
        self._assert_rejects("interval_count", interval_count=0)

    def test_day_of_month_must_be_in_range(self):
        self._assert_rejects("day_of_month", day_of_month=0)
        self._assert_rejects("day_of_month", day_of_month=32)

    def test_weekday_must_be_in_range(self):
        self._assert_rejects("weekday", frequency="WEEKLY", weekday=7)

    def test_end_date_must_be_after_start_date(self):
        self._assert_rejects(
            "end_date",
            end_type=RecurringEndTypeChoices.BY_DATE,
            start_date="2026-01-01",
            end_date="2026-01-01",  # equal is not "after"
        )

    def test_end_after_occurrences_must_be_at_least_one(self):
        self._assert_rejects(
            "end_after_occurrences",
            end_type=RecurringEndTypeChoices.AFTER_COUNT,
            end_after_occurrences=0,
        )

    def test_reminder_defaults_are_still_accepted(self):
        # §3.2 quirk: a REMINDER template posts untouched MONTHLY defaults.
        # Only values are range-checked, never presence — this must NOT reject.
        template = self._save(
            self._base_payload(
                template_type=RecurringTemplateTypeChoices.REMINDER,
                remind_days_before=3,
            )
        )
        self.assertEqual(template.template_type, "REMINDER")

    # ---- cheque-specific --------------------------------------------------

    def test_cheque_rejects_a_non_bank_account(self):
        from categoryio.models import Category

        card = ChartOfAccount.objects.create(
            code="2100", title="Company Card", company=self.company,
            account_type=Category.objects.create(
                title="Credit Card", company=self.company
            ),
        )
        payload = self._base_payload(
            txn_type="CHEQUE", payment_account=str(card.uid)
        )
        payload.pop("terms")
        payload.pop("warehouse")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_account", serializer.errors)

    def test_cheque_accepts_an_account_with_no_type_set(self):
        # account_type is still nullable on legacy accounts — don't reject those.
        payload = self._base_payload(
            txn_type="CHEQUE", payment_account=str(self.account.uid),
            cheque_number="CHQ-004182", print_later=False,
        )
        payload.pop("terms")
        payload.pop("warehouse")
        template = self._save(payload)
        self.assertEqual(template.cheque_number, "CHQ-004182")
        self.assertFalse(template.print_later)

    def test_customer_uid_as_payee_gets_a_readable_error(self):
        payload = self._base_payload(supplier=str(self.customer.uid))
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("vendor", str(serializer.errors["supplier"]).lower())

    def test_bill_requires_terms(self):
        payload = self._base_payload()
        payload.pop("terms")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("terms", serializer.errors)

    def test_bill_requires_warehouse(self):
        payload = self._base_payload()
        payload.pop("warehouse")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("warehouse", serializer.errors)

    def test_non_bill_types_do_not_require_terms_or_warehouse(self):
        # Only BILL carries them; EXPENSE must still save without either.
        payload = self._base_payload(
            txn_type="EXPENSE", payment_account=str(self.account.uid),
            payment_method=str(self.payment_method.uid),
        )
        payload.pop("terms")
        payload.pop("warehouse")
        template = self._save(payload)
        self.assertIsNone(template.terms)
        self.assertIsNone(template.warehouse)

    def test_cheque_with_bank_account_persists(self):
        payload = self._base_payload(
            txn_type="CHEQUE",
            payment_account=str(self.account.uid),
            cheque_number="1005",
            print_later=True,
        )
        template = self._save(payload)
        self.assertEqual(template.txn_type, "CHEQUE")
        self.assertEqual(template.payment_account, self.account)
        self.assertTrue(template.print_later)
        self.assertEqual(template.cheque_number, "1005")

    def test_estimate_requires_customer(self):
        payload = self._base_payload(txn_type="ESTIMATE")
        payload.pop("supplier")  # estimates don't use a supplier
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("customer", serializer.errors)

    def _estimate_payload(self, **overrides):
        """An estimate is product-only and needs a store (spec §4, §12 Q2)."""
        defaults = dict(
            txn_type="ESTIMATE",
            customer=str(self.customer.uid),
            lines=[{
                "line_type": "ITEM", "product": str(self.product.uid),
                "quantity": "2", "rate": "50.00", "amount": "100.00",
            }],
        )
        defaults.update(overrides)
        payload = self._base_payload(**defaults)
        payload.pop("supplier")
        payload.pop("terms")  # estimates are non-posting: no terms
        return payload

    def test_estimate_rejects_category_lines(self):
        # The edit screen filters to ITEM on hydration, so a stored CATEGORY
        # line would silently vanish from the form.
        payload = self._estimate_payload()
        payload["lines"] = [{
            "line_type": "CATEGORY", "charter_account": str(self.account.uid),
            "amount": "100.00",
        }]
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_item_line_amount_is_recomputed_from_quantity_and_rate(self):
        # Client totals are advisory: the frontends compute with toFixed(3)
        # against a 2dp ledger, so a trusted client figure will not reconcile.
        template = self._save(self._estimate_payload(lines=[{
            "line_type": "ITEM", "product": str(self.product.uid),
            "quantity": "3", "rate": "10.00", "amount": "999.99",  # wrong
        }]))
        self.assertEqual(template.lines.get().amount, Decimal("30.000"))

    def test_category_line_amount_is_taken_as_given(self):
        # A category line has no quantity or rate to derive from.
        template = self._save(self._base_payload(lines=[{
            "line_type": "CATEGORY", "charter_account": str(self.account.uid),
            "amount": "42.50",
        }]))
        self.assertEqual(template.lines.get().amount, Decimal("42.500"))

    def test_expiry_days_round_trips(self):
        template = self._save(self._estimate_payload(expiry_days=30))
        self.assertEqual(template.expiry_days, 30)

    def test_estimate_requires_a_store(self):
        payload = self._estimate_payload()
        payload.pop("warehouse")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("warehouse", serializer.errors)

    def test_estimate_with_customer_persists(self):
        payload = self._estimate_payload(
            email_to="ap@acme.com",
            auto_email=True,
            message_on_estimate="Thanks for your business",
        )
        template = self._save(payload)
        self.assertEqual(template.txn_type, "ESTIMATE")
        self.assertEqual(template.customer, self.customer)
        self.assertIsNone(template.supplier)
        self.assertTrue(template.auto_email)
        self.assertEqual(template.email_to, "ap@acme.com")

    def test_money_out_still_requires_supplier(self):
        payload = self._base_payload()  # BILL
        payload.pop("supplier")
        serializer = PrivateWeRecurringTemplateSerializer(
            data=payload, context=self._context()
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("supplier", serializer.errors)

    def test_update_replaces_lines_and_recomputes_total(self):
        template = self._save(self._base_payload())

        update_payload = {
            "lines": [
                {
                    "line_type": "CATEGORY",
                    "amount": "1500.00",
                    "charter_account": str(self.account.uid),
                    "description": "New rent",
                },
                {
                    "line_type": "CATEGORY",
                    "amount": "250.00",
                    "charter_account": str(self.account.uid),
                    "description": "Parking",
                },
            ]
        }
        serializer = PrivateWeRecurringTemplateSerializer(
            instance=template,
            data=update_payload,
            partial=True,
            context=self._context(),
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        self.assertEqual(updated.lines.count(), 2)
        self.assertEqual(updated.total_amount, Decimal("1750.000"))


class RefundReceiptTemplateTests(TestCase):
    """REFUND_RECEIPT is one more txn_type: a customer-side, settled document."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="Dana", display_name="Northwind Co", company=cls.company
        )
        cls.refund_account = ChartOfAccount.objects.create(
            code="1010", title="Checking", company=cls.company
        )
        cls.product = Product.objects.create(
            title="Gold Plan", sku="GP-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly subscription refund",
            "txn_type": "REFUND_RECEIPT",
            "template_type": RecurringTemplateTypeChoices.UNSCHEDULED,
            "customer": str(self.customer.uid),
            # refund wire aliases (RECURRING_REFUND_RECEIPT_BACKEND.md §11)
            "refund_from": str(self.refund_account.uid),
            "customer_email": "dana@northwind.co",
            "cc_emails": "billing@northwind.co",
            "message_on_receipt": "Sorry to see you go.",
            "reference_number": "CHQ-004182",
            "tracking_number": "RR-2026-0091",
            "statement_memo": "BALANZIFY REFUND",
            "tax_kind": "EXCLUSIVE",
            "lines": [
                {"line_type": "ITEM", "product": str(self.product.uid),
                 "quantity": "1", "rate": "199.00", "amount": "199.00",
                 "description": "Gold plan refunded", "is_billable": False},
            ],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def test_create_maps_refund_aliases_to_model_fields(self):
        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()

        self.assertEqual(t.payment_account, self.refund_account)   # refund_from
        self.assertEqual(t.email_to, "dana@northwind.co")          # customer_email
        self.assertEqual(t.email_cc, "billing@northwind.co")
        self.assertEqual(t.message_on_estimate, "Sorry to see you go.")
        self.assertEqual(t.reference_number, "CHQ-004182")
        self.assertEqual(t.tracking_number, "RR-2026-0091")
        self.assertEqual(t.statement_memo, "BALANZIFY REFUND")
        self.assertEqual(t.tax_kind, "EXCLUSIVE")
        self.assertEqual(t.total_amount, Decimal("199.000"))

    def test_representation_echoes_refund_aliases(self):
        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()
        data = PrivateWeRecurringTemplateSerializer(t, context=self._context()).data
        self.assertEqual(str(data["refund_from"]), str(self.refund_account.uid))
        self.assertEqual(data["customer_email"], "dana@northwind.co")
        self.assertEqual(data["message_on_receipt"], "Sorry to see you go.")

    def test_requires_customer(self):
        s = self._serializer(customer=None)
        self.assertFalse(s.is_valid())
        self.assertIn("customer", s.errors)

    def test_requires_refund_from(self):
        payload = self._payload()
        payload.pop("refund_from")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("refund_from", s.errors)

    def test_rejects_category_line(self):
        s = self._serializer(lines=[{"line_type": "CATEGORY", "amount": "10.00",
                                     "charter_account": str(self.refund_account.uid)}])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_rejects_negative_amount(self):
        s = self._serializer(lines=[{"line_type": "ITEM", "product": str(self.product.uid),
                                     "quantity": "1", "rate": "10.00", "amount": "-10.00"}])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_rejects_negative_quantity(self):
        # A negative qty reaches update_quantity() at fire time and decrements
        # stock on a document that nominally adds it.
        s = self._serializer(lines=[{"line_type": "ITEM", "product": str(self.product.uid),
                                     "quantity": "-1", "rate": "10.00", "amount": "10.00"}])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_rejects_negative_rate(self):
        s = self._serializer(lines=[{"line_type": "ITEM", "product": str(self.product.uid),
                                     "quantity": "1", "rate": "-10.00", "amount": "10.00"}])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_list_party_name_is_customer(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()
        row = PrivateWeRecurringTemplateListSerializer(t).data
        self.assertEqual(row["party_name"], "Northwind Co")

    def test_firing_without_an_acting_user_fails_clearly(self):
        # The sale serializer reads user.get_employee() directly, and a refund
        # moves real money -- fail with a readable message, not AttributeError.
        from recurringio.services.generation import generate_from_template

        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()
        with self.assertRaises(ValueError) as ctx:
            generate_from_template(t, None, self.company)
        self.assertIn("user", str(ctx.exception).lower())


class PaymentTemplateTests(TestCase):
    """PAYMENT is a customer-side, product-only cash sale (spec §3)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="North", display_name="Northwind", company=cls.company
        )
        cls.deposit_to = ChartOfAccount.objects.create(
            code="1000", title="Undeposited Funds", company=cls.company
        )
        cls.method = PaymentMethod.objects.create(
            title="Card", company=cls.company, status="ACTIVE"
        )
        cls.product = Product.objects.create(
            title="Retainer", sku="RET-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly retainer",
            "txn_type": "PAYMENT",
            "template_type": "SCHEDULED",
            "customer": str(self.customer.uid),
            "deposit_to": str(self.deposit_to.uid),   # wire alias
            "payment_method": str(self.method.uid),
            "when_to_charge": "FUTURE",
            "internal_note": "hidden note",
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [{
                "line_type": "ITEM", "product": str(self.product.uid),
                "quantity": "1", "rate": "500.00", "amount": "500.00",
            }],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def test_payment_template_saves(self):
        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()
        self.assertEqual(t.txn_type, "PAYMENT")
        self.assertEqual(t.customer, self.customer)
        self.assertEqual(t.when_to_charge, "FUTURE")
        self.assertEqual(t.internal_note, "hidden note")

    def test_deposit_to_maps_onto_the_shared_settlement_account(self):
        s = self._serializer()
        s.is_valid(raise_exception=True)
        t = s.save()
        self.assertEqual(t.payment_account, self.deposit_to)

        data = PrivateWeRecurringTemplateSerializer(t, context=self._context()).data
        self.assertEqual(str(data["deposit_to"]), str(self.deposit_to.uid))
        self.assertEqual(data["deposit_to_title"], "Undeposited Funds")

    def test_payment_requires_a_deposit_account(self):
        payload = self._payload()
        payload.pop("deposit_to")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("deposit_to", s.errors)

    def test_payment_requires_a_customer_not_a_vendor(self):
        payload = self._payload()
        payload.pop("customer")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("customer", s.errors)

    def test_payment_rejects_category_lines(self):
        account = ChartOfAccount.objects.create(
            code="4000", title="Income", company=self.company
        )
        s = self._serializer(lines=[{
            "line_type": "CATEGORY", "charter_account": str(account.uid),
            "amount": "500.00",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_payment_row_shows_the_customer_as_party(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        s = self._serializer()
        s.is_valid(raise_exception=True)
        row = PrivateWeRecurringTemplateListSerializer(s.save()).data
        self.assertEqual(row["party_name"], "Northwind")


class InvoiceTemplateTests(TestCase):
    """INVOICE: customer-side, product-only, with real document money inputs."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="North", display_name="Northwind", company=cls.company
        )
        cls.term = Term.objects.create(title="Net 30", days=30, company=cls.company)
        cls.warehouse = Warehouse.objects.create(title="Main", company=cls.company)
        cls.deposit_to = ChartOfAccount.objects.create(
            code="1200", title="Accounts Receivable", company=cls.company
        )
        cls.service = Product.objects.create(
            title="Retainer", sku="RET-2", quantity=0, date=date(2026, 1, 1),
            kind="SERVICE", status="ACTIVE", company=cls.company,
        )
        cls.tracked = Product.objects.create(
            title="Widget", sku="WID-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company, is_inventory=True,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Acme monthly retainer",
            "txn_type": "INVOICE",
            "template_type": "SCHEDULED",
            "customer": str(self.customer.uid),
            "term": str(self.term.uid),          # wire name is singular
            "warehouse": "",                      # screen sends "" when unpicked
            "message_on_invoice": "Thank you for your business.",
            "payment_instructions": "Pay by ACH.",
            "include_unbilled_charges": True,
            "discount_kind": "PERCENTAGE",
            "discount": "150",
            "shipping_fee": "25",
            "deposit": "0",
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [{
                "line_type": "ITEM", "product": str(self.service.uid),
                "quantity": "2", "rate": "450", "amount": "900",
            }],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def _save(self, **overrides):
        s = self._serializer(**overrides)
        s.is_valid(raise_exception=True)
        return s.save()

    def test_invoice_template_saves_with_wire_aliases(self):
        t = self._save()
        self.assertEqual(t.txn_type, "INVOICE")
        self.assertEqual(t.terms, self.term)          # `term` -> terms
        self.assertIsNone(t.warehouse)                # "" -> null
        self.assertEqual(t.message_on_estimate, "Thank you for your business.")
        self.assertTrue(t.include_unbilled_charges)
        self.assertEqual(t.discount, Decimal("150"))
        self.assertEqual(t.shipping_fee, Decimal("25"))

    def test_total_amount_includes_shipping_minus_discount(self):
        t = self._save()
        # 900 (lines) + 0 tax + 25 shipping - 150 discount
        self.assertEqual(t.total_amount, Decimal("775.000"))

    def test_read_echoes_the_invoice_wire_names(self):
        data = PrivateWeRecurringTemplateSerializer(
            self._save(), context=self._context()
        ).data
        self.assertEqual(str(data["term"]), str(self.term.uid))
        self.assertEqual(data["term_title"], "Net 30")
        self.assertEqual(data["term_days"], 30)
        self.assertEqual(data["message_on_invoice"], "Thank you for your business.")

    def test_deposit_requires_a_deposit_account(self):
        s = self._serializer(deposit="100")
        self.assertFalse(s.is_valid())
        self.assertIn("deposit_to", s.errors)

    def test_deposit_with_account_saves(self):
        t = self._save(deposit="100", deposit_to=str(self.deposit_to.uid))
        self.assertEqual(t.deposit, Decimal("100"))
        self.assertEqual(t.payment_account, self.deposit_to)

    def test_discount_cannot_exceed_the_subtotal(self):
        s = self._serializer(discount="901")
        self.assertFalse(s.is_valid())
        self.assertIn("discount", s.errors)

    def test_inventory_product_requires_a_store(self):
        s = self._serializer(discount="0", lines=[{
            "line_type": "ITEM", "product": str(self.tracked.uid),
            "quantity": "1", "rate": "80", "amount": "80",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("warehouse", s.errors)

    def test_inventory_product_with_a_store_saves(self):
        t = self._save(
            warehouse=str(self.warehouse.uid),
            discount="0",
            lines=[{
                "line_type": "ITEM", "product": str(self.tracked.uid),
                "quantity": "1", "rate": "80", "amount": "80",
            }],
        )
        self.assertEqual(t.warehouse, self.warehouse)

    def test_services_only_invoice_saves_without_a_store(self):
        # Deliberately looser than BILL/ESTIMATE: matches the real invoice
        # screen, which only requires a store for inventory-tracked products.
        t = self._save()
        self.assertIsNone(t.warehouse)

    def test_invoice_rejects_category_lines(self):
        account = ChartOfAccount.objects.create(
            code="4000", title="Income", company=self.company
        )
        s = self._serializer(lines=[{
            "line_type": "CATEGORY", "charter_account": str(account.uid),
            "amount": "900",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_tax_companions_round_trip(self):
        from agencyio.models import AgencyTax

        tax = AgencyTax.objects.create(
            title="NY combined", total_rate=8.875, company=self.company
        )
        data = PrivateWeRecurringTemplateSerializer(
            self._save(tax=str(tax.uid)), context=self._context()
        ).data
        self.assertEqual(data["tax_title"], "NY combined")
        self.assertEqual(data["tax_rate"], 8.875)


class PurchaseOrderTemplateTests(TestCase):
    """PURCHASE_ORDER is BILL plus shipping plus email (spec §1)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="Pack", display_name="PackRight Co", company=cls.company
        )
        cls.ship_to = Customer.objects.create(
            first_name="Dock", display_name="Dock 4", company=cls.company
        )
        cls.account = ChartOfAccount.objects.create(
            code="6100", title="Freight", company=cls.company
        )
        cls.warehouse = Warehouse.objects.create(title="Main", company=cls.company)
        cls.product = Product.objects.create(
            title="Boxes", sku="BOX-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly packaging restock",
            "txn_type": "PURCHASE_ORDER",
            "template_type": "SCHEDULED",
            "supplier": str(self.supplier.uid),
            "mailing_address": "48 Industrial Pkwy Round Rock TX",
            "ship_to": str(self.ship_to.uid),
            "full_shipping_address": "Balanzify Inc\n12 Main St\nAustin TX 73301",
            "shipping_by": "FedEx",
            "warehouse": str(self.warehouse.uid),
            "permit_number": "TX-RS-884120",
            "email": "orders@packrightco.com",
            "cc_emails": "ap@balanzify.com,ops@balanzify.com",
            "bcc_emails": "audit@balanzify.com",
            "tax_kind": "EXCLUSIVE",
            "memo": "Deliver to the loading dock.",
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [
                {"line_type": "CATEGORY", "charter_account": str(self.account.uid),
                 "amount": "125.5", "description": "Inbound freight", "position": 0},
                {"line_type": "ITEM", "product": str(self.product.uid),
                 "quantity": "24", "rate": "18.75", "amount": "450"},
            ],
        }
        payload.update(overrides)
        return payload

    def _save(self, **overrides):
        s = PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )
        s.is_valid(raise_exception=True)
        return s.save()

    def test_purchase_order_saves_with_shipping_and_email(self):
        t = self._save()
        self.assertEqual(t.txn_type, "PURCHASE_ORDER")
        self.assertEqual(t.supplier, self.supplier)
        self.assertEqual(t.ship_to, self.ship_to)
        self.assertEqual(t.shipping_by, "FedEx")
        self.assertIn("\n", t.full_shipping_address)  # newlines preserved
        self.assertEqual(t.email_to, "orders@packrightco.com")  # `email` alias
        self.assertEqual(t.email_cc, "ap@balanzify.com,ops@balanzify.com")

    def test_mixed_category_and_item_lines_are_kept(self):
        t = self._save()
        self.assertEqual(t.lines.count(), 2)
        # 125.5 + (24 x 18.75 = 450)
        self.assertEqual(t.total_amount, Decimal("575.500"))

    def test_read_echoes_the_po_wire_names(self):
        data = PrivateWeRecurringTemplateSerializer(
            self._save(), context=self._context()
        ).data
        self.assertEqual(str(data["ship_to"]), str(self.ship_to.uid))
        self.assertEqual(data["ship_to_name"], "Dock 4")
        self.assertEqual(data["email"], "orders@packrightco.com")
        self.assertEqual(data["shipping_by"], "FedEx")

    def test_party_is_the_vendor_not_the_ship_to_customer(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        row = PrivateWeRecurringTemplateListSerializer(self._save()).data
        self.assertEqual(row["party_name"], "PackRight Co")

    def test_purchase_order_requires_a_vendor(self):
        payload = self._payload()
        payload.pop("supplier")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("supplier", s.errors)

    def test_empty_string_ship_to_reads_as_null(self):
        t = self._save(ship_to="", warehouse="")
        self.assertIsNone(t.ship_to)
        self.assertIsNone(t.warehouse)


class SalesReceiptTemplateTests(TestCase):
    """SALES_RECEIPT is ESTIMATE plus a settlement block (spec §1)."""

    @classmethod
    def setUpTestData(cls):
        from categoryio.models import Category

        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="Dana", display_name="Northgate", company=cls.company
        )
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Checking", company=cls.company,
            account_type=Category.objects.create(title="Bank", company=cls.company),
        )
        cls.method = PaymentMethod.objects.create(
            title="Card", company=cls.company, status="ACTIVE"
        )
        cls.product = Product.objects.create(
            title="Membership", sku="MEM-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly gym membership receipt",
            "txn_type": "SALES_RECEIPT",
            "template_type": "SCHEDULED",
            "customer": str(self.customer.uid),
            "mailing_address": "12 Main St, Austin, TX, 73301",
            "shipping_from": "480 Congress Ave Austin TX 78701",
            "reference_number": "MEMBER-2026-08",
            "payment_method": str(self.method.uid),
            "deposit_to": str(self.bank.uid),
            "tax_kind": "EXCLUSIVE",
            "memo": "Thanks for being a member.",
            "message_on_receipt": "Thanks for being a member.",
            "statement_memo": "BALANZIFY MEMBERSHIP",
            "auto_email": True,
            "print_later": True,
            # the ONE nested object on this resource
            "email": {
                "customer_email": "dana@northgate.example",
                "cc_emails": "accounts@northgate.example",
                "bcc_emails": "archive@balanzify.example",
            },
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [{
                "line_type": "ITEM", "product": str(self.product.uid),
                "quantity": "1", "rate": "99", "amount": "99",
            }],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def _save(self, **overrides):
        s = self._serializer(**overrides)
        s.is_valid(raise_exception=True)
        return s.save()

    def test_nested_email_object_is_unwrapped(self):
        # PURCHASE_ORDER sends `email` as a string; this type sends an object.
        t = self._save()
        self.assertEqual(t.email_to, "dana@northgate.example")
        self.assertEqual(t.email_cc, "accounts@northgate.example")
        self.assertEqual(t.email_bcc, "archive@balanzify.example")

    def test_email_reads_back_nested(self):
        data = PrivateWeRecurringTemplateSerializer(
            self._save(), context=self._context()
        ).data
        self.assertEqual(data["email"]["customer_email"], "dana@northgate.example")
        self.assertEqual(data["email"]["cc_emails"], "accounts@northgate.example")

    def test_settlement_and_notes_round_trip(self):
        t = self._save()
        self.assertEqual(t.payment_account, self.bank)   # deposit_to alias
        self.assertEqual(t.payment_method, self.method)
        self.assertEqual(t.shipping_from, "480 Congress Ave Austin TX 78701")
        self.assertEqual(t.statement_memo, "BALANZIFY MEMBERSHIP")
        self.assertTrue(t.print_later)
        self.assertTrue(t.auto_email)

    def test_deposit_must_be_a_bank_account(self):
        from categoryio.models import Category

        other = ChartOfAccount.objects.create(
            code="1200", title="A/R", company=self.company,
            account_type=Category.objects.create(
                title="Accounts Receivable", company=self.company
            ),
        )
        s = self._serializer(deposit_to=str(other.uid))
        self.assertFalse(s.is_valid())
        self.assertIn("deposit_to", s.errors)

    def test_requires_deposit_account_and_method(self):
        for missing in ("deposit_to", "payment_method"):
            payload = self._payload()
            payload.pop(missing)
            s = PrivateWeRecurringTemplateSerializer(
                data=payload, context=self._context()
            )
            self.assertFalse(s.is_valid(), missing)
            self.assertIn(missing, s.errors)

    def test_rejects_category_lines(self):
        account = ChartOfAccount.objects.create(
            code="4000", title="Income", company=self.company
        )
        s = self._serializer(lines=[{
            "line_type": "CATEGORY", "charter_account": str(account.uid),
            "amount": "99",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_party_is_the_customer(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        row = PrivateWeRecurringTemplateListSerializer(self._save()).data
        self.assertEqual(row["party_name"], "Northgate")


class DepositTemplateTests(TestCase):
    """DEPOSIT: no document party, fund rows only, cash back SUBTRACTS."""

    @classmethod
    def setUpTestData(cls):
        from categoryio.models import Category

        cls.company = Company.objects.create(name="Acme")
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Operating", company=cls.company,
            account_type=Category.objects.create(title="Bank", company=cls.company),
        )
        cls.income = ChartOfAccount.objects.create(
            code="4000", title="Consulting income", company=cls.company
        )
        cls.petty = ChartOfAccount.objects.create(
            code="1050", title="Petty cash", company=cls.company
        )
        cls.customer = Customer.objects.create(
            first_name="Dana", display_name="Northgate", company=cls.company
        )
        cls.supplier = Supplier.objects.create(
            first_name="Vend", display_name="VendorCo", company=cls.company
        )
        cls.method = PaymentMethod.objects.create(
            title="Cheque", company=cls.company, status="ACTIVE"
        )
        cls.product = Product.objects.create(
            title="Thing", sku="TH-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly branch cash deposit",
            "txn_type": "DEPOSIT",
            "template_type": "SCHEDULED",
            "deposit_to": str(self.bank.uid),
            "cash_back_account": str(self.petty.uid),
            "cash_back_memo": "Front desk float",
            "cash_back_amount": "150.00",
            "track_returns": True,
            "memo": "Sweep of counter takings.",
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [
                {"line_type": "CATEGORY", "charter_account": str(self.income.uid),
                 "amount": "1200.00", "description": "Q3 settlement", "position": 0,
                 "customer": str(self.customer.uid),
                 "payment_method": str(self.method.uid),
                 "reference_number": "CHK-99120"},
                {"line_type": "CATEGORY", "charter_account": str(self.income.uid),
                 "amount": "480.50", "description": "Vendor rebate", "position": 1,
                 "supplier": str(self.supplier.uid),
                 "reference_number": "ACH-07"},
            ],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def _save(self, **overrides):
        s = self._serializer(**overrides)
        s.is_valid(raise_exception=True)
        return s.save()

    def test_saves_without_any_document_level_party(self):
        # Unique to this type: the payer is per line, not on the document.
        t = self._save()
        self.assertIsNone(t.customer)
        self.assertIsNone(t.supplier)
        self.assertEqual(t.payment_account, self.bank)   # deposit_to alias
        self.assertTrue(t.track_returns)

    def test_cash_back_is_subtracted_from_the_total(self):
        # The ONLY type where an extra amount reduces the total.
        t = self._save()
        self.assertEqual(t.total_amount, Decimal("1530.500"))  # 1200 + 480.50 - 150

    def test_fund_rows_carry_their_own_payer_and_instrument(self):
        t = self._save()
        first, second = list(t.lines.order_by("position"))
        self.assertEqual(first.customer, self.customer)
        self.assertIsNone(first.supplier)
        self.assertEqual(first.payment_method, self.method)
        self.assertEqual(first.reference_number, "CHK-99120")
        self.assertEqual(second.supplier, self.supplier)
        self.assertIsNone(second.customer)

    def test_a_fund_row_cannot_have_both_payers(self):
        s = self._serializer(cash_back_amount="0", lines=[{
            "line_type": "CATEGORY", "charter_account": str(self.income.uid),
            "amount": "100", "position": 0,
            "customer": str(self.customer.uid),
            "supplier": str(self.supplier.uid),
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_cash_back_cannot_exceed_the_deposit(self):
        s = self._serializer(cash_back_amount="2000")
        self.assertFalse(s.is_valid())
        self.assertIn("cash_back_amount", s.errors)

    def test_cash_back_needs_an_account(self):
        payload = self._payload()
        payload.pop("cash_back_account")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("cash_back_account", s.errors)

    def test_zero_cash_back_needs_no_account(self):
        payload = self._payload(cash_back_amount="0")
        payload.pop("cash_back_account")
        t = self._save(**{k: v for k, v in payload.items() if k != "txn_type"},
                       txn_type="DEPOSIT")
        self.assertEqual(t.total_amount, Decimal("1680.500"))

    def test_deposit_must_land_in_a_bank_account(self):
        from categoryio.models import Category

        card = ChartOfAccount.objects.create(
            code="2100", title="Company Card", company=self.company,
            account_type=Category.objects.create(
                title="Credit Card", company=self.company
            ),
        )
        s = self._serializer(deposit_to=str(card.uid))
        self.assertFalse(s.is_valid())
        self.assertIn("deposit_to", s.errors)

    def test_rejects_item_lines(self):
        s = self._serializer(cash_back_amount="0", lines=[{
            "line_type": "ITEM", "product": str(self.product.uid),
            "quantity": "1", "rate": "100", "amount": "100",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)


class PartyNameAndAttachmentTests(TestCase):
    """display_name is nullable, and attachments arrive as pre-uploaded uids."""

    @classmethod
    def setUpTestData(cls):
        from fileroomio.models import FileItem

        cls.company = Company.objects.create(name="Acme")
        # No display_name -- the common case, and what returned null before.
        cls.supplier = Supplier.objects.create(
            first_name="Ada", last_name="Lovelace", company=cls.company
        )
        cls.customer = Customer.objects.create(
            first_name="Grace", last_name="Hopper", company=cls.company
        )
        cls.account = ChartOfAccount.objects.create(
            code="6000", title="Rent", company=cls.company
        )
        cls.term = Term.objects.create(title="Net 15", days=15, company=cls.company)
        cls.warehouse = Warehouse.objects.create(title="Main", company=cls.company)
        cls.file_a = FileItem.objects.create(
            company=cls.company, title="contract.pdf", status="PUBLISHED"
        )
        cls.file_b = FileItem.objects.create(
            company=cls.company, title="invoice.pdf", status="PUBLISHED"
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly rent",
            "txn_type": "BILL",
            "template_type": "SCHEDULED",
            "supplier": str(self.supplier.uid),
            "terms": str(self.term.uid),
            "warehouse": str(self.warehouse.uid),
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [{
                "line_type": "CATEGORY", "charter_account": str(self.account.uid),
                "amount": "100.00", "position": 0,
                "customer": str(self.customer.uid),
            }],
        }
        payload.update(overrides)
        return payload

    def _save(self, **overrides):
        s = PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )
        s.is_valid(raise_exception=True)
        return s.save()

    def _read(self, template):
        return PrivateWeRecurringTemplateSerializer(
            template, context=self._context()
        ).data

    # ---- party names -----------------------------------------------------

    def test_names_fall_back_to_the_name_parts(self):
        # display_name is nullable while first_name is not, so reading it
        # directly returned null for these parties.
        data = self._read(self._save())
        self.assertEqual(data["supplier_name"], "Ada Lovelace")
        self.assertEqual(data["lines"][0]["customer_name"], "Grace Hopper")

    def test_display_name_still_wins_when_set(self):
        self.supplier.display_name = "Lovelace Ltd"
        self.supplier.save(update_fields=["display_name"])
        self.assertEqual(self._read(self._save())["supplier_name"], "Lovelace Ltd")

    def test_list_row_party_name_falls_back_too(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        row = PrivateWeRecurringTemplateListSerializer(self._save()).data
        self.assertEqual(row["party_name"], "Ada Lovelace")
        self.assertEqual(row["supplier_name"], "Ada Lovelace")

    def test_name_is_null_only_when_there_is_no_party(self):
        data = self._read(self._save())
        self.assertIsNone(data["customer_name"])   # BILL has no doc-level customer

    # ---- attachments -----------------------------------------------------

    def test_file_uids_are_linked_and_returned(self):
        template = self._save(
            file_uids=[str(self.file_a.uid), str(self.file_b.uid)],
            file_description="Signed contract",
        )
        files = self._read(template)["files"]
        self.assertEqual(
            {f["uid"] for f in files},
            {str(self.file_a.uid), str(self.file_b.uid)},
        )
        self.assertIn("contract.pdf", {f["title"] for f in files})

    def test_omitting_file_uids_on_patch_leaves_attachments_alone(self):
        # Otherwise every edit that didn't resend them would silently detach.
        template = self._save(file_uids=[str(self.file_a.uid)])
        s = PrivateWeRecurringTemplateSerializer(
            template, data=self._payload(), context=self._context()
        )
        s.is_valid(raise_exception=True)
        self.assertEqual(len(self._read(s.save())["files"]), 1)

    def test_an_explicit_empty_list_clears_attachments(self):
        template = self._save(file_uids=[str(self.file_a.uid)])
        s = PrivateWeRecurringTemplateSerializer(
            template, data=self._payload(file_uids=[]), context=self._context()
        )
        s.is_valid(raise_exception=True)
        self.assertEqual(self._read(s.save())["files"], [])

    def test_templates_without_attachments_return_an_empty_list(self):
        self.assertEqual(self._read(self._save())["files"], [])


class DepositPartyNameTests(TestCase):
    """A DEPOSIT has no document party, so the list row names it another way."""

    @classmethod
    def setUpTestData(cls):
        from categoryio.models import Category

        cls.company = Company.objects.create(name="Acme")
        cls.bank = ChartOfAccount.objects.create(
            code="1010", title="Operating", company=cls.company, status="ACTIVE",
            account_type=Category.objects.create(title="Bank", company=cls.company),
        )
        cls.income = ChartOfAccount.objects.create(
            code="4000", title="Income", company=cls.company
        )
        cls.vendor = Supplier.objects.create(
            first_name="Vend", last_name="Co", company=cls.company
        )
        cls.other = Supplier.objects.create(
            first_name="Other", last_name="Vendor", company=cls.company
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _row(self, lines):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        s = PrivateWeRecurringTemplateSerializer(
            data={
                "name": "Recurring Deposit", "txn_type": "DEPOSIT",
                "template_type": "SCHEDULED", "deposit_to": str(self.bank.uid),
                "frequency": "DAILY", "interval_count": 1,
                "start_date": "2026-07-28", "end_type": "NONE",
                "lines": lines,
            },
            context=self._context(),
        )
        s.is_valid(raise_exception=True)
        return PrivateWeRecurringTemplateListSerializer(s.save()).data

    def _line(self, supplier=None, **extra):
        line = {
            "line_type": "CATEGORY", "charter_account": str(self.income.uid),
            "amount": "399", "position": 0,
        }
        if supplier:
            line["supplier"] = str(supplier.uid)
        line.update(extra)
        return line

    def test_single_payer_names_the_row(self):
        row = self._row([self._line(self.vendor)])
        self.assertEqual(row["party_name"], "Vend Co")

    def test_mixed_payers_fall_back_to_the_deposit_account(self):
        # No single counterparty, so name it the way the screen's footer does.
        row = self._row([
            self._line(self.vendor),
            dict(self._line(self.other), position=1),
        ])
        self.assertEqual(row["party_name"], "Operating")

    def test_no_payer_falls_back_to_the_deposit_account(self):
        row = self._row([self._line()])
        self.assertEqual(row["party_name"], "Operating")


class CreditMemoTemplateTests(TestCase):
    """CREDIT_MEMO is ESTIMATE plus four fields; the store is required."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="Ada", display_name="Northwind", company=cls.company
        )
        cls.warehouse = Warehouse.objects.create(title="Main", company=cls.company)
        cls.product = Product.objects.create(
            title="Gold widget", sku="GW-1", quantity=0, date=date(2026, 1, 1),
            kind="PRODUCT", status="ACTIVE", company=cls.company,
        )
        cls.account = ChartOfAccount.objects.create(
            code="4000", title="Income", company=cls.company
        )

    def _context(self):
        return {"request": SimpleNamespace(user=_FakeUser(self.company))}

    def _payload(self, **overrides):
        payload = {
            "name": "Monthly loyalty credit",
            "txn_type": "CREDIT_MEMO",
            "template_type": "SCHEDULED",
            "customer": str(self.customer.uid),
            "mailing_address": "12 Main St, Austin, TX, 73301",
            "warehouse": str(self.warehouse.uid),
            "shipping_from": "440 Congress Ave Austin TX",
            "email": {
                "customer_email": "ada@northwind.co",
                "cc_emails": "billing@northwind.co",
                "bcc_emails": "archive@balanzify.com",
            },
            "tax_kind": "EXCLUSIVE",
            "memo": "Loyalty credit applied.",
            "message_on_credit_memo": "Loyalty credit applied.",
            "statement_memo": "BALANZIFY LOYALTY CREDIT",
            "frequency": "MONTHLY", "interval_count": 1,
            "day_mode": "DAY_OF_MONTH", "day_of_month": 1,
            "start_date": "2026-08-01", "end_type": "NONE",
            "lines": [{
                "line_type": "ITEM", "product": str(self.product.uid),
                "quantity": "2", "rate": "150", "amount": "300",
                "description": "Returned goods credit",
            }],
        }
        payload.update(overrides)
        return payload

    def _serializer(self, **overrides):
        return PrivateWeRecurringTemplateSerializer(
            data=self._payload(**overrides), context=self._context()
        )

    def _save(self, **overrides):
        s = self._serializer(**overrides)
        s.is_valid(raise_exception=True)
        return s.save()

    def test_credit_memo_saves(self):
        t = self._save()
        self.assertEqual(t.txn_type, "CREDIT_MEMO")
        self.assertEqual(t.customer, self.customer)
        self.assertEqual(t.warehouse, self.warehouse)
        self.assertEqual(t.statement_memo, "BALANZIFY LOYALTY CREDIT")
        self.assertEqual(t.shipping_from, "440 Congress Ave Austin TX")

    def test_total_is_positive(self):
        # A credit reduces the balance, but is stored positive with a negative
        # ledger effect -- the manual screen does the same.
        self.assertEqual(self._save().total_amount, Decimal("300.000"))

    def test_nested_email_round_trips(self):
        data = PrivateWeRecurringTemplateSerializer(
            self._save(), context=self._context()
        ).data
        self.assertEqual(data["email"]["customer_email"], "ada@northwind.co")
        self.assertEqual(data["message_on_credit_memo"], "Loyalty credit applied.")

    def test_store_is_required(self):
        payload = self._payload()
        payload.pop("warehouse")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("warehouse", s.errors)

    def test_requires_a_customer(self):
        payload = self._payload()
        payload.pop("customer")
        s = PrivateWeRecurringTemplateSerializer(data=payload, context=self._context())
        self.assertFalse(s.is_valid())
        self.assertIn("customer", s.errors)

    def test_rejects_category_lines(self):
        s = self._serializer(lines=[{
            "line_type": "CATEGORY", "charter_account": str(self.account.uid),
            "amount": "300",
        }])
        self.assertFalse(s.is_valid())
        self.assertIn("lines", s.errors)

    def test_party_is_the_customer(self):
        from weapi.django_rest.serializers.recurring_transactions import (
            PrivateWeRecurringTemplateListSerializer,
        )
        row = PrivateWeRecurringTemplateListSerializer(self._save()).data
        self.assertEqual(row["party_name"], "Northwind")
