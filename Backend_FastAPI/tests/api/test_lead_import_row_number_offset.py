"""Số dòng báo cho người dùng phải khớp dòng trong tệp họ đang mở.

Template chính thức (``GET /api/leads/import/template``) mở đầu bằng **7 dòng**
``#`` rồi mới tới hàng tiêu đề. ``_bo_chu_thich_dau_tep`` cắt phần đầu đó để
pandas đọc được, nhưng chỉ số dòng của pandas vì thế lùi đi đúng 7 — nên trước
bản vá, dòng dữ liệu đầu tiên (thực tế nằm ở **dòng 9**) được báo là "Dòng 2".

Người nhập mở tệp lên, tới dòng 2, thấy một dòng chú thích và không hiểu hệ
thống đang nói gì.
"""

import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from tests.fixtures.constants import LeadsURLs

log = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio

# Đúng số dòng `#` mà router sinh ra. Đổi template mà quên số này thì test đỏ —
# đó là chủ ý: hai nơi phải đi cùng nhau.
SO_DONG_CHU_THICH_TEMPLATE = 7


@pytest_asyncio.fixture(scope="function")
async def _initial_status_legacy_marker(seed_lead_dependencies):
    """Xem chú thích cùng tên ở ``test_lead_import.py``."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(models.ConsultationStatus).where(
                        models.ConsultationStatus.id == INITIAL_LEAD_STATUS_ID
                    )
                )
            ).scalar_one()
            row.legacy_status = "new"
            row.is_final = False
    return seed_lead_dependencies


async def test_template_that_bao_dung_so_dong(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Tải template THẬT → làm hỏng đúng dòng dữ liệu đầu → nhập lại.

    Không dựng tệp giả: chính template do hệ thống phát ra mới là thứ người dùng
    cầm trên tay, và cũng chính nó mang 7 dòng chú thích gây lệch.
    """
    # 1. Tải template thật.
    tai_ve = await client.get(
        f"{LeadsURLs.LEADS}/import/template", headers=admin_token_headers
    )
    assert tai_ve.status_code == 200, tai_ve.text
    noi_dung = tai_ve.text

    cac_dong = noi_dung.splitlines()
    so_dong_chu_thich = 0
    while so_dong_chu_thich < len(cac_dong) and cac_dong[so_dong_chu_thich].lstrip().startswith("#"):
        so_dong_chu_thich += 1

    assert so_dong_chu_thich == SO_DONG_CHU_THICH_TEMPLATE, (
        f"template đổi số dòng chú thích ({so_dong_chu_thich}) — cập nhật hằng số "
        f"và kiểm lại phần bù `row_number`"
    )

    # Hàng tiêu đề ngay sau phần chú thích; dòng dữ liệu đầu nằm liền kế.
    chi_so_dong_du_lieu = so_dong_chu_thich + 1  # 0-based
    so_dong_nguoi_dung_thay = chi_so_dong_du_lieu + 1  # 1-based, đúng thứ họ mở ra
    assert so_dong_nguoi_dung_thay == 9

    # 2. Làm hỏng đúng dòng dữ liệu ví dụ: bỏ trống số điện thoại.
    cot = cac_dong[so_dong_chu_thich].split(",")
    vi_tri_phone = cot.index("phone")
    o_du_lieu = cac_dong[chi_so_dong_du_lieu].split(",")
    o_du_lieu[vi_tri_phone] = ""
    cac_dong[chi_so_dong_du_lieu] = ",".join(o_du_lieu)
    tep_hong = ("\n".join(cac_dong) + "\n").encode("utf-8")

    # 3. Nhập lại.
    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("template_sua.csv", tep_hong, "text/csv")},
        headers=officer_token_headers,
    )
    assert phan_hoi.status_code == 200, phan_hoi.text
    kq = phan_hoi.json()

    assert kq["failed_imports"] >= 1, f"dòng hỏng không bị bắt: {kq}"
    so_dong_bao_ve = [e["row_number"] for e in kq["errors"] if e["row_number"] > 0]
    assert so_dong_bao_ve, f"không có lỗi nào gắn với dòng: {kq['errors']}"
    assert so_dong_nguoi_dung_thay in so_dong_bao_ve, (
        f"báo sai dòng: hệ thống nói {so_dong_bao_ve}, thực tế dòng "
        f"{so_dong_nguoi_dung_thay} trong tệp"
    )


async def test_tep_khong_co_chu_thich_van_bao_dung_so_dong(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Phần bù chỉ được áp khi THẬT SỰ có cắt phần đầu.

    Cộng nhầm vào tệp thường sẽ đẩy mọi số dòng lệch theo chiều ngược lại — lỗi
    y hệt, chỉ đổi dấu.
    """
    tep = (
        b"full_name,phone,source\n"
        b"Nguyen Van A,0901239001,website\n"
        b"Nguyen Van B,,website\n"  # dòng 3: thiếu SĐT
    )

    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("khong_chu_thich.csv", tep, "text/csv")},
        headers=officer_token_headers,
    )
    assert phan_hoi.status_code == 200, phan_hoi.text
    kq = phan_hoi.json()

    so_dong_bao_ve = [e["row_number"] for e in kq["errors"] if e["row_number"] > 0]
    assert so_dong_bao_ve == [3], f"tệp không có chú thích mà vẫn bị bù: {kq['errors']}"
