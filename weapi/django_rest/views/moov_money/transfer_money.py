import logging
import uuid
import time
from decimal import Decimal, ROUND_HALF_UP

from rest_framework import response, status
from rest_framework.views import APIView
from rest_framework import permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings

from rest_framework.generics import (
    ListAPIView,
    CreateAPIView,
    RetrieveAPIView,
    get_object_or_404,
)
from weapi.django_rest.serializers.moov_money.transfer_money import (
    MoovTransferListDetailsSerializer,
)
import json

from moovmoneyio.django_rest.helpers.moov_connection import (
    moov_client,
    moov_call,
    describe_moov_error,
)
from moovmoneyio.django_rest.helpers.transfer_timeline import (
    build_transfer_timeline,
    build_transfer_details,
)
from moovmoneyio.django_rest.helpers.convert_moov_response import _convert_moov_result
from moovio_sdk.models import errors as moov_errors
from moovmoneyio.models import (
    MoovAccountSettings,
    MoovBankAccountSettings,
    MoovTransfers,
)
from moovmoneyio.choices import (
    MoovBankAccountKindChoices,
    MoovTransferStatusChoices,
)

logger = logging.getLogger(__name__)

# Where callers of the deprecated batch transfer endpoint should move to.
_TRANSFER_SUCCESSOR = "/api/v1/we/payroll/salary-process/{uid}/pay"


class MoovTransferListView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            user = request.user
            company = user.get_active_company()
            moov_account_setting = MoovAccountSettings.objects.filter(
                company=company
            ).first()
            if not moov_account_setting:
                return response.Response(
                    {"detail": "Moov account settings not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            moov_account_uid = moov_account_setting.moov_account_uid

            # pagination params
            skip = int(request.query_params.get("skip", 0))
            count = int(request.query_params.get("count", 50))
            transfer_status = str(request.query_params.get("status", "completed"))

            with moov_client() as moov:
                res = moov.transfers.list(
                    account_id=moov_account_uid,
                    skip=skip,
                    count=count,
                    status=transfer_status,
                )

            try:
                data = _convert_moov_result(res.result)
            except Exception:
                data = res.result

            return response.Response(
                {"error": False, "data": data}, status=status.HTTP_200_OK
            )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovTransferCancellationView(APIView):
    """POST /moov-money/transfer/cancellation/{transfer_uid} — cancel a transfer.

    Cancellation is only possible while the transfer is still cancellable (e.g.
    PENDING, before the ACH debit originates); Moov returns the cancellation's
    status. Scoped to the caller's company Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, transfer_uid: str = None, *args, **kwargs):
        if not transfer_uid:
            return response.Response(
                {"error": True, "message": "transfer_uid is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company = request.user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return response.Response(
                {"detail": "Moov account settings not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        moov_account_uid = moov_account_setting.moov_account_uid

        try:
            with moov_client() as moov:
                # Use the CALLER's Moov account (not the platform account) so a
                # company can only cancel its own transfers.
                data = moov_call(
                    lambda: moov.transfers.create_cancellation(
                        account_id=moov_account_uid, transfer_id=transfer_uid
                    )
                )

            cancel_status = (data or {}).get("status")
            # Reflect a confirmed cancellation locally right away; the webhook
            # still reconciles the final state.
            if str(cancel_status).lower() in ("completed", "canceled", "cancelled"):
                MoovTransfers.objects.filter(
                    company=company, moov_transfer_uid=transfer_uid
                ).update(status=MoovTransferStatusChoices.CANCELED)

            logger.info(
                "Moov transfer cancellation: transfer=%s status=%s",
                transfer_uid, cancel_status,
            )
            return response.Response(
                {"error": False, "data": data}, status=status.HTTP_201_CREATED
            )
        except moov_errors.MoovError as exc:
            detail = describe_moov_error(exc)
            logger.error(
                "Moov transfer cancellation failed: transfer=%s %s",
                transfer_uid,
                json.dumps(detail, default=str),
            )
            return response.Response(
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected error cancelling transfer %s", transfer_uid)
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovTransferCancellationDetailView(APIView):
    """
    Retrieve details for a transfer cancellation: calls
    moov.transfers.get_cancellation(account_id, transfer_id, cancellation_id)
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(
        self,
        request,
        transfer_uid: str = None,
        cancellation_uid: str = None,
        *args,
        **kwargs,
    ):
        try:
            user = request.user
            company = user.get_active_company()
            moov_account_setting = MoovAccountSettings.objects.filter(
                company=company
            ).first()
            if not moov_account_setting:
                return response.Response(
                    {"detail": "Moov account settings not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            moov_account_uid = moov_account_setting.moov_account_uid

            if not transfer_uid or not cancellation_uid:
                return response.Response(
                    {
                        "error": True,
                        "message": "transfer_uid and cancellation_id are required",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with moov_client() as moov:
                res = moov.transfers.get_cancellation(
                    account_id=moov_account_uid,
                    transfer_id=transfer_uid,
                    cancellation_id=cancellation_uid,
                )
                try:
                    data = _convert_moov_result(res.result)
                except Exception:
                    data = res.result

                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_200_OK
                )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovTransferDetailView(APIView):
    """GET /moov-money/transfer/detail/{transfer_uid}.

    Returns the transfer shaped for the detail screen — payment summary
    (amount / fees / net), From/To banks, the ACH debit block (company name,
    hold, SEC code, trace number) and metadata — alongside the raw Moov object.
    Scoped to the caller's company Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, transfer_uid: str, *args, **kwargs):
        company = request.user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return response.Response(
                {"detail": "Moov account settings not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        moov_account_uid = moov_account_setting.moov_account_uid

        try:
            with moov_client() as moov:
                data = moov_call(
                    lambda: moov.transfers.get(
                        account_id=moov_account_uid, transfer_id=transfer_uid
                    )
                )
            return response.Response(
                {
                    "error": False,
                    "details": build_transfer_details(data),
                    "data": data,
                },
                status=status.HTTP_200_OK,
            )
        except moov_errors.MoovError as exc:
            detail = describe_moov_error(exc)
            logger.error(
                "Moov transfer detail failed: transfer=%s %s",
                transfer_uid,
                json.dumps(detail, default=str),
            )
            return response.Response(
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected error fetching transfer detail %s", transfer_uid)
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovTransferTimelineView(APIView):
    """GET /moov-money/transfer/detail/{transfer_uid}/timeline.

    A Moov-dashboard-style status timeline (Transfer created -> ACH debit
    originated -> ACH credit initiated -> Completed) built live from the Moov
    transfer object. Scoped to the caller's company Moov account, so a caller
    can only read their own transfers.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, transfer_uid: str, *args, **kwargs):
        company = request.user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return response.Response(
                {"detail": "Moov account settings not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        moov_account_uid = moov_account_setting.moov_account_uid

        try:
            with moov_client() as moov:
                # moov_call survives the SDK failing to parse newer response
                # enums (e.g. an 'instant-bank-credit' payment method).
                data = moov_call(
                    lambda: moov.transfers.get(
                        account_id=moov_account_uid, transfer_id=transfer_uid
                    )
                )
            return response.Response(
                {
                    "error": False,
                    "data": {
                        "transfer_uid": transfer_uid,
                        "status": data.get("status"),
                        "amount": data.get("amount"),
                        "timeline": build_transfer_timeline(data),
                    },
                },
                status=status.HTTP_200_OK,
            )
        except moov_errors.MoovError as exc:
            detail = describe_moov_error(exc)
            logger.error(
                "Moov transfer timeline failed: transfer=%s %s",
                transfer_uid,
                json.dumps(detail, default=str),
            )
            return response.Response(
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected error building transfer timeline %s", transfer_uid
            )
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# class MoovTransferCreateView(CreateAPIView):
#     permission_classes = [permissions.IsAuthenticated]

#     def post(self, request, *args, **kwargs):
#         payload = request.data or {}
#         user = request.user
#         company = user.get_active_company()
#         print("payload---------", payload)
#         # Get the company's Moov account settings
#         moov_account_setting = MoovAccountSettings.objects.filter(
#             company=company
#         ).first()
#         if not moov_account_setting:
#             return response.Response(
#                 {"detail": "Moov account settings not found."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )
#         moov_account_uid = moov_account_setting.moov_account_uid
#         # Support accepting a list of transfers or a single transfer.
#         # Payload accepted shapes:
#         #  - [{"bank_account_uid": "...","amount": 12.3, ...}, {...}]
#         #  - {"transfers": [...]}  (dict with transfers list)
#         #  - {"bank_account_uid": ..., "amount": ...} (single transfer dict)
#         if isinstance(payload, list):
#             transfers = payload
#             top_level_delay = request.query_params.get("delay", 1.5)
#         elif isinstance(payload, dict):
#             if isinstance(payload.get("transfers"), list):
#                 transfers = payload.get("transfers")
#             else:
#                 transfers = [payload]
#             top_level_delay = payload.get(
#                 "delay", request.query_params.get("delay", 1.5)
#             )
#         else:
#             return response.Response(
#                 {"error": True, "message": "Invalid payload format."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         # Find source bank account
#         source_bank_account = MoovBankAccountSettings.objects.filter(
#             moov_account_settings=moov_account_setting,
#             bank_account_kind=MoovBankAccountKindChoices.SOURCE,
#         ).first()
#         print("source_bank_account", source_bank_account)
#         if not source_bank_account:
#             return response.Response(
#                 {
#                     "error": True,
#                     "message": "No source bank account found for transfers",
#                 },
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         # We'll call Moov once, cache payment methods.
#         # Collect payment methods keyed by bank_account_id so we only attempt
#         # transfers for the destination payment methods that belong to the
#         # current transfer's bank account (avoid cross-product duplication).
#         source_payment_method_id = None
#         payment_methods_map = {}

#         # collect requested bank_account_uids from payload so we only keep PMs for them
#         requested_bank_ids = set()
#         for t in transfers:
#             if isinstance(t, dict):
#                 b = t.get("bank_account_uid")
#                 if b:
#                     requested_bank_ids.add(b)

#         with moov_client() as moov:
#             try:
#                 payment_methods_response = moov.payment_methods.list(
#                     account_id=moov_account_uid
#                 )
#                 payment_methods = _convert_moov_result(payment_methods_response.result)

#                 for pm in payment_methods:
#                     bank_id = pm.get("bank_account", {}).get("bank_account_id")
#                     pm_type = pm.get("payment_method_type")
#                     pm_id = pm.get("payment_method_id")

#                     # identify source payment method id only if it's an ACH debit funding method
#                     if (
#                         pm_type in ["ach-debit-fund"]
#                         and bank_id == source_bank_account.bank_account_uid
#                         and not source_payment_method_id
#                     ):
#                         source_payment_method_id = pm_id

#                     # collect destination ACH credit same-day method ids per bank
#                     # only for bank accounts requested in the payload and configured as DESTINATION
#                     if (
#                         pm_type == "ach-credit-same-day"
#                         and bank_id in requested_bank_ids
#                     ):
#                         dest_account = MoovBankAccountSettings.objects.filter(
#                             moov_account_settings=moov_account_setting,
#                             bank_account_uid=bank_id,
#                             bank_account_kind=MoovBankAccountKindChoices.DESTINATION,
#                         ).first()
#                         if dest_account:
#                             lst = payment_methods_map.setdefault(bank_id, [])
#                             if pm_id not in lst:
#                                 lst.append(pm_id)

#                 if not source_payment_method_id:
#                     return response.Response(
#                         {
#                             "error": True,
#                             "message": "No ACH debit payment method found for source bank account",
#                         },
#                         status=status.HTTP_400_BAD_REQUEST,
#                     )

#                 results = []
#                 print("payment_methods_map", payment_methods_map)
#                 print("transfers", transfers)
#                 print("top_level_delay", top_level_delay)
#                 print("source_payment_method_id ----->", source_payment_method_id)
#                 # Process each requested transfer
#                 for item in transfers:
#                     # validate item
#                     if not isinstance(item, dict):
#                         results.append(
#                             {
#                                 "error": True,
#                                 "message": "Invalid transfer item",
#                                 "item": item,
#                             }
#                         )
#                         continue

#                     bank_account_uid = item.get("bank_account_uid")
#                     amount = item.get("amount")
#                     description = item.get("description")
#                     bank_account_kind = item.get(
#                         "bank_account_kind", MoovBankAccountKindChoices.DESTINATION
#                     )
#                     delay = float(item.get("delay", top_level_delay))

#                     if not bank_account_uid or amount is None:
#                         results.append(
#                             {
#                                 "bank_account_uid": bank_account_uid,
#                                 "error": True,
#                                 "message": "bank_account_uid and amount are required for each transfer",
#                             }
#                         )
#                         continue

#                     # Ensure destination bank account exists in our DB and is the expected kind
#                     destination_bank_account = MoovBankAccountSettings.objects.filter(
#                         moov_account_settings=moov_account_setting,
#                         bank_account_uid=bank_account_uid,
#                         bank_account_kind=bank_account_kind,
#                     ).first()

#                     if not destination_bank_account:
#                         results.append(
#                             {
#                                 "bank_account_uid": bank_account_uid,
#                                 "error": True,
#                                 "message": f"Bank account with UID {bank_account_uid} not found or not a {bank_account_kind} account",
#                             }
#                         )
#                         continue

#                     # use the bank-specific list of destination payment method ids
#                     dest_pms = payment_methods_map.get(bank_account_uid, [])
#                     if not dest_pms:
#                         results.append(
#                             {
#                                 "bank_account_uid": bank_account_uid,
#                                 "error": True,
#                                 "message": "No ACH credit same-day payment methods available",
#                             }
#                         )
#                         continue

#                     # For each destination payment method, attempt transfer
#                     for dest_pm in dest_pms:
#                         transfer_key = str(uuid.uuid4())
#                         try:
#                             res = moov.transfers.create(
#                                 x_idempotency_key=transfer_key,
#                                 account_id="36d656f4-adba-4160-be10-aabe853f3244",
#                                 source={"payment_method_id": source_payment_method_id},
#                                 destination={"payment_method_id": dest_pm},
#                                 amount={"currency": "USD", "value": int(amount * 100)},
#                                 description=(
#                                     description or f"Transfer to {bank_account_uid}"
#                                 ),
#                             )
#                             try:
#                                 # data = _convert_moov_result(getattr(res, "result", res))
#                                 data = _convert_moov_result(res.result)
#                                 print("Moov transfer create response:", data)
#                             except Exception:
#                                 data = getattr(res, "result", res)
#                             results.append(
#                                 {
#                                     "bank_account_uid": bank_account_uid,
#                                     "destination": dest_pm,
#                                     "amount": amount,
#                                     "success": True,
#                                     "data": data,
#                                 }
#                             )
#                         except Exception as exc:
#                             results.append(
#                                 {
#                                     "bank_account_uid": bank_account_uid,
#                                     "destination": dest_pm,
#                                     "amount": amount,
#                                     "error": True,
#                                     "message": str(exc),
#                                 }
#                             )
#                         time.sleep(delay)

#                 return response.Response(
#                     {"error": False, "results": results}, status=status.HTTP_201_CREATED
#                 )

#             except Exception as exc:
#                 return response.Response(
#                     {"error": True, "message": str(exc)},
#                     status=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 )


class MoovTransferCreateView(CreateAPIView):
    """DEPRECATED — use ``POST /payroll/salary-process/{uid}/pay`` instead.

    This batch transfer endpoint moves money without linking to a payroll run,
    with no atomicity and a random idempotency key per call — the combination
    that allowed split-brain double-payments (money moved, the payroll call
    failed, a retry paid again). The payroll pay endpoint validates before moving
    money, is idempotent, records the transfer against the run, and returns a
    receipt. Kept only for backward compatibility; do not build new flows on it.
    """

    permission_classes = [permissions.IsAuthenticated]

    def finalize_response(self, request, resp, *args, **kwargs):
        resp = super().finalize_response(request, resp, *args, **kwargs)
        # RFC 8594 deprecation signalling on every response from this view.
        resp["Deprecation"] = "true"
        resp["Link"] = f'<{_TRANSFER_SUCCESSOR}>; rel="successor-version"'
        resp["Warning"] = (
            '299 - "Deprecated endpoint: use '
            'POST /payroll/salary-process/{uid}/pay"'
        )
        return resp

    def post(self, request, *args, **kwargs):
        logger.warning(
            "DEPRECATED endpoint used: POST /moov-money/transfer/create "
            "(user=%s) — migrate to %s",
            getattr(request.user, "pk", None),
            _TRANSFER_SUCCESSOR,
        )
        transfers = request.data
        if not isinstance(transfers, list):
            return response.Response(
                {"error": True, "message": "Payload must be a list of transfers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        company = user.get_active_company()

        # Get company's Moov account
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return response.Response(
                {"error": True, "message": "Moov account settings not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        moov_account_uid = moov_account_setting.moov_account_uid

        # Get source bank account
        source_bank_account = MoovBankAccountSettings.objects.filter(
            moov_account_settings=moov_account_setting,
            bank_account_kind=MoovBankAccountKindChoices.SOURCE,
        ).first()
        if not source_bank_account:
            return response.Response(
                {"error": True, "message": "No source bank account found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        with moov_client() as moov:
            try:
                # Load all payment methods
                pm_response = moov.payment_methods.list(account_id=moov_account_uid)
                payment_methods = _convert_moov_result(pm_response.result)

                source_payment_method_id = None
                dest_payment_methods = {}

                # Collect payment methods
                for pm in payment_methods:
                    bank_id = pm.get("bank_account", {}).get("bank_account_id")
                    pm_type = pm.get("payment_method_type")
                    pm_id = pm.get("payment_method_id")

                    # Identify source
                    if (
                        pm_type == "ach-debit-fund"
                        and bank_id == source_bank_account.bank_account_uid
                    ):
                        source_payment_method_id = pm_id

                    # Keep one destination PM per bank
                    if pm_type == "ach-credit-same-day":
                        dest_payment_methods[bank_id] = pm_id

                if not source_payment_method_id:
                    return response.Response(
                        {
                            "error": True,
                            "message": "No source ACH debit payment method found",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Process transfers
                for item in transfers:
                    bank_account_uid = item.get("bank_account_uid")
                    employee_uid = item.get("employee_uid", None)
                    amount = item.get("amount")
                    description = item.get(
                        "description", f"Transfer to {bank_account_uid}"
                    )

                    if not bank_account_uid or amount is None:
                        results.append(
                            {
                                "bank_account_uid": bank_account_uid,
                                "error": True,
                                "message": "bank_account_uid and amount are required",
                            }
                        )
                        continue

                    # Validate destination bank account for this employee
                    dest_account = MoovBankAccountSettings.objects.filter(
                        moov_account_settings=moov_account_setting,
                        bank_account_uid=bank_account_uid,
                        bank_account_kind=MoovBankAccountKindChoices.DESTINATION,
                        employee__uid=employee_uid,
                    ).first()

                    if not dest_account:
                        results.append(
                            {
                                "bank_account_uid": bank_account_uid,
                                "error": True,
                                "message": f"No destination bank account found for employee {employee_uid}",
                            }
                        )
                        continue

                    dest_pm = dest_payment_methods.get(bank_account_uid)
                    if not dest_pm:
                        results.append(
                            {
                                "bank_account_uid": bank_account_uid,
                                "error": True,
                                "message": "No ACH credit same-day payment method available",
                            }
                        )
                        continue

                    # Create Moov transfer
                    transfer_key = str(uuid.uuid4())
                    try:
                        res = moov.transfers.create(
                            x_idempotency_key=transfer_key,
                            account_id=settings.MOOV_ACCOUNT_UID,
                            source={"payment_method_id": source_payment_method_id},
                            destination={"payment_method_id": dest_pm},
                            amount={
                                "currency": "USD",
                                # Decimal, not int(float*100), to avoid binary
                                # float truncation (e.g. 12.29 -> 1228).
                                "value": int(
                                    (Decimal(str(amount)) * 100).to_integral_value(
                                        rounding=ROUND_HALF_UP
                                    )
                                ),
                            },
                            description=description,
                        )
                        data = _convert_moov_result(res.result)
                        results.append(
                            {
                                "bank_account_uid": bank_account_uid,
                                "employee_uid": employee_uid,
                                "amount": amount,
                                "success": True,
                                "data": data,
                            }
                        )
                        # Create MoovTransfers record
                        if data:
                            moov_transfer_obj = MoovTransfers.objects.create(
                                moov_transfer_uid=data.get("transfer_id"),
                                amount=amount,
                                currency="USD",
                                description=description,
                                source_bank_account=source_bank_account,
                                destination_bank_account=dest_account,
                                status=MoovTransferStatusChoices.PENDING,
                                employee=dest_account.employee,
                                created_by=user.get_employee(),
                                company=company,
                            )
                    except Exception as exc:
                        results.append(
                            {
                                "bank_account_uid": bank_account_uid,
                                "employee_uid": employee_uid,
                                "amount": amount,
                                "error": True,
                                "message": str(exc),
                            }
                        )

                    # Optional delay to avoid rate limits
                    time.sleep(1.5)

                # Don't report 201/success when every item failed.
                any_success = any(r.get("success") for r in results)
                return response.Response(
                    {"error": not any_success, "results": results},
                    status=(
                        status.HTTP_201_CREATED
                        if any_success
                        else status.HTTP_400_BAD_REQUEST
                    ),
                )

            except Exception as exc:
                return response.Response(
                    {"error": True, "message": str(exc)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )


class MeMoovTransferListView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MoovTransferListDetailsSerializer
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    search_fields = [
        "currency",
        "description",
        "employee__first_name",
        "employee__last_name",
    ]
    filterset_fields = [
        "status",
        "source_bank_account",
        "destination_bank_account",
    ]

    def get_queryset(self):
        return MoovTransfers.objects.filter(
            company=self.request.user.get_active_company()
        )


class MeMoovTransferDetailView(RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MoovTransferListDetailsSerializer

    def get_object(self):
        uid = self.kwargs.get("uid")
        return get_object_or_404(
            MoovTransfers,
            uid=uid,
            company=self.request.user.get_active_company(),
        )
