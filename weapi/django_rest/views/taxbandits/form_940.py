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
    get_940_form_list,
    get_form_940_details,
    create_form_940,
    post_form_940_transmit,
    get_form_940_pdf,
)

from taxbanditsio.ownership import owns_940, extract_submission_id

from taxbanditsio.models import TaxBanditsBusinessAccount, TaxBanditsReturn940


from weapi.django_rest.serializers.taxbandits.form_940 import (
    TaxBanditsReturn940CreateSerializer,
)



logger = logging.getLogger(__name__)

class GetForm940ListView(APIView):
    def get(self, request):
        token = get_access_token()
        company = request.user.get_active_company()
        tb_business = TaxBanditsBusinessAccount.objects.filter(
            company=company,
        ).first()

        try:
            resp = get_940_form_list(
                token,
                business_id=tb_business.tb_business_id,
            )
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                # custom message on not found
                return Response(
                    {
                        "message": "no 940 forms found",
                        "error": True,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        return Response(resp, status=status.HTTP_200_OK)


class GetForm940DetailsView(APIView):
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
        if not owns_940(
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
            result = get_form_940_details(
                token,
                submission_id=submission_id,
                record_ids=record_ids,
            )
        except Exception as e:
            return Response(
                {
                    "message": "no 940 forms found",
                    "error": True,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result, status=status.HTTP_200_OK)


class CreateForm940View(APIView):
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
        try:
            result = create_form_940(token, payload)
            print("Form 940 created:", result)
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
        except Exception as e:
            print("Error creating Form 940:", str(e))
            return Response(
                {"detail": "upstream error", "error": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        # Create TaxBanditsReturn940 instance
        # Extract RecordId from nested structure
        record_id = None
        if (
            result.get("Form940Records")
            and result["Form940Records"].get("SuccessRecords")
            and len(result["Form940Records"]["SuccessRecords"]) > 0
        ):
            record_id = result["Form940Records"]["SuccessRecords"][0].get("RecordId")

        # Extract tax year from payload nested structure
        tax_year = None
        if (
            payload.get("Form940Records")
            and len(payload["Form940Records"]) > 0
            and payload["Form940Records"][0].get("ReturnHeader")
        ):
            tax_year = payload["Form940Records"][0]["ReturnHeader"].get("TaxYr")

        data = {
            "tax_year": tax_year,
            "record_id": record_id,
            "submission_id": result.get("SubmissionId"),
            "pdf_url": result.get("PdfUrl", ""),
            "business_account": tb_business.pk,
        }
        print("Creating TaxBanditsReturn940 with data:", data)
        serializer = TaxBanditsReturn940CreateSerializer(
            data=data, context={"request": request}
        )
        if serializer.is_valid():
            tax_return = serializer.save()
            print("TaxBanditsReturn940 created successfully:", tax_return.uid)
        else:
            print("Serializer errors:", serializer.errors)
        return Response(result, status=status.HTTP_200_OK)


class CreateForm940TransmitView(APIView):
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
        if not submission_id or not owns_940(
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
            res = post_form_940_transmit(token, payload)
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


class GetForm940PdfView(APIView):
    def get(self, request, *args, **kwargs):
        submission_id = kwargs.get("SubmissionId") or request.GET.get("SubmissionId")
        record_ids = kwargs.get("RecordIds") or request.GET.get("RecordIds")
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
        if not owns_940(
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
            resp = get_form_940_pdf(token, submission_id, record_ids)
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
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(resp, status=status.HTTP_200_OK)


