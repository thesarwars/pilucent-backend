"""Test helpers for the rule book. Nothing here is imported by production code."""

from io import StringIO

from django.core.management import call_command


def seed_rules():
    call_command("seed_bd_rule_book", stdout=StringIO())
