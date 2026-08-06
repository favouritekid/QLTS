# app/repositories/payment_repository.py
"""
Payment Repository - Data access layer for Payment operations.

Security Features:
- IDOR Protection: All queries filter through lead.unit_id
- Maker-Checker Support: Queries for pending verification
- Audit Trail: Payment transaction history

Architecture:
- Extends BaseRepository for common CRUD operations
- Implements custom queries for payment-specific operations
- Supports both online (PaymentIntent) and manual (Payment) flows
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select, and_, or_, func, desc, text
from sqlalchemy import Date, Integer, Numeric
from sqlalchemy import column as sa_column, values as sa_values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.models.finance import (
    Payment,
    PaymentIntent,
    PaymentTransaction,
    RefundRequest,
    OverpaymentRecord,
    Fee,
    Invoice,
    PaymentMethod,
    PaymentStatusEnum,
    PaymentIntentStatusEnum,
    RefundStatusEnum,
    OverpaymentStatusEnum,
)
from app.repositories.base import BaseRepository
from app.utils.datetime_helpers import vn_calendar_date

#: Trần số ứng viên trùng đọc lên. Không phải tối ưu — là hàng rào: người ghi
#: có thể xác nhận rồi tạo bao nhiêu phiếu ``pending`` giống nhau tuỳ ý (phiếu
#: chờ duyệt chưa làm giảm số dư nên không có gì chặn), và lần gửi KHÔNG xác
#: nhận kế tiếp sẽ nạp toàn bộ chúng lên rồi (ở bước sau) đưa hết vào thân lỗi
#: 409. Một thông báo lỗi không có kích thước tối đa là một thông báo lỗi có
#: thể bị dùng làm vũ khí.
MAX_DUPLICATE_CANDIDATES = 20


def _dieu_kien_nghi_trung(fee_id_expr, amount_expr, day_from_expr, day_to_expr):
    """MỘT định nghĩa duy nhất của "hai phiếu có thể là cùng một lần thu".

    Nhận **biểu thức** chứ không phải giá trị, nên dùng được cho cả đường một
    phiếu (giá trị Python) lẫn đường bó nhiều dòng (cột của bảng ``VALUES``).
    Luật nghiệp vụ ở ngay đây và chỉ ở đây — đường nhập lô mà chép lại điều
    kiện thì hai hàng rào sẽ trôi khỏi nhau đúng vào lúc không ai để ý, và
    hàng rào lỏng hơn mới là hàng rào quyết định.

    Ý nghĩa từng vế xem docstring của :meth:`PaymentRepository.find_duplicate_candidates`.
    """
    vn_day = func.date(func.timezone("Asia/Ho_Chi_Minh", Payment.payment_date))

    # Tổng tiền ĐÃ CHI của từng phiếu. Tương quan với hàng Payment bên ngoài
    # nên tính đúng theo từng ứng viên, không cần gom nhóm riêng.
    refunded_total = (
        select(func.coalesce(func.sum(RefundRequest.amount), 0))
        .where(
            RefundRequest.payment_id == Payment.id,
            RefundRequest.status == RefundStatusEnum.refunded.value,
        )
        .correlate(Payment)
        .scalar_subquery()
    )

    return [
        Invoice.fee_id == fee_id_expr,
        Payment.amount == amount_expr,
        Payment.status.in_(
            [
                PaymentStatusEnum.pending.value,
                PaymentStatusEnum.verified.value,
            ]
        ),
        Payment.payment_date.is_not(None),
        vn_day >= day_from_expr,
        vn_day <= day_to_expr,
        refunded_total < Payment.amount,
    ]


class PaymentRepository(BaseRepository[Payment]):
    """Repository for Payment model operations with IDOR protection."""

    def __init__(self, db: AsyncSession):
        """Initialize Payment repository."""
        super().__init__(db, Payment)

    async def get_imported_payment_ids(self, payment_ids: List[int]) -> set:
        """Trả tập con của ``payment_ids`` là các payment do IMPORT tạo (id nằm
        trong ``PaymentImportRow.payment_ids`` JSONB). Dùng cho badge nguồn thu
        ở drawer "Thu học phí".

        An toàn: ``CASE WHEN jsonb_typeof(payment_ids)='array'`` BỌC quanh
        ``jsonb_array_elements_text`` để hàng có ``payment_ids`` scalar/null
        KHÔNG làm unnest 500 (guard ở WHERE không đủ — FROM-LATERAL chạy trước).
        """
        if not payment_ids:
            return set()
        rows = await self.db.execute(
            text(
                "SELECT DISTINCT elem::int AS pid "
                "FROM payment_import_row, "
                "jsonb_array_elements_text("
                "  CASE WHEN jsonb_typeof(payment_ids) = 'array' "
                "       THEN payment_ids ELSE '[]'::jsonb END"
                ") AS elem "
                "WHERE elem ~ '^[0-9]+$' AND elem::int = ANY(:ids)"
            ),
            {"ids": payment_ids},
        )
        return {r[0] for r in rows}

    async def get_by_id_with_relations(
        self,
        payment_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Payment]:
        """
        Get payment by ID with all related data.

        Args:
            payment_id: Payment ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Payment with relations or None
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice).joinedload(Invoice.fee),
                joinedload(Payment.method),
                joinedload(Payment.intent),
                joinedload(Payment.created_by),
                joinedload(Payment.verified_by),
                selectinload(Payment.transactions),
            )
            .where(Payment.id == payment_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        payment_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[Payment]:
        """Get a payment with a pessimistic row lock (SELECT FOR UPDATE).

        Three callers, all serializing writes against the same payment row:

        * refund creation — the second request blocks until the first commits,
          then re-reads the committed-refund total and cannot over-commit;
        * ``verify_payment`` — without the lock two concurrent verifications
          both read 'pending' and both add the amount to invoice/fee, i.e.
          money counted twice. Taking the payment row first ALSO normalises
          lock order (verify used to take invoice → fee and only reach the
          payment row at flush time). That part is preventive, not a live
          fix: today's ``void_batch`` only reverses 'verified' payments while
          verify only accepts 'pending', so the two can never contend for the
          same payment row. A single-payment void would close that cycle;
        * ``reject_payment`` — same reason, so that reject racing verify
          cannot leave two different final states.

        Lock order across the whole system: batch (if any) → payment →
        invoice → fee.

        No nullable joinedloads (FOR UPDATE can't apply to the nullable side of
        an outer join); only the row's own columns are returned. A caller that
        needs relations must hydrate them AFTER the checks pass — see
        ``reject_payment``, which calls ``get_by_id_with_relations`` on the
        already-locked row (the identity map returns the same instance).
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Payment.id == payment_id)
            .with_for_update(of=Payment)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_verified_by_profile(self, profile_id: int) -> List[Payment]:
        """All VERIFIED payments on REFUNDABLE fees of an admission profile.

        Joins Payment→Invoice→Fee, keeps only ``status='verified'`` payments and
        EXCLUDES the non-refundable ``application`` fee (lệ phí xét tuyển). Used
        by the withdraw orchestrator (PR-B) to auto-create a refund request per
        collected tuition payment. No IDOR filter — the caller
        (``withdraw_profile``) has already authorized access to the profile.
        """
        query = (
            select(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .join(Fee, Invoice.fee_id == Fee.id)
            .where(
                Fee.admission_profile_id == profile_id,
                Payment.status == PaymentStatusEnum.verified.value,
                Fee.fee_type != "application",
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_invoice_id(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[Payment]:
        """
        Get all payments for an invoice.

        Args:
            invoice_id: Invoice ID
            unit_id: Filter by lead.unit_id (for IDOR protection)
            status: Optional filter by payment status

        Returns:
            List of payments
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .where(Payment.invoice_id == invoice_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if status is not None:
            query = query.where(Payment.status == status)

        query = query.order_by(Payment.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_pending_verification(
        self,
        unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
        fee_id: Optional[int] = None,
    ) -> Tuple[List[Payment], int]:
        """
        Get payments pending verification (maker-checker workflow).

        Args:
            unit_id: Filter by lead.unit_id (for IDOR protection)
            skip: Number of records to skip
            limit: Maximum records to return
            fee_id: Thu hẹp về MỘT khoản phí (mọi đợt của nó). Ô "đang chờ
                duyệt" ở form ghi tiền phải hỏi đúng câu hỏi mà hàng đợi
                maker-checker trả lời — phiếu TAY chưa duyệt — chứ không phải
                ``status=pending`` chung, vì bộ lọc chung còn trả cả phiếu
                ONLINE đang treo (``intent_id`` khác NULL), thứ kế toán không
                nhập tay và không được tính vào cảnh báo trùng.

        Returns:
            Tuple of (List of pending payments, total_count)
        """
        base_conditions = [
            Payment.status == PaymentStatusEnum.pending.value,
            Payment.intent_id.is_(None),  # Manual payments only
        ]

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # `is not None` chứ KHÔNG phải `if fee_id:` — cùng lý do như
        # get_filtered_with_count: id 0 falsy sẽ bị hiểu thành "không lọc" rồi
        # trả toàn bộ hàng đợi trong phạm vi quyền.
        if fee_id is not None:
            base_conditions.append(Invoice.fee_id == fee_id)

        # Count query
        count_query = (
            select(func.count(Payment.id))
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(and_(*base_conditions))
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                # Load the profile→lead chain too so _build_payment_list_item
                # can read profile_name without a lazy load (MissingGreenlet).
                joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .where(and_(*base_conditions))
            .offset(skip)
            .limit(limit)
            .order_by(Payment.created_at.asc())  # Oldest first
        )

        result = await self.db.execute(data_query)
        payments = list(result.scalars().all())

        return payments, total

    async def find_duplicate_candidates(
        self,
        fee_id: int,
        amount: Decimal,
        payment_date: datetime,
        window_days: int = 3,
        exclude_payment_id: Optional[int] = None,
        limit: int = MAX_DUPLICATE_CANDIDATES,
        unit_id: Optional[int] = None,
    ) -> Tuple[List[Payment], bool]:
        """Phiếu thu đã có mà một khoản thu mới có thể đang lặp lại.

        Luật (chốt ở plan PR B, mục B2):

        * **phạm vi = KHOẢN PHÍ**, mọi hoá đơn của nó — ca ghi nhầm sang đợt
          khác là ca thật, lọc theo ``invoice_id`` sẽ bỏ sót;
        * ``amount`` **bằng nhau** — không có "xấp xỉ", vì thu góp hợp lệ
          thường khác số tiền;
        * lệch **NGÀY LỊCH Việt Nam** không quá ``window_days`` — không phải
          72 giờ. Hai phiếu cùng một ngày làm việc phải dính nhau kể cả khi
          một cái ghi 07:00 và cái kia 16:00, mà chênh giờ thì không nói lên
          điều đó;
        * chỉ ``pending`` và ``verified`` — phiếu đã từ chối/đã đảo không còn
          là tiền, cảnh báo về nó là cảnh báo oan;
        * **không** có luật theo ``reference_code``: dialog prefill mã hồ sơ
          làm tham chiếu, nên mọi lần thu góp của cùng hồ sơ đều trùng mã —
          áp luật đó là bắn cảnh báo vào mọi lần thu thứ hai trở đi, cách
          nhanh nhất khiến kế toán ngừng đọc cảnh báo.

        Phiếu đã **hoàn đủ** bị loại: ``RefundRequest`` cho hoàn một phần, nên
        "có một yêu cầu hoàn đã chi" chưa đủ — hoàn 1 trên 5 triệu thì 4 triệu
        còn lại vẫn là tiền thật và vẫn phải cảnh báo. Chỉ khi tổng đã chi
        ``>=`` số tiền phiếu thì phiếu đó mới hết đóng góp. Dùng ``>=`` (không
        phải ``==``) để fail-safe trước dữ liệu lịch sử bất thường.

        ⚠️ Gọi hàm này **sau** khi đã khoá ``Fee``: nó đọc mọi hoá đơn của
        khoản phí, nên nếu không có điểm gặp chung thì hai request ghi vào hai
        hoá đơn khác nhau cùng thấy "chưa trùng" rồi cùng ghi.

        Thứ tự trả về ổn định (``payment_date`` mới nhất trước, rồi ``id``) để
        danh sách hiện ra không nhảy giữa hai lần gọi.

        Trả ``(ứng_viên, bị_cắt)``. Đọc tối đa ``limit`` dòng và hỏi thêm MỘT
        dòng nữa chỉ để biết có bị cắt hay không — người gọi cần phân biệt
        "đúng 20 phiếu" với "ít nhất 20 phiếu", vì một câu thông báo nói con số
        chính xác trong khi danh sách đã bị cắt là một câu sai.
        """
        # Cùng một quy ước đọc naive với `normalize_to_utc` mà service dùng để
        # dựng giá trị sắp GHI — nếu hai bên đọc khác nhau thì phép so và bản
        # ghi nói hai ngày khác nhau.
        target_day = vn_calendar_date(payment_date)
        day_from = target_day - timedelta(days=window_days)
        day_to = target_day + timedelta(days=window_days)

        conditions = _dieu_kien_nghi_trung(fee_id, amount, day_from, day_to)
        if exclude_payment_id is not None:
            conditions.append(Payment.id != exclude_payment_id)

        query = (
            select(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .options(
                # Nạp sẵn cả chuỗi tới `lead`: đường XEM TRƯỚC dựng
                # `PaymentListItem` (cần `profile_name`, `method_name`,
                # `created_by_name`), và mọi truy cập quan hệ phải xảy ra
                # trong ngữ cảnh async ở đây — chạm tới nó lúc serialize là
                # `MissingGreenlet`. Tối đa 21 dòng nên chi phí không đáng kể.
                joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
            .limit(limit + 1)  # +1 chỉ để biết còn nữa hay không
        )

        # IDOR. Đường gọi từ service đã khoá `Fee` theo `unit_id` nên fee ở đó
        # chắc chắn thuộc phạm vi người gọi; nhưng hàm này còn phục vụ đường
        # ĐỌC (xem trước) nơi `fee_id` đến thẳng từ query string — một số đoán
        # được. Không có điều kiện này thì ai cũng dò được phiếu thu, tên người
        # nộp và mã tham chiếu của đơn vị khác.
        if unit_id is not None:
            query = (
                query.join(Fee, Invoice.fee_id == Fee.id)
                .join(models.AdmissionProfile)
                .join(models.Lead)
            )
            conditions.append(models.Lead.unit_id == unit_id)

        query = query.where(and_(*conditions))

        result = await self.db.execute(query)
        rows = list(result.scalars().unique().all())
        truncated = len(rows) > limit
        return rows[:limit], truncated

    async def find_duplicate_candidates_bulk(
        self,
        keys: Sequence[Tuple[int, int, Decimal, datetime]],
        window_days: int = 3,
        exclude_payment_ids: Optional[Set[int]] = None,
    ) -> Dict[int, List[int]]:
        """Bản BÓ của :meth:`find_duplicate_candidates` cho đường nhập lô.

        ``keys`` là dãy ``(idx, fee_id, amount, payment_date)``; trả về map
        ``idx -> [payment_id…]``. ``idx`` do người gọi đặt (thường là số thứ tự
        dòng trong tệp) vì hai dòng khác nhau có thể trùng cả ba tham số còn
        lại — gộp theo ``(fee, tiền, ngày)`` sẽ làm hai dòng đó dính vào nhau.

        Vì sao không gọi hàm một-phiếu trong vòng lặp: một tệp nhập lô có tới
        vài trăm dòng, mỗi dòng một lượt đi-về cơ sở dữ liệu. Kiến trúc của
        repo này cấm N+1 và đường xem trước đã prefetch mọi thứ khác theo lô.

        Luật so khớp **không** viết lại ở đây — dùng chung
        :func:`_dieu_kien_nghi_trung` với đường một phiếu.

        Không nạp quan hệ: người gọi chỉ cần biết *có trùng hay không* và mấy
        mã phiếu để nêu trong thông báo. Muốn chi tiết đầy đủ (tên người nộp,
        số hoá đơn) thì gọi hàm một-phiếu cho đúng dòng đang xét.
        """
        if not keys:
            return {}

        # Quy đổi ngày ở Python bằng đúng helper mà đường một phiếu dùng, thay
        # vì để Postgres tự diễn giải: naive datetime trong repo này là GIỜ VN,
        # còn cột thì timestamptz — đẩy phép quy đổi xuống SQL là mời thêm một
        # cách đọc thứ hai vào chính chỗ vừa sửa vì lệch ngày.
        rows = [
            {
                "idx": idx,
                "fee_id": fee_id,
                "amount": amount,
                "day_from": vn_calendar_date(pay_date) - timedelta(days=window_days),
                "day_to": vn_calendar_date(pay_date) + timedelta(days=window_days),
            }
            for idx, fee_id, amount, pay_date in keys
        ]

        k = sa_values(
            sa_column("idx", Integer),
            sa_column("fee_id", Integer),
            sa_column("amount", Numeric(15, 2)),
            sa_column("day_from", Date),
            sa_column("day_to", Date),
            name="k",
        ).data(
            [
                (r["idx"], r["fee_id"], r["amount"], r["day_from"], r["day_to"])
                for r in rows
            ]
        )

        conditions = _dieu_kien_nghi_trung(
            k.c.fee_id, k.c.amount, k.c.day_from, k.c.day_to
        )
        if exclude_payment_ids:
            conditions.append(Payment.id.notin_(exclude_payment_ids))

        # Trần tổng: hàng rào chống một tệp bệnh kéo cả bảng lên bộ nhớ. Cắt ở
        # đây làm danh sách của MỘT SỐ dòng ngắn đi, nhưng người gọi chỉ dùng
        # nó để cảnh báo "có trùng" nên cắt bớt mã phiếu không đổi kết luận.
        tran_tong = len(rows) * MAX_DUPLICATE_CANDIDATES

        query = (
            select(k.c.idx, Payment.id)
            .select_from(k)
            .join(Invoice, Invoice.fee_id == k.c.fee_id)
            .join(Payment, Payment.invoice_id == Invoice.id)
            .where(and_(*conditions))
            .order_by(k.c.idx, Payment.id)
            .limit(tran_tong)
        )

        ket_qua: Dict[int, List[int]] = {}
        for idx, payment_id in (await self.db.execute(query)).all():
            ds = ket_qua.setdefault(idx, [])
            if len(ds) < MAX_DUPLICATE_CANDIDATES:
                ds.append(payment_id)
        return ket_qua

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[Payment]:
        """
        Get filtered list of payments with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, invoice_id, method_id)

        Returns:
            List of Payment instances
        """
        query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(Payment.status == filters["status"])

        if filters.get("invoice_id"):
            query = query.where(Payment.invoice_id == filters["invoice_id"])

        if filters.get("method_id"):
            query = query.where(Payment.method_id == filters["method_id"])

        if filters.get("created_by_id"):
            query = query.where(Payment.created_by_id == filters["created_by_id"])

        query = query.order_by(Payment.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        invoice_id: Optional[int] = None,
        method_id: Optional[int] = None,
        fee_id: Optional[int] = None,
    ) -> Tuple[List[Payment], int]:
        """
        Get filtered list of payments with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            statuses: List of statuses to filter
            invoice_id: Filter by invoice ID
            method_id: Filter by payment method ID
            fee_id: Filter by fee — trả phiếu thu của MỌI hoá đơn thuộc khoản
                phí đó, không chỉ một đợt. Cần cho ô "đang chờ duyệt" ở form
                ghi tiền: khoản phí nhiều đợt thì phiếu vừa nhập có thể nằm ở
                hoá đơn khác, lọc theo ``invoice_id`` sẽ không thấy và kế toán
                lại tưởng chưa ai nhập.

        Returns:
            Tuple of (List of Payment instances, total_count)
        """
        base_conditions = []

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses and len(statuses) > 0:
            base_conditions.append(Payment.status.in_(statuses))

        if invoice_id:
            base_conditions.append(Payment.invoice_id == invoice_id)

        if method_id:
            base_conditions.append(Payment.method_id == method_id)

        # Lọc ở mức KHOẢN PHÍ: Invoice đã nằm trong join bên dưới nên không cần
        # thêm bảng. Đi qua Invoice.fee_id chứ không phải Fee.id để tránh phụ
        # thuộc thứ tự join.
        # `is not None` chứ KHÔNG phải `if fee_id:` — id 0 không hợp lệ nhưng
        # nếu ai đó gửi tới đây thì falsy sẽ bị hiểu thành "không lọc" và trả
        # về toàn bộ phiếu trong phạm vi quyền. Router chặn bằng ge=1; đây là
        # lớp thứ hai cho các caller gọi thẳng repository.
        if fee_id is not None:
            base_conditions.append(Invoice.fee_id == fee_id)

        # Count query
        count_query = (
            select(func.count(Payment.id))
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Payment.invoice).joinedload(Invoice.fee).joinedload(
                    Fee.admission_profile
                ).joinedload(models.AdmissionProfile.lead),
                joinedload(Payment.method),
                joinedload(Payment.created_by),
            )
            .offset(skip)
            .limit(limit)
            .order_by(Payment.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        payments = list(result.scalars().all())

        return payments, total

    async def check_self_approval(
        self,
        payment_id: int,
        verifier_id: int
    ) -> bool:
        """
        Check if verifier is trying to approve their own payment.

        Args:
            payment_id: Payment ID
            verifier_id: User ID attempting to verify

        Returns:
            True if self-approval attempt (should be blocked)
        """
        query = (
            select(Payment.created_by_id)
            .where(Payment.id == payment_id)
        )
        result = await self.db.execute(query)
        created_by_id = result.scalar()

        return created_by_id == verifier_id

    async def get_active_payment_methods(
        self,
        is_online: Optional[bool] = None
    ) -> List[PaymentMethod]:
        """
        Get active payment methods, optionally filtered by online/offline.

        Args:
            is_online: Filter by online (True) or offline (False) methods

        Returns:
            List of active PaymentMethod instances
        """
        query = (
            select(PaymentMethod)
            .where(PaymentMethod.is_active.is_(True))
            .order_by(PaymentMethod.display_order)
        )

        if is_online is not None:
            query = query.where(PaymentMethod.is_online == is_online)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_total_refunds_for_payment(
        self,
        payment_id: int,
        statuses: Optional[List[str]] = None,
    ) -> Decimal:
        """
        Get the total refund amount for a payment.

        Mặc định (``statuses=None``) đếm mọi yêu cầu KHÔNG bị từ chối (pending +
        approved + refunded) để các yêu cầu đang mở được *giữ chỗ* trên payment.
        Dùng khi TẠO yêu cầu, ép ``total_committed_refunds <= payment.amount``
        (Finance Phase 1 F2).

        Truyền ``statuses`` để đếm hẹp hơn. Ca thật: lúc CHI
        (``process_approved_refund``) chỉ được trừ phần **đã thực sự ra tiền**
        (``refunded``) — pending/approved chưa chi đồng nào, và chính yêu cầu
        đang xử lý cũng mang trạng thái ``approved`` nên đếm rộng sẽ khiến nó
        tự trừ mình rồi từ chối oan.

        Args:
            payment_id: Payment ID
            statuses: Danh sách trạng thái cần cộng; None = mọi trạng thái
                không phải ``rejected``.

        Returns:
            Tổng số tiền hoàn theo phạm vi trạng thái đã chọn
        """
        status_filter = (
            RefundRequest.status.in_(statuses)
            if statuses is not None
            else RefundRequest.status != RefundStatusEnum.rejected.value
        )
        query = (
            select(func.coalesce(func.sum(RefundRequest.amount), 0))
            .where(
                and_(
                    RefundRequest.payment_id == payment_id,
                    status_filter,
                )
            )
        )
        result = await self.db.execute(query)
        return Decimal(result.scalar() or 0)


class PaymentIntentRepository(BaseRepository[PaymentIntent]):
    """Repository for PaymentIntent model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize PaymentIntent repository."""
        super().__init__(db, PaymentIntent)

    async def get_by_id_with_relations(
        self,
        intent_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by ID with all related data.

        Args:
            intent_id: PaymentIntent ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            PaymentIntent with relations or None
        """
        query = (
            select(PaymentIntent)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentIntent.invoice).joinedload(Invoice.fee),
                joinedload(PaymentIntent.method),
                joinedload(PaymentIntent.payment),
            )
            .where(PaymentIntent.id == intent_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_gateway_ref(
        self,
        gateway_ref: str
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by gateway reference.

        Used for processing gateway callbacks.

        Args:
            gateway_ref: Gateway transaction reference

        Returns:
            PaymentIntent or None
        """
        query = (
            select(PaymentIntent)
            .options(
                joinedload(PaymentIntent.invoice),
                joinedload(PaymentIntent.method),
            )
            .where(PaymentIntent.gateway_ref == gateway_ref)
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        invoice_id: int
    ) -> Optional[PaymentIntent]:
        """
        Get payment intent by idempotency key and invoice.

        Used to prevent duplicate intent creation.

        Args:
            idempotency_key: Client-provided idempotency key
            invoice_id: Invoice ID

        Returns:
            PaymentIntent or None
        """
        query = (
            select(PaymentIntent)
            .where(
                and_(
                    PaymentIntent.idempotency_key == idempotency_key,
                    PaymentIntent.invoice_id == invoice_id
                )
            )
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_expired_intents(
        self,
        before_datetime: Optional[datetime] = None
    ) -> List[PaymentIntent]:
        """
        Get expired payment intents for cleanup.

        Args:
            before_datetime: Consider expired before this time (default: now)

        Returns:
            List of expired intents
        """
        check_time = before_datetime or datetime.now(timezone.utc)

        query = (
            select(PaymentIntent)
            .where(
                and_(
                    PaymentIntent.expires_at < check_time,
                    PaymentIntent.status.in_([
                        PaymentIntentStatusEnum.created.value,
                        PaymentIntentStatusEnum.pending.value
                    ])
                )
            )
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[PaymentIntent]:
        """
        Get filtered list of payment intents with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, invoice_id)

        Returns:
            List of PaymentIntent instances
        """
        query = (
            select(PaymentIntent)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentIntent.invoice),
                joinedload(PaymentIntent.method),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(PaymentIntent.status == filters["status"])

        if filters.get("invoice_id"):
            query = query.where(PaymentIntent.invoice_id == filters["invoice_id"])

        query = query.order_by(PaymentIntent.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())


class RefundRepository(BaseRepository[RefundRequest]):
    """Repository for RefundRequest model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize RefundRequest repository."""
        super().__init__(db, RefundRequest)

    async def get_by_id_with_relations(
        self,
        refund_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[RefundRequest]:
        """
        Get refund request by ID with all related data.

        Args:
            refund_id: RefundRequest ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            RefundRequest with relations or None
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                # Cùng bộ nạp sẵn với ``get_filtered_with_count`` — router dựng
                # CÙNG một response schema từ cả hai đường (list và detail/sau
                # mutation). Lệch bộ options ⇒ list đủ field còn detail thiếu,
                # hoặc tệ hơn: MissingGreenlet khi router chạm quan hệ chưa nạp.
                joinedload(RefundRequest.payment)
                .joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead),
                joinedload(RefundRequest.payment)
                .joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.resolved_major),
                joinedload(RefundRequest.payment).joinedload(Payment.method),
                joinedload(RefundRequest.requested_by),
                joinedload(RefundRequest.approved_by),
                joinedload(RefundRequest.rejected_by),
            )
            .where(RefundRequest.id == refund_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        refund_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[RefundRequest]:
        """Get a refund request with a pessimistic row lock (SELECT FOR UPDATE).

        Used by approve/reject/process so concurrent lifecycle ops on the same
        refund serialize: the second op blocks until the first commits, then
        re-reads the (now-changed) status and is rejected. Locks only the
        refund row (``of=RefundRequest``); payment→invoice are inner-joined and
        eager-loaded so process can update balances without a lazy load.
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment).joinedload(Payment.invoice),
            )
            .where(RefundRequest.id == refund_id)
            .with_for_update(of=RefundRequest)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_pending_approval(
        self,
        unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[RefundRequest], int]:
        """
        Get refund requests pending approval.

        Args:
            unit_id: Filter by lead.unit_id (for IDOR protection)
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (List of pending refunds, total_count)
        """
        base_conditions = [
            RefundRequest.status == RefundStatusEnum.pending.value,
        ]

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # Count query
        count_query = (
            select(func.count(RefundRequest.id))
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(and_(*base_conditions))
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment),
                joinedload(RefundRequest.requested_by),
            )
            .where(and_(*base_conditions))
            .offset(skip)
            .limit(limit)
            .order_by(RefundRequest.requested_at.asc())
        )

        result = await self.db.execute(data_query)
        refunds = list(result.scalars().all())

        return refunds, total

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[RefundRequest]:
        """
        Get filtered list of refund requests with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, payment_id)

        Returns:
            List of RefundRequest instances
        """
        query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(RefundRequest.payment),
                joinedload(RefundRequest.requested_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(RefundRequest.status == filters["status"])

        if filters.get("payment_id"):
            query = query.where(RefundRequest.payment_id == filters["payment_id"])

        query = query.order_by(RefundRequest.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        payment_id: Optional[int] = None,
    ) -> Tuple[List[RefundRequest], int]:
        """Get filtered refund requests with total count and IDOR scope."""
        base_conditions = []

        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses:
            base_conditions.append(RefundRequest.status.in_(statuses))

        if payment_id:
            base_conditions.append(RefundRequest.payment_id == payment_id)

        count_query = (
            select(func.count(RefundRequest.id))
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        data_query = (
            select(RefundRequest)
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                # Chuỗi fee→hồ sơ→lead + ngành + hình thức thu: màn Hoàn phí hiển
                # thị tên học sinh / ngành / phiếu thu gốc ngay trên bảng. Nạp sẵn
                # ở đây (không lazy) vì router dựng response NGOÀI transaction —
                # lazy load sẽ ném MissingGreenlet chứ không âm thầm chậm.
                joinedload(RefundRequest.payment)
                .joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead),
                joinedload(RefundRequest.payment)
                .joinedload(Payment.invoice)
                .joinedload(Invoice.fee)
                .joinedload(Fee.resolved_major),
                joinedload(RefundRequest.payment).joinedload(Payment.method),
                joinedload(RefundRequest.requested_by),
                joinedload(RefundRequest.approved_by),
                joinedload(RefundRequest.rejected_by),
            )
            .offset(skip)
            .limit(limit)
            .order_by(RefundRequest.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        return list(result.scalars().all()), total

    async def get_refunded_totals_for_payments(
        self,
        payment_ids: List[int],
    ) -> dict:
        """Tổng tiền ĐÃ CHI hoàn theo từng phiếu thu — một query cho cả lô.

        Router cần con số này để tính ``refundable`` cho mỗi dòng (số mà
        ``process_approved_refund`` thực sự gác). Gọi lẻ từng dòng sẽ thành N+1
        trên một màn hình 50 dòng.

        Chỉ cộng ``refunded``: ``pending``/``approved`` chưa ra tiền, và cộng chúng
        vào sẽ khiến chính phiếu đang xem tự trừ mình — đúng cái bẫy mà chốt ở
        ``process_approved_refund`` phải tránh.

        Returns:
            ``{payment_id: Decimal}``; phiếu chưa hoàn đồng nào thì KHÔNG có khoá
            (caller dùng ``.get(pid, Decimal("0"))``).
        """
        if not payment_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    RefundRequest.payment_id,
                    func.coalesce(func.sum(RefundRequest.amount), 0),
                )
                .where(
                    RefundRequest.payment_id.in_(payment_ids),
                    RefundRequest.status == RefundStatusEnum.refunded.value,
                )
                .group_by(RefundRequest.payment_id)
            )
        ).all()
        return {pid: Decimal(str(total or 0)) for pid, total in rows}

    async def get_status_summary(
        self,
        unit_id: Optional[int] = None,
        payment_id: Optional[int] = None,
    ) -> dict:
        """Đếm + cộng tiền theo trạng thái trên TOÀN phạm vi người dùng thấy.

        Một query gộp (``GROUP BY status``) thay vì bốn lần đếm. Cùng phép nối +
        cùng bộ lọc IDOR **và cùng bộ lọc ``payment_id``** với
        ``get_filtered_with_count`` — nếu hai bên lệch nhau thì con số ở dải tổng
        quan sẽ mâu thuẫn với chính cái bảng bên dưới nó (lọc theo một phiếu thu mà
        dải vẫn đếm cả đơn vị ⇒ bảng một dòng, dải nói "47 phiếu chờ duyệt").

        Cố ý KHÔNG nhận ``statuses``: dải tổng quan phải nói về mọi trạng thái, kể
        cả trạng thái đang không được chọn — đó là điểm của nó.

        Returns:
            ``{status: {"count": int, "amount": Decimal}}``
        """
        query = (
            select(
                RefundRequest.status,
                func.count(RefundRequest.id),
                func.coalesce(func.sum(RefundRequest.amount), 0),
            )
            .join(Payment)
            .join(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .group_by(RefundRequest.status)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)
        if payment_id:
            query = query.where(RefundRequest.payment_id == payment_id)

        rows = (await self.db.execute(query)).all()
        return {
            status: {"count": count, "amount": Decimal(str(amount or 0))}
            for status, count, amount in rows
        }


class OverpaymentRepository(BaseRepository[OverpaymentRecord]):
    """Repository for OverpaymentRecord model operations."""

    def __init__(self, db: AsyncSession):
        """Initialize OverpaymentRecord repository."""
        super().__init__(db, OverpaymentRecord)

    async def get_by_id_with_relations(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[OverpaymentRecord]:
        """Get overpayment by ID with all related data and IDOR scope."""
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice).joinedload(Invoice.fee),
                joinedload(OverpaymentRecord.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
                joinedload(OverpaymentRecord.resolved_by),
                joinedload(OverpaymentRecord.applied_to_invoice),
                joinedload(OverpaymentRecord.refund_request),
            )
            .where(OverpaymentRecord.id == overpayment_id)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_for_update(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[OverpaymentRecord]:
        """Get an overpayment with a pessimistic row lock (SELECT FOR UPDATE).

        Used by every resolution path (apply/refund/write-off) so two concurrent
        requests cannot both pass the pending check and double-resolve the same
        liability (Finance Phase 1 F6). No nullable joinedloads here — FOR UPDATE
        cannot be applied to the nullable side of an outer join; relations are
        re-fetched separately by the service.
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(OverpaymentRecord.id == overpayment_id)
            .with_for_update(of=OverpaymentRecord)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_pending_for_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None
    ) -> List[OverpaymentRecord]:
        """
        Get pending overpayments for an admission profile.

        Args:
            profile_id: Admission profile ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            List of pending overpayment records
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice),
            )
            .where(
                and_(
                    OverpaymentRecord.admission_profile_id == profile_id,
                    OverpaymentRecord.status == OverpaymentStatusEnum.pending.value
                )
            )
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[OverpaymentRecord]:
        """
        Get filtered list of overpayment records with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, profile_id)

        Returns:
            List of OverpaymentRecord instances
        """
        query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(OverpaymentRecord.status == filters["status"])

        if filters.get("profile_id"):
            query = query.where(
                OverpaymentRecord.admission_profile_id == filters["profile_id"]
            )

        query = query.order_by(OverpaymentRecord.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        profile_id: Optional[int] = None,
    ) -> Tuple[List[OverpaymentRecord], int]:
        """Get filtered overpayments with total count and IDOR scope."""
        base_conditions = []

        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses:
            base_conditions.append(OverpaymentRecord.status.in_(statuses))

        if profile_id:
            base_conditions.append(OverpaymentRecord.admission_profile_id == profile_id)

        count_query = (
            select(func.count(OverpaymentRecord.id))
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        data_query = (
            select(OverpaymentRecord)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(OverpaymentRecord.payment),
                joinedload(OverpaymentRecord.invoice).joinedload(Invoice.fee),
                joinedload(OverpaymentRecord.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
                joinedload(OverpaymentRecord.resolved_by),
                joinedload(OverpaymentRecord.applied_to_invoice),
                joinedload(OverpaymentRecord.refund_request),
            )
            .offset(skip)
            .limit(limit)
            .order_by(OverpaymentRecord.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        return list(result.scalars().all()), total


class PaymentTransactionRepository(BaseRepository[PaymentTransaction]):
    """Repository for PaymentTransaction model operations (audit trail)."""

    def __init__(self, db: AsyncSession):
        """Initialize PaymentTransaction repository."""
        super().__init__(db, PaymentTransaction)

    async def get_by_fee_id(
        self,
        fee_id: int,
        unit_id: Optional[int] = None
    ) -> List[PaymentTransaction]:
        """
        Get all transactions for a fee (audit trail).

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            List of transactions ordered by created_at
        """
        query = (
            select(PaymentTransaction)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentTransaction.payment),
                joinedload(PaymentTransaction.performed_by),
            )
            .where(PaymentTransaction.fee_id == fee_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        query = query.order_by(PaymentTransaction.created_at)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[PaymentTransaction]:
        """
        Get filtered list of transactions with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (fee_id, transaction_type, period_id)

        Returns:
            List of PaymentTransaction instances
        """
        query = (
            select(PaymentTransaction)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(PaymentTransaction.payment),
                joinedload(PaymentTransaction.performed_by),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("fee_id"):
            query = query.where(PaymentTransaction.fee_id == filters["fee_id"])

        if filters.get("transaction_type"):
            query = query.where(
                PaymentTransaction.transaction_type == filters["transaction_type"]
            )

        if filters.get("period_id"):
            query = query.where(PaymentTransaction.period_id == filters["period_id"])

        query = query.order_by(PaymentTransaction.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())
