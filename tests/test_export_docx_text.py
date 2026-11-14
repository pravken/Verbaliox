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


if __name__ == "__main__":
    unittest.main()
