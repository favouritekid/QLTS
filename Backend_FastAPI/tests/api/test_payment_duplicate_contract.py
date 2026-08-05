"""Hợp đồng JSON của lỗi 409 "nghi trùng phiếu thu" — qua ASGI THẬT.

Vì sao phải đi qua app thật thay vì gọi thẳng handler: một handler đăng ký sai
chỗ (ví dụ trong ``lifespan``) vẫn chạy đúng khi được gọi trực tiếp, nên unit
test sẽ xanh trong khi client thật nhận về một thân lỗi khác hẳn. Bài học đó
đã trả giá một lần rồi (memory ``handler-wiring-needs-real-stack-test``).

Thân của một lỗi không đi qua ``response_model`` nào cả — không có ai rà hộ.
Nên ở đây khoá **exact JSON**: đúng tập khoá, đúng KIỂU (số tiền là chuỗi,
ngày là ISO hoặc null), và không có gì thừa lọt ra.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
)
from app.repositories.payment_repository import MAX_DUPLICATE_CANDIDATES
from app.security import get_password_hash
from app.services.fee_calculation_service import FeeCalculationService
from app.services.payment_service import PaymentService

pytestmark = pytest.mark.asyncio

_HALF = Decimal("1000000")
_WHEN = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)  # 10:00 giờ VN

KHOA_HOP_DONG = {"payment_id", "amount", "payment_date", "status", "invoice_number"}


@pytest_asyncio.fixture
async def fee_with_one_payment(seed_lead_dependencies: dict, admin_user_in_db: dict):
    """Một khoản phí, hai đợt, và MỘT phiếu đã ghi ở đợt 1.

    ``tests/api/`` không có fixture ``db`` — tự mở session và **commit**, vì
    client gọi API qua session khác.
    """
    seeded = seed_lead_dependencies
    admin_id = admin_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="dupcontract_cash", name="Cash", is_online=False, is_active=True
        )
        db.add(method)

        maker = models.User(
            username="dupcontract_maker",
            email="dupcontract_maker@test.com",
            password_hash=get_password_hash("Maker123!"),
            role="officer",
            status="active",
            full_name="Dup Contract Maker",
            unit_id=seeded["unit_id"],
        )
        db.add(maker)
        await db.flush()

        lead = models.Lead(
            full_name="Dup Contract Student",
            phone="0901770001",
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

        fee, _ = await FeeCalculationService(db).calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=_HALF * 2,
            academic_year=2025,
            user_id=admin_id,
            unit_id=seeded["unit_id"],
        )
        await db.flush()

        invoices = []
        for idx in (1, 2):
            inv = Invoice(
                fee_id=fee.id,
                invoice_number=f"INV-DUPCONTRACT-{idx}",
                installment_no=idx,
                amount=_HALF,
                status=InvoiceStatusEnum.issued.value,
                due_date=date.today() + timedelta(days=30 * idx),
            )
            db.add(inv)
            invoices.append(inv)
        await db.commit()

        cu, _ = await PaymentService(db).record_manual_payment(
            invoice_id=invoices[0].id,
            method_id=method.id,
            amount=_HALF,
            user_id=maker.id,
            unit_id=seeded["unit_id"],
            payment_date=_WHEN,
        )
        await db.commit()

        return {
            "fee_id": fee.id,
            "invoice_ids": [i.id for i in invoices],
            "method_id": method.id,
            "maker_id": maker.id,
            "phieu_cu_id": cu.id,
            "so_hoa_don_cu": invoices[0].invoice_number,
        }


def _body(ctx: dict, *, invoice_idx: int = 1, confirm: bool | None = None):
    body = {
        "invoice_id": ctx["invoice_ids"][invoice_idx],
        "method_id": ctx["method_id"],
        "amount": "1000000",
        "payment_date": "2026-08-05T03:00:00+00:00",
    }
    if confirm is not None:
        body["confirm_duplicate"] = confirm
    return body


async def _dem_payment(fee_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count(Payment.id))
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .where(Invoice.fee_id == fee_id)
            )
        ).scalar() or 0


class TestHopDong409:
    async def test_than_loi_dung_hop_dong_va_dung_kieu(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        ctx = fee_with_one_payment
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        body = r.json()

        assert set(body.keys()) == {
            "detail",
            "error_code",
            "duplicates",
            "duplicates_truncated",
        }, f"khoá lạ trong thân lỗi: {sorted(body.keys())}"
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["error_code"] == "PAYMENT_DUPLICATE_SUSPECTED"
        assert body["duplicates_truncated"] is False

        assert len(body["duplicates"]) == 1
        d = body["duplicates"][0]
        assert set(d.keys()) == KHOA_HOP_DONG, f"khoá lạ: {sorted(d.keys())}"
        assert d["payment_id"] == ctx["phieu_cu_id"]
        # Số tiền là CHUỖI — khớp quy ước Decimal→string của giao diện và
        # không mất chính xác qua JSON number.
        assert isinstance(d["amount"], str), type(d["amount"])
        assert Decimal(d["amount"]) == _HALF
        # Ngày là ISO-8601, đọc lại được — không phải một chuỗi tuỳ hứng.
        assert isinstance(d["payment_date"], str)
        assert datetime.fromisoformat(d["payment_date"]) == _WHEN
        assert d["status"] == "pending"
        assert d["invoice_number"] == ctx["so_hoa_don_cu"]

    async def test_409_khong_sinh_them_phieu(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Cảnh báo phải là TỪ CHỐI, không phải ghi xong rồi mới kêu."""
        ctx = fee_with_one_payment
        truoc = await _dem_payment(ctx["fee_id"])
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        assert await _dem_payment(ctx["fee_id"]) == truoc

    async def test_khong_ro_context_noi_bo(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """``context`` là chỗ chứa dữ liệu debug — không được đi ra."""
        ctx = fee_with_one_payment
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        body = r.json()
        assert "context" not in body
        # Vài trường của Payment cố tình nằm NGOÀI danh sách trắng.
        for cam in ("created_by_id", "notes", "payer_account", "invoice_id"):
            assert cam not in body["duplicates"][0], cam

    async def test_xac_nhan_thi_ghi_duoc_201(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Khoá TOÀN chuỗi router → service của cờ xác nhận.

        Thiếu một mắt (schema, router, chữ ký service) thì cờ không tới nơi và
        ca này trả 409 — đúng cái lỗi "nối thiếu một mắt" mà plan cảnh báo.
        """
        ctx = fee_with_one_payment
        r = await client.post(
            "/api/payments",
            json=_body(ctx, confirm=True),
            headers=admin_token_headers,
        )
        assert r.status_code == 201, r.text

    async def test_khong_xac_nhan_mac_dinh_la_chan(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Bỏ hẳn khoá ``confirm_duplicate`` ⇒ mặc định False ⇒ vẫn chặn.

        Fail-closed: một client cũ không biết cờ này vẫn được bảo vệ.
        """
        ctx = fee_with_one_payment
        body = _body(ctx)
        assert "confirm_duplicate" not in body
        r = await client.post("/api/payments", json=body, headers=admin_token_headers)
        assert r.status_code == 409, r.text


class TestPayloadKhongDeGhiDe:
    """``public_payload`` là dữ liệu, không phải quyền ghi đè hợp đồng."""

    async def test_payload_khong_ghi_de_duoc_detail_va_error_code(self):
        """Client rẽ nhánh theo ``error_code`` — nó phải do máy chủ quyết.

        Nếu payload thắng, một lỗi mang khoá trùng tên sẽ đổi được mã lỗi mà
        giao diện dùng để phân biệt "nghi trùng" với mọi lỗi 409 khác.
        """
        from fastapi import Request

        from app.middleware.exception_handlers import base_app_exception_handler
        from app.utils.exceptions import PaymentDuplicateSuspected

        exc = PaymentDuplicateSuspected("thật", duplicates=[])
        exc.public_payload["detail"] = "giả"
        exc.public_payload["error_code"] = "GIA_MAO"

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/payments",
            "headers": [],
            "query_string": b"",
        }
        resp = await base_app_exception_handler(Request(scope), exc)
        import json

        body = json.loads(resp.body)
        assert body["detail"] == "thật"
        assert body["error_code"] == "PAYMENT_DUPLICATE_SUSPECTED"

    async def test_hai_lan_nem_khong_dung_chung_payload(self):
        """Payload phải riêng theo từng instance.

        Đặt mặc định ở cấp lớp là chia sẻ MỘT dict cho mọi lần ném — hai lỗi
        liên tiếp đắp dữ liệu của nhau, và người dùng thứ hai nhìn thấy danh
        sách phiếu của người thứ nhất.
        """
        from app.utils.exceptions import PaymentDuplicateSuspected

        a = PaymentDuplicateSuspected("a", duplicates=[{"payment_id": 1}])
        b = PaymentDuplicateSuspected("b", duplicates=[])

        assert a.public_payload["duplicates"] == [{"payment_id": 1}]
        assert b.public_payload["duplicates"] == []
        assert a.public_payload is not b.public_payload

    async def test_lỗi_thuong_khong_co_payload_cong_khai(self):
        """Mặc định là RỖNG — fail-closed.

        Một lỗi không chủ động khai báo dữ liệu công khai thì không được vô
        tình mang gì ra ngoài.
        """
        from app.utils.exceptions import ConflictError

        assert ConflictError("x").public_payload == {}


class TestCatDanhSachTrongThanLoi:
    async def test_toi_da_20_phan_tu_va_co_co_bao_bi_cat(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Thân lỗi phải có kích thước hữu hạn.

        Xác nhận trùng là hợp lệ và phiếu chờ duyệt chưa giảm số dư, nên số
        phiếu giống nhau có thể tăng không giới hạn. Một thông báo lỗi không
        có trần là một thông báo lỗi có thể bị dùng làm vũ khí.
        """
        ctx = fee_with_one_payment
        # Đã có 1 phiếu từ fixture; thêm 20 nữa (xác nhận trùng) → 21.
        for _ in range(MAX_DUPLICATE_CANDIDATES):
            r = await client.post(
                "/api/payments",
                json=_body(ctx, confirm=True),
                headers=admin_token_headers,
            )
            assert r.status_code == 201, r.text

        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        body = r.json()
        assert len(body["duplicates"]) == MAX_DUPLICATE_CANDIDATES
        assert body["duplicates_truncated"] is True
        # Bị cắt thì câu chữ không được tuyên bố con số.
        assert "20" not in body["detail"], body["detail"]
