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


# ── (a) người tải / người nhận không tự duyệt / từ chối; không rõ ⇒ cam kết + lý do (câu 1, 2, 3 owner 19-11) ──────────
def _tep(uploaded_by=5, unknown=False):
    return SimpleNamespace(id=11, file_path="uploads/admissions/1/ut.pdf", uploaded_by=uploaded_by,
                           uploaded_by_unknown=unknown)


def _giay(paper_by=5, unknown=False):
    """Bản giấy đã ghi nhận (dòng KHÔNG tệp) — người nhận = ``paper_submitted_by``."""
    return SimpleNamespace(id=12, file_path=None, paper_submitted_by=paper_by, paper_submitted_by_unknown=unknown,
                           uploaded_by=None, uploaded_by_unknown=False)


@pytest.mark.parametrize("hanh_dong", ["verify", "reject"])
@pytest.mark.parametrize(
    "dong, nguoi_bam, mong",
    [
        # (cho phép, mã chặn, cần cam kết)
        (_tep(uploaded_by=5), 6, (True, None, False)),
        (_tep(uploaded_by=5), 5, (False, rules.OWN_SUBMISSION, False)),
        (_tep(uploaded_by=None), 6, (True, None, True)),  # tệp không rõ người tải
        (_tep(uploaded_by=5, unknown=True), 6, (True, None, True)),
        (_giay(paper_by=5), 6, (True, None, False)),
        (_giay(paper_by=5), 5, (False, rules.OWN_SUBMISSION, False)),  # người nhận giấy tự duyệt / từ chối
        (_giay(paper_by=None), 6, (True, None, True)),  # giấy không rõ người nhận
        (_giay(paper_by=5, unknown=True), 6, (True, None, True)),
        (None, 6, (True, None, True)),  # chưa ghi nhận giấy, chưa có tệp ⇒ không rõ người nhận
    ],
)
def test_luat_nguoi_nhan(hanh_dong, dong, nguoi_bam, mong):
    q = rules.decide_priority_evidence(
        hanh_dong, actor_id=nguoi_bam, evidence=rules.PriorityEvidenceFacts.from_row(dong)
    )
    assert (q.allowed, q.block_reason, q.requires_ack) == mong


def test_cam_ket_khong_mo_duong_khi_nguoi_nhan_la_nguoi_bam():
    """Người nhận đã biết = người bấm ⇒ chặn trước, không thành ca cần cam kết (như ``_receiver_gate``)."""
    q = rules.decide_priority_evidence("verify", actor_id=5, evidence=rules.PriorityEvidenceFacts.from_row(_giay(5)))
    assert not q.allowed and not q.requires_ack


@pytest.mark.parametrize(
    "cam_ket, ly_do, mong",
    [
        (False, "Đã đối chiếu bản gốc", False),
        (True, None, False),
        (True, "", False),
        (True, "   \t ", False),  # bỏ khoảng trắng hai đầu mà rỗng ⇒ từ chối
        (True, "Đã đối chiếu bản gốc", True),
    ],
)
def test_duong_cam_ket_can_co_va_ly_do_khac_rong(cam_ket, ly_do, mong):
    q = rules.decide_priority_evidence("verify", actor_id=6, evidence=rules.PriorityEvidenceFacts.from_row(None))
    assert rules.priority_evidence_ack_satisfied(q, unknown_submitter_ack=cam_ket, reason=ly_do) is mong


def test_nguoi_nhan_ro_thi_khong_can_cam_ket():
    q = rules.decide_priority_evidence("verify", actor_id=6, evidence=rules.PriorityEvidenceFacts.from_row(_giay(5)))
    assert rules.priority_evidence_ack_satisfied(q, unknown_submitter_ack=False, reason=None) is True


def test_cong_tac_tep_khong_ro_nguoi_tai_dao_duoc_o_mot_cho(monkeypatch):
    """Công tắc MỘT chỗ (owner 19-11: giữ "giống GĐ1b" = ``True``). Đảo ⇒ tệp không rõ người tải bị chặn kể cả có cam kết;
    giấy không rõ người nhận vẫn đi cam kết."""
    assert rules.UNKNOWN_UPLOADER_ACK_ALLOWED is True
    monkeypatch.setattr(rules, "UNKNOWN_UPLOADER_ACK_ALLOWED", False)
    q = rules.decide_priority_evidence("verify", actor_id=6, evidence=rules.PriorityEvidenceFacts.from_row(_tep(None)))
    assert (q.allowed, q.block_reason) == (False, rules.UNKNOWN_SUBMITTER)
    q = rules.decide_priority_evidence("verify", actor_id=6, evidence=rules.PriorityEvidenceFacts.from_row(_giay(None)))
    assert q.allowed and q.requires_ack


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
        # Câu 2 owner 19-11: mục CHƯA duyệt không được mang dấu của đường duyệt / bản giấy.
        ({}, {"04": dict(CHO, paper_only_verification=True)}, ["04"]),
        ({}, {"04": dict(CHO, document_id=77)}, ["04"]),
        ({"04": CHO}, {"04": dict(CHO, verified_by=9)}, ["04"]),
        ({}, {"04": dict(CHO, rejected_by=9)}, ["04"]),
        ({}, {"04": dict(CHO, paper_only_verification=False, document_id=None)}, []),
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


def _nguoi_q(uid=7):
    return SimpleNamespace(id=uid, role="manager", full_name="Q", email="q@example.com")


def _kw(ham, **them):
    kw = {"document_id": None} if ham == "verify_object_evidence" else {"reject_reason": "Minh chứng không đạt yêu cầu"}
    kw.update(them)
    return kw


@pytest.mark.parametrize("ham", ["verify_object_evidence", "reject_object_evidence"])
@pytest.mark.parametrize(
    "dong, ma",
    [
        (_tep(uploaded_by=7), "OWN_SUBMISSION"),
        (_giay(paper_by=7), "OWN_SUBMISSION"),
        (_tep(uploaded_by=None), "UNKNOWN_SUBMITTER"),
        (_giay(paper_by=None), "UNKNOWN_SUBMITTER"),
        (None, "UNKNOWN_SUBMITTER"),
    ],
)
async def test_dich_vu_chan_nguoi_nhan_va_khong_ro_khong_cam_ket(ham, dong, ma):
    from app.services import priority_override_service as svc

    ho_so = _ho_so_dv()
    with pytest.raises(svc.PriorityEvidenceReviewConflict) as e:
        await getattr(svc, ham)(_db(dong), ho_so, sub_code="04", actor=_nguoi_q(), expected_version=5, **_kw(ham))
    assert e.value.error_code == ma  # CÙNG mã lỗi với giấy tờ GĐ1b
    assert ho_so.priority_object_evidence == {} and ho_so.version == 5


async def test_dich_vu_cam_ket_khong_mo_duong_cho_nguoi_nhan_tu_duyet():
    from app.services import priority_override_service as svc

    with pytest.raises(svc.PriorityEvidenceReviewConflict) as e:
        await svc.verify_object_evidence(
            _db(_giay(paper_by=7)), _ho_so_dv(), sub_code="04", document_id=None, actor=_nguoi_q(),
            expected_version=5, unknown_submitter_ack=True, reason="Cam kết",
        )
    assert e.value.error_code == "OWN_SUBMISSION"


@pytest.mark.parametrize("ham", ["verify_object_evidence", "reject_object_evidence"])
@pytest.mark.parametrize("dong", [_tep(uploaded_by=None), _giay(paper_by=None), None])
async def test_dich_vu_khong_ro_nguoi_nhan_co_cam_ket_va_ly_do_thi_qua_va_luu_vet(ham, dong):
    from app import models
    from app.services import priority_override_service as svc

    ho_so, db = _ho_so_dv(), _db(dong)
    them = {"unknown_submitter_ack": True}
    if ham == "verify_object_evidence":
        them["reason"] = "  Đã đối chiếu bản gốc  "
    await getattr(svc, ham)(db, ho_so, sub_code="04", actor=_nguoi_q(), expected_version=5, **_kw(ham, **them))
    vet = [c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], models.PriorityAuditLog)]
    assert len(vet) == 1 and vet[0].actor_id == 7 and vet[0].new_value["sub_code"] == "04"
    ly_do = "Đã đối chiếu bản gốc" if ham == "verify_object_evidence" else "Minh chứng không đạt yêu cầu"
    assert vet[0].audit_metadata["unknown_submitter_ack"] is True
    assert vet[0].audit_metadata["receiver_unknown"] is True
    assert vet[0].audit_metadata["ack_reason"] == ly_do
    assert ho_so.version == 6


async def test_dich_vu_cam_ket_ly_do_toan_khoang_trang_bi_chan():
    from app.services import priority_override_service as svc

    with pytest.raises(svc.PriorityEvidenceReviewConflict) as e:
        await svc.verify_object_evidence(
            _db(None), _ho_so_dv(), sub_code="04", document_id=None, actor=_nguoi_q(),
            expected_version=5, unknown_submitter_ack=True, reason="   ",
        )
    assert e.value.error_code == "UNKNOWN_SUBMITTER"


async def test_dich_vu_duyet_ban_giay_nguoi_khac_nhan_gan_dong_va_la_duyet_giay():
    from app.services import priority_override_service as svc

    giay = _giay(paper_by=99)
    giay.id = 55
    ho_so, _ = await svc.verify_object_evidence(
        _db(giay), _ho_so_dv(), sub_code="04", document_id=None, actor=_nguoi_q(), expected_version=5,
    )
    muc = ho_so.priority_object_evidence["04"]
    assert (muc["status"], muc["document_id"], muc["paper_only_verification"]) == ("verified", 55, True)


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


def test_route_ghi_nhan_ban_giay_co_dong_casbin_template_bang_migration():
    """Route ghi nhận bản giấy: template (seed dev / test) sinh ĐÚNG các dòng migration ``gd2a20261118`` chép cứng (seed
    production): cán bộ allow, kế toán deny. Thiếu dòng ⇒ 403 cho mọi vai trừ Admin."""
    import importlib.util
    from pathlib import Path

    from app.casbin_config import policy_templates as pt

    mig = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "gd2a20261118_quota_table.py"
    spec = importlib.util.spec_from_file_location("_gd2a_mig_casbin", mig)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    doi_tuong = set(pt.GD2_PRIORITY_PAPER_OBJECTS)
    tu_template = set()
    for tid in pt.POLICY_TEMPLATES:
        for r in pt.apply_template(tid, f"role:{tid}"):
            if (r["object"], r["action"]) in doi_tuong:
                tu_template.add((r["subject"], r["object"], r["action"], r["eft"]))
    assert set(m.CASBIN_POLICIES) == tu_template
    assert ("role:officer", *next(iter(doi_tuong)), "allow") in tu_template
    assert ("role:accountant", *next(iter(doi_tuong)), "deny") in tu_template
    assert f"template_id = '{m.CASBIN_TEMPLATE_ID}'" in m.DOWNGRADE_SQL


def test_route_ghi_nhan_ban_giay_khop_dong_casbin():
    from fastapi.routing import APIRoute

    from app.casbin_config import policy_templates as pt
    from app.main import fastapi_app

    duong = [
        (m, r.path) for r in fastapi_app.routes if isinstance(r, APIRoute) and r.path.endswith("/paper-submitted")
        and "priority-evidence" in r.path for m in r.methods
    ]
    assert duong == [("POST", "/api/v2/admissions/{profile_id}/priority-evidence/{sub_code}/paper-submitted")]
    assert pt.GD2_PRIORITY_PAPER_OBJECTS == (("/api/v2/admissions/*/priority-evidence/*/paper-submitted", "POST"),)


def test_ghi_nhan_ban_giay_khoa_ho_so_truoc_va_ghi_nguoi_nhan():
    from app.services import admission_service

    src = inspect.getsource(admission_service.mark_priority_evidence_paper_submitted)
    assert src.index("_lock_profile_for_document_write(") < src.index("models.ProfileDocument(")
    assert src.count("paper_submitted_by=current_user.id") == 1


def test_tai_minh_chung_khoa_ho_so_truoc_va_ghi_nguoi_tai():
    from app.services import admission_service

    src = inspect.getsource(admission_service.upload_priority_evidence_document)
    assert src.index("_lock_profile_for_document_write(") < src.index("models.ProfileDocument(")
    assert src.count("uploaded_by=current_user.id") == 1
    assert src.count("doc_row.uploaded_by = current_user.id") == 1
