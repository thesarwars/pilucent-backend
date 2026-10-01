import os
import csv
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription
from django.http import HttpResponse

from transactionio.models import TransactionInformation
from transactionio.transaction_extractor import process_pdf as transaction_process_pdf
from transactionio.transaction_categorizer import process_transactions
from ...serializers.transactions.pdf_transactions import (
    PrivateTransactionInformationSerializer,
)

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.country_code import CountryCode
from plaid.model.products import Products
from datetime import datetime, timedelta

PLAID_CLIENT_ID = os.environ.get("PLAID_CLIENT_ID")
PLAID_SECRET = os.environ.get("PLAID_SECRET")

# BR-24. The host was pinned to `plaid.Environment.Production` in source, so any
# deployment that set PLAID_CLIENT_ID talked to the real thing -- staging, a
# developer's laptop, a test runner with the variable exported.
#
# Sandbox is the default deliberately. The failure mode of defaulting to
# Production is moving real money against a real institution; the failure mode
# of defaulting to Sandbox is a call that does not work until somebody sets the
# variable, which announces itself.
_PLAID_ENVIRONMENTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}
PLAID_ENV = _PLAID_ENVIRONMENTS.get(
    os.environ.get("PLAID_ENVIRONMENT", "sandbox").strip().lower(),
    plaid.Environment.Sandbox,
)

configuration = plaid.Configuration(
    host=PLAID_ENV,
    api_key={
        'clientId': PLAID_CLIENT_ID,
        'secret': PLAID_SECRET,
    }
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)


# `plaid_integration_view` was here: an unauthenticated Django view rendering a
# Plaid Link demo page at /plaid-test/. Removed with its template and route.
#
# It had no authentication of any kind, and it could not work either -- the
# template fetched `/create_link_token` and `/exchange_public_token` at the
# root, while the real endpoints are DRF actions under
# /api/v1/we/transactions/. It was an open door onto nothing.
#
# The Plaid actions on the viewset below are a separate matter and stay: they
# inherit the viewset's permission classes, added in `7f4ee89c`. What they still
# do NOT do is persist anything -- `exchange_public_token` returns the access
# token to the browser and stores no Item, cursor or webhook. That is a build,
# not a fix, and it is deferred with the rest of the feed work.


class TransactionInformationViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing, processing, and upserting transaction information.

    The permission classes are not decoration. This viewset resolved to the
    project default -- `IsAuthenticated` alone -- while every sibling view in
    the module declares `HaveSubscription` + `IsGroupPermission` with the
    `is_bank_transaction` feature gate. Any authenticated user of any company on
    any plan could therefore reach a full CRUD surface over imported statement
    lines, including the fields the reconciliation close path depends on.
    """

    serializer_class = PrivateTransactionInformationSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_bank_transaction"

    def get_queryset(self):
        company = self.request.user.get_active_company()
        return TransactionInformation.objects.filter(company=company)

    @action(detail=False, methods=['post'], url_path='upload-and-process-pdf', url_name='upload_and_process_pdf')
    def upload_and_process_pdf(self, request):
        """
        Upload a bank statement PDF, process it using OCR and categorization,
        and return the extracted transaction data for review.
        """
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"error": "No file uploaded."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Save the uploaded file temporarily
            temp_file_path = os.path.join(
                settings.MEDIA_ROOT, uploaded_file.name)
            with default_storage.open(temp_file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)

            # Process the PDF file to extract transactions via OCR and categorization
            transactions = transaction_process_pdf(temp_file_path)
            categorized_transactions = process_transactions(transactions)

            # Remove the temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            # Return the processed transaction data for the client to review/edit
            return Response(
                {"transactions": categorized_transactions},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    #deprecated
    @action(detail=False, methods=['post'], url_path='upsert-transactions', url_name='upsert_transactions')
    def upsert_transactions(self, request):
        """
        Upsert transaction information.
        The request should include a list of transactions under the "transactions" key.
        For each transaction, update the record if it exists (based on your uniqueness criteria)
        or create a new record if it does not.
        """
        transactions_data = request.data.get("transactions")
        if not transactions_data:
            return Response(
                {"error": "No transaction data provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        company = request.user.get_active_company()
        upserted = []
        errors = []

        for txn_data in transactions_data:
            try:
                # Strip description to avoid mismatches due to whitespace
                description = txn_data.get("description", "").strip()
                date = txn_data.get("date")

                # Uniqueness check based on company + date + description
                unique_fields = {
                    "company": company,
                    "date": date,
                    "description": description,
                }

                defaults = {
                    "received": txn_data.get("received"),
                    "spent": txn_data.get("spent"),
                    # "ending_balance": txn_data.get("ending_balance"),
                    "category": txn_data.get("category"),
                    "is_spam": txn_data.get("is_spam", False),
                    "chart_of_account": txn_data.get("chart_of_account"),
                    # Keep track of file for history/audits
                    # "filename": txn_data.get("filename", ""),
                }

                txn_instance, created = TransactionInformation.objects.update_or_create(
                    **unique_fields,
                    defaults=defaults
                )

                upserted.append({
                    "id": txn_instance.slug,
                    "created": created
                })

            except Exception as e:
                errors.append(str(e))

        if errors:
            return Response(
                {"error": "Some transactions could not be upserted.", "details": errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"message": "Transactions upserted successfully.", "upserted": upserted},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], url_path='create-link-token')
    def create_link_token(self, request):
        try:
            request_data = LinkTokenCreateRequest(
                client_name="Pilucent",
                user=LinkTokenCreateRequestUser(
                    client_user_id=str(request.user.id)),
                products=[Products('transactions')],
                country_codes=[CountryCode('US')],
                language="en"
            )
            response = plaid_client.link_token_create(request_data)
            return Response(response.to_dict(), status=status.HTTP_200_OK)
        except plaid.exceptions.ApiException as e:
            return Response({"error": e.body}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='exchange-public-token')
    def exchange_public_token(self, request):
        public_token = request.data.get("public_token")
        if not public_token:
            return Response({"error": "Public token not provided."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exchange_request = ItemPublicTokenExchangeRequest(
                public_token=public_token)
            exchange_response = plaid_client.item_public_token_exchange(
                exchange_request)
            access_token = exchange_response['access_token']
            return Response({'access_token': access_token}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='get-plaid-transactions')
    def get_plaid_transactions(self, request):
        access_token = request.data.get("access_token")
        if not access_token:
            return Response({"error": "Access token not provided."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_date = (datetime.today() - timedelta(days=30)).date()
            end_date = datetime.today().date()

            request_data = TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date,
                options=TransactionsGetRequestOptions(count=10)
            )
            response = plaid_client.transactions_get(request_data)
            data = response.to_dict()
            transactions = data.get("transactions", [])
            # Format transaction dates
            if "transactions" in data:
                for txn in data["transactions"]:
                    if txn.get("date"):
                        txn["date"] = datetime.strptime(
                            str(txn["date"]), "%Y-%m-%d").strftime("%Y-%m-%d")

            # self.export_to_csv(transactions)
            
            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def export_to_csv(self, data_list, filename="transactions.csv"):
        """
        Export transaction information to CSV.
        """
        file_path = os.path.join(settings.BASE_DIR, 'tmp', filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    'account_id',
                    'account_owner',
                    'amount',
                    'authorized_date',
                    'authorized_datetime',
                    'category',
                    'category_id',
                    'check_number',
                    'date',
                    'datetime',
                    'iso_currency_code',
                    'merchant_entity_id',
                    'merchant_name',
                    'name',
                    'payment_channel',
                    'pending',
                    'pending_transaction_id',
                    'transaction_id',
                    'transaction_type'
                ]
            )

            for data in data_list:
                writer.writerow(
                    [
                        data.get('account_id'),
                        data.get('account_owner'),
                        data.get('amount'),
                        data.get('authorized_date'),
                        data.get('authorized_datetime'),
                        data.get('category'),
                        data.get('category_id'),
                        data.get('check_number'),
                        data.get('date'),
                        data.get('datetime'),
                        data.get('iso_currency_code'),
                        data.get('merchant_entity_id'),
                        data.get('merchant_name'),
                        data.get('name'),
                        data.get('payment_channel'),
                        data.get('pending'),
                        data.get('pending_transaction_id'),
                        data.get('transaction_id'),
                        data.get('transaction_type')
                    ]
                )
       
        return file_path