import logging
import requests
from rest_framework import response, status
from rest_framework.views import APIView
from rest_framework import permissions
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from taxbanditsio.utils import (
    get_access_token,
    get_941_form_list,
    get_941_form_details,
    create_form_941,
    get_941_form_validate,
    post_form_941_transmit,
    get_941_form_pdf,
)

from taxbanditsio.ownership import owns_941, extract_submission_id

from taxbanditsio.models import TaxBanditsBusinessAccount, TaxBanditsReturn941


from weapi.django_rest.serializers.taxbandits.form_941 import (
    TaxBanditsReturn941CreateSerializer,
)



logger = logging.getLogger(__name__)

class GetForm941ListView(APIView):
    def get(self, request):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()

        try:
            resp = get_941_form_list(token, business_id=tb_business.tb_business_id)
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "no 941 forms found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        return Response(resp, status=status.HTTP_200_OK)


class GetForm941DetailsView(APIView):
    def get(self, request, *args, **kwargs):
        submission_id = kwargs.get("SubmissionId")
        if not submission_id:
            return Response(
                {"detail": "SubmissionId is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Ownership before upstream. `get_access_token()` authenticates as the
        # platform, not as this company, so TaxBandits returns whatever id it is
        # given -- the check has to happen here or not at all. It runs before the
        # token call too: no reason to mint a credential for a refused request.
        #
        # 404 rather than 403, matching the Moov account views: a 403 would
        # confirm the submission exists, which is itself a disclosure.
        if not owns_941(
            request.user.get_active_company(), submission_id=submission_id
        ):
            logger.warning(
                "TaxBandits access denied: user=%s requested submission_id=%s "
                "not owned by their company",
                request.user.pk,
                submission_id,
            )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = get_access_token()

        try:
            resp = get_941_form_details(token, submission_id)
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "941 form details not found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
        return Response(resp, status=status.HTTP_200_OK)


class CreateForm941View(APIView):
    def post(self, request):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()
        if not tb_business:
            return Response(
                {"detail": "No business account found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = request.data
        print("Request data:", payload)
        if not isinstance(payload, dict):
            return Response(
                {"detail": "JSON payload expected"}, status=status.HTTP_400_BAD_REQUEST
            )
        # payload["BusinessId"] = tb_business.tb_business_id
        try:
            resp = create_form_941(token, payload)
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
                error_detail,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        # Create TaxBanditsReturn941 instance
        # Extract RecordId from nested structure
        record_id = None
        if (
            resp.get("Form941Records")
            and resp["Form941Records"].get("SuccessRecords")
            and len(resp["Form941Records"]["SuccessRecords"]) > 0
        ):
            record_id = resp["Form941Records"]["SuccessRecords"][0].get("RecordId")

        # Extract tax year and quarter from payload nested structure
        tax_year = None
        quarter = None
        if (
            payload.get("Form941Records")
            and len(payload["Form941Records"]) > 0
            and payload["Form941Records"][0].get("ReturnHeader")
        ):
            tax_year = payload["Form941Records"][0]["ReturnHeader"].get("TaxYr")
            quarter = payload["Form941Records"][0]["ReturnHeader"].get("Quarter")

        data = {
            "tax_year": tax_year,
            "quarter": quarter,
            "record_id": record_id,
            "submission_id": resp.get("SubmissionId"),
            "form941_payload": payload,
            "business_account": tb_business.pk,
        }
        
        serializer = TaxBanditsReturn941CreateSerializer(
            data=data, context={"request": request}
        )
        if serializer.is_valid():
            tax_return = serializer.save()
            print("TaxBanditsReturn941 created successfully:", tax_return.uid)
        else:
            print("Serializer errors:", serializer.errors)
        return Response(resp, status=status.HTTP_200_OK)


class GetForm941ValidateView(APIView):
    def get(self, request, *args, **kwargs):
        submission_id = kwargs.get("SubmissionId")
        record_ids = kwargs.get("RecordIds")
        if not submission_id or not record_ids:
            return Response(
                {"detail": "SubmissionId and RecordIds are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Ownership before upstream. `get_access_token()` authenticates as the
        # platform, not as this company, so TaxBandits returns whatever id it is
        # given -- the check has to happen here or not at all. It runs before the
        # token call too: no reason to mint a credential for a refused request.
        #
        # 404 rather than 403, matching the Moov account views: a 403 would
        # confirm the submission exists, which is itself a disclosure.
        if not owns_941(
            request.user.get_active_company(), submission_id=submission_id
        ):
            logger.warning(
                "TaxBandits access denied: user=%s requested submission_id=%s "
                "not owned by their company",
                request.user.pk,
                submission_id,
            )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = get_access_token()
        try:
            resp = get_941_form_validate(token, submission_id, record_ids)
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "941 form details not found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
        return Response(resp, status=status.HTTP_200_OK)


class CreateForm941TransmitView(APIView):
    def post(self, request):
        payload = request.data
        print("Request data:", payload)
        if not isinstance(payload, dict):
            return Response(
                {"detail": "JSON payload expected"}, status=status.HTTP_400_BAD_REQUEST
            )
        # Transmit files a return with the IRS under the platform credential, so
        # an unscoped payload could transmit another tenant's draft. The id is
        # located rather than assumed, and a payload we cannot identify is
        # refused -- that is precisely the case we cannot authorise.
        submission_id = extract_submission_id(payload)
        if not submission_id or not owns_941(
            request.user.get_active_company(), submission_id=submission_id
        ):
            logger.warning(
                "TaxBandits transmit denied: user=%s payload submission_id=%s "
                "not owned by their company",
                request.user.pk,
                submission_id,
            )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = get_access_token()
        try:
            res = post_form_941_transmit(token, payload)
            print("Form 940 transmitted:", res)
        except requests.HTTPError as e:
            # Return full error details
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
            return Response(error_detail, status=status.HTTP_502_BAD_GATEWAY)
        return Response(res, status=status.HTTP_200_OK)


class GetForm941PDFView(APIView):
    def get(self, request, *args, **kwargs):
        submission_id = kwargs.get("SubmissionId")
        record_ids = kwargs.get("RecordIds")
        if not submission_id or not record_ids:
            return Response(
                {"detail": "SubmissionId and RecordIds are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Ownership before upstream. `get_access_token()` authenticates as the
        # platform, not as this company, so TaxBandits returns whatever id it is
        # given -- the check has to happen here or not at all. It runs before the
        # token call too: no reason to mint a credential for a refused request.
        #
        # 404 rather than 403, matching the Moov account views: a 403 would
        # confirm the submission exists, which is itself a disclosure.
        if not owns_941(
            request.user.get_active_company(), submission_id=submission_id
        ):
            logger.warning(
                "TaxBandits access denied: user=%s requested submission_id=%s "
                "not owned by their company",
                request.user.pk,
                submission_id,
            )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = get_access_token()
        try:
            resp = get_941_form_pdf(token, submission_id, record_ids)
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "941 form PDF not found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({"err_msg": err_msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(resp, status=status.HTTP_200_OK)