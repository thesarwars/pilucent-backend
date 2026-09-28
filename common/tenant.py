"""Per-request tenant (company) context.

The selected company travels on the request as a JWT claim (see the auth
layer) and is resolved into a database id by ``TenantContextMiddleware``. We
stash it in a :class:`contextvars.ContextVar` so that any code deep in the call
stack -- model methods, serializers, services -- can read "which company is
this request scoped to" without having to thread ``request`` everywhere.

``contextvars`` is coroutine-safe, which matters because the app runs under
ASGI/Daphne: each request (HTTP or WebSocket consumer) gets its own context and
cannot leak the company id into a concurrently running request.

This is the single source of truth that powers:
  * ``User.get_active_company()`` / ``User.get_employee()`` (app-level scoping)
  * the Postgres ``app.company_id`` session variable used by RLS policies
"""

from contextlib import contextmanager
from contextvars import ContextVar

# Holds the *database primary key* of the active company, or None when the
# request is not scoped to a company (e.g. login, company selection, or a
# management command).
_current_company_id: ContextVar[int | None] = ContextVar(
    "current_company_id", default=None
)


def set_current_company_id(company_id):
    """Set the active company id for the current context. Returns a reset token."""
    return _current_company_id.set(company_id)


def get_current_company_id():
    """Return the active company id for the current context, or None."""
    return _current_company_id.get()


def reset_current_company_id(token):
    """Restore the previous value using the token returned by ``set``."""
    _current_company_id.reset(token)


def clear_current_company_id():
    """Clear the active company id for the current context."""
    _current_company_id.set(None)


@contextmanager
def use_company_id(company_id):
    """Temporarily scope a block of code to ``company_id``.

    Useful in management commands, Celery tasks, and tests that need to run
    work on behalf of a specific company outside the request/response cycle.
    """
    token = _current_company_id.set(company_id)
    try:
        yield
    finally:
        _current_company_id.reset(token)


@contextmanager
def tenant_unscoped():
    """Run a block with NO active company, so Postgres RLS is permissive.

    Some operations are legitimately *cross-company*: e.g. creating a new
    company seeds that company's default data (chart of accounts, etc.) while
    the request is still scoped to a different company. The RLS ``WITH CHECK``
    would reject those inserts because the new rows' ``company_id`` doesn't
    match the request's ``app.company_id``. Wrapping such work in this context
    clears both the app-level company context and the Postgres ``app.company_id``
    GUC (then restores the prior GUC value), letting the writes through.

    The middleware also clears the GUC at request end, so this is belt-and-
    suspenders even if the restore is skipped.
    """
    from django.db import connection

    token = _current_company_id.set(None)
    is_postgres = connection.vendor == "postgresql"
    prior = None
    try:
        if is_postgres:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.company_id', true)")
                prior = cursor.fetchone()[0]
                cursor.execute("SELECT set_config('app.company_id', '', false)")
        yield
    finally:
        _current_company_id.reset(token)
        if is_postgres:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.company_id', %s, false)", [prior or ""]
                )
