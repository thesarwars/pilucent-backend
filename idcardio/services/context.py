"""The render context (what a binding reads) and the snapshot taken at
issue (§3.4). A card renders from its snapshot, never from live data: an
employee who changes designation does not change the card in their pocket.

The catalogue is the binding picker's list and the validator's: a path not
in it is a typo, and the picker says which field was probably meant.
"""

from collections import defaultdict

from django.conf import settings

CATALOGUE = [
    ("employee", "Employee", [
        ("employee.fullName", "Full name", "text"),
        ("employee.fullNameBn", "Full name (Bangla)", "text"),
        ("employee.employeeCode", "Employee code", "text"),
        ("employee.photo", "Photo", "image"),
        ("employee.bloodGroup", "Blood group", "text"),
        ("employee.mobile", "Mobile", "text"),
        ("employee.email", "Email", "text"),
        ("employee.dateOfJoining", "Date of joining", "date"),
        ("employee.type", "Classification", "enum"),
        ("employee.emergencyName", "Emergency contact name", "text"),
        ("employee.emergencyPhone", "Emergency contact phone", "text"),
    ]),
    ("job", "Job", [
        ("employee.job.designation", "Designation", "text"),
        ("employee.job.grade", "Grade", "text"),
        ("employee.job.employmentType", "Employment type", "enum"),
        ("employee.department.name", "Department", "text"),
        ("employee.section.name", "Section", "text"),
        ("employee.location.name", "Site", "text"),
    ]),
    ("company", "Company", [
        ("company.name", "Company name", "text"),
        ("company.nameBn", "Company name (Bangla)", "text"),
        ("company.address", "Address", "text"),
        ("company.website", "Website", "text"),
        ("company.signatoryTitle", "Signatory title", "text"),
    ]),
    ("card", "Card", [
        ("card.number", "Card number", "text"),
        ("card.issueDate", "Issue date", "date"),
        ("card.expiryDate", "Expiry date", "date"),
        ("card.verifyUrl", "Verification link", "text"),
    ]),
]
CARD_PATHS = {"card.number", "card.issueDate", "card.expiryDate", "card.verifyUrl", "card.token", "card.status"}


def catalogue(company):
    from ..models import CardField

    groups = [{"id": gid, "label": label, "fields": [{"path": p, "label": lab, "type": t} for p, lab, t in fields]}
              for gid, label, fields in CATALOGUE]
    custom = [{"path": f.path, "label": f.label, "labelBn": f.label_bn or None, "type": f.kind.lower(),
               "options": f.enum_options, "pii": f.is_pii, "printable": f.printable}
              for f in CardField.objects.filter(company=company)]
    groups.append({"id": "custom", "label": "Custom fields", "fields": custom})
    return groups


def known_paths(company):
    return {f["path"] for g in catalogue(company) for f in g["fields"]} | CARD_PATHS


def verify_url(token):
    return f"{settings.APP_URL.rstrip('/')}/verify/{token}"


def company_ctx(company):
    from ..models import CardSettings

    s, _ = CardSettings.objects.get_or_create(company=company)
    return {"name": company.name, "nameBn": s.name_bn or None,
            "address": s.address or company.customer_facing_address or None,
            "website": (company.website or "").replace("https://", "").replace("http://", "").rstrip("/") or None,
            "signatoryTitle": s.signatory_title or None}


def photo_ref(asset):
    if asset is None:
        return None
    w, h = asset.placed_size
    return {"assetId": str(asset.uid), "width": w, "height": h}


def employee_ctx(employee, *, photo=None, custom=None):
    blood = dict(employee._meta.get_field("blood").choices).get(employee.blood, "") if employee.blood else ""
    etype = dict(employee._meta.get_field("employment_type").choices).get(employee.employment_type, "") \
        if employee.employment_type else ""
    return {
        "fullName": employee.name_en, "fullNameBn": employee.name_bn or None, "employeeCode": employee.code,
        "photo": photo_ref(photo), "bloodGroup": blood or None, "mobile": employee.mobile or None,
        "email": employee.email or None, "dateOfJoining": employee.doj.isoformat() if employee.doj else None,
        "type": employee.classification or None,
        "emergencyName": employee.emergency_name or None, "emergencyPhone": employee.emergency_phone or None,
        "job": {"designation": employee.designation.title if employee.designation_id else None,
                "grade": employee.grade or None, "employmentType": etype or None},
        "department": {"name": employee.department.title if employee.department_id else None},
        "section": {"name": employee.section.title if employee.section_id else None},
        "location": {"name": employee.site.name if employee.site_id else None},
    }


def card_ctx(card):
    if card is None:
        return {"number": "", "issueDate": "", "expiryDate": "", "token": "", "verifyUrl": "", "status": ""}
    return {"number": card.card_number, "issueDate": card.issued_on.isoformat() if card.issued_on else "",
            "expiryDate": card.expires_on.isoformat() if card.expires_on else "", "token": card.verify_token,
            "verifyUrl": verify_url(card.verify_token), "status": card.status}


def current_photos(employees):
    from ..models import MediaAsset

    return {a.employee_id: a for a in MediaAsset.objects.filter(employee__in=employees, kind="PHOTO",
                                                                 is_current=True, purged_at__isnull=True)}


def custom_values(employees, printable_only=True):
    from ..models import CardFieldValue

    out = defaultdict(dict)
    qs = CardFieldValue.objects.filter(employee__in=employees).select_related("field")
    for v in qs:
        if printable_only and (not v.field.printable or v.field.is_pii):
            continue
        out[v.employee_id][v.field.key] = v.value
    return out


def live_context(company, employee, *, card=None, photos=None, customs=None, company_part=None):
    photos = photos if photos is not None else current_photos([employee])
    customs = customs if customs is not None else custom_values([employee])
    return {"employee": employee_ctx(employee, photo=photos.get(employee.pk), custom=None),
            "company": company_part or company_ctx(company), "card": card_ctx(card),
            "custom": customs.get(employee.pk, {})}


def snapshot(ctx, paths):
    """The bound values at issue, keyed by path."""
    from .engine import get_path

    snap = {}
    for p in sorted(paths):
        if p.startswith("card."):
            continue
        snap[p] = get_path(ctx, p)
    return snap


def from_snapshot(snap, card):
    """A render context rebuilt from a card's snapshot -- the reprint is the
    card that was issued."""
    ctx = {"employee": {}, "company": {}, "custom": {}, "card": card_ctx(card)}
    for path, value in (snap or {}).items():
        cur = ctx
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
    return ctx


def field_stats(company, employees, paths):
    """§7.2: the share of the roster each bound field is populated for."""
    from .engine import get_path

    employees = list(employees)
    if not employees:
        return {}
    photos, customs, comp = current_photos(employees), custom_values(employees), company_ctx(company)
    counts = defaultdict(int)
    for e in employees:
        ctx = live_context(company, e, photos=photos, customs=customs, company_part=comp)
        for p in paths:
            if p in CARD_PATHS:
                counts[p] += 1
                continue
            v = get_path(ctx, p)
            if v not in (None, "", []):
                counts[p] += 1
    return {p: round(100 * counts[p] / len(employees)) for p in paths}
