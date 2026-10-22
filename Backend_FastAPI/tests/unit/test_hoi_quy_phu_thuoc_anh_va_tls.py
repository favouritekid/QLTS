"""Hồi quy cho các chỗ mã dùng Pillow / qrcode / certifi — khoá hành vi qua các lần nâng phụ thuộc.

Ra đời khi nâng Pillow 12.3.0 → 13.0.0 và certifi 2025.10.5 → 2026.10.19 (21-10-2026). Lúc ấy
``test_upload_image_verify.py`` — tệp DUY NHẤT import PIL — không thuộc tier PR nào, nên CI xanh không nói gì
về Pillow. Tệp này phủ đúng những chỗ mã chạm tới thư viện ảnh, trực tiếp hoặc qua thư viện khác:

- ``_sniff_and_verify_upload`` (Image.open / width / height / verify): con trỏ tệp phải về 0 ở MỌI nhánh, vì
  người gọi chép tệp bằng ``copyfileobj`` từ vị trí hiện tại — con trỏ lệch ⇒ ghi ra tệp cụt mà không báo lỗi.
  Ảnh quá chiều THẬT (10001 px), không monkeypatch hằng số.
- ``upload_priority_evidence_document`` với helper THẬT: byte ghi ra đĩa = byte gửi lên.
- ``admission_pdf_service._load_asset`` (reportlab ImageReader → Pillow) trên 3 asset thật — hàm này NUỐT lỗi và
  trả None, nên giấy báo vẫn phát được nhưng thiếu letterhead/chữ ký mà không test nào đỏ.
- ``vietqr.render_qr_png`` và ``mfa_service.generate_qr_code_base64`` (qrcode → Pillow).
- certifi: bundle nạp được, xác minh TLS BẬT, requests/httpx dùng đúng bundle.

Thông điệp assert mang nhãn ``CON_TRO:`` / ``BYTE_GHI_RA:`` để kiểm ngược đối chiếu được ĐÚNG chỗ bắt.
"""
from __future__ import annotations

import base64
import io
import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import admission_service
from app.utils.exceptions import BadRequest

pytestmark = pytest.mark.unit


def _anh(fmt: str, size=(64, 48), color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def _nua_dau(b: bytes) -> bytes:
    return b[: len(b) // 2]


def _upload(content: bytes, content_type: str):
    return SimpleNamespace(file=io.BytesIO(content), content_type=content_type, filename="x")


# ---------------------------------------------------------------- helper: con trỏ tệp ở MỌI nhánh

@pytest.mark.parametrize("fmt,ct,kind", [("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpeg")])
def test_helper_anh_hop_le_tra_kind_va_con_tro_ve_0(fmt, ct, kind):
    up = _upload(_anh(fmt), ct)
    up.file.seek(17)  # con trỏ lệch sẵn — helper phải tự về đầu rồi trả về 0
    assert admission_service._sniff_and_verify_upload(up) == kind
    vt = up.file.tell()
    assert vt == 0, "CON_TRO: sau verify con trỏ ở %d, phải là 0" % vt


_CA_XAU = [
    ("png_cat_cut", _nua_dau(_anh("PNG", size=(64, 64))), "image/png", "Ảnh"),
    ("jpeg_cat_cut", _nua_dau(_anh("JPEG", size=(64, 64))), "image/jpeg", "Ảnh"),
    ("jpeg_rac", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg", "Ảnh"),
    ("png_than_rac", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png", "Ảnh"),
    ("png_khai_jpeg", _anh("PNG"), "image/jpeg", "Content-Type"),
    ("jpeg_khai_png", _anh("JPEG"), "image/png", "Content-Type"),
    ("png_qua_chieu_that", _anh("PNG", size=(10001, 1)), "image/png", "quá lớn"),
]


@pytest.mark.parametrize("ten,content,ct,khop", _CA_XAU, ids=[c[0] for c in _CA_XAU])
def test_helper_anh_xau_bi_tu_choi_va_con_tro_ve_0(ten, content, ct, khop):
    up = _upload(content, ct)
    with pytest.raises(BadRequest, match=khop):
        admission_service._sniff_and_verify_upload(up)
    vt = up.file.tell()
    assert vt == 0, "CON_TRO: %s — sau khi từ chối con trỏ ở %d, phải là 0" % (ten, vt)


def test_helper_anh_dung_bien_10000px_van_qua():
    # Biên trên đúng hằng số: 10000 px một chiều phải QUA (chỉ > 10000 mới bị chặn).
    up = _upload(_anh("PNG", size=(10000, 1)), "image/png")
    assert admission_service._sniff_and_verify_upload(up) == "png"
    vt = up.file.tell()
    assert vt == 0, "CON_TRO: ảnh biên 10000 px, con trỏ ở %d, phải là 0" % vt


# ---------------------------------------------------------------- đường bằng chứng ưu tiên, helper THẬT

@pytest.mark.parametrize("fmt,ct,duoi", [("PNG", "image/png", ".png"), ("JPEG", "image/jpeg", ".jpg")])
async def test_bang_chung_uu_tien_ghi_dung_byte_qua_helper_that(monkeypatch, tmp_path, fmt, ct, duoi):
    from tests.unit.test_phase_e4_pr2_priority_evidence import _make_actor, _make_profile, _make_upload_db_full
    from app.repositories.admission_repository import AdmissionRepository

    profile = _make_profile(status="draft", codes=["04"], evidence={})

    async def _get_profile(db_, pid, user):
        return profile

    async def _populate(db, p, u, documents=None):
        return None

    async def _all_docs(self, pid):
        return []

    # KHÔNG giả _sniff_document_signature / _sniff_and_verify_upload: đường thật tới Pillow.
    monkeypatch.setattr(admission_service, "get_profile", _get_profile)
    monkeypatch.setattr(admission_service, "_populate_response_fields", _populate)
    monkeypatch.setattr(AdmissionRepository, "get_all_documents", _all_docs)
    monkeypatch.chdir(tmp_path)

    data = _anh(fmt, size=(80, 60), color="blue")
    _, finalize = await admission_service.upload_priority_evidence_document(
        db=_make_upload_db_full(existing_doc=None), profile_id=42, sub_code="04", file=_upload(data, ct),
        current_user=_make_actor("officer"),
    )
    await finalize(True)
    ra = [f for f in (tmp_path / "uploads" / "admissions" / "42").iterdir() if not f.name.startswith(".staging.")]
    assert len(ra) == 1 and ra[0].suffix == duoi, ra
    ghi = ra[0].read_bytes()
    assert ghi == data, "BYTE_GHI_RA: ghi %d byte, gửi %d byte" % (len(ghi), len(data))


# ---------------------------------------------------------------- PDF giấy báo: ImageReader của reportlab → Pillow

def test_asset_giay_bao_nap_duoc_va_dung_kich_thuoc():
    from app.services import admission_pdf_service as pdf

    goc = Path(admission_service.__file__).resolve().parent.parent / "assets" / "letters"
    for ten in ("header.png", "footer.png", "signature.png"):
        p = goc / ten
        kq = pdf._load_asset(str(p))
        assert kq is not None, "%s: _load_asset trả None — ImageReader hỏng bị nuốt im lặng" % ten
        _, w, h = kq
        with Image.open(p) as im:
            assert (w, h) == (float(im.width), float(im.height)), ten


def test_pdf_giay_bao_nhung_du_ba_anh():
    pypdf = pytest.importorskip("pypdf")
    from app.services import admission_pdf_service as pdf
    from tests.unit.test_enrollment_letter_pdf import _base_data

    pdf._ASSET_CACHE.clear()  # nạp lại qua Pillow, không lấy bản đệm của test trước
    trang = pypdf.PdfReader(io.BytesIO(pdf.render_enrollment_letter(_base_data()))).pages
    anh = []

    def _duyet(res):
        res = res.get_object()
        if "/XObject" not in res:
            return
        xo = res["/XObject"].get_object()
        for k in xo:
            o = xo[k].get_object()
            if o.get("/Subtype") == "/Image":
                anh.append((int(o["/Width"]), int(o["/Height"])))
            elif o.get("/Subtype") == "/Form" and "/Resources" in o:
                _duyet(o["/Resources"])

    for pg in trang:
        _duyet(pg["/Resources"])
    assert len(trang) == 1
    assert len(anh) >= 3, "letterhead + footer + chữ ký phải được nhúng, thấy %r" % anh


# ---------------------------------------------------------------- QR (qrcode → Pillow)

def test_qr_vietqr_va_mfa_giai_ma_duoc():
    from app.services import mfa_service
    from app.utils import vietqr

    png = vietqr.render_qr_png("00020101021153037045405100006304ABCD")
    with Image.open(io.BytesIO(png)) as im:
        im.verify()
    with Image.open(io.BytesIO(png)) as im:
        assert im.format == "PNG" and im.width == im.height and im.width > 0
    uri = mfa_service.generate_qr_code_base64("otpauth://totp/QLTS:kiem?secret=JBSWY3DPEHPK3PXP&issuer=QLTS")
    assert uri.startswith("data:image/png;base64,")
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as im:
        assert im.format == "PNG" and im.width == im.height and im.width > 0


# ---------------------------------------------------------------- certifi: nạp bundle, KHÔNG tắt xác minh

def test_certifi_nap_bundle_va_tls_bat_xac_minh():
    import certifi
    import httpx
    import requests.utils

    p = certifi.where()
    ctx = ssl.create_default_context(cafile=p)
    n = ctx.cert_store_stats()["x509_ca"]
    assert n > 50, "bundle certifi chỉ có %d CA" % n
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert requests.utils.DEFAULT_CA_BUNDLE_PATH == p
    hc = httpx.create_ssl_context()
    assert hc.verify_mode == ssl.CERT_REQUIRED and hc.check_hostname
    assert hc.cert_store_stats()["x509_ca"] == n, "httpx phải nạp cùng bundle certifi"
