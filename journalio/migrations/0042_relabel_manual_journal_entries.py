"""Relabel hand-keyed entries that were stamped PURCHASE by the model default.

`JournalEntry.kind` defaults to PURCHASE, and the manual-journal create path
never set it -- `kind` is not among that serializer's fields. Every other member
of the enum names the document an entry was posted from; a hand-keyed entry has
no document, so it was labelled a bill. Nothing read the field until the
register's Type column did, at which point every manual entry in the system
would have rendered as "Bill".

The predicate is exact rather than heuristic: an entry that claims to be a
PURCHASE while holding no document FK at all cannot be one. `create_journal_entry`
sets the FK named by the kind, so a real purchase always carries `purchase`.
"""

from django.db import migrations
from django.db.models import Q


# Every document link on JournalEntry. An entry holding none of them was not
# posted from a document, so it was keyed by hand.
DOCUMENT_FKS = [
    "purchase",
    "expense",
    "purchase_payment",
    "pay_bill",
    "sale",
    "sale_payment_receive",
    "credit_note",
    "stock_adjustment",
    "product",
    "bank_deposit",
    "bank_reconciliation",
    "payroll_salary",
    "tax_payment",
    "sales_tax",
]


def _orphans(model, kind):
    unlinked = Q()
    for fk in DOCUMENT_FKS:
        unlinked &= Q(**{f"{fk}__isnull": True})
    return model.objects.filter(unlinked, kind=kind)


def relabel(apps, schema_editor):
    JournalEntry = apps.get_model("journalio", "JournalEntry")
    moved = _orphans(JournalEntry, "PURCHASE").update(kind="JOURNAL_ENTRY")
    if moved:
        print(f"  relabelled {moved} hand-keyed entries PURCHASE -> JOURNAL_ENTRY")


def unrelabel(apps, schema_editor):
    JournalEntry = apps.get_model("journalio", "JournalEntry")
    _orphans(JournalEntry, "JOURNAL_ENTRY").update(kind="PURCHASE")


class Migration(migrations.Migration):

    dependencies = [
        ("journalio", "0041_alter_journalentry_kind"),
    ]

    operations = [
        migrations.RunPython(relabel, unrelabel),
    ]
