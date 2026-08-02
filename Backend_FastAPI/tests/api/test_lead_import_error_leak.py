"""Chi tiết lỗi hạ tầng KHÔNG được đi ra tới màn hình người dùng.

Đường rò: trong vòng xử lý từng dòng, ``calculate_lead_score()`` có truy vấn cơ
sở dữ liệu. Một ``OperationalError``/``DBAPIError`` từ đó không phải
``ValueError``/``TypeError``, nên nó rơi xuống nhánh bắt-tất-cả — nơi trước đây
ghép thẳng ``{e}`` vào ``error_message``. Chuỗi ấy mang câu SQL kèm **tham số**,
tức dữ liệu của người khác, và giao diện in nguyên nó lên thông báo
(``useLeads.ts``).

Phép kiểm dùng một chuỗi mồi: nếu nó xuất hiện ở bất kỳ đâu trong phản hồi thì
đường rò còn đó. Mồi được đặt trong thông điệp ngoại lệ đúng như cách driver
nhét SQL vào.
"""

import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import lead_service
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from tests.conftest import create_mock_lead_file
from tests.fixtures.constants import LeadsURLs

log = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio

# Đại diện cho phần nguy hiểm của một thông điệp lỗi driver: câu lệnh + tham số.
MOI_BI_MAT = "SECRET_SQL_PARAMS"


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


@pytest.mark.parametrize(
    "lop_loi",
    [RuntimeError, TypeError, ValueError],
    ids=["RuntimeError", "TypeError", "ValueError"],
)
async def test_loi_ha_tang_khong_lot_ra_phan_hoi(
    lop_loi: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Lỗi hạ tầng giữa vòng xử lý dòng ⇒ thông báo chung, không kèm chi tiết."""

    async def _no_ha_tang(*args, **kwargs):
        # Mô phỏng đúng hình dạng thông điệp của driver: mô tả + SQL + tham số.
        #
        # 🔴 Chạy với NHIỀU lớp ngoại lệ, vì lỗ hổng nằm ở chỗ PHÂN LOẠI chứ không
        # ở chỗ định dạng: một mệnh đề `except (ValueError, TypeError)` coi là
        # "lỗi người dùng" sẽ trả nguyên văn, nên chỉ cần đổi lớp ngoại lệ là mồi
        # lọt ra — dù `RuntimeError` đã bị bịt. `ValueError` ở đây đến từ một hàm
        # KHÔNG phải tầng validate, nên nó cũng không được trả nguyên.
        raise lop_loi(
            "connection failed while executing "
            f"SELECT * FROM lead WHERE phone = '{MOI_BI_MAT}'"
        )

    monkeypatch.setattr(lead_service, "calculate_lead_score", _no_ha_tang)

    file_data = [
        {"full_name": "Nguyen Van A", "phone": "+84911500001", "source": "file_import"},
    ]

    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": create_mock_lead_file(file_data, file_format="csv")},
        headers=officer_token_headers,
    )

    assert phan_hoi.status_code == 200, phan_hoi.text
    kq = phan_hoi.json()

    # Dòng phải hỏng — nếu nó "thành công" thì mock không hề chạy và cả phép kiểm
    # này vô nghĩa.
    assert kq["failed_imports"] == 1, f"mock không chạy: {kq}"
    assert kq["successful_imports"] == 0

    # 🔴 Điểm chính: mồi không được xuất hiện ở BẤT KỲ đâu trong phản hồi.
    assert MOI_BI_MAT not in phan_hoi.text, (
        "chi tiết lỗi hạ tầng lọt ra phản hồi: " + phan_hoi.text[:400]
    )

    # Và người dùng vẫn phải nhận được một câu dùng được.
    thong_bao = " ".join(e["error_message"] for e in kq["errors"])
    assert thong_bao.strip(), "không có thông báo nào cho dòng hỏng"
    assert "SELECT" not in thong_bao.upper()


async def test_loi_du_lieu_van_giu_nguyen_thong_bao_cho_nguoi_nhap(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Chiều ngược lại — đừng bịt nhầm thứ người dùng CẦN đọc.

    Lỗi validate do chính hệ thống phát ra (SĐT sai định dạng, email trùng…) là
    tiếng Việt và viết cho người nhập. Gộp chúng vào một câu chung chung sẽ khiến
    họ không biết phải sửa ô nào.
    """
    file_data = [
        {"full_name": "Nguyen Van B", "phone": "khong-phai-so", "source": "file_import"},
    ]

    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": create_mock_lead_file(file_data, file_format="csv")},
        headers=officer_token_headers,
    )

    assert phan_hoi.status_code == 200, phan_hoi.text
    kq = phan_hoi.json()
    assert kq["failed_imports"] == 1

    thong_bao = " ".join(e["error_message"] for e in kq["errors"])
    assert "Số điện thoại" in thong_bao, (
        f"thông báo hữu ích bị bịt mất: {thong_bao}"
    )

MOI_NOI_DUNG_TEP = "SECRET_FILE_CONTENT"


@pytest.mark.parametrize(
    "lop_loi",
    [ValueError, RuntimeError],
    ids=["ValueError", "RuntimeError"],
)
async def test_loi_doc_tep_khong_lot_ra_phan_hoi(
    lop_loi: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """🔴 Đường ĐỌC TỆP có cái bẫy kín hơn vòng xử lý dòng.

    ``pandas.errors.ParserError`` **kế thừa ``ValueError``**, nên một mệnh đề
    ``except ValueError: raise`` — viết với ý "chuyển tiếp lỗi kiểm tra của
    mình" — lại chuyển thẳng thông điệp của pandas ra ngoài. Thông điệp đó mang
    một phần NỘI DUNG tệp (``Expected 2 fields in line 3, saw 3``).

    Chạy với cả ``ValueError`` để khoá đúng quan hệ kế thừa ấy.
    """

    def _no_khi_doc(*args, **kwargs):
        raise lop_loi(f"Error tokenizing data: {MOI_NOI_DUNG_TEP}")

    # `lead_service` import pandas BÊN TRONG hàm, nên phải vá thẳng ở module
    # gốc — vá qua `lead_service.pd` sẽ không có thuộc tính đó.
    import pandas

    monkeypatch.setattr(pandas, "read_csv", _no_khi_doc)

    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("hong.csv", b"full_name,phone\nA,0900000001\n", "text/csv")},
        headers=officer_token_headers,
    )

    assert MOI_NOI_DUNG_TEP not in phan_hoi.text, (
        "nội dung tệp lọt ra phản hồi: " + phan_hoi.text[:400]
    )
    assert "tokenizing" not in phan_hoi.text.lower()


async def test_loi_tep_co_y_van_giu_nguyen_thong_bao(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Chiều ngược lại: lỗi mức tệp do CHÍNH hàm phát ra vẫn phải tới người dùng."""
    phan_hoi = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("rong.csv", b"", "text/csv")},
        headers=officer_token_headers,
    )

    assert phan_hoi.status_code >= 400
    assert "rỗng" in phan_hoi.text.lower(), (
        f"thông báo hữu ích bị bịt mất: {phan_hoi.text[:300]}"
    )
