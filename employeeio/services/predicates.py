"""One predicate per question (doc §1.7). The roster badge and the profile
panel both ask these; neither reimplements them."""

from rulebookio.book import RuleBookError

from .tax import project


class LiabilityUndetermined(Exception):
    """The rule book cannot answer for this date. Never read as "no liability"."""


def has_tax_liability(employee, as_of=None, book=None):
    """Is there tax to withhold? Runs threshold -> employment exemption -> slab
    walk on the employee's own category, from the rule book (§3.3).

    False when no salary structure is in force: with no pay there is nothing to
    withhold, and the missing structure is its own hard block. Raises
    `LiabilityUndetermined` when the rule book has no answer, so a caller cannot
    mistake "unknown" for "nil" -- that is how the e-TIN item used to vanish.
    """
    try:
        projection = project(employee, as_of=as_of, book=book)
    except RuleBookError as exc:
        raise LiabilityUndetermined(str(exc)) from exc
    return projection.available and projection.liability > 0


def blocks_payroll(employee, as_of=None, book=None):
    from .compliance import evaluate

    return bool(evaluate(employee, as_of=as_of, book=book).blocks)
