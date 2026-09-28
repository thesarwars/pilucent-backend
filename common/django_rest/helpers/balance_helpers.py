import logging
from decimal import Decimal

from django.db.models import F

from accounts.choices import ChartOfAccountKindChoices

from journalio.choices import JournalEntryConnectorKindChoices

from payrollio.django_rest.helpers.payroll_journal_mappings import quantize_money

logger = logging.getLogger(__name__)


def update_opening_balance(
    object,
    operation_type,
    request_opening_balance,
    current_opening_balance,
):
    """Move an object's stored running balance.

    `operation_type` is CREDIT / DEBIT / UPDATE. CREDIT and DEBIT are **not**
    accounting sides here -- they mean add and subtract against the stored
    balance, in the account's own natural direction. Use
    `balance_operation_for_action()` to convert a connector action_type
    ("addition" / "substraction") into the right one; passing those strings
    directly is the mistake this function used to swallow.

    Raises ValueError on an unrecognised operation. It previously fell through
    every branch and returned silently, so six purchase-module call sites passing
    "addition"/"substraction" had been dead for their whole lifetime -- the
    journal line was written while the stored balance was not, which is one of
    the named sources of the drift `manage.py audit_ledger` reports. A balance
    mutation that silently does nothing is the worst possible failure here: the
    caller has already committed to the journal by the time it is called.

    The write itself is an atomic `F()` increment rather than a read-modify-write.
    Two concurrent postings against the same account both used to read the same
    starting figure and write back their own total, so one increment was simply
    lost -- and control accounts like Accounts Receivable are touched by nearly
    every document, which is where that collides most often.

    Three contracts this has to keep while doing that, each of which a naive
    `F()` rewrite silently breaks:

    1. **The caller reads the new value straight afterwards.** ~84 call sites do
       `connector.last_balance = account.opening_balance` on the next line. An
       `F()` update leaves the in-memory instance holding the OLD figure, so
       those would stamp the pre-update balance into the ledger -- a fresh
       silent-corruption bug of exactly the kind this work exists to remove.
       Hence the `refresh_from_db()`.
    2. **It is polymorphic.** `ChartOfAccount`, `Customer` and `Supplier` all
       have an `opening_balance` and are all passed here, so the update goes
       through `type(object)._default_manager`, not a hard-coded manager.
    3. **The trailing `save_dirty_fields()` also flushed whatever else the
       caller had dirtied.** That is incidental, but callers rely on it, so it
       still runs -- after the refresh, by which point `opening_balance` is
       clean and cannot be written back stale over another writer's increment.
    """
    request_opening_balance = quantize_money(request_opening_balance)
    current_opening_balance = quantize_money(current_opening_balance)
    # The model declares `default=0.00`, a Python float, so an instance that has
    # not been round-tripped through the database still holds a float here and
    # `float + Decimal` raises TypeError. Reachable whenever an account is
    # created and posted to without an intervening refresh.
    object.opening_balance = quantize_money(object.opening_balance)
    debit_or_credit = {}
    operation_type = str(operation_type).upper()

    if operation_type not in {
        JournalEntryConnectorKindChoices.CREDIT,
        JournalEntryConnectorKindChoices.DEBIT,
        "UPDATE",
    }:
        raise ValueError(
            f"update_opening_balance: unknown operation {operation_type!r} for "
            f"{object!r}. Expected CREDIT (add), DEBIT (subtract) or UPDATE. "
            "If you have a connector action_type, convert it with "
            "balance_operation_for_action()."
        )

    logger.info(
        "update_opening_balance called: object=%s, operation=%s, "
        "request_balance=%s, current_balance=%s, opening_balance_before=%s",
        object, operation_type, request_opening_balance,
        current_opening_balance, object.opening_balance,
    )

    # Work out the signed movement; apply it to the database, not to the
    # in-memory value.
    delta = Decimal("0.00")

    if operation_type in [
        JournalEntryConnectorKindChoices.CREDIT,
        JournalEntryConnectorKindChoices.DEBIT,
    ]:
        delta = {
            JournalEntryConnectorKindChoices.CREDIT: 1,
            JournalEntryConnectorKindChoices.DEBIT: -1,
        }.get(operation_type, 0) * request_opening_balance

    elif operation_type == "UPDATE":
        if request_opening_balance > current_opening_balance:
            delta = request_opening_balance - current_opening_balance
            debit_or_credit["action_type"] = "addition"
            debit_or_credit["total_debit_or_credit"] = delta

        elif request_opening_balance < current_opening_balance:
            delta = -(current_opening_balance - request_opening_balance)
            debit_or_credit["action_type"] = "substraction"
            debit_or_credit["total_debit_or_credit"] = -delta

    apply_balance_delta(object, delta)

    logger.info(
        "update_opening_balance result: object=%s, opening_balance_after=%s, "
        "debit_or_credit=%s",
        object, object.opening_balance, debit_or_credit,
    )

    return debit_or_credit


def apply_balance_delta(object, delta):
    """Add `delta` to `object.opening_balance` atomically, then resynchronise.

    Split out so the ordering is explicit and testable. Each step is load-bearing:

    * the `F()` update is computed by the database, so two concurrent postings
      against the same account cannot lose one another's increment;
    * `refresh_from_db` pulls the committed figure back, because ~84 callers read
      `object.opening_balance` on the next line to stamp
      `JournalEntryConnector.last_balance`. It also clears the dirty flag for
      that one field (DirtyFieldsMixin resets per-field when `fields=` is given);
    * `save_dirty_fields()` then flushes anything ELSE the caller dirtied before
       calling in -- preserving behaviour callers depended on. It runs *after*
       the refresh precisely so it cannot write a stale balance back over
       another writer's increment.
    """
    if object.pk is None:
        # Nothing to increment against yet; fall back to the in-memory path.
        object.opening_balance = quantize_money(object.opening_balance) + delta
        object.save_dirty_fields()
        return

    if delta:
        type(object)._default_manager.filter(pk=object.pk).update(
            opening_balance=F("opening_balance") + delta
        )
        object.refresh_from_db(fields=["opening_balance"])

    object.save_dirty_fields()


def action_for_side(account_kind, side):
    """The `connector_data` action that posts `side` for this account kind.

    `get_debit_or_credit` maps "addition"/"substraction" to DEBIT/CREDIT
    differently per kind, so hard-coding "addition" only lands on the intended
    side for some kinds. Where a leg's direction is fixed by the *transaction*
    rather than by the account -- cash back on a deposit is always a debit,
    whatever account it is taken to -- resolve the action from the side instead.
    """
    mapping = get_debit_or_credit(account_kind) or {}
    for action, resolved in mapping.items():
        if resolved == side:
            return action
    return "addition"


def balance_operation_for_action(action_type):
    """How `update_opening_balance` must be called to match a connector action.

    Its CREDIT/DEBIT argument is add/subtract against the stored balance, not an
    accounting side (see that function's docstring), so "addition" pairs with
    CREDIT and "substraction" with DEBIT. Pairing them wrongly leaves the stored
    running balance disagreeing with the journal.
    """
    return (
        JournalEntryConnectorKindChoices.CREDIT
        if action_type == "addition"
        else JournalEntryConnectorKindChoices.DEBIT
    )


def inverse_balance_operation(operation):
    """The operation that undoes `operation`.

    `update_opening_balance` reads CREDIT as add and DEBIT as subtract -- they
    are not accounting sides here -- so undoing a move is simply the other one.

    Exists because amend paths kept hard-coding the undo. That is correct only
    while the account is the kind the author pictured, and it silently stops
    mirroring the posting leg the moment the posting becomes kind-aware. Pair
    this with `balance_operation_for_action(action_for_side(...))` so a
    reversal is derived from the same rule as the thing it reverses.
    """
    return (
        JournalEntryConnectorKindChoices.DEBIT
        if operation == JournalEntryConnectorKindChoices.CREDIT
        else JournalEntryConnectorKindChoices.CREDIT
    )


def amend_leg(account, side, new_amount, old_amount):
    """Move an already-posted leg from `old_amount` to `new_amount`.

    Returns `(action_type, amount)` for the connector, or None when the figure
    did not change and no leg should be written.

    Amend paths across the serializers were written as
    `update_opening_balance(account, "update", new, old)`, which decides the
    direction from whether the number went *up or down* rather than from what
    the leg is. That is wrong twice over on a leg whose side is fixed by the
    transaction:

    - Raising a payment receipt from 100 to 150 CREDITS the receivable a further
      50 -- the customer owes less still. The "update" op added 50 to the stored
      balance and recorded "addition", which on an asset resolves to a DEBIT. So
      the amendment moved both the balance and the journal the opposite way from
      the posting it was amending.
    - It reads no account kind at all, so even where the direction happened to be
      right for an asset it stopped mirroring the moment the posting leg became
      kind-aware -- which is what the rest of this sweep has been doing to the
      posting legs.

    Deriving both halves from `side` here means an amendment is the same rule as
    the posting, evaluated against the same account, and a decrease is simply the
    other side of it.
    """
    delta = quantize_money(new_amount) - quantize_money(old_amount)
    if not delta:
        return None

    effective_side = (
        side
        if delta > 0
        else (
            JournalEntryConnectorKindChoices.DEBIT
            if side == JournalEntryConnectorKindChoices.CREDIT
            else JournalEntryConnectorKindChoices.CREDIT
        )
    )
    action = action_for_side(account.kind, effective_side)
    amount = abs(delta)
    update_opening_balance(
        account, balance_operation_for_action(action), amount, 0
    )
    return action, amount


def amend_balance(object, posting_operation, new_amount, old_amount):
    """`amend_leg` for something that has no account kind.

    `Customer` and `Supplier` carry an `opening_balance` and are passed to
    `update_opening_balance` like accounts are, but they have no `kind`, so there
    is no side to resolve -- the posting simply moved the balance one way and an
    amendment has to continue in that direction.

    Pass the operation the POSTING used. Raising the figure moves further the
    same way; lowering it walks back. This is the same contract as `amend_leg`
    and exists so a kind-less balance beside a leg is amended by the same rule
    rather than by `"update"`, which reads the direction off whether the number
    rose and so inverts every posting that subtracted.

    Returns `(operation, amount)` for symmetry with `amend_leg`, or None when the
    figure did not change.
    """
    delta = quantize_money(new_amount) - quantize_money(old_amount)
    if not delta:
        return None

    operation = (
        posting_operation
        if delta > 0
        else inverse_balance_operation(posting_operation)
    )
    amount = abs(delta)
    update_opening_balance(object, operation, amount, 0)
    return operation, amount


def get_migration_undo_balance_operation(account, connector_kind):
    """Return the `update_opening_balance` op that undoes a migration import connector.

    Migration importers (invoice / sales receipt) adjust balances with
    ``update_opening_balance`` using an internal convention (CREDIT = add,
    DEBIT = subtract) that does not always match the accounting DEBIT/CREDIT
    stored on ``JournalEntryConnector.kind`` (via ``get_debit_or_credit``).

    Importers always use CREDIT for "addition" connectors and DEBIT for
    "substraction" connectors in that internal sense — regardless of account
    type. Rollback must invert those ops, not the connector's accounting kind.
    """
    connector_kind = (connector_kind or "").upper()
    mapping = get_debit_or_credit(account.kind) or {}
    if connector_kind in mapping.values():
        # Same resolution `action_for_side` does; kept in terms of it so the
        # side/operation pairing lives in exactly one place.
        import_op = balance_operation_for_action(
            action_for_side(account.kind, connector_kind)
        )
        return (
            JournalEntryConnectorKindChoices.DEBIT
            if import_op == JournalEntryConnectorKindChoices.CREDIT
            else JournalEntryConnectorKindChoices.CREDIT
        )
    # Unknown mapping — fall back to inverting connector kind in internal terms.
    return (
        JournalEntryConnectorKindChoices.DEBIT
        if connector_kind == JournalEntryConnectorKindChoices.CREDIT
        else JournalEntryConnectorKindChoices.CREDIT
    )


def get_debit_or_credit(account_kind):
    return {
        ChartOfAccountKindChoices.ASSETS: {
            "addition": JournalEntryConnectorKindChoices.DEBIT,
            "substraction": JournalEntryConnectorKindChoices.CREDIT,
        },
        ChartOfAccountKindChoices.LIABILITIES: {
            "addition": JournalEntryConnectorKindChoices.CREDIT,
            "substraction": JournalEntryConnectorKindChoices.DEBIT,
        },
        ChartOfAccountKindChoices.EQUITIES: {
            "addition": JournalEntryConnectorKindChoices.CREDIT,
            "substraction": JournalEntryConnectorKindChoices.DEBIT,
        },
        ChartOfAccountKindChoices.INCOMES: {
            "addition": JournalEntryConnectorKindChoices.CREDIT,
            "substraction": JournalEntryConnectorKindChoices.DEBIT,
        },
        ChartOfAccountKindChoices.EXPENSES: {
            "addition": JournalEntryConnectorKindChoices.DEBIT,
            "substraction": JournalEntryConnectorKindChoices.CREDIT,
        },
    }.get(account_kind)
