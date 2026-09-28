"""The forced-close plug posts a bank leg that no session has cleared.

Found by an adversarial design review of Phase 5, in shipped Phase 3/4 code.

`post_reconciliation_discrepancy` runs AFTER the ticking pass in
`PrivateWeTransactionMatchSerializer.save()`, and never sets
`connector.reconciliation` on the legs it writes. So the plug -- an entry whose
whole purpose is to make the book agree with a statement the session just closed
against -- lands on the bank account as an UNCLEARED candidate, and is offered
to every later session as though it were outstanding activity.

It is not outstanding. It was accounted for by the close that created it.

The consequence is worse than an extra row, because the two readers disagree on
their unit: `cleared_totals` sums LEGS while `candidate_documents` sums GROUPS.
A later session that ticks the plug moves its difference by the plug amount
while its register row reads 0.00.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from journalio.models import JournalEntryConnector

from transactionio.django_rest.helpers.reconciliation import (
    candidate_documents,
    cleared_totals,
)
from transactionio.models import BankReconciliation

from transactionio.tests_register_gap_evidence import LedgerReconcileBase


class PlugLegTests(LedgerReconcileBase):
    def force_close(self, session, entries, reason="fee not booked"):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        s = PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(session.uid),
                "journal_entry_ids": [str(e.uid) for e in entries],
                "force": True,
                "forced_reason": reason,
            },
            context={"request": self._req()},
        )
        s.is_valid(raise_exception=True)
        return s.save()

    def _req(self):
        class R:
            def __init__(inner, user):
                inner.user = user

        return R(self.user)

    def test_the_plug_is_cleared_by_the_session_that_posted_it(self):
        entry = self.deposit(Decimal("60"), when=date(2026, 7, 1))
        recon = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.force_close(recon, [entry])
        recon.refresh_from_db()
        self.assertTrue(recon.is_forced, "the session did not force-close")

        plug_legs = JournalEntryConnector.objects.filter(
            account=self.bank, journal__bank_reconciliation=recon
        )
        self.assertTrue(plug_legs.exists(), "no plug leg was posted to the bank")
        unclear = plug_legs.filter(reconciliation__isnull=True)
        self.assertFalse(
            unclear.exists(),
            f"{unclear.count()} plug leg(s) left uncleared -- the entry that "
            f"exists to make this session balance is offered to the next "
            f"session as outstanding activity",
        )

    def test_a_later_session_is_not_offered_the_plug(self):
        entry = self.deposit(Decimal("60"), when=date(2026, 7, 1))
        first = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.force_close(first, [entry])

        later = BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("100"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 9, 1),
        )
        offered = [d["journal__uid"] for d in candidate_documents(later)]
        plug_uids = {
            c.journal.uid
            for c in JournalEntryConnector.objects.filter(
                account=self.bank, journal__bank_reconciliation=first
            ).select_related("journal")
        }
        leaked = plug_uids & set(offered)
        self.assertEqual(
            leaked, set(),
            "the prior session's discrepancy plug is offered to the next "
            "session as an outstanding item",
        )

    def test_the_two_readers_agree_on_the_plug(self):
        """`cleared_totals` sums legs; `candidate_documents` sums groups."""
        entry = self.deposit(Decimal("60"), when=date(2026, 7, 1))
        recon = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.force_close(recon, [entry])

        debits, credits = cleared_totals(recon)
        rows = list(candidate_documents(recon, cleared=True))
        group_debits = sum(Decimal(str(r["debit"])) for r in rows)
        group_credits = sum(Decimal(str(r["credit"])) for r in rows)
        self.assertEqual(
            (debits, credits), (group_debits, group_credits),
            "the leg sum and the group sum disagree, so the difference and the "
            "register rows are computed from different populations",
        )
