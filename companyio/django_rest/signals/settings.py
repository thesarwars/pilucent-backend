from django.db.models.signals import post_save
from django.dispatch import receiver

from purchaseio.models import PurchaseSetting

from salesio.models import SaleSetting

from common.tenant import tenant_unscoped

from ...models import Company, CompanySetting
from ...django_rest.helpers.signal_helpers import create_chart_of_accounts


@receiver(post_save, sender=Company)
def create_company_setting(sender, instance, created, **kwargs):
    if created:
        # Seeding a brand-new company writes rows for *that* company (e.g. its
        # chart of accounts, an RLS-protected table). The request creating it is
        # usually scoped to a different company, so run the seeding unscoped to
        # avoid tripping the RLS WITH CHECK on the new company's rows.
        with tenant_unscoped():
            company_setting = CompanySetting.objects.get_or_create(company=instance)
            SaleSetting.objects.get_or_create(company=instance)
            PurchaseSetting.objects.get_or_create(company=instance)
            create_chart_of_accounts(instance, company_setting[0])
