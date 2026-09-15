"""Ba nhánh của hợp đồng "giá HK1" trên ``POST /api/fees/calculate``.

Vì sao tệp này tồn tại
======================

``finance-lifecycle.spec.ts`` bước "Calculate fee" đỏ với **400**. Sổ nightly chỉ
ghi được ``detail=<str:107 h=80d29745>`` (thân lỗi bị lọc để không rò PII), và
phép kiểm khi ấy là GỘP::

    expect(resp.ok() || resp.status() === 201).toBeTruthy();

nên nó nhận cả 200/202/204 và khi đỏ chỉ in "Received: false".

Đo cục bộ trên CSDL dựng theo ĐÚNG chuỗi nightly (``alembic upgrade head`` →
``scripts.seed_from_xlsx``): ``offering_semester_tuition = 0`` hàng, trong khi
``offering_academic_info = 23`` và ``admission_path = 52``. Gọi thẳng hàm sản
phẩm ``FeeCalculationService._semester_tuition_amount_for_ai(1, 1)`` cho ra
nguyên văn câu 400 có ``len=107`` và ``FNV-1a = 80d29745`` — TRÙNG KHÍT dòng
nightly. Hai câu 400 khác của cùng endpoint KHÔNG trùng (thiếu kế hoạch ``FULL``
``h=7cfcd3fa``; hồ sơ không đủ điều kiện ``h=68dad46e``), và ``FULL`` thì CÓ
trong CSDL. ⇒ Thiếu **dữ liệu danh mục**, service trả 400 ĐÚNG HỢP ĐỒNG.

Tệp này khoá hợp đồng ấy lại bằng ba ca, **mỗi ca một bất biến**:

1. thiếu hàng HK1 ⇒ 400 đúng câu ấy, và ``fee`` / ``invoice`` KHÔNG sinh thêm
   hàng nào (đếm trước/sau, cả toàn cục lẫn theo hồ sơ);
2. có ĐÚNG MỘT hàng HK1 ⇒ ``tuition-preview`` 200, ``calculate`` 201, sinh ĐÚNG
   MỘT ``fee`` và ĐÚNG MỘT ``invoice``;
3. GỠ hàng HK1 đi ⇒ quay lại ĐÚNG câu 400 ấy (kiểm ngược: chứng minh ca 2 xanh
   vì hàng giá, không vì thứ gì khác).

Cộng một ca "ca kiểm có đủ mạnh không": nếu fixture danh mục đã sẵn hàng HK1 thì
ca 1 xanh mà chẳng chứng minh gì.

KHÔNG chép lại bộ dựng hồ sơ: dùng lại ``fee_calc_config`` +
``_create_approved_profile`` của ``test_fees_calculate_authorization`` (cùng
endpoint, cùng cổng submit/approve). Hai bản dựng song song là hai cơ hội drift.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal

# Fixture + helper dùng CHUNG với bộ authz của chính endpoint này.
from tests.api.test_fees_calculate_authorization import (  # noqa: F401
    _create_approved_profile,
    fee_calc_config,
)

pytestmark = pytest.mark.asyncio

FEES_CALCULATE = "/api/fees/calculate"
TUITION_PREVIEW = "/api/fees/tuition-preview"

#: Giá HK1 dùng cho nhánh "có đúng một hàng". CỐ Ý KHÁC
#: ``tuition_fee_per_year`` của fixture (5.000.000) để một hồi quy trong đó
#: đường định giá lặng lẽ rơi về ``tuition_fee_per_year`` lộ ra bằng CON SỐ chứ
#: không chỉ bằng mã trạng thái.
GIA_HK1 = Decimal("6500000.00")
TUITION_FEE_PER_YEAR_CUA_FIXTURE = Decimal("5000000.00")

#: Đầu câu 400 của ``_semester_tuition_amount_for_ai``
#: (``fee_calculation_service.py``). So ĐẦU CÂU, không so cả câu, vì phần đuôi
#: mang ``academic_info_id`` đổi theo lượt chạy.
DAU_CAU_400 = "Chưa cấu hình học phí cho HK1"


# ---------------------------------------------------------------------------
# Đo trạng thái thật
# ---------------------------------------------------------------------------

async def _academic_info_id_cua(profile_id: int) -> int:
    """Ngành mà đường TÍNH PHÍ sẽ định giá — qua ĐÚNG hàm sản phẩm.

    Không tự suy từ fixture: ``resolve_fee_academic_info`` là nguồn chuẩn dùng
    chung của router lẫn service, nên hỏi nó là hỏi đúng chỗ.
    """
    from app.services.fee_calculation_service import resolve_fee_academic_info

    async with AsyncSessionLocal() as s:
        profile = (
            await s.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()
        ai = await resolve_fee_academic_info(s, profile)
        return ai.id


async def _dem_hang_hk1(academic_info_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(models.OfferingSemesterTuition)
                .where(
                    models.OfferingSemesterTuition.academic_info_id
                    == academic_info_id,
                    models.OfferingSemesterTuition.semester_no == 1,
                )
            )
        ).scalar_one()


async def _go_hang_hk1(academic_info_id: int) -> int:
    """Xoá hàng giá HK1 của ngành. Trả về SỐ HÀNG đã xoá (đo, không đoán)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            hang = (
                await s.execute(
                    select(models.OfferingSemesterTuition).where(
                        models.OfferingSemesterTuition.academic_info_id
                        == academic_info_id,
                        models.OfferingSemesterTuition.semester_no == 1,
                    )
                )
            ).scalars().all()
            for h in hang:
                await s.delete(h)
            return len(hang)


async def _dat_hang_hk1(academic_info_id: int, amount: Decimal) -> None:
    """Đặt ĐÚNG MỘT hàng giá HK1 với số tiền cho trước (get-or-update)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            co_san = (
                await s.execute(
                    select(models.OfferingSemesterTuition).where(
                        models.OfferingSemesterTuition.academic_info_id
                        == academic_info_id,
                        models.OfferingSemesterTuition.semester_no == 1,
                    )
                )
            ).scalar_one_or_none()
            if co_san is None:
                s.add(
                    models.OfferingSemesterTuition(
                        academic_info_id=academic_info_id,
                        semester_no=1,
                        amount=amount,
                    )
                )
            else:
                co_san.amount = amount


async def _dem_tien() -> dict[str, int]:
    """Tổng số hàng ``fee`` và ``invoice`` TOÀN BẢNG.

    Toàn bảng chứ không chỉ theo hồ sơ: một bản vá làm rò một ``Fee`` mồ côi
    (không gắn hồ sơ đang đo) vẫn phải bị nhìn thấy.
    """
    async with AsyncSessionLocal() as s:
        return {
            "fee": (
                await s.execute(select(func.count()).select_from(models.Fee))
            ).scalar_one(),
            "invoice": (
                await s.execute(select(func.count()).select_from(models.Invoice))
            ).scalar_one(),
        }


async def _dem_tien_cua_ho_so(profile_id: int) -> dict[str, int]:
    async with AsyncSessionLocal() as s:
        so_fee = (
            await s.execute(
                select(func.count())
                .select_from(models.Fee)
                .where(models.Fee.admission_profile_id == profile_id)
            )
        ).scalar_one()
        so_invoice = (
            await s.execute(
                select(func.count())
                .select_from(models.Invoice)
                .join(models.Fee, models.Invoice.fee_id == models.Fee.id)
                .where(models.Fee.admission_profile_id == profile_id)
            )
        ).scalar_one()
        return {"fee": so_fee, "invoice": so_invoice}


async def _tinh_phi(client: AsyncClient, headers: dict, profile_id: int):
    """Gọi endpoint THẬT với ĐÚNG payload mà ``finance-lifecycle.spec.ts`` gửi.

    Cố ý KHÔNG gửi ``semester_no`` — spec E2E cũng không gửi, và việc chuẩn hoá
    về HK1 nằm trong ``calculate_fee``. Gửi thêm trường ở đây sẽ là dựng ca theo
    hình dung thay vì theo đường thật.
    """
    return await client.post(
        FEES_CALCULATE,
        json={
            "admission_profile_id": profile_id,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
        },
        headers=headers,
    )


@pytest_asyncio.fixture
async def ho_so_da_duyet(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,  # noqa: F811 — fixture nhập từ module authz
) -> dict:
    """Hồ sơ đã duyệt + ngành đã giải + số hàng giá HK1 hiện có."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="HK1 Probe",
    )
    ai_id = await _academic_info_id_cua(pid)
    return {"profile_id": pid, "academic_info_id": ai_id}


# ---------------------------------------------------------------------------
# 0. Ca kiểm có đủ mạnh không
# ---------------------------------------------------------------------------

async def test_ca_kiem_co_du_manh_khong(ho_so_da_duyet: dict):
    """Ba ca dưới đây vô nghĩa nếu KHÔNG gỡ nổi hàng giá HK1.

    ``fee_calc_config`` CÓ seed sẵn một hàng HK1 (đó là lý do bộ authz xanh).
    Ca 1 vì thế phải GỠ nó đi — và phải chứng minh là có cái để gỡ, nếu không
    "thiếu hàng" chỉ là một câu nói.
    """
    ai_id = ho_so_da_duyet["academic_info_id"]
    assert await _dem_hang_hk1(ai_id) == 1, (
        "fixture không seed hàng giá HK1 như giả định — ca 'gỡ hàng' bên dưới "
        "sẽ gỡ vào chỗ trống và không chứng minh gì"
    )
    assert (await _go_hang_hk1(ai_id)) == 1
    assert await _dem_hang_hk1(ai_id) == 0


# ---------------------------------------------------------------------------
# 1. THIẾU hàng HK1 ⇒ 400 đúng câu ấy, KHÔNG sinh fee/invoice
# ---------------------------------------------------------------------------

async def test_thieu_hang_HK1_thi_400_va_khong_sinh_fee_hay_invoice(
    client: AsyncClient,
    admin_token_headers: dict,
    ho_so_da_duyet: dict,
):
    pid = ho_so_da_duyet["profile_id"]
    ai_id = ho_so_da_duyet["academic_info_id"]
    assert (await _go_hang_hk1(ai_id)) == 1
    assert await _dem_hang_hk1(ai_id) == 0

    truoc = await _dem_tien()
    truoc_ho_so = await _dem_tien_cua_ho_so(pid)

    resp = await _tinh_phi(client, admin_token_headers, pid)

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body.get("error_code") == "HTTP_400", body
    assert body.get("detail", "").startswith(DAU_CAU_400), body
    assert f"academic_info_id={ai_id}" in body["detail"], body

    sau = await _dem_tien()
    sau_ho_so = await _dem_tien_cua_ho_so(pid)
    assert sau == truoc, f"400 mà vẫn ghi tiền: trước={truoc} sau={sau}"
    assert sau_ho_so == truoc_ho_so == {"fee": 0, "invoice": 0}, (
        f"trước={truoc_ho_so} sau={sau_ho_so}"
    )


# ---------------------------------------------------------------------------
# 2. CÓ ĐÚNG MỘT hàng HK1 ⇒ preview 200 · calculate 201 · 1 fee + 1 invoice
# ---------------------------------------------------------------------------

async def test_co_dung_mot_hang_HK1_thi_preview_200_calculate_201_va_mot_fee_mot_invoice(
    client: AsyncClient,
    admin_token_headers: dict,
    ho_so_da_duyet: dict,
):
    pid = ho_so_da_duyet["profile_id"]
    ai_id = ho_so_da_duyet["academic_info_id"]
    await _dat_hang_hk1(ai_id, GIA_HK1)
    assert await _dem_hang_hk1(ai_id) == 1

    truoc = await _dem_tien()
    assert await _dem_tien_cua_ho_so(pid) == {"fee": 0, "invoice": 0}

    pv = await client.get(
        TUITION_PREVIEW,
        params={"admission_profile_id": pid, "semester_no": 1},
        headers=admin_token_headers,
    )
    assert pv.status_code == 200, pv.text
    assert Decimal(str(pv.json()["base_amount"])) == GIA_HK1, (
        "preview không đọc giá HK1 của danh mục — số này KHÁC "
        f"tuition_fee_per_year ({TUITION_FEE_PER_YEAR_CUA_FIXTURE}) đúng để "
        "một lần rơi về cột cũ là thấy ngay"
    )

    resp = await _tinh_phi(client, admin_token_headers, pid)
    assert resp.status_code == 201, resp.text
    fee = resp.json()
    assert Decimal(str(fee["base_amount"])) == GIA_HK1, fee

    sau_ho_so = await _dem_tien_cua_ho_so(pid)
    assert sau_ho_so == {"fee": 1, "invoice": 1}, sau_ho_so
    sau = await _dem_tien()
    assert sau == {"fee": truoc["fee"] + 1, "invoice": truoc["invoice"] + 1}, (
        f"trước={truoc} sau={sau} — phải sinh ĐÚNG một fee và ĐÚNG một invoice"
    )


# ---------------------------------------------------------------------------
# 3. KIỂM NGƯỢC — gỡ hàng HK1 ⇒ quay lại ĐÚNG 400 ấy
# ---------------------------------------------------------------------------

async def test_go_hang_HK1_thi_quay_lai_dung_400_ay(
    client: AsyncClient,
    admin_token_headers: dict,
    ho_so_da_duyet: dict,
):
    """Ca 2 xanh vì HÀNG GIÁ, không vì thứ gì khác.

    Hồ sơ y hệt, payload y hệt, chỉ khác đúng một hàng danh mục. Không đỏ ở đây
    nghĩa là ca 2 đang xanh nhờ một lý do chưa biết tên.
    """
    pid = ho_so_da_duyet["profile_id"]
    ai_id = ho_so_da_duyet["academic_info_id"]

    await _dat_hang_hk1(ai_id, GIA_HK1)
    assert await _dem_hang_hk1(ai_id) == 1
    xanh = await _tinh_phi(client, admin_token_headers, pid)
    assert xanh.status_code == 201, xanh.text
    ma_fee = xanh.json()["id"]

    # Dọn fee vừa tạo: giữ lại thì lượt sau dừng ở "Học phí HK1 đã được tính"
    # (409/400 của phép chống trùng) — một câu 400 KHÁC, và ca này sẽ xanh vì
    # lý do sai.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for inv in (
                await s.execute(
                    select(models.Invoice).where(models.Invoice.fee_id == ma_fee)
                )
            ).scalars().all():
                await s.delete(inv)
            await s.delete(await s.get(models.Fee, ma_fee))
    assert await _dem_tien_cua_ho_so(pid) == {"fee": 0, "invoice": 0}

    assert (await _go_hang_hk1(ai_id)) == 1
    assert await _dem_hang_hk1(ai_id) == 0

    do = await _tinh_phi(client, admin_token_headers, pid)
    assert do.status_code == 400, do.text
    assert do.json().get("detail", "").startswith(DAU_CAU_400), do.json()
    assert await _dem_tien_cua_ho_so(pid) == {"fee": 0, "invoice": 0}
