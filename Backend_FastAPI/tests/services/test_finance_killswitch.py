"""Kill-switch kế toán fail-closed — `close_period` và `apply_penalty`.

Bộ này canh **hai** thứ, và cả hai đều cần thiết:

1. **Cổng đóng khi cờ tắt** — service ném ``AccountingOperationLocked``, HTTP trả
   409 ổn định, và **DB không đổi một byte nào** (zero-delta).
2. **Cổng MỞ được khi cờ bật** — đây là phép kiểm ngược. Không có nó, một bản vá
   làm hỏng hẳn hai endpoint (import sai, route chết, service ném lỗi khác) vẫn
   khiến nhóm (1) xanh rờn: cái gì cũng "bị chặn", nhưng vì lý do khác. Nhóm (2)
   chứng minh thứ đang chặn ĐÚNG LÀ kill-switch chứ không phải một đống đổ vỡ.

Zero-delta được đo bằng cách đọc lại hàng thật từ DB sau lời gọi, không bằng giá
trị trả về của service — service bị chặn thì có trả về gì đâu mà tin.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    AccountingPeriod,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
)
from app.services.accounting_service import AccountingPeriodService
from app.services.fee_calculation_service import FeeCalculationService
from app.services.finance_killswitch import (
    OPERATION_INVOICE_PENALTY,
    OPERATION_PERIOD_CLOSE,
    is_invoice_penalty_allowed,
    is_period_close_allowed,
)
from app.services.invoice_service import InvoiceService
from app.utils.exceptions import AccountingOperationLocked
from app.config import settings

pytestmark = pytest.mark.asyncio


# =============================================================================
# FIXTURES
# =============================================================================


# ``cho_phep_dong_ky`` / ``cho_phep_ap_phat`` nằm ở ``tests/conftest.py`` — cả
# thư mục này lẫn ``tests/integration/`` đều dùng, nên chỉ có MỘT bản.


@pytest_asyncio.fixture
async def ky_dang_mo(db: AsyncSession) -> AccountingPeriod:
    """Một kỳ kế toán ĐANG MỞ, tách khỏi mọi kỳ khác.

    Dùng năm 2099 để không đụng ràng buộc "kỳ trước phải đóng" của H7 với dữ
    liệu do fixture khác sinh ra: bài toán ở đây là kill-switch, không phải
    thứ tự kỳ. Một ca kiểm chỉ được vi phạm một bất biến.
    """
    period = AccountingPeriod(
        period_month=6,
        period_year=2099,
        is_closed=False,
        total_revenue=Decimal("0"),
        total_payments=Decimal("0"),
        total_refunds=Decimal("0"),
    )
    db.add(period)
    await db.commit()
    await db.refresh(period)
    return period


@pytest_asyncio.fixture
async def hoa_don_qua_han(
    db: AsyncSession, seeded_dependencies: dict, admin_user
) -> Invoice:
    """Một hoá đơn ĐÃ PHÁT HÀNH và ĐÃ QUÁ HẠN — đủ điều kiện áp phạt.

    Quá hạn là bắt buộc: ``apply_penalty`` gate ``_invoice_is_overdue`` TRƯỚC
    khi tới bất kỳ thứ gì khác, nên một hoá đơn chưa quá hạn sẽ bị từ chối vì
    lý do KHÁC và phép kiểm ngược mất hết ý nghĩa.
    """
    lead = models.Lead(
        full_name="Killswitch Penalty Student",
        phone="0901990001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2025,
        applied_rules={},
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)

    fee_service = FeeCalculationService(db)
    fee, _ = await fee_service.calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.application,
        base_amount=Decimal("900000"),
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    invoice_service = InvoiceService(db)
    invoices, _ = await invoice_service.generate_invoices_for_fee(
        fee_id=fee.id,
        due_date_base=date.today() - timedelta(days=5),
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
        auto_issue=True,
    )
    await db.commit()
    await db.refresh(invoices[0])
    return invoices[0]


async def _doc_lai_ky(db: AsyncSession, period_id: int):
    """Đọc lại kỳ **bằng SQL thô**, không qua ORM.

    Vì sao không dùng ``select(AccountingPeriod)`` rồi đọc thuộc tính: câu ấy
    trả về đúng đối tượng đang nằm trong identity map của session, nên một
    thay đổi do service để lại vẫn hiện ra y như lúc chưa đụng gì — zero-delta
    xanh trong khi hàng thật đã đổi. Còn ``expire_all()`` để ép nạp lại thì
    quét luôn các fixture khác (``admin_user``), và lần đọc thuộc tính kế tiếp
    kích hoạt lazy-load trong ngữ cảnh async → ``MissingGreenlet``.

    SQL thô trả về giá trị nguyên thuỷ: không identity map, không lazy-load,
    và đọc đúng cái đang nằm trong bảng.

    Autoflush **để nguyên**: nếu service có làm bẩn đối tượng mà chưa flush,
    lần đọc này sẽ đẩy nó xuống DB và phép so bên dưới bắt được. Tắt autoflush
    ở đây là tự bịt mắt mình.
    """
    row = await db.execute(
        text(
            "SELECT is_closed, closed_at, closed_by_id "
            "FROM accounting_period WHERE id = :pid"
        ),
        {"pid": period_id},
    )
    return row.mappings().one()


async def _doc_lai_hoa_don(db: AsyncSession, invoice_id: int):
    """Đọc lại hoá đơn bằng SQL thô. Xem ``_doc_lai_ky``."""
    row = await db.execute(
        text(
            "SELECT status, amount, penalty_amount, paid_amount "
            "FROM invoice WHERE id = :iid"
        ),
        {"iid": invoice_id},
    )
    return row.mappings().one()


# =============================================================================
# 1. FAIL-CLOSED: mặc định là CHẶN
# =============================================================================


class TestMacDinhFailClosed:
    async def test_hai_co_mac_dinh_deu_tat(self):
        """Không đặt biến môi trường nào ⇒ cả hai thao tác đều bị chặn.

        Đây là bất biến quan trọng nhất của cả tệp. Cờ mang nghĩa "CHO PHÉP",
        nên gõ sai tên biến / quên nạp env / container tạo trước khi env đổi
        đều rơi về chặn. Cờ mang nghĩa "KHOÁ" thì cùng những ca ấy làm hàng
        rào biến mất trong im lặng.
        """
        assert is_period_close_allowed() is False
        assert is_invoice_penalty_allowed() is False

    async def test_pydantic_khai_bao_mac_dinh_false(self):
        """Mặc định nằm ở KHAI BÁO, không phải ở môi trường test.

        Test trên đọc ``settings`` đã dựng — nếu môi trường test tình cờ đặt
        cờ = false thì nó xanh mà không chứng minh gì. Ca này soi thẳng vào
        default của model, thứ quyết định hành vi trên production.
        """
        fields = type(settings).model_fields
        assert fields["ACCOUNTING_PERIOD_CLOSE_ENABLED"].default is False
        assert fields["INVOICE_PENALTY_ENABLED"].default is False


# =============================================================================
# 2. ĐÓNG KỲ — service + HTTP + zero-delta
# =============================================================================


class TestDongKyBiChan:
    async def test_service_nem_loi_khoa(self, db, ky_dang_mo, admin_user):
        service = AccountingPeriodService(db)

        with pytest.raises(AccountingOperationLocked) as exc:
            await service.close_period(
                month=ky_dang_mo.period_month,
                year=ky_dang_mo.period_year,
                user_id=admin_user.id,
                notes="thu dong ky",
            )

        assert exc.value.status_code == 409
        assert exc.value.error_code == "ACCOUNTING_OPERATION_LOCKED"
        assert exc.value.operation == OPERATION_PERIOD_CLOSE

    async def test_db_khong_doi(self, db, ky_dang_mo, admin_user):
        """Zero-delta: kỳ vẫn mở, không có dấu vết người đóng."""
        service = AccountingPeriodService(db)

        with pytest.raises(AccountingOperationLocked):
            await service.close_period(
                month=ky_dang_mo.period_month,
                year=ky_dang_mo.period_year,
                user_id=admin_user.id,
            )

        sau = await _doc_lai_ky(db, ky_dang_mo.id)
        assert sau["is_closed"] is False
        assert sau["closed_at"] is None
        assert sau["closed_by_id"] is None

    async def test_ky_khong_ton_tai_van_tra_khoa_chu_khong_404(
        self, db, admin_user
    ):
        """Chặn ĐỨNG TRƯỚC mọi lệnh đọc.

        Nếu guard đứng sau ``get_period``, gọi lần lượt từng (tháng, năm) sẽ
        phân biệt được kỳ nào có thật qua chênh lệch 404 ↔ 409 — một kênh dò
        trạng thái trong khi chức năng lẽ ra đang đóng hoàn toàn.
        """
        service = AccountingPeriodService(db)

        with pytest.raises(AccountingOperationLocked):
            await service.close_period(month=1, year=2098, user_id=admin_user.id)

    async def test_http_tra_409_on_dinh(
        self, client, admin_token_headers, db, ky_dang_mo
    ):
        resp = await client.put(
            f"/api/accounting/periods/{ky_dang_mo.id}/close",
            headers=admin_token_headers,
        )

        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["error_code"] == "ACCOUNTING_OPERATION_LOCKED"
        assert body["operation"] == OPERATION_PERIOD_CLOSE

        sau = await _doc_lai_ky(db, ky_dang_mo.id)
        assert sau["is_closed"] is False
        assert sau["closed_at"] is None

    async def test_http_id_khong_ton_tai_van_409_chu_khong_404(
        self, client, admin_token_headers
    ):
        """Khoá ĐƯỜNG HTTP, không chỉ đường service.

        Ca ``test_ky_khong_ton_tai_van_tra_khoa_chu_khong_404`` ở trên gọi
        THẲNG service nên nó xanh kể cả khi router đọc kỳ trước rồi mới gọi
        service. Đúng ca ấy mới là ca khai thác được: router
        ``close_period`` đọc ``AccountingPeriod`` và ném 404 TRƯỚC khi đường
        đi chạm tới guard, nên qua HTTP một id có thật trả 409 còn id không
        có trả 404 — gọi lần lượt từng id là liệt kê được kỳ nào tồn tại.

        Đã đo: gỡ ``finance_killswitch.assert_period_close_allowed()`` khỏi
        router mà giữ nguyên guard ở service thì 18 ca cũ VẪN xanh trọn —
        không ca nào canh chỗ ấy. Ca này là ca duy nhất đỏ.
        """
        resp = await client.put(
            "/api/accounting/periods/999999/close",
            headers=admin_token_headers,
        )

        assert resp.status_code == 409, (
            "id khong ton tai phai tra 409 y het id co that; "
            f"nhan {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["error_code"] == "ACCOUNTING_OPERATION_LOCKED"
        assert body["operation"] == OPERATION_PERIOD_CLOSE


class TestDongKyKiemNguoc:
    """Bật cờ ⇒ đóng kỳ chạy THẬT. Không có nhóm này, mọi ca ở trên vẫn xanh
    kể cả khi hai endpoint đã hỏng hoàn toàn vì lý do khác."""

    async def test_bat_co_thi_dong_duoc(
        self, db, ky_dang_mo, admin_user, cho_phep_dong_ky
    ):
        # Chốt id ra biến thường TRƯỚC lời gọi: sau ``close_period`` +
        # ``commit``, đọc ``admin_user.id`` là chạm vào một thuộc tính đã hết
        # hạn ⇒ SQLAlchemy nạp lại ngầm ⇒ ``MissingGreenlet`` trong async.
        uid = admin_user.id
        service = AccountingPeriodService(db)

        period, _ = await service.close_period(
            month=ky_dang_mo.period_month,
            year=ky_dang_mo.period_year,
            user_id=admin_user.id,
            notes="kiem nguoc",
        )
        await db.commit()

        assert period.is_closed is True

        sau = await _doc_lai_ky(db, ky_dang_mo.id)
        assert sau["is_closed"] is True
        assert sau["closed_at"] is not None
        assert sau["closed_by_id"] == uid


# =============================================================================
# 3. ÁP PHẠT — service + HTTP + zero-delta
# =============================================================================


class TestApPhatBiChan:
    async def test_service_nem_loi_khoa(
        self, db, hoa_don_qua_han, admin_user, seeded_dependencies
    ):
        service = InvoiceService(db)

        with pytest.raises(AccountingOperationLocked) as exc:
            await service.apply_penalty(
                invoice_id=hoa_don_qua_han.id,
                penalty_amount=Decimal("50000"),
                reason="tre han",
                user_id=admin_user.id,
                unit_id=seeded_dependencies["unit_id"],
            )

        assert exc.value.status_code == 409
        assert exc.value.error_code == "ACCOUNTING_OPERATION_LOCKED"
        assert exc.value.operation == OPERATION_INVOICE_PENALTY

    async def test_db_khong_doi(
        self, db, hoa_don_qua_han, admin_user, seeded_dependencies
    ):
        """Zero-delta: ``penalty_amount`` vẫn 0, ``total_due`` không nhúc nhích."""
        truoc_penalty = hoa_don_qua_han.penalty_amount
        truoc_amount = hoa_don_qua_han.amount
        service = InvoiceService(db)

        with pytest.raises(AccountingOperationLocked):
            await service.apply_penalty(
                invoice_id=hoa_don_qua_han.id,
                penalty_amount=Decimal("50000"),
                reason="tre han",
                user_id=admin_user.id,
                unit_id=seeded_dependencies["unit_id"],
            )

        sau = await _doc_lai_hoa_don(db, hoa_don_qua_han.id)
        assert sau["penalty_amount"] == truoc_penalty == Decimal("0")
        assert sau["amount"] == truoc_amount

    async def test_hoa_don_khong_ton_tai_van_tra_khoa_chu_khong_404(
        self, db, admin_user
    ):
        """Chặn trước ``get_for_update`` — không khoá hàng cho một thao tác
        chắc chắn bị từ chối, và không để lộ hoá đơn nào tồn tại."""
        service = InvoiceService(db)

        with pytest.raises(AccountingOperationLocked):
            await service.apply_penalty(
                invoice_id=987654321,
                penalty_amount=Decimal("1000"),
                reason="tre han",
                user_id=admin_user.id,
            )

    async def test_http_tra_409_on_dinh(
        self, client, admin_token_headers, db, hoa_don_qua_han
    ):
        resp = await client.post(
            f"/api/invoices/{hoa_don_qua_han.id}/apply-penalty",
            params={"penalty_amount": "50000", "reason": "tre han"},
            headers=admin_token_headers,
        )

        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["error_code"] == "ACCOUNTING_OPERATION_LOCKED"
        assert body["operation"] == OPERATION_INVOICE_PENALTY

        sau = await _doc_lai_hoa_don(db, hoa_don_qua_han.id)
        assert sau["penalty_amount"] == Decimal("0")


class TestApPhatKiemNguoc:
    async def test_bat_co_thi_ap_phat_duoc(
        self, db, hoa_don_qua_han, admin_user, seeded_dependencies, cho_phep_ap_phat
    ):
        service = InvoiceService(db)

        penalized, _ = await service.apply_penalty(
            invoice_id=hoa_don_qua_han.id,
            penalty_amount=Decimal("50000"),
            reason="kiem nguoc",
            user_id=admin_user.id,
            unit_id=seeded_dependencies["unit_id"],
        )
        await db.commit()

        assert penalized.penalty_amount == Decimal("50000")

        sau = await _doc_lai_hoa_don(db, hoa_don_qua_han.id)
        assert sau["penalty_amount"] == Decimal("50000")


# =============================================================================
# 4. CỜ can_apply_penalty — lớp phụ trên giao diện
# =============================================================================


class TestCoGiaoDien:
    """``can_apply_penalty`` và ``can_close`` phải tắt theo kill-switch, nếu
    không giao diện lại mời người dùng bấm đúng cái nút trả 409.

    Hai cờ này KHÔNG phải hàng rào — hàng rào ở service. Chúng chỉ giữ cho
    giao diện khỏi hứa một việc mà backend đang từ chối."""

    def _hoa_don_gia_qua_han(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() - timedelta(days=5),
            paid_amount=Decimal("0"),
            remaining_amount=Decimal("900000"),
            amount=Decimal("900000"),
            penalty_amount=Decimal("0"),
            __dict__={},
        )

    async def test_khoa_thi_co_tat(self):
        from app.routers.invoices import _compute_invoice_permissions

        flags = _compute_invoice_permissions(
            self._hoa_don_gia_qua_han(), current_user_role="admin"
        )
        assert flags["can_apply_penalty"] is False

    async def test_mo_thi_co_bat(self, cho_phep_ap_phat):
        """Kiểm ngược cho chính cờ giao diện: nếu nó false vì hoá đơn dựng sai
        (không quá hạn, sai vai trò) thì ca trên xanh mà chẳng canh gì cả."""
        from app.routers.invoices import _compute_invoice_permissions

        flags = _compute_invoice_permissions(
            self._hoa_don_gia_qua_han(), current_user_role="admin"
        )
        assert flags["can_apply_penalty"] is True

    async def test_can_close_tat_khi_khoa(self, client, admin_token_headers, ky_dang_mo):
        """Đối xứng với ``can_apply_penalty``: kỳ đang MỞ, người gọi là ADMIN,
        nhưng kill-switch còn bật ⇒ nút phải ẩn.

        Đọc qua HTTP chứ không gọi thẳng helper: cờ chỉ có giá trị nếu nó thật
        sự đi ra tới client, và một schema quên khai trường sẽ nuốt nó im lặng.
        """
        resp = await client.get(
            f"/api/accounting/periods/{ky_dang_mo.id}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["can_close"] is False

    async def test_can_close_bat_khi_mo(
        self, client, admin_token_headers, ky_dang_mo, cho_phep_dong_ky
    ):
        """Kiểm ngược cho chính cờ giao diện.

        Không có ca này thì ca trên xanh kể cả khi ``can_close`` được nối cứng
        ``False`` — hoặc khi kỳ dựng sai (đã đóng) làm cờ tắt vì lý do khác.
        """
        resp = await client.get(
            f"/api/accounting/periods/{ky_dang_mo.id}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["can_close"] is True

    async def test_can_close_tat_cho_manager_du_da_mo_khoa(
        self, client, manager_token_headers, ky_dang_mo, cho_phep_dong_ky
    ):
        """Cờ phải phản ánh CẢ vai trò, không chỉ kill-switch.

        ``close_period`` gắn ``require_admin``; manager bấm vào là 403. Gỡ mệnh
        đề vai trò khỏi ``_build_period_response`` mà chỉ có hai ca trên thì
        không ca nào đỏ.
        """
        resp = await client.get(
            f"/api/accounting/periods/{ky_dang_mo.id}", headers=manager_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["can_close"] is False

    async def test_can_close_tat_cho_ky_da_dong(
        self, client, admin_token_headers, db, ky_dang_mo, cho_phep_dong_ky
    ):
        """Và phản ánh cả trạng thái kỳ. Ba mệnh đề, ba ca — mỗi ca gỡ đúng một."""
        await db.execute(
            text("UPDATE accounting_period SET is_closed = true WHERE id = :pid"),
            {"pid": ky_dang_mo.id},
        )
        await db.commit()

        resp = await client.get(
            f"/api/accounting/periods/{ky_dang_mo.id}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["can_close"] is False


# =============================================================================
# 5. KHÔNG ĐỤNG CHỨC NĂNG KHÁC
# =============================================================================


class TestKhongLanSangChucNangKhac:
    async def test_doc_danh_sach_ky_van_200(self, client, admin_token_headers):
        resp = await client.get("/api/accounting/periods", headers=admin_token_headers)
        assert resp.status_code == 200, resp.text

    async def test_doc_chi_tiet_ky_van_200(
        self, client, admin_token_headers, ky_dang_mo
    ):
        resp = await client.get(
            f"/api/accounting/periods/{ky_dang_mo.id}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_closed"] is False

    async def test_tao_ky_moi_van_chay(self, db, admin_user):
        """Kill-switch chỉ chặn ĐÓNG kỳ. Tạo kỳ vẫn phải chạy — nếu nó cũng
        chết thì guard đã đặt sai chỗ (ví dụ ở tầng repository dùng chung)."""
        service = AccountingPeriodService(db)

        period, _ = await service.create_period(
            month=7, year=2097, user_id=admin_user.id
        )
        await db.commit()

        assert period.id is not None
        assert period.is_closed is False

    async def test_huy_hoa_don_van_chay(
        self, db, hoa_don_qua_han, admin_user, seeded_dependencies
    ):
        """Kill-switch chỉ chặn ÁP PHẠT. Các thao tác hoá đơn khác không đổi."""
        service = InvoiceService(db)

        cancelled, _ = await service.cancel_invoice(
            invoice_id=hoa_don_qua_han.id,
            reason="kiem tra khong lan",
            user_id=admin_user.id,
            unit_id=seeded_dependencies["unit_id"],
        )
        await db.commit()

        assert cancelled.status == InvoiceStatusEnum.cancelled.value


# =============================================================================
# 6. KHÔNG RÒ SỐ LIỆU SỔ SÁCH THẬT RA KHO PUBLIC
# =============================================================================


_DOI_TUONG_SO_SACH = (
    "(?:kỳ|hoá đơn|hóa đơn|phiếu thu|hồ sơ|bản ghi|khoản thu|giao dịch|lead)"
)

# Nhóm 1 — số liệu viết bằng CHỮ SỐ.
_MAU_METADATA_PRODUCTION = [
    # ⚠️ Lookaround phải chặn cả `.` chứ không riêng chữ số. Với `(?<!\d)` đơn
    # thuần, chuỗi tiền `9.000.000` VẪN khớp ở cụm `000.000` — ký tự đứng trước
    # là `.`, không phải chữ số. Đã đo: bốn ví dụ định dạng VND và một ví dụ số
    # thập phân bị bắt nhầm. `(?<![\d.]) … (?![\d.])` loại mọi chuỗi phân nhóm
    # nhiều tầng: một SỐ ĐẾM đứng một mình (1.795), còn SỐ TIỀN thì kéo dài
    # (2.570.000).
    (
        r"(?<![\d.])\d{1,3}\.\d{3}(?![\d.])",
        "so dem so sach kieu Viet (vd 1.795 phieu thu) — lo quy mo du lieu that",
    ),
    # Neo vào DẤU CHẤM PHÂN NHÓM, không phải "một số chia một số". Bản đầu
    # dùng `\b\d+\s*/\s*\d{3,}` và bắt nhầm ba chỗ vô hại đã có sẵn trong kho:
    # `10/2026`, `04/2026` (tháng/năm) và `403/503` (mã HTTP). Một guard bắt
    # nhầm là guard sẽ bị nới cho tới lúc hết canh gì.
    (
        r"(?<![\d.])\d+\s*/\s*\d{1,3}\.\d{3}(?![\d.])",
        "ty le dem duoc tren so that (vd 143/1.795)",
    ),
    # Số không phân nhóm thì không phân biệt được với năm hay mã lỗi — nên bắt
    # theo DANH TỪ SỔ SÁCH đi kèm thay vì theo hình dạng con số.
    (
        r"\b\d{3,}\s+" + _DOI_TUONG_SO_SACH,
        "so dem kem danh tu so sach (vd '1795 phieu thu')",
    ),
    (
        r"\b\d+,\d+\s*%",
        "phan tram do duoc tren so that (vd 8,0%)",
    ),
    (
        r"\b\d{2}-\d{2}-20\d{2}\b",
        "ngay audit tuyet doi — moc thoi gian mot lan cham vao production",
    ),
    (
        r"\.py:\d+",
        "tro so dong ma nguon — kem theo mot ban do noi bo, va lech mot dong la sai",
    ),
]

# Nhóm 2 — cùng thông tin ấy viết bằng LỜI.
#
# Bộ đầu chỉ canh chữ số, nên "chưa có kỳ nào", "thiệt hại hiện tại bằng 0",
# "CHƯA từng chạy trên production" đi lọt trọn vẹn — mà đó đúng là thông tin
# nhạy hơn cả một con số: nó nói thẳng trạng thái hệ thống đang chạy.
#
# Mỗi mẫu đòi MỘT danh từ sổ sách hoặc một cụm chỉ hệ thống thật đứng cùng câu.
# Không dùng mẫu chung chung ("chưa từng", "trên production"): đã đo, chúng bắt
# nhầm sáu chỗ hoàn toàn hợp lệ — "khoá chưa bao giờ được lắp" (nói về ngữ
# nghĩa cờ), "tiền chưa từng trả cho ai" (nghiệp vụ), "Pepper là BẮT BUỘC ở
# production" (yêu cầu triển khai, không phải trạng thái).
_MAU_TRANG_THAI_PRODUCTION = [
    (
        r"chưa (?:từng|bao giờ) (?:chạy|được chạy|áp|được áp|dùng|được dùng)"
        r"|chưa chạy lần nào",
        "tuyen bo mot thao tac CHUA TUNG chay tren he that",
    ),
    (
        r"chưa (?:có )?" + _DOI_TUONG_SO_SACH + r"\w* nào",
        "tuyen bo khong ton tai ban ghi nao — trang thai so sach that",
    ),
    (
        r"(?:thiệt hại|sai lệch|chênh lệch)[^.\n]{0,25}(?:bằng 0|= 0|hiện tại)",
        "tuyen bo muc thiet hai/lech hien tai cua he that",
    ),
    (
        r"\b0 " + _DOI_TUONG_SO_SACH + r"\b",
        "dem 0 doi tuong — van la mot phep do tren so that",
    ),
    (
        r"audit[^.\n]{0,30}(?:production|vận hành|sổ thật)",
        "nhac toi mot lan audit he that — moc thoi gian va pham vi truy cap",
    ),
    (
        r"mọi " + _DOI_TUONG_SO_SACH + r"\w*[^.\n]{0,20}(?:đều )?chưa",
        "tuyen bo pho quat ve trang thai moi ban ghi tren he that",
    ),
]

# Danh sách TƯỜNG MINH. Không quét bằng glob: một tệp mới sinh ra sẽ lặng lẽ
# nằm ngoài guard mà guard vẫn xanh. Thêm tệp vào bề mặt kill-switch thì thêm
# tên vào đây — kể cả tệp frontend: cờ `can_close` đi qua schema, zod, type và
# component, nên cả bốn đều là chỗ một lời giải thích "cho rõ" có thể chép số
# liệu vận hành vào.
#
# ⚠️ Tệp test này KHÔNG có trong danh sách và không được thêm vào: chính chú
# thích ở đây phải viết ra ví dụ ("1.795", "chưa có kỳ nào") để nói guard canh
# cái gì. Đó đúng là cái bẫy đã sập nhiều lần trong kho này — guard tự bắn vào
# phần giải thích của chính nó rồi bị nới cho tới lúc hết canh gì.
_BE_MAT_KILL_SWITCH = [
    "Backend_FastAPI/app/services/finance_killswitch.py",
    "Backend_FastAPI/app/routers/accounting.py",
    "Backend_FastAPI/app/routers/invoices.py",
    "Backend_FastAPI/app/services/accounting_service.py",
    "Backend_FastAPI/app/services/invoice_service.py",
    "Backend_FastAPI/app/schemas/finance.py",
    "Backend_FastAPI/app/config.py",
    "Backend_FastAPI/app/utils/exceptions.py",
    ".env.production.example",
    "frontend/src/types/finance.types.ts",
    "frontend/src/lib/zod/finance.ts",
    "frontend/src/app/(dashboard)/finance/accounting/_components/"
    "AccountingPeriodClient.tsx",
    "frontend/src/test/mocks/data/finance.ts",
]


# Ngoại lệ TƯỜNG MINH: (tệp, chuỗi khớp) đã soi tay và xác nhận vô hại.
#
# Một guard theo danh sách cấm mà không có lối này thì cách duy nhất để dùng
# tiếp là NỚI MẪU — và mẫu nới một lần là hết canh. Ngoại lệ ghi ở đây thì nó
# nằm trong diff, người review nhìn thấy, và mỗi mục phải kèm lý do.
#
# Khớp theo CHUỖI chứ không theo số dòng: chèn thêm một dòng phía trên không
# được phép làm ngoại lệ trượt sang chỗ khác.
_NGOAI_LE = {
    (
        "Backend_FastAPI/app/schemas/finance.py",
        "100.001",
    ): "vi du so thap phan trong chu thich ve so khop tien, khong phai so dem",
}


def _goc_repo():
    """Gốc cây repo, tìm bằng MỐC chứ không đếm tầng thư mục.

    ``parents[3]`` chỉ đúng trên runner CI. Dưới lệnh chạy tại máy mà CLAUDE.md
    ghi, ``Backend_FastAPI`` được mount thành ``/app`` nên đếm tầng ra thẳng
    ``/`` và guard quét vào hư không.
    """
    import os
    from pathlib import Path

    ung_vien = list(Path(__file__).resolve().parents)
    tu_env = os.environ.get("QLTS_REPO_ROOT")
    if tu_env:
        ung_vien.insert(0, Path(tu_env))
    for thu_muc in ung_vien:
        if (thu_muc / "docker-compose.yml").is_file() and (thu_muc / ".git").exists():
            return thu_muc
    return None


class TestKhongRoMetadataProduction:
    """Đây là kho **public**. Trạng thái hệ thống đang chạy không thuộc về nó.

    Bản đầu của PR này viết thẳng vào docstring và vào ``.env.production.example``
    số phiếu thu, số hoá đơn, tỷ lệ lệch tháng và ngày audit. Bản thứ hai gỡ hết
    chữ số nhưng **giữ nguyên cùng thông tin viết bằng lời**: "chưa có kỳ nào",
    "thiệt hại hiện tại bằng 0", "CHƯA từng chạy trên production". Không dòng
    nào là bí mật kỹ thuật — và đó chính là chỗ dễ mất cảnh giác: gộp lại, chúng
    mô tả quy mô, chất lượng và mức độ sử dụng thật của sổ sách tài chính một
    trường có thật, cho bất kỳ ai clone kho.

    Guard canh **bề mặt kill-switch** theo hai nhóm mẫu — chữ số và lời văn.

    ⚠️ Đây là **danh sách cấm cho những hình dạng đã thấy**, không phải chứng
    minh không còn gì. Nó chặn đường mà rò rỉ đã đi vào hai lần; nó không thay
    được việc đọc diff. Thêm một hình dạng mới thì thêm mẫu, đừng nới mẫu cũ.
    """

    async def test_be_mat_kill_switch_khong_chua_so_lieu_do_duoc(self):
        """Nhóm 1 — số liệu viết bằng chữ số."""
        self._quet(_MAU_METADATA_PRODUCTION, "So lieu do tren so sach that")

    async def test_be_mat_kill_switch_khong_ta_trang_thai_production(self):
        """Nhóm 2 — cùng thông tin ấy viết bằng lời.

        Tách khỏi ca trên vì đây là bất biến KHÁC, và vì bản thứ hai của PR này
        đã xanh trọn ca trên trong khi vẫn còn nguyên ba chỗ mô tả trạng thái
        production bằng lời.
        """
        self._quet(
            _MAU_TRANG_THAI_PRODUCTION, "Trang thai he thong dang chay"
        )

    def _quet(self, bo_mau, nhan):
        import os
        import re

        goc = _goc_repo()
        if goc is None:
            # Trên CI cây repo LUÔN có (actions/checkout). Không thấy nghĩa là
            # guard đang chạy sai chỗ — báo đỏ, đừng skip: một guard tự skip
            # trong đúng cổng cần nó là guard không tồn tại.
            assert not os.environ.get("CI"), (
                "khong tim thay goc repo tren CI — guard metadata dang chay sai "
                "cho, KHONG duoc bo qua"
            )
            pytest.skip(
                "khong thay goc repo (can docker-compose.yml + .git). Chay trong "
                "container backend thi mount cay repo va dat QLTS_REPO_ROOT."
            )

        vi_pham = []
        thieu = []
        for ten in _BE_MAT_KILL_SWITCH:
            duong = goc / ten
            if not duong.is_file():
                thieu.append(ten)
                continue
            for dong_so, dong in enumerate(
                duong.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for mau, vi_sao in bo_mau:
                    khop = re.search(mau, dong, re.IGNORECASE)
                    if khop:
                        if (ten, khop.group(0)) in _NGOAI_LE:
                            continue
                        vi_pham.append(
                            "%s:%d — %r (%s)" % (ten, dong_so, khop.group(0), vi_sao)
                        )

        # Tệp đổi tên/bị xoá mà guard không biết = guard xanh vì không quét gì.
        assert not thieu, (
            "cac tep sau co ten trong _BE_MAT_KILL_SWITCH nhung khong ton tai — "
            "guard dang KHONG quet chung: " + ", ".join(thieu)
        )

        assert not vi_pham, (
            nhan + " lot vao kho PUBLIC. Giu ly do o muc CO CHE trong repo, "
            "chuyen trang thai van hanh sang ho so NGOAI repo:"
            + "\n  "
            + "\n  ".join(vi_pham)
        )

    async def test_khong_con_ngoai_le_chet(self):
        """Mục ngoại lệ không còn khớp gì thì phải bị GỠ, không được ở lại.

        Một allowlist chỉ mọc thêm là allowlist sẽ nuốt dần chính guard: mục
        thêm vào cho một dòng đã bị xoá từ lâu vẫn tiếp tục miễn trừ đúng chuỗi
        ấy ở BẤT KỲ dòng nào sinh sau trong cùng tệp. Ca này buộc mỗi ngoại lệ
        phải chứng minh nó vẫn đang miễn trừ một thứ có thật.
        """
        import os
        import re

        goc = _goc_repo()
        if goc is None:
            assert not os.environ.get("CI"), "khong thay goc repo tren CI"
            pytest.skip("khong thay goc repo — xem ca quet ben tren")

        chet = []
        for (ten, chuoi), ly_do in _NGOAI_LE.items():
            duong = goc / ten
            if not duong.is_file():
                chet.append("%s (tep khong con) — %s" % (ten, ly_do))
                continue
            noi_dung = duong.read_text(encoding="utf-8")
            # Phải vừa CÓ MẶT trong tệp, vừa là thứ mà một mẫu thật sự bắt —
            # nếu không thì ngoại lệ đang miễn trừ một chuyện không xảy ra.
            co_mat = chuoi in noi_dung
            bi_bat = any(
                re.fullmatch(mau, chuoi, re.IGNORECASE)
                for mau, _ in _MAU_METADATA_PRODUCTION + _MAU_TRANG_THAI_PRODUCTION
            )
            if not (co_mat and bi_bat):
                chet.append(
                    "%s / %r (co_mat=%s, bi_bat=%s) — %s"
                    % (ten, chuoi, co_mat, bi_bat, ly_do)
                )

        assert not chet, (
            "cac ngoai le sau khong con mien tru gi — GO khoi _NGOAI_LE:\n  "
            + "\n  ".join(chet)
        )

    async def test_thong_bao_ra_client_khong_kem_con_so(self):
        """``detail`` đi thẳng ra HTTP body — đó là bề mặt công khai nhất.

        Tách khỏi hai ca trên vì đây là bất biến KHÁC: kể cả khi tệp nguồn đã
        sạch, một lần sửa lời nhắn cho "thuyết phục hơn" là đủ để đẩy số liệu
        ra cho mọi caller gọi được endpoint.
        """
        import re

        from app.services.finance_killswitch import (
            _INVOICE_PENALTY_DETAIL,
            _PERIOD_CLOSE_DETAIL,
        )

        for ten, loi in (
            ("_PERIOD_CLOSE_DETAIL", _PERIOD_CLOSE_DETAIL),
            ("_INVOICE_PENALTY_DETAIL", _INVOICE_PENALTY_DETAIL),
        ):
            assert not re.search(r"\d", loi), (
                "%s chua chu so — thong bao ra client phai mo ta VI SAO khoa, "
                "khong kem quy mo so sach: %r" % (ten, loi)
            )


class TestCongCIThayDuocThuNoCanh:
    """Tám nodeid nằm trong workflow không có nghĩa là chúng được CHẠY.

    Khối `tests:` của mỗi tier là scalar YAML gấp (``>-``): mọi dòng bị gấp
    thành MỘT dòng rồi đưa nguyên cho shell. Một chú thích ``#`` đặt bên trong
    khối ấy không phải chú thích YAML — nó là NỘI DUNG, và bash cắt từ đó tới
    hết dòng.

    Đo thật ở bản trước của PR này: lệnh nhận **17** đối số thay vì 25, cả tám
    nodeid kill-switch biến mất, và required check vẫn xanh — không có gì đỏ để
    báo rằng cổng vừa ngừng canh.
    """

    def _cac_tier(self):
        import yaml

        goc = _goc_repo()
        if goc is None:
            import os

            assert not os.environ.get("CI"), "khong thay goc repo tren CI"
            pytest.skip("khong thay goc repo — xem TestKhongRoMetadataProduction")
        duong = goc / ".github" / "workflows" / "backend-test.yml"
        assert duong.is_file(), "khong thay backend-test.yml: %s" % duong
        doc = yaml.safe_load(duong.read_text(encoding="utf-8"))
        return doc["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]

    async def test_khong_tier_nao_co_dau_thang_trong_khoi_tests(self):
        """Quét MỌI tier, không riêng tier kill-switch — cùng cái bẫy, cùng giá."""
        dinh = []
        for t in self._cac_tier():
            s = str(t.get("tests", ""))
            if "#" in s:
                mat = len(s.split()) - len(s.split("#")[0].split())
                dinh.append(
                    "%s — '#' trong scalar `tests:`, bash nuot %d doi so cuoi"
                    % (t.get("tier"), mat)
                )
        assert not dinh, (
            "Chu thich phai nam NGOAI scalar `tests: >-` (dat tren dong "
            "`- tier:`). Ben trong, YAML coi no la noi dung:\n  " + "\n  ".join(dinh)
        )

    async def test_tam_nodeid_kill_switch_thuc_su_toi_pytest(self):
        """Khẳng định theo thứ BASH NHẬN, không theo thứ tệp YAML chứa.

        Cắt chuỗi ở ``#`` đúng như shell làm, rồi mới đếm. Ca trên bắt nguyên
        nhân, ca này bắt hậu quả — giữ cả hai thì một cách nuốt đối số khác
        (nối dòng, dấu nháy) vẫn có chỗ đỏ.
        """
        can = [
            "tests/services/test_finance_killswitch.py",
            "tests/services/test_invoice_service.py::TestInvoiceLifecycle"
            "::test_apply_penalty",
            "tests/services/test_invoice_service.py::TestInvoiceLifecycle"
            "::test_apply_penalty_on_paid_invoice",
            "tests/services/test_invoice_service.py::TestApplyPenaltyGuards"
            "::test_penalty_none_rejected_not_500",
            "tests/services/test_invoice_service.py::TestApplyPenaltyGuards"
            "::test_penalty_exceeds_amount_rejected",
            "tests/services/test_invoice_service.py::TestApplyPenaltyGuards"
            "::test_penalty_within_cap_ok",
            "tests/services/test_invoice_service.py::TestApplyPenaltyGuards"
            "::test_penalty_blocked_when_not_overdue",
            "tests/services/test_invoice_service.py::TestApplyPenaltyGuards"
            "::test_penalty_blocked_on_draft_invoice",
            "tests/integration/test_finance_workflow.py::TestAccountingPeriod"
            "::test_create_and_close_period",
        ]
        toi_noi = set()
        for t in self._cac_tier():
            # Cắt ở '#' đúng như bash, rồi tách theo khoảng trắng.
            toi_noi.update(str(t.get("tests", "")).split("#")[0].split())

        thieu = [c for c in can if c not in toi_noi]
        assert not thieu, (
            "cac nodeid sau co trong workflow nhung KHONG toi duoc pytest "
            "(bi bash cat bo):\n  " + "\n  ".join(thieu)
        )
