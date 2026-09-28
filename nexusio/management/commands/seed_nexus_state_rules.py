"""Seed / upsert NexusStateRule from nexusio/data/state_rules.py.

Idempotent (keyed on state_code + effective_from): re-running updates a version's
fields in place only when they changed, and inserts new versions. A rule *change*
is a new row (never an edit of an existing effective_from), so re-seeding never
rewrites history.

    python manage.py seed_nexus_state_rules

Run once at rollout and whenever the bundled rule data changes.
"""

from datetime import date

from django.core.management.base import BaseCommand

from nexusio.data.state_rules import STATE_RULES
from nexusio.models import NexusStateRule

_FIELDS = (
    "state_name",
    "has_sales_tax",
    "sales_threshold",
    "txn_threshold",
    "combination_logic",
    "includable_sales_basis",
    "measurement_period_type",
    "effective_to",
    "notes",
)


class Command(BaseCommand):
    help = "Seed/upsert economic-nexus state rules from bundled reference data."

    def handle(self, *args, **options):
        created = updated = unchanged = 0
        for row in STATE_RULES:
            effective_from = date.fromisoformat(row["effective_from"])
            effective_to = (
                date.fromisoformat(row["effective_to"])
                if row.get("effective_to")
                else None
            )
            defaults = {
                "state_name": row["state_name"],
                "has_sales_tax": row["has_sales_tax"],
                "sales_threshold": row["sales_threshold"],
                "txn_threshold": row["txn_threshold"],
                "combination_logic": row["combination_logic"],
                "includable_sales_basis": row["includable_sales_basis"],
                "measurement_period_type": row["measurement_period_type"],
                "effective_to": effective_to,
                "notes": row.get("notes"),
            }
            obj, was_created = NexusStateRule.objects.get_or_create(
                state_code=row["state_code"],
                effective_from=effective_from,
                defaults=defaults,
            )
            if was_created:
                created += 1
                continue
            changes = [f for f in _FIELDS if getattr(obj, f) != defaults[f]]
            if changes:
                for field in changes:
                    setattr(obj, field, defaults[field])
                obj.save(update_fields=changes + ["updated_at"])
                updated += 1
            else:
                unchanged += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Nexus rules: created {created}, updated {updated}, "
                f"unchanged {unchanged} (total rows {len(STATE_RULES)})."
            )
        )
