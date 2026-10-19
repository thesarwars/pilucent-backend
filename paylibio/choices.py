from django.db import models

# The eight bases, in their fixed order (§2: flags are positional on the
# screen; the order never changes). Named columns in the database.
BASES = (
    ("in_taxable_income", "taxable", "Taxable income", "enters the income tax computation"),
    ("in_pf_base", "pf", "Provident fund base", "the employee's and the employer's contribution are computed on it"),
    ("in_ot_base_s108", "ot", "Overtime base", "the s.108 hourly rate divides this"),
    ("in_gratuity_base", "gratuity", "Gratuity wage basis", "the separation payout is computed on it"),
    ("in_festival_base", "festival", "Festival bonus basis", "the two annual bonuses are computed on it"),
    ("prorate_part_month", "prorate", "Prorated on a part month", "a joiner or leaver receives a fraction of it"),
    ("in_wages_base", "wages", "Wages base (s.125)", "the deduction cap on wages is measured against it"),
    ("in_perquisite_ceiling", "perquisite", "Perquisite ceiling", "counts toward the tax-exempt perquisite ceiling"),
)
BASE_FIELDS = tuple(b[0] for b in BASES)
EARNING_BASES = BASE_FIELDS  # every base is an earnings base: a deduction enters none


class ComponentKindChoices(models.TextChoices):
    EARNING = "EARNING", "Earning"
    DEDUCTION = "DEDUCTION", "Deduction"
    EMPLOYER_COST = "EMPLOYER_COST", "Employer cost"
    NOTIONAL = "NOTIONAL", "Notional"


class CalcBasisChoices(models.TextChoices):
    PCT_OF_GROSS = "PCT_OF_GROSS", "% of gross"
    PCT_OF_BASIC = "PCT_OF_BASIC", "% of basic"
    FIXED = "FIXED", "Fixed amount"
    PER_SHIFT = "PER_SHIFT", "Per shift"
    DERIVED = "DERIVED", "Derived"


class RowBasisChoices(models.TextChoices):
    PCT_OF_GROSS = "PCT_OF_GROSS", "% of gross"
    PCT_OF_BASIC = "PCT_OF_BASIC", "% of basic"
    FIXED = "FIXED", "Fixed amount"


class TemplateModeChoices(models.TextChoices):
    GROSS_DOWN = "GROSS_DOWN", "Gross-down"
    BASIC_UP = "BASIC_UP", "Basic-up"


class TemplateStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    ARCHIVED = "ARCHIVED", "Archived"


class BulkMethodChoices(models.TextChoices):
    PCT_INCREASE = "PCT_INCREASE", "Percentage increase"
    FIXED_INCREASE = "FIXED_INCREASE", "Fixed increase"
    NEW_GROSS = "NEW_GROSS", "New gross"
    CHANGE_TEMPLATE = "CHANGE_TEMPLATE", "Change template"


class RoundingChoices(models.TextChoices):
    NONE = "NONE", "No rounding"
    NEAREST_1 = "NEAREST_1", "Nearest ৳1"
    NEAREST_10 = "NEAREST_10", "Nearest ৳10"
    NEAREST_100 = "NEAREST_100", "Nearest ৳100"
    NEAREST_500 = "NEAREST_500", "Nearest ৳500"


ROUNDING_STEP = {"NONE": 0, "NEAREST_1": 1, "NEAREST_10": 10, "NEAREST_100": 100, "NEAREST_500": 500}


class BulkStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PREVIEWED = "PREVIEWED", "Previewed"
    APPLIED = "APPLIED", "Applied"
    REVERSED = "REVERSED", "Reversed"


class LibraryAuditActionChoices(models.TextChoices):
    COMPONENT_CREATED = "COMPONENT_CREATED", "Component created"
    COMPONENT_EDITED = "COMPONENT_EDITED", "Component edited"
    FLAG_CHANGED = "FLAG_CHANGED", "Base flag changed"
    COMPONENT_SUPERSEDED = "COMPONENT_SUPERSEDED", "Component superseded"
    TEMPLATE_SAVED = "TEMPLATE_SAVED", "Template saved"
    TEMPLATE_PUBLISHED = "TEMPLATE_PUBLISHED", "Template published"
    TEMPLATE_SUPERSEDED = "TEMPLATE_SUPERSEDED", "Template superseded"
    TEMPLATE_ARCHIVED = "TEMPLATE_ARCHIVED", "Template archived"
    GL_MAPPED = "GL_MAPPED", "GL account mapped"
    POLICY_CHANGED = "POLICY_CHANGED", "Payroll policy changed"
    BULK_PREVIEWED = "BULK_PREVIEWED", "Bulk revision previewed"
    BULK_APPLIED = "BULK_APPLIED", "Bulk revision applied"
    BULK_REVERSED = "BULK_REVERSED", "Bulk revision reversed"
