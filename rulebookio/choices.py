from django.db import models


class RuleFamilyChoices(models.TextChoices):
    # Income tax: one set per income year (July to June).
    TAX = "TAX", "Income tax"
    # Labour law: one set per amendment, open-ended until superseded.
    LABOUR = "LABOUR", "Labour law"


class RuleSetStatusChoices(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class ConfidenceChoices(models.TextChoices):
    """How far a statutory value may travel (doc §1.5).

    DRAFTED -> settings only. CORROBORATED -> simulation. VERIFIED -> production.
    LIVE -> released. DISPUTED is a value whose sources disagree; like DRAFTED
    and CORROBORATED it may be shown and simulated but never released.
    """

    DRAFTED = "DRAFTED", "Drafted"
    CORROBORATED = "CORROBORATED", "Corroborated"
    DISPUTED = "DISPUTED", "Disputed"
    VERIFIED = "VERIFIED", "Verified"
    LIVE = "LIVE", "Live"


PRODUCTION_SAFE = {ConfidenceChoices.VERIFIED, ConfidenceChoices.LIVE}
