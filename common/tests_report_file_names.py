"""Two PDFs generated in the same second must not be the same file.

`get_pdf` and `generate_pdf_direct` both built their working path as
``media/reports/{label}-{timestamp}.pdf`` with second granularity and no company
in it. Two people in **different companies** generating the same kind of
document within one second raced on a single path:

1. request A writes the file
2. request B overwrites it
3. A opens the path and attaches **B's PDF** to A's own FileItem
4. A removes the file
5. B opens the path and gets FileNotFoundError

Step 3 is a cross-tenant document leak and is silent. Step 5 is a 500, and is
what made this test suite unable to run two processes at once.
"""

from django.test import TestCase

from common.django_rest.helpers.file_helpers import (
    REPORT_WORKING_DIR,
    report_file_names,
)


class Company:
    def __init__(self, name):
        self.name = name


class ReportFileNameTests(TestCase):
    STAMP = "31th august 2026, 12:54:53"

    def test_two_companies_in_the_same_second_get_different_paths(self):
        """The collision itself. Same label, same timestamp, different tenants."""
        _, first = report_file_names(Company("Acme"), "invoice", self.STAMP)
        _, second = report_file_names(Company("Beta"), "invoice", self.STAMP)
        self.assertNotEqual(first, second)

    def test_even_one_company_twice_in_the_same_second_differs(self):
        """Two users of the same company collided too -- rarer, same outcome."""
        company = Company("Acme")
        _, first = report_file_names(company, "invoice", self.STAMP)
        _, second = report_file_names(company, "invoice", self.STAMP)
        self.assertNotEqual(first, second)

    def test_the_working_path_stays_under_the_reports_directory(self):
        _, path = report_file_names(Company("Acme"), "invoice", self.STAMP)
        self.assertTrue(path.startswith(REPORT_WORKING_DIR))
        self.assertTrue(path.endswith(".pdf"))

    def test_the_stored_name_carries_the_company(self):
        """What a person downloads should say whose it is."""
        name, _ = report_file_names(Company("Acme Ltd"), "invoice", self.STAMP)
        self.assertIn("Acme Ltd", name)
        self.assertIn("invoice", name)
        self.assertIn(self.STAMP, name)
        self.assertTrue(name.endswith(".pdf"))

    def test_the_stored_name_is_not_the_working_path(self):
        """Kept apart on purpose: one is readable, the other unique."""
        name, path = report_file_names(Company("Acme"), "invoice", self.STAMP)
        self.assertNotIn(name, path)

    def test_a_missing_company_still_yields_a_usable_name(self):
        """`get_pdf` leaves `company` None when called without a request."""
        name, path = report_file_names(None, "invoice", self.STAMP)
        self.assertTrue(name.endswith(".pdf"))
        self.assertNotIn("None", name)
        self.assertTrue(path.endswith(".pdf"))
