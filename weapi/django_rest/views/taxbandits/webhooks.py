# yourapp/views_webhooks.py
import json
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from taxbanditsio.webhook import TaxBanditsGuardMixin

# ---- Option A: Class-based views (recommended) ----

@method_decorator(csrf_exempt, name="dispatch")
class EfileStatusChangeWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        sub_id = payload.get("SubmissionId") or payload.get("SubmissionID")
        for rec in payload.get("Records") or []:
            rid   = rec.get("RecordId") or rec.get("RecordID")
            recip = rec.get("RecipientId") or rec.get("RecipientID")
            acc   = rec.get("AccountNum")
            status= rec.get("Status")
            code  = rec.get("StatusCode")
            when  = rec.get("StatusTime")
            print(f"[E-File] SubmissionId={sub_id} RecordId={rid} RecipientId={recip} AccountNum={acc} Status={status} Code={code} Time={when}")
        return HttpResponse(status=200)

@method_decorator(csrf_exempt, name="dispatch")
class EfileStateStatusChangeWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        sub_id = payload.get("SubmissionId") or payload.get("SubmissionID")
        for rec in payload.get("Records") or []:
            state = rec.get("State") or payload.get("State")
            status= rec.get("StateStatus") or rec.get("Status")
            when  = rec.get("StatusTime")
            print(f"[State] SubmissionId={sub_id} State={state} Status={status} Time={when}")
        return HttpResponse(status=200)

@method_decorator(csrf_exempt, name="dispatch")
class PdfCompleteWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        sub_id = payload.get("SubmissionId") or payload.get("SubmissionID")
        ftype  = payload.get("FormType")
        for rec in payload.get("Records") or []:
            rid   = rec.get("RecordId") or rec.get("RecordID")
            fname = rec.get("FileName")
            fpath = rec.get("FilePath") or rec.get("PdfUrl") or rec.get("PDFUrl")
            status= rec.get("Status")
            when  = rec.get("StatusTime")
            print(f"[PDF Complete] SubmissionId={sub_id} FormType={ftype} RecordId={rid} FileName={fname} FilePath={fpath} Status={status} Time={when}")
        return HttpResponse(status=200)

@method_decorator(csrf_exempt, name="dispatch")
class W9StatusChangeWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        rid   = payload.get("RecordId") or payload.get("RecordID")
        cert  = payload.get("CertificateStatus") or payload.get("Status")
        pdf   = payload.get("PdfUrl") or payload.get("PDFUrl")
        when  = payload.get("StatusTime")
        print(f"[W-9] RecordId={rid} CertificateStatus={cert} PdfUrl={pdf} Time={when}")
        return HttpResponse(status=200)

@method_decorator(csrf_exempt, name="dispatch")
class TinMatchingWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        rid   = payload.get("RecordId") or payload.get("RecordID")
        code  = payload.get("TINStatusCode") or payload.get("StatusCode")
        label = payload.get("TINStatus") or payload.get("Status")
        msg   = payload.get("TINStatusMsg") or payload.get("Message")
        print(f"[TIN Match] RecordId={rid} Code={code} Status={label} Msg={msg}")
        return HttpResponse(status=200)

@method_decorator(csrf_exempt, name="dispatch")
class BusinessCompleteWebhookView(TaxBanditsGuardMixin, APIView):
    permission_classes = []
    def post(self, request, *args, **kwargs):
        payload = self._validate_and_get_payload(request)
        if isinstance(payload, HttpResponse): return payload
        biz_id = payload.get("BusinessId") or payload.get("BusinessID")
        name   = payload.get("BusinessName")
        when   = payload.get("StatusTime") or payload.get("CreatedTime")
        print(f"[Business Complete] BusinessId={biz_id} BusinessName={name} Time={when} PayloadKeys={list(payload.keys())}")
        return HttpResponse(status=200)
