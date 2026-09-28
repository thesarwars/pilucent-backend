import logging
from rest_framework import response, status
from rest_framework.views import APIView
from rest_framework import permissions
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from taxbanditsio.utils import (
    get_access_token,
    list_businesses,
    get_business,
    create_business,
    update_business,
    delete_business,
)

from taxbanditsio.models import TaxBanditsBusinessAccount
from taxbanditsio.ownership import company_business_ids
from weapi.django_rest.serializers.taxbandits.business import (
    TaxBanditsBusinessCreateSerializer,
    TaxBanditsBusinessUpdateSerializer,
) 



logger = logging.getLogger(__name__)

def _own_business_entries(payload, owned_ids):
    """Keep only the entries whose business id this company owns.

    Fails CLOSED. `list_businesses` pages the shared TaxBandits account, so an
    unrecognised response shape must yield nothing rather than pass the whole
    platform through -- the failure mode this function exists to prevent is
    exactly "we did not recognise the field, so we returned everything".

    Matches any key whose name contains "businessid", because the upstream
    field name is not pinned by anything on our side.
    """
    if not isinstance(payload, dict):
        return payload if not payload else None

    def owned(entry):
        if not isinstance(entry, dict):
            return False
        return any(
            str(v) in owned_ids
            for k, v in entry.items()
            if "businessid" in k.replace("_", "").lower()
        )

    return {
        key: [e for e in value if owned(e)] if isinstance(value, list) else value
        for key, value in payload.items()
    }


class GetBusinessListView(APIView):
    """List the caller's businesses -- not the platform's.

    `get_access_token()` authenticates as Balanzify, not as the company, so
    `list_businesses` returns every business registered on the shared account:
    legal name, EIN, address, contact, for every tenant. This endpoint required
    no identifier at all, so nothing had to be guessed to read them.

    The upstream call is kept so the response keeps its paging envelope and
    upstream fields, and the result is filtered to the ids this company owns.
    """

    def get(self, request):
        owned_ids = company_business_ids(request.user.get_active_company())
        if not owned_ids:
            return Response(
                {"message": "no businesses found", "error": True},
                status=status.HTTP_404_NOT_FOUND,
            )
        token = get_access_token()
        page = request.GET.get("Page", "1")
        page_size = request.GET.get("PageSize", "10")
        from_date = request.GET.get("FromDate")
        to_date = request.GET.get("ToDate")

        try:
            resp = list_businesses(
                token,
                page=page,
                page_size=page_size,
                from_date=from_date,
                to_date=to_date,
            )
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "no businesses found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(
                {"detail": "upstream error", "error": err_msg},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        filtered = _own_business_entries(resp, owned_ids)
        if filtered is None:
            logger.error(
                "TaxBandits business list returned an unrecognised shape; "
                "refusing rather than passing the platform-wide list through"
            )
            return Response(
                {"message": "no businesses found", "error": True},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(filtered, status=status.HTTP_200_OK)


class GetBusinessDetailView(APIView):
    def get(self, request, *args, **kwargs):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()
        if not tb_business:
            return Response(
                {
                    "message": "no businesses found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            result = get_business(token, tb_business.tb_business_id)
        except Exception as e:
            return Response(
                {
                    "message": "no businesses found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result, status=status.HTTP_200_OK)


class CreateBusinessView(APIView):
    def post(self, request):
        token = get_access_token()
        business_data = request.data
        if not business_data:
            return Response(
                {"detail": "Business data is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        company = request.user.get_active_company()
        if TaxBanditsBusinessAccount.objects.filter(company=company).exists():
            return Response(
                {"detail": "Company already has a TaxBandits business account"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = create_business(token, business_data)
        except Exception as e:
            # The upstream URL and body used to be returned to the caller.
            # Both are written by TaxBandits about whatever record was asked
            # for, so on a near-miss they described somebody else's filing --
            # and the URL carries the submission id. Logged for us, not
            # returned to them.
            logger.warning(
                "TaxBandits upstream error %s %s: %s",
                e.response.status_code,
                e.response.url,
                e.response.text,
            )
            error_detail = {
                "detail": "upstream HTTP error",
                "status_code": e.response.status_code,
                "reason": e.response.reason,
            }
            return Response(
                {"error": error_detail},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Create TaxBanditsBusinessAccount
        tb_business_id = result.get("BusinessId")
        if business_data.get("IsForeign"):
            address = business_data.get("ForeignAddress", {})
            state_key = "ProvinceOrStateNm"
            zip_key = "PostalCd"
        else:
            address = business_data.get("USAddress", {})
            state_key = "State"
            zip_key = "ZipCd"
        mapped_data = {
            "legal_name": business_data.get("BusinessNm"),
            "payer_ref": business_data.get("PayerRef"),
            "ein_or_ssn": business_data.get("EINorSSN"),
            "email": business_data.get("Email"),
            "contact_name": business_data.get("ContactNm"),
            "contact_phone": business_data.get("Phone"),
            "address1": address.get("Address1"),
            "address2": address.get("Address2"),
            "city": address.get("City"),
            "state": address.get(state_key),
            "zip": address.get(zip_key),
            "tb_business_id": tb_business_id,
        }
        print("mapped_data:", mapped_data)
        serializer = TaxBanditsBusinessCreateSerializer(
            data=mapped_data, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()

        return Response(result, status=status.HTTP_200_OK)


class DeleteBusinessDetailView(APIView):
    def get(self, request, *args, **kwargs):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()
        is_force_delete = request.GET.get("isForceDelete", "True").lower() == "true"
        if not tb_business:
            return Response(
                {
                    "message": "no businesses found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = delete_business(
                token,
                tb_business.tb_business_id,
                tb_business.ein_or_ssn,
                is_force_delete,
            )
            # Delete the local TaxBanditsBusinessAccount after successful API delete
            tb_business.delete()
        except Exception as e:
            return Response(
                {
                    "message": "no businesses found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result, status=status.HTTP_200_OK)


class UpdateBusinessView(APIView):
    def put(self, request):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()
        if not tb_business:
            return Response(
                {
                    "message": "no businesses found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        business_data = request.data.copy()
        business_data["BusinessId"] = tb_business.tb_business_id
        try:
            result = update_business(token, business_data)
        except Exception as e:
            # The upstream URL and body used to be returned to the caller.
            # Both are written by TaxBandits about whatever record was asked
            # for, so on a near-miss they described somebody else's filing --
            # and the URL carries the submission id. Logged for us, not
            # returned to them.
            logger.warning(
                "TaxBandits upstream error %s %s: %s",
                e.response.status_code,
                e.response.url,
                e.response.text,
            )
            error_detail = {
                "detail": "upstream HTTP error",
                "status_code": e.response.status_code,
                "reason": e.response.reason,
            }
            return Response(
                {"error": error_detail},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Update TaxBanditsBusinessAccount
        if business_data.get("IsForeign"):
            address = business_data.get("ForeignAddress", {})
            state_key = "ProvinceOrStateNm"
            zip_key = "PostalCd"
        else:
            address = business_data.get("USAddress", {})
            state_key = "State"
            zip_key = "ZipCd"
        mapped_data = {
            "legal_name": business_data.get("BusinessNm"),
            "payer_ref": business_data.get("PayerRef"),
            "ein_or_ssn": business_data.get("EINorSSN"),
            "email": business_data.get("Email"),
            "contact_name": business_data.get("ContactNm"),
            "contact_phone": business_data.get("Phone"),
            "address1": address.get("Address1"),
            "address2": address.get("Address2"),
            "city": address.get("City"),
            "state": address.get(state_key),
            "zip": address.get(zip_key),
            "tb_business_id": tb_business.tb_business_id,
        }
        serializer = TaxBanditsBusinessUpdateSerializer(
            tb_business, data=mapped_data, context={"request": request}, partial=True
        )
        if serializer.is_valid():
            serializer.save()

        return Response(result, status=status.HTTP_200_OK)
