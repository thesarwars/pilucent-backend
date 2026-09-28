from django.core.management.base import BaseCommand
from django.db import transaction

from rulebookio.models import RuleSet
from rulebookio.seed_bd import assert_enum_coverage, rule_sets


class Command(BaseCommand):
    help = "Load the Bangladesh statutory rule sets ported from rules.js. Safe to re-run."

    @transaction.atomic
    def handle(self, *args, **options):
        sets = rule_sets()
        assert_enum_coverage(sets)
        for spec in sets:
            key = {"jurisdiction": "BD", "family": spec.pop("family"), "version": spec.pop("version")}
            _, created = RuleSet.objects.update_or_create(**key, defaults=spec)
            self.stdout.write(
                f"{'created' if created else 'updated'} {key['family']} {key['version']} "
                f"({spec['effective_from']} to {spec['effective_to'] or 'open'})"
            )
