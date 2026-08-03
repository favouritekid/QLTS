"""Số điện thoại TOÀN ký tự phân cách không được làm hỏng cả lô nhập.

Đường đi của lỗi (trước bản vá):

1. ``normalize_vietnam_phone("---")`` gỡ hết ký tự trong ``PHONE_STRIP_CHARS``
   (`` \\t\\n\\r.-()/``) nên còn chuỗi rỗng ⇒ trả ``None``.
2. Validator của ``LeadCreate`` gặp ``None`` thì **trả nguyên chuỗi gốc** với lời
   hẹn "để ``min_length`` lo" — nhưng ``min_length=1`` thấy ``"---"`` dài 3 nên
   cho qua.
3. Trong ``import_leads_from_file_content``, CẢ HAI lớp chống trùng đều so trên
   bản chuẩn hoá (``phone_norm``), vốn là ``None`` ⇒ ``if phone_norm:`` bỏ qua.
4. Giá trị rác đi thẳng tới ``bulk_insert_leads`` và đâm unique index — làm hỏng
   **cả lô**, không riêng dòng của nó.

Vì vậy phép kiểm trung tâm không phải "dòng rác bị từ chối" mà là **những dòng
HỢP LỆ đi cùng lô vẫn vào được**.
"""

import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from tests.conftest import create_mock_lead_file
from tests.fixtures.constants import LeadsURLs

log = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="function")
async def _initial_status_legacy_marker(seed_lead_dependencies):
    """Đóng dấu ``legacy_status="new"`` cho TTHV000 — đường nhập lead tra trạng
    thái ban đầu qua ``StatusHelper.get_initial_status()``.

    Bản sao có chủ ý của fixture cùng tên trong ``test_lead_import.py``: nó là
    file-local ở đó (các suite khác phụ thuộc việc cột này giữ NULL), nên không
    import chéo được.
    """
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


@pytest.mark.parametrize("rac", ["---", "...", "( )", "//", "-", " - . - "])
async def test_sdt_toan_ky_tu_phan_cach_bi_tu_choi(
    rac: str,
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Từng biến thể rác đều phải bị chặn ở tầng validate, không lọt xuống DB."""
    file_data = [
        {"full_name": "SDT Rac", "phone": rac, "source": "file_import"},
    ]

    response = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": create_mock_lead_file(file_data, file_format="csv")},
        headers=officer_token_headers,
    )

    assert response.status_code == 200, response.text
    kq = response.json()
    assert kq["successful_imports"] == 0, f"'{rac}' lọt qua validate: {kq}"
    assert kq["failed_imports"] == 1
    assert kq["created_lead_ids"] == []


async def test_hai_dong_sdt_rac_khong_lam_hong_ca_lo(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """🔴 Ca trung tâm.

    Hai dòng cùng mang ``"---"``: trước bản vá chúng qua được validator, qua cả
    hai lớp chống trùng (vì bản chuẩn hoá là ``None``), rồi cùng đâm unique
    index ở ``bulk_insert_leads`` — kéo theo **cả lô**.

    Nên điều cần khẳng định là ba dòng hợp lệ đi cùng vẫn vào đủ.
    """
    file_data = [
        {"full_name": "Hop Le 1", "phone": "+84911300001", "source": "file_import"},
        {"full_name": "Rac 1", "phone": "---", "source": "file_import"},
        {"full_name": "Hop Le 2", "phone": "+84911300002", "source": "file_import"},
        {"full_name": "Rac 2", "phone": "---", "source": "file_import"},
        {"full_name": "Hop Le 3", "phone": "+84911300003", "source": "file_import"},
    ]

    response = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": create_mock_lead_file(file_data, file_format="csv")},
        headers=officer_token_headers,
    )

    assert response.status_code == 200, response.text
    kq = response.json()

    assert kq["total_rows_processed"] == 5
    assert kq["successful_imports"] == 3, (
        f"lô bị hỏng vì hai dòng rác: {kq['errors']}"
    )
    assert kq["failed_imports"] == 2
    assert len(kq["created_lead_ids"]) == 3

    # Ba lead hợp lệ phải CÓ THẬT trong DB — `created_lead_ids` được ném thẳng
    # vào payload `LEAD_IMPORTED`, nên id ma là lỗi lan sang hệ thông báo.
    async with AsyncSessionLocal() as session:
        so_ton_tai = (
            await session.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.id.in_(kq["created_lead_ids"])
                )
            )
        ).scalar_one()
        assert so_ton_tai == 3

        # Và tuyệt đối không có bản ghi nào mang số rác.
        so_rac = (
            await session.execute(
                select(func.count(models.Lead.id)).where(models.Lead.phone == "---")
            )
        ).scalar_one()
        assert so_rac == 0, "số điện thoại rác đã lọt xuống cơ sở dữ liệu"


async def test_sdt_phu_toan_ky_tu_phan_cach_cung_bi_tu_choi(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """`phone2` là nhánh anh em — cùng validator, cùng lỗ.

    Ô TRỐNG ở `phone2` vẫn phải hợp lệ (nó là trường tuỳ chọn); chỉ chuỗi rác
    mới bị chặn. Không phân biệt được hai thứ đó thì bản vá sẽ chặn nhầm mọi
    tệp không điền số phụ — tức phần lớn tệp thật.
    """
    file_data = [
        {
            "full_name": "Phu Rac",
            "phone": "+84911400001",
            "phone2": "---",
            "source": "file_import",
        },
        {
            "full_name": "Phu Trong",
            "phone": "+84911400002",
            "phone2": "",
            "source": "file_import",
        },
    ]

    response = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": create_mock_lead_file(file_data, file_format="csv")},
        headers=officer_token_headers,
    )

    assert response.status_code == 200, response.text
    kq = response.json()

    assert kq["successful_imports"] == 1, f"ô trống bị chặn nhầm: {kq['errors']}"
    assert kq["failed_imports"] == 1
