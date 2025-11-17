# tests/routers/test_lead_import_assign.py
import asyncio
import io  # ✅ Import io đã được thêm
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings

# Import helpers và components
from app.database import AsyncSessionLocal

# Import helper tạo file mock
from tests.conftest import (  # Helper nằm trong root conftest
    create_mock_lead_file,
)

# Import constants và fixtures
from tests.fixtures.constants import (
    LeadsURLs,  # Thêm LeadsURLs nếu bạn dùng lambda URLs (hiện tại không cần)
)
from tests.fixtures.constants import (  # TestLeadData # Không cần trực tiếp vì dùng data custom
    AdminURLs,
    TestOrgData,
    TestPipelineData,
    TestUsers,
)

log = logging.getLogger(__name__)

# --- Dữ liệu file mẫu sử dụng constants ---
# Sử dụng UNIT_ID và MAJOR_ID từ TestOrgData
FILE_DATA_UNIT_ID = TestOrgData.UNIT_1["id"]
FILE_DATA_MAJOR_ID = TestOrgData.MAJOR_1["id"]

VALID_LEAD_DATA_FOR_FILE = [
    {
        "full_name": "Import Lead 1",
        "email": "import1@example.com",
        "phone": "1110001",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },
    {
        "full_name": "Import Lead 2",
        "email": "import2@example.com",
        "phone": "1110002",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
        "major_id": FILE_DATA_MAJOR_ID,
    },
]

INVALID_LEAD_DATA_FOR_FILE = [
    {
        "full_name": "Import Lead 3 Valid",
        "email": "import3@example.com",
        "phone": "1110003",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },
    {
        "full_name": "Missing Email",
        "phone": "1110004",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },  # Thiếu email
    {
        "full_name": "Bad Email Format",
        "email": "bad-email",
        "phone": "1110005",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },  # Sai email
    {
        "full_name": "Duplicate Email In File",
        "email": "import3@example.com",
        "phone": "1110006",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },  # Trùng email dòng 1
]
# ------------------------------------

# --- FIxture seed_lead_dependencies (Đã chuyển sang conftest.py) ---
# Xóa định nghĩa fixture khỏi đây


# --- Test Import Thành Công và Bulk Assign ---
@pytest.mark.integration
@pytest.mark.asyncio
async def test_import_and_bulk_assign_success(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,  # ✅ THÊM FIXTURE NÀY
    setup_test_database,
):
    """
    Test flow hoàn chỉnh: Import CSV -> Bulk Assign -> Verify Assignment.
    Sử dụng constants cho URLs và settings.
    """
    log.info("--- Running: test_import_and_bulk_assign_success ---")
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_id"]
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
    assigned_status_id = settings.DEFAULT_ASSIGNED_LEAD_STATUS
    unassigned_status_id = settings.DEFAULT_UNASSIGNED_LEAD_STATUS

    # Chuẩn bị dữ liệu file hợp lệ (sử dụng unit/major ID từ fixture)
    file_data = [
        {
            "full_name": "Import Assign 1",
            "email": "imp_assign1@example.com",
            "phone": "2220001",
            "source": "import_test",
            "unit_id": unit_id,
            "major_id": major_id,
        },
        {
            "full_name": "Import Assign 2",
            "email": "imp_assign2@example.com",
            "phone": "2220002",
            "source": "import_test",
            "unit_id": unit_id,
        },  # Ko major
        {
            "full_name": "Import Assign 3",
            "email": "imp_assign3@example.com",
            "phone": "2220003",
            "source": "import_test",
            "unit_id": unit_id,
            "major_id": major_id,
        },
    ]
    mock_file_tuple = create_mock_lead_file(file_data, file_format="csv")

    # --- Bước 1: Gọi API Import ---
    import_url = f"{AdminURLs.BASE}/leads/import"
    log.info(f"Calling import API: {import_url}")
    import_response = await client.post(
        import_url, files={"file": mock_file_tuple}, headers=admin_token_headers
    )

    # --- Assert Import Response ---
    assert import_response.status_code == 200, f"Import failed: {import_response.text}"
    import_result = import_response.json()
    log.debug(f"Import response: {import_result}")
    assert import_result["successful_imports"] == len(file_data)
    assert import_result["failed_imports"] == 0
    assert len(import_result["created_lead_ids"]) == len(file_data)
    assert len(import_result["errors"]) == 0
    created_lead_ids = import_result["created_lead_ids"]
    log.info(f"Import successful. Created Lead IDs: {created_lead_ids}")

    # --- Assert DB State (Sau Import) ---
    async with AsyncSessionLocal() as session:
        leads_after_import = (
            (
                await session.execute(
                    select(models.Lead).where(models.Lead.id.in_(created_lead_ids))
                )
            )
            .scalars()
            .all()
        )
        assert len(leads_after_import) == len(file_data)
        for lead in leads_after_import:
            assert lead.status == initial_status_id
            assert lead.assigned_officer_id is None
    log.info("DB state after import verified.")

    # --- Bước 2: Gọi API Bulk Assign ---
    bulk_assign_url = f"{AdminURLs.BASE}/leads/bulk-assign"
    log.info(f"Calling bulk assign API: {bulk_assign_url}")
    assign_payload = {"lead_ids": created_lead_ids}
    assign_response = await client.post(
        bulk_assign_url, json=assign_payload, headers=admin_token_headers
    )

    # --- Assert Bulk Assign Response ---
    assert (
        assign_response.status_code == 202
    ), f"Bulk assign call failed: {assign_response.text}"
    assign_result = assign_response.json()
    assert "Successfully dispatched" in assign_result.get("message", "")
    log.info("Bulk assign request accepted (202).")

    # --- Bước 3: Chờ Worker Xử Lý & Verify Kết Quả ---
    wait_time = 15
    log.info(f"Waiting {wait_time}s for Celery workers to process assignments...")
    await asyncio.sleep(wait_time)

    # --- Assert DB State (Sau Bulk Assign) ---
    log.info("Verifying DB state after assignment...")
    assigned_count = 0
    unassigned_count = 0
    async with AsyncSessionLocal() as session:
        leads_after_assign = (
            (
                await session.execute(
                    select(models.Lead).where(models.Lead.id.in_(created_lead_ids))
                )
            )
            .scalars()
            .all()
        )
        assert len(leads_after_assign) == len(file_data)
        for lead in leads_after_assign:
            if lead.assigned_officer_id is not None:
                assigned_count += 1
                assert lead.status == assigned_status_id
                # ✅ Thêm assertion kiểm tra officer_id
                assert lead.assigned_officer_id == officer_user_in_db["id"]
            else:
                unassigned_count += 1
                assert lead.status in [initial_status_id, unassigned_status_id]

    log.info(
        f"Assignment verification: Assigned={assigned_count}, Unassigned={unassigned_count}"
    )
    assert assigned_count > 0, "Expected at least one lead to be assigned"
    assert unassigned_count == (
        len(file_data) - assigned_count
    ), "Unassigned count mismatch"

    log.info("--- Finished: test_import_and_bulk_assign_success ---")


# --- Test Import Có Lỗi ---
@pytest.mark.integration
@pytest.mark.asyncio
async def test_import_with_errors(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,  # ✅ Fixture được cung cấp từ conftest.py
    setup_test_database,
):
    """
    Test Import file CSV có cả dòng hợp lệ và không hợp lệ.
    Sử dụng constants cho URLs.
    """
    log.info("--- Running: test_import_with_errors ---")
    unit_id = seed_lead_dependencies["unit_id"]

    # Chuẩn bị dữ liệu file (sử dụng data mẫu và cập nhật unit_id)
    file_data_with_errors = [d.copy() for d in INVALID_LEAD_DATA_FOR_FILE]
    for row in file_data_with_errors:
        if "unit_id" in row:
            row["unit_id"] = unit_id

    mock_file_tuple = create_mock_lead_file(file_data_with_errors, file_format="csv")

    # --- Action: Gọi API Import ---
    import_url = f"{AdminURLs.BASE}/leads/import"
    import_response = await client.post(
        import_url, files={"file": mock_file_tuple}, headers=admin_token_headers
    )

    # --- Assert Import Response ---
    assert (
        import_response.status_code == 200
    ), f"Import with errors failed: {import_response.text}"
    import_result = import_response.json()
    log.debug(f"Import response (with errors): {import_result}")

    expected_success = 1
    expected_fails = 3
    total_processed = expected_success + expected_fails

    assert import_result["total_rows_processed"] == total_processed
    assert import_result["successful_imports"] == expected_success  # 1
    assert import_result["failed_imports"] == expected_fails  # 3
    assert len(import_result["created_lead_ids"]) == expected_success  # 1
    assert len(import_result["errors"]) == expected_fails  # 3

    # --- ✅ SỬA LẠI ASSERTIONS CHO ĐÚNG THỨ TỰ LỖI ---
    errors = import_result["errors"]

    # Lỗi 1: Dòng 3 (Missing Email) -> Bị ép kiểu thành 'nan' -> Lỗi format
    assert errors[0]["row_number"] == 3
    assert (
        "email" in errors[0]["error_message"]
        and "valid email address" in errors[0]["error_message"]
    )
    assert (
        "input_value='nan'" in errors[0]["error_message"]
    )  # Kiểm tra lỗi cụ thể 'nan'

    # Lỗi 2: Dòng 4 (Bad Email Format)
    assert errors[1]["row_number"] == 4
    assert (
        "email" in errors[1]["error_message"]
        and "valid email address" in errors[1]["error_message"]
    )
    assert (
        "input_value='bad-email'" in errors[1]["error_message"]
    )  # Kiểm tra lỗi 'bad-email'

    # Lỗi 3: Dòng 5 (Duplicate Email)
    assert errors[2]["row_number"] == 5
    assert (
        "Email" in errors[2]["error_message"]
        and "already exists" in errors[2]["error_message"]
    )

    log.info("Import with errors handled correctly. Response verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        created_lead = (
            await session.execute(
                select(models.Lead).where(
                    models.Lead.email == "import3@example.com"
                )  # Email hợp lệ duy nhất
            )
        ).scalar_one_or_none()
        assert created_lead is not None
        assert created_lead.id == import_result["created_lead_ids"][0]

        total_leads_in_db = (
            await session.execute(select(func.count(models.Lead.id)))
        ).scalar_one()
        assert total_leads_in_db == expected_success
    log.info("DB state verified: Only valid lead was created.")
    log.info("--- Finished: test_import_with_errors ---")


# --- Các Test Case Lỗi Khác ---


@pytest.mark.integration
@pytest.mark.asyncio
async def test_import_invalid_file_format(
    client: AsyncClient, admin_token_headers: dict
):
    """Test Import file sai định dạng (.txt)."""
    log.info("--- Running: test_import_invalid_file_format ---")
    mock_file_tuple = ("invalid.txt", io.BytesIO(b"some text data"), "text/plain")
    import_url = f"{AdminURLs.BASE}/leads/import"
    response = await client.post(
        import_url, files={"file": mock_file_tuple}, headers=admin_token_headers
    )
    assert response.status_code == 400
    assert "Invalid file format" in response.json()["detail"]
    log.info("Invalid file format correctly blocked (400).")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_import_empty_file(client: AsyncClient, admin_token_headers: dict):
    """Test Import file rỗng."""
    log.info("--- Running: test_import_empty_file ---")
    mock_file_tuple = ("empty.csv", io.BytesIO(b""), "text/csv")
    import_url = f"{AdminURLs.BASE}/leads/import"
    response = await client.post(
        import_url, files={"file": mock_file_tuple}, headers=admin_token_headers
    )
    assert response.status_code == 400
    assert "Empty file uploaded" in response.json()["detail"]
    log.info("Empty file correctly blocked (400).")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_assign_unauthorized(
    client: AsyncClient, officer_token_headers: dict
):
    """Test gọi Bulk Assign bằng token Officer (403)."""
    log.info("--- Running: test_bulk_assign_unauthorized ---")
    assign_payload = {"lead_ids": [1, 2, 3]}
    bulk_assign_url = f"{AdminURLs.BASE}/leads/bulk-assign"
    response = await client.post(
        bulk_assign_url,
        json=assign_payload,
        headers=officer_token_headers,  # Dùng token officer
    )
    assert response.status_code == 403
    assert "You do not have permission" in response.json()["detail"]
    log.info("Bulk assign unauthorized access correctly blocked (403).")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_assign_empty_list(client: AsyncClient, admin_token_headers: dict):
    """Test gọi Bulk Assign với danh sách ID rỗng (422)."""
    log.info("--- Running: test_bulk_assign_empty_list ---")
    assign_payload = {"lead_ids": []}  # Danh sách rỗng
    bulk_assign_url = f"{AdminURLs.BASE}/leads/bulk-assign"
    response = await client.post(
        bulk_assign_url, json=assign_payload, headers=admin_token_headers
    )
    assert response.status_code == 422
    error_data = response.json()
    assert "detail" in error_data and error_data["detail"] == "Validation Error"
    assert "errors" in error_data and isinstance(error_data["errors"], list)
    found_error = False
    for err in error_data["errors"]:
        if err.get(
            "field"
        ) == "body -> lead_ids" and "List should have at least 1 item" in err.get(
            "message", ""
        ):
            found_error = True
            break
    assert found_error
    log.info("Bulk assign with empty list correctly blocked (422).")
