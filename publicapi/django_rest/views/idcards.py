"""ID cards, public (docs/backend/id-cards-done.md §7): the verification a QR
code opens, and the signed, short-lived image URLs the app and the
verification page use. Unauthenticated by design; nothing here enumerates.
"""

from django.http import Http404, HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from idcardio.models import MediaAsset
from idcardio.services import ops
from idcardio.services.render import processed_image


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


class PublicCardVerify(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        body, code = ops.verify(token, client_ip(request))
        resp = Response(body, status=code)
        resp["Cache-Control"] = "no-store"
        resp["X-Robots-Tag"] = "noindex"
        return resp


class PublicCardMedia(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, signed):
        found = ops.read_signed(signed)
        if found is None:
            raise Http404
        company_id, uid = found
        a = MediaAsset.objects.filter(company_id=company_id, uid=uid, purged_at__isnull=True).first()
        if a is None:
            raise Http404
        with a.file.open("rb") as f:
            raw = f.read()
        if request.query_params.get("original"):
            data, mime = raw, a.mime_type
        else:
            data, mime = processed_image(raw, a.crop, a.adjustments)
        resp = HttpResponse(data, content_type=mime)
        resp["Cache-Control"] = "private, max-age=300"
        resp["X-Robots-Tag"] = "noindex"
        return resp
