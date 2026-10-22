import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import generators


class FreshBuildTest(unittest.TestCase):
    def test_failed_rebuild_preserves_pdf_source_and_diagnostics(self):
        for engine in ('latex', 'typst'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                filename = 'document.' + ('tex' if engine == 'latex' else 'typ')
                source = Path(temp, filename)
                source.write_text('invalid synthetic source')
                pdf = Path(temp, 'document.pdf')
                pdf.write_bytes(b'previous good bytes')
                function = generators.compile_latex if engine == 'latex' else generators.compile_typst
                with patch('generators.subprocess.run', return_value=subprocess.CompletedProcess([], 1, b'', b'compiler error')):
                    ok, log = function(temp, filename, 'document.pdf', temp)
                self.assertFalse(ok)
                self.assertIn('compiler error', log)
                self.assertEqual(pdf.read_bytes(), b'previous good bytes')
                self.assertTrue(source.exists())
                self.assertTrue(Path(temp, 'document.build.log').exists())

    def test_exit_zero_without_pdf_is_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'document.tex').write_text('synthetic source')
            with patch('generators.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
                self.assertFalse(generators.compile_studio_document(temp)[0])

    def test_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'document.tex').write_text('synthetic source')
            with patch('generators.subprocess.run', side_effect=subprocess.TimeoutExpired('pdflatex', 45)):
                self.assertFalse(generators.compile_studio_document(temp)[0])

    def test_escape_does_not_escape_its_own_commands(self):
        self.assertEqual(generators.escape_latex('C:\\Users & 50%'), r'C:\textbackslash{}Users \& 50\%')

    def test_preview_page_count_shrinks_without_old_pages(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'preview-1.png').write_bytes(b'old page one')
            Path(temp, 'preview-2.png').write_bytes(b'old page two')
            def render(command, cwd, **kwargs):
                Path(cwd, 'preview-1.png').write_bytes(b'new page one')
                return subprocess.CompletedProcess(command, 0, b'', b'')
            with patch('generators.subprocess.run', side_effect=render):
                self.assertEqual(generators.convert_pdf_to_images('synthetic.pdf', temp, 'preview'), ['preview-1.png'])
            self.assertEqual(Path(temp, 'preview-1.png').read_bytes(), b'new page one')
            self.assertFalse(Path(temp, 'preview-2.png').exists())
