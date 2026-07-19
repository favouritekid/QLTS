# app/services/enrollment_letter_service.py
"""
Service for issuing the official "Giấy báo nhập học" PDF.

Flow: gather + VALIDATE the data (gate trạng thái + required fields + the
profile's active HK1 tuition Fee), render the PDF off the event loop, persist
the bytes to disk (atomic + sha256 + retention) and record an ``EnrollmentLetter``
issuance row. The router commits; this service only flushes (arch rule).

SỐ TIỀN bám ACTIVE HK1 tuition ``Fee`` của hồ sơ (final_amount, trừ đã nộp /
được miễn) — không bao giờ tính lại — nên học phí in ra khớp khoản thu thật.
NGÀNH + TRÌNH ĐỘ thì resolve theo NGUYỆN VỌNG rồi ĐỐI CHIẾU với ngành mà tiền
đã tính theo (xem ``_resolve_admitted_major``): giấy ghi "Đã trúng tuyển ngành
X" nên X phải là nguyện vọng, và lệch giữa hai nguồn thì KHÔNG phát giấy.
Thiếu Fee (hoặc bất kỳ trường bắt buộc nào) → lỗi "thiếu dữ liệu" thay vì phát
ra một tờ giấy khuyết.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import structlog
from anyio import to_thread
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.constants import enrollment_letter as C
from app.models.finance.fee import FeeStatusEnum, FeeTypeEnum
from app.services.admission_pdf_service import render_enrollment_letter
from app.utils.address_format import format_permanent_address
from app.utils.admission_status import is_enrollment_letter_eligible
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.sms_export import STAGING_PREFIX, sha256_file

log = structlog.get_logger(__name__)


async def _get_active_hk1_tuition_fee(db, profile_id: int):
    """Return the profile's single ACTIVE HK1 tuition Fee (or None).

    Active = ``status != cancelled`` (a unique partial index guarantees at most
    one such fee per profile for tuition — see ``Fee.__table_args__``). Eager
    loads ``resolved_major`` so the ngành name is available without a lazy load.
    """
    stmt = (
        select(models.Fee)
        .where(
            models.Fee.admission_profile_id == profile_id,
            models.Fee.fee_type == FeeTypeEnum.tuition.value,
            models.Fee.semester_no == 1,
            models.Fee.status != FeeStatusEnum.cancelled.value,
        )
        .options(selectinload(models.Fee.resolved_major))
        .order_by(models.Fee.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _resolve_admitted_major(db, profile, fee):
    """Ngành + trình độ IN LÊN GIẤY, lấy theo NGUYỆN VỌNG (không phải cột
    snapshot trên Fee).

    Giấy in nguyên văn "Đã trúng tuyển ngành: X" nên X phải là nguyện vọng, và
    học phí phải được tính theo ĐÚNG nguyện vọng đó. ``resolve_fee_academic_info``
    là single-source-of-truth cho luật này (dùng chung với fees/invoices):

      * đã công bố kết quả ⇒ NV có ``decision='admitted'`` — có thể KHÔNG phải
        NV1, và in NV1 lúc đó là sai sự thật;
      * chưa công bố + đúng 1 NV ⇒ chính NV đó (= NV1, đường prepay/giữ chỗ ở
        ``submitted`` mà gate phát giấy đang mở);
      * ≥2 NV còn pending, hoặc 0 NV ⇒ fail-closed.

    Vì sao KHÔNG đọc thẳng ``fee.resolved_major``: cột đó chỉ được ghi lại khi
    resnapshot chạy, nên có thể trỏ ngành CŨ nếu cấu hình đổi sau lúc tính phí —
    repo đã biết trước rủi ro này và log ``fee_resolved_major_drift``
    (``fee_calculation_service.py``). Ở đây ta resolve LẠI từ nguyện vọng rồi
    ĐỐI CHIẾU với ngành mà tiền đã tính theo; lệch nhau thì KHÔNG phát giấy, vì
    một tờ giấy ghi ngành A kèm học phí của ngành B là văn bản tự mâu thuẫn.

    Trả về ``(major_name, degree_level)``. Ném ``ValidationError`` với lý do đọc
    được nếu không xác định được ngành hoặc phát hiện lệch.
    """
    from sqlalchemy import select as _select

    from app.services.fee_calculation_service import resolve_fee_academic_info
    from app.utils.exceptions import BadRequest

    # --- Nguồn 1 (ưu tiên): nguyện vọng ---
    live: tuple[int, str, str | None] | None = None
    try:
        academic_info = await resolve_fee_academic_info(db, profile)
    except BadRequest:
        # Hồ sơ legacy thiếu offering_admission_config / applied_rules, hoặc
        # multi-NV chưa công bố: KHÔNG chặn phát giấy ở đây — còn snapshot trên
        # Fee (nguồn 2) là ngành mà TIỀN thực sự đã tính theo.
        academic_info = None

    if academic_info is not None:
        row = (
            await db.execute(
                _select(models.MajorProgram.id, models.MajorProgram.name,
                        models.MajorProgram.degree_level)
                .select_from(models.OfferingAcademicInfo)
                .join(
                    models.ProgramOffering,
                    models.ProgramOffering.id
                    == models.OfferingAcademicInfo.offering_id,
                )
                .join(
                    models.MajorProgram,
                    models.MajorProgram.id == models.ProgramOffering.program_id,
                )
                .where(models.OfferingAcademicInfo.id == academic_info.id)
            )
        ).first()
        if row is not None and row[1]:
            live = (row[0], row[1], row[2])

    # --- Nguồn 2 (đối chứng / dự phòng): snapshot đã đóng băng trên Fee ---
    snap_major = fee.resolved_major if fee is not None else None
    snap = (
        (snap_major.id, snap_major.name, fee.resolved_degree_level)
        if snap_major and snap_major.name
        else None
    )

    if live is None and snap is None:
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — chưa xác định được ngành trúng "
            "tuyển (hồ sơ chưa chọn nguyện vọng, hoặc học phí chưa gắn ngành). "
            "Hãy tính lại học phí trước khi phát giấy."
        )

    # Cả hai cùng có nhưng LỆCH ⇒ tiền và ngành đang nói hai chuyện khác nhau.
    # Một tờ giấy ghi ngành A kèm học phí của ngành B là văn bản tự mâu thuẫn,
    # nên fail-closed thay vì chọn bừa một bên.
    if live and snap and live[0] != snap[0]:
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — nguyện vọng trúng tuyển là "
            f"'{live[1]}' nhưng học phí đang tính theo ngành '{snap[1]}'. "
            f"Hãy tính lại học phí cho đúng ngành trước khi phát giấy."
        )

    _, major_name, degree_level = live or snap
    return major_name, degree_level


def _school_year_label(fee) -> str:
    """Nhãn năm học "2026-2027" dẫn xuất từ ``fee.academic_year``.

    Cùng công thức với fees.py / invoices.py để giấy báo, màn học phí và hoá
    đơn không bao giờ nói hai năm khác nhau cho cùng một Fee. Fee thiếu
    academic_year (dữ liệu cũ) mới rơi về hằng số.
    """
    year = getattr(fee, "academic_year", None)
    if isinstance(year, int) and year > 0:
        return f"{year}-{year + 1}"
    return C.SCHOOL_YEAR


async def build_letter_data(db, profile) -> dict:
    """Gather + validate the data snapshot rendered onto the letter.

    Raises ``BusinessRuleViolation`` if the profile is not letter-eligible, or
    ``ValidationError`` listing every missing required field. The returned dict
    is BOTH the render input and the persisted ``data_snapshot`` (JSON-safe:
    dates as ISO strings, amounts as int).
    """
    if not is_enrollment_letter_eligible(profile):
        raise BusinessRuleViolation(
            "Chỉ phát giấy báo nhập học cho hồ sơ đã nộp trở đi "
            "(đã nộp / đã duyệt / xác nhận / nhập học) và chưa thôi học."
        )

    missing: list[str] = []

    full_name = (profile.full_name or "").strip()
    if not full_name:
        missing.append("họ tên")

    dob = profile.dob
    if not dob:
        missing.append("ngày sinh")

    address = format_permanent_address(profile)
    if not address:
        missing.append("địa chỉ thường trú")

    fee = await _get_active_hk1_tuition_fee(db, profile.id)
    if fee is None:
        missing.append("phí học kỳ 1 (HK1) — hãy tính học phí trước")

    if missing:
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — thiếu dữ liệu: "
            + ", ".join(missing)
            + "."
        )

    # Ngành + trình độ resolve LẠI từ nguyện vọng và đối chiếu với ngành mà học
    # phí đã tính theo (xem ``_resolve_admitted_major``). Chạy SAU khối
    # ``missing`` vì nó cần fee, và nó tự ném ValidationError với lý do riêng
    # thay vì gộp vào danh sách "thiếu dữ liệu".
    major_name, degree_level = await _resolve_admitted_major(db, profile, fee)

    return {
        "full_name": full_name,
        "dob": dob.isoformat(),
        "permanent_address": address,
        # Ngành + trình độ theo nguyện vọng. TRÌNH ĐỘ LÀ BẮT BUỘC trên giấy:
        # dữ liệu thật có ngành TRÙNG TÊN giữa hai trình độ (Kế toán, Công nghệ
        # ô tô, Y sỹ đa khoa, Chăn nuôi - Thú y, Công nghệ thông tin), nên
        # "Đã trúng tuyển ngành: Kế toán" một mình là câu chưa xác định.
        "major_name": major_name,
        "degree_level": degree_level,
        # MVP: offering_type is not snapshotted on Fee; live-resolving the
        # academic_info → offering chain is deferred (v2). Almost all offerings
        # are "Chính quy" and the user accepted a literal fallback.
        "offering_type": C.DEFAULT_OFFERING_TYPE,
        # round (not truncate) so a hypothetical fractional discount never
        # under-states the charge on the official letter; VND fees are whole.
        "hk1_fee_amount": int(round(fee.final_amount)),
        # ĐÃ NỘP / ĐƯỢC MIỄN đi kèm để giấy in đúng số CÒN PHẢI NỘP. Luồng
        # prepay (giữ chỗ) cho phép đóng HK1 khi hồ sơ còn `submitted`, nên một
        # thí sinh đã trả trước rất dễ được duyệt rồi nhận giấy — in
        # `final_amount` gộp là đòi lại tiền họ đã đóng, trên văn bản có chữ ký
        # Hiệu trưởng. (Fee đã miễn toàn phần cũng vào đây thay vì bị đòi đủ.)
        "hk1_paid_amount": int(round(fee.paid_amount or 0)),
        "hk1_waived_amount": int(round(fee.waived_amount or 0)),
        "fee_id": fee.id,
        # Nhãn năm học DẪN XUẤT từ chính Fee đang render (quy ước dùng khắp
        # repo: fees.py / invoices.py), KHÔNG lấy hằng process-wide — nếu không
        # màn Học phí hiện "2026-2027" còn giấy báo in một năm khác.
        "school_year": _school_year_label(fee),
        # Literal ĐÃ IN lên giấy được chụp lại cùng: đây là official record,
        # mà mọi hằng dưới đây đều có thể đổi giữa các mùa tuyển sinh. Không
        # lưu thì sau retention không còn gì đối chiếu "giấy đã nói gì".
        "first_installment": C.FIRST_INSTALLMENT,
        "bank_account_number": C.BANK_ACCOUNT_NUMBER,
        "bank_account_name": C.BANK_ACCOUNT_NAME,
        "bank_name": C.BANK_NAME,
        "signatory_title": C.SIGNATORY_TITLE,
        "signatory_name": C.SIGNATORY_NAME,
        "phone": (profile.phone or "").strip(),
    }


def _write_pdf_atomic(content: bytes, final_path: str) -> tuple[str, int]:
    """Write ``content`` atomically (staging → fsync → os.replace). Returns
    (sha256_hex, size). SYNC/blocking → call via ``to_thread.run_sync``."""
    sha = hashlib.sha256(content).hexdigest()
    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    staging = os.path.join(
        os.path.dirname(final_path), f"{STAGING_PREFIX}{uuid4().hex[:12]}.pdf"
    )
    try:
        with open(staging, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(staging, final_path)
    except Exception:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass
        raise
    # Best-effort parent-dir fsync (durability on Linux; no-op on Windows).
    try:
        dir_fd = os.open(os.path.dirname(final_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, AttributeError):
        pass
    return sha, len(content)


def _best_effort_delete(path: str) -> None:
    """Delete a file, swallowing I/O errors. Used to clean up the just-written
    PDF when the issuance transaction fails so it does not orphan on disk.
    SYNC → call via to_thread."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def issue_enrollment_letter(
    db,
    profile,
    start_date,
    end_date,
    current_user,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple["models.EnrollmentLetter", bytes]:
    """Render + persist an official letter. Returns (row, pdf_bytes).

    Caller (router) commits. Date validation (end >= start) is done at the API
    schema layer; this trusts the validated inputs.
    """
    data = await build_letter_data(db, profile)
    render_data = {
        **data,
        "enrollment_start_date": start_date.isoformat(),
        "enrollment_end_date": end_date.isoformat(),
    }

    # ReportLab is synchronous + CPU-bound → keep it off the event loop.
    pdf_bytes = await to_thread.run_sync(render_enrollment_letter, render_data)

    final_path = os.path.join(
        settings.ENROLLMENT_LETTER_STORAGE_DIR, str(profile.id), f"{uuid4().hex}.pdf"
    )
    sha, size = await to_thread.run_sync(_write_pdf_atomic, pdf_bytes, final_path)

    # KHOÁ MUỘN: chỉ giữ SELECT FOR UPDATE từ đây tới lúc router commit, thay vì
    # từ đầu request. Lấy khoá ở dependency (như bản trước) nghĩa là giữ khoá
    # ghi trên hồ sơ suốt cả quá trình render ReportLab + fsync — mọi thao tác
    # song song trên đúng hồ sơ đó (duyệt, ghi nhận thanh toán, rút hồ sơ) phải
    # xếp hàng sau, và trên volume mạng chậm thì đủ lâu để chúng timeout.
    #
    # Đổi lại phải KIỂM TRA LẠI gate sau khi có khoá: trong lúc render, hồ sơ có
    # thể đã bị rollback về draft / rút / thôi học. Không kiểm lại thì ta vừa
    # đánh mất đúng thứ mà cái khoá sinh ra để bảo vệ.
    # Chỉ SELECT 2 cột cần cho gate: ``select(models.AdmissionProfile)`` sẽ kéo
    # theo eager-join sang ``lead`` và Postgres từ chối FOR UPDATE trên nhánh
    # nullable của outer join (đúng cảnh báo trong deps.py). Khoá theo cột vẫn
    # khoá đúng row.
    locked = (
        await db.execute(
            select(
                models.AdmissionProfile.status,
                models.AdmissionProfile.is_dropped,
            )
            .where(models.AdmissionProfile.id == profile.id)
            .with_for_update()
        )
    ).first()
    if locked is None or not is_enrollment_letter_eligible(
        SimpleNamespace(status=locked[0], is_dropped=locked[1])
    ):
        await to_thread.run_sync(_best_effort_delete, final_path)
        raise BusinessRuleViolation(
            "Hồ sơ đã đổi trạng thái trong lúc tạo giấy báo — không phát hành. "
            "Hãy tải lại trang và kiểm tra trạng thái hồ sơ."
        )

    _now = datetime.now(timezone.utc)
    expires_at = _now + timedelta(days=settings.ENROLLMENT_LETTER_RETENTION_DAYS)
    letter = models.EnrollmentLetter(
        profile_id=profile.id,
        enrollment_start_date=start_date,
        enrollment_end_date=end_date,
        data_snapshot=data,
        file_path=final_path,
        sha256=sha,
        file_size=size,
        generated_by_id=current_user.id if current_user else None,
        expires_at=expires_at,
    )
    db.add(letter)
    try:
        await db.flush()
        # Bản vừa phát trở thành BẢN HIỆN HÀNH; mọi bản trước của cùng hồ sơ
        # đóng dấu "đã thay thế" và ĐƯỢC KÉO DÀI hạn lưu trữ bằng bản mới.
        #
        # Vì sao đồng bộ expires_at: hạn tính riêng từng bản kể từ lúc phát,
        # nên bản 1 — bản nhiều khả năng ĐÃ TRAO TAY thí sinh — hết hạn và bị
        # xoá PII TRƯỚC bản 2 mà chưa ai cầm. Khi có tranh chấp "giấy tôi cầm
        # ghi gì", bằng chứng còn sống lại là bản sai. Cho cả nhóm chết cùng
        # lúc theo bản mới nhất.
        await db.execute(
            update(models.EnrollmentLetter)
            .where(
                models.EnrollmentLetter.profile_id == profile.id,
                models.EnrollmentLetter.id != letter.id,
                models.EnrollmentLetter.superseded_at.is_(None),
            )
            .values(superseded_at=_now, expires_at=expires_at)
        )
    except Exception:
        # Flush failed → the PDF we just wrote would orphan on disk with no
        # row referencing it. Delete it before propagating. (A router commit
        # failure AFTER this is cleaned up by the router; the periodic cleanup
        # task is the final backstop.)
        await to_thread.run_sync(_best_effort_delete, final_path)
        raise
    # Audit the issuance (symmetry with the 'downloaded' event) so the
    # EntityAuditLog access stream also captures the initial PII-PDF delivery,
    # not just re-downloads. Committed by the router.
    db.add(
        models.EntityAuditLog(
            entity_type="EnrollmentLetter",
            entity_id=letter.id,
            action="issued",
            actor_user_id=current_user.id if current_user else None,
            source="api",
            ip_address=(ip_address or None),
            user_agent=(user_agent[:500] if user_agent else None),
            reason=f"Phát giấy báo nhập học hồ sơ #{profile.id}",
        )
    )
    log.info(
        "enrollment_letter.issued",
        letter_id=letter.id,
        profile_id=profile.id,
        generated_by=current_user.id if current_user else None,
    )
    return letter, pdf_bytes


async def get_letter_record(db, profile_id: int, letter_id: int):
    """Fetch an issuance row scoped to ``profile_id`` (IDOR handled upstream by
    the profile dependency). Returns None if not found / not this profile's."""
    stmt = select(models.EnrollmentLetter).where(
        models.EnrollmentLetter.id == letter_id,
        models.EnrollmentLetter.profile_id == profile_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def discard_letter_file(letter) -> None:
    """Best-effort delete the letter's PDF from disk — called by the router if
    the commit fails AFTER issuance flushed, so a rolled-back letter does not
    orphan its file. Safe post-rollback: file_path is a loaded scalar
    (expire_on_commit=False)."""
    await to_thread.run_sync(_best_effort_delete, letter.file_path)


async def list_letters_for_profile(db, profile_id: int):
    """Issued letters for a profile, newest first (for the re-download UI).

    Kept in the service so the router stays a dumb translator (no db.execute /
    raw SQL in the HTTP layer)."""
    stmt = (
        select(models.EnrollmentLetter)
        .where(models.EnrollmentLetter.profile_id == profile_id)
        .order_by(models.EnrollmentLetter.generated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_letter_for_download(
    db,
    profile_id: int,
    letter_id: int,
    actor_user_id: int | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """Resolve a letter for re-download (IDOR-scoped to profile) AND record a
    'downloaded' access-audit row (A09 — mirrors document download).

    Raises ResourceNotFoundError (→ 404, no existence leak) if the letter is not
    this profile's or the file has been purged by retention. Flushes the audit;
    the router commits before streaming the file.
    """
    letter = await get_letter_record(db, profile_id, letter_id)
    now = datetime.now(timezone.utc)
    # 404 (no existence leak) for: not this profile's · file purged · past
    # retention (expires_at). Mirrors the SMS export "expired → not served" gate
    # so an expired official document is never downloadable even if the daily
    # cleanup task has not yet removed the file.
    if (
        letter is None
        or not os.path.exists(letter.file_path)
        or (letter.expires_at is not None and letter.expires_at <= now)
    ):
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )

    # THU HỒI THEO TRẠNG THÁI HIỆN TẠI của hồ sơ. Không luồng nào (rút hồ sơ /
    # từ chối / thôi học / rollback về nháp) đụng tới bảng enrollment_letter,
    # nên nếu chỉ kiểm row thì giấy "Đã trúng tuyển" của một thí sinh đã rút hồ
    # sơ vẫn tải về được suốt cả thời hạn lưu trữ. Kiểm tại thời điểm tải là
    # cách rẻ nhất mà luôn đúng: không cần cột revoked_at, không cần hook vào
    # mọi luồng workflow, và tự đúng lại nếu hồ sơ được khôi phục.
    profile_state = (
        await db.execute(
            select(
                models.AdmissionProfile.status,
                models.AdmissionProfile.is_dropped,
            ).where(models.AdmissionProfile.id == profile_id)
        )
    ).first()
    if profile_state is None or not is_enrollment_letter_eligible(
        SimpleNamespace(status=profile_state[0], is_dropped=profile_state[1])
    ):
        log.info(
            "enrollment_letter.download_blocked_ineligible_profile",
            letter_id=letter_id,
            profile_id=profile_id,
            status=None if profile_state is None else profile_state[0],
        )
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )
    # Integrity (A08): recompute the sha256 and refuse to stream a
    # tampered/corrupt official PDF. Chunked read off the event loop.
    actual_sha = await to_thread.run_sync(sha256_file, letter.file_path)
    if actual_sha != letter.sha256:
        log.error(
            "enrollment_letter.integrity_mismatch",
            letter_id=letter.id,
            profile_id=profile_id,
            expected_sha256=letter.sha256,
            actual_sha256=actual_sha,
        )
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )
    db.add(
        models.EntityAuditLog(
            entity_type="EnrollmentLetter",
            entity_id=letter.id,
            action="downloaded",
            actor_user_id=actor_user_id,
            source="api",
            ip_address=(ip_address or None),
            user_agent=(user_agent[:500] if user_agent else None),
            reason=f"Tải giấy báo nhập học hồ sơ #{profile_id}",
        )
    )
    await db.flush()
    return letter
