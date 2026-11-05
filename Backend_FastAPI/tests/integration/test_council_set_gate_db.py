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
    ma_gia,
    seed_hoi_dong,
)
from tests.integration.test_council_document_store import _dem, _tai_ba_mau

pytestmark = pytest.mark.integration

NV_SACH = [(1, "oto_cd", "cq", "g1")]
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


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_CHAN))
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


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_CANH_BAO))
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


@pytest.mark.parametrize("s", sorted(cong.TRANG_THAI_KHONG_CANH_BAO))
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


async def test_giao_dich_doc_van_chi_doc_khi_tra_an_dinh_thu_cong(hs):
    # Phiên ORM tra sổ ấn định chạy TRÊN kết nối chỉ đọc: không mở giao dịch ghi nào.
    cccd, _ = await _an_dinh_thu_cong(hs)
    anh = await doc.doc_ho_so_theo_ma(csdl.engine, [cccd], academic_year=2026)
    assert anh.giao_dich.transaction_read_only == "on"
    assert anh.kiem[0].kv_ly_do is None
