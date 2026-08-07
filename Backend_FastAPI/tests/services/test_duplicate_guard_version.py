"""``fee.duplicate_guard_version`` phải tăng ở tầng CƠ SỞ DỮ LIỆU.

Vì sao các ca dưới đây cố tình dùng SQL THÔ chứ không gọi service: điều cần
chứng minh không phải "service nhớ tăng version" — mà là "KHÔNG đường nào ghi
phiếu mà version đứng yên". Một quy ước ở tầng service chỉ đúng cho tới khi ai
đó viết đường thứ tư (repo này đã có bốn chỗ tạo ``Payment``), hoặc tới lần
đầu có người chữa dữ liệu bằng một câu ``UPDATE`` trong psql.

Nếu ai đó bỏ trigger và thay bằng một dòng Python, các ca này đỏ — đúng như
mong muốn.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.finance import (
    Fee,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
    PaymentStatusEnum,
    RefundRequest,
    RefundStatusEnum,
)

pytestmark = pytest.mark.asyncio


async def _dung_khoan_phi(db: AsyncSession, deps: dict, user_id: int):
    method = (
        await db.execute(select(PaymentMethod).where(PaymentMethod.code == "dgv_cash"))
    ).scalars().first()
    if method is None:
        method = PaymentMethod(
            code="dgv_cash", name="Tiền mặt", is_online=False, is_active=True
        )
        db.add(method)
        await db.flush()

    lead = models.Lead(
        full_name="Nguyễn Văn Version",
        phone="0901990001",
        source="test",
        unit_id=deps["unit_id"],
        consultation_status_id=deps["initial_status_id"],
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id, status="submitted", academic_year=2026, applied_rules={}
    )
    db.add(profile)
    await db.flush()

    fee = Fee(
        admission_profile_id=profile.id,
        fee_type="tuition",
        academic_year=2026,
        semester_no=1,
        base_amount=Decimal("10000000"),
        final_amount=Decimal("10000000"),
        status="invoiced",
    )
    db.add(fee)
    await db.flush()
    inv = Invoice(
        fee_id=fee.id,
        invoice_number=f"INV-DGV-{fee.id}",
        installment_no=1,
        amount=Decimal("10000000"),
        status=InvoiceStatusEnum.issued.value,
        due_date=date.today() + timedelta(days=30),
    )
    db.add(inv)
    await db.flush()
    await db.commit()
    return fee, inv, method


async def _version(db: AsyncSession, fee_id: int) -> int:
    return (
        await db.execute(
            text("SELECT duplicate_guard_version FROM fee WHERE id = :i"),
            {"i": fee_id},
        )
    ).scalar_one()


class TestVersionTangTheoDuLieu:
    async def test_INSERT_bang_SQL_THO_cung_lam_version_tang(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        """Ca then chốt: không đi qua một dòng Python nào của ứng dụng."""
        fee, inv, method = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)
        truoc = await _version(db, fee.id)

        await db.execute(
            text(
                "INSERT INTO payment (invoice_id, method_id, amount, status, "
                "payment_date, created_by_id, created_at, updated_at) VALUES "
                "(:inv, :m, 1000000, 'pending', now(), :u, now(), now())"
            ),
            {"inv": inv.id, "m": method.id, "u": admin_user.id},
        )
        await db.commit()

        assert await _version(db, fee.id) == truoc + 1, (
            "ghi phiếu thẳng bằng SQL mà version đứng yên ⇒ hàng rào nằm ở tầng "
            "ứng dụng, và mọi đường không đi qua nó đều đi vòng được"
        )

    async def test_doi_so_tien_cua_phieu_lam_version_tang(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        fee, inv, method = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)
        p = Payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            status=PaymentStatusEnum.pending.value,
            payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
            created_by_id=admin_user.id,
        )
        db.add(p)
        await db.commit()
        truoc = await _version(db, fee.id)

        await db.execute(
            text("UPDATE payment SET amount = 2000000 WHERE id = :i"), {"i": p.id}
        )
        await db.commit()
        assert await _version(db, fee.id) == truoc + 1

    async def test_doi_trang_thai_phieu_lam_version_tang(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        """`pending` → `rejected` đưa một phiếu RA KHỎI tập ứng viên."""
        fee, inv, method = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)
        p = Payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            status=PaymentStatusEnum.pending.value,
            payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
            created_by_id=admin_user.id,
        )
        db.add(p)
        await db.commit()
        truoc = await _version(db, fee.id)

        await db.execute(
            text("UPDATE payment SET status = 'rejected' WHERE id = :i"), {"i": p.id}
        )
        await db.commit()
        assert await _version(db, fee.id) == truoc + 1

    async def test_hoan_tien_lam_version_tang_du_KHONG_cham_payment(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        """Đường hoàn tiền chỉ đổi ``RefundRequest``; ``Payment`` đứng yên.

        Nhưng hoàn ĐỦ thì phiếu thôi không còn là ứng viên — tập đổi. Trigger
        chỉ nghe ``payment`` sẽ bỏ sót đúng ca này, và một phiếu xác nhận cấp
        trước đó vẫn được nhận cho một tập đã khác.
        """
        fee, inv, method = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)
        p = Payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            status=PaymentStatusEnum.verified.value,
            payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
            created_by_id=admin_user.id,
        )
        db.add(p)
        await db.commit()
        truoc = await _version(db, fee.id)

        db.add(
            RefundRequest(
                payment_id=p.id,
                amount=Decimal("1000000"),
                status=RefundStatusEnum.refunded.value,
                reason="test",
                requested_by_id=admin_user.id,
            )
        )
        await db.commit()
        assert await _version(db, fee.id) == truoc + 1

    async def test_CHUYEN_yeu_cau_hoan_sang_phieu_KHAC_lam_CA_HAI_fee_tang(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        """Ca `COALESCE` bỏ sót — và nó bỏ sót đúng vế nguy hiểm.

        `COALESCE(NEW.payment_id, OLD.payment_id)` luôn chọn NEW ở một `UPDATE`,
        nên chuyển một yêu cầu hoàn sang phiếu của khoản phí KHÁC chỉ làm
        version của khoản phí MỚI nhích. Khoản phí CŨ vừa có một phiếu quay lại
        tập ứng viên (nó thôi không còn được hoàn nữa) mà mọi phiếu xác nhận
        đang lưu hành của nó vẫn hợp lệ — tức hàng rào mở đúng ở ca nó cần đóng.
        """
        feeA, invA, method = await _dung_khoan_phi(
            db, seeded_dependencies, admin_user.id
        )
        feeB, invB, _ = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)

        def _phieu(inv):
            return Payment(
                invoice_id=inv.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                status=PaymentStatusEnum.verified.value,
                payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
                created_by_id=admin_user.id,
            )

        pA, pB = _phieu(invA), _phieu(invB)
        db.add_all([pA, pB])
        await db.flush()
        yc = RefundRequest(
            payment_id=pA.id,
            amount=Decimal("1000000"),
            status=RefundStatusEnum.refunded.value,
            reason="test",
            requested_by_id=admin_user.id,
        )
        db.add(yc)
        await db.commit()

        truocA = await _version(db, feeA.id)
        truocB = await _version(db, feeB.id)

        await db.execute(
            text("UPDATE refund_request SET payment_id = :p WHERE id = :i"),
            {"p": pB.id, "i": yc.id},
        )
        await db.commit()

        assert await _version(db, feeA.id) == truocA + 1, (
            "khoản phí CŨ không nhích — phiếu của nó vừa quay lại tập ứng viên "
            "mà mọi xác nhận đang lưu hành vẫn hợp lệ"
        )
        assert await _version(db, feeB.id) == truocB + 1, "khoản phí MỚI cũng đổi"

    async def test_sua_ghi_chu_phieu_KHONG_lam_version_tang(
        self, db: AsyncSession, seeded_dependencies, admin_user
    ):
        """Chiều ngược lại, và nó cũng quan trọng.

        Nghe mọi ``UPDATE`` thì một lần sửa ghi chú cũng vô hiệu hoá hết phiếu
        xác nhận đang lưu hành — người ghi phải xác nhận lại vì một lý do không
        dính gì tới tiền, và cách nhanh nhất để họ bấm qua cảnh báo mà không
        đọc.
        """
        fee, inv, method = await _dung_khoan_phi(db, seeded_dependencies, admin_user.id)
        p = Payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            status=PaymentStatusEnum.pending.value,
            payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
            created_by_id=admin_user.id,
        )
        db.add(p)
        await db.commit()
        truoc = await _version(db, fee.id)

        await db.execute(
            text("UPDATE payment SET notes = 'sửa ghi chú' WHERE id = :i"), {"i": p.id}
        )
        await db.commit()
        assert await _version(db, fee.id) == truoc, (
            "trigger đang nghe cả những cột không đổi tập ứng viên"
        )
