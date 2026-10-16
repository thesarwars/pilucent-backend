"""The print file (§4, §5.5). Resolved sides become HTML positioned in
millimetres, and WeasyPrint lays it out in the pinned fonts -- the same
fonts the text was measured in, so the fit computed in preflight is the fit
that prints.

Output profiles impose the pages: one card a page for a card printer, a
grid on A4 or Letter with crop marks for a guillotine (the backs mirrored
for long-edge duplex), or PNG images for a bureau.
"""

import base64
import hashlib
import html
import io
import zipfile

from .code128 import encode
from .engine import resolve_side, walk_nodes
from .fonts import font_face_css, stack, weight

SHEETS = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}
MARK = 3.0  # crop-mark length, mm


def esc(s):
    return html.escape(str(s or ""))


# ===================================================================== parts


def _qr_svg(payload, ec="M", quiet=4, dark="#141414", light="#FFFFFF"):
    import qrcode

    level = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
             "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}.get(ec or "M")
    qr = qrcode.QRCode(error_correction=level, border=int(quiet if quiet is not None else 4), box_size=1)
    qr.add_data(payload or " ")
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1"/>' for y, row in enumerate(m)
                    for x, on in enumerate(row) if on)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="100%" height="100%" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="{esc(light)}"/>'
            f'<g fill="{esc(dark)}">{rects}</g></svg>')


def _barcode_svg(value, quiet=2, colour="#141414", w_mm=None, h_mm=None):
    """Sized in mm when given: a percentage size lets WeasyPrint keep the
    viewBox's 1-unit height, and the bars collapse to a line."""
    try:
        bars = encode(value)
    except ValueError:
        return ""
    total = sum(m for _, m in bars) + 2 * quiet
    x, rects = quiet, []
    for is_bar, m in bars:
        if is_bar:
            rects.append(f'<rect x="{x}" y="0" width="{m}" height="1"/>')
        x += m
    size = (f'width="{w_mm:.3f}mm" height="{h_mm:.3f}mm"' if w_mm and h_mm else 'width="100%" height="100%"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} 1" {size} '
            f'preserveAspectRatio="none" shape-rendering="crispEdges"><g fill="{esc(colour)}">{"".join(rects)}</g></svg>')


def _text_css(style, size=None):
    fam = style.get("fontFamily")
    return (f"font-family:{stack(fam)};font-weight:{weight(fam, style.get('fontWeight'))};"
            f"font-size:{size or style.get('fontSize') or 8}pt;line-height:{style.get('lineHeight') or 1.2};"
            f"letter-spacing:{style.get('letterSpacing') or 0}pt;color:{esc(style.get('color') or '#141414')};"
            f"text-align:{style.get('align') or 'left'};"
            + ("font-style:italic;" if style.get("italic") else "")
            + ("text-decoration:underline;" if style.get("underline") else ""))


def _box(f, extra=""):
    rot = f"transform:rotate({f['rotation']}deg);" if f.get("rotation") else ""
    return (f"position:absolute;left:{f['x']:.3f}mm;top:{f['y']:.3f}mm;width:{f['w']:.3f}mm;"
            f"height:{f['h']:.3f}mm;{rot}{extra}")


def node_html(n, asset_src):
    el, f, t = n["el"], n["frame"], n["type"]
    op = f"opacity:{n.get('opacity', 1)};" if n.get("opacity", 1) != 1 else ""
    if t == "shape":
        fill = (el.get("fill") or {}).get("color") or "transparent"
        radius = "50%" if el.get("shape") == "ellipse" else f"{float(el.get('cornerRadius') or 0):.3f}mm"
        stroke = el.get("stroke") or {}
        border = f"border:{float(stroke['width']):.3f}mm solid {esc(stroke.get('color'))};" if stroke.get("width") else ""
        return f'<div style="{_box(f, f"background:{esc(fill)};border-radius:{radius};box-sizing:border-box;{border}{op}")}"></div>'
    if t == "text":
        fit, style = n["fit"], n["style"]
        va = {"middle": "center", "bottom": "flex-end"}.get(style.get("verticalAlign"), "flex-start")
        lines = "<br>".join(esc(x) for x in fit["lines"])
        return (f'<div style="{_box(f, f"display:flex;flex-direction:column;justify-content:{va};overflow:hidden;{op}")}">'
                f'<div style="{_text_css(style, fit["fontSize"])}white-space:pre;">{lines}</div></div>')
    if t == "photo":
        shape = el.get("shape") or {}
        radius = "50%" if shape.get("kind") == "ellipse" else f"{float(shape.get('radius') or 0):.3f}mm"
        border = el.get("border") or {}
        bd = f"border:{float(border['width']):.3f}mm solid {esc(border.get('color'))};" if border.get("width") else ""
        inner = ""
        if n.get("photo"):
            src = asset_src(n["photo"])
            if src:
                fit = "contain" if el.get("fit") == "contain" else "cover"
                inner = f'<img src="{src}" style="width:100%;height:100%;object-fit:{fit};display:block">'
        if not inner:
            inner = (f'<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;'
                     f'background:#ECECEC;color:#8F8F8F;font-family:{stack("IBM Plex Sans")};font-weight:600;'
                     f'font-size:{max(6, f["w"] * 0.9):.1f}pt">{esc(n.get("initials") or "")}</div>')
        return (f'<div style="{_box(f, f"overflow:hidden;border-radius:{radius};box-sizing:border-box;{bd}{op}")}">'
                f'{inner}</div>')
    if t == "qr":
        svg = _qr_svg(n.get("payload"), el.get("errorCorrection"), el.get("quietZoneModules"),
                      el.get("moduleColor") or "#141414", el.get("backgroundColor") or "#FFFFFF")
        return f'<div style="{_box(f, op)}">{svg}</div>'
    if t == "barcode":
        human = el.get("showHumanReadable")
        bar_h = f["h"] * (0.72 if human else 1)
        svg = _barcode_svg(n.get("value") or "", int(el.get("quietZone") or 2), el.get("barColor") or "#141414",
                           f["w"], bar_h)
        text = (f'<div style="font-family:{stack("IBM Plex Mono")};font-size:{min(7, f["h"] * 0.6):.1f}pt;'
                f'text-align:center;line-height:1;margin-top:0.4mm">{esc(n.get("value"))}</div>') if human else ""
        return f'<div style="{_box(f, op)}"><div style="height:{bar_h:.3f}mm">{svg}</div>{text}</div>'
    if t in ("image", "signature"):
        src = asset_src(n["src"]) if n.get("src") else None
        if not src:
            return ""
        return f'<div style="{_box(f, op)}"><img src="{src}" style="width:100%;height:100%;object-fit:contain"></div>'
    if t == "kvTable":
        ls, vs = n["labelStyle"], n["valueStyle"]
        lw = float(el.get("labelWidth") or 10)
        gap = float(el.get("rowGap") or 0)
        rows = "".join(
            f'<div style="display:flex;margin-bottom:{gap:.3f}mm">'
            f'<div style="width:{lw:.3f}mm;flex:none;{_text_css(ls)}white-space:nowrap;overflow:hidden">'
            f'{esc((r["label"] or "").upper() if ls.get("textTransform") == "upper" else r["label"])}</div>'
            f'<div style="flex:1;{_text_css(vs)}white-space:nowrap;overflow:hidden">{esc(r["value"])}</div></div>'
            for r in n["rows"])
        return f'<div style="{_box(f, f"overflow:hidden;{op}")}">{rows}</div>'
    return ""


def side_html(resolved, ab, asset_src, *, include_bleed, mirror=False):
    """One side as a positioned block. With the bleed, the block is the
    trim plus the bleed on every edge, and the card sits inset by it."""
    b = ab["bleed"] if include_bleed else 0.0
    w, h = ab["width"] + 2 * b, ab["height"] + 2 * b
    bg = resolved["background"] or {}
    if bg.get("type") == "image" and bg.get("assetId"):
        src = asset_src({"assetId": bg["assetId"]})
        reach = ab["bleed"] if bg.get("extendToBleed") else 0
        bg_html = (f'<img src="{src}" style="position:absolute;left:{b - reach:.3f}mm;top:{b - reach:.3f}mm;'
                   f'width:{ab["width"] + 2 * reach:.3f}mm;height:{ab["height"] + 2 * reach:.3f}mm;object-fit:cover">'
                   if src else "")
        fill = "#FFFFFF"
    else:
        bg_html, fill = "", esc(bg.get("color") or "#FFFFFF")
    nodes = "".join(node_html(n, asset_src) for n in walk_nodes(resolved["nodes"]))
    flip = "transform:scaleX(-1);" if mirror else ""
    return (f'<div style="position:relative;width:{w:.3f}mm;height:{h:.3f}mm;overflow:hidden;background:{fill};{flip}">'
            f'{bg_html}<div style="position:absolute;left:{b:.3f}mm;top:{b:.3f}mm;width:{ab["width"]:.3f}mm;'
            f'height:{ab["height"]:.3f}mm">{nodes}</div></div>'), w, h


# =================================================================== assets


def asset_loader(open_asset):
    """`open_asset(asset_id) -> (bytes, crop, adjustments) | None`, wrapped
    to produce cropped, adjusted data URIs, each once."""
    cache = {}

    def src(ref):
        aid = ref.get("assetId") if isinstance(ref, dict) else ref
        if not aid:
            return None
        if aid not in cache:
            loaded = open_asset(aid)
            cache[aid] = _data_uri(*loaded) if loaded else None
        return cache[aid]

    return src


def _data_uri(raw, crop=None, adjustments=None):
    data, mime = processed_image(raw, crop, adjustments)
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def processed_image(raw, crop=None, adjustments=None):
    """The photo as it prints: cropped and adjusted; the original is kept."""
    from PIL import Image, ImageEnhance

    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
    if crop:
        x, y, w, h = (int(crop.get(k, 0)) for k in ("x", "y", "w", "h"))
        if w > 0 and h > 0:
            img = img.crop((x, y, x + w, y + h))
    adj = adjustments or {}
    for key, enhancer in (("brightness", ImageEnhance.Brightness), ("contrast", ImageEnhance.Contrast),
                          ("saturation", ImageEnhance.Color)):
        v = float(adj.get(key) or 0)
        if v:
            img = enhancer(img.convert("RGB")).enhance(1 + v / 100)
    out = io.BytesIO()
    img.save(out, format="PNG" if img.mode == "RGBA" else "JPEG", quality=92)
    return out.getvalue(), "image/png" if img.mode == "RGBA" else "image/jpeg"


# ================================================================== documents


def _pdf(pages_html, page_w, page_h):
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    fc = FontConfiguration()
    body = "".join(f'<div class="page">{p}</div>' for p in pages_html)
    css = (font_face_css() + f"@page{{size:{page_w:.3f}mm {page_h:.3f}mm;margin:0}}"
           "html,body{margin:0;padding:0}"
           # In mm, not 100%: the body's height is auto, and a sheet's cards are
           # absolutely positioned -- a percentage page collapses and clips them.
           f".page{{position:relative;width:{page_w:.3f}mm;height:{page_h:.3f}mm;"
           "page-break-after:always;break-after:page;overflow:hidden}")
    return HTML(string=f"<html><body>{body}</body></html>").write_pdf(stylesheets=[CSS(string=css, font_config=fc)],
                                                                      font_config=fc)


def _crop_marks(x, y, w, h):
    """Corner marks just outside the trim, for the guillotine."""
    marks, g = [], 1.0
    for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
        dx = -1 if cx == x else 1
        dy = -1 if cy == y else 1
        hx = cx + (g if dx > 0 else -g - MARK)
        vy = cy + (g if dy > 0 else -g - MARK)
        marks.append(f'<div style="position:absolute;left:{hx:.3f}mm;top:{cy - 0.05:.3f}mm;width:{MARK}mm;'
                     f'height:0.1mm;background:#000"></div>')
        marks.append(f'<div style="position:absolute;left:{cx - 0.05:.3f}mm;top:{vy:.3f}mm;width:0.1mm;'
                     f'height:{MARK}mm;background:#000"></div>')
    return "".join(marks)


def render_cards(cards, profile, asset_src):
    """`cards`: [{"front": resolved, "back": resolved|None, "artboard": ab}].
    Returns (bytes, content_type, extension, pages)."""
    include_bleed = profile["include_bleed"]
    duplex = profile["duplex"] != "NONE"
    mirror = profile.get("mirror", False)
    sheet = profile["sheet"]
    if sheet in ("CARD_DIRECT", "PNG"):
        pages = []
        sizes = None
        for c in cards:
            front, w, h = side_html(c["front"], c["artboard"], asset_src, include_bleed=include_bleed, mirror=mirror)
            pages.append(front)
            sizes = sizes or (w, h)
            if c.get("back") and duplex:
                back, _, _ = side_html(c["back"], c["artboard"], asset_src, include_bleed=include_bleed,
                                       mirror=mirror)
                pages.append(back)
        pdf = _pdf(pages, *sizes)
        if sheet == "PNG":
            return _pngs(pdf, cards, profile["dpi"], duplex), "application/zip", "zip", len(pages)
        return pdf, "application/pdf", "pdf", len(pages)

    page_w, page_h = SHEETS[sheet]
    cols, rows = profile["cols"], profile["rows"]
    margin, gutter = profile["margin_mm"], profile["gutter_mm"]
    pages = []
    per = cols * rows
    for start in range(0, len(cards), per):
        chunk = cards[start:start + per]
        for side in ("front", "back") if duplex and any(c.get("back") for c in chunk) else ("front",):
            cells = []
            for i, c in enumerate(chunk):
                ab = c["artboard"]
                b = ab["bleed"] if include_bleed else 0
                cw, ch = ab["width"] + 2 * b, ab["height"] + 2 * b
                col, row = i % cols, i // cols
                if side == "back":  # long-edge duplex: the back of column 1 is behind column n
                    col = cols - 1 - col
                x, y = margin + col * (cw + gutter), margin + row * (ch + gutter)
                resolved = c["front"] if side == "front" else c.get("back")
                if resolved is None:
                    continue
                block, _, _ = side_html(resolved, ab, asset_src, include_bleed=include_bleed, mirror=mirror)
                cells.append(f'<div style="position:absolute;left:{x:.3f}mm;top:{y:.3f}mm">{block}</div>')
                if profile.get("crop_marks"):
                    cells.append(_crop_marks(x + b, y + b, ab["width"], ab["height"]))
            pages.append("".join(cells))
    return _pdf(pages, page_w, page_h), "application/pdf", "pdf", len(pages)


def _pngs(pdf, cards, dpi, duplex):
    import fitz

    doc = fitz.open(stream=pdf, filetype="pdf")
    out = io.BytesIO()
    names = []
    for c in cards:
        names.append(f"{c.get('code') or 'card'}-front.png")
        if c.get("back") and duplex:
            names.append(f"{c.get('code') or 'card'}-back.png")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for page, name in zip(doc, names):
            z.writestr(name, page.get_pixmap(dpi=dpi).tobytes("png"))
    return out.getvalue()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def preview_png(resolved_front, ab, asset_src, dpi=200):
    """One side as a PNG: what the server will print, for comparison."""
    import fitz

    block, w, h = side_html(resolved_front, ab, asset_src, include_bleed=False)
    doc = fitz.open(stream=_pdf([block], w, h), filetype="pdf")
    return doc[0].get_pixmap(dpi=dpi).tobytes("png")


__all__ = ["asset_loader", "preview_png", "render_cards", "resolve_side", "sha256"]
