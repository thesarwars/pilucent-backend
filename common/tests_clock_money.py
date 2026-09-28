"""One clock and one money path for the BD modules (doc §4.5, §9, §10.1).

`timezone.now()` scattered through modules made tenure and eligibility figures
irreproducible in tests; floats and ad-hoc rounding produced three coexisting
money conventions. These are the single replacements.
"""

import os
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from common import clock
from common.money import apply_rate, money_str, round_to_paisa, round_to_taka, to_decimal


class ClockTests(SimpleTestCase):
    def tearDown(self):
        clock.unfreeze()

    def test_frozen_wins_and_nests(self):
        with clock.frozen("2027-03-08"):
            self.assertEqual(clock.today(), date(2027, 3, 8))
            with clock.frozen(date(2020, 1, 1)):
                self.assertEqual(clock.today_iso(), "2020-01-01")
            self.assertEqual(clock.today(), date(2027, 3, 8))

    def test_the_fixture_date_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {clock.ENV_VAR: "2027-03-08"}):
            self.assertEqual(clock.today(), date(2027, 3, 8))


class MoneyTests(SimpleTestCase):
    def test_a_float_is_refused(self):
        with self.assertRaises(TypeError):
            to_decimal(0.1)

    def test_fractions_and_strings_are_exact(self):
        self.assertEqual(apply_rate(900000, "1/3"), Decimal(300000))
        self.assertEqual(apply_rate(900000, "0.3333"), Decimal("299970.0000"))
        self.assertEqual(to_decimal("0.10"), Decimal("0.10"))

    def test_named_rounding_points_round_half_up(self):
        self.assertEqual(round_to_taka("2.5"), Decimal("3"))
        self.assertEqual(round_to_paisa("0.125"), Decimal("0.13"))

    def test_wire_format_is_a_two_place_string(self):
        self.assertEqual(money_str(Decimal("400000")), "400000.00")
        self.assertIsNone(money_str(None))
