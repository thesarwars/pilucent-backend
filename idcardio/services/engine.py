"""The card engine (backend spec §2, §4): units, bindings, conditions, text
fitting, `resolve_side` and `preflight`. Pure -- no I/O; text is measured
through a `measurer`, so the same code runs on the client's approximation
(for layout warnings) and on real font metrics (for print).

Millimetres and points throughout. Pixels appear only in `effective_dpi`.

A port of the design's `idcard-core.js`, which the client runs too: one
resolved tree drives the thumbnail, the canvas, the preview and the print
file, so they cannot disagree.
"""

import re
from datetime import date, datetime

MM_PER_INCH = 25.4
CSS_PX_PER_MM = 96 / MM_PER_INCH


def pt_to_mm(pt):
    return pt * MM_PER_INCH / 72


def mm_to_pt(mm):
    return mm * 72 / MM_PER_INCH


def effective_dpi(pixel_w, placed_w_mm):
    return round(pixel_w / (placed_w_mm / MM_PER_INCH)) if placed_w_mm else 0


def px_at(mm, dpi):
    """Pixels across `mm` at `dpi` (C1: CR80 at 300 dpi is 1011 x 638)."""
    return round(mm / MM_PER_INCH * dpi)


# ================================================================ bindings

BN_DIGITS = "০১২৩৪৫৬৭৮৯"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def to_bengali_numerals(s):
    return re.sub(r"[0-9]", lambda m: BN_DIGITS[int(m.group())], str(s))


def to_latin_numerals(s):
    return re.sub(f"[{BN_DIGITS}]", lambda m: str(BN_DIGITS.index(m.group())), str(s))


def get_path(ctx, path):
    cur = ctx
    for part in str(path or "").split("."):
        if not part:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def format_date(value, pattern):
    if isinstance(value, (date, datetime)):
        d = value
    else:
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return "" if value is None else str(value)
    out = str(pattern or "dd MMM yyyy")
    for token, rep in (("yyyy", f"{d.year}"), ("MMM", MONTHS[d.month - 1]), ("MM", f"{d.month:02d}"),
                       ("dd", f"{d.day:02d}")):
        out = out.replace(token, rep)
    return out


def title_case(s):
    return re.sub(r"(^|\s|[-'])([a-zঀ-৿])", lambda m: m.group(1) + m.group(2).upper(), str(s).lower())


def apply_formatter(value, f):
    s = "" if value is None else str(value)
    fn, arg = f.get("fn"), f.get("arg")
    if fn == "upper":
        return s.upper()
    if fn == "lower":
        return s.lower()
    if fn == "title":
        return title_case(s)
    if fn == "trim":
        return s.strip()
    if fn == "initials":
        return "".join(w[0] for w in s.split() if w).upper()
    if fn == "default":
        return str(arg) if s == "" else s
    if fn == "truncate":
        n = int(arg or 0)
        return s[:n] + "…" if n and len(s) > n else s
    if fn == "date":
        return format_date(value, arg) if s else ""
    if fn == "pad":
        return s.rjust(int(arg or 0), "0")
    if fn == "mask":
        return ("•" * max(0, len(s) - 4)) + s[-4:]
    if fn == "numerals":
        return to_bengali_numerals(s) if arg == "bengali" else to_latin_numerals(s)
    return s


FORMATTERS = ("upper", "lower", "title", "trim", "initials", "default", "truncate", "date", "pad", "mask", "numerals")


def parse_expression(expr):
    """`path | fmt | fmt(arg)` -> (path, [formatters]); None when malformed."""
    parts = [p.strip() for p in str(expr or "").split("|")]
    if not parts or not re.match(r"^[A-Za-z_][\w.]*$", parts[0]):
        return None
    fmts = []
    for p in parts[1:]:
        m = re.match(r"^(\w+)(?:\(([^)]*)\))?$", p)
        if not m or m.group(1) not in FORMATTERS:
            return None
        arg = m.group(2)
        fmts.append({"fn": m.group(1), "arg": arg.strip("'\"") if arg is not None else None})
    return parts[0], fmts


def resolve_value(src, ctx):
    """The text, and how it was arrived at: the inspector explains
    fallbacks and preflight counts them."""
    if not src:
        return {"text": "", "missing": False, "usedFallback": False}
    kind = src.get("kind")
    if kind == "literal":
        return {"text": str(src.get("value") or ""), "missing": False, "usedFallback": False}
    if kind == "expression":
        parsed = parse_expression(src.get("expr"))
        if parsed is None:
            return {"text": "", "missing": True, "usedFallback": False, "invalid": True}
        src = {"kind": "binding", "path": parsed[0], "formatters": parsed[1]}
        kind = "binding"
    if kind == "binding":
        raw = get_path(ctx, src.get("path"))
        missing = raw is None or raw == "" or raw == []
        text = "" if missing else (", ".join(map(str, raw)) if isinstance(raw, list) else str(raw))
        used_fallback = False
        for f in src.get("formatters") or []:
            if f.get("fn") == "default" and text == "":
                used_fallback = True
            # A date formats the raw value; everything else the text so far.
            text = (format_date(raw, f.get("arg")) if not missing else "") if f.get("fn") == "date" \
                else apply_formatter(text, f)
        return {"text": text, "missing": missing, "usedFallback": used_fallback, "raw": raw}
    return {"text": "", "missing": False, "usedFallback": False}


# ============================================================== conditions


def eval_condition(cond, ctx):
    if not cond:
        return True
    op = cond.get("op")
    if op == "and":
        return all(eval_condition(c, ctx) for c in cond.get("children") or [])
    if op == "or":
        return any(eval_condition(c, ctx) for c in cond.get("children") or [])
    if op == "not":
        return not eval_condition(cond.get("child"), ctx)
    v, t = get_path(ctx, cond.get("path")), cond.get("value")
    sv = "" if v is None else (", ".join(map(str, v)) if isinstance(v, list) else str(v)).lower()
    st = "" if t is None else str(t).lower()
    items = [str(x).lower() for x in v] if isinstance(v, list) else None
    if op == "eq":
        return sv == st
    if op == "neq":
        return sv != st
    if op == "contains":
        return st in sv
    if op == "startsWith":
        return sv.startswith(st)
    if op in ("isEmpty", "empty"):
        return sv == ""
    if op in ("isNotEmpty", "notEmpty"):
        return sv != ""
    if op == "isTrue":
        return v is True or sv == "true"
    if op == "isFalse":
        return v is False or sv == "false"
    if op == "includes":
        return st in items if items is not None else st in sv
    if op == "excludes":
        return st not in items if items is not None else st not in sv
    if op in ("gt", "lt"):
        try:
            a, b = float(v), float(t)
        except (TypeError, ValueError):
            a, b = sv, st
        return a > b if op == "gt" else a < b
    if op == "in":
        return sv in [str(x).lower() for x in (t or [])]
    if op == "notIn":
        return sv not in [str(x).lower() for x in (t or [])]
    return True


VERBS = {"eq": "is", "neq": "is not", "contains": "contains", "startsWith": "starts with", "isEmpty": "is empty",
         "isNotEmpty": "is not empty", "gt": "is more than", "lt": "is less than", "in": "is one of",
         "includes": "includes", "excludes": "does not include", "isTrue": "is true", "isFalse": "is false"}


def describe_condition(cond):
    if not cond:
        return ""
    if cond.get("op") in ("and", "or"):
        return f" {cond['op']} ".join(describe_condition(c) for c in cond.get("children") or [])
    val = cond.get("value")
    val = ", ".join(map(str, val)) if isinstance(val, list) else val
    return f"{cond.get('path')} {VERBS.get(cond.get('op'), cond.get('op'))}" + ("" if val in (None, "") else f" {val}")


# ============================================================ measurement

NARROW = "ijltfIr.,:;'\"|!()[]{} "
WIDE = "mwMW@%"


def _advance(ch):
    if "ঀ" <= ch <= "৿":
        return 0.58
    if ch in NARROW:
        return 0.30
    if ch in WIDE:
        return 0.86
    if "A" <= ch <= "Z":
        return 0.63
    if "0" <= ch <= "9":
        return 0.55
    return 0.52


class ApproxMeasurer:
    """The design's per-character model. Adequate for layout warnings,
    inadequate for print -- Bengali conjuncts and matras make glyphs and
    characters differ (§4.2)."""

    exact = False

    def width_per_pt(self, text, family, weight):
        bold = 1.035 if (weight or 400) >= 600 else 1
        return sum(_advance(c) for c in text) * pt_to_mm(1) * bold

    def measure(self, text, size_pt, letter_spacing_pt, family, weight):
        return self.width_per_pt(text, family, weight) * size_pt + pt_to_mm(letter_spacing_pt or 0) * len(text)


class RecordingMeasurer(ApproxMeasurer):
    """Answers with the approximation and remembers every string asked
    about, so the real measurer can measure them all in one layout pass."""

    def __init__(self):
        self.asked = set()

    def width_per_pt(self, text, family, weight):
        self.asked.add((text, family or "IBM Plex Sans", int(weight or 400)))
        return super().width_per_pt(text, family, weight)


def wrap_lines(text, max_w, size, style, measurer, max_lines=None):
    words, lines, cur = [w for w in str(text).split() if w], [], ""
    for w in words:
        trial = f"{cur} {w}" if cur else w
        if not cur or measurer.measure(trial, size, style.get("letterSpacing"), style.get("fontFamily"),
                                       style.get("fontWeight")) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
        if max_lines and len(lines) >= max_lines:
            break
    if cur and (not max_lines or len(lines) < max_lines):
        lines.append(cur)
    return lines


def fit_text(text, frame, style, overflow, measurer):
    """Returns the size actually used, so preflight can say 'shrank from
    11pt to 8.4pt' rather than silently producing an unreadable card."""
    size = float(style.get("fontSize") or 10)
    floor = float((overflow or {}).get("minFontSize") or size)
    mode = (overflow or {}).get("mode") or "overflow"
    ls, fam, wt = style.get("letterSpacing"), style.get("fontFamily"), style.get("fontWeight")
    width = lambda t, s: measurer.measure(t, s, ls, fam, wt)  # noqa: E731
    lines, shrunk, clipped = [text], False, False
    line_h = lambda s: pt_to_mm(s) * float(style.get("lineHeight") or 1.2)  # noqa: E731
    if mode == "wrap":
        max_lines = int((overflow or {}).get("maxLines") or 2)
        lines = wrap_lines(text, frame["w"], size, style, measurer, max_lines)
        while len(lines) * line_h(size) > frame["h"] and size > floor:
            size, shrunk = max(floor, size - 0.2), True
            lines = wrap_lines(text, frame["w"], size, style, measurer, max_lines)
        clipped = len(wrap_lines(text, frame["w"], size, style, measurer)) > max_lines \
            or len(lines) * line_h(size) > frame["h"] + 0.05
    elif mode in ("shrink", "condense"):
        while width(text, size) > frame["w"] and size > floor:
            size, shrunk = max(floor, round(size - 0.2, 4)), True
        clipped = width(text, size) > frame["w"] + 0.01
    elif mode == "truncate":
        ell, t = (overflow or {}).get("ellipsis") or "…", text
        while len(t) > 1 and width(t + ell, size) > frame["w"]:
            t, clipped = t[:-1], True
        lines = [t + ell if clipped else text]
        clipped = False  # truncation is the remedy, not a failure
    else:
        clipped = width(text, size) > frame["w"] + 0.01
    return {"lines": lines, "fontSize": round(size, 2), "shrunk": shrunk, "shrunkFrom": style.get("fontSize"),
            "clipped": clipped, "widthMm": round(max((width(x, size) for x in lines), default=0), 3)}


# ============================================================ resolve_side


def _frame(el, offset=0):
    f = el.get("frame") or {}
    return {"x": float(f.get("x", 0)), "y": float(f.get("y", 0)) + offset, "w": float(f.get("w", 0)),
            "h": float(f.get("h", 0)), "rotation": float(f.get("rotation") or 0)}


def resolve_side(side, ctx, measurer=None):
    """One resolved tree for every renderer. `ctx` is the render context
    ({employee, company, card, custom}); `measurer` measures text."""
    measurer = measurer or ApproxMeasurer()
    notes = []

    def walk(elements, flow):
        out, offset = [], 0.0
        for el in elements or []:
            if el.get("hidden"):
                continue
            name = el.get("name") or el.get("id")
            if el.get("visibleWhen") and not eval_condition(el["visibleWhen"], ctx):
                notes.append({"elementId": el.get("id"), "name": name, "kind": "hidden-by-condition",
                              "detail": describe_condition(el["visibleWhen"])})
                if flow:
                    offset -= _frame(el)["h"] + float(el.get("flowGap") or 0)
                continue
            frame = _frame(el, offset)
            node = {"id": el.get("id"), "name": name, "type": el.get("type"), "frame": frame,
                    "opacity": el.get("opacity", 1), "el": el}
            t = el.get("type")
            if t == "text":
                rv = resolve_value(el.get("content"), ctx)
                if rv["text"] == "" and el.get("emptyBehaviour") == "hide":
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "hidden-empty",
                                  "detail": "Field is empty"})
                    if flow:
                        offset -= frame["h"] + float(el.get("flowGap") or 0)
                    continue
                style = dict(el.get("style") or {})
                text = rv["text"] if rv["text"] != "" else (el.get("placeholder") or "—")
                tt = style.get("textTransform")
                text = text.upper() if tt == "upper" else text.lower() if tt == "lower" else \
                    title_case(text) if tt == "title" else text
                if style.get("numerals") == "bengali":
                    text = to_bengali_numerals(text)
                fit = fit_text(text, frame, style, el.get("overflow"), measurer)
                content = el.get("content") or {}
                node.update(text=text, fit=fit, style=style, usedFallback=rv.get("usedFallback") or rv.get("missing"),
                            binding=content.get("path") if content.get("kind") == "binding" else None,
                            formatters=content.get("formatters") or [])
                if fit["shrunk"]:
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "shrunk",
                                  "detail": f"Shrunk from {fit['shrunkFrom']}pt to {fit['fontSize']:.1f}pt to fit"})
                if fit["clipped"]:
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "overflow",
                                  "detail": "Text does not fit its box"})
            elif t == "photo":
                photo = get_path(ctx, el.get("path") or "employee.photo")
                node.update(photo=photo or None, binding=el.get("path") or "employee.photo")
                if not photo:
                    if el.get("fallback") == "hide":
                        continue
                    node["fallbackKind"] = el.get("fallback") or "initials"
                    node["initials"] = apply_formatter(get_path(ctx, "employee.fullName") or "", {"fn": "initials"})
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "fallback",
                                  "detail": f"No photo — showing {node['fallbackKind']}"})
                elif photo.get("width"):
                    node["dpi"] = effective_dpi(photo["width"], frame["w"])
            elif t == "qr":
                payload = el.get("payload") or {"kind": "url"}
                card = ctx.get("card") or {}
                if payload.get("kind") == "signed":
                    node["payload"] = card.get("token") or ""
                elif payload.get("kind") == "url":
                    node["payload"] = card.get("verifyUrl") or ""
                else:
                    node["payload"] = resolve_value(payload.get("source"), ctx)["text"]
                node["binding"] = "card.verifyUrl"
            elif t == "barcode":
                bv = resolve_value(el.get("value"), ctx)
                node.update(value=bv["text"], binding=(el.get("value") or {}).get("path"))
            elif t in ("image", "signature"):
                src = el.get("source") or {}
                node["src"] = get_path(ctx, src.get("path")) if src.get("kind") == "binding" else src.get("assetId")
                node["binding"] = src.get("path") if src.get("kind") == "binding" else None
                if not node["src"]:
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "hidden-empty",
                                  "detail": "No image"})
                    continue
            elif t == "kvTable":
                rows = []
                for r in el.get("rows") or []:
                    if r.get("visibleWhen") and not eval_condition(r["visibleWhen"], ctx):
                        continue
                    label, value = resolve_value(r.get("label"), ctx)["text"], resolve_value(r.get("value"), ctx)["text"]
                    if el.get("collapseEmptyRows") and value == "":
                        continue
                    rows.append({"label": label, "value": value,
                                 "valueBinding": (r.get("value") or {}).get("path")
                                 if (r.get("value") or {}).get("kind") == "binding" else None})
                ls, vs = el.get("labelStyle") or {}, el.get("valueStyle") or {}
                # Rows are laid out by the renderer, so the fit is computed here or the
                # overflow check has a hole and a clipped row ships silently.
                row_h = pt_to_mm(max(float(vs.get("fontSize") or 7), float(ls.get("fontSize") or 6))) \
                    * float(vs.get("lineHeight") or 1.2)
                need = len(rows) * row_h + max(0, len(rows) - 1) * float(el.get("rowGap") or 0)
                node.update(rows=rows, kvNeededMm=round(need, 3), kvOverflow=need > frame["h"] + 0.05,
                            labelStyle=ls, valueStyle=vs)
                if node["kvOverflow"]:
                    notes.append({"elementId": el.get("id"), "name": name, "kind": "overflow",
                                  "detail": f"{len(rows)} rows need {need:.1f}mm but the box is {frame['h']:.1f}mm"})
            elif t == "group":
                node["children"] = walk(el.get("children") or [], bool(el.get("flow")))
            out.append(node)
        return out

    return {"nodes": walk(side.get("elements") or [], False), "notes": notes,
            "background": side.get("background") or {"type": "solid", "color": "#FFFFFF"}}


def walk_nodes(nodes):
    for n in nodes:
        if n.get("children"):
            yield from walk_nodes(n["children"])
        else:
            yield n


def bindings_of(side):
    """Every path a side reads -- what an issue snapshots."""
    out = set()

    def visit(src):
        if not src:
            return
        if src.get("kind") == "binding":
            out.add(src["path"])
        elif src.get("kind") == "expression":
            parsed = parse_expression(src.get("expr"))
            if parsed:
                out.add(parsed[0])

    def walk(elements):
        for el in elements or []:
            visit(el.get("content"))
            visit(el.get("value"))
            if el.get("type") == "photo":
                out.add(el.get("path") or "employee.photo")
            if el.get("type") in ("image", "signature"):
                visit(el.get("source"))
            for r in el.get("rows") or []:
                visit(r.get("label"))
                visit(r.get("value"))
                if r.get("visibleWhen", {}).get("path"):
                    out.add(r["visibleWhen"]["path"])
            if (el.get("visibleWhen") or {}).get("path"):
                out.add(el["visibleWhen"]["path"])
            walk(el.get("children"))

    walk(side.get("elements"))
    return out


# =============================================================== preflight


def artboard(t):
    return {"width": float(t["width_mm"]), "height": float(t["height_mm"]), "bleed": float(t["bleed_mm"]),
            "safe": float(t["safe_area_mm"]), "radius": float(t["corner_radius_mm"])}


def preflight_side(kind, side, ab, ctx, measurer, field_stats=None):
    """§4.3. Every finding names its measurement."""
    findings = []
    res = resolve_side(side, ctx, measurer)
    bg = res["background"]

    def add(severity, element, message, fix=None, element_id=None):
        findings.append({"severity": severity, "side": kind, "element": element, "elementId": element_id,
                         "message": message, "fix": fix})

    if bg.get("type") == "image" and not bg.get("extendToBleed"):
        add("error", "Background", "The background does not reach the bleed: trimming may leave a white edge.",
            "extendToBleed")
    if kind == "back" and not (side.get("elements") or []):
        add("warning", "Back side", "The back side has no content.")
    safe_l, safe_t, safe_r, safe_b = ab["safe"], ab["safe"], ab["width"] - ab["safe"], ab["height"] - ab["safe"]
    for n in walk_nodes(res["nodes"]):
        f, name, eid = n["frame"], n["name"], n["id"]
        full_bleed_shape = n["type"] == "shape" and (f["x"] <= 0 or f["y"] <= 0 or f["x"] + f["w"] >= ab["width"]
                                                     or f["y"] + f["h"] >= ab["height"])
        if f["x"] + f["w"] < 0 or f["y"] + f["h"] < 0 or f["x"] > ab["width"] or f["y"] > ab["height"]:
            add("error", name, f"‘{name}’ is off the card.", "move-on", eid)
        elif not full_bleed_shape and (f["x"] < safe_l - 0.05 or f["y"] < safe_t - 0.05
                                       or f["x"] + f["w"] > safe_r + 0.05 or f["y"] + f["h"] > safe_b + 0.05):
            out = max(safe_l - f["x"], safe_t - f["y"], f["x"] + f["w"] - safe_r, f["y"] + f["h"] - safe_b)
            add("warning", name, f"‘{name}’ is {out:.1f}mm outside the safe area and may be clipped.", "nudge-in", eid)
        if n["type"] == "photo" and n.get("dpi"):
            if n["dpi"] < 150:
                add("error", name, f"‘{name}’ is {n['dpi']} DPI at {f['w']:.1f}mm: too low to print.", None, eid)
            elif n["dpi"] < 300:
                add("warning", name, f"‘{name}’ is {n['dpi']} DPI at {f['w']:.1f}mm: print quality may be soft.",
                    None, eid)
        if n.get("fit") and n["fit"]["clipped"]:
            add("error", name, f"‘{name}’ does not fit its box: {n['fit']['widthMm']:.1f}mm of text in "
                               f"{f['w']:.1f}mm at {n['fit']['fontSize']}pt.", None, eid)
        if n.get("kvOverflow"):
            add("error", name, f"‘{name}’ needs {n['kvNeededMm']:.1f}mm for its rows but the box is {f['h']:.1f}mm. "
                               "The last row will be cut in half.", "grow-box", eid)
        if n.get("binding") and field_stats and n["binding"] in field_stats and field_stats[n["binding"]] < 50:
            add("warning", name, f"Only {field_stats[n['binding']]}% of employees have ‘{n['binding']}’.", None, eid)
        style = n.get("style") or {}
        if n["type"] == "text" and re.search("[ঀ-৿]", n.get("text") or "") \
                and "Bengali" not in (style.get("fontFamily") or ""):
            add("warning", name, f"‘{style.get('fontFamily') or 'This font'}’ has no Bangla glyphs: the text falls "
                                 "back to Noto Sans Bengali. Choose it so the layout is measured in it.", "font", eid)
    return findings, res


def summarise(findings):
    return {"findings": findings, "errors": sum(1 for f in findings if f["severity"] == "error"),
            "warnings": sum(1 for f in findings if f["severity"] == "warning")}


# ============================================================= validation

TYPES = {"text", "photo", "qr", "barcode", "shape", "image", "kvTable", "group", "signature"}


def validate_side(side, kind):
    """§3.2: the database cannot validate element shape, so the service does
    on write. A malformed element found at print time is a batch of ruined
    cards. Returns a list of problems (empty when valid)."""
    problems = []
    if not isinstance(side, dict):
        return [f"The {kind} side is not an object."]
    elements = side.get("elements")
    if not isinstance(elements, list):
        return [f"The {kind} side needs an elements list."]
    ids = set()

    def check(el, where):
        if not isinstance(el, dict):
            problems.append(f"{where}: an element is not an object.")
            return
        name = el.get("name") or el.get("id") or "an element"
        if el.get("type") not in TYPES:
            problems.append(f"{where} ‘{name}’: unknown type {el.get('type')!r}.")
        if not el.get("id") or el["id"] in ids:
            problems.append(f"{where} ‘{name}’: needs a unique id.")
        ids.add(el.get("id"))
        f = el.get("frame") or {}
        try:
            w, h = float(f["w"]), float(f["h"])
            float(f["x"]), float(f["y"])
            if w <= 0 or h <= 0:
                problems.append(f"{where} ‘{name}’: width and height must be positive millimetres.")
        except (KeyError, TypeError, ValueError):
            problems.append(f"{where} ‘{name}’: frame needs x, y, w and h in millimetres.")
        t = el.get("type")
        if t == "text" and not (el.get("content") or {}).get("kind"):
            problems.append(f"{where} ‘{name}’: a text element needs content (a field, an expression or fixed text).")
        if t == "text" and not isinstance(el.get("style"), dict):
            problems.append(f"{where} ‘{name}’: a text element needs a style.")
        if t == "text" and (el.get("content") or {}).get("kind") == "expression" \
                and parse_expression(el["content"].get("expr")) is None:
            problems.append(f"{where} ‘{name}’: the expression cannot be read.")
        if t == "kvTable" and not isinstance(el.get("rows"), list):
            problems.append(f"{where} ‘{name}’: a key-value block needs rows.")
        if t == "barcode" and el.get("symbology", "code128") != "code128":
            problems.append(f"{where} ‘{name}’: only Code 128 barcodes are supported.")
        for c in el.get("children") or []:
            check(c, where)

    for el in elements:
        check(el, kind.capitalize())
    return problems
