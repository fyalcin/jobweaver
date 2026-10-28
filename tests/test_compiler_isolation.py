"""Real compiler security checks; only synthetic temporary inputs are used."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from generators import compile_latex


class CompilerIsolationTest(unittest.TestCase):
    def test_missing_isolation_fails_without_an_unsafe_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'document.tex').write_text(r'\documentclass{article}\begin{document}Fictional\end{document}')
            with patch('compiler_sandbox.shutil.which', return_value=None):
                ok, message = compile_latex(temp, 'document.tex', 'document.pdf', temp)
            self.assertFalse(ok)
            self.assertIn('require Bubblewrap', message)
            self.assertFalse(Path(temp, 'document.pdf').exists())

    def test_latex_compiles_owned_inputs_but_cannot_read_an_outside_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / 'document'
            work.mkdir()
            source = work / 'document.tex'
            source.write_text(r'\documentclass{article}\begin{document}Fictional document\end{document}')
            ok, log = compile_latex(str(work), source.name, 'document.pdf', str(work))
            self.assertTrue(ok, log)
            good_pdf = (work / 'document.pdf').read_bytes()
            sentinel = root / 'private.txt'
            sentinel.write_text('SAFE OUTSIDE FILE SENTINEL')
            source.write_text(r'\documentclass{article}\begin{document}\input{' + str(sentinel) + r'}\end{document}')
            ok, log = compile_latex(str(work), source.name, 'document.pdf', str(work))
            self.assertFalse(ok, 'The document read a file outside its mounted inputs')
            self.assertEqual((work / 'document.pdf').read_bytes(), good_pdf)
