from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from moovmoneyio.django_rest.helpers.slug_helpers import (
    get_moov_account_setting_slug,
    get_moov_bank_account_setting_slug,
    get_moov_transfer_slug,
)
from moovmoneyio.choices import (
    MoovAccountSettingsStatusChoices,
    MoovAccountBankAccountSettingsStatusChoices,
    MoovBankAccountKindChoices,
    MoovTransferStatusChoices,
)


class MoovAccountSettings(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_moov_account_setting_slug, unique=True, always_update=False
    )
    moov_account_uid = models.CharField(
        max_length=64, unique=True, blank=False, null=False
    )
    moov_account_display_name = models.CharField(max_length=255, blank=True, null=True)
    moov_representative_uid = models.CharField(
        max_length=64, unique=True, blank=True, null=True
    )
    status = models.CharField(
        choices=MoovAccountSettingsStatusChoices.choices,
        max_length=250,
        default=MoovAccountSettingsStatusChoices.ACTIVE,
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return self.moov_account_display_name


class MoovBankAccountSettings(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_moov_bank_account_setting_slug,
        unique=True,
        always_update=False,
    )
    moov_account_settings = models.ForeignKey(
        MoovAccountSettings,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="moov_bank_accounts",
    )
    bank_account_uid = models.CharField(
        max_length=64, unique=True, blank=False, null=False
    )
    account_type = models.CharField(max_length=50, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    routing_number = models.CharField(max_length=50, blank=True, null=True)
    account_holder_name = models.CharField(max_length=255, blank=True, null=True)
    account_holder_type = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        choices=MoovAccountBankAccountSettingsStatusChoices.choices,
        max_length=250,
        default=MoovAccountBankAccountSettingsStatusChoices.DRAFT,
    )
    employee = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moov_employee_bank_accounts",
    )
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )
    bank_account_kind = models.CharField(
        choices=MoovBankAccountKindChoices.choices,
        max_length=250,
        default=MoovBankAccountKindChoices.DESTINATION,
    )

    def __str__(self):
        last4 = self.account_number[-4:] if self.account_number else "????"
        return f"{self.bank_name} - ****{last4}"


class MoovTransfers(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_moov_transfer_slug,
        unique=True,
        always_update=False,
    )
    moov_transfer_uid = models.CharField(
        max_length=64, unique=True, blank=False, null=False
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, blank=False, null=False
    )
    currency = models.CharField(max_length=10, blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    source_bank_account = models.ForeignKey(
        MoovBankAccountSettings,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_transfers",
    )
    destination_bank_account = models.ForeignKey(
        MoovBankAccountSettings,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="destination_transfers",
    )
    status = models.CharField(
        choices=MoovTransferStatusChoices.choices,
        max_length=250,
        default=MoovTransferStatusChoices.PENDING,
    )
    employee = models.ForeignKey(
        "employeeio.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moov_employee_transfers",
    )
    # Who initiated the transfer. Whoever moves money must be able to log in, so
    # this is a User (not an Employee, unlike the app-wide created_by convention):
    # admins/owners who run a payout have no Employee record.
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    # The payroll run this transfer pays out (a payroll payout moves the run's
    # net pay). Nullable because standalone/non-payroll transfers have no run.
    payroll_salary_process = models.ForeignKey(
        "payrollio.PayrollSalaryProcess",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moov_transfers",
    )

    def __str__(self):
        return f"Transfer {self.moov_transfer_uid} - {self.amount} {self.currency}"
