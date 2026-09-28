"""Field validation (doc §4). Lengths and ranges are the contract's, and the
PF range is read from the rule book rather than written here."""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from employeeio.services import validation
from employeeio.test_support import seed_rules
from rulebookio.book import rule_book


class IdentityNumberTests(TestCase):
    def test_nid_is_10_13_or_17_digits_after_stripping(self):
        for good in ("1234567890", "1234567890123", "12345678901234567", "123-456-7890"):
            with self.subTest(good=good):
                self.assertTrue(validation.nid_valid(good))
        for bad in ("", "123456789", "12345678901", "123456789012345678"):
            with self.subTest(bad=bad):
                self.assertFalse(validation.nid_valid(bad))

    def test_mobile_and_wallet_are_11_digits_starting_01(self):
        self.assertTrue(validation.mobile_valid("01712-345678"))
        self.assertFalse(validation.mobile_valid("02712345678"))
        self.assertFalse(validation.mobile_valid("0171234567"))
        self.assertFalse(validation.mobile_valid(""))


class ProvidentFundPercentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rules()

    def setUp(self):
        self.book = rule_book(date(2027, 3, 8))

    def test_the_range_comes_from_the_rule_book(self):
        self.assertEqual(str(validation.validate_pf_percent("7", self.book)), "7")
        self.assertEqual(str(validation.validate_pf_percent("8.00", self.book)), "8.00")

    def test_out_of_range_and_nan_are_rejected_with_the_range_stated(self):
        for bad in ("6.99", "8.01", "NaN", "abc", ""):
            with self.subTest(bad=bad), self.assertRaises(ValidationError) as caught:
                validation.validate_pf_percent(bad, self.book)
            self.assertIn("between 7% and 8%", caught.exception.messages[0])


class ReasonTests(TestCase):
    def test_ten_characters_after_trimming(self):
        with self.assertRaises(ValidationError):
            validation.validate_reason("  123456789  ")
        self.assertEqual(validation.validate_reason("  1234567890  "), "1234567890")
