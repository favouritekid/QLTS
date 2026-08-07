"""Nhập lô đối đầu ghi tay trên cùng một khoản phí — không được kẹt chéo.

**Chu kỳ đang có trên nhánh này (P1):**

* Nhập lô (``commit_batch``) khoá **Fee trước** ở pha soát phiếu, rồi mới khoá
  Invoice trong vòng lặp ghi dòng.
* Ghi tay (``record_manual_payment``) khoá **Invoice trước**, rồi Fee — và
  ``InvoiceRepository.get_for_update`` dựng ``select(Invoice).join(Fee)…
  .with_for_update()`` mà ``FOR UPDATE`` không kèm ``OF``, nên câu đó khoá hàng
  của MỌI bảng trong ``FROM``, gồm cả ``fee``.

Hai chiều ngược nhau trên cùng cặp hàng ⇒ ``deadlock detected`` (40P01).

⚠️ Pha khoá Fee trước **không phải thứ để gỡ**: nó là bản vá của bẫy soát phiếu
tuần tự (dòng đầu ghi xong làm ``duplicate_guard_version`` nhích, giết phiếu hợp
lệ của dòng thứ hai cùng khoản phí ⇒ mỗi lượt được đúng một dòng). Bản vá phải
giữ CẢ HAI tính chất.

**Ca này phải ĐỎ trước bản vá và XANH sau** — nên nó khẳng định điều bền vững
("không được kẹt chéo"), không khẳng định sự có mặt của lỗi.

Điểm hẹn không phải ``sleep``: một session giám sát thứ ba đọc
``pg_blocking_pids()`` cho tới khi thấy bên ghi tay **thật sự đang bị chặn**,
rồi mới thả cho bên nhập lô đi xin khoá Invoice. Thiếu chứng cứ ấy thì hai
coroutine chạy nối đuôi và ca xanh kể cả khi thứ tự khoá sai — đúng cái bẫy mà
``_hen_gap_tai_diem_quet`` trong ``test_payment_duplicate_guard`` đã ghi lại.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    Fee,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    PaymentImportBatch,
    PaymentImportBatchStatusEnum,
    PaymentImportRow,
    PaymentMethod,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.security import get_password_hash
from app.services import payment_import_service as pis
from app.services.payment_service import PaymentService

pytestmark = pytest.mark.asyncio

_CCCD = "001234567891"
_TIEN_LO = Decimal("2000000")
_TIEN_TAY = Decimal("3000000")
#: Trần chờ cho mọi điểm hẹn. Vượt trần = ca KHÔNG tái hiện được điều nó nói và
#: phải đỏ với thông báo RIÊNG — không được lẫn vào kết luận "kẹt chéo".
_TRAN_CHO = 20.0


@pytest_asyncio.fixture
async def hai_ben_cung_fee(db, seeded_dependencies, admin_user):
    """Một khoản phí + một hoá đơn + một lô nhập MỘT dòng, đã commit.

    Dựng bằng CHÍNH session của ca kiểm rồi commit — không dùng
    ``AsyncSessionLocal`` riêng: đơn vị và tài khoản do ``seeded_dependencies``
    tạo ra vẫn đang nằm trong giao dịch của session ấy, nên một kết nối khác
    chèn ``user.unit_id`` trỏ vào đó sẽ vỡ khoá ngoại.

    Phải commit thật: các session độc lập bên dưới đọc qua kết nối riêng và sẽ
    không thấy dữ liệu chưa commit.
    """
    unit_id = seeded_dependencies["unit_id"]
    method = (
        await db.execute(select(PaymentMethod).where(PaymentMethod.code == "cash"))
    ).scalars().first()
    if method is None:
        method = PaymentMethod(
            code="cash", name="Tiền mặt", is_online=False, is_active=True
        )
        db.add(method)
        await db.flush()

    # Dấu vân tài khoản kỹ thuật bị soi rất chặt — sai một trường là 409
    # "fingerprint is invalid" chứ không phải lỗi nghiệp vụ.
    sysu = (
        await db.execute(
            select(models.User).where(models.User.username == "system")
        )
    ).scalars().first()
    if sysu is None:
        sysu = models.User(
            username="system",
            email="system@qlts.internal",
            password_hash=get_password_hash("SystemX123!"),
            role="user",
            status="inactive",
            full_name="System Policy",
            unit_id=None,
        )
        db.add(sysu)
        await db.flush()

    ke_toan = models.User(
        username="deadlock_ketoan",
        email="deadlock_ketoan@test.com",
        password_hash=get_password_hash("KeToan123!"),
        role="accountant",
        status="active",
        full_name="Ke toan doi dau",
        unit_id=unit_id,
    )
    db.add(ke_toan)
    await db.flush()

    lead = models.Lead(
        full_name="Tran Thi Ket",
        phone="0901770888",
        source="test",
        unit_id=unit_id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2026,
        citizen_id=_CCCD,
        applied_rules={},
    )
    db.add(profile)
    await db.flush()

    # Dựng thẳng Fee/Invoice: `FeeCalculationService` đòi cấu hình ngành,
    # không liên quan gì tới thứ ca này chứng minh.
    fee = Fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.tuition.value,
        academic_year=2026,
        semester_no=1,
        base_amount=Decimal("50000000"),
        final_amount=Decimal("50000000"),
        status="invoiced",
    )
    db.add(fee)
    await db.flush()
    inv = Invoice(
        fee_id=fee.id,
        invoice_number="INV-DEADLOCK-1",
        installment_no=1,
        amount=Decimal("50000000"),
        status=InvoiceStatusEnum.issued.value,
        due_date=date.today() + timedelta(days=30),
    )
    db.add(inv)
    await db.flush()

    batch = PaymentImportBatch(
        academic_year=2026,
        semester_no=1,
        file_name="deadlock.xlsx",
        file_sha256="d" * 64,
        status=PaymentImportBatchStatusEnum.preview.value,
        row_count=1,
        matched_count=1,
        total_amount=_TIEN_LO,
        created_by_id=ke_toan.id,
    )
    db.add(batch)
    await db.flush()
    db.add(
        PaymentImportRow(
            batch_id=batch.id,
            row_no=1,
            citizen_id=_CCCD,
            raw={
                pis.COL_CCCD: _CCCD,
                pis.COL_NAME: "Tran Thi Ket",
                pis.COL_AMOUNT: "2.000.000",
                pis.COL_DATE: "05/09/2026",
                pis.COL_METHOD: "TM",
                pis.COL_REF: "UNC-LO",
                pis.COL_NOTE: "",
            },
            resolved_profile_id=profile.id,
            resolved_fee_id=fee.id,
            validation_status="matched",
            amount=_TIEN_LO,
        )
    )
    await db.commit()

    return {
        "fee_id": fee.id,
        "invoice_id": inv.id,
        "batch_id": batch.id,
        "method_id": method.id,
        "ke_toan_id": ke_toan.id,
        "admin_id": admin_user.id,
        "unit_id": unit_id,
    }


def _la_ket_cheo(exc: Optional[BaseException]) -> bool:
    """40P01 và CHỈ 40P01 — timeout hay lỗi fixture không được tính là kẹt chéo."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        ma = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
        if ma == "40P01" or type(exc).__name__ == "DeadlockDetectedError":
            return True
        exc = getattr(exc, "orig", None) or getattr(exc, "__cause__", None)
    return False


async def _do_thi_khoa() -> str:
    """Ảnh chụp đồ thị chờ, đọc bằng session RIÊNG không dính giao dịch nào."""
    async with AsyncSessionLocal() as giam_sat:
        rows = (
            await giam_sat.execute(
                text(
                    """
                    SELECT a.pid, pg_blocking_pids(a.pid)::text, a.wait_event_type,
                           a.state, left(a.query, 90)
                    FROM pg_stat_activity a
                    WHERE a.datname = current_database()
                      AND cardinality(pg_blocking_pids(a.pid)) > 0
                    """
                )
            )
        ).all()
    if not rows:
        return "  (không có ai đang bị chặn)"
    return "\n".join(
        f"  pid {r[0]} bị chặn bởi {r[1]} — {r[2]}/{r[3]} — {r[4]}" for r in rows
    )


async def _cho_toi_khi_co_ai_bi_chan(tran: float = _TRAN_CHO) -> str:
    """Điểm hẹn CÓ BẰNG CHỨNG: chờ tới khi PostgreSQL xác nhận có kẻ đang chờ.

    Trả về đồ thị chờ tại đúng khoảnh khắc ấy — vật chứng của ca này, thay cho
    một con số ``sleep`` đoán mò. Chuỗi rỗng nghĩa là không ai bị chặn trong
    trần chờ: hai bên đã chạy nối đuôi, ca không chứng minh được gì.
    """
    async with AsyncSessionLocal() as giam_sat:
        for _ in range(int(tran / 0.05)):
            co = (
                await giam_sat.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND cardinality(pg_blocking_pids(pid)) > 0"
                    )
                )
            ).scalar_one()
            if co:
                return await _do_thi_khoa()
            await asyncio.sleep(0.05)
    return ""


class TestNhapLoDoiDauGhiTay:
    async def test_khong_duoc_ket_cheo_tren_cung_khoan_phi(self, hai_ben_cung_fee):
        """Hai đường ghi tiền gặp nhau trên cùng Fee — không bên nào được chết 40P01."""
        ctx = hai_ben_cung_fee
        phien: dict = {}
        lo_giu_fee = asyncio.Event()
        tay_dang_bi_chan = asyncio.Event()
        do_thi: list[str] = []

        goc_fee = FeeRepository.get_for_update
        goc_inv = InvoiceRepository.get_for_update

        async def fee_hook(self, *a, **k):
            ket_qua = await goc_fee(self, *a, **k)
            # Chỉ khoá ĐẦU TIÊN của bên nhập lô mới là điểm hẹn: đó là pha soát
            # phiếu, chỗ sinh ra chiều Fee → Invoice.
            if phien.get("lo") is self.db and not lo_giu_fee.is_set():
                lo_giu_fee.set()
            return ket_qua

        async def inv_hook(self, *a, **k):
            if phien.get("lo") is self.db:
                # Bên nhập lô chỉ được đi xin Invoice SAU khi đã có bằng chứng
                # bên ghi tay đang bị chặn. Không có vế này thì nó xin trước,
                # lấy được, và chu kỳ không bao giờ khép.
                try:
                    await asyncio.wait_for(
                        tay_dang_bi_chan.wait(), timeout=_TRAN_CHO
                    )
                except asyncio.TimeoutError:
                    pass
            return await goc_inv(self, *a, **k)

        async def nhap_lo():
            async with AsyncSessionLocal() as ss:
                phien["lo"] = ss
                try:
                    await pis.commit_batch(
                        ss,
                        batch_id=ctx["batch_id"],
                        importer_id=ctx["ke_toan_id"],
                        unit_id=ctx["unit_id"],
                    )
                    await ss.commit()
                    return ("ok", None)
                except Exception as exc:  # noqa: BLE001 — cần giữ lỗi để phân loại
                    await ss.rollback()
                    return ("err", exc)

        async def ghi_tay():
            # Chỉ vào cuộc sau khi bên nhập lô đã CẦM khoá Fee — nếu không, nó
            # lấy trọn Invoice+Fee rồi xong, và chẳng có gì đối đầu.
            try:
                await asyncio.wait_for(lo_giu_fee.wait(), timeout=_TRAN_CHO)
            except asyncio.TimeoutError:
                return ("err", RuntimeError("bên nhập lô không tới được khoá Fee"))
            async with AsyncSessionLocal() as ss:
                phien["tay"] = ss
                try:
                    await PaymentService(ss).record_manual_payment(
                        invoice_id=ctx["invoice_id"],
                        method_id=ctx["method_id"],
                        amount=_TIEN_TAY,
                        user_id=ctx["admin_id"],
                        unit_id=ctx["unit_id"],
                    )
                    await ss.commit()
                    return ("ok", None)
                except Exception as exc:  # noqa: BLE001
                    await ss.rollback()
                    return ("err", exc)

        async def giam_sat():
            """Bên thứ ba: chỉ quan sát, và chính nó mở cổng cho bên nhập lô."""
            try:
                await asyncio.wait_for(lo_giu_fee.wait(), timeout=_TRAN_CHO)
            except asyncio.TimeoutError:
                tay_dang_bi_chan.set()
                return
            anh = await _cho_toi_khi_co_ai_bi_chan()
            do_thi.append(anh)
            tay_dang_bi_chan.set()

        FeeRepository.get_for_update = fee_hook
        InvoiceRepository.get_for_update = inv_hook
        try:
            ket_qua = await asyncio.wait_for(
                asyncio.gather(nhap_lo(), ghi_tay(), giam_sat()),
                timeout=_TRAN_CHO * 3,
            )
        finally:
            FeeRepository.get_for_update = goc_fee
            InvoiceRepository.get_for_update = goc_inv

        anh_khoa = do_thi[0] if do_thi else ""
        assert anh_khoa, (
            "Không quan sát được ai bị chặn trong trần chờ — hai bên đã chạy nối "
            "đuôi, nên ca này chưa chứng minh được gì về thứ tự khoá. Sửa điểm "
            "hẹn trước, đừng đọc kết quả bên dưới như một lời bảo đảm."
        )

        ket_cheo = [r[1] for r in ket_qua[:2] if r[0] == "err" and _la_ket_cheo(r[1])]
        assert not ket_cheo, (
            "KẸT CHÉO (40P01) giữa nhập lô và ghi tay trên cùng khoản phí.\n"
            f"Đồ thị chờ tại điểm hẹn:\n{anh_khoa}\n"
            f"Lỗi: {ket_cheo[0]!r}\n"
            "Chu kỳ: nhập lô giữ Fee (pha soát phiếu) rồi xin Invoice; ghi tay "
            "giữ Invoice (kèm Fee, vì FOR UPDATE không có OF) rồi xin Fee."
        )
