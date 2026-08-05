"""Hàng rào MỀM chống ghi trùng phiếu thu (PR B — B2).

Prod có 9 phiếu nghi trùng. Nguyên nhân không phải bất cẩn mà là màn hình nói
dối: ``fee.paid_amount`` chỉ tăng khi phiếu được DUYỆT, nên sau lần nhập đầu
mà chưa ai duyệt thì mọi màn hình hiện y như chưa thu. B1 đã chữa phần hiển
thị; đây là lớp thứ hai, ở phía máy chủ, cho những lần vẫn lọt qua.

**Mềm, không cứng.** Nộp hai lần cùng số tiền là chuyện có thật, nên phát hiện
trùng chỉ dừng lại và hỏi; người ghi xác nhận rồi gửi lại là ghi được. Một
hàng rào cứng ở đây sẽ chặn nghiệp vụ hợp lệ và bị vô hiệu hoá bằng cách khác.

Ba điều dễ làm sai mà bộ test này khoá lại:

* **quét theo KHOẢN PHÍ, không theo hoá đơn** — ca ghi nhầm sang đợt khác là ca
  thật (``test_phieu_o_dot_khac_cung_khoan_phi_van_dinh``);
* **lệch NGÀY LỊCH Việt Nam, không phải 72 giờ** — có ca vắt qua nửa đêm để
  phân biệt hai cách tính (``test_bien_ngay_lich_vn_khong_phai_gio_utc``);
* **không có luật theo mã tham chiếu** — dialog prefill mã hồ sơ nên mọi lần
  thu góp của cùng hồ sơ đều trùng mã; áp luật đó là bắn cảnh báo vào mọi lần
  thu thứ hai trở đi (``test_cung_ma_tham_chieu_khac_so_tien_khong_canh_bao``).
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
    PaymentStatusEnum,
    RefundRequest,
    RefundStatusEnum,
)
from app.repositories.payment_repository import (
    MAX_DUPLICATE_CANDIDATES,
    PaymentRepository,
)
from app.security import get_password_hash
from app.services.fee_calculation_service import FeeCalculationService
from app.services.payment_service import PaymentService
from app.utils.datetime_helpers import vn_calendar_date
from app.utils.exceptions import PaymentDuplicateSuspected

pytestmark = pytest.mark.asyncio

_HALF = Decimal("1000000")
_TOTAL = _HALF * 2
# Mốc cố định để các phép tính ngày không phụ thuộc lúc chạy test.
_BASE = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)  # 10:00 giờ VN


@pytest_asyncio.fixture
async def fee_two_invoices(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Một khoản phí → HAI hoá đơn (hai đợt) + một người ghi phiếu.

    Hai đợt là điều kiện cần để kiểm được điều quan trọng nhất: phạm vi dò
    trùng phải là khoản phí, không phải một hoá đơn.
    """
    method = PaymentMethod(
        code="dupguard_cash", name="Cash", is_online=False, is_active=True
    )
    db.add(method)
    await db.flush()

    lead = models.Lead(
        full_name="Dup Guard Student",
        phone="0901660001",
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
        base_amount=_TOTAL,
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.flush()

    # Hai đợt, tạo thẳng: `generate_invoices_for_fee` chỉ sinh MỘT hoá đơn khi
    # khoản phí không gắn kế hoạch trả góp, mà điều kiện cần của bộ test này
    # là hai hoá đơn cùng một khoản phí.
    invoices = []
    for idx in (1, 2):
        inv = Invoice(
            fee_id=fee.id,
            invoice_number=f"INV-DUPGUARD-{idx}",
            installment_no=idx,
            amount=_HALF,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30 * idx),
        )
        db.add(inv)
        invoices.append(inv)
    await db.flush()

    maker = models.User(
        username="dupguard_maker",
        email="dupguard_maker@test.com",
        password_hash=get_password_hash("Maker123!"),
        role="officer",
        status="active",
        full_name="Dup Guard Maker",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(maker)
    await db.flush()
    await db.commit()

    return {
        "fee_id": fee.id,
        "invoice_ids": [i.id for i in invoices],
        "method_id": method.id,
        "maker_id": maker.id,
        "unit_id": seeded_dependencies["unit_id"],
    }


async def _ghi(
    db: AsyncSession,
    ctx: dict,
    *,
    invoice_idx: int = 0,
    amount: Decimal = _HALF,
    when: datetime = _BASE,
    reference: str | None = None,
    confirm: bool = False,
):
    payment, _ = await PaymentService(db).record_manual_payment(
        invoice_id=ctx["invoice_ids"][invoice_idx],
        method_id=ctx["method_id"],
        amount=amount,
        user_id=ctx["maker_id"],
        unit_id=ctx["unit_id"],
        payment_date=when,
        reference_code=reference,
        confirm_duplicate=confirm,
    )
    await db.flush()
    return payment


class TestLuatDoTrung:
    async def test_cung_tien_cach_mot_ngay_bi_chan(
        self, db: AsyncSession, fee_two_invoices
    ):
        await _ghi(db, fee_two_invoices)
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, when=_BASE + timedelta(days=1))

    async def test_bien_dung_ba_ngay_van_dinh(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Biên trên phải NẰM TRONG. Viết `< 3` thay vì `<= 3` là lọt ca này."""
        await _ghi(db, fee_two_invoices)
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, when=_BASE + timedelta(days=3))

    async def test_qua_ba_ngay_thi_thoi(self, db: AsyncSession, fee_two_invoices):
        await _ghi(db, fee_two_invoices)
        p = await _ghi(db, fee_two_invoices, when=_BASE + timedelta(days=4))
        assert p.id is not None

    async def test_bien_ngay_lich_vn_khong_phai_gio_utc(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Ca vắt qua nửa đêm — chỗ hai cách tính cho hai kết quả khác nhau.

        Phiếu cũ 05/08 18:00Z = **06/08** 01:00 giờ VN.
        Phiếu mới 09/08 02:00Z = **09/08** 09:00 giờ VN.
        Lệch theo NGÀY LỊCH VN = 3 ⇒ phải dính.
        Lệch theo giờ = 3 ngày 8 giờ, và lệch theo ngày UTC = 4 ⇒ nếu ai đó so
        bằng 72 giờ hoặc bằng ngày UTC thì ca này lọt.
        """
        await _ghi(
            db,
            fee_two_invoices,
            when=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(
                db,
                fee_two_invoices,
                when=datetime(2026, 8, 9, 2, 0, tzinfo=timezone.utc),
            )

    async def test_khac_so_tien_khong_canh_bao(
        self, db: AsyncSession, fee_two_invoices
    ):
        await _ghi(db, fee_two_invoices)
        p = await _ghi(db, fee_two_invoices, amount=Decimal("500000"))
        assert p.id is not None

    async def test_phieu_o_dot_khac_cung_khoan_phi_van_dinh(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Lý do phạm vi là KHOẢN PHÍ chứ không phải hoá đơn.

        Ghi nhầm sang đợt khác là ca thật. Nếu quét theo ``invoice_id`` thì
        phiếu ở đợt 1 và đợt 2 không bao giờ thấy nhau.
        """
        await _ghi(db, fee_two_invoices, invoice_idx=0)
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, invoice_idx=1)

    async def test_xac_nhan_thi_ghi_duoc(self, db: AsyncSession, fee_two_invoices):
        """Hàng rào MỀM: xác nhận rồi thì đi tiếp, không chặn cứng."""
        await _ghi(db, fee_two_invoices)
        p = await _ghi(db, fee_two_invoices, invoice_idx=1, confirm=True)
        assert p.id is not None

    async def test_cung_ma_tham_chieu_khac_so_tien_khong_canh_bao(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Khoá regression cho luật đã BỊ BỎ.

        Dialog prefill mã hồ sơ làm mã tham chiếu, nên mọi lần thu của cùng
        hồ sơ đều trùng mã. Thêm luật "cùng reference bất kể tiền" là bắn cảnh
        báo vào MỌI lần thu góp thứ hai — cách nhanh nhất khiến kế toán ngừng
        đọc cảnh báo.
        """
        await _ghi(db, fee_two_invoices, reference="HS-000123")
        p = await _ghi(
            db,
            fee_two_invoices,
            amount=Decimal("300000"),
            reference="HS-000123",
        )
        assert p.id is not None


class TestTrangThaiPhieuCu:
    async def test_phieu_da_tu_choi_khong_tinh(
        self, db: AsyncSession, fee_two_invoices
    ):
        cu = await _ghi(db, fee_two_invoices)
        cu.status = PaymentStatusEnum.rejected.value
        await db.flush()
        p = await _ghi(db, fee_two_invoices, invoice_idx=1)
        assert p.id is not None

    async def test_phieu_da_dao_khong_tinh(self, db: AsyncSession, fee_two_invoices):
        cu = await _ghi(db, fee_two_invoices)
        cu.status = PaymentStatusEnum.refunded.value
        await db.flush()
        p = await _ghi(db, fee_two_invoices, invoice_idx=1)
        assert p.id is not None

    async def test_phieu_da_duyet_van_tinh(self, db: AsyncSession, fee_two_invoices):
        cu = await _ghi(db, fee_two_invoices)
        cu.status = PaymentStatusEnum.verified.value
        await db.flush()
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, invoice_idx=1)


class TestHoanTien:
    """Chỉ phiếu đã hoàn ĐỦ mới hết là ứng viên.

    ``RefundRequest`` cho hoàn một phần, nên "có một yêu cầu hoàn đã chi" chưa
    đủ để loại: hoàn 1 trên 5 triệu thì 4 triệu còn lại vẫn là tiền thật.
    """

    async def _them_refund(
        self, db: AsyncSession, payment: Payment, amount: Decimal, status: str
    ):
        db.add(
            RefundRequest(
                payment_id=payment.id,
                reason="test",
                amount=amount,
                status=status,
                requested_by_id=payment.created_by_id,
            )
        )
        await db.flush()

    async def test_hoan_mot_phan_van_la_ung_vien(
        self, db: AsyncSession, fee_two_invoices
    ):
        cu = await _ghi(db, fee_two_invoices)
        await self._them_refund(
            db, cu, _HALF / 4, RefundStatusEnum.refunded.value
        )
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, invoice_idx=1)

    async def test_hoan_du_mot_lan_thi_loai(
        self, db: AsyncSession, fee_two_invoices
    ):
        cu = await _ghi(db, fee_two_invoices)
        await self._them_refund(db, cu, _HALF, RefundStatusEnum.refunded.value)
        p = await _ghi(db, fee_two_invoices, invoice_idx=1)
        assert p.id is not None

    async def test_nhieu_lan_hoan_cong_lai_du_thi_loai(
        self, db: AsyncSession, fee_two_invoices
    ):
        cu = await _ghi(db, fee_two_invoices)
        await self._them_refund(
            db, cu, _HALF / 2, RefundStatusEnum.refunded.value
        )
        await self._them_refund(
            db, cu, _HALF / 2, RefundStatusEnum.refunded.value
        )
        p = await _ghi(db, fee_two_invoices, invoice_idx=1)
        assert p.id is not None

    @pytest.mark.parametrize(
        "status",
        [
            RefundStatusEnum.pending.value,
            RefundStatusEnum.approved.value,
            RefundStatusEnum.rejected.value,
        ],
    )
    async def test_yeu_cau_hoan_chua_chi_khong_tinh_la_da_hoan(
        self, db: AsyncSession, fee_two_invoices, status
    ):
        """Tiền chưa ra khỏi két thì phiếu vẫn là tiền — vẫn phải cảnh báo."""
        cu = await _ghi(db, fee_two_invoices)
        await self._them_refund(db, cu, _HALF, status)
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(db, fee_two_invoices, invoice_idx=1)


class TestMocThoiGianNaive:
    """Giá trị KHÔNG mang múi giờ là giờ Việt Nam, không phải UTC.

    Quy ước của repo (``utils/datetime_helpers``, khớp ``notification_tasks``):
    naive = giờ app = ``Asia/Ho_Chi_Minh``. Đọc nó thành UTC thì
    ``2026-08-05T23:30`` — người dùng gõ giờ Việt Nam — biến thành 06:30 sáng
    **hôm sau**, và mọi phép so theo ngày lịch lệch đúng một ngày.

    Nguy hiểm hơn cả việc lệch: nếu phép dò và bản ghi tự diễn giải lấy thì
    chúng nói hai thời điểm khác nhau — cảnh báo tính trên một ngày, sổ lưu
    một ngày khác.
    """

    async def test_naive_sat_nua_dem_van_thuoc_ngay_hom_do(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Ca quyết định của quy ước naive.

        Phiếu cũ ``2026-08-05T23:30`` naive:
        * hiểu đúng (giờ VN) ⇒ ngày lịch **05/08**, cách 09/08 **bốn** ngày ⇒
          KHÔNG cảnh báo;
        * hiểu sai (UTC)     ⇒ ngày lịch 06/08, cách 09/08 ba ngày ⇒ cảnh báo.
        """
        await _ghi(db, fee_two_invoices, when=datetime(2026, 8, 5, 23, 30))
        p = await _ghi(
            db,
            fee_two_invoices,
            invoice_idx=1,
            when=datetime(2026, 8, 9, 10, 0),
        )
        assert p.id is not None

    async def test_naive_sat_nua_dem_van_dinh_trong_cua_so(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Đối chứng: vẫn phải dính khi thật sự nằm trong cửa sổ 3 ngày."""
        await _ghi(db, fee_two_invoices, when=datetime(2026, 8, 5, 23, 30))
        with pytest.raises(PaymentDuplicateSuspected):
            await _ghi(
                db,
                fee_two_invoices,
                invoice_idx=1,
                when=datetime(2026, 8, 8, 10, 0),
            )

    async def test_chi_co_ngay_khong_gio_van_thuoc_dung_ngay(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Đường thật của giao diện: FE gửi "2026-08-05", Pydantic ra naive 00:00."""
        p = await _ghi(db, fee_two_invoices, when=datetime(2026, 8, 5, 0, 0))
        assert vn_calendar_date(p.payment_date) == date(2026, 8, 5)

    async def test_aware_giu_dung_moc_khi_doi_sang_ngay_vn(
        self, db: AsyncSession, fee_two_invoices
    ):
        """``18:00Z`` là 01:00 **hôm sau** giờ VN — mốc mang múi giờ thì tôn trọng nó."""
        p = await _ghi(
            db,
            fee_two_invoices,
            when=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
        )
        assert vn_calendar_date(p.payment_date) == date(2026, 8, 6)

    async def test_gia_tri_luu_va_lan_do_ke_tiep_cung_mot_ngay_lich(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Phép dò và bản ghi phải nói CÙNG một ngày.

        Ghi bằng giá trị naive sát nửa đêm, rồi hỏi lại kho dữ liệu bằng chính
        giá trị ấy: phải tìm thấy đúng phiếu vừa ghi. Nếu hai bên đọc naive
        theo hai quy ước thì câu truy vấn trượt khỏi bản ghi của chính nó.
        """
        goc = datetime(2026, 8, 5, 23, 30)
        p = await _ghi(db, fee_two_invoices, when=goc)

        ung_vien, bi_cat = await PaymentRepository(db).find_duplicate_candidates(
            fee_id=fee_two_invoices["fee_id"], amount=_HALF, payment_date=goc
        )
        assert [x.id for x in ung_vien] == [p.id]
        assert bi_cat is False
        assert vn_calendar_date(p.payment_date) == date(2026, 8, 5)


class TestTranSoUngVien:
    """Danh sách ứng viên phải có kích thước tối đa.

    Xác nhận trùng là hợp lệ và phiếu ``pending`` chưa làm giảm số dư, nên một
    người ghi có thể tạo bao nhiêu phiếu giống nhau tuỳ ý. Lần gửi KHÔNG xác
    nhận kế tiếp sẽ nạp tất cả lên — và ở bước sau, đưa hết vào thân lỗi 409.
    Một thông báo lỗi không có kích thước tối đa là một thông báo lỗi có thể bị
    dùng làm vũ khí.
    """

    async def _tao_nhieu_phieu(self, db: AsyncSession, ctx: dict, n: int):
        for _ in range(n):
            await _ghi(db, ctx, confirm=True)

    async def test_doc_toi_da_20_va_bao_bi_cat(
        self, db: AsyncSession, fee_two_invoices
    ):
        await self._tao_nhieu_phieu(db, fee_two_invoices, 21)
        ung_vien, bi_cat = await PaymentRepository(db).find_duplicate_candidates(
            fee_id=fee_two_invoices["fee_id"], amount=_HALF, payment_date=_BASE
        )
        assert len(ung_vien) == MAX_DUPLICATE_CANDIDATES
        assert bi_cat is True

    async def test_dung_20_thi_khong_bao_bi_cat(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Biên: đúng trần thì chưa cắt. Hỏi thừa một dòng chính là để biết điều này."""
        await self._tao_nhieu_phieu(db, fee_two_invoices, MAX_DUPLICATE_CANDIDATES)
        ung_vien, bi_cat = await PaymentRepository(db).find_duplicate_candidates(
            fee_id=fee_two_invoices["fee_id"], amount=_HALF, payment_date=_BASE
        )
        assert len(ung_vien) == MAX_DUPLICATE_CANDIDATES
        assert bi_cat is False

    async def test_bi_cat_thi_thong_bao_KHONG_noi_con_so(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Nói "20 phiếu" trong khi thực tế có thể 200 là một câu SAI.

        Người đọc dựa vào con số đó để quyết định có ghi tiếp hay không.
        """
        await self._tao_nhieu_phieu(db, fee_two_invoices, 21)
        with pytest.raises(PaymentDuplicateSuspected) as exc:
            await _ghi(db, fee_two_invoices, invoice_idx=1)
        loi = str(exc.value)
        assert "nhiều" in loi, loi
        assert "20" not in loi, loi

    async def test_chua_bi_cat_thi_noi_dung_con_so(
        self, db: AsyncSession, fee_two_invoices
    ):
        await self._tao_nhieu_phieu(db, fee_two_invoices, 2)
        with pytest.raises(PaymentDuplicateSuspected) as exc:
            await _ghi(db, fee_two_invoices, invoice_idx=1)
        assert "2 phiếu" in str(exc.value)

    async def test_tran_nam_trong_CAU_LENH_khong_phai_cat_sau_khi_da_nap(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Trần phải ở tầng SQL, không phải ``rows[:20]`` sau khi đã nạp hết.

        Cắt ở Python cho ra **cùng một kết quả** nên mọi ca ở trên vẫn xanh —
        đã kiểm chứng: gỡ ``LIMIT`` khỏi câu lệnh, cả bốn ca kia vẫn xanh. Mà
        thứ cần chặn lại chính là việc nạp: hydrate hàng nghìn ORM object vào
        bộ nhớ chỉ để vứt đi tất cả trừ hai mươi cái. Ca này soi đúng câu lệnh
        được gửi xuống.
        """
        cac_cau: list[str] = []
        goc_execute = db.execute

        async def execute_spy(stmt, *a, **k):
            try:
                cac_cau.append(
                    str(stmt.compile(compile_kwargs={"literal_binds": True}))
                )
            except Exception:  # noqa: BLE001 — câu không compile được thì bỏ qua
                cac_cau.append(str(stmt))
            return await goc_execute(stmt, *a, **k)

        db.execute = execute_spy
        try:
            await PaymentRepository(db).find_duplicate_candidates(
                fee_id=fee_two_invoices["fee_id"],
                amount=_HALF,
                payment_date=_BASE,
            )
        finally:
            db.execute = goc_execute

        assert cac_cau, "không bắt được câu lệnh nào"
        cau = cac_cau[-1]
        assert "LIMIT" in cau.upper(), f"câu truy vấn không có LIMIT:\n{cau}"
        # +1 để phân biệt "đúng trần" với "còn nữa" — xem docstring của repo.
        assert f"LIMIT {MAX_DUPLICATE_CANDIDATES + 1}" in cau.upper().replace(
            "LIMIT  ", "LIMIT "
        ), f"LIMIT phải là {MAX_DUPLICATE_CANDIDATES + 1}:\n{cau}"


class TestThuTuKhoa:
    async def test_khoa_invoice_roi_fee_roi_moi_quet_roi_moi_ghi(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Khoá KẾT QUẢ chưa đủ — phải khoá cả THỨ TỰ.

        Quét trùng trước khi khoá khoản phí thì hai request vào hai đợt khác
        nhau vẫn cùng thấy "chưa trùng". Ca đồng thời bên dưới chứng minh hậu
        quả; ca này chỉ ra đúng chỗ sai nếu ai đó đảo hai dòng.
        """
        svc = PaymentService(db)
        calls: list[str] = []

        goc_invoice = svc.invoice_repo.get_for_update
        goc_fee = svc.fee_repo.get_for_update
        goc_quet = svc.payment_repo.find_duplicate_candidates
        goc_add = db.add

        async def invoice_spy(*a, **k):
            calls.append("invoice.get_for_update")
            return await goc_invoice(*a, **k)

        async def fee_spy(*a, **k):
            calls.append("fee.get_for_update")
            return await goc_fee(*a, **k)

        async def quet_spy(*a, **k):
            calls.append("find_duplicate_candidates")
            return await goc_quet(*a, **k)

        def add_spy(obj, *a, **k):
            if isinstance(obj, Payment):
                calls.append("db.add(payment)")
            return goc_add(obj, *a, **k)

        svc.invoice_repo.get_for_update = invoice_spy
        svc.fee_repo.get_for_update = fee_spy
        svc.payment_repo.find_duplicate_candidates = quet_spy
        db.add = add_spy
        try:
            await svc.record_manual_payment(
                invoice_id=fee_two_invoices["invoice_ids"][0],
                method_id=fee_two_invoices["method_id"],
                amount=_HALF,
                user_id=fee_two_invoices["maker_id"],
                unit_id=fee_two_invoices["unit_id"],
                payment_date=_BASE,
            )
        finally:
            db.add = goc_add

        assert calls == [
            "invoice.get_for_update",
            "fee.get_for_update",
            "find_duplicate_candidates",
            "db.add(payment)",
        ], f"thứ tự thực tế: {calls}"


async def _ghi_trong_session_rieng(ctx: dict, invoice_idx: int):
    """Ghi phiếu trong session + giao dịch RIÊNG. Trả ('ok'|'err', lỗi)."""
    async with AsyncSessionLocal() as session:
        try:
            await PaymentService(session).record_manual_payment(
                invoice_id=ctx["invoice_ids"][invoice_idx],
                method_id=ctx["method_id"],
                amount=_HALF,
                user_id=ctx["maker_id"],
                unit_id=ctx["unit_id"],
                payment_date=_BASE,
            )
            await session.commit()
            return ("ok", None)
        except Exception as exc:  # noqa: BLE001 — cần giữ lỗi để assert
            await session.rollback()
            return ("err", exc)


def _hen_gap_tai_diem_quet(timeout: float = 2.0):
    """Ép hai lượt ghi gặp nhau ĐÚNG tại điểm quét trùng.

    Không có chỗ hẹn này thì ca đồng thời **không thể đỏ**: hai coroutine chạy
    xen kẽ trên một event loop, và lượt thứ nhất gần như luôn commit xong
    trước khi lượt thứ hai kịp quét — nên nó xanh y hệt cả khi khoá khoản phí
    bị gỡ bỏ. (Đã kiểm chứng: bỏ khoá `Fee` mà ca vẫn xanh.)

    Cách hoạt động: lượt tới quét TRƯỚC sẽ đứng chờ lượt kia.
    * **Có khoá** — lượt thứ hai còn đang bị chặn ở `get_for_update` nên không
      bao giờ tới; bên chờ hết ``timeout`` rồi đi tiếp. Đúng hành vi mong
      muốn: tuần tự hoá.
    * **Không có khoá nào** — cả hai cùng tới, gặp nhau, cùng quét trên dữ
      liệu chưa ai ghi, và cùng ghi. Đó chính là lỗi cần bắt.
    """
    goc = PaymentRepository.find_duplicate_candidates
    da_toi: list[int] = []
    cong = asyncio.Event()

    async def hook(self, *a, **k):
        da_toi.append(1)
        if len(da_toi) == 1:
            try:
                await asyncio.wait_for(cong.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        else:
            cong.set()
        return await goc(self, *a, **k)

    return hook, goc


class TestDongThoiHaiHoaDonCungKhoanPhi:
    async def test_chi_mot_request_ghi_duoc_request_kia_409(
        self, db: AsyncSession, fee_two_invoices
    ):
        """Ca mà cả hàng rào này sinh ra để chặn.

        Hai kế toán ghi cùng lúc vào HAI đợt khác nhau của cùng một khoản phí.
        Không có điểm gặp chung thì hai giao dịch không tranh chấp hàng nào,
        cùng quét thấy "chưa trùng", rồi cùng ghi — hàng rào vắng mặt đúng lúc
        cần nhất.

        Hai session độc lập, không dùng chung ``db``: chung session thì hai
        lượt gọi nằm trong cùng một giao dịch, khoá không bao giờ tranh chấp,
        và ca này xanh kể cả khi bản vá bị gỡ.

        ⚠️ **Ca này KHÔNG chứng minh riêng dòng khoá `Fee` trong service.** Đã
        kiểm: gỡ dòng đó ra thì ca vẫn xanh, vì `invoice_repo.get_for_update`
        dựng `select(Invoice).join(Fee)...with_for_update()` và `FOR UPDATE`
        không kèm `OF` khoá hàng của MỌI bảng trong FROM — hàng `fee` đã bị
        khoá sẵn. Cái ca này khoá là **tính tuần tự** nói chung: gỡ CẢ hai
        khoá thì nó đỏ (đã kiểm chứng, hai phiếu cùng được ghi). Vai trò của
        dòng khoá tường minh là giữ hợp đồng khỏi treo trên một chi tiết ngầm
        của câu lệnh bên cạnh; thứ tự gọi được canh riêng ở
        ``TestThuTuKhoa``.
        """
        await db.commit()  # dữ liệu fixture phải nhìn thấy được từ session khác

        hook, goc = _hen_gap_tai_diem_quet()
        PaymentRepository.find_duplicate_candidates = hook
        try:
            ket_qua = await asyncio.gather(
                _ghi_trong_session_rieng(fee_two_invoices, 0),
                _ghi_trong_session_rieng(fee_two_invoices, 1),
            )
        finally:
            PaymentRepository.find_duplicate_candidates = goc

        ok = [r for r in ket_qua if r[0] == "ok"]
        loi = [r for r in ket_qua if r[0] == "err"]

        assert len(ok) == 1, f"phải đúng MỘT lượt ghi được, nhận {ket_qua}"
        assert len(loi) == 1
        assert isinstance(loi[0][1], PaymentDuplicateSuspected), (
            f"lượt thua phải là cảnh báo trùng, nhận {type(loi[0][1])}: {loi[0][1]}"
        )

        async with AsyncSessionLocal() as check:
            rows = (
                await check.execute(
                    select(Payment).where(
                        Payment.invoice_id.in_(fee_two_invoices["invoice_ids"])
                    )
                )
            ).scalars().all()
        assert len(rows) == 1, f"chỉ được ghi một phiếu, DB có {len(rows)}"
