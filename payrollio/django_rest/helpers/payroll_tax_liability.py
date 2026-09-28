"""Build the "Tax liability" report.

Unlike the other two payroll reports, this one is organised by **filing group**
rather than by employee: what a company owes the IRS on a 941 is one number, and
the lines beneath it exist to explain that number. The grouping is not invented
here -- `payroll_journal_mappings` already owns it, because the journal poster
credits the same buckets, and the Tax Center reads them too.

Shape returned::

    {
      "columns": [{"key": "tax_type", ...}],
      "rows": [{"key", "label", "is_group", "tax_amount", "tax_paid", "tax_owed"}]
    }

Rows are flat, group header followed by its members, so the table renders
top to bottom without recursion.

**On "Tax paid": payments are recorded per group, not per tax line.**
`TaxCenterPayMethod` has no tax-type column at all -- a payment carries an
amount, a liability chart account and a free-text `liability_period`. So the
attributable unit is the group, and a member line's paid figure is a pro-rata
share of its group's, which keeps the column summing correctly. `payments_note`
on the payload says so, and `attribution` records how each group's payments were
found.
"""

from decimal import Decimal

from payrollio.django_rest.helpers.accounting_preferences_setup import (
    FEDERAL_TAX_LIABILITY_COMPONENTS,
    STATE_TAX_LIABILITY_COMPONENTS,
)
from payrollio.django_rest.helpers.component_labels import component_label
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAX_GROUP_940,
    FEDERAL_TAX_GROUP_941,
    payroll_types_for_group,
)
from payrollio.django_rest.helpers.payroll_report_common import (
    EMPLOYEE_TAXES,
    EMPLOYER_TAXES,
    ZERO,
    amount_string,
    money,
    normalize_name,
)


COLUMNS = [
    {"key": "tax_type", "label": "Tax types", "align": "left"},
    {"key": "tax_amount", "label": "Tax amount", "align": "right"},
    {"key": "tax_paid", "label": "Tax paid", "align": "right"},
    {"key": "tax_owed", "label": "Tax owed", "align": "right"},
]

# Only tax categories reach this report. Deductions and company contributions
# are withheld or spent, but they are not a tax liability.
_TAX_CATEGORIES = (EMPLOYEE_TAXES, EMPLOYER_TAXES)

# The 941 lines pair each employee tax with its employer half, which neither the
# declared group tuple nor an alphabetical sort produces. Every other group
# falls back to label order -- which happens to be what the reference prints for
# the state groups.
_FEDERAL_941_DISPLAY_ORDER = (
    "FEDERAL_INCOME_TAX",
    "SOCIAL_SECURITY",
    "SOCIAL_SECURITY_EMPLOYER",
    "MEDICARE",
    "MEDICARE_EMPLOYER",
    "MEDICARE_ADDITIONAL",
)

# Within a state, employment taxes print above income tax, as the reference
# shows. Groups not matched here keep their declared order.
_STATE_GROUP_RANK = (("_EMPLOYMENT_TAXES", 0), ("_UNEMPLOYMENT_TAXES", 0),
                     ("_INCOME_TAX", 1))


def _state_group_rank(group_key):
    for suffix, rank in _STATE_GROUP_RANK:
        if group_key.endswith(suffix):
            return rank
    return 2  # anything else (MN Paid Leave) trails


def known_groups(state_code=None, present_types=None):
    """(group key, label) in print order: federal first, then state groups.

    The company's own state leads, but **every** state whose taxes actually
    appear in the data gets its groups too. Production has a Minnesota company
    carrying NY employment taxes -- restricting to the configured state dumped
    those into "Other taxes" instead of grouping them under NY, which is wrong
    for anyone running multi-state payroll.

    `present_types` is the set of payroll types found in the range; pass None to
    get the company's own state only (the historical behaviour, used where the
    components are not yet known).
    """
    groups = list(FEDERAL_TAX_LIABILITY_COMPONENTS)
    home = (state_code or "").strip().upper()

    states = [home] if home in STATE_TAX_LIABILITY_COMPONENTS else []
    if present_types:
        for state, state_groups in STATE_TAX_LIABILITY_COMPONENTS.items():
            if state in states:
                continue
            if any(
                payroll_type in present_types
                for group_key, _ in state_groups
                for payroll_type in payroll_types_for_group(group_key)
            ):
                states.append(state)

    for state in states:
        state_groups = list(STATE_TAX_LIABILITY_COMPONENTS.get(state, ()))
        state_groups.sort(key=lambda pair: _state_group_rank(pair[0]))
        groups.extend(state_groups)
    return groups


def member_order(group_key, payroll_types):
    if group_key == FEDERAL_TAX_GROUP_941:
        ranked = {code: index for index, code in
                  enumerate(_FEDERAL_941_DISPLAY_ORDER)}
        return sorted(
            payroll_types,
            key=lambda code: (ranked.get(code, len(ranked)),
                              component_label(code).lower()),
        )
    return sorted(payroll_types, key=lambda code: component_label(code).lower())


def _row(key, label, *, is_group, amount, paid):
    owed = amount - paid
    if owed < ZERO:
        # An overpayment is not a negative liability on this report; the excess
        # belongs to a refund/credit flow the report does not model.
        owed = ZERO
    return {
        "key": key,
        "label": label,
        "is_group": is_group,
        "tax_amount": amount_string(amount),
        "tax_paid": amount_string(paid),
        "tax_owed": amount_string(owed),
    }


def _allocate(total_paid, member_amounts):
    """Split a group's payment across its lines, pro-rata by amount.

    Payments are recorded against the group, so a per-line figure is an
    allocation rather than a record. The last non-zero line absorbs the rounding
    remainder, so the member lines always sum to exactly the group's paid
    figure -- a report whose column does not add up reads as a bug.
    """
    if not total_paid or not member_amounts:
        return [ZERO for _ in member_amounts]

    total_amount = sum(member_amounts, ZERO)
    if total_amount <= ZERO:
        return [ZERO for _ in member_amounts]

    shares = []
    running = ZERO
    last_index = None
    for index, amount in enumerate(member_amounts):
        if amount > ZERO:
            last_index = index
        share = money(total_paid * amount / total_amount)
        shares.append(share)
        running += share

    if last_index is not None and running != total_paid:
        shares[last_index] += total_paid - running
    return shares


def collect_component_totals(payrolls):
    """Sum tax components by `payroll_type` across every run in range."""
    totals = {}
    for payroll in payrolls:
        for component in payroll.payroll_components.all():
            if component.payroll_category not in _TAX_CATEGORIES:
                continue
            payroll_type = component.payroll_type or ""
            totals[payroll_type] = totals.get(payroll_type, ZERO) + money(
                component.current
            )
    return totals


def build_tax_liability(payrolls, *, state_code=None, paid_by_group=None):
    """Group tax components into filing groups with amount / paid / owed.

    `paid_by_group` maps a group key to the amount paid against it -- see
    `resolve_paid_by_group`, which is where the attribution guesswork lives.
    """
    paid_by_group = paid_by_group or {}
    component_totals = collect_component_totals(payrolls)
    claimed = set()
    rows = []

    for group_key, group_label in known_groups(state_code, set(component_totals)):
        members = [
            payroll_type
            for payroll_type in payroll_types_for_group(group_key)
            # A member line prints only if the payroll actually produced it --
            # including at 0.00, which the reference does show. What it must not
            # do is invent lines for taxes this company never ran.
            if payroll_type in component_totals
            # ...nor count one twice. The engine's generic "_INCOME_TAX" key is
            # a declared member of *every* state's income-tax group, so on a
            # multi-state company it would be added under each of them and
            # overstate the total. First group wins, and since the company's own
            # state is ordered first, that is the one it belongs to.
            and payroll_type not in claimed
        ]
        if not members:
            continue

        members = member_order(group_key, members)
        amounts = [component_totals[payroll_type] for payroll_type in members]
        group_amount = sum(amounts, ZERO)
        group_paid = money(paid_by_group.get(group_key, ZERO))
        shares = _allocate(group_paid, amounts)

        rows.append(
            _row(group_key, group_label, is_group=True, amount=group_amount,
                 paid=group_paid)
        )
        for payroll_type, amount, share in zip(members, amounts, shares):
            rows.append(
                _row(
                    f"{group_key}.{payroll_type}",
                    component_label(payroll_type),
                    is_group=False,
                    amount=amount,
                    paid=share,
                )
            )
        claimed.update(members)

    # A tax that belongs to no known group would otherwise vanish silently, and
    # the report would understate what is owed. Surface it rather than drop it.
    ungrouped = [
        payroll_type
        for payroll_type in component_totals
        if payroll_type not in claimed
    ]
    if ungrouped:
        ungrouped = sorted(ungrouped, key=lambda code: component_label(code).lower())
        amounts = [component_totals[payroll_type] for payroll_type in ungrouped]
        rows.append(
            _row("OTHER_TAXES", "Other taxes", is_group=True,
                 amount=sum(amounts, ZERO), paid=ZERO)
        )
        for payroll_type, amount in zip(ungrouped, amounts):
            rows.append(
                _row(
                    f"OTHER_TAXES.{payroll_type}",
                    component_label(payroll_type),
                    is_group=False,
                    amount=amount,
                    paid=ZERO,
                )
            )

    return {"columns": COLUMNS, "rows": rows}


def resolve_paid_by_group(company, state_code=None, date_from=None, date_to=None):
    """Attribute recorded tax payments to filing groups.

    `TaxCenterPayMethod` has no tax-type column, so attribution goes through
    whatever the row does carry, in order of trustworthiness:

    1. `liability_period` beginning with the group key (e.g. "FUTA-2026").
    2. The liability chart account, matched by **title** against the account
       configured for that group in the company's payroll accounting
       preferences.

    Title rather than id is deliberate. Production has payments pointing at a
    "MN Income Tax" account whose id differs from the currently-configured MN
    income-tax account -- the account was replaced and the old payments still
    reference the old row. Matching on id silently reports those as unpaid.

    Anything that matches neither is left out rather than spread across groups;
    a payment against a bank account (production has one) is not evidence about
    any particular tax.
    """
    from django.db.models import Q

    from payrollio.models import PayrollAccountExpenseAccountComponent
    from payrollio.models import TaxCenterPayMethod

    groups = [key for key, _ in known_groups(state_code)]

    # Both lookups are scoped to the company. Neither model is reachable from a
    # tenant-filtered manager, so an unscoped query here reports another
    # company's payments as this one's -- which is exactly what happened before
    # this filter existed: one FUTA payment appeared against two companies.
    title_to_group = {}
    configured = (
        PayrollAccountExpenseAccountComponent.objects.filter(
            payroll_accounting_preferences__company=company,
            account_type__in=groups,
            expense_account__isnull=False,
        )
        .select_related("expense_account")
        .values_list("account_type", "expense_account__title")
    )
    for account_type, title in configured:
        normalized = normalize_name(title)
        if normalized:
            title_to_group.setdefault(normalized, account_type)

    payments = TaxCenterPayMethod.objects.filter(
        Q(tax_liability_account__company=company)
        | Q(tax_record_account__company=company),
        is_paid=True,
    ).select_related("tax_liability_account")
    if date_from:
        payments = payments.filter(payment_date__gte=date_from)
    if date_to:
        payments = payments.filter(payment_date__lte=date_to)

    paid = {}
    attribution = {}
    for payment in payments:
        group_key = None

        period = (payment.liability_period or "").strip()
        if period:
            for candidate in groups:
                if period.upper().startswith(candidate.upper()):
                    group_key = candidate
                    break
            if group_key is None:
                # "FUTA-2026" names the tax, not the group key -- fall back to
                # the group whose members include a matching payroll type.
                head = normalize_name(period.split("-")[0])
                for candidate in groups:
                    if any(
                        head and head in normalize_name(payroll_type)
                        for payroll_type in payroll_types_for_group(candidate)
                    ):
                        group_key = candidate
                        break

        if group_key is None and payment.tax_liability_account_id:
            title = normalize_name(
                getattr(payment.tax_liability_account, "title", "")
            )
            group_key = title_to_group.get(title)

        if group_key is None:
            continue

        paid[group_key] = paid.get(group_key, ZERO) + money(payment.tax_amount)
        attribution.setdefault(group_key, 0)
        attribution[group_key] += 1

    return paid, attribution
