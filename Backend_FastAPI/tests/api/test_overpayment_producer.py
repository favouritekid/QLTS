"""Hai phiếu pending cùng invoice → verify lần lượt → phải mở sổ tiền thừa.

Lỗ hổng bộ này khoá, đã tái hiện trên dev (invoice #778):

* lúc TẠO phiếu, server chỉ so số tiền với phần còn nợ tính trên các khoản ĐÃ
  verified — nên hai phiếu pending trên cùng invoice đều qua được cửa đó;
* lúc VERIFY, server khoá invoice/fee nhưng không cộng lại tổng đã ghi, nên
  khoản thứ hai đẩy số dư xuống ÂM;
* và tuy model tuyên bố "excess phải sinh OverpaymentRecord", không có đường
  nào thực sự tạo nó.

Kết quả đo được: invoice 8.000.000 nhận 8.000.000 + 70.000, transaction thứ hai
ghi ``balance_after = -70.000``, bảng ``overpayment_record`` RỖNG. Tiền thật của
người học nằm ngoài mọi sổ.

Bộ này đi qua HTTP thật vì đó là đường duy nhất chứng minh cả chuỗi — tạo phiếu,
maker-checker, khoá, settlement — chứ không phải chỉ hàm tính toán.
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
    OverpaymentRecord,
    Payment,
    PaymentMethod,
    PaymentTransaction,
)
from app.services.fee_calculation_service import FeeCalculationService
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import get_auth_headers

pytestmark = pytest.mark.asyncio

_TIEN_HOA_DON = Decimal("8000000")
_PHIEU_1 = Decimal("8000000")
_PHIEU_2 = Decimal("70000")  # đúng con số đã gặp trên dev


async def _tao(username: str, role: str, unit_id: int) -> dict:
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": username,
            "email": f"{username}@test.com",
            "password": "Overpay123!",
            "role": role,
            "status": "active",
        },
        f"role:{role}",
        unit_id=unit_id,
    )


@pytest_asyncio.fixture
async def boi_canh(seed_lead_dependencies: dict, admin_user_in_db: dict):
    """Một hoá đơn 8.000.000 chưa thu đồng nào, kèm maker và checker."""
    seeded = seed_lead_dependencies
    unit = seeded["unit_id"]

    maker = await _tao("ovp_maker", "accountant", unit)
    checker = await _tao("ovp_checker", "manager", unit)

    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="ovp_cash", name="Cash", is_online=False, is_active=True
        )
        db.add(method)

        lead = models.Lead(
            full_name="Overpay Student",
            phone="0901990001",
            source="test",
            unit_id=unit,
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
            base_amount=_TIEN_HOA_DON,
            academic_year=2025,
            user_id=admin_user_in_db["id"],
            unit_id=unit,
        )
        await db.flush()

        inv = Invoice(
            fee_id=fee.id,
            invoice_number="INV-OVP-1",
            installment_no=1,
            amount=_TIEN_HOA_DON,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30),
        )
        db.add(inv)

        # User kỹ thuật cho maker-checker của auto-verify (đường nhập lô).
        # Dấu vân bị soi rất chặt (`_get_system_application_fee_user`): sai một
        # trường là 409 "fingerprint is invalid", không phải lỗi nghiệp vụ.
        sysu = (
            await db.execute(
                select(models.User).where(models.User.username == "system")
            )
        ).scalars().first()
        if sysu is None:
            from app.security import get_password_hash

            db.add(
                models.User(
                    username="system",
                    email="system@qlts.internal",
                    password_hash=get_password_hash("SystemX123!"),
                    role="user",
                    status="inactive",
                    full_name="System Policy",
                    unit_id=None,
                )
            )
        await db.commit()

        return {
            "invoice_id": inv.id,
            "fee_id": fee.id,
            "profile_id": profile.id,
            "method_id": method.id,
            "maker": maker,
            "checker": checker,
        }


async def _dang_nhap(client: AsyncClient, user: dict) -> dict:
    """Đăng nhập NGAY TRƯỚC mỗi lượt đổi vai.

    🔴 Không giữ hai bộ headers song song. Client dùng chung một cookie jar và
    máy chủ đọc phiên từ COOKIE ("Token source: cookie"), nên lần đăng nhập sau
    ghi đè lần trước: mọi request "của maker" sau đó vẫn đi bằng danh tính
    checker, bất kể truyền headers nào. Bản đầu của bộ này lấy cả hai headers ở
    đầu ca và nhận 403 với log ghi rõ `username: ovp_checker` cho request lẽ ra
    là của maker.
    """
    return await get_auth_headers(client, user, AuthURLs.LOGIN)


async def _ghi_phieu(
    client: AsyncClient, h: dict, ctx: dict, amount: Decimal, ref: str
) -> int:
    r = await client.post(
        "/api/payments",
        json={
            "invoice_id": ctx["invoice_id"],
            "method_id": ctx["method_id"],
            "amount": str(amount),
            "reference_code": ref,
            "payer_name": "Overpay Student",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _so_ban_ghi_thua(invoice_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(OverpaymentRecord)
                .where(OverpaymentRecord.invoice_id == invoice_id)
            )
        ).scalar_one()


async def test_hai_pending_verify_lan_luot_thi_mo_so_tien_thua(
    client: AsyncClient, boi_canh: dict
):
    """Ca chính. Trước bản vá: số dư về -70.000 và không có sổ nào."""
    h_maker = await _dang_nhap(client, boi_canh["maker"])

    # Hai phiếu pending cùng lúc — cửa "không vượt quá còn nợ" chỉ nhìn phần ĐÃ
    # verified, nên cả hai đều lọt qua.
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "OVP-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "OVP-2")

    assert await _so_ban_ghi_thua(boi_canh["invoice_id"]) == 0, (
        "chưa verify thì chưa có tiền vào sổ, nên chưa được có khoản thừa nào"
    )

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    r1 = await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    assert r1.status_code == 200, r1.text
    assert await _so_ban_ghi_thua(boi_canh["invoice_id"]) == 0, (
        "phiếu đầu vừa đủ số phải trả — không có phần vượt nào"
    )

    r2 = await client.put(f"/api/payments/{p2}/verify", headers=h_checker)
    assert r2.status_code == 200, r2.text

    async with AsyncSessionLocal() as db:
        so = (
            await db.execute(
                select(OverpaymentRecord).where(
                    OverpaymentRecord.invoice_id == boi_canh["invoice_id"]
                )
            )
        ).scalars().all()

    assert len(so) == 1, (
        f"phải mở ĐÚNG MỘT sổ tiền thừa, đang có {len(so)}. Số dư invoice đã âm "
        "mà không có sổ nghĩa là tiền của người học nằm ngoài mọi bản ghi."
    )
    ban_ghi = so[0]
    assert ban_ghi.overpayment_amount == _PHIEU_2
    assert ban_ghi.payment_id == p2, "sổ phải trỏ đúng phiếu gây ra phần vượt"
    assert ban_ghi.status == "pending"
    assert ban_ghi.source_type == "payment_settlement"
    assert ban_ghi.admission_profile_id == boi_canh["profile_id"]


async def test_retry_verify_khong_de_them_so_thu_hai(
    client: AsyncClient, boi_canh: dict
):
    """Idempotency: gọi verify lại không được sinh nghĩa vụ trả nợ thứ hai."""
    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "OVP-R1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "OVP-R2")

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    await client.put(f"/api/payments/{p2}/verify", headers=h_checker)

    lan_hai = await client.put(f"/api/payments/{p2}/verify", headers=h_checker)
    assert lan_hai.status_code == 400, lan_hai.text

    assert await _so_ban_ghi_thua(boi_canh["invoice_id"]) == 1


async def test_thu_dung_bang_hoa_don_thi_khong_sinh_so(
    client: AsyncClient, boi_canh: dict
):
    """Chiều âm: luồng thường KHÔNG được đẻ ra khoản thừa giả.

    Không có ca này thì một bản vá 'luôn mở sổ' vẫn làm ca chính xanh, và mọi
    hoá đơn trả đủ đều mọc một khoản nợ không có thật.
    """
    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p = await _ghi_phieu(client, h_maker, boi_canh, _TIEN_HOA_DON, "OVP-EXACT")

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    r = await client.put(f"/api/payments/{p}/verify", headers=h_checker)
    assert r.status_code == 200, r.text

    assert await _so_ban_ghi_thua(boi_canh["invoice_id"]) == 0

    async with AsyncSessionLocal() as db:
        inv = (
            await db.execute(
                select(Invoice).where(Invoice.id == boi_canh["invoice_id"])
            )
        ).scalar_one()
        assert inv.remaining_amount == Decimal("0")
        assert inv.status == InvoiceStatusEnum.paid.value


async def test_so_du_am_luon_di_kem_mot_so(client: AsyncClient, boi_canh: dict):
    """Bất biến ràng buộc hai thứ với nhau, thay vì kiểm rời từng cái.

    "Số dư âm" và "có sổ tiền thừa" phải luôn đi cùng nhau: mỗi đồng làm số dư
    âm phải có đúng một đồng nằm trong sổ. Kiểm rời thì một bản vá ghi sổ sai số
    tiền vẫn qua được.
    """
    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "OVP-INV1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "OVP-INV2")

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    await client.put(f"/api/payments/{p2}/verify", headers=h_checker)

    async with AsyncSessionLocal() as db:
        inv = (
            await db.execute(
                select(Invoice).where(Invoice.id == boi_canh["invoice_id"])
            )
        ).scalar_one()
        tong_thua = (
            await db.execute(
                select(func.coalesce(func.sum(OverpaymentRecord.overpayment_amount), 0))
                .where(OverpaymentRecord.invoice_id == boi_canh["invoice_id"])
            )
        ).scalar_one()

    am = max(Decimal("0"), -inv.remaining_amount)
    assert am == tong_thua, (
        f"số dư âm {am} nhưng sổ tiền thừa ghi {tong_thua} — hai con số này "
        "phải khớp từng đồng"
    )
    assert am > 0, "ca này phải thật sự tạo ra số dư âm, nếu không nó chứng minh rỗng"


# ---------------------------------------------------------------------------
# NHẬP LÔ — không được đẻ khoản thừa giả
# ---------------------------------------------------------------------------

async def test_import_thu_dung_khong_sinh_so_gia(boi_canh: dict):
    """Đường nhập lô đi qua CÙNG hàm money-math, nên nó cũng phải im lặng khi
    không có gì thừa.

    Phân bổ FIFO của lô chỉ rót tối đa bằng số còn nợ của từng đợt, nên luồng
    thường KHÔNG sinh khoản thừa. Ca này chốt điều đó: nếu một bản vá "luôn mở
    sổ" lọt vào, mọi lô thu đúng sẽ mọc ra nợ không có thật — và với lô thì đó
    là hàng loạt, không phải một hoá đơn.
    """
    from app.models.finance import Fee
    from app.services.payment_import_service import (
        auto_verify_payment,
        get_system_user,
    )

    async with AsyncSessionLocal() as db:
        inv = (
            await db.execute(
                select(Invoice).where(Invoice.id == boi_canh["invoice_id"])
            )
        ).scalar_one()
        fee = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        system_user = await get_system_user(db)

        payment = await auto_verify_payment(
            db,
            invoice=inv,
            fee=fee,
            method_id=boi_canh["method_id"],
            amount=_TIEN_HOA_DON,  # đúng bằng số phải trả
            payment_date=datetime.now(timezone.utc),
            reference="IMP-EXACT",
            importer_id=boi_canh["maker"]["id"],
            system_user=system_user,
            idempotency_key="imp-exact-1",
        )
        await db.commit()

    assert payment is not None
    assert await _so_ban_ghi_thua(boi_canh["invoice_id"]) == 0, (
        "lô thu đúng số phải trả mà vẫn mở sổ tiền thừa — mỗi dòng của mọi lô "
        "sẽ mọc ra một khoản nợ không có thật"
    )

    async with AsyncSessionLocal() as db:
        inv = (
            await db.execute(
                select(Invoice).where(Invoice.id == boi_canh["invoice_id"])
            )
        ).scalar_one()
        assert inv.remaining_amount == Decimal("0")
        assert inv.status == InvoiceStatusEnum.paid.value


# ---------------------------------------------------------------------------
# GIẢI QUYẾT SỔ — tiền không được nhân lên
# ---------------------------------------------------------------------------

async def test_apply_khong_lam_tang_tong_tien_phan_bo(
    client: AsyncClient, boi_canh: dict, seed_lead_dependencies: dict
):
    """Producer THẬT → apply sang hoá đơn khác: tổng tiền phân bổ không đổi.

    Đây là bất biến quan trọng nhất của cả cơ chế: hệ thống chỉ được phân bổ
    đúng số tiền đã nhận. Phần vượt phải RỜI hoá đơn nguồn trước khi vào hoá
    đơn đích — nếu chỉ cộng vào đích mà không trừ nguồn thì cùng một khoản tiền
    được ghi nhận hai lần.

    Ca này dùng record do PRODUCER thật sinh ra, không dựng tay — vì lỗi chỉ lộ
    khi nguồn thực sự đang giữ phần vượt.
    """
    from app.models.finance import Fee
    from app.services.overpayment_service import OverpaymentService

    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "APPLY-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "APPLY-2")

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    await client.put(f"/api/payments/{p2}/verify", headers=h_checker)

    # Hoá đơn đích: một đợt khác của cùng hồ sơ, còn nợ.
    async with AsyncSessionLocal() as db:
        fee = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        fee.final_amount = fee.final_amount + _PHIEU_2
        dich = Invoice(
            fee_id=fee.id,
            invoice_number="INV-OVP-2",
            installment_no=2,
            amount=_PHIEU_2,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=60),
        )
        db.add(dich)
        await db.commit()
        dich_id = dich.id

        so = (
            await db.execute(
                select(OverpaymentRecord).where(
                    OverpaymentRecord.invoice_id == boi_canh["invoice_id"]
                )
            )
        ).scalar_one()
        so_id = so.id

        tong_truoc = (
            await db.execute(
                select(func.coalesce(func.sum(Invoice.paid_amount), 0)).where(
                    Invoice.fee_id == fee.id
                )
            )
        ).scalar_one()

    # Kế toán áp khoản thừa sang đợt sau.
    async with AsyncSessionLocal() as db:
        await OverpaymentService(db).apply_to_invoice(
            overpayment_id=so_id,
            target_invoice_id=dich_id,
            user_id=boi_canh["checker"]["id"],
            unit_id=seed_lead_dependencies["unit_id"],
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        fee = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        tong_sau = (
            await db.execute(
                select(func.coalesce(func.sum(Invoice.paid_amount), 0)).where(
                    Invoice.fee_id == fee.id
                )
            )
        ).scalar_one()
        tong_da_thu_that = (
            await db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.status == "verified",
                    Payment.invoice_id.in_(
                        select(Invoice.id).where(Invoice.fee_id == fee.id)
                    ),
                )
            )
        ).scalar_one()

    assert tong_sau == tong_truoc, (
        f"tổng tiền phân bổ trên các hoá đơn đã TĂNG {tong_sau - tong_truoc} "
        "sau khi áp khoản thừa — cùng một khoản tiền được ghi nhận hai lần"
    )
    assert tong_sau == tong_da_thu_that, (
        f"tổng phân bổ {tong_sau} khác tổng tiền thật đã nhận {tong_da_thu_that}"
    )


async def test_apply_sang_fee_khac_giu_tong_hai_fee(
    client: AsyncClient, boi_canh: dict, seed_lead_dependencies: dict, admin_user_in_db: dict
):
    """Chuyển sang một KHOẢN PHÍ khác: Fee nguồn giảm, Fee đích tăng, tổng hai
    Fee không đổi.

    Nhánh này khác hẳn nhánh cùng-Fee: ở đó `fee.paid_amount` phải đứng yên,
    còn ở đây hai Fee phải dịch chuyển ngược chiều nhau. Một ca không chứng
    minh được cả hai.
    """
    from app.models.finance import Fee, FeeStatusEnum
    from app.services.overpayment_service import OverpaymentService

    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "X-FEE-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "X-FEE-2")
    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    await client.put(f"/api/payments/{p2}/verify", headers=h_checker)

    unit_id = seed_lead_dependencies["unit_id"]

    async with AsyncSessionLocal() as db:
        # Dựng thẳng Fee thứ hai thay vì gọi `calculate_fee`: loại `tuition` đòi
        # thông tin tuyển sinh (offering/academic_info) mà bối cảnh này không
        # có, và ca đang kiểm phép CHUYỂN TIỀN chứ không kiểm cách tính phí.
        fee2 = Fee(
            admission_profile_id=boi_canh["profile_id"],
            fee_type="other",
            academic_year=2025,
            base_amount=_PHIEU_2,
            final_amount=_PHIEU_2,
            status=FeeStatusEnum.invoiced.value,
        )
        db.add(fee2)
        await db.flush()
        dich = Invoice(
            fee_id=fee2.id,
            invoice_number="INV-OVP-XFEE",
            installment_no=1,
            amount=_PHIEU_2,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=60),
        )
        db.add(dich)
        await db.commit()
        dich_id, fee2_id = dich.id, fee2.id

        so = (
            await db.execute(
                select(OverpaymentRecord).where(
                    OverpaymentRecord.invoice_id == boi_canh["invoice_id"]
                )
            )
        ).scalar_one()
        so_id = so.id

        f1 = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        f2 = (await db.execute(select(Fee).where(Fee.id == fee2_id))).scalar_one()
        tong_fee_truoc = f1.paid_amount + f2.paid_amount
        f1_truoc, f2_truoc = f1.paid_amount, f2.paid_amount

    async with AsyncSessionLocal() as db:
        await OverpaymentService(db).apply_to_invoice(
            overpayment_id=so_id,
            target_invoice_id=dich_id,
            user_id=boi_canh["checker"]["id"],
            unit_id=unit_id,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        f1 = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        f2 = (await db.execute(select(Fee).where(Fee.id == fee2_id))).scalar_one()

    assert f1.paid_amount == f1_truoc - _PHIEU_2, "Fee nguồn phải GIẢM đúng phần dư"
    assert f2.paid_amount == f2_truoc + _PHIEU_2, "Fee đích phải TĂNG đúng phần dư"
    assert f1.paid_amount + f2.paid_amount == tong_fee_truoc, (
        "tổng hai khoản phí đã đổi — tiền bị nhân lên hoặc bốc hơi"
    )


# ---------------------------------------------------------------------------
# REFUND THƯỜNG — fail-closed khi còn khoản dư chưa giải quyết
# ---------------------------------------------------------------------------

async def _tao_so_du(client: AsyncClient, boi_canh: dict) -> int:
    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "RF-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "RF-2")
    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put(f"/api/payments/{p1}/verify", headers=h_checker)
    await client.put(f"/api/payments/{p2}/verify", headers=h_checker)
    return p2


async def test_refund_thuong_bi_chan_khi_con_khoan_du_pending(
    client: AsyncClient, boi_canh: dict
):
    """Hoàn qua đường thường chỉ rút tiền khỏi hóa đơn; nó KHÔNG đóng được
    nghĩa vụ khoản dư. Nếu cho qua, có thể hoàn 70.000 rồi vẫn apply hoặc hoàn
    khoản ấy LẦN NỮA.
    """
    p2 = await _tao_so_du(client, boi_canh)
    h = await _dang_nhap(client, boi_canh["maker"])

    r = await client.post(
        "/api/refunds",
        json={
            "payment_id": p2,
            "amount": str(_PHIEU_2),
            "reason": "hoàn phần dư qua đường thường",
        },
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "khoản dư" in r.text.lower()

    async with AsyncSessionLocal() as db:
        con = (
            await db.execute(
                select(OverpaymentRecord).where(
                    OverpaymentRecord.payment_id == p2
                )
            )
        ).scalar_one()
        assert con.status == "pending", "khoản dư phải còn nguyên trạng"


@pytest.mark.parametrize(
    "trang_thai",
    ["pending", "applied", "cancelled"],
)
async def test_ma_tran_refund_thuong_bi_chan_theo_trang_thai_khoan_du(
    client: AsyncClient, boi_canh: dict, trang_thai: str
):
    """Ba ô ÂM của ma trận: nghĩa vụ chưa chi thì đường thường phải đóng.

    Cả ba đều là tiền chưa ra khỏi két: cho hoàn qua đường thường là rút tiền
    khỏi hoá đơn mà vẫn để lại nghĩa vụ nguyên vẹn, và khoản ấy sau đó vẫn
    apply/refund được LẦN NỮA.

    Ô DƯƠNG (`refunded` ⇒ cho qua) nằm ở
    `test_hoan_thuong_duoc_phep_khi_khoan_du_da_hoan_that`, chạy qua vòng đời
    thật. Không gộp vào đây: dựng `refunded` bằng một phép UPDATE thì ô dương
    chỉ chứng minh guard đọc được chuỗi ký tự.
    """
    p2 = await _tao_so_du(client, boi_canh)

    async with AsyncSessionLocal() as db:
        con = (
            await db.execute(
                select(OverpaymentRecord).where(OverpaymentRecord.payment_id == p2)
            )
        ).scalar_one()
        con.status = trang_thai
        await db.commit()

    h = await _dang_nhap(client, boi_canh["maker"])
    r = await client.post(
        "/api/refunds",
        json={
            "payment_id": p2,
            "amount": str(_PHIEU_2),
            "reason": "hoan khi khoan du dang " + trang_thai,
        },
        headers=h,
    )

    assert r.status_code == 400, (
        "khoan du '" + trang_thai + "' la nghia vu chua chi ma duong hoan thuong "
        "van cho qua — " + str(r.status_code) + ": " + r.text
    )
    assert "khoản dư" in r.text.lower()


async def test_refund_qua_luong_khoan_du_khong_bi_guard_chan(
    client: AsyncClient, boi_canh: dict
):
    """Luồng khoản dư đi qua CHÍNH hàm mang guard, với `source='overpayment'`.

    Chặn nó là chặn đúng con đường mà thông điệp lỗi bảo người dùng phải đi —
    khoản dư khi ấy không giải quyết được bằng bất kỳ cách nào. Ca này khoá
    nhánh miễn trừ ấy lại.
    """
    p2 = await _tao_so_du(client, boi_canh)

    async with AsyncSessionLocal() as db:
        so_id = (
            await db.execute(
                select(OverpaymentRecord.id).where(OverpaymentRecord.payment_id == p2)
            )
        ).scalar_one()

    # Giải quyết khoản dư là quyền ACCOUNTANT (write-off mới là manager-only);
    # đăng nhập lại ngay trước lượt gọi vì client dùng chung cookie jar.
    h = await _dang_nhap(client, boi_canh["maker"])
    r = await client.post(
        "/api/overpayments/" + str(so_id) + "/refund",
        json={"overpayment_id": so_id, "notes": "hoan phan du dung luong"},
        headers=h,
    )
    assert r.status_code in (200, 201), (
        "luong khoan du bi chinh guard cua no chan — "
        + str(r.status_code) + ": " + r.text
    )


async def test_audit_cung_fee_du_hai_ve_va_tong_bang_khong(
    client: AsyncClient, boi_canh: dict, seed_lead_dependencies: dict
):
    """Chuyển giữa hai đợt của CÙNG khoản phí vẫn phải để lại đủ hai vế.

    Ở ca này `fee.paid_amount` đứng yên. Nếu sổ chỉ ghi vế `+apply_amount` thì
    mọi báo cáo cộng cột `amount` của `adjustment` sẽ thấy tiền phình ra đúng
    chừng ấy trong khi số dư không nhúc nhích.

    Khoá thêm bất biến từng dòng: ``balance_after == balance_before - amount``.
    Một cặp ±X mà cả hai dòng đều `before == after` vẫn cộng bằng 0 nhưng nói
    dối về đường đi của tiền.
    """
    from app.models.finance import Fee
    from app.services.overpayment_service import OverpaymentService

    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "AUDIT-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "AUDIT-2")
    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put("/api/payments/" + str(p1) + "/verify", headers=h_checker)
    await client.put("/api/payments/" + str(p2) + "/verify", headers=h_checker)

    async with AsyncSessionLocal() as db:
        fee = (
            await db.execute(select(Fee).where(Fee.id == boi_canh["fee_id"]))
        ).scalar_one()
        fee.final_amount = fee.final_amount + _PHIEU_2
        dich = Invoice(
            fee_id=fee.id,
            invoice_number="INV-AUDIT-2",
            installment_no=2,
            amount=_PHIEU_2,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=60),
        )
        db.add(dich)
        await db.commit()
        dich_id = dich.id
        so_id = (
            await db.execute(
                select(OverpaymentRecord.id).where(
                    OverpaymentRecord.invoice_id == boi_canh["invoice_id"]
                )
            )
        ).scalar_one()

    async with AsyncSessionLocal() as db:
        await OverpaymentService(db).apply_to_invoice(
            overpayment_id=so_id,
            target_invoice_id=dich_id,
            user_id=boi_canh["checker"]["id"],
            unit_id=seed_lead_dependencies["unit_id"],
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        dong = (
            (
                await db.execute(
                    select(PaymentTransaction)
                    .where(
                        PaymentTransaction.external_reference
                        == "OVERPAY-" + str(so_id)
                    )
                    .order_by(PaymentTransaction.id)
                )
            )
            .scalars()
            .all()
        )

    assert len(dong) == 2, (
        "phep chuyen de lai " + str(len(dong)) + " ve, phai du hai ve mang cung "
        "ma OVERPAY-" + str(so_id)
    )
    assert sum(d.amount for d in dong) == 0, (
        "tong hai ve khac 0 — so noi co tien chay vao trong khi so du khoan "
        "phi dung yen"
    )
    assert {d.amount for d in dong} == {_PHIEU_2, -_PHIEU_2}
    for d in dong:
        assert d.balance_after == d.balance_before - d.amount, (
            "dong #" + str(d.id) + ": balance " + str(d.balance_before) + " -> "
            + str(d.balance_after) + " khong khop amount " + str(d.amount)
        )


async def test_thu_tu_khoa_invoice_truoc_roi_fee_theo_id_tang_dan(
    client: AsyncClient,
    boi_canh: dict,
    seed_lead_dependencies: dict,
    admin_user_in_db: dict,
):
    """Quy ước thứ tự khoá (#541): invoice trước — id tăng dần — rồi mới fee.

    Xin một khoá Invoice SAU khi đã cầm Fee mở lại đúng chu kỳ mà quy ước dựng
    lên để tránh: hai lượt áp khoản dư ngược chiều (X→Y và Y→X) ôm chéo nhau và
    Postgres bắn 40P01.

    Ca này soi trình tự khoá thực tế thay vì dựng hai phiên tranh chấp: nó bắt
    được vi phạm một cách xác định, không phụ thuộc `deadlock_timeout` hay may
    rủi lịch chạy. Đổi lại, nó KHÔNG chứng minh 40P01 biến mất — nó chứng minh
    tiền đề của 40P01 không còn.
    """
    from app.models.finance import Fee, FeeStatusEnum
    from app.services.overpayment_service import OverpaymentService

    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_1, "LOCK-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_2, "LOCK-2")
    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put("/api/payments/" + str(p1) + "/verify", headers=h_checker)
    await client.put("/api/payments/" + str(p2) + "/verify", headers=h_checker)

    async with AsyncSessionLocal() as db:
        fee2 = Fee(
            admission_profile_id=boi_canh["profile_id"],
            fee_type="other",
            academic_year=2025,
            base_amount=_PHIEU_2,
            final_amount=_PHIEU_2,
            status=FeeStatusEnum.invoiced.value,
        )
        db.add(fee2)
        await db.flush()
        dich = Invoice(
            fee_id=fee2.id,
            invoice_number="INV-LOCK-XFEE",
            installment_no=1,
            amount=_PHIEU_2,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=60),
        )
        db.add(dich)
        await db.commit()
        dich_id = dich.id
        so_id = (
            await db.execute(
                select(OverpaymentRecord.id).where(
                    OverpaymentRecord.invoice_id == boi_canh["invoice_id"]
                )
            )
        ).scalar_one()

    trinh_tu: list = []

    async with AsyncSessionLocal() as db:
        svc = OverpaymentService(db)

        goc_khoa_tap = svc.invoice_repo.khoa_invoice_theo_id
        goc_khoa_le = svc.invoice_repo.get_for_update
        goc_khoa_fee = svc.fee_repo.get_for_update

        async def _spy_tap(invoice_ids, unit_id=None):
            for _i in sorted(set(invoice_ids)):
                trinh_tu.append(("invoice", _i))
            return await goc_khoa_tap(invoice_ids, unit_id)

        async def _spy_le(invoice_id, unit_id=None):
            trinh_tu.append(("invoice", invoice_id))
            return await goc_khoa_le(invoice_id, unit_id)

        async def _spy_fee(fee_id, unit_id=None):
            trinh_tu.append(("fee", fee_id))
            return await goc_khoa_fee(fee_id, unit_id)

        svc.invoice_repo.khoa_invoice_theo_id = _spy_tap
        svc.invoice_repo.get_for_update = _spy_le
        svc.fee_repo.get_for_update = _spy_fee

        await svc.apply_to_invoice(
            overpayment_id=so_id,
            target_invoice_id=dich_id,
            user_id=boi_canh["checker"]["id"],
            unit_id=seed_lead_dependencies["unit_id"],
        )
        await db.commit()

    inv = [i for loai, i in trinh_tu if loai == "invoice"]
    fee_ids = [i for loai, i in trinh_tu if loai == "fee"]
    assert len(inv) == 2 and len(fee_ids) == 2, (
        "ca nay phai cham dung hai invoice va hai fee, da ghi: " + str(trinh_tu)
    )

    vi_tri_fee_dau = next(i for i, (loai, _) in enumerate(trinh_tu) if loai == "fee")
    vi_tri_inv_cuoi = max(
        i for i, (loai, _) in enumerate(trinh_tu) if loai == "invoice"
    )
    assert vi_tri_inv_cuoi < vi_tri_fee_dau, (
        "co khoa Invoice duoc xin SAU khi da cam Fee — dung thu quy uoc cam. "
        "Trinh tu: " + str(trinh_tu)
    )
    assert inv == sorted(inv), "invoice khong khoa theo id tang dan: " + str(inv)
    assert fee_ids == sorted(fee_ids), (
        "fee khong khoa theo id tang dan: " + str(fee_ids)
    )


# Phiếu chứa CẢ gốc lẫn dư — điều kiện bắt buộc của ca dương bên dưới. Với
# fixture 8.000.000 + 70.000 thì phần dư CHÍNH LÀ toàn bộ phiếu: hoàn nó đi rồi
# thì phiếu còn 0 đồng, và lượt hoàn thường tiếp theo bị chặn vì hết tiền chứ
# không phải vì guard cho qua. Ca ấy xanh mà không chứng minh được gì.
_PHIEU_GOC_MOT_PHAN = Decimal("7900000")  # hoá đơn còn nợ 100.000
_PHIEU_GOC_VA_DU = Decimal("170000")  # 100.000 gốc + 70.000 dư
_PHAN_GOC_CON_LAI = Decimal("100000")


async def test_hoan_thuong_duoc_phep_khi_khoan_du_da_hoan_that(
    client: AsyncClient, boi_canh: dict
):
    """Ô dương của ma trận, đi qua VÒNG ĐỜI THẬT chứ không gán trạng thái tay.

    `refund_overpayment` KHÔNG đặt record sang 'refunded' — nó để 'pending' và
    chỉ gắn `refund_request_id`; record chỉ đóng khi phiếu hoàn ấy được duyệt và
    CHI (`process_approved_refund`). Gán thẳng `status='refunded'` trong DB bỏ
    qua đúng đoạn ấy, nên ca cũ chứng minh guard đọc được một chuỗi ký tự, không
    chứng minh guard mở đúng lúc trong đời thật.

    Phiếu ở đây mang 100.000 gốc + 70.000 dư: sau khi phần dư đã chi, phần gốc
    vẫn phải hoàn được qua đường thường.
    """
    h_maker = await _dang_nhap(client, boi_canh["maker"])
    p1 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_GOC_MOT_PHAN, "RFD-1")
    p2 = await _ghi_phieu(client, h_maker, boi_canh, _PHIEU_GOC_VA_DU, "RFD-2")

    h_checker = await _dang_nhap(client, boi_canh["checker"])
    await client.put("/api/payments/" + str(p1) + "/verify", headers=h_checker)
    await client.put("/api/payments/" + str(p2) + "/verify", headers=h_checker)

    async with AsyncSessionLocal() as db:
        so = (
            await db.execute(
                select(OverpaymentRecord).where(OverpaymentRecord.payment_id == p2)
            )
        ).scalar_one()
        so_id, so_tien_du = so.id, so.overpayment_amount

    assert so_tien_du == _PHIEU_GOC_VA_DU - _PHAN_GOC_CON_LAI, (
        "bối cảnh sai: phần dư phải NHỎ HƠN phiếu thu, nếu không ca này không "
        "phân biệt được 'guard mở' với 'phiếu đã hết tiền'"
    )

    # 1) Hoàn phần dư qua đúng luồng khoản dư (accountant).
    h = await _dang_nhap(client, boi_canh["maker"])
    r = await client.post(
        "/api/overpayments/" + str(so_id) + "/refund",
        json={"overpayment_id": so_id, "notes": "hoan phan du"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text

    async with AsyncSessionLocal() as db:
        so = (
            await db.execute(
                select(OverpaymentRecord).where(OverpaymentRecord.id == so_id)
            )
        ).scalar_one()
        refund_id = so.refund_request_id
        assert so.status == "pending", (
            "record phải còn 'pending' cho tới khi phiếu hoàn được CHI — nếu nó "
            "đã 'refunded' ngay đây thì nghĩa vụ đóng trước khi tiền ra khỏi két"
        )
    assert refund_id is not None, "luồng khoản dư không gắn refund_request_id"

    # 2) Duyệt (manager) rồi chi (accountant) — maker-checker.
    h_checker = await _dang_nhap(client, boi_canh["checker"])
    r = await client.post(
        "/api/refunds/" + str(refund_id) + "/approve",
        json={"refund_id": refund_id, "approve": True},
        headers=h_checker,
    )
    assert r.status_code in (200, 201), r.text

    h = await _dang_nhap(client, boi_canh["maker"])
    r = await client.post(
        "/api/refunds/" + str(refund_id) + "/process",
        json={"refund_id": refund_id},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text

    async with AsyncSessionLocal() as db:
        so = (
            await db.execute(
                select(OverpaymentRecord).where(OverpaymentRecord.id == so_id)
            )
        ).scalar_one()
        assert so.status == "refunded", (
            "chi xong mà nghĩa vụ chưa đóng — record vẫn " + str(so.status)
        )

    # 3) Giờ mới tới điều cần chứng minh: phần GỐC hoàn được qua đường thường.
    h = await _dang_nhap(client, boi_canh["maker"])
    r = await client.post(
        "/api/refunds",
        json={
            "payment_id": p2,
            "amount": str(_PHAN_GOC_CON_LAI),
            "reason": "hoan phan goc con lai",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), (
        "khoản dư đã chi và đã đóng sổ mà guard vẫn chặn — phần gốc của phiếu "
        "thu không hoàn được nữa. " + str(r.status_code) + ": " + r.text
    )
