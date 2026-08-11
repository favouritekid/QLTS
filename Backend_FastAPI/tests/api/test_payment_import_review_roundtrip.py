"""Vòng xác nhận dòng nghi trùng, đi qua ĐÚNG các tầng mà giao diện đi.

Vì sao cần một bộ ca ở tầng API trong khi tầng service đã có ca riêng: ca
service tự dựng tham số cho `commit_batch`, nên nó xanh kể cả khi giao diện gửi
thiếu một trường bắt buộc. Đã xảy ra thật — bản trước đòi `candidate_count`
nhưng giao diện không gửi, service test vẫn xanh, và tính năng "ghi tiếp các
dòng nghi trùng" thực tế không dùng được.

Bộ ca này đi: upload → xem trước → commit (bị chặn) → đọc dấu vân từ CHÍNH
phản hồi → commit lại bằng đúng thân yêu cầu giao diện gửi → phải ghi được.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    Fee,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
    PaymentStatusEnum,
)
from app.security import get_password_hash

pytestmark = pytest.mark.asyncio

PREVIEW_URL = "/api/payments/import/preview"
COMMIT_URL = "/api/payments/import/{}/commit"

_CCCD = "001234567891"
_TIEN = Decimal("2000000")
_NGAY = date(2026, 9, 5)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


@pytest_asyncio.fixture
async def lo_co_dong_nghi_trung(seed_lead_dependencies, admin_user_in_db):
    """Một hồ sơ có học phí + MỘT phiếu chờ duyệt trùng đúng dòng sắp nhập."""
    async with AsyncSessionLocal() as db:
        # `admin_user_in_db` là dict (conftest), không phải ORM object.
        return await _dung_du_lieu(
            db, seed_lead_dependencies, admin_user_in_db["id"]
        )


async def _dung_du_lieu(db, seeded_dependencies, admin_user_id: int):
    method = PaymentMethod(
        code="cash", name="Tiền mặt", is_online=False, is_active=True
    )
    existing = (
        await db.execute(select(PaymentMethod).where(PaymentMethod.code == "cash"))
    ).scalars().first()
    if existing is None:
        db.add(method)
        await db.flush()
    else:
        method = existing

    # system_user cho maker-checker của auto-verify.
    sysu = (
        await db.execute(select(models.User).where(models.User.username == "system"))
    ).scalars().first()
    if sysu is None:
        # Dấu vân của user kỹ thuật bị soi rất chặt (`_get_system_application_fee_user`):
        # sai một trường là 409 "fingerprint is invalid", không phải lỗi nghiệp vụ.
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

    lead = models.Lead(
        full_name="Nguyễn Văn Vòng",
        phone="0901660777",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
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

    # Dựng Fee thẳng thay vì qua `FeeCalculationService`: dịch vụ đó đòi hồ sơ
    # có `offering_admission_config` hoặc `applied_rules.academic_info_id`, thứ
    # không liên quan gì tới thứ bộ ca này chứng minh (vòng xác nhận nghi trùng).
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
        invoice_number="INV-ROUNDTRIP-1",
        installment_no=1,
        amount=Decimal("50000000"),
        status=InvoiceStatusEnum.issued.value,
        due_date=date.today() + timedelta(days=30),
    )
    db.add(inv)
    await db.flush()

    # Phiếu chờ duyệt trùng đúng (khoản phí, số tiền, ngày) của dòng sắp nhập.
    db.add(
        Payment(
            invoice_id=inv.id,
            method_id=method.id,
            amount=_TIEN,
            reference_code="UNC-CU",
            status=PaymentStatusEnum.pending.value,
            payment_date=datetime(2026, 9, 5, tzinfo=timezone.utc),
            created_by_id=admin_user_id,
        )
    )
    await db.commit()
    return {"fee_id": fee.id, "invoice_id": inv.id}


def _file_mot_dong() -> bytes:
    from app.services import payment_import_service as pis

    return _csv_bytes(
        [
            pis.TEMPLATE_COLS,
            [_CCCD, "Nguyễn Văn Vòng", "2.000.000", "05/09/2026", "TM", "UNC-MOI", ""],
        ]
    )


class TestVongXacNhanQuaAPI:
    """Vòng xác nhận của ĐƯỜNG NHẬP LÔ, đi qua HTTP thật.

    Ca ở tầng service tự dựng tham số cho ``commit_batch`` và tự đọc phiếu ra
    khỏi cơ sở dữ liệu, nên nó xanh kể cả khi giao diện không có đường nào lấy
    được phiếu. Đã xảy ra thật ở đường ghi tay: bản trước đòi một trường mà
    giao diện không gửi, ca service vẫn xanh, và tính năng "ghi tiếp dòng nghi
    trùng" thực tế không dùng được.
    """

    async def test_bi_chan_roi_xac_nhan_thi_ghi_duoc(
        self, client: AsyncClient, admin_token_headers: dict, lo_co_dong_nghi_trung
    ):
        """Preview → commit (bị giữ) → đọc phiếu TỪ RESPONSE → commit lại."""
        r = await client.post(
            PREVIEW_URL,
            files={"file": ("thu.csv", _file_mot_dong(), "text/csv")},
            data={"academic_year": "2026", "semester_no": "1"},
            headers=admin_token_headers,
        )
        assert r.status_code in (200, 201), r.text
        batch_id = r.json()["batch_id"]

        r = await client.post(COMMIT_URL.format(batch_id), headers=admin_token_headers)
        assert r.status_code == 200, r.text
        than = r.json()
        assert than["committed_count"] == 0, than
        # Bị hàng rào giữ lại KHÁC ghi hỏng — hai con số riêng, vì chúng đòi hai
        # hành động khác nhau.
        assert than["review_required_count"] == 1, than
        assert than["failed_count"] == 0, than
        # Lô KHÔNG được đóng, nếu không thì lượt sau trả 409 và tiền kẹt.
        assert than["status"] == "preview", than["status"]

        dong = than["rows"][0]
        assert dong["commit_status"] == "duplicate_review_required", dong
        # Trục KIỂM giữ nguyên kết quả xem trước — dòng này đọc được, nó chỉ
        # chưa ghi được.
        assert dong["validation_status"] == "warned", dong
        phieu = dong["review_token"]
        assert isinstance(phieu, str) and phieu, (
            "máy chủ phải cấp phiếu trong CHÍNH response — không có nó thì giao "
            "diện không có đường nào ghi tiếp, và hàng rào mềm thành hàng rào cứng"
        )

        r = await client.post(
            COMMIT_URL.format(batch_id),
            json={
                "confirmed_rows": [
                    {"row_no": dong["row_no"], "review_token": phieu}
                ]
            },
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        than2 = r.json()
        assert than2["committed_count"] == 1, than2
        assert than2["payment_count"] == 1, than2
        assert than2["review_required_count"] == 0, than2
        assert than2["status"] == "committed", than2["status"]

    async def test_phieu_SAI_thi_van_bi_chan(
        self, client: AsyncClient, admin_token_headers: dict, lo_co_dong_nghi_trung
    ):
        """Một chuỗi trông giống phiếu không mở được cửa."""
        r = await client.post(
            PREVIEW_URL,
            files={"file": ("thu2.csv", _file_mot_dong(), "text/csv")},
            data={"academic_year": "2026", "semester_no": "1"},
            headers=admin_token_headers,
        )
        batch_id = r.json()["batch_id"]
        await client.post(COMMIT_URL.format(batch_id), headers=admin_token_headers)

        r = await client.post(
            COMMIT_URL.format(batch_id),
            json={"confirmed_rows": [{"row_no": 2, "review_token": "gia.mao"}]},
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["committed_count"] == 0, r.json()

    async def test_phieu_RONG_bi_tu_choi_o_tang_schema(
        self, client: AsyncClient, admin_token_headers: dict, lo_co_dong_nghi_trung
    ):
        """Thân yêu cầu thiếu phiếu ⇒ 422, không âm thầm bỏ qua."""
        r = await client.post(
            PREVIEW_URL,
            files={"file": ("thu3.csv", _file_mot_dong(), "text/csv")},
            data={"academic_year": "2026", "semester_no": "1"},
            headers=admin_token_headers,
        )
        batch_id = r.json()["batch_id"]
        r = await client.post(
            COMMIT_URL.format(batch_id),
            json={"confirmed_rows": [{"row_no": 2, "review_token": ""}]},
            headers=admin_token_headers,
        )
        assert r.status_code == 422, r.text


class TestPayloadLegacyKhongCapQuyen:
    """Client CŨ không được ghi tiền bằng contract đã gỡ.

    ``confirm_duplicates=true`` từng là cờ bỏ qua hàng rào cho TOÀN LÔ. Nay nó
    không còn trong chữ ký, nên FastAPI IM LẶNG bỏ qua nó — và im lặng ở đây là
    đúng, MIỄN LÀ nó không cấp quyền gì. Ca này khoá đúng vế "không cấp quyền":
    một client cũ gửi cờ ấy phải nhận lại y hệt kết quả của một lượt commit
    thường, tức dòng nghi trùng vẫn bị giữ.

    Vì sao không trả 410 như đường xem trước: ở đó, bỏ qua tham số làm response
    ĐỔI NGHĨA (danh sách phiếu thường bị đọc thành danh sách nghi trùng). Ở đây
    bỏ qua cờ chỉ làm nó mất tác dụng, và kết quả trả về vẫn nói đúng sự thật —
    dòng nào chưa ghi được thì vẫn hiện là chưa ghi được.
    """

    async def test_confirm_duplicates_query_KHONG_ghi_duoc(
        self, client: AsyncClient, admin_token_headers: dict, lo_co_dong_nghi_trung
    ):
        r = await client.post(
            PREVIEW_URL,
            files={"file": ("legacy.csv", _file_mot_dong(), "text/csv")},
            data={"academic_year": "2026", "semester_no": "1"},
            headers=admin_token_headers,
        )
        batch_id = r.json()["batch_id"]

        r = await client.post(
            COMMIT_URL.format(batch_id) + "?confirm_duplicates=true",
            headers=admin_token_headers,
        )
        assert r.status_code == 200, r.text
        than = r.json()
        assert than["committed_count"] == 0, (
            "cờ đã gỡ vẫn cấp được quyền ghi — client cũ bỏ qua hàng rào bằng "
            "một tham số không ai còn đọc"
        )
        assert than["review_required_count"] == 1, than
        assert than["rows"][0]["commit_status"] == "duplicate_review_required"

    async def test_confirm_duplicates_trong_THAN_cung_khong_cap_quyen(
        self, client: AsyncClient, admin_token_headers: dict, lo_co_dong_nghi_trung
    ):
        """Và cả khi nó nằm trong thân JSON — cùng một câu trả lời."""
        r = await client.post(
            PREVIEW_URL,
            files={"file": ("legacy2.csv", _file_mot_dong(), "text/csv")},
            data={"academic_year": "2026", "semester_no": "1"},
            headers=admin_token_headers,
        )
        batch_id = r.json()["batch_id"]

        r = await client.post(
            COMMIT_URL.format(batch_id),
            json={"confirm_duplicates": True, "confirmed_rows": []},
            headers=admin_token_headers,
        )
        assert r.status_code in (200, 422), r.text
        if r.status_code == 200:
            assert r.json()["committed_count"] == 0, r.json()
