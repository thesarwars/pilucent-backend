from django.db import models
from django.db.models import Q

from common.models import BaseModelWithUID

from .choices import RuleFamilyChoices, RuleSetStatusChoices


class RuleSet(BaseModelWithUID):
    """One version of one family of statutory rules, in force for a window.

    `data` is a tree. A leaf that is a rule is an object carrying `value`,
    `confidence`, `citation` and `note`; everything above a leaf is a plain
    object grouping them. Each set is stored whole rather than as a delta on
    its predecessor, so a figure computed under it recomputes on exactly the
    law that applied, whatever is published later.
    """

    jurisdiction = models.CharField(max_length=8, default="BD", db_index=True)
    family = models.CharField(max_length=20, choices=RuleFamilyChoices.choices)
    version = models.CharField(max_length=40)
    effective_from = models.DateField()
    # Inclusive. Null means in force until a later set supersedes it.
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=RuleSetStatusChoices.choices,
        default=RuleSetStatusChoices.PUBLISHED,
    )
    source = models.CharField(max_length=255)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ("jurisdiction", "family", "-effective_from")
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "family", "version"],
                name="rulebookio_ruleset_unique_version",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gte=models.F("effective_from")),
                name="rulebookio_ruleset_window_not_inverted",
            ),
        ]

    def __str__(self):
        return f"{self.jurisdiction} {self.family} {self.version}"
