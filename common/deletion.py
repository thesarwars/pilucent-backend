"""Making Django's collector walk edges the schema told it to ignore.

Several foreign keys in this project are `on_delete=DO_NOTHING`, which does not
mean "no constraint" -- `db_constraint` still defaults to True. The collector
skips those rows while Postgres goes on enforcing the FK, so the violation
surfaces at COMMIT where no view can catch it:

    update or delete on table "employeeio_employee" violates foreign key
    constraint "payrollio_payrollsal_employee_id_35b6c426_fk_employeei"

Administrative teardown commands need those edges traversable. Migrating them
would change how every ordinary delete in the running app behaves, so instead
this rebinds `on_delete` in memory for the length of one operation and puts it
back in a `finally`.
"""

from contextlib import contextmanager

from django.apps import apps
from django.db.models import ForeignKey
from django.db.models.deletion import CASCADE, DO_NOTHING


# Two `DO_NOTHING` FKs must never become CASCADE, not even for one run.
#
# `JournalEntryConnector` IS the ledger -- its own `account` FK is PROTECT
# precisely so that deleting an account cannot erase journal legs and leave the
# parent entry permanently unbalanced (see journalio/models.py:155). But
# `warehose` and `tax` on that same row are DO_NOTHING. Flipping them would
# reopen that hole from a different direction: a warehouse or tax agency inside
# the cascade would take ledger legs down with it, while `JournalEntry` -- which
# has no FK to either -- survived holding the remaining legs.
#
# Teardown that is *meant* to destroy a ledger deletes those rows explicitly and
# in order (see `companyio.deletion`). It never gets there by cascade, so this
# guard holds for every caller.
LEDGER_GUARDED = {
    ("journalio.JournalEntryConnector", "warehose"),
    ("journalio.JournalEntryConnector", "tax"),
}


@contextmanager
def do_nothing_as_cascade():
    """Make `DO_NOTHING` FKs traversable, then put them back.

    The collector reads `field.remote_field.on_delete` live during `collect()`,
    so rebinding the attribute is enough -- no model needs reloading and no
    migration state changes. Restored in `finally` so a raised `ProtectedError`
    cannot leave the registry rewritten for the rest of the process.

    Yields `(patched, skipped)`. Everything except `LEDGER_GUARDED` is flipped;
    PROTECT and RESTRICT are never touched, so every existing delete guard still
    fires.
    """
    patched, skipped = [], []
    for model in apps.get_models():
        for field in model._meta.local_fields:
            if not isinstance(field, ForeignKey):
                continue
            if field.remote_field.on_delete is not DO_NOTHING:
                continue
            if (model._meta.label, field.name) in LEDGER_GUARDED:
                skipped.append(field)
                continue
            field.remote_field.on_delete = CASCADE
            patched.append(field)
    try:
        yield patched, skipped
    finally:
        for field in patched:
            field.remote_field.on_delete = DO_NOTHING
