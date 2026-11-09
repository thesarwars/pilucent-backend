"""§6.5: the PDF of a stored document. It reads only what the document holds,
so it prints the same in five years. Bengali comes from the image's fonts."""

from html import escape

from common.words import format_money, format_month_year, to_bangla_numerals

T = {
    "en": {"slip": "Wage slip", "earn": "Earnings", "ded": "Deductions, in statutory order", "net": "Net pay",
           "no": "Document", "days": "Payable days", "lwp": "Leave without pay", "ot": "Overtime hours",
           "pf": "Employer PF", "wages": "Wages for s.125", "cash": "Non-cash benefits", "tax": "Tax withheld to date",
           "total": "Total", "working": "Tax working"},
    "bn": {"slip": "মজুরি স্লিপ", "earn": "আয়", "ded": "কাটা, আইনি ক্রমানুসারে", "net": "নিট বেতন", "no": "নথি",
           "days": "প্রদেয় দিন", "lwp": "বিনা বেতনে ছুটি", "ot": "ওভারটাইম ঘণ্টা", "pf": "নিয়োগকর্তার পিএফ",
           "wages": "ধারা ১২৫-এর মজুরি", "cash": "অ-নগদ সুবিধা", "tax": "এ পর্যন্ত কর্তিত কর", "total": "মোট",
           "working": "করের হিসাব"},
}
CSS = """@page { size: A4; margin: 16mm }
body { font: 10.5pt 'Noto Sans Bengali','Lohit Bengali','Mukti Narrow','DejaVu Sans',sans-serif; color: #16172A }
header { border-bottom: 2px solid #16172A; padding-bottom: 8pt; margin-bottom: 10pt }
h1 { font-size: 14pt; margin: 0 } h2 { font-size: 9pt; text-transform: uppercase; margin: 12pt 0 4pt }
table { width: 100%; border-collapse: collapse } td { padding: 2pt 0; vertical-align: top }
td.n { text-align: right; font-family: 'DejaVu Sans Mono',monospace } .cols { width: 100% } .cols > tbody > tr > td { width: 50%; padding-right: 14pt }
.net { border-top: 1px solid #16172A; margin-top: 10pt; padding-top: 8pt; font-size: 15pt; font-weight: 700 }
.words { font-size: 10pt; font-weight: 400 } .meta { color: #58536E; font-size: 9pt } .total td { border-top: 1px solid #ccc; font-weight: 700 }"""


def render_html(d, lang):
    t, bn = T[lang], lang == "bn"
    e = escape
    num = (lambda x: to_bangla_numerals(x)) if bn else (lambda x: x)
    money = lambda x: format_money(x, lang, places=2)
    f, er = d.facts_json, d.employer_json
    who = f["employee"]
    name = (bn and who["nameBn"]) or who["nameEn"]
    site = (bn and er.get("establishmentBn")) or er.get("establishment", "")

    def rows(items, label):
        return "".join(f"<tr><td>{e(label(i))}</td><td class=n>{money(i['amount'])}</td></tr>" for i in items)

    facts = [(t["days"], num(f["payableDays"].rstrip("0").rstrip("."))), (t["lwp"], num(f["lwpDays"].rstrip("0").rstrip("."))),
             (t["ot"], num(f["otHours"].rstrip("0").rstrip("."))), (t["pf"], money(f["employerPf"])),
             (t["tax"], money(f["taxWithheldToDate"])), (t["wages"], money(f["wagesForS125"])), (t["cash"], money(f["nonCash"]))]
    working = "".join(
        f"<tr><td>{'=' if s.get('isResult') else num(s['stage'])}</td>"
        f"<td>{e((bn and s['labelBn']) or s['label'])}</td><td class=n>{money(s['amount'])}</td></tr>"
        for s in d.derivation_json)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<header><h1>{e(er['name'])}</h1><div class=meta>{e(er.get('address') or '')} · {e(site)}</div>
<div>{t['slip']} — {e(format_month_year(d.run.period_start, lang))} · {t['no']} {e(d.document_no)}</div></header>
<div><b>{e(name)}</b> · {e(who['code'])} · {e(who['designation'])}</div>
<table class=cols><tr><td><h2>{t['earn']}</h2><table>{rows(d.earnings_json, lambda i: i['label'])}
<tr class=total><td>{t['total']}</td><td class=n>{money(d.gross)}</td></tr></table></td>
<td><h2>{t['ded']}</h2><table>{rows(d.deductions_json, lambda i: i['bn'] if bn else i['label'])}
<tr class=total><td>{t['total']}</td><td class=n>{money(d.total_deductions)}</td></tr></table></td></tr></table>
<div class=net>{t['net']}: {money(d.net_pay)}<div class=words>{e(d.net_in_words_bn if bn else d.net_in_words)}</div></div>
<table style="margin-top:10pt">{''.join(f'<tr><td>{a}</td><td class=n>{b}</td></tr>' for a, b in facts)}</table>
<h2>{t['working']}</h2><table>{working}</table>
<div class=meta style="margin-top:12pt">{e(d.document_hash or '')}</div></body></html>"""


def render(d, lang):
    from weasyprint import HTML

    return HTML(string=render_html(d, lang)).write_pdf()
