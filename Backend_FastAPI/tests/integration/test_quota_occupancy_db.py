# -*- coding: utf-8 -*-
"""F230 chặng 2b (C8) — MỘT nguồn đếm chỗ chỉ tiêu ``quota_occupancy_service`` trên PostgreSQL thật (CSDL test,
dữ liệu GIẢ dựng bằng SQL trong một giao dịch, lùi khi ra). Đặc tả ``ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md``
mục 5.4 + 5.6 (G9) + bổ sung lượt J; Codex lần 14 câu 5.

Mỗi điều Codex đòi có ca RIÊNG (CLAUDE.md §3), số kỳ vọng VIẾT TAY:

* A / B không đếm đôi một hồ sơ (hồ sơ chiếm chỗ + có dòng hiệu lực ⇒ một lần);
* Phần B dùng khoá CHỤP ở dòng bộ, không dùng giá trị hiện tại của hồ sơ (lead / nguyện vọng / applied_rules);
* lọc năm và ``exclude_profile_id`` nhất quán giữa A và B;
* ``withdrawn`` không đếm, ``withdrawal_pending`` VẪN đếm;
* điều chỉnh / huỷ ghi nhận / huỷ hiệu lực / khôi phục cho đúng số;
* dòng bộ thiếu khoá (NULL) — hành vi tạm theo đặc tả 1.1 + đếm để báo (câu hỏi owner mở — báo cáo lượt J);
* ``is_already_occupying`` (Phê duyệt cũ) = trạng thái chiếm chỗ HOẶC có dòng hiệu lực;
* ma trận chỉ tiêu: chỉ cột "approved" đổi, các cột phễu khác giữ nguyên;
* kiểm kê: tập trạng thái chiếm chỗ định nghĩa MỘT lần (AST toàn ``app/``).
"""
import ast
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import app.database as csdl
from app import models
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import BusinessRuleViolation
from tests.fixtures.hoi_dong_seed import danh_muc, ho_so, ma_gia

pytestmark = pytest.mark.integration

GOC = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def c(setup_test_database):
    """Một kết nối + giao dịch; lùi hết khi ra. ``info``: danh mục + hai "ô" chỉ tiêu X / Y."""
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        d = await danh_muc(conn)
        conn.info["d"] = d
        conn.info["so"] = 300
        for ten, (nganh, lh) in (("X", ("oto_cd", "cq")), ("Y", ("duoc_cd", "cq"))):
            path = d["psg"][(nganh, lh, "g1")][0]
            ai, off = (
                await conn.execute(
                    text(
                        "SELECT ap.academic_info_id, oai.offering_id FROM admission_path ap "
                        "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id "
                        "WHERE ap.id = :p"
                    ),
                    {"p": path},
                )
            ).one()
            conn.info[ten] = {"path": path, "ai": ai, "off": off, "nganh": nganh, "lh": lh}
        try:
            yield conn
        finally:
            await gd.rollback()


async def _x(c, sql, **ts):
    return await c.execute(text(sql), ts)


async def _hs(c, status="submitted", *, o=None, nv=None, kieu_cu=None, nam=2026):
    """Hồ sơ giả. ``o`` = ô của ``lead.offering_id``; ``nv`` = ô của nguyện vọng ``admitted`` (bộ máy NV);
    ``kieu_cu`` = ô của ``applied_rules.admission_path_id`` (hồ sơ một nguyện vọng kiểu cũ)."""
    c.info["so"] += 1
    d = c.info["d"]
    them = {}
    if nv is not None:
        o_nv = c.info[nv]
        them["nv"] = [(1, o_nv["nganh"], o_nv["lh"], "g1")]
    if kieu_cu is not None:
        them["uses_choice_engine"] = False
    pid = await ho_so(c, d, cccd=ma_gia(80000 + c.info["so"]), status=status, nam=nam, **them)
    if nv is not None:
        await _x(c, "UPDATE admission_profile_choice SET decision = 'admitted' WHERE admission_profile_id = :p", p=pid)
    if kieu_cu is not None:
        await _x(
            c,
            "UPDATE admission_profile SET applied_rules = CAST(:r AS jsonb) WHERE id = :p",
            r=json.dumps({"admission_path_id": c.info[kieu_cu]["path"]}),
            p=pid,
        )
    if o is not None:
        await _x(
            c,
            "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
            o=c.info[o]["off"],
            p=pid,
        )
    return pid


async def _bo(c, pids, o="X", *, nam=2026, thieu=None):
    """Một bộ + dòng bộ mang khoá đếm CHỤP của ô ``o`` (``thieu`` = tên cột khoá để NULL)."""
    k = c.info[o]
    sid = (
        await _x(
            c,
            "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, kich_thuoc_tong, "
            "ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES (now(), 'Cao đẳng', :n, 1, 1, "
            "CAST(:ma AS jsonb), CAST(:dto AS jsonb), '{}') RETURNING id",
            n=len(pids),
            ma=json.dumps(["GIA"] * len(pids)),
            dto=json.dumps([{}] * len(pids)),
        )
    ).scalar_one()
    khoa = {"admission_path_id": k["path"], "academic_info_id": k["ai"], "offering_id": k["off"]}
    if thieu:
        khoa[thieu] = None
    dong = []
    for i, p in enumerate(pids, 1):
        dong.append(
            (
                await _x(
                    c,
                    "INSERT INTO council_document_set_row (set_id, stt, profile_id, academic_year, "
                    "status_luc_dung, admission_path_id, academic_info_id, offering_id) VALUES "
                    "(:s, :i, :p, :y, 'approved', :ap, :ai, :off) RETURNING id",
                    s=sid,
                    i=i,
                    p=p,
                    y=nam,
                    ap=khoa["admission_path_id"],
                    ai=khoa["academic_info_id"],
                    off=khoa["offering_id"],
                )
            ).scalar_one()
        )
    return sid, dong


async def _qd(c, set_id, *, loai="trung_tuyen", goc_id=None, huy_qd_id=None, can_bo=None):
    c.info["so"] += 1
    if can_bo is None:
        can_bo = set_id is not None
    return (
        await _x(
            c,
            "INSERT INTO council_decision (loai, can_bo, set_id, goc_id, huy_qd_id, so_quyet_dinh, "
            "ngay_ky, pham_vi_so, trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES (:l, :cb, :s, :g, :h, "
            ":so, DATE '2026-09-08', 2026, 'hieu_luc', 0, 1) RETURNING id",
            l=loai,
            cb=can_bo,
            s=set_id,
            g=goc_id,
            h=huy_qd_id,
            so=str(c.info["so"]),
        )
    ).scalar_one()


async def _ghi_nhan(c, pids, o="X", **kw):
    """Bộ + Quyết định hiệu lực + dòng (chép từ dòng bộ, như ``chen_dong_tu_bo``) ⇒ (văn bản, [dòng QĐ])."""
    sid, dong = await _bo(c, pids, o, **kw)
    qd = await _qd(c, sid)
    await _x(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, profile_id, stt) "
        "SELECT :d, 'hieu_luc', r.set_id, r.id, r.profile_id, r.stt FROM council_document_set_row r "
        "WHERE r.set_id = :s",
        d=qd,
        s=sid,
    )
    ids = [r[0] for r in (await _x(c, "SELECT id FROM council_decision_row WHERE decision_id = :d ORDER BY stt", d=qd)).all()]
    return qd, ids


async def _dem(c, o, ex=None, nam=2026):
    """Số chỗ đã dùng của ô ``o`` ở BỐN nơi đếm (một phiên gắn vào giao dịch của ca)."""
    k = c.info[o]
    async with AsyncSession(bind=c) as db:
        return {
            "nganh_nam": await qos.dem_theo_nganh_nam(
                db, offering_id=k["off"], academic_year=nam, exclude_profile_id=ex
            ),
            "hoc_vu": await qos.dem_theo_thong_tin_hoc_vu(
                db, academic_info_id=k["ai"], exclude_profile_id=ex
            ),
            "duong_xet": await qos.dem_theo_duong_xet(
                db, admission_path_id=k["path"], exclude_profile_id=ex
            ),
            "ma_tran": (await qos.dem_da_trung_tuyen_theo_duong_xet(db, [k["path"]]))[k["path"]],
        }


def _deu(n, *, tru=()):
    return {k: n for k in ("nganh_nam", "hoc_vu", "duong_xet", "ma_tran") if k not in tru}


# ═══════════════════════════════ G9 — sáu hồ sơ, số viết tay cho bốn nơi đếm ═══════════════════
async def test_g9_sau_ho_so_so_viet_tay(c):
    # H1 chiếm chỗ (bộ máy NV, NV trúng ở X, lead X) · H2 chiếm chỗ (kiểu cũ, đường xét X, lead X) ·
    # H3 "Đã nộp" + QĐ X · H4 chiếm chỗ ở Y (NV + lead) NHƯNG QĐ chụp X ⇒ chỉ X, một lần ·
    # H5 "Chờ hoàn để rút" + QĐ X (vẫn giữ chỗ) · H6 "Đã rút" + QĐ X (trả chỗ).
    await _hs(c, "approved", o="X", nv="X")
    await _hs(c, "approved", o="X", kieu_cu="X")
    h3 = await _hs(c, "submitted")
    h4 = await _hs(c, "approved", o="Y", nv="Y")
    h5 = await _hs(c, "withdrawal_pending")
    h6 = await _hs(c, "withdrawn")
    await _ghi_nhan(c, [h3, h4, h5, h6], "X")
    assert await _dem(c, "X") == _deu(5)
    assert await _dem(c, "Y") == _deu(0)


# ═══════════════════════════════ A / B không đếm đôi ═══════════════════════════════════════════
async def test_a_b_khong_dem_doi_ho_so_chiem_cho_co_qd(c):
    # Hồ sơ chiếm chỗ ở ĐÚNG ô X theo mọi khoá hiện tại (lead, NV trúng) VÀ có dòng hiệu lực chụp X ⇒ 1.
    p = await _hs(c, "approved", o="X", nv="X")
    assert await _dem(c, "X") == _deu(1)
    await _ghi_nhan(c, [p], "X")
    assert await _dem(c, "X") == _deu(1)


async def test_a_b_khong_dem_doi_ho_so_kieu_cu_co_qd(c):
    p = await _hs(c, "confirmed", o="X", kieu_cu="X")
    await _ghi_nhan(c, [p], "X")
    assert await _dem(c, "X") == _deu(1)


# ═══════════════════════════════ Phần B theo khoá CHỤP ═════════════════════════════════════════
async def test_b_dung_khoa_chup_khong_dung_gia_tri_hien_tai(c):
    # Hiện tại hồ sơ trỏ Y ở MỌI khoá (lead, nguyện vọng — chưa trúng, applied_rules); dòng bộ chụp X.
    p = await _hs(c, "submitted", o="Y", kieu_cu="Y")
    await _x(
        c,
        "INSERT INTO admission_profile_choice (admission_profile_id, admission_path_id, "
        "path_subject_group_config_id, display_order, decision) VALUES (:p, :ap, :psg, 1, 'pending')",
        p=p,
        ap=c.info["Y"]["path"],
        psg=c.info["d"]["psg"][("duoc_cd", "cq", "g1")][1],
    )
    await _ghi_nhan(c, [p], "X")
    assert await _dem(c, "X") == _deu(1)
    assert await _dem(c, "Y") == _deu(0)


async def test_b_nam_chup_khong_theo_nam_hien_tai_cua_ho_so(c):
    # Năm học của hồ sơ bị sửa SAU khi dựng bộ (2026 → 2027): Phần B vẫn ở năm CHỤP 2026.
    p = await _hs(c, "submitted")
    await _ghi_nhan(c, [p], "X")
    await _x(c, "UPDATE admission_profile SET academic_year = 2027 WHERE id = :p", p=p)
    k = c.info["X"]
    async with AsyncSession(bind=c) as db:
        n26 = await qos.dem_theo_nganh_nam(db, offering_id=k["off"], academic_year=2026)
        n27 = await qos.dem_theo_nganh_nam(db, offering_id=k["off"], academic_year=2027)
    assert (n26, n27) == (1, 0)


async def test_b_chi_dong_hieu_luc_khong_tinh_dong_bo_chua_ghi_nhan(c):
    # Đối chứng: dòng bộ (bộ nháp, chưa có Quyết định) KHÔNG chiếm chỗ.
    p = await _hs(c, "submitted")
    await _bo(c, [p], "X")
    assert await _dem(c, "X") == _deu(0)


# ═══════════════════════════════ lọc năm + exclude_profile_id nhất quán A / B ═════════════════
async def test_loc_nam_a_va_b_cung_nam(c):
    # Ô ngành + năm: A theo năm của hồ sơ, B theo năm CHỤP ở dòng bộ — cả hai ở 2025 ⇒ 2026 không thấy.
    await _hs(c, "approved", o="X", nv="X", nam=2025)
    p = await _hs(c, "submitted", nam=2025)
    await _ghi_nhan(c, [p], "X", nam=2025)
    k = c.info["X"]
    async with AsyncSession(bind=c) as db:
        n26 = await qos.dem_theo_nganh_nam(db, offering_id=k["off"], academic_year=2026)
        n25 = await qos.dem_theo_nganh_nam(db, offering_id=k["off"], academic_year=2025)
    assert (n26, n25) == (0, 2)


@pytest.mark.parametrize("phan", ["A", "B"])
async def test_exclude_profile_id_loai_ca_hai_phan(c, phan):
    a = await _hs(c, "approved", o="X", nv="X")
    b = await _hs(c, "submitted")
    await _ghi_nhan(c, [b], "X")
    ex = a if phan == "A" else b
    assert await _dem(c, "X") == _deu(2)
    d = await _dem(c, "X", ex=ex)
    d.pop("ma_tran")  # ma trận không có exclude (hiển thị)
    assert d == {"nganh_nam": 1, "hoc_vu": 1, "duong_xet": 1}


# ═══════════════════════════════ withdrawn / withdrawal_pending ════════════════════════════════
async def test_b_cho_hoan_de_rut_van_giu_cho(c):
    p = await _hs(c, "withdrawal_pending")
    await _ghi_nhan(c, [p], "X")
    assert await _dem(c, "X") == _deu(1)


async def test_b_da_rut_han_tra_cho(c):
    p = await _hs(c, "withdrawn")
    await _ghi_nhan(c, [p], "X")
    assert await _dem(c, "X") == _deu(0)


# ═══════════════════════════════ điều chỉnh / huỷ ghi nhận / huỷ hiệu lực / khôi phục ═════════
async def test_dieu_chinh_huy_ghi_nhan_huy_hieu_luc_khoi_phuc_dung_so(c):
    p = await _hs(c, "submitted")
    q1, (r1,) = await _ghi_nhan(c, [p], "X")
    assert (await _dem(c, "X"), await _dem(c, "Y")) == (_deu(1), _deu(0))
    # Điều chỉnh "sửa ngành X → Y": bỏ dòng cũ TRƯỚC, thêm dòng của bộ điều chỉnh (chụp Y) SAU.
    s2, (sr2,) = await _bo(c, [p], "Y")
    q2 = await _qd(c, s2, loai="dieu_chinh", goc_id=q1)
    await _x(c, "UPDATE council_decision_row SET bi_bo_boi_id = :q WHERE id = :r", q=q2, r=r1)
    await _x(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, profile_id, stt) "
        "VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=q2,
        s=s2,
        r=sr2,
        p=p,
    )
    assert (await _dem(c, "X"), await _dem(c, "Y")) == (_deu(0), _deu(1))
    # Huỷ ghi nhận điều chỉnh (nhập sai): dòng của nó tắt (CSDL lan), dòng cũ bật lại.
    await _x(
        c,
        "UPDATE council_decision SET trang_thai = 'huy_ghi_nhan', huy_ghi_nhan_boi_id = 1, huy_ghi_nhan_luc = now(), "
        "ly_do_huy_ghi_nhan = 'GIA nhap sai' WHERE id = :q",
        q=q2,
    )
    await _x(c, "UPDATE council_decision_row SET bi_bo_boi_id = NULL WHERE bi_bo_boi_id = :q", q=q2)
    assert (await _dem(c, "X"), await _dem(c, "Y")) == (_deu(1), _deu(0))
    # Huỷ hiệu lực (văn bản huỷ của trường): trả chỗ.
    h = await _qd(c, None, loai="van_ban_huy", huy_qd_id=q1, can_bo=False)
    await _x(
        c,
        "UPDATE council_decision SET trang_thai = 'het_hieu_luc', het_hieu_luc_boi_id = :h WHERE id = :q",
        h=h,
        q=q1,
    )
    assert await _dem(c, "X") == _deu(0)
    # Khôi phục (huỷ ghi nhận văn bản huỷ): Quyết định hiệu lực lại ⇒ chiếm chỗ lại.
    await _x(
        c,
        "UPDATE council_decision SET trang_thai = 'huy_ghi_nhan', huy_ghi_nhan_boi_id = 1, huy_ghi_nhan_luc = now(), "
        "ly_do_huy_ghi_nhan = 'GIA nhap sai' WHERE id = :h",
        h=h,
    )
    await _x(
        c,
        "UPDATE council_decision SET trang_thai = 'hieu_luc', het_hieu_luc_boi_id = NULL WHERE id = :q",
        q=q1,
    )
    assert await _dem(c, "X") == _deu(1)


# ═══════════════════════════════ dòng bộ thiếu khoá (câu hỏi owner mở) ═════════════════════════
@pytest.mark.parametrize(
    "thieu, noi",
    [("admission_path_id", "duong_xet"), ("academic_info_id", "hoc_vu"), ("offering_id", "nganh_nam")],
)
async def test_dong_bo_thieu_khoa_khong_khop_noi_can_khoa_va_duoc_dem_de_bao(c, thieu, noi):
    # Hành vi TẠM theo đặc tả 1.1 ("Rỗng được … không đếm dòng ở nơi cần khoá ấy") — gặp thì làm gì là CÂU HỎI
    # OWNER (báo cáo lượt J). Không đường dựng bộ nào tạo được dòng này (cổng dữ liệu — xem ca API); ca này khoá
    # để hành vi KHÔNG đổi âm thầm và có số đếm để báo.
    p = await _hs(c, "submitted")
    await _ghi_nhan(c, [p], "X", thieu=thieu)
    ky_vong = _deu(1)
    ky_vong[noi] = 0
    if thieu == "admission_path_id":
        ky_vong["ma_tran"] = 0  # ma trận cũng theo đường xét
    assert await _dem(c, "X") == ky_vong
    async with AsyncSession(bind=c) as db:
        cot = getattr(models.CouncilDocumentSetRow, thieu)
        assert await qos.so_dong_hieu_luc_thieu_khoa(db, cot) == 1


# ═══════════════════════════════ is_already_occupying (Phê duyệt cũ) ══════════════════════════
async def test_dang_chiem_cho_trang_thai_hoac_dong_hieu_luc(c):
    a = await _hs(c, "submitted")
    b = await _hs(c, "submitted")
    e = await _hs(c, "approved")
    await _ghi_nhan(c, [a], "X")
    async with AsyncSession(bind=c) as db:
        hs = {p: await db.get(models.AdmissionProfile, p) for p in (a, b, e)}
        assert await qos.dang_chiem_cho(db, hs[a]) is True
        assert await qos.dang_chiem_cho(db, hs[b]) is False
        assert await qos.dang_chiem_cho(db, hs[e]) is True


async def test_phe_duyet_cu_em_co_qd_khong_cong_them_cho(c):
    # Chỉ tiêu ô X = 1: Q chiếm chỗ (A); P "Đã nộp" có QĐ chụp X (B — ghi nhận vượt được, N9). Duyệt kiểu cũ cho
    # P (lead X) KHÔNG cộng thêm chỗ (P đã được đếm ở B): đếm người khác (trừ P) = 1 ≤ 1 ⇒ qua; nếu coi P "chưa
    # chiếm chỗ" thì 1 + 1 > 1 ⇒ chặn sai. Đối chứng cùng ca: R (không QĐ) bị chặn vì vượt chỉ tiêu.
    from app.services import admission_service as asv

    await _x(c, "UPDATE offering_academic_info SET annual_admission_quota = 1 WHERE id = :a", a=c.info["X"]["ai"])
    await _hs(c, "approved", o="X", nv="X")
    p = await _hs(c, "submitted", o="X")
    r = await _hs(c, "submitted", o="X")
    await _ghi_nhan(c, [p], "X")
    async with AsyncSession(bind=c) as db:
        nap = [selectinload(models.AdmissionProfile.lead)]
        hp = await db.get(models.AdmissionProfile, p, options=nap)
        await asv._assert_quota_or_bypass(db, hp, None, False, None, transition="approve")
        hr = await db.get(models.AdmissionProfile, r, options=nap)
        with pytest.raises(BusinessRuleViolation):
            await asv._assert_quota_or_bypass(db, hr, None, False, None, transition="approve")


# ═══════════════════════════════ ma trận: chỉ cột "approved" đổi ═════════════════════════════
async def test_ma_tran_chi_cot_approved_doi_cac_cot_pheu_giu_nguyen(c):
    from app.services.quota_matrix_service import QuotaMatrixService

    # P: "Đã nhập học", NV trúng ở Y (hiện tại), QĐ chụp X ⇒ approved: X 1 / Y 0; enrolled + submitted theo
    # nguyện vọng hiện tại như cũ: Y 1 / X 0.
    p = await _hs(c, "enrolled", nv="Y")
    await _ghi_nhan(c, [p], "X")
    x, y = c.info["X"]["path"], c.info["Y"]["path"]
    async with AsyncSession(bind=c) as db:
        fc = await QuotaMatrixService(db)._compute_funnel_counts([x, y])
    assert fc[x] == {"submitted": 0, "approved": 1, "enrolled": 0, "dropped": 0}
    assert fc[y] == {"submitted": 1, "approved": 0, "enrolled": 1, "dropped": 0}


# ═══════════════════════════════ kiểm kê: tập trạng thái chiếm chỗ MỘT định nghĩa ═════════════
NAM = {"approved", "overridden", "admitted", "confirmed", "enrolled"}
#: Bộ chữ TRÙNG tập chiếm chỗ nhưng KHÁC khái niệm, được phép: mức "không cảnh báo" của cổng dựng bộ (F228 —
#: owner chốt trạng thái nào vào Quyết định không cần xác nhận) — không phải câu hỏi "chiếm chỗ".
NGOAI_LE = {("services/council_set_gate_service.py", "TRANG_THAI_KHONG_CANH_BAO")}


def _ten_gan(cay):
    """{nút literal: tên được gán} cho các phép gán ở mọi cấp."""
    out = {}
    for n in ast.walk(cay):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            dich = n.targets if isinstance(n, ast.Assign) else [n.target]
            ten = [t.id for t in dich if isinstance(t, ast.Name)]
            if n.value is not None and ten:
                for con in ast.walk(n.value):
                    out[id(con)] = ten[0]
    return out


def test_trang_thai_chiem_cho_dinh_nghia_mot_lan():
    from app.services import admission_choice_engine_service as eng
    from app.services import admission_service as asv

    assert asv.QUOTA_OCCUPYING_STATUSES is qos.TRANG_THAI_CHIEM_CHO
    assert eng._QUOTA_OCCUPYING_STATUSES is qos.TRANG_THAI_CHIEM_CHO
    assert set(qos.TRANG_THAI_CHIEM_CHO) == NAM and len(qos.TRANG_THAI_CHIEM_CHO) == 5
    thay = []
    for tep in sorted((GOC / "app").rglob("*.py")):
        cay = ast.parse(tep.read_text(encoding="utf-8"))
        ten = _ten_gan(cay)
        for n in ast.walk(cay):
            if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
                gt = [e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if len(gt) == len(n.elts) and set(gt) == NAM:
                    thay.append((tep.relative_to(GOC / "app").as_posix(), ten.get(id(n))))
    assert ("services/quota_occupancy_service.py", "TRANG_THAI_CHIEM_CHO") in thay, thay
    ngoai = set(thay) - {("services/quota_occupancy_service.py", "TRANG_THAI_CHIEM_CHO")}
    assert ngoai == NGOAI_LE, sorted(ngoai)
