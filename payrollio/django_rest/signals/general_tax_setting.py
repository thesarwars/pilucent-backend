from django.db.models.signals import post_save
from django.dispatch import receiver

from payrollio.models import PayrollGeneralTaxSetting

from ..helpers.payroll_onboarding import on_general_tax_setting_saved


@receiver(post_save, sender=PayrollGeneralTaxSetting)
def payroll_general_tax_setting_post_save(sender, instance, **kwargs):
    on_general_tax_setting_saved(instance)
