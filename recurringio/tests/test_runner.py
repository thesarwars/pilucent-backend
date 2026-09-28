"""Tests for the recurring generation job.

The scheduling maths is already covered in ``test_scheduling``; these cover the
things only the runner decides — when an occurrence is due, what happens to
missed ones, that a retry cannot double-post, and that one broken template
cannot stall the rest.

Document generation itself is stubbed: what is under test is the driver, not the
importers (which have their own tests).
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from accounts.models import ChartOfAccount
from companyio.models import Company
from customerio.models import Customer
from purchaseio.models import Purchase
from supplierio.models import Supplier

from recurringio.choices import (
    RecurringOccurrenceStatusChoices as OccStatus,
    RecurringTemplateStatusChoices as TplStatus,
)
from recurringio.models import RecurringOccurrence, RecurringTemplate, RecurringTemplateLine
from recurringio.services import runner, scheduling

GEN = "recurringio.services.runner.generate_from_template"


def _purchase(company, supplier):
    """A real Purchase -- the runner assigns it to a genuine FK."""
    return Purchase.objects.create(
        company=company, supplier=supplier, date=date(2026, 1, 1)
    )


class RunnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="Landlord", display_name="Landlord LLC", company=cls.company
        )
        cls.account = ChartOfAccount.objects.create(
            code="6000", title="Rent", company=cls.company
        )

    def _template(self, **overrides):
        defaults = dict(
            name="Monthly rent",
            txn_type="BILL",
            template_type="SCHEDULED",
            status=TplStatus.ACTIVE,
            company=self.company,
            supplier=self.supplier,
            frequency="MONTHLY",
            interval_count=1,
            day_mode="DAY_OF_MONTH",
            day_of_month=1,
            start_date=date(2026, 1, 1),
            end_type="NONE",
            next_run_date=date(2026, 1, 1),
        )
        defaults.update(overrides)
        template = RecurringTemplate.objects.create(**defaults)
        RecurringTemplateLine.objects.create(
            template=template, company=self.company, line_type="CATEGORY",
            amount="1000.00", charter_account=self.account,
        )
        return template

    # ---- due-ness --------------------------------------------------------

    def test_nothing_fires_before_the_occurrence_date(self):
        template = self._template()
        with patch(GEN) as gen:
            runner.run_template(template, today=date(2025, 12, 31))
        gen.assert_not_called()
        self.assertEqual(RecurringOccurrence.objects.count(), 0)

    def test_create_days_in_advance_fires_early(self):
        template = self._template(create_days_in_advance=5)
        with patch(GEN, return_value=_purchase(self.company, self.supplier)) as gen:
            runner.run_template(template, today=date(2025, 12, 27))
        gen.assert_called_once()
        self.assertEqual(
            RecurringOccurrence.objects.get().occurrence_date, date(2026, 1, 1)
        )

    def test_paused_template_does_not_fire(self):
        template = self._template(status=TplStatus.ENDED)
        with patch(GEN) as gen:
            runner.run_template(template, today=date(2026, 6, 1))
        gen.assert_not_called()

    def test_unscheduled_template_never_fires(self):
        template = self._template(template_type="UNSCHEDULED", frequency=None)
        with patch(GEN) as gen:
            runner.run_template(template, today=date(2026, 6, 1))
        gen.assert_not_called()

    # ---- the schedule actually advances ----------------------------------

    def test_firing_advances_the_schedule_and_counts_it(self):
        template = self._template()
        with patch(GEN, return_value=_purchase(self.company, self.supplier)):
            runner.run_template(template, today=date(2026, 1, 1))

        template.refresh_from_db()
        self.assertEqual(template.previous_run_date, date(2026, 1, 1))
        self.assertEqual(template.next_run_date, date(2026, 2, 1))
        self.assertEqual(template.occurrences_generated, 1)

    def test_schedule_end_marks_the_template_ended(self):
        template = self._template(end_type="BY_DATE", end_date=date(2026, 1, 15))
        with patch(GEN, return_value=_purchase(self.company, self.supplier)):
            runner.run_template(template, today=date(2026, 1, 1))

        template.refresh_from_db()
        self.assertIsNone(template.next_run_date)
        self.assertEqual(template.status, TplStatus.ENDED)

    # ---- catch-up --------------------------------------------------------

    def test_missed_occurrences_inside_the_window_all_fire(self):
        template = self._template(frequency="DAILY", next_run_date=date(2026, 1, 1))
        with patch(GEN, return_value=_purchase(self.company, self.supplier)) as gen:
            runner.run_template(template, today=date(2026, 1, 5), catch_up_days=30)

        # 1st through 5th inclusive.
        self.assertEqual(gen.call_count, 5)
        self.assertEqual(
            RecurringOccurrence.objects.filter(status=OccStatus.GENERATED).count(), 5
        )

    def test_occurrences_older_than_the_window_are_skipped_not_dropped(self):
        template = self._template(frequency="DAILY", next_run_date=date(2026, 1, 1))
        with patch(GEN, return_value=_purchase(self.company, self.supplier)) as gen:
            runner.run_template(template, today=date(2026, 3, 1), catch_up_days=30)

        skipped = RecurringOccurrence.objects.filter(status=OccStatus.SKIPPED)
        self.assertTrue(skipped.exists())
        # Skipped ones are recorded with a reason -- visible, not silently lost.
        self.assertIn("catch-up window", skipped.first().error_detail)
        # And they did not post documents.
        self.assertLess(gen.call_count, 60)

    def test_skipped_occurrences_do_not_consume_the_after_count_budget(self):
        # AFTER_COUNT means "produce N documents"; a skip produced none.
        template = self._template(
            frequency="DAILY", next_run_date=date(2026, 1, 1),
            end_type="AFTER_COUNT", end_after_occurrences=3,
        )
        with patch(GEN, return_value=_purchase(self.company, self.supplier)):
            runner.run_template(template, today=date(2026, 3, 1), catch_up_days=30)

        template.refresh_from_db()
        self.assertEqual(template.occurrences_generated, 3)

    # ---- idempotency & failure isolation ---------------------------------

    def test_rerunning_the_same_date_does_not_double_post(self):
        template = self._template()
        with patch(GEN, return_value=_purchase(self.company, self.supplier)) as gen:
            runner.fire_occurrence(template, date(2026, 1, 1))
            runner.fire_occurrence(template, date(2026, 1, 1))

        gen.assert_called_once()
        self.assertEqual(RecurringOccurrence.objects.count(), 1)

    def test_a_failed_firing_is_recorded_and_does_not_block_the_schedule(self):
        template = self._template()
        with patch(GEN, side_effect=RuntimeError("no bank account")):
            runner.run_template(template, today=date(2026, 1, 1))

        occurrence = RecurringOccurrence.objects.get()
        self.assertEqual(occurrence.status, OccStatus.FAILED)
        self.assertIn("no bank account", occurrence.error_detail)

        template.refresh_from_db()
        self.assertEqual(template.next_run_date, date(2026, 2, 1))  # not wedged
        self.assertEqual(template.occurrences_generated, 0)  # produced nothing

    def test_one_broken_template_does_not_stall_the_others(self):
        broken = self._template(name="broken")
        healthy = self._template(name="healthy")

        def _explode(template, *a, **kw):
            if template.pk == broken.pk:
                raise RuntimeError("boom")
            return _purchase(self.company, self.supplier)

        with patch(GEN, side_effect=_explode):
            summary = runner.run_due(self.company, today=date(2026, 1, 1))

        self.assertEqual(summary["templates_examined"], 2)
        healthy.refresh_from_db()
        self.assertEqual(healthy.occurrences_generated, 1)

    # ---- reminders -------------------------------------------------------

    def test_reminder_template_records_a_reminder_and_posts_nothing(self):
        template = self._template(template_type="REMINDER", remind_days_before=2)
        with patch(GEN) as gen:
            runner.run_template(template, today=date(2025, 12, 30))

        gen.assert_not_called()
        occurrence = RecurringOccurrence.objects.get()
        self.assertEqual(occurrence.status, OccStatus.REMINDED)
        self.assertIsNotNone(occurrence.reminded_at)

    # ---- company-local dates ---------------------------------------------

    def test_timezone_accepts_every_shape_production_actually_stores(self):
        """``Company.time_zone`` is free text and prod holds three shapes.

        Only the bare IANA name worked before; the JSON blob the timezone picker
        writes and the bare city name both fell back to the server zone. For a
        Hawaii company that meant UTC-10 being treated as UTC+6.
        """
        picker_blob = (
            '{"value":"Pacific/Honolulu","label":"(GMT-10:00) Hawaii",'
            '"offset":-10,"abbrev":"HAST"}'
        )
        self.assertEqual(str(runner.resolve_timezone(picker_blob)), "Pacific/Honolulu")
        self.assertEqual(str(runner.resolve_timezone("Asia/Dhaka")), "Asia/Dhaka")
        self.assertEqual(str(runner.resolve_timezone("Dhaka")), "Asia/Dhaka")

    def test_timezone_falls_back_on_unusable_values(self):
        for bad in (None, "", "Not/AZone", "{not json", '{"value":""}'):
            self.assertEqual(
                str(runner.resolve_timezone(bad)), settings.TIME_ZONE, f"for {bad!r}"
            )

    def test_json_blob_timezone_drives_the_date_not_the_server_zone(self):
        # The end-to-end consequence: company_today must follow the blob.
        self.company.time_zone = '{"value":"Pacific/Midway","label":"(GMT-11:00)"}'
        self.company.save(update_fields=["time_zone"])
        behind = runner.company_today(self.company)

        self.company.time_zone = '{"value":"Pacific/Kiritimati","label":"(GMT+14:00)"}'
        self.company.save(update_fields=["time_zone"])
        ahead = runner.company_today(self.company)

        self.assertGreaterEqual((ahead - behind).days, 1)

    def test_today_follows_the_company_timezone(self):
        self.company.time_zone = "Pacific/Kiritimati"  # UTC+14
        self.company.save(update_fields=["time_zone"])
        ahead = runner.company_today(self.company)

        self.company.time_zone = "Pacific/Midway"  # UTC-11
        self.company.save(update_fields=["time_zone"])
        behind = runner.company_today(self.company)

        self.assertGreaterEqual((ahead - behind).days, 1)

    def test_unusable_timezone_falls_back_instead_of_crashing(self):
        self.company.time_zone = "Not/AZone"
        self.company.save(update_fields=["time_zone"])
        self.assertIsInstance(runner.company_today(self.company), date)


class PauseResumeTests(TestCase):
    """Pausing stops a template firing; resuming skips what it missed."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.supplier = Supplier.objects.create(
            first_name="L", display_name="L LLC", company=cls.company
        )

    def _template(self, **overrides):
        defaults = dict(
            name="Rent", txn_type="BILL", template_type="SCHEDULED",
            status=TplStatus.ACTIVE, company=self.company, supplier=self.supplier,
            frequency="MONTHLY", interval_count=1, day_mode="DAY_OF_MONTH",
            day_of_month=1, start_date=date(2026, 1, 1), end_type="NONE",
            next_run_date=date(2026, 1, 1),
        )
        defaults.update(overrides)
        return RecurringTemplate.objects.create(**defaults)

    def test_paused_template_is_not_picked_up_by_the_job(self):
        self._template(status=TplStatus.PAUSED)
        self.assertEqual(runner.due_templates(self.company).count(), 0)

    def test_resuming_skips_what_was_missed_rather_than_back_filling(self):
        # Paused in January, resumed in June: the pause was meant to skip those
        # occurrences, so it must not post five back-dated bills.
        template = self._template(status=TplStatus.PAUSED)
        template.status = TplStatus.ACTIVE
        template.next_run_date = scheduling.next_on_or_after(template, date(2026, 6, 15))
        self.assertEqual(template.next_run_date, date(2026, 7, 1))

    def test_next_on_or_after_respects_the_end_condition(self):
        template = self._template(end_type="BY_DATE", end_date=date(2026, 3, 1))
        self.assertIsNone(scheduling.next_on_or_after(template, date(2026, 6, 1)))


class WhenToChargeTests(TestCase):
    """ACCEPT must never charge a customer who has not accepted."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Acme")
        cls.customer = Customer.objects.create(
            first_name="N", display_name="Northwind", company=cls.company
        )

    def _template(self, **overrides):
        defaults = dict(
            name="Retainer", txn_type="PAYMENT", template_type="SCHEDULED",
            status=TplStatus.ACTIVE, company=self.company, customer=self.customer,
            frequency="MONTHLY", interval_count=1, day_mode="DAY_OF_MONTH",
            day_of_month=1, start_date=date(2026, 1, 1), end_type="NONE",
            next_run_date=date(2026, 1, 1), when_to_charge="ACCEPT",
        )
        defaults.update(overrides)
        return RecurringTemplate.objects.create(**defaults)

    def test_unaccepted_template_expires_instead_of_charging(self):
        # Charging someone who never accepted is exactly what the setting
        # prevents; expiring beats recording a FAILED occurrence every run.
        template = self._template()
        with patch(GEN) as gen:
            runner.run_template(template, today=date(2026, 1, 1))

        gen.assert_not_called()
        template.refresh_from_db()
        self.assertEqual(template.status, TplStatus.EXPIRED)
        self.assertEqual(RecurringOccurrence.objects.count(), 0)

    def test_it_does_not_expire_before_the_start_date(self):
        template = self._template()
        runner.run_template(template, today=date(2025, 12, 1))
        template.refresh_from_db()
        self.assertEqual(template.status, TplStatus.ACTIVE)

    def test_accepted_template_fires_normally(self):
        template = self._template(acceptance_status="ACCEPTED")
        with patch(GEN, return_value=None):
            runner.run_template(template, today=date(2026, 1, 1))

        template.refresh_from_db()
        self.assertEqual(template.status, TplStatus.ACTIVE)
        self.assertEqual(RecurringOccurrence.objects.count(), 1)

    def test_future_templates_are_unaffected(self):
        template = self._template(when_to_charge="FUTURE")
        with patch(GEN, return_value=None):
            runner.run_template(template, today=date(2026, 1, 1))
        self.assertEqual(RecurringOccurrence.objects.count(), 1)
