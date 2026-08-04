"""Lọc phiếu thu theo KHOẢN PHÍ, không chỉ theo một đợt hoá đơn.

Vì sao cần: form ghi tiền sắp hiện ô "đang chờ duyệt" để kế toán thấy phiếu
mình vừa nhập mà chưa ai duyệt. Một khoản phí có thể có NHIỀU hoá đơn (mỗi đợt
một cái), nên phiếu vừa nhập rất dễ nằm ở hoá đơn khác với hoá đơn đang mở.
Lọc theo ``invoice_id`` sẽ không thấy nó, ô đếm hiện 0, và kế toán lại tưởng
lần nhập trước trượt — đúng cái vòng dẫn tới 9 phiếu trùng trên prod.

Ca quyết định ở đây là ``test_fee_id_thay_ca_hai_dot``: nó chỉ xanh khi bộ lọc
đi qua ``Invoice.fee_id``. Bỏ điều kiện ``fee_id`` trong repository thì nó trả
về CẢ phiếu của khoản phí khác và ca này đỏ.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    PaymentMethod,
)
from app.security import get_password_hash
from app.services.fee_calculation_service import FeeCalculationService
from app.services.payment_service import PaymentService

pytestmark = pytest.mark.asyncio


async def _seed_fee_with_two_invoices(
    db: AsyncSession,
    seeded: dict,
    admin_user_id: int,
    *,
    phone: str,
    prefix: str,
    total: Decimal,
):
    """Một khoản phí → HAI hoá đơn (hai đợt) → mỗi đợt một phiếu thu 'pending'."""
    lead = models.Lead(
        full_name=f"Hoc sinh {prefix}",
        phone=phone,
        source="test",
        unit_id=seeded["unit_id"],
        consultation_status_id=seeded["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id, status="submitted", academic_year=2025, applied_rules={}
    )
    db.add(profile)
    await db.flush()

    # Lệ phí hồ sơ, KHÔNG phải học phí: `calculate_fee` với `tuition` đòi hồ sơ
    # có thông tin tuyển sinh để tra giá theo ngành, mà ở đây ta chỉ cần một
    # khoản phí bất kỳ để treo hai hoá đơn lên. Loại phí không liên quan tới
    # thứ đang kiểm (bộ lọc theo fee).
    fee, _ = await FeeCalculationService(db).calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.application,
        base_amount=total,
        academic_year=2025,
        user_id=admin_user_id,
        unit_id=seeded["unit_id"],
    )
    await db.flush()

    half = total / 2
    invoices = []
    for idx in (1, 2):
        inv = Invoice(
            fee_id=fee.id,
            invoice_number=f"INV-TEST-{prefix}-{idx}",
            installment_no=idx,
            amount=half,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30 * idx),
        )
        db.add(inv)
        invoices.append(inv)
    await db.flush()

    return fee, invoices


@pytest_asyncio.fixture
async def two_fees_ctx(seed_lead_dependencies: dict, admin_user_in_db: dict):
    """Hai khoản phí độc lập, mỗi cái hai đợt — để chứng minh bộ lọc không rò.

    ``tests/api/`` không có fixture ``db`` (đó là của ``tests/services/``), nên
    tự mở session và **commit** — client gọi API qua session khác, không thấy
    dữ liệu chưa commit. ``admin_user_in_db`` trả **dict**, không phải object.
    """
    seeded = seed_lead_dependencies
    admin_id = admin_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="listfilter_cash", name="Cash", is_online=False, is_active=True
        )
        db.add(method)

        maker = models.User(
            username="listfilter_maker",
            email="listfilter_maker@test.com",
            password_hash=get_password_hash("Maker123!"),
            role="officer",
            status="active",
            full_name="List Filter Maker",
            unit_id=seeded["unit_id"],
        )
        db.add(maker)
        await db.flush()

        fee_a, inv_a = await _seed_fee_with_two_invoices(
            db, seeded, admin_id,
            phone="0901550001", prefix="A", total=Decimal("2000000"),
        )
        fee_b, inv_b = await _seed_fee_with_two_invoices(
            db, seeded, admin_id,
            phone="0901550002", prefix="B", total=Decimal("4000000"),
        )
        await db.commit()

        svc = PaymentService(db)
        pay_a = []
        for inv in inv_a:
            p, _ = await svc.record_manual_payment(
                invoice_id=inv.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                user_id=maker.id,
                unit_id=seeded["unit_id"],
            )
            pay_a.append(p)
        # Khoản phí B chỉ một phiếu — đủ để phát hiện rò sang khoản phí khác.
        pay_b, _ = await svc.record_manual_payment(
            invoice_id=inv_b[0].id,
            method_id=method.id,
            amount=Decimal("2000000"),
            user_id=maker.id,
            unit_id=seeded["unit_id"],
        )
        await db.commit()

        return {
            "fee_a_id": fee_a.id,
            "fee_b_id": fee_b.id,
            "inv_a_ids": [i.id for i in inv_a],
            "pay_a_ids": sorted(p.id for p in pay_a),
            "pay_b_id": pay_b.id,
        }


class TestListPaymentsByFee:
    async def test_fee_id_thay_ca_hai_dot(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """Lọc theo fee phải trả phiếu của MỌI đợt thuộc khoản phí đó."""
        ctx = two_fees_ctx
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_a_id']}&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = sorted(item["id"] for item in r.json()["items"])

        assert ids == ctx["pay_a_ids"], (
            f"phải thấy ĐỦ hai phiếu của hai đợt {ctx['pay_a_ids']}, nhận {ids}"
        )
        # Không rò sang khoản phí khác — nếu bộ lọc bị bỏ thì phiếu này lọt vào.
        assert ctx["pay_b_id"] not in ids, (
            "phiếu của khoản phí KHÁC lọt vào kết quả — bộ lọc fee_id không có tác dụng"
        )

    async def test_invoice_id_chi_thay_mot_dot(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """Đối chứng: lọc theo invoice chỉ thấy MỘT đợt.

        Đây là lý do tồn tại của ``fee_id``. Nếu ca này cũng trả về hai phiếu
        thì hai bộ lọc đang làm cùng một việc và ``fee_id`` là thừa.
        """
        ctx = two_fees_ctx
        r = await client.get(
            f"/api/payments?invoice_id={ctx['inv_a_ids'][0]}&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]

        assert len(ids) == 1, f"lọc theo một đợt phải ra đúng 1 phiếu, nhận {ids}"
        assert ids[0] in ctx["pay_a_ids"]

    async def test_khong_truyen_fee_id_thi_khong_loc(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """Bỏ trống fee_id thì hành vi cũ giữ nguyên — thấy cả hai khoản phí."""
        ctx = two_fees_ctx
        r = await client.get("/api/payments?page_size=100", headers=admin_token_headers)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}

        assert set(ctx["pay_a_ids"]).issubset(ids)
        assert ctx["pay_b_id"] in ids

    async def test_fee_id_bang_khong_bi_tu_choi(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """fee_id=0 phải bị TỪ CHỐI, không được coi như 'không lọc'.

        Đây là ca biên thật, không phải bắt bẻ: viết ``if fee_id:`` thì 0 là
        falsy nên bộ lọc bị bỏ qua **im lặng** và API trả về toàn bộ phiếu
        trong phạm vi quyền — người gọi tưởng đang xem một khoản phí.
        """
        r = await client.get(
            "/api/payments?fee_id=0&page_size=100", headers=admin_token_headers
        )
        assert r.status_code == 422, (
            f"fee_id=0 phải bị chặn ở tầng validate, nhận {r.status_code}: {r.text[:200]}"
        )

    async def test_fee_id_khong_ton_tai_tra_rong(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """Khoản phí không có thật → danh sách rỗng, không phải lỗi."""
        r = await client.get(
            "/api/payments?fee_id=99999999&page_size=100", headers=admin_token_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["items"] == []
        assert r.json()["total"] == 0
