"""GĐ1b K4 — xoá tài khoản theo sổ phân loại khoá ngoại MỘT nguồn (đặc tả bản 3.6 §4.3, §9; mốc nền V5 17-11).

Mốc nền V5 ở ``221a757d`` (``logs-P5/cong-bo-ket-qua/gd1b/v5/``): có ``assignment_log`` / tư vấn ⇒ 500; có lead đang giao ⇒
lead bị gỡ âm thầm (cả xoá lẻ lẫn hàng loạt). Sau GĐ1b: mọi ca có tham chiếu ⇒ 409, không xoá, không gỡ lead.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select, text

from app import models
from app.database import AsyncSessionLocal, engine
from app.security import get_password_hash
from app.services.user_deletion_policy import USER_REFERENCES, UserRefGroup
from tests.fixtures.constants import AdminURLs

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------------------------------------------------
# Một nguồn: sổ phân loại == khoá ngoại thật tới "user" trong pg_constraint.
# --------------------------------------------------------------------------------------------------------------------
async def test_so_phan_loai_khop_dung_tap_khoa_ngoai_toi_user_trong_pg_constraint(setup_test_database):
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT c.conrelid::regclass::text AS tbl, a.attname AS col, c.confdeltype::text AS deltype, "
                    "a.attnotnull AS notnull "
                    "FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
                    "WHERE c.contype = 'f' AND c.confrelid = '\"user\"'::regclass AND array_length(c.conkey, 1) = 1"
                )
            )
        ).all()
    that = {(r.tbl.strip('"'), r.col) for r in rows}
    so = [(r.table, r.column) for r in USER_REFERENCES]
    assert len(so) == len(set(so)), "một cột chỉ được ở MỘT nhóm"
    assert set(so) == that, {"thiếu trong sổ": sorted(that - set(so)), "thừa trong sổ": sorted(set(so) - that)}

    # Cột NO ACTION / RESTRICT / NOT NULL không được ở IGNORE (CSDL sẽ không tự xử lý được).
    ignore = {(r.table, r.column) for r in USER_REFERENCES if r.group is UserRefGroup.IGNORE}
    for r in rows:
        if (r.tbl.strip('"'), r.col) in ignore:
            assert r.deltype == "n", (r.tbl, r.col)  # n = SET NULL
            assert not r.notnull, (r.tbl, r.col)


# --------------------------------------------------------------------------------------------------------------------
# Dữ liệu giả.
# --------------------------------------------------------------------------------------------------------------------
async def _tao_can_bo(ten: str, unit_id: int, role: str = "officer") -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            u = models.User(
                username=ten, email=f"{ten}@example.com", password_hash=get_password_hash("MatKhauThu!K4x9"),
                full_name=ten, role=role, status="active", unit_id=unit_id,
            )
            s.add(u)
            await s.flush()
            return u.id


async def _tao_lead(ten: str, seed: dict, officer_id) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Lead {ten}", phone=f"09{abs(hash(ten)) % 10**8:08d}", email=f"lead_{ten}@example.com",
                source="website", unit_id=seed["unit_id"], assigned_officer_id=officer_id,
                consultation_status_id=seed["initial_status_id"], consultation_count=0, status="new",
            )
            s.add(lead)
            await s.flush()
            return lead.id


async def _tu_van(lead_id: int, uid: int, seed: dict):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(
                models.Consultation(
                    lead_id=lead_id, officer_id=uid, consultation_date=datetime.now(timezone.utc), method="phone",
                    notes="k4", consultation_status_id=seed["initial_status_id"],
                )
            )


async def _dung_ca(loai: str, ten: str, seed: dict) -> int:
    uid = await _tao_can_bo(ten, seed["unit_id"])
    if loai == "lead_dang_giao":
        await _tao_lead(ten, seed, uid)
    elif loai == "assignment_log":
        lead_id = await _tao_lead(ten, seed, None)
        async with AsyncSessionLocal() as s:
            async with s.begin():
                s.add(models.AssignmentLog(lead_id=lead_id, method="manual", officer_id=uid))
    elif loai == "tu_van":
        await _tu_van(await _tao_lead(ten, seed, None), uid, seed)
    elif loai == "ca_ba":
        lead_id = await _tao_lead(ten, seed, uid)
        async with AsyncSessionLocal() as s:
            async with s.begin():
                s.add(models.AssignmentLog(lead_id=lead_id, method="manual", officer_id=uid))
        await _tu_van(lead_id, uid, seed)
    elif loai == "chi_dau_tai":
        # Người chỉ còn dấu tải xuống (hồ sơ nháp đã bị xoá — dòng tải sống độc lập, không khoá ngoại tới hồ sơ).
        async with AsyncSessionLocal() as s:
            async with s.begin():
                s.add(models.DocumentDownloadLog(actor_user_id=uid, profile_id=999999, document_row_id=999999))
    elif loai != "khong_tham_chieu":
        raise AssertionError(loai)
    return uid


async def _con_ton_tai(uid: int) -> bool:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(models.User).where(models.User.id == uid))).scalar() == 1


async def _lead_dang_giao(uid: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(func.count()).select_from(models.Lead).where(models.Lead.assigned_officer_id == uid))
        ).scalar()


async def _xoa(client, headers, duong: str, ids):
    if duong == "xoa_le":
        return await client.delete(AdminURLs.USER_DETAIL(ids[0]), headers=headers)
    return await client.post(AdminURLs.BULK_ACTION, json={"action": "delete", "user_ids": list(ids)}, headers=headers)


MONG_DOI = {
    "khong_tham_chieu": (200, None),
    "lead_dang_giao": (409, "USER_HAS_CURRENT_WORK"),
    "assignment_log": (409, "USER_HAS_ASSIGNMENT_HISTORY"),
    "tu_van": (409, "USER_HAS_ACTIVITY"),
    "ca_ba": (409, "USER_HAS_CURRENT_WORK"),
    "chi_dau_tai": (409, "USER_HAS_ACTIVITY"),
}


@pytest.mark.parametrize("loai", sorted(MONG_DOI))
@pytest.mark.parametrize("duong", ["xoa_le", "xoa_hang_loat"])
async def test_ma_tran_v5_sau_gd1b_thanh_409_khong_xoa_khong_go_lead(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict, loai: str, duong: str
):
    uid = await _dung_ca(loai, f"k4_{duong}_{loai}", seed_lead_dependencies)
    lead_truoc = await _lead_dang_giao(uid)
    r = await _xoa(client, admin_token_headers, duong, [uid])
    ma, code = MONG_DOI[loai]
    assert r.status_code == ma, r.text
    if ma == 200:
        assert not await _con_ton_tai(uid)
        return
    assert r.json().get("error_code") == code, r.text
    assert await _con_ton_tai(uid)
    assert await _lead_dang_giao(uid) == lead_truoc  # KHÔNG gỡ âm thầm (K4b = C)
    if loai in ("lead_dang_giao", "ca_ba"):
        assert "Đang phụ trách 1 lead" in r.json()["detail"], r.text


async def test_xoa_hang_loat_mot_nguoi_khong_dat_thi_409_khong_mot_cau_ghi_nao(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
):
    tot = await _dung_ca("khong_tham_chieu", "k4_lo_tot", seed_lead_dependencies)
    xau = await _dung_ca("lead_dang_giao", "k4_lo_xau", seed_lead_dependencies)
    cau = []

    def _ghi(conn, cursor, statement, parameters, context, executemany):
        cau.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _ghi)
    try:
        r = await _xoa(client, admin_token_headers, "xoa_hang_loat", [tot, xau])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _ghi)
    assert r.status_code == 409, r.text
    ghi = [c for c in cau if re.match(r"\s*(UPDATE|DELETE)\b", c, re.I)]
    assert ghi == [], ghi
    assert await _con_ton_tai(tot) and await _con_ton_tai(xau)
    assert await _lead_dang_giao(xau) == 1


async def _lo(uid: int, status: str):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            b = models.DocumentBulkBatch(
                batch_id=uuid.uuid4(), actor_user_id=uid, filter_json={"profile_ids": []}, payload_sha256="0" * 64,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30), status=status,
            )
            s.add(b)
            await s.flush()
            s.add(
                models.DocumentBulkBatchItem(
                    batch_id=b.batch_id, document_row_id=1, profile_id=1, expected_row_version=1,
                )
            )
            return b.batch_id


async def test_ban_xem_truoc_chua_chay_xoa_cung_nguoi_dung_lo_da_chay_thi_chan(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
):
    a = await _dung_ca("khong_tham_chieu", "k4_lo_xem_truoc", seed_lead_dependencies)
    lo_a = await _lo(a, "previewed")
    r = await _xoa(client, admin_token_headers, "xoa_le", [a])
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        assert await s.get(models.DocumentBulkBatch, lo_a) is None

    b = await _dung_ca("khong_tham_chieu", "k4_lo_da_chay", seed_lead_dependencies)
    await _lo(b, "completed")
    r = await _xoa(client, admin_token_headers, "xoa_hang_loat", [b])
    assert r.status_code == 409 and r.json()["error_code"] == "USER_HAS_ACTIVITY", r.text
    assert await _con_ton_tai(b)
