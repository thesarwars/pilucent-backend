"""The ID cards API (docs/backend/id-cards-done.md §5), mounted at
/api/v1/we/idcards: the gallery, cards and their lifecycle, templates and
their versions, resolution rules, print jobs, photos, custom fields, output
profiles and the card settings.

The client renders cards with its own engine for the canvas; every gate --
issue, publish, print -- runs the server's preflight with real font metrics.
A context returned here carries signed, short-lived photo URLs, because an
<img> cannot send the auth header.

Permissions (§6): issue_cards, revoke_cards, edit_card_templates,
publish_card_templates, print_cards, override_card_print (distinct from
print), manage_card_photos, manage_card_fields. Reading needs the
employees feature only.

Tenancy: every record is resolved with `company=`.
"""

import copy
from datetime import date

from django.http import FileResponse
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from employeeio.models import Employee
from employeeio.services.salary_access import has_company_permission
from idcardio.choices import PRESETS
from idcardio.models import (
    Card,
    CardAudit,
    CardField,
    CardSettings,
    CardTemplate,
    MediaAsset,
    OutputProfile,
    PrintJob,
    ResolutionRule,
)
from idcardio.services import context as C
from idcardio.services import ops
from idcardio.services.engine import describe_condition
from idcardio.services.ops import CardRefused
from idcardio.services.seed import ensure_setup

from ..serializers.bd_employees import ui_errors
from .bd_employees import BDEmployeeView

APP = "idcardio"
ISSUE, REVOKE, EDIT, PUBLISH, PRINT, OVERRIDE, PHOTOS, FIELDS = (
    "issue_cards", "revoke_cards", "edit_card_templates", "publish_card_templates", "print_cards",
    "override_card_print", "manage_card_photos", "manage_card_fields")
NEEDS = {
    ISSUE: "Issuing a card needs the 'issue cards' permission.",
    REVOKE: "Revoking, reporting lost or replacing a card needs the 'revoke cards' permission.",
    EDIT: "Designing a template needs the 'edit card templates' permission.",
    PUBLISH: "Publishing a template version needs the 'publish card templates' permission.",
    PRINT: "Submitting a print job needs the 'print cards' permission.",
    OVERRIDE: "Printing cards that carry warnings needs the 'override card print' permission.",
    PHOTOS: "Changing a card photo needs the 'manage card photos' permission.",
    FIELDS: "Custom fields need the 'manage card fields' permission -- it decides what the public "
            "verification page shows.",
}


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise CardRefused({field: [f"{field} must be a date, YYYY-MM-DD."]}, status=400) from None


def with_urls(company, ctx):
    """A render context with a signed URL on each image reference."""
    ctx = copy.deepcopy(ctx)
    photo = (ctx.get("employee") or {}).get("photo")
    if isinstance(photo, dict) and photo.get("assetId"):
        photo["url"] = f"/api/v1/public/idcard-media/{ops.sign_media(company, photo['assetId'])}"
    return ctx


class CardsView(BDEmployeeView):
    def handle_exception(self, exc):
        if isinstance(exc, CardRefused):
            body = ui_errors(exc.errors)
            if exc.detail is not None:
                body["consequence"] = exc.detail
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def may(self, codename):
        return has_company_permission(self.request.user, self.company(), codename, APP)

    def refuse_unless(self, codename):
        if not self.may(codename):
            raise CardRefused({"permission": [NEEDS[codename]]}, status=status.HTTP_403_FORBIDDEN)

    def can(self):
        return {"issue": self.may(ISSUE), "revoke": self.may(REVOKE), "edit": self.may(EDIT),
                "publish": self.may(PUBLISH), "print": self.may(PRINT), "override": self.may(OVERRIDE),
                "photos": self.may(PHOTOS), "fields": self.may(FIELDS)}

    def employee(self, code=None):
        code = code or self.kwargs.get("code") or self.request.data.get("employeeCode")
        return get_object_or_404(Employee.objects.select_related("designation", "department", "section", "site"),
                                 code=str(code or "").strip(), company=self.company())

    def template(self, uid=None):
        return get_object_or_404(CardTemplate, uid=uid or self.kwargs["uid"], company=self.company())

    def card(self, uid=None):
        return get_object_or_404(Card.objects.select_related("template", "employee", "replaced_by"),
                                 uid=uid or self.kwargs["uid"], company=self.company())


def audit_out(a):
    return {"action": a.action, "label": a.get_action_display(), "by": a.actor_name or None,
            "at": a.created_at.isoformat(), "reason": a.reason or None, "ip": a.actor_ip,
            "after": a.after_json}


# ------------------------------------------------------------------- setup


class IdSetup(CardsView):
    """Everything the screens share: the binding catalogue, presets, the
    profiles, the settings and what this caller may do."""

    def get(self, request):
        company = self.company()
        ensure_setup(company)
        s, _ = CardSettings.objects.get_or_create(company=company)
        return Response({
            "catalogue": C.catalogue(company), "company": C.company_ctx(company),
            "presets": [{"id": k, "widthMm": float(w), "heightMm": float(h), "label": k} for k, (w, h, _) in
                        PRESETS.items()],
            "profiles": [ops.profile_out(p) for p in OutputProfile.objects.filter(company=company)
                         .order_by("-is_default", "name")],
            "settings": settings_out(s), "can": self.can(),
        })


def settings_out(s):
    return {"nameBn": s.name_bn or None, "address": s.address or None, "signatoryTitle": s.signatory_title or None,
            "numberPrefix": s.number_prefix, "validityYears": s.validity_years,
            "photoRetentionDays": s.photo_retention_days}


class IdSettings(CardsView):
    def patch(self, request):
        self.refuse_unless(EDIT)
        s, _ = CardSettings.objects.get_or_create(company=self.company())
        d = request.data
        for attr, key in (("name_bn", "nameBn"), ("address", "address"), ("signatory_title", "signatoryTitle"),
                          ("number_prefix", "numberPrefix")):
            if key in d:
                setattr(s, attr, str(d[key] or "").strip())
        for attr, key, lo, hi in (("validity_years", "validityYears", 1, 10),
                                  ("photo_retention_days", "photoRetentionDays", 0, 3650)):
            if key in d:
                try:
                    v = int(d[key])
                except (TypeError, ValueError):
                    v = -1
                if not lo <= v <= hi:
                    raise CardRefused({key: [f"{key} is between {lo} and {hi}."]}, status=400)
                setattr(s, attr, v)
        if not s.number_prefix.isalnum():
            raise CardRefused({"numberPrefix": ["A prefix is letters and digits, e.g. ID."]}, status=400)
        s.save()
        return Response(settings_out(s))


# ----------------------------------------------------------------- gallery


class IdGallery(CardsView):
    def get(self, request):
        p = request.query_params
        flt = (p.get("filter") or "ALL").upper()
        if flt not in ("ALL", "NOT_ISSUED", "EXPIRING", "MISSING", "REVOKED"):
            raise CardRefused({"filter": ["filter is ALL, NOT_ISSUED, EXPIRING, MISSING or REVOKED."]}, status=400)
        company = self.company()
        out = ops.gallery(company, q=(p.get("q") or "").strip(), flt=flt)
        # Thumbnails render on the client: each row's context, and each template once.
        uids = {r["template"]["uid"] for r in out["rows"] if r["template"]}
        uids |= {r["card"]["template"]["uid"] for r in out["rows"] if r["card"]}
        tpls = {str(t.uid): ops.template_out(t, full=True)
                for t in CardTemplate.objects.filter(company=company, uid__in=uids)}
        cards = {str(c.uid): c for c in Card.objects.filter(
            company=company, uid__in=[r["card"]["uid"] for r in out["rows"] if r["card"]])
            .select_related("template", "employee")}
        employees = {e.code: e for e in Employee.objects.filter(company=company,
                                                               code__in=[r["code"] for r in out["rows"]])
                     .select_related("designation", "department", "section", "site")}
        photos = C.current_photos(list(employees.values()))
        customs = C.custom_values(list(employees.values()))
        comp = C.company_ctx(company)
        for r in out["rows"]:
            if r["card"]:
                ctx = ops.card_context(company, cards[r["card"]["uid"]])
            else:
                ctx = C.live_context(company, employees[r["code"]], photos=photos, customs=customs,
                                     company_part=comp)
            r["context"] = with_urls(company, ctx)
            if r["photo"]:
                r["photo"]["url"] = f"/api/v1/public/idcard-media/{ops.sign_media(company, r['photo']['assetId'])}"
        return Response({**out, "templates": tpls, "can": self.can()})


class IdEmployee(CardsView):
    """One employee: what their card would say now, on which template, with
    the server's measured preflight; their cards; their photo."""

    def get(self, request, code):
        company = self.company()
        e = self.employee(code)
        t_uid = request.query_params.get("template")
        if t_uid:
            t, rule = self.template(t_uid), None
        else:
            t, rule = ops.template_for(company, e)
        ctx, report = (ops.employee_preview(company, e, t) if t else (C.live_context(company, e), None))
        photo = C.current_photos([e]).get(e.pk)
        cards = Card.objects.filter(company=company, employee=e).select_related("template", "employee",
                                                                               "replaced_by").order_by("-created_at")
        return Response({
            "employee": {"code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn or None,
                         "designation": e.designation.title if e.designation_id else None,
                         "department": e.department.title if e.department_id else None,
                         "hasProfilePhoto": bool(e.photo)},
            "template": ops.template_out(t, full=True) if t else None, "rule": rule.label if rule else None,
            "context": with_urls(company, ctx), "preflight": report,
            "photo": ops.asset_out(company, photo) if photo else None,
            "customValues": C.custom_values([e], printable_only=False).get(e.pk, {}),
            "cards": [ops.card_out(c) for c in cards], "can": self.can(),
        })


# ------------------------------------------------------------------- cards


class IdCards(CardsView):
    def post(self, request):
        """Issue: snapshot, number, token, expiry -- or 422 with the preflight."""
        self.refuse_unless(ISSUE)
        company = self.company()
        e = self.employee()
        t = self.template(request.data["templateUid"]) if request.data.get("templateUid") else None
        card, report = ops.issue_card(company, e, template=t, user=request.user,
                                      expires_on=_date(request.data.get("expiresOn"), "expiresOn"))
        return Response({"card": ops.card_out(card), "preflight": report}, status=status.HTTP_201_CREATED)


class IdCardsBulk(CardsView):
    """Issue for several employees; each refusal is reported, not fatal."""

    def post(self, request):
        self.refuse_unless(ISSUE)
        company = self.company()
        issued, refused = [], []
        for code in request.data.get("employeeCodes") or []:
            e = Employee.objects.filter(company=company, code=str(code).strip()).first()
            if e is None:
                refused.append({"code": code, "messages": ["No such employee."]})
                continue
            try:
                card, _ = ops.issue_card(company, e, user=request.user)
                issued.append(ops.card_out(card))
            except CardRefused as exc:
                refused.append({"code": code, "messages": [m for ms in exc.errors.values() for m in ms]})
        return Response({"issued": issued, "refused": refused})


class IdCard(CardsView):
    def get(self, request, uid):
        company = self.company()
        c = self.card(uid)
        report, _ = ops.card_preflight(company, ops.card_context(company, c), c.template)
        jobs = c.print_jobs.order_by("-created_at")
        return Response({
            "card": ops.card_out(c), "template": ops.template_out(c.template, full=True),
            "context": with_urls(company, ops.card_context(company, c)), "preflight": report,
            "jobs": [ops.job_out(j) for j in jobs],
            "audit": [audit_out(a) for a in CardAudit.objects.filter(card=c).order_by("-created_at")[:50]],
            "can": self.can(),
        })


class IdCardAction(CardsView):
    def post(self, request, uid, action):
        company = self.company()
        c = self.card(uid)
        reason = request.data.get("reason")
        if action in ("revoke", "lost"):
            self.refuse_unless(REVOKE)
            c = ops.revoke_card(company, c, reason=reason, lost=action == "lost", user=request.user)
            return Response({"card": ops.card_out(c)})
        if action == "replace":
            self.refuse_unless(REVOKE)
            self.refuse_unless(ISSUE)
            new, report = ops.replace_card(company, c, reason=reason, user=request.user)
            return Response({"card": ops.card_out(new), "replaced": c.card_number, "preflight": report},
                            status=status.HTTP_201_CREATED)
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


# --------------------------------------------------------------- templates


class IdTemplates(CardsView):
    def get(self, request):
        return Response({"templates": ops.templates(self.company()), "can": self.can()})

    def post(self, request):
        self.refuse_unless(EDIT)
        d = request.data
        copy_of = self.template(d["copyOf"]) if d.get("copyOf") else None
        t = ops.create_template(self.company(), code=d.get("code"), name=str(d.get("name") or "").strip(),
                                preset=d.get("preset"), name_bn=str(d.get("nameBn") or "").strip(),
                                description=str(d.get("description") or "").strip(), user=request.user,
                                copy_of=copy_of)
        return Response(ops.template_out(t, full=True), status=status.HTTP_201_CREATED)


class IdTemplate(CardsView):
    def get(self, request, uid):
        company = self.company()
        t = self.template(uid)
        versions = CardTemplate.objects.filter(company=company, code=t.code).order_by("-version")
        return Response({**ops.template_out(t, full=True),
                         "versions": [ops.template_out(v) for v in versions],
                         "liveCards": Card.objects.filter(template=t, status__in=("ISSUED", "ACTIVE")).count(),
                         "audit": [audit_out(a) for a in CardAudit.objects.filter(template__code=t.code,
                                                                                  company=company)[:30]],
                         "can": self.can()})

    def patch(self, request, uid):
        """A draft saves in place; a published or locked version becomes the
        next draft -- 200 with `versioned`, and the draft to continue on."""
        self.refuse_unless(EDIT)
        t, versioned = ops.save_template(self.company(), self.template(uid), request.data, user=request.user)
        return Response({**ops.template_out(t, full=True), "versioned": versioned})


class IdTemplateAction(CardsView):
    def post(self, request, uid, action):
        company = self.company()
        t = self.template(uid)
        if action == "preflight":
            # The draft as it stands in the designer, unsaved, against the roster.
            probe = copy.copy(t)
            if "front" in request.data:
                probe.front_json = request.data["front"]
            if "back" in request.data:
                probe.back_json = request.data["back"]
            return Response(ops.preflight_template(company, probe))
        if action == "publish":
            self.refuse_unless(PUBLISH)
            t, report = ops.publish_template(company, t, acknowledge_errors=bool(request.data.get("acknowledgeErrors")),
                                             user=request.user)
            return Response({**ops.template_out(t, full=True), "preflight": report})
        if action == "default":
            self.refuse_unless(PUBLISH)
            CardTemplate.objects.filter(company=company).exclude(code=t.code).update(is_default=False)
            CardTemplate.objects.filter(company=company, code=t.code).update(is_default=True)
            return Response({"default": t.code})
        if action == "archive":
            self.refuse_unless(PUBLISH)
            if t.is_default:
                raise CardRefused({"template": ["The default template is not archived; make another default "
                                                "first."]}, status=409)
            CardTemplate.objects.filter(company=company, code=t.code).exclude(status="ARCHIVED").update(
                status="ARCHIVED")
            ops.audit(company, "TEMPLATE_ARCHIVED", request.user, template=t)
            return Response({"archived": t.code})
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class IdTemplateContexts(CardsView):
    """The designer's preview data: each employee's live context, so the
    canvas can show anyone -- and the worst case -- without a round trip."""

    def get(self, request, uid):
        company = self.company()
        t = self.template(uid)
        employees = list(ops.roster(company)[:500])
        photos, customs, comp = C.current_photos(employees), C.custom_values(employees), C.company_ctx(company)
        from idcardio.services.engine import bindings_of

        paths = bindings_of(t.front_json) | (bindings_of(t.back_json) if t.back_json else set())
        return Response({
            "employees": [{"code": e.code, "nameEn": e.name_en,
                           "context": with_urls(company, C.live_context(company, e, photos=photos, customs=customs,
                                                                        company_part=comp))} for e in employees],
            "fieldStats": C.field_stats(company, employees, paths),
        })


# ------------------------------------------------------------------- rules


def rule_out(r):
    return {"uid": str(r.uid), "priority": r.priority, "label": r.label, "templateCode": r.template_code,
            "condition": r.condition, "describe": describe_condition(r.condition), "enabled": r.enabled}


def _rule_fields(r, d, company):
    if "label" in d:
        r.label = str(d["label"] or "").strip()
    if "priority" in d:
        r.priority = max(1, int(d["priority"] or 1))
    if "templateCode" in d:
        r.template_code = str(d["templateCode"] or "")
    if "condition" in d:
        cond = d["condition"] or {}
        if not isinstance(cond, dict) or not cond.get("op"):
            raise CardRefused({"condition": ["A rule needs a condition."]}, status=400)
        if cond.get("path") and cond["path"] not in C.known_paths(company):
            raise CardRefused({"condition": [f"Unknown field {cond['path']}."]}, status=400)
        r.condition = cond
    if "enabled" in d:
        r.enabled = bool(d["enabled"])
    if not r.label:
        raise CardRefused({"label": ["A rule needs a label."]}, status=400)
    if not CardTemplate.objects.filter(company=company, code=r.template_code).exists():
        raise CardRefused({"templateCode": ["Choose a template."]}, status=400)


class IdRules(CardsView):
    def get(self, request):
        return Response({"rules": [rule_out(r) for r in ResolutionRule.objects.filter(company=self.company())
                                   .order_by("priority", "created_at")]})

    def post(self, request):
        self.refuse_unless(PUBLISH)
        company = self.company()
        r = ResolutionRule(company=company, condition={})
        _rule_fields(r, {"priority": ResolutionRule.objects.filter(company=company).count() + 1, **request.data},
                     company)
        r.save()
        return Response(rule_out(r), status=status.HTTP_201_CREATED)


class IdRule(CardsView):
    def patch(self, request, uid):
        self.refuse_unless(PUBLISH)
        company = self.company()
        r = get_object_or_404(ResolutionRule, uid=uid, company=company)
        _rule_fields(r, request.data, company)
        r.save()
        return Response(rule_out(r))

    def delete(self, request, uid):
        self.refuse_unless(PUBLISH)
        get_object_or_404(ResolutionRule, uid=uid, company=self.company()).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- print jobs


class IdPrintCheck(CardsView):
    """The wizard's Check step: each card's measured preflight, nothing saved."""

    def post(self, request):
        company = self.company()
        cards = list(Card.objects.filter(company=company, uid__in=request.data.get("cardUids") or [])
                     .select_related("template", "employee"))
        checks = ops.check_cards(company, cards)
        return Response({"checks": checks, "ready": sum(not c["errors"] and not c["warnings"] for c in checks),
                         "warnings": sum(not c["errors"] and bool(c["warnings"]) for c in checks),
                         "blocked": sum(bool(c["errors"]) for c in checks)})


class IdPrintJobs(CardsView):
    def get(self, request):
        jobs = PrintJob.objects.filter(company=self.company()).order_by("-created_at")[:200]
        return Response({"jobs": [ops.job_out(j) for j in jobs], "can": self.can()})

    def post(self, request):
        self.refuse_unless(PRINT)
        include = bool(request.data.get("includeWarnings"))
        if include:
            self.refuse_unless(OVERRIDE)
        job = ops.submit_job(self.company(), request.data.get("cardUids"), request.data.get("profileUid"),
                             include_warnings=include, name=request.data.get("name") or "", user=request.user)
        return Response(ops.job_out(job, detail=True), status=status.HTTP_201_CREATED)


class IdPrintJob(CardsView):
    def get(self, request, uid):
        job = get_object_or_404(PrintJob, uid=uid, company=self.company())
        cards = job.cards.select_related("employee").order_by("employee__code")
        return Response({**ops.job_out(job, detail=True),
                         "cardList": [{"uid": str(c.uid), "number": c.card_number, "code": c.employee.code,
                                       "nameEn": c.employee.name_en} for c in cards]})


class IdPrintJobAction(CardsView):
    def post(self, request, uid, action):
        self.refuse_unless(PRINT)
        company = self.company()
        job = get_object_or_404(PrintJob, uid=uid, company=company)
        if action == "printed":
            return Response(ops.job_out(ops.mark_printed(company, job, user=request.user)))
        if action == "retry":
            if job.status != "FAILED":
                raise CardRefused({"job": ["Only a failed job is retried."]}, status=409)
            PrintJob.objects.filter(pk=job.pk).update(status="QUEUED", failure_reason="")
            job.refresh_from_db()
            return Response(ops.job_out(ops.render_job(job)))
        if action == "cancel":
            if job.status not in ("QUEUED", "READY", "FAILED"):
                raise CardRefused({"job": [f"A {job.status.lower()} job is not cancelled."]}, status=409)
            job.status = "CANCELLED"
            job.save(update_fields=["status", "updated_at"])
            return Response(ops.job_out(job))
        return Response({"message": f"Unknown action {action}."}, status=status.HTTP_404_NOT_FOUND)


class IdPrintJobDownload(CardsView):
    def get(self, request, uid):
        self.refuse_unless(PRINT)
        job = get_object_or_404(PrintJob, uid=uid, company=self.company())
        if job.status not in ("READY", "PRINTED") or not job.artifact:
            raise CardRefused({"job": [f"{job.reference} has no file to download ({job.status.lower()})."]},
                              status=409)
        ext = job.artifact.name.rsplit(".", 1)[-1]
        resp = FileResponse(job.artifact.open("rb"), as_attachment=True, filename=f"{job.reference}.{ext}",
                            content_type="application/zip" if ext == "zip" else "application/pdf")
        resp["X-Artifact-SHA256"] = job.artifact_sha256
        return resp


# ------------------------------------------------------------------ photos


class IdPhoto(CardsView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, code):
        self.refuse_unless(PHOTOS)
        company = self.company()
        e = self.employee(code)
        if request.data.get("fromProfile"):
            a = ops.photo_from_profile(company, e, user=request.user)
        else:
            upload = request.FILES.get("file")
            if upload is None:
                raise CardRefused({"file": ["Choose a photo to upload."]}, status=400)
            a = ops.upload_asset(company, e, upload, user=request.user)
        return Response(ops.asset_out(company, a), status=status.HTTP_201_CREATED)


class IdAsset(CardsView):
    def patch(self, request, uid):
        self.refuse_unless(PHOTOS)
        company = self.company()
        a = get_object_or_404(MediaAsset, uid=uid, company=company, purged_at__isnull=True)
        a = ops.adjust_asset(company, a, crop=request.data.get("crop"), adjustments=request.data.get("adjustments"),
                             user=request.user)
        return Response(ops.asset_out(company, a))


# ------------------------------------------------------------------ fields


class IdFields(CardsView):
    def get(self, request):
        company = self.company()
        fields = list(CardField.objects.filter(company=company).order_by("position", "label"))
        employees = list(ops.roster(company))
        stats = C.field_stats(company, employees, {f.path for f in fields}) if fields else {}
        values = C.custom_values(employees, printable_only=False)
        return Response({
            "fields": [ops.field_out(f, stats.get(f.path)) for f in fields],
            "employees": [{"code": e.code, "nameEn": e.name_en, "values": values.get(e.pk, {})} for e in employees],
            "can": self.can()})

    def post(self, request):
        self.refuse_unless(FIELDS)
        f = ops.save_field(self.company(), request.data, user=request.user)
        return Response(ops.field_out(f), status=status.HTTP_201_CREATED)


class IdField(CardsView):
    def patch(self, request, uid):
        self.refuse_unless(FIELDS)
        company = self.company()
        f = get_object_or_404(CardField, uid=uid, company=company)
        return Response(ops.field_out(ops.save_field(company, {k: v for k, v in request.data.items() if k != "key"},
                                                     field=f, user=request.user)))


class IdFieldValues(CardsView):
    def put(self, request, code):
        self.refuse_unless(FIELDS)
        company = self.company()
        return Response({"values": ops.set_field_values(company, self.employee(code), request.data.get("values"),
                                                        user=request.user)})


# ---------------------------------------------------------------- profiles


def _profile_fields(p, d):
    for attr, key in (("name", "name"), ("note", "note"), ("sheet", "sheet"), ("duplex", "duplex"),
                      ("colour_profile", "colourProfile")):
        if key in d:
            setattr(p, attr, str(d[key] or "").strip())
    for attr, key in (("cols", "cols"), ("rows", "rows"), ("dpi", "dpi")):
        if key in d:
            setattr(p, attr, int(d[key] or 0))
    for attr, key in (("gutter_mm", "gutterMm"), ("margin_mm", "marginMm")):
        if key in d:
            setattr(p, attr, float(d[key] or 0))
    for attr, key in (("include_bleed", "includeBleed"), ("crop_marks", "cropMarks"), ("mirror", "mirror")):
        if key in d:
            setattr(p, attr, bool(d[key]))
    if not p.name:
        raise CardRefused({"name": ["A profile needs a name."]}, status=400)
    if p.sheet not in ("CARD_DIRECT", "A4", "LETTER", "PNG"):
        raise CardRefused({"sheet": ["sheet is CARD_DIRECT, A4, LETTER or PNG."]}, status=400)
    if not 150 <= p.dpi <= 1200:
        raise CardRefused({"dpi": ["DPI is between 150 and 1200."]}, status=400)
    if p.sheet in ("A4", "LETTER") and not (1 <= p.cols <= 6 and 1 <= p.rows <= 8):
        raise CardRefused({"cols": ["A sheet is 1-6 columns by 1-8 rows."]}, status=400)
    if p.sheet in ("CARD_DIRECT", "PNG"):
        p.cols = p.rows = 1


class IdProfiles(CardsView):
    def post(self, request):
        self.refuse_unless(PRINT)
        p = OutputProfile(company=self.company(), sheet="CARD_DIRECT")
        _profile_fields(p, request.data)
        p.save()
        return Response(ops.profile_out(p), status=status.HTTP_201_CREATED)


class IdProfile(CardsView):
    def patch(self, request, uid):
        self.refuse_unless(PRINT)
        company = self.company()
        p = get_object_or_404(OutputProfile, uid=uid, company=company)
        _profile_fields(p, request.data)
        p.save()
        if request.data.get("isDefault"):
            OutputProfile.objects.filter(company=company).exclude(pk=p.pk).update(is_default=False)
            OutputProfile.objects.filter(pk=p.pk).update(is_default=True)
            p.refresh_from_db()
        return Response(ops.profile_out(p))
