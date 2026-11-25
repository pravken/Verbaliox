"""Text pasted from Word or a PDF brings characters XML does not allow; the Word export took them."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import io
import unittest

try:
    from docx import Document

    from app.exporter import export_docx
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    export_docx = None


@unittest.skipIf(export_docx is None, "app dependencies not installed")
class DocxControlCharsTest(unittest.TestCase):
    def test_a_vertical_tab_does_not_break_the_export(self):
        data = export_docx({"title": "План\x0bвстречи", "speakers": {"S": {"name": "Анна"}},
                            "segments": [{"start": 0, "end": 2, "speaker": "S", "text": "раз\x0cдва"}]})
        text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        self.assertIn("План встречи", text)
        self.assertIn("раз два", text)

    def test_word_is_not_loaded_at_the_start(self):
        """Audit В22: python-docx and lxml were imported with the app (about 0.1 s of every start); they are
        loaded at the first Word export."""
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        code = "import sys, app.export_build, app.exporter; print('docx' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip().splitlines()[-1:], ["False"], out.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
