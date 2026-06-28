# app/services/public_lead_intake_service.py
"""Service nhận lead công khai từ website (WordPress/Formidable).

Không nhận ``current_user`` (luồng hệ thống). Tuân kiến trúc V3: chỉ flush, trả
``(result, post_commit_callback)`` cho router commit + chạy callback.

Hành vi (xem ``Documents/WEBSITE_LEAD_INTAKE_PLAN.md``):
- Honeypot ``hp`` có giá trị ⇒ coi là bot → trả 200 "thành công" GIẢ, KHÔNG tạo lead.
- Upsert-by-phone qua bảng canonical ``lead_phone_identity`` dưới advisory lock
  (race-safe). Trùng SĐT → cập nhật / ghi nhận, KHÔNG tạo trùng.
- SĐT mới → tạo lead ``source="website"`` ở đơn vị mặc định (env) → auto-assign.
- Lead đã ngừng tư vấn (terminal) / đã có hồ sơ → CHỈ ghi nhận, KHÔNG reopen.
- Mọi lead cũ đều được thông báo cho officer/quản lý đơn vị (re-engagement signal).
- Hệ/ngành/ghi-chú từ web → lưu vào một Consultation HỆ THỐNG (officer = system user,
  insert raw, KHÔNG đổi pipeline) để officer đọc trong timeline. Consultation này
  KHÔNG cập nhật ``last_consultation_at``/``consultation_count`` (không phải lần
  officer liên hệ thật → tránh phá SLA auto-close + méo urgency/recency).
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import text
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
# Giá trị tùy ý, miễn ổn định + riêng cho luồng intake để không đụng lock khác.
_INTAKE_ADVISORY_NS = 815074  # "intake"

# Múi giờ Việt Nam cho nhãn ngày trong note (officer đọc theo giờ địa phương).
_VN_TZ = timezone(timedelta(hours=7))

# Chuẩn hoá nhãn trình độ thô từ web → EducationLevelEnum của Lead (bind enum để
# không drift khi đổi tên member).
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
    """Gộp hệ/ngành/ghi-chú + địa chỉ thành 1 ghi chú có tiền tố ngày (giờ VN)."""
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
    """True nếu lead đã có hồ sơ tuyển sinh (AdmissionProfile hard-delete, không có
    cột deleted_at → chỉ cần kiểm tra tồn tại)."""
    return bool(lead.admission_profiles)


def _backfill_empty_fields(lead: models.Lead, data: schemas.PublicLeadIntake) -> bool:
    """Điền các trường cấu trúc còn TRỐNG từ web (KHÔNG ghi đè dữ liệu officer đã có).

    Trả True nếu có thay đổi (để bump version).
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


async def _insert_system_consultation(
    db: AsyncSession, lead: models.Lead, note: str
) -> Optional[models.Consultation]:
    """Chèn Consultation HỆ THỐNG (timeline note) — KHÔNG qua add_consultation.

    officer = system user; status = trạng thái hiện tại của lead (tránh "Status
    #null" trên UI); KHÔNG đổi ``lead.consultation_status_id``/pipeline → không
    reopen lead terminal.

    KHÔNG gọi ``update_lead_cache``: system note KHÔNG phải lần officer liên hệ
    thật, nên KHÔNG được đẩy ``last_consultation_at``=now (phá SLA auto-close
    sts04) hay tăng ``consultation_count``/``cached_urgency_score``.

    Nếu user kỹ thuật 'system' không khả dụng (thiếu/fingerprint sai) → bỏ note,
    GIỮ lead (không làm mất lead vì một phụ thuộc phụ trợ). Trả None khi đó.
    """
    # Lazy import: payment_import_service kéo theo finance models → tránh
    # circular import lúc load module.
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
    # Đánh dấu state đổi cho optimistic-lock (officer giữ version cũ → PUT sẽ 409).
    lead.version = (lead.version or 1) + 1
    return consultation


async def _handle_existing_lead(
    db: AsyncSession, lead: models.Lead, data: schemas.PublicLeadIntake, note: str
) -> Tuple[schemas.PublicLeadIntakeResult, List[Callable]]:
    """Lead đã tồn tại (trùng SĐT): cập nhật field trống + ghi nhận, KHÔNG reopen."""
    callbacks: List[Callable] = []

    is_terminal = is_consultation_terminal_status(lead.consultation_status)
    has_profile = _lead_has_profile(lead)

    # Backfill field cấu trúc còn trống (location/education) — KHÔNG ghi đè.
    changed = _backfill_empty_fields(lead, data)

    consultation = await _insert_system_consultation(db, lead, note)
    if changed and consultation is None:
        # Có backfill nhưng không chèn được consultation → vẫn bump version.
        lead.version = (lead.version or 1) + 1

    # Thông báo officer/quản lý đơn vị cho MỌI lead cũ (re-engagement signal) —
    # rule sẵn fanout lead_owner + unit_managers; actor=None → actor_excluded
    # không loại ai. Chỉ dispatch khi có consultation (cần consultation.id).
    if consultation is not None:
        _, notif_cb = await dispatch(
            db=db,
            event=SystemEvents.CONSULTATION_CREATED,
            payload=EventPayload.for_consultation_created(consultation, lead, None),
            dedupe_key=f"intake_existing:{consultation.id}",
            rooms=rooms_for_lead(lead),
        )
        if notif_cb:
            callbacks.append(notif_cb)

    status = "noted" if (is_terminal or has_profile) else "updated"
    return schemas.PublicLeadIntakeResult(status=status, lead_id=lead.id), callbacks


async def intake_public_lead(
    db: AsyncSession, data: schemas.PublicLeadIntake
) -> Tuple[schemas.PublicLeadIntakeResult, Optional[Callable]]:
    """Điểm vào: nhận 1 lead từ website. Trả ``(result, post_commit_callback)``."""
    # 0. Honeypot — bot điền ``hp`` → trả 200 GIẢ, KHÔNG tạo lead (bot không biết).
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

    # 4. Tạo lead mới (source=website, unit mặc định) → auto-assign qua callback.
    lead_in = schemas.LeadCreate(
        full_name=data.full_name,
        phone=phone,
        email=data.email,
        source="website",
        unit_id=default_unit_id,
        education_level=_normalize_education(data.education_level_raw),
        location=data.address,
    )
    try:
        lead, create_cb = await lead_service.create_lead(db, lead_in, created_by=None)
    except DuplicateResourceError:
        # create_lead chặn trùng theo SĐT (phone/phone2) HOẶC email (cùng đơn vị).
        # Nếu reload canonical thấy lead → xử lý như existing (race SĐT). Nếu KHÔNG
        # (vd trùng EMAIL khác SĐT) → raise lỗi ĐÃ LÀM SẠCH PII (detail gốc chứa
        # tên/SĐT/đơn vị/officer của lead khác — KHÔNG được rò ra caller công khai).
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
