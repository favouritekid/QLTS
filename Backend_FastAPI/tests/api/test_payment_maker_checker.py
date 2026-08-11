"""Maker-checker của phiếu thu tay — qua ASGI THẬT, cả hai nhánh quyết định.

Bất biến: **người ghi phiếu không được tự quyết phiếu của mình**, ở CẢ HAI
nhánh — duyệt và từ chối.

Vì sao phải có bộ này, và vì sao nó đi qua HTTP thật:

* Nhánh ``verify`` đã có hàng rào từ đầu (service + CHECK constraint).
* Nhánh ``reject`` thì KHÔNG: cho tới bản vá này, chính người ghi gọi
  ``PUT /api/payments/{id}/reject`` vẫn nhận 200. Giao diện có ẩn nút và ghi
  "Khoản bạn tạo — cần người khác duyệt", nên nhìn từ màn hình thì tưởng đã có
  kiểm soát — đúng thứ chỉ lộ ra khi gọi thẳng API. Đã tái hiện trên dev
  (payment #862: ``created_by_id`` = ``rejected_by_id``).
* Và hàng rào chỉ có nghĩa nếu người ĐÚNG vẫn làm được việc: nếu manager bị
  403 thì đơn vị chỉ có một kế toán sẽ không ai duyệt nổi phiếu do người đó
  ghi. Nên bộ này khoá cả chiều dương lẫn chiều âm.

Chiều âm của IDOR cũng nằm ở đây: manager ĐƠN VỊ KHÁC phải bị chặn, và chặn
bằng 404 chứ không phải 403 — 403 tiết lộ rằng phiếu đó có thật.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.payment_service import PaymentService
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import get_auth_headers

pytestmark = pytest.mark.asyncio

_TIEN = Decimal("2000000")
_KHI = datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)  # 10:00 giờ VN


async def _tao(username: str, role: str, unit_id: int) -> dict:
    """Dùng helper CHUẨN của conftest (`_create_user_and_role`) thay vì gọi
    thẳng `create_user_with_role`: helper đó truyền đúng instance FastAPI để
    enforcer nạp lại policy sau khi thêm g-rule. Tự truyền `app.main.app` vào
    thì nhận về ASGIApp đã bọc middleware — không có `.state`, và fixture nổ
    ngay ở bước reload."""
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": username,
            "email": f"{username}@test.com",
            "password": "Checker123!",
            "role": role,
            "status": "active",
        },
        f"role:{role}",
        unit_id=unit_id,
    )


@pytest_asyncio.fixture
async def boi_canh(seed_lead_dependencies: dict, admin_user_in_db: dict):
    """Một phiếu thu PENDING do kế toán A ghi, kèm bốn nhân vật:

    maker (kế toán cùng đơn vị) · checker kế toán khác · manager cùng đơn vị ·
    manager đơn vị KHÁC.
    """
    seeded = seed_lead_dependencies
    unit = seeded["unit_id"]

    maker = await _tao("mkchk_maker", "accountant", unit)
    ke_toan_khac = await _tao("mkchk_acc2", "accountant", unit)
    mgr_cung = await _tao("mkchk_mgr", "manager", unit)

    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="mkchk_cash", name="Cash", is_online=False, is_active=True
        )
        db.add(method)

        lead = models.Lead(
            full_name="Maker Checker Student",
            phone="0901880001",
            source="test",
            unit_id=unit,
            consultation_status_id=seeded["initial_status_id"],
        )
        db.add(lead)
        await db.flush()

        profile = models.AdmissionProfile(
            lead_id=lead.id, status="submitted", academic_year=2025, applied_rules={}
        )
        db.add(profile)
        await db.flush()

        fee, _ = await FeeCalculationService(db).calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=_TIEN * 2,
            academic_year=2025,
            user_id=admin_user_in_db["id"],
            unit_id=unit,
        )
        await db.flush()

        inv = Invoice(
            fee_id=fee.id,
            invoice_number="INV-MKCHK-1",
            installment_no=1,
            amount=_TIEN * 2,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(inv)
        await db.commit()

        # Phiếu do MAKER ghi — đây là phiếu mà maker không được tự quyết.
        phieu, _ = await PaymentService(db).record_manual_payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=_TIEN,
            user_id=maker["id"],
            unit_id=unit,
            payment_date=_KHI,
        )
        await db.commit()

        return {
            "payment_id": phieu.id,
            "invoice_id": inv.id,
            "fee_id": fee.id,
            "maker": maker,
            "ke_toan_khac": ke_toan_khac,
            "mgr_cung": mgr_cung,
        }


async def _headers(client: AsyncClient, user: dict) -> dict:
    return await get_auth_headers(client, user, AuthURLs.LOGIN)


async def _doc_phieu(payment_id: int) -> Payment:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Payment).where(Payment.id == payment_id))
        ).scalar_one()


# ---------------------------------------------------------------------------
# CHIỀU ÂM — người ghi không được tự quyết
# ---------------------------------------------------------------------------

async def test_maker_khong_tu_verify_duoc(client: AsyncClient, boi_canh: dict):
    r = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/verify",
        headers=await _headers(client, boi_canh["maker"]),
    )
    assert r.status_code == 400, r.text
    assert "maker-checker" in r.text.lower()

    phieu = await _doc_phieu(boi_canh["payment_id"])
    assert phieu.status == "pending"
    assert phieu.verified_by_id is None


async def test_maker_khong_tu_reject_duoc(client: AsyncClient, boi_canh: dict):
    """Ca chính của bản vá.

    Trước khi vá, lượt gọi này trả 200 và phiếu chuyển ``rejected`` với
    ``rejected_by_id == created_by_id`` — maker tự dọn sạch hàng chờ của mình.
    """
    r = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/reject",
        params={"reason": "maker tu tu choi phieu minh ghi"},
        headers=await _headers(client, boi_canh["maker"]),
    )
    assert r.status_code == 400, r.text
    assert "maker-checker" in r.text.lower()

    # Không chỉ mã lỗi: phiếu phải KHÔNG đổi trạng thái, và không dính vết từ
    # chối nào. Một bản vá raise sau khi đã gán field vẫn làm ca trên xanh.
    phieu = await _doc_phieu(boi_canh["payment_id"])
    assert phieu.status == "pending"
    assert phieu.rejected_by_id is None
    assert phieu.rejected_at is None
    assert phieu.rejection_reason is None


# ---------------------------------------------------------------------------
# CHIỀU DƯƠNG — người khác maker vẫn phải làm được việc
# ---------------------------------------------------------------------------

async def test_manager_cung_don_vi_verify_duoc(client: AsyncClient, boi_canh: dict):
    """Nếu ca này đỏ thì hàng rào đã chặn nhầm người: đơn vị chỉ có một kế toán
    sẽ không ai duyệt nổi phiếu do người đó ghi."""
    r = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/verify",
        headers=await _headers(client, boi_canh["mgr_cung"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"

    phieu = await _doc_phieu(boi_canh["payment_id"])
    assert phieu.verified_by_id == boi_canh["mgr_cung"]["id"]
    assert phieu.verified_by_id != phieu.created_by_id


async def test_manager_cung_don_vi_reject_duoc(client: AsyncClient, boi_canh: dict):
    r = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/reject",
        params={"reason": "checker tu choi hop le"},
        headers=await _headers(client, boi_canh["mgr_cung"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    phieu = await _doc_phieu(boi_canh["payment_id"])
    assert phieu.rejected_by_id == boi_canh["mgr_cung"]["id"]
    assert phieu.rejected_by_id != phieu.created_by_id
    assert phieu.rejection_reason == "checker tu choi hop le"


async def test_ke_toan_khac_reject_duoc(client: AsyncClient, boi_canh: dict):
    """Checker không nhất thiết phải là manager — miễn KHÁC người ghi."""
    r = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/reject",
        params={"reason": "ke toan khac tu choi"},
        headers=await _headers(client, boi_canh["ke_toan_khac"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# IDOR — đúng vai nhưng SAI ĐƠN VỊ
# ---------------------------------------------------------------------------

async def test_manager_khac_don_vi_bi_chan_bang_404(
    client: AsyncClient,
    boi_canh: dict,
    manager_other_unit_user_in_db: dict,
):
    """404 chứ không phải 403: 403 xác nhận phiếu đó có thật.

    Dùng fixture đơn vị-khác của conftest thay vì bịa `unit_id`: đơn vị phải
    TỒN TẠI thật trong `organization_unit`, không thì fixture chết ở FK và ca
    IDOR không bao giờ chạy."""
    h = await _headers(client, manager_other_unit_user_in_db)

    r_ver = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/verify", headers=h
    )
    assert r_ver.status_code == 404, r_ver.text

    r_rej = await client.put(
        f"/api/payments/{boi_canh['payment_id']}/reject",
        params={"reason": "khac don vi"},
        headers=h,
    )
    assert r_rej.status_code == 404, r_rej.text

    phieu = await _doc_phieu(boi_canh["payment_id"])
    assert phieu.status == "pending"
    assert phieu.rejected_by_id is None
