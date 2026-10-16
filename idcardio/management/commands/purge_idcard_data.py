from django.core.management.base import BaseCommand

from companyio.models import Company
from idcardio.services.ops import apply_retention, emit_expiring


class Command(BaseCommand):
    help = "ID cards §11: set photo retention on separation, purge expired photos and 90-day print artifacts."

    def handle(self, *args, **options):
        for company in Company.objects.all():
            out = {**apply_retention(company), "expiringNotices": emit_expiring(company)}
            if any(out.values()):
                self.stdout.write(f"{company.pk}: {out}")
