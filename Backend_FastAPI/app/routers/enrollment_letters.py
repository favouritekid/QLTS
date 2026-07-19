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
     fake-404 khi ngoài phạm vi. POST dùng biến thể CÓ KHOÁ
     (``get_admission_for_user`` → SELECT FOR UPDATE) vì phát giấy là MUTATION:
     cửa sổ giữa lúc đọc gate và lúc ghi row rất rộng (render ReportLab off-
     thread + ghi file + fsync), nên nếu không khoá, một admin-rollback
     approved→draft có thể commit giữa chừng và ta vẫn phát ra giấy "đã trúng
     tuyển" cho hồ sơ vừa quay về nháp. GET dùng biến thể đọc.

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
from ..core.deps import get_admission_for_user, get_admission_for_user_read
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
@limiter.limit(RateLimits.DATA_EXPORT)
async def issue_enrollment_letter(
    request: Request,
    payload: EnrollmentLetterIssueRequest,
    current_user: models.User = deps.CasbinAuth,
    # Biến thể CÓ KHOÁ (SELECT FOR UPDATE): xem docstring module — phát giấy là
    # mutation, phải serialize với các chuyển trạng thái song song.
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Render + persist an official admission letter, then stream the PDF.

    Gate: only post-decision profiles (admitted / confirmed / enrolled). Domain
    errors (not eligible / missing HK1 fee / missing field) propagate to the
    global handler as 400 with an ``error_code``.
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
@limiter.limit(RateLimits.DATA_EXPORT)
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
