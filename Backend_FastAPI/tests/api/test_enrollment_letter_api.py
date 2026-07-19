"""API integration tests for the enrollment-letter endpoints.

Locks the two things unit tests cannot prove end-to-end on a live route:

1. Casbin runs BEFORE body validation and BEFORE the IDOR dependency
   (``deps.CasbinAuth`` is the first dependency parameter). An accountant with
   an EMPTY body gets 403 PERMISSION_DENIED — not a 422 that would leak the
   Pydantic schema, and not the IDOR 404.
2. The GET download commits a 'downloaded' EntityAuditLog row BEFORE streaming
   the file, with the PII response headers, IDOR ownership, and cross-profile
   letter isolation all working together.

Scope is deliberately narrow: minimal seed of an approved (→ admitted) profile
assigned to the officer + an active HK1 tuition fee + the issued letter — NOT a
full admissions E2E.
"""
import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.finance import Fee, FeeStatusEnum
from tests.conftest import _create_user_and_role, _get_token_headers

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def letter_storage_tmp(tmp_path, monkeypatch):
    """Trỏ thư mục lưu PDF sang tmp của test.

    ``ENROLLMENT_LETTER_STORAGE_DIR`` mặc định là ``/app/private_exports/letters``
    — đường dẫn TUYỆT ĐỐI bên trong container. Chạy local qua ``docker compose``
    thì có thật, nhưng CI chạy pytest TRỰC TIẾP trên runner (không container):
    ``/app`` không tồn tại và không tạo được ⇒ ``os.makedirs`` ném
    ``PermissionError: [Errno 13] Permission denied: '/app'`` ngay khi phát giấy.

    Autouse để cả đường phát hành (service tự dựng path) lẫn ``_seed_letter_row``
    dùng chung một thư mục tạm, và mỗi test được dọn sạch — không test nào thấy
    file của test khác.
    """
    monkeypatch.setattr(
        settings, "ENROLLMENT_LETTER_STORAGE_DIR", str(tmp_path / "letters")
    )


_ACCOUNTANT = {
    "username": "el_accountant",
    "email": "el_accountant@example.com",
    "password": "AccountantPassword!345",
    "role": "accountant",
    "status": "active",
}


@pytest_asyncio.fixture
async def accountant_token_headers(client, seed_lead_dependencies: dict) -> dict:
    """Accountant in the SAME unit as the seed — isolates the Casbin deny from
    any IDOR difference (accountant is bounced at Casbin, not by unit)."""
    user = await _create_user_and_role(
        _ACCOUNTANT, "role:accountant", unit_id=seed_lead_dependencies["unit_id"]
    )
    return await _get_token_headers(client, user)


async def _seed_approved_profile(
    unit_id: int, officer_id: int, citizen_id: str
) -> int:
    """Approved (→ effective 'admitted', letter-eligible) profile owned by the
    officer (assigned + in-unit)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="EL Test Lead",
                phone="0901234567",
                email=f"el_{citizen_id}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
            )
            session.add(lead)
            await session.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                status="approved",
                academic_year=2026,
                citizen_id=citizen_id,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                full_name="Nguyễn Văn A",
                dob=date(2008, 5, 1),
                permanent_province="Tỉnh Đắk Lắk",
                permanent_ward="Phường Tự An",
                phone="0901234567",
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def _seed_letter(
    profile_id: int,
    *,
    expires_at,
    content: bytes = b"%PDF-1.4 seeded test letter",
    sha256: str | None = None,
) -> int:
    """Seed an EnrollmentLetter row + its file on disk directly (skips issuance)
    so download-side gates (expiry / integrity / filename) can be exercised."""
    base = os.path.join(settings.ENROLLMENT_LETTER_STORAGE_DIR, str(profile_id))
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"seed-{uuid.uuid4().hex}.pdf")
    with open(path, "wb") as f:
        f.write(content)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            letter = models.EnrollmentLetter(
                profile_id=profile_id,
                enrollment_start_date=date(2026, 7, 28),
                enrollment_end_date=date(2026, 8, 5),
                data_snapshot={"full_name": "Seed"},
                file_path=path,
                sha256=sha256 or hashlib.sha256(content).hexdigest(),
                file_size=len(content),
                expires_at=expires_at,
            )
            session.add(letter)
            await session.flush()
            return letter.id


async def _seed_hk1_fee(profile_id: int, major_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Fee(
                    admission_profile_id=profile_id,
                    fee_type="tuition",
                    academic_year=2026,
                    semester_no=1,
                    base_amount=Decimal("9200000"),
                    final_amount=Decimal("9200000"),
                    status=FeeStatusEnum.invoiced.value,  # != cancelled
                    resolved_major_id=major_id,
                    resolved_degree_level="Cao đẳng",
                )
            )


# --------------------------------------------------------------------------- #
# 1. Casbin-first: accountant 403 BEFORE body validation
# --------------------------------------------------------------------------- #


async def test_accountant_denied_403_before_body(
    client: AsyncClient, accountant_token_headers: dict
):
    """Empty body would normally 422 (missing dates). Getting 403 instead proves
    Casbin (deps.CasbinAuth, first dependency) runs before body parse AND before
    IDOR — the accountant-DENY policy fires with no schema leak."""
    resp = await client.post(
        "/api/admissions/1/enrollment-letter",
        headers=accountant_token_headers,
        json={},  # empty → would be 422 if body validated first
    )
    assert resp.status_code == 403, resp.text
    assert resp.json().get("error_code") == "PERMISSION_DENIED"
    assert "loc" not in resp.text  # Pydantic 422 `loc` must NOT leak


async def test_officer_allowed_passes_casbin(
    client: AsyncClient, officer_token_headers: dict
):
    """Officer is ALLOWED by Casbin, so it never gets 403 — it falls through to
    the IDOR 404 (bogus profile) or body 422, proving the allow side works."""
    resp = await client.post(
        "/api/admissions/999999/enrollment-letter",
        headers=officer_token_headers,
        json={},
    )
    assert resp.status_code != 403, resp.text
    assert resp.status_code in (404, 422)


# --------------------------------------------------------------------------- #
# 2. Issue → download records audit + PII headers + ownership
# --------------------------------------------------------------------------- #


async def test_issue_then_download_records_audit(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    pid = await _seed_approved_profile(
        unit_id=seed_lead_dependencies["unit_id"],
        officer_id=officer_user_in_db["id"],
        citizen_id="012345678901",
    )
    await _seed_hk1_fee(pid, seed_lead_dependencies["major_program_id"])

    # --- issue (happy path) ---
    issue = await client.post(
        f"/api/admissions/{pid}/enrollment-letter",
        headers=officer_token_headers,
        json={
            "enrollment_start_date": "2026-07-28",
            "enrollment_end_date": "2026-08-05",
        },
    )
    assert issue.status_code == 200, issue.text
    assert issue.headers["content-type"] == "application/pdf"
    assert issue.content[:4] == b"%PDF"
    assert issue.headers.get("cache-control") == "private, no-store"
    letter_id = int(issue.headers["x-enrollment-letter-id"])

    # --- re-download → audit + PII headers ---
    dl = await client.get(
        f"/api/admissions/{pid}/enrollment-letter/{letter_id}/download",
        headers={**officer_token_headers, "X-Real-IP": "203.0.113.9"},
    )
    assert dl.status_code == 200, dl.text
    assert dl.content[:4] == b"%PDF"
    assert dl.headers.get("cache-control") == "private, no-store"
    assert dl.headers.get("referrer-policy") == "no-referrer"
    assert dl.headers.get("x-content-type-options") == "nosniff"

    # --- the 'downloaded' audit row was committed before the file streamed ---
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(models.EntityAuditLog).where(
                models.EntityAuditLog.entity_type == "EnrollmentLetter",
                models.EntityAuditLog.entity_id == letter_id,
                models.EntityAuditLog.action == "downloaded",
            )
        )
    assert row is not None
    assert row.actor_user_id == officer_user_in_db["id"]
    assert row.ip_address == "203.0.113.9"


async def test_letter_not_downloadable_via_other_profile(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """A letter issued for profile A must not be downloadable via profile B's
    URL, even when the officer owns both (letter is scoped to its profile)."""
    unit_id = seed_lead_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    pid_a = await _seed_approved_profile(unit_id, officer_id, "012300000001")
    await _seed_hk1_fee(pid_a, seed_lead_dependencies["major_program_id"])
    pid_b = await _seed_approved_profile(unit_id, officer_id, "012300000002")

    issue = await client.post(
        f"/api/admissions/{pid_a}/enrollment-letter",
        headers=officer_token_headers,
        json={
            "enrollment_start_date": "2026-07-28",
            "enrollment_end_date": "2026-08-05",
        },
    )
    assert issue.status_code == 200, issue.text
    letter_id = int(issue.headers["x-enrollment-letter-id"])

    # Same officer, owns B, but the letter belongs to A → 404 (not this profile's).
    cross = await client.get(
        f"/api/admissions/{pid_b}/enrollment-letter/{letter_id}/download",
        headers=officer_token_headers,
    )
    assert cross.status_code == 404, cross.text


# --------------------------------------------------------------------------- #
# 3. Download gates: expiry, integrity, PII-free filename
# --------------------------------------------------------------------------- #


async def test_expired_letter_not_downloadable(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """A letter past its expires_at must not be served even if the daily cleanup
    task has not yet removed the file."""
    pid = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"], officer_user_in_db["id"], "012400000001"
    )
    lid = await _seed_letter(
        pid, expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    resp = await client.get(
        f"/api/admissions/{pid}/enrollment-letter/{lid}/download",
        headers=officer_token_headers,
    )
    assert resp.status_code == 404, resp.text


async def test_corrupt_letter_not_streamed(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """A file whose sha256 no longer matches the stored hash (tampered/corrupt)
    must not be streamed."""
    pid = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"], officer_user_in_db["id"], "012400000002"
    )
    lid = await _seed_letter(
        pid,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        sha256="0" * 64,  # deliberately wrong → integrity mismatch
    )
    resp = await client.get(
        f"/api/admissions/{pid}/enrollment-letter/{lid}/download",
        headers=officer_token_headers,
    )
    assert resp.status_code == 404, resp.text


async def test_download_filename_has_no_citizen_id(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """The Content-Disposition filename must NOT leak the CCCD (PII)."""
    citizen = "012499999999"
    pid = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"], officer_user_in_db["id"], citizen
    )
    lid = await _seed_letter(
        pid, expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    resp = await client.get(
        f"/api/admissions/{pid}/enrollment-letter/{lid}/download",
        headers=officer_token_headers,
    )
    assert resp.status_code == 200, resp.text
    disposition = resp.headers.get("content-disposition", "")
    assert citizen not in disposition
    assert f"letter-{lid}" in disposition  # ids, not PII


# --------------------------------------------------------------------------- #
# build_letter_data — hàng rào cuối trước khi in văn bản có chữ ký Hiệu trưởng
# --------------------------------------------------------------------------- #


async def test_build_letter_data_binds_major_degree_and_real_fee(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Snapshot phải bám ĐÚNG Fee đang hoạt động: tổng học phí, phần đã nộp,
    nhãn năm học dẫn từ ``fee.academic_year``, và ngành + TRÌNH ĐỘ.

    Trình độ là bắt buộc: dữ liệu thật có ngành trùng tên giữa Cao đẳng và
    Trung cấp, nên chỉ tên ngành là câu chưa xác định.
    """
    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"bld{uuid.uuid4().hex[:9]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        data = await build_letter_data(session, profile)

    assert data["hk1_fee_amount"] == 9_200_000
    assert data["hk1_paid_amount"] == 0
    assert data["hk1_waived_amount"] == 0
    assert data["school_year"] == "2026-2027"  # từ fee.academic_year, không hằng
    assert data["major_name"]
    assert data["degree_level"]
    # Literal đã in được chụp lại để còn đối chiếu sau khi retention scrub PII.
    assert data["first_installment"] > 0
    assert data["bank_account_number"]
    assert data["signatory_name"]


async def test_build_letter_data_rejects_profile_without_fee(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Không có Fee HK1 ⇒ KHÔNG phát giấy (thà không có giấy còn hơn giấy
    khuyết số tiền), và lỗi phải nói rõ thiếu gì."""
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"nofee{uuid.uuid4().hex[:7]}",
    )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)

    assert "học phí" in str(exc.value).lower()


async def test_build_letter_data_rejects_dropped_profile(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """``drop_profile`` giữ status='enrolled', nên gate theo status không bắt
    được — phải chặn tường minh, nếu không sinh viên đã thôi học vẫn nhận giấy
    báo nhập học."""
    from app.utils.exceptions import BusinessRuleViolation

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"drop{uuid.uuid4().hex[:8]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = await session.get(models.AdmissionProfile, profile_id)
            profile.status = "enrolled"
            profile.is_dropped = True

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(BusinessRuleViolation):
            await build_letter_data(session, profile)
