import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import reviewed_documents as documents
import user_assets


class ReviewedDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.multiple(user_assets, BASE_DIR=self.temp.name, PROFILES_DIR=str(Path(self.temp.name, 'profiles')))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cv = 'Synthetic Applicant\nPython engineer\nEXPERIENCE\nResearch lab | 2020-2024\n- Used Python for simulation.\n- Learning SQL basics.'
        path = Path(user_assets.user_profile_dir('synthetic'))
        path.mkdir(parents=True)
        (path / 'CV-plaintext.txt').write_text(self.cv)

    def test_unsupported_claims_are_not_model_output(self):
        store = documents.evidence('synthetic', self.cv)
        with self.assertRaises(ValueError):
            documents.select_facts(store, '{"fact_ids": ["invented Kubernetes expertise"]}')
        with self.assertRaises(ValueError):
            documents.select_facts(store, '{"fact_ids": [], "new_qualification": "expert"}')

    def test_no_notes_or_other_applicant_facts(self):
        store = documents.evidence('synthetic', self.cv + '\n\nRecent Experience & Standing Notes:\nWant to learn Kubernetes')
        self.assertNotIn('Kubernetes', json.dumps(store))
        seen = []
        def model(prompt, **kwargs):
            seen.append(prompt)
            return json.dumps({'fact_ids': list(store['facts'])})
        result = documents.generate({'title': 'Kubernetes expert'}, self.cv, 'synthetic', 'latex', 'cv', 'industry', 'mock', model,
                                    compact=True)
        self.assertNotIn('Kubernetes', result)
        self.assertIn('Learning SQL basics.', result)
        self.assertNotIn('surfflow', seen[0])
        self.assertIn('2020-2024', result)

    def test_edit_preserves_layout_and_chronology(self):
        store = documents.evidence('synthetic', self.cv)
        original = documents.render_cv(store, list(store['facts']), 'latex')
        fewer = [key for key, value in store['facts'].items() if 'SQL' not in value]
        edited = documents.grounded_edit(original, 'Remove the learning bullet', 'synthetic', 'mock',
                                         lambda *args, **kwargs: json.dumps({'fact_ids': fewer}))
        self.assertNotIn('Learning SQL basics.', edited)
        self.assertIn('2020-2024', edited)
        self.assertIn(r'\usepackage[a4paper,margin=19mm]{geometry}', edited)
        with self.assertRaises(ValueError):
            documents.grounded_edit(original.replace('simulation.', 'invented ownership.'), 'Polish', 'synthetic', 'mock', lambda *a, **k: '{}')

    def test_baseline_is_user_specific_and_keeps_presentation(self):
        source = r'''\documentclass[10pt,a4paper]{article}
\begin{document}
{\fontsize{28pt}{32pt}\selectfont\bfseries\color{ink} Synthetic Applicant}\par
\section{Experience}
\begin{itemize}
\item Used \textbf{Python} for reviewed research.
\end{itemize}
\end{document}
'''
        approved = Path(user_assets.user_profile_dir('synthetic'), 'approved')
        approved.mkdir()
        (approved / 'cv.tex').write_text(source)
        store = documents.evidence('synthetic', self.cv)
        rendered = documents.render_cv(store, list(store['facts']), 'latex')
        self.assertEqual(rendered.split('\n', 1)[1], source)
        typst = documents.render_cv(store, list(store['facts']), 'typst')
        self.assertIn('size: 28pt', typst)
        self.assertIn('*Python*', typst)
        self.assertFalse(documents.evidence('other', 'Other Applicant\nDocker expert')['approved'])

    def _letter(self, store, extra=''):
        facts = documents.letter_evidence(store)
        python = [key for key, value in facts.items() if 'Used Python' in value]
        lab = [key for key, value in facts.items() if 'Research lab' in value]
        filler = ' The work required careful checks of every result before anyone else relied on it.'
        return {'salutation': 'Dear Hiring Team,', 'paragraphs': [
            {'text': 'Your role combines simulation with software that colleagues depend on every day.' + filler, 'fact_ids': []},
            {'text': 'At the research lab I used Python for simulation and kept the workflows maintainable.' + filler * 3 + extra, 'fact_ids': python},
            {'text': 'Between 2020 and 2024 the research lab gave me regular practice in explaining results.' + filler * 3, 'fact_ids': lab},
            {'text': 'I would welcome a conversation about the problems your team is working on.' + filler, 'fact_ids': []}]}

    def _model(self, *answers, verdict='supported'):
        """Fake model: a fixed plan, the given letters in order, and a verifier giving `verdict` to sentence 1.

        `calls` collects only the letter prompts; `self.labels` every call's label.
        """
        calls, self.labels = [], []
        facts = documents.letter_evidence(documents.evidence('synthetic', self.cv))
        plan = {'plan': [{'fact_id': key, 'need': 'simulation software', 'framing': value}
                         for key, value in facts.items() if 'Used Python' in value or 'Research lab' in value]}
        def model(prompt, **kwargs):
            self.labels.append(kwargs.get('label'))
            if kwargs.get('label') == 'Letter plan':
                return json.dumps(plan)
            if kwargs.get('label') == 'Letter verification':
                return json.dumps({'verdicts': [{'n': n, 'verdict': verdict if n == 1 else 'supported', 'note': 'test'}
                                                for n in range(1, 40)]})
            calls.append(prompt)
            return json.dumps(answers[min(len(calls), len(answers)) - 1])
        return model, calls

    def test_letter_is_a_complete_checked_letter(self):
        store = documents.evidence('synthetic', self.cv)
        model, calls = self._model(self._letter(store))
        job = {'title': 'Developer', 'company': 'A&B', 'description': 'We use Kubernetes.'}
        result = documents.generate(job, self.cv, 'synthetic', 'latex', 'letter', 'research', 'mock', model)
        self.assertEqual(len(calls), 1)
        for text in ('Dear Hiring Team,', r'A\&B', 'Kind regards', 'used Python for simulation', 'Synthetic Applicant'):
            self.assertIn(text, result)
        self.assertNotIn('I am applying for', result)
        self.assertNotIn('Kubernetes', result)
        self.assertIn('Kubernetes', calls[0])  # the posting is context for the model, never evidence

    def test_letter_rejects_unsupported_claims_and_retries(self):
        store = documents.evidence('synthetic', self.cv)
        bad = self._letter(store, ' I also ran Kubernetes clusters and cut costs by 37 percent.')
        model, calls = self._model(bad, self._letter(store))
        result = documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                                    'research', 'mock', model)
        self.assertEqual(len(calls), 2)
        self.assertIn('"Kubernetes" is not in the approved evidence', calls[1])
        self.assertIn('Numbers not in the approved evidence: 37', calls[1])
        self.assertNotIn('Kubernetes', result)
        bare = self._letter(store)
        bare['paragraphs'][1]['fact_ids'] = [i.removeprefix('fact-') for i in bare['paragraphs'][1]['fact_ids']]
        model, calls = self._model(bare)
        documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter', 'research', 'mock', model)
        self.assertEqual(len(calls), 1)
        model, calls = self._model(bad)
        with self.assertRaisesRegex(ValueError, 'evidence check'):
            documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                               'research', 'mock', model)
        self.assertEqual(len(calls), 3)

    def test_letter_checks_forbidden_terms_ids_structure_and_names(self):
        store = documents.evidence('synthetic', self.cv)
        facts = documents.letter_evidence(store)
        job = {'title': 'Dev', 'company': 'C', 'company_contact': 'Frau Ursula Popp'}
        Path(user_assets.user_profile_dir('synthetic'), 'claim_policy.json').write_text(
            json.dumps({'forbidden_terms': ['simulation expert']}))
        policy = documents.claim_policy('synthetic')
        letter = self._letter(store, ' I am a simulation expert.')
        self.assertTrue(any('forbidden claim' in p for p in documents.check_letter(letter, facts, job, policy)))
        letter = self._letter(store)
        letter['paragraphs'][1]['fact_ids'] = ['invented-id']
        self.assertTrue(any('Unknown fact IDs' in p for p in documents.check_letter(letter, facts, job, policy)))
        letter = self._letter(store)
        letter['paragraphs'] = letter['paragraphs'][:2]
        self.assertTrue(any('paragraphs' in p for p in documents.check_letter(letter, facts, job, policy)))
        letter = self._letter(store, ' It saw seven releases.')
        self.assertTrue(any('Numbers not in the approved evidence: 7' in p for p in documents.check_letter(letter, facts, job, policy)))
        letter = self._letter(store)
        letter['salutation'] = 'Dear Ms. Popp,'
        self.assertEqual(documents.check_letter(letter, facts, job, policy), [])
        letter['salutation'] = 'Dear Ms. Popp and Mr. Popp,'
        self.assertTrue(any('team greeting' in p for p in documents.check_letter(letter, facts, job, policy)))
        letter['salutation'] = 'Dear Mr. Invented,'
        self.assertTrue(any('Salutation' in p for p in documents.check_letter(letter, facts, job, policy)))

    def test_german_letter_uses_german_date_and_closing(self):
        store = documents.evidence('synthetic', self.cv)
        model, calls = self._model(self._letter(store))
        german = 'Wir suchen eine Entwicklerin oder einen Entwickler für unsere Simulationen und die Auswertung der Daten.'
        result = documents.generate({'title': 'Dev', 'company': 'C', 'description': german}, self.cv, 'synthetic',
                                    'typst', 'letter', 'research', 'mock', model)
        self.assertIn('Language: German', calls[0])
        self.assertIn('Mit freundlichen Grüßen', result)
        self.assertEqual(documents.letter_date('de', date(2026, 10, 9)), '9. Oktober 2026')
        self.assertEqual(documents.letter_date('en', date(2026, 10, 9)), '9 October 2026')

    def test_letter_edit_rewrites_through_the_same_check(self):
        store = documents.evidence('synthetic', self.cv)
        model, _ = self._model(self._letter(store))
        original = documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                                      'research', 'mock', model)
        shorter = self._letter(store)
        shorter['paragraphs'][0]['text'] = 'Your role combines simulation with software that colleagues rely on, which is the work I enjoy most.'
        model, calls = self._model(shorter)
        edited = documents.grounded_edit(original, 'Rephrase the first paragraph', 'synthetic', 'mock', model)
        self.assertIn('work I enjoy most', edited)
        self.assertIn('Current letter:', calls[0])
        model, _ = self._model(self._letter(store, ' I administer Kubernetes.'))
        with self.assertRaisesRegex(ValueError, 'evidence check'):
            documents.grounded_edit(original, 'Add Kubernetes', 'synthetic', 'mock', model)
        with self.assertRaisesRegex(ValueError, 'manual changes'):
            documents.grounded_edit(original.replace('Kind regards', 'Cheers'), 'Shorter', 'synthetic', 'mock', model)

    def test_personal_design_needs_opt_in_and_compact_bounds_bullets(self):
        personal = Path(user_assets.user_profile_dir('synthetic'), 'base-cv-tex')
        personal.mkdir()
        model = lambda *a, **k: '{}'
        with self.assertRaisesRegex(ValueError, 'existing design'):
            documents.generate({}, self.cv, 'synthetic', 'latex', 'cv', 'research', 'mock', model)
        personal.rmdir()
        cv = self.cv + '\n' + '\n'.join(f'- Verified result {i}.' for i in range(12))
        store = documents.evidence('synthetic', cv)
        render = documents.generate({}, cv, 'synthetic', 'latex', 'cv', 'industry', 'mock',
                                    lambda *a, **k: json.dumps({'fact_ids': list(store['facts'])}), compact=True)
        self.assertLessEqual(sum(line.startswith('- ') for line in render.splitlines()), 8)
        self.assertIn('2020-2024', render)

    def test_typst_inline_tokens_preserve_header_and_escaped_words(self):
        source = r'''\begin{document}
{\fontsize{11pt}{14pt}\selectfont\textbf{Scientific computing} | Python}
\textbf{Research \& Teaching}\par
\href{https://example.invalid/1}{\#123}
\end{document}'''
        result = documents.render_approved_typst(source)
        self.assertIn('*Scientific computing*', result)
        self.assertIn('*Research & Teaching*', result)
        self.assertIn(r'[\#123]', result)
        self.assertNotIn('TOKEN', result)

    def test_non_string_ids_and_unsupported_translation_report_clear_errors(self):
        store = documents.evidence('synthetic', self.cv)
        with self.assertRaises(ValueError):
            documents.select_facts(store, '{"fact_ids": [{"claim": "Expert"}]}')
        original = documents.render_cv(store, list(store['facts']), 'latex')
        with self.assertRaisesRegex(ValueError, 'manual review'):
            documents.grounded_edit(original, 'Translate to German', 'synthetic', 'mock', lambda *a, **k: '{}')

    # --- 13.10.2026: plan, strength words, verifier, posting language, full CV ---------------------------

    def test_letter_language_follows_the_posting_not_the_german_level(self):
        english = {'german_level': 'B2', 'description': 'We are looking for a developer. German is a plus for our team.'}
        self.assertEqual(documents.letter_language(english), 'en')
        german = {'german_level': 'none', 'description': 'Wir suchen dich für unser Team und die Entwicklung der Software.'}
        self.assertEqual(documents.letter_language(german), 'de')
        self.assertEqual(documents.letter_language({}), 'en')

    def test_cv_keeps_every_bullet_without_a_model_call(self):
        def model(*a, **k):
            raise AssertionError('no model call expected')
        result = documents.generate({'title': 'Dev'}, self.cv, 'synthetic', 'latex', 'cv', 'research', 'mock', model)
        for line in ('Used Python for simulation.', 'Learning SQL basics.', 'Research lab | 2020-2024'):
            self.assertIn(line, result)

    def test_strength_words_need_support_in_the_cited_facts(self):
        """Today's (13.10.2026) overclaims: real work renamed in the posting's vocabulary."""
        facts = {'fact-h': 'Wrote two custom Custodian handlers: one applies staged remedies when calculations fail.',
                 'fact-s': 'Main developer and maintainer of a Python package that generates simulation jobs.'}
        context = 'Senior Software Engineer - Backend Restream'
        problems = documents._strength_problems(
            'To automate test execution, I built custom Custodian handlers.', facts['fact-h'], 'Developer Co', 'P2')
        self.assertTrue(any('"test"' in p for p in problems), problems)
        problems = documents._strength_problems(
            'I focused on architecting distributed execution cores; I designed and maintained surfflow.',
            facts['fact-s'], context, 'P2')
        self.assertEqual(sorted(p.split('"')[1] for p in problems), ['architecting', 'designed'])
        # the job title may be named: "your backend role" is about the posting, not a claim
        self.assertEqual(documents._strength_problems('Your backend role caught my attention.', '', context, 'P1'), [])

    def test_plan_is_checked_and_letters_may_cite_only_planned_facts(self):
        store = documents.evidence('synthetic', self.cv)
        facts = documents.letter_evidence(store)
        python = next(key for key, value in facts.items() if 'Used Python' in value)
        lab = next(key for key, value in facts.items() if 'Research lab' in value)
        policy = {'forbidden_terms': ['test automation'], 'limits': []}
        bad = {'plan': [{'fact_id': python, 'need': 'QA', 'framing': 'test automation in Python'},
                        {'fact_id': 'invented', 'need': 'x', 'framing': 'y'}]}
        _, problems = documents.check_plan(bad, facts, {'title': 'Dev'}, policy)
        self.assertTrue(any('Unknown fact IDs' in p for p in problems))
        self.assertTrue(any('"test automation"' in p for p in problems))
        self.assertTrue(any('says "test"' in p for p in problems))
        letter = self._letter(store)
        problems = documents.check_letter(letter, facts, {'title': 'Dev', 'company': 'C'}, policy, allowed={python})
        self.assertTrue(any('Cite only the planned facts' in p and lab in p for p in problems))

    def test_verifier_rejection_goes_back_to_the_writer(self):
        store = documents.evidence('synthetic', self.cv)
        model, calls = self._model(self._letter(store), verdict='stronger')
        with self.assertRaisesRegex(ValueError, 'evidence check'):
            documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                               'research', 'mock', model)
        self.assertEqual(len(calls), 3)
        self.assertIn('judged stronger: test', calls[1])
        self.assertEqual(self.labels.count('Letter verification'), 3)
        self.assertEqual(self.labels[0], 'Letter plan')

    def test_verifier_fails_closed_and_can_be_switched_off(self):
        store = documents.evidence('synthetic', self.cv)
        letter = self._letter(store)
        def garbage(prompt, **kwargs):
            if kwargs.get('label') == 'Letter verification':
                return 'not json'
            return model(prompt, **kwargs)
        model, _ = self._model(letter)
        with self.assertRaisesRegex(ValueError, 'no usable answer'):
            documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                               'research', 'mock', garbage)
        Path(user_assets.user_profile_dir('synthetic'), 'scraper_config.json').write_text(
            json.dumps({'letter_verifier_model': ''}))
        model, _ = self._model(letter, verdict='stronger')
        documents.generate({'title': 'Dev', 'company': 'C'}, self.cv, 'synthetic', 'latex', 'letter',
                           'research', 'mock', model)
        self.assertNotIn('Letter verification', self.labels)
