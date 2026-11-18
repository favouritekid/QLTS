"""GĐ1b — migration ``gd1b20261117``: phép kiểm đường dẫn / trần khi băm tệp bằng chứng (Codex 71 điểm 1).

Migration không nhập mã ứng dụng nên CHÉP phép kiểm ``admission_service._resolve_under`` và trần tải lên. CLAUDE.md §7: hai
bản phải có test khoá bằng nhau — ở đây so từng ca (kể cả ``..``, tuyệt đối, tiền tố tên thư mục, symlink trong / ngoài).
"""
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

from app.services import admission_service, document_evidence_service

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI


def _mig():
    p = GOC / "alembic" / "versions" / "gd1b20261117_bulk_verify_documents.py"
    spec = importlib.util.spec_from_file_location("_gd1b_mig_duong_dan", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_tran_doc_cua_migration_bang_tran_tai_bang_chung():
    assert _mig().EVIDENCE_MAX_BYTES == document_evidence_service.EVIDENCE_MAX_BYTES


@pytest.fixture
def ho_so(tmp_path):
    """Thư mục hồ sơ thật dưới ``GOC/uploads/admissions`` + một tệp ngoài (``tmp_path``) + hai symlink."""
    pid = 990107
    thu_muc = GOC / "uploads" / "admissions" / str(pid)
    thu_muc.mkdir(parents=True, exist_ok=True)
    ngoai = tmp_path / "ngoai.pdf"
    ngoai.write_bytes(b"x")
    (thu_muc / "trong.pdf").write_bytes(b"y")
    (thu_muc / "lk-ra-ngoai.pdf").symlink_to(ngoai)
    (thu_muc / "lk-trong.pdf").symlink_to(thu_muc / "trong.pdf")
    try:
        yield pid, thu_muc, ngoai
    finally:
        for t in ("trong.pdf", "lk-ra-ngoai.pdf", "lk-trong.pdf"):
            (thu_muc / t).unlink(missing_ok=True)
        thu_muc.rmdir()


def test_kiem_duong_dan_cua_migration_cung_ket_qua_voi_resolve_under(ho_so, monkeypatch):
    pid, thu_muc, ngoai = ho_so
    monkeypatch.chdir(GOC)  # ``_resolve_under`` resolve theo thư mục làm việc (= /app trong ảnh); migration theo APP_ROOT
    m = _mig()
    assert m.APP_ROOT == GOC
    ca = [
        "uploads/admissions/%d/trong.pdf" % pid,
        "uploads/admissions/%d/con/b.pdf" % pid,
        "uploads/admissions/%d/../990108/a.pdf" % pid,
        "uploads/admissions/%d/../../admissions/%d/trong.pdf" % (pid, pid),
        "uploads/admissions/%d1/a.pdf" % pid,  # tiền tố tên thư mục hồ sơ khác
        "uploads/admissions/%d" % pid,
        str(thu_muc / "trong.pdf"),
        str(ngoai),
        "/etc/passwd",
        "uploads/admissions/%d/lk-ra-ngoai.pdf" % pid,
        "uploads/admissions/%d/lk-trong.pdf" % pid,
    ]
    ket_qua = {}
    for duong in ca:
        mig = m._evidence_target(pid, duong)
        app = admission_service._resolve_under("uploads/admissions/%d" % pid, duong)
        assert (None if mig is None else str(mig)) == app, duong
        ket_qua[duong] = mig is not None
    # Mốc tuyệt đối (không chỉ "bằng nhau"): đúng các ca này phải BỊ CHẶN / ĐƯỢC QUA.
    assert ket_qua == {
        ca[0]: True, ca[1]: True, ca[2]: False, ca[3]: True, ca[4]: False, ca[5]: True,
        ca[6]: True, ca[7]: False, ca[8]: False, ca[9]: False, ca[10]: True,
    }


def test_bam_co_tran_dung_doc_khi_vuot(tmp_path, monkeypatch):
    m = _mig()
    monkeypatch.setattr(m, "EVIDENCE_MAX_BYTES", 8)
    dung = tmp_path / "dung.bin"
    dung.write_bytes(b"12345678")
    assert m._sha256_capped(dung) == hashlib.sha256(b"12345678").hexdigest()
    vuot = tmp_path / "vuot.bin"
    vuot.write_bytes(b"123456789")
    assert m._sha256_capped(vuot) is None
    assert os.path.getsize(vuot) == 9
