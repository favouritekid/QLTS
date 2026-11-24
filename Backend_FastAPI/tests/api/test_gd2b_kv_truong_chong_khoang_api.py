# tests/api/test_gd2b_kv_truong_chong_khoang_api.py
"""Codex 22-11 lượt 2 B-P1 — đường THẬT cán bộ đi (HTTP ``POST /api/v2/admissions/{id}/publish-result``, T6): danh mục KV
trường có HAI dòng cùng khớp một (trường, năm) — khoảng hiệu lực chồng nhau (CSDL cho phép; chỉ dịch vụ quản trị kiểm chồng lấn
trước khi chèn). T6 phải chọn ĐÚNG dòng theo thứ tự chung ``models.vn_school.school_kv_pick_order_sql`` (năm bắt đầu mới nhất,
rồi ``id`` lớn nhất) — CÙNG dòng mà máy xét GĐ2-B chọn ở đường lô.

Dữ liệu: trường của bộ gieo ``seed_cascade_profile`` có KV3 cho 2020–2024 (dòng CŨ, chèn trước); thêm KV1 từ 2022, không hạn (dòng
MỚI, chèn sau). Quá trình học 2020→2024 — sau G5 (khoá = NĂM BẮT ĐẦU của năm học: tra 2020, 2021, 2022, 2023; không tra 2024):
2020–2021 chỉ khớp KV3; 2022–2023 khớp CẢ HAI ⇒ chọn KV1 ⇒ KV3 2 năm = KV1 2 năm ⇒ HOÀ ⇒ tra trường tốt nghiệp (chính trường ấy)
ở năm học cuối 2023 ⇒ lại chọn KV1 ⇒ KV1, ``tiebreak_graduation_school`` (mức 0,75). (Trước G5: 2022–2024 ⇒ KV1 3 năm > KV3 2 năm.)
Chọn bừa dòng đầu (thứ tự vật lý) ⇒ KV3 cả 4 năm ⇒ ``longest_duration`` KV3 ⇒ mức 0,00.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.cascade import seed_cascade_profile

pytestmark = pytest.mark.integration


async def test_publish_result_kv_truong_chong_khoang_chon_dong_nam_bat_dau_moi_nhat(
    client, manager_token_headers, seed_lead_dependencies,
):
    ho_so = await seed_cascade_profile(seed_lead_dependencies)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(
                models.VnSchoolKvAssignment(
                    school_id=ho_so["seed"]["school_id"],
                    kv_code="KV1",
                    effective_from_year=2022,
                    effective_to_year=None,
                    source="manual_admin",
                )
            )
    r = await client.post(f"/api/v2/admissions/{ho_so['profile_id']}/publish-result", headers=manager_token_headers)
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        anh_chup = (
            await s.execute(
                select(models.AdmissionProfile.priority_resolution_snapshot).where(
                    models.AdmissionProfile.id == ho_so["profile_id"]
                )
            )
        ).scalar_one()
        diem_kv = (
            await s.execute(
                select(models.AdmissionProfileChoice.priority_area_bonus_snapshot).where(
                    models.AdmissionProfileChoice.id == ho_so["choice_ids"][0]
                )
            )
        ).scalar_one()
    assert anh_chup["kv_resolved"] == "KV1", anh_chup
    # Codex GĐ2-B lượt 2 P4: sau G5 ca này đi nhánh HOÀ 2–2 — khoá đúng nhánh, không chỉ đúng KV.
    assert anh_chup["rule_applied"] == "tiebreak_graduation_school", anh_chup
    assert anh_chup["breakdown"]["kv_totals"] == {"KV3": 2, "KV1": 2}, anh_chup["breakdown"]
    assert anh_chup["breakdown"]["graduation_lookup_year"] == 2023, anh_chup["breakdown"]
    assert diem_kv is not None and Decimal(diem_kv) == Decimal("0.75"), diem_kv
