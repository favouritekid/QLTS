# app/routers/enrollment_letters.py
"""
Router for the official "Giấy báo nhập học" PDF.

Two-layer authorization (issuance is a MUTATION — persists a row + PDF + audit —
so it follows the repo's "CasbinAuth at the router, IDOR/scope in the dependency"
contract, F10):
  1. ``CasbinAuth`` (check_permission) is the FIRST dependency parameter, so it
     is enforced in solve_dependencies phase 1 — BEFORE body validation AND
     before the IDOR dependency. Denied roles get a clean 403 PERMISSION_DENIED
     (no Pydantic-schema leak, no 404 from the IDOR allow-list pre-empting it).
     Policy: officer ALLOW the 3 routes (manager/admin inherit); accountant
     explicit DENY; user default-deny.
  2. IDOR scope 3 tầng (admin: all; manager: unit; officer: assigned + in-unit),
     fake-404 khi ngoài phạm vi. Cả 3 route dùng biến thể ĐỌC: phát giấy vẫn là
     MUTATION, nhưng khoá được lấy MUỘN trong service (ngay trước khi ghi row,
     kèm kiểm tra lại gate) thay vì giữ suốt quá trình render + fsync — xem
     ``enrollment_letter_service.issue_enrollment_letter``.

POST issues an OFFICIAL letter and returns the PDF immediately. GET re-downloads
a prior issuance by id and records a 'downloaded' access-audit row.
"""

import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.client_ip import get_client_ip
from ..core.deps import get_admission_for_user_read
from ..core.rate_limits import RateLimits, limiter
from ..schemas.enrollment_letter import (
    EnrollmentLetterIssueRequest,
    EnrollmentLetterResponse,
)
from ..services import enrollment_letter_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admissions", tags=["Giấy báo nhập học"])

# PII artifact: never cache, don't leak the referrer, no MIME sniffing.
_PII_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _letter_filename(profile_id: int, letter_id: int) -> str:
    """Download filename WITHOUT PII — deliberately NOT citizen_id, which would
    otherwise land in the user's downloads folder / browser history. Uses the
    profile + letter ids already present in the request URL."""
    return f"giay-bao-nhap-hoc-profile-{profile_id}-letter-{letter_id}.pdf"


@router.post(
    "/{profile_id}/enrollment-letter",
    summary="Phát Giấy báo nhập học (official issuance, trả PDF)",
)
# DATA_WRITE (200/h) chứ không phải DATA_EXPORT (20/h): DATA_EXPORT là tier cho
# export workbook hàng loạt (1 request = N nghìn dòng), còn đây là hành động ghi
# LẺ trên MỘT hồ sơ. Lưu ý slowapi ở repo này dùng key_style="url", nên bucket
# là (IP, path-đã-thay-id) — tức trần áp cho TỪNG hồ sơ, không phải cho cả
# phòng tuyển sinh; officer phát cho nhiều hồ sơ khác nhau không đụng trần.
@limiter.limit(RateLimits.DATA_WRITE)
async def issue_enrollment_letter(
    request: Request,
    payload: EnrollmentLetterIssueRequest,
    current_user: models.User = deps.CasbinAuth,
    # Biến thể ĐỌC: khoá lấy muộn trong service (xem docstring module) để không
    # giữ khoá ghi trên hồ sơ suốt lúc render PDF.
    profile: models.AdmissionProfile = Depends(get_admission_for_user_read),
    db: AsyncSession = Depends(database.get_db),
):
    """Render + persist an official admission letter, then stream the PDF.

    Gate: hồ sơ ĐÃ NỘP trở đi (submitted/resubmitted · admitted-like ·
    confirmed · enrolled) và chưa thôi học — xem
    ``admission_status.is_enrollment_letter_eligible`` để biết vì sao mở tới
    submitted. Domain errors (không đủ điều kiện / thiếu Fee HK1 / thiếu trường
    / ngành lệch tiền) propagate to the global handler as 400 với
    ``error_code``.
    """
    letter, pdf_bytes = await enrollment_letter_service.issue_enrollment_letter(
        db,
        profile,
        payload.enrollment_start_date,
        payload.enrollment_end_date,
        current_user,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    try:
        await db.commit()
    except Exception:
        # Commit failed after the PDF was written to disk → delete the orphan.
        await enrollment_letter_service.discard_letter_file(letter)
        raise

    filename = _letter_filename(profile.id, letter.id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Enrollment-Letter-Id": str(letter.id),
            **_PII_HEADERS,
        },
    )


@router.get(
    "/{profile_id}/enrollment-letter/{letter_id}/download",
    summary="Tải lại Giấy báo nhập học đã phát",
)
# Tải lại một file đã có = thao tác ĐỌC, không phải export. Để ở DATA_EXPORT
# khiến chính đường phục hồi (thay cho việc phát bản mới) bị bó chặt hơn cả
# đường phát hành.
@limiter.limit(RateLimits.DATA_READ)
async def download_enrollment_letter(
    request: Request,
    letter_id: int,
    current_user: models.User = deps.CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_user_read),
    db: AsyncSession = Depends(database.get_db),
):
    """Re-download a previously issued letter by id (IDOR-scoped to profile).

    The service resolves the letter, returns 404 (never 403) for a missing /
    other-profile / purged file, and records a 'downloaded' audit row committed
    before the file streams.
    """
    letter = await enrollment_letter_service.get_letter_for_download(
        db,
        profile.id,
        letter_id,
        actor_user_id=current_user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()  # persist the 'downloaded' audit before streaming
    return FileResponse(
        letter.file_path,
        media_type="application/pdf",
        filename=_letter_filename(profile.id, letter_id),
        content_disposition_type="attachment",
        headers=dict(_PII_HEADERS),
    )


@router.get(
    "/{profile_id}/enrollment-letters",
    response_model=list[EnrollmentLetterResponse],
    summary="Danh sách Giấy báo nhập học đã phát cho hồ sơ",
)
@limiter.limit(RateLimits.DATA_READ)
async def list_enrollment_letters(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    profile: models.AdmissionProfile = Depends(get_admission_for_user_read),
    db: AsyncSession = Depends(database.get_db),
):
    """List issued letters for a profile (newest first) for the re-download UI."""
    return await enrollment_letter_service.list_letters_for_profile(db, profile.id)
