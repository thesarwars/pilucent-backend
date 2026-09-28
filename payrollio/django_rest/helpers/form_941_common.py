"""Shared Form 941 helpers (no imports from builder/pdf_fields)."""

from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money


def pdf_field(name):
    """Map logical field ``f1_10`` to AcroForm name ``f1_10[0]``."""
    if "[" in name:
        return name
    return f"{name}[0]"


def money_parts(value):
    amount = quantize_money(value)
    whole, cents = divmod(int(amount * 100), 100)
    return str(whole), f"{cents:02d}"
