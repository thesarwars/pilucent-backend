import logging

from rest_framework import response, status
from rest_framework.views import APIView
from rest_framework import permissions
from django.db import IntegrityError

logger = logging.getLogger(__name__)

from rest_framework.generics import (
    ListAPIView,
    CreateAPIView,
    UpdateAPIView,
)
from employeeio.models import Employee
from moovio_sdk.models import components
from moovmoneyio.django_rest.helpers.moov_connection import moov_client, moov_call
from moovmoneyio.django_rest.helpers.convert_moov_response import _convert_moov_result
from moovmoneyio.models import MoovAccountSettings, MoovBankAccountSettings
from moovmoneyio.choices import (
    MoovAccountBankAccountSettingsStatusChoices,
    MoovBankAccountKindChoices,
)


class MoovBankAccountListView(ListAPIView):
    """
    List all Moov bank accounts linked to the user's Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        company = user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return []
        moov_account_uid = moov_account_setting.moov_account_uid

        with moov_client() as moov:
            # moov_call tolerates the SDK failing to parse newer response enums
            # (e.g. an 'instant-bank-credit' payment method) by using the raw body.
            data = moov_call(
                lambda: moov.bank_accounts.list(account_id=moov_account_uid)
            )

        # Normalize to a list for DRF pagination. Common SDK shapes are:
        # - a list
        # - a dict like {'bankAccounts': [...]} or {'bank_accounts': [...]}
        if isinstance(data, list):
            return data

        # simple behavior: only accept list results from the SDK; otherwise
        # return an empty list so DRF pagination doesn't fail.
        if isinstance(data, list):
            return data
        return []

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(page)

        return response.Response(queryset, status=status.HTTP_200_OK)


class MoovBankAccountCreateView(CreateAPIView):
    """
    Create a new Moov bank account linked to the user's Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]
    # Using direct model creation for persistence (serializer removed)

    def create(self, request, *args, **kwargs):
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

        payload = request.data or {}
        bank_account_kind = (
            payload.get("bank_account_kind") or MoovBankAccountKindChoices.DESTINATION
        )
        # resolve employee_uid (if provided) to an Employee instance
        employee_uid = payload.get("employee_uid")
        employee_instance = None
        if employee_uid:
            employee_instance = Employee.objects.get(uid=employee_uid, company=company)

        link_bank_account = payload.get("link_bank_account") or payload
        with moov_client() as moov:
            try:
                # moov_call recovers the linked account from the raw response when
                # the SDK can't parse a payment-method type it doesn't know (e.g.
                # 'instant-bank-credit' — the account IS linked, the SDK just lags
                # the API). Otherwise a successful link would surface as a 400.
                data = moov_call(
                    lambda: moov.bank_accounts.link(
                        account_id=moov_account_uid,
                        link_bank_account=link_bank_account,
                        x_wait_for=components.BankAccountWaitFor.PAYMENT_METHOD,
                    )
                )
                # Persist MoovBankAccountSettings from Moov response
                try:
                    bank_uid = data.get("bankAccountID") or data.get("bank_account_id")
                    if bank_uid:
                        # map common fields
                        account_type = data.get("bankAccountType") or data.get(
                            "bank_account_type"
                        )
                        bank_name = data.get("bankName") or data.get("bank_name")
                        holder_name = data.get("holderName") or data.get("holder_name")
                        holder_type = data.get("holderType") or data.get("holder_type")
                        last_four = data.get("lastFourAccountNumber") or data.get(
                            "last_four_account_number"
                        )
                        routing = data.get("routingNumber") or data.get(
                            "routing_number"
                        )

                        status_val = (
                            data.get("status")
                            or MoovAccountBankAccountSettingsStatusChoices.NEW
                        )

                        # Idempotent on the Moov bank id: re-linking the same
                        # bank returns the SAME bankAccountID, so update the
                        # existing row instead of a blind create() that trips the
                        # unique constraint on bank_account_uid.
                        moov_bank_obj, created = (
                            MoovBankAccountSettings.objects.update_or_create(
                                bank_account_uid=str(bank_uid),
                                defaults={
                                    "moov_account_settings": moov_account_setting,
                                    "account_type": account_type,
                                    "account_number": (last_four or None),
                                    "routing_number": routing,
                                    "account_holder_name": holder_name,
                                    "account_holder_type": holder_type,
                                    "bank_name": bank_name,
                                    "status": (
                                        status_val
                                        or MoovAccountBankAccountSettingsStatusChoices.NEW
                                    ),
                                    "created_by": request.user.get_employee(),
                                    "employee": employee_instance,
                                    "bank_account_kind": bank_account_kind,
                                },
                            )
                        )
                        logger.info(
                            "Moov bank account %s: %s",
                            "linked" if created else "re-linked (updated)",
                            bank_uid,
                        )
                except IntegrityError as ie:
                    return response.Response(
                        {"error": True, "message": str(ie)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                except Exception:
                    # ignore persistence errors but continue returning Moov data
                    moov_bank_obj = None

                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_201_CREATED
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountDetailsView(APIView):
    """
    Retrieve details of a specific Moov bank account linked to the user's Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, bank_account_uid, *args, **kwargs):
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
        with moov_client() as moov:
            try:
                response_data = moov.bank_accounts.get(
                    account_id=moov_account_uid,
                    bank_account_id=bank_account_uid,
                )
                data = _convert_moov_result(response_data.result)
                # If Moov reports verification success, update local record
                try:
                    if isinstance(data, dict) and str(data.get("status")).lower() in (
                        "successful",
                        "success",
                    ):
                        # find the local record scoped to this company/employee
                        local_obj = MoovBankAccountSettings.objects.filter(
                            bank_account_uid=bank_account_uid,
                            moov_account_settings__company=company,
                        ).first()
                        if local_obj:
                            local_obj.status = (
                                MoovAccountBankAccountSettingsStatusChoices.ACTIVE
                            )
                            local_obj.save()
                except Exception as _:
                    # don't fail the API if local update fails; proceed to
                    # return the Moov response
                    pass

                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_200_OK
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountInitiateVerificationView(APIView):
    """
    Initiate verification for a specific Moov bank account linked to the user's Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, bank_account_uid, *args, **kwargs):
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
        # update it after a successful verification.
        local_obj = MoovBankAccountSettings.objects.filter(
            moov_account_settings=moov_account_setting,
            bank_account_uid=bank_account_uid,
            moov_account_settings__company=company,
        ).first()
        with moov_client() as moov:
            try:
                response_data = moov.bank_accounts.initiate_verification(
                    account_id=moov_account_uid,
                    bank_account_id=bank_account_uid,
                )
                data = _convert_moov_result(response_data.result)

                if data.get("status") == "new" and local_obj:
                    local_obj.status = (
                        MoovAccountBankAccountSettingsStatusChoices.PENDING
                    )
                    local_obj.save()
                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_200_OK
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountCompleteVerificationView(APIView):
    """
    Complete verification for a specific Moov bank account linked to the user's Moov account.
    """

    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, bank_account_uid, *args, **kwargs):
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

        payload = request.data or {}
        code = payload.get("code")

        local_obj = MoovBankAccountSettings.objects.filter(
            moov_account_settings=moov_account_setting,
            bank_account_uid=bank_account_uid,
            moov_account_settings__company=company,
        ).first()

        with moov_client() as moov:
            try:
                response_data = moov.bank_accounts.complete_verification(
                    account_id=moov_account_uid,
                    bank_account_id=bank_account_uid,
                    code=code,
                )
                data = _convert_moov_result(response_data.result)

                if data.get("status") == "successful" and local_obj:
                    local_obj.status = (
                        MoovAccountBankAccountSettingsStatusChoices.ACTIVE
                    )
                    local_obj.save()
                    if local_obj.employee:
                        local_obj.employee.is_banking_info_verified = True
                        local_obj.employee.save()

                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_200_OK
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountPaymentMethodList(ListAPIView):
    """
    List all Moov bank accounts with 'payment method' list
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        company = user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return response.Response(
                {"error": True, "message": "Moov account settings not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        moov_account_uid = moov_account_setting.moov_account_uid

        with moov_client() as moov:
            try:
                response_data = moov.payment_methods.list(account_id=moov_account_uid)
                try:
                    data = _convert_moov_result(response_data.result)
                except Exception:
                    data = response_data.result

                return response.Response(
                    {"error": False, "data": data}, status=status.HTTP_200_OK
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountPaymentsDetailsView(APIView):
    """
    Retrieve details of a specific Moov bank account linked to the user's Moov account,
    including any associated payment methods.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, bank_account_uid, *args, **kwargs):
        user = request.user
        company = user.get_active_company()

        # Get user's Moov account
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()

        if not moov_account_setting:
            return response.Response(
                {"error": True, "message": "Moov account settings not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        moov_account_uid = moov_account_setting.moov_account_uid

        with moov_client() as moov:
            try:
                # Get bank account details
                bank_account_response = moov.bank_accounts.get(
                    account_id=moov_account_uid,
                    bank_account_id=bank_account_uid,
                )
                bank_account_data = _convert_moov_result(bank_account_response.result)

                payment_methods_response = moov.payment_methods.list(
                    account_id=moov_account_uid
                )
                payment_methods = _convert_moov_result(payment_methods_response.result)

                bank_account_payment_methods = [
                    {
                        "payment_method_id": pm.get("payment_method_id"),
                        "payment_method_type": pm.get("payment_method_type"),
                    }
                    for pm in payment_methods
                    if pm.get("bank_account", {}).get("bank_account_id")
                    == bank_account_uid
                ]

                bank_account_data["payment_methods"] = bank_account_payment_methods
                return response.Response(
                    {"error": False, "data": bank_account_data},
                    status=status.HTTP_200_OK,
                )

            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )


class MoovBankAccountDeleteView(APIView):
    """
    Delete a specific Moov bank account linked to the user's Moov account.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, bank_account_uid, *args, **kwargs):
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

        moov_bank_account = MoovBankAccountSettings.objects.filter(
            moov_account_settings=moov_account_setting,
            bank_account_uid=bank_account_uid,
            moov_account_settings__company=company,
        ).first()

        if not moov_bank_account:
            return response.Response(
                {"detail": "Bank account not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        with moov_client() as moov:
            try:
                response_data = moov.bank_accounts.disable(
                    account_id=moov_account_uid,
                    bank_account_id=bank_account_uid,
                )
                # Assuming success if no exception
                # Update employee's banking info verified status
                if moov_bank_account.employee:
                    moov_bank_account.employee.is_banking_info_verified = False
                    moov_bank_account.employee.save()
                # Delete the moov_bank_account record
                moov_bank_account.delete()

                return response.Response(
                    {"error": False, "message": "Bank account deleted successfully."},
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                return response.Response(
                    {"error": True, "message": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

