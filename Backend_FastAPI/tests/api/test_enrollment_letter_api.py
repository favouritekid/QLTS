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
from tests.fixtures.constants import TestOrgData

# Mã ngành THẬT có trong bảng thu (app/constants/enrollment_letter.py):
# 5510216 = Công nghệ ô tô, Trung cấp, học phí HK1 = 9.200.000.
_SCHEDULED_MAJOR_CODE = "5510216"
_SCHEDULED_MAJOR_ID = 9510216

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
    data_snapshot: dict | None = None,
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
                data_snapshot=(
                    {"full_name": "Seed"} if data_snapshot is None else data_snapshot
                ),
                file_path=path,
                sha256=sha256 or hashlib.sha256(content).hexdigest(),
                file_size=len(content),
                expires_at=expires_at,
            )
            session.add(letter)
            await session.flush()
            return letter.id


async def _get_or_create_scheduled_major() -> int:
    """MajorProgram mang MÃ NGÀNH THẬT có trong bảng thu (``TUITION_SCHEDULE``).

    Fixture chung dùng mã giả 'TM1', mà từ 19-07 khối tiền trên giấy được tra từ
    bảng thu theo mã ngành và FAIL-CLOSED khi không tra được — nên hồ sơ gắn mã
    giả không phát được giấy. Chọn 5510216 (Công nghệ ô tô, Trung cấp) vì tổng
    học phí của nó = 9.200.000, đúng số các test ở đây vẫn seed.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = (
                await session.execute(
                    select(models.MajorProgram).where(
                        models.MajorProgram.code == _SCHEDULED_MAJOR_CODE
                    )
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            # id TƯỜNG MINH: fixture chung chèn MAJOR_1 với id=1 cứng nên
            # sequence của major_program vẫn đứng ở 1 — để SQLAlchemy tự cấp id
            # sẽ đụng ngay khoá chính (đã tái hiện: UniqueViolation id=1).
            major = models.MajorProgram(
                id=_SCHEDULED_MAJOR_ID,
                name="Công nghệ ô tô",
                code=_SCHEDULED_MAJOR_CODE,
                degree_level="Trung cấp",
                unit_id=TestOrgData.UNIT_1["id"],
            )
            session.add(major)
            await session.flush()
            return major.id


async def _seed_hk1_fee(profile_id: int, major_id: int | None = None) -> None:
    """Fee HK1 gắn ngành CÓ trong bảng thu, tổng khớp bảng thu (9.200.000).

    ``major_id`` giữ lại cho tương thích chữ ký cũ nhưng bị BỎ QUA: gắn ngành
    ngoài bảng thu thì build_letter_data từ chối phát giấy.
    """
    resolved_major_id = await _get_or_create_scheduled_major()
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
                    resolved_major_id=resolved_major_id,
                    resolved_degree_level="Trung cấp",
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
    assert data["school_year"] == "2026-2027"  # từ fee.academic_year, không hằng
    assert data["major_name"]
    assert data["degree_level"]
    # Khối tiền phải là MỨC CHUẨN của bảng thu cho đúng mã ngành đã tra
    # (5510216 Trung cấp: 4.500.000 + 4.700.000), không phải số suy từ Fee.
    assert data["major_code"] == _SCHEDULED_MAJOR_CODE
    assert data["first_installment"] == 4_500_000
    assert data["second_installment"] == 4_700_000
    assert data["tuition_discount_percent"] == 0
    assert data["first_installment_due"] == "2026-07-31"
    assert data["second_installment_due"] == "2026-09-30"
    assert data["bank_account_number"]
    assert data["signatory_name"]


async def test_db_refuses_two_current_letters_for_one_profile(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """DB tự canh bất biến "mỗi hồ sơ ĐÚNG MỘT bản hiện hành".

    Trước đây bất biến này chỉ do application giữ (câu UPDATE đóng dấu
    superseded_at chạy cùng transaction với INSERT bản mới), nên mọi writer đi
    vòng qua hàm đó — bulk-issue, script phát lại, migration backfill, hai
    request đồng thời — đều phá được. Hậu quả không phải lỗi kỹ thuật mà là hai
    tờ giấy cùng mang chữ ký Hiệu trưởng, cùng được hệ thống gọi là "bản hiện
    hành", với số tiền có thể khác nhau.

    Test đi THẲNG vào DB, cố ý bỏ qua service — đó chính là kịch bản cần chặn.
    """
    from sqlalchemy.exc import IntegrityError

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"uniq{uuid.uuid4().hex[:8]}",
    )
    await _seed_letter(profile_id, expires_at=None)  # bản hiện hành thứ nhất

    with pytest.raises(IntegrityError):
        await _seed_letter(profile_id, expires_at=None)  # thứ hai → phải chặn


async def test_reissue_is_still_allowed_after_superseding(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """...nhưng index UNIQUE KHÔNG được chặn việc phát lại.

    Đây là mặt kia của cùng một đồng xu: đánh rơi mệnh đề ``WHERE superseded_at
    IS NULL`` thì index thành unique trên toàn bộ profile_id và mỗi hồ sơ chỉ
    phát được ĐÚNG MỘT giấy suốt đời. (Bản nháp đầu của migration đã đánh rơi
    đúng mệnh đề đó.)
    """
    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"reis{uuid.uuid4().hex[:8]}",
    )
    first_id = await _seed_letter(profile_id, expires_at=None)

    # Đóng dấu bản cũ rồi phát bản mới — đúng trình tự service làm.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            old = await session.get(models.EnrollmentLetter, first_id)
            old.superseded_at = datetime.now(timezone.utc)

    second_id = await _seed_letter(profile_id, expires_at=None)
    assert second_id != first_id


async def test_purged_letter_is_not_revived_by_a_later_issuance(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Phát bản mới KHÔNG được hồi sinh bản đã bị retention purge.

    Câu UPDATE đồng bộ hạn lưu trữ trước đây đẩy ``expires_at`` cho MỌI bản cũ,
    kể cả bản mà cleanup đã xoá file + scrub PII. Row đó sống lại với hạn tương
    lai trong khi file đã biến mất: danh sách hiện nút "Tải lại", officer bấm
    vào và nhận 404. Ngòi nổ 90 ngày — không ai gặp cho tới hết retention đầu
    tiên.
    """
    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"purge{uuid.uuid4().hex[:7]}",
    )
    from types import SimpleNamespace

    from app.services.enrollment_letter_service import issue_enrollment_letter

    old_expiry = datetime.now(timezone.utc) - timedelta(days=1)
    purged_id = await _seed_letter(
        profile_id,
        expires_at=old_expiry,
        data_snapshot={"_purged": True, "major_name": "Công nghệ ô tô"},
    )
    await _seed_hk1_fee(profile_id)

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        await issue_enrollment_letter(
            session,
            profile,
            date(2026, 7, 28),
            date(2026, 8, 5),
            SimpleNamespace(id=officer_user_in_db["id"]),
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        purged = await session.get(models.EnrollmentLetter, purged_id)
        assert purged.expires_at == old_expiry, (
            "bản đã purge bị đẩy hạn — row sống lại nhưng file đã bị xoá"
        )
        assert purged.is_downloadable is False
        assert purged.is_purged is True


async def test_active_fee_lookup_sees_amount_committed_by_another_session(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Guard "học phí đổi giữa lúc render" phải THẤY được thay đổi.

    ``issue_enrollment_letter`` gọi ``_get_active_hk1_tuition_fee`` HAI lần trên
    CÙNG một session: lần đầu ở ``build_letter_data``, lần sau sau khi có khoá,
    rồi so tổng học phí hai lần. Mặc định SQLAlchemy trả instance trong identity
    map và giữ nguyên thuộc tính đã nạp ⇒ lần hai đọc lại giá trị cũ và phép so
    trở thành "so một giá trị với chính nó" — guard chết mà mọi test vẫn xanh.

    Test PHẢI đổi số bằng một session KHÁC đã commit; đổi trong cùng session sẽ
    xanh giả vì session đó đương nhiên nhìn thấy thay đổi của chính nó.
    """
    from app.services.enrollment_letter_service import (
        _get_active_hk1_tuition_fee,
    )

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"reread{uuid.uuid4().hex[:6]}",
    )
    await _seed_hk1_fee(profile_id)

    async with AsyncSessionLocal() as session:
        first = await _get_active_hk1_tuition_fee(session, profile_id)
        assert int(first.final_amount) == 9_200_000

        # Session KHÁC, đã commit — đúng kịch bản kế toán sửa tiền giữa lúc ta
        # đang render PDF.
        async with AsyncSessionLocal() as other:
            async with other.begin():
                fee_other = await other.get(Fee, first.id)
                fee_other.final_amount = Decimal("9900000")

        second = await _get_active_hk1_tuition_fee(session, profile_id)
        assert int(second.final_amount) == 9_900_000, (
            "đọc lại vẫn ra số cũ — identity map che mất thay đổi, guard "
            "fee_changed_during_render không thể kích hoạt"
        )


async def test_build_letter_data_rejects_fee_from_another_academic_year(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Fee thuộc năm học khác năm của bảng thu ⇒ chặn.

    Bảng thu chỉ đúng cho MỘT mùa tuyển sinh. (Đối chiếu prod 20-07: cả 341 hồ
    sơ HK1 đang là academic_year=2026 nên cửa này không chặn nhầm ai; nó chặn
    đúng hồ sơ mùa sau nếu ai đó quên cập nhật bảng thu.)
    """
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"year{uuid.uuid4().hex[:8]}",
    )
    major_id = await _get_or_create_scheduled_major()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Fee(
                    admission_profile_id=profile_id,
                    fee_type="tuition",
                    academic_year=2027,  # bảng thu là của mùa 2026
                    semester_no=1,
                    base_amount=Decimal("9200000"),
                    final_amount=Decimal("9200000"),
                    status=FeeStatusEnum.invoiced.value,
                    resolved_major_id=major_id,
                    resolved_degree_level="Trung cấp",
                )
            )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)

    assert "2027" in str(exc.value) and "2026" in str(exc.value)


async def test_amount_drift_error_does_not_advise_recalculating_fee(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Thông báo lệch số KHÔNG được khuyên bấm tính lại học phí.

    Nguồn lệch nhiều khả năng nhất là hồ sơ được giảm/chỉnh học phí thủ công
    (applied_discount source='manual_discount'); officer làm theo lời khuyên đó
    sẽ xoá đúng khoản chỉnh tay mà kế toán vừa nhập.
    """
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"advice{uuid.uuid4().hex[:6]}",
    )
    major_id = await _get_or_create_scheduled_major()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Fee(
                    admission_profile_id=profile_id,
                    fee_type="tuition",
                    academic_year=2026,
                    semester_no=1,
                    base_amount=Decimal("9200000"),
                    final_amount=Decimal("7000000"),  # đã giảm tay
                    status=FeeStatusEnum.invoiced.value,
                    resolved_major_id=major_id,
                    resolved_degree_level="Trung cấp",
                )
            )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)

    msg = str(exc.value)
    assert "kế toán" in msg, "phải hướng officer sang người, không sang nút bấm"
    assert "ĐỪNG bấm tính lại" in msg


async def test_build_letter_data_rejects_major_missing_from_schedule(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Ngành KHÔNG có trong bảng thu ⇒ chặn phát giấy (quyết định 19-07).

    Không tra được mã ngành nghĩa là không biết thu bao nhiêu mỗi đợt. Rơi về
    một công thức mặc định sẽ in ra mức thu không đúng chính sách mà không ai
    biết — thà chặn và báo lỗi đọc được.
    """
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"nosch{uuid.uuid4().hex[:7]}",
    )
    # Fee gắn ngành fixture mã 'TM1' — mã giả, chắc chắn ngoài bảng thu.
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
                    status=FeeStatusEnum.invoiced.value,
                    resolved_major_id=seed_lead_dependencies["major_program_id"],
                    resolved_degree_level="Cao đẳng",
                )
            )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)

    assert "bảng thu" in str(exc.value).lower()


async def test_build_letter_data_rejects_amount_drift_from_schedule(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
):
    """Tổng học phí trong hệ thống LỆCH bảng thu ⇒ chặn.

    Hai nguồn đang nói hai số khác nhau; in bên nào cũng là đoán. Đây là lưới
    an toàn cho đúng kịch bản dễ xảy ra nhất: ai đó sửa học phí trong phần mềm
    mà quên cập nhật bảng thu của giấy báo (hằng số Python, phải deploy).
    """
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"drift{uuid.uuid4().hex[:7]}",
    )
    major_id = await _get_or_create_scheduled_major()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Fee(
                    admission_profile_id=profile_id,
                    fee_type="tuition",
                    academic_year=2026,
                    semester_no=1,
                    base_amount=Decimal("9900000"),
                    final_amount=Decimal("9900000"),  # bảng thu ghi 9.200.000
                    status=FeeStatusEnum.invoiced.value,
                    resolved_major_id=major_id,
                    resolved_degree_level="Trung cấp",
                )
            )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)

    msg = str(exc.value)
    # Tiền viết theo lối Việt (dấu chấm), không phải "9,900,000" kiểu Anh —
    # officer phải đối chiếu con số này với màn Học phí.
    assert "9.900.000" in msg and "9.200.000" in msg


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


# --------------------------------------------------------------------------- #
# Vòng đời nhiều bản: bản hiện hành · thu hồi theo trạng thái hồ sơ
# --------------------------------------------------------------------------- #


async def test_reissue_marks_previous_letters_superseded_and_syncs_expiry(
    client: AsyncClient, officer_token_headers: dict,
    seed_lead_dependencies: dict, officer_user_in_db: dict,
):
    """Phát bản mới ⇒ bản trước thành 'đã thay thế' VÀ được kéo dài hạn lưu trữ
    bằng bản mới.

    Hạn tính riêng từng bản nghĩa là bản 1 — bản nhiều khả năng ĐÃ TRAO TAY —
    hết hạn và bị xoá PII trước bản 2 chưa ai cầm; lúc tranh chấp thì bằng
    chứng còn sống lại là bản sai.
    """
    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"sup{uuid.uuid4().hex[:9]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    body = {
        "enrollment_start_date": "2026-07-28",
        "enrollment_end_date": "2026-08-05",
    }
    url = f"/api/admissions/{profile_id}/enrollment-letter"
    first = await client.post(url, json=body, headers=officer_token_headers)
    assert first.status_code == 200
    second = await client.post(url, json=body, headers=officer_token_headers)
    assert second.status_code == 200

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(models.EnrollmentLetter)
                .where(models.EnrollmentLetter.profile_id == profile_id)
                .order_by(models.EnrollmentLetter.id)
            )
        ).scalars().all()

    assert len(rows) == 2
    older, newer = rows
    assert older.superseded_at is not None, "bản cũ phải được đánh dấu đã thay thế"
    assert newer.superseded_at is None, "bản mới nhất là bản hiện hành"
    # Cả nhóm hết hạn cùng lúc theo bản mới nhất.
    assert older.expires_at == newer.expires_at


async def test_download_blocked_after_profile_leaves_eligible_state(
    client: AsyncClient, officer_token_headers: dict,
    seed_lead_dependencies: dict, officer_user_in_db: dict,
):
    """Hồ sơ rút/thôi học SAU khi đã phát ⇒ giấy không tải lại được nữa.

    Không luồng workflow nào đụng bảng enrollment_letter, nên nếu chỉ kiểm row
    thì giấy 'Đã trúng tuyển' của thí sinh đã rút vẫn phục vụ suốt thời hạn lưu
    trữ. Gate đặt ở thời điểm tải nên tự đúng lại nếu hồ sơ được khôi phục.
    """
    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"rvk{uuid.uuid4().hex[:9]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    issued = await client.post(
        f"/api/admissions/{profile_id}/enrollment-letter",
        json={
            "enrollment_start_date": "2026-07-28",
            "enrollment_end_date": "2026-08-05",
        },
        headers=officer_token_headers,
    )
    assert issued.status_code == 200
    letter_id = int(issued.headers["x-enrollment-letter-id"])
    dl_url = (
        f"/api/admissions/{profile_id}/enrollment-letter/{letter_id}/download"
    )

    ok = await client.get(dl_url, headers=officer_token_headers)
    assert ok.status_code == 200  # còn hợp lệ thì tải được

    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = await session.get(models.AdmissionProfile, profile_id)
            profile.status = "withdrawn"

    blocked = await client.get(dl_url, headers=officer_token_headers)
    assert blocked.status_code == 404  # 404 chứ không phải 403: không lộ tồn tại


async def test_major_resolved_from_choice_not_fee_snapshot(
    seed_lead_dependencies: dict, officer_user_in_db: dict,
):
    """Nhánh CHÍNH: ngành/trình độ/hệ đào tạo resolve từ NGUYỆN VỌNG.

    Mọi test khác seed hồ sơ legacy (không choice-engine, không
    offering_admission_config) nên `resolve_fee_academic_info` luôn ném
    BadRequest và code rơi về snapshot Fee — tức query join
    OfferingAcademicInfo→ProgramOffering→MajorProgram CHƯA TỪNG chạy trong test,
    dù 339/350 hồ sơ prod đi đúng đường đó. Test này bắt buộc đi nhánh live.
    """
    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"nv{uuid.uuid4().hex[:10]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    # Dựng chuỗi THẬT ProgramOffering → OfferingAcademicInfo cho đúng ngành của
    # Fee, rồi trỏ hồ sơ vào academic_info đó ⇒ resolve đi nhánh live và join 3
    # bảng thực sự chạy. Hệ đào tạo cố tình KHÁC mặc định để chứng minh giấy in
    # theo dữ liệu chứ không theo hằng.
    # Cùng ngành với Fee (ngành CÓ trong bảng thu) — trỏ sang ngành khác thì
    # guard "nguyện vọng lệch ngành đã tính phí" chặn trước, và test này không
    # còn kiểm được nhánh live nữa.
    scheduled_major_id = await _get_or_create_scheduled_major()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering = models.ProgramOffering(
                program_id=scheduled_major_id,
                offering_type="Liên thông",
                is_active=True,
            )
            session.add(offering)
            await session.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                is_published=True,
            )
            session.add(ai)
            await session.flush()
            ai_id = ai.id
            profile = await session.get(models.AdmissionProfile, profile_id)
            profile.applied_rules = {
                **(profile.applied_rules or {}),
                "academic_info_id": ai_id,
            }

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        data = await build_letter_data(session, profile)

    # Đến được đây nghĩa là join 3 bảng đã chạy và khớp với ngành của Fee
    # (lệch nhau thì _resolve_admitted_major đã ném ValidationError).
    assert data["major_name"]
    assert data["degree_level"]
    # Bằng chứng đi nhánh live: hệ đào tạo bằng đúng giá trị vừa seed, KHÔNG
    # phải hằng mặc định "Chính quy".
    assert data["offering_type"] == "Liên thông"


async def test_letter_refuses_when_fee_has_no_major(
    seed_lead_dependencies: dict, officer_user_in_db: dict,
):
    """Fee chưa gắn ngành ⇒ không đối chiếu được tiền↔ngành ⇒ KHÔNG phát giấy.

    Bỏ chặn này thì giấy in ngành resolve được kèm số tiền của một Fee không rõ
    tính theo ngành nào."""
    from app.utils.exceptions import ValidationError

    from app.services.enrollment_letter_service import build_letter_data

    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"nomaj{uuid.uuid4().hex[:7]}",
    )
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
                    status=FeeStatusEnum.invoiced.value,
                    resolved_major_id=None,      # <- chưa gắn ngành
                    resolved_degree_level=None,
                )
            )

    async with AsyncSessionLocal() as session:
        profile = await session.get(models.AdmissionProfile, profile_id)
        with pytest.raises(ValidationError) as exc:
            await build_letter_data(session, profile)
    assert "ngành" in str(exc.value).lower()


async def test_third_issue_extends_expiry_of_ALL_previous_letters(
    client: AsyncClient, officer_token_headers: dict,
    seed_lead_dependencies: dict, officer_user_in_db: dict,
):
    """Phát lần THỨ BA: bản ĐẦU TIÊN cũng phải được gia hạn.

    Bản trước lọc `superseded_at IS NULL` nên chỉ chạm bản ngay trước — bản #1
    giữ hạn cũ và bị xoá file + scrub PII sớm hơn, dù nó mới là bản nhiều khả
    năng đã trao tay thí sinh. Test 2-bản cũ không bắt được ca này."""
    profile_id = await _seed_approved_profile(
        seed_lead_dependencies["unit_id"],
        officer_user_in_db["id"],
        f"x3{uuid.uuid4().hex[:10]}",
    )
    await _seed_hk1_fee(profile_id, seed_lead_dependencies["major_program_id"])

    body = {
        "enrollment_start_date": "2026-07-28",
        "enrollment_end_date": "2026-08-05",
    }
    url = f"/api/admissions/{profile_id}/enrollment-letter"
    for _ in range(3):
        resp = await client.post(url, json=body, headers=officer_token_headers)
        assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(models.EnrollmentLetter)
                .where(models.EnrollmentLetter.profile_id == profile_id)
                .order_by(models.EnrollmentLetter.id)
            )
        ).scalars().all()

    assert len(rows) == 3
    first, second, third = rows
    assert third.superseded_at is None
    assert first.superseded_at is not None and second.superseded_at is not None
    # Điểm mấu chốt: CẢ BA cùng hạn, kể cả bản đầu.
    assert first.expires_at == third.expires_at
    assert second.expires_at == third.expires_at
