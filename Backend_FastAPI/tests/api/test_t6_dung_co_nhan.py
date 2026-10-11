"""T6 "Công bố kết quả" DỪNG có nhãn thay vì chấm 0 điểm / ghi "trượt" — C8 + C8b + Q19(d) + Q20.

Quyết định owner (sổ ``bang-chung``): Q10(a) mức theo NĂM TUYỂN SINH, hàng ĐANG MỞ, không lọc ngày; Q10-kèm
thiếu mức ⇒ dừng; Q17(a) KV chưa phân giải / đóng băng lỗi ⇒ dừng; Q19(d)(ii) một phần năm/trường thiếu danh mục KV
⇒ dừng; Q20(a) thiếu cấu hình trình độ/loại hình của ngành ⇒ dừng, KHÔNG ghi trượt.

Mỗi ca canh MỘT bất biến và đi đúng đường cán bộ đi (HTTP ``POST /api/v2/admissions/{id}/publish-result``), kiểm
cả nhãn tới client. "Dừng" = mã lỗi đúng + KHÔNG quyết định nào được ghi + trạng thái giữ nguyên.

Khuôn cho bộ chấm đột biến: KHÔNG ``pytest.raises``, KHÔNG ``parametrize``; lời gọi có thể ném bọc
``try/except`` trong thân ca rồi ``assert``.

Hàng loạt: T6 hôm nay chỉ có MỘT lối gọi (từng hồ sơ một request) — ``test_t6_dung_co_nhan_mot_nguon.py`` khoá
điều ấy. Ca ``test_lo_nhieu_ho_so_dung_mot_khong_cham_ho_so_khac`` chạy nối tiếp nhiều hồ sơ như cán bộ bấm
lần lượt: hồ sơ dừng không làm hỏng hồ sơ khác.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app import models
from app.database import AsyncSessionLocal
from app.models.priority_config import PriorityObjectConfig
from tests.fixtures.cascade import doc_lai_ho_so, seed_area_rates, seed_cascade_profile

pytestmark = pytest.mark.integration

NAM = 2026
TAT_CA = {"apply_area_bonus": False, "apply_object_bonus": False}


async def _cong_bo(client, headers, profile_id: int):
    return await client.post(f"/api/v2/admissions/{profile_id}/publish-result", headers=headers)


def _lich_su_nam(seed: dict, nam_tu: int, nam_den: int) -> list:
    """Một mục THPT tại trường của seed (danh mục KV3 phủ 2020–2024)."""
    return [{
        "school_name": "THPT Submittable",
        "year_from": nam_tu,
        "year_to": nam_den,
        "gpa": 8.0,
        "graduation_type": "THPT",
        "level": "THPT",
        "grade_to": 12,
        "school_id": seed["school_id"],
    }]


async def _diem_kv_cua_nv(choice_id: int):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.AdmissionProfileChoice.priority_area_bonus_snapshot).where(
                    models.AdmissionProfileChoice.id == choice_id
                )
            )
        ).scalar_one()


# ===========================================================================
# C8 — mức theo năm tuyển sinh, hàng ĐANG MỞ, không lọc ngày
# ===========================================================================


async def test_d3_thieu_hang_muc_kv_thi_dung_503_khong_ghi_quyet_dinh(
    client, manager_token_headers, seed_lead_dependencies,
):
    """KV3 phân giải được nhưng năm 2026 KHÔNG có hàng mức KV3 ⇒ 503 có nhãn, không quyết định nào."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies, area_rates={"KV1": Decimal("0.75")})
    pid = ho_so["profile_id"]
    loi = None
    try:
        r = await _cong_bo(client, manager_token_headers, pid)
    except Exception as exc:  # noqa: BLE001 — bộ chấm cần assertion trong thân ca
        loi, r = exc, None
    assert loi is None, repr(loi)
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error_code"] == "PRIORITY_RATE_NOT_CONFIGURED", body
    assert body.get("missing_codes") == ["KV3"] and body.get("academic_year") == NAM, body
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])


async def test_d1_hang_mo_co_effective_from_tuong_lai_van_ap(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Hàng KV3 ĐANG MỞ nhưng ``effective_from`` 2027-01-01 (tương lai) ⇒ VẪN áp (Q10(a): bỏ lọc ngày)."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies, area_rates={})
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await seed_area_rates(
                s, academic_year=NAM, rates={"KV3": Decimal("0.50")}, effective_from=date(2027, 1, 1),
            )
    r = await _cong_bo(client, manager_token_headers, ho_so["profile_id"])
    assert r.status_code == 200, r.text
    diem = await _diem_kv_cua_nv(ho_so["choice_ids"][0])
    assert diem is not None and Decimal(diem) == Decimal("0.50"), diem


async def test_d4_hang_da_dong_du_ngay_dong_o_tuong_lai_khong_dung(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Hàng KV3 có ``effective_to`` (dù ở tương lai) là ĐÃ ĐÓNG ⇒ không dùng ⇒ thiếu mức ⇒ dừng."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies, area_rates={})
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await seed_area_rates(
                s, academic_year=NAM, rates={"KV3": Decimal("0.75")},
                effective_from=date(2025, 1, 1), effective_to=date(2027, 6, 1),
            )
    r = await _cong_bo(client, manager_token_headers, ho_so["profile_id"])
    assert r.status_code == 503, r.text
    assert r.json()["error_code"] == "PRIORITY_RATE_NOT_CONFIGURED", r.text


async def test_d3c_co_tat_thi_thieu_muc_khong_dung(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Luật cộng điểm TẮT cả hai cờ ⇒ không tra mức ⇒ thiếu hàng mức KHÔNG dừng; quyết định được ghi."""
    ho_so = await seed_cascade_profile(
        seed_lead_dependencies, area_rates={}, choices=[{"bonus_rule": TAT_CA}],
    )
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 200, r.text
    _status, quyet_dinh = await doc_lai_ho_so(pid)
    assert quyet_dinh != ["pending"], quyet_dinh


async def test_d5_nam_dot_lech_nam_ho_so_thi_dung_400(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Hồ sơ năm 2026, đợt của NV năm 2027 ⇒ 400 ``PRIORITY_YEAR_MISMATCH``; không tra mức theo năm đợt."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies, choices=[{"round_year": NAM + 1}])
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error_code"] == "PRIORITY_YEAR_MISMATCH", body
    assert (body.get("profile_year"), body.get("round_year")) == (NAM, NAM + 1), body
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])


async def test_d6_xem_truoc_thieu_muc_tra_200_kem_nhan_khong_0(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Xem trước: thiếu hàng KV3 ⇒ VẪN 200, ``area_bonus`` None (không 0) + cảnh báo liệt kê mã thiếu."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies, area_rates={"KV1": Decimal("0.75")})
    r = await client.post(
        f"/api/v2/admissions/{ho_so['profile_id']}/preview-priority-kv", json={}, headers=manager_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kv_resolved"] == "KV3", body
    assert body["area_bonus"] is None, body
    assert body["priority_rate_warnings"] == [{
        "code": "PRIORITY_RATE_NOT_CONFIGURED",
        "table": "priority_area_config",
        "academic_year": NAM,
        "missing_codes": ["KV3"],
    }], body


async def test_d3b_thieu_mot_ma_ut_da_xac_minh_thi_dung(seed_lead_dependencies):
    """Hai mã UT đã xác minh, chỉ ``01`` có hàng mở ⇒ ``PriorityRateNotConfigured(missing=['06'])``, không lấy max 01."""
    from app.services.priority_service import calculate_priority_bonus
    from app.utils.exceptions import PriorityRateNotConfigured

    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(PriorityObjectConfig(
                academic_year=NAM, group_code="UT1", sub_code="01", description="UT 01",
                bonus_points=Decimal("2.00"), effective_from=date(2025, 1, 1), effective_to=None,
            ))
    ho_so = SimpleNamespace(
        id=1,
        academic_year=NAM,
        priority_resolution_snapshot={},
        area_resolution_basis=None,
        priority_object_codes=["01", "06"],
        priority_object_evidence={"01": {"status": "verified"}, "06": {"status": "verified"}},
    )
    loi = None
    async with AsyncSessionLocal() as s:
        try:
            await calculate_priority_bonus(
                db=s, profile=ho_so, rule={"apply_object_bonus": True}, academic_year=NAM,
            )
        except Exception as exc:  # noqa: BLE001
            loi = exc
    assert isinstance(loi, PriorityRateNotConfigured), repr(loi)
    assert loi.missing_codes == ["06"], loi.missing_codes


async def test_d7_nhom_ut_xac_minh_thieu_muc_mang_nhan_khong_0(seed_lead_dependencies):
    """Nhóm UT đã xác minh (hiển thị): thiếu hàng mức ⇒ ``rate_status=not_configured``, điểm None — không 0, không ném."""
    from app.services.priority_override_service import _recompute_ut_verified_bucket

    ho_so = SimpleNamespace(
        id=1,
        academic_year=NAM,
        priority_object_codes=["06"],
        priority_object_evidence={"06": {"status": "verified"}},
    )
    loi = None
    nhom = None
    async with AsyncSessionLocal() as s:
        try:
            nhom = await _recompute_ut_verified_bucket(s, ho_so)
        except Exception as exc:  # noqa: BLE001
            loi = exc
    assert loi is None, repr(loi)
    assert nhom == {
        "applied_code": None, "applied_rate": None, "rate_status": "not_configured", "missing_codes": ["06"],
    }, nhom


async def test_e8_danh_muc_doi_tuong_bat_buoc_nam(client, manager_token_headers):
    """``GET /priority-objects/catalog`` thiếu ``academic_year`` ⇒ 422 — không rơi về năm cứng."""
    r = await client.get("/api/v2/admissions/priority-objects/catalog", headers=manager_token_headers)
    assert r.status_code == 422, r.text


# ===========================================================================
# C8b — KV chưa phân giải / đóng băng lỗi ⇒ dừng
# ===========================================================================


async def test_k1_kv_chua_phan_giai_ma_co_kv_bat_thi_dung(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Mọi năm của trường ngoài danh mục ⇒ KV chưa phân giải; cờ KV bật ⇒ 400 ``PRIORITY_KV_UNRESOLVED``."""
    ho_so = await seed_cascade_profile(
        seed_lead_dependencies, history_fn=lambda seed: _lich_su_nam(seed, 2010, 2014),
    )
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error_code"] == "PRIORITY_KV_UNRESOLVED", body
    assert body.get("rule_applied") == "catalog_gap_school", body
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])


async def test_k2_kv_chua_phan_giai_ma_co_kv_tat_thi_khong_dung(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Như K1 nhưng cờ KV TẮT ⇒ không cần KV ⇒ 200, quyết định được ghi."""
    ho_so = await seed_cascade_profile(
        seed_lead_dependencies,
        history_fn=lambda seed: _lich_su_nam(seed, 2010, 2014),
        choices=[{"bonus_rule": TAT_CA}],
    )
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 200, r.text
    _status, quyet_dinh = await doc_lai_ho_so(pid)
    assert quyet_dinh != ["pending"], quyet_dinh


async def test_k4_dong_bang_loi_thi_dung_ke_ca_khi_co_kv_tat(
    client, manager_token_headers, seed_lead_dependencies, monkeypatch,
):
    """Lỗi ngoài dự kiến trong đóng băng ⇒ 500 ``PRIORITY_FREEZE_FAILED``, kể cả khi cờ KV tắt; không quyết định."""
    from app.services import priority_service

    async def _hong(*args, **kwargs):
        raise RuntimeError("gia lap loi dong bang")

    ho_so = await seed_cascade_profile(seed_lead_dependencies, choices=[{"bonus_rule": TAT_CA}])
    pid = ho_so["profile_id"]
    monkeypatch.setattr(priority_service, "resolve_kv_for_profile", _hong)
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 500, r.text
    assert r.json().get("error_code") == "PRIORITY_FREEZE_FAILED", r.text
    assert r.json().get("stage") == "freeze_priority_snapshot", r.text
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])


async def test_k5_loi_mien_trong_dong_bang_giu_nguyen_nhan(
    client, manager_token_headers, seed_lead_dependencies, monkeypatch,
):
    """Lỗi MIỀN (``BusinessRuleViolation``) trong đóng băng giữ nhãn của nó — không bị gói thành FREEZE_FAILED."""
    from app.services import priority_service
    from app.utils.exceptions import BusinessRuleViolation

    async def _mien(*args, **kwargs):
        raise BusinessRuleViolation("loi mien gia lap")

    ho_so = await seed_cascade_profile(seed_lead_dependencies)
    monkeypatch.setattr(priority_service, "resolve_kv_for_profile", _mien)
    r = await _cong_bo(client, manager_token_headers, ho_so["profile_id"])
    assert r.status_code == 400, r.text
    assert r.json()["error_code"] == "BUSINESS_RULE_VIOLATION", r.text


async def test_k7_nv_sau_dung_thi_ca_ho_so_dung_nv_truoc_khong_bi_ghi(
    client, manager_token_headers, seed_lead_dependencies,
):
    """NV1 hết chỉ tiêu (đáng lẽ ghi ``waitlisted``) rồi NV2 dừng ⇒ dừng CẢ hồ sơ: NV1 cũng không bị ghi."""
    ho_so = await seed_cascade_profile(
        seed_lead_dependencies, choices=[{"admit_quota": 0}, {"round_year": NAM + 1}],
    )
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 400, r.text
    assert r.json()["error_code"] == "PRIORITY_YEAR_MISMATCH", r.text
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending", "pending"])


async def test_lo_nhieu_ho_so_dung_mot_khong_cham_ho_so_khac(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Công bố lần lượt ba hồ sơ (như cán bộ bấm nối tiếp): hồ sơ giữa dừng; hai hồ sơ còn lại vẫn có kết quả."""
    a = await seed_cascade_profile(seed_lead_dependencies, nhan="LA")
    b = await seed_cascade_profile(
        seed_lead_dependencies, nhan="LB", history_fn=lambda seed: _lich_su_nam(seed, 2010, 2014),
    )
    c = await seed_cascade_profile(seed_lead_dependencies, nhan="LC")
    ma = []
    for ho_so in (a, b, c):
        r = await _cong_bo(client, manager_token_headers, ho_so["profile_id"])
        ma.append(r.status_code)
    assert ma == [200, 400, 200], ma
    assert (await doc_lai_ho_so(b["profile_id"])) == ("reviewing", ["pending"])
    assert (await doc_lai_ho_so(a["profile_id"]))[1] != ["pending"]
    assert (await doc_lai_ho_so(c["profile_id"]))[1] != ["pending"]


# ===========================================================================
# Q19(d) — một phần năm/trường thiếu danh mục KV ⇒ dừng (bắt ở nhánh resolver)
# ===========================================================================


async def test_q19d_mot_phan_nam_thieu_danh_muc_thi_t6_dung(
    client, manager_token_headers, seed_lead_dependencies,
):
    """Trường B (lớp 10, 2019→2020) KHÔNG có hàng KV nào; trường A (lớp 11–12, 2020→2022) là KV3.

    Trước đây năm của B bị bỏ và KV3 thắng; nay dừng ``catalog_gap_school``. Ca dựng sao cho vẫn đúng khi G5
    (Q15(b): khoá ``year_from+1..year_to``) lên: năm thiếu (2020 của B) vẫn nằm trong tập khoá được tra.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            truong_b = models.VnSchool(
                moet_school_code="SQ19D", moet_province_code="001", name="THPT khong danh muc",
                province="Hà Nội", district="Ba Đình", level="THPT",
            )
            s.add(truong_b)
            await s.flush()
            sid_b = truong_b.id

    def _lich_su(seed: dict) -> list:
        return [
            {**_lich_su_nam(seed, 2020, 2022)[0], "grade_to": 12},
            {**_lich_su_nam(seed, 2019, 2020)[0], "school_id": sid_b, "grade_to": 10},
        ]

    ho_so = await seed_cascade_profile(seed_lead_dependencies, history_fn=_lich_su)
    pid = ho_so["profile_id"]
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error_code"] == "PRIORITY_KV_UNRESOLVED", body
    assert (body.get("rule_applied"), body.get("reason")) == ("catalog_gap_school", "some_school_lookups_failed"), body
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])


# ===========================================================================
# Q20 — thiếu cấu hình trình độ/loại hình của ngành ⇒ dừng, KHÔNG ghi trượt
# ===========================================================================


async def test_q20_nganh_thieu_trinh_do_thi_dung_503_khong_ghi_truot(
    client, manager_token_headers, seed_lead_dependencies,
):
    """``major_program.degree_level_id`` NULL ⇒ 503 ``CHOICE_TARGET_LEVEL_NOT_CONFIGURED``; NV vẫn ``pending``."""
    ho_so = await seed_cascade_profile(seed_lead_dependencies)
    pid = ho_so["profile_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                update(models.MajorProgram)
                .where(models.MajorProgram.id == ho_so["seed"]["major_program_id"])
                .values(degree_level_id=None)
            )
    r = await _cong_bo(client, manager_token_headers, pid)
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error_code"] == "CHOICE_TARGET_LEVEL_NOT_CONFIGURED", body
    assert (body.get("display_order"), body.get("gap_kind")) == (1, "degree_level_missing"), body
    assert await doc_lai_ho_so(pid) == ("reviewing", ["pending"])
