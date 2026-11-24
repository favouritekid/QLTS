# -*- coding: utf-8 -*-
"""Danh mục THCS (owner 22-11) — NỐI DÂY qua app thật: tạo trường THCS mã nội bộ, KV gợi ý từ xã, xác nhận KV
(máy chủ chép KV, không nhận ``kv_code`` từ client), câu kiểm lệch, chỉ Admin.

Logic chi tiết: ``tests/unit/test_vn_school_thcs_noi_bo.py``. Ở đây chỉ kiểm đường người dùng đi (CLAUDE.md chung §10).
"""
import re

import pytest
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app.models.vn_school import VnSchool

pytestmark = [pytest.mark.asyncio]

BASE = "/api/v2/admin/vn-school"
XA = "/api/v2/admin/vn-locality/communes"


async def _tao_xa(client, h, ma="99101", kv="KV1") -> dict:
    r = await client.post(
        XA,
        json={"commune_code": ma, "province": "Tỉnh Thử", "district": "", "ward": "Xã Thử", "area_code": kv},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _thcs(**kw) -> dict:
    return {
        "moet_province_code": "048",
        "name": kw.get("name", "THCS Thử API"),
        "province": "Tỉnh Thử",
        "level": kw.get("level", "THCS"),
        "commune_code": kw.get("commune_code", "99101"),
        "is_dtnt": kw.get("is_dtnt", False),
    }


async def test_tao_truong_thcs_ma_noi_bo_va_xac_nhan_kv_goi_y(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    xa = await _tao_xa(client, h, kv="KV2-NT")

    r = await client.post(f"{BASE}/schools", json=_thcs(is_dtnt=True), headers=h)
    assert r.status_code == 201, r.text
    s = r.json()
    assert re.match(r"^NB[0-9]{6}$", s["moet_school_code"]), s
    assert s["is_internal_code"] is True
    assert s["commune_code"] == "99101"
    assert s["is_dtnt"] is True
    assert s["current_kv"] is None  # chưa xác nhận

    r = await client.get(f"{BASE}/schools/{s['id']}/kv-suggestion", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["suggested_kv"] == "KV2-NT"

    # Client gửi kèm kv_code / năm giả ⇒ bị bỏ qua: KV do máy chủ chép từ xã, năm do máy điền (từ 2000, không năm
    # kết thúc — owner 22-11, L3-a câu 2).
    r = await client.post(
        f"{BASE}/schools/{s['id']}/kv/from-commune",
        json={"effective_from_year": 2021, "effective_to_year": 2022, "kv_code": "KV3", "source": "manual_admin"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    kv = r.json()
    assert (kv["kv_code"], kv["source"], kv["effective_from_year"], kv["effective_to_year"]) == (
        "KV2-NT", "xa_hien_hanh", 2000, None,
    )
    r = await client.get(f"{BASE}/schools", params={"level": "THCS"}, headers=h)
    assert [x["current_kv"] for x in r.json()["items"]] == ["KV2-NT"]

    r = await client.get(f"{BASE}/internal/kv-mismatch", headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["mismatch_count"], r.json()["commune_inactive_count"]) == (0, 0)

    # Xã đổi KV ⇒ câu kiểm lệch đếm 1.
    r = await client.post(f"{XA}/{xa['id']}/replace-area", json={"area_code": "KV1"}, headers=h)
    assert r.status_code in (200, 201), r.text
    r = await client.get(f"{BASE}/internal/kv-mismatch", headers=h)
    assert r.json()["mismatch_count"] == 1
    assert r.json()["items"][0]["school_id"] == s["id"]


async def test_thcs_go_ma_bo_400_va_ma_NB_go_tay_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    await _tao_xa(client, h)
    r = await client.post(f"{BASE}/schools", json={**_thcs(), "moet_school_code": "040123"}, headers=h)
    assert r.status_code == 400, r.text
    r = await client.post(
        f"{BASE}/schools",
        json={"moet_school_code": "NB000001", "moet_province_code": "048", "name": "X", "province": "P",
              "level": "THPT"},
        headers=h,
    )
    assert r.status_code == 400, r.text


async def test_thcs_thieu_xa_400_xa_la_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    r = await client.post(f"{BASE}/schools", json={**_thcs(), "commune_code": None}, headers=h)
    assert r.status_code == 400, r.text
    r = await client.post(f"{BASE}/schools", json=_thcs(commune_code="00000"), headers=h)
    assert r.status_code == 400, r.text


async def test_duong_kv_chung_khong_nhan_nguon_xa_hien_hanh(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    await _tao_xa(client, h)
    sid = (await client.post(f"{BASE}/schools", json=_thcs(), headers=h)).json()["id"]
    r = await client.post(
        f"{BASE}/schools/{sid}/kv",
        json={"kv_code": "KV3", "effective_from_year": 2020, "source": "xa_hien_hanh"},
        headers=h,
    )
    assert r.status_code == 400, r.text


async def test_cac_duong_moi_chi_admin(
    client: AsyncClient, officer_token_headers: dict, setup_test_database
) -> None:
    client.cookies.clear()
    h = officer_token_headers
    for method, path, body in (
        ("get", f"{BASE}/schools/1/kv-suggestion", None),
        ("post", f"{BASE}/schools/1/kv/from-commune", {}),
        ("get", f"{BASE}/internal/kv-mismatch", None),
    ):
        r = await getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.status_code, r.text)


# ---- Rà Codex đoàn 3b T3: trường cấp THCS ĐÃ có mã Bộ vẫn sửa được; chỉ chặn tạo mới / đổi cấp sang THCS ----


async def _truong_thcs_co_ma_bo_cu() -> int:
    """Dòng như production trước đoàn 3b: cấp THCS KÈM mã Bộ (đường tạo cũ không chặn). Đường tạo của 3b đã cấm
    nên phải chèn thẳng — cách DUY NHẤT dựng lại trạng thái ấy."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            truong = VnSchool(
                moet_school_code="040555", moet_province_code="048", name="THCS cũ có mã Bộ",
                province="Tỉnh Thử", level="THCS", is_dtnt=False,
            )
            s.add(truong)
            await s.flush()
            return truong.id


async def test_truong_thcs_co_ma_bo_san_sua_dtnt_kem_cap_khong_doi_200(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    sid = await _truong_thcs_co_ma_bo_cu()
    # Form sửa của trang Admin LUÔN gửi kèm cấp (SchoolTable.tsx) — ở đây cấp không đổi.
    r = await client.patch(
        f"{BASE}/schools/{sid}", json={"level": "THCS", "is_dtnt": True}, headers=admin_token_headers
    )
    assert r.status_code == 200, r.text
    assert (r.json()["moet_school_code"], r.json()["level"], r.json()["is_dtnt"]) == ("040555", "THCS", True)


async def test_truong_thpt_co_ma_bo_doi_sang_cap_thcs_van_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    r = await client.post(
        f"{BASE}/schools",
        json={"moet_school_code": "040556", "moet_province_code": "048", "name": "THPT có mã Bộ",
              "province": "Tỉnh Thử", "level": "THPT"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = await client.patch(f"{BASE}/schools/{r.json()['id']}", json={"level": "THCS"}, headers=h)
    assert r.status_code == 400, r.text


async def test_tao_moi_truong_thcs_kem_ma_bo_van_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    await _tao_xa(client, h)
    r = await client.post(f"{BASE}/schools", json={**_thcs(), "moet_school_code": "040557"}, headers=h)
    assert r.status_code == 400, r.text
