"""The one source of "today" for the BD modules.

`docs/employee-profile.md` §4.5: "today" comes from a single injectable clock,
never `timezone.now()` scattered through modules, so tests can freeze it and
every tenure, eligibility and deadline figure is reproducible.

Resolution order:

1. a date frozen with `frozen()` / `freeze()` -- tests;
2. the `PILUCENT_AS_OF_DATE` environment variable (`YYYY-MM-DD`) -- a dev
   database built around a fixture as-of date;
3. the real date in the project time zone.

Dates handed out here are `datetime.date`; `today_iso()` gives the `YYYY-MM-DD`
string the API and the lexical date comparisons use.
"""

import os
import threading
from contextlib import contextmanager
from datetime import date

from django.utils import timezone

ENV_VAR = "PILUCENT_AS_OF_DATE"

_state = threading.local()


def _parse(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def today():
    frozen_on = getattr(_state, "frozen_on", None)
    if frozen_on is not None:
        return frozen_on
    configured = os.environ.get(ENV_VAR)
    if configured:
        return _parse(configured)
    return timezone.localdate()


def today_iso():
    return today().isoformat()


def freeze(on):
    """Pin today to `on` for this thread until `unfreeze()`."""
    _state.frozen_on = _parse(on)


def unfreeze():
    _state.frozen_on = None


@contextmanager
def frozen(on):
    previous = getattr(_state, "frozen_on", None)
    freeze(on)
    try:
        yield _state.frozen_on
    finally:
        _state.frozen_on = previous
