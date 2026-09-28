import logging
import requests
from rest_framework import response, status
from rest_framework.views import APIView
from rest_framework import permissions
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response

from taxbanditsio.ownership import owns_any_return

from taxbanditsio.utils import get_access_token, start_8453_emp, get_signature_status



logger = logging.getLogger(__name__)

class Start8453EmpView(APIView):

    def post(self, request):
        token = get_access_token()
        company = request.user.get_active_company()
        payload = request.data
        print("Request data:", payload)
        if not isinstance(payload, dict):
            return Response(
                {"detail": "JSON payload expected"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = start_8453_emp(token, payload)
        except requests.HTTPError as e:
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
            return Response(error_detail, status=e.response.status_code)
        return Response(result, status=status.HTTP_200_OK)


class SignatureStatusView(APIView):
    def get(self, request):
        token = get_access_token()
        record_id = request.query_params.get("record_id")
        if not record_id:
            return Response(
                {"detail": "record_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Not form-specific: an 8453-EMP signature belongs to whichever return
        # it authorises, so either form's record id is accepted -- but it must
        # be one this company filed.
        if not owns_any_return(
            request.user.get_active_company(), record_id=record_id
        ):
            logger.warning(
                "TaxBandits signature status denied: user=%s record_id=%s not "
                "owned by their company",
                request.user.pk,
                record_id,
            )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            result = get_signature_status(token, record_id)
            print("Signature status retrieved:", result)
        except requests.HTTPError as e:
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
            return Response(error_detail, status=e.response.status_code)
        return Response(result, status=status.HTTP_200_OK)
