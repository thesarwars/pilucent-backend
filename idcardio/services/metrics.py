"""Text measured with real font metrics (§4.2): laid out by WeasyPrint --
Pango and HarfBuzz underneath -- in the pinned fonts, so Bengali conjuncts
and matras are shaped, not counted.

A width scales linearly with the font size, so each (text, family, weight)
is measured once, at 100pt, and cached. Strings are measured in batches:
one layout pass for a whole card or a whole job.
"""

import html
import threading

from .engine import ApproxMeasurer, pt_to_mm
from .fonts import family, font_face_css, stack, weight

_cache = {}
_lock = threading.Lock()
REF_PT = 100.0


def _layout(items):
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    fc = FontConfiguration()
    body = "".join(
        f'<div><span id="m{i}" style="font-family:{stack(fam)};font-weight:{w};font-size:{REF_PT}pt;'
        f'white-space:pre">{html.escape(text)}</span></div>' for i, (text, fam, w) in enumerate(items))
    doc = HTML(string=f"<html><body>{body}</body></html>").render(
        stylesheets=[CSS(string=font_face_css() + "@page{size:20000mm 20000mm;margin:0}", font_config=fc)],
        font_config=fc)
    widths = {}

    def walk(box):
        el = getattr(box, "element", None)
        if el is not None and getattr(box, "element_tag", None) == "span" and el.get("id"):
            widths[el.get("id")] = widths.get(el.get("id"), 0) + box.width
            return
        for child in getattr(box, "children", None) or []:
            walk(child)

    for page in doc.pages:
        walk(page._page_box)
    # CSS px at REF_PT -> mm per point.
    return {items[int(k[1:])]: v * 25.4 / 96 / REF_PT for k, v in widths.items()}


def prime(keys):
    """Measure every (text, family, weight) not yet cached, in one pass."""
    todo = []
    for text, fam, w in keys:
        key = (text, family(fam), weight(fam, w))
        if key not in _cache and key not in todo and text:
            todo.append(key)
    for i in range(0, len(todo), 400):
        measured = _layout(todo[i:i + 400])
        with _lock:
            _cache.update(measured)
            for k in todo[i:i + 400]:
                _cache.setdefault(k, 0.0)


class FontMeasurer(ApproxMeasurer):
    """Real metrics. A string the batch did not include is measured on its
    own -- slower, never wrong."""

    exact = True

    def width_per_pt(self, text, fam, w):
        if not text:
            return 0.0
        key = (text, family(fam), weight(fam, w))
        if key not in _cache:
            prime([key])
        return _cache[key]

    def measure(self, text, size_pt, letter_spacing_pt, fam, w):
        return self.width_per_pt(text, fam, w) * size_pt + pt_to_mm(letter_spacing_pt or 0) * len(text)
