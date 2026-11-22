"""PR-D (F12) — User-Agent dài hơn cột nhật ký KHÔNG làm hỏng thao tác nghiệp vụ; vết lưu bị cắt đúng độ dài cột.

Trước PR-D: ``document_audit_log.user_agent`` / ``document_download_log.user_agent`` là ``VARCHAR(500)``,
``user_activity_log.user_agent`` là ``VARCHAR(256)``; đường duyệt từng giấy, chạy lô (từng giấy), tải xuống ghi nguyên chuỗi ⇒
lỗi ``22001`` ⇒ 500 (lẻ / tải) / ``system_error`` (lô dừng ở hồ sơ đầu); mọi thao tác Admin ghi nhật ký hoạt động với
User-Agent 257–500 ký tự ⇒ 500. Từ PR-D: cột khai ``TruncatedString(n)`` — cắt ở tầng kiểu, MỘT chỗ cho mỗi bảng.

Độ dài cột đọc từ CSDL (``information_schema``), không ghim số trong test. Mỗi đường chạy hai biến thể: đúng trần (``du = 0``,
đối chứng — xanh cả trước PR-D) và vượt trần một ký tự (``du = 1``). Mỗi ca MỘT bất biến: thao tác vẫn đúng như khi
User-Agent ngắn, và chuỗi lưu = ``ua[:độ dài cột]``. User-Agent dài chỉ gửi ở YÊU CẦU nghiệp vụ, không ở lúc đăng nhập
(phiên đăng nhập không thuộc phạm vi PR-D). Dữ liệu giả.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    CROSS,
    dn,
    dong_lo,
    lo_config,
    lo_routers,
    tao_ho_so_cho_xet,
    xac_nhan,
)
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)
from tests.api.test_gd1b_bang_chung_tai import (  # noqa: F401
    PDF,
    _bang_chung,
    _duyet as _duyet_co_tep,
    _tai_len,
    _url,
    gan_route_bang_chung,
)
from tests.api.test_gd1b_cheo_quyen import can_bo_cheo  # noqa: F401
from tests.fixtures.constants import AdminURLs
from tests.fixtures.gd1b import phien_ban_giay

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"
DU = pytest.mark.parametrize("du", [0, 1], ids=["dung_tran", "vuot_tran_1_ky_tu"])


def _ua(n: int) -> str:
    """User-Agent giả dài đúng ``n`` ký tự; đuôi đổi theo vị trí để phép so ``ua[:trần]`` bắt được cắt sai chỗ."""
    dau = "Mozilla/5.0 (PR-D F12) "
    return (dau + "".join(chr(ord("a") + i % 26) for i in range(n)))[:n]


async def _tran(bang: str) -> int:
    async with AsyncSessionLocal() as s:
        n = (
            await s.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :t AND column_name = 'user_agent'"
                ),
                {"t": bang},
            )
        ).scalar_one()
    assert n, bang
    return int(n)


async def _dn(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    return await _login(client, user["username"], user["password"])


async def _id_giay(pid: int, code: str) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument.id)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def _ua_nhat_ky_giay(doc_id: int, action: str) -> list:
    async with AsyncSessionLocal() as s:
        return list(
            (
                await s.execute(
                    select(models.DocumentAuditLog.user_agent)
                    .where(models.DocumentAuditLog.profile_document_id == doc_id, models.DocumentAuditLog.action == action)
                    .order_by(models.DocumentAuditLog.id)
                )
            ).scalars()
        )


# ---------------------------------------------------------------- duyệt từng giấy (nút lẻ)
@DU
async def test_duyet_le_user_agent_dai_van_duyet_duoc_va_vet_cat_dung_do_dai_cot(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, du
):
    tran = await _tran("document_audit_log")
    ua = _ua(tran + du)
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, f"prd_ua_le_{du}")
    pid, code = prof["id"], parity_config["paper_doc_code"]
    h = await _dn(client, officer_user_in_db)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted", headers=h, json={"actual_submission_format": "original"}
    )
    assert r.status_code == 200, r.text
    h = await _dn(client, admin_user_in_db)
    r = await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{code}/verify-format", headers={**h, "User-Agent": ua},
        json={"format": "original", "expected_row_version": await phien_ban_giay(pid, code)},
    )
    assert r.status_code == 200, r.text
    assert await _ua_nhat_ky_giay(await _id_giay(pid, code), "verified") == [ua[:tran]]


# ---------------------------------------------------------------- chạy lô (Quản lý)
@DU
async def test_chay_lo_user_agent_dai_lo_hoan_tat_va_vet_cat_dung_do_dai_cot(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers, du
):
    tran_nk, tran_lo = await _tran("document_audit_log"), await _tran("document_bulk_batch")
    ua = _ua(max(tran_nk, tran_lo) + du)
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, f"prd_ua_lo_{du}")
    h = {**(await dn(client, manager_user_in_db)), "User-Agent": ua}
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": [p["id"]], "include_optional": False})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    r = await client.post(f"{BULK}/{ma}/execute", headers=h, json=await xac_nhan(ma))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["counts"]["recorded"] == 2, r.text
    assert (await dong_lo(ma))["user_agent"] == ua[:tran_lo]
    for k in "AB":
        assert await _ua_nhat_ky_giay(p["docs"][k].id, "verified") == [ua[:tran_nk]], k


# ---------------------------------------------------------------- tải lại tệp bằng chứng duyệt
@DU
async def test_tai_bang_chung_user_agent_dai_van_tai_duoc_va_vet_cat_dung_do_dai_cot(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, gan_route_bang_chung, du
):
    tran_nk, tran_dau = await _tran("document_audit_log"), await _tran("document_download_log")
    ua = _ua(max(tran_nk, tran_dau) + du)
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, f"prd_ua_bc_{du}")
    pid, code = prof["id"], parity_config["upload_doc_code"]
    noi_dung = PDF + f"pr-d {du}".encode()
    await _tai_len(client, officer_user_in_db, pid, code, noi_dung)
    d = await _duyet_co_tep(client, admin_user_in_db, pid, code)
    ev = (await _bang_chung(d.id))[-1]
    h = await _dn(client, admin_user_in_db)
    r = await client.get(_url(pid, d.id, ev.id), headers={**h, "User-Agent": ua})
    assert r.status_code == 200, r.text
    assert r.content == noi_dung
    assert await _ua_nhat_ky_giay(d.id, "downloaded") == [ua[:tran_nk]]
    async with AsyncSessionLocal() as s:
        dau = list(
            (
                await s.execute(
                    select(models.DocumentDownloadLog.user_agent).where(models.DocumentDownloadLog.document_row_id == d.id)
                )
            ).scalars()
        )
    assert dau == [ua[:tran_dau]]


# ---------------------------------------------------------------- thao tác Admin ghi nhật ký hoạt động (xoá tài khoản lẻ)
async def _tao_tai_khoan(ten: str, unit_id: int) -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            u = models.User(
                username=ten, email=f"{ten}@example.com", password_hash=get_password_hash("MatKhauThu!PrD9x"),
                full_name=ten, role="officer", status="active", unit_id=unit_id,
            )
            s.add(u)
            await s.flush()
            return u.id


@DU
async def test_xoa_tai_khoan_user_agent_dai_van_xoa_duoc_va_nhat_ky_hoat_dong_cat_dung_do_dai_cot(
    client, admin_token_headers, seed_lead_dependencies, du
):
    tran = await _tran("user_activity_log")
    ua = _ua(tran + du)
    uid = await _tao_tai_khoan(f"prd_ua_xoa_{du}", seed_lead_dependencies["unit_id"])
    r = await client.delete(AdminURLs.USER_DETAIL(uid), headers={**admin_token_headers, "User-Agent": ua})
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        con = (await s.execute(select(func.count()).select_from(models.User).where(models.User.id == uid))).scalar()
        luu = list(
            (
                await s.execute(
                    select(models.UserActivityLog.user_agent).where(
                        models.UserActivityLog.action == "delete_user", models.UserActivityLog.resource_id == uid
                    )
                )
            ).scalars()
        )
    assert con == 0
    assert luu == [ua[:tran]]


# ---------------------------------------------------------------- cấp quyền duyệt chéo (entity_audit_log — bỏ bản cắt rời)
async def test_cap_quyen_cheo_user_agent_dai_van_cap_duoc_va_vet_cat_dung_do_dai_cot(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    tran = await _tran("entity_audit_log")
    ua = _ua(tran + 1)
    h = await dn(client, admin_user_in_db)
    r = await client.post(
        f"{CROSS}/grants", headers={**h, "User-Agent": ua},
        json={
            "grantee_user_id": can_bo_cheo["id"], "unit_id": lo_config["unit_id"], "allow_verify": True,
            "allow_reject": False, "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            "reason": "Thiếu người duyệt",
        },
    )
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as s:
        luu = list(
            (
                await s.execute(
                    select(models.EntityAuditLog.user_agent).where(
                        models.EntityAuditLog.entity_type == "document_cross_review_grant",
                        models.EntityAuditLog.entity_id == r.json()["id"],
                        models.EntityAuditLog.action == "granted",
                    )
                )
            ).scalars()
        )
    assert luu == [ua[:tran]]
