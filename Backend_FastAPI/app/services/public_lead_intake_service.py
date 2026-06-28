# app/services/public_lead_intake_service.py
"""Service nhận lead công khai từ website (WordPress/Formidable).

Không nhận ``current_user`` (luồng hệ thống). Tuân kiến trúc V3: chỉ flush, trả
``(result, post_commit_callback)`` cho router commit + chạy callback.

Hành vi (xem ``Documents/WEBSITE_LEAD_INTAKE_PLAN.md``):
- Honeypot ``hp`` có giá trị ⇒ coi là bot → KHÔNG tạo lead.
- Upsert-by-phone qua bảng canonical ``lead_phone_identity`` dưới advisory lock
  (race-safe). Trùng SĐT → cập nhật / ghi nhận, KHÔNG tạo trùng.
- SĐT mới → tạo lead ``source="website"`` ở đơn vị mặc định (env) → auto-assign.
- Lead đã ngừng tư vấn (terminal) / đã có hồ sơ → CHỈ ghi nhận, KHÔNG reopen.
- Email KHÔNG ghi vào Lead.email (tránh xung đột unique + oracle) — chỉ vào note.
- Hệ/ngành/ghi-chú/email → một Consultation HỆ THỐNG (officer = system user, insert
  raw, method="website") để officer đọc trong timeline. Consultation này bị LOẠI
  khỏi aggregate recency/count (xem ``get_consultation_aggregates``) nên KHÔNG phá
  SLA auto-close / méo urgency.
- Chống amplification: bỏ qua nếu đã có website-consultation gần đây cho lead này.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings
from app.core.events import SystemEvents
from app.core.status_mapping import is_consultation_terminal_status
from app.models.lead import EducationLevelEnum
from app.repositories.lead_repository import LeadRepository
from app.services import lead_service
from app.services.notification_bundle import compose_post_commit_callbacks
from app.services.notification_dispatcher import dispatch, rooms_for_lead
from app.services.notification_payloads import EventPayload
from app.utils.exceptions import (
    ConflictError,
    DuplicateResourceError,
    ServiceUnavailableError,
)
from app.utils.text_helpers import strip_accents

log = structlog.get_logger("public_lead_intake")

# Namespace cố định cho pg_advisory_xact_lock (2 tham số int: ns + hashtext(phone)).
_INTAKE_ADVISORY_NS = 815074  # "intake"

# Múi giờ Việt Nam cho nhãn ngày trong note (officer đọc theo giờ địa phương).
_VN_TZ = timezone(timedelta(hours=7))

# Cửa sổ chống lặp: trong khoảng này KHÔNG chèn thêm website-consultation/notif.
_DEDUP_WINDOW = timedelta(hours=6)

# Chuẩn hoá nhãn trình độ thô từ web → EducationLevelEnum của Lead (bind enum).
_EDUCATION_MAP = {
    "thpt": EducationLevelEnum.high_school.value,
    "trung hoc pho thong": EducationLevelEnum.high_school.value,
    "trung cap": EducationLevelEnum.diploma.value,
    "cao dang": EducationLevelEnum.diploma.value,
    "dai hoc": EducationLevelEnum.bachelor.value,
    "thac si": EducationLevelEnum.master.value,
    "tien si": EducationLevelEnum.phd.value,
    "thcs": EducationLevelEnum.other.value,
    "trung hoc co so": EducationLevelEnum.other.value,
    "khac": EducationLevelEnum.other.value,
}


def _normalize_education(raw: Optional[str]) -> Optional[str]:
    """Map nhãn trình độ thô (có dấu/không dấu) → enum; không khớp → None."""
    if not raw:
        return None
    key = strip_accents(raw.strip().lower())
    return _EDUCATION_MAP.get(key)


def _build_intake_note(data: schemas.PublicLeadIntake) -> str:
    """Gộp hệ/ngành/ghi-chú + địa chỉ + email thành 1 ghi chú có tiền tố ngày (giờ VN).

    Note luôn bắt đầu bằng "[" → khi export cell KHÔNG bị Excel hiểu là công thức
    (CSV/formula-injection chỉ kích hoạt khi cell BẮT ĐẦU bằng = + - @).
    """
    today = datetime.now(_VN_TZ).strftime("%d/%m/%Y")
    parts: List[str] = []
    if data.he:
        parts.append(f"Hệ: {data.he}")
    if data.nganh_xet:
        parts.append(f"Ngành xét tuyển: {data.nganh_xet}")
    if data.nganh_dang_ky:
        parts.append(f"Ngành đăng ký: {data.nganh_dang_ky}")
    if data.address:
        parts.append(f"Địa chỉ: {data.address}")
    if data.email:
        parts.append(f"Email: {data.email}")
    if data.extra_note:
        parts.append(f"Ghi chú: {data.extra_note}")
    body = " | ".join(parts) if parts else "Đăng ký không kèm thông tin bổ sung"
    return f"[Đăng ký qua website {today}] {body}"


async def _advisory_lock_phone(db: AsyncSession, phone_normalized: str) -> None:
    """Khóa advisory theo SĐT chuẩn hoá — serialize request cùng số (chống race)."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:phone))"),
        {"ns": _INTAKE_ADVISORY_NS, "phone": phone_normalized},
    )


def _lead_has_profile(lead: models.Lead) -> bool:
    """True nếu lead đã có hồ sơ tuyển sinh (AdmissionProfile hard-delete → chỉ cần
    kiểm tra tồn tại)."""
    return bool(lead.admission_profiles)


def _backfill_empty_fields(lead: models.Lead, data: schemas.PublicLeadIntake) -> bool:
    """Điền các trường cấu trúc còn TRỐNG từ web (KHÔNG ghi đè dữ liệu officer đã có).

    Trả True nếu có thay đổi. CHỈ gọi cho lead active (nhánh 'updated') — KHÔNG đụng
    lead terminal/đã-có-hồ-sơ để hạn chế bề mặt poisoning từ caller ẩn danh.
    """
    changed = False
    if not lead.location and data.address:
        lead.location = data.address
        changed = True
    if not lead.education_level:
        edu = _normalize_education(data.education_level_raw)
        if edu:
            lead.education_level = edu
            changed = True
    return changed


async def _recent_website_consultation_exists(db: AsyncSession, lead_id: int) -> bool:
    """True nếu lead đã có website-consultation trong ``_DEDUP_WINDOW`` (chống lặp
    note/notif/version-churn khi WP retry hoặc bị spam)."""
    cutoff = datetime.now(timezone.utc) - _DEDUP_WINDOW
    result = await db.execute(
        select(models.Consultation.id)
        .where(
            models.Consultation.lead_id == lead_id,
            models.Consultation.method == "website",
            models.Consultation.deleted_at.is_(None),
            models.Consultation.consultation_date >= cutoff,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _insert_system_consultation(
    db: AsyncSession, lead: models.Lead, note: str
) -> Optional[models.Consultation]:
    """Chèn Consultation HỆ THỐNG (timeline note) — KHÔNG qua add_consultation.

    officer = system user; status = trạng thái hiện tại của lead; KHÔNG đổi
    pipeline → không reopen lead terminal. KHÔNG bump version ở đây (caller bump).

    Nếu user kỹ thuật 'system' không khả dụng → bỏ note, GIỮ lead. Trả None khi đó.
    """
    from app.services.payment_import_service import get_system_user

    try:
        system_user = await get_system_user(db)
    except ConflictError as exc:
        log.warning(
            "intake: system user unavailable, skipping timeline note",
            lead_id=lead.id,
            error=str(exc),
        )
        return None

    consultation = models.Consultation(
        lead_id=lead.id,
        officer_id=system_user.id,
        consultation_status_id=lead.consultation_status_id,
        consultation_date=datetime.now(timezone.utc),
        method="website",
        notes=note,
    )
    db.add(consultation)
    await db.flush()
    return consultation


async def _dispatch_existing_notif(
    db: AsyncSession, lead: models.Lead, consultation: models.Consultation
) -> Optional[Callable]:
    """Dispatch CONSULTATION_CREATED cho lead cũ trong SAVEPOINT — lỗi persist
    notification CHỈ rollback savepoint, KHÔNG kéo cả intake (chống mất dữ liệu)."""
    try:
        async with db.begin_nested():
            _, notif_cb = await dispatch(
                db=db,
                event=SystemEvents.CONSULTATION_CREATED,
                payload=EventPayload.for_consultation_created(consultation, lead, None),
                dedupe_key=f"intake_existing:{consultation.id}",
                rooms=rooms_for_lead(lead),
                strict=True,
            )
        return notif_cb
    except Exception as exc:  # noqa: BLE001 — best-effort, savepoint đã rollback
        log.warning(
            "intake: notification dispatch failed (savepoint rolled back)",
            lead_id=lead.id,
            error=str(exc),
        )
        return None


async def _handle_existing_lead(
    db: AsyncSession, lead: models.Lead, data: schemas.PublicLeadIntake, note: str
) -> Tuple[schemas.PublicLeadIntakeResult, List[Callable]]:
    """Lead đã tồn tại (trùng SĐT): cập nhật field trống + ghi nhận, KHÔNG reopen."""
    callbacks: List[Callable] = []
    is_terminal = is_consultation_terminal_status(lead.consultation_status)
    has_profile = _lead_has_profile(lead)
    status = "noted" if (is_terminal or has_profile) else "updated"

    # Chống amplification: đã có website-consultation gần đây → no-op idempotent.
    if await _recent_website_consultation_exists(db, lead.id):
        return schemas.PublicLeadIntakeResult(status=status, lead_id=lead.id), callbacks

    mutated = False
    # Backfill CHỈ cho lead active (updated) — không đụng terminal/đã-có-hồ-sơ.
    if status == "updated" and _backfill_empty_fields(lead, data):
        mutated = True

    consultation = await _insert_system_consultation(db, lead, note)
    if consultation is not None:
        mutated = True
        notif_cb = await _dispatch_existing_notif(db, lead, consultation)
        if notif_cb:
            callbacks.append(notif_cb)

    # Bump version 1 lần nếu có thay đổi state (optimistic-lock cho officer).
    if mutated:
        lead.version = (lead.version or 1) + 1

    return schemas.PublicLeadIntakeResult(status=status, lead_id=lead.id), callbacks


async def intake_public_lead(
    db: AsyncSession, data: schemas.PublicLeadIntake
) -> Tuple[schemas.PublicLeadIntakeResult, Optional[Callable]]:
    """Điểm vào: nhận 1 lead từ website. Trả ``(result, post_commit_callback)``.

    Lưu ý: ``result`` (created/updated/noted + lead_id thật) chỉ dùng NỘI BỘ
    (log/test). Router trả response GENERIC cho caller (chống enumeration).
    """
    # 0. Honeypot — bot điền ``hp`` (đã trim ở schema) → KHÔNG tạo lead.
    if data.hp:
        return schemas.PublicLeadIntakeResult(status="created", lead_id=0), None

    # 1. Đơn vị mặc định (D9) — fail-closed nếu chưa cấu hình / không tồn tại.
    default_unit_id = settings.PUBLIC_INTAKE_DEFAULT_UNIT_ID
    if default_unit_id is None:
        raise ServiceUnavailableError(
            detail=(
                "Website intake chưa cấu hình đơn vị mặc định "
                "(PUBLIC_INTAKE_DEFAULT_UNIT_ID)."
            )
        )
    unit = await db.get(models.OrganizationUnit, default_unit_id)
    if unit is None:
        raise ServiceUnavailableError(
            detail="Đơn vị mặc định của website intake không tồn tại."
        )

    phone = data.phone  # đã normalize ở schema validator
    note = _build_intake_note(data)
    callbacks: List[Callable] = []

    # 2. Khóa advisory theo SĐT — serialize request cùng số.
    await _advisory_lock_phone(db, phone)

    # 3. Lookup canonical (KHÔNG dùng get_by_phone raw).
    repo = LeadRepository(db)
    existing = await repo.get_active_lead_by_phone_identity(phone)

    if existing is not None:
        result, cbs = await _handle_existing_lead(db, existing, data, note)
        callbacks.extend(cbs)
        return result, compose_post_commit_callbacks(
            label="intake", callbacks=callbacks
        )

    # 4. Tạo lead mới (source=website, unit mặc định). KHÔNG set Lead.email (tránh
    # xung đột unique uq_lead_email_unit_active + email-existence oracle) — email
    # đã nằm trong note. → DuplicateResourceError giờ chỉ còn từ SĐT (race hiếm).
    lead_in = schemas.LeadCreate(
        full_name=data.full_name,
        phone=phone,
        source="website",
        unit_id=default_unit_id,
        education_level=_normalize_education(data.education_level_raw),
        location=data.address,
    )
    try:
        lead, create_cb = await lead_service.create_lead(db, lead_in, created_by=None)
    except (DuplicateResourceError, IntegrityError):
        # Race SĐT giữa lookup và create (advisory lock chặn phần lớn). Reload
        # canonical → xử lý như existing; nếu vẫn None → lỗi ĐÃ LÀM SẠCH PII
        # (detail gốc chứa tên/SĐT/đơn vị/officer lead khác — KHÔNG rò ra caller).
        existing = await repo.get_active_lead_by_phone_identity(phone)
        if existing is None:
            raise DuplicateResourceError(
                detail="Thông tin đăng ký trùng với một hồ sơ đã có."
            )
        result, cbs = await _handle_existing_lead(db, existing, data, note)
        callbacks.extend(cbs)
        return result, compose_post_commit_callbacks(
            label="intake", callbacks=callbacks
        )

    if create_cb:
        callbacks.append(create_cb)
    await _insert_system_consultation(db, lead, note)
    log.info("website lead created", lead_id=lead.id, unit_id=default_unit_id)
    return (
        schemas.PublicLeadIntakeResult(status="created", lead_id=lead.id),
        compose_post_commit_callbacks(label="intake", callbacks=callbacks),
    )
