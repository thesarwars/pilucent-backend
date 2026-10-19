"""Pay components and structures (docs/backend/components-n-structures-backend-done.md):
the library a salary structure is assembled from.

- A component declares its bases as named columns -- eight of them, the one
  canonical set (§13 question 1): the six of the library and the two the
  payroll engine needs (s.125 wages base, perquisite ceiling).
- Components and templates are versioned. A flag change makes version n+1
  from a date; a structure line pins the version it was built on, so a 2026
  structure resolves its 2026 bases after a 2027 change.
- A component maps to an account in the company's own chart of accounts; an
  active component without one blocks the payroll journal.
- Nothing here stores an employee's money. `employeeio` holds the
  structures.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import BaseModelWithUID

from .choices import (
    BASE_FIELDS,
    BulkMethodChoices,
    BulkStatusChoices,
    CalcBasisChoices,
    ComponentKindChoices,
    LibraryAuditActionChoices,
    RoundingChoices,
    RowBasisChoices,
    TemplateModeChoices,
    TemplateStatusChoices,
)


def _text(max_length=255, **kwargs):
    return models.CharField(max_length=max_length, blank=True, default="", **kwargs)


def _user():
    return models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")


class PayComponent(BaseModelWithUID):
    """§3.1. One version of a component. The current version of a code is the
    one with no `superseded_by`; an older one still resolves the structures
    built on it."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="pay_components")
    code = models.CharField(max_length=10)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    name_bn = _text(120)
    kind = models.CharField(max_length=14, choices=ComponentKindChoices.choices)
    calc_basis = models.CharField(max_length=14, choices=CalcBasisChoices.choices)
    calc_expression = _text(200)  # 'Basic ÷ 208 × 2' for DERIVED

    in_taxable_income = models.BooleanField(default=False)
    in_pf_base = models.BooleanField(default=False)
    in_ot_base_s108 = models.BooleanField(default=False)
    in_gratuity_base = models.BooleanField(default=False)
    in_festival_base = models.BooleanField(default=False)
    prorate_part_month = models.BooleanField(default=True)
    in_wages_base = models.BooleanField(default=False)
    in_perquisite_ceiling = models.BooleanField(default=False)

    gl_account = models.ForeignKey("accounts.ChartOfAccount", on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="+")
    is_statutory = models.BooleanField(default=False)
    statutory_basis = _text(200)  # the section it rests on
    locked_flags = models.JSONField(default=list, blank=True)  # base names that may be set, never unset
    flags_frozen = models.BooleanField(default=False)  # no base changes at all (PFE)

    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField()
    superseded_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="supersedes")
    change_reason = models.TextField(blank=True, default="")
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("display_order", "code", "-version")
        constraints = [
            models.UniqueConstraint(fields=["company", "code", "version"], name="paylibio_component_code_version"),
            models.CheckConstraint(condition=~Q(calc_basis="DERIVED") | ~Q(calc_expression=""),
                                   name="paylibio_component_derived_has_expression"),
            models.CheckConstraint(condition=Q(is_statutory=False) | ~Q(statutory_basis=""),
                                   name="paylibio_component_statutory_cites_basis"),
            # §3.1: a deduction enters no earnings base.
            models.CheckConstraint(
                condition=~Q(kind="DEDUCTION") | Q(**{f: False for f in BASE_FIELDS if f != "prorate_part_month"}),
                name="paylibio_component_deduction_has_no_bases"),
        ]
        indexes = [models.Index(fields=["company", "display_order"], name="paylibio_component_active",
                                condition=Q(is_active=True, superseded_by__isnull=True))]

    def __str__(self):
        return f"{self.code} v{self.version}"

    def flags(self):
        return {f: getattr(self, f) for f in BASE_FIELDS}

    def save(self, *args, **kwargs):
        """§3.3, at the model too: a locked flag may be set, never unset."""
        if not self._state.adding and self.locked_flags:
            before = type(self).objects.filter(pk=self.pk).values(*BASE_FIELDS).first()
            for f in self.locked_flags:
                if before and before.get(f) and not getattr(self, f):
                    raise ValidationError(f"{self.name} is statutory — {f} cannot be unset. Change it in the rule "
                                          "book, not in company data.")
        super().save(*args, **kwargs)


class StructureTemplate(BaseModelWithUID):
    """§3.4. A named split, versioned. Gross-down takes a gross and splits it;
    basic-up takes a basic and stacks the allowances, so gross is an output.

    A GAZETTE template (RMG) takes its figures from the rule book as at the
    structure's date -- the gazette sets basic, not gross -- and has no rows."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="structure_templates")
    code = models.CharField(max_length=40)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    name_bn = _text(120)
    mode = models.CharField(max_length=10, choices=TemplateModeChoices.choices)
    note = models.TextField()  # states the CONSEQUENCE of choosing it
    note_bn = models.TextField(blank=True, default="")
    balancing_code = models.CharField(max_length=10, default="BASIC")
    gazette = models.BooleanField(default=False)
    grade_scope = models.JSONField(null=True, blank=True)  # [G5, G6] -- null = any grade
    site_scope = models.JSONField(null=True, blank=True)  # [site uid] -- null = any establishment
    status = models.CharField(max_length=10, choices=TemplateStatusChoices.choices,
                              default=TemplateStatusChoices.DRAFT)
    locked = models.BooleanField(default=False)  # set on first use
    display_order = models.PositiveSmallIntegerField(default=0)
    effective_from = models.DateField()
    superseded_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="supersedes")
    published_at = models.DateTimeField(null=True, blank=True)
    published_by_name = _text()
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("display_order", "code", "-version")
        constraints = [
            models.UniqueConstraint(fields=["company", "code", "version"], name="paylibio_template_code_version"),
            models.CheckConstraint(condition=Q(gazette=False) | Q(mode="BASIC_UP"),
                                   name="paylibio_template_gazette_is_basic_up"),
        ]

    def __str__(self):
        return f"{self.code} v{self.version}"


class StructureTemplateRow(BaseModelWithUID):
    """§3.5. `value` at four places: 66.6700 stays exact."""

    template = models.ForeignKey(StructureTemplate, on_delete=models.CASCADE, related_name="rows")
    component_code = models.CharField(max_length=10)
    basis = models.CharField(max_length=14, choices=RowBasisChoices.choices)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("display_order", "id")
        constraints = [
            models.UniqueConstraint(fields=["template", "component_code"], name="paylibio_row_one_per_component"),
            models.CheckConstraint(condition=Q(value__gte=0), name="paylibio_row_value_non_negative"),
            models.CheckConstraint(condition=Q(basis="FIXED") | Q(value__gt=0, value__lte=100),
                                   name="paylibio_row_pct_in_range"),
        ]


class PayrollPolicy(BaseModelWithUID):
    """The company's own basic floor, which may exceed the gazette. The
    provident-fund rates moved to the PF scheme in payroll settings."""

    company = models.OneToOneField("companyio.Company", on_delete=models.CASCADE, related_name="payroll_policy")
    company_floor_basic = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    basic_share_warn_pct = models.DecimalField(max_digits=6, decimal_places=2, default=50)


class BulkRevision(BaseModelWithUID):
    """§3.8. A rise across a cohort, applied only after a stored preview."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    reference = models.CharField(max_length=20)
    scope_json = models.JSONField()  # {grades, departments, sites, templates, employeeCodes}
    method = models.CharField(max_length=16, choices=BulkMethodChoices.choices)
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_template = models.ForeignKey(StructureTemplate, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="+")
    rounding = models.CharField(max_length=12, choices=RoundingChoices.choices, default=RoundingChoices.NEAREST_100)
    effective_from = models.DateField()
    include_overridden = models.BooleanField(default=False)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=BulkStatusChoices.choices, default=BulkStatusChoices.DRAFT)
    preview_json = models.JSONField(null=True, blank=True)
    affected_count = models.PositiveIntegerField(default=0)
    refused_count = models.PositiveIntegerField(default=0)
    applied_structures = models.JSONField(default=list, blank=True)  # structure uids it created
    previewed_at = models.DateTimeField(null=True, blank=True)
    previewed_by_name = _text()
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = _user()
    applied_by_name = _text()
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True, default="")
    created_by = _user()
    created_by_name = _text()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["company", "reference"], name="paylibio_bulk_reference_unique"),
            models.CheckConstraint(condition=~Q(method="CHANGE_TEMPLATE") | Q(target_template__isnull=False),
                                   name="paylibio_bulk_template_method_has_target"),
            # The constraint that matters: 148 structures nobody checked is the failure.
            models.CheckConstraint(condition=~Q(status="APPLIED") | Q(preview_json__isnull=False),
                                   name="paylibio_bulk_applied_was_previewed"),
            models.CheckConstraint(condition=~Q(status="REVERSED") | ~Q(reverse_reason=""),
                                   name="paylibio_bulk_reverse_needs_reason"),
        ]


class LibraryEvent(BaseModelWithUID):
    """§8. The outbox: payroll and the salary module read and mark consumed."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = _text(60)

    class Meta:
        ordering = ("created_at", "id")


class LibraryAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("The library audit is append-only.")

    def delete(self):
        raise ValidationError("The library audit is append-only.")


class LibraryAudit(BaseModelWithUID):
    """§3.9. A flag change records that flag's before and after: "who removed
    house rent from the gratuity base, and when" is the question."""

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE, related_name="+")
    action = models.CharField(max_length=24, choices=LibraryAuditActionChoices.choices)
    entity_type = models.CharField(max_length=20)
    entity_code = models.CharField(max_length=40)
    entity_version = models.PositiveIntegerField(null=True, blank=True)
    actor = _user()
    actor_name = _text()
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    objects = LibraryAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        # §7. Flags, apply and publish are each their own permission.
        permissions = [
            ("edit_pay_components", "Can edit pay components (name, calculation)"),
            ("change_component_flags", "Can change a pay component's base flags"),
            ("edit_structure_templates", "Can draft structure templates"),
            ("publish_structure_templates", "Can publish a structure template version"),
            ("preview_bulk_revision", "Can preview a bulk salary revision"),
            ("apply_bulk_revision", "Can apply a bulk salary revision"),
            ("map_gl_accounts", "Can map pay components to GL accounts"),
            ("manage_payroll_policy", "Can set the company floor and provident fund rates"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("The library audit is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The library audit is append-only.")


__all__ = ["BulkMethodChoices"]
