import json
import unittest
from unittest import mock

from jobweaver import scrapers


REWE_NOISY = """Marktmanager:in Stellvertretung | Jobs bei REWE Group
Gelber Hintergrund, davor eine lächelnde Frau mit einem Obstkorb in der Hand
Sprache auswählen
german
english
croatian
serbian
slovakian
czech
hungarian
turkish
italian
slovenian
Information zur Übersetzung
Die Übersetzung erfolgt automatisch über Google Translate. Keine Gewähr für Richtigkeit oder Vollständigkeit.
Marktmanager:in Stellvertretung
(weiblich/männlich/divers)

Standort: Wien

Das sind Ihre Aufgaben:
- Sie verantworten die Führung des Marktes
Ihre Qualifikationen:
- Abgeschlossene Berufsausbildung
- Führungsverantwortung

Wir verwenden cookies, um Ihr Erlebnis zu verbessern.
Jetzt bewerben"""


class CleanJobDescriptionNoiseTest(unittest.TestCase):
    def test_rewe_style_noise_is_removed(self):
        cleaned = scrapers.clean_job_description_noise(REWE_NOISY)
        # noise gone
        self.assertNotIn("Sprache auswählen", cleaned)
        self.assertNotIn("Google Translate", cleaned)
        self.assertNotIn("croatian", cleaned)
        self.assertNotIn("cookies", cleaned.lower())
        # content kept
        self.assertIn("Standort: Wien", cleaned)
        self.assertIn("Abgeschlossene Berufsausbildung", cleaned)
        self.assertIn("(weiblich/männlich/divers)", cleaned)

    def test_lone_language_word_line_is_kept(self):
        text = "Wir arbeiten international.\ngerman\nAls Sprache am Arbeitsplatz ist Deutsch erforderlich."
        # 'german' here is surrounded by content lines (no run) -> must survive
        cleaned = scrapers.clean_job_description_noise(text)
        self.assertIn("german", cleaned)

    def test_over_stripping_falls_back_to_original(self):
        text = "Sprache auswählen\ngerman\nenglish"  # everything is noise
        self.assertEqual(scrapers.clean_job_description_noise(text), text)

    def test_empty_input_untouched(self):
        self.assertEqual(scrapers.clean_job_description_noise(""), "")
        self.assertIsNone(scrapers.clean_job_description_noise(None))


class ProcessJobWithAiCleanupTest(unittest.TestCase):
    """process_job_with_ai pre-cleans deterministically, asks the AI for a
    removal-only cleanup, and falls back to the pre-cleaned original when the
    AI's version is missing or over-eagerly shortened."""

    def setUp(self):
        self.noisy = REWE_NOISY

    @staticmethod
    def _ai_response(cleaned):
        return json.dumps({
            "german_level": "none", "minimum_salary": "Not Specified",
            "skills": "Not Specified", "summary": "Sums.",
            "company_contact": None, "cleaned_description": cleaned,
        })

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_good_ai_cleanup_is_used(self, mock_prompt):
        good = scrapers.clean_job_description_noise(self.noisy)
        mock_prompt.return_value = self._ai_response(good)

        res = scrapers.process_job_with_ai(self.noisy)

        # the prompt carried the pre-cleaned (noise-free) description
        sent = mock_prompt.call_args[0][0]
        self.assertNotIn("Sprache auswählen", sent)
        self.assertIn("cleaned_description", sent)
        self.assertEqual(res["description"], good.strip())
        self.assertEqual(res['raw_description'], self.noisy)

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_over_eager_cleanup_falls_back_to_original(self, mock_prompt):
        mock_prompt.return_value = self._ai_response("Nur eine Kurzfassung.")

        res = scrapers.process_job_with_ai(self.noisy)

        self.assertIn("Standort: Wien", res["description"])  # pre-cleaned original kept
        self.assertNotIn("Sprache auswählen", res["description"])

    @mock.patch.object(scrapers, "run_ai_prompt")
    def test_missing_cleanup_key_falls_back(self, mock_prompt):
        mock_prompt.return_value = json.dumps({
            "german_level": "none", "minimum_salary": "x", "skills": "y", "summary": "s",
        })

        res = scrapers.process_job_with_ai(self.noisy)

        self.assertIn("Standort: Wien", res["description"])
        self.assertNotIn("Sprache auswählen", res["description"])


if __name__ == "__main__":
    unittest.main()
