"""Bank advice and wallet disbursement files (run payroll §6.5), ported from
the front end's `bankprofiles.js`.

There is no national standard: large banks vary the format by corporate
agreement, so formats are a profile library, not code paths. The company's
own debit account for a profile is a `CorporateAccount`. One invalid row
rejects most bulk batches, so validation runs before anything is written and
a part-file is never produced. The bytes generated are the bytes stored and
hashed (BNK-1: the preview is the file).

`CASH-SHEET` is ours: cash wages are paid against signature, so the
instruction for them is a signing sheet rather than a bank file.
"""

import hashlib
from decimal import ROUND_HALF_UP, Decimal

from common.money import to_decimal

WALLET_PREFIXES = ("013", "014", "015", "016", "017", "018", "019")

PROFILES = [
    {"code": "BP-CITY-CSV", "name": "City Bank — corporate salary, CSV", "bank": "City Bank", "kind": "BANK",
     "format": "CSV", "encoding": "UTF-8", "delimiter": ",", "dateFormat": "DD/MM/YYYY", "amountDecimals": 2,
     "headerRows": [{"kind": "literal", "text": "CORPORATE SALARY UPLOAD"},
                    {"kind": "tokens", "tokens": ["{{corporateAccount}}", "{{paymentDate}}", "{{recordCount}}"]},
                    {"kind": "columnNames"}],
     "columns": [{"field": "accountNumber", "header": "BENEF_AC"}, {"field": "accountName", "header": "BENEF_NAME"},
                 {"field": "amount", "header": "AMOUNT"}, {"field": "employeeRef", "header": "REF"},
                 {"field": "narration", "header": "NARRATION"}, {"field": "routingNumber", "header": "ROUTING"}],
     "footerRows": [{"kind": "tokens", "tokens": ["TOTAL", "{{controlTotal}}", "{{recordCount}}"]}]},
    {"code": "BP-BRAC-FW", "name": "BRAC Bank — fixed width, 200 char", "bank": "BRAC Bank", "kind": "BANK",
     "format": "FIXED", "encoding": "Windows-1252", "dateFormat": "YYYYMMDD", "amountDecimals": 2,
     "headerRows": [{"kind": "tokens", "tokens": ["H", "{{corporateAccount}}", "{{paymentDate}}", "{{recordCount}}"]}],
     "columns": [{"field": "accountNumber", "header": "AC", "width": 20, "align": "left", "pad": " "},
                 {"field": "accountName", "header": "NAME", "width": 40, "align": "left", "pad": " "},
                 {"field": "amount", "header": "AMT", "width": 15, "align": "right", "pad": "0"},
                 {"field": "employeeRef", "header": "REF", "width": 12, "align": "left", "pad": " "},
                 {"field": "routingNumber", "header": "ROUTE", "width": 9, "align": "right", "pad": "0"},
                 {"field": "narration", "header": "NARR", "width": 30, "align": "left", "pad": " "}],
     "footerRows": [{"kind": "tokens", "tokens": ["T", "{{controlTotal}}", "{{recordCount}}"]}]},
    {"code": "MFS-BKASH", "name": "bKash — bulk disbursement, CSV", "bank": "bKash", "kind": "MFS",
     "provider": "BKASH", "format": "CSV", "encoding": "UTF-8", "delimiter": ",", "dateFormat": "YYYY-MM-DD",
     "amountDecimals": 2, "headerRows": [{"kind": "columnNames"}],
     "columns": [{"field": "walletNumber", "header": "MSISDN"}, {"field": "amount", "header": "AMOUNT"},
                 {"field": "employeeRef", "header": "REFERENCE"}, {"field": "narration", "header": "REMARKS"}],
     "footerRows": []},
    {"code": "MFS-NAGAD", "name": "Nagad — bulk disbursement, CSV", "bank": "Nagad", "kind": "MFS",
     "provider": "NAGAD", "format": "CSV", "encoding": "UTF-8", "delimiter": ",", "dateFormat": "DD-MM-YYYY",
     "amountDecimals": 0,
     "headerRows": [{"kind": "literal", "text": "NAGAD BULK DISBURSEMENT"}, {"kind": "columnNames"}],
     "columns": [{"field": "walletNumber", "header": "ACCOUNT"}, {"field": "amount", "header": "AMOUNT"},
                 {"field": "employeeRef", "header": "REF"}],
     "footerRows": [{"kind": "tokens", "tokens": ["TOTAL", "{{controlTotal}}"]}]},
    {"code": "MFS-ROCKET", "name": "Rocket — bulk disbursement, TSV", "bank": "Rocket", "kind": "MFS",
     "provider": "ROCKET", "format": "TSV", "encoding": "UTF-8", "delimiter": "\t", "dateFormat": "YYYYMMDD",
     "amountDecimals": 2, "headerRows": [{"kind": "columnNames"}],
     "columns": [{"field": "walletNumber", "header": "WALLET"}, {"field": "amount", "header": "AMOUNT"},
                 {"field": "employeeRef", "header": "REF"}, {"field": "narration", "header": "PURPOSE"}],
     "footerRows": [{"kind": "tokens", "tokens": ["CTRL", "{{controlTotal}}", "{{recordCount}}"]}]},
    {"code": "MFS-UPAY", "name": "Upay — bulk disbursement, CSV", "bank": "Upay", "kind": "MFS", "provider": "UPAY",
     "format": "CSV", "encoding": "UTF-8", "delimiter": ",", "dateFormat": "YYYY-MM-DD", "amountDecimals": 2,
     "headerRows": [{"kind": "columnNames"}],
     "columns": [{"field": "walletNumber", "header": "MOBILE"}, {"field": "amount", "header": "AMOUNT"},
                 {"field": "employeeRef", "header": "EMP_ID"}],
     "footerRows": []},
    {"code": "CASH-SHEET", "name": "Cash — signing sheet, CSV", "bank": "Cash", "kind": "CASH", "format": "CSV",
     "encoding": "UTF-8", "delimiter": ",", "dateFormat": "DD/MM/YYYY", "amountDecimals": 0, "needsAccount": False,
     "headerRows": [{"kind": "literal", "text": "CASH WAGES — PAID AGAINST SIGNATURE"},
                    {"kind": "tokens", "tokens": ["{{paymentDate}}", "{{recordCount}}"]}, {"kind": "columnNames"}],
     "columns": [{"field": "employeeRef", "header": "CODE"}, {"field": "accountName", "header": "NAME"},
                 {"field": "amount", "header": "AMOUNT"}, {"field": "signature", "header": "SIGNATURE"}],
     "footerRows": [{"kind": "tokens", "tokens": ["TOTAL", "{{controlTotal}}", "{{recordCount}}"]}]},
]
BY_CODE = {p["code"]: p for p in PROFILES}


class FileRefused(Exception):
    def __init__(self, message, issues=None):
        self.message = message
        self.issues = issues or []
        super().__init__(message)


def profile(code):
    p = BY_CODE.get(code)
    if p is None:
        raise FileRefused(f"Unknown bank or wallet profile: {code}.")
    return p


def method_of(p):
    return {"BANK": "BANK_TRANSFER", "MFS": "MOBILE_WALLET", "CASH": "CASH"}[p["kind"]]


def needs_account(p):
    return p.get("needsAccount", True)


def matches(p, line):
    """Whether a run line is paid through this profile."""
    if line.payment_method != method_of(p):
        return False
    return p["kind"] != "MFS" or (line.mfs_provider or "") == p["provider"]


def fmt_date(d, pattern):
    return pattern.replace("YYYY", f"{d.year:04d}").replace("DD", f"{d.day:02d}").replace("MM", f"{d.month:02d}")


def fmt_amount(value, p):
    places = p["amountDecimals"]
    q = Decimal(1).scaleb(-places)
    return format(to_decimal(value).quantize(q, rounding=ROUND_HALF_UP), "f")


def _pad(s, width, align, pad):
    s = str(s if s is not None else "")[:width]
    fill = (pad or " ") * max(0, width - len(s))
    return fill + s if align == "right" else s + fill


def _cell(s, delim):
    s = str(s if s is not None else "")
    if delim in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def validate_wallet(number, p):
    s = "".join(ch for ch in str(number or "") if ch.isdigit())
    if not s:
        return "Missing wallet number"
    if len(s) != 11:
        return f"Wallet number must be 11 digits — this one has {len(s)}"
    if not s.startswith("01"):
        return "Wallet number must start 01"
    if s[:3] not in WALLET_PREFIXES:
        return f"Prefix {s[:3]} is not valid for {p['bank']}"
    return None


def validate_rows(rows, p):
    """[{index, employeeRef, name, severity BLOCKS|WARNS, check, message}]."""
    issues, seen = [], {}

    def add(i, r, severity, check, message):
        issues.append({"index": i, "employeeRef": r["employeeRef"], "name": r.get("accountName") or "",
                       "severity": severity, "check": check, "message": message})

    for i, r in enumerate(rows):
        if not to_decimal(r["amount"]) > 0:
            add(i, r, "BLOCKS", "Net pay", "Net pay is zero or negative")
        if p["kind"] == "MFS":
            w = validate_wallet(r.get("walletNumber"), p)
            if w:
                add(i, r, "BLOCKS", "Wallet", w)
        elif p["kind"] == "BANK":
            if not r.get("accountNumber"):
                add(i, r, "BLOCKS", "Account", "Missing account number")
            if len("".join(ch for ch in str(r.get("routingNumber") or "") if ch.isdigit())) != 9:
                add(i, r, "BLOCKS", "Routing", "Routing number must be 9 digits")
        if p["kind"] != "CASH":
            key = r.get("walletNumber") if p["kind"] == "MFS" else r.get("accountNumber")
            if key:
                if key in seen:
                    add(i, r, "WARNS", "Duplicate",
                        f"Same destination as row {seen[key] + 1} — legitimate for family members")
                else:
                    seen[key] = i
            if r.get("accountName") and r.get("employeeName") and \
                    r["accountName"].strip() != r["employeeName"].strip():
                add(i, r, "WARNS", "Name match", "Account name differs from employee name")
    return issues


def generate(p, rows, *, corporate_account, payment_date, run_ref):
    """{text, lines, recordCount, controlTotal, fileName, hash}; refuses the
    whole file when any row blocks."""
    issues = validate_rows(rows, p)
    blocking = [x for x in issues if x["severity"] == "BLOCKS"]
    if blocking:
        n = len(blocking)
        raise FileRefused(f"{n} row{'' if n == 1 else 's'} must be fixed before a file can be generated. In most "
                          "bulk formats a single invalid row rejects the entire batch.", issues)
    if not rows:
        raise FileRefused(f"No line in this run is paid through {p['name']}.")
    control = sum((to_decimal(r["amount"]) for r in rows), Decimal(0))
    tokens = {"{{corporateAccount}}": corporate_account or "", "{{paymentDate}}": fmt_date(payment_date, p["dateFormat"]),
              "{{recordCount}}": str(len(rows)), "{{controlTotal}}": fmt_amount(control, p), "{{runId}}": run_ref,
              "{{bank}}": p["bank"]}

    def expand(s):
        for k, v in tokens.items():
            s = s.replace(k, v)
        return s

    delim, fixed, lines = p.get("delimiter", ","), p["format"] == "FIXED", []

    def emit(cells):
        lines.append("".join(cells) if fixed else delim.join(_cell(c, delim) for c in cells))

    for h in p["headerRows"]:
        if h["kind"] == "literal":
            emit([expand(h["text"])])
        elif h["kind"] == "columnNames":
            emit([_pad(c["header"], c["width"], c["align"], " ") if fixed else c["header"] for c in p["columns"]])
        else:
            emit([expand(t) for t in h["tokens"]])
    for r in rows:
        cells = []
        for c in p["columns"]:
            if c["field"] == "amount":
                raw = fmt_amount(r["amount"], p)
            elif c["field"] == "paymentDate":
                raw = fmt_date(payment_date, p["dateFormat"])
            else:
                raw = r.get(c["field"]) or ""
            cells.append(_pad(raw, c["width"], c["align"], c["pad"]) if fixed else raw)
        emit(cells)
    for f in p["footerRows"]:
        emit([expand(f["text"])] if f["kind"] == "literal" else [expand(t) for t in f["tokens"]])

    text = "\r\n".join(lines) + "\r\n"
    ext = {"TSV": "tsv", "FIXED": "txt"}.get(p["format"], "csv")
    data = text.encode("cp1252" if p["encoding"] == "Windows-1252" else "utf-8", errors="replace")
    return {"text": text, "lines": lines, "recordCount": len(rows), "controlTotal": control,
            "fileName": f"{run_ref}-{p['code']}.{ext}", "hash": hashlib.sha256(data).hexdigest(), "issues": issues}


def profile_out(p, account=None):
    return {"code": p["code"], "name": p["name"], "bank": p["bank"], "kind": p["kind"],
            "provider": p.get("provider"), "format": p["format"], "encoding": p["encoding"],
            "method": method_of(p), "needsAccount": needs_account(p), "corporateAccount": account}
