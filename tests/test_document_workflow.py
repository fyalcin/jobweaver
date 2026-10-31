"""Offline generation -> real compiler -> edit -> immutable publication."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from jobweaver import reviewed_documents
from jobweaver import server
from jobweaver import user_assets


@unittest.skipUnless(shutil.which('pdflatex') and shutil.which('pdfinfo') and shutil.which('pdftoppm'),
                     'Native LaTeX/Poppler prerequisites missing')
class DocumentWorkflowTest(unittest.TestCase):
    def test_supported_edit_and_failed_rebuild_preserve_last_publication(self):
        with tempfile.TemporaryDirectory() as temp, patch.multiple(
                user_assets, BASE_DIR=temp, PROFILES_DIR=str(Path(temp, 'profiles'))):
            user = {'id': 1, 'username': 'synthetic'}
            cv = 'Synthetic Applicant\nEXPERIENCE\nResearch lab | 2020-2024\n- Used Python for simulations.\n- Learning SQL basics.'
            profile = Path(user_assets.user_profile_dir('synthetic'))
            profile.mkdir(parents=True)
            (profile / 'CV-plaintext.txt').write_text(cv)
            store = reviewed_documents.evidence('synthetic', cv)
            ids = list(store['facts'])
            job = {'id': 'one', 'company': 'Synthetic', 'title': 'Research Software Engineer', 'description': 'Python'}
            with patch('jobweaver.server.db.get_job_by_id', return_value=job), patch(
                    'jobweaver.generators.run_ai_prompt', return_value=json.dumps({'fact_ids': ids})) as model:
                response = server.generate_cv(server.GenerateRequest(job_id='one', modelName='mock', engine='latex'), user=user)
                self.assertIn('/revisions/', response['download_url'])
                self.assertEqual(model.call_count, 0)  # every approved bullet is kept; no selection call
                initial = server.get_job_documents('one', user=user)
                self.assertTrue(initial['cv_pdf_current'])
                self.assertIn('2020-2024', initial['cv_tex'])
                model.return_value = json.dumps({'fact_ids': [key for key, text in store['facts'].items() if 'SQL' not in text]})
                edited = server.ai_edit_job_document('one', server.JobDocAiEditRequest(
                    tex=initial['cv_tex'], instruction='Remove learning SQL'), user=user)
                self.assertTrue(edited['compile_success'])
                self.assertNotIn('Learning SQL', edited['modified_tex'])
                published = server.finalize_job_documents('one', server.JobDocFinalizeRequest(
                    document_type='cv', cv_source=edited['modified_tex']), user=user)
                output = Path(user_assets.user_outputs_dir('synthetic'), 'Synthetic_one')
                pointer = (output / 'publication.json').read_bytes()
                first = output / 'revisions' / published['revision'] / 'CV-Synthetic.pdf'
                good_pdf = first.read_bytes()
                failed = server.compile_job_document('one', server.JobDocCompileRequest(
                    tex=r'\documentclass{article}\begin{document}\DefinitelyInvalidCommand\end{document}'), user=user)
                self.assertFalse(failed['success'])
                with self.assertRaises(HTTPException):
                    server.finalize_job_documents('one', server.JobDocFinalizeRequest(document_type='cv'), user=user)
                self.assertEqual((output / 'publication.json').read_bytes(), pointer)
                self.assertEqual(first.read_bytes(), good_pdf)
