# tests/routers/test_lead_import_assign.py
import io  # ✅ Import io đã được thêm
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings
from tests._lead_status_test_ids import (
    INITIAL_LEAD_STATUS_ID,
)

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


@pytest_asyncio.fixture(scope="function")
async def _initial_status_legacy_marker(seed_lead_dependencies):
    """Patch the conftest-seeded TTHV000 row to set ``legacy_status="new"``.

    The lead import path resolves the initial consultation status via
    ``StatusHelper.get_initial_status()`` which queries ``legacy_status="new"``
    + ``is_final=False``. The shared conftest fixture seeds TTHV000 without
    the marker (other test suites depend on it staying NULL), so this
    file-local fixture stamps the marker just for the import tests.
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

# --- Dữ liệu file mẫu sử dụng constants ---
FILE_DATA_UNIT_ID = TestOrgData.UNIT_1["id"]

VALID_LEAD_DATA_FOR_FILE = [
    {
        "full_name": "Import Lead 1",
        "email": "import1@example.com",
        "phone": "+84911100001",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },
    {
        "full_name": "Import Lead 2",
        "email": "import2@example.com",
        "phone": "+84911100002",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },
]

INVALID_LEAD_DATA_FOR_FILE = [
    {
        "full_name": "Import Lead 3 Valid",
        "email": "import3@example.com",
        "phone": "+84911100003",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },
    {
        "full_name": "Missing Email",
        "phone": "+84911100004",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },  # Thiếu email
    {
        "full_name": "Bad Email Format",
        "email": "bad-email",
        "phone": "+84911100005",
        "source": "file_import",
        "unit_id": FILE_DATA_UNIT_ID,
    },  # Sai email
    {
        "full_name": "Duplicate Email In File",
        "email": "import3@example.com",
        "phone": "+84911100006",
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
    _initial_status_legacy_marker,
    officer_user_in_db: dict,  # ✅ THÊM FIXTURE NÀY
    setup_test_database,
):
    """
    Test flow hoàn chỉnh: Import CSV -> Bulk Assign -> Verify Assignment.
    Sử dụng constants cho URLs và settings.
    """
    log.info("--- Running: test_import_and_bulk_assign_success ---")
    unit_id = seed_lead_dependencies["unit_id"]
    initial_status_id = INITIAL_LEAD_STATUS_ID

    # Lead model dùng `offering_id` (3-tier architecture), không còn
    # `major_id`. File import giữ tối thiểu các field model accept.
    file_data = [
        {
            "full_name": "Import Assign 1",
            "email": "imp_assign1@example.com",
            "phone": "+84922200001",
            "source": "import_test",
            "unit_id": unit_id,
        },
        {
            "full_name": "Import Assign 2",
            "email": "imp_assign2@example.com",
            "phone": "+84922200002",
            "source": "import_test",
            "unit_id": unit_id,
        },
        {
            "full_name": "Import Assign 3",
            "email": "imp_assign3@example.com",
            "phone": "+84922200003",
            "source": "import_test",
            "unit_id": unit_id,
        },
    ]
    mock_file_tuple = create_mock_lead_file(file_data, file_format="csv")

    # --- Bước 1: Gọi API Import ---
    import_url = f"{AdminURLs.BASE}/users/leads/import"
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
            # ``lead.status`` is the legacy_status string (e.g. "new"),
            # ``lead.consultation_status_id`` is the FK to ConsultationStatus.id
            assert lead.consultation_status_id == initial_status_id
            assert lead.assigned_officer_id is None
            # ✅ cached_urgency_score must NOT be default 50
            # New lead with 0 consultations: base(30) + never_contacted(25) = 55
            # (+ hot bonus 15 if lead_score >= 70)
            assert lead.cached_urgency_score != 50, (
                f"Lead {lead.id} has stale default cached_urgency_score=50"
            )
            assert lead.cached_urgency_score >= 55
    log.info("DB state after import verified.")

    # --- Bước 2: Gọi API Bulk Assign ---
    bulk_assign_url = f"{AdminURLs.BASE}/users/leads/bulk-assign"
    log.info(f"Calling bulk assign API: {bulk_assign_url}")
    assign_payload = {"lead_ids": created_lead_ids}
    assign_response = await client.post(
        bulk_assign_url, json=assign_payload, headers=admin_token_headers
    )

    # --- Assert Bulk Assign Response ---
    # Endpoint returns 200 OK with dispatch summary (was 202 in earlier
    # implementation that fanned out fully async).
    assert (
        assign_response.status_code == 200
    ), f"Bulk assign call failed: {assign_response.text}"
    assign_result = assign_response.json()
    # Endpoint returns dispatch summary in ``detail`` (FastAPI default)
    # rather than ``message``.
    summary_text = assign_result.get("detail") or assign_result.get("message", "")
    assert "Successfully dispatched" in summary_text
    log.info("Bulk assign request accepted (202).")

    # --- Bước 3: Verify Celery dispatch (skip downstream worker check) ---
    # The bulk-assign endpoint dispatches per-lead assignment tasks to the
    # Celery broker (Redis DB 12 in test env) but no worker is wired to that
    # broker during pytest, so the assignment outcome cannot be observed
    # here. Verifying the endpoint dispatched successfully is sufficient at
    # this layer; assignment-outcome behavior is exercised by dedicated
    # service-level tests with task-eager fixtures.
    log.info(
        "Bulk assign dispatched %d task(s); skipping post-worker DB verification "
        "(test env Celery broker has no attached worker).",
        len(created_lead_ids),
    )

    log.info("--- Finished: test_import_and_bulk_assign_success ---")


# --- Test Import Có Lỗi ---
@pytest.mark.integration
@pytest.mark.asyncio
async def test_import_with_errors(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,  # ✅ Fixture được cung cấp từ conftest.py
    _initial_status_legacy_marker,
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
    import_url = f"{AdminURLs.BASE}/users/leads/import"
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

    # Lỗi 3: Dòng 5 (Duplicate Email — tin Việt: "Email '...' đã tồn tại...")
    assert errors[2]["row_number"] == 5
    assert (
        "Email" in errors[2]["error_message"]
        and "đã tồn tại" in errors[2]["error_message"]
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
    import_url = f"{AdminURLs.BASE}/users/leads/import"
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
    import_url = f"{AdminURLs.BASE}/users/leads/import"
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
    bulk_assign_url = f"{AdminURLs.BASE}/users/leads/bulk-assign"
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
    bulk_assign_url = f"{AdminURLs.BASE}/users/leads/bulk-assign"
    response = await client.post(
        bulk_assign_url, json=assign_payload, headers=admin_token_headers
    )
    assert response.status_code == 422
    error_data = response.json()
    assert error_data.get("error_code") == "VALIDATION_ERROR"
    assert "errors" in error_data and isinstance(error_data["errors"], list)
    found_error = False
    for err in error_data["errors"]:
        if (
            err.get("loc") == ["body", "lead_ids"]
            and "List should have at least 1 item" in err.get("msg", "")
        ):
            found_error = True
            break
    assert found_error
    log.info("Bulk assign with empty list correctly blocked (422).")
