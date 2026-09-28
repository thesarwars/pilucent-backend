import logging

from django.conf import settings
from rest_framework import response, status

logger = logging.getLogger(__name__)
from rest_framework.views import APIView
from rest_framework import permissions
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.generics import (
    ListAPIView,
    CreateAPIView,
)
from moovmoneyio.django_rest.helpers.moov_connection import (
    moov_client,
    moov_patch,
    moov_get_oauth_token,
    moov_bearer_from_request,
    build_terms_of_service_body,
    describe_moov_error,
    redact_moov_payload,
)
from moovio_sdk.models import components, errors as moov_errors

from weapi.django_rest.serializers.moov_money.account_settings import (
    MoovAccountCreateSerializer,
    MoovAccountDetailSerializer,
    MoovBankAccountSettingsSerializer,
)
from moovmoneyio.models import MoovAccountSettings, MoovBankAccountSettings
from django.utils.dateparse import parse_datetime
from django.db import IntegrityError

import json
from typing import Any, Dict, List, Optional

from moovmoneyio.django_rest.helpers.industries_to_raw_response import (
    _coerce_industries_from_raw,
    _extract_raw_text_from_exception,
)

from moovmoneyio.django_rest.helpers.convert_moov_response import _convert_moov_result


# _convert_moov_result moved to moovmoneyio.django_rest.helpers.convert_moov_response


class MoovAccessTokenView(APIView):
    """Mint a short-lived Moov OAuth token for THIS company's Moov.js Drop.

    The browser must never hold facilitator credentials or a money-moving token.
    So the secret stays server-side (settings), and the scope is the narrowest
    the Drop needs: profile.write on the caller's OWN account, or /accounts.write
    only while they have no account yet (initial onboarding). Never /transfers.*.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        company = request.user.get_active_company()
        existing = MoovAccountSettings.objects.filter(company=company).first()

        if existing and existing.moov_account_uid:
            scope = f"/accounts/{existing.moov_account_uid}/profile.write"
        else:
            # No account yet — the Drop needs account-write to accept ToS for the
            # account about to be created. Still no transfers scope.
            scope = "/accounts.write"

        try:
            token = moov_get_oauth_token(scope=scope)
            return response.Response(
                {"error": False, "data": {"access_token": token, "scope": scope}},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            logger.exception("Moov access-token mint failed")
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountListView(APIView):
    # Platform-wide: moov.accounts.list() returns EVERY Moov account across ALL
    # tenants, so this stays staff-only (IsAdminUser checks is_staff). Do NOT
    # relax it to is_admin — registration sets is_admin=True on every signup, so
    # that would expose every customer's Moov account to every user.
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        try:
            # optional query param to filter by account type, e.g. ?type=business
            req_type = request.query_params.get("type")
            acct_type = None
            if req_type:
                t = req_type.strip().lower()
                if t == "business":
                    acct_type = components.AccountType.BUSINESS
                elif t == "individual":
                    acct_type = components.AccountType.INDIVIDUAL
                else:
                    return response.Response(
                        {"error": True, "message": f"invalid type '{req_type}'"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            with moov_client() as moov:
                business_list_res = moov.accounts.list(
                    type_=acct_type or components.AccountType.BUSINESS,
                    skip=0,
                    count=0,
                )

            # Convert nested list-of-pairs into JSON-friendly dict/list
            try:
                data = _convert_moov_result(business_list_res.result)
            except Exception:
                data = business_list_res.result

            return response.Response(
                {"error": False, "data": data},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovIndustriesListView(APIView):
    def get(self, request):
        try:
            with moov_client() as moov:
                try:
                    res = moov.industries.list()
                except Exception as exc:
                    raw_text = _extract_raw_text_from_exception(exc)
                    coerced = (
                        _coerce_industries_from_raw(raw_text) if raw_text else None
                    )
                    if coerced is not None:
                        return response.Response(
                            {
                                "error": False,
                                "warning": "Moov industries response schema differed from SDK model; items coerced",
                                "data": coerced,
                            },
                            status=status.HTTP_200_OK,
                        )

                    return response.Response(
                        {
                            "error": False,
                            "data": [],
                            "warning": "Moov industries response validation failed",
                            "raw_error": str(raw_text),
                        },
                        status=status.HTTP_200_OK,
                    )

                # Convert nested list-of-pairs into JSON-friendly dict/list
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


class MoovAccountMeDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            company = request.user.get_active_company()
            obj = MoovAccountSettings.objects.filter(
                company=company,
            ).first()
            if not obj:
                return response.Response(
                    {
                        "error": True,
                        "message": "no MoovAccountSettings found for this user/company",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = MoovAccountDetailSerializer(obj, context={"request": request})
            return response.Response(
                {"error": False, "data": serializer.data},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountDetailsView(APIView):
    # Company admins (every signup carries is_admin, so IsAdminUser/is_staff would
    # 403 them) may read a Moov account — but only their OWN. `account_uid` is
    # caller-supplied, so **ownership is the security boundary here**, not the
    # permission class: prove the uid belongs to the requester's company before
    # asking Moov for it, otherwise any user could read any tenant's account.
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, account_uid: str):
        owns_account = MoovAccountSettings.objects.filter(
            company=request.user.get_active_company(),
            moov_account_uid=account_uid,
        ).exists()
        if not owns_account:
            # 404 rather than 403 so we don't confirm whether the uid exists.
            logger.warning(
                "Moov account details denied: user=%s requested account_uid=%s "
                "not owned by their company",
                request.user.pk,
                account_uid,
            )
            return response.Response(
                {
                    "error": True,
                    "message": "no Moov account found for this company",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with moov_client() as moov:
                acct_res = moov.accounts.get(account_id=account_uid)

            # Convert nested list-of-pairs into JSON-friendly dict/list
            try:
                data = _convert_moov_result(acct_res.result)
            except Exception:
                data = acct_res.result

            return response.Response(
                {"error": False, "data": data},
                status=status.HTTP_200_OK,
            )
        except moov_errors.MoovError as exc:
            detail = describe_moov_error(exc)
            logger.error(
                "Moov account fetch failed: account_uid=%s %s",
                account_uid,
                json.dumps(detail, default=str),
            )
            return response.Response(
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected error fetching Moov account %s", account_uid)
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountCreateView(CreateAPIView):
    serializer_class = MoovAccountCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _accept_terms_of_service(
        self,
        account_uid: str,
        tos_body: Optional[Dict],
        bearer_token: Optional[str] = None,
    ):
        """Apply the Moov.js Drop's ToS token to a freshly created account.

        Moov only accepts a Drop-generated token via PATCH; sending it on create
        is a gated flow that 400s for platforms Moov hasn't authorised. Failure
        here leaves a usable account — the frontend can re-accept via the update
        flow — so it is reported, not raised.
        """
        if not tos_body:
            return {"accepted": False, "reason": "no terms_of_service token supplied"}

        resp = moov_patch(
            f"/accounts/{account_uid}",
            {"termsOfService": tos_body},
            bearer_token=bearer_token,
        )

        if resp.is_success:
            logger.info("Moov terms of service accepted: account_id=%s", account_uid)
            return {"accepted": True}

        detail = resp.text[:500] if resp.text else f"HTTP {resp.status_code}, empty body"
        request_id = resp.headers.get("x-request-id")
        logger.error(
            "Moov terms of service PATCH failed: account_id=%s status=%s "
            "request_id=%s body=%s",
            account_uid,
            resp.status_code,
            request_id,
            detail,
        )
        return {
            "accepted": False,
            "status_code": resp.status_code,
            "request_id": request_id,
            "error": detail,
        }

    def post(self, request, *args, **kwargs):
        # Expect request.data to contain fields for Moov creation. We'll
        # support a minimal shape and pass through optional nested data.
        payload = request.data or {}

        logger.info(
            "Moov account create requested: %s",
            json.dumps(redact_moov_payload(payload), default=str),
        )

        account_type = payload.get("account_type", "BUSINESS")
        acct_type_enum = (
            components.CreateAccountType.BUSINESS
            if str(account_type).strip().upper() == "BUSINESS"
            else components.CreateAccountType.INDIVIDUAL
        )

        profile = payload.get("profile") or {}
        profile_obj = None
        # choose profile shape based on account type; accept either
        # full shape ({'business': {...}}) or bare profile dict and wrap it.
        if isinstance(profile, dict):
            if acct_type_enum == components.CreateAccountType.INDIVIDUAL:
                # if caller already provided {'individual': {...}} keep it,
                # otherwise wrap the dict under 'individual'
                if "individual" in profile:
                    profile_obj = profile
                else:
                    profile_obj = {"individual": profile}
            else:
                # business
                if "business" in profile:
                    profile_obj = profile
                else:
                    profile_obj = {"business": profile}

        metadata = payload.get("metadata")

        # Accepts either {"manual": {...}} (attested — preferred) or {"token": ...}.
        # acceptedIP is taken from THIS request, never from the client body.
        tos_body, tos_error = build_terms_of_service_body(
            payload.get("terms_of_service"), request
        )
        if tos_error:
            return response.Response(
                {"error": True, "message": tos_error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer_support = payload.get("customer_support")
        settings_payload = payload.get("settings")
        mode = payload.get("mode")

        logger.info(
            "Moov account create: tos=%s mode=%s settings=%s",
            (list(tos_body)[0] if tos_body else "none"),
            mode,
            json.dumps(settings_payload, default=str),
        )

        try:
            # NOTE: the terms-of-service token is deliberately NOT sent here.
            # Creating an account *with* a termsOfService token is a gated Moov
            # flow ("not available to everyone ... you will receive a 400 error"),
            # which is what the 400 "server address must not match client address"
            # was. A Moov.js Drop token is meant to be applied afterwards — the docs:
            # "The token can be patched to an account using the accounts PATCH
            # endpoint". ToS also isn't required at creation unless capabilities
            # beyond `transfers` are requested here, and those are requested in a
            # separate call. So: create the account, then PATCH the ToS token.
            with moov_client() as moov:
                res = moov.accounts.create(
                    account_type=acct_type_enum,
                    profile=profile_obj,
                    metadata=metadata,
                    customer_support=customer_support,
                    settings=settings_payload,
                    mode=getattr(components.Mode, str(mode).upper()) if mode else None,
                )

                moov_data = _convert_moov_result(res.result)

            display_name = moov_data.get("displayName") or moov_data.get("display_name")
            account_uid = moov_data.get("accountID") or moov_data.get("account_id")

            logger.info("Moov account created: account_id=%s", account_uid)
            logger.debug(
                "Moov account create response: %s", json.dumps(moov_data, default=str)
            )

            # Persist immediately: the Moov account now exists, so a later failure
            # must not orphan it (a retry would otherwise create a duplicate).
            serializer = self.get_serializer(
                data={
                    "moov_account_uid": account_uid,
                    "moov_account_display_name": display_name,
                },
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # tos_result = self._accept_terms_of_service(account_uid, tos_body)

            return response.Response(
                {
                    "error": False,
                    "moov": moov_data,
                    "saved": serializer.data,
                    # "terms_of_service": tos_result,
                },
                status=status.HTTP_201_CREATED,
            )
        except moov_errors.MoovError as exc:
            # Moov rejected the request. `str(exc)` is just the raw body, which
            # hides the status, the X-Request-ID and the per-field detail (e.g.
            # what exactly was wrong with termsOfService). Log all of it.
            detail = describe_moov_error(exc)
            logger.error(
                "Moov account create failed: %s",
                json.dumps(detail, default=str),
                exc_info=True,
            )
            return response.Response(
                # `message` keeps its existing shape (the raw Moov body) so the
                # frontend's error parsing keeps working; `moov_error` is new.
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected error creating Moov account")
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        # Accept account_uid either from URL kwargs or from request body
        payload = request.data or {}
        account_uid = kwargs.get("account_uid") or payload.get("account_uid")
        if not account_uid:
            return response.Response(
                {
                    "error": True,
                    "message": "account_uid is required (in URL or request body)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # account_uid is caller-supplied, so prove it belongs to this company
        # before patching it at Moov — otherwise any authenticated user could
        # modify any tenant's Moov account through this endpoint.
        if not MoovAccountSettings.objects.filter(
            company=request.user.get_active_company(),
            moov_account_uid=account_uid,
        ).exists():
            logger.warning(
                "Moov account update denied: user=%s account_uid=%s not owned by "
                "their company",
                request.user.pk,
                account_uid,
            )
            return response.Response(
                {"error": True, "message": "no Moov account found for this company"},
                status=status.HTTP_404_NOT_FOUND,
            )

        profile = payload.get("profile") or {}
        profile_obj = None
        if isinstance(profile, dict):
            # If caller already provided wrapped profile, use it directly
            if "individual" in profile or "business" in profile:
                profile_obj = profile
            else:
                account_type = payload.get("account_type", "BUSINESS")
                if str(account_type).strip().upper() == "INDIVIDUAL":
                    profile_obj = {"individual": profile}
                else:
                    profile_obj = {"business": profile}

        metadata = payload.get("metadata")
        tos_raw = payload.get("terms_of_service")
        customer_support = payload.get("customer_support")

        # Build PATCH body with only the supplied fields
        patch_body: Dict[str, Any] = {}
        if profile_obj:
            patch_body["profile"] = profile_obj
        if metadata is not None:
            patch_body["metadata"] = metadata

        tos_body, tos_error = build_terms_of_service_body(tos_raw, request)
        if tos_error:
            return response.Response(
                {"error": True, "message": tos_error},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if customer_support is not None:
            patch_body["customerSupport"] = (
                customer_support.model_dump(exclude_none=True)
                if hasattr(customer_support, "model_dump")
                else customer_support
            )

        http_status_map = {
            400: status.HTTP_400_BAD_REQUEST,
            401: status.HTTP_401_UNAUTHORIZED,
            403: status.HTTP_403_FORBIDDEN,
            404: status.HTTP_404_NOT_FOUND,
            409: status.HTTP_409_CONFLICT,
            422: status.HTTP_422_UNPROCESSABLE_ENTITY,
        }

        def _log_headers_line_by_line(prefix, resp):
            logger.error("[MoovUpdate] %s response headers:", prefix)
            for header_name, header_value in resp.headers.items():
                logger.error("[MoovUpdate]   %s: %s", header_name, header_value)

        def _moov_error_response(resp):
            moov_error = resp.text
            try:
                moov_error = resp.json().get("error", moov_error)
            except Exception:
                pass
            if not moov_error:
                cf_ray = resp.headers.get("cf-ray")
                server = resp.headers.get("server", "")
                if resp.status_code == 403 and cf_ray:
                    # Cloudflare WAF block — empty body + cf-ray header.
                    moov_error = (
                        f"Request blocked by Moov's edge (Cloudflare) from this server's IP. "
                        f"cf-ray={cf_ray} server={server}. "
                        f"Local machines work because Cloudflare allows residential IPs; "
                        f"datacenter IPs are often blocked. "
                        f"Fix: contact Moov support to allowlist the server's egress IP, "
                        f"or route requests via a proxy with a residential/allowlisted IP."
                    )
                    logger.error(
                        "[MoovUpdate] Cloudflare WAF block: cf-ray=%s server=%s",
                        cf_ray, server,
                    )
                    _log_headers_line_by_line("Cloudflare WAF block", resp)
                else:
                    moov_error = f"Moov returned HTTP {resp.status_code} with no body"
                    logger.error(
                        "[MoovUpdate] Empty-body error: status=%s",
                        resp.status_code,
                    )
                    _log_headers_line_by_line("Empty-body error", resp)
            return response.Response(
                {"error": True, "message": moov_error},
                status=http_status_map.get(resp.status_code, status.HTTP_400_BAD_REQUEST),
            )

        if tos_body:
            patch_body["termsOfService"] = tos_body

        if not patch_body:
            return response.Response({"error": False, "data": {}}, status=status.HTTP_200_OK)

        try:
            # Use the Moov OAuth token the frontend supplied (X-Moov-Token) when
            # present; moov_patch falls back to facilitator Basic Auth otherwise.
            api_resp = moov_patch(
                f"/accounts/{account_uid}",
                patch_body,
                bearer_token=moov_bearer_from_request(request),
            )
            logger.debug("[MoovUpdate] status=%s body=%r", api_resp.status_code, api_resp.text[:300])

            if api_resp.status_code in (200, 204):
                data = api_resp.json() if api_resp.text else {}
                return response.Response({"error": False, "data": data}, status=status.HTTP_200_OK)

            return _moov_error_response(api_resp)

        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountCreateRepresentativesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Expect request.data to contain fields for Moov creation. We'll
        # support a minimal shape and pass through optional nested data.
        payload = request.data or {}
        logger.info(
            "Moov representative create requested: %s",
            json.dumps(redact_moov_payload(payload), default=str),
        )
        account_uid = kwargs.get("account_uid") or payload.get("account_uid")
        if not account_uid:
            return response.Response(
                {
                    "error": True,
                    "message": "account_uid is required (in URL or request body)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Representative fields: accept plain JSON for name, phone, email,
        # address, birth_date and responsibilities. We'll pass them straight
        # through to the SDK.
        name = payload.get("name")
        phone = payload.get("phone")
        email = payload.get("email")
        address = payload.get("address")
        birth_date = payload.get("birth_date")
        governmentID = payload.get("governmentID")
        responsibilities = payload.get("responsibilities")

        try:
            with moov_client() as moov:
                res = moov.representatives.create(
                    account_id=account_uid,
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    birth_date=birth_date,
                    government_id=governmentID,
                    responsibilities=responsibilities,
                )

            try:
                data = _convert_moov_result(res.result)
                rep_uid = data.get("representativeId") or data.get("representative_id")
            except Exception:
                data = res.result

            # attempt to extract representative id from the SDK response and
            # persist it to MoovAccountSettings.moov_representative_uid if a
            # matching MoovAccountSettings exists.
            if rep_uid:
                try:
                    # match the record by moov_account_uid plus the requesting user's
                    # active company and employee to ensure ownership.
                    company = request.user.get_active_company()
                    obj = MoovAccountSettings.objects.filter(
                        moov_account_uid=account_uid,
                        company=company,
                    ).first()
                    if obj:
                        obj.moov_representative_uid = rep_uid
                        obj.save()
                        saved = {"moov_representative_uid": rep_uid}
                    else:
                        return response.Response(
                            {
                                "error": True,
                                "message": "no matching MoovAccountSettings for this user/company",
                            },
                            status=status.HTTP_404_NOT_FOUND,
                        )
                except IntegrityError as ie:
                    return response.Response(
                        {"error": True, "message": str(ie)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                except Exception:
                    # swallow DB errors but report no saved value
                    saved = None

            return response.Response(
                {"error": False, "data": data}, status=status.HTTP_201_CREATED
            )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountUpdateRepresentativesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        # Accept account_uid and representative_uid from URL kwargs
        payload = request.data or {}
        account_uid = kwargs.get("account_uid") or payload.get("account_uid")
        representative_uid = (
            kwargs.get("representative_uid")
            or payload.get("representative_uid")
            or payload.get("id")
        )
        if not account_uid or not representative_uid:
            return response.Response(
                {
                    "error": True,
                    "message": "account_uid and representative_uid are required (in URL or request body)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Representative fields: accept plain JSON for name, phone, email,
        # address, birth_date and responsibilities. We'll pass them straight
        # through to the SDK.
        name = payload.get("name")
        phone = payload.get("phone")
        email = payload.get("email")
        address = payload.get("address")
        birth_date = payload.get("birth_date")
        governmentID = payload.get("governmentID")
        responsibilities = payload.get("responsibilities")

        try:
            with moov_client() as moov:
                res = moov.representatives.update(
                    account_id=account_uid,
                    representative_id=representative_uid,
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    birth_date=birth_date,
                    government_id=governmentID,
                    responsibilities=responsibilities,
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


#: Moov's requirement id for an outstanding platform-agreement acceptance.
TOS_REQUIREMENT = "account.tos-acceptance"


class MoovAccountCapabilitiesListView(APIView):
    """GET the account's capabilities + what Moov is still waiting on.

    The dashboard showing no terms-of-service warning does NOT mean the terms are
    accepted — Moov only asks for them once a capability beyond `transfers` is
    requested. The authoritative signal is `account.tos-acceptance` appearing in
    a capability's ``requirements.currentlyDue``, which is surfaced here as
    ``terms_of_service_due`` so it takes one call, not a guess.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, account_uid: str):
        if not MoovAccountSettings.objects.filter(
            company=request.user.get_active_company(),
            moov_account_uid=account_uid,
        ).exists():
            return response.Response(
                {"error": True, "message": "no Moov account found for this company"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with moov_client() as moov:
                res = moov.capabilities.list(account_id=account_uid)

            try:
                data = _convert_moov_result(res.result)
            except Exception:
                data = res.result

            capabilities = data if isinstance(data, list) else [data]

            currently_due: list = []
            requirement_errors: list = []
            for capability in capabilities:
                if not isinstance(capability, dict):
                    continue
                requirements = capability.get("requirements") or {}
                currently_due.extend(requirements.get("currentlyDue") or [])
                requirement_errors.extend(requirements.get("errors") or [])

            tos_due = TOS_REQUIREMENT in currently_due

            logger.info(
                "Moov capabilities: account_id=%s tos_due=%s currently_due=%s",
                account_uid,
                tos_due,
                sorted(set(currently_due)),
            )

            return response.Response(
                {
                    "error": False,
                    "data": data,
                    "terms_of_service_due": tos_due,
                    "currently_due": sorted(set(currently_due)),
                    "requirement_errors": requirement_errors,
                },
                status=status.HTTP_200_OK,
            )
        except moov_errors.MoovError as exc:
            detail = describe_moov_error(exc)
            logger.error(
                "Moov capabilities fetch failed: account_uid=%s %s",
                account_uid,
                json.dumps(detail, default=str),
            )
            return response.Response(
                {"error": True, "message": str(exc), "moov_error": detail},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("Unexpected error listing Moov capabilities")
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountCreateCapabilitiesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Expect request.data to contain fields for Moov creation. We'll
        # support a minimal shape and pass through optional nested data.
        payload = request.data or {}
        logger.info(
            "Moov capabilities create requested: account_uid=%s payload=%s",
            kwargs.get("account_uid"),
            json.dumps(redact_moov_payload(payload), default=str),
        )
        account_uid = kwargs.get("account_uid") or payload.get("account_uid")
        if not account_uid:
            return response.Response(
                {
                    "error": True,
                    "message": "account_uid is required (in URL or request body)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Capability fields: accept plain JSON for type and details.
        caps = payload.get("capabilities") or []
        if not isinstance(caps, list) or not caps:
            return response.Response(
                {"error": True, "message": "capabilities must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mapped = []
        for c in caps:
            # allow passing enum values or plain strings
            if isinstance(c, str):
                try:
                    mapped.append(
                        getattr(components.CapabilityID, str(c).strip().upper())
                    )
                except Exception:
                    return response.Response(
                        {"error": True, "message": f"invalid capability '{c}'"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                # if caller provided the enum object directly, accept it
                mapped.append(c)

        try:
            with moov_client() as moov:
                res = moov.capabilities.request(
                    account_id=account_uid,
                    capabilities=mapped,
                )

            try:
                data = _convert_moov_result(res.result)
            except Exception:
                data = res.result

            return response.Response(
                {"error": False, "data": data}, status=status.HTTP_201_CREATED
            )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountRepresentativesDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, representative_uid, *args, **kwargs):
        """Retrieve a Moov representative by UID scoped to the user's company."""
        try:
            # locate the moov account for this user's active company/employee
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
                    res = moov.representatives.get(
                        account_id=moov_account_uid,
                        representative_id=representative_uid,
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
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        except Exception as exc:
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MoovAccountBankMeAccountListView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MoovBankAccountSettingsSerializer
    filter_backends = [
        filters.SearchFilter,
        # filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    search_fields = [
        "account_holder_name",
        "bank_name",
        "account_number",
        "account_type",
    ]
    filterset_fields = [
        "status",
        "bank_account_kind",
        "employee__uid",
    ]

    def get_queryset(self):
        company = self.request.user.get_active_company()
        moov_account_setting = MoovAccountSettings.objects.filter(
            company=company
        ).first()
        if not moov_account_setting:
            return MoovBankAccountSettings.objects.none()
        return MoovBankAccountSettings.objects.filter(
            moov_account_settings=moov_account_setting
        ).select_related("employee")


class MoovAccountAccessTokenView(APIView):
    """
    Mint a short-lived OAuth access token scoped to a single Moov account.

    The frontend calls this endpoint, then uses the returned bearer token to
    PATCH api.moov.io/accounts/{account_uid} directly from the browser. The
    browser's residential IP is not Cloudflare-WAF-blocked, so this is the
    recommended path when server-side PATCH from the datacenter IP is blocked.

    Security note: the returned token is scoped only to the one account and
    expires in minutes, so it is safe to hand to the browser.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, account_uid: str, *args, **kwargs):
        # The TODO that stood here is the check below. Without it this endpoint
        # minted a Moov OAuth bearer with profile.read + profile.write on ANY
        # account_uid for ANY authenticated user, and handed it to the browser.
        # The docstring's claim that a narrow, short-lived token is safe to hand
        # out holds only once the caller is known to own the account.
        #
        # Same shape as MoovAccountDetailsView and the capabilities view in this
        # file, including the 404: a 403 would confirm the account exists.
        if not MoovAccountSettings.objects.filter(
            company=request.user.get_active_company(),
            moov_account_uid=account_uid,
        ).exists():
            logger.warning(
                "Moov token denied: user=%s requested account_uid=%s not owned "
                "by their company",
                request.user.pk,
                account_uid,
            )
            return response.Response(
                {"error": True, "message": "no Moov account found for this company"},
                status=status.HTTP_404_NOT_FOUND,
            )

        payload = request.data or {}
        requested_scopes = payload.get("scopes") or [
            f"/accounts/{account_uid}/profile.read",
            f"/accounts/{account_uid}/profile.write",
        ]
        if not isinstance(requested_scopes, list) or not all(
            isinstance(s, str) and s.startswith(f"/accounts/{account_uid}/")
            for s in requested_scopes
        ):
            return response.Response(
                {
                    "error": True,
                    "message": (
                        "scopes must be a list of strings, each starting with "
                        f"/accounts/{account_uid}/"
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = moov_get_oauth_token(scope=" ".join(requested_scopes))
        except Exception as exc:
            logger.exception("Failed to mint Moov access token: %s", exc)
            return response.Response(
                {"error": True, "message": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return response.Response(
            {
                "error": False,
                "data": {
                    "access_token": token,
                    "token_type": "Bearer",
                    "scopes": requested_scopes,
                    "account_id": account_uid,
                },
            },
            status=status.HTTP_200_OK,
        )
