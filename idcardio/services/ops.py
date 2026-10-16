"""ID card operations (§5): templates and their versions, preflight, the
card lifecycle, print jobs, photos, custom fields, output profiles and the
public verification.

Preflight runs here, server-side, with real font metrics, before every
publish and every print job: a client that skips it cannot produce a print
file.
"""

import hashlib
import io
import secrets
import string
from collections import defaultdict
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common import clock
from employeeio.models import Employee

from ..choices import PRESETS
from ..models import (
    Card,
    CardAudit,
    CardEvent,
    CardField,
    CardFieldValue,
    CardSettings,
    CardTemplate,
    MediaAsset,
    OutputProfile,
    PrintJob,
    ResolutionRule,
)
from . import context as C
from .engine import RecordingMeasurer, artboard, bindings_of, eval_condition, preflight_side, resolve_side, summarise
from .engine import validate_side
from .seed import ensure_setup

ALPHABET = string.ascii_letters + string.digits
MIN_REASON = 10


class CardRefused(Exception):
    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def audit(company, action, user=None, *, card=None, template=None, job=None, before=None, after=None, reason="",
          ip=None):
    CardAudit.objects.create(company=company, card=card, template=template, job=job, action=action, actor=_who(user),
                             actor_name=_name(user), actor_ip=ip, before_json=before, after_json=after,
                             reason=reason or "")


# Event -> (notification kind, the permissions whose holders hear of it). A
# revocation reaches access control through the outbox in the same commit.
ROUTES = {
    "CardIssued": ("ID_CARD_ISSUED", ("print_cards",)),
    "CardRevoked": ("ID_CARD_REVOKED", ("revoke_cards", "print_cards")),
    "CardExpiring": ("ID_CARD_EXPIRING", ("issue_cards",)),
    "PrintJobReady": ("CARD_PRINT_READY", ("print_cards",)),
    "PrintJobFailed": ("CARD_PRINT_FAILED", ("print_cards",)),
    "TemplatePublished": ("CARD_TEMPLATE_PUBLISHED", ("edit_card_templates",)),
}


def holders(company, codename):
    from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
    from accounts.models import User

    held = (Q(companyuser__company=company, companyuser__roles__company=company,
              companyuser__roles__name=ADMIN_GROUP_NAME, companyuser__roles__is_system=True)
            | Q(companyuser__company=company, companyuser__roles__permission__codename=codename,
                companyuser__roles__permission__content_type__app_label="idcardio")
            | Q(companyuser__company=company, companyuser__permission__codename=codename,
                companyuser__permission__content_type__app_label="idcardio"))
    return list(User.objects.filter(held).exclude(status__in=["INACTIVE", "REMOVED"]).distinct())


def event(company, name, card=None, *, message="", actor=None, **payload):
    """Write the outbox row and notify, in the transaction that caused it."""
    from notificationio.choices import NotificationModelKindChoices, NotificationStatusChoices
    from notificationio.services.notifications import NotificationService

    ev = CardEvent.objects.create(company=company, name=name, card=card, payload=payload)
    kind, perms = ROUTES[name]
    users = {u.pk: u for p in perms for u in holders(company, p)}
    users.pop(getattr(actor, "pk", None), None)
    if users:
        NotificationService.create_notification(
            status=NotificationStatusChoices.PUBLISHED, model_kind=NotificationModelKindChoices.ID_CARD, kind=kind,
            message=(message or name)[:100], is_company=True, users=list(users.values()))
    return ev


def emit_expiring(company, today=None):
    """§9: CardExpiring once per card, 30 days before expiry."""
    today = today or clock.today()
    done = set(CardEvent.objects.filter(company=company, name="CardExpiring").values_list("card_id", flat=True))
    n = 0
    for c in Card.objects.filter(company=company, status__in=("ISSUED", "ACTIVE"), expires_on__gte=today,
                                 expires_on__lte=today + timedelta(days=30)).select_related("employee"):
        if c.pk in done:
            continue
        event(company, "CardExpiring", c, number=c.card_number, employee=c.employee.code,
              expiresOn=c.expires_on.isoformat(),
              message=f"{c.card_number} ({c.employee.name_en}) expires on {c.expires_on:%d %b %Y}")
        n += 1
    return n


def _reason(text, what="a reason"):
    text = str(text or "").strip()
    if len(text) < MIN_REASON:
        raise CardRefused({"reason": [f"Give {what}, at least {MIN_REASON} characters ({len(text)} so far)."]})
    return text


def new_token():
    """§7.2: 128 bits from a CSPRNG, base62 -- never the employee id, never
    the card number, never a hash of either."""
    n = secrets.randbits(128)
    out = ""
    while n:
        n, r = divmod(n, 62)
        out = ALPHABET[r] + out
    return out.rjust(22, "0")


def roster(company):
    return (Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
            .select_related("designation", "department", "section", "site").order_by("code"))


# ================================================================= measurement


def _measured_preflight(items, field_stats=None):
    """items: [(kind, side, ab, ctx, key)]. One approximate pass records every
    string, one layout pass measures them all, then the real pass."""
    from .metrics import FontMeasurer, prime

    rec = RecordingMeasurer()
    for kind, side, ab, ctx, _ in items:
        resolve_side(side, ctx, rec)
    prime(rec.asked)
    real = FontMeasurer()
    out = []
    for kind, side, ab, ctx, key in items:
        findings, resolved = preflight_side(kind, side, ab, ctx, real, field_stats)
        out.append((key, kind, findings, resolved))
    return out


# ================================================================== templates


def template_out(t, *, full=False):
    out = {
        "uid": str(t.uid), "code": t.code, "name": t.name, "nameBn": t.name_bn or None,
        "description": t.description or None, "version": t.version, "preset": t.preset,
        "widthMm": float(t.width_mm), "heightMm": float(t.height_mm), "cornerRadiusMm": float(t.corner_radius_mm),
        "bleedMm": float(t.bleed_mm), "safeAreaMm": float(t.safe_area_mm), "status": t.status, "locked": t.locked,
        "isDefault": t.is_default, "hasBack": t.back_json is not None,
        "publishedAt": t.published_at.isoformat() if t.published_at else None,
        "publishedBy": t.published_by_name or None, "updatedAt": t.updated_at.isoformat(),
        "publishFindings": t.publish_findings,
    }
    if full:
        out.update(front=t.front_json, back=t.back_json)
    return out


def templates(company):
    ensure_setup(company)
    rows = list(CardTemplate.objects.filter(company=company).order_by("code", "-version"))
    by_code = defaultdict(list)
    for t in rows:
        by_code[t.code].append(t)
    live = Card.objects.filter(company=company, status__in=("ISSUED", "ACTIVE"))
    counts = defaultdict(int)
    for code in live.values_list("template__code", flat=True):
        counts[code] += 1
    out = []
    for code, versions in by_code.items():
        published = next((v for v in versions if v.status == "PUBLISHED"), None)
        draft = next((v for v in versions if v.status == "DRAFT"), None)
        head = draft or published or versions[0]
        out.append({**template_out(head), "currentVersion": published.version if published else None,
                    "currentUid": str(published.uid) if published else None,
                    "draftUid": str(draft.uid) if draft else None, "liveCards": counts[code],
                    "versions": [{"uid": str(v.uid), "version": v.version, "status": v.status, "locked": v.locked}
                                 for v in versions]})
    out.sort(key=lambda r: (not r["isDefault"], r["name"]))
    return out


def _validated(front, back):
    problems = validate_side(front, "front") + (validate_side(back, "back") if back is not None else [])
    if problems:
        raise CardRefused({"template": problems}, status=400)


def create_template(company, *, code, name, preset, name_bn="", description="", user=None, copy_of=None):
    ensure_setup(company)
    code = str(code or "").strip().lower().replace(" ", "-")
    if not code or not name:
        raise CardRefused({"code": ["A template needs a code and a name."]}, status=400)
    if CardTemplate.objects.filter(company=company, code=code).exists():
        raise CardRefused({"code": [f"A template {code} already exists."]}, status=409)
    if copy_of is not None:
        w, h, front, back = copy_of.width_mm, copy_of.height_mm, copy_of.front_json, copy_of.back_json
        preset = copy_of.preset
    else:
        if preset not in PRESETS:
            raise CardRefused({"preset": [f"preset is one of {', '.join(PRESETS)}."]}, status=400)
        w, h, _ = PRESETS[preset]
        front = {"kind": "front", "background": {"type": "solid", "color": "#FFFFFF"}, "elements": []}
        back = None
    t = CardTemplate.objects.create(company=company, code=code, name=name, name_bn=name_bn, description=description,
                                    preset=preset, width_mm=w, height_mm=h, front_json=front, back_json=back,
                                    created_by=_who(user), created_by_name=_name(user))
    audit(company, "TEMPLATE_SAVED", user, template=t, after={"code": code, "version": 1})
    return t


def save_template(company, t, data, *, user=None):
    """§5.1. Only a draft is edited in place. A published or locked version
    is never changed: the edit becomes the code's draft (version n+1),
    created if there is none -- so a 2026 reprint reproduces the 2026 card."""
    front = data.get("front", t.front_json)
    back = data.get("back", t.back_json) if "back" in data else t.back_json
    _validated(front, back)
    versioned = False
    with transaction.atomic():
        if t.status != "DRAFT" or t.locked:
            draft = CardTemplate.objects.filter(company=company, code=t.code, status="DRAFT").first()
            if draft is None:
                top = CardTemplate.objects.filter(company=company, code=t.code).order_by("-version").first()
                draft = CardTemplate.objects.create(
                    company=company, code=t.code, name=t.name, name_bn=t.name_bn, description=t.description,
                    version=top.version + 1, preset=t.preset, width_mm=t.width_mm, height_mm=t.height_mm,
                    corner_radius_mm=t.corner_radius_mm, bleed_mm=t.bleed_mm, safe_area_mm=t.safe_area_mm,
                    front_json=t.front_json, back_json=t.back_json, is_default=t.is_default,
                    created_by=_who(user), created_by_name=_name(user))
                audit(company, "TEMPLATE_VERSIONED", user, template=draft,
                      after={"from": t.version, "to": draft.version, "locked": t.locked})
            t, versioned = draft, True
        for field in ("name", "name_bn", "description"):
            key = {"name_bn": "nameBn"}.get(field, field)
            if key in data:
                setattr(t, field, str(data[key] or "").strip())
        for field, key in (("bleed_mm", "bleedMm"), ("safe_area_mm", "safeAreaMm"),
                           ("corner_radius_mm", "cornerRadiusMm")):
            if key in data:
                setattr(t, field, data[key])
        if "preset" in data and data["preset"] != t.preset:
            if data["preset"] == "CUSTOM":
                t.width_mm, t.height_mm = data.get("widthMm", t.width_mm), data.get("heightMm", t.height_mm)
            elif data["preset"] in PRESETS:
                t.width_mm, t.height_mm, _ = PRESETS[data["preset"]]
            t.preset = data["preset"]
        t.front_json, t.back_json = front, back
        try:
            t.save()
        except IntegrityError:
            raise CardRefused({"template": ["The corner radius does not fit the card."]}, status=400) from None
        audit(company, "TEMPLATE_SAVED", user, template=t, after={"version": t.version})
    return t, versioned


def preflight_template(company, t, employees=None):
    """§4.3 against the roster: each finding once, with the employees it
    affects -- 'Employee name does not fit its box for 2 employees'."""
    employees = list(employees if employees is not None else roster(company))
    ab = artboard(template_out_raw(t))
    sides = [("front", t.front_json)] + ([("back", t.back_json)] if t.back_json is not None else [])
    paths = set()
    for _, side in sides:
        paths |= bindings_of(side)
    stats = C.field_stats(company, employees, paths)
    photos, customs, comp = C.current_photos(employees), C.custom_values(employees), C.company_ctx(company)
    sample = employees or [None]
    items = []
    for e in sample:
        ctx = C.live_context(company, e, photos=photos, customs=customs, company_part=comp) if e else \
            {"employee": {}, "company": comp, "card": C.card_ctx(None), "custom": {}}
        for kind, side in sides:
            items.append((kind, side, ab, ctx, e.code if e else None))
    grouped = {}
    for code, kind, findings, _ in _measured_preflight(items, stats):
        for f in findings:
            key = (f["side"], f["elementId"] or f["element"], f["severity"], f["message"].split(":")[0][:40])
            g = grouped.setdefault(key, {**f, "employees": []})
            if code and code not in g["employees"]:
                g["employees"].append(code)
    findings = sorted(grouped.values(), key=lambda f: (f["severity"] != "error", f["side"], f["element"]))
    for f in findings:
        n = len(f["employees"])
        f["affected"] = n
        if employees and 0 < n < len(employees):
            f["message"] += f" ({n} of {len(employees)} employees)"
    return {**summarise(findings), "fieldStats": stats, "roster": len(employees)}


def template_out_raw(t):
    return {"width_mm": t.width_mm, "height_mm": t.height_mm, "bleed_mm": t.bleed_mm,
            "safe_area_mm": t.safe_area_mm, "corner_radius_mm": t.corner_radius_mm}


def publish_template(company, t, *, acknowledge_errors=False, user=None):
    """§5.2. Errors need an explicit acknowledgement, recorded with who gave it."""
    if t.status != "DRAFT":
        raise CardRefused({"template": [f"Version {t.version} is {t.status.lower()}; publish a draft."]}, status=409)
    report = preflight_template(company, t)
    if report["errors"] and not acknowledge_errors:
        raise CardRefused({"template": [f"Preflight found {report['errors']} errors. Fix them, or acknowledge them "
                                        "to publish anyway — the acknowledgement is recorded."]},
                          status=422, detail=report)
    with transaction.atomic():
        CardTemplate.objects.filter(company=company, code=t.code, status="PUBLISHED").update(status="ARCHIVED")
        t.status, t.published_at, t.published_by, t.published_by_name = "PUBLISHED", timezone.now(), _who(user), _name(user)
        t.publish_findings = {"errors": report["errors"], "warnings": report["warnings"],
                              "acknowledgedBy": _name(user) if report["errors"] else None,
                              "findings": report["findings"][:50]}
        t.save()
        audit(company, "TEMPLATE_PUBLISHED", user, template=t, after=t.publish_findings)
        event(company, "TemplatePublished", template=t.code, version=t.version, actor=user,
              message=f"Card template {t.name} v{t.version} published")
    return t, report


# ================================================================= resolution


def published(company, code):
    return CardTemplate.objects.filter(company=company, code=code, status="PUBLISHED").order_by("-version").first()


def template_for(company, employee, rules=None, comp=None, photos=None, customs=None):
    """The first enabled rule that matches, by priority; else the default."""
    rules = rules if rules is not None else list(ResolutionRule.objects.filter(company=company, enabled=True))
    if rules:
        ctx = C.live_context(company, employee, photos=photos or {}, customs=customs or {},
                             company_part=comp or C.company_ctx(company))
        for r in sorted(rules, key=lambda r: r.priority):
            if eval_condition(r.condition, ctx):
                t = published(company, r.template_code)
                if t:
                    return t, r
    default = (CardTemplate.objects.filter(company=company, status="PUBLISHED", is_default=True)
               .order_by("-version").first()
               or CardTemplate.objects.filter(company=company, status="PUBLISHED").order_by("code", "-version").first())
    return default, None


# ====================================================================== cards


def effective_status(card, today=None):
    """Stored status, with expiry read against today."""
    today = today or clock.today()
    if card.status in ("ISSUED", "ACTIVE") and card.expires_on:
        if card.expires_on < today:
            return "EXPIRED"
        if card.expires_on <= today + timedelta(days=30):
            return "EXPIRING"
    return card.status


def card_out(card, today=None):
    return {
        "uid": str(card.uid), "number": card.card_number, "status": card.status,
        "effectiveStatus": effective_status(card, today), "employee": {"code": card.employee.code,
                                                                       "nameEn": card.employee.name_en},
        "template": {"uid": str(card.template.uid), "code": card.template.code, "name": card.template.name,
                     "version": card.template_version},
        "issuedOn": card.issued_on.isoformat() if card.issued_on else None,
        "expiresOn": card.expires_on.isoformat() if card.expires_on else None,
        "issuedBy": card.issued_by_name or None, "revokedOn": card.revoked_on.isoformat() if card.revoked_on else None,
        "revokeReason": card.revoke_reason or None, "revokedBy": card.revoked_by_name or None,
        "replacedBy": card.replaced_by.card_number if card.replaced_by_id else None,
        "printCount": card.print_count, "lastPrintedAt": card.last_printed_at.isoformat() if card.last_printed_at else None,
        "lastPrintedBy": card.last_printed_by_name or None, "verifyUrl": C.verify_url(card.verify_token),
        "snapshot": card.data_snapshot,
    }


def _next_number(company, year):
    s, _ = CardSettings.objects.get_or_create(company=company)
    head = f"{s.number_prefix}-{year}-"
    last = (Card.objects.filter(company=company, card_number__startswith=head).order_by("-card_number")
            .values_list("card_number", flat=True).first())
    n = int(last[len(head):]) + 1 if last else 1
    return f"{head}{n:05d}"


def card_preflight(company, card_or_ctx, t):
    """One card's findings, measured. Used by issue and by print jobs."""
    ab = artboard(template_out_raw(t))
    ctx = card_or_ctx
    sides = [("front", t.front_json)] + ([("back", t.back_json)] if t.back_json is not None else [])
    findings = []
    resolved = {}
    for _, kind, f, res in _measured_preflight([(k, s, ab, ctx, None) for k, s in sides]):
        findings += f
        resolved[kind] = res
    return summarise(findings), resolved


def issue_card(company, employee, *, template=None, expires_on=None, user=None, replaces=None):
    """§5.3: snapshot the bound values, number the card, a random token,
    lock the version. Refused when the employee already has a live card, or
    the preflight finds an error, or the template wants a photo and there
    is none."""
    ensure_setup(company)
    t = template or template_for(company, employee)[0]
    if t is None or t.status != "PUBLISHED":
        raise CardRefused({"template": ["No published template to issue on."]}, status=422)
    today = clock.today()
    settings_, _ = CardSettings.objects.get_or_create(company=company)
    expires = expires_on or date(today.year + settings_.validity_years, today.month, min(today.day, 28))
    if expires <= today:
        raise CardRefused({"expiresOn": ["The expiry is after the issue date."]}, status=400)
    photos = C.current_photos([employee])
    paths = bindings_of(t.front_json) | (bindings_of(t.back_json) if t.back_json else set())
    if "employee.photo" in paths and employee.pk not in photos:
        raise CardRefused({"photo": [f"{employee.name_en} has no photo. Add one in the photo studio first."]},
                          status=422)
    with transaction.atomic():
        Employee.objects.select_for_update().get(pk=employee.pk)
        live = Card.objects.filter(employee=employee, status__in=("ISSUED", "ACTIVE")).exclude(
            pk=replaces.pk if replaces else None).first()
        if live:
            raise CardRefused({"employee": [f"{employee.name_en} already has a live card ({live.card_number}). "
                                            "Replace it, or revoke it first."]}, status=409)
        card = Card(company=company, employee=employee, card_number=_next_number(company, today.year), template=t,
                    template_version=t.version, data_snapshot={}, photo_asset=photos.get(employee.pk),
                    status="DRAFT", issued_on=today, expires_on=expires, issued_by=_who(user),
                    issued_by_name=_name(user), verify_token=new_token(), created_by=_who(user),
                    created_by_name=_name(user))
        ctx = C.live_context(company, employee, card=card, photos=photos)
        card.data_snapshot = C.snapshot(ctx, paths)
        report, _ = card_preflight(company, C.from_snapshot(card.data_snapshot, card), t)
        if report["errors"]:
            raise CardRefused({"preflight": [f"{report['errors']} preflight errors: "
                                             + "; ".join(f["message"] for f in report["findings"]
                                                         if f["severity"] == "error")]},
                              status=422, detail=report)
        if replaces is not None:
            replaces.status = "REPLACED"
            replaces.save(update_fields=["status", "updated_at"])
        card.status = "ISSUED"
        card.save()
        if replaces is not None:
            replaces.replaced_by = card
            replaces.save(update_fields=["replaced_by", "updated_at"])
        audit(company, "CARD_ISSUED", user, card=card, template=t,
              after={"number": card.card_number, "version": t.version, "warnings": report["warnings"]})
        event(company, "CardIssued", card, number=card.card_number, employee=employee.code, actor=user,
              message=f"{card.card_number} issued to {employee.name_en}")
    return card, report


def revoke_card(company, card, *, reason, lost=False, user=None):
    """§5.4. Never deleted: a guard scanning it gets 'revoked on 14 March',
    not 'unknown card'."""
    reason = _reason(reason, "the reason for revoking")
    if card.status not in ("DRAFT", "ISSUED", "ACTIVE"):
        raise CardRefused({"card": [f"{card.card_number} is already {card.status.lower()}."]}, status=409)
    card.status = "LOST" if lost else "REVOKED"
    card.revoked_on, card.revoked_by, card.revoked_by_name, card.revoke_reason = clock.today(), _who(user), _name(user), reason
    card.save()
    audit(company, "CARD_LOST" if lost else "CARD_REVOKED", user, card=card, reason=reason)
    event(company, "CardRevoked", card, number=card.card_number, status=card.status, reason=reason,
          employee=card.employee.code, actor=user,
          message=f"{card.card_number} ({card.employee.name_en}) {'reported lost' if lost else 'revoked'}")
    return card


def replace_card(company, card, *, reason, user=None):
    """A replacement moves the old card to REPLACED and points it forward.
    The new card snapshots today's record."""
    reason = _reason(reason, "the reason for replacing")
    if card.replaced_by_id:
        raise CardRefused({"card": [f"Already replaced by {card.replaced_by.card_number}."]}, status=409)
    new, report = issue_card(company, card.employee, user=user, replaces=card)
    audit(company, "CARD_REPLACED", user, card=card, reason=reason, after={"replacedBy": new.card_number})
    return new, report


def gallery(company, *, q="", flt="ALL"):
    """Everyone on the roster with their live (or latest) card, which
    template they resolve to, and whether their data is complete."""
    ensure_setup(company)
    today = clock.today()
    employees = list(roster(company))
    if q:
        needle = q.lower()
        employees = [e for e in employees if needle in e.code.lower() or needle in e.name_en.lower()
                     or needle in (e.name_bn or "")]
    cards = defaultdict(list)
    for c in (Card.objects.filter(company=company, employee__in=employees).select_related("template", "employee",
                                                                                          "replaced_by")
              .order_by("-created_at")):
        cards[c.employee_id].append(c)
    rules = list(ResolutionRule.objects.filter(company=company, enabled=True))
    photos, customs, comp = C.current_photos(employees), C.custom_values(employees), C.company_ctx(company)
    templates_cache = {}
    rows = []
    for e in employees:
        t, rule = template_for(company, e, rules, comp, photos, customs)
        if t is not None:
            templates_cache[t.pk] = t
        mine = cards.get(e.pk, [])
        live = next((c for c in mine if c.status in ("ISSUED", "ACTIVE")), None)
        latest = live or (mine[0] if mine else None)
        missing = []
        if e.pk not in photos:
            missing.append("photo")
        if not e.designation_id:
            missing.append("designation")
        status = effective_status(latest, today) if latest else "NOT_ISSUED"
        rows.append({"code": e.code, "nameEn": e.name_en, "nameBn": e.name_bn or None,
                     "designation": e.designation.title if e.designation_id else None,
                     "department": e.department.title if e.department_id else None,
                     "template": {"uid": str(t.uid), "code": t.code, "name": t.name, "version": t.version} if t else None,
                     "rule": rule.label if rule else None, "card": card_out(latest, today) if latest else None,
                     "status": status, "missing": missing, "hasPhoto": e.pk in photos,
                     "photo": C.photo_ref(photos.get(e.pk))})
    counts = {"ALL": len(rows), "NOT_ISSUED": sum(r["status"] == "NOT_ISSUED" for r in rows),
              "EXPIRING": sum(r["status"] in ("EXPIRING", "EXPIRED") for r in rows),
              "MISSING": sum(bool(r["missing"]) for r in rows),
              "REVOKED": sum(r["status"] in ("REVOKED", "LOST", "REPLACED") for r in rows)}
    pick = {"NOT_ISSUED": lambda r: r["status"] == "NOT_ISSUED",
            "EXPIRING": lambda r: r["status"] in ("EXPIRING", "EXPIRED"),
            "MISSING": lambda r: bool(r["missing"]),
            "REVOKED": lambda r: r["status"] in ("REVOKED", "LOST", "REPLACED")}.get(flt)
    if pick:
        rows = [r for r in rows if pick(r)]
    return {"rows": rows, "counts": counts}


def card_context(company, card):
    return C.from_snapshot(card.data_snapshot, card)


def employee_preview(company, employee, t):
    """What a card for `employee` on `t` would say now, before issue."""
    ctx = C.live_context(company, employee)
    report, resolved = card_preflight(company, ctx, t)
    return ctx, report


# ================================================================= print jobs


def profile_out(p):
    return {"uid": str(p.uid), "name": p.name, "note": p.note or None, "sheet": p.sheet, "cols": p.cols,
            "rows": p.rows, "gutterMm": float(p.gutter_mm), "marginMm": float(p.margin_mm),
            "includeBleed": p.include_bleed, "cropMarks": p.crop_marks, "duplex": p.duplex,
            "colourProfile": p.colour_profile, "dpi": p.dpi, "mirror": p.mirror, "isDefault": p.is_default,
            "cardsPerSheet": p.cards_per_sheet}


def check_cards(company, cards):
    """Preflight every card from its snapshot, in one measured pass."""
    items, index = [], {}
    for c in cards:
        t = c.template
        ab = artboard(template_out_raw(t))
        ctx = card_context(company, c)
        for kind, side in [("front", t.front_json)] + ([("back", t.back_json)] if t.back_json is not None else []):
            items.append((kind, side, ab, ctx, c.pk))
        index[c.pk] = c
    per = defaultdict(list)
    for key, kind, findings, _ in _measured_preflight(items):
        per[key] += findings
    out = []
    for pk, c in index.items():
        s = summarise(per[pk])
        out.append({"card": str(c.uid), "number": c.card_number, "code": c.employee.code, "nameEn": c.employee.name_en,
                    "errors": s["errors"], "warnings": s["warnings"], "findings": s["findings"]})
    return out


def submit_job(company, card_uids, profile_uid, *, include_warnings=False, name="", user=None, render=True):
    """§5.5. Cards with errors never reach the file -- the database refuses
    a ready job with errors -- and cards with warnings only when asked.
    The preflight is stored as it stood at submission."""
    profile = OutputProfile.objects.filter(company=company, uid=profile_uid).first()
    if profile is None:
        raise CardRefused({"profile": ["Choose an output profile."]}, status=400)
    cards = list(Card.objects.filter(company=company, uid__in=card_uids or [])
                 .select_related("template", "employee"))
    if not cards:
        raise CardRefused({"cards": ["Choose at least one issued card."]}, status=400)
    wrong = [c.card_number for c in cards if c.status not in ("ISSUED", "ACTIVE")]
    if wrong:
        raise CardRefused({"cards": [f"Only issued or active cards print; {', '.join(wrong)} are not."]}, status=422)
    checks = check_cards(company, cards)
    keep, skipped = [], []
    by_uid = {str(c.uid): c for c in cards}
    for r in checks:
        if r["errors"]:
            skipped.append({"code": r["code"], "card": r["number"], "why": f"{r['errors']} errors"})
        elif r["warnings"] and not include_warnings:
            skipped.append({"code": r["code"], "card": r["number"], "why": f"{r['warnings']} warnings, not included"})
        else:
            keep.append(by_uid[r["card"]])
    if not keep:
        raise CardRefused({"cards": ["Nothing left to print: every card has errors or warnings not included."]},
                          status=422, detail={"checks": checks})
    with transaction.atomic():
        last = (PrintJob.objects.filter(company=company).order_by("-created_at").values_list("reference", flat=True)
                .first())
        n = int(last.split("-")[1]) + 1 if last else 1
        job = PrintJob.objects.create(
            company=company, reference=f"JOB-{n:04d}", name=(name or "").strip()[:120], output_profile=profile,
            profile_snapshot=profile_out(profile), card_count=len(keep), skipped=skipped,
            preflight_json={"checks": checks, "at": timezone.now().isoformat()},
            preflight_errors=0, include_warnings=include_warnings, submitted_by=_who(user),
            submitted_by_name=_name(user))
        job.cards.set(keep)
        audit(company, "PRINT_SUBMITTED", user, job=job,
              after={"cards": len(keep), "skipped": len(skipped), "profile": profile.name})
    if render:
        from ..tasks import render_print_job

        transaction.on_commit(lambda: render_print_job.delay(job.pk))
    return job


def render_job(job):
    """Render the artifact; READY with its sha256, or FAILED with the reason.
    The first print locks each template version used."""
    from .metrics import FontMeasurer, prime
    from .render import asset_loader, render_cards, sha256

    company = job.company
    PrintJob.objects.filter(pk=job.pk).update(status="RENDERING")
    try:
        cards = list(job.cards.select_related("template", "employee").order_by("employee__code"))
        rec = RecordingMeasurer()
        prepared = []
        for c in cards:
            ctx = card_context(company, c)
            t = c.template
            for side in [t.front_json] + ([t.back_json] if t.back_json else []):
                resolve_side(side, ctx, rec)
            prepared.append((c, ctx))
        prime(rec.asked)
        real = FontMeasurer()
        docs = [{"front": resolve_side(c.template.front_json, ctx, real),
                 "back": resolve_side(c.template.back_json, ctx, real) if c.template.back_json else None,
                 "artboard": artboard(template_out_raw(c.template)), "code": c.employee.code} for c, ctx in prepared]
        data, ctype, ext, pages = render_cards(docs, job.profile_snapshot | {
            "include_bleed": job.profile_snapshot["includeBleed"], "crop_marks": job.profile_snapshot["cropMarks"],
            "margin_mm": job.profile_snapshot["marginMm"], "gutter_mm": job.profile_snapshot["gutterMm"]},
            asset_loader(lambda aid: open_asset(company, aid)))
        with transaction.atomic():
            job.refresh_from_db()
            job.artifact.save(f"{job.reference}.{ext}", ContentFile(data), save=False)
            job.artifact_sha256, job.artifact_pages = sha256(data), pages
            job.status, job.completed_at = "READY", timezone.now()
            job.purge_after = timezone.now() + timedelta(days=90)
            job.save()
            CardTemplate.objects.filter(pk__in={c.template_id for c in cards}).update(locked=True)
            audit(company, "PRINT_COMPLETED", None, job=job, after={"sha256": job.artifact_sha256, "pages": pages})
            event(company, "PrintJobReady", reference=job.reference, cards=len(cards),
                  message=f"{job.reference}: {len(cards)} cards ready to print")
    except Exception as exc:  # noqa: BLE001 -- a failed render is a state, reported
        PrintJob.objects.filter(pk=job.pk).update(status="FAILED", failure_reason=str(exc)[:1000])
        audit(company, "PRINT_FAILED", None, job=job, reason=str(exc)[:1000])
        event(company, "PrintJobFailed", reference=job.reference, reason=str(exc)[:300],
              message=f"{job.reference} failed to render")
    job.refresh_from_db()
    return job


def mark_printed(company, job, *, user=None):
    if job.status != "READY":
        raise CardRefused({"job": [f"{job.reference} is {job.status.lower()}, not ready."]}, status=409)
    now = timezone.now()
    with transaction.atomic():
        job.status, job.printed_at = "PRINTED", now
        job.save(update_fields=["status", "printed_at", "updated_at"])
        for c in job.cards.all():
            c.print_count += 1
            c.last_printed_at, c.last_printed_by_name = now, _name(user)
            if c.status == "ISSUED":
                c.status = "ACTIVE"
                audit(company, "CARD_ACTIVATED", user, card=c, job=job)
            c.save(update_fields=["print_count", "last_printed_at", "last_printed_by_name", "status", "updated_at"])
        audit(company, "PRINT_MARKED", user, job=job)
    return job


def job_out(job, *, detail=False):
    out = {"uid": str(job.uid), "reference": job.reference, "name": job.name or None, "status": job.status,
           "profile": job.profile_snapshot.get("name"), "cards": job.card_count, "skipped": job.skipped,
           "submittedBy": job.submitted_by_name or None, "submittedAt": job.created_at.isoformat(),
           "completedAt": job.completed_at.isoformat() if job.completed_at else None,
           "printedAt": job.printed_at.isoformat() if job.printed_at else None,
           "sha256": job.artifact_sha256 or None, "pages": job.artifact_pages,
           "purgeAfter": job.purge_after.isoformat() if job.purge_after else None,
           "failure": job.failure_reason or None, "hasArtifact": bool(job.artifact)}
    if detail:
        out["preflight"] = job.preflight_json
    return out


# ===================================================================== media


SIGNER_SALT = "idcardio.media"


def sign_media(company, asset_uid, minutes=60):
    """§7.2 rule 5: a signed, short-lived URL. A permanent one is a leak
    the moment it is shared."""
    return TimestampSigner(salt=SIGNER_SALT).sign(f"{company.pk}:{asset_uid}:{minutes}")


def read_signed(token):
    try:
        raw = TimestampSigner(salt=SIGNER_SALT).unsign(token, max_age=24 * 3600)
        company_id, asset_uid, minutes = raw.split(":")
        TimestampSigner(salt=SIGNER_SALT).unsign(token, max_age=int(minutes) * 60)
        return int(company_id), asset_uid
    except (BadSignature, SignatureExpired, ValueError):
        return None


def open_asset(company, asset_id):
    a = MediaAsset.objects.filter(company=company, uid=asset_id, purged_at__isnull=True).first()
    if a is None:
        return None
    with a.file.open("rb") as f:
        return f.read(), a.crop, a.adjustments


def asset_out(company, a):
    w, h = a.placed_size
    return {"uid": str(a.uid), "kind": a.kind, "width": a.pixel_width, "height": a.pixel_height,
            "placedWidth": w, "placedHeight": h, "crop": a.crop, "adjustments": a.adjustments or {},
            "bytes": a.bytes, "mime": a.mime_type, "uploadedBy": a.uploaded_by_name or None,
            "uploadedAt": a.created_at.isoformat(), "retainUntil": a.retain_until.isoformat() if a.retain_until else None,
            "url": f"/api/v1/public/idcard-media/{sign_media(company, a.uid)}",
            "originalUrl": f"/api/v1/public/idcard-media/{sign_media(company, a.uid)}?original=1"}


def upload_asset(company, employee, upload, *, kind="PHOTO", user=None):
    from PIL import Image, UnidentifiedImageError

    raw = upload.read()
    if len(raw) > 12 * 1024 * 1024:
        raise CardRefused({"file": ["A photo is at most 12 MB."]}, status=400)
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError):
        raise CardRefused({"file": ["That file is not an image."]}, status=400) from None
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise CardRefused({"file": ["Use a JPEG, PNG or WebP image."]}, status=400)
    w, h = img.size
    with transaction.atomic():
        before = None
        if employee is not None:
            before = MediaAsset.objects.filter(employee=employee, kind=kind, is_current=True).first()
            MediaAsset.objects.filter(employee=employee, kind=kind, is_current=True).update(is_current=False)
        a = MediaAsset(company=company, employee=employee, kind=kind, mime_type=f"image/{img.format.lower()}",
                       pixel_width=w, pixel_height=h, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                       is_pii=kind in ("PHOTO", "SIGNATURE"), uploaded_by=_who(user), uploaded_by_name=_name(user))
        a.file.save(f"{secrets.token_hex(12)}.{img.format.lower()}", ContentFile(raw), save=False)
        a.save()
        if employee is not None and kind == "PHOTO":
            audit(company, "PHOTO_REPLACED", user, before={"asset": str(before.uid)} if before else None,
                  after={"asset": str(a.uid), "employee": employee.code, "px": [w, h]})
    return a


def adjust_asset(company, a, *, crop=None, adjustments=None, user=None):
    """Crop and adjustments are parameters; the original is always kept."""
    if crop is not None:
        try:
            x, y, w, h = (int(round(float(crop[k]))) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            raise CardRefused({"crop": ["A crop is x, y, w and h in source pixels."]}, status=400) from None
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > a.pixel_width or y + h > a.pixel_height:
            raise CardRefused({"crop": ["The crop falls outside the photo."]}, status=400)
        a.crop = {"x": x, "y": y, "w": w, "h": h}
    if adjustments is not None:
        a.adjustments = {k: max(-100, min(100, int(adjustments.get(k) or 0)))
                         for k in ("brightness", "contrast", "saturation")}
    a.save(update_fields=["crop", "adjustments", "updated_at"])
    return a


def photo_from_profile(company, employee, user=None):
    """The employee profile's photo, brought into the studio once."""
    if not employee.photo:
        raise CardRefused({"photo": ["The employee profile has no photo either."]}, status=404)
    with employee.photo.open("rb") as f:
        return upload_asset(company, employee, ContentFile(f.read(), name="profile"), user=user)


def apply_retention(company, today=None):
    """§11: a photo is kept for the retention period after separation, then
    the file is purged; a print artifact after 90 days."""
    today = today or clock.today()
    s, _ = CardSettings.objects.get_or_create(company=company)
    for e in Employee.objects.filter(company=company, separated_on__isnull=False):
        until = e.separated_on + timedelta(days=s.photo_retention_days)
        MediaAsset.objects.filter(employee=e, retain_until__isnull=True).update(retain_until=until)
    purged = 0
    for a in MediaAsset.objects.filter(company=company, retain_until__lt=today, purged_at__isnull=True):
        a.file.delete(save=False)
        a.purged_at = timezone.now()
        a.save(update_fields=["purged_at", "file", "updated_at"])
        purged += 1
    expired = 0
    for j in PrintJob.objects.filter(company=company, purge_after__lt=timezone.now()).exclude(artifact=""):
        j.artifact.delete(save=False)
        j.status = "EXPIRED" if j.status in ("READY", "PRINTED") else j.status
        j.save(update_fields=["artifact", "status", "updated_at"])
        expired += 1
    return {"photosPurged": purged, "artifactsPurged": expired}


# ===================================================================== fields


def field_out(f, population=None):
    return {"uid": str(f.uid), "key": f.key, "path": f.path, "label": f.label, "labelBn": f.label_bn or None,
            "kind": f.kind, "options": f.enum_options, "group": f.group_name, "help": f.help or None,
            "required": f.required, "isPii": f.is_pii, "printable": f.printable, "verifyVisible": f.verify_visible,
            "position": f.position, "population": population}


def save_field(company, data, *, field=None, user=None):
    key = str(data.get("key") or (field.key if field else "")).strip()
    if not key or not key.replace("_", "").isalnum():
        raise CardRefused({"key": ["A key is letters and digits, e.g. shiftGroup."]}, status=400)
    f = field or CardField(company=company, key=key)
    before = field_out(f) if field else None
    for attr, k in (("label", "label"), ("label_bn", "labelBn"), ("kind", "kind"), ("group_name", "group"),
                    ("help", "help")):
        if k in data:
            setattr(f, attr, str(data[k] or "").strip())
    for attr, k in (("required", "required"), ("is_pii", "isPii"), ("printable", "printable"),
                    ("verify_visible", "verifyVisible")):
        if k in data:
            setattr(f, attr, bool(data[k]))
    if "options" in data:
        f.enum_options = [str(o).strip() for o in data["options"] or [] if str(o).strip()]
    if "position" in data:
        f.position = int(data["position"] or 0)
    if f.is_pii:  # personal data never prints and never reaches the public page
        f.printable, f.verify_visible = False, False
    if not f.label:
        raise CardRefused({"label": ["A field needs a label."]}, status=400)
    if f.kind not in ("TEXT", "DATE", "NUMBER", "ENUM", "MULTI", "BOOLEAN"):
        raise CardRefused({"kind": ["Unknown kind."]}, status=400)
    try:
        f.save()
    except IntegrityError:
        raise CardRefused({"key": [f"A field {key} already exists."]}, status=409) from None
    audit(company, "FIELD_CHANGED", user, before=before, after=field_out(f))
    return f


def set_field_values(company, employee, values, *, user=None):
    fields = {f.key: f for f in CardField.objects.filter(company=company)}
    for key, value in (values or {}).items():
        f = fields.get(key)
        if f is None:
            raise CardRefused({"values": [f"No custom field {key}."]}, status=400)
        if value in (None, "", []):
            CardFieldValue.objects.filter(field=f, employee=employee).delete()
            continue
        if f.kind == "ENUM" and value not in f.enum_options:
            raise CardRefused({key: [f"{f.label} is one of {', '.join(f.enum_options)}."]}, status=400)
        if f.kind == "MULTI" and (not isinstance(value, list) or any(v not in f.enum_options for v in value)):
            raise CardRefused({key: [f"{f.label} takes options from {', '.join(f.enum_options)}."]}, status=400)
        CardFieldValue.objects.update_or_create(field=f, employee=employee,
                                                defaults={"company": company, "value": value})
    return {k: v for k, v in C.custom_values([employee], printable_only=False).get(employee.pk, {}).items()}


# ================================================================ verification

RATE = 50  # scans an hour, per IP and per token


def _throttled(key):
    from django.core.cache import cache

    bucket = f"idcard-verify:{key}:{timezone.now():%Y%m%d%H}"
    try:
        n = cache.incr(bucket)
    except ValueError:
        cache.add(bucket, 1, 3600)
        n = 1
    return n > RATE


def verify(token, ip):
    """§7: public, and it leaks nothing -- name, photo, code, designation,
    validity, the employer, and custom fields opted in. A revoked card is a
    definite answer, not a 404."""
    token = str(token or "")
    card = (Card.objects.filter(verify_token=token).select_related("company", "employee", "replaced_by").first()
            if 16 <= len(token) <= 32 and token.isalnum() else None)
    if _throttled(f"ip:{ip}") or (card and _throttled(f"tok:{token}")):
        if card:
            audit(card.company, "VERIFY_THROTTLED", None, card=card, ip=ip)
        return {"status": "THROTTLED", "message": "Too many checks from here. Try again in a while."}, 429
    if card is None:
        return {"status": "UNKNOWN", "message": "This is not a card this employer issued."}, 404
    audit(card.company, "VERIFY_SCANNED", None, card=card, ip=ip)
    s = card.data_snapshot
    status = effective_status(card)
    base = {"status": "EXPIRING" if status == "EXPIRING" else status, "employer": card.company.name,
            "employeeName": s.get("employee.fullName") or card.employee.name_en}
    if card.status in ("REVOKED", "LOST", "REPLACED"):
        return {**base, "revokedOn": card.revoked_on.isoformat() if card.revoked_on else None,
                "replacedBy": card.replaced_by.card_number if card.replaced_by_id else None}, 200
    if card.status == "DRAFT":
        return {**base, "status": "NOT_ISSUED"}, 200
    photo = s.get("employee.photo")
    visible = {f.key: f.label for f in CardField.objects.filter(company=card.company, verify_visible=True,
                                                                is_pii=False)}
    custom = [{"label": label, "value": s.get(f"custom.{key}")} for key, label in visible.items()
              if s.get(f"custom.{key}") not in (None, "", [])]
    return {**base, "employeeNameBn": s.get("employee.fullNameBn"), "employeeCode": card.employee.code,
            "designation": s.get("employee.job.designation"), "cardNumber": card.card_number,
            "photoUrl": (f"/api/v1/public/idcard-media/{sign_media(card.company, photo['assetId'], 5)}"
                         if photo else None),
            "issuedOn": card.issued_on.isoformat() if card.issued_on else None,
            "expiresOn": card.expires_on.isoformat() if card.expires_on else None, "custom": custom}, 200


__all__ = ["CardRefused", "Q"]
