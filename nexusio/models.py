"""Economic Nexus data model (Phase 1: rule engine + per-company status).

Two tables here:

* ``NexusStateRule`` — the effective-dated per-state threshold rules. This is
  **global reference data** (like ``payrollio.PayrollTaxConfig``): no ``company``
  FK, and deliberately NOT under the tenant RLS policy. Seeded from
  ``docs/updated-prompts/Balanzify_State_Economic_Nexus_Rules_Reference.md``.
* ``NexusStateStatus`` — the computed dashboard row per (company, state). Tenant
  data: carries ``company`` and the tenant-isolation RLS policy.

Nexus monitoring never posts to the ledger — it only measures sales activity
against thresholds. See the module spec for the full design.
"""

from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    NexusAlertTypeChoices,
    NexusCombinationLogicChoices,
    NexusFilingFrequencyChoices,
    NexusIncludableSalesBasisChoices,
    NexusMeasurementPeriodChoices,
    NexusRegistrationStatusChoices,
    NexusRegistrationTypeChoices,
    NexusStatusChoices,
)


class NexusStateRule(BaseModelWithUID):
    """One effective-dated economic-nexus rule for a US jurisdiction.

    A rule change (e.g. a state dropping its transaction test) is a NEW row with
    a later ``effective_from`` and the prior row's ``effective_to`` closed — never
    an in-place edit — so any past verdict can be reproduced.
    """

    state_code = models.CharField(max_length=2, db_index=True)  # USPS code / "DC" / "PR"
    state_name = models.CharField(max_length=100)
    has_sales_tax = models.BooleanField(default=True)
    sales_threshold = models.DecimalField(
        max_digits=14, decimal_places=2, blank=True, null=True
    )
    txn_threshold = models.PositiveIntegerField(blank=True, null=True)
    combination_logic = models.CharField(
        max_length=20, choices=NexusCombinationLogicChoices.choices
    )
    includable_sales_basis = models.CharField(
        max_length=10,
        choices=NexusIncludableSalesBasisChoices.choices,
        default=NexusIncludableSalesBasisChoices.GROSS,
    )
    measurement_period_type = models.CharField(
        max_length=30, choices=NexusMeasurementPeriodChoices.choices
    )
    trailing_nexus_rule = models.TextField(blank=True, null=True)
    registration_timing_note = models.TextField(blank=True, null=True)
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)  # null = currently in force
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("state_code", "-effective_from")
        constraints = [
            models.UniqueConstraint(
                fields=["state_code", "effective_from"],
                name="uniq_nexus_rule_state_effective",
            )
        ]

    def __str__(self):
        return f"{self.state_code} rule from {self.effective_from} ({self.combination_logic})"


class NexusStateStatus(BaseModelWithUID):
    """Computed nexus status for one company × state — the dashboard row.

    Upserted by the recompute engine. ``threshold_met_date`` is the date the
    engine FIRST OBSERVED the threshold met, and is immutable thereafter. For a
    company onboarded with back-dated sales this is the first evaluation date,
    which may post-date the actual crossing; precise historical crossing
    detection is a later refinement.
    """

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    state_code = models.CharField(max_length=2, db_index=True)

    window_start = models.DateField(blank=True, null=True)
    window_end = models.DateField(blank=True, null=True)
    sales_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_sales_amount = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    txn_count = models.PositiveIntegerField(default=0)
    pct_of_sales_threshold = models.DecimalField(
        max_digits=8, decimal_places=4, blank=True, null=True
    )
    pct_of_txn_threshold = models.DecimalField(
        max_digits=8, decimal_places=4, blank=True, null=True
    )
    threshold_met = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=NexusStatusChoices.choices,
        default=NexusStatusChoices.NOT_APPROACHING,
    )
    threshold_met_date = models.DateField(blank=True, null=True)
    episode_key = models.CharField(max_length=64, blank=True, null=True)
    last_evaluated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("state_code",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "state_code"],
                name="uniq_nexus_status_company_state",
            )
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.company_id} / {self.state_code}: {self.status}"


class NexusAgencyRegistration(BaseModelWithUID):
    """A company's registration (or manual physical-nexus mark) for a state.

    Records the handoff to Sales Tax: the intent + registration facts. Linking to
    an ``agencyio.Agency`` and turning on rate calculation is the Sales Tax
    module's job (this stores the pointer once it exists). A row here with
    ``registration_status=REGISTERED`` or ``registration_type=PHYSICAL_MANUAL``
    makes the state show as REGISTERED on the dashboard.
    """

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    state_code = models.CharField(max_length=2, db_index=True)
    tax_agency = models.ForeignKey(
        "agencyio.Agency", on_delete=models.SET_NULL, blank=True, null=True
    )
    registration_type = models.CharField(
        max_length=20,
        choices=NexusRegistrationTypeChoices.choices,
        default=NexusRegistrationTypeChoices.ECONOMIC,
    )
    registration_status = models.CharField(
        max_length=20,
        choices=NexusRegistrationStatusChoices.choices,
        default=NexusRegistrationStatusChoices.NOT_STARTED,
    )
    sales_tax_permit_number = models.CharField(max_length=100, blank=True, null=True)
    filing_frequency = models.CharField(
        max_length=20, choices=NexusFilingFrequencyChoices.choices, blank=True, null=True
    )
    collection_start_date = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "state_code"],
                name="uniq_nexus_registration_company_state",
            )
        ]

    def is_handled(self):
        """True when the state should display as REGISTERED (registered or marked)."""
        return (
            self.registration_status == NexusRegistrationStatusChoices.REGISTERED
            or self.registration_type == NexusRegistrationTypeChoices.PHYSICAL_MANUAL
        )

    def __str__(self):
        return f"{self.company_id} / {self.state_code}: {self.registration_status}"


class NexusAlertLog(BaseModelWithUID):
    """Append-only record of approaching/crossing alerts, for de-dup + audit.

    The unique constraint on (company, state, type, episode) enforces
    exactly-once delivery per episode at the database level — an ``episode`` is a
    single approach-then-cross sequence; a fresh approach after a real dip mints a
    new episode key so a genuinely new crossing can alert again.
    """

    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    state_code = models.CharField(max_length=2, db_index=True)
    alert_type = models.CharField(
        max_length=20, choices=NexusAlertTypeChoices.choices
    )
    episode_key = models.CharField(max_length=64)
    threshold_pct_at_alert = models.DecimalField(
        max_digits=8, decimal_places=4, blank=True, null=True
    )
    triggered_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, blank=True, null=True
    )
    acknowledged_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-triggered_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "state_code", "alert_type", "episode_key"],
                name="uniq_nexus_alert_episode",
            )
        ]
        indexes = [models.Index(fields=["company", "triggered_at"])]

    def __str__(self):
        return f"{self.company_id} / {self.state_code}: {self.alert_type}"


class NexusSettings(BaseModelWithUID):
    """Per-company configuration for the nexus module."""

    company = models.OneToOneField("companyio.Company", on_delete=models.CASCADE)
    warning_fraction = models.DecimalField(
        max_digits=4, decimal_places=3, default=0.800
    )
    include_marketplace_in_measurement = models.BooleanField(default=True)
    alert_channels = models.JSONField(default=list)

    def __str__(self):
        return f"NexusSettings for {self.company_id}"
