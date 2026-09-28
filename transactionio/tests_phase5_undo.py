"""Phase 5: undo, LIFO, and the frozen report. BR-12 and BR-35.

A closed session had no exit. `validate()` refused to reopen one and said so, so
a mistake was permanent -- and because the ledger legs still pointed at it, the
lines it had cleared could never be reconciled again either.

Undo is LIFO and terminal. The session keeps its row and its close details,
moves to UNDONE, and frees its statement period for a fresh one. It is never
reopened in place: reopening would let a second forced close hit `get_or_create`
on the same `bank_reconciliation` FK, giving an entry whose header amount is the
first close's figure while its legs net to the second's.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from journalio.models import JournalEntry, JournalEntryConnector

from transactionio.choices import BankReconciliationStatusChoices as S
from transactionio.django_rest.helpers.reconciliation import (
    ReconciliationOutOfOrder,
    reconciled_through,
    undo_reconciliation,
)
from transactionio.models import BankReconciliation

from transactionio.tests_register_gap_evidence import LedgerReconcileBase


class UndoBase(LedgerReconcileBase):
    def _actor(self):
        return self.user.get_employee()

    def undo(self, session, reason="statement was wrong"):
        """Re-read first, as the endpoint does.

        `close()` re-reads the row under a lock and returns that instance, so a
        caller holding the original still sees `status=OPEN`. The real undo path
        resolves the session by uid from the database, so refreshing here
        mirrors it rather than papering over anything.
        """
        session.refresh_from_db()
        return undo_reconciliation(session, reason, actor=self._actor())

    def force_close(self, session, entries, reason="fee not booked"):
        from weapi.django_rest.serializers.transactions.bank_reconcile import (
            PrivateWeTransactionMatchSerializer,
        )

        class R:
            def __init__(inner, user):
                inner.user = user

        s = PrivateWeTransactionMatchSerializer(
            data={
                "reconciliation_id": str(session.uid),
                "journal_entry_ids": [str(e.uid) for e in entries],
                "force": True,
                "forced_reason": reason,
            },
            context={"request": R(self.user)},
        )
        s.is_valid(raise_exception=True)
        return s.save()


class CleanUndoTests(UndoBase):
    def test_undo_moves_the_session_to_undone_and_records_why(self):
        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])

        self.undo(recon, "bank restated the statement")

        recon.refresh_from_db()
        self.assertEqual(recon.status, S.UNDONE)
        self.assertEqual(recon.undo_reason, "bank restated the statement")
        self.assertIsNotNone(recon.undone_on)
        self.assertIsNotNone(
            recon.reconciled_on,
            "the close date was erased, so the record no longer says what was "
            "undone",
        )

    def test_lines_revert_to_cleared_not_to_unmarked(self):
        """Spec s16.7: lines revert R to C.

        R is "points at a closed session"; C is "carries a tick date and no
        session". Dropping `cleared_on` too would throw away the work of having
        ticked a month.
        """
        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])

        self.undo(recon)

        leg = JournalEntryConnector.objects.get(journal=entry, account=self.bank)
        self.assertIsNone(leg.reconciliation, "the line is still reconciled")
        self.assertIsNotNone(
            leg.cleared_on, "the tick date went with the session; C was lost"
        )

    def test_the_released_lines_are_reconcilable_again(self):
        from transactionio.django_rest.helpers.reconciliation import (
            candidate_documents,
        )

        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])
        self.undo(recon)

        fresh = self.session(ending=Decimal("100"), on=date(2026, 8, 2))
        offered = [d["journal__uid"] for d in candidate_documents(fresh)]
        self.assertIn(
            entry.uid, offered,
            "the line stayed locked to the undone session, so undoing left it "
            "permanently unreconcilable -- which is the defect, not the fix",
        )

    def test_undo_frees_the_statement_period(self):
        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.close(recon, [entry])
        self.undo(recon)

        BankReconciliation.objects.create(
            company=self.company, bank_account=self.bank,
            beginning_balance=Decimal("0"),
            statement_ending_balance=Decimal("100"),
            statement_ending_date=date(2026, 8, 1),
        )

    def test_undo_requires_a_reason(self):
        from rest_framework.serializers import ValidationError

        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])
        with self.assertRaises(ValidationError):
            self.undo(recon, "   ")

    def test_an_open_session_cannot_be_undone(self):
        from rest_framework.serializers import ValidationError

        recon = self.session(ending=Decimal("100"))
        with self.assertRaises(ValidationError):
            self.undo(recon)

    def test_a_session_cannot_be_undone_twice(self):
        from rest_framework.serializers import ValidationError

        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])
        self.undo(recon)
        with self.assertRaises(ValidationError):
            self.undo(recon)


class LifoTests(UndoBase):
    def _two_closed_periods(self):
        first = self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s1 = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        self.close(s1, [first])

        second = self.deposit(Decimal("50"), when=date(2026, 8, 15))
        s2 = self.session(
            ending=Decimal("150"), beginning=Decimal("100"), on=date(2026, 9, 1)
        )
        self.close(s2, [second])
        return s1, s2

    def test_an_earlier_session_is_blocked_by_a_later_one(self):
        s1, s2 = self._two_closed_periods()
        with self.assertRaises(ReconciliationOutOfOrder) as caught:
            self.undo(s1)
        detail = caught.exception.detail
        self.assertIn("blocking_sessions", detail)
        self.assertEqual(
            [b["uid"] for b in detail["blocking_sessions"]], [str(s2.uid)],
            "the refusal must name what to undo first, not merely refuse",
        )

    def test_the_latest_session_undoes(self):
        s1, s2 = self._two_closed_periods()
        self.undo(s2)
        s2.refresh_from_db(); s1.refresh_from_db()
        self.assertEqual(s2.status, S.UNDONE)
        self.assertEqual(s1.status, S.CLOSED, "undoing the top disturbed the rest")

    def test_unwinding_the_whole_stack_works_top_down(self):
        s1, s2 = self._two_closed_periods()
        self.undo(s2)
        self.undo(s1)
        s1.refresh_from_db()
        self.assertEqual(s1.status, S.UNDONE)

    def test_reconciled_through_steps_back_on_undo(self):
        s1, s2 = self._two_closed_periods()
        self.assertEqual(
            reconciled_through(self.company, self.bank), date(2026, 9, 1)
        )
        self.undo(s2)
        self.assertEqual(
            reconciled_through(self.company, self.bank), date(2026, 8, 1),
            "spec s6.4: reconciled-through is recomputed on undo",
        )
        self.undo(s1)
        self.assertIsNone(
            reconciled_through(self.company, self.bank),
            "with nothing closed it must be None, not a stale date",
        )

    def test_closing_out_of_order_is_refused(self):
        """A LIFO undo rule with a non-LIFO close rule is not a stack."""
        later = self.deposit(Decimal("50"), when=date(2026, 8, 15))
        s2 = self.session(ending=Decimal("50"), on=date(2026, 9, 1))
        self.close(s2, [later])

        earlier = self.deposit(Decimal("100"), when=date(2026, 7, 1))
        s1 = self.session(ending=Decimal("100"), on=date(2026, 8, 1))
        with self.assertRaises(ReconciliationOutOfOrder):
            self.close(s1, [earlier])


class ForcedUndoTests(UndoBase):
    def _plug_net(self, recon):
        entry = JournalEntry.objects.filter(bank_reconciliation=recon).first()
        if entry is None:
            return None
        totals = JournalEntryConnector.objects.filter(
            journal=entry, account=self.bank
        ).aggregate(d=Sum("debit"), c=Sum("credit"))
        return Decimal(str(totals["d"] or 0)) - Decimal(str(totals["c"] or 0))

    def test_undoing_a_forced_close_nets_the_plug_to_zero(self):
        entry = self.deposit(Decimal("60"))
        recon = self.session(ending=Decimal("100"))
        self.force_close(recon, [entry])
        self.assertNotEqual(self._plug_net(recon), Decimal("0"))

        self.undo(recon)
        self.assertEqual(
            self._plug_net(recon), Decimal("0"),
            "the plug still moves the bank account after the session that "
            "posted it was undone",
        )

    def test_the_plug_entry_survives_as_history(self):
        entry = self.deposit(Decimal("60"))
        recon = self.session(ending=Decimal("100"))
        self.force_close(recon, [entry])
        plug = JournalEntry.objects.get(bank_reconciliation=recon)

        self.undo(recon)
        self.assertTrue(
            JournalEntry.objects.filter(pk=plug.pk).exists(),
            "the adjustment was deleted rather than reversed, so the ledger no "
            "longer records that a forced close ever happened",
        )

    def test_undoing_twice_does_not_double_the_reversal(self):
        """Netting per group is what makes a repeat harmless."""
        from rest_framework.serializers import ValidationError

        entry = self.deposit(Decimal("60"))
        recon = self.session(ending=Decimal("100"))
        self.force_close(recon, [entry])
        self.undo(recon)
        legs_after_first = JournalEntryConnector.objects.filter(
            journal__bank_reconciliation=recon
        ).count()

        with self.assertRaises(ValidationError):
            self.undo(recon)
        self.assertEqual(
            JournalEntryConnector.objects.filter(
                journal__bank_reconciliation=recon
            ).count(),
            legs_after_first,
        )

    def test_every_plug_leg_is_released(self):
        entry = self.deposit(Decimal("60"))
        recon = self.session(ending=Decimal("100"))
        self.force_close(recon, [entry])
        self.undo(recon)

        still_held = JournalEntryConnector.objects.filter(
            journal__bank_reconciliation=recon, reconciliation__isnull=False
        )
        self.assertFalse(
            still_held.exists(),
            "a plug leg is still cleared by the undone session; a later OPEN "
            "session that ticked it would carry a cleared leg and an unticked "
            "sibling, moving its difference while its register row read 0.00",
        )


class FrozenReportTests(UndoBase):
    """BR-35. The report cannot be recomputed once the ledger moves."""

    def test_closing_freezes_the_report(self):
        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])
        recon.refresh_from_db()

        snap = recon.report_snapshot
        self.assertIsNotNone(snap, "no report was frozen at close")
        self.assertEqual(snap["difference"], "0.00")
        self.assertEqual(snap["cleared"]["document_count"], 1)
        self.assertEqual(snap["statement"]["ending_balance"], "100.00")

    def test_the_frozen_report_survives_a_later_amendment(self):
        """An amend appends a delta leg to a document already cleared."""
        from journalio.choices import JournalEntryConnectorRequestKindChoices

        entry = self.deposit(Decimal("100"))
        recon = self.session(ending=Decimal("100"))
        self.close(recon, [entry])
        recon.refresh_from_db()
        frozen = dict(recon.report_snapshot["cleared"])

        self._leg(
            entry, self.bank, debit=Decimal("40"),
            request_kind=JournalEntryConnectorRequestKindChoices.UPDATED,
        )
        recon.refresh_from_db()
        self.assertEqual(
            recon.report_snapshot["cleared"], frozen,
            "the stored report moved when the ledger did, so last month's "
            "report no longer says what the bank agreed to",
        )

    def test_the_snapshot_records_a_forced_close(self):
        entry = self.deposit(Decimal("60"))
        recon = self.session(ending=Decimal("100"))
        self.force_close(recon, [entry], reason="bank fee not booked")
        recon.refresh_from_db()

        self.assertTrue(recon.report_snapshot["forced"]["is_forced"])
        self.assertEqual(
            recon.report_snapshot["forced"]["reason"], "bank fee not booked"
        )
