"""Amount in words, Bangla numerals and grouping (doc §10).

The prototype hardcoded the words for two amounts and left every other figure
blank on a legal document, and composed Bangla numbers from parts -- which is
wrong for every value from 1 to 99 (41 is একচল্লিশ, not চল্লিশ এক).
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from common.words import (
    BN_1_99,
    amount_in_words,
    both_words,
    format_date,
    format_money,
    format_month_year,
    group_south_asian,
    integer_words,
    to_bangla_numerals,
)


class EnglishWordsTests(SimpleTestCase):
    def test_any_amount_in_lakh_and_crore(self):
        cases = {
            0: "Zero taka only",
            7: "Seven taka only",
            22000: "Twenty two thousand taka only",
            105: "One hundred five taka only",
            125000: "One lakh twenty five thousand taka only",
            1250000: "Twelve lakh fifty thousand taka only",
            35612345: "Three crore fifty six lakh twelve thousand three hundred forty five taka only",
            # Above 99 crore the crore count is itself spelled out.
            12345000000: "One thousand two hundred thirty four crore fifty lakh taka only",
        }
        for amount, words in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(amount_in_words(amount), words)

    def test_paisa_and_sign(self):
        self.assertEqual(amount_in_words("1234.567"),
                         "One thousand two hundred thirty four taka and fifty seven paisa only")
        self.assertEqual(amount_in_words(Decimal("-500")), "Minus five hundred taka only")

    def test_a_float_never_reaches_it(self):
        with self.assertRaises(TypeError):
            amount_in_words(22000.5)


class BanglaWordsTests(SimpleTestCase):
    def test_one_to_ninety_nine_is_a_table_not_a_composition(self):
        self.assertEqual(len(BN_1_99), 100)
        self.assertEqual(integer_words(41, "bn"), "একচল্লিশ")
        self.assertEqual(integer_words(99, "bn"), "নিরানব্বই")

    def test_any_amount(self):
        cases = {
            0: "শূন্য টাকা মাত্র",
            22000: "বাইশ হাজার টাকা মাত্র",
            125000: "এক লক্ষ পঁচিশ হাজার টাকা মাত্র",
            35612345: "তিন কোটি ছাপ্পান্ন লক্ষ বারো হাজার তিনশত পঁয়তাল্লিশ টাকা মাত্র",
        }
        for amount, words in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(amount_in_words(amount, "bn"), words)
        self.assertEqual(amount_in_words("10.50", "bn"), "দশ টাকা পঞ্চাশ পয়সা মাত্র")

    def test_both_languages_together(self):
        self.assertEqual(both_words(22000), {"en": "Twenty two thousand taka only", "bn": "বাইশ হাজার টাকা মাত্র"})


class NumeralsAndGroupingTests(SimpleTestCase):
    def test_south_asian_grouping(self):
        self.assertEqual(group_south_asian(1234567), "12,34,567")
        self.assertEqual(group_south_asian(999), "999")
        self.assertEqual(group_south_asian("100000"), "1,00,000")
        self.assertEqual(group_south_asian("1234.5"), "1,234.50")
        self.assertEqual(group_south_asian(-1234567), "-12,34,567")

    def test_bangla_numerals_are_applied_after_formatting(self):
        self.assertEqual(format_money(1234567), "৳ 12,34,567")
        self.assertEqual(format_money(1234567, "bn"), "৳ ১২,৩৪,৫৬৭")
        self.assertEqual(to_bangla_numerals("EMP-0142"), "EMP-০১৪২")
        self.assertEqual(format_date(date(2027, 3, 8), "bn"), "০৮/০৩/২০২৭")

    def test_a_year_is_a_label_never_grouped(self):
        self.assertEqual(format_month_year("2026-02"), "February 2026")
        self.assertEqual(format_month_year(date(2026, 2, 1), "bn"), "ফেব্রুয়ারি ২০২৬")
