"""The rules in force on a date.

`rule_book(as_of)` is the only way a BD module reads a statutory constant
(doc §1.1). It resolves, per family, the published set whose effective window
contains `as_of`, and hands out `RuleValue`s that carry their own confidence,
citation and name. Lookups throw on anything missing: a silent fallback is how
the wrong year's slabs reach a payslip.

`require_production_safe()` is the gate of doc §1.5. A value below VERIFIED
may be displayed and may drive a simulation; it may not reach a released
payslip, an issued register or a filed return, and the gate throws, naming
the rule, rather than warning.
"""

from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from common import clock
from common.money import to_decimal

from .choices import PRODUCTION_SAFE, RuleFamilyChoices, RuleSetStatusChoices
from .models import RuleSet

RULE_KEYS = {"value", "confidence"}


class RuleBookError(LookupError):
    pass


class NoRuleSetInForce(RuleBookError):
    pass


class UnknownRule(RuleBookError):
    pass


class RuleNotProductionSafe(Exception):
    def __init__(self, rule_value):
        self.rule = rule_value.rule
        self.confidence = rule_value.confidence
        super().__init__(
            f"Rule {rule_value.rule} is {rule_value.confidence.lower()} and may not "
            "reach a released payslip, an issued register or a filed return. It "
            "must be signed off against the Bangla gazette first."
            if rule_value.value is not None
            else f"Rule {rule_value.rule} has no value. It must come from the "
            "gazette before it can reach a released payslip, an issued register "
            "or a filed return."
        )


@dataclass(frozen=True)
class RuleValue:
    rule: str
    value: Any
    confidence: str
    citation: str | None
    note: str | None

    @property
    def production_safe(self):
        return self.confidence in PRODUCTION_SAFE and self.value is not None

    @property
    def decimal(self):
        if self.value is None:
            raise UnknownRule(f"Rule {self.rule} has no value.")
        return to_decimal(self.value)

    def as_dict(self):
        return {
            "rule": self.rule,
            "value": self.value,
            "confidence": self.confidence,
            "citation": self.citation,
            "note": self.note,
        }


def require_production_safe(rule_value):
    if not rule_value.production_safe:
        raise RuleNotProductionSafe(rule_value)
    return rule_value.value


class RuleSetView:
    def __init__(self, rule_set):
        self.rule_set = rule_set
        self.family = rule_set.family
        self.version = rule_set.version
        self.source = rule_set.source
        self.effective_from = rule_set.effective_from
        self.effective_to = rule_set.effective_to

    def _name(self, path):
        return f"{self.family.lower()}.{self.version}.{path}"

    def get(self, path):
        node = self.rule_set.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise UnknownRule(f"No rule {self._name(path)} in the rule book.")
            node = node[part]
        if not isinstance(node, dict) or not RULE_KEYS <= node.keys():
            raise UnknownRule(f"{self._name(path)} is a group of rules, not a rule.")
        return RuleValue(
            rule=self._name(path),
            value=node["value"],
            confidence=node["confidence"],
            citation=node.get("citation"),
            note=node.get("note"),
        )

    def value(self, path):
        return self.get(path).value

    def decimal(self, path):
        return self.get(path).decimal

    def citation(self, name):
        """A statutory citation by topic, e.g. `pf` -> `Bangladesh Labour Act 2006, s.264`."""
        citations = self.rule_set.data.get("citations", {})
        if name not in citations:
            raise UnknownRule(f"No citation {self._name('citations.' + name)} in the rule book.")
        return citations[name]


class RuleBook:
    """The rule sets in force on one date, one per family, resolved lazily."""

    def __init__(self, as_of, jurisdiction="BD"):
        self.as_of = as_of
        self.jurisdiction = jurisdiction
        self._sets = {}

    def family(self, family):
        if family not in self._sets:
            self._sets[family] = RuleSetView(
                resolve(family, self.as_of, self.jurisdiction)
            )
        return self._sets[family]

    @property
    def tax(self):
        return self.family(RuleFamilyChoices.TAX)

    @property
    def labour(self):
        return self.family(RuleFamilyChoices.LABOUR)


def resolve(family, as_of, jurisdiction="BD"):
    found = (
        RuleSet.objects.filter(
            jurisdiction=jurisdiction,
            family=family,
            status=RuleSetStatusChoices.PUBLISHED,
            effective_from__lte=as_of,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of))
        .order_by("-effective_from")
        .first()
    )
    if found is None:
        raise NoRuleSetInForce(
            f"No published {jurisdiction} {family.lower()} rule set is in force on "
            f"{as_of}. Seed or publish one (manage.py seed_bd_rule_book)."
        )
    return found


def rule_book(as_of=None, jurisdiction="BD"):
    return RuleBook(as_of or clock.today(), jurisdiction)
