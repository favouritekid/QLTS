"""Thứ tự lấy row lock trên đường xác minh / từ chối phiếu thu.

Trước bản vá này, ``verify_payment`` đọc phiếu thu KHÔNG khoá rồi mới khoá
invoice → fee, và chỉ chạm tới hàng payment lúc flush ở cuối.

**Lỗi đang sống trên prod — đó là thứ bộ test này canh:** hai lượt xác minh
song song cùng đọc 'pending', cùng qua phép kiểm trạng thái, rồi cùng cộng
tiền vào invoice và fee. Xác minh đối đầu từ chối hỏng theo đúng cơ chế ấy.

**Chuẩn hoá thứ tự khoá — phòng ngừa, KHÔNG phải lỗi hiện hữu:** khoá payment
trước cũng dựng lại thứ tự batch → payment → invoice → fee cho thống nhất. Với
``void_batch`` hiện tại thì vòng chờ không khép được (xem đoạn dưới), nên đừng
mô tả đây là kẹt chéo đang xảy ra; nó là hàng rào dựng sẵn cho đường void MỘT
phiếu sau này.

Bộ test này chạy trên PostgreSQL thật với **hai AsyncSession độc lập** —
không dùng chung session, không mock ``asyncio.gather``. Chạy chung session
thì hai lượt gọi nằm trong cùng một giao dịch, khoá không bao giờ tranh chấp,
và ca kiểm sẽ xanh kể cả khi bản vá bị gỡ bỏ.

⚠️ Phạm vi: KHÔNG có ca verify-đối-đầu-void ở đây. ``void_batch`` chỉ đảo
phiếu 'verified' thuộc lô đã committed, mà phiếu bulk được tạo thẳng ở trạng
thái 'verified' (payment_import_service: "tạo Payment verified NGAY, không từ
pending") và phiếu không phải 'verified' thì bị **bỏ qua**, không báo lỗi.
Dựng một phiếu vừa 'pending' vừa thuộc lô committed là fixture không tồn tại
trong vòng đời thật. Ca verify-đối-đầu-void-lẻ thuộc về đường void một phiếu
(chưa có), và là cổng bắt buộc của phần đó.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeStatusEnum,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    PaymentMethod,
    PaymentStatusEnum,
    PaymentTransaction,
    TransactionTypeEnum,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.security import get_password_hash
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.services.payment_service import PaymentService
from app.utils.exceptions import BusinessRuleViolation

pytestmark = pytest.mark.asyncio

_AMOUNT = Decimal("1000000")


@pytest_asyncio.fixture
async def committed_pending_payment(
    db: AsyncSession, seeded_dependencies: dict, admin_user
):
    """Một phiếu thu 'pending' đã **commit** — session khác phải nhìn thấy.

    Fixture của các file khác chỉ flush; ở đây bắt buộc commit, vì hai session
    độc lập bên dưới đọc qua kết nối riêng và sẽ không thấy dữ liệu chưa commit.
    """
    method = PaymentMethod(
        code="lockorder_cash", name="Cash", is_online=False, is_active=True
    )
    db.add(method)
    await db.flush()

    lead = models.Lead(
        full_name="Lock Order Student",
        phone="0901440001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id, status="submitted", academic_year=2025, applied_rules={}
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)

    fee, _ = await FeeCalculationService(db).calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.application,
        base_amount=_AMOUNT,
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    invoices, _ = await InvoiceService(db).generate_invoices_for_fee(
        fee_id=fee.id,
        due_date_base=date.today() + timedelta(days=30),
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
        auto_issue=True,
    )
    await db.commit()

    maker = models.User(
        username="lockorder_maker",
        email="lockorder_maker@test.com",
        password_hash=get_password_hash("Maker123!"),
        role="officer",
        status="active",
        full_name="Lock Maker",
        unit_id=seeded_dependencies["unit_id"],
    )
    checker_a = models.User(
        username="lockorder_checker_a",
        email="lockorder_a@test.com",
        password_hash=get_password_hash("Checker123!"),
        role="manager",
        status="active",
        full_name="Lock Checker A",
        unit_id=seeded_dependencies["unit_id"],
    )
    checker_b = models.User(
        username="lockorder_checker_b",
        email="lockorder_b@test.com",
        password_hash=get_password_hash("Checker123!"),
        role="manager",
        status="active",
        full_name="Lock Checker B",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add_all([maker, checker_a, checker_b])
    await db.flush()

    payment, _ = await PaymentService(db).record_manual_payment(
        invoice_id=invoices[0].id,
        method_id=method.id,
        amount=_AMOUNT,
        user_id=maker.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    return {
        "payment_id": payment.id,
        "invoice_id": invoices[0].id,
        "fee_id": fee.id,
        "checker_a_id": checker_a.id,
        "checker_b_id": checker_b.id,
        "unit_id": seeded_dependencies["unit_id"],
    }


async def _verify_in_own_session(payment_id: int, verifier_id: int, unit_id: int):
    """Chạy verify trong session + giao dịch RIÊNG. Trả ('ok'|'err', lỗi)."""
    async with AsyncSessionLocal() as session:
        try:
            await PaymentService(session).verify_payment(
                payment_id=payment_id, verifier_id=verifier_id, unit_id=unit_id
            )
            await session.commit()
            return ("ok", None)
        except Exception as exc:  # noqa: BLE001 — cần giữ nguyên lỗi để assert
            await session.rollback()
            return ("err", exc)


async def _reject_in_own_session(payment_id: int, rejector_id: int, unit_id: int):
    async with AsyncSessionLocal() as session:
        try:
            await PaymentService(session).reject_payment(
                payment_id=payment_id,
                reason="Trùng phiếu, kiểm tra lại",
                rejector_id=rejector_id,
                unit_id=unit_id,
            )
            await session.commit()
            return ("ok", None)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            return ("err", exc)


class TestConcurrentVerify:
    """Hai lần xác minh song song — tiền chỉ được cộng MỘT lần."""

    async def test_two_concurrent_verifies_only_one_wins(
        self, committed_pending_payment
    ):
        ctx = committed_pending_payment

        results = await asyncio.wait_for(
            asyncio.gather(
                _verify_in_own_session(
                    ctx["payment_id"], ctx["checker_a_id"], ctx["unit_id"]
                ),
                _verify_in_own_session(
                    ctx["payment_id"], ctx["checker_b_id"], ctx["unit_id"]
                ),
            ),
            # Kẹt khoá chéo sẽ treo tới hết đời test thay vì báo hỏng; đặt trần
            # để deadlock hiện ra dưới dạng TimeoutError chứ không phải "chạy mãi".
            timeout=60,
        )

        oks = [r for r in results if r[0] == "ok"]
        errs = [r for r in results if r[0] == "err"]
        assert len(oks) == 1, f"phải đúng MỘT lượt thành công, nhận: {results}"
        assert len(errs) == 1

        # Lượt thua phải trượt vì TRẠNG THÁI, không phải vì kẹt khoá hay giao
        # dịch bị DB huỷ. Chỉ đếm "một ok" là chưa đủ: một deadlock cũng cho ra
        # đúng một bên thất bại, và ca kiểm sẽ xanh trong khi hệ đang hỏng.
        loser = errs[0][1]
        assert isinstance(loser, BusinessRuleViolation), (
            f"bên thua phải trượt vì phép kiểm nghiệp vụ, nhận {type(loser).__name__}: "
            f"{loser!r}"
        )
        assert "pending" in str(loser).lower() or "verified" in str(loser).lower(), (
            f"thông báo không nói về tranh chấp trạng thái: {loser!r}"
        )

        async with AsyncSessionLocal() as s:
            fee = await s.get(models.Fee, ctx["fee_id"])
            invoice = await s.get(models.Invoice, ctx["invoice_id"])
            payment = await s.get(models.Payment, ctx["payment_id"])

            # Cốt lõi: tiền cộng ĐÚNG MỘT lần. Bỏ khoá ở verify_payment thì hai
            # ca đều ghi và giá trị ở đây thành 2 × _AMOUNT.
            assert fee.paid_amount == _AMOUNT, (
                f"fee.paid_amount = {fee.paid_amount}, phải là {_AMOUNT} "
                f"(tiền bị cộng hai lần?)"
            )
            assert invoice.paid_amount == _AMOUNT
            assert payment.status == PaymentStatusEnum.verified.value

            # Và đúng MỘT bút toán ghi tiền.
            n_tx = await s.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.payment_id == ctx["payment_id"],
                    PaymentTransaction.transaction_type
                    == TransactionTypeEnum.payment.value,
                )
            )
            assert n_tx == 1, f"có {n_tx} bút toán 'payment', phải đúng 1"

            # Bất biến sổ tiền: tổng bút toán có dấu == fee.paid_amount.
            total = await s.scalar(
                select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                    PaymentTransaction.fee_id == ctx["fee_id"]
                )
            )
            assert Decimal(str(total)) == fee.paid_amount


class TestVerifyVersusReject:
    """Xác minh đối đầu từ chối — đúng một thao tác thắng."""

    async def test_verify_and_reject_exactly_one_wins(
        self, committed_pending_payment
    ):
        ctx = committed_pending_payment

        results = await asyncio.wait_for(
            asyncio.gather(
                _verify_in_own_session(
                    ctx["payment_id"], ctx["checker_a_id"], ctx["unit_id"]
                ),
                _reject_in_own_session(
                    ctx["payment_id"], ctx["checker_b_id"], ctx["unit_id"]
                ),
            ),
            timeout=60,
        )

        oks = [r for r in results if r[0] == "ok"]
        errs = [r for r in results if r[0] == "err"]
        assert len(oks) == 1, f"phải đúng MỘT lượt thành công, nhận: {results}"
        assert len(errs) == 1, f"phải đúng MỘT lượt thất bại, nhận: {results}"

        # Như ca trên: đếm "một ok" thôi thì một lần kẹt khoá hoặc một giao dịch
        # bị DB huỷ cũng đóng vai "bên thua" rất thuyết phục. Đòi đúng loại lỗi
        # nghiệp vụ, và đòi thông báo nói về trạng thái không còn 'pending'.
        loser = errs[0][1]
        assert isinstance(loser, BusinessRuleViolation), (
            f"bên thua phải trượt vì phép kiểm nghiệp vụ, nhận {type(loser).__name__}: "
            f"{loser!r}"
        )
        assert "pending" in str(loser).lower(), (
            f"thông báo phải nói phiếu không còn 'pending': {loser!r}"
        )

        verify_won = results[0][0] == "ok"

        async with AsyncSessionLocal() as s:
            payment = await s.get(models.Payment, ctx["payment_id"])
            fee = await s.get(models.Fee, ctx["fee_id"])

            if verify_won:
                # Xác minh thắng → tiền vào sổ, đúng một lần.
                assert payment.status == PaymentStatusEnum.verified.value
                assert fee.paid_amount == _AMOUNT
            else:
                # Từ chối thắng → KHÔNG đồng nào được ghi.
                assert payment.status == PaymentStatusEnum.rejected.value
                assert fee.paid_amount == Decimal("0")

            # Dù bên nào thắng, sổ tiền vẫn khớp trạng thái.
            total = await s.scalar(
                select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                    PaymentTransaction.fee_id == ctx["fee_id"]
                )
            )
            assert Decimal(str(total)) == fee.paid_amount


class TestLockAcquisitionOrder:
    """Khoá phải xin theo đúng thứ tự payment → invoice → fee.

    Hai ca đồng thời ở trên chứng minh *kết quả* đúng, nhưng không chứng minh
    được *thứ tự*: chúng vẫn xanh nếu ai đó khoá invoice trước rồi payment sau
    — kết quả cuối vẫn một-thắng-một-thua, chỉ là hệ lại mở lại cửa kẹt chéo
    với đường đảo tiền. Ca này canh đúng chỗ đó.
    """

    async def test_payment_locked_before_invoice_and_fee(
        self, db, committed_pending_payment, monkeypatch
    ):
        ctx = committed_pending_payment
        order: list[str] = []

        orig_payment = PaymentRepository.get_for_update
        orig_invoice = InvoiceRepository.get_for_update
        orig_fee = FeeRepository.get_for_update

        async def spy_payment(self, *args, **kwargs):
            order.append("payment")
            return await orig_payment(self, *args, **kwargs)

        async def spy_invoice(self, *args, **kwargs):
            order.append("invoice")
            return await orig_invoice(self, *args, **kwargs)

        async def spy_fee(self, *args, **kwargs):
            order.append("fee")
            return await orig_fee(self, *args, **kwargs)

        monkeypatch.setattr(PaymentRepository, "get_for_update", spy_payment)
        monkeypatch.setattr(InvoiceRepository, "get_for_update", spy_invoice)
        monkeypatch.setattr(FeeRepository, "get_for_update", spy_fee)

        await PaymentService(db).verify_payment(
            payment_id=ctx["payment_id"],
            verifier_id=ctx["checker_a_id"],
            unit_id=ctx["unit_id"],
        )
        await db.commit()

        assert "payment" in order, (
            "verify_payment KHÔNG khoá phiếu thu — đây chính là lỗ cũ: đọc "
            "không khoá thì hai lượt song song cùng cộng tiền"
        )
        assert order.index("payment") < order.index("invoice"), (
            f"phải khoá payment TRƯỚC invoice, thứ tự thực tế: {order}"
        )
        assert order.index("invoice") < order.index("fee"), (
            f"phải khoá invoice TRƯỚC fee, thứ tự thực tế: {order}"
        )

    async def test_reject_locks_payment(
        self, db, committed_pending_payment, monkeypatch
    ):
        """Từ chối không đụng tiền, nên khoá đúng phiếu thu và KHÔNG gì khác.

        Phải theo dõi cả ba repository, không chỉ payment: chỉ spy payment thì
        danh sách ``["payment"]`` không nói được gì về invoice/fee — chúng có
        thể đang bị khoá mà ca kiểm vẫn xanh, và đó chính là thứ cần loại trừ
        (từ chối mà giữ khoá tiền là mở thêm mặt tranh chấp vô ích).
        """
        ctx = committed_pending_payment
        order: list[str] = []

        orig_payment = PaymentRepository.get_for_update
        orig_invoice = InvoiceRepository.get_for_update
        orig_fee = FeeRepository.get_for_update

        async def spy_payment(self, *args, **kwargs):
            order.append("payment")
            return await orig_payment(self, *args, **kwargs)

        async def spy_invoice(self, *args, **kwargs):
            order.append("invoice")
            return await orig_invoice(self, *args, **kwargs)

        async def spy_fee(self, *args, **kwargs):
            order.append("fee")
            return await orig_fee(self, *args, **kwargs)

        monkeypatch.setattr(PaymentRepository, "get_for_update", spy_payment)
        monkeypatch.setattr(InvoiceRepository, "get_for_update", spy_invoice)
        monkeypatch.setattr(FeeRepository, "get_for_update", spy_fee)

        await PaymentService(db).reject_payment(
            payment_id=ctx["payment_id"],
            reason="Nhầm hồ sơ",
            rejector_id=ctx["checker_a_id"],
            unit_id=ctx["unit_id"],
        )
        await db.commit()

        assert order == ["payment"], (
            f"reject_payment phải khoá đúng phiếu thu và không gì khác: {order}"
        )

    async def test_reject_still_reaches_fee_through_relations(
        self, db, committed_pending_payment
    ):
        """Từ chối vẫn dựng được payload thông báo sau khi đổi sang khoá.

        ``get_for_update`` cố ý không joinedload, nên nếu quên bước nạp quan hệ
        thì ``payment.invoice.fee`` ở đoạn dựng payload sẽ lazy-load trong ngữ
        cảnh async và nổ MissingGreenlet. Ca này đi đúng qua đường đó.
        """
        ctx = committed_pending_payment

        payment, post_commit = await PaymentService(db).reject_payment(
            payment_id=ctx["payment_id"],
            reason="Kiểm tra nạp quan hệ",
            rejector_id=ctx["checker_a_id"],
            unit_id=ctx["unit_id"],
        )
        await db.commit()

        assert payment.status == PaymentStatusEnum.rejected.value
        # Chạm thẳng vào quan hệ mà đoạn dựng payload dựa vào.
        assert payment.invoice is not None
        assert payment.invoice.fee is not None
        assert payment.invoice.fee.id == ctx["fee_id"]


# ---------------------------------------------------------------------------
# `InvoiceRepository.khoa_invoice_theo_id` — TẬP khoá và THỨ TỰ khoá
# ---------------------------------------------------------------------------
#
# Ca theo dõi trình tự GỌI helper (`test_overpayment_producer.py`) chỉ chứng
# minh service gọi đúng thứ tự hàm. Nó KHÔNG chạm tới thứ mà quy ước thật sự
# dựa vào: câu SQL khoá đúng những hàng nào. Gỡ `of=Invoice` (khoá kèm
# fee/profile/lead) hay gỡ `ORDER BY id` đều không làm ca ấy đỏ.
#
# Bộ dưới đây hỏi thẳng PostgreSQL bằng `FOR UPDATE NOWAIT`: khoá được ⇒ hàng
# đang rảnh, `55P03` ⇒ hàng đang bị session kia giữ. Không suy đoán qua mock.


async def _thu_khoa_nowait(bang: str, row_id: int) -> bool:
    """True nếu khoá được hàng, False nếu bị session khác giữ (`55P03`).

    Mỗi lượt thử dùng session RIÊNG: `55P03` làm hỏng giao dịch hiện tại, tái
    dùng session sẽ nhận `InFailedSQLTransaction` ở lượt sau và ca kiểm đọc
    thành "vẫn bị khoá" cho MỌI bảng — đúng kiểu xanh/đỏ vì lý do sai.
    """
    async with AsyncSessionLocal() as ss:
        try:
            await ss.execute(
                text(f"SELECT 1 FROM {bang} WHERE id = :i FOR UPDATE NOWAIT"),
                {"i": row_id},
            )
            return True
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate != "55P03":
                raise
            return False
        finally:
            await ss.rollback()


async def _khoa_tap_trong_session_rieng(invoice_ids, unit_id, nha_khoa: asyncio.Event):
    """Gọi `khoa_invoice_theo_id` rồi GIỮ khoá tới khi được bảo nhả."""
    async with AsyncSessionLocal() as ss:
        try:
            await InvoiceRepository(ss).khoa_invoice_theo_id(invoice_ids, unit_id)
            await nha_khoa.wait()
        finally:
            await ss.rollback()


@pytest_asyncio.fixture
async def hai_invoice_committed(committed_pending_payment: dict):
    """Thêm một invoice thứ hai (id LỚN hơn) trên cùng khoản phí, đã commit."""
    async with AsyncSessionLocal() as ss:
        inv2 = Invoice(
            fee_id=committed_pending_payment["fee_id"],
            invoice_number="INV-LOCKSET-2",
            installment_no=2,
            amount=_AMOUNT,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=60),
        )
        ss.add(inv2)
        await ss.commit()
        inv2_id = inv2.id

    ctx = dict(committed_pending_payment)
    ctx["invoice_nho"] = min(committed_pending_payment["invoice_id"], inv2_id)
    ctx["invoice_lon"] = max(committed_pending_payment["invoice_id"], inv2_id)
    return ctx


class TestKhoaInvoiceTheoId:
    """Tập hàng bị khoá, và thứ tự khoá, của pha khoá đầu."""

    async def test_chi_khoa_hang_invoice_khong_keo_fee_profile_lead(
        self, hai_invoice_committed: dict
    ):
        """`FOR UPDATE OF invoice` — khoá đúng invoice, không hơn.

        Đây là cả lý do hàm tồn tại. Câu `FOR UPDATE` trần khoá luôn
        fee/profile/lead theo thứ tự của invoice; dùng nó ở pha đầu là dựng lại
        đúng chu kỳ mà quy ước thứ tự khoá đang gỡ bỏ — và không ca nào ở tầng
        service nhìn thấy điều đó.
        """
        ctx = hai_invoice_committed
        nha_khoa = asyncio.Event()
        giu = asyncio.create_task(
            _khoa_tap_trong_session_rieng(
                [ctx["invoice_nho"], ctx["invoice_lon"]], ctx["unit_id"], nha_khoa
            )
        )
        try:
            # Chờ tới khi khoá thực sự nắm — đo bằng chính hàng invoice.
            for _ in range(80):
                if not await _thu_khoa_nowait("invoice", ctx["invoice_nho"]):
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("pha khoá đầu không giữ được hàng invoice nào")

            assert not await _thu_khoa_nowait("invoice", ctx["invoice_lon"]), (
                "invoice thứ hai KHÔNG bị khoá — pha đầu không cầm trọn tập, "
                "nên vẫn phải xin thêm khoá Invoice ở giữa chừng"
            )

            async with AsyncSessionLocal() as ss:
                fee_id, profile_id, lead_id = (
                    await ss.execute(
                        text(
                            "SELECT f.id, p.id, l.id FROM fee f "
                            "JOIN admission_profile p ON p.id = f.admission_profile_id "
                            "JOIN lead l ON l.id = p.lead_id WHERE f.id = :f"
                        ),
                        {"f": ctx["fee_id"]},
                    )
                ).one()

            assert await _thu_khoa_nowait("fee", fee_id), (
                "hàng fee bị khoá kèm — câu khoá đang là FOR UPDATE trần, "
                "không phải OF invoice"
            )
            assert await _thu_khoa_nowait("admission_profile", profile_id), (
                "hàng admission_profile bị khoá kèm — chính hàng dùng chung này "
                "khép vòng chờ giữa hai lượt áp khoản dư trên cùng hồ sơ"
            )
            assert await _thu_khoa_nowait("lead", lead_id), "hàng lead bị khoá kèm"
        finally:
            nha_khoa.set()
            await giu

    async def test_khoa_theo_id_tang_dan_du_duoc_goi_theo_thu_tu_nguoc(
        self, hai_invoice_committed: dict
    ):
        """Hàng id NHỎ phải bị khoá trước, kể cả khi caller đưa id lớn lên đầu.

        Dựng đúng thế kẹt: một session khác đang giữ hàng id LỚN. Nếu pha khoá
        chạy theo thứ tự tăng dần, nó kịp cầm hàng NHỎ rồi mới chờ ở hàng lớn —
        quan sát được từ session thứ ba. Nếu nó chạy theo thứ tự caller đưa
        (lớn trước), nó chờ ngay và hàng nhỏ còn rảnh.
        """
        ctx = hai_invoice_committed
        nha_khoa = asyncio.Event()

        async with AsyncSessionLocal() as chan:
            await chan.execute(
                text("SELECT 1 FROM invoice WHERE id = :i FOR UPDATE"),
                {"i": ctx["invoice_lon"]},
            )

            giu = asyncio.create_task(
                _khoa_tap_trong_session_rieng(
                    [ctx["invoice_lon"], ctx["invoice_nho"]],  # cố ý đưa NGƯỢC
                    ctx["unit_id"],
                    nha_khoa,
                )
            )
            try:
                for _ in range(80):
                    if not await _thu_khoa_nowait("invoice", ctx["invoice_nho"]):
                        break
                    await asyncio.sleep(0.05)
                else:
                    pytest.fail(
                        "hàng id nhỏ vẫn rảnh trong khi pha khoá đang chờ hàng id "
                        "lớn — khoá KHÔNG đi theo id tăng dần, hai luồng ngược "
                        "chiều sẽ ôm chéo"
                    )
            finally:
                nha_khoa.set()
                await chan.rollback()
                await giu

    async def test_cau_khoa_giu_order_by_id(self, hai_invoice_committed: dict):
        """Lock-in cho `ORDER BY id` ở mức câu lệnh.

        Ca hành vi phía trên chỉ đỏ khi PostgreSQL thực sự đổi thứ tự quét; với
        `IN (a, b)` trên khoá chính, plan thường trả tăng dần **kể cả khi không
        có** `ORDER BY`, nên nó không một mình khoá được mệnh đề ấy. Ca này đọc
        thẳng câu đã gửi xuống driver.
        """
        ctx = hai_invoice_committed
        cau_da_gui: list = []

        async with AsyncSessionLocal() as ss:
            # `AsyncSession.get_bind()` trả về Engine ĐỒNG BỘ bên dưới —
            # `before_cursor_execute` gắn thẳng vào đó.
            sync_engine = ss.get_bind()

            def _ghi(conn, cursor, statement, parameters, context, executemany):
                cau_da_gui.append(statement)

            event.listen(sync_engine, "before_cursor_execute", _ghi)
            try:
                await InvoiceRepository(ss).khoa_invoice_theo_id(
                    [ctx["invoice_lon"], ctx["invoice_nho"]], ctx["unit_id"]
                )
            finally:
                event.remove(sync_engine, "before_cursor_execute", _ghi)
                await ss.rollback()

        khoa = [c for c in cau_da_gui if "FOR UPDATE" in c.upper()]
        assert len(khoa) == 1, (
            f"pha khoá phải gửi đúng MỘT câu FOR UPDATE, đã gửi {len(khoa)}: {khoa}"
        )
        cau = " ".join(khoa[0].split()).upper()
        assert "ORDER BY INVOICE.ID" in cau, (
            "câu khoá không còn ORDER BY id — thứ tự khoá phụ thuộc vào plan, "
            f"không phải vào quy ước. Câu: {cau}"
        )
        assert "FOR UPDATE OF INVOICE" in cau, (
            f"câu khoá không còn giới hạn OF invoice. Câu: {cau}"
        )
