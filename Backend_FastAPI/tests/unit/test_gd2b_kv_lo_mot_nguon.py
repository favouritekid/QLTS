# tests/unit/test_gd2b_kv_lo_mot_nguon.py
"""GĐ2-B đợt 2 (đề cương §3, CLAUDE.md §7) — MỘT nguồn luật cho hai đường đọc KV:

* đường TỪNG HỒ SƠ (``resolve_kv_for_profile`` / ``verify_manual_override_provenance`` — T1, T6, bản in GĐ1) đọc CSDL theo từng
  phép tra;
* đường LÔ (``decide_kv_for_profile`` / ``decide_manual_override_provenance`` — máy xét GĐ2-B) trả lời CÙNG bộ quyết định từ bản đồ
  đã nạp theo :func:`kv_lookup_keys`.

Khoá: cùng dữ kiện ⇒ cùng kết quả (hoặc cùng loại lỗi) trên đủ các nhánh resolver; mọi phép tra đường từng hồ sơ hỏi đều nằm trong
tập khoá bao trùm (thiếu khoá ⇒ đường lô fail-closed ``KvLookupNotLoaded``, không đoán). Không CSDL: hai hàm đọc được thay bằng
bảng tra trong bộ nhớ (ghi lại từng lần hỏi).
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import priority_service as ps

pytestmark = pytest.mark.unit

NAM = 2026
#: Danh mục giả: KV xã theo (mã, năm) và KV trường theo (id trường, năm). Thiếu khoá = danh mục không có hàng.
XA = {("X1", NAM): "KV1", ("X2", NAM): "KV2-NT"}
TRUONG = {}
for _y in range(2018, 2027):
    TRUONG[(1, _y)] = "KV1"
    TRUONG[(2, _y)] = "KV2"
    TRUONG[(3, _y)] = "KV3"
TRUONG.pop((2, 2023))  # trường 2 thiếu một năm (Q19(d)(ii))


def _ls(sid, tu, den, **kw):
    return {"level": "THPT", "school_id": sid, "year_from": tu, "year_to": den, **kw}


def _hs(**kw):
    goc = dict(
        id=1,
        academic_year=NAM,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code="X1",
        academic_history=[_ls(1, 2022, 2024)],
    )
    goc.update(kw)
    return SimpleNamespace(**goc)


# (nhãn, thuộc tính hồ sơ, target_level, admission_type)
#: L3 (owner 22-11): ba ca thường trú dùng nhánh "hoàn thành THPT, không chuyên môn" (GIỮ theo hộ khẩu) — nhánh "tốt nghiệp THCS" cũ
#: nay là "chờ xác minh"; ca L3 (trường THCS, cờ DTNT, hồ sơ cũ) ở ``test_l3_kv_cho_xac_minh.py`` (cũng chạy cả hai đường).
_HT_THPT = dict(cultural_education_level="completed_thpt")
CA = [
    ("thuong_tru_co_xa", dict(_HT_THPT, academic_history=[]), None, None),
    ("thuong_tru_xa_khong_co_trong_danh_muc", dict(_HT_THPT, permanent_commune_code="X9"), None, None),
    ("thuong_tru_thieu_ma_xa", dict(_HT_THPT, permanent_commune_code=None), None, None),
    ("dien_dac_biet", dict(area_resolution_basis="permanent_address_special", permanent_commune_code="X2"), None, None),
    ("an_dinh_thu_cong", dict(area_resolution_basis="manual_override"), None, None),
    ("chua_khai_van_hoa", dict(cultural_education_level=None), None, None),
    ("lich_su_mot_truong", {}, None, None),
    ("lich_su_theo_ngu_canh_cao_dang", dict(cultural_education_level="completed_thpt"), "cao_dang", "chinh_quy"),
    ("lich_su_hai_truong_lau_hon_thang", dict(academic_history=[_ls(1, 2020, 2022), _ls(3, 2023, 2024)]), None, None),
    ("lich_su_hoa_lay_truong_tot_nghiep", dict(academic_history=[_ls(1, 2021, 2022, grade_to=11), _ls(3, 2023, 2024, grade_to=12)]), None, None),
    ("lich_su_hoa_khong_phan_dinh", dict(academic_history=[_ls(1, 2021, 2022, grade_to=12), _ls(3, 2021, 2022, grade_to=12)]), None, None),
    ("lich_su_thieu_mot_nam", dict(academic_history=[_ls(1, 2020, 2022), _ls(2, 2022, 2024)]), None, None),
    ("lich_su_truong_khong_co_danh_muc", dict(academic_history=[_ls(99, 2020, 2022)]), None, None),
    ("lich_su_muc_khong_hop_le_van_la_ung_vien_tot_nghiep",
     dict(academic_history=[_ls(1, 2021, 2022, grade_to=11), _ls(3, 2023, 2024, grade_to=11), _ls(2, None, 2025, grade_to=12)]), None, None),
    ("lich_su_rong", dict(academic_history=[]), None, None),
    ("lich_su_nam_sai_kieu", dict(academic_history=[_ls(1, "2022", 2024)]), None, None),
]


def _duong_tung_ho_so(monkeypatch, hs, tl, at):
    """Chạy ``resolve_kv_for_profile`` với hai hàm đọc thay bằng bảng tra; trả (kết quả | lỗi, các khoá đã hỏi)."""
    hoi = {"commune": [], "school": []}

    async def _xa(db, ma, nam):
        hoi["commune"].append((ma, nam))
        return XA.get((ma, nam))

    async def _truong(db, sid, nam):
        hoi["school"].append((sid, nam))
        return TRUONG.get((sid, nam))

    monkeypatch.setattr(ps, "_lookup_commune_kv", _xa)
    monkeypatch.setattr(ps, "lookup_kv_for_school_year", _truong)
    try:
        kq = asyncio.run(ps.resolve_kv_for_profile(hs, db=None, target_level=tl, admission_type=at))
    except Exception as exc:  # noqa: BLE001 — so LOẠI lỗi giữa hai đường
        kq = type(exc)
    return kq, hoi


def _duong_lo(hs, tl, at):
    xa_k, truong_k = ps.kv_lookup_keys(hs, target_level=tl, admission_type=at)
    commune = {k: XA.get(k) for k in xa_k}
    school = {k: TRUONG.get(k) for k in truong_k}
    try:
        return ps.decide_kv_for_profile(hs, commune_kv=commune, school_kv=school, target_level=tl, admission_type=at), (
            xa_k,
            truong_k,
        )
    except Exception as exc:  # noqa: BLE001
        return type(exc), (xa_k, truong_k)


@pytest.mark.parametrize("nhan, kw, tl, at", CA, ids=[c[0] for c in CA])
def test_duong_lo_va_duong_tung_ho_so_cung_ket_qua(monkeypatch, nhan, kw, tl, at):
    hs = _hs(**kw)
    tung, hoi = _duong_tung_ho_so(monkeypatch, hs, tl, at)
    lo, (xa_k, truong_k) = _duong_lo(hs, tl, at)
    assert lo == tung, (nhan, lo, tung)
    # Tập khoá nạp trước BAO TRÙM mọi phép tra đường từng hồ sơ thật sự hỏi (khoá đúng kiểu).
    assert set(hoi["commune"]) <= set(xa_k), (nhan, hoi["commune"], xa_k)
    hop_le = {k for k in hoi["school"] if all(isinstance(v, int) for v in k)}
    assert hop_le <= set(truong_k), (nhan, hoi["school"], truong_k)


def test_phep_do_hop_le_cac_ca_phu_du_nhanh_resolver(monkeypatch):
    """Phép đo không rỗng: các ca phủ đủ ``rule_applied`` của resolver + một ca lỗi kiểu dữ liệu."""
    thay = set()
    for nhan, kw, tl, at in CA:
        kq, _ = _duong_tung_ho_so(monkeypatch, _hs(**kw), tl, at)
        thay.add(kq[1]["rule_applied"] if isinstance(kq, tuple) else kq.__name__)
    assert {
        "commune_lookup",
        "catalog_gap_commune",
        "address_not_normalized",
        "manual_override",
        "not_resolved",
        "longest_duration",
        "tiebreak_graduation_school",
        "ambiguous_requires_manual",
        "catalog_gap_school",
        "insufficient_data",
        "TypeError",
    } <= thay, thay


def test_khoa_vang_thi_duong_lo_tu_choi_khong_doan():
    hs = _hs()
    with pytest.raises(ps.KvLookupNotLoaded):
        ps.decide_kv_for_profile(hs, commune_kv={}, school_kv={})


# ═══════════════════════════════ ấn định KV thủ công — sổ ═══════════════════════════════
LUC = "2026-10-02T03:04:05+00:00"


def _hs_thu_cong(**snap_kw):
    snap = {
        "kv_resolved": "KV1",
        "rule_applied": "manual_override",
        "manual_override_by": 7,
        "manual_override_at": LUC,
        "manual_override_reason": "Lý do giả ấn định khu vực đủ dài",
    }
    snap.update(snap_kw)
    hs = _hs(area_resolution_basis="manual_override", priority_resolution_snapshot=snap)
    return hs


def _so(hs, **kw):
    goc = dict(
        id=11,
        actor_id=7,
        new_value={"kv_resolved": "KV1"},
        audit_metadata={"actor_role": "admin", ps.KV_INPUTS_FINGERPRINT_KEY: ps.kv_inputs_fingerprint(hs)},
        created_at=datetime(2026, 10, 2, 3, 4, 6, tzinfo=timezone.utc),
    )
    goc.update(kw)
    return SimpleNamespace(**goc)


class _CsdlGia:
    """Phiên giả cho ``verify_manual_override_provenance``: trả ĐÚNG một hàng sổ (hoặc không), đếm số câu."""

    def __init__(self, hang):
        self.hang, self.so_cau = hang, 0

    async def execute(self, stmt):
        self.so_cau += 1
        hang = self.hang
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: hang))


SO_CA = [
    ("hop_le", {}, {}),
    ("khong_co_anh_chup", None, {}),
    ("ly_do_ngan", {"manual_override_reason": "ngắn"}, {}),
    ("khong_co_so", {}, None),
    ("nguoi_lech", {}, {"actor_id": 8}),
    ("kv_lech", {}, {"new_value": {"kv_resolved": "KV2"}}),
    ("vai_khong_duoc_phep", {}, {"audit_metadata": {"actor_role": "officer"}}),
    ("lech_gio", {}, {"created_at": datetime(2026, 10, 3, tzinfo=timezone.utc)}),
    ("van_tay_lech", {}, {"audit_metadata": {"actor_role": "admin", "kv_inputs_fingerprint": "khac"}}),
]


@pytest.mark.parametrize("nhan, snap_kw, so_kw", SO_CA, ids=[c[0] for c in SO_CA])
def test_xac_minh_so_hai_duong_cung_ket_qua(nhan, snap_kw, so_kw):
    if snap_kw is None:
        hs = _hs(priority_resolution_snapshot={})
    else:
        hs = _hs_thu_cong(**snap_kw)
    hang = None if so_kw is None else _so(hs, **so_kw)
    csdl = _CsdlGia(hang)
    tung = asyncio.run(ps.verify_manual_override_provenance(csdl, hs))
    lo = ps.decide_manual_override_provenance(hs, hang)
    assert lo == tung, (nhan, lo, tung)
    # Ảnh chụp hỏng ⇒ đường từng hồ sơ KHÔNG đọc sổ (giữ hành vi cũ); còn lại đọc đúng một câu.
    assert csdl.so_cau == (0 if ps.manual_override_claim_refusal(hs) else 1), (nhan, csdl.so_cau)
    if nhan == "hop_le":
        assert tung[0] is True, tung
    else:
        assert tung[0] is False, tung


def test_doi_tuong_da_xac_minh_mot_ham_cho_t6_va_may_xet():
    hs = SimpleNamespace(
        priority_object_codes=["03", "01", "05"],
        priority_object_evidence={"03": {"status": "verified"}, "01": {"status": "pending"}, "05": "verified"},
    )
    assert ps.verified_object_codes(hs) == ["03"]


# ═══════════════════════════════ Codex 22-11 lượt 2 — B-P1, B-P2 ═══════════════════════════════
class _GhiCau:
    """Phiên giả ghi lại câu mà hàm đọc từng phép tra gửi (để biên dịch, không cần CSDL)."""

    def __init__(self):
        self.cau = []

    async def execute(self, stmt):
        self.cau.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: None)


def _sql(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())


def test_b_p1_hai_duong_tra_kv_cung_mot_thu_tu_chon_dong():
    """Khoảng KV chồng nhau / hoà: đường TỪNG HỒ SƠ (câu thật của ``lookup_kv_for_school_year`` / ``_lookup_commune_kv``, biên
    dịch) và đường LÔ (``SQL_SCHOOL_KV`` / ``SQL_COMMUNE_KV``) sắp bằng CÙNG một hàm thứ tự (một nguồn — ``models``)."""
    from app.models.vn_locality import commune_kv_pick_order_sql
    from app.models.vn_school import school_kv_pick_order_sql
    from app.repositories import admission_review_load_repository as load_repo

    db = _GhiCau()
    asyncio.run(ps.lookup_kv_for_school_year(db, 1, NAM))
    asyncio.run(ps._lookup_commune_kv(db, "X1", NAM))
    truong, xa = (_sql(s) for s in db.cau)
    assert "ORDER BY " + school_kv_pick_order_sql("vn_school_kv_assignment") + " LIMIT" in truong, truong
    assert "ORDER BY " + commune_kv_pick_order_sql("vn_commune_area_map") + " LIMIT" in xa, xa
    assert " ".join(load_repo.SQL_SCHOOL_KV.text.split()).endswith(", " + school_kv_pick_order_sql("a"))
    assert " ".join(load_repo.SQL_COMMUNE_KV.text.split()).endswith(", " + commune_kv_pick_order_sql("m"))
    assert school_kv_pick_order_sql("a") == "a.effective_from_year DESC, a.id DESC"
    assert commune_kv_pick_order_sql("m") == "m.effective_from DESC, m.id DESC"


def _canh_gia(join, pairs):
    prop = SimpleNamespace(
        direction=SimpleNamespace(name="MANYTOONE"), primaryjoin=join, secondary=None, local_remote_pairs=pairs
    )
    return SimpleNamespace(property=prop, class_=SimpleNamespace(__name__="GiaA"), key="b")


def test_b_p2_phep_noi_phai_la_hai_cot_truc_tiep():
    """``load_relationship_paths`` chỉ nạp quan hệ mà phép nối là ``cột = cột`` đúng cặp ``local_remote_pairs``: có hàm / ép kiểu
    (vẫn mang toán tử ``=``) ⇒ ``UnsupportedBatchRelationship`` TRƯỚC mọi câu. Đối chứng: nối hai cột trực tiếp qua được chốt (lỗi
    sau đó là do quan hệ giả không có mapper — không phải chốt)."""
    from sqlalchemy import Column, Integer, MetaData, String, Table, cast, func

    from app.repositories import admission_review_load_repository as load_repo

    md = MetaData()
    a = Table("gia_a", md, Column("id", Integer, primary_key=True), Column("ma", String))
    b = Table("gia_b", md, Column("id", Integer, primary_key=True), Column("ma", String))
    cap = [(a.c.ma, b.c.ma)]
    for join in (func.lower(a.c.ma) == b.c.ma, cast(a.c.ma, String) == b.c.ma, a.c.ma == func.upper(b.c.ma)):
        with pytest.raises(load_repo.UnsupportedBatchRelationship):
            asyncio.run(load_repo._load_edge(None, [], _canh_gia(join, cap)))
    with pytest.raises(load_repo.UnsupportedBatchRelationship):  # hai cột trực tiếp nhưng KHÔNG phải cặp của quan hệ
        asyncio.run(load_repo._load_edge(None, [], _canh_gia(a.c.id == b.c.id, cap)))
    with pytest.raises(AttributeError):
        asyncio.run(load_repo._load_edge(None, [], _canh_gia(a.c.ma == b.c.ma, cap)))
