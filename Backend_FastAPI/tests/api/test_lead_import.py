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

    # Dòng "Missing Email" nay NHẬP ĐƯỢC: `Lead.email` nullable và LeadCreate.email
    # Optional, nên ô email trống là hợp lệ. Trước đây nó bị loại chỉ vì pandas đọc
    # ô trống thành NaN rồi `str(NaN)` cho ra chuỗi "nan" — một ràng buộc không tầng
    # nào đặt ra (2425/2535 lead trên production không có email).
    expected_success = 2  # dòng hợp lệ + dòng thiếu email
    expected_fails = 2    # email sai định dạng + email trùng trong file
    total_processed = expected_success + expected_fails

    assert import_result["total_rows_processed"] == total_processed
    assert import_result["successful_imports"] == expected_success  # 1
    assert import_result["failed_imports"] == expected_fails  # 3
    assert len(import_result["created_lead_ids"]) == expected_success  # 1
    assert len(import_result["errors"]) == expected_fails  # 3

    errors = import_result["errors"]

    # Không dòng nào được hỏng vì chuỗi "nan" nữa — đó là dấu hiệu ô trống lại bị
    # ép kiểu thành chuỗi.
    assert not any("'nan'" in e["error_message"] for e in errors), (
        f"ô trống lại biến thành chuỗi 'nan': {errors}"
    )

    # Lỗi 1: Dòng 4 (Bad Email Format) — email có giá trị nhưng sai định dạng
    assert errors[0]["row_number"] == 4
    assert (
        "email" in errors[0]["error_message"]
        and "valid email address" in errors[0]["error_message"]
    )
    assert "input_value='bad-email'" in errors[0]["error_message"]

    # Lỗi 2: Dòng 5 (Duplicate Email — tin Việt: "Email '...' đã tồn tại...")
    assert errors[1]["row_number"] == 5
    assert (
        "Email" in errors[1]["error_message"]
        and "đã tồn tại" in errors[1]["error_message"]
    )

    # Dòng 3 (Missing Email) phải NẰM TRONG nhóm thành công, không phải nhóm lỗi
    assert all(e["row_number"] != 3 for e in errors), (
        f"dòng thiếu email vẫn bị loại: {errors}"
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
        # `in` chứ không phải `[0]`: nay có HAI dòng thành công nên thứ tự trong
        # `created_lead_ids` phụ thuộc thứ tự `RETURNING` của một lệnh chèn nhiều
        # dòng — không có gì bảo đảm, và đây là một cổng CI bắt buộc.
        assert created_lead.id in import_result["created_lead_ids"]

        # 🔴 Đây là chỗ DUY NHẤT trong cả bản vá chạm Postgres thật. Mọi chứng cứ
        # "email trống lưu thành NULL" khác đều đọc dict của một repository giả,
        # không phải một CỘT. Nếu ô trống lùi về lưu chuỗi rỗng — cột nullable
        # nhận hết, và ``_cell_or_none(...) or ""`` ngay cạnh đó vốn đã làm vậy
        # cho full_name/source — thì toàn bộ suite vẫn xanh trong khi hành vi
        # đứng tên bản vá đã hỏng.
        lead_thieu_email = (
            await session.execute(
                select(models.Lead).where(models.Lead.full_name == "Missing Email")
            )
        ).scalar_one_or_none()
        assert lead_thieu_email is not None, "dòng thiếu email không vào được DB"
        assert lead_thieu_email.email is None, (
            f"email trống phải lưu NULL, đang lưu {lead_thieu_email.email!r}"
        )

        total_leads_in_db = (
            await session.execute(select(func.count(models.Lead.id)))
        ).scalar_one()
        assert total_leads_in_db == expected_success
    log.info("DB state verified: Only valid lead was created.")
    log.info("--- Finished: test_import_with_errors ---")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_officer_import_thieu_email_va_dem_dung(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Đường nhập của OFFICER — đường mà giao diện thật sự gọi.

    🔴 Mọi test khác trong tệp này đều bắn vào ``/api/admin/users/leads/import``,
    còn ``frontend/src/lib/api/leads.ts`` gọi ``/api/leads/import``. Endpoint
    officer là nhánh DUY NHẤT truyền ``default_unit_id`` (làm ``unit_id`` thôi bắt
    buộc — đúng nhánh bản vá này chạm), duy nhất truyền ``auto_assign_officer_id``,
    và duy nhất phát ``LEAD_IMPORTED`` kèm ``created_lead_ids``. Nói cách khác,
    hậu quả nặng nhất của lỗi id-ma nằm ở nhánh chưa từng có test API nào.
    """
    log.info("--- Running: test_officer_import_thieu_email_va_dem_dung ---")

    # KHÔNG có cột unit_id: officer flow tự gán unit của officer. Dòng 2 thiếu email.
    file_data = [
        {
            "full_name": "Officer Import 1",
            "email": "officer1@example.com",
            "phone": "+84911200001",
            "source": "file_import",
        },
        {
            "full_name": "Officer Import Khong Email",
            "phone": "+84911200002",
            "source": "file_import",
        },
    ]
    mock_file_tuple = create_mock_lead_file(file_data, file_format="csv")

    response = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": mock_file_tuple},
        headers=officer_token_headers,
    )
    assert response.status_code == 200, f"Officer import failed: {response.text}"
    kq = response.json()

    assert kq["total_rows_processed"] == 2
    assert kq["successful_imports"] == 2, f"dòng thiếu email bị loại: {kq['errors']}"
    # Ba con số phải cộng khớp — giao diện nêu thẳng `failed_imports` lên tiêu đề.
    assert kq["successful_imports"] + kq["failed_imports"] == kq["total_rows_processed"]
    assert len(kq["created_lead_ids"]) == 2

    # `created_lead_ids` được ném thẳng vào payload LEAD_IMPORTED → mọi id trong đó
    # phải là id CÓ THẬT trong cơ sở dữ liệu.
    async with AsyncSessionLocal() as session:
        so_ton_tai = (
            await session.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.id.in_(kq["created_lead_ids"])
                )
            )
        ).scalar_one()
        assert so_ton_tai == len(kq["created_lead_ids"]), (
            "created_lead_ids chứa id không tồn tại — LEAD_IMPORTED sẽ trỏ vào hư không"
        )

        lead_khong_email = (
            await session.execute(
                select(models.Lead).where(
                    models.Lead.full_name == "Officer Import Khong Email"
                )
            )
        ).scalar_one_or_none()
        assert lead_khong_email is not None
        assert lead_khong_email.email is None
        # Hai thứ chỉ nhánh officer mới làm — file không có cột unit_id nào:
        assert lead_khong_email.unit_id == seed_lead_dependencies["unit_id"], (
            "officer import phải tự điền unit của officer khi file không có cột unit_id"
        )
        assert lead_khong_email.assigned_officer_id == officer_user_in_db["id"], (
            "officer import phải tự gán lead cho chính officer đó"
        )

    log.info("--- Finished: test_officer_import_thieu_email_va_dem_dung ---")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_template_tai_ve_phai_nhap_lai_duoc_va_khong_doi_email(
    client: AsyncClient,
    officer_token_headers: dict,
    seed_lead_dependencies: dict,
    _initial_status_legacy_marker,
    setup_test_database,
):
    """Template chính thức phải nhập lại được, và không được đòi email nữa.

    🔴 Hai lỗi cùng nằm trên mấy dòng này:

    1. Template CSV mở đầu bằng các dòng chú thích ``#``, mà ``pd.read_csv`` không
       biết — nó lấy dòng ``# Lead Import Template`` làm tiêu đề rồi nghẹn ở dòng
       chú thích có dấu phẩy, trả về 400 kèm thông báo C-tokenizer trông như tệp
       hỏng. Tức là cửa vào chính thức của luồng nhập lead không dùng được.
    2. Sau khi ``email`` thôi bắt buộc, mọi thứ NGƯỜI DÙNG ĐỌC vẫn ghi email là
       cột bắt buộc. Hành vi đổi mà tài liệu không đổi thì officer vẫn hoặc bỏ
       cuộc, hoặc bịa email giả — rồi những email bịa đó đâm
       ``uq_lead_email_unit_active`` và bị loại vì trùng.

    Đi vòng GET → POST nên nó khoá được CẢ HAI đầu: đổi template mà quên đường
    đọc, hoặc ngược lại, đều đỏ.
    """
    log.info("--- Running: test_template_tai_ve_phai_nhap_lai_duoc ---")

    r = await client.get(
        f"{LeadsURLs.LEADS}/import/template?format=csv", headers=officer_token_headers
    )
    assert r.status_code == 200, f"Không tải được template: {r.text}"
    noi_dung = r.content

    # --- Tài liệu trong chính tệp template ---
    van_ban = noi_dung.decode("utf-8")
    dong_bat_buoc = [
        d for d in van_ban.splitlines() if d.startswith("# Required columns:")
    ]
    assert dong_bat_buoc, "template không còn dòng liệt kê cột bắt buộc"
    assert "email" not in dong_bat_buoc[0], (
        f"template vẫn bảo email là cột bắt buộc: {dong_bat_buoc[0]!r}"
    )

    # --- Nhập ngược lại chính tệp vừa tải ---
    resp = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("template.csv", io.BytesIO(noi_dung), "text/csv")},
        headers=officer_token_headers,
    )
    assert resp.status_code == 200, (
        f"template chính hệ thống phát ra lại không nhập được: {resp.text}"
    )
    kq = resp.json()
    assert kq["successful_imports"] == 1, (
        f"dòng ví dụ trong template bị loại: {kq['errors']}"
    )

    # --- Và bỏ HẲN cột email thì vẫn phải nhập được ---
    cac_dong = [d for d in van_ban.splitlines() if d and not d.startswith("#")]
    cot = cac_dong[0].split(",")
    vi_tri_email = cot.index("email")
    bo_email = "\n".join(
        ",".join(v for j, v in enumerate(d.split(",")) if j != vi_tri_email)
        for d in cac_dong
    )
    # Đổi SĐT để không đụng dòng vừa nhập ở trên.
    bo_email = bo_email.replace("0901234567", "0901234599")

    resp2 = await client.post(
        f"{LeadsURLs.LEADS}/import",
        files={"file": ("khong_email.csv", io.BytesIO(bo_email.encode("utf-8")), "text/csv")},
        headers=officer_token_headers,
    )
    assert resp2.status_code == 200, f"bỏ cột email thì hỏng: {resp2.text}"
    assert resp2.json()["successful_imports"] == 1, (
        f"template bỏ cột email bị loại: {resp2.json()['errors']}"
    )

    log.info("--- Finished: test_template_tai_ve_phai_nhap_lai_duoc ---")


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
    # Thông báo nay là tiếng Việt: lỗi mức tệp do chính service phát ra
    # (`_LoiTepNhapLead`) là thứ NGƯỜI DÙNG đọc, nên nó phải đọc được.
    assert "rỗng" in response.json()["detail"].lower()
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
