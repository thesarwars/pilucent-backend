"""Pay library operations (components-n-structures-backend-done.md §4, §6).

Components and templates are versioned. A flag change never rewrites a
version: it makes version n+1 from a stated date, and every structure line
keeps resolving the version it pinned. Statutory constants come from the
rule book as at the date asked about; the provident-fund rates are the
PF scheme in payroll settings (paysetio).
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common import clock
from common.money import ZERO, money_str, round_to_paisa, to_decimal

from ..choices import BASE_FIELDS, BASES, ROUNDING_STEP
from ..models import (
    BulkRevision,
    LibraryAudit,
    LibraryEvent,
    PayComponent,
    StructureTemplate,
    StructureTemplateRow,
)
from .seed import GL_ACCOUNTS, ensure_components, ensure_library, ensure_policy

MIN_REASON = 10
HUNDRED = Decimal("100")


class LibraryRefused(Exception):
    def __init__(self, errors, status=422, detail=None):
        self.errors = errors
        self.status = status
        self.detail = detail
        super().__init__("; ".join(m for ms in errors.values() for m in ms))


def _who(user):
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _name(user):
    return (getattr(user, "name", "") or getattr(user, "email", "")) if user else ""


def _reason(text, what="a reason"):
    text = str(text or "").strip()
    if len(text) < MIN_REASON:
        raise LibraryRefused({"reason": [f"Give {what}, at least {MIN_REASON} characters ({len(text)} so far)."]})
    return text


def audit(company, action, user=None, *, entity_type, code, version=None, before=None, after=None, reason=""):
    LibraryAudit.objects.create(company=company, action=action, entity_type=entity_type, entity_code=code,
                                entity_version=version, actor=_who(user), actor_name=_name(user),
                                before_json=before, after_json=after, reason=reason or "")


def event(company, name, **payload):
    LibraryEvent.objects.create(company=company, name=name, payload=payload)


# =============================================================== components


def version_on(company, code, on):
    """The version of `code` in force on `on`."""
    ensure_components(company)
    return (PayComponent.objects.filter(company=company, code=code, effective_from__lte=on)
            .order_by("-effective_from", "-version").first())


def flags_of(company, code, version):
    """A line's eight bases, from the component version it pins. An unknown
    line counts toward nothing -- FALSE is the safe direction (§12)."""
    if company is not None:
        ensure_components(company)
    c = (PayComponent.objects.filter(company=company, code=code, version=version).first()
         if company is not None and version else None)
    out = {f: bool(getattr(c, f)) if c else False for f in BASE_FIELDS}
    out["version"] = c.version if c else None
    return out


def current_components(company):
    ensure_components(company)
    return list(PayComponent.objects.filter(company=company, superseded_by__isnull=True)
                .select_related("gl_account").order_by("display_order", "code"))


def gl_out(a):
    return {"uid": str(a.uid), "code": a.code, "title": a.title, "kind": a.kind} if a else None


def component_out(c, usage=None):
    return {
        "uid": str(c.uid), "code": c.code, "version": c.version, "name": c.name, "nameBn": c.name_bn or None,
        "kind": c.kind, "isDeduction": c.kind == "DEDUCTION", "calcBasis": c.calc_basis,
        "calcExpression": c.calc_expression or None,
        "flags": [getattr(c, f) for f in BASE_FIELDS],
        "bases": {key: getattr(c, f) for f, key, _, _ in BASES},
        "lockedFlags": c.locked_flags, "flagsFrozen": c.flags_frozen, "isStatutory": c.is_statutory,
        "statutoryBasis": c.statutory_basis or None, "gl": gl_out(c.gl_account),
        "suggestedGl": {"code": GL_ACCOUNTS[c.code][0], "title": GL_ACCOUNTS[c.code][1]} if c.code in GL_ACCOUNTS else None,
        "isActive": c.is_active, "effectiveFrom": c.effective_from.isoformat(), "displayOrder": c.display_order,
        "usage": usage,
    }


def component_usage(company):
    """Lines on live structures, per code (§11.2)."""
    from employeeio.models import EmployeeSalaryComponent

    today = clock.today()
    rows = (EmployeeSalaryComponent.objects
            .filter(structure__employee__company=company, structure__cancelled_at__isnull=True,
                    structure__effective_from__lte=today)
            .filter(Q(structure__effective_to__isnull=True) | Q(structure__effective_to__gte=today))
            .values_list("code", flat=True))
    out = defaultdict(int)
    for code in rows:
        out[code] += 1
    return out


def change_flags(company, component, changes, *, effective_from, reason, user=None):
    """§6.1. Each change is checked against the statutory lock -- set is
    allowed, unset is not -- and the component becomes version n+1 from
    `effective_from`. The version a structure pinned is untouched, so no past
    payslip is restated."""
    reason = _reason(reason, "the reason for changing a base")
    if component.superseded_by_id:
        raise LibraryRefused({"component": ["That version was already superseded: change the current one."]},
                             status=409)
    unknown = [k for k in changes if k not in BASE_FIELDS]
    if unknown:
        raise LibraryRefused({"flags": [f"Unknown base {', '.join(unknown)}."]}, status=400)
    moved = {k: bool(v) for k, v in changes.items() if bool(v) != getattr(component, k)}
    if not moved:
        raise LibraryRefused({"flags": ["Nothing changes."]}, status=400)
    if component.flags_frozen:
        raise LibraryRefused({"flags": [f"{component.name} is statutory — its bases are fixed. Rules module, not "
                                        "company data."]})
    unset = [k for k, v in moved.items() if not v and k in (component.locked_flags or [])]
    if unset:
        raise LibraryRefused({"flags": [f"{component.name} is statutory — {', '.join(unset)} cannot be unset. "
                                        "Change it in the rule book, not in company data."]})
    if component.kind == "DEDUCTION" and any(v for k, v in moved.items() if k != "prorate_part_month"):
        raise LibraryRefused({"flags": ["A deduction enters no earnings base."]})
    if effective_from < component.effective_from:
        raise LibraryRefused({"effectiveFrom": [f"The change takes effect on or after {component.effective_from}, "
                                                "when this version started."]})
    with transaction.atomic():
        fields = {f.name: getattr(component, f.name) for f in PayComponent._meta.concrete_fields
                  if f.name not in ("id", "uid", "created_at", "updated_at", "version", "superseded_by",
                                    "effective_from", "change_reason", "created_by", "created_by_name")}
        fields.update(moved)
        same_day = effective_from == component.effective_from and not _used(company, component)
        if same_day:
            # Nothing was ever built on it: correct it in place, still audited.
            for k, v in moved.items():
                setattr(component, k, v)
            component.change_reason = reason
            component.save()
            new = component
        else:
            new = PayComponent.objects.create(**fields, version=component.version + 1, effective_from=effective_from,
                                              change_reason=reason, created_by=_who(user), created_by_name=_name(user))
            component.superseded_by = new
            component.save(update_fields=["superseded_by", "updated_at"])
            audit(company, "COMPONENT_SUPERSEDED", user, entity_type="component", code=component.code,
                  version=component.version, after={"by": new.version, "from": effective_from.isoformat()})
            event(company, "ComponentSuperseded", code=component.code, version=new.version,
                  effectiveFrom=effective_from.isoformat())
        for k, v in moved.items():
            audit(company, "FLAG_CHANGED", user, entity_type="component", code=component.code, version=new.version,
                  before={k: not v}, after={k: v}, reason=reason)
        event(company, "ComponentFlagsChanged", code=component.code, version=new.version, changes=moved,
              effectiveFrom=effective_from.isoformat())
    return new


def _used(company, component):
    from employeeio.models import EmployeeSalaryComponent

    return EmployeeSalaryComponent.objects.filter(structure__employee__company=company, code=component.code,
                                                  component_version=component.version).exists()


def edit_component(company, component, data, *, user=None):
    """Name, Bangla name, calculation and display order -- not the bases."""
    before = component_out(component)
    for attr, key in (("name", "name"), ("name_bn", "nameBn"), ("calc_expression", "calcExpression")):
        if key in data:
            setattr(component, attr, str(data[key] or "").strip())
    if not component.name:
        raise LibraryRefused({"name": ["A component needs a name."]}, status=400)
    try:
        component.save()
    except IntegrityError:
        raise LibraryRefused({"calcExpression": ["A derived component needs its expression."]}, status=400) from None
    audit(company, "COMPONENT_EDITED", user, entity_type="component", code=component.code, version=component.version,
          before={k: before[k] for k in ("name", "nameBn", "calcExpression")},
          after={k: component_out(component)[k] for k in ("name", "nameBn", "calcExpression")})
    return component


def create_component(company, data, *, user=None):
    """A company component. FALSE on every base until set deliberately --
    the safe direction (§12): an under-counted base shows up as a low figure
    somebody queries."""
    from ..choices import CalcBasisChoices, ComponentKindChoices

    ensure_components(company)
    code = str(data.get("code") or "").strip().upper()
    if not code.isalnum() or len(code) > 10:
        raise LibraryRefused({"code": ["A code is up to ten letters and digits, e.g. LOAN."]}, status=400)
    if PayComponent.objects.filter(company=company, code=code).exists():
        raise LibraryRefused({"code": [f"A component {code} already exists."]}, status=409)
    kind, basis = data.get("kind"), data.get("calcBasis")
    if kind not in ComponentKindChoices.values or basis not in CalcBasisChoices.values:
        raise LibraryRefused({"kind": ["Choose the kind and how it is calculated."]}, status=400)
    if basis == "DERIVED" and not str(data.get("calcExpression") or "").strip():
        raise LibraryRefused({"calcExpression": ["A derived component states how it is derived."]}, status=400)
    order = (PayComponent.objects.filter(company=company).order_by("-display_order")
             .values_list("display_order", flat=True).first() or 0) + 1
    c = PayComponent.objects.create(
        company=company, code=code, version=1, name=str(data.get("name") or code).strip(),
        name_bn=str(data.get("nameBn") or "").strip(), kind=kind, calc_basis=basis,
        calc_expression=str(data.get("calcExpression") or "").strip(), display_order=order,
        effective_from=clock.today(), prorate_part_month=kind == "EARNING", created_by=_who(user),
        created_by_name=_name(user), **{f: False for f in BASE_FIELDS if f != "prorate_part_month"})
    audit(company, "COMPONENT_CREATED", user, entity_type="component", code=code, version=1, after=component_out(c))
    return c


def map_gl(company, component, account, *, user=None):
    """Map a component to an account in the company's chart of accounts.
    Mapping is not a base change: every version of the code takes it."""
    if account is not None and account.company_id != company.pk:
        raise LibraryRefused({"account": ["Not an account of this company."]}, status=404)
    before = gl_out(component.gl_account)
    was_blocked = bool(readiness(company)["blocked"])
    PayComponent.objects.filter(company=company, code=component.code).update(gl_account=account)
    audit(company, "GL_MAPPED", user, entity_type="component", code=component.code, version=component.version,
          before=before, after=gl_out(account))
    if was_blocked and not readiness(company)["blocked"]:
        event(company, "GlMappingCompleted")
    component.refresh_from_db()
    return component


def create_payroll_accounts(company, codes=None, *, user=None):
    """Create the payroll accounts the seed expects and are missing, in the
    company's own chart of accounts, and map them. An advance is an ASSET:
    the company is owed the money."""
    from accounts.models import ChartOfAccount

    made, mapped = [], []
    for c in current_components(company):
        if c.gl_account_id or c.code not in GL_ACCOUNTS or (codes and c.code not in codes):
            continue
        code, title, kind = GL_ACCOUNTS[c.code]
        account = (ChartOfAccount.objects.filter(company=company, title__iexact=title).exclude(status="REMOVED")
                   .first())
        if account is None:
            account = ChartOfAccount.objects.create(company=company, title=title, code=code, kind=kind,
                                                    status="ACTIVE", currency="BDT")
            made.append(title)
        map_gl(company, c, account, user=user)
        mapped.append(c.code)
    return {"created": made, "mapped": mapped}


def readiness(company):
    """§6.4: any active component without an account blocks the journal --
    a block, not a warning: an unmapped component means a journal that does
    not balance."""
    blocked = [{"code": c.code, "name": c.name} for c in current_components(company)
               if c.is_active and c.gl_account_id is None]
    return {"blocked": blocked, "ready": not blocked,
            "message": None if not blocked else
            f"{len(blocked)} component{'s' if len(blocked) != 1 else ''} not mapped to a GL account — blocks the "
            "payroll journal."}


# ================================================================ templates


def template_out(t, usage=None):
    return {
        "uid": str(t.uid), "code": t.code, "version": t.version, "name": t.name, "nameBn": t.name_bn or None,
        "mode": t.mode, "note": t.note, "balancingCode": t.balancing_code, "gazette": t.gazette,
        "gradeScope": t.grade_scope, "siteScope": t.site_scope, "status": t.status, "locked": t.locked,
        "effectiveFrom": t.effective_from.isoformat(), "displayOrder": t.display_order,
        "publishedAt": t.published_at.isoformat() if t.published_at else None,
        "publishedBy": t.published_by_name or None, "superseded": bool(t.superseded_by_id),
        "rows": [{"code": r.component_code, "basis": r.basis, "value": f"{r.value.normalize():f}"}
                 for r in t.rows.all()],
        "usage": usage,
    }


def template_usage(company):
    """Live structures per template code (§11.2): 148 is not safe to edit."""
    from employeeio.models import EmployeeSalaryStructure

    today = clock.today()
    out = defaultdict(int)
    for code in (EmployeeSalaryStructure.objects.filter(employee__company=company).in_force_on(today)
                 .values_list("template", flat=True)):
        out[code] += 1
    return out


def templates(company):
    ensure_library(company)
    usage = template_usage(company)
    rows = StructureTemplate.objects.filter(company=company).prefetch_related("rows").order_by(
        "display_order", "code", "-version")
    by_code = defaultdict(list)
    for t in rows:
        by_code[t.code].append(t)
    out = []
    for code, versions in by_code.items():
        current = next((v for v in versions if v.status == "PUBLISHED" and not v.superseded_by_id), None)
        draft = next((v for v in versions if v.status == "DRAFT"), None)
        head = draft or current or versions[0]
        out.append({**template_out(current or head, usage.get(code, 0)),
                    "draft": template_out(draft) if draft else None,
                    "versions": [{"uid": str(v.uid), "version": v.version, "status": v.status,
                                  "effectiveFrom": v.effective_from.isoformat()} for v in versions]})
    return sorted(out, key=lambda r: (r["displayOrder"], r["code"]))


def _check_rows(company, mode, rows, balancing):
    known = {c.code: c for c in current_components(company)}
    errors = []
    codes = [r.get("code") for r in rows]
    if len(codes) != len(set(codes)):
        errors.append("A component appears twice.")
    if "BASIC" not in codes:
        errors.append("A template has a basic row.")
    for r in rows:
        c = known.get(r.get("code"))
        if c is None:
            errors.append(f"Unknown component {r.get('code')!r}.")
            continue
        if c.kind != "EARNING":
            errors.append(f"{c.name} is a {c.kind.lower().replace('_', ' ')}: a structure splits earnings.")
        if not c.is_active:
            errors.append(f"{c.name} is inactive.")
        basis = r.get("basis")
        if basis not in ("PCT_OF_GROSS", "PCT_OF_BASIC", "FIXED"):
            errors.append(f"{c.name}: basis is % of gross, % of basic or a fixed amount.")
            continue
        try:
            v = Decimal(str(r.get("value")))
        except Exception:  # noqa: BLE001
            errors.append(f"{c.name}: a number, please.")
            continue
        if v < 0 or (basis != "FIXED" and not ZERO < v <= HUNDRED):
            errors.append(f"{c.name}: a percentage is above 0 and at most 100.")
        if c.code == "BASIC" and basis == "PCT_OF_BASIC":
            errors.append("Basic cannot be a percentage of itself.")
        if mode == "BASIC_UP" and basis == "PCT_OF_GROSS":
            errors.append(f"{c.name}: a basic-up template has no gross to take a percentage of; use % of basic or "
                          "a fixed amount.")
        if mode == "BASIC_UP" and c.code == "BASIC" and basis != "FIXED":
            errors.append("A basic-up template states basic as a fixed amount (the grade floor raises it).")
    if mode == "GROSS_DOWN":
        if balancing not in ("BASIC", "OTHER") and balancing not in codes:
            errors.append("The balancing line is basic, Other allowance, or one of the rows.")
        basic = next((r for r in rows if r.get("code") == "BASIC"), None)
        if basic and basic.get("basis") == "PCT_OF_GROSS":
            b = Decimal(str(basic["value"]))
            total = sum(Decimal(str(r["value"])) * (b / HUNDRED if r["basis"] == "PCT_OF_BASIC" else 1)
                        for r in rows if r["basis"] != "FIXED")
            # 0.01 of slack: 66.67% is a rounded two-thirds, and with house rent at half of it the split
            # reads 100.005%. The engine's balancing line absorbs the taka either way.
            if total > Decimal("100.01"):
                errors.append(f"The rows allocate {total:.2f}% of gross: more than all of it.")
    if errors:
        raise LibraryRefused({"rows": errors}, status=400)


def _elected_balancing(company):
    """A new template's balancing line starts from the company's balancing
    election (payroll settings §7.7); a template may still name its own."""
    from paysetio.services.resolve import election

    return election(company, "balancing_component").value or "BASIC"


def save_template(company, data, *, template=None, user=None):
    """A draft is edited in place; a published version is never changed --
    the edit becomes the next draft (§1 rule 4)."""
    from ..choices import TemplateModeChoices

    ensure_library(company)
    if template is not None and template.gazette:
        raise LibraryRefused({"template": ["The RMG template follows the gazette in the rule book; it is not edited "
                                           "here."]}, status=409)
    mode = data.get("mode", template.mode if template else "GROSS_DOWN")
    if mode not in TemplateModeChoices.values:
        raise LibraryRefused({"mode": ["A template is gross-down or basic-up."]}, status=400)
    rows = data.get("rows", [{"code": r.component_code, "basis": r.basis, "value": r.value}
                             for r in template.rows.all()] if template else [])
    balancing = data.get("balancingCode", template.balancing_code if template else _elected_balancing(company))
    _check_rows(company, mode, rows, balancing)
    name = str(data.get("name", template.name if template else "") or "").strip()
    note = str(data.get("note", template.note if template else "") or "").strip()
    if not name or not note:
        raise LibraryRefused({"note": ["A template needs a name and a note stating what choosing it does."]},
                             status=400)
    with transaction.atomic():
        if template is None:
            code = str(data.get("code") or "").strip().lower().replace(" ", "-")
            if not code or StructureTemplate.objects.filter(company=company, code=code).exists():
                raise LibraryRefused({"code": [f"Give a new code{f'; {code} is taken' if code else ''}."]},
                                     status=409 if code else 400)
            t = StructureTemplate(company=company, code=code, version=1, effective_from=clock.today(),
                                  created_by=_who(user), created_by_name=_name(user))
        elif template.status == "DRAFT":
            t = template
        else:
            draft = StructureTemplate.objects.filter(company=company, code=template.code, status="DRAFT").first()
            if draft is None:
                top = StructureTemplate.objects.filter(company=company, code=template.code).order_by("-version").first()
                draft = StructureTemplate(company=company, code=template.code, version=top.version + 1,
                                          effective_from=max(clock.today(), template.effective_from),
                                          display_order=template.display_order, created_by=_who(user),
                                          created_by_name=_name(user))
            t = draft
        t.name, t.note, t.mode = name, note, mode
        t.name_bn = str(data.get("nameBn", t.name_bn) or "").strip()
        t.balancing_code = balancing if mode == "GROSS_DOWN" else "BASIC"
        t.grade_scope = data.get("gradeScope", t.grade_scope) or None
        t.site_scope = data.get("siteScope", t.site_scope) or None
        if data.get("effectiveFrom"):
            t.effective_from = date.fromisoformat(str(data["effectiveFrom"]))
        t.status = "DRAFT"
        t.save()
        t.rows.all().delete()
        for i, r in enumerate(sorted(rows, key=lambda r: r["code"] != "BASIC")):
            StructureTemplateRow.objects.create(template=t, component_code=r["code"], basis=r["basis"],
                                                value=Decimal(str(r["value"])), display_order=i)
        audit(company, "TEMPLATE_SAVED", user, entity_type="template", code=t.code, version=t.version,
              after={"mode": mode, "rows": [dict(r, value=str(r["value"])) for r in rows]})
    return t


def publish_template(company, t, *, user=None):
    """§6.2: every row's component exists, is active and has a GL account.
    The version it replaces is superseded from the new one's date."""
    if t.status != "DRAFT":
        raise LibraryRefused({"template": [f"Version {t.version} is {t.status.lower()}; publish a draft."]},
                             status=409)
    rows = list(t.rows.all())
    _check_rows(company, t.mode, [{"code": r.component_code, "basis": r.basis, "value": r.value} for r in rows],
                t.balancing_code)
    comps = {c.code: c for c in current_components(company)}
    unmapped = [comps[r.component_code].name for r in rows if comps[r.component_code].gl_account_id is None]
    if unmapped:
        raise LibraryRefused({"template": [f"{', '.join(unmapped)} has no GL account: a template that pays it would "
                                           "block the payroll journal. Map it first."]})
    with transaction.atomic():
        previous = (StructureTemplate.objects.filter(company=company, code=t.code, status="PUBLISHED",
                                                     superseded_by__isnull=True).exclude(pk=t.pk).first())
        if previous is not None and t.effective_from <= previous.effective_from:
            raise LibraryRefused({"effectiveFrom": [f"Version {t.version} starts after the version it replaces "
                                                    f"({previous.effective_from})."]})
        t.status, t.published_at, t.published_by_name = "PUBLISHED", timezone.now(), _name(user)
        t.save()
        if previous is not None:
            previous.superseded_by = t
            previous.save(update_fields=["superseded_by", "updated_at"])
            audit(company, "TEMPLATE_SUPERSEDED", user, entity_type="template", code=t.code, version=previous.version,
                  after={"by": t.version, "from": t.effective_from.isoformat()})
        audit(company, "TEMPLATE_PUBLISHED", user, entity_type="template", code=t.code, version=t.version)
        event(company, "TemplatePublished", code=t.code, version=t.version, effectiveFrom=t.effective_from.isoformat())
    return t


def archive_template(company, t, *, user=None):
    if t.gazette:
        raise LibraryRefused({"template": ["The gazette template is not archived."]}, status=409)
    used = template_usage(company).get(t.code, 0)
    if used:
        raise LibraryRefused({"template": [f"{used} live structures use {t.name}. Move them first."]}, status=409)
    StructureTemplate.objects.filter(company=company, code=t.code, status="PUBLISHED").update(status="ARCHIVED")
    audit(company, "TEMPLATE_ARCHIVED", user, entity_type="template", code=t.code, version=t.version)
    return t


def preview_template(company, t, amount, *, grade="", on=None):
    """What the template gives for `amount` -- the live preview (§9)."""
    from employeeio.services.salary import build, floor_book
    from employeeio.services.salary_templates import Split, build_basic_up, build_split

    on = on or clock.today()
    if t.gazette:
        built = build("rmg", to_decimal(amount) if amount else None, floor_book(on), grade, company, on)
        lines = built.components
    else:
        split = Split.of(t)
        lines = build_basic_up(split, amount) if t.mode == "BASIC_UP" else build_split(split, amount)
    gross = sum((a for _, a in lines), ZERO)
    basic = sum((a for c, a in lines if c == "BASIC"), ZERO)
    policy = ensure_policy(company)
    share = (basic * HUNDRED / gross).quantize(Decimal("0.1")) if gross else ZERO
    return {"lines": [{"code": c, "amount": money_str(a)} for c, a in lines], "gross": money_str(gross),
            "basic": money_str(basic), "basicShare": f"{share:f}",
            "basicShareWarning": (f"Basic is {share}% of gross, below {policy.basic_share_warn_pct.normalize()}%. Not "
                                  "illegal, but it suppresses the provident fund, gratuity and overtime bases at once.")
            if gross and share < policy.basic_share_warn_pct else None,
            "bases": bases_for(company, lines, on)}


# ===================================================================== bases


def constants(company, on):
    """§4.2: every statutory constant from the rule book as at `on`; the PF
    rates from the PF scheme, the overtime divisor from the overtime election."""
    from rulebookio.book import rule_book

    book = rule_book(on)
    L = book.labour

    def rule(key, default):
        try:
            r = L.get(key)
            return to_decimal(r.value), {"key": key, "citation": r.citation, "confidence": r.confidence}
        except Exception:  # noqa: BLE001 -- a missing rule falls back, and says so
            return Decimal(default), {"key": key, "citation": None, "confidence": "FALLBACK"}

    from paysetio.services.ops import scheme_config
    from paysetio.services.resolve import election

    pf = scheme_config(company, "PF", on)
    ot = election(company, "overtime_base", on)
    ot_div, ot_div_src = rule("standardMonthHours", 208)
    if ot.answered and ot.hours:
        ot_div, ot_div_src = Decimal(ot.hours), {"key": "overtime_base.standardMonthHours",
                                                  "citation": ot.row.statutory_citation, "confidence": "POLICY"}
    ot_mult, ot_mult_src = rule("overtimeMultiplier", 2)
    fest, fest_src = rule("festivalBonusesPerYear", 2)
    grat, grat_src = rule("gratuityDaysStandard", 30)
    return {"otDivisor": ot_div, "otMultiplier": ot_mult, "festivalCount": fest, "gratuityDays": grat,
            "pfRateEmployee": to_decimal(pf["employeeRatePct"]) / HUNDRED,
            "pfRateEmployer": to_decimal(pf["employerRatePct"]) / HUNDRED,
            "sources": {"otDivisor": ot_div_src, "otMultiplier": ot_mult_src, "festivalCount": fest_src,
                        "gratuityDays": grat_src, "pfRate": {"key": "PF scheme", "citation": "Payroll settings — PF scheme",
                                                              "confidence": "POLICY"}}}


def bases_for(company, lines, on, *, flags_by_code=None):
    """§4.1: eight independent sums over the same lines, then §4.2's derived
    figures. `flags_by_code` overrides a code's flags (the effects panel's
    "what if")."""
    k = constants(company, on)
    sums = {f: ZERO for f in BASE_FIELDS}
    for code, amount in lines:
        c = version_on(company, code, on)
        fl = (flags_by_code or {}).get(code) or ({f: getattr(c, f) for f in BASE_FIELDS} if c else {})
        for f in BASE_FIELDS:
            if fl.get(f):
                sums[f] += to_decimal(amount)
    ot = sums["in_ot_base_s108"]
    return {
        "sums": {key: money_str(sums[f]) for f, key, _, _ in BASES},
        "overtimeHourly": money_str(round_to_paisa(ot / k["otDivisor"] * k["otMultiplier"]) if k["otDivisor"] else ZERO),
        "pfEmployee": money_str(round_to_paisa(sums["in_pf_base"] * k["pfRateEmployee"])),
        "pfEmployer": money_str(round_to_paisa(sums["in_pf_base"] * k["pfRateEmployer"])),
        "gratuityMonthly": money_str(round_to_paisa(sums["in_gratuity_base"] / 30 * k["gratuityDays"] / 12)),
        "festivalMonthly": money_str(round_to_paisa(sums["in_festival_base"] * k["festivalCount"] / 12)),
        "constants": {"otDivisor": str(k["otDivisor"]), "otMultiplier": str(k["otMultiplier"]),
                      "festivalCount": str(k["festivalCount"]), "gratuityDays": str(k["gratuityDays"]),
                      "pfRateEmployee": f"{k['pfRateEmployee'].normalize():f}",
                      "pfRateEmployer": f"{k['pfRateEmployer'].normalize():f}"},
        "sources": k["sources"],
    }


def effects(company, gross=Decimal("50000"), template_code="officer", on=None):
    """The flag-effects panel (§8): what the flags do on a ৳50,000 gross,
    and what each figure would be with basic alone -- the alternative."""
    from employeeio.services.salary_templates import Split, build_split, template_on

    on = on or clock.today()
    t = template_on(company, template_code, on)
    lines = build_split(Split.of(t), gross) if t and not t.gazette and t.mode == "GROSS_DOWN" else [("BASIC", gross)]
    now = bases_for(company, lines, on)
    basic_only = {code: {f: code == "BASIC" and f != "in_perquisite_ceiling" for f in BASE_FIELDS} for code, _ in lines}
    alone = bases_for(company, lines, on, flags_by_code=basic_only)
    return {"gross": money_str(gross), "template": template_code, "lines": [{"code": c, "amount": money_str(a)}
                                                                            for c, a in lines],
            "now": now, "basicOnly": alone}


# ===================================================================== floors


def floors(company, on=None):
    """The gazette's grade floors against the company floor, and who is below
    either today (§3.6)."""
    from employeeio.models import Employee, EmployeeSalaryStructure
    from employeeio.services.salary import floor_book, grade_label

    on = on or clock.today()
    book = floor_book(on)
    rule = book.labour.get("gradeWageFloors")
    total = book.labour.get("gradeTotalWageFloors")
    policy = ensure_policy(company)
    company_floor = policy.company_floor_basic
    structures = {s.employee_id: s for s in EmployeeSalaryStructure.objects.filter(employee__company=company)
                  .in_force_on(on).prefetch_related("components")}
    employees = list(Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT"))
                     .select_related("designation", "department"))
    in_use = defaultdict(int)
    breaches = []
    for e in employees:
        s = structures.get(e.pk)
        if e.grade:
            in_use[e.grade] += 1
        if s is None:
            continue
        basic = sum((c.amount for c in s.components.all() if c.code == "BASIC"), ZERO)
        gazette = to_decimal(rule.value[e.grade]) if e.grade and e.grade in rule.value else None
        need = max([x for x in (gazette, company_floor) if x is not None], default=None)
        if need is not None and basic < need:
            breaches.append({"code": e.code, "nameEn": e.name_en, "grade": e.grade or None,
                             "gradeLabel": grade_label(e.grade), "basic": money_str(basic),
                             "floor": money_str(need), "short": money_str(need - basic),
                             "which": "gazette" if gazette is not None and need == gazette else "company",
                             "template": s.template})
    grades = [{"grade": g, "label": grade_label(g), "floorBasic": money_str(to_decimal(v)),
               "floorTotal": money_str(to_decimal(total.value[g])) if g in total.value else None,
               "employees": in_use.get(g, 0),
               "companyFloorBinds": company_floor is not None and company_floor > to_decimal(v)}
              for g, v in sorted(rule.value.items())]
    return {"grades": grades, "companyFloor": money_str(company_floor) if company_floor is not None else None,
            "citation": rule.citation, "confidence": rule.confidence, "effective": rule.effective_from.isoformat()
            if getattr(rule, "effective_from", None) else None, "breaches": breaches,
            "pfRateEmployee": _pf_fraction(company, "employeeRatePct"),
            "pfRateEmployer": _pf_fraction(company, "employerRatePct"),
            "basicShareWarnPct": f"{policy.basic_share_warn_pct.normalize():f}"}


def _pf_fraction(company, key):
    """The PF scheme's rate as a fraction, '0.08' -- the shape the floors tab reads."""
    from paysetio.services.ops import scheme_config

    return f"{(to_decimal(scheme_config(company, 'PF')[key]) / HUNDRED).normalize():f}"


def set_policy(company, data, *, user=None):
    """The company floor may exceed the gazette, never fall below it for a
    grade in use: below every grade it would bind nobody (§3.6, interpreted:
    the lowest floor among grades in use)."""
    from employeeio.models import Employee
    from employeeio.services.salary import floor_book

    p = ensure_policy(company)
    if "pfRateEmployee" in data or "pfRateEmployer" in data:
        raise LibraryRefused({"pfRateEmployee": [
            "The provident-fund rates are set on the PF scheme in Payroll settings, where a change is "
            "effective-dated and does not restate past contributions."]}, status=410)
    before = {"companyFloor": str(p.company_floor_basic) if p.company_floor_basic is not None else None}
    if "companyFloor" in data:
        v = data["companyFloor"]
        if v in (None, ""):
            p.company_floor_basic = None
        else:
            v = to_decimal(v)
            rule = floor_book(clock.today()).labour.get("gradeWageFloors").value
            used = set(Employee.objects.filter(company=company).exclude(grade="").values_list("grade", flat=True))
            lowest = min((to_decimal(rule[g]) for g in used if g in rule), default=None)
            if lowest is not None and v < lowest:
                raise LibraryRefused({"companyFloor": [
                    f"৳{v:,.0f} is below the gazette's lowest floor for a grade in use (৳{lowest:,.0f}). A company "
                    "floor may only add to the gazette."]})
            p.company_floor_basic = v
    for attr, key in (("basic_share_warn_pct", "basicShareWarnPct"),):
        if key in data:
            setattr(p, attr, to_decimal(data[key]))
    try:
        p.save()
    except IntegrityError:
        raise LibraryRefused({"basicShareWarnPct": ["Not a valid percentage."]}, status=400) from None
    audit(company, "POLICY_CHANGED", user, entity_type="policy", code="payroll", before=before,
          after={"companyFloor": str(p.company_floor_basic) if p.company_floor_basic is not None else None})
    return p


# ============================================================== bulk revision


def _cohort(company, scope):
    from employeeio.models import Employee

    qs = Employee.objects.filter(company=company).exclude(status__in=("REMOVED", "DRAFT")).select_related(
        "department", "site")
    if scope.get("grades"):
        qs = qs.filter(grade__in=scope["grades"])
    if scope.get("departments"):
        qs = qs.filter(department__uid__in=scope["departments"])
    if scope.get("sites"):
        qs = qs.filter(site__uid__in=scope["sites"])
    if scope.get("employeeCodes"):
        qs = qs.filter(code__in=scope["employeeCodes"])
    return list(qs.order_by("code"))


def bulk_out(b, *, detail=False):
    out = {"uid": str(b.uid), "reference": b.reference, "scope": b.scope_json, "method": b.method,
           "value": f"{b.value.normalize():f}" if b.value is not None else None,
           "targetTemplate": b.target_template.code if b.target_template_id else None, "rounding": b.rounding,
           "effectiveFrom": b.effective_from.isoformat(), "includeOverridden": b.include_overridden,
           "reason": b.reason or None, "status": b.status, "affected": b.affected_count, "refused": b.refused_count,
           "previewedAt": b.previewed_at.isoformat() if b.previewed_at else None,
           "appliedAt": b.applied_at.isoformat() if b.applied_at else None, "appliedBy": b.applied_by_name or None,
           "reversedAt": b.reversed_at.isoformat() if b.reversed_at else None, "reverseReason": b.reverse_reason or None,
           "createdBy": b.created_by_name or None, "createdAt": b.created_at.isoformat()}
    if detail:
        out["preview"] = b.preview_json
    return out


def create_bulk(company, data, *, user=None):
    from ..choices import BulkMethodChoices, RoundingChoices

    method = data.get("method")
    if method not in BulkMethodChoices.values:
        raise LibraryRefused({"method": ["Choose how the revision changes pay."]}, status=400)
    target = None
    if method == "CHANGE_TEMPLATE":
        target = StructureTemplate.objects.filter(company=company, code=data.get("targetTemplate"),
                                                  status="PUBLISHED", superseded_by__isnull=True).first()
        if target is None:
            raise LibraryRefused({"targetTemplate": ["Choose a published template to move to."]}, status=400)
    value = data.get("value")
    if method != "CHANGE_TEMPLATE" and value in (None, ""):
        raise LibraryRefused({"value": ["Give the figure."]}, status=400)
    rounding = data.get("rounding") or "NEAREST_100"
    if rounding not in RoundingChoices.values:
        raise LibraryRefused({"rounding": ["Unknown rounding."]}, status=400)
    try:
        effective = date.fromisoformat(str(data.get("effectiveFrom")))
    except (TypeError, ValueError):
        raise LibraryRefused({"effectiveFrom": ["Give the date it takes effect."]}, status=400) from None
    scope = {k: data.get("scope", {}).get(k) or [] for k in ("grades", "departments", "sites", "employeeCodes")}
    last = BulkRevision.objects.filter(company=company).order_by("-created_at").values_list("reference", flat=True).first()
    n = int(last.split("-")[1]) + 1 if last else 1
    return BulkRevision.objects.create(
        company=company, reference=f"BR-{n:04d}", scope_json=scope, method=method,
        value=to_decimal(value) if value not in (None, "") else None, target_template=target, rounding=rounding,
        effective_from=effective, include_overridden=bool(data.get("includeOverridden")),
        reason=str(data.get("reason") or "").strip(), created_by=_who(user), created_by_name=_name(user))


SALARY_METHOD = {"PCT_INCREASE": "PERCENTAGE_INCREASE", "FIXED_INCREASE": "FIXED_INCREASE", "NEW_GROSS": "NEW_GROSS",
                 "CHANGE_TEMPLATE": "CHANGE_TEMPLATE"}


def _one(employee, b, *, preview, user=None):
    """One employee through the salary module's own revision -- the same
    checks and floors as a revision made by hand."""
    from employeeio.services import salary

    current = salary.latest_structure(employee)
    if current is None:
        return {"refused": "No salary structure to revise."}
    if not b.include_overridden and current.overrides.exists():
        return {"refused": "Structure overridden — excluded (an override is a decision that this person is an "
                           "exception)."}
    method = SALARY_METHOD[b.method]
    value = b.value
    template = b.target_template.code if b.target_template_id else None
    if salary.is_basic_up(employee.company, current.template, b.effective_from) and method == "NEW_GROSS":
        return {"refused": "On a basic-up template: a new gross does not apply. Revise it by percentage."}
    try:
        out = salary.revise(employee, method=method, value=value, effective_from=b.effective_from,
                            reason=b.reason or f"Bulk revision {b.reference}", template=template,
                            rounding=ROUNDING_STEP[b.rounding], user=user, preview=preview,
                            revision_type="INCREMENT" if method in ("PERCENTAGE_INCREASE", "FIXED_INCREASE")
                            else None)
    except salary.SalaryRefused as exc:
        return {"refused": " ".join(m for ms in exc.errors.values() for m in ms)}
    floor = ensure_policy(employee.company).company_floor_basic
    if floor is not None and to_decimal(out["basic"]) < floor:
        return {"refused": f"Proposed basic ৳{to_decimal(out['basic']):,.0f} is below the company floor of "
                           f"৳{floor:,.0f}."}
    return {"outcome": out, "current": current}


def preview_bulk(company, b, *, user=None):
    """§6.3: per employee -- current gross, proposed gross, delta, rounding,
    and refusals with reasons. Stored: apply refuses without it."""
    if b.status not in ("DRAFT", "PREVIEWED"):
        raise LibraryRefused({"bulk": [f"{b.reference} is {b.status.lower()}."]}, status=409)
    rows, refusals = [], []
    for e in _cohort(company, b.scope_json):
        r = _one(e, b, preview=True)
        if "refused" in r:
            refusals.append({"code": e.code, "nameEn": e.name_en, "reason": r["refused"]})
            continue
        cur, o = r["current"], r["outcome"]
        new_gross = to_decimal(o["gross"])
        rows.append({"code": e.code, "nameEn": e.name_en, "grade": e.grade or None, "template": cur.template,
                     "newTemplate": o.get("template"), "currentGross": money_str(cur.gross),
                     "proposedGross": money_str(new_gross), "delta": money_str(new_gross - cur.gross),
                     "basic": o.get("basic"), "warnings": [w.get("message") for w in o.get("warnings", [])]})
    b.preview_json = {"rows": rows, "refusals": refusals, "at": timezone.now().isoformat(),
                      "total": money_str(sum((to_decimal(r["delta"]) for r in rows), ZERO))}
    b.affected_count, b.refused_count = len(rows), len(refusals)
    b.status, b.previewed_at, b.previewed_by_name = "PREVIEWED", timezone.now(), _name(user)
    b.save()
    audit(company, "BULK_PREVIEWED", user, entity_type="bulk", code=b.reference,
          after={"affected": len(rows), "refused": len(refusals)})
    return b


def apply_bulk(company, b, *, user=None):
    """Apply what the preview showed -- and only to those it showed."""
    if b.status != "PREVIEWED" or not b.preview_json:
        raise LibraryRefused({"bulk": ["Preview it first: a bulk revision is applied only as previewed."]},
                             status=409)
    codes = {r["code"] for r in b.preview_json["rows"]}
    made, failed = [], []
    from employeeio.models import Employee

    with transaction.atomic():
        for e in Employee.objects.filter(company=company, code__in=codes).order_by("code"):
            r = _one(e, b, preview=False, user=user)
            if "refused" in r:
                failed.append({"code": e.code, "reason": r["refused"]})
                continue
            made.append((r["outcome"].get("structure") or {}).get("uid"))
        if failed:
            raise LibraryRefused({"bulk": [f"{len(failed)} employees changed since the preview. Preview again."]},
                                 status=409, detail={"failed": failed})
        b.applied_structures = [m for m in made if m]
        b.status, b.applied_at, b.applied_by, b.applied_by_name = "APPLIED", timezone.now(), _who(user), _name(user)
        b.save()
        audit(company, "BULK_APPLIED", user, entity_type="bulk", code=b.reference, after={"structures": len(made)})
        event(company, "BulkRevisionApplied", reference=b.reference, employees=len(made),
              effectiveFrom=b.effective_from.isoformat())
    return b


def library_audit(company, limit=60):
    return [{"action": a.action, "label": a.get_action_display(), "entity": a.entity_type, "code": a.entity_code,
             "version": a.entity_version, "by": a.actor_name or None, "at": a.created_at.isoformat(),
             "before": a.before_json, "after": a.after_json, "reason": a.reason or None}
            for a in LibraryAudit.objects.filter(company=company)[:limit]]


__all__ = ["LibraryRefused", "ROUND_HALF_UP"]
