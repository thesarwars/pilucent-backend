"""The recurring generation job — the thing that actually makes templates recur.

Until this existed, ``next_run_date`` was computed and displayed but nothing ever
acted on it: ``RecurringOccurrence`` had zero write sites, so a template only
ever produced a document when a human pressed "Use". This module is the driver
that turns the pure scheduling engine in :mod:`.scheduling` into real documents.

Design points worth knowing:

**Dates are company-local.** A document dated the 1st has to be the 1st in the
company's own books, not on the server. Each company's ``time_zone`` decides its
own "today"; the Django ``TIME_ZONE`` is only the fallback.

**Catch-up is bounded.** Missed occurrences are fired in order, but only back to
``catch_up_days``. Anything older is recorded as ``SKIPPED`` with a reason rather
than silently dropped, so a template that lay dormant for months cannot dump a
year of documents into the ledger in one run — while nothing disappears without
a trace either.

**Idempotency is the database's job.** ``unique(template, occurrence_date)`` on
``RecurringOccurrence`` is what makes a retried or overlapping run safe; this
module leans on it via ``get_or_create`` rather than trying to be clever.

**A failure never blocks the schedule.** A failed firing is recorded as
``FAILED`` with the error and the schedule still advances, so one broken
occurrence cannot wedge every future one behind it. The row stays visible and
re-runnable.
"""

import json
import logging
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.conf import settings
from django.core.exceptions import FieldError
from django.db import transaction
from django.utils import timezone

from journalio.models import JournalEntry

from ..choices import (
    RecurringAcceptanceStatusChoices,
    RecurringOccurrenceStatusChoices,
    RecurringTemplateStatusChoices,
    RecurringTemplateTypeChoices,
    RecurringWhenToChargeChoices,
)
from purchaseio.models import ExpenseConnector

from ..models import RecurringOccurrence, RecurringTemplate
from . import scheduling
from .generation import generate_from_template

logger = logging.getLogger(__name__)

# How far back a missed occurrence is still worth firing. Older ones are recorded
# as SKIPPED instead, so an outage or a long-dormant template can't post months
# of back-dated documents in a single run.
DEFAULT_CATCH_UP_DAYS = 30

# Hard stop on how many occurrences one template may fire in a single run. Guards
# against a pathological schedule (or a bug in the date math) looping forever.
MAX_OCCURRENCES_PER_RUN = 100


@lru_cache(maxsize=1)
def _zones_by_city():
    """``{"Dhaka": "Asia/Dhaka", …}`` for city names that map to exactly one zone."""
    seen = {}
    for zone in available_timezones():
        city = zone.rsplit("/", 1)[-1]
        seen[city] = None if city in seen else zone
    return {city: zone for city, zone in seen.items() if zone}


def resolve_timezone(raw):
    """Best-effort :class:`ZoneInfo` from whatever ``Company.time_zone`` holds.

    That column is free-text and production contains three different shapes,
    only one of which ``ZoneInfo`` accepts directly:

    * a JSON blob from the timezone picker —
      ``{"value": "Pacific/Honolulu", "label": "(GMT-10:00) Hawaii", …}``
    * a bare IANA name — ``"Asia/Dhaka"``
    * a bare city name — ``"Dhaka"``

    Getting this wrong is not cosmetic: silently falling back to the server's
    ``TIME_ZONE`` put a Hawaii company (UTC-10) on Dhaka time (UTC+6), a 20-hour
    swing that dates a generated document a full day out.
    """
    if not raw:
        return ZoneInfo(settings.TIME_ZONE)

    candidate = str(raw).strip()
    if candidate.startswith("{"):
        try:
            candidate = (json.loads(candidate).get("value") or "").strip()
        except (ValueError, AttributeError):
            candidate = ""

    if candidate:
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass

        # A bare city ("Dhaka"), but only when it is unambiguous.
        zone = _zones_by_city().get(candidate)
        if zone:
            return ZoneInfo(zone)

    logger.warning(
        "Unusable company time_zone %r; falling back to %s. Dates for this "
        "company may land on the wrong calendar day.",
        raw,
        settings.TIME_ZONE,
    )
    return ZoneInfo(settings.TIME_ZONE)


def company_today(company):
    """Today's date in ``company``'s own timezone.

    Which calendar day an occurrence lands on decides the document's date, so
    this has to follow the company's books rather than the server's clock.
    """
    return timezone.now().astimezone(
        resolve_timezone(getattr(company, "time_zone", None))
    ).date()


def _acting_user(template):
    """The user a generated document is attributed to.

    A scheduled firing has no request user, so it is attributed to whoever
    created the template. The importers only need ``get_employee()``, and they
    already tolerate ``None``.
    """
    employee = template.created_by
    return getattr(employee, "user", None) if employee else None


def _is_due(template, occurrence_date, today):
    """Has this occurrence reached the day it should be acted on?

    Scheduled templates fire ``create_days_in_advance`` early; reminder templates
    surface ``remind_days_before`` early. Both offsets already live in the
    scheduling engine.
    """
    if template.template_type == RecurringTemplateTypeChoices.REMINDER:
        return scheduling.reminder_date(template, occurrence_date) <= today
    return scheduling.creation_trigger_date(template, occurrence_date) <= today


def _advance(template, occurrence_date, *, counts_toward_total):
    """Move the template past ``occurrence_date`` and persist its run state.

    ``counts_toward_total`` is False for skipped/failed firings: ``AFTER_COUNT``
    means "produce N documents", so an occurrence that produced nothing must not
    consume one of them.
    """
    template.previous_run_date = occurrence_date
    if counts_toward_total:
        template.occurrences_generated = (template.occurrences_generated or 0) + 1

    template.next_run_date = scheduling.advance_run_date(template, occurrence_date)
    fields = ["previous_run_date", "occurrences_generated", "next_run_date", "updated_at"]

    if template.next_run_date is None:
        # The schedule is exhausted (end date passed or the count is complete).
        template.status = RecurringTemplateStatusChoices.ENDED
        fields.append("status")

    template.save(update_fields=fields)


def _link_document(occurrence, document):
    """Point the occurrence at whatever the generator produced.

    The three generators return three different things: a ``Purchase`` (bill,
    cheque), a ``Sale`` (estimate), or an ``Expense`` — and an Expense has **no**
    direct FK to its backing Purchase, only an ``ExpenseConnector`` row. So the
    purchase has to be looked up rather than read off the object.
    """
    if document is None:
        return

    model = document._meta.model_name
    if model == "sale":
        occurrence.generated_sale = document
    elif model == "purchase":
        occurrence.generated_purchase = document
    elif model == "creditnote":
        occurrence.generated_credit_note = document
    elif model == "bankdeposit":
        occurrence.generated_deposit = document
    elif model == "expense":
        connector = ExpenseConnector.objects.filter(expense=document).first()
        occurrence.generated_purchase = connector.purchase if connector else None
    else:
        logger.warning(
            "Recurring occurrence %s: generator returned an unlinkable %s.",
            occurrence.uid,
            model,
        )


def _log_document_balance(template, occurrence_date, document):
    """Assert the journal this firing produced actually balances.

    Nothing was checking. `post_sale_document` gained a balance check with R5,
    but recurring generation does not use it -- it drives the
    `datamigrationio` importer services instead, a separate posting
    implementation. So a template whose invoice posted income and inventory but
    no receivable produced an entry short by the whole invoice total, every
    night, and the only trace was a number in a report nobody was running.

    Deliberately does not raise. The document is already committed by the time
    this can be checked, and refusing to record the occurrence would make the
    same broken invoice regenerate tomorrow on top of today's. Loud is the
    requirement; blocking is not.
    """
    if document is None:
        return

    for entry in _entries_for(document):
        rows = entry.journalentryconnector_set.all()
        debit = sum(Decimal(str(row.debit or 0)) for row in rows)
        credit = sum(Decimal(str(row.credit or 0)) for row in rows)
        if debit == credit:
            logger.info(
                "Recurring template %s (%s) %s: journal %s balances at %s "
                "across %s lines.",
                template.uid, template.txn_type, occurrence_date,
                entry.pk, debit, len(rows),
            )
            continue
        logger.error(
            "Recurring template %s (%s) fired for %s and wrote an UNBALANCED "
            "journal entry %s -- debit %s vs credit %s (out by %s) across %s "
            "lines. The document is committed; the ledger is short.",
            template.uid, template.txn_type, occurrence_date,
            entry.pk, debit, credit, debit - credit, len(rows),
        )


def _entries_for(document):
    """Journal entries written for `document`, whatever kind it is.

    `JournalEntry` points at its document through per-kind FKs, so there is no
    single field to filter on -- try each one the generators can return.
    """
    lookups = {
        "sale": "sale",
        "purchase": "purchase",
        "creditnote": "credit_note",
        "bankdeposit": "bank_deposit",
        "expense": "expense",
    }
    field = lookups.get(document._meta.model_name)
    if field is None:
        return JournalEntry.objects.none()
    try:
        return JournalEntry.objects.filter(**{field: document}).prefetch_related(
            "journalentryconnector_set"
        )
    except FieldError:
        # The FK is named something else on this model; a missing check is
        # better than a firing that raises on its way out.
        logger.warning(
            "Recurring: cannot locate journal entries for a %s to balance-check "
            "it.", document._meta.model_name,
        )
        return JournalEntry.objects.none()


def fire_occurrence(template, occurrence_date, *, user=None):
    """Materialize one occurrence. Returns the ``RecurringOccurrence``.

    Safe to call twice for the same date: the unique constraint means the second
    call finds the existing row and does nothing, which is what makes a retried
    run harmless.
    """
    occurrence, created = RecurringOccurrence.objects.get_or_create(
        template=template,
        occurrence_date=occurrence_date,
        defaults={
            "company": template.company,
            "status": RecurringOccurrenceStatusChoices.GENERATED,
        },
    )
    if not created:
        return occurrence

    # A reminder template never posts anything — surfacing the date IS the
    # deliverable.
    if template.template_type == RecurringTemplateTypeChoices.REMINDER:
        occurrence.status = RecurringOccurrenceStatusChoices.REMINDED
        occurrence.reminded_at = timezone.now()
        occurrence.save(update_fields=["status", "reminded_at", "updated_at"])
        return occurrence

    try:
        document = generate_from_template(
            template,
            user if user is not None else _acting_user(template),
            template.company,
            transaction_date=occurrence_date,
        )
    except Exception as exc:
        # Record and move on. Wedging every future occurrence behind one broken
        # firing would be worse than a visible, re-runnable failure.
        logger.exception(
            "Recurring template %s failed to fire for %s.", template.uid, occurrence_date
        )
        occurrence.status = RecurringOccurrenceStatusChoices.FAILED
        occurrence.error_detail = str(exc)[:2000]
        occurrence.save(update_fields=["status", "error_detail", "updated_at"])
        return occurrence

    _link_document(occurrence, document)
    _log_document_balance(template, occurrence_date, document)
    occurrence.status = RecurringOccurrenceStatusChoices.GENERATED
    occurrence.resolved_at = timezone.now()
    occurrence.save(
        update_fields=[
            "generated_sale",
            "generated_purchase",
            "generated_deposit",
            "generated_credit_note",
            "status",
            "resolved_at",
            "updated_at",
        ]
    )
    return occurrence


def _skip(template, occurrence_date, reason):
    """Record an occurrence that was deliberately not fired."""
    occurrence, created = RecurringOccurrence.objects.get_or_create(
        template=template,
        occurrence_date=occurrence_date,
        defaults={
            "company": template.company,
            "status": RecurringOccurrenceStatusChoices.SKIPPED,
            "error_detail": reason,
        },
    )
    return occurrence


def run_template(template, *, today=None, catch_up_days=DEFAULT_CATCH_UP_DAYS, user=None):
    """Fire every occurrence ``template`` owes up to ``today``.

    Returns a per-status count dict. Occurrences are processed oldest-first so
    document numbering and run history stay in chronological order.
    """
    if template.status != RecurringTemplateStatusChoices.ACTIVE:
        return {}
    if not scheduling.is_schedulable(template):
        return {}

    today = today or company_today(template.company)

    # A charge-on-acceptance template that reached its start date without an
    # acceptance can never produce anything: firing it would charge a customer
    # who never agreed, which is the whole point of the setting. Stop it rather
    # than record a FAILED occurrence every single run.
    if (
        template.when_to_charge == RecurringWhenToChargeChoices.ACCEPT
        and template.acceptance_status != RecurringAcceptanceStatusChoices.ACCEPTED
    ):
        if template.next_run_date and template.next_run_date <= today:
            template.status = RecurringTemplateStatusChoices.EXPIRED
            template.save(update_fields=["status", "updated_at"])
            logger.info(
                "Recurring template %s expired: start date reached with no "
                "customer acceptance.",
                template.uid,
            )
        return {}

    cutoff = today - timedelta(days=catch_up_days)
    counts = {}

    for _ in range(MAX_OCCURRENCES_PER_RUN):
        occurrence_date = template.next_run_date
        if occurrence_date is None or not _is_due(template, occurrence_date, today):
            break

        if occurrence_date < cutoff:
            _skip(
                template,
                occurrence_date,
                f"Older than the {catch_up_days}-day catch-up window; not fired "
                "automatically. Use the template manually if it is still wanted.",
            )
            status = RecurringOccurrenceStatusChoices.SKIPPED
            _advance(template, occurrence_date, counts_toward_total=False)
        else:
            with transaction.atomic():
                occurrence = fire_occurrence(template, occurrence_date, user=user)
            status = occurrence.status
            _advance(
                template,
                occurrence_date,
                counts_toward_total=status
                in (
                    RecurringOccurrenceStatusChoices.GENERATED,
                    RecurringOccurrenceStatusChoices.REMINDED,
                ),
            )

        counts[status] = counts.get(status, 0) + 1
    else:
        logger.warning(
            "Recurring template %s hit the %s-occurrence per-run cap; the rest "
            "will be picked up on the next run.",
            template.uid,
            MAX_OCCURRENCES_PER_RUN,
        )

    return counts


def due_templates(company=None):
    """Active, scheduled templates that have a next run date."""
    queryset = RecurringTemplate.objects.filter(
        status=RecurringTemplateStatusChoices.ACTIVE,
        next_run_date__isnull=False,
    ).exclude(template_type=RecurringTemplateTypeChoices.UNSCHEDULED)
    if company is not None:
        queryset = queryset.filter(company=company)
    return queryset.select_related("company", "created_by")


def run_due(company=None, *, today=None, catch_up_days=DEFAULT_CATCH_UP_DAYS, user=None):
    """Run every due template. Returns a summary dict.

    One template's failure never stops the run — each is isolated so a single bad
    template cannot stall everyone else's schedules.
    """
    summary = {"templates_examined": 0, "templates_fired": 0}

    for template in due_templates(company).iterator():
        summary["templates_examined"] += 1
        try:
            counts = run_template(
                template, today=today, catch_up_days=catch_up_days, user=user
            )
        except Exception:
            logger.exception(
                "Recurring template %s could not be processed; continuing.",
                template.uid,
            )
            summary["errors"] = summary.get("errors", 0) + 1
            continue

        if counts:
            summary["templates_fired"] += 1
            for status, count in counts.items():
                summary[status] = summary.get(status, 0) + count

    return summary
