# -*- coding: utf-8 -*-
"""Cổng dựng bộ văn bản Hội đồng (lượt G — owner 05-11) trên PostgreSQL THẬT, dữ liệu GIẢ.

* F228 — 15 trạng thái qua ``tao_bo_van_ban`` (chặn 400 / cảnh báo 409 / qua); trạng thái LẠ
  (CHECK nới ra như khi thêm trạng thái mới) ⇒ chặn; xác nhận đúng số đếm ⇒ dựng + ghi vết; người
  không được xác nhận ⇒ 403 TRƯỚC khi đọc hồ sơ.
* F229 — mỗi luồng một nguồn: NV2+ trúng, cùng ngành khác tổ hợp, cùng ngành khác phương thức,
  học phí khác ngành NV, thiếu / chưa gắn học phí, hai NV trúng, bộ máy NV không có NV, điểm hai
  nguồn khác nhau; hồ sơ một nguyện vọng kiểu cũ có dòng nguyện vọng do "backfill" (Phase 3 —
  ``scripts/phase3-backfill-dryrun.py``, ``Documents/ADMISSION_DAILY_LOG.md`` "Backfill SQL
  DEFERRED"): khớp ⇒ qua; điểm hồ sơ đổi SAU backfill ⇒ chặn; khác tổ hợp / đường xét / ngành;
  không có dòng nguyện vọng; thứ tự nguồn ngành (cấu hình hồ sơ trước ``applied_rules``).
* F231 — khu vực: thiếu / chưa phân giải; mức theo NĂM HỌC (khác bộ xuất CÓ CHỦ Ý khi năm khác có
  mức mới hơn); chưa có mức cho năm; hai mức mở; ấn định thủ công không sổ / hợp lệ / dữ liệu đổi.

Mỗi ca dựng một hồ sơ vi phạm ĐÚNG MỘT bất biến (trừ ca ghi rõ hai), so ``chan`` NGUYÊN VẸN
(CLAUDE.md §3).
"""
import json
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

import app.database as csdl
from app.database import AsyncSessionLocal
from app.models.admission import AdmissionProfile
from app.models.council_document import CouncilDocumentSet
from app.services import council_candidate_service as doc
from app.services import council_document_set_service as bo_vb
from app.services import council_set_gate_service as cong
from app.services.priority_service import kv_inputs_fingerprint
from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    PermissionDeniedError,
)
from tests.fixtures.hoi_dong_seed import (
    HP_CD,
    LUC,
    chen,
    ho_so,
    kv,
    lich_su_thpt,
    ma_gia,
    seed_hoi_dong,
)
from tests.integration.test_council_document_store import _dem, _tai_ba_mau

pytestmark = pytest.mark.integration

NV_SACH = [(1, "oto_cd", "cq", "g1")]
# Ba mức VIẾT TAY theo nguyên văn owner 05-11 — KHÔNG lấy từ mã (lấy từ mã thì đổi tập trong mã là
# đổi luôn ca kiểm, phép đo thành rỗng).
OWNER_CHAN = ["draft", "rejected", "withdrawal_pending", "withdrawn"]
OWNER_CANH_BAO = [
    "submitted",
    "resubmitted",
    "reviewing",
    "revision_requested",
    "waitlisted",
    "result_published",
]
OWNER_KHONG = ["approved", "admitted", "confirmed", "enrolled", "overridden"]
DIEM_SACH = {0: {"toan": "7.25", "ly": "6.50", "hoa": "8.00"}}


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        hs = await seed_hoi_dong(conn)
        d = hs["_danh_muc"]
        # Phương thức THỨ HAI + đường xét cùng ngành ô tô CĐ chính quy (ca "cùng ngành khác
        # phương thức").
        d["pt2"] = await chen(
            conn,
            "admission_method",
            code="gia_thpt",
            name="Xét điểm thi (giả)",
            requires_gpa=False,
            requires_subject_scores=True,
            display_order=2,
            is_active=True,
        )
        ap1, _ = d["psg"][("oto_cd", "cq", "g1")]
        d["oai_oto_cq"] = (
            await conn.execute(
                text("SELECT academic_info_id FROM admission_path WHERE id = :a"),
                {"a": ap1},
            )
        ).scalar_one()
        ap_duoc, _ = d["psg"][("duoc_cd", "cq", "g1")]
        d["oai_duoc_cq"] = (
            await conn.execute(
                text("SELECT academic_info_id FROM admission_path WHERE id = :a"),
                {"a": ap_duoc},
            )
        ).scalar_one()
        ap2 = await chen(
            conn,
            "admission_path",
            academic_info_id=d["oai_oto_cq"],
            admission_method_id=d["pt2"],
            status="active",
            display_order=2,
            visibility="public",
            admission_round_id=d["vong"],
            created_at=LUC,
            updated_at=LUC,
        )
        d["psg_pt2_g1"] = (
            ap2,
            await chen(
                conn,
                "path_subject_group_config",
                admission_path_id=ap2,
                subject_group_id=d["to_hop"]["g1"],
            ),
        )
    return hs


_SO = iter(range(500, 10_000))


async def _mot(hs, **kw):
    """Một hồ sơ SẠCH (bộ máy nguyện vọng, đã duyệt, NV1 ô tô CĐ, học phí ô tô CĐ, KV1) — ``kw``
    ghi đè đúng chỗ cần vi phạm. Trả (cccd, pid)."""
    d = hs["_danh_muc"]
    goc = dict(
        full_name="Họ Giả Cổng",
        dob=date(2008, 1, 1),
        gender="Nam",
        ethnicity="01",
        permanent_commune_code="GX1",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot=kv("KV1"),
        # Lượt H (câu 21): lịch sử THPT để resolver của app tính lại ra đúng KV1 của ảnh chụp.
        academic_history=lich_su_thpt(d, "KV1"),
        nv=NV_SACH,
        diem=DIEM_SACH,
        hoc_phi=[HP_CD],
    )
    goc.update(kw)
    cccd = ma_gia(next(_SO))
    async with csdl.engine.begin() as conn:
        pid = await ho_so(conn, d, cccd=cccd, **goc)
    return cccd, pid


async def _sql(cau, **ts):
    async with csdl.engine.begin() as conn:
        return await conn.execute(text(cau), ts)


async def _nv_cua(pid):
    r = await _sql(
        "SELECT id FROM admission_profile_choice WHERE admission_profile_id = :p "
        "ORDER BY display_order",
        p=pid,
    )
    return [x for (x,) in r.all()]


async def _diem_ho_so(hs, pid, bang):
    d = hs["_danh_muc"]
    async with csdl.engine.begin() as conn:
        for m, sc in bang.items():
            await chen(
                conn,
                "profile_subject_score",
                profile_id=pid,
                subject_id=d["mon"][m],
                score=sc,
                created_at=LUC,
                updated_at=LUC,
            )


async def _cong(ma, nam=2026):
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, ma, academic_year=nam)
    return cong.danh_gia(anh.kiem), anh


def _mot_ly_do(ma):
    return ((ma, None, (1,)),)


# ═══════════════════════════════ đối chứng: hồ sơ sạch qua cổng ═══════════════════════════
async def test_ho_so_sach_qua_cong_va_diem_kv_theo_nam(hs):
    cccd, _ = await _mot(hs)
    kq, anh = await _cong([cccd])
    assert kq.chan == () and kq.canh_bao == {}
    assert kq.diem_kv == ("0.75",) and anh.rows[0].diem_kv == "0.75"


# ═══════════════════════════════ F228 — 15 trạng thái qua tao_bo_van_ban ══════════════════
async def _tao(ma, **kw):
    async with AsyncSessionLocal() as db:
        bo, _ = await bo_vb.tao_bo_van_ban(
            db,
            csdl.engine,
            ma_ho_so=ma,
            academic_year=kw.pop("nam", 2026),
            tham_so=None,
            nguoi_tao_id=kw.pop("nguoi", None),
            **kw,
        )
        await db.commit()
        return bo.id


@pytest.mark.parametrize("s", OWNER_CHAN)
async def test_trang_thai_chan_thi_400_khong_ghi(hs, s):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, _ = await _mot(hs, status=s)
    with pytest.raises(DataValidationError) as e:
        await _tao([cccd])
    p = e.value.public_payload["kiem_tra_dung_bo"]
    assert [(c["ma"], c["trang_thai"], c["dong"]) for c in p["chan"]] == [
        ("trang_thai_chan", s, [1])
    ]
    assert await _dem() == (0, 0)


@pytest.mark.parametrize("s", OWNER_CANH_BAO)
async def test_trang_thai_canh_bao_thi_409_khong_ghi(hs, s):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, _ = await _mot(hs, status=s)
    with pytest.raises(ConflictError) as e:
        await _tao([cccd], duoc_xac_nhan=True)
    p = e.value.public_payload["kiem_tra_dung_bo"]
    assert p["muc"] == "can_xac_nhan" and p["chan"] == []
    assert p["canh_bao"]["so_ho_so_theo_trang_thai"] == {s: 1}
    assert await _dem() == (0, 0)


@pytest.mark.parametrize("s", OWNER_KHONG)
async def test_trang_thai_khong_canh_bao_thi_dung_duoc(hs, s):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, _ = await _mot(hs, status=s)
    sid = await _tao([cccd])
    async with AsyncSessionLocal() as db:
        b = await db.get(CouncilDocumentSet, sid)
        assert b.thong_tin_dung["trang_thai_ho_so"] == {s: 1}
        assert b.thong_tin_dung["xac_nhan_canh_bao_trang_thai"] is None


async def test_trang_thai_la_khi_check_noi_ra_thi_chan(hs):
    # Như khi app thêm trạng thái mới (nới CHECK) mà cổng chưa cập nhật: phải CHẶN.
    cccd, pid = await _mot(hs)
    await _sql(
        "ALTER TABLE admission_profile DROP CONSTRAINT ck_admission_profile_status"
    )
    await _sql(
        "UPDATE admission_profile SET status = 'trang_thai_moi' WHERE id = :p", p=pid
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == (("trang_thai_la", "trang_thai_moi", (1,)),)


async def test_xac_nhan_dung_so_dem_thi_dung_va_ghi_vet(hs):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    a, _ = await _mot(hs, status="submitted")
    b, _ = await _mot(hs)
    c, _ = await _mot(hs, status="reviewing")
    e_, _ = await _mot(hs, status="submitted")
    nguoi = hs["_danh_muc"]["nguoi"]
    with pytest.raises(ConflictError):  # lệch số đếm (thiếu một hồ sơ "submitted")
        await _tao(
            [a, b, c, e_],
            nguoi=nguoi,
            xac_nhan_trang_thai={"submitted": 1, "reviewing": 1},
            duoc_xac_nhan=True,
        )
    assert await _dem() == (0, 0)
    sid = await _tao(
        [a, b, c, e_],
        nguoi=nguoi,
        xac_nhan_trang_thai={"submitted": 2, "reviewing": 1},
        duoc_xac_nhan=True,
    )
    async with AsyncSessionLocal() as db:
        bo = await db.get(CouncilDocumentSet, sid)
        vet = bo.thong_tin_dung["xac_nhan_canh_bao_trang_thai"]
        assert vet["nguoi_xac_nhan_id"] == nguoi
        assert datetime.fromisoformat(vet["luc"]) == bo.tao_luc
        assert vet["so_ho_so_theo_trang_thai"] == {"reviewing": 1, "submitted": 2}
        assert vet["dong_theo_trang_thai"] == {"reviewing": [3], "submitted": [1, 4]}
        assert bo.thong_tin_dung["trang_thai_ho_so"] == {
            "approved": 1,
            "reviewing": 1,
            "submitted": 2,
        }


async def test_khong_duoc_xac_nhan_thi_403_truoc_khi_doc(hs, monkeypatch):
    goi = []
    monkeypatch.setattr(bo_vb, "doc_ho_so_theo_ma", lambda *a, **k: goi.append(1))
    cccd, _ = await _mot(hs, status="submitted")
    with pytest.raises(PermissionDeniedError):
        await _tao([cccd], xac_nhan_trang_thai={"submitted": 1}, duoc_xac_nhan=False)
    assert goi == [] and await _dem() == (0, 0)


# ═══════════════════════════════ F229 — bộ máy nguyện vọng (lấy NV1) ═════════════════════
async def _quyet_dinh(pid, thu_tu, gia_tri="admitted"):
    ids = await _nv_cua(pid)
    await _sql(
        "UPDATE admission_profile_choice SET decision = :g WHERE id = :i",
        g=gia_tri,
        i=ids[thu_tu - 1],
    )


async def test_nv1_theo_display_order_khong_theo_id(hs):
    # NV có display_order 1 chèn SAU (id lớn hơn) — app lấy NV1 theo display_order (ĐỐI CHỨNG sạch).
    cccd, _ = await _mot(
        hs,
        nv=[(2, "duoc_cd", "cq", "g2"), (1, "oto_cd", "cq", "g1")],
        diem={0: {"van": "9.00", "toan": "9.00", "ly": "9.00"}, 1: DIEM_SACH[0]},
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == ()


async def test_nv2_trung_cung_nganh_khac_to_hop(hs):
    cccd, pid = await _mot(
        hs,
        nv=[(1, "oto_cd", "cq", "g1"), (2, "oto_cd", "cq", "g2")],
        diem={0: DIEM_SACH[0], 1: {"van": "9.00", "toan": "9.00", "ly": "9.00"}},
    )
    await _quyet_dinh(pid, 2)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("trung_nv_khac")


async def test_nv2_trung_cung_nganh_khac_phuong_thuc(hs):
    d = hs["_danh_muc"]
    cccd, pid = await _mot(hs)
    ap2, psg2 = d["psg_pt2_g1"]
    async with csdl.engine.begin() as conn:
        nv2 = await chen(
            conn,
            "admission_profile_choice",
            admission_profile_id=pid,
            admission_path_id=ap2,
            path_subject_group_config_id=psg2,
            display_order=2,
            decision="admitted",
        )
        for m, sc in DIEM_SACH[0].items():
            await chen(
                conn,
                "profile_choice_score",
                admission_profile_choice_id=nv2,
                subject_id=d["mon"][m],
                score=sc,
                max_score_snapshot="10",
            )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("trung_nv_khac")


async def test_nv2_trung_khac_nganh_hoc_phi_theo_nv2(hs):
    # Hồ sơ này vi phạm HAI bất biến do bản chất (trúng NV2 + học phí theo NV2 khác ngành in).
    cccd, pid = await _mot(
        hs,
        nv=[(1, "oto_cd", "cq", "g1"), (2, "duoc_cd", "cq", "g2")],
        hoc_phi=[dict(HP_CD, resolved_major="duoc_cd")],
    )
    await _quyet_dinh(pid, 2)
    kq, _ = await _cong([cccd])
    assert {m for m, _, _ in kq.chan} == {"trung_nv_khac", "hoc_phi_khac_nganh_nv"}


async def test_hoc_phi_khac_nganh_nv1_chua_cong_bo(hs):
    cccd, _ = await _mot(hs, hoc_phi=[dict(HP_CD, resolved_major="duoc_cd")])
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("hoc_phi_khac_nganh_nv")


@pytest.mark.parametrize(
    "hoc_phi, ma",
    [
        ([], "thieu_hoc_phi_hk1"),
        ([dict(HP_CD, status="cancelled")], "thieu_hoc_phi_hk1"),
        ([dict(HP_CD, semester_no=2)], "thieu_hoc_phi_hk1"),
        ([dict(HP_CD, resolved_major=None)], "hoc_phi_chua_gan_nganh"),
    ],
    ids=["khong_co", "da_huy", "chi_hk2", "chua_gan_nganh"],
)
async def test_hoc_phi_hk1(hs, hoc_phi, ma):
    cccd, _ = await _mot(hs, hoc_phi=hoc_phi)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do(ma)


async def test_hai_nv_cung_trung(hs):
    cccd, pid = await _mot(
        hs, nv=[(1, "oto_cd", "cq", "g1"), (2, "oto_cd", "cq", "g2")]
    )
    await _quyet_dinh(pid, 1)
    await _quyet_dinh(pid, 2)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("nhieu_nv_trung")


async def test_nv1_trung_thi_qua(hs):
    cccd, pid = await _mot(
        hs, nv=[(1, "oto_cd", "cq", "g1"), (2, "duoc_cd", "cq", "g2")]
    )
    await _quyet_dinh(pid, 1)
    await _quyet_dinh(pid, 2, "skip")
    kq, _ = await _cong([cccd])
    assert kq.chan == ()


async def test_bo_may_nguyen_vong_khong_co_nv(hs):
    cccd, _ = await _mot(hs, nv=[], diem={}, uses_choice_engine=True)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("nhieu_nv_khong_co_nv")


async def test_bo_may_nguyen_vong_diem_hai_nguon_khac(hs):
    cccd, pid = await _mot(hs)
    await _diem_ho_so(hs, pid, {"toan": "7.00"})  # NV1: 7.25
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("diem_hai_nguon_khac")


async def test_bo_may_nguyen_vong_diem_hai_nguon_bang_nhau_thi_qua(hs):
    cccd, pid = await _mot(hs)
    await _diem_ho_so(hs, pid, {"toan": "7.25", "van": "1.00"})  # van ngoài tổ hợp in
    kq, _ = await _cong([cccd])
    assert kq.chan == ()


# ═══════════════════════════════ F229 — hồ sơ một nguyện vọng kiểu cũ ═════════════════════
async def _mot_nv_cu(hs, *, ar=None, sg="g1", nv=NV_SACH, diem_hs=None, **kw):
    """Hồ sơ kiểu cũ (``uses_choice_engine`` = false) có MỘT dòng nguyện vọng do backfill tạo
    (khớp cấu hình hồ sơ) + bảng điểm hồ sơ = điểm nguyện vọng (lúc backfill)."""
    d = hs["_danh_muc"]
    ap1, _ = d["psg"][("oto_cd", "cq", "g1")]
    cccd, pid = await _mot(
        hs,
        nv=nv,
        uses_choice_engine=False,
        selected_subject_group_id=d["to_hop"][sg] if sg else None,
        **kw,
    )
    gia = {"academic_info_id": d["oai_oto_cq"], "admission_path_id": ap1}
    gia.update(ar or {})
    await _sql(
        "UPDATE admission_profile SET applied_rules = CAST(:a AS jsonb) WHERE id = :p",
        a=json.dumps({k: v for k, v in gia.items() if v is not None}),
        p=pid,
    )
    await _diem_ho_so(hs, pid, DIEM_SACH[0] if diem_hs is None else diem_hs)
    return cccd, pid


async def test_mot_nv_backfill_khop_thi_qua(hs):
    cccd, _ = await _mot_nv_cu(hs)
    kq, _ = await _cong([cccd])
    assert kq.chan == ()


async def test_mot_nv_diem_ho_so_doi_sau_backfill_thi_chan(hs):
    cccd, pid = await _mot_nv_cu(hs)
    d = hs["_danh_muc"]
    # update_profile ghi bảng điểm HỒ SƠ (admission_service.py:6019) — dòng nguyện vọng giữ điểm cũ.
    # Đổi NHỎ (6.50 → 6.75): làm tròn hai bên vẫn bằng nhau — phép so phải so đúng giá trị.
    await _sql(
        "UPDATE profile_subject_score SET score = 6.75 WHERE profile_id = :p AND subject_id = :s",
        p=pid,
        s=d["mon"]["ly"],
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_diem_lech")


async def test_mot_nv_bang_diem_ho_so_thieu_mon_cua_to_hop(hs):
    cccd, _ = await _mot_nv_cu(hs, diem_hs={"toan": "7.25", "ly": "6.50"})
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_diem_lech")


async def test_mot_nv_dong_nguyen_vong_thieu_mon_bang_diem_ho_so_co(hs):
    # Dòng nguyện vọng (backfill) thiếu điểm một môn mà bảng điểm hồ sơ có ⇒ văn bản in thiếu môn.
    cccd, _ = await _mot_nv_cu(hs, diem={0: {"toan": "7.25", "ly": "6.50"}})
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_diem_lech")


async def test_mot_nv_khac_to_hop(hs):
    cccd, _ = await _mot_nv_cu(hs, sg="g2")
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_khac_to_hop")


async def test_mot_nv_khac_duong_xet(hs):
    d = hs["_danh_muc"]
    ap2, _ = d["psg_pt2_g1"]  # cùng ngành, phương thức khác
    cccd, _ = await _mot_nv_cu(hs, ar={"admission_path_id": ap2})
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_khac_duong_xet")


async def test_mot_nv_khac_nganh(hs):
    d = hs["_danh_muc"]
    cccd, _ = await _mot_nv_cu(hs, ar={"academic_info_id": d["oai_duoc_cq"]})
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_khac_nganh")


async def test_mot_nv_cau_hinh_ho_so_truoc_applied_rules(hs):
    # Thứ tự nguồn ngành = nhánh legacy của resolve_fee_academic_info: offering_admission_config
    # (cấu hình hồ sơ) TRƯỚC applied_rules.academic_info_id.
    d = hs["_danh_muc"]
    async with csdl.engine.begin() as conn:
        tc = await chen(
            conn,
            "admission_criteria",
            method_id=d["pt"],
            code="GIA-TC-1",
            name="Tiêu chí giả",
            is_active=True,
            subject_selection_mode="fixed",
            scoring_method="sum",
            policy_version="2025.1",
        )
        oac = await chen(
            conn,
            "offering_admission_config",
            academic_info_id=d["oai_duoc_cq"],
            criteria_id=tc,
            is_active=True,
            created_at=LUC,
        )
    cccd, _ = await _mot_nv_cu(hs, offering_admission_config_id=oac)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_khac_nganh")


async def test_mot_nv_khong_co_dong_nguyen_vong(hs):
    cccd, _ = await _mot_nv_cu(hs, nv=[], diem={})
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("mot_nv_khong_co_dong_nguyen_vong")


@pytest.mark.parametrize(
    "ar, sg, ma",
    [
        ({"academic_info_id": None}, "g1", "mot_nv_khong_xac_dinh_nganh"),
        ({"academic_info_id": "abc"}, "g1", "mot_nv_khong_xac_dinh_nganh"),
        ({"admission_path_id": None}, "g1", "mot_nv_khong_xac_dinh_duong_xet"),
        ({}, None, "mot_nv_khong_xac_dinh_to_hop"),
    ],
    ids=["thieu_nganh", "nganh_khong_phai_so", "thieu_duong_xet", "thieu_to_hop"],
)
async def test_mot_nv_cau_hinh_ho_so_thieu(hs, ar, sg, ma):
    cccd, _ = await _mot_nv_cu(hs, ar=ar, sg=sg)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do(ma)


# ═══════════════════════════════ F231 — khu vực ưu tiên ═══════════════════════════════════
async def test_thieu_khu_vuc(hs):
    kq, anh = await _cong([hs["khong_khu_vuc"][0]])
    assert kq.chan == _mot_ly_do("thieu_khu_vuc") and kq.diem_kv == (None,)
    assert anh.rows[0].diem_kv == "0"  # bộ xuất in 0 — bộ văn bản KHÔNG in


async def test_khu_vuc_chua_phan_giai_thi_chan(hs):
    cccd, _ = await _mot(
        hs,
        priority_resolution_snapshot={
            "kv_resolved": "KV1",
            "rule_applied": "manual_override_unverified",
        },
    )
    kq, anh = await _cong([cccd])
    assert kq.chan == _mot_ly_do("thieu_khu_vuc")
    assert anh.rows[0].kv == "KV1"  # bộ xuất vẫn in KV1


async def test_khac_nam_lay_muc_nam_hoc_cua_ho_so(hs):
    # Năm 2027 có mức KV1 MỚI HƠN theo ngày ⇒ bộ xuất (mới nhất) lấy 1.00; bộ văn bản lấy mức của
    # NĂM HỌC hồ sơ (2026) = 0.75 — khác bộ xuất CÓ CHỦ Ý (owner 05-11, F231).
    async with csdl.engine.begin() as conn:
        await chen(
            conn,
            "priority_area_config",
            academic_year=2027,
            area_code="KV1",
            area_name="Khu vực giả KV1",
            bonus_points="1.00",
            effective_from=date(2027, 1, 1),
        )
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, _ = await _mot(hs)
    kq, anh = await _cong([cccd])
    assert anh.rows[0].diem_kv == "1.00" and kq.diem_kv == ("0.75",)
    sid = await _tao([cccd])
    async with AsyncSessionLocal() as db:
        dto = (
            await db.execute(
                select(CouncilDocumentSet.snapshot_dto).where(
                    CouncilDocumentSet.id == sid
                )
            )
        ).scalar_one()
    assert dto[0]["diem_kv"] == "0.75"


async def test_chua_co_muc_cho_nam_hoc(hs):
    cccd, _ = await _mot(hs, nam=2027)
    kq, _ = await _cong([cccd], nam=2027)
    assert kq.chan == _mot_ly_do("chua_co_muc_khu_vuc")


async def test_hai_muc_dang_mo_cung_nam(hs):
    async with csdl.engine.begin() as conn:
        await chen(
            conn,
            "priority_area_config",
            academic_year=2026,
            area_code="KV1",
            area_name="Khu vực giả KV1 trùng",
            bonus_points="0.10",
            effective_from=date(2026, 6, 1),
        )
    cccd, _ = await _mot(hs)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("muc_khu_vuc_khong_nhat_quan")


async def _an_dinh_thu_cong(hs, *, so_audit=True):
    d = hs["_danh_muc"]
    luc = "2026-10-02T03:04:05+00:00"
    cccd, pid = await _mot(
        hs,
        area_resolution_basis="manual_override",
        priority_resolution_snapshot={
            "kv_resolved": "KV1",
            "rule_applied": "manual_override",
            "manual_override_by": d["nguoi"],
            "manual_override_at": luc,
            "manual_override_reason": "Lý do giả ấn định khu vực đủ dài",
        },
    )
    if so_audit:
        async with AsyncSessionLocal() as db:
            ho = await db.get(AdmissionProfile, pid)
            dau = kv_inputs_fingerprint(ho)
        async with csdl.engine.begin() as conn:
            await chen(
                conn,
                "priority_audit_log",
                profile_id=pid,
                action_type="kv_manual_override",
                actor_id=d["nguoi"],
                new_value={"kv_resolved": "KV1"},
                metadata={"actor_role": "admin", "kv_inputs_fingerprint": dau},
                created_at=datetime(2026, 10, 2, 3, 4, 6, tzinfo=timezone.utc),
            )
    return cccd, pid


async def test_an_dinh_thu_cong_khong_co_so_thi_chan(hs):
    cccd, _ = await _an_dinh_thu_cong(hs, so_audit=False)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_thu_cong_khong_hieu_luc")


async def test_ho_so_khai_an_dinh_thu_cong_ma_anh_chup_thuong_van_phai_xac_minh(hs):
    # area_resolution_basis = manual_override ⇒ T6 đi nhánh MANUAL và xác minh sổ
    # (priority_service._derive_kv_basis_level + freeze_priority_snapshot) — dù ảnh chụp cũ ghi
    # commune_lookup. Không có sổ ⇒ chặn.
    cccd, _ = await _mot(
        hs,
        area_resolution_basis="manual_override",
        priority_resolution_snapshot=kv("KV1"),
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_thu_cong_khong_hieu_luc")


async def test_an_dinh_thu_cong_hop_le_thi_qua(hs):
    cccd, _ = await _an_dinh_thu_cong(hs)
    kq, _ = await _cong([cccd])
    assert kq.chan == () and kq.diem_kv == ("0.75",)


async def test_an_dinh_thu_cong_du_lieu_doi_sau_khi_duyet_thi_chan(hs):
    cccd, pid = await _an_dinh_thu_cong(hs)
    await _sql(
        "UPDATE admission_profile SET permanent_commune_code = 'GX2' WHERE id = :p",
        p=pid,
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_thu_cong_khong_hieu_luc")


# ═══════════════ Câu 21 (owner 06-11) — tính lại KV chỉ đọc, lệch ⇒ chặn và liệt kê ══════════
async def _doi_lich_su(hs, pid, ma_kv):
    """Mô phỏng "sửa nơi học THPT rồi Nộp lại": dữ liệu KV đổi, ảnh chụp KHÔNG chụp lại."""
    await _sql(
        "UPDATE admission_profile SET academic_history = CAST(:h AS jsonb) WHERE id = :p",
        h=json.dumps(lich_su_thpt(hs["_danh_muc"], ma_kv)),
        p=pid,
    )


async def test_kv_tinh_lai_khac_anh_chup_thi_chan(hs):
    cccd, pid = await _mot(hs)  # ảnh chụp KV1, đang học trường KV1
    await _doi_lich_su(hs, pid, "KV2")
    kq, anh = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_doi_sau_anh_chup") and kq.diem_kv == (None,)
    assert anh.rows[0].kv == "KV1"  # bộ xuất vẫn in KV cũ của ảnh chụp


async def test_kv_tinh_lai_theo_thuong_tru_khac_anh_chup_thi_chan(hs):
    # Nhánh THƯỜNG TRÚ (văn hoá THCS): đổi xã thường trú GX3 (KV2-NT) ⇒ GX1 (KV1).
    cccd, pid = await _mot(
        hs,
        permanent_commune_code="GX3",
        cultural_education_level="graduated_thcs",
        vocational_qualification="so_cap",
        priority_resolution_snapshot=kv("KV2-NT"),
        academic_history=[],
    )
    assert (await _cong([cccd]))[0].chan == ()  # phép đo hợp lệ: trước khi đổi thì qua
    await _sql(
        "UPDATE admission_profile SET permanent_commune_code = 'GX1' WHERE id = :p",
        p=pid,
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_doi_sau_anh_chup")


async def test_du_lieu_doi_ma_kv_tinh_lai_khong_doi_thi_qua(hs):
    # Đổi xã thường trú của hồ sơ đi nhánh LỊCH SỬ THPT ⇒ KV tính lại vẫn KV1: so MÃ KV, không
    # so dữ liệu đầu vào.
    cccd, pid = await _mot(hs)
    await _sql(
        "UPDATE admission_profile SET permanent_commune_code = 'GX2' WHERE id = :p",
        p=pid,
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == () and kq.diem_kv == ("0.75",)


async def test_kv_tinh_lai_dung_ngu_canh_trinh_do_cua_anh_chup(hs):
    # "Hoàn thành THPT, không chuyên môn": không ngữ cảnh trình độ ⇒ resolver đi THƯỜNG TRÚ (GX2 =
    # KV2); ngữ cảnh "cao đẳng chính quy" ghi trong ảnh chụp ⇒ LỊCH SỬ THPT (trường KV1). Tính lại
    # phải dùng ĐÚNG ngữ cảnh của lần chụp ⇒ KV1 = ảnh chụp ⇒ qua.
    cccd, _ = await _mot(
        hs,
        permanent_commune_code="GX2",
        cultural_education_level="completed_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot={
            "kv_resolved": "KV1",
            "rule_applied": "longest_duration",
            "target_level": "cao_dang",
            "admission_type": "chinh_quy",
        },
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == () and kq.diem_kv == ("0.75",)


async def test_kv_tinh_lai_khong_phan_giai_duoc_thi_chan(hs):
    # Bỏ lịch sử THPT ⇒ resolver trả None (thiếu dữ liệu) trong khi ảnh chụp vẫn KV1 ⇒ "KV in"
    # không còn chứng minh được từ dữ liệu hiện tại ⇒ chặn (None ≠ KV1 — không coi là khớp).
    cccd, pid = await _mot(hs)
    await _sql(
        "UPDATE admission_profile SET academic_history = '[]'::jsonb WHERE id = :p",
        p=pid,
    )
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_doi_sau_anh_chup")


async def test_resolver_nem_loi_thi_chan(hs, monkeypatch):
    from app.services import priority_service

    async def hong(*a, **k):
        raise RuntimeError("giả: resolver hỏng")

    cccd, _ = await _mot(hs)
    monkeypatch.setattr(priority_service, "resolve_kv_for_profile", hong)
    kq, _ = await _cong([cccd])
    assert kq.chan == _mot_ly_do("khu_vuc_khong_tinh_lai_duoc")


async def test_tinh_lai_kv_khong_ghi_gi_vao_ho_so(hs):
    cccd, pid = await _mot(hs)
    await _doi_lich_su(hs, pid, "KV3")
    q = (
        "SELECT priority_resolution_snapshot::text, updated_at FROM admission_profile "
        "WHERE id = :p"
    )
    truoc = (await _sql(q, p=pid)).one()
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
    # Phép đo hợp lệ: đã tính lại (và thấy lệch).
    assert anh.kiem[0].kv_ly_do == "khu_vuc_doi_sau_anh_chup"
    assert anh.giao_dich.transaction_read_only == "on"
    assert (await _sql(q, p=pid)).one() == truoc


# ═══════════════ Câu 22 (owner 06-11) — điểm KV in theo luật cộng điểm của đường xét ═══════════
# Phương thức giả có mặc định CỘNG KV (seed). ``override`` / ``mac_dinh`` là CHỮ SQL cố định của
# test (không phải đầu vào): ``NULL`` (SQL NULL), ``'null'::jsonb`` (JSON null), hay một luật.
TAT_KV = """'{"apply_area_bonus": false, "apply_object_bonus": true}'::jsonb"""
BAT_KV = """'{"apply_area_bonus": true, "apply_object_bonus": true}'::jsonb"""


async def _dat_luat(pid, *, override, mac_dinh=None):
    ap = (
        await _sql(
            "SELECT admission_path_id FROM admission_profile_choice "
            "WHERE admission_profile_id = :p ORDER BY display_order LIMIT 1",
            p=pid,
        )
    ).scalar_one()
    await _sql(
        "UPDATE admission_path SET bonus_rule_override = %s WHERE id = :a" % override,
        a=ap,
    )
    if mac_dinh is not None:
        await _sql(
            "UPDATE admission_method SET default_bonus_rule = %s WHERE id = "
            "(SELECT admission_method_id FROM admission_path WHERE id = :a)" % mac_dinh,
            a=ap,
        )
    return ap


async def test_override_json_null_thi_theo_phuong_thuc(hs):
    cccd, pid = await _mot(hs)
    ap = await _dat_luat(pid, override="'null'::jsonb")
    # Phép đo hợp lệ: cột là JSON null, KHÔNG phải SQL NULL (COALESCE của SQL không thay nó).
    loai = await _sql(
        "SELECT bonus_rule_override IS NULL, jsonb_typeof(bonus_rule_override) "
        "FROM admission_path WHERE id = :a",
        a=ap,
    )
    assert tuple(loai.one()) == (False, "null")
    kq, _ = await _cong([cccd])
    assert kq.luat_kv == ("cong",) and kq.diem_kv == ("0.75",)


async def test_override_sql_null_thi_theo_phuong_thuc(hs):
    cccd, pid = await _mot(hs)
    ap = await _dat_luat(pid, override="NULL")
    loai = await _sql(
        "SELECT bonus_rule_override IS NULL FROM admission_path WHERE id = :a", a=ap
    )
    assert loai.scalar_one() is True  # phép đo hợp lệ: SQL NULL
    kq, _ = await _cong([cccd])
    assert kq.luat_kv == ("cong",) and kq.diem_kv == ("0.75",)


async def test_override_that_tat_kv_thi_in_0(hs):
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override=TAT_KV)
    kq, anh = await _cong([cccd])
    assert kq.chan == () and kq.luat_kv == ("tat",) and kq.diem_kv == ("0.00",)
    # Bộ xuất (luật v1) vẫn cộng KV — khác CÓ CHỦ Ý.
    assert anh.rows[0].diem_kv == "0.75"


async def test_override_bat_kv_thang_phuong_thuc_tat(hs):
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override=BAT_KV, mac_dinh=TAT_KV)
    kq, _ = await _cong([cccd])
    assert kq.luat_kv == ("cong",) and kq.diem_kv == ("0.75",)


async def test_phuong_thuc_tat_kv_khong_override_thi_in_0(hs):
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override="NULL", mac_dinh=TAT_KV)
    kq, _ = await _cong([cccd])
    assert kq.luat_kv == ("tat",) and kq.diem_kv == ("0.00",)


@pytest.mark.parametrize(
    "override, mac_dinh",
    [("NULL", "NULL"), ("'null'::jsonb", "'null'::jsonb")],
    ids=["sql_null", "json_null"],
)
async def test_khong_co_luat_nao_thi_in_0_nhu_t6(hs, override, mac_dinh):
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override=override, mac_dinh=mac_dinh)
    kq, _ = await _cong([cccd])
    assert kq.chan == () and kq.luat_kv == ("khong_co_luat",)
    assert kq.diem_kv == ("0.00",)


async def test_luat_khong_phai_dict_thi_chan(hs):
    # Override là JSON hợp lệ nhưng không phải luật (chuỗi) — T6 cũng không đọc được ⇒ chặn, không
    # đoán bên nào.
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override="""'"khong-phai-luat"'::jsonb""")
    kq, _ = await _cong([cccd])
    # Lượt H2: cùng luật quyết cả công tắc đối tượng ⇒ hai mã (đổi CÓ CHỦ Ý từ một mã).
    assert kq.chan == (
        ("khong_xac_dinh_luat_cong_diem_kv", None, (1,)),
        ("khong_xac_dinh_luat_cong_diem_ut", None, (1,)),
    )
    assert kq.diem_kv == (None,)


async def test_dung_bo_ghi_diem_kv_theo_luat_va_vet(hs):
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, pid = await _mot(hs)
    await _dat_luat(pid, override=TAT_KV)
    sid = await _tao([cccd])
    async with AsyncSessionLocal() as db:
        dto, tt = (
            await db.execute(
                select(
                    CouncilDocumentSet.snapshot_dto, CouncilDocumentSet.thong_tin_dung
                ).where(CouncilDocumentSet.id == sid)
            )
        ).one()
    assert dto[0]["diem_kv"] == "0.00"
    assert tt["luat_diem_kv"] == "theo_luat_cong_diem_cua_duong_xet"
    assert tt["so_ho_so_theo_luat_kv"] == {"tat": 1}


# ═══════ Lượt H2 (owner 06-11) — điểm ĐỐI TƯỢNG theo công tắc của đường xét, giữ cách tính v1 ═══════
TAT_DOI_TUONG = """'{"apply_area_bonus": true, "apply_object_bonus": false}'::jsonb"""


async def _dung_bo_dtts(hs, **luat):
    """Hồ sơ DTTS ở xã KV1 (luật v1: mã 01, 2,00 điểm đối tượng), đặt luật ``luat`` cho đường xét
    in rồi DỰNG bộ thật; trả (DTO hàng in, thông tin dựng, DTO đọc ra = bộ xuất)."""
    async with AsyncSessionLocal() as db:
        await _tai_ba_mau(db, hs)
        await db.commit()
    cccd, pid = await _mot(hs, ethnicity="02")
    if luat:
        await _dat_luat(pid, **luat)
    _, anh = await _cong([cccd])
    sid = await _tao([cccd])
    async with AsyncSessionLocal() as db:
        dto, tt = (
            await db.execute(
                select(
                    CouncilDocumentSet.snapshot_dto, CouncilDocumentSet.thong_tin_dung
                ).where(CouncilDocumentSet.id == sid)
            )
        ).one()
    return dto[0], tt, anh.rows[0]


async def test_cong_tac_doi_tuong_bat_thi_in_diem_v1(hs):
    dong, tt, xuat = await _dung_bo_dtts(hs)  # phương thức giả: bật cả hai
    # Phép đo hợp lệ: luật v1 cho mã 01, 2,00 điểm.
    assert (xuat.ut_ma, xuat.diem_ut) == ("01", "2.00")
    assert (dong["ut_ma"], dong["diem_ut"]) == ("01", "2.00")
    assert tt["so_ho_so_theo_luat_ut"] == {"cong": 1}


async def test_cong_tac_doi_tuong_tat_thi_in_0_giu_kv(hs):
    dong, tt, xuat = await _dung_bo_dtts(hs, override=TAT_DOI_TUONG)
    assert xuat.diem_ut == "2.00"  # bộ xuất (luật v1) vẫn cộng — khác CÓ CHỦ Ý
    assert (dong["ut_ma"], dong["diem_ut"], dong["diem_kv"]) == ("01", "0", "0.75")
    assert tt["luat_diem_ut"] == "cong_tac_doi_tuong_cua_duong_xet_cach_tinh_v1"
    assert tt["so_ho_so_theo_luat_ut"] == {"tat": 1}


async def test_khong_co_luat_thi_diem_doi_tuong_0_nhu_t6(hs):
    dong, tt, _ = await _dung_bo_dtts(hs, override="NULL", mac_dinh="NULL")
    assert (dong["diem_ut"], dong["diem_kv"]) == ("0", "0.00")
    assert tt["so_ho_so_theo_luat_ut"] == {"khong_co_luat": 1}


async def test_giao_dich_doc_van_chi_doc_khi_tra_an_dinh_thu_cong(hs):
    # Phiên ORM tra sổ ấn định chạy TRÊN kết nối chỉ đọc: không mở giao dịch ghi nào.
    cccd, _ = await _an_dinh_thu_cong(hs)
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
    assert anh.giao_dich.transaction_read_only == "on"
    assert anh.kiem[0].kv_ly_do is None
