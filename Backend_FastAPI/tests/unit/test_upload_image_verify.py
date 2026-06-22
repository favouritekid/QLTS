"""Security hardening tests (1-PR backend hardening).

Covers:
- #6 — ``_sniff_and_verify_upload`` helper (magic-byte sniff + content-type
  match + PIL structural verify for images). Unit tests on the helper PLUS one
  REAL service-level test through ``upload_priority_evidence_document`` so the
  priority-evidence path (a sibling of ``upload_document``) is exercised end to
  end, not just the helper in isolation.
- #5 — student_code uses ``secrets`` (CSPRNG), not ``random``.

NOTE: PIL ``.verify()`` catches corrupt / fake image structure (valid magic
bytes but broken body), NOT arbitrary polyglot/malware — see helper docstring.
"""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.services import admission_service
from app.utils.exceptions import BadRequest


pytestmark = pytest.mark.unit


def _png_bytes(color: str = "red", size=(2, 2)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload(content: bytes, content_type: str):
    """Minimal UploadFile-like with a real BytesIO stream."""
    return SimpleNamespace(
        file=io.BytesIO(content),
        content_type=content_type,
        filename="test",
    )


# ---------------------------------------------------------------------------
# #6 — helper unit tests (shared by upload_document + priority evidence)
# ---------------------------------------------------------------------------


def test_sniff_and_verify_valid_png_returns_png():
    assert admission_service._sniff_and_verify_upload(
        _upload(_png_bytes(), "image/png")
    ) == "png"


def test_sniff_and_verify_valid_jpeg_returns_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buf, "JPEG")
    assert admission_service._sniff_and_verify_upload(
        _upload(buf.getvalue(), "image/jpeg")
    ) == "jpeg"


def test_sniff_and_verify_corrupt_png_raises():
    # Valid PNG magic header but garbage body → PIL verify() fails.
    corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with pytest.raises(BadRequest, match="Ảnh"):
        admission_service._sniff_and_verify_upload(_upload(corrupt, "image/png"))


def test_sniff_and_verify_clean_pdf_passes():
    # A clean PDF (no active-content markers) passes; PDFs skip PIL.
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>"
    assert admission_service._sniff_and_verify_upload(
        _upload(pdf, "application/pdf")
    ) == "pdf"


def test_sniff_and_verify_pdf_with_active_content_raises():
    # A PDF carrying JavaScript / OpenAction is rejected (malware vector).
    pdf = b"%PDF-1.4\n/OpenAction << /S /JavaScript /JS (app.alert(1)) >>\ntrailer"
    with pytest.raises(BadRequest, match="nội dung động"):
        admission_service._sniff_and_verify_upload(_upload(pdf, "application/pdf"))


def test_sniff_and_verify_pdf_js_substring_not_false_rejected():
    # REGRESSION: the 3-byte "/JS" sequence occurs by chance inside the
    # compressed stream bytes of legitimate scanned PDFs. With /JS dropped from
    # the marker set it must NOT trigger a reject — only the longer real tokens
    # do. (No /JavaScript/OpenAction/Launch/EmbeddedFile present here.)
    pdf = (
        b"%PDF-1.4\n1 0 obj\nstream\n"
        b"random /JS bytes here /JS"
        b"\nendstream\nendobj\ntrailer<<>>"
    )
    assert admission_service._sniff_and_verify_upload(
        _upload(pdf, "application/pdf")
    ) == "pdf"


def test_sniff_and_verify_pdf_launch_still_rejected():
    # The longer markers stay active: /Launch (run external program) is rejected.
    pdf = b"%PDF-1.4\n<< /S /Launch /F (calc.exe) >>\ntrailer<<>>"
    with pytest.raises(BadRequest, match="nội dung động"):
        admission_service._sniff_and_verify_upload(_upload(pdf, "application/pdf"))


def test_sniff_and_verify_oversized_image_raises(monkeypatch):
    # Image-bomb guard: cap monkeypatched low so we don't allocate a real bomb.
    monkeypatch.setattr(admission_service, "_MAX_IMAGE_DIMENSION", 2)
    big = _png_bytes(size=(64, 64))  # 64 > 2 per side → rejected before decode
    with pytest.raises(BadRequest, match="quá lớn"):
        admission_service._sniff_and_verify_upload(_upload(big, "image/png"))


def test_sniff_and_verify_truncated_png_raises():
    # A real PNG cut mid-stream: the header opens fine (lazy read) but
    # Image.verify() detects the truncation. This exercises the .verify()
    # branch specifically — the magic+garbage fixture above trips Image.open()
    # first, so this is the case that pins verify() itself.
    full = _png_bytes(size=(64, 64))
    truncated = full[: len(full) // 2]
    with pytest.raises(BadRequest, match="Ảnh"):
        admission_service._sniff_and_verify_upload(_upload(truncated, "image/png"))


def test_sniff_and_verify_unknown_magic_raises():
    with pytest.raises(BadRequest, match="magic bytes"):
        admission_service._sniff_and_verify_upload(
            _upload(b"not-a-real-file", "image/png")
        )


def test_sniff_and_verify_content_type_mismatch_raises():
    # Real PNG bytes but client claims application/pdf → mismatch raised
    # OUTSIDE the PIL try/except (the except must not swallow it).
    with pytest.raises(BadRequest, match="Content-Type"):
        admission_service._sniff_and_verify_upload(
            _upload(_png_bytes(), "application/pdf")
        )


# ---------------------------------------------------------------------------
# #6 — REAL priority-evidence upload path rejects a corrupt image
# ---------------------------------------------------------------------------


def _make_profile(status="draft", codes=None):
    return SimpleNamespace(
        id=42,
        lead_id=100,
        status=status,
        version=5,
        academic_year=2026,
        priority_object_codes=codes or ["04"],
        priority_object_evidence={},
        priority_resolution_snapshot={},
    )


def _make_actor():
    return SimpleNamespace(id=7, role="officer", full_name="U7", email="u7@e.com")


def _make_catalog_db(has_sub_code=True):
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none = MagicMock(
        return_value=1 if has_sub_code else None
    )

    async def _execute(stmt, *a, **k):
        return catalog_result

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


async def test_priority_evidence_upload_rejects_corrupt_image(monkeypatch):
    """The priority-evidence path passes all guards (status/sub_code/catalog)
    then hits the SHARED helper — a corrupt PNG must be rejected with 400."""
    profile = _make_profile(status="draft", codes=["04"])
    db = _make_catalog_db(has_sub_code=True)

    async def _mock_get_profile(db_, profile_id, current_user):
        return profile

    monkeypatch.setattr(admission_service, "get_profile", _mock_get_profile)

    corrupt_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    upload = _upload(corrupt_png, "image/png")

    with pytest.raises(BadRequest, match="Ảnh"):
        await admission_service.upload_priority_evidence_document(
            db=db,
            profile_id=42,
            sub_code="04",
            file=upload,
            current_user=_make_actor(),
        )


# ---------------------------------------------------------------------------
# #5 — student_code uses CSPRNG (secrets), not random
# ---------------------------------------------------------------------------


def test_student_code_module_uses_secrets_not_random():
    """Pins the CSPRNG swap: admission_service uses ``secrets.randbelow`` and no
    longer uses ``random.randint`` anywhere. The source-level check below also
    catches a FUNCTION-LOCAL ``import random; random.randint(...)`` regression
    that the module-attribute check alone would miss."""
    import inspect
    import secrets as _secrets

    assert admission_service.secrets is _secrets
    assert not hasattr(admission_service, "random")

    src = inspect.getsource(admission_service)
    assert "secrets.randbelow" in src, "student_code generator must use CSPRNG"
    assert "random.randint" not in src, "no insecure random.randint may return"
