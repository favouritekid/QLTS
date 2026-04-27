"""ADM-019 regression: document upload signature sniff.

Helper ``_sniff_document_signature`` is the gate that closes two gaps in
the original upload code:
  1. ``UploadFile.content_type`` is fully client-controlled.
  2. Whitelist on filename extension fell back to ``.bin`` for unknowns
     instead of rejecting them.

These unit tests pin the magic-byte detection contract for the file
types we support (PDF, JPEG, PNG) and confirm that everything else
returns ``None`` so the caller can raise ``BadRequest``.
"""

import io

import pytest

from app.services.admission_service import _sniff_document_signature


pytestmark = pytest.mark.unit


class TestSniffDocumentSignature:
    def test_detects_pdf(self):
        stream = io.BytesIO(b"%PDF-1.7\n... rest of pdf bytes ...")
        assert _sniff_document_signature(stream) == "pdf"
        # Stream cursor is restored so caller can write the file out.
        assert stream.read(5) == b"%PDF-"

    def test_detects_jpeg(self):
        stream = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
        assert _sniff_document_signature(stream) == "jpeg"

    def test_detects_png(self):
        stream = io.BytesIO(b"\x89PNG\r\n\x1a\n<rest>")
        assert _sniff_document_signature(stream) == "png"

    def test_rejects_html_disguised_as_pdf(self):
        """The original bug: an HTML upload with ``content_type=application/pdf``
        would pass content-type check + ``.bin`` fallback. Magic-byte sniff
        catches it."""
        stream = io.BytesIO(b"<!DOCTYPE html><html>...")
        assert _sniff_document_signature(stream) is None

    def test_rejects_executable(self):
        # PE/COFF "MZ" header
        stream = io.BytesIO(b"MZ\x90\x00\x03\x00")
        assert _sniff_document_signature(stream) is None

    def test_rejects_zip_or_office_xml(self):
        # ZIP-based files (docx/xlsx/pptx) start with PK\x03\x04
        stream = io.BytesIO(b"PK\x03\x04 ...")
        assert _sniff_document_signature(stream) is None

    def test_rejects_empty_stream(self):
        stream = io.BytesIO(b"")
        assert _sniff_document_signature(stream) is None

    def test_short_stream_with_partial_pdf_header_rejected(self):
        # Less than the full ``%PDF-`` magic — must NOT match.
        stream = io.BytesIO(b"%PDF")  # missing trailing dash
        assert _sniff_document_signature(stream) is None
