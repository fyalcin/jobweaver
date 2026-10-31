import json
import unittest
from datetime import date
from unittest import mock

from jobweaver import salary
from jobweaver import scrapers


class SalaryYearlyEurTest(unittest.TestCase):
    """AI-path normalization: (salary_amount, salary_period) -> EUR/year."""

    def test_month_is_multiplied_by_14(self):
        self.assertEqual(salary.salary_yearly_eur(3400, "month"), 47_600)

    def test_year_passthrough(self):
        self.assertEqual(salary.salary_yearly_eur(60_000, "year"), 60_000)

    def test_period_aliases_accepted(self):
        self.assertEqual(salary.salary_yearly_eur(3400, "monthly"), 47_600)
        self.assertEqual(salary.salary_yearly_eur(60_000, "annually"), 60_000)

    def test_unknown_period_is_none(self):
        self.assertIsNone(salary.salary_yearly_eur(3400, "week"))
        self.assertIsNone(salary.salary_yearly_eur(3400, None))
        self.assertIsNone(salary.salary_yearly_eur(3400, ""))

    def test_missing_amount_is_none(self):
        self.assertIsNone(salary.salary_yearly_eur(None, "month"))
        self.assertIsNone(salary.salary_yearly_eur("", "month"))

    def test_string_amount_is_coerced(self):
        self.assertEqual(salary.salary_yearly_eur("3.400", "month"), 47_600)

    def test_bounds_reject_garbage(self):
        self.assertIsNone(salary.salary_yearly_eur(25, "month"))
        self.assertIsNone(salary.salary_yearly_eur(5_000_000, "year"))

    def test_result_is_rounded_int(self):
        self.assertEqual(salary.salary_yearly_eur(2349.59, "month"), 32_894)


class ParseSalaryYearlyTest(unittest.TestCase):
    """Deterministic parsing of raw salary strings (backfill path)."""

    def test_german_monthly_keyword(self):
        self.assertEqual(salary.parse_salary_yearly("ab € 3.400 monatl."), 47_600)

    def test_english_monthly_keywords(self):
        self.assertEqual(salary.parse_salary_yearly("5000 EUR per month"), 70_000)
        self.assertEqual(salary.parse_salary_yearly("€ 4,000.00 gross/month"), 56_000)

    def test_monthly_with_decimals(self):
        self.assertEqual(salary.parse_salary_yearly("€2.349,59"), 32_894)

    def test_yearly_keywords(self):
        self.assertEqual(salary.parse_salary_yearly("80,000 EUR gross a year"), 80_000)
        self.assertEqual(salary.parse_salary_yearly("60.000 € brutto/Jahr"), 60_000)

    def test_magnitude_heuristic_without_period(self):
        # below the threshold -> assumed monthly (x14)
        self.assertEqual(salary.parse_salary_yearly("3000 €"), 42_000)
        self.assertEqual(salary.parse_salary_yearly("€ 5.000,–"), 70_000)
        # at/above the threshold -> assumed yearly
        self.assertEqual(salary.parse_salary_yearly("88.000 €"), 88_000)
        self.assertEqual(salary.parse_salary_yearly("€88,000"), 88_000)
        self.assertEqual(salary.parse_salary_yearly("€45.000"), 45_000)
        self.assertEqual(salary.parse_salary_yearly("€ 53,000"), 53_000)

    def test_range_uses_lower_bound(self):
        self.assertEqual(salary.parse_salary_yearly("€45.000–50.000"), 45_000)

    def test_unknown_salary(self):
        self.assertIsNone(salary.parse_salary_yearly("Not Specified"))
        self.assertIsNone(salary.parse_salary_yearly(""))
        self.assertIsNone(salary.parse_salary_yearly(None))
        self.assertIsNone(salary.parse_salary_yearly("salary negotiable"))

    def test_hourly_wage_is_none(self):
        self.assertIsNone(salary.parse_salary_yearly("€25/hour"))
        self.assertIsNone(salary.parse_salary_yearly("25 € pro Stunde"))

    def test_non_eur_currency_is_none(self):
        self.assertIsNone(salary.parse_salary_yearly("$80,000 a year"))
        self.assertIsNone(salary.parse_salary_yearly("60,000 GBP per year"))


class ParseSalaryYearlyRealWorldTest(unittest.TestCase):
    """Real salary strings that the first parser revision mis-parsed
    (regression: scraped jobs left unknown despite a stated salary)."""

    def test_apprenticeship_year_does_not_beat_month(self):
        self.assertEqual(salary.parse_salary_yearly("€1,396 per month in the 1st year"), 19_544)
        self.assertEqual(salary.parse_salary_yearly("€ 1.200,- monatlich im 1. Lehrjahr"), 16_800)
        self.assertEqual(salary.parse_salary_yearly("1026€ brutto monatlich im ersten Lehrjahr"), 14_364)

    def test_apprenticeship_year_without_month_falls_to_heuristic(self):
        self.assertEqual(salary.parse_salary_yearly("€ 1.200,- im 1. Lehrjahr"), 16_800)

    def test_workload_qualifier_is_not_a_wage_period(self):
        self.assertEqual(
            salary.parse_salary_yearly("€ 2.251 brutto pro Monat auf Basis einer Vollzeitbeschäftigung von 38,5 Stunden/Woche"),
            31_514)
        self.assertEqual(
            salary.parse_salary_yearly("2.251,00 € anteilig je nach Pensum an 38.5 h/Woche"),
            31_514)
        self.assertEqual(
            salary.parse_salary_yearly("€2,026 gross/month (full-time); €1,018.86 gross/month (20 hours/week)"),
            28_364)
        self.assertEqual(
            salary.parse_salary_yearly("€1,975.32 gross/month based on 30 hours"),
            27_654)
        self.assertEqual(
            salary.parse_salary_yearly("€2,251.00 pro rata according to workload based on 38.5 hours/week"),
            31_514)
        self.assertEqual(
            salary.parse_salary_yearly("1.195,00 EUR brutto pro Monat (auf Basis 20h/Woche)"),
            16_730)

    def test_fourteen_payments_qualifier_keeps_monthly(self):
        self.assertEqual(salary.parse_salary_yearly("€1,379 gross per month, paid 14 times annually"), 19_306)
        self.assertEqual(salary.parse_salary_yearly("3,200 € gross per month, paid 14 times per year"), 44_800)
        self.assertEqual(salary.parse_salary_yearly("€3,500 gross per month, 14 times per year"), 49_000)
        # regression: monthly figure >= 5,000 with a distant "times/year" —
        # first parser revision stored the monthly amount as yearly
        self.assertEqual(salary.parse_salary_yearly("EUR 5,014.30/month gross, 14 times/year"), 70_200)

    def test_swiss_apostrophe_thousands(self):
        self.assertEqual(salary.parse_salary_yearly("€ 2’251 brutto pro Monat"), 31_514)

    def test_hourly_wages_stay_none(self):
        self.assertIsNone(salary.parse_salary_yearly("€ 14,67/Stunde"))
        self.assertIsNone(salary.parse_salary_yearly("12,99 € brutto pro Stunde"))


class ProcessJobWithAiSalaryTest(unittest.TestCase):
    """process_job_with_ai derives salary_yearly from the AI's amount+period."""

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_salary_yearly_computed_from_amount_and_period(self, mock_prompt):
        mock_prompt.return_value = json.dumps({
            "german_level": "none", "minimum_salary": "€ 3.400 monatl.",
            "salary_amount": 3400, "salary_period": "month",
            "salary_currency": "EUR", "salary_country": "AT",
            "skills": "x", "summary": "s", "company_contact": None,
        })
        res = scrapers.process_job_with_ai("Wir bieten eine monatliche Entlohnung." * 10)
        self.assertEqual(res["salary_yearly"], 47_600)
        self.assertEqual(res["salary"], "€ 3.400 monatl.")

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_salary_yearly_none_when_no_salary(self, mock_prompt):
        mock_prompt.return_value = json.dumps({
            "german_level": "none", "minimum_salary": "Not Specified",
            "salary_amount": None, "salary_period": None,
            "skills": "x", "summary": "s",
        })
        res = scrapers.process_job_with_ai("Keine Angabe." * 10)
        self.assertIsNone(res["salary_yearly"])

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_salary_yearly_none_on_malformed_ai_values(self, mock_prompt):
        mock_prompt.return_value = json.dumps({
            "german_level": "none", "minimum_salary": "Weird",
            "salary_amount": "much money", "salary_period": "fortnight",
            "skills": "x", "summary": "s",
        })
        with self.assertRaises(ValueError):
            scrapers.process_job_with_ai("Undefinierbar." * 10)


class SelectBackfillUpdatesTest(unittest.TestCase):
    """Recent-jobs selection for the backfill (older jobs stay unknown)."""

    def _job(self, **kw):
        base = {
            "id": "j1", "processed": 1, "is_one_off": 0,
            "date_scraped": "2026-09-01", "salary": "3000 €", "salary_yearly": None,
        }
        base.update(kw)
        return base

    def _run(self, jobs, days=7):
        return salary.select_backfill_updates(jobs, days=days, today=date(2026, 9, 2))

    def test_recent_parsable_job_is_selected(self):
        self.assertEqual(self._run([self._job()]), {"j1": 42_000})

    def test_cutoff_day_is_inclusive(self):
        self.assertEqual(self._run([self._job(date_scraped="2026-08-26")]), {"j1": 42_000})

    def test_older_job_is_excluded(self):
        self.assertEqual(self._run([self._job(date_scraped="2026-08-25")]), {})

    def test_unparsable_salary_is_excluded(self):
        self.assertEqual(self._run([self._job(salary="Not Specified")]), {})

    def test_existing_yearly_is_not_overwritten(self):
        self.assertEqual(self._run([self._job(salary_yearly=12_345)]), {})

    def test_unprocessed_and_one_off_are_excluded(self):
        self.assertEqual(self._run([self._job(processed=0), self._job(is_one_off=1)]), {})

    def test_k_notation_salaries(self):
        self.assertEqual(salary.parse_salary_yearly("85K EUR gross per year, based on 14 salaries"), 85_000)
        self.assertEqual(salary.parse_salary_yearly("49,2k Euros"), 49_200)
        self.assertEqual(salary.parse_salary_yearly("36,4k brutto"), 36_400)
        self.assertEqual(salary.parse_salary_yearly("35k brutto"), 35_000)
        self.assertEqual(salary.parse_salary_yearly("€70k"), 70_000)
        self.assertEqual(salary.parse_salary_yearly("€80-100k"), 80_000)
        self.assertEqual(salary.parse_salary_yearly("53k Jahresbrutto"), 53_000)
        self.assertEqual(salary.parse_salary_yearly("100k€"), 100_000)

    def test_all_jobs_backfill_when_days_is_none(self):
        old_job = self._job(date_scraped="2024-01-01")
        self.assertEqual(salary.select_backfill_updates([old_job], days=None), {"j1": 42_000})

    def test_force_flag_re_evaluates_existing_salary(self):
        job = self._job(salary_yearly=99_999)
        self.assertEqual(salary.select_backfill_updates([job], days=None, force=False), {})
        self.assertEqual(salary.select_backfill_updates([job], days=None, force=True), {"j1": 42_000})


if __name__ == "__main__":
    unittest.main()
