"""MoovAccountDetailsView must be gated by OWNERSHIP, not by is_staff.

Every signup gets is_admin=True, so the permission class can't be the security
boundary — a caller-supplied account_uid has to be proven to belong to the
requester's company before we ask Moov for it.
"""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from companyio.models import Company, CompanyUser
from moovmoneyio.django_rest.helpers.moov_connection import (
    build_terms_of_service_body,
    moov_bearer_from_request,
    redact_moov_payload,
)
from moovmoneyio.models import MoovAccountSettings

from weapi.django_rest.views.moov_money.account_settings import (
    MoovAccessTokenView,
    MoovAccountCapabilitiesListView,
    MoovAccountCreateCapabilitiesView,
    MoovAccountCreateRepresentativesView,
    MoovAccountDetailsView,
)


class PayrollPayoutTests(TestCase):
    """Atomic-as-possible payout: validate before money, never double-pay, and
    leave the run unpaid if Moov fails."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal
        from accounts.models import ChartOfAccount
        from employeeio.models import Employee
        from payrollio.models import PayrollSalaryProcess

        self.Decimal = Decimal
        self.PayrollSalaryProcess = PayrollSalaryProcess

        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="pay@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)
        self.employee = Employee.objects.create(
            company=self.company, user=self.user, code="EMP-0001", name_en="Pay Employee",
        )
        coa = ChartOfAccount.objects.create(company=self.company, code="7000")
        self.run = PayrollSalaryProcess.objects.create(
            employee=self.employee,
            payment_account=coa,
            pay_date=date(2026, 7, 21),
            pay_period="05/10/26 - 05/23/26",
            pay_method="DIRECT_DEPOSIT",
            net_pay=Decimal("6.61"),
        )
        self.moov_setting = MoovAccountSettings.objects.create(
            company=self.company, moov_account_uid="acct_A",
            moov_account_display_name="A",
        )
        from moovmoneyio.choices import MoovBankAccountKindChoices
        from moovmoneyio.models import MoovBankAccountSettings

        self.MoovBankAccountSettings = MoovBankAccountSettings
        self.source = MoovBankAccountSettings.objects.create(
            moov_account_settings=self.moov_setting, bank_account_uid="src_uid",
            bank_account_kind=MoovBankAccountKindChoices.SOURCE,
        )
        self.dest = MoovBankAccountSettings.objects.create(
            moov_account_settings=self.moov_setting, bank_account_uid="dst_uid",
            bank_account_kind=MoovBankAccountKindChoices.DESTINATION,
            employee=self.employee, bank_name="US Bank", account_number="6189",
        )

        self._pm_list = [
            {"payment_method_type": "ach-debit-fund", "payment_method_id": "src_pm",
             "bank_account": {"bank_account_id": "src_uid"}},
            {"payment_method_type": "ach-credit-same-day", "payment_method_id": "dst_pm",
             "bank_account": {"bank_account_id": "dst_uid"}},
        ]

    def _pay(self):
        from unittest.mock import MagicMock
        from weapi.django_rest.helpers.payroll.salary_payout import pay_salary_run

        return pay_salary_run(MagicMock(), self.run, self.user)

    @patch("weapi.django_rest.helpers.payroll.salary_payout.generate_transfer_receipt",
           return_value={"file_uid": "f1", "url": "http://x/r.pdf"})
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_client")
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_call")
    def test_success_marks_run_paid_and_links_transfer(
        self, mock_call, mock_client, mock_receipt
    ):
        from moovmoneyio.models import MoovTransfers

        mock_call.side_effect = [self._pm_list, {"transfer_id": "tx1"}]
        result = self._pay()

        self.assertFalse(result["already_paid"])
        transfer = MoovTransfers.objects.get(moov_transfer_uid="tx1")
        self.assertEqual(transfer.payroll_salary_process_id, self.run.pk)
        self.assertEqual(transfer.amount, self.Decimal("6.61"))
        self.run.refresh_from_db()
        self.assertTrue(self.run.is_salary_done)
        self.assertEqual(result["receipt"]["url"], "http://x/r.pdf")

    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_client")
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_call")
    def test_validation_fails_before_any_money_moves(self, mock_call, mock_client):
        from weapi.django_rest.helpers.payroll.salary_payout import PayoutError

        self.source.delete()  # no funding account
        with self.assertRaises(PayoutError) as ctx:
            self._pay()
        self.assertEqual(ctx.exception.status_code, 400)
        mock_call.assert_not_called()  # Moov never contacted → no money moved

    @patch("weapi.django_rest.helpers.payroll.salary_payout.generate_transfer_receipt",
           return_value={"file_uid": "f1", "url": "http://x/r.pdf"})
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_client")
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_call")
    def test_already_paid_run_is_not_paid_again(
        self, mock_call, mock_client, mock_receipt
    ):
        from moovmoneyio.models import MoovTransfers
        from moovmoneyio.choices import MoovTransferStatusChoices

        MoovTransfers.objects.create(
            moov_transfer_uid="existing_tx", amount=self.Decimal("6.61"),
            currency="USD", company=self.company, employee=self.employee,
            status=MoovTransferStatusChoices.PENDING,
            payroll_salary_process=self.run,
        )
        result = self._pay()

        self.assertTrue(result["already_paid"])
        mock_call.assert_not_called()  # no second transfer
        self.assertEqual(
            MoovTransfers.objects.filter(payroll_salary_process=self.run).count(), 1
        )

    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_client")
    @patch("weapi.django_rest.helpers.payroll.salary_payout.moov_call")
    def test_moov_failure_leaves_run_unpaid(self, mock_call, mock_client):
        import httpx
        from moovmoneyio.models import MoovTransfers
        from moovio_sdk.models import errors as moov_errors
        from weapi.django_rest.helpers.payroll.salary_payout import PayoutError

        resp = httpx.Response(422, request=httpx.Request("POST", "https://api.moov.io/t"))
        mock_call.side_effect = [
            self._pm_list,
            moov_errors.MoovError("insufficient funds", resp, None),
        ]
        with self.assertRaises(PayoutError) as ctx:
            self._pay()

        self.assertEqual(ctx.exception.status_code, 502)
        self.run.refresh_from_db()
        self.assertFalse(self.run.is_salary_done)
        self.assertEqual(
            MoovTransfers.objects.filter(payroll_salary_process=self.run).count(), 0
        )


class DeprecatedTransferEndpointTests(TestCase):
    """The batch transfer endpoint is superseded by the payroll pay endpoint and
    must advertise its deprecation on every response."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create(email="dep@x.test", password="x")

    def test_response_carries_deprecation_headers(self):
        from weapi.django_rest.views.moov_money.transfer_money import (
            MoovTransferCreateView,
        )

        # A non-list body 400s early, but finalize_response still runs.
        request = self.factory.post("/moov-money/transfer/create", {"x": 1},
                                    format="json")
        force_authenticate(request, user=self.user)
        res = MoovTransferCreateView.as_view()(request)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res["Deprecation"], "true")
        self.assertIn("successor-version", res["Link"])
        self.assertIn("salary-process", res["Warning"])


class MoovWebhookTests(TestCase):
    """Signature-verified webhook drives PENDING transfers to their final state."""

    def setUp(self):
        import hashlib
        import hmac

        self.hashlib = hashlib
        self.hmac = hmac
        self.factory = APIRequestFactory()
        self.secret = "whsec_test"
        self.company = Company.objects.create(name="A")

    def _sig(self, ts, nonce, wid):
        return self.hmac.new(
            self.secret.encode(), f"{ts}|{nonce}|{wid}".encode(), self.hashlib.sha512
        ).hexdigest()

    def _post(self, body):
        from weapi.django_rest.views.moov_money.webhooks import MoovWebhookView

        ts, nonce, wid = "1", "n1", "wh1"
        request = self.factory.post("/moov-money/webhook", body, format="json")
        request.META["HTTP_X_TIMESTAMP"] = ts
        request.META["HTTP_X_NONCE"] = nonce
        request.META["HTTP_X_WEBHOOK_ID"] = wid
        request.META["HTTP_X_SIGNATURE"] = self._sig(ts, nonce, wid)
        return MoovWebhookView.as_view()(request)

    def _make_transfer(self, status_value="PENDING"):
        from moovmoneyio.models import MoovTransfers

        return MoovTransfers.objects.create(
            moov_transfer_uid="tx1", amount="6.61", currency="USD",
            company=self.company, status=status_value,
        )

    def test_valid_signature_transitions_status(self):
        from django.test import override_settings
        from moovmoneyio.models import MoovTransfers

        self._make_transfer()
        with override_settings(MOOV_WEBHOOK_SECRET=self.secret):
            res = self._post(
                {"type": "transfer.updated",
                 "data": {"transferID": "tx1", "status": "completed"}}
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            MoovTransfers.objects.get(moov_transfer_uid="tx1").status, "COMPLETED"
        )

    def test_bad_signature_rejected_and_no_update(self):
        from django.test import override_settings
        from moovmoneyio.models import MoovTransfers

        self._make_transfer()
        with override_settings(MOOV_WEBHOOK_SECRET=self.secret):
            request = self.factory.post(
                "/moov-money/webhook",
                {"type": "transfer.updated",
                 "data": {"transferID": "tx1", "status": "completed"}},
                format="json",
            )
            request.META["HTTP_X_SIGNATURE"] = "deadbeef"
            from weapi.django_rest.views.moov_money.webhooks import MoovWebhookView
            res = MoovWebhookView.as_view()(request)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            MoovTransfers.objects.get(moov_transfer_uid="tx1").status, "PENDING"
        )

    def test_missing_secret_fails_closed(self):
        from django.test import override_settings

        with override_settings(MOOV_WEBHOOK_SECRET=""):
            res = self._post({"type": "transfer.updated", "data": {}})
        self.assertEqual(res.status_code, 400)


class MoovCallFallbackTests(TestCase):
    """moov_call must recover a successful response the SDK can't parse (its enums
    lag Moov's API) and re-raise genuine failures."""

    def _rve(self, status_code, body):
        import httpx
        from moovio_sdk.models import errors as moov_errors

        resp = httpx.Response(
            status_code,
            content=body.encode(),
            request=httpx.Request("GET", "https://api.moov.io/x"),
        )
        return moov_errors.ResponseValidationError(
            "Response validation failed", resp, ValueError("unknown enum"), body
        )

    def test_recovers_raw_body_on_successful_validation_error(self):
        from moovmoneyio.django_rest.helpers.moov_connection import moov_call

        body = '{"bankAccountID": "bank_1", "paymentMethods": []}'

        def call():
            raise self._rve(200, body)

        data = moov_call(call)
        self.assertEqual(data.get("bankAccountID"), "bank_1")

    def test_reraises_when_response_is_an_error(self):
        from moovmoneyio.django_rest.helpers.moov_connection import moov_call
        from moovio_sdk.models import errors as moov_errors

        def call():
            raise self._rve(400, '{"error": "bad"}')

        with self.assertRaises(moov_errors.ResponseValidationError):
            moov_call(call)

    def test_happy_path_returns_result(self):
        from moovmoneyio.django_rest.helpers.moov_connection import moov_call

        class Res:
            result = {"bankAccountID": "b2"}

        with patch(
            "moovmoneyio.django_rest.helpers.convert_moov_response._convert_moov_result",
            side_effect=lambda x: x,
        ):
            data = moov_call(lambda: Res())
        self.assertEqual(data["bankAccountID"], "b2")


class TransferTimelineBuilderTests(TestCase):
    """Maps the Moov transfer object to the dashboard-style timeline."""

    def _transfer(self):
        return {
            "status": "pending",
            "createdOn": "2026-07-21T19:09:00Z",
            "source": {
                "achDetails": {
                    "statusUpdates": {
                        "initiatedOn": "2026-07-21T19:10:00Z",
                        "originatedOn": "2026-07-21T20:00:00Z",
                    }
                }
            },
            "destination": {"achDetails": {"statusUpdates": {}}},
        }

    def test_maps_created_and_ach_debit_steps(self):
        from moovmoneyio.django_rest.helpers.transfer_timeline import (
            build_transfer_timeline,
        )

        steps = {s["key"]: s for s in build_transfer_timeline(self._transfer())}

        self.assertEqual(steps["created"]["at"], "2026-07-21T19:09:00Z")
        self.assertTrue(steps["created"]["done"])
        self.assertEqual(steps["debit_originated"]["at"], "2026-07-21T20:00:00Z")
        self.assertTrue(steps["debit_originated"]["done"])
        # Not reached yet -> present but not done (grayed on the dashboard).
        self.assertIsNone(steps["credit_initiated"]["at"])
        self.assertFalse(steps["credit_initiated"]["done"])
        self.assertFalse(steps["completed"]["done"])

    def test_handles_snake_case_and_empty(self):
        from moovmoneyio.django_rest.helpers.transfer_timeline import (
            build_transfer_timeline,
        )

        snake = build_transfer_timeline(
            {"created_on": "2026-01-01T00:00:00Z", "source": {}, "destination": {}}
        )
        self.assertEqual(snake[0]["at"], "2026-01-01T00:00:00Z")

        empty = build_transfer_timeline({})
        self.assertTrue(all(s["done"] is False for s in empty))
        self.assertEqual(empty[0]["key"], "created")


class TransferDetailsBuilderTests(TestCase):
    """Shapes the Moov transfer into the detail screen's blocks."""

    def test_maps_summary_banks_and_ach_debit(self):
        from moovmoneyio.django_rest.helpers.transfer_timeline import (
            build_transfer_details,
        )

        details = build_transfer_details({
            "transferID": "tr_1", "status": "pending",
            "amount": {"currency": "USD", "value": 661},
            "facilitatorFee": {"totalDecimal": "0.00"},
            "source": {
                "account": {"displayName": "Balanzify inc"},
                "bankAccount": {"lastFourAccountNumber": "7521",
                                "bankAccountType": "checking"},
                "achDetails": {"secCode": "CCD", "traceNumber": "27397",
                               "debitHoldPeriod": "2-day",
                               "companyEntryDescription": "Balanzify inc"},
            },
            "destination": {"bankAccount": {"lastFourAccountNumber": "6189",
                                            "bankAccountType": "savings"}},
        })

        self.assertEqual(details["payment_summary"],
                         {"amount": "6.61", "fees": "0.00",
                          "net_amount": "6.61", "currency": "USD"})
        self.assertEqual(details["source"]["last_four"], "7521")
        self.assertEqual(details["destination"]["last_four"], "6189")
        self.assertEqual(details["ach_debit"],
                         {"company_name": "Balanzify inc", "ach_hold": "2-day",
                          "sec_code": "CCD", "trace_number": "27397"})

    def test_empty_transfer_is_safe(self):
        from moovmoneyio.django_rest.helpers.transfer_timeline import (
            build_transfer_details,
        )
        details = build_transfer_details({})
        self.assertIsNone(details["amount"])
        self.assertEqual(details["payment_summary"]["fees"], "0.00")
        self.assertEqual(details["metadata"], {})


class PaymentTabCountsTests(TestCase):
    """on_process = unpaid salary runs (local); pending/canceled = Moov.

    The Pending/Cancel tabs list live Moov transfers, so their badges must be
    counted from Moov too — counting the local mirror produced a screen showing
    3 canceled rows above a badge reading 0.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="pc@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)
        MoovAccountSettings.objects.create(
            company=self.company, moov_account_uid="acct_A",
            moov_account_display_name="A",
        )

    def _seed_local_mirror(self):
        """Local rows that deliberately DISAGREE with Moov (stale webhooks)."""
        from decimal import Decimal
        from moovmoneyio.models import MoovTransfers
        from moovmoneyio.choices import MoovTransferStatusChoices as S

        for i, st in enumerate([S.PENDING, S.PENDING, S.PENDING, S.COMPLETED]):
            MoovTransfers.objects.create(
                moov_transfer_uid=f"t{i}", amount=Decimal("1"), currency="USD",
                company=self.company, status=st,
            )

    def _get(self):
        from weapi.django_rest.views.payroll.salary_process import (
            PayrollPaymentTabCountsView,
        )

        request = self.factory.get("/x")
        request.user = self.user  # get() reads user.get_active_company() directly
        return PayrollPaymentTabCountsView().get(request)

    @patch("weapi.django_rest.helpers.payroll.payment_tab_counts.moov_call")
    @patch("weapi.django_rest.helpers.payroll.payment_tab_counts.moov_client")
    def test_counts_come_from_moov_not_the_local_mirror(self, _client, mock_call):
        # The reported bug: Moov reports 3 canceled, the local mirror still has
        # them PENDING because the status webhooks never landed.
        self._seed_local_mirror()
        mock_call.side_effect = [
            [{"transferID": "p1"}],                        # pending page
            [{"transferID": f"c{i}"} for i in range(3)],   # canceled page
        ]

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["data"]["pending"], 1)
        self.assertEqual(res.data["data"]["canceled"], 3)  # was 0 before the fix
        self.assertEqual(res.data["data"]["on_process"], 0)  # no salary runs

    @patch("weapi.django_rest.helpers.payroll.payment_tab_counts.moov_call")
    @patch("weapi.django_rest.helpers.payroll.payment_tab_counts.moov_client")
    def test_falls_back_to_local_mirror_when_moov_is_unreachable(
        self, _client, mock_call
    ):
        self._seed_local_mirror()
        mock_call.side_effect = RuntimeError("moov unreachable")

        res = self._get()

        # Degrades to the mirror instead of 500-ing the whole payment screen.
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["data"]["pending"], 3)
        self.assertEqual(res.data["data"]["canceled"], 0)

    def test_zero_when_company_has_no_moov_account(self):
        MoovAccountSettings.objects.filter(company=self.company).delete()

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["data"]["pending"], 0)
        self.assertEqual(res.data["data"]["canceled"], 0)


class MoovTransferCancelTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="cx@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)
        MoovAccountSettings.objects.create(
            company=self.company, moov_account_uid="acct_A",
            moov_account_display_name="A",
        )

    @patch("weapi.django_rest.views.moov_money.transfer_money.moov_call")
    @patch("weapi.django_rest.views.moov_money.transfer_money.moov_client")
    def test_completed_cancellation_marks_transfer_canceled(self, mock_client, mock_call):
        from moovmoneyio.models import MoovTransfers
        from moovmoneyio.choices import MoovTransferStatusChoices
        from weapi.django_rest.views.moov_money.transfer_money import (
            MoovTransferCancellationView,
        )
        from decimal import Decimal

        MoovTransfers.objects.create(
            moov_transfer_uid="tr_1", amount=Decimal("6.61"), currency="USD",
            company=self.company, status=MoovTransferStatusChoices.PENDING,
        )
        mock_call.return_value = {"status": "completed"}

        request = self.factory.post("/x")
        force_authenticate(request, user=self.user)
        res = MoovTransferCancellationView.as_view()(request, transfer_uid="tr_1")

        self.assertEqual(res.status_code, 201)
        self.assertEqual(
            MoovTransfers.objects.get(moov_transfer_uid="tr_1").status,
            MoovTransferStatusChoices.CANCELED,
        )
        mock_call.assert_called_once()


class MoovBankAccountLinkIdempotencyTests(TestCase):
    """Re-linking a bank returns the SAME bank_account_uid from Moov, so persistence
    must update the row, not blind-create it into a unique-constraint 500."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="bank@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)
        MoovAccountSettings.objects.create(
            company=self.company, moov_account_uid="acct_A",
            moov_account_display_name="A",
        )

    def _post(self):
        from weapi.django_rest.views.moov_money.bank_account_settings import (
            MoovBankAccountCreateView,
        )
        request = self.factory.post(
            "/x", {"bank_account_kind": "SOURCE"}, format="json"
        )
        force_authenticate(request, user=self.user)
        return MoovBankAccountCreateView.as_view()(request)

    @patch("weapi.django_rest.views.moov_money.bank_account_settings.moov_call")
    @patch("weapi.django_rest.views.moov_money.bank_account_settings.moov_client")
    def test_relinking_same_bank_does_not_duplicate(self, mock_client, mock_call):
        from moovmoneyio.models import MoovBankAccountSettings

        mock_call.return_value = {
            "bankAccountID": "cc712f82",
            "bankAccountType": "savings",
            "bankName": "Test Bank",
            "holderName": "Osman",
            "holderType": "business",
            "lastFourAccountNumber": "6189",
            "routingNumber": "091000022",
        }

        first = self._post()
        second = self._post()  # same bankAccountID -> used to 500 on unique key

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            MoovBankAccountSettings.objects.filter(
                bank_account_uid="cc712f82"
            ).count(),
            1,
        )


class MoovAccessTokenScopeTests(TestCase):
    """The browser token must be scoped to the caller's own account, never
    /transfers.* — otherwise a leaked token could move money."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="tok@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)

    def _get(self):
        request = self.factory.get("/x")
        force_authenticate(request, user=self.user)
        return MoovAccessTokenView.as_view()(request)

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_get_oauth_token")
    def test_scopes_to_own_account_when_it_exists(self, mock_token):
        mock_token.return_value = "tok"
        MoovAccountSettings.objects.create(
            company=self.company, moov_account_uid="acct_A",
            moov_account_display_name="A",
        )
        res = self._get()
        self.assertEqual(res.status_code, 200)
        scope = mock_token.call_args.kwargs["scope"]
        self.assertEqual(scope, "/accounts/acct_A/profile.write")
        self.assertNotIn("transfers", scope)

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_get_oauth_token")
    def test_onboarding_scope_has_no_transfers(self, mock_token):
        mock_token.return_value = "tok"
        res = self._get()  # no MoovAccountSettings yet
        self.assertEqual(res.status_code, 200)
        scope = mock_token.call_args.kwargs["scope"]
        self.assertEqual(scope, "/accounts.write")
        self.assertNotIn("transfers", scope)


class MoovGenericViewSerializerTests(TestCase):
    """Views that override their handler must not extend a DRF generic view.

    CreateAPIView/ListAPIView assert a `serializer_class`; these views never use
    one, so they blew up with
    "should either include a serializer_class attribute..." — which meant
    capabilities and representatives were never actually created at Moov.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = Company.objects.create(name="A")
        self.user = User.objects.create(email="gen@x.test", password="x")
        CompanyUser.objects.create(company=self.company, user=self.user)

    @patch("weapi.django_rest.views.moov_money.account_settings._convert_moov_result")
    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_capabilities_post_does_not_raise_assertionerror(
        self, mock_client, mock_convert
    ):
        mock_convert.return_value = [{"capability": "wallet", "status": "pending"}]
        request = self.factory.post(
            "/x", {"capabilities": ["Send_Funds", "WALLET"]}, format="json"
        )
        force_authenticate(request, user=self.user)

        res = MoovAccountCreateCapabilitiesView.as_view()(request, account_uid="acct_A")

        self.assertEqual(res.status_code, 201)
        mock_client.assert_called_once()

    @patch("weapi.django_rest.views.moov_money.account_settings._convert_moov_result")
    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_representatives_post_does_not_raise_assertionerror(
        self, mock_client, mock_convert
    ):
        mock_convert.return_value = {"representativeId": "rep_1"}
        request = self.factory.post(
            "/x", {"name": {"firstName": "A", "lastName": "B"}}, format="json"
        )
        force_authenticate(request, user=self.user)

        res = MoovAccountCreateRepresentativesView.as_view()(
            request, account_uid="acct_A"
        )

        # Reaches Moov (no AssertionError). 404 here only means no matching
        # MoovAccountSettings row, which is the view's own business logic.
        self.assertNotEqual(res.status_code, 500)
        mock_client.assert_called_once()


class TermsOfServiceBodyTests(TestCase):
    """`manual` acceptance must attest the REAL end-user IP from the request."""

    def setUp(self):
        self.factory = APIRequestFactory()

    def _request(self, **meta):
        request = self.factory.post("/x")
        request.META.update(meta)
        return request

    def test_manual_is_camelcased_with_real_client_ip(self):
        request = self._request(
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",  # client first, then proxy
            HTTP_USER_AGENT="Mozilla/5.0",
        )
        body, error = build_terms_of_service_body(
            {
                "manual": {
                    "accepted_date": "2026-07-14T10:00:00Z",
                    "accepted_user_agent": "Mozilla/5.0",
                    "accepted_domain": "app.balanzify.ai",
                }
            },
            request,
        )
        self.assertIsNone(error)
        self.assertEqual(
            body,
            {
                "manual": {
                    "acceptedDate": "2026-07-14T10:00:00Z",
                    "acceptedIP": "203.0.113.7",
                    "acceptedUserAgent": "Mozilla/5.0",
                    "acceptedDomain": "app.balanzify.ai",
                }
            },
        )

    def test_client_cannot_spoof_accepted_ip(self):
        request = self._request(
            HTTP_X_FORWARDED_FOR="203.0.113.7", HTTP_USER_AGENT="UA"
        )
        body, _ = build_terms_of_service_body(
            {
                "manual": {
                    "accepted_date": "2026-07-14T10:00:00Z",
                    "accepted_ip": "1.2.3.4",  # attacker-supplied — must be ignored
                    "accepted_user_agent": "UA",
                    "accepted_domain": "d.com",
                }
            },
            request,
        )
        self.assertEqual(body["manual"]["acceptedIP"], "203.0.113.7")

    def test_cloudflare_connecting_ip_wins_over_forwarded_for(self):
        request = self._request(
            HTTP_CF_CONNECTING_IP="198.51.100.9",
            HTTP_X_FORWARDED_FOR="203.0.113.7",
            HTTP_USER_AGENT="UA",
        )
        body, _ = build_terms_of_service_body(
            {"manual": {"accepted_date": "d", "accepted_domain": "x.com"}}, request
        )
        self.assertEqual(body["manual"]["acceptedIP"], "198.51.100.9")

    def test_token_shape_still_supported(self):
        body, error = build_terms_of_service_body({"token": "abc"}, self._request())
        self.assertIsNone(error)
        self.assertEqual(body, {"token": "abc"})

    def test_token_wins_when_both_supplied(self):
        # Moov has not enabled the manual flow for this platform, so the Drop
        # token is the only shape that can succeed — it must take precedence.
        request = self._request(
            HTTP_X_FORWARDED_FOR="203.0.113.7", HTTP_USER_AGENT="UA"
        )
        body, error = build_terms_of_service_body(
            {
                "token": "drop-token",
                "manual": {
                    "accepted_date": "2026-07-14T10:00:00Z",
                    "accepted_domain": "d.com",
                },
            },
            request,
        )
        self.assertIsNone(error)
        self.assertEqual(body, {"token": "drop-token"})

    def test_invalid_shape_is_rejected(self):
        body, error = build_terms_of_service_body({"nonsense": 1}, self._request())
        self.assertIsNone(body)
        self.assertIn("token", error)

    def test_absent_terms_of_service_is_a_noop(self):
        body, error = build_terms_of_service_body(None, self._request())
        self.assertIsNone(body)
        self.assertIsNone(error)


class MoovAccountDetailsPermissionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.company_a = Company.objects.create(name="A")
        self.company_b = Company.objects.create(name="B")

        # A normal signup: is_admin=True but NOT is_staff (this used to 403).
        self.user_a = User.objects.create(email="a@x.test", password="x")
        self.user_a.is_admin = True
        self.user_a.is_staff = False
        self.user_a.save()
        CompanyUser.objects.create(company=self.company_a, user=self.user_a)

        MoovAccountSettings.objects.create(
            company=self.company_a,
            moov_account_uid="acct_A",
            moov_account_display_name="A",
        )
        MoovAccountSettings.objects.create(
            company=self.company_b,
            moov_account_uid="acct_B",
            moov_account_display_name="B",
        )

    def _get(self, account_uid):
        request = self.factory.get(f"/moov/account/{account_uid}")
        force_authenticate(request, user=self.user_a)
        return MoovAccountDetailsView.as_view()(request, account_uid=account_uid)

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_company_admin_can_read_own_account(self, mock_client):
        moov = mock_client.return_value.__enter__.return_value
        moov.accounts.get.return_value.result = {"accountID": "acct_A"}

        res = self._get("acct_A")

        # is_admin (without is_staff) is no longer rejected.
        self.assertNotEqual(res.status_code, 403)
        self.assertEqual(res.status_code, 200)

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_cannot_read_another_companys_account(self, mock_client):
        res = self._get("acct_B")

        self.assertEqual(res.status_code, 404)
        # Moov must never even be contacted for a uid this company doesn't own.
        mock_client.assert_not_called()

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_unknown_account_uid_is_not_leaked(self, mock_client):
        res = self._get("acct_DOES_NOT_EXIST")

        self.assertEqual(res.status_code, 404)
        mock_client.assert_not_called()


class MoovBearerFromRequestTests(TestCase):
    """The frontend's Moov OAuth token, taken from X-Moov-Token (not Authorization)."""

    def setUp(self):
        self.factory = APIRequestFactory()

    def test_reads_x_moov_token_header(self):
        request = self.factory.post("/x", HTTP_X_MOOV_TOKEN="abc123")
        self.assertEqual(moov_bearer_from_request(request), "abc123")

    def test_strips_bearer_prefix(self):
        request = self.factory.post("/x", HTTP_X_MOOV_TOKEN="Bearer abc123")
        self.assertEqual(moov_bearer_from_request(request), "abc123")

    def test_ignores_our_own_authorization_header(self):
        # Authorization carries OUR jwt — it must never be forwarded to Moov.
        request = self.factory.post("/x", HTTP_AUTHORIZATION="Bearer our-django-jwt")
        self.assertIsNone(moov_bearer_from_request(request))

    def test_absent_token_falls_back_to_none(self):
        self.assertIsNone(moov_bearer_from_request(self.factory.post("/x")))

    def test_token_is_redacted_from_logs(self):
        safe = redact_moov_payload({"moov_token": "secret", "city": "Minneapolis"})
        self.assertEqual(safe["moov_token"], "***redacted***")
        self.assertEqual(safe["city"], "Minneapolis")


class MoovCapabilitiesTests(TestCase):
    """`terms_of_service_due` is the authoritative answer, not the dashboard."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.company_a = Company.objects.create(name="A")
        self.company_b = Company.objects.create(name="B")
        self.user_a = User.objects.create(email="cap@x.test", password="x")
        self.user_a.is_admin = True
        self.user_a.is_staff = False
        self.user_a.save()
        CompanyUser.objects.create(company=self.company_a, user=self.user_a)
        MoovAccountSettings.objects.create(
            company=self.company_a,
            moov_account_uid="acct_A",
            moov_account_display_name="A",
        )
        MoovAccountSettings.objects.create(
            company=self.company_b,
            moov_account_uid="acct_B",
            moov_account_display_name="B",
        )

    def _get(self, account_uid):
        request = self.factory.get(f"/moov/account/details/{account_uid}/capabilities")
        force_authenticate(request, user=self.user_a)
        return MoovAccountCapabilitiesListView.as_view()(
            request, account_uid=account_uid
        )

    @patch("weapi.django_rest.views.moov_money.account_settings._convert_moov_result")
    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_flags_terms_of_service_as_due(self, mock_client, mock_convert):
        mock_convert.return_value = [
            {
                "capability": "wallet",
                "status": "pending",
                "requirements": {
                    "currentlyDue": ["account.tos-acceptance", "business.ein"],
                    "errors": [],
                },
            }
        ]
        res = self._get("acct_A")

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["terms_of_service_due"])
        self.assertEqual(
            res.data["currently_due"], ["account.tos-acceptance", "business.ein"]
        )

    @patch("weapi.django_rest.views.moov_money.account_settings._convert_moov_result")
    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_terms_not_due_when_absent(self, mock_client, mock_convert):
        mock_convert.return_value = [
            {
                "capability": "transfers",
                "status": "enabled",
                "requirements": {"currentlyDue": [], "errors": []},
            }
        ]
        res = self._get("acct_A")

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["terms_of_service_due"])

    @patch("weapi.django_rest.views.moov_money.account_settings.moov_client")
    def test_cannot_read_another_companys_capabilities(self, mock_client):
        res = self._get("acct_B")

        self.assertEqual(res.status_code, 404)
        mock_client.assert_not_called()
