"""Seed / upsert statutory PayrollTaxConfig rows from bundled JSON files.

Reads payrollio/data/tax_config/<year>/<jurisdiction>.json (jurisdiction =
``federal`` or a lowercase USPS code) and upserts one row per file. Idempotent:
re-running updates ``data`` and bumps ``version`` only when the payload changed.

    python manage.py seed_payroll_tax_config --year 2026 [--publish]

Run once per deploy that ships new/updated tables (prod is seeded this way, like
setup_payroll_accounting_preferences).
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from payrollio.choicess import PayrollTaxConfigStatusChoices
from payrollio.django_rest.helpers.tax_config import normalize_jurisdiction
from payrollio.models import PayrollTaxConfig

DATA_ROOT = Path(settings.BASE_DIR) / "payrollio" / "data" / "tax_config"


class Command(BaseCommand):
    help = "Seed/upsert PayrollTaxConfig rows for a year from bundled JSON files."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Tax year, e.g. 2026")
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Set status=PUBLISHED (default keeps existing / DRAFT for new).",
        )

    def handle(self, *args, **options):
        year = options["year"]
        publish = options["publish"]
        year_dir = DATA_ROOT / str(year)
        if not year_dir.is_dir():
            raise CommandError(f"No seed directory for {year}: {year_dir}")

        files = sorted(year_dir.glob("*.json"))
        if not files:
            raise CommandError(f"No JSON seed files in {year_dir}")

        for path in files:
            jurisdiction = normalize_jurisdiction(path.stem)
            if not jurisdiction:
                self.stderr.write(f"Skipping {path.name}: not a valid jurisdiction")
                continue

            data = json.loads(path.read_text())
            existing = PayrollTaxConfig.objects.filter(
                year=year, jurisdiction=jurisdiction
            ).first()

            status = (
                PayrollTaxConfigStatusChoices.PUBLISHED
                if publish
                else (existing.status if existing else PayrollTaxConfigStatusChoices.DRAFT)
            )

            if existing:
                changed = existing.data != data
                existing.data = data
                existing.status = status
                if changed:
                    existing.version += 1
                existing.save(
                    update_fields=["data", "status", "version", "updated_at"]
                )
                action = "updated (v%d)" % existing.version if changed else "unchanged"
            else:
                obj = PayrollTaxConfig.objects.create(
                    year=year,
                    jurisdiction=jurisdiction,
                    status=status,
                    data=data,
                    source_notes="Seeded from bundled JSON (IRS Pub 15-T / NY DOL / MN DOR).",
                )
                action = "created (v%d)" % obj.version

            self.stdout.write(
                self.style.SUCCESS(f"{year} {jurisdiction}: {action} [{status}]")
            )
