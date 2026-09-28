import logging

from accounts.managers import MONEY_ACCOUNT_TYPE_TITLES
from accounts.choices import ChartOfAccountStatusChoices
from accounts.models import ChartOfAccount


from common.django_rest.helpers.chart_of_account_helpers import (
    resolve_taxonomy_category,
    SYSTEM_KEY_TO_TITLE,
    TITLE_TO_SYSTEM_KEY,
    missing_system_keys,
)

from ..helpers.chart_of_accounts import chart_of_accounts


logger = logging.getLogger(__name__)


def template_for(company_kind):
    """The seed rows for a company kind, or an empty list."""
    for block in chart_of_accounts:
        if block["kind"] == company_kind:
            return block["chart_of_accounts"]
    return []


def create_control_account(company, system_key, company_setting=None):
    """Create one missing control account from the company's industry template.

    Taking the row from the template rather than inventing one means the account
    lands with the account_type, detail_type and code a company onboarded today
    would get. Returns the account, or None if it could not be built.
    """
    title = SYSTEM_KEY_TO_TITLE[system_key]
    row = next(
        (r for r in template_for(company.kind) if r.get("title") == title), None
    )
    if row is None:
        logger.error(
            "control account %s (%r) is not in the %s template -- company=%s "
            "cannot post documents that need it",
            system_key,
            title,
            company.kind,
            company.pk,
        )
        return None

    account_type = resolve_taxonomy_category(row["account_type_title"])
    if account_type is None:
        logger.error(
            "control account %s for company=%s: account_type %r is not in the "
            "category tree",
            system_key,
            company.pk,
            row["account_type_title"],
        )
        return None

    if company_setting is None:
        company_setting = company.companysetting_set.first()

    return ChartOfAccount.objects.create(
        title=row["title"],
        code=row["code"],
        status=ChartOfAccountStatusChoices.ACTIVE,
        kind=account_type.parent.title.upper(),
        account_type=account_type,
        detail_type=resolve_taxonomy_category(
            row["detail_type_title"], parent=account_type
        ),
        system_key=system_key,
        is_fixed=True,
        # Stamped at seed time from the same titles `ChartOfAccountQuerySet.money()`
        # matches on. Migration 0047 backfilled the flag once and nothing set it
        # afterwards, so every company created since had it False on every Bank
        # and Credit Card it owns -- and a client keying a Reconcile button on
        # the flag saw none of them. `money()` still carries a title fallback, so
        # this is belt and braces rather than the only control.
        is_money_account=account_type.title in MONEY_ACCOUNT_TYPE_TITLES,
        currency=getattr(company_setting, "home_currency", None) or "USD",
        company=company,
    )


def ensure_control_accounts(company, company_setting=None):
    """Create whatever the control-account spine is missing. Returns what remains.

    Seeding is not reliable: a template row whose account_type is not in the
    category tree is skipped entirely, and a production backfill found **106
    control accounts missing across 28 of 60 companies** -- five of them missing
    all ten, which meant those tenants could not post a single document
    correctly. It failed silently every time.

    So rather than only asserting, this repairs. Raising instead is not an
    option: this runs in a `post_save` and company creation is not wrapped in a
    transaction, so raising would leave a committed company with a broken chart
    -- strictly worse than what it replaced.
    """
    missing = missing_system_keys(company)
    if not missing:
        return []

    logger.warning(
        "company=%s (%s) finished seeding without %d control account(s): %s -- "
        "creating them from the template",
        company.pk,
        company.kind,
        len(missing),
        ", ".join(missing),
    )
    for system_key in missing:
        create_control_account(company, system_key, company_setting)

    still_missing = missing_system_keys(company)
    if still_missing:
        logger.error(
            "company=%s (%s) CANNOT POST: no account for %s. Documents needing "
            "these will post one-sided entries.",
            company.pk,
            company.kind,
            ", ".join(still_missing),
        )
    return still_missing


def create_chart_of_accounts(instance, company_setting):
    """Seed a new company's chart of accounts from its industry template.

    Two things worth knowing about what this does *not* do:

    * It does not raise on a bad template row. Roughly 30% of seed rows still
      reference an account_type/detail_type pair that does not exist
      (`manage.py validate_chart_of_account_seeds`), so raising would block
      onboarding for every industry. Instead every skipped or untyped row is now
      **logged** -- it used to fail in complete silence, which is why the damage
      went unnoticed. Turn these into hard failures once the validator is clean.
    * It does not fix the templates. That is separate work, tracked by the
      validator's baseline.
    """
    data = []
    for chart_of_account in chart_of_accounts:
        if instance.kind == chart_of_account["kind"]:
            data = chart_of_account["chart_of_accounts"]
            break

    if not data:
        logger.error(
            "chart of accounts: no seed template for company kind %s (company=%s); "
            "this company starts with an empty chart and cannot post",
            instance.kind,
            instance.pk,
        )
        return

    for item in data:
        account_type = resolve_taxonomy_category(item["account_type_title"])
        if not account_type:
            # The row is dropped entirely -- the account is never created.
            logger.error(
                "chart of accounts: skipping %r for company=%s -- account_type %r "
                "does not exist in the category tree",
                item["title"],
                instance.pk,
                item["account_type_title"],
            )
            continue

        detail_type = resolve_taxonomy_category(
            item["detail_type_title"], parent=account_type
        )
        if not detail_type:
            # The account is created but untyped, and silently drops out of
            # every report that filters on detail_type (payroll tax/wage, the
            # balance-sheet payroll carve-out, the sales-tax lookup).
            logger.warning(
                "chart of accounts: %r for company=%s has no detail_type -- %r "
                "does not exist in the category tree",
                item["title"],
                instance.pk,
                item["detail_type_title"],
            )

        parent = None
        if parent_title := item.get("parent"):
            # Scoped to this company. Unscoped, seeding could attach a brand new
            # company's account to a DIFFERENT tenant's account as its parent.
            parent = ChartOfAccount.objects.filter(
                company=instance, title=parent_title
            ).first()

        ChartOfAccount.objects.create(
            parent=parent,
            title=item["title"],
            code=item["code"],
            status=ChartOfAccountStatusChoices.ACTIVE,
            kind=account_type.parent.title.upper(),
            account_type=account_type,
            detail_type=detail_type,
            # Stamped from the template's canonical title. After this the key is
            # what the posting engine resolves on, so the user is free to rename
            # the account without breaking anything.
            system_key=TITLE_TO_SYSTEM_KEY.get(item["title"]),
            is_fixed=True,
            is_money_account=account_type.title in MONEY_ACCOUNT_TYPE_TITLES,
            currency=company_setting.home_currency,
            company=instance,
        )

    # Last line of defence. A company that finishes onboarding without its full
    # spine cannot post, and until now discovered that at its first invoice.
    ensure_control_accounts(instance, company_setting)
