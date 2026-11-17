"""Codex 68 — MỘT chỗ xoá tệp giấy thường chỉ xoá đường dẫn ĐÃ XÁC THỰC nằm trong ``uploads/admissions/{profile_id}``.

Đường dẫn lấy từ CSDL mà sai lệch (sang hồ sơ khác, có ``..``, tuyệt đối ra ngoài) ⇒ KHÔNG xoá (fail closed).
"""
import pytest

from app.services.document_file_guard import (
    DELETED,
    REFUSED_OUTSIDE_PROFILE_DIR,
    delete_document_file_unless_evidence,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def cay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for rel in ("uploads/admissions/1/hop-le.pdf", "uploads/admissions/2/cua-ho-so-khac.pdf", "bi-mat.txt"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return tmp_path


@pytest.mark.parametrize(
    "duong_dan",
    [
        "uploads/admissions/2/cua-ho-so-khac.pdf",  # thư mục hồ sơ KHÁC
        "uploads/admissions/1/../2/cua-ho-so-khac.pdf",  # leo ra bằng ..
        "bi-mat.txt",  # ngoài uploads
    ],
)
def test_duong_dan_ngoai_thu_muc_ho_so_thi_khong_xoa(cay, duong_dan):
    assert delete_document_file_unless_evidence(duong_dan, frozenset(), profile_id=1) == REFUSED_OUTSIDE_PROFILE_DIR
    assert (cay / "uploads/admissions/2/cua-ho-so-khac.pdf").exists()
    assert (cay / "bi-mat.txt").exists()


def test_duong_dan_tuyet_doi_ra_ngoai_thi_khong_xoa(cay):
    assert (
        delete_document_file_unless_evidence(str(cay / "bi-mat.txt"), frozenset(), profile_id=1)
        == REFUSED_OUTSIDE_PROFILE_DIR
    )
    assert (cay / "bi-mat.txt").exists()


def test_duong_dan_hop_le_trong_thu_muc_ho_so_thi_xoa(cay):
    assert delete_document_file_unless_evidence("uploads/admissions/1/hop-le.pdf", frozenset(), profile_id=1) == DELETED
    assert not (cay / "uploads/admissions/1/hop-le.pdf").exists()
