import tempfile
import unittest
from pathlib import Path

from converter_core.mathpix import process_pdf


class Response:
    def __init__(self, payload=None, text="", content=b"", headers=None):
        self._payload = payload or {}
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class Session:
    def __init__(self):
        self.deleted = False

    def post(self, *args, **kwargs):
        return Response({"pdf_id": "job-1"})

    def get(self, url, **kwargs):
        if url.endswith(".mmd"):
            return Response(text=r"Inline \(x^2\) and \[\frac{a}{b}\]")
        return Response({"status": "completed"})

    def delete(self, *args, **kwargs):
        self.deleted = True
        return Response()


class MathpixTests(unittest.TestCase):
    def test_document_flow_and_remote_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF mock")
            session = Session()
            result = process_pdf(pdf, root / "out", "id", "key", max_pages=3, session=session)
            self.assertIn("$x^2$", result.markdown)
            self.assertTrue(session.deleted)


if __name__ == "__main__":
    unittest.main()

