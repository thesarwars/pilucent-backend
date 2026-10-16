"""What a company starts with: two templates from the design's fixtures
(a CR80 portrait card with a back, and a landscape contractor card), the
output profiles, and two optional custom fields. Seeded on first use."""

from django.db import IntegrityError, transaction

INK, MUTED, BRAND, BRAND_2 = "#141414", "#5C5C5C", "#1B4D3E", "#C8A24A"


def style(**o):
    return {"fontFamily": "IBM Plex Sans", "fontSize": 8, "fontWeight": 400, "italic": False, "color": INK,
            "letterSpacing": 0, "lineHeight": 1.2, "align": "left", "verticalAlign": "top", "textTransform": "none",
            "underline": False, "numerals": "latin", **o}


def frame(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h, "rotation": 0}


def el(id_, name, type_, f, **extra):
    return {"id": id_, "name": name, "type": type_, "frame": f, "opacity": 1, "hidden": False, "locked": False, **extra}


def binding(path, *formatters):
    return {"kind": "binding", "path": path, "formatters": list(formatters)}


def literal(value):
    return {"kind": "literal", "value": value}


BN = "Noto Sans Bengali"
MONO = "IBM Plex Mono"


def standard_front():
    return {"kind": "front", "background": {"type": "solid", "color": "#FFFFFF"}, "elements": [
        el("el-band", "Header band", "shape", frame(-2, -2, 58, 17), shape="rect", fill={"kind": "solid", "color": BRAND}),
        el("el-rule", "Brand rule", "shape", frame(-2, 15, 58, 0.9), shape="rect", fill={"kind": "solid", "color": BRAND_2}),
        el("el-logo", "Company mark", "shape", frame(4, 3.6, 8, 8), shape="ellipse", fill={"kind": "solid", "color": BRAND_2}),
        el("el-coy", "Company name", "text", frame(14.5, 4.4, 35, 4.4), content=binding("company.name"),
           style=style(fontSize=8.5, fontWeight=600, color="#FFFFFF", letterSpacing=-0.05),
           overflow={"mode": "shrink", "minFontSize": 6.5}, emptyBehaviour="placeholder", placeholder="Company"),
        el("el-coy-bn", "Company name (Bangla)", "text", frame(14.5, 8.9, 35, 4), content=binding("company.nameBn"),
           style=style(fontFamily=BN, fontSize=7, color="rgba(255,255,255,0.82)"),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
        el("el-photo", "Photo", "photo", frame(15, 20, 24, 30), path="employee.photo",
           shape={"kind": "rect", "radius": 1.5}, fit="cover", fallback="initials", minDpi=300,
           border={"width": 0.4, "color": "#DCDCDC"}),
        el("el-name", "Employee name", "text", frame(4, 52, 46, 6), content=binding("employee.fullName"),
           style=style(fontSize=11, fontWeight=600, align="center", letterSpacing=-0.1),
           overflow={"mode": "shrink", "minFontSize": 7.5}, emptyBehaviour="placeholder", placeholder="—"),
        el("el-name-bn", "Employee name (Bangla)", "text", frame(4, 57.6, 46, 4.4),
           content=binding("employee.fullNameBn"), style=style(fontFamily=BN, fontSize=7.5, align="center", color=MUTED),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
        el("el-desig", "Designation", "text", frame(4, 62, 46, 4), content=binding("employee.job.designation"),
           style=style(fontSize=7.5, fontWeight=500, align="center", textTransform="upper", letterSpacing=0.3,
                       color=BRAND), overflow={"mode": "shrink", "minFontSize": 5.5}, emptyBehaviour="hide"),
        el("el-kv", "Details", "kvTable", frame(5, 66.5, 30, 11), rows=[
            {"label": literal("ID"), "value": binding("employee.employeeCode")},
            {"label": literal("Dept"), "value": binding("employee.department.name")},
            {"label": literal("Blood"), "value": binding("employee.bloodGroup")}],
           labelStyle=style(fontSize=5.8, color="#8F8F8F", textTransform="upper", letterSpacing=0.2),
           valueStyle=style(fontSize=6.6, fontWeight=500), labelWidth=8, rowGap=0.7, collapseEmptyRows=True),
        el("el-qr", "Verification QR", "qr", frame(38, 66.5, 11, 11), payload={"kind": "url"}, errorCorrection="M",
           quietZoneModules=1, moduleColor=INK, backgroundColor="#FFFFFF"),
        el("el-cardno", "Card number", "text", frame(4, 78.4, 46, 3), content=binding("card.number"),
           style=style(fontFamily=MONO, fontSize=6, align="center", color="#8F8F8F"),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
    ]}


def standard_back():
    return {"kind": "back", "background": {"type": "solid", "color": "#FAFAFA"}, "elements": [
        el("bk-band", "Footer band", "shape", frame(-2, 74, 58, 13.6), shape="rect", fill={"kind": "solid", "color": BRAND}),
        el("bk-title", "Section title", "text", frame(6, 7, 42, 4), content=literal("If found, please return to"),
           style=style(fontSize=6.4, fontWeight=600, textTransform="upper", letterSpacing=0.4, color="#8F8F8F"),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
        el("bk-addr", "Company address", "text", frame(6, 11.5, 42, 12), content=binding("company.address"),
           style=style(fontSize=6.6, lineHeight=1.35, color=MUTED),
           overflow={"mode": "wrap", "maxLines": 4, "minFontSize": 5.5}, emptyBehaviour="hide"),
        el("bk-emg-t", "Emergency title", "text", frame(6, 26, 42, 4), content=literal("Emergency contact"),
           style=style(fontSize=6.4, fontWeight=600, textTransform="upper", letterSpacing=0.4, color="#8F8F8F"),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
        el("bk-emg", "Emergency details", "kvTable", frame(6, 30.5, 42, 8), rows=[
            {"label": literal("Name"), "value": binding("employee.emergencyName")},
            {"label": literal("Phone"), "value": binding("employee.emergencyPhone")}],
           labelStyle=style(fontSize=5.8, color="#8F8F8F", textTransform="upper", letterSpacing=0.2),
           valueStyle=style(fontSize=6.6, fontWeight=500), labelWidth=11, rowGap=0.7, collapseEmptyRows=True),
        el("bk-barcode", "Code 128", "barcode", frame(9, 42, 36, 10), symbology="code128",
           value=binding("employee.employeeCode"), showHumanReadable=True, quietZone=2, barColor=INK),
        el("bk-valid", "Validity", "kvTable", frame(6, 55, 42, 8), rows=[
            {"label": literal("Issued"), "value": binding("card.issueDate", {"fn": "date", "arg": "dd MMM yyyy"})},
            {"label": literal("Expires"), "value": binding("card.expiryDate", {"fn": "date", "arg": "dd MMM yyyy"})}],
           labelStyle=style(fontSize=5.8, color="#8F8F8F", textTransform="upper", letterSpacing=0.2),
           valueStyle=style(fontFamily=MONO, fontSize=6.6, fontWeight=500), labelWidth=11, rowGap=0.7),
        el("bk-sigline", "Signature rule", "shape", frame(28, 68, 20, 0.3), shape="rect",
           fill={"kind": "solid", "color": "#C4C4C4"}),
        el("bk-sig", "Signatory title", "text", frame(28, 68.8, 20, 3.4), content=binding("company.signatoryTitle"),
           style=style(fontSize=5.8, align="center", color="#8F8F8F"), overflow={"mode": "truncate", "ellipsis": "…"},
           emptyBehaviour="hide"),
        el("bk-web", "Website", "text", frame(4, 78.5, 46, 4), content=binding("company.website"),
           style=style(fontFamily=MONO, fontSize=6, align="center", color="rgba(255,255,255,0.86)"),
           overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
    ]}


def contractor_front():
    return {"kind": "front", "background": {"type": "solid", "color": "#FFFFFF"}, "elements": [
        el("c-band", "Side band", "shape", frame(-2, -2, 16, 58), shape="rect", fill={"kind": "solid", "color": "#7A4A0F"}),
        el("c-tag", "Contractor tag", "text", frame(3.5, 22, 7, 10), content=literal("C"),
           style=style(fontSize=22, fontWeight=700, color="#FFFFFF", align="center"),
           overflow={"mode": "shrink", "minFontSize": 12}),
        el("c-photo", "Photo", "photo", frame(17, 6, 20, 25), path="employee.photo",
           shape={"kind": "rect", "radius": 1.2}, fit="cover", fallback="initials", minDpi=300),
        el("c-name", "Employee name", "text", frame(40, 6, 41, 6), content=binding("employee.fullName"),
           style=style(fontSize=10, fontWeight=600), overflow={"mode": "shrink", "minFontSize": 7},
           emptyBehaviour="placeholder", placeholder="—"),
        el("c-desig", "Designation", "text", frame(40, 12.5, 41, 4), content=binding("employee.job.designation"),
           style=style(fontSize=7, color=MUTED), overflow={"mode": "truncate", "ellipsis": "…"}, emptyBehaviour="hide"),
        el("c-kv", "Details", "kvTable", frame(40, 18, 41, 13), rows=[
            {"label": literal("ID"), "value": binding("employee.employeeCode")},
            {"label": literal("Site"), "value": binding("employee.location.name")},
            {"label": literal("Valid to"), "value": binding("card.expiryDate", {"fn": "date", "arg": "dd MMM yyyy"})}],
           labelStyle=style(fontSize=5.8, color="#8F8F8F", textTransform="upper"),
           valueStyle=style(fontSize=6.6, fontWeight=500), labelWidth=11, rowGap=0.6, collapseEmptyRows=True),
        el("c-qr", "Verification QR", "qr", frame(17, 35, 14, 14), payload={"kind": "url"}, errorCorrection="M",
           quietZoneModules=1),
        el("c-coy", "Company name", "text", frame(40, 40, 41, 5), content=binding("company.name"),
           style=style(fontSize=7.5, fontWeight=600), overflow={"mode": "shrink", "minFontSize": 6}),
        el("c-cardno", "Card number", "text", frame(40, 45.5, 41, 3.5), content=binding("card.number"),
           style=style(fontFamily=MONO, fontSize=6, color="#8F8F8F"), overflow={"mode": "truncate", "ellipsis": "…"},
           emptyBehaviour="hide"),
    ]}


TEMPLATES = [
    dict(code="standard", name="Standard card", name_bn="সাধারণ কার্ড", description="Permanent employees, all sites",
         preset="BADGE_PORTRAIT", width_mm=54, height_mm=85.6, is_default=True, front=standard_front,
         back=standard_back),
    dict(code="contractor", name="Contractor card", name_bn="ঠিকাদার কার্ড", description="Fixed-term and vendor staff",
         preset="CR80", width_mm=85.6, height_mm=54, is_default=False, front=contractor_front, back=None),
]

PROFILES = [
    dict(name="Card printer, duplex", note="One card per pass, both sides", sheet="CARD_DIRECT", duplex="LONG_EDGE",
         is_default=True),
    dict(name="A4 sheet, 9-up", note="Short runs, cut on a guillotine", sheet="A4", cols=3, rows=3, gutter_mm=4,
         margin_mm=10, include_bleed=True, crop_marks=True, duplex="LONG_EDGE", colour_profile="Coated FOGRA39"),
    dict(name="PNG at 300 DPI", note="Handover to an external bureau", sheet="PNG", duplex="LONG_EDGE"),
]

FIELDS = [
    dict(key="vehicleNo", label="Vehicle number", label_bn="যানবাহন নম্বর", kind="TEXT", position=1),
    dict(key="accessZones", label="Access zones", label_bn="প্রবেশ এলাকা", kind="MULTI", position=2,
         enum_options=["Server room", "Warehouse", "Executive floor", "Plant floor"]),
]


def ensure_setup(company):
    """Seeds what is missing; never overwrites what a company has changed."""
    from django.utils import timezone

    from ..models import CardField, CardSettings, CardTemplate, OutputProfile

    CardSettings.objects.get_or_create(company=company)
    if not CardTemplate.objects.filter(company=company).exists():
        for t in TEMPLATES:
            try:
                with transaction.atomic():
                    CardTemplate.objects.create(
                        company=company, code=t["code"], name=t["name"], name_bn=t["name_bn"],
                        description=t["description"], preset=t["preset"], width_mm=t["width_mm"],
                        height_mm=t["height_mm"], front_json=t["front"](), back_json=t["back"]() if t["back"] else None,
                        status="PUBLISHED", published_at=timezone.now(), published_by_name="seeded",
                        is_default=t["is_default"], created_by_name="seeded")
            except IntegrityError:
                pass
    if not OutputProfile.objects.filter(company=company).exists():
        OutputProfile.objects.bulk_create([OutputProfile(company=company, **p) for p in PROFILES])
    if not CardField.objects.filter(company=company).exists():
        CardField.objects.bulk_create([CardField(company=company, **f) for f in FIELDS])
