import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from jobweaver import server
from jobweaver import user_assets
from jobweaver.document_artifacts import record_build, matching_build, decode_pdf
from pdf_fixture import pdf_bytes


class DocumentBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.multiple(user_assets, BASE_DIR=self.temp.name, PROFILES_DIR=str(Path(self.temp.name, 'profiles')))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = {'id': 1, 'username': 'synthetic'}
        job = patch('jobweaver.server.db.get_job_by_id', return_value={'id': 'one', 'company': 'Synthetic'})
        job.start()
        self.addCleanup(job.stop)
        self.draft = Path(user_assets.user_drafts_dir('synthetic'), 'Synthetic_one')
        self.draft.mkdir(parents=True)
        self.source = r'\documentclass{article}\begin{document}Synthetic\end{document}'
        (self.draft / 'cv_one.tex').write_text(self.source)
        self.pdf = self.draft / 'cv_draft_one.pdf'
        self.pdf.write_bytes(pdf_bytes())
        record_build(self.pdf, self.source, 'latex')

    def test_dirty_or_missing_build_cannot_finalize(self):
        with self.assertRaises(HTTPException) as error:
            server.finalize_job_documents('one', server.JobDocFinalizeRequest(document_type='cv', cv_source='dirty'), user=self.user)
        self.assertEqual(error.exception.status_code, 409)
        (self.draft / 'cv_one.tex').write_text('changed')
        with self.assertRaises(HTTPException):
            server.finalize_job_documents('one', server.JobDocFinalizeRequest(document_type='cv'), user=self.user)

    def test_publication_is_an_immutable_bundle(self):
        response = server.finalize_job_documents('one', server.JobDocFinalizeRequest(document_type='cv', cv_source=self.source), user=self.user)
        self.assertIn('/revisions/', response['cv_url'])
        out = Path(user_assets.user_outputs_dir('synthetic'), 'Synthetic_one')
        bundle = out / 'revisions' / response['revision']
        manifest = json.loads((bundle / 'manifest.json').read_text())
        self.assertEqual(manifest['cv']['source_hash'], __import__('jobweaver.document_artifacts', fromlist=['digest']).digest(self.source))
        self.assertEqual((bundle / 'cv_one.tex').read_text(), self.source)
        self.assertEqual((bundle / 'CV-Synthetic.pdf').read_bytes(), pdf_bytes())

    def test_invalid_upload_does_not_replace_good_source_or_pdf(self):
        with self.assertRaises(HTTPException):
            server.compile_job_document('one', server.JobDocCompileRequest(tex='changed', pdf_base64=base64.b64encode(b'NOT PDF').decode()), user=self.user)
        self.assertEqual((self.draft / 'cv_one.tex').read_text(), self.source)
        self.assertEqual(self.pdf.read_bytes(), pdf_bytes())
        with self.assertRaises(ValueError):
            decode_pdf('a' * (17 * 1024 * 1024))

    def test_tampered_pdf_invalidates_binding(self):
        self.pdf.write_bytes(pdf_bytes() + b'changed')
        self.assertIsNone(matching_build(self.pdf, self.source))

    def test_engine_switch_keeps_old_source_but_selects_new_source(self):
        (self.draft / 'cv_one.typ').write_text('#set text(10pt)\nOLD')
        response = server.compile_job_document('one', server.JobDocCompileRequest(
            tex=self.source, pdf_base64=base64.b64encode(pdf_bytes()).decode()), user=self.user)
        self.assertTrue(response['success'])
        loaded = server.get_job_documents('one', user=self.user)
        self.assertEqual(loaded['cv_engine'], 'latex')
        self.assertEqual(loaded['cv_tex'], self.source)
        self.assertTrue((self.draft / 'cv_one.typ').exists())

    def test_library_conflict_preserves_source_and_build(self):
        folder = Path(user_assets.user_documents_dir('synthetic'), 'one')
        folder.mkdir(parents=True)
        (folder / 'document.tex').write_text(self.source)
        with self.assertRaises(HTTPException) as error:
            server.update_studio_document('one', server.UpdateDocumentRequest(
                content='overwritten', expected_source_hash='not-current'), user=self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((folder / 'document.tex').read_text(), self.source)
