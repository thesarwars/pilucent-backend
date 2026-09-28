"""Resolve the control accounts the posting engine depends on.

`get_chart_of_account(titles, company)` returns `{title: ChartOfAccount}` and is
called from ~55 places. That contract is unchanged -- but how it *finds* the
accounts is not.

It used to match on `ChartOfAccount.title`. Titles are user-editable, so
renaming "Inventory Asset" silently broke every sale posting: the lookup missed,
the caller got `None`, and the journal leg was skipped with at most a log line.
The `food_beverage` template spells all ten of these differently, so companies on
it could never post at all.

Resolution is now by `system_key` -- a stable identifier the user cannot edit --
with the old title match kept as a fallback for accounts that have not been
backfilled yet. The fallback is deliberately temporary: once every tenant has
its spine keyed, `TITLE_TO_SYSTEM_KEY` is the only path that should matter.

REMOVED accounts are excluded. A soft-deleted control account is not a usable
posting target, and returning one produced entries against a dead account.
"""

from accounts.choices import (
    ChartOfAccountKindChoices,
    ChartOfAccountStatusChoices,
    ChartOfAccountSystemKeyChoices as Key,
)
from accounts.models import ChartOfAccount

from rest_framework.serializers import ValidationError


# The canonical title each system key ships with, and therefore the mapping that
# lets existing callers keep passing titles. Callers were not changed; this is
# what translates their vocabulary into the stable one.
TITLE_TO_SYSTEM_KEY = {
    "Accounts Receivable (A/R)": Key.AR,
    "Accounts Payable (A/P)": Key.AP,
    "Retained Earnings": Key.RETAINED_EARNINGS,
    "Payroll Liabilities": Key.PAYROLL_LIABILITIES,
    "Federal Taxes (941/943/944)": Key.FEDERAL_TAX_941,
    "Federal Unemployment (940)": Key.FEDERAL_UNEMPLOYMENT_940,
    "Inventory Asset": Key.INVENTORY_ASSET,
    "Undeposited Funds": Key.UNDEPOSITED_FUNDS,
    "Opening Balance Equity": Key.OPENING_BALANCE_EQUITY,
    "Sales Tax Payable": Key.SALES_TAX_PAYABLE,
    "Cost of Goods Sold (COGS)": Key.COGS,
    "Sales of Product Income": Key.SALES_OF_PRODUCT_INCOME,
    "Service": Key.SERVICE,
    "Other Miscellaneous Expense": Key.OTHER_MISC_EXPENSE,
    "Sales Discounts": Key.SALES_DISCOUNTS,
    "Shipping Income": Key.SHIPPING_INCOME,
}

SYSTEM_KEY_TO_TITLE = {key: title for title, key in TITLE_TO_SYSTEM_KEY.items()}

# Titles an account may already carry for a given key on tenants seeded before
# the canonical name existed. Used by the backfill so an existing account is
# renamed and keyed, rather than left beside a freshly created duplicate --
# two accounts for one concept is how the wrong one gets picked.
LEGACY_TITLES = {
    Key.SALES_DISCOUNTS: ["Discounts Given"],
}


def get_chart_of_account(account_titles, company):
    """`{requested title: ChartOfAccount}` for `company`.

    A requested title that maps to a system key resolves by that key, so a
    renamed account is still found. Anything else -- and any control account not
    yet backfilled -- falls back to matching on title.
    """
    titles = list(account_titles)
    resolved = {}

    live = ChartOfAccount.objects.filter(company=company).exclude(
        status=ChartOfAccountStatusChoices.REMOVED
    )

    # Preferred path: stable key.
    title_by_key = {
        TITLE_TO_SYSTEM_KEY[title]: title
        for title in titles
        if title in TITLE_TO_SYSTEM_KEY
    }
    if title_by_key:
        for account in live.filter(system_key__in=list(title_by_key)):
            resolved[title_by_key[account.system_key]] = account

    # Fallback: title match, for non-control accounts and un-backfilled tenants.
    remaining = [title for title in titles if title not in resolved]
    if remaining:
        for account in live.filter(title__in=remaining):
            resolved[account.title] = account

    return resolved


def get_account_by_system_key(system_key, company):
    """The single account for `system_key`, or None.

    Preferred entry point for new code -- no title involved at any step.
    """
    return (
        ChartOfAccount.objects.filter(company=company, system_key=system_key)
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .first()
    )


# Keys that are NOT part of the spine every company is seeded with, because the
# account is created the first time the thing that needs it happens. Seeding
# them anyway would put an account on every chart that most tenants never use,
# and in this case one whose mere existence is a claim about the books:
# a Reconciliation Discrepancies balance says the ledger and the bank disagreed
# by that much and nobody established why.
ON_DEMAND_KEYS = frozenset(
    {
        Key.RECONCILIATION_DISCREPANCIES,
        # Only 15 of 20 templates ship a "Payroll Liabilities" row, so demanding
        # it at onboarding would report 5 industries as unable to post when they
        # can. It is needed only when a deduction reaches no configured account,
        # and is created at that moment.
        Key.PAYROLL_LIABILITIES,
        # Seeded by 19 of 20 templates and present on ~33 of 60 companies, and
        # deliberately NOT auto-created -- `TAX_LIABILITY_AUTO_CREATE_CHART`
        # limits that to MN_PAID_LEAVE. Keying them makes a rename safe and
        # makes COA-153 refuse deactivation; it does not change what happens
        # when the account genuinely does not exist.
        Key.FEDERAL_TAX_941,
        Key.FEDERAL_UNEMPLOYMENT_940,
    }
)


def missing_system_keys(company):
    """System keys this company has no live account for.

    Empty means the company can post. Intended for the onboarding check, so a
    company fails loudly at creation rather than silently at its first invoice.

    `ON_DEMAND_KEYS` are excluded: they are not required to post, so their
    absence is the normal state and not a seeding failure.
    """
    present = set(
        ChartOfAccount.objects.filter(company=company, system_key__isnull=False)
        .exclude(status=ChartOfAccountStatusChoices.REMOVED)
        .values_list("system_key", flat=True)
    )
    return [
        key
        for key in Key.values
        if key not in present and key not in ON_DEMAND_KEYS
    ]


def derive_account_kind(account_type):
    """The ChartOfAccountKindChoices value an account type belongs to, or None.

    `kind` is derived from the account type's parent -- the root category, which
    is one of the five account kinds. Two shapes used to slip through:

    * a **detail-level** category (a grandchild) has a parent that is not a
      root, so this produced a kind like "OTHER CURRENT LIABILITIES" -- a value
      outside ChartOfAccountKindChoices, which Django does not enforce on
      save(). Such an account matches no bucket on any statement and silently
      disappears from the balance sheet;
    * a **root** category has no parent at all, so dereferencing it raised
      AttributeError and returned a 500.
    """
    parent = getattr(account_type, "parent", None)
    kind = parent.title.upper() if parent is not None else ""
    return kind if kind in ChartOfAccountKindChoices.values else None


def validate_detail_type_belongs_to(account_type, detail_type):
    """Reject a detail type that is not a child of the chosen account type.

    The two fields are independent FKs into the same category tree, and nothing
    tied them together: any active chart-of-account category was accepted as the
    detail type of any account type. "Bank" under "Expenses", "Payroll
    Liabilities" under "Income" -- all storable.

    That is not cosmetic. Reports group by one or the other, and the payroll and
    tax modules resolve their posting targets by detail type NAME, so a
    mismatched pair silently routes postings to an account sitting on the wrong
    side of the statements. It is also the same inconsistency the seed validator
    exists to catch in the fixtures -- 486 rows of it -- while the API stayed
    free to create more.

    Only checked when both are present; the caller decides which half to resolve
    from an existing instance on a partial update.
    """
    if account_type is None or detail_type is None:
        return
    if detail_type.parent_id == account_type.pk:
        return
    raise ValidationError(
        {
            "detail_type_slug": (
                f"{detail_type.title!r} is not a detail type of "
                f"{account_type.title!r}. Choose a detail type listed under the "
                "account type you selected."
            )
        }
    )


def root_kind_of(category, max_depth=6):
    """The root category's title, uppercased -- i.e. the `kind` it implies.

    Walks all the way up, which is the whole point. The taxonomy is three deep
    (`Expenses -> Other Expenses -> Interest Paid`), so stopping at the parent
    reports `OTHER EXPENSES` for an account correctly marked `EXPENSES`. There
    is no `OTHER EXPENSES` kind -- `ChartOfAccountKindChoices` has five values,
    all of them roots -- so a one-level walk cannot be right for anything nested
    deeper than one level, and it is the accounts typed against a depth-2 node
    that most need checking.

    Returns None for a null category or a cycle.
    """
    node = category
    for _ in range(max_depth):
        if node is None:
            return None
        if node.parent_id is None:
            return (node.title or "").upper()
        node = node.parent
    return None


def resolve_taxonomy_category(title, parent=None):
    """Resolve a seeded account-type / detail-type category by title.

    Seeding matched `Category.objects.filter(title=...)` with no other
    constraint. `Category` carries a nullable `company` and is tenant-writable
    through the categories API, and `BaseModelWithUID.Meta.ordering` is
    `("-created_at",)`, so `.first()` returns the NEWEST match: any tenant could
    create a category named "Bank" and every company onboarded afterwards would
    have its control accounts typed against that row instead of the shipped one.

    The shipped taxonomy is global -- all of it has `company` NULL, and its
    titles are unique -- so restricting to that set both closes the hole and
    leaves correct seeding byte-identical.

    Passing `parent` additionally enforces that a detail type really belongs to
    its account type, which is the same pairing the API now validates and the
    seed validator asserts over the fixtures.
    """
    from categoryio.choicess import CategoryKindChoices

    from categoryio.models import Category

    queryset = Category.objects.filter(
        title=title,
        kind=CategoryKindChoices.CHART_OF_ACCOUNT,
        company__isnull=True,
    )
    if parent is not None:
        queryset = queryset.filter(parent=parent)
    return queryset.first()


def assert_account_identity_is_free(company, title=None, code=None, exclude_pk=None):
    """Reject a title or code already taken by another live account.

    `create()` checked this; `update()` did not, so an account could be *renamed*
    onto another's title. That is the failure mode the whole `system_key` change
    exists to survive -- two accounts sharing a name means a title lookup picks
    one arbitrarily -- and until every caller resolves by key, minting the
    collision is still worth refusing.

    Raises with the offending field named rather than a bare "already exists", so
    the client can point at the input that has to change.

    `exclude_pk` is the row being edited: an account keeping its own title is not
    colliding with itself.
    """
    live = ChartOfAccount.objects.filter(company=company).exclude(
        status=ChartOfAccountStatusChoices.REMOVED
    )
    if exclude_pk is not None:
        live = live.exclude(pk=exclude_pk)

    errors = {}
    # Case-insensitive, to match the database. `unique_title_per_company_ci` is
    # on `Upper(title)`, so a plain `=` here passed a rename onto "OFFICE
    # SUPPLIES" while "Office Supplies" was live -- and the constraint then
    # raised an IntegrityError, which nothing converts, so the client got a bare
    # 500 with no field named instead of this 400. The guard and the index have
    # to agree on what "already exists" means.
    if title and live.filter(title__iexact=title).exists():
        errors["title"] = f"An account named {title!r} already exists."
    if code and live.filter(code=code).exists():
        errors["code"] = f"Code {code!r} is already used by another account."
    if errors:
        raise ValidationError(errors)


def resolve_import_account_kind(account_type):
    """The kind a CSV-imported account should carry, or None if unusable.

    The API and the seeds treat `account_type` as a depth-1 node -- "Bank",
    "Expense" -- and derive the kind from its root parent. The CSV template
    shipped to customers uses the opposite vocabulary: its "Account Type" column
    lists the ROOTS ("Assets", "Liabilities") and its "Detail Type" column lists
    the depth-1 nodes. Both are internally consistent, so both are accepted here.

    What is NOT acceptable is a depth-2 detail type in that column, and that was
    the whole defect. The importer derived kind as
    `account_type.parent.title.upper()` with no check, so a customer typing a
    QuickBooks detail type -- "Credit Card", "Checking" -- got an account whose
    kind was "CREDIT CARDS": a value outside ChartOfAccountKindChoices, which
    Django does not enforce on save(). Such an account matches no bucket on any
    statement, so it and every line posted to it vanish from the balance sheet
    and the P&L, and the first automatic posting against it raises TypeError
    because `get_debit_or_credit` returns None for an unknown kind.

    That is on the data-migration path, which is the moment a customer's entire
    ledger is established, and the validator reported those rows READY.
    """
    if account_type is None:
        return None

    # Template vocabulary: the root category IS the kind.
    if getattr(account_type, "parent_id", None) is None:
        kind = (account_type.title or "").upper()
        return kind if kind in ChartOfAccountKindChoices.values else None

    # API/seed vocabulary: a depth-1 node, whose parent names the kind.
    return derive_account_kind(account_type)


# Spec BLZ-FIN-COA-SPEC-001 s9.2 / COA-130: "Maximum depth is five levels
# including the top parent." This was 10 -- chosen when the number only had to
# terminate a cycle walk promptly and be larger than any legitimate chart, before
# there was a specification saying what the limit is.
#
# Safe to tighten: production's deepest chart is TWO levels. Measured across all
# 3,759 live accounts -- 3,664 at depth 1, 95 at depth 2, none deeper. So no
# existing account is affected and nothing has to be re-parented first.
#
# It is still the cycle-walk bound as well as the policy limit, which is why the
# walk allows MAX_ACCOUNT_DEPTH + 1 steps: an already-corrupt chain has to be
# detectable, not merely refused.
MAX_ACCOUNT_DEPTH = 5


def assert_parent_is_not_a_cycle(account, parent):
    """Reject a parent that would put `account` beneath itself.

    Only direct self-parenting was checked, so two ordinary PATCHes --
    `A.parent = B`, then `B.parent = A` -- built a cycle. Both accounts and
    everything under them then vanished from the account tree while still
    appearing in the flat list, the journal and the statements, so the tree
    stopped being a partition of the chart. Neither could be deleted afterwards
    (each is the other's parent) and neither could be re-parented to the top,
    because `parent_uid` rejected null. There was no API sequence that recovered
    it.

    Walks up from the proposed parent rather than comparing one link, and stops
    at a depth cap so an already-corrupt row cannot make the walk itself loop.
    """
    if parent is None or account is None or account.pk is None:
        return

    seen = set()
    current = parent
    for _ in range(MAX_ACCOUNT_DEPTH + 1):
        if current is None:
            return
        if current.pk == account.pk:
            raise ValidationError(
                {
                    "parent_uid": (
                        f"{parent.title!r} already sits beneath "
                        f"{account.title!r}, so this would make the account its "
                        "own ancestor."
                    )
                }
            )
        if current.pk in seen:
            # The chain above the proposed parent is already circular.
            raise ValidationError(
                {
                    "parent_uid": (
                        f"{parent.title!r} is part of an existing parent loop and "
                        "cannot be used until that is untangled."
                    )
                }
            )
        seen.add(current.pk)
        current = current.parent

    raise ValidationError(
        {
            "parent_uid": (
                f"{parent.title!r} is nested more than {MAX_ACCOUNT_DEPTH} levels "
                "deep. Move it nearer the top before parenting to it."
            )
        }
    )


def detail_type_is_under(account_type, detail_type, max_depth=6):
    """Whether `detail_type` sits anywhere beneath `account_type`.

    DESCENDANT, not child, and the difference is load-bearing. The API puts a
    depth-1 node in `account_type` and its direct child in `detail_type`, so
    "child" describes it. The CSV template shipped to customers puts a ROOT in
    the Account Type column and mixes depth-1 and depth-2 nodes in the Detail
    Type column -- so 95 of its 157 documented pairs are grandchildren, and
    enforcing "child" there would reject the majority of imports that follow our
    own reference sheet.

    A pair naming the same category twice is accepted: the sheet lists
    ("Equity", "Equity") and ("Income", "Income"), which is how it expresses an
    account typed at the root itself.
    """
    if account_type is None or detail_type is None:
        return True
    if account_type.pk == detail_type.pk:
        return True

    node = detail_type
    for _ in range(max_depth):
        node = node.parent
        if node is None:
            return False
        if node.pk == account_type.pk:
            return True
    return False
