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

from datetime import date, datetime, timedelta, timezone
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
    Payment,
    PaymentIntent,
    PaymentMethod,
)
from app.security import get_password_hash
from app.services.fee_calculation_service import FeeCalculationService
from app.utils.exceptions import PaymentDuplicateSuspected
from app.services.payment_service import PaymentService
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import get_auth_headers

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
            # Fixture này CỐ Ý dựng hai phiếu cùng số tiền trên hai đợt của
            # cùng một khoản phí — đúng hình dạng mà hàng rào chống trùng chặn
            # lại. Ở đây ta đang dựng dữ liệu cho bài kiểm bộ LỌC, không kiểm
            # hàng rào, nên đi trọn vòng xác nhận: bấm gửi, bị chặn thì lấy
            # PHIẾU từ chính phản hồi rồi gửi lại. Việc phải làm vậy chính là
            # bằng chứng hàng rào đang chạy trên đường thật; luật của nó được
            # canh ở `tests/services/test_payment_duplicate_guard.py`.
            tham_so = dict(
                invoice_id=inv.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                user_id=maker.id,
                unit_id=seeded["unit_id"],
            )
            try:
                p, _ = await svc.record_manual_payment(**tham_so)
            except PaymentDuplicateSuspected as exc:
                # Không rollback: hàng rào từ chối trước khi ghi gì, phiên vẫn
                # sạch — và rollback sẽ xoá luôn phiếu của vòng lặp trước.
                p, _ = await svc.record_manual_payment(
                    **tham_so, review_token=exc.public_payload["review_token"]
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


@pytest_asyncio.fixture
async def online_pending_on_fee_a(two_fees_ctx: dict, admin_user_in_db: dict):
    """Thêm vào khoản phí A một phiếu ONLINE đang treo (``intent_id`` khác NULL).

    Đây là con dao phân biệt hai hợp đồng nghiệp vụ mà FE dễ nhầm:
    ``status=pending`` trả về MỌI phiếu chờ — kể cả phiếu online do người học
    tự bấm thanh toán rồi bỏ dở — còn hàng đợi maker-checker
    (``pending_manual_only``) chỉ trả phiếu TAY. Ô "đang chờ duyệt" ở form ghi
    tiền nói về việc *kế toán đã nhập mà chưa ai duyệt*, nên đếm nhầm phiếu
    online vào đó là dựng cảnh báo trên dữ liệu sai loại.
    """
    ctx = dict(two_fees_ctx)
    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="listfilter_gw", name="Gateway", is_online=True, is_active=True
        )
        db.add(method)
        await db.flush()

        intent = PaymentIntent(
            invoice_id=ctx["inv_a_ids"][0],
            method_id=method.id,
            amount=Decimal("300000"),
            idempotency_key="listfilter-intent-1",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(intent)
        await db.flush()

        online = Payment(
            invoice_id=ctx["inv_a_ids"][0],
            method_id=method.id,
            intent_id=intent.id,
            amount=Decimal("300000"),
            status="pending",
            created_by_id=admin_user_in_db["id"],
        )
        db.add(online)
        await db.flush()
        ctx["online_pay_id"] = online.id
        await db.commit()

    return ctx


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

    async def test_fee_id_vuot_tran_int4_bi_tu_choi_khong_phai_500(
        self, client: AsyncClient, admin_token_headers: dict, two_fees_ctx
    ):
        """Số lớn hơn 2^31-1 phải bị chặn ở tầng validate.

        Không có ``le`` thì Pydantic cho qua (int Python vô hạn) và câu lệnh
        vỡ dưới PostgreSQL với "integer out of range" — người gọi nhận **500**
        cho một đầu vào đáng lẽ là 422, kèm một traceback trong log lỗi.
        """
        r = await client.get(
            "/api/payments?fee_id=2147483648&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 422, (
            f"fee_id vượt trần INT4 phải là 422, nhận {r.status_code}: {r.text[:300]}"
        )

    async def test_fee_id_don_vi_khac_tra_rong_khong_ro_ton_tai(
        self,
        client: AsyncClient,
        manager_other_unit_user_in_db: dict,
        two_fees_ctx,
    ):
        """IDOR: manager đơn vị khác hỏi đúng ``fee_id`` thật → rỗng.

        Bộ lọc mới không được trở thành cửa sau: ``fee_id`` là số đoán được,
        nên nếu điều kiện đơn vị bị bỏ thì bất kỳ ai cũng dò được phiếu thu và
        tên người nộp của đơn vị khác.
        """
        headers = await get_auth_headers(
            client, manager_other_unit_user_in_db, AuthURLs.LOGIN
        )
        r = await client.get(
            f"/api/payments?fee_id={two_fees_ctx['fee_a_id']}&page_size=100",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == [], f"rò phiếu sang đơn vị khác: {body['items']}"
        assert body["total"] == 0


class TestPendingManualOnlyByFee:
    """Hàng đợi maker-checker của MỘT khoản phí — nguồn cho ô 'đang chờ duyệt'.

    Ô đó phải trả lời đúng câu "kế toán đã nhập gì mà chưa ai duyệt", nên nó
    phải hỏi hàng đợi maker-checker chứ không phải ``status=pending`` chung.
    """

    async def test_loai_phieu_online_khoi_o_cho_duyet(
        self, client: AsyncClient, admin_token_headers: dict, online_pending_on_fee_a
    ):
        ctx = online_pending_on_fee_a
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_a_id']}&pending_manual_only=true"
            "&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = sorted(item["id"] for item in r.json()["items"])

        assert ids == ctx["pay_a_ids"], (
            f"phải đúng hai phiếu TAY {ctx['pay_a_ids']}, nhận {ids}"
        )
        assert ctx["online_pay_id"] not in ids, (
            "phiếu ONLINE đang treo lọt vào ô 'đang chờ duyệt' — kế toán sẽ "
            "thấy một khoản mình chưa từng nhập"
        )

    async def test_status_pending_van_lot_phieu_online(
        self, client: AsyncClient, admin_token_headers: dict, online_pending_on_fee_a
    ):
        """Đối chứng — vì sao không được dùng ``status=pending`` cho ô đó.

        Ca này khoá sự KHÁC BIỆT giữa hai đường. Nếu nó đỏ thì hoặc
        ``status=pending`` đã âm thầm đổi nghĩa, hoặc hai bộ lọc đã trùng nhau
        và cái tên ``pending_manual_only`` không còn bảo đảm điều nó hứa.
        """
        ctx = online_pending_on_fee_a
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_a_id']}&status=pending&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}

        assert ctx["online_pay_id"] in ids, (
            "status=pending phải trả CẢ phiếu online — đó chính là lý do ô "
            "'đang chờ duyệt' không được dùng bộ lọc này"
        )

    async def test_khong_ro_sang_khoan_phi_khac(
        self, client: AsyncClient, admin_token_headers: dict, online_pending_on_fee_a
    ):
        """``fee_id`` phải được AND vào hàng đợi, không bị bỏ qua.

        Ca quyết định: nếu nhánh ``pending_manual_only`` phớt lờ ``fee_id``
        (như bản đầu) thì nó trả toàn bộ hàng đợi trong phạm vi quyền — phiếu
        của khoản phí B lọt vào và bảng công nợ của hồ sơ A cộng cả tiền của
        người khác.
        """
        ctx = online_pending_on_fee_a
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_b_id']}&pending_manual_only=true"
            "&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]

        assert ids == [ctx["pay_b_id"]], (
            f"chỉ được thấy phiếu của khoản phí B, nhận {ids}"
        )
        assert r.json()["total"] == 1, (
            f"total cũng phải bị lọc theo fee, nhận {r.json()['total']}"
        )

    async def test_khong_truyen_fee_id_thi_hang_doi_giu_nguyen_hanh_vi_cu(
        self, client: AsyncClient, admin_token_headers: dict, online_pending_on_fee_a
    ):
        """Tab 'Chờ duyệt' của workspace không truyền fee_id — không được đổi."""
        ctx = online_pending_on_fee_a
        r = await client.get(
            "/api/payments?pending_manual_only=true&page_size=100",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}

        assert set(ctx["pay_a_ids"]).issubset(ids)
        assert ctx["pay_b_id"] in ids
        assert ctx["online_pay_id"] not in ids
