"""Test helpers for the rule book. Nothing here is imported by production code."""

from io import StringIO

from django.core.management import call_command


def seed_rules():
    call_command("seed_bd_rule_book", stdout=StringIO())


def _sign_off(node):
    if isinstance(node, dict):
        if {"value", "confidence"} <= node.keys():
            node["confidence"] = "VERIFIED"
            return
        for child in node.values():
            _sign_off(child)


def verify_every_rule():
    """Every rule signed off against the gazette, as a released document needs."""
    from .models import RuleSet

    for rs in RuleSet.objects.all():
        _sign_off(rs.data)
        rs.save(update_fields=["data"])
