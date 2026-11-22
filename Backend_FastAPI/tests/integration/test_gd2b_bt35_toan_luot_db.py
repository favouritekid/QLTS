# tests/integration/test_gd2b_bt35_toan_luot_db.py
"""GĐ2-B đợt 2 — nghiệm thu BT35 trên TOÀN lượt chạy "Kiểm hồ sơ" + các khoá một nguồn của bộ nạp theo lô.

* BT35 (đặc tả bản 4 :617; owner K1 21-11; đề cương đợt 2 §4): đếm MỌI câu SQL gửi xuống driver trên CẢ HAI kết nối (ảnh chụp
  chỉ đọc + giao dịch chính) từ lúc gọi dịch vụ tới ``commit`` — khoá thử, đọc lần xét, nạp, tính lại KV F231, ghi run + dòng, vết.
  10, 200 rồi 1.500 hồ sơ (owner Q3 22-11: đúng ở MỌI cỡ — 1.500 > khúc 500 của ``selectinload``) cùng bộ gieo, kết quả XEN KẼ (được xếp · thiếu giấy + học phí HK1 · dừng ở NV · đủ nhánh F231 · ấn định thủ
  công hợp lệ · có hồ sơ năm trước A13). Khẳng định: tổng câu như nhau; ghi dòng đúng MỘT câu, KHÔNG ``executemany`` (Codex 22-11
  mục D P1); hai kết nối thật sự khác nhau (ca đối chứng: đếm một kết nối thì phép so 10 / 200 vô nghĩa).
* Dữ kiện E6 mức hồ sơ của bộ nạp == ``CheckData`` của bản in GĐ1 (``read_profiles_by_id``) — khoá F231 đường lô = đường từng hồ
  sơ trên đủ nhánh (CLAUDE.md §7: bản in đổi sang đường lô là PR riêng).
* K2: khoản HK1 = khoản ``tuition`` HK1 CHƯA huỷ có ``id`` lớn nhất (khoản cũ đã đóng + khoản mới hơn đã huỷ ⇒ chọn khoản cũ); mệnh đề
  chép nguyên chữ của bản in.
* Tổng điểm môn của NV = cột ``tong_diem`` của bản in cho NV in.
* Bộ đếm mọi học vụ trong một câu == ``count_by_academic_info`` / ``count_by_offering_year`` / ``count_by_group`` (nhóm một thành viên).
* Cổng nguyện vọng trên đồ thị nạp theo lô == trên đồ thị ``selectinload`` của T6 (cùng đường ``t6_profile_load_paths``).
* Owner Q5 22-11: NV trỏ tới học vụ năm khác ⇒ DỪNG ``choice_academic_year_mismatch``, NV sau không xét.
* Owner Q7 22-11: A13 so CCCD sau khi xoá MỌI khoảng trắng ở cả hai phía; rỗng sau khi xoá ⇒ không so.

Mã lý do / tab viết TAY theo đặc tả (không lấy từ mã — lấy từ mã thì đổi mã là đổi luôn ca kiểm).
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from app.repositories import admission_review_load_repository as load_repo
from app.repositories.council_candidate_repository import SQL_PRINT_FIGURES, read_only_transaction, read_print_figures
from app.services import admission_review_loader as loader
from app.services import admission_review_rules as rules
from app.services import admission_review_run_service as run_service
from app.services import council_candidate_service as doc
from app.services import quota_occupancy_service as qos
from app.services.admission_choice_engine_service import t6_profile_load_options
from app.services.priority_service import kv_inputs_fingerprint
from tests.fixtures.hoi_dong_seed import chen, danh_muc, ho_so, kv, lich_su_thpt, ma_gia

pytestmark = pytest.mark.integration

NAM = 2026
DIEM = {"toan": "8.00", "ly": "7.00", "hoa": "9.00"}
HP = dict(fee_type="tuition", semester_no=1, status="paid", paid_amount="1000", resolved_major="oto_cd",
          resolved_degree_level="Cao đẳng")
KHAI_SINH = dict(loai="giay_khai_sinh", status="verified", actual_submission_format="certified_copy")
QUY_TAC_GIAY = {"mandatory_docs": ["giay_khai_sinh"], "doc_configs": {"giay_khai_sinh": {"is_mandatory": True}}}
LUC_THU_CONG = "2026-10-02T03:04:05+00:00"

#: Mười kiểu hồ sơ XEN KẼ (chu kỳ 10) và kết quả mong đợi (tab, mã lý do) — viết tay theo đặc tả §6.2 / §6.5 / §6.7.
KIEU = (
    "xep_nam_truoc",
    "thieu_giay_hp",
    "dung_nv",
    "thieu_kv",
    "tc_hop_le",
    "tc_khong_hl",
    "kv_doi",
    "kv_hong",
    "chua_muc",
    "muc_lech",
)
MONG_DOI = {
    "xep_nam_truoc": ("auto", []),
    "thieu_giay_hp": ("ineligible", ["mandatory_document_missing", "thieu_hoc_phi_hk1"]),
    "dung_nv": ("ineligible", ["floor_missing"]),
    "thieu_kv": ("ineligible", ["thieu_khu_vuc"]),
    "tc_hop_le": ("auto", []),
    "tc_khong_hl": ("ineligible", ["khu_vuc_thu_cong_khong_hieu_luc"]),
    "kv_doi": ("ineligible", ["khu_vuc_doi_sau_anh_chup"]),
    "kv_hong": ("ineligible", ["khu_vuc_khong_tinh_lai_duoc"]),
    "chua_muc": ("ineligible", ["chua_co_muc_khu_vuc"]),
    "muc_lech": ("ineligible", ["muc_khu_vuc_khong_nhat_quan"]),
}
SAU_NHANH_F231 = {
    "thieu_khu_vuc",
    "khu_vuc_thu_cong_khong_hieu_luc",
    "khu_vuc_doi_sau_anh_chup",
    "khu_vuc_khong_tinh_lai_duoc",
    "chua_co_muc_khu_vuc",
    "muc_khu_vuc_khong_nhat_quan",
}


async def _x(conn, cau, **ts):
    return await conn.execute(text(cau), ts)


async def _nen(conn) -> dict:
    """Danh mục GĐ1 + phần GĐ2-B cần: trình độ + tiêu chí (cổng NV qua được), bảng chỉ tiêu năm + nhóm + thành viên, lần xét nháp +
    sàn (chỉ ô tô CĐ — Dược CĐ thiếu sàn ⇒ ca "dừng ở NV"), loại giấy cư trú, mức đối tượng, mức KV: KV3 không còn mức mở năm 2026,
    KV2-NT hai mức mở năm 2026."""
    d = await danh_muc(conn)
    dl = await chen(conn, "config_degree_level", code="cao_dang", name="Cao đẳng giả", display_order=2, is_active=True)
    d["ai"], d["duong"] = {}, {}
    for k in ("oto_cd", "duoc_cd"):
        await _x(conn, "UPDATE major_program SET degree_level_id = :dl WHERE id = :m", dl=dl, m=d["mp"][k])
        ap, _ = d["psg"][(k, "cq", "g1")]
        cr = await chen(conn, "admission_criteria", method_id=d["pt"], code="GIA-TC-" + k, name="Tiêu chí giả " + k,
                        is_active=True, subject_selection_mode="fixed", scoring_method="sum", policy_version="2025.1")
        await _x(conn, "UPDATE admission_path SET criteria_id = :c WHERE id = :a", c=cr, a=ap)
        d["duong"][k] = ap
        d["ai"][k] = (await _x(conn, "SELECT academic_info_id FROM admission_path WHERE id = :a", a=ap)).scalar_one()
        await _x(conn, "UPDATE offering_academic_info SET annual_admission_quota = 500 WHERE id = :i", i=d["ai"][k])
    await _x(conn, "INSERT INTO admission_quota_table (academic_year, status, version) VALUES (:y, 'draft', 1)", y=NAM)
    d["nhom"] = {}
    for k in ("oto_cd", "duoc_cd"):
        d["nhom"][k] = await chen(conn, "admission_quota_group", academic_year=NAM, code="GIA-N-" + k, name="Nhóm giả " + k,
                                  ceiling=1000)
        await chen(conn, "admission_quota_group_member", group_id=d["nhom"][k], offering_academic_info_id=d["ai"][k],
                   academic_year=NAM)
    d["lan_xet"] = await chen(conn, "admission_review_session", academic_year=NAM, admission_round_id=d["vong"], seq_no=1,
                              status="draft", version=1, created_by_user_id=d["nguoi"])
    await chen(conn, "admission_review_floor", session_id=d["lan_xet"], academic_year=NAM,
               offering_academic_info_id=d["ai"]["oto_cd"], floor_score="10.00", updated_by_user_id=d["nguoi"])
    d["giay"]["giay_xac_nhan_cu_tru"] = await chen(
        conn, "config_document_type", code="giay_xac_nhan_cu_tru", name="Giấy cư trú giả", display_order=99, is_active=True
    )
    for ma, diem in (("01", "2.00"), ("06", "1.00")):
        await chen(conn, "priority_object_config", academic_year=NAM, group_code="UT1", sub_code=ma,
                   description="Đối tượng giả " + ma, bonus_points=diem, effective_from=date(2026, 1, 1))
    await _x(conn, "UPDATE priority_area_config SET effective_to = DATE '2026-06-30' "
                   "WHERE academic_year = 2026 AND area_code = 'KV3'")
    await chen(conn, "priority_area_config", academic_year=NAM, area_code="KV2-NT", area_name="Khu vực giả KV2-NT trùng",
               bonus_points="0.40", effective_from=date(2026, 6, 1))
    return d


async def _ho_so_kieu(conn, d, i: int, kieu: str) -> int:
    cccd = ma_gia(20_000 + i)
    goc = dict(
        full_name="Họ Giả Lần Xét",
        dob=date(2008, 1, 1),
        gender="Nam",
        ethnicity="01",
        permanent_commune_code="GX1",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot=kv("KV1"),
        academic_history=lich_su_thpt(d, "KV1"),
        nv=[(1, "oto_cd", "cq", "g1")],
        diem={0: DIEM},
        hoc_phi=[HP],
        giay=[KHAI_SINH],
        status="submitted",
    )
    thu_cong = {
        "kv_resolved": "KV1",
        "rule_applied": "manual_override",
        "manual_override_by": d["nguoi"],
        "manual_override_at": LUC_THU_CONG,
        "manual_override_reason": "Lý do giả ấn định khu vực đủ dài",
    }
    if kieu == "thieu_giay_hp":
        goc.update(giay=[], hoc_phi=[])
    elif kieu == "dung_nv":
        goc.update(nv=[(1, "duoc_cd", "cq", "g1"), (2, "oto_cd", "cq", "g1")], diem={0: DIEM, 1: DIEM},
                   hoc_phi=[dict(HP, resolved_major="duoc_cd")])
    elif kieu == "thieu_kv":
        goc.update(priority_resolution_snapshot={})
    elif kieu in ("tc_hop_le", "tc_khong_hl"):
        goc.update(area_resolution_basis="manual_override", priority_resolution_snapshot=thu_cong)
    elif kieu == "kv_doi":
        goc.update(academic_history=lich_su_thpt(d, "KV2"))
    elif kieu == "kv_hong":
        goc.update(academic_history=[dict(lich_su_thpt(d, "KV1")[0], year_from="2023")])
    elif kieu == "chua_muc":
        goc.update(priority_resolution_snapshot=kv("KV3"), academic_history=lich_su_thpt(d, "KV3"))
    elif kieu == "muc_lech":
        goc.update(priority_resolution_snapshot=kv("KV2-NT"), academic_history=lich_su_thpt(d, "KV2-NT"))
    pid = await ho_so(conn, d, cccd=cccd, **goc)
    await _x(conn, "UPDATE admission_profile SET applied_rules = CAST(:a AS jsonb) WHERE id = :p",
             a=json.dumps(QUY_TAC_GIAY), p=pid)
    if kieu == "tc_hop_le":
        dau = kv_inputs_fingerprint(SimpleNamespace(
            cultural_education_level=goc["cultural_education_level"],
            vocational_qualification=goc["vocational_qualification"],
            permanent_commune_code=goc["permanent_commune_code"],
            academic_year=NAM,
            academic_history=goc["academic_history"],
        ))
        await chen(conn, "priority_audit_log", profile_id=pid, action_type="kv_manual_override", actor_id=d["nguoi"],
                   new_value={"kv_resolved": "KV1"}, metadata={"actor_role": "admin", "kv_inputs_fingerprint": dau},
                   created_at=datetime(2026, 10, 2, 3, 4, 6, tzinfo=timezone.utc))
    if kieu == "xep_nam_truoc":
        await ho_so(conn, d, cccd=cccd, nam=NAM - 1, status="approved")
    return pid


async def _gieo(d, tu: int, den: int) -> dict:
    kieu_cua = {}
    async with csdl.engine.begin() as conn:
        for i in range(tu, den):
            k = KIEU[i % len(KIEU)]
            kieu_cua[await _ho_so_kieu(conn, d, i, k)] = k
    return kieu_cua


@pytest_asyncio.fixture
async def nen(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await _nen(conn)


class _Dem:
    """Mọi câu gửi xuống driver của MỌI kết nối thuộc ``csdl.engine`` (listener cấp engine) — ghi (kết nối, đầu câu, executemany)."""

    def __init__(self):
        self.cau = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.cau.append((id(conn.connection.dbapi_connection), " ".join(statement.split()[:4]), executemany))

    def theo_ket_noi(self):
        out = {}
        for k, dau, _ in self.cau:
            out.setdefault(k, []).append(dau)
        return out


async def _chay_va_dem(d):
    dem = _Dem()
    dong_co = csdl.engine.sync_engine
    event.listen(dong_co, "before_cursor_execute", dem)
    try:
        async with AsyncSessionLocal() as db:
            run, _ = await run_service.run_evaluate(
                db, engine=csdl.engine, session_id=d["lan_xet"], session_version=1, actor_user_id=d["nguoi"]
            )
            run_id = run.id
            await db.commit()
    finally:
        event.remove(dong_co, "before_cursor_execute", dem)
    return run_id, dem


async def _dong_cua_run(run_id):
    async with csdl.engine.connect() as conn:
        return {
            r.profile_id: r
            for r in (
                await _x(conn, "SELECT profile_id, tab, reason_codes, flags, prior_year_findings "
                               "FROM admission_review_row WHERE run_id = :r", r=run_id)
            ).all()
        }


#: Cỡ đo BT35 (owner Q3 22-11: đúng ở mọi cỡ; đo thêm ở 1.500 — vượt khúc 500 khoá của ``selectinload``).
CO_DO = (10, 200, 1500)


@pytest.mark.timeout(300)
async def test_bt35_toan_luot_so_cau_sql_nhu_nhau_voi_10_200_va_1500_ho_so(nen):
    d = nen
    ket_qua = {}
    kieu_cua = {}
    for tu, den in zip((0,) + CO_DO[:-1], CO_DO):
        kieu_cua.update(await _gieo(d, tu, den))
        run_id, dem = await _chay_va_dem(d)
        dong = await _dong_cua_run(run_id)
        assert len(dong) == den, (den, len(dong))
        for pid, k in kieu_cua.items():
            tab, ly_do = MONG_DOI[k]
            assert (dong[pid].tab, sorted(dong[pid].reason_codes)) == (tab, ly_do), (k, dong[pid])
            co_a13 = "same_citizen_admitted_previous_year" in dong[pid].flags
            assert co_a13 == (k == "xep_nam_truoc"), (k, dong[pid].flags)
            if co_a13:
                thay = dong[pid].prior_year_findings
                thay = json.loads(thay) if isinstance(thay, str) else thay
                assert thay == [{"year": NAM - 1, "basis": "occupying_status", "status": "approved"}], thay
        ket_qua[den] = dem
    nho = ket_qua[CO_DO[0]]
    # Ca đối chứng (đếm phải trên HAI kết nối): ảnh chụp chỉ đọc và giao dịch chính là hai kết nối khác nhau, cả hai có câu.
    for dem in ket_qua.values():
        theo = dem.theo_ket_noi()
        assert len(theo) == 2, {k: len(v) for k, v in theo.items()}
        anh_chup = [v for v in theo.values() if any(c.startswith("SELECT current_setting('transaction_isolation')") for c in v)]
        chinh = [v for v in theo.values() if any(c.startswith("INSERT INTO admission_review_row") for c in v)]
        assert len(anh_chup) == 1 and len(chinh) == 1 and anh_chup[0] is not chinh[0]
        ghi = [(dau, em) for _, dau, em in dem.cau if dau.startswith("INSERT INTO admission_review_row")]
        assert ghi == [(ghi[0][0], False)], ghi  # MỘT câu, không executemany
    for co in CO_DO[1:]:
        lon = ket_qua[co]
        assert len(lon.cau) == len(nho.cau), (co, len(nho.cau), len(lon.cau))
        assert sorted(len(v) for v in lon.theo_ket_noi().values()) == sorted(
            len(v) for v in nho.theo_ket_noi().values()
        ), co


async def _nap(d):
    async with read_only_transaction(csdl.engine) as (conn, _):
        return await loader.load_run_facts(conn, session_id=d["lan_xet"], session_version=1, fee_gate_mode="legacy")


async def test_dieu_kien_muc_ho_so_bang_ban_in_gd1_tren_du_nhanh_f231(nen):
    """Dữ kiện E6 mức hồ sơ (gồm kết quả F231 ``kv_ly_do`` / ``kv_muc``, luật cộng điểm, NV in) của bộ nạp theo lô == ``CheckData``
    mà bản in GĐ1 dựng bằng đường TỪNG HỒ SƠ (``_resolve_area`` + ``_area_recompute_mismatch``) cho cùng hồ sơ, cùng thứ tự."""
    await _gieo(nen, 0, len(KIEU))
    nap = await _nap(nen)
    pids = [p.profile_id for p in nap.profiles]
    ban_in = await doc.read_profiles_by_id(csdl.engine, pids, academic_year=NAM)
    assert tuple(p.check for p in nap.profiles) == ban_in.check_data
    # Phép đo không rỗng: đủ sáu nhánh chặn F231 + nhánh qua (mức theo năm).
    assert SAU_NHANH_F231 <= {p.check.kv_ly_do for p in nap.profiles}
    assert any(p.check.kv_ly_do is None and p.check.kv_muc == "0.75" for p in nap.profiles)
    # Tổng điểm môn của NV in == cột ``tong_diem`` của bản in.
    async with read_only_transaction(csdl.engine) as (conn, _):
        so_lieu = {h["pid"]: h for h in await read_print_figures(conn, pids)}
    so_sanh = 0
    for p in nap.profiles:
        nv_in = so_lieu[p.profile_id]["nv_in_id"]
        for c in p.choices:
            if c.choice_id == nv_in and so_lieu[p.profile_id]["tong_diem"] != "":
                assert c.subject_total == Decimal(so_lieu[p.profile_id]["tong_diem"]), p.profile_id
                so_sanh += 1
    assert so_sanh >= 1
    # Cổng NV trên đồ thị nạp theo lô == trên đồ thị ``selectinload`` của T6 (cùng đường ``t6_profile_load_paths``).
    async with read_only_transaction(csdl.engine) as (conn, _):
        orm = AsyncSession(bind=conn)
        try:
            t6 = (
                await orm.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id.in_(pids))
                    .options(*t6_profile_load_options())
                )
            ).scalars().all()
            cong_t6 = {int(c.id): rules.choice_gate_facts(p, c) for p in t6 for c in p.choices}
        finally:
            await orm.close()
    cong_lo = {c.choice_id: c.gate for p in nap.profiles for c in p.choices}
    assert cong_lo == cong_t6
    assert {g.status for g in cong_lo.values()} >= {rules.GATE_PASSED}


async def _hoc_vu_nam_khac(conn, d) -> int:
    """Học vụ ô tô CĐ NĂM TRƯỚC (chỉ tiêu 500) + đường xét + tổ hợp g1 — khoá ``d["psg"][("oto_cd_nam_truoc", "cq", "g1")]``."""
    off = (await _x(conn, "SELECT offering_id FROM offering_academic_info WHERE id = :i", i=d["ai"]["oto_cd"])).scalar_one()
    ai_cu = await chen(conn, "offering_academic_info", academic_year=NAM - 1, is_published=True, offering_id=off,
                       annual_admission_quota=500)
    ap_cu = await chen(conn, "admission_path", academic_info_id=ai_cu, admission_method_id=d["pt"], status="active",
                       display_order=1, visibility="public", admission_round_id=d["vong"],
                       created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                       updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    psg_cu = await chen(conn, "path_subject_group_config", admission_path_id=ap_cu, subject_group_id=d["to_hop"]["g1"])
    d["psg"][("oto_cd_nam_truoc", "cq", "g1")] = (ap_cu, psg_cu)
    return ai_cu


async def _ho_so_hai_nv(conn, d, so: int, nv2: str, nganh_hp: str) -> int:
    """Hồ sơ sạch: NV1 ô tô CĐ 2026 (đạt sàn), NV2 ``nv2``, học phí HK1 gán ngành ``nganh_hp``."""
    pid = await ho_so(
        conn, d, cccd=ma_gia(so), full_name="Họ Giả Hai Nguyện Vọng", dob=date(2008, 1, 1), gender="Nam", ethnicity="01",
        permanent_commune_code="GX1", cultural_education_level="graduated_thpt", vocational_qualification="none",
        priority_resolution_snapshot=kv("KV1"), academic_history=lich_su_thpt(d, "KV1"),
        nv=[(1, "oto_cd", "cq", "g1"), (2, nv2, "cq", "g1")], diem={0: DIEM, 1: DIEM},
        hoc_phi=[dict(HP, resolved_major=nganh_hp)], giay=[KHAI_SINH], status="submitted",
    )
    await _x(conn, "UPDATE admission_profile SET applied_rules = CAST(:a AS jsonb) WHERE id = :p",
             a=json.dumps(QUY_TAC_GIAY), p=pid)
    return pid


async def test_q5_doi_xung_nv1_da_xep_nv2_nam_khac_khong_doi_ket_qua_va_khong_goi_y_nv_sau(nen):
    """Codex 22-11 lượt 2 B-P4: (a) NV1 hợp lệ đã được xếp, NV2 thuộc năm khác ⇒ NV1 GIỮ kết quả (``auto``), NV2
    ``not_considered``; (b) ``needs_decision`` (lệch ngành học phí) mà NV sau DUY NHẤT thuộc năm khác ⇒ KHÔNG gợi ý
    ``consider_next_choice``; (c) owner 22-11 "mọi mã dừng" (``gd2/gd2b/dot2/QUYET-DINH-OWNER-GD2B-DOT2-MOI-MA-DUNG-2026-11-22.md``):
    NV sau cùng năm nhưng THIẾU SÀN (Dược CĐ — bước 5, máy xét dừng) ⇒ KHÔNG gợi ý; (d) đối chứng: thêm sàn cho Dược CĐ rồi nạp lại ⇒
    CÓ gợi ý (phép đo không rỗng)."""
    d = nen
    async with csdl.engine.begin() as conn:
        ai_cu = await _hoc_vu_nam_khac(conn, d)
        giu = await _ho_so_hai_nv(conn, d, 20_955, "oto_cd_nam_truoc", "oto_cd")
        lech_nam_khac = await _ho_so_hai_nv(conn, d, 20_956, "oto_cd_nam_truoc", "duoc_cd")
        lech_cung_nam = await _ho_so_hai_nv(conn, d, 20_957, "duoc_cd", "duoc_cd")
    nap = await _nap(d)
    dong = {r.profile_id: r for r in rules.evaluate_run(nap.profiles, nap.run).rows}
    assert (dong[giu].tab, list(dong[giu].reason_codes)) == ("auto", []), dong[giu]
    assert [(o.offering_academic_info_id, o.status) for o in dong[giu].per_choice] == [
        (d["ai"]["oto_cd"], "passed_floor"),
        (ai_cu, "not_considered"),
    ], dong[giu].per_choice
    assert dong[giu].considered.offering_academic_info_id == d["ai"]["oto_cd"]
    assert (dong[lech_nam_khac].tab, list(dong[lech_nam_khac].reason_codes)) == ("needs_decision", ["tuition_major_mismatch"])
    assert "consider_next_choice" not in dong[lech_nam_khac].decision_hints, dong[lech_nam_khac].decision_hints
    assert (dong[lech_cung_nam].tab, list(dong[lech_cung_nam].reason_codes)) == ("needs_decision", ["tuition_major_mismatch"])
    assert "consider_next_choice" not in dong[lech_cung_nam].decision_hints, dong[lech_cung_nam].decision_hints
    async with csdl.engine.begin() as conn:
        await chen(conn, "admission_review_floor", session_id=d["lan_xet"], academic_year=NAM,
                   offering_academic_info_id=d["ai"]["duoc_cd"], floor_score="10.00", updated_by_user_id=d["nguoi"])
    nap = await _nap(d)
    dong = {r.profile_id: r for r in rules.evaluate_run(nap.profiles, nap.run).rows}
    assert (dong[lech_cung_nam].tab, list(dong[lech_cung_nam].reason_codes)) == ("needs_decision", ["tuition_major_mismatch"])
    assert "consider_next_choice" in dong[lech_cung_nam].decision_hints, dong[lech_cung_nam].decision_hints
    assert "consider_next_choice" not in dong[lech_nam_khac].decision_hints, dong[lech_nam_khac].decision_hints


#: Owner f7fe49b3 (22-11) — nghiệm thu B-P1, ba ca × (trường, xã). Dòng CŨ luôn chèn TRƯỚC (thứ tự vật lý ≠ thứ tự chọn). KV mong đợi
#: VIẾT TAY. Trường: tra năm 2023 (năm của dòng THPT 2023–2025; cả ba năm cùng kết quả). Xã: mốc 31/12/2026.
CA_TRUONG = (
    # (nhãn, [(kv, năm bắt đầu, năm kết thúc)] theo thứ tự chèn, KV mong đợi)
    ("chong_khoang", [("KV2", 2020, None), ("KV1", 2022, None)], "KV1"),
    ("cung_nam_bat_dau_id_lon_thang", [("KV2", 2022, None), ("KV1", 2022, None)], "KV1"),
    ("moi_hon_da_het_hieu_luc_chon_cu", [("KV2", 2020, None), ("KV1", 2021, 2022)], "KV2"),
)
CA_XA = (
    # (nhãn, mã xã, [(kv, từ ngày, tới ngày)] theo thứ tự chèn, KV mong đợi). Production có UNIQUE từng phần "một dòng ĐANG MỞ / xã"
    # ⇒ mọi ca chỉ có tối đa một dòng không ngày kết thúc.
    ("chong_khoang", "GXCK1", [("KV2", date(2020, 1, 1), date(2027, 6, 30)), ("KV1", date(2024, 1, 1), None)], "KV1"),
    ("cung_ngay_bat_dau_id_lon_thang", "GXCK2",
     [("KV2", date(2024, 1, 1), date(2027, 6, 30)), ("KV1", date(2024, 1, 1), None)], "KV1"),
    ("moi_hon_da_het_hieu_luc_chon_cu", "GXCK3",
     [("KV2", date(2020, 1, 1), None), ("KV1", date(2024, 1, 1), date(2026, 6, 30))], "KV2"),
)
MUC_KV = {"KV1": "0.75", "KV2": "0.25"}


async def test_b_p1_kv_chong_khoang_ba_ca_hai_duong_chon_cung_mot_dong(nen):
    """Owner f7fe49b3 (Codex 22-11 lượt 2 B-P1): lọc khoảng CÒN HIỆU LỰC tại mốc rồi chọn mới nhất (trường: năm bắt đầu lớn nhất; xã:
    ngày bắt đầu mới nhất), hoà ⇒ ``id`` lớn nhất. Ba ca cho cả KV trường lẫn KV xã: (a) chồng khoảng, (b) cùng mốc bắt đầu, (c) khoảng
    mới hơn đã HẾT hiệu lực ⇒ khoảng cũ còn hiệu lực.

    Kiểm CẢ HAI đường bằng giá trị viết tay: hàm tra từng phép (T1 / T6 / bản in) và câu lô (máy xét); rồi ca đối chiếu F231 —
    ``CheckData`` của bộ nạp == của bản in GĐ1 trên các hồ sơ dùng đúng dữ liệu ấy (trường: nhánh lịch sử THPT; xã: nhánh thường trú)."""
    from app.services import priority_service

    d = nen
    truong, pid_truong, pid_xa = {}, {}, {}
    async with csdl.engine.begin() as conn:
        for i, (nhan, dong, _) in enumerate(CA_TRUONG):
            t = await chen(conn, "vn_school", moet_school_code="GIACK%02d" % i, moet_province_code="99",
                           name="Trường giả chồng khoảng %d" % i, province="Tỉnh giả", level="THPT")
            for ma_kv, tu, den in dong:
                await chen(conn, "vn_school_kv_assignment", school_id=t, kv_code=ma_kv, effective_from_year=tu,
                           effective_to_year=den, source="gia")
            truong[nhan] = t
            pid = await _ho_so_kieu(conn, d, 970 + i, "thieu_giay_hp")
            await _x(conn, "UPDATE admission_profile SET academic_history = CAST(:h AS jsonb), "
                           "priority_resolution_snapshot = CAST(:s AS jsonb) WHERE id = :p",
                     h=json.dumps([{"level": "THPT", "school_id": t, "school_name": "Trường giả", "year_from": 2023,
                                    "year_to": 2025}]),
                     s=json.dumps(kv(dict((c[0], c[2]) for c in CA_TRUONG)[nhan], "longest_duration")), p=pid)
            pid_truong[nhan] = pid
        for i, (nhan, ma_xa, dong, mong) in enumerate(CA_XA):
            for ma_kv, tu, den in dong:
                await chen(conn, "vn_commune_area_map", commune_code=ma_xa, province="Tỉnh giả", district="Huyện giả",
                           ward="Xã giả " + ma_xa, area_code=ma_kv, effective_from=tu, effective_to=den)
            pid = await _ho_so_kieu(conn, d, 975 + i, "thieu_giay_hp")
            await _x(conn, "UPDATE admission_profile SET cultural_education_level = 'graduated_thcs', "
                           "vocational_qualification = 'so_cap', academic_history = '[]'::jsonb, permanent_commune_code = :x, "
                           "priority_resolution_snapshot = CAST(:s AS jsonb) WHERE id = :p",
                     x=ma_xa, s=json.dumps(kv(mong)), p=pid)
            pid_xa[nhan] = pid
    # Hai đường tra, giá trị viết tay.
    async with AsyncSessionLocal() as db:
        tung_truong = {n: await priority_service.lookup_kv_for_school_year(db, truong[n], 2023) for n in truong}
        tung_xa = {c[0]: await priority_service._lookup_commune_kv(db, c[1], NAM) for c in CA_XA}
    async with read_only_transaction(csdl.engine) as (conn, _):
        lo_truong = await load_repo.read_school_kv(conn, [(t, 2023) for t in truong.values()])
        lo_xa = await load_repo.read_commune_kv(conn, [(c[1], NAM) for c in CA_XA])
    mong_truong = {c[0]: c[2] for c in CA_TRUONG}
    mong_xa = {c[0]: c[3] for c in CA_XA}
    assert tung_truong == mong_truong, tung_truong
    assert {n: lo_truong[(truong[n], 2023)] for n in truong} == mong_truong, lo_truong
    assert tung_xa == mong_xa, tung_xa
    assert {c[0]: lo_xa[(c[1], NAM)] for c in CA_XA} == mong_xa, lo_xa
    # Ca đối chiếu F231: hai đường cùng kết quả TRÊN CẢ hồ sơ, và kết quả là "qua" với mức của KV mong đợi.
    nap = await _nap(d)
    ban_in = await doc.read_profiles_by_id(csdl.engine, [p.profile_id for p in nap.profiles], academic_year=NAM)
    assert tuple(p.check for p in nap.profiles) == ban_in.check_data
    cua = {p.profile_id: p.check for p in nap.profiles}
    for nhan, pid in pid_truong.items():
        assert (cua[pid].kv_ly_do, cua[pid].kv_muc) == (None, MUC_KV[mong_truong[nhan]]), (nhan, cua[pid])
    for nhan, pid in pid_xa.items():
        assert (cua[pid].kv_ly_do, cua[pid].kv_muc) == (None, MUC_KV[mong_xa[nhan]]), (nhan, cua[pid])


async def test_uu_tien_dan_toc_tra_kv_xa_theo_lo_doi_ket_qua(nen):
    """Codex 22-11 lượt 2 (bộ gieo bổ sung b): em dân tộc NGOÀI Kinh, khai sinh + giấy cư trú đã duyệt ⇒ ``full_evidence``; mã đối
    tượng theo KV của xã thường trú tra THEO LÔ cho năm lần xét: GX1 (KV1) ⇒ ``01`` = 2,00; GX2 (KV2) ⇒ ``06`` = 1,00 — tổng điểm
    khác nhau đúng phần ấy (KV trường 0,75; trần 2,75)."""
    d = nen
    cu_tru = dict(loai="giay_xac_nhan_cu_tru", status="verified", actual_submission_format="certified_copy")
    pid = {}
    async with csdl.engine.begin() as conn:
        for i, xa in enumerate(("GX1", "GX2")):
            pid[xa] = await _ho_so_kieu(conn, d, 980 + i, "thieu_giay_hp")
            await _x(conn, "UPDATE admission_profile SET ethnicity = '02', permanent_commune_code = :x WHERE id = :p",
                     x=xa, p=pid[xa])
            await _x(conn, "DELETE FROM profile_document WHERE profile_id = :p", p=pid[xa])
            await chen(conn, "fee", admission_profile_id=pid[xa], academic_year=NAM, base_amount="1000",
                       final_amount="1000", paid_amount="1000", calculated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                       created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                       updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc), fee_type="tuition", semester_no=1,
                       status="paid", resolved_major_id=d["mp"]["oto_cd"], resolved_degree_level="Cao đẳng")
            for g in (KHAI_SINH, cu_tru):
                await chen(conn, "profile_document", profile_id=pid[xa], document_type_id=d["giay"][g["loai"]],
                           status="verified", actual_submission_format=g["actual_submission_format"],
                           verified_format=g["actual_submission_format"], paper_submitted_by_unknown=True,
                           created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                           updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    nap = await _nap(d)
    dong = {r.profile_id: r for r in rules.evaluate_run(nap.profiles, nap.run).rows}
    thay = {xa: (dong[p].tab, dong[p].ethnic_priority_state, str(dong[p].scores.object), str(dong[p].scores.review_total))
            for xa, p in pid.items()}
    assert thay == {
        "GX1": ("auto", "full_evidence", "2.00", "26.75"),
        "GX2": ("auto", "full_evidence", "1.00", "25.75"),
    }, thay


async def test_q5_nguyen_vong_hoc_vu_nam_khac_thi_dung_khong_sang_nv_sau(nen):
    """Owner Q5 22-11: NV1 trỏ tới học vụ NĂM KHÁC năm lần xét ⇒ hồ sơ DỪNG ở NV1 với mã riêng; NV2 (hợp lệ, đủ sàn) KHÔNG xét."""
    d = nen
    async with csdl.engine.begin() as conn:
        ai_cu = await _hoc_vu_nam_khac(conn, d)
        pid = await ho_so(
            conn, d, cccd=ma_gia(20_950), full_name="Họ Giả Năm Khác", dob=date(2008, 1, 1), gender="Nam", ethnicity="01",
            permanent_commune_code="GX1", cultural_education_level="graduated_thpt", vocational_qualification="none",
            priority_resolution_snapshot=kv("KV1"), academic_history=lich_su_thpt(d, "KV1"),
            nv=[(1, "oto_cd_nam_truoc", "cq", "g1"), (2, "oto_cd", "cq", "g1")], diem={0: DIEM, 1: DIEM},
            hoc_phi=[HP], giay=[KHAI_SINH], status="submitted",
        )
        await _x(conn, "UPDATE admission_profile SET applied_rules = CAST(:a AS jsonb) WHERE id = :p",
                 a=json.dumps(QUY_TAC_GIAY), p=pid)
    nap = await _nap(d)
    ket_qua = rules.evaluate_run(nap.profiles, nap.run)
    dong = next(r for r in ket_qua.rows if r.profile_id == pid)
    assert (dong.tab, list(dong.reason_codes)) == ("ineligible", ["choice_academic_year_mismatch"]), dong
    assert [(o.offering_academic_info_id, o.status) for o in dong.per_choice] == [
        (ai_cu, "config_missing"),
        (d["ai"]["oto_cd"], "not_reached"),
    ], dong.per_choice
    assert dong.considered is None


@pytest.mark.parametrize(
    "cccd_nay, cccd_truoc, co_a13",
    [
        ("0999 9903 0001", "099999030001", True),
        ("099999030002", "0999\t9903\u00a00002", True),
        ("   ", " \t ", False),
    ],
    ids=["khoang_trang_phia_nay", "tab_va_nbsp_phia_truoc", "rong_sau_khi_xoa_khong_so"],
)
async def test_q7_a13_so_cccd_sau_khi_xoa_moi_khoang_trang(nen, cccd_nay, cccd_truoc, co_a13):
    """Owner Q7 22-11 — khoá so CCCD của A13: xoá MỌI khoảng trắng ở CẢ HAI phía; rỗng sau khi xoá ⇒ không ghép."""
    d = nen
    async with csdl.engine.begin() as conn:
        pid = await _ho_so_kieu(conn, d, 960, "tc_khong_hl")
        await _x(conn, "UPDATE admission_profile SET citizen_id = :c WHERE id = :p", c=cccd_nay, p=pid)
        await ho_so(conn, d, cccd=cccd_truoc, nam=NAM - 1, status="approved")
    nap = await _nap(d)
    hs = next(p for p in nap.profiles if p.profile_id == pid)
    mong = (rules.PriorYearProfileFacts(NAM - 1, "approved", False),) if co_a13 else ()
    assert hs.prior_year_profiles == mong, hs.prior_year_profiles


def test_q7_khoa_so_cccd_mot_dinh_nghia_khoang_trang():
    assert rules.citizen_id_match_key(" 0999\t99\u00a003\u3000") == "09999903"
    assert rules.citizen_id_match_key(" \t\u2003 ") is None
    assert rules.citizen_id_match_key(None) is None
    toan_bo = "".join(c for c in map(chr, range(0x110000)) if c.isspace())
    assert rules.CITIZEN_ID_WHITESPACE == toan_bo


def test_k2_menh_de_chon_khoan_hk1_chep_nguyen_chu_ban_in():
    assert load_repo.SQL_HK1_TUITION_FILTER in SQL_PRINT_FIGURES.text
    assert load_repo.SQL_HK1_TUITION_ORDER in SQL_PRINT_FIGURES.text


@pytest.mark.parametrize("moi_huy", [True, False], ids=["khoan_moi_da_huy_chon_khoan_cu", "khoan_moi_chua_huy_chon_khoan_moi"])
async def test_k2_chon_khoan_hk1_chua_huy_id_lon_nhat(nen, moi_huy):
    d = nen
    async with csdl.engine.begin() as conn:
        pid = await _ho_so_kieu(conn, d, 900, "xep_nam_truoc")
        cu = (await _x(conn, "SELECT id FROM fee WHERE admission_profile_id = :p", p=pid)).scalar_one()
        moi = await chen(conn, "fee", admission_profile_id=pid, academic_year=NAM, base_amount="1000", final_amount="1000",
                         calculated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                         created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                         updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc), fee_type="tuition", semester_no=1,
                         status="cancelled" if moi_huy else "pending", resolved_major_id=d["mp"]["oto_cd"])
    nap = await _nap(d)
    hs = next(p for p in nap.profiles if p.profile_id == pid)
    assert moi > cu
    assert hs.tuition_fee.fee_id == (cu if moi_huy else moi)
    assert hs.tuition_fee.status == ("paid" if moi_huy else "pending")


async def test_bo_dem_moi_hoc_vu_mot_cau_bang_ba_ham_goc(nen):
    """``count_by_academic_infos`` == ``count_by_academic_info`` (công bố) + ``count_by_offering_year`` (Phê duyệt cũ) cho TỪNG học
    vụ, và == ``count_by_group`` cho nhóm một thành viên. Có hồ sơ chiếm chỗ thật ở cả hai cách đếm (phép đo không rỗng)."""
    d = nen
    async with csdl.engine.begin() as conn:
        pid = await _ho_so_kieu(conn, d, 901, "xep_nam_truoc")
        await _x(conn, "UPDATE admission_profile SET status = 'approved' WHERE id = :p", p=pid)
        await _x(conn, "UPDATE admission_profile_choice SET decision = 'admitted' WHERE admission_profile_id = :p", p=pid)
        offering = (await _x(conn, "SELECT offering_id FROM offering_academic_info WHERE id = :i",
                             i=d["ai"]["oto_cd"])).scalar_one()
        await _x(conn, "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
                 o=offering, p=pid)
    ids = [d["ai"]["oto_cd"], d["ai"]["duoc_cd"]]
    async with AsyncSessionLocal() as db:
        mot_cau = await qos.count_by_academic_infos(db, academic_info_ids=ids)
        for k in ("oto_cd", "duoc_cd"):
            ai = d["ai"][k]
            off = (await db.execute(text("SELECT offering_id FROM offering_academic_info WHERE id = :i"), {"i": ai})).scalar_one()
            cong_bo = await qos.count_by_academic_info(db, academic_info_id=ai)
            phe_duyet = await qos.count_by_offering_year(db, offering_id=off, academic_year=NAM)
            assert mot_cau[ai] == {"publish_count": cong_bo, "approved_count": phe_duyet, "used": max(cong_bo, phe_duyet)}
            assert mot_cau[ai] == await qos.count_by_group(db, group_id=d["nhom"][k])
    assert mot_cau[d["ai"]["oto_cd"]]["publish_count"] >= 1 and mot_cau[d["ai"]["oto_cd"]]["approved_count"] >= 1
