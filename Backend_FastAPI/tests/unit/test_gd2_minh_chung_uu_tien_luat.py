"""GĐ2-0 — luật duyệt minh chứng ưu tiên (C1) ở mức hàm thuần + nối dây (không CSDL).

Ca HTTP thật: ``tests/api/test_gd2_minh_chung_uu_tien_api.py``. Ở đây khoá:
  * vị từ người duyệt (b) = ``reviewer_scope`` của giấy tờ (Admin / Quản lý trong đơn vị), cán bộ phụ trách KHÔNG;
  * luật người tải (a) theo từng ca của dòng giấy;
  * luật đường PUT hồ sơ thường (không đặt / đổi / bỏ trạng thái đã duyệt);
  * dịch vụ duyệt / từ chối ném 409 đúng mã khi người tải là người bấm;
  * nối dây: hai route duyệt / từ chối đi qua ``deps.require_priority_evidence_reviewer``.
"""
from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import document_review_rules as rules
from app.services.admission_document_policy import DocumentActionPolicy

pytestmark = pytest.mark.unit

DON_VI = 14


def _ho_so(don_vi=DON_VI, can_bo=7, trang_thai="submitted"):
    lead = SimpleNamespace(unit_id=don_vi, assigned_officer_id=can_bo)
    return SimpleNamespace(lead=lead, status=trang_thai)


def _nguoi(vai, uid=7, don_vi=DON_VI):
    return SimpleNamespace(id=uid, role=vai, unit_id=don_vi)


# ── (b) ai được duyệt ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "nguoi, mong",
    [
        (_nguoi("admin", 1, None), True),
        (_nguoi("manager", 2, DON_VI), True),
        (_nguoi("manager", 3, 99), False),
        (_nguoi("officer", 7, DON_VI), False),  # cán bộ PHỤ TRÁCH hồ sơ (can_bo=7)
        (_nguoi("accountant", 8, DON_VI), False),
    ],
)
def test_nguoi_duyet_minh_chung_la_admin_va_quan_ly_trong_don_vi(nguoi, mong):
    assert rules.priority_evidence_reviewer(DocumentActionPolicy.for_(_ho_so(), nguoi)) is mong


def test_quan_ly_chua_gan_don_vi_khong_duyet_ho_so_khong_don_vi():
    """Lead không đơn vị + quản lý không đơn vị: ``None == None`` KHÔNG được coi là "trong đơn vị"."""
    assert rules.priority_evidence_reviewer(
        DocumentActionPolicy.for_(_ho_so(don_vi=None), _nguoi("manager", 2, None))
    ) is False


# ── (a) người tải không tự duyệt ───────────────────────────────────────────────────────────────────────────────────
def _giay(file_path="uploads/admissions/1/ut.pdf", uploaded_by=5, unknown=False):
    return SimpleNamespace(file_path=file_path, uploaded_by=uploaded_by, uploaded_by_unknown=unknown)


@pytest.mark.parametrize("hanh_dong", ["verify", "reject"])
@pytest.mark.parametrize(
    "giay, nguoi_bam, mong",
    [
        (None, 5, (True, None)),  # không dòng giấy — duyệt theo hồ sơ giấy
        (_giay(file_path=None), 5, (True, None)),  # dòng không tệp
        (_giay(uploaded_by=5), 6, (True, None)),
        (_giay(uploaded_by=5), 5, (False, rules.OWN_SUBMISSION)),
        (_giay(uploaded_by=None), 6, (False, rules.UNKNOWN_SUBMITTER)),
        (_giay(uploaded_by=5, unknown=True), 6, (False, rules.UNKNOWN_SUBMITTER)),
    ],
)
def test_luat_nguoi_tai(hanh_dong, giay, nguoi_bam, mong):
    q = rules.decide_priority_evidence(
        hanh_dong, actor_id=nguoi_bam, evidence=rules.PriorityEvidenceFacts.from_row(giay)
    )
    assert (q.allowed, q.block_reason) == mong


def test_luat_nguoi_tai_tu_choi_hanh_dong_la():
    with pytest.raises(ValueError):
        rules.decide_priority_evidence("reset", actor_id=1, evidence=rules.PriorityEvidenceFacts.from_row(None))


# ── PUT hồ sơ thường ──────────────────────────────────────────────────────────────────────────────────────────────────
DUYET = {"status": "verified", "verified_by": 9, "document_id": None}
TU_CHOI = {"status": "rejected", "rejected_by": 9, "reject_reason": "x" * 12}
CHO = {"status": "pending"}


@pytest.mark.parametrize(
    "hien_tai, gui, ma_vi_pham",
    [
        ({}, {"04": dict(DUYET)}, ["04"]),  # đặt mới "đã duyệt"
        ({}, {"04": dict(TU_CHOI)}, ["04"]),  # đặt mới "từ chối"
        ({"04": CHO}, {"04": dict(DUYET)}, ["04"]),  # chờ ⇒ đã duyệt
        ({"04": DUYET}, {"04": dict(CHO)}, ["04"]),  # bỏ duyệt
        ({"04": DUYET}, {}, ["04"]),  # bỏ hẳn mục đã duyệt
        ({"04": DUYET}, {"04": dict(DUYET, verified_by=10)}, ["04"]),  # đổi người duyệt
        ({"04": TU_CHOI}, {"04": dict(DUYET)}, ["04"]),  # từ chối ⇒ đã duyệt
        ({"04": DUYET}, {"04": dict(DUYET)}, []),  # gửi lại nguyên
        ({}, {"04": dict(CHO)}, []),  # chỉ "chờ"
        ({"04": CHO}, {}, []),  # bỏ mục "chờ"
        ({"04": DUYET, "06": CHO}, {"04": dict(DUYET), "06": dict(DUYET)}, ["06"]),
    ],
)
def test_put_ho_so_khong_doi_trang_thai_da_duyet(hien_tai, gui, ma_vi_pham):
    _, sai = rules.merge_profile_evidence_update(hien_tai, gui)
    assert sai == ma_vi_pham


def test_put_ho_so_giu_nguyen_ban_luu_cua_muc_da_duyet():
    hien_tai = {"04": dict(DUYET, verified_at="2026-11-01T00:00:00+00:00", paper_only_verification=True)}
    gui = {"04": dict(DUYET, verified_at="2026-12-31T00:00:00+00:00", paper_only_verification=False), "06": dict(CHO)}
    luu, sai = rules.merge_profile_evidence_update(hien_tai, gui)
    assert sai == []
    assert luu == {"04": hien_tai["04"], "06": CHO}


# ── dịch vụ: 409 đúng mã ─────────────────────────────────────────────────────────────────────────────────────────────
def _db(doc_row):
    doc = MagicMock()
    doc.scalar_one_or_none = MagicMock(return_value=doc_row)
    cat = MagicMock()
    cat.all = MagicMock(return_value=[("04", Decimal("1.00"))])

    async def _execute(stmt, *a, **k):
        return doc if "profile_document" in str(stmt).lower() else cat

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _ho_so_dv():
    return SimpleNamespace(
        id=42, lead_id=100, status="submitted", version=5, academic_year=2026,
        priority_object_codes=["04"], priority_object_evidence={}, priority_resolution_snapshot={},
    )


@pytest.mark.parametrize("ham", ["verify_object_evidence", "reject_object_evidence"])
@pytest.mark.parametrize(
    "giay, ma",
    [
        (_giay(uploaded_by=7), "PRIORITY_EVIDENCE_OWN_SUBMISSION"),
        (_giay(uploaded_by=None), "PRIORITY_EVIDENCE_UNKNOWN_SUBMITTER"),
    ],
)
async def test_dich_vu_chan_nguoi_tai_tu_duyet_tu_choi(ham, giay, ma):
    from app.services import priority_override_service as svc

    ho_so = _ho_so_dv()
    nguoi = SimpleNamespace(id=7, role="manager", full_name="Q", email="q@example.com")
    kw = {"document_id": None} if ham == "verify_object_evidence" else {"reject_reason": "Minh chứng không đạt yêu cầu"}
    with pytest.raises(svc.PriorityEvidenceReviewConflict) as e:
        await getattr(svc, ham)(_db(giay), ho_so, sub_code="04", actor=nguoi, expected_version=5, **kw)
    assert e.value.error_code == ma
    assert ho_so.priority_object_evidence == {} and ho_so.version == 5


# ── nối dây ────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "duong",
    [
        "/api/v2/admissions/{profile_id}/priority-objects/{sub_code}/verify",
        "/api/v2/admissions/{profile_id}/priority-objects/{sub_code}/reject",
    ],
)
def test_route_duyet_tu_choi_di_qua_cong_nguoi_duyet(duong):
    from fastapi.routing import APIRoute

    from app.core import deps
    from app.main import fastapi_app

    route = next(r for r in fastapi_app.routes if isinstance(r, APIRoute) and r.path == duong)

    def _goi(dep):
        yield dep.call
        for con in dep.dependencies:
            yield from _goi(con)

    goi = set(_goi(route.dependant))
    assert deps.require_priority_evidence_reviewer in goi, duong
    assert deps.get_admission_for_user in goi, duong


def test_tai_minh_chung_khoa_ho_so_truoc_va_ghi_nguoi_tai():
    from app.services import admission_service

    src = inspect.getsource(admission_service.upload_priority_evidence_document)
    assert src.index("_lock_profile_for_document_write(") < src.index("models.ProfileDocument(")
    assert src.count("uploaded_by=current_user.id") == 1
    assert src.count("doc_row.uploaded_by = current_user.id") == 1
