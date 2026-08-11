"""Upload lại cùng file KHÔNG được xoá một lô đã ghi tiền một phần.

``create_preview_batch`` thay thế lô cũ khi gặp lại cùng ``file_sha256``, và nó
quyết định điều đó **chỉ bằng ``batch.status``**: hễ chưa phải ``committed`` thì
``db.delete(existing)`` — cascade cuốn theo toàn bộ ``payment_import_row``.

Chỗ hở nằm ở giả định "chưa ``committed`` nghĩa là chưa ghi đồng nào". Không
đúng: lô còn dòng bị hàng rào nghi trùng giữ lại vẫn ở trạng thái ``preview``
trong khi các dòng khác ĐÃ ghi tiền và đang mang ``payment_ids``. Trạng thái ấy
là bình thường, không phải ngoại lệ — nó xuất hiện ở mọi lượt commit có dòng
``duplicate_review_required``, tức đúng luồng mà cả đợt này dựng ra.

Hậu quả nếu xoá: ``Payment`` vẫn nằm trong sổ và tiền vẫn ở invoice/fee, nhưng
hàng ``payment_import_row`` trỏ tới nó biến mất. Mất **liên kết audit** giữa
tiền đã thu và dòng file sinh ra nó — không còn đường lần ngược "khoản này vào
sổ từ đâu", và lượt import kế tiếp không thấy dòng cũ nên có thể ghi lại lần
hai.

Ca này chạm cơ sở dữ liệu thật vì thứ cần chứng minh là hành vi CASCADE, không
phải một nhánh if.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models
from app.models.finance import (
    Fee,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentImportBatch,
    PaymentImportBatchStatusEnum,
    PaymentImportCommitStatusEnum,
    PaymentImportRow,
    PaymentMethod,
    PaymentStatusEnum,
)
from app.services import payment_import_service as pis
from app.services.payment_import_service import PreviewResult
from app.utils.exceptions import ConflictError

pytestmark = pytest.mark.asyncio

_SHA = "e" * 64
_TIEN = Decimal("2000000")


async def _lo_da_ghi_mot_phan(db, seeded_dependencies, admin_user):
    """Lô ở trạng thái ``preview`` nhưng MỘT dòng đã ghi tiền thật.

    Đây không phải trạng thái bịa: nó là kết quả của một lượt commit trong đó
    một dòng ghi được và một dòng bị hàng rào nghi trùng giữ lại.
    """
    method = (
        await db.execute(select(PaymentMethod).where(PaymentMethod.code == "cash"))
    ).scalars().first()
    if method is None:
        method = PaymentMethod(code="cash", name="Tiền mặt", is_online=False, is_active=True)
        db.add(method)
        await db.flush()

    lead = models.Lead(
        full_name="Lô ghi một phần",
        phone="0901550001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()
    hs = models.AdmissionProfile(
        lead_id=lead.id, status="submitted", academic_year=2026, applied_rules={}
    )
    db.add(hs)
    await db.flush()

    fee = Fee(
        admission_profile_id=hs.id,
        fee_type=FeeTypeEnum.tuition.value,
        academic_year=2026,
        semester_no=1,
        base_amount=_TIEN,
        final_amount=_TIEN,
        paid_amount=_TIEN,
        status="paid",
    )
    db.add(fee)
    await db.flush()
    inv = Invoice(
        fee_id=fee.id,
        invoice_number="INV-REPLACE-GUARD",
        installment_no=1,
        amount=_TIEN,
        paid_amount=_TIEN,
        status=InvoiceStatusEnum.paid.value,
        due_date=date.today() + timedelta(days=30),
    )
    db.add(inv)
    await db.flush()

    pay = Payment(
        invoice_id=inv.id,
        method_id=method.id,
        amount=_TIEN,
        reference_code="REPLACE-GUARD-1",
        status=PaymentStatusEnum.verified.value,
        payment_date=datetime.now(timezone.utc),
        created_by_id=admin_user.id,
    )
    db.add(pay)
    await db.flush()

    lo = PaymentImportBatch(
        academic_year=2026,
        semester_no=1,
        file_name="ghi-mot-phan.xlsx",
        file_sha256=_SHA,
        # ⚠️ Vẫn là `preview` — lô chưa đóng vì còn dòng chờ soát.
        status=PaymentImportBatchStatusEnum.preview.value,
        row_count=2,
        committed_row_count=1,
        review_required_count=1,
        total_amount=_TIEN,
        created_by_id=admin_user.id,
    )
    db.add(lo)
    await db.flush()

    db.add(
        PaymentImportRow(
            batch_id=lo.id,
            row_no=1,
            raw={},
            validation_status="matched",
            commit_status=PaymentImportCommitStatusEnum.committed.value,
            amount=_TIEN,
            resolved_fee_id=fee.id,
            payment_ids=[pay.id],  # ← liên kết audit sẽ mất nếu lô bị xoá
        )
    )
    db.add(
        PaymentImportRow(
            batch_id=lo.id,
            row_no=2,
            raw={},
            validation_status="warned",
            commit_status=PaymentImportCommitStatusEnum.duplicate_review_required.value,
            amount=_TIEN,
            resolved_fee_id=fee.id,
        )
    )
    await db.flush()
    return {"batch_id": lo.id, "payment_id": pay.id, "fee_id": fee.id}


def _preview_rong() -> PreviewResult:
    return PreviewResult(
        rows=[], matched_count=0, warned_count=0, failed_count=0,
        total_amount=Decimal("0"),
    )


class TestKhongXoaLoDaGhiMotPhan:
    async def test_upload_lai_cung_file_khong_duoc_xoa_lien_ket_payment(
        self, db, seeded_dependencies, admin_user
    ):
        """Lô `preview` có dòng đã ghi tiền ⇒ upload lại phải DỪNG, không thay thế.

        Thay thế ở đây không phải "làm mới ảnh chụp" mà là xoá bằng chứng: tiền
        đã vào sổ nhưng dòng nối nó với file nhập biến mất.
        """
        ctx = await _lo_da_ghi_mot_phan(db, seeded_dependencies, admin_user)

        with pytest.raises(ConflictError) as loi:
            await pis.create_preview_batch(
                db,
                preview=_preview_rong(),
                academic_year=2026,
                semester_no=1,
                file_name="ghi-mot-phan.xlsx",
                file_sha256_hex=_SHA,
                created_by_id=admin_user.id,
            )

        assert "ghi" in str(loi.value).lower() or "lô" in str(loi.value).lower(), (
            f"thông báo phải nói rõ lô đã ghi một phần, nhận: {loi.value}"
        )

        # Và quan trọng hơn lời từ chối: bằng chứng còn nguyên.
        con = (
            await db.execute(
                select(PaymentImportRow).where(
                    PaymentImportRow.batch_id == ctx["batch_id"]
                )
            )
        ).scalars().all()
        assert len(con) == 2, "rows của lô đã ghi một phần bị xoá mất"
        dong_da_ghi = [r for r in con if r.payment_ids]
        assert dong_da_ghi and dong_da_ghi[0].payment_ids == [ctx["payment_id"]], (
            "liên kết payment_ids biến mất — tiền còn trong sổ mà không lần ngược "
            "được về dòng file đã sinh ra nó"
        )

    async def test_lo_preview_SACH_van_duoc_thay_the(
        self, db, seeded_dependencies, admin_user
    ):
        """Ca dương — giữ cho ca trên không 'đạt' bằng cách chặn mọi thứ.

        Lô preview chưa ghi đồng nào vẫn phải thay thế được: đó là đường người
        dùng sửa file rồi xem lại, và chặn nó là dựng một ngõ cụt mới.
        """
        lo = PaymentImportBatch(
            academic_year=2026,
            semester_no=1,
            file_name="sach.xlsx",
            file_sha256="f" * 64,
            status=PaymentImportBatchStatusEnum.preview.value,
            row_count=1,
            created_by_id=admin_user.id,
        )
        db.add(lo)
        await db.flush()
        db.add(
            PaymentImportRow(
                batch_id=lo.id,
                row_no=1,
                raw={},
                validation_status="matched",
                commit_status=PaymentImportCommitStatusEnum.pending.value,
                amount=_TIEN,
            )
        )
        await db.flush()
        cu = lo.id

        moi = await pis.create_preview_batch(
            db,
            preview=_preview_rong(),
            academic_year=2026,
            semester_no=1,
            file_name="sach.xlsx",
            file_sha256_hex="f" * 64,
            created_by_id=admin_user.id,
        )
        await db.flush()
        assert moi.id != cu, "lô preview sạch phải được thay bằng lô mới"
        con_cu = await db.get(PaymentImportBatch, cu)
        assert con_cu is None, "lô preview sạch cũ phải bị xoá"
