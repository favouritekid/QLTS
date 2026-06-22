# app/services/admission_service.py
"""
Admission Service - Business logic for AdmissionProfile workflow.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks in ALL functions (lead.unit_id == user.unit_id)
- Transactions: Services use db.add()/db.flush(), Router commits via db.commit()
- Performance: selectinload to prevent N+1 queries
- Error Handling: Raise custom exceptions (ResourceNotFoundError, BadRequest, etc.)

Workflow:
1. CREATE: Officer creates profile -> snapshot admission_rules from ProgramOffering
2. UPDATE: Officer updates profile (only when status = 'draft')
3. SUBMIT: System validates against applied_rules -> auto-approve or return errors
4. ENROLL: System creates Student + StudentDocument (ACID transaction)

Security Features:
- IDOR Protection: All functions check lead.unit_id == current_user.unit_id (unless admin)
- Snapshot Pattern: Validation uses applied_rules (never queries ProgramOffering)
- State Locking: Updates only allowed when status = 'draft'
- ACID Transactions: enroll_student uses begin_nested() savepoint
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Awaitable, List, Optional, Dict, Any, Tuple, Callable
from decimal import Decimal, InvalidOperation
import structlog
from sqlalchemy import or_, and_, select, func
from sqlalchemy.exc import IntegrityError

from app.utils.redis_lock import acquire_redis_lock
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from .. import models
from ..admission_metrics import admission_quota_skip_total
from ..core.events import SystemEvents
from ..core.admission_correction_constants import (
    SAFE_MINOR_CORRECTION_FIELDS,
    HARD_DENY_FIELDS,
)
from ..schemas.admission import DEFAULT_UPLOAD_CONFIG
from ..core.constants import UserRole
from .admission_state_service import transition as state_transition
from .commission_service import safe_check_commission_on_status_change
from .notification_bundle import (
    NotificationIntent,
    compose_post_commit_callbacks,
    dispatch_bundle,
)
from .notification_dispatcher import rooms_for_admission
from .admission_correction_helpers import (
    parse_and_normalize,
    post_parse_business_check,
    safe_serialize,
)
from ..utils.admission_status import (
    is_admitted_like,
    is_confirmation_eligible,
    is_fee_eligible,
)
from ..utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    PermissionDeniedError,
    ConflictError,
    ValidationError,
)
from ..utils.admission_round_guards import assert_round_open
from ..utils.masking import mask_citizen_id

log = structlog.get_logger(__name__)


# ADM-012: Safe domain exceptions whose ``str()`` is user-facing copy.
# Anything outside this tuple becomes "Unexpected error" + correlation id
# in bulk-action error maps so internal DB/stack details cannot leak to
# the client. Keep this tuple in sync with imports above.
_BULK_SAFE_DOMAIN_EXCEPTIONS = (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    PermissionDeniedError,
    ConflictError,
    ValidationError,
)


def _resolve_under(base_dir: str, candidate_path: str) -> Optional[str]:
    """Path-traversal guard. Return the resolved absolute path iff
    ``candidate_path`` stays under ``base_dir`` after normalizing ``..``,
    else ``None``.

    Mirrors ``file_helpers.py`` (``Path.resolve`` + ``os.path.commonpath``);
    reused by the upload builders and the authed download endpoint so a
    tampered/malformed path can never escape the profile's upload dir.
    """
    import os
    from pathlib import Path

    base = Path(base_dir).resolve(strict=False)
    target = Path(candidate_path).resolve(strict=False)
    try:
        if os.path.commonpath([str(base), str(target)]) != str(base):
            return None
    except ValueError:
        # commonpath raises on mixed drives / empty input — treat as unsafe.
        return None
    return str(target)


def _sniff_document_signature(stream) -> Optional[str]:
    """ADM-019: detect a document upload's true type by magic bytes.

    Returns ``"pdf"`` / ``"jpeg"`` / ``"png"`` when the first bytes of
    ``stream`` match a known signature, ``None`` otherwise. The stream
    cursor is restored to the start so the caller can still write the
    file out.

    Why magic bytes:
    - ``UploadFile.content_type`` is taken straight from the multipart
      header — fully attacker-controlled.
    - The filename extension is just as untrusted.
    - Without sniffing, a renamed ``.exe`` or HTML file with a forged
      ``Content-Type: application/pdf`` would still pass validation.

    We deliberately avoid pulling in ``python-magic`` / libmagic so the
    check works in any container without an extra system dep.
    """
    try:
        stream.seek(0)
        head = stream.read(8)
    finally:
        try:
            stream.seek(0)
        except Exception:  # pragma: no cover — defensive
            pass

    if not head:
        return None

    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def _safe_bulk_error_message(
    exc: Exception,
    *,
    bulk_label: str,
    profile_id: int,
    actor_id: Optional[int] = None,
) -> str:
    """Return a client-safe message for a bulk-action failure.

    - Domain exceptions: pass through their message (already user-facing).
    - Anything else: log full detail server-side with a correlation id and
      return ``"Unexpected error (ref: <uuid>)"`` so internals do not leak.

    The correlation id is logged alongside the original exception so ops
    can pivot from a client report ("ref abc-123") to the full traceback.
    """
    import uuid as _uuid

    if isinstance(exc, _BULK_SAFE_DOMAIN_EXCEPTIONS):
        return str(exc)

    correlation_id = _uuid.uuid4().hex[:12]
    log.exception(
        "bulk_action_unexpected_error",
        bulk_label=bulk_label,
        profile_id=profile_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        error=str(exc),
        error_type=exc.__class__.__name__,
    )
    return f"Unexpected error (ref: {correlation_id})"


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _authorize_document_action(
    *,
    action: str,
    profile: models.AdmissionProfile,
    doc_status: str,
    doc_code: str,
    current_user: models.User,
) -> None:
    """Enforce the PR #5 document-action matrix at the service layer.

    Delegates to :class:`DocumentActionPolicy` — same matrix
    ``_compute_document_permissions`` (in ``_compute_frontend_fields``)
    consults to build the per-document ``can_*`` response flags.
    Single source of truth means the FE flag promise and the BE gate
    stay in lockstep automatically; updating one branch without the
    other is no longer possible.

    Casbin gates the route at role level (officer can hit
    ``/paper-submitted``, manager ``/verify-format`` / ``/reject`` /
    ``/reset``); the policy adds the fine-grained rules Casbin can't
    express: unit scope for manager, owner check for officer, allowed
    ``doc_status`` transition, and ``requires_upload`` flag for
    paper-submit.

    ``action`` is one of: ``"upload"``, ``"paper_submitted"``,
    ``"verify"``, ``"reject"``, ``"reset"``. Raises
    :class:`PermissionDeniedError` on fail — the router maps that to
    404 (no existence leak).
    """
    from .admission_document_policy import DocumentActionPolicy

    applied_rules = profile.applied_rules or {}
    doc_configs = applied_rules.get("doc_configs", {}) or {}
    config = doc_configs.get(doc_code, {}) or {}
    requires_upload = bool(config.get("requires_upload", True))

    # BR2 (2026-04-29; fix 2026-06-09): the document is "extra" — exists in
    # the DB but is no longer in the current ``applied_rules.doc_configs``
    # (typically because the AdmissionPath was edited after the profile was
    # created). The response marks these rows ``is_extra=True`` + clamps every
    # ``can_*`` flag to False (read-only). The service-side gate must mirror
    # that contract. MUST check ``doc_configs`` (mandatory + optional), NOT
    # just ``mandatory_docs`` — else optional docs (``is_mandatory=false``)
    # would be treated as extra here and a real officer/manager mutation
    # rejected even though the FE shows action buttons. Mirrors the builder's
    # ``_active_set`` (= doc_configs keyset). Empty config → every request is
    # on an extra (no snapshot to tell which docs are active).
    if doc_code not in doc_configs:
        raise PermissionDeniedError(
            f"Document '{doc_code}' is no longer in the current admission "
            f"path's document config (treated as extra / evidence-only). "
            f"Direct '{action}' actions are blocked until an explicit "
            f"sync-path action ships."
        )

    policy = DocumentActionPolicy.for_(profile, current_user)
    if not policy.authorize(action, doc_status, requires_upload):
        # 404 per IDOR convention — router translates.
        raise PermissionDeniedError(
            f"Action '{action}' not permitted on document '{doc_code}' "
            f"(status={doc_status}, profile_status={profile.status}, "
            f"role={current_user.role})"
        )


def _resolve_idor_filters(current_user: models.User) -> tuple[Optional[int], Optional[int]]:
    """
    Resolve IDOR filter parameters based on user role.

    Returns (unit_id, assigned_officer_id) for repository queries.
    - Admin: (None, None) — see all
    - Manager: (unit_id, None) — see unit
    - Officer: (unit_id, officer_id) — see only assigned

    Fail-closed: a MANAGER/OFFICER whose ``unit_id IS NULL`` is a
    misconfiguration, not "see everything". The repository treats
    ``unit_id=None`` as *no unit filter* (``admission_repository`` only
    applies the predicate ``if unit_id is not None``), so returning
    ``(None, ...)`` here would silently widen a unit-scoped staff member to a
    system-wide view of every profile / CSV row / status count / nợ-bằng
    entry. Deny instead — mirrors the KPI precedent
    (``test_coverage_manager_no_unit_gets_403``).
    """
    if current_user.role == UserRole.ADMIN:
        return None, None
    elif current_user.role == UserRole.MANAGER:
        if current_user.unit_id is None:
            raise PermissionDeniedError(
                "Tài khoản quản lý chưa được gán đơn vị nên không thể truy "
                "cập danh sách hồ sơ tuyển sinh. Liên hệ quản trị viên để "
                "gán đơn vị."
            )
        return current_user.unit_id, None
    elif current_user.role == UserRole.OFFICER:
        if current_user.unit_id is None:
            # Without a unit the officer filter would collapse to
            # assigned_officer_id alone, leaking any cross-unit lead ever
            # assigned to this officer. Deny rather than under-scope.
            raise PermissionDeniedError(
                "Tài khoản cán bộ chưa được gán đơn vị nên không thể truy "
                "cập danh sách hồ sơ tuyển sinh. Liên hệ quản trị viên để "
                "gán đơn vị."
            )
        return current_user.unit_id, current_user.id
    else:
        # F8 fix 2026-05-16: defense-in-depth fallback. The expected gate
        # is at Casbin (ACCOUNTANT_TEMPLATE B1 deny block), so accountant
        # never reaches here. If a new role bypasses Casbin we return a
        # role-neutral message instead of leaking internal expectations.
        raise PermissionDeniedError(
            f"Vai trò '{current_user.role}' không có quyền truy cập danh sách hồ sơ tuyển sinh."
        )


def _check_idor_access(
    profile: models.AdmissionProfile,
    current_user: Optional[models.User],
) -> None:
    """
    3-tier IDOR Protection for admission profiles.

    Rules:
    - System (current_user=None): Bypass — used by magic-link candidate path
      where the caller has already verified CCCD against the profile (token
      acts as proof of identity, IDOR is not applicable to a candidate
      acting on their own profile).
    - Admin: Full access to all profiles
    - Manager: Access profiles where lead.unit_id == user.unit_id
    - Officer: Access profiles where lead.assigned_officer_id == user.id AND lead.unit_id == user.unit_id

    Raises:
        ResourceNotFoundError: Returns 404 to prevent resource enumeration
    """
    if current_user is None:
        return

    if current_user.role == UserRole.ADMIN:
        return

    if not profile.lead:
        log.error(
            "Data integrity: profile without lead",
            profile_id=profile.id,
        )
        raise ResourceNotFoundError(f"Admission profile {profile.id} not found")

    if current_user.role == UserRole.MANAGER:
        if profile.lead.unit_id == current_user.unit_id:
            return
    elif current_user.role == UserRole.OFFICER:
        if (profile.lead.assigned_officer_id == current_user.id
                and profile.lead.unit_id == current_user.unit_id):
            return

    log.warning(
        "IDOR attempt: User tried to access profile without permission",
        user_id=current_user.id,
        user_role=current_user.role,
        user_unit_id=current_user.unit_id,
        profile_id=profile.id,
        profile_unit_id=profile.lead.unit_id if profile.lead else None,
        profile_officer_id=profile.lead.assigned_officer_id if profile.lead else None,
    )
    raise ResourceNotFoundError(f"Admission profile {profile.id} not found")


# =========================================================================
# ADM-026: Quota enforcement helpers
# =========================================================================

# Statuses that occupy a quota slot. These are profiles already committed to
# the cohort: approved or further along the funnel. ``withdrawn`` and
# pre-approval states (draft/submitted/rejected/resubmitted/revision_requested)
# are NOT counted because they have not yet committed a seat.
#
# Note: ``enrolled`` profiles with ``is_dropped=True`` ARE still counted —
# they took a seat that cannot be reassigned for the same academic year.
# This matches the legal/compliance reading that quota = seats consumed,
# not seats currently active.
QUOTA_OCCUPYING_STATUSES = (
    # Admitted-equivalent (legacy + choice-engine). ``admitted`` lands here
    # forward-compat for #15 — Phase 1 widens the CHECK constraint and #16
    # wires the writes; the moment the new string can land on the column,
    # quota accounting is already correct without touching this site again.
    "approved",
    "overridden",
    "admitted",
    "confirmed",
    "enrolled",
)


async def _resolve_quota_context(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    lock: bool = True,
) -> tuple[Optional[models.OfferingAcademicInfo], Optional[int]]:
    """
    Resolve the OfferingAcademicInfo + quota for ``profile``.

    Strategy:
    1. Prefer ``applied_rules.academic_info_id`` (snapshotted at create_profile).
    2. Fall back to (lead.offering_id, profile.academic_year) for legacy
       profiles that pre-date the snapshot.

    If ``lock=True`` (default), the OfferingAcademicInfo row is acquired
    with ``FOR UPDATE`` to serialize concurrent approve/finalize calls
    against the same offering — without it, two parallel transactions can
    each see ``count < quota`` and both insert, blowing the cap by 1+.

    Returns:
        (academic_info, quota). ``quota`` is ``None`` when the field is
        unset (treat as unlimited / quota disabled). ``academic_info`` is
        ``None`` when the profile cannot be linked to an offering academic
        info row (legacy profile without offering_id, or seed/test data).
    """
    applied_rules = profile.applied_rules or {}
    academic_info_id = applied_rules.get("academic_info_id")

    stmt = select(models.OfferingAcademicInfo)
    if academic_info_id:
        stmt = stmt.where(models.OfferingAcademicInfo.id == academic_info_id)
    else:
        # Fallback: legacy profile. Need lead.offering_id + academic_year.
        if not profile.lead or not getattr(profile.lead, "offering_id", None):
            return (None, None)
        stmt = stmt.where(
            models.OfferingAcademicInfo.offering_id == profile.lead.offering_id,
            models.OfferingAcademicInfo.academic_year == profile.academic_year,
        )

    if lock:
        stmt = stmt.with_for_update()

    result = await db.execute(stmt)
    academic_info = result.scalar_one_or_none()
    if academic_info is None:
        return (None, None)
    return (academic_info, academic_info.annual_admission_quota)


async def _count_quota_occupying_profiles(
    db: AsyncSession,
    *,
    offering_id: int,
    academic_year: int,
    exclude_profile_id: Optional[int] = None,
) -> int:
    """
    Count AdmissionProfile rows that currently occupy a quota seat for the
    given (offering, academic_year). Excludes ``exclude_profile_id`` so a
    transition INTO a quota-occupying status doesn't double-count itself
    when the profile is mid-update.
    """
    stmt = (
        select(func.count(models.AdmissionProfile.id))
        .join(models.Lead, models.AdmissionProfile.lead_id == models.Lead.id)
        .where(
            models.Lead.offering_id == offering_id,
            models.AdmissionProfile.academic_year == academic_year,
            models.AdmissionProfile.status.in_(QUOTA_OCCUPYING_STATUSES),
        )
    )
    if exclude_profile_id is not None:
        stmt = stmt.where(models.AdmissionProfile.id != exclude_profile_id)

    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def _assert_quota_or_bypass(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    actor: models.User,
    bypass_quota: bool,
    bypass_reason: Optional[str],
    *,
    transition: str,
    source: str = "api",
) -> None:
    """
    ADM-026: Enforce ``annual_admission_quota`` for transitions INTO
    quota-occupying statuses (approve / finalize). Emits a durable
    ``entity_audit_log`` row whenever an admin bypasses the cap.

    Behaviour:
    - Profile not yet in a quota status + count + 1 ≤ quota → pass silently.
    - Count + 1 > quota and ``bypass_quota=False`` → raise
      ``BusinessRuleViolation`` (the standard hard-cap error path).
    - ``bypass_quota=True`` and ``actor.role != ADMIN`` → raise
      ``PermissionDeniedError``. Manager cannot bypass under Q12 Option B.
    - ``bypass_quota=True`` without a ≥20-char reason → raise
      ``ValidationError``. Schema-level validators catch this earlier for
      Pydantic-bound payloads, but service-layer callers (tests, internal
      flows) must still satisfy the contract.
    - ``bypass_quota=True`` from admin with valid reason → pass and write
      ``entity_audit_log`` with ``action="quota_bypassed"`` + full
      changeset (quota, count_before/after, actor, reason).

    The OfferingAcademicInfo row is locked (``FOR UPDATE``) before the
    count so concurrent approve/finalize transactions serialize and the
    cap holds under load.

    Args:
        db: Active session (caller's transaction frame).
        profile: AdmissionProfile being transitioned. Must have ``lead``
            eager-loaded so the offering-id fallback works.
        actor: User performing the action.
        bypass_quota: Whether the caller asked to override the cap.
        bypass_reason: Audit-trail evidence. Required iff
            ``bypass_quota=True`` (≥20 chars).
        transition: Short label for audit/log (e.g. ``"approve"``,
            ``"finalize"``, ``"bulk_approve"``).
        source: Audit ``source`` field. Defaults to ``"api"``.

    Raises:
        BusinessRuleViolation: cap reached and no bypass.
        PermissionDeniedError: bypass requested by non-admin.
        ValidationError: bypass requested without valid reason.
    """
    academic_info, quota = await _resolve_quota_context(db, profile, lock=True)

    # ADM-026 review (Round 2): three distinct quota states must be
    # disambiguated. Conflating them was the original bug.
    #   academic_info missing → unconfigured / legacy → SKIP (no enforcement)
    #   quota IS NULL         → "unlimited"          → SKIP (no enforcement)
    #   quota <= 0            → "offering closed"    → BLOCK ALL approves
    #
    # Schema currently allows annual_admission_quota = 0 (ge=0). Treating 0
    # as unlimited would let admin/manager admit unbounded students into a
    # deliberately closed cohort. Instead, 0 (or negative for safety) is a
    # hard block — the only escape is admin bypass with the standard reason
    # contract. This is the safe interpretation; if product wants a
    # different model later (e.g. force schema to ge=1, or rename "0" to
    # "frozen with admin override"), update both schema and this gate
    # together.
    # Disambiguate the two skip flavours so observability can tell them
    # apart. ``_resolve_quota_context`` returns ``(None, None)`` for
    # legacy profiles where neither ``applied_rules.academic_info_id``
    # nor ``lead.offering_id`` is available — that is the SAME data-drift
    # signal as a post-snapshot lead with offering_id stripped (handled
    # below), so both branches tick ``missing_offering_id``. Only the
    # ``quota IS NULL`` (unlimited) flavour stays at debug + no metric.
    if academic_info is None:
        lead_missing_offering = (
            not profile.lead
            or getattr(profile.lead, "offering_id", None) is None
        )
        if lead_missing_offering:
            admission_quota_skip_total.labels(
                reason="missing_offering_id"
            ).inc()
            log.warning(
                "Quota check skipped: legacy profile + missing lead.offering_id",
                profile_id=profile.id,
                transition=transition,
            )
        else:
            log.debug(
                "Quota check skipped: academic_info row not found",
                profile_id=profile.id,
                transition=transition,
            )
        return

    if quota is None:
        log.debug(
            "Quota check skipped (unlimited)",
            profile_id=profile.id,
            transition=transition,
            academic_info_id=academic_info.id,
        )
        return

    # Count seats currently occupied by other profiles. Exclude self so a
    # finalize on an already-approved profile doesn't double-count.
    offering_id = profile.lead.offering_id if profile.lead else None
    if offering_id is None:
        # Snapshot resolved an academic_info row but ``lead.offering_id``
        # was stripped post-snapshot. Same data-drift signal as the
        # legacy branch above — count under the same reason.
        admission_quota_skip_total.labels(reason="missing_offering_id").inc()
        log.warning(
            "Quota check skipped: profile has no lead.offering_id",
            profile_id=profile.id,
            transition=transition,
        )
        return

    count_before = await _count_quota_occupying_profiles(
        db,
        offering_id=offering_id,
        academic_year=profile.academic_year,
        exclude_profile_id=profile.id,
    )
    # If profile is ALREADY in a quota status (e.g. finalize on an approved
    # profile), it was excluded from count_before, so count_after = count_before.
    # If profile is transitioning INTO a quota status from outside (e.g.
    # approve from submitted), count_after = count_before + 1.
    is_already_occupying = profile.status in QUOTA_OCCUPYING_STATUSES
    count_after = count_before if is_already_occupying else count_before + 1

    over_cap = count_after > quota

    if not over_cap:
        return  # Under cap, allow.

    # Cap reached. Either bypass or block.
    if not bypass_quota:
        raise BusinessRuleViolation(
            f"Vượt chỉ tiêu tuyển sinh: chỉ tiêu năm {profile.academic_year} là "
            f"{quota} hồ sơ, hiện đã đầy ({count_before}/{quota}). "
            "Liên hệ admin nếu cần ghi đè (bypass_quota=true + bypass_reason ≥20 ký tự)."
        )

    # Bypass path. Admin-only.
    #
    # ADM-026 review (Major #3): denied bypass attempts also generate an
    # audit row so compliance can reconstruct WHO tried to overflow the
    # cap, not just who succeeded. Because denial raises, the caller's
    # transaction rolls back — we use a fresh AsyncSessionLocal()
    # (separate connection, separate transaction) for the audit write so
    # the row persists regardless of the outer rollback. Action codes:
    #   * quota_bypass_denied_role    — non-admin tried bypass
    #   * quota_bypass_denied_reason  — admin tried bypass without ≥20-char reason
    #   * quota_bypassed              — admin success path (existing)
    if actor.role != UserRole.ADMIN:
        await _audit_quota_bypass_denied(
            entity_id=profile.id,
            actor=actor,
            denial_action="quota_bypass_denied_role",
            denial_detail=f"role={actor.role}",
            quota=quota,
            count_before=count_before,
            count_after=count_after,
            academic_info_id=academic_info.id,
            academic_year=profile.academic_year,
            offering_id=offering_id,
            transition=transition,
            source=source,
            attempted_reason=bypass_reason,
        )
        raise PermissionDeniedError(
            "Chỉ Admin được phép ghi đè chỉ tiêu tuyển sinh (bypass_quota). "
            f"Role hiện tại: {actor.role}."
        )

    reason = (bypass_reason or "").strip()
    if len(reason) < 20:
        await _audit_quota_bypass_denied(
            entity_id=profile.id,
            actor=actor,
            denial_action="quota_bypass_denied_reason",
            denial_detail=f"reason_len={len(reason)}",
            quota=quota,
            count_before=count_before,
            count_after=count_after,
            academic_info_id=academic_info.id,
            academic_year=profile.academic_year,
            offering_id=offering_id,
            transition=transition,
            source=source,
            attempted_reason=bypass_reason,
        )
        raise ValidationError(
            "bypass_reason là bắt buộc và phải có ít nhất 20 ký tự khi bypass_quota=true."
        )

    # Admin bypass authorized. Write durable audit log evidence (success path).
    from ..services import audit_service
    await audit_service.log_audit(
        db,
        entity_type="AdmissionProfile",
        entity_id=profile.id,
        action="quota_bypassed",
        actor_user_id=actor.id,
        changes={
            "quota": {"old": None, "new": quota},
            "enrolled_count_before": {"old": None, "new": count_before},
            "enrolled_count_after": {"old": None, "new": count_after},
            "academic_info_id": {"old": None, "new": academic_info.id},
            "academic_year": {"old": None, "new": profile.academic_year},
            "offering_id": {"old": None, "new": offering_id},
            "transition": {"old": None, "new": transition},
        },
        reason=reason,
        source=source,
    )
    log.warning(
        "ADM-026 quota cap bypassed by admin",
        profile_id=profile.id,
        transition=transition,
        quota=quota,
        count_before=count_before,
        count_after=count_after,
        actor_id=actor.id,
        reason=reason[:80],
    )


async def _audit_quota_bypass_denied(
    *,
    entity_id: int,
    actor: models.User,
    denial_action: str,
    denial_detail: str,
    quota: int,
    count_before: int,
    count_after: int,
    academic_info_id: int,
    academic_year: int,
    offering_id: int,
    transition: str,
    source: str,
    attempted_reason: Optional[str],
) -> None:
    """
    ADM-026 review (Major #3): persist a denied bypass-attempt audit row.

    Runs in its OWN session (``AsyncSessionLocal``) and commits
    independently so the audit row survives the caller's rollback. The
    caller is about to raise (PermissionDeniedError or ValidationError),
    which will tear down the route's transaction frame; without an
    independent session, the audit write would also rollback and the
    attempt would leave no trace.

    Best-effort: any exception here is logged but swallowed so we never
    convert "bypass denied" into "bypass denied + 500 audit error".
    """
    from ..database import AsyncSessionLocal
    from ..services import audit_service

    try:
        async with AsyncSessionLocal() as audit_db:
            await audit_service.log_audit(
                audit_db,
                entity_type="AdmissionProfile",
                entity_id=entity_id,
                action=denial_action,
                actor_user_id=actor.id,
                changes={
                    "denial_detail": {"old": None, "new": denial_detail},
                    "quota": {"old": None, "new": quota},
                    "enrolled_count_before": {"old": None, "new": count_before},
                    "enrolled_count_after": {"old": None, "new": count_after},
                    "academic_info_id": {"old": None, "new": academic_info_id},
                    "academic_year": {"old": None, "new": academic_year},
                    "offering_id": {"old": None, "new": offering_id},
                    "transition": {"old": None, "new": transition},
                    # Only store reason text when it had any content; admins'
                    # short-reason attempts are still useful evidence.
                    "attempted_reason": {
                        "old": None,
                        "new": (attempted_reason or "").strip()[:1000] or None,
                    },
                },
                reason=denial_detail,
                source=source,
            )
            await audit_db.commit()
    except Exception as audit_err:  # noqa: BLE001 — best-effort, never block denial
        log.error(
            "ADM-026 audit write FAILED for denied bypass attempt",
            entity_id=entity_id,
            denial_action=denial_action,
            actor_id=actor.id,
            error=str(audit_err),
        )


async def check_enrollment_fee_eligibility(
    db: AsyncSession,
    profile_id: int,
) -> None:
    """
    Fee Gate: Verify tuition fee clearance before enrollment.

    Dispatches to one of two modes based on ADMISSION_FEE_GATE_MODE
    (ADR-002 Decision 2):
    - 'legacy': status must be paid or waived (pre-PR4 behavior, unchanged)
    - 'semester_hk1': HK1 financial clearance — partial payment with
      any non-zero amount also passes (SPEC §4.2)

    The caller (enroll_profile) checks ENABLE_FEE_VERIFICATION first;
    this function is only called when verification is enabled.
    """
    from app.config import settings

    mode = settings.ADMISSION_FEE_GATE_MODE

    if mode == "semester_hk1":
        await _check_fee_gate_semester_hk1(db, profile_id)
    else:
        await _check_fee_gate_legacy(db, profile_id)


async def _check_fee_gate_legacy(
    db: AsyncSession,
    profile_id: int,
) -> None:
    """Legacy gate: tuition fee must be paid or waived.

    Extracted from the pre-PR4 check_enrollment_fee_eligibility body.
    Pinned to semester_no=1 so that HK2+ fees (which can now be
    created via PR 3's semester-aware API) do not contaminate the
    enrollment gate check.
    """
    from app.repositories.fee_repository import FeeRepository
    from app.models.finance.fee import FeeTypeEnum, FeeStatusEnum

    fee_repo = FeeRepository(db)

    fees = await fee_repo.get_by_profile_id(
        profile_id=profile_id,
        fee_type=FeeTypeEnum.tuition.value,
        semester_no=1,
    )

    if not fees:
        log.warning(
            "Fee gate check failed: No tuition fee record found",
            profile_id=profile_id,
        )
        raise BadRequest(
            "Cannot enroll: Tuition fee has not been calculated. "
            "Please calculate the fee before proceeding with enrollment."
        )

    fee = fees[0]

    if fee.status not in (FeeStatusEnum.paid.value, FeeStatusEnum.waived.value):
        remaining = fee.remaining_amount
        log.warning(
            "Fee gate check failed: Tuition fee not cleared",
            profile_id=profile_id,
            fee_id=fee.id,
            fee_status=fee.status,
            remaining_amount=str(remaining),
        )
        raise BadRequest(
            f"Cannot enroll: Tuition fee not cleared. "
            f"Current status: {fee.status}, Remaining: {remaining:,.0f} VND. "
            "Please complete payment or apply for fee waiver before enrollment."
        )

    log.info(
        "Fee gate check passed: Tuition fee cleared",
        profile_id=profile_id,
        fee_id=fee.id,
        fee_status=fee.status,
    )


async def _check_fee_gate_semester_hk1(
    db: AsyncSession,
    profile_id: int,
) -> None:
    """HK1 Financial Clearance gate (ADMISSION_FEE_GATE_MODE=semester_hk1).

    Per SEMESTER_TUITION_SPEC §4.2 and ADR-002:
    - Fee must exist: fee_type='tuition', semester_no=1 for this profile
    - Cleared if: status='paid' OR status='waived' OR
      (status='partial' AND paid_amount > 0)
    - No minimum payment threshold — any non-zero payment passes
    - Partial payment: remainder stays as HK1 debt, does NOT block
    """
    from app.repositories.fee_repository import FeeRepository
    from app.models.finance.fee import FeeTypeEnum, FeeStatusEnum

    fee_repo = FeeRepository(db)

    fees = await fee_repo.get_by_profile_id(
        profile_id=profile_id,
        fee_type=FeeTypeEnum.tuition.value,
        semester_no=1,
    )

    if not fees:
        log.warning(
            "HK1 fee gate check failed: No HK1 tuition fee record found",
            profile_id=profile_id,
        )
        raise BadRequest(
            "Không thể nhập học: Chưa có phí học kỳ 1 (HK1). "
            "Vui lòng tính phí trước khi tiến hành nhập học."
        )

    fee = fees[0]

    if fee.status in (FeeStatusEnum.paid.value, FeeStatusEnum.waived.value):
        log.info(
            "HK1 fee gate check passed",
            profile_id=profile_id,
            fee_id=fee.id,
            fee_status=fee.status,
        )
        return

    if fee.status == FeeStatusEnum.partial.value and fee.paid_amount > 0:
        log.info(
            "HK1 fee gate check passed: partial payment accepted",
            profile_id=profile_id,
            fee_id=fee.id,
            fee_status=fee.status,
            paid_amount=str(fee.paid_amount),
            remaining=str(fee.remaining_amount),
        )
        return

    remaining = fee.remaining_amount
    log.warning(
        "HK1 fee gate check failed: HK1 tuition fee not cleared",
        profile_id=profile_id,
        fee_id=fee.id,
        fee_status=fee.status,
        paid_amount=str(fee.paid_amount),
        remaining=str(remaining),
    )
    raise BadRequest(
        f"Không thể nhập học: Phí HK1 chưa được thanh toán. "
        f"Trạng thái hiện tại: {fee.status}, Còn lại: {remaining:,.0f} VND. "
        "Vui lòng thanh toán (một phần hoặc toàn bộ) hoặc xin miễn phí "
        "trước khi nhập học."
    )


def _validate_scores(
    profile: models.AdmissionProfile,
    applied_rules: dict,
) -> tuple[bool, list[str], list[str]]:
    """
    Validate score requirements based on applied rules.
    Returns: (has_gpa_error, validation_errors_list, gpa_errors_list)
    """
    # P0 hotfix multi-NV (2026-06-04) — scores live per-choice in
    # ProfileChoiceScore, NOT the profile-level ProfileSubjectScore the
    # legacy body below reads. Branch out so multi-NV eligibility/completion
    # use the choice-aware data-completeness gate. Data-complete ONLY (no
    # min_score/sàn → that is T6 publish per-NV); when complete this returns
    # no error so eligibility_status flips to "eligible" even below the
    # threshold (correct per contract — "nộp" ≠ "trúng tuyển").
    if getattr(profile, "uses_choice_engine", False):
        # Sync helper — read choices from __dict__ to avoid triggering a
        # lazy-load (MissingGreenlet) in the async session. All response
        # paths eager-load choices (admission_repository
        # _choices_eager_load_options + _populate_response_fields 8d
        # defensive fetch); the submit gate re-queries fresh.
        choices = profile.__dict__.get("choices")
        if choices is None:
            # Relationship not eager-loaded on this path — stay non-blocking
            # rather than crash (MissingGreenlet) or spuriously block. This is
            # display-only fail-open; the authoritative submit gate re-queries
            # fresh. Log so a missing eager-load on a NEW code path is
            # observable instead of silently masking incompleteness.
            log.warning(
                "validate_scores_choices_unloaded",
                profile_id=getattr(profile, "id", None),
                reason=(
                    "multi-NV profile reached _validate_scores without "
                    "eager-loaded choices; eligibility computed fail-open. "
                    "Ensure the caller eager-loads choices "
                    "(_choices_eager_load_options / _populate_response_fields)."
                ),
            )
            return False, [], []
        if not choices:
            msg = "Cần ít nhất 1 nguyện vọng để nộp hồ sơ"
            return True, [msg], [msg]
        from .admission_choice_engine_service import (
            validate_choice_scores_complete,
        )
        errs = validate_choice_scores_complete(choices, applied_rules)
        return bool(errs), errs, errs

    min_gpa = float(applied_rules.get("min_gpa") or 0)
    req_count_val = applied_rules.get("required_subject_count")
    required_count = int(req_count_val) if req_count_val is not None else 3
    
    # Get current score count from relational data
    scores_map = {s.subject.code: float(s.score) for s in profile.subject_scores} if profile.subject_scores else {}
    current_count = len(scores_map)
    
    method_type = applied_rules.get("method_type", "subject_based")
    current_gpa = profile.average_score or 0
    min_score = float(applied_rules.get("min_score") or 0)
    current_total = profile.total_score or 0

    validation_errors = []
    gpa_errors = []
    gpa_error = False

    if method_type == "gpa_only":
        # GPA-Only: Check average_score only
        if min_gpa > 0 and current_gpa < min_gpa:
            error_msg = f"GPA không đạt: {current_gpa:.2f} < {min_gpa}"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True

    elif method_type == "combined":
        # Combined: Check BOTH total_score AND average_score
        # First: Check subject count
        if current_count < required_count:
            error_msg = f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
        else:
            # Check total_score
            if min_score > 0 and current_total < min_score:
                error_msg = f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}"
                validation_errors.append(error_msg)
                gpa_errors.append(error_msg)
                gpa_error = True
            # Check GPA (even if total passed)
            if min_gpa > 0 and current_gpa < min_gpa:
                error_msg = f"GPA không đạt: {current_gpa:.2f} < {min_gpa}"
                validation_errors.append(error_msg)
                gpa_errors.append(error_msg)
                gpa_error = True

    else:
        # subject_based, hoc_ba, tot_nghiep, etc.: Check total_score only
        if current_count < required_count:
            error_msg = f"Chưa nhập đủ đầu điểm ({current_count}/{required_count})"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
        elif min_score > 0 and current_total < min_score:
            error_msg = f"Tổng điểm thấp hơn điểm chuẩn: {current_total:.2f} < {min_score}"
            validation_errors.append(error_msg)
            gpa_errors.append(error_msg)
            gpa_error = True
            
    return gpa_error, validation_errors, gpa_errors


def _validate_documents(
    profile: models.AdmissionProfile,
    documents: list | None,
    applied_rules: dict,
) -> tuple[list[str], list[str], set[str], list[str], list[str]]:
    """
    Validate document requirements.
    Returns: ``(doc_errors, validation_errors, uploaded_doc_codes,
              upload_required_docs, unverified_doc_codes)``.

    ``doc_errors`` is the union of truly-missing and (in strict mode)
    uploaded-but-unverified codes — submit-gate consumers want a single
    "anything blocks submit" list. ``unverified_doc_codes`` is the
    subset that *was* uploaded but is still pending officer
    verification; UI consumers (``document_stats``,
    ``grouped_validation_errors``) split the two so a doc waiting on
    verify isn't double-counted as "missing".

    PR #6 — uploaded-but-not-verified docs no longer satisfy the submit
    gate by default. The path-level `allow_unverified_submission` flag
    is snapshotted into ``applied_rules`` at profile creation so admin
    changes to a path don't retroactively re-score in-flight profiles.

    Schema versioning:
      * schema_version == 1 → legacy profile created before PR #6.
        Grandfathered: treat missing flag as True so existing drafts
        keep submitting.
      * schema_version >= 2 → post-PR profile. The flag MUST be present;
        its absence is a create_profile bug and raises ConfigError so
        the failure surfaces loudly instead of silently downgrading.
    """
    upload_required_docs = applied_rules.get("upload_required_docs", applied_rules.get("mandatory_docs", []))
    doc_errors: list[str] = []
    unverified_doc_codes: list[str] = []
    validation_errors: list[str] = []
    uploaded_doc_codes: set[str] = set()
    # Separate set of codes that exist in the uploads table with a file
    # but have not yet been verified — used to distinguish "missing" vs
    # "pending verify" in strict mode for UI counts/labels.
    pending_verify_codes: set[str] = set()

    schema_version = applied_rules.get("schema_version", 1)
    if schema_version == 1:
        # Pre-PR #6 profile, grandfathered.
        allow_unverified = bool(applied_rules.get("allow_unverified_submission", True))
    else:
        if "allow_unverified_submission" not in applied_rules:
            # Domain-level misconfiguration — create_profile forgot to
            # snapshot the flag. Fail loudly rather than downgrade silently.
            raise BusinessRuleViolation(
                f"Profile {getattr(profile, 'id', '?')} applied_rules missing "
                f"allow_unverified_submission (schema_version={schema_version}). "
                "create_profile must snapshot this flag from the AdmissionPath."
            )
        allow_unverified = bool(applied_rules["allow_unverified_submission"])

    if documents is not None:
        # Phase E.4 fix (smoke 2026-05-20): priority_evidence docs do NOT have
        # a ``document_type_id`` FK (they map 1:1 with priority_object_codes
        # via the ``priority_sub_code`` column, not the path's mandatory_docs
        # ConfigDocumentType catalog). They MUST be filtered out before
        # accessing ``doc.document_type.code`` or the validator crashes with
        # ``AttributeError: 'NoneType' object has no attribute 'code'`` on
        # the first priority evidence row.
        path_docs = [
            doc for doc in documents
            if doc.document_type is not None
            and getattr(doc, "category", None) != "priority_evidence"
        ]
        if allow_unverified:
            # Legacy behaviour: uploaded (with file) / verified / paper-submitted
            # all count toward submission.
            uploaded_doc_codes = {
                doc.document_type.code for doc in path_docs
                if doc.status in ("verified", "paper_submitted")
                or (doc.file_path and doc.status == "uploaded")
            }
        else:
            # Strict mode: only verified or paper_submitted count.
            uploaded_doc_codes = {
                doc.document_type.code for doc in path_docs
                if doc.status in ("verified", "paper_submitted")
            }
            # Track uploaded-with-file rows that strict mode rejected so
            # the UI can label them as "pending verify" rather than
            # "missing".
            pending_verify_codes = {
                doc.document_type.code for doc in path_docs
                if doc.file_path and doc.status == "uploaded"
            }

        log.debug(
            "Document validation check",
            profile_id=profile.id,
            upload_required_docs=upload_required_docs,
            uploaded_doc_codes=list(uploaded_doc_codes),
            total_documents=len(documents),
            schema_version=schema_version,
            allow_unverified=allow_unverified,
        )

        for doc_code in upload_required_docs:
            if doc_code in uploaded_doc_codes:
                continue
            doc_errors.append(doc_code)
            if not allow_unverified and doc_code in pending_verify_codes:
                unverified_doc_codes.append(doc_code)
                validation_errors.append(
                    f"Tài liệu {doc_code} chưa được xác minh. Liên hệ quản lý "
                    f"để verify trước khi nộp hồ sơ."
                )
            else:
                validation_errors.append(_missing_doc_error_message(doc_code))

    return (
        doc_errors,
        validation_errors,
        uploaded_doc_codes,
        upload_required_docs,
        unverified_doc_codes,
    )


def _missing_doc_error_message(code: str) -> str:
    """Single source of truth for the "missing mandatory document" message.

    Emitted by ``_validate_documents`` when a required doc is absent and
    reconstructed by ``_compute_frontend_fields`` to SUBTRACT those messages
    from ``validation_errors`` (computing ``_other_errors`` for
    ``can_submit_with_document_debt``). Both sites MUST use this helper so the
    format can never drift apart — a drift would break the subtraction and
    silently kill ``can_submit_with_document_debt`` (fast-track nợ giấy tờ).
    """
    return f"Thiếu tài liệu bắt buộc: {code}"


def _compute_outstanding_debt_codes(
    profile: models.AdmissionProfile,
    documents: list | None,
) -> list[str]:
    """Fast-track nợ giấy tờ — VERIFIED-based resolution of a document debt.

    A debt code is "satisfied" (no longer outstanding) ONLY once the
    corresponding document reaches ``verified`` or ``paper_submitted`` — i.e.
    an officer/reviewer has actually confirmed it. Merely UPLOADING the file
    (status ``uploaded``) does NOT clear the debt; the decision is "hết nợ chỉ
    khi VERIFY" (PLAN §C1.5).

    This is intentionally STRICTER than ``missing_doc_codes`` (which, in lax
    ``allow_unverified=True`` mode, counts an uploaded-but-unverified doc as
    present and would prematurely empty the debt). Mirrors the priority_evidence
    filter from ``_validate_documents`` so a priority-evidence row (no
    ``document_type`` FK) never crashes on ``doc.document_type.code``.

    Args:
        profile: AdmissionProfile carrying the ``document_debt`` snapshot.
        documents: Eager-loaded ProfileDocument list (or None → nothing
            satisfied, every debt code stays outstanding).

    Returns:
        The subset of ``document_debt['codes']`` not yet verified/paper_submitted.
        ``[]`` when there is no debt snapshot (NULL column → never gates approve).
    """
    debt_snapshot = getattr(profile, "document_debt", None)
    debt_codes = (
        debt_snapshot.get("codes", [])
        if isinstance(debt_snapshot, dict)
        else []
    )
    if not debt_codes:
        return []

    # Shared "verified/paper_submitted, priority_evidence filtered out" logic —
    # single source of truth in ``admission_document_policy`` so the satisfied-
    # doc definition can't drift from the doc-policy layer. Local import keeps
    # this leaf helper cycle-free (matches the other ``admission_document_policy``
    # imports in this module).
    from .admission_document_policy import _satisfied_doc_codes

    satisfied_now = _satisfied_doc_codes(documents)
    return [code for code in debt_codes if code not in satisfied_now]


async def _outstanding_debt_for_approval(db, profile) -> list[str]:
    """Outstanding (verified-based) debt codes for an approval gate; [] if no debt.

    Shared by ``approve_profile`` and ``bulk_approve`` so both approve gates
    compute the same thing: load the profile's documents and intersect the
    ``document_debt`` snapshot with docs not yet verified/paper_submitted. A
    profile without a debt snapshot returns ``[]`` (no query, never gates).
    """
    if not getattr(profile, "document_debt", None):
        return []
    from app.repositories import AdmissionRepository

    documents = await AdmissionRepository(db).get_all_documents(profile.id)
    return _compute_outstanding_debt_codes(profile, documents)


def _validate_personal_info(
    profile: models.AdmissionProfile,
) -> tuple[list[str], list[str]]:
    """
    Validate mandatory personal fields.
    Returns: (missing_fields_list, validation_errors_list)
    """
    missing_personal = []
    validation_errors = []
    
    field_map = {
        "full_name": "Họ tên",
        "dob": "Ngày sinh",
        "gender": "Giới tính",
        "citizen_id": "Số CCCD/CMND",
        "nationality": "Quốc tịch",
        "ethnicity": "Dân tộc",
        "phone": "Số điện thoại",
        "place_of_birth": "Nơi sinh"
    }
    
    for field, label in field_map.items():
        if not getattr(profile, field, None):
            missing_personal.append(label)
            validation_errors.append(f"Thiếu thông tin cá nhân: {label}")
            
    return missing_personal, validation_errors


def _compute_completion_percent(
    profile: models.AdmissionProfile,
    documents: list = None,
) -> int:
    """
    Compute completion_percent for a profile from step status weights.

    Pure helper — no current_user needed. Runs validation helpers internally
    but does NOT set any transient fields on the profile except completion_percent.

    Args:
        profile: AdmissionProfile with subject_scores and lead loaded
        documents: Optional list of ProfileDocument

    Returns:
        Completion percentage (0-100)
    """
    applied_rules = profile.applied_rules or {}
    gpa_error, _, _ = _validate_scores(profile, applied_rules)
    doc_errors, _, _, _, _ = _validate_documents(profile, documents, applied_rules)
    missing_personal, _ = _validate_personal_info(profile)

    # Eligibility (simplified — mirrors _compute_frontend_fields logic)
    has_any_validation_error = gpa_error or len(doc_errors) > 0 or len(missing_personal) > 0
    is_ineligible = has_any_validation_error and not (
        is_admitted_like(profile) or profile.status == "enrolled"
    )

    cccd_error = not profile.citizen_id
    personal_required = ["full_name", "phone", "citizen_id"]
    personal_optional = ["email", "dob", "gender", "nationality", "ethnicity"]
    personal_required_filled = all(getattr(profile, f, None) for f in personal_required)
    personal_optional_filled = all(getattr(profile, f, None) for f in personal_optional)
    has_family = profile.family_info and len(profile.family_info) > 0
    has_academic = profile.academic_history and len(profile.academic_history) > 0
    # P0 hotfix multi-NV — Step 5 (Scores) "has any" reads per-choice
    # ProfileChoiceScore, not the profile-level relation (always empty for
    # multi-NV). __dict__ access is lazy-load-safe in this sync helper.
    if getattr(profile, "uses_choice_engine", False):
        _ch = profile.__dict__.get("choices") or []
        has_any_scores = any(bool(c.__dict__.get("scores")) for c in _ch)
    else:
        has_any_scores = (
            bool(profile.subject_scores)
            if hasattr(profile, "subject_scores")
            else False
        )

    # Phase E.4 — Step 4 Priority compute (KV resolved + cultural input)
    has_priority_input = bool(
        getattr(profile, "cultural_education_level", None)
    )
    snapshot = getattr(profile, "priority_resolution_snapshot", None) or {}
    kv_resolved = bool(snapshot.get("kv_resolved")) if isinstance(snapshot, dict) else False

    docs_format_confirmed = True
    if documents is not None:
        for doc in documents:
            if doc.status == "uploaded" and doc.file_path:
                docs_format_confirmed = False
                break

    # Phase E.4 (G0) — 8-step model. Step 4 = Priority (new gộp KV+UT).
    # Previous Step 4 (Scores) renumbered → Step 5. Step 5 (Documents) → 6.
    # Step 6 (Tuition) → 7. Step 7 (Finalize) → 8. FE PipelineSidebar đã 8 steps.
    step_status = {
        1: "error" if (cccd_error or not personal_required_filled) else ("success" if personal_optional_filled else "warning"),
        2: "success" if has_family else "warning",
        3: "success" if has_academic else "warning",
        4: (
            "error" if not has_priority_input
            else "warning" if not kv_resolved
            else "success"
        ),
        5: "error" if gpa_error else ("success" if has_any_scores else "warning"),
        6: "error" if len(doc_errors) > 0 else ("warning" if not docs_format_confirmed else "success"),
        7: "success",
        8: "locked" if is_ineligible else "success",
    }

    # Phase E.4 (G0) — rebalance weights 7→8 entries, total=100.
    # Pattern 13×4 + 12×4 → 52+48=100. Prioritize "input" steps (Personal,
    # Family, Academic, Documents) slightly over "output" steps (Priority,
    # Scores, Tuition, Finalize) — equal weight per pair for simplicity.
    step_weights = {1: 13, 2: 13, 3: 13, 4: 12, 5: 12, 6: 13, 7: 12, 8: 12}
    completion = 0
    for step_num, weight in step_weights.items():
        state = step_status.get(step_num, "locked")
        if state == "success":
            completion += weight
        elif state == "warning":
            completion += int(weight * 0.5)
    return min(100, completion)


@dataclass
class LeadAdmissionEligibility:
    """Result of lead-level admission eligibility check.

    Returned by check_lead_level_admission_eligibility(). When eligible=True,
    blocker_code and blocker_message are None.
    """
    eligible: bool
    blocker_code: Optional[str]  # None when eligible
    blocker_message: Optional[str]  # Vietnamese message for UI


async def check_lead_level_admission_eligibility(
    db: AsyncSession,
    lead: models.Lead,
    current_user: models.User,
    *,
    check_role: bool = True,
    academic_year: Optional[int] = None,
) -> LeadAdmissionEligibility:
    """Check 7 lead-level conditions for creating an admission profile.

    SINGLE SOURCE OF TRUTH for lead-level eligibility.
    Called by:
      - create_admission_profile() with check_role=False (IDOR enforced upstream)
      - lead_service._populate_lead_detail_fields() with check_role=True (gate UX)

    Does NOT check offering/method/path-level rules (those require
    admission_method_id and are validated in create_admission_profile directly).

    Blocker codes (precedence order):
      forbidden > already_has_profile > invalid_lead_status > consultation_terminal
      > missing_offering > no_consultation > consultation_missing_status
      > consultation_universal_status

    Requires lead.admission_profiles eager-loaded (Wave 4 #15b plural) —
    uses __dict__.get() to avoid lazy-load crash in async context.
    """
    # Role check (optional — skipped when caller already enforced IDOR at deps layer)
    if check_role:
        user_role = current_user.role
        is_admin = user_role == UserRole.ADMIN
        is_manager = user_role == UserRole.MANAGER
        is_officer = user_role == UserRole.OFFICER
        is_assigned = lead.assigned_officer_id == current_user.id
        role_ok = is_admin or is_manager or (is_officer and is_assigned)
        if not role_ok:
            return LeadAdmissionEligibility(
                False,
                "forbidden",
                "Bạn không có quyền tạo hồ sơ cho lead này.",
            )

    # Precedence order mirrors the original create_admission_profile() contract
    # (pre-refactor): existing_profile → missing_offering → invalid_lead_status
    # → consultation chain. Keep this order stable — a lead that is both
    # `converted` and missing an offering must surface `missing_offering` first,
    # matching the historical POST /admissions response.

    # 1. Already has profile (structural conflict)
    #
    # Wave 4 #15b — composite check: lead can hold one profile per
    # academic_year (Wave 3-E composite UNIQUE), so blocking is now
    # year-specific. Caller passes ``academic_year`` to scope the
    # check; legacy callers (year=None) fall back to "any profile"
    # semantic so the UX doesn't silently allow conflicting creates
    # before the rest of the codebase is migrated.
    profiles = lead.__dict__.get("admission_profiles") or []
    has_conflict = (
        any(p.academic_year == academic_year for p in profiles)
        if academic_year is not None
        else bool(profiles)
    )
    if has_conflict:
        message = (
            f"Lead này đã có hồ sơ tuyển sinh năm {academic_year}."
            if academic_year is not None
            else "Lead này đã có hồ sơ tuyển sinh."
        )
        return LeadAdmissionEligibility(
            False,
            "already_has_profile",
            message,
        )

    # 2. Missing offering (fixable first — historical precedence)
    if not lead.offering_id:
        return LeadAdmissionEligibility(
            False,
            "missing_offering",
            "Lead chưa có chương trình đào tạo. Vui lòng chọn chương trình trước.",
        )

    # 3. Invalid lead status (checked after offering per original contract)
    if lead.status == "converted":
        return LeadAdmissionEligibility(
            False,
            "invalid_lead_status",
            f"Lead đang ở trạng thái '{lead.status}', không thể tạo hồ sơ.",
        )

    # 3b. CONSULTATION-phase give-up (e.g. sts20 CONSULT_GIVEUP). A lead whose
    # current consultation status is a CONSULTATION-phase terminal has been
    # formally ended in the tư-vấn pipeline — block any new admission profile
    # until it is re-opened (officer request → manager/admin approval). Without
    # this gate sts20 leaks an unintended "escape" into the admission flow.
    #
    # IMPORTANT: scope to phase=='consultation'. A lead whose status is an
    # ADMISSION/FEE/ENROLLED terminal (sts16 rejected, sts08 withdrawn, sts18
    # refunded, sts11/sts12) is_final too, but those are END of an EARLIER
    # admission cycle — the composite (lead_id, academic_year) UNIQUE deliberately
    # lets such a lead apply again in a LATER academic_year. Blocking on every
    # is_final status would break multi-year re-application. Explicit DB get
    # avoids a lazy-load crash in async context.
    if lead.consultation_status_id:
        from ..core.status_mapping import is_consultation_terminal_status
        current_cs = await db.get(
            models.ConsultationStatus, lead.consultation_status_id
        )
        if is_consultation_terminal_status(current_cs):
            return LeadAdmissionEligibility(
                False,
                "consultation_terminal",
                f"Lead đã ở trạng thái cuối '{current_cs.name}' (đã đóng), "
                "không thể tạo hồ sơ. Cần mở lại lead trước.",
            )

    # 4-6. Consultation checks (DB query — reuse admission_repo, consultation_status eager-loaded)
    from app.repositories import AdmissionRepository  # local import (matches pattern at lines 995, 1288)
    admission_repo = AdmissionRepository(db)
    latest = await admission_repo.get_latest_consultation_for_lead(lead.id)
    if latest is None:
        return LeadAdmissionEligibility(
            False,
            "no_consultation",
            "Lead chưa có lịch sử tư vấn. Vui lòng thêm ít nhất 1 lần tư vấn.",
        )
    if not latest.consultation_status_id:
        return LeadAdmissionEligibility(
            False,
            "consultation_missing_status",
            "Lần tư vấn gần nhất chưa cập nhật kết quả.",
        )
    if latest.consultation_status and latest.consultation_status.is_universal:
        return LeadAdmissionEligibility(
            False,
            "consultation_universal_status",
            f"Trạng thái '{latest.consultation_status.name}' chỉ là ghi nhận hoạt động, "
            "chưa phải kết quả tư vấn.",
        )

    return LeadAdmissionEligibility(True, None, None)


def _sync_available_actions(profile: models.AdmissionProfile) -> None:
    """Rebuild ``profile.available_actions`` from ``profile.permissions``.

    Mirror of the line in ``_compute_frontend_fields`` (~line 858) that
    derives ``available_actions`` from the permissions dict. Extracted
    so the async ``_resolve_minor_correction_state`` resolver can flip
    a permission flag and resync the action list without duplicating
    the comprehension.

    Safe to call repeatedly — idempotent given the same ``permissions``
    dict.
    """
    perms = getattr(profile, "permissions", None) or {}
    profile.available_actions = [
        action for action, allowed in perms.items() if allowed
    ]


async def _resolve_minor_correction_state(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    current_user: Optional[models.User],
) -> None:
    """Resolve per-profile ``minor_correction_fields`` + flip the permission
    flag based on the live AdmissionPath allowlist.

    Must be called AFTER ``_compute_frontend_fields`` has populated
    ``profile.permissions`` (the resolver only refines, never invents).
    Safe defaults if context is missing: empty allowlist + permission =
    False so FE renders no button rather than crashing.

    Why async: AdmissionPath is fetched live (governance setting, not
    snapshotted to applied_rules) so any admin change applies
    immediately to all profiles tied to the path. Single-row fetch in
    detail; the list endpoint should batch through ``get_by_ids`` and
    then call this resolver per profile with the cached path object —
    helper accepts ``path`` injection via ``_resolve_with_path`` below.
    """
    profile.minor_correction_fields = []

    if current_user is None or not getattr(profile, "permissions", None):
        return

    if not (is_admitted_like(profile) or profile.status == "confirmed"):
        profile.permissions["minor_correction"] = False
        _sync_available_actions(profile)
        return

    path_id = (profile.applied_rules or {}).get("admission_path_id")
    if path_id is None:
        profile.permissions["minor_correction"] = False
        _sync_available_actions(profile)
        return

    from app.repositories import AdmissionPathRepository
    path = await AdmissionPathRepository(db).get_by_id(path_id)
    _apply_minor_correction_state(profile, path)


def _apply_minor_correction_state(
    profile: models.AdmissionProfile,
    path: Optional[Any],
) -> None:
    """Sync helper for the resolver — splits the path-application step
    so the list endpoint can batch-fetch paths and apply state per row
    without redundant async hops.

    CONTRACT: action visible only when the effective allowlist is
    NON-empty. A path with empty config (default after migration)
    keeps the action hidden so officers don't see a button that opens
    an empty dialog.
    """
    effective: set[str] = set()
    if path is not None:
        effective = SAFE_MINOR_CORRECTION_FIELDS & set(
            getattr(path, "minor_correction_allowed_fields", []) or []
        )

    perms = profile.permissions
    role_ok = perms.get("minor_correction", False)
    perms["minor_correction"] = role_ok and len(effective) > 0
    profile.minor_correction_fields = sorted(effective)
    _sync_available_actions(profile)


async def _resolve_verifier_names(
    db: AsyncSession,
    documents: Optional[List[models.ProfileDocument]],
) -> Dict[int, str]:
    """Batch-resolve verifier display names for a documents list.

    Returns ``{user_id: display_name}`` so the documents_checklist payload can
    surface "duyệt bởi <Tên>" without an N+1 storm. Display precedence:
    ``full_name`` → ``username`` → omitted (FE then renders "User #<id>").

    REVIEW NOTE (Lane A round 10 follow-up): an earlier draft fell back to
    ``email`` after ``full_name``. Admission/audit actor names elsewhere in
    this codebase use ``full_name or username`` and never expose staff
    emails to other staff readers — every officer/manager/admin who can read
    a profile sees verifier identity, so leaking an internal email there
    would be a quiet privacy regression. Aligned to the dominant pattern
    here.

    One SELECT per profile load — cost is bounded by the number of distinct
    verifiers, not documents.
    """
    if not documents:
        return {}
    verifier_ids: set[int] = {
        doc.verified_by
        for doc in documents
        if getattr(doc, "verified_by", None) is not None
    }
    if not verifier_ids:
        return {}
    rows = (
        await db.execute(
            select(
                models.User.id, models.User.full_name, models.User.username
            ).where(models.User.id.in_(verifier_ids))
        )
    ).all()
    out: Dict[int, str] = {}
    for user_id, full_name, username in rows:
        display = (full_name or "").strip() or (username or "").strip()
        if display:
            out[user_id] = display
    return out


def _strict_int(value) -> Optional[int]:
    """Ép int NGHIÊM + AN TOÀN (KHÔNG bao giờ raise).

    Loại bool (subclass int → int(True)==1) và float (int(9.7) cắt cụt).
    Với str: CHỈ nhận chuỗi-integer ASCII — loại '²' (isdigit()=True nhưng
    int() ném ValueError) + chữ số Unicode khác; giới hạn độ dài (tránh
    ValueError "integer string conversion limit" với chuỗi cực dài). Bọc
    try/except phòng hờ. Dùng cho JSONB academic_history (grade_to/year_to)
    vốn có thể lẫn bool/float/rác do nhập tay.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        core = s[1:] if s.startswith("-") else s
        if core.isascii() and core.isdigit() and 0 < len(core) <= 9:
            try:
                return int(s)
            except ValueError:
                return None
    return None


def _coerce_year(value) -> Optional[int]:
    """Như ``_strict_int`` nhưng CHẤP NHẬN thêm float nguyên (2026.0 → 2026)
    cho year_to — số trong JSONB có thể là float. Loại bool, float lẻ
    (2026.5), NaN/inf. Chuỗi-integer ASCII đi qua ``_strict_int``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None  # NaN / inf
        return int(value) if value == int(value) else None
    return _strict_int(value)


def _thcs_grade9_completion_year(academic_history) -> Optional[int]:
    """Năm hoàn thành lớp 9 = max(year_to) của các record THCS lớp 9.

    academic_history = JSONB list[dict] (AcademicRecordSchema). Nhận record
    khi ``grade_to == 9`` HOẶC ``level == 'THCS'`` — officer có thể điền 1
    trong 2 (cả hai đều Optional); 'THCS_THPT' KHÔNG tính (year_to là năm TN
    THPT, không phải lớp 9). Trả None nếu không có record lớp 9 hợp lệ →
    caller KHÔNG cảnh báo (tránh false-positive khi thiếu dữ liệu).
    """
    if not academic_history:
        return None
    years: List[int] = []
    for rec in academic_history:
        if not isinstance(rec, dict):
            continue
        level = rec.get("level")
        is_thcs = _strict_int(rec.get("grade_to")) == 9 or (
            isinstance(level, str) and level.strip().upper() == "THCS"
        )
        if not is_thcs:
            continue
        year_to = _coerce_year(rec.get("year_to"))
        # Chỉ nhận năm hợp lệ (mirror AcademicRecordSchema ge=1900 le=2100) —
        # applied JSONB có thể bẩn (không qua schema validate khi đọc lại).
        if year_to is not None and 1900 <= year_to <= 2100:
            years.append(year_to)
    return max(years) if years else None


def _thcs_diploma_review_warning(
    cultural: Optional[str],
    academic_history,
    review_from_year: Optional[int],
) -> Optional[dict]:
    """Cảnh báo MỀM rà soát nhãn THCS (KHÔNG chặn submit).

    Bật khi hồ sơ ghi `graduated_thcs` (có bằng TN THCS) nhưng học sinh
    hoàn thành lớp 9 TỪ `review_from_year` trở đi — diện Thông tư
    10/2026/TT-BGDĐT (từ 15/04/2026 không cấp bằng TN THCS, thay bằng xác
    nhận hoàn thành chương trình trong học bạ). `review_from_year=None` →
    no-op (pure-test / chưa cấu hình). Trả None nếu không áp dụng.
    """
    if cultural != "graduated_thcs" or review_from_year is None:
        return None
    year9 = _thcs_grade9_completion_year(academic_history)
    if year9 is None or year9 < review_from_year:
        return None
    return {
        "code": "thcs_diploma_review",
        "message": (
            f"Hoàn thành lớp 9 năm {year9} — theo Thông tư 10/2026/TT-BGDĐT, "
            "học sinh hoàn thành chương trình THCS được xác nhận trong học bạ "
            "thay cho cấp Bằng tốt nghiệp THCS. Vui lòng kiểm tra lại trình độ "
            "đã chọn."
        ),
        "step": 4,
        "section": "priority",
        "severity": "warning",
    }


def _build_executive_summary_items(
    *,
    personal_error_count: int,
    missing_doc_count: int,
    unverified_doc_count: int,
    gpa_error: bool,
    has_family: bool,
    has_academic: bool,
    docs_format_confirmed: bool,
    cultural: Optional[str] = None,
    academic_history=None,
    thcs_review_from_year: Optional[int] = None,
) -> tuple[list[dict], list[dict]]:
    """Build executive_summary ``(critical_blockers, warnings)`` as structured items.

    Phase 3 — each item is ``{code, message, step, section, severity}`` so the FE
    routes a blocker to its EXACT pipeline step (CTA "Sửa Step X") instead of a
    heuristic. ``code`` is stable + snake_case (text-independent — copy can change
    without breaking consumers). Step mapping: personal->1, family->2, academic->3,
    priority->4, gpa/score->5, docs->6, tuition->7.

    Semantics are UNCHANGED from the prior string form: identical trigger
    conditions and the SAME blocker/warning split — family/academic/docs-format
    stay WARNINGS (not promoted to blockers); tuition emits nothing (display-only,
    no item). Pure function — no DB, no migration.
    """
    critical_blockers: list[dict] = []
    if personal_error_count > 0:
        critical_blockers.append({
            "code": "personal_info_missing",
            "message": f"Thiếu {personal_error_count} thông tin cá nhân bắt buộc",
            "step": 1,
            "section": "personal_info",
            "severity": "blocker",
        })
    # PR #6 review — phrase per bucket so the dashboard reflects whether the user
    # must upload OR ask the manager to verify.
    if missing_doc_count > 0:
        critical_blockers.append({
            "code": "documents_missing",
            "message": f"Thiếu {missing_doc_count} tài liệu bắt buộc",
            "step": 6,
            "section": "documents",
            "severity": "blocker",
        })
    if unverified_doc_count > 0:
        critical_blockers.append({
            "code": "documents_unverified",
            "message": f"{unverified_doc_count} tài liệu chờ xác minh từ quản lý",
            "step": 6,
            "section": "documents",
            "severity": "blocker",
        })
    if gpa_error:
        critical_blockers.append({
            "code": "score_below_threshold",
            "message": "Điểm số chưa đạt yêu cầu",
            "step": 5,
            "section": "scores",
            "severity": "blocker",
        })

    warnings: list[dict] = []
    if not has_family:
        warnings.append({
            "code": "family_missing",
            "message": "Chưa điền thông tin gia đình",
            "step": 2,
            "section": "family",
            "severity": "warning",
        })
    if not has_academic:
        warnings.append({
            "code": "academic_missing",
            "message": "Chưa điền lịch sử học tập",
            "step": 3,
            "section": "academic",
            "severity": "warning",
        })
    if not docs_format_confirmed:
        warnings.append({
            "code": "documents_format_unconfirmed",
            "message": "Một số tài liệu chưa được xác nhận định dạng",
            "step": 6,
            "section": "documents",
            "severity": "warning",
        })

    # Cảnh báo MỀM rà soát nhãn THCS (Thông tư 10/2026 — bỏ bằng TN THCS từ
    # 15/04/2026). KHÔNG chặn submit; chỉ append vào warnings để FE nhắc officer.
    thcs_warn = _thcs_diploma_review_warning(
        cultural, academic_history, thcs_review_from_year
    )
    if thcs_warn:
        warnings.append(thcs_warn)

    return critical_blockers, warnings


def _compute_frontend_fields(
    profile: models.AdmissionProfile,
    current_user: models.User,
    documents: list = None,
    verifier_names: Optional[Dict[int, str]] = None,
) -> None:
    """
    Phase 7: Frontend Thin Client Compliance

    Compute permissions, eligibility, validation_errors, available_actions,
    and completion_percent for AdmissionProfileResponse.

    These are transient fields (not stored in DB) computed at response time.

    Args:
        profile: AdmissionProfile object
        current_user: Current authenticated user (for role-based permissions). None for debug.
        documents: Optional list of ProfileDocument (to avoid re-fetching)
    """
    status = profile.status
    user_role = current_user.role                                   
    is_admin = user_role == UserRole.ADMIN                          
    is_manager = user_role == UserRole.MANAGER                      
    is_officer = user_role == UserRole.OFFICER


    # Check if user owns this profile (for applicant self-actions)
    is_owner = (profile.lead
                and profile.lead.assigned_officer_id is not None
                and profile.lead.assigned_officer_id == current_user.id)

    # =========================================================================
    # 1. PERMISSIONS (computed from role + status + Casbin-like rules)
    # =========================================================================
    _is_dropped = getattr(profile, "is_dropped", False)
    # P0 hotfix multi-NV — a multi-NV profile needs ≥1 choice before the
    # Submit button shows (otherwise the candidate clicks Nộp only to hit a
    # 400 from submit_and_evaluate's ≥1-choice gate). Block ONLY when it is
    # multi-NV AND choices are eager-loaded AND empty; an unloaded relation
    # (None) does NOT block (display-only paths — the submit gate
    # re-validates with a fresh query). __dict__ access avoids a sync
    # lazy-load (MissingGreenlet).
    _loaded_choices = profile.__dict__.get("choices")
    _multi_nv_no_choice = (
        getattr(profile, "uses_choice_engine", False)
        and _loaded_choices is not None
        and len(_loaded_choices) == 0
    )
    # Fast-track nợ giấy tờ (C1.5) — compute the VERIFIED-based outstanding debt
    # FIRST so the approve permission below can be gated on it. A code stays
    # outstanding until the doc is verified/paper_submitted (NOT merely
    # uploaded). No debt snapshot → [] → approve is unaffected. Mirror of the
    # service-side gate in ``approve_profile``; assigned to the profile lower
    # down (single source of truth for the FE badge + parity with GET).
    _outstanding_debt_codes = _compute_outstanding_debt_codes(profile, documents)
    permissions = {
        "edit": status in ["draft", "rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "save": status in ["draft", "rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "submit": status == "draft" and (is_owner or is_manager or is_admin) and not _multi_nv_no_choice,
        # Approve is BLOCKED while any owed doc is unverified (nợ giấy tờ): the
        # FE hides/disables the button and the service raises BusinessRuleViolation
        # if it is attempted anyway. ``_outstanding_debt_codes`` is [] for every
        # profile without a debt snapshot → no behaviour change there.
        "approve": (
            status in ["submitted", "resubmitted"]
            and (is_manager or is_admin)
            and not _outstanding_debt_codes
        ),
        "reject": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        # Phase 3 multi-NV simplified flow 2026-05-15: manager/admin click
        # "Công bố kết quả" trực tiếp từ submitted/reviewing → engine cascade
        # auto-transition submitted→reviewing→result_published→admitted/rejected.
        # Bỏ T2 start-review explicit step (YAGNI per user clarification).
        # Mirror BE service guard publish_result(): uses_choice_engine=True +
        # status IN (submitted, reviewing) + manager/admin role.
        #
        # Fast-track nợ giấy tờ (C1.5) — publish_result is the multi-NV DECISION
        # site (admit/reject cascade), so it must obey the same "no decision
        # while docs are owed" gate as ``approve``: a multi-NV profile can submit
        # WITH a document debt, so it could reach ``submitted`` with a non-empty
        # ``_outstanding_debt_codes``. Block the FE button (and the
        # ``admission_choice_engine_service.publish_result`` service guard raises
        # BusinessRuleViolation if attempted anyway). No debt snapshot → [] → no
        # behaviour change for the common path.
        "publish_result": (
            getattr(profile, "uses_choice_engine", False)
            and status in ["submitted", "reviewing"]
            and (is_manager or is_admin)
            and not _outstanding_debt_codes
        ),
        "request_revision": status in ["submitted", "resubmitted"] and (is_manager or is_admin),
        "resubmit": status in ["rejected", "revision_requested"] and (is_owner or is_manager or is_admin),
        "enroll": status in ["confirmed", "overridden"] and (is_owner or is_manager or is_admin),
        # Send/resend magic-link confirmation email. Mirrors the real route
        # contract for POST /admissions/{id}/send-confirmation:
        #   - Casbin policy grants this to every role (officer/manager/admin)
        #     via `policy_templates.py:139`
        #   - `get_admission_for_manager` dependency gates IDOR 3-tier:
        #     admin (all) / manager (unit) / officer (assigned + in-unit)
        # Equivalent client-side: assigned officer, unit manager, or admin.
        # Only meaningful while waiting on the applicant — after `confirmed`,
        # no more tokens are generated.
        "send_confirmation": is_confirmation_eligible(profile) and (is_owner or is_manager or is_admin),
        # W2-1 fix Wave 7 (2026-05-16) — Generate magic-link cho 3 candidate
        # self-service actions. Mirrors send_confirmation permission shape
        # (assigned officer / unit manager / admin) + per-action state
        # validation handled service-side. Flag chỉ true khi profile state
        # cho phép GENERATE link tương ứng (mirror service precheck —
        # avoid showing button only to fail with 400 state mismatch).
        "send_submit_link": (
            status == "draft"
            and (is_owner or is_manager or is_admin)
        ),
        "send_resubmit_link": (
            status == "revision_requested"
            and (is_owner or is_manager or is_admin)
        ),
        "send_withdraw_link": (
            status in (
                "draft", "submitted", "reviewing", "rejected",
                "resubmitted", "revision_requested", "waitlisted",
            )
            and (is_owner or is_manager or is_admin)
        ),
        # Q9 #07 Phase E.4 commit 7 hardening (yêu cầu nghiệp vụ #10):
        # Officer KHÔNG được override KV. Chỉ admin + manager mới có quyền.
        # Pre-fix-up: officer được override cho submitted/reviewing/
        # revision_requested + ownership check. Hardening:
        #   - admin: any state (UI shows button; dialog handles post-publish ack)
        #   - manager: submitted/reviewing/revision_requested + draft (engine
        #     signal required, service-layer gate verifies live recompute)
        #   - officer / accountant / user: never (UI hide button)
        # Service-layer (priority_override_service) cũng có hard-deny officer
        # ngay đầu override_kv là defense-in-depth.
        "override_priority_kv": (
            is_admin
            or (
                is_manager
                and status in [
                    "draft",
                    "submitted",
                    "reviewing",
                    "revision_requested",
                ]
            )
        ),
        # Q9 #07 Phase E.3 — UT evidence verify/reject (officer write-path).
        # Used by FE UtEvidenceTab (Step 8 officer-only). Service-layer
        # (priority_override_service._evidence_mutation_common_checks) refuses
        # draft/withdrawn/dropped. Officer scope: assigned to profile;
        # manager/admin via diamond/wildcard.
        "verify_priority_object": (
            is_admin
            or is_manager
            or (is_officer and is_owner)
        ) and status not in ["draft", "withdrawn", "dropped"],
        "drop": status == "enrolled" and not _is_dropped and (is_manager or is_admin),
        "claim": (status in ["submitted", "resubmitted"] and (is_manager or is_admin)
                  and not profile.assigned_reviewer_id),
        "unclaim": (bool(profile.assigned_reviewer_id)
                    and (profile.assigned_reviewer_id == current_user.id or is_admin)),
        # Officer-to-lead assignment via POST /admissions/bulk/assign. Mirrors
        # the route: admin always, manager when the lead's unit matches theirs.
        # Not gated by profile status (route updates lead.assigned_officer_id
        # regardless of admission state).
        "assign_officer": is_admin or (
            is_manager
            and profile.lead is not None
            and profile.lead.unit_id is not None
            and profile.lead.unit_id == current_user.unit_id
        ),
        # PR #7 — official fee/invoice creation via POST /api/fees/calculate.
        # Mirrors _fee_calc_authorized in routers/fees.py: admin + accountant
        # always (central finance roles, Casbin grants accountant /fees/calculate
        # with no unit qualifier), manager same-unit, officer same-unit AND
        # assigned. The
        # fee-eligible STATE gate is the shared ``is_fee_eligible`` helper
        # (anti-drift, single source of truth with _fee_calc_authorized): C2
        # fast-track adds ``submitted`` (prepay/hold-spot before the decision,
        # single-path only) on top of post-decision (admitted-like/confirmed/
        # enrolled); draft stays blocked.
        "calculate_fee": (
            is_fee_eligible(profile)
            and (
                is_admin
                or user_role == UserRole.ACCOUNTANT
                or (
                    profile.lead is not None
                    and profile.lead.unit_id is not None
                    and (
                        (user_role == UserRole.MANAGER
                         and profile.lead.unit_id == current_user.unit_id)
                        or (
                            is_officer
                            and profile.lead.unit_id == current_user.unit_id
                            and profile.lead.assigned_officer_id is not None
                            and profile.lead.assigned_officer_id == current_user.id
                        )
                    )
                )
            )
        ),
        "delete": status == "draft" and is_admin,
        # F6 fix 2026-05-16: Override = bypass normal eligibility flow,
        # admin-only per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN §3.4.
        # State machine allows ONLY approved → overridden (see
        # admission_state_machine.ALLOWED_TRANSITIONS line 117-122).
        # Without this flag the UI cannot surface an Override button,
        # so admin would only be able to invoke /override via direct API.
        "override": status == "approved" and is_admin,
        # Tentative — true only when role + status + path_id snapshot
        # exists. Async resolver _resolve_minor_correction_state flips
        # this back to False if the per-path effective allowlist is
        # empty, so FE never sees a button without renderable fields.
        "minor_correction": (
            (is_admitted_like(profile) or status == "confirmed")
            and (profile.applied_rules or {}).get("admission_path_id") is not None
            and (
                is_admin
                or is_manager
                or (is_officer and is_owner)
            )
        ),
        # Thu lệ phí xét tuyển - POST /api/admissions/{id}/record-fee-payment.
        # Mirror get_admission_for_fee_collection (deps.py): admin all;
        # manager/accountant same-unit; officer assigned+same-unit. Gate
        # draft/submitted + le phi thuc su pending -> nut khong hien cho exempt /
        # da-paid / post-decision.
        "record_fee_payment": (
            status in ("draft", "submitted")
            and bool((profile.applied_rules or {}).get("requires_application_fee"))
            and (profile.applied_rules or {}).get("fee_status") == "pending"
            and (
                is_admin
                or (
                    profile.lead is not None
                    and profile.lead.unit_id is not None
                    and (
                        (
                            user_role in (UserRole.MANAGER, UserRole.ACCOUNTANT)
                            and profile.lead.unit_id == current_user.unit_id
                        )
                        or (
                            is_officer
                            and profile.lead.unit_id == current_user.unit_id
                            and profile.lead.assigned_officer_id is not None
                            and profile.lead.assigned_officer_id == current_user.id
                        )
                    )
                )
            )
        ),
        "view": True,
    }
    # Dropped students (is_dropped=True; status deliberately stays "enrolled")
    # are a terminal side-channel — no workflow/mutation action applies anymore.
    # Status-based guards above can't catch this because the status is still
    # "enrolled", so e.g. calculate_fee / minor_correction / verify_priority_object
    # would otherwise stay True. Collapse every permission except read-only
    # `view` to False so neither `permissions` nor the derived
    # `available_actions` surface a stale button on a dropped seat. Runs BEFORE
    # `has_decision` below so that aggregate flag also collapses to False.
    if _is_dropped:
        permissions = {key: (key == "view") for key in permissions}
    # Code review 2026-05-22 — aggregate `has_decision` flag để FE
    # PipelineSidebar (Step 8 unlock gate) + AdmissionActions (sticky Next
    # gate 7→8) check 1 flag thay vì OR 7 permission flags rời rạc. Nếu
    # tương lai thêm decision permission mới (vd `cancel`), BE chỉ cần
    # thêm flag vào OR-list dưới và FE pickup ngay mà không cần update.
    permissions["has_decision"] = any(
        permissions[key]
        for key in (
            "submit",
            "approve",
            "reject",
            "resubmit",
            "request_revision",
            "publish_result",
            "enroll",
        )
    )
    profile.permissions = permissions

    # P0-1 fix 2026-05-22 (review B-scope) — BE-aggregated mode flag thay thế
    # FE `user.role` string check ở PriorityTab (vi phạm Thin Client RULE 2
    # frontend/CLAUDE.md). Drift risk: nếu Casbin policy đổi (accountant
    # diamond-inherit manager, role rename), FE silent flip mode. Top-level
    # field thay vì nested trong permissions dict (`Dict[str, bool]` không
    # nhận string literal).
    #
    # Values:
    #   - "admin":   admin user, full bypass (post-publish via acknowledge flag)
    #   - "manager": manager user, post-pre-publish window only
    #   - "officer": officer (READ-ONLY dialog view; backend hard-deny mutation —
    #                kept for FE empty-state CTA "Đề nghị quản lý ấn định KV")
    #   - "none":    không có quyền access workbench
    if is_admin:
        profile.override_priority_kv_mode = "admin"
    elif is_manager:
        profile.override_priority_kv_mode = "manager"
    elif is_officer:
        profile.override_priority_kv_mode = "officer"
    else:
        profile.override_priority_kv_mode = "none"
    
    # =========================================================================
    # 2. AVAILABLE ACTIONS (list of action names that are currently allowed)
    # =========================================================================
    profile.available_actions = [action for action, allowed in permissions.items() if allowed]

    # Denormalized display names (avoid N+1 in frontend)
    # ⚠️ Use __dict__.get() instead of hasattr/getattr to avoid triggering
    # SQLAlchemy lazy-load from a sync function (raises MissingGreenlet in async session).
    # Callers MUST eager-load these relationships via selectinload() before reaching here.
    _reviewer = profile.__dict__.get("assigned_reviewer")
    profile.assigned_reviewer_name = _reviewer.full_name if _reviewer else None

    _lead = profile.__dict__.get("lead")
    _officer = _lead.__dict__.get("assigned_officer") if _lead else None
    profile.assigned_officer_name = _officer.full_name if _officer else None

    # =========================================================================
    # 3. ELIGIBILITY STATUS & VALIDATION ERRORS
    # =========================================================================
    applied_rules = profile.applied_rules or {}
    
    # Set snapshot_score if available (computed by _calculate_and_update_totals)
    if not hasattr(profile, 'snapshot_score') or profile.snapshot_score is None:
        profile.snapshot_score = None
    
    # --- Execute Validation Helpers ---
    gpa_error, score_ve, gpa_errors = _validate_scores(profile, applied_rules)
    doc_errors, doc_ve, uploaded_doc_codes, upload_required_docs, unverified_doc_codes = _validate_documents(profile, documents, applied_rules)
    # PR #6 review — split missing vs pending-verify so downstream
    # stats/messages don't conflate the two ("đã nộp 1/1" + "Còn thiếu 1"
    # was reachable for a doc that's uploaded-but-pending-verify in
    # strict mode).
    missing_doc_codes = [code for code in doc_errors if code not in unverified_doc_codes]
    missing_personal, personal_ve = _validate_personal_info(profile)
    
    # Aggregate validation errors
    validation_errors = score_ve + doc_ve + personal_ve
    
    # Track CCCD error for backward compatibility with step_status logic
    cccd_error = not profile.citizen_id
    
    # Determine eligibility status
    if len(validation_errors) == 0:
        profile.eligibility_status = "eligible"
    elif status in ["approved", "enrolled"]:
        profile.eligibility_status = "eligible"
    else:
        profile.eligibility_status = "ineligible"
    
    # Ticket #2: Compute is_qualified
    profile.is_qualified = not gpa_error
    if status in ["approved", "enrolled"]:
        profile.is_qualified = True
    
    profile.validation_errors = validation_errors

    # =========================================================================
    # Fast-track prepay/giữ chỗ — nợ giấy tờ contract (C1)
    # =========================================================================
    # SUBTRACTION (not enumeration): "other_errors" = every validation error
    # EXCEPT the truly-missing-mandatory-document ones. We can submit-with-debt
    # only when other_errors is empty (eligible apart from missing docs).
    #
    # The missing-doc messages produced by _validate_documents are exactly
    # ``"Thiếu tài liệu bắt buộc: {code}"`` for each code in missing_doc_codes
    # (uploaded-but-pending-verify docs use a DIFFERENT "chưa được xác minh"
    # message and stay in other_errors → they still block, honouring B2:
    # only truly-missing docs are waivable, never unverified ones).
    _missing_doc_messages = {
        _missing_doc_error_message(code) for code in missing_doc_codes
    }
    _other_errors = [
        err for err in validation_errors if err not in _missing_doc_messages
    ]

    # The badge the FE renders is the COMPUTED set of debt codes whose docs are
    # STILL not VERIFIED — it self-resolves once a reviewer verifies (or marks
    # paper_submitted) each owed doc. VERIFIED-based, NOT missing-based: a doc
    # that was merely uploaded (status ``uploaded``, not yet verified) still
    # counts as outstanding (PLAN §C1.5 — hết nợ chỉ khi VERIFY). Computed via
    # the shared ``_compute_outstanding_debt_codes`` helper above so the FE
    # badge, the gated ``approve`` permission here, and the service-side approve
    # gate all agree on one definition.
    profile.outstanding_debt_codes = list(_outstanding_debt_codes)
    # Expose the currently-missing mandatory doc codes so the FE can list them
    # in the submit-with-debt dialog (B3).
    profile.missing_doc_codes = list(missing_doc_codes)

    # L1 owner-consistency: gate the submit-with-debt button on the SAME actor
    # set as ``permissions["submit"]`` (is_owner or is_manager or is_admin) to
    # prevent drift — submit-with-debt is just submit + a doc-debt snapshot, so
    # an actor who can't submit must not see the debt variant either. (Previous
    # ``is_admin or is_manager or is_officer`` admitted any officer, including
    # one not assigned to the lead, which submit itself rejects via is_owner.)
    # The server-side submit gate in submit_and_evaluate is role+IDOR based and
    # unchanged — this only aligns the FE flag. The button shows only when the
    # draft is eligible apart from missing docs (other_errors empty + ≥1 missing
    # doc) and is not a multi-NV profile lacking choices.
    profile.can_submit_with_document_debt = bool(
        status == "draft"
        and (is_owner or is_manager or is_admin)
        and not _other_errors
        and missing_doc_codes
        and not _multi_nv_no_choice
    )

    # F7 fix 2026-05-16: surface bypass-eligibility hazard to FE.
    # When `applied_rules.allow_unverified_submission=True`, applicant can
    # submit a profile despite missing required data (per Decision 1 in
    # admission-audit-decisions-2026-04-24). Reviewer (admin/manager) can
    # then approve a profile that is actually `eligibility_status=ineligible`
    # — silently creating a student row with NULL name etc. UI must show
    # warning + confirmation dialog before /approve fires.
    profile.bypass_warning = bool(
        applied_rules.get("allow_unverified_submission")
        and profile.eligibility_status == "ineligible"
        and status in ("submitted", "resubmitted", "reviewing")
    )

    # =========================================================================
    # 4. VALIDATION SUMMARY (Grouped Errors for UX)
    # =========================================================================
    # Calculate GPA label for summary
    min_gpa = float(applied_rules.get("min_gpa") or 0)
    current_gpa = profile.average_score or 0
    personal_error_count = len(missing_personal)
    
    profile.validation_summary = {
        "gpa": {
            "has_error": len(gpa_errors) > 0,
            "label": f"GPA: {current_gpa:.1f}/{min_gpa}" if min_gpa > 0 else "GPA: N/A",
            "count": len(gpa_errors)
        },
        "documents": {
            "has_error": len(doc_errors) > 0,
            "label": f"Tài liệu: {len(uploaded_doc_codes)}/{len(upload_required_docs)}",
            "count": len(doc_errors)
        },
        "personal": {
            "has_error": personal_error_count > 0,
            "label": f"Thiếu {personal_error_count} thông tin cá nhân" if personal_error_count > 0 else "Thông tin cá nhân: OK",
            "count": personal_error_count
        }
    }

    # =========================================================================
    # 4.1 GROUPED VALIDATION ERRORS (Enhanced UX - Categorized Display)
    # =========================================================================
    profile.grouped_validation_errors = {
        "personal_info": {
            "category": "Thông tin cá nhân",
            "errors": personal_ve, # Use the computed list from helper
            "count": len(personal_ve)
        },
        "documents": {
            "category": "Tài liệu",
            # PR #6 review — distinguish missing vs pending-verify in the
            # grouped list. Same render order as doc_errors so existing
            # consumers that index by position don't drift.
            "errors": (
                [f"Thiếu tài liệu bắt buộc: {doc_code}" for doc_code in missing_doc_codes]
                + [
                    f"Tài liệu {doc_code} đã tải lên nhưng chưa được xác minh"
                    for doc_code in unverified_doc_codes
                ]
            ),
            "count": len(doc_errors),
            "missing_count": len(missing_doc_codes),
            "unverified_count": len(unverified_doc_codes),
        },
        "scores": {
            "category": "Điểm số",
            "errors": gpa_errors,
            "count": len(gpa_errors)
        }
    }

    # =========================================================================
    # 4.2 SCORE SNAPSHOT STATUS (Thin Client Compliance - Ticket #5)
    # Backend computes pass/fail for each subject and total score
    # Frontend ONLY renders, never calculates
    # =========================================================================
    min_subject_score = float(applied_rules.get("min_subject_score") or 0)
    min_score = float(applied_rules.get("min_score") or 0)
    total_score = profile.total_score
    subject_scores = {s.subject.code: float(s.score) for s in profile.subject_scores} if profile.subject_scores else {}

    # Compute subject pass/fail statuses
    subject_statuses = {}
    for code, score in subject_scores.items():
        if score is not None:
            # Pass if score >= min_subject_score (0 threshold means always pass)
            subject_statuses[code] = "passing" if score >= min_subject_score else "failing"
        else:
            subject_statuses[code] = None  # No score yet

    # Compute total score status
    total_status = None
    if total_score is not None:
        # Pass if total >= min_score (0 threshold means always pass)
        total_status = "passing" if total_score >= min_score else "failing"

    profile.score_snapshot_status = {
        "total_status": total_status,
        "subject_statuses": subject_statuses,
        "min_subject_score": min_subject_score,
        "min_score": min_score,
    }
    
    # =========================================================================
    # 5. STEP STATUS (Architecture Compliant - Backend computes, FE renders)
    # =========================================================================
    # Required personal fields for step 1 check
    personal_required = ["full_name", "phone", "citizen_id"]
    personal_optional = ["email", "dob", "gender", "nationality", "ethnicity"]
    personal_required_filled = all(getattr(profile, f, None) for f in personal_required)
    personal_optional_filled = all(getattr(profile, f, None) for f in personal_optional)
    
    # Family
    has_family = profile.family_info and len(profile.family_info) > 0
    
    # Academic
    has_academic = profile.academic_history and len(profile.academic_history) > 0
    
    # P0 hotfix multi-NV — Step 5 (Scores) "has any" must read per-choice
    # ProfileChoiceScore for multi-NV (profile.subject_scores is always empty
    # there), mirroring _compute_completion_percent. Without this branch the
    # RESPONSE step_status[5] stays 'warning' for a fully-scored multi-NV
    # profile (it never turns 'success'), contradicting completion_percent.
    if getattr(profile, "uses_choice_engine", False):
        _ch = profile.__dict__.get("choices") or []
        has_any_scores = any(bool(c.__dict__.get("scores")) for c in _ch)
    else:
        has_any_scores = (
            bool(profile.subject_scores)
            if hasattr(profile, 'subject_scores')
            else False
        )

    # Phase E.4 — Step 4 Priority compute (KV resolved + cultural input)
    has_priority_input = bool(getattr(profile, "cultural_education_level", None))
    snapshot = getattr(profile, "priority_resolution_snapshot", None) or {}
    kv_resolved = bool(snapshot.get("kv_resolved")) if isinstance(snapshot, dict) else False

    # ✅ FIX: Documents format confirmation check
    # Check if all uploaded documents have been verified by manager or confirmed as paper submitted
    docs_format_confirmed = True
    if documents is not None:
        for doc in documents:
            # If document is uploaded but not yet verified/paper_submitted, format not confirmed
            if doc.status == "uploaded" and doc.file_path:
                docs_format_confirmed = False
                break

    # Phase E.4 (G0) — 8-step model. Step 4 = Priority (new gộp KV+UT).
    # Previous Step 4 (Scores) renumbered → Step 5. Step 5 (Documents) → 6.
    # Step 6 (Tuition) → 7. Step 7 (Finalize) → 8. FE PipelineSidebar đã 8 steps.
    step_status = {
        # Step 1: Personal Info
        1: "error" if (cccd_error or not personal_required_filled) else ("success" if personal_optional_filled else "warning"),
        # Step 2: Family
        2: "success" if has_family else "warning",
        # Step 3: Academic History
        3: "success" if has_academic else "warning",
        # Step 4: Priority (NEW — Phase E.4 gộp KV+UT)
        4: (
            "error" if not has_priority_input
            else "warning" if not kv_resolved
            else "success"
        ),
        # Step 5: Scores (renumbered từ Step 4)
        5: "error" if gpa_error else ("success" if has_any_scores else "warning"),
        # Step 6: Documents (renumbered từ Step 5)
        6: "error" if len(doc_errors) > 0 else ("warning" if not docs_format_confirmed else "success"),
        # Step 7: Tuition (renumbered từ Step 6, display only)
        7: "success",
        # Step 8: Finalize (renumbered từ Step 7)
        8: "locked" if profile.eligibility_status == "ineligible" else "success",
    }
    profile.step_status = step_status

    # =========================================================================
    # 6. COMPLETION PERCENT (delegates to shared pure helper)
    # =========================================================================
    profile.completion_percent = _compute_completion_percent(profile, documents)
    
    # =========================================================================
    # 7. DOCUMENTS CHECKLIST (for frontend display)
    # Build from applied_rules + ProfileDocument data
    # =========================================================================
    all_mandatory_docs = applied_rules.get("mandatory_docs", [])
    doc_configs = applied_rules.get("doc_configs", {})  # {code: {requires_upload, submission_format}}
    
    # ADM-031 round 10: verifier display name comes from the pre-resolved
    # ``verifier_names`` map (built once per profile load by
    # ``_resolve_verifier_names`` — single SELECT for all distinct
    # verified_by ids). ``None`` here means the caller didn't pass the map
    # (mutation paths that go through ``_populate_response_fields`` do; a
    # few internal recompute sites don't), in which case the FE renders
    # "User #<id>" using the raw ``verified_by`` field. Always safe.
    _verifier_names_local = verifier_names or {}

    # Create lookup of uploaded documents by code.
    #
    # ADM-031 round 10 review (B1): the response contract for each row is
    # gated by the CURRENT status, not by the raw DB columns. Reject /
    # reset paths historically leave artifact columns dirty
    # (``file_path``, ``uploaded_at``, ``actual_submission_format``,
    # ``verified_format``, ``paper_submitted_at``, ``verified_at``,
    # ``verified_by``). Emitting them unconditionally produced UI rows
    # like "Đã ghi nhận: Chụp/scan · 29/04" alongside a "Từ chối" badge
    # that says reception is "Chưa" — two halves of the same cell
    # contradicting each other. Gate here so each terminal state shows
    # only what it actually has:
    #
    #   * uploaded            : file artifact + officer-declared format
    #   * paper_submitted     : paper receipt timestamp + declared format
    #   * verified            : everything above + verifier identity +
    #                           verified_format
    #   * rejected / missing  : status only; reason for rejection;
    #                           no artifact, no format, no verifier
    #
    # Avoids a DB backfill while keeping the API contract clean.
    _ARTIFACT_STATUSES = ("uploaded", "paper_submitted", "verified")
    doc_by_code = {}
    if documents:
        for doc in documents:
            if doc.document_type:
                _has_artifact = doc.status in _ARTIFACT_STATUSES
                _is_verified = doc.status == "verified"
                doc_by_code[doc.document_type.code] = {
                    # PR1 Commit 1: ProfileDocument PK — surfaced as
                    # ``document_id`` in the checklist projection so the FE
                    # builds the authed download URL. The append blocks below
                    # only expose it when a real file_path exists.
                    "id": doc.id,
                    "status": doc.status,
                    "label_from_db": doc.document_type.name,
                    # rejection_reason is the only field that is meaningful
                    # specifically when status == rejected — keep it
                    # visible in the rejected branch so the FE row can
                    # render the "Lý do" line.
                    "rejection_reason": doc.rejection_reason,
                    # submission_format_confirmed: True if manager verified the format.
                    "submission_format_confirmed": _is_verified,
                    # Artifact fields — only meaningful while a usable
                    # document exists on the row.
                    "file_path": doc.file_path if _has_artifact else None,
                    "uploaded_at": (
                        doc.uploaded_at.isoformat()
                        if _has_artifact and doc.uploaded_at
                        else None
                    ),
                    # ADM-031 round 4: officer-declared format. ADM-031
                    # round 10 (B1): suppress on missing/rejected.
                    "actual_submission_format": (
                        doc.actual_submission_format if _has_artifact else None
                    ),
                    # verified_format is only meaningful when the doc is
                    # currently in the verified state — uploaded /
                    # paper_submitted rows haven't been verified yet, so
                    # the column should not surface even if it was set
                    # before a manager later reset/rejected.
                    "verified_format": doc.verified_format if _is_verified else None,
                    # ADM-031 round 7: paper-receipt timestamp.
                    "paper_submitted_at": (
                        doc.paper_submitted_at.isoformat()
                        if _has_artifact and doc.paper_submitted_at
                        else None
                    ),
                    # ADM-031 round 10: verifier identity. verified_by_name
                    # is filled from a batched User lookup so this loop
                    # stays N+1-free. Suppress unless status == verified.
                    "verified_at": (
                        doc.verified_at.isoformat()
                        if _is_verified and doc.verified_at
                        else None
                    ),
                    "verified_by": doc.verified_by if _is_verified else None,
                    "verified_by_name": (
                        _verifier_names_local.get(doc.verified_by)
                        if _is_verified and doc.verified_by is not None
                        else None
                    ),
                    # PR #13 — loại giấy tốt nghiệp + hạn "nợ bằng".
                    "graduation_proof_kind": (
                        doc.graduation_proof_kind if _has_artifact else None
                    ),
                    "supplement_due_date": (
                        doc.supplement_due_date.isoformat()
                        if _has_artifact and doc.supplement_due_date
                        else None
                    ),
                }
    
    # PR #5 — per-document action permissions delegate to the
    # DocumentActionPolicy class so the FE can_* flag matrix and the
    # service-side _authorize_document_action gate are computed from a
    # single source of truth. Update one place; both stay in sync.
    from .admission_document_policy import DocumentActionPolicy
    _doc_policy = DocumentActionPolicy.for_(profile, current_user)

    def _compute_document_permissions(
        doc_status: str,
        requires_upload: bool,
    ) -> dict[str, bool]:
        """Per-document action flags via :class:`DocumentActionPolicy`.

        Route contracts mirrored:
        - Upload  : POST /admissions/{id}/documents/{code}/upload
                    officer assigned to the lead, profile in editable state,
                    doc expects an upload and isn't already verified/paper.
        - Verify  : POST /admissions/{id}/documents/{code}/verify-format
                    manager/admin in scope, doc status uploaded|paper_submitted.
        - Reject  : POST /admissions/{id}/documents/{code}/reject
                    manager/admin in scope, doc status uploaded|paper_submitted|verified.
        - Reset   : POST /admissions/{id}/documents/{code}/reset
                    manager/admin in scope, doc status != missing.
        - Paper   : POST /admissions/{id}/documents/{code}/paper-submitted
                    officer assigned to the lead, paper-only doc (requires_upload=False),
                    status still missing.
        """
        return {
            "can_upload": _doc_policy.authorize("upload", doc_status, requires_upload),
            "can_verify": _doc_policy.authorize("verify", doc_status, requires_upload),
            "can_reject": _doc_policy.authorize("reject", doc_status, requires_upload),
            "can_reset": _doc_policy.authorize("reset", doc_status, requires_upload),
            "can_mark_paper_submitted": _doc_policy.authorize(
                "paper_submitted", doc_status, requires_upload
            ),
        }

    # Build documents_checklist.
    # Two passes:
    #   (1) snapshot-driven mandatory docs from ``applied_rules.mandatory_docs``
    #       — flagged ``is_mandatory=True``, ``is_extra=False``.
    #   (2) BR2 (2026-04-29): ProfileDocument rows whose code is NOT in
    #       the snapshot — flagged ``is_extra=True``, all ``can_*``
    #       forced false (extras are evidence/audit, never silently
    #       dropped, but no actions surface in the UI). Happens when the
    #       AdmissionPath was edited after the profile was created and
    #       previously-uploaded docs are no longer in the current
    #       mandatory list. Sync action that would refresh the snapshot
    #       is intentionally out of scope for this PR.
    documents_checklist = []
    _mandatory_set = set(all_mandatory_docs)
    # BR2 fix (2026-06-09): "active" = MỌI doc trong doc_configs hiện tại
    # (mandatory + optional), KHÔNG chỉ mandatory_docs. Optional doc
    # (is_mandatory=false trong doc_configs, vd giay_kham_suc_khoe /
    # giay_xac_nhan_cu_tru) khi đã nộp trước đây rơi vào pass 2 →
    # is_extra=True + read-only + nhãn "ngoài yêu cầu hiện tại" SAI (thực
    # ra là tài liệu tùy chọn của phương thức hiện tại). Thứ tự: mandatory
    # trước (giữ thứ tự required), optional sau (thứ tự config).
    _active_codes = list(all_mandatory_docs) + [
        c for c in doc_configs.keys() if c not in _mandatory_set
    ]
    _active_set = set(_active_codes)

    for i, doc_code in enumerate(_active_codes):
        config = doc_configs.get(doc_code, {})
        uploaded_doc = doc_by_code.get(doc_code, {})
        _doc_status = uploaded_doc.get("status", "missing")
        _requires_upload = config.get("requires_upload", True)
        _perms = _compute_document_permissions(_doc_status, _requires_upload)

        documents_checklist.append({
            "code": doc_code,
            "label": config.get("label") or uploaded_doc.get("label_from_db") or doc_code,
            "is_mandatory": doc_code in _mandatory_set,
            "is_extra": False,
            "requires_upload": _requires_upload,
            "submission_format": config.get("submission_format"),
            # ADM-031 round 4: pass through the officer-declared and
            # manager-verified format codes so the FE row can render the
            # actual/verified state next to the required format.
            "actual_submission_format": uploaded_doc.get("actual_submission_format"),
            "verified_format": uploaded_doc.get("verified_format"),
            "status": _doc_status,
            "file_path": uploaded_doc.get("file_path"),
            # PR1 Commit 1: PK only when a real downloadable file exists, so
            # the FE renders the "Xem PDF" button iff document_id is non-null.
            "document_id": uploaded_doc.get("id") if uploaded_doc.get("file_path") else None,
            "uploaded_at": uploaded_doc.get("uploaded_at"),
            # ADM-031 round 7: paper-receipt timestamp
            "paper_submitted_at": uploaded_doc.get("paper_submitted_at"),
            # ADM-031 round 10: verifier identity for the Trạng thái cell
            "verified_at": uploaded_doc.get("verified_at"),
            "verified_by": uploaded_doc.get("verified_by"),
            "verified_by_name": uploaded_doc.get("verified_by_name"),
            "rejection_reason": uploaded_doc.get("rejection_reason"),
            "submission_format_confirmed": uploaded_doc.get("submission_format_confirmed", False),
            # PR #13 — graduation proof + cờ "đã nhận bằng chính thức".
            "graduation_proof_kind": uploaded_doc.get("graduation_proof_kind"),
            "supplement_due_date": uploaded_doc.get("supplement_due_date"),
            "can_update_graduation_kind": (
                doc_code == "bang_tot_nghiep_thpt"
                and uploaded_doc.get("graduation_proof_kind")
                == "provisional_cert"
            ),
            **_perms,
        })

    # Pass (2): extra ProfileDocument rows — code KHÔNG còn trong doc_configs
    # hiện tại (path đã đổi sau khi nộp). Stable sort by code so repeated GETs
    # render in a consistent order. Dùng _active_set (= doc_configs keyset),
    # KHÔNG _mandatory_set, để optional doc không bị coi nhầm là extra.
    for extra_code in sorted(c for c in doc_by_code.keys() if c not in _active_set):
        uploaded_doc = doc_by_code[extra_code]
        _doc_status = uploaded_doc.get("status", "missing")
        # No live config for extras (path changed). Infer
        # requires_upload from the artifact: a file_path means an
        # upload happened, otherwise treat as paper-only.
        _requires_upload = bool(uploaded_doc.get("file_path"))

        documents_checklist.append({
            "code": extra_code,
            "label": uploaded_doc.get("label_from_db") or extra_code,
            "is_mandatory": False,
            "is_extra": True,
            "requires_upload": _requires_upload,
            "submission_format": None,
            "actual_submission_format": uploaded_doc.get("actual_submission_format"),
            "verified_format": uploaded_doc.get("verified_format"),
            "status": _doc_status,
            "file_path": uploaded_doc.get("file_path"),
            # PR1 Commit 1: PK only when a real downloadable file exists.
            "document_id": uploaded_doc.get("id") if uploaded_doc.get("file_path") else None,
            "uploaded_at": uploaded_doc.get("uploaded_at"),
            "paper_submitted_at": uploaded_doc.get("paper_submitted_at"),
            "verified_at": uploaded_doc.get("verified_at"),
            "verified_by": uploaded_doc.get("verified_by"),
            "verified_by_name": uploaded_doc.get("verified_by_name"),
            "rejection_reason": uploaded_doc.get("rejection_reason"),
            "submission_format_confirmed": uploaded_doc.get(
                "submission_format_confirmed", False
            ),
            # PR #13 — surface the "nợ bằng" debt even on an extra row so the
            # badge stays visible if bang_tot_nghiep_thpt drops out of the
            # snapshot; extras are read-only → no upgrade action (the service
            # is_extra guard would reject it anyway).
            "graduation_proof_kind": uploaded_doc.get("graduation_proof_kind"),
            "supplement_due_date": uploaded_doc.get("supplement_due_date"),
            "can_update_graduation_kind": False,
            # Extras are read-only: row visible for evidence + audit,
            # but no action buttons. A future sync-path action will own
            # the cleanup workflow.
            "can_upload": False,
            "can_verify": False,
            "can_reject": False,
            "can_reset": False,
            "can_mark_paper_submitted": False,
        })

    profile.documents_checklist = documents_checklist

    # ✅ Ticket #3.1: Document Status Summary (Backend Computed)
    # Calculate stats for Thin Client compliance
    if documents is not None:
         mandatory_docs = [doc for doc in documents if doc.document_type and doc.document_type.code in upload_required_docs]
         
         # Count based on status
         submitted_count = len([d for d in mandatory_docs if d.status in ["uploaded", "verified", "paper_submitted"]])
         verified_count = len([d for d in mandatory_docs if d.status == "verified"])
         mandatory_count = len(upload_required_docs)
         # PR #6 review — split: pending-verify shouldn't count as
         # "missing" because the file IS uploaded; UI prior to the fix
         # rendered "1/1 đã nộp" + "Còn thiếu: 1" simultaneously for the
         # same row. unverified_count surfaces that bucket explicitly so
         # the FE can label it "Chờ xác minh".
         missing_count = len(missing_doc_codes)
         unverified_count = len(unverified_doc_codes)

         profile.document_stats = {
             "submitted_count": submitted_count,
             "verified_count": verified_count,
             "mandatory_count": mandatory_count,
             "missing_count": missing_count,
             "unverified_count": unverified_count,
         }

    # =========================================================================
    # 8. EXECUTIVE SUMMARY (Dashboard Overview)
    # =========================================================================
    # Provides high-level status summary for dashboard display
    # Frontend uses this to show overall progress and next actions

    # Count steps by status
    step_counts = {"success": 0, "warning": 0, "error": 0, "locked": 0}
    for step_state in step_status.values():
        step_counts[step_state] = step_counts.get(step_state, 0) + 1

    # Determine overall status
    has_errors = step_counts["error"] > 0
    has_warnings = step_counts["warning"] > 0
    has_locked = step_counts["locked"] > 0

    if has_errors or has_locked:
        overall_status = "incomplete"  # Blocking issues exist
    elif has_warnings:
        overall_status = "warning"  # Optional fields missing
    else:
        overall_status = "ready"  # All steps complete

    # Identify critical blockers + warnings as STRUCTURED items (Phase 3 — each
    # carries {code, message, step, section, severity} so the FE routes a blocker
    # to its exact step). Built by a pure helper for unit-testability. Semantics
    # UNCHANGED vs the old string form (same conditions, same blocker/warning
    # split). Transient field (no DB migration).
    # Local import (mirror :777) — KHÔNG global để pure-test import sạch.
    from app.config import settings

    critical_blockers, warning_messages = _build_executive_summary_items(
        personal_error_count=personal_error_count,
        missing_doc_count=len(missing_doc_codes),
        unverified_doc_count=len(unverified_doc_codes),
        gpa_error=bool(gpa_error),
        has_family=bool(has_family),
        has_academic=bool(has_academic),
        docs_format_confirmed=bool(docs_format_confirmed),
        cultural=profile.cultural_education_level,
        academic_history=profile.academic_history,
        thcs_review_from_year=settings.THCS_DIPLOMA_REVIEW_FROM_GRADE9_YEAR,
    )

    # Suggest next action (Phase E.4 — 8-step model: Step 4=Priority, 5=Scores, 6=Documents)
    if step_status[1] == "error":
        next_action = "Hoàn thiện thông tin cá nhân bắt buộc"
    elif step_status[4] == "error":
        next_action = "Cần ghi nhận trình độ văn hóa cho ưu tiên KV"
    elif step_status[5] == "error":
        next_action = "Nhập điểm số đạt yêu cầu"
    elif step_status[6] == "error":
        next_action = "Tải lên tài liệu bắt buộc"
    elif has_warnings:
        next_action = "Hoàn thiện thông tin còn thiếu (không bắt buộc)"
    elif profile.eligibility_status == "eligible" and status == "draft":
        next_action = "Kiểm tra và nộp hồ sơ"
    else:
        next_action = "Hồ sơ đã hoàn tất"

    # Can submit only if eligible and in draft status
    can_submit = profile.eligibility_status == "eligible" and status == "draft"

    profile.executive_summary = {
        "overall_status": overall_status,
        "completion_percent": profile.completion_percent,
        "step_summary": step_counts,
        "critical_blockers": critical_blockers,
        "warnings": warning_messages,
        "next_action": next_action,
        "can_submit": can_submit,
    }

    # =========================================================================
    # 9. SENSITIVE DATA MASKING (Security & Privacy Compliance)
    # =========================================================================
    # Mask CCCD for display purposes - show only last 4 digits
    # Full citizen_id is still available for form editing
    profile.citizen_id_masked = mask_citizen_id(profile.citizen_id)


# =============================================================================
# Q9 #07 Phase E.4 — Priority evidence transient projection helpers
# =============================================================================

# Display-only fields trên enriched evidence dict — KHÔNG persist xuống JSONB.
# Spec G3 (audit cycle 4): nếu code path nào mutate raw evidence rồi assign back
# vào JSONB column, các field này có thể leak. Helper _strip_display_fields_from_
# evidence() strip trước assignment để defensive guard.
_EVIDENCE_DISPLAY_ONLY_FIELDS = frozenset({
    "verified_by_name",
    "document_file_path",
})


def _strip_display_fields_from_evidence(
    evidence: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Sanitize evidence dict before writing back to JSONB column.

    Display fields chỉ valid trên transient `_display` projection. Persisting
    chúng vào raw JSONB column sẽ cause schema drift on re-read (next
    denormalize pass thêm fields, growing nested dict mỗi request).

    `paper_only_verification` IS persisted (set during verify), NOT stripped.

    Use sites: any function mutating ``profile.priority_object_evidence`` MUST
    call helper trước assign — verify_object_evidence, reject_object_evidence,
    untick_priority_evidence, manual_override_kv nếu touches evidence.
    """
    cleaned: Dict[str, Dict[str, Any]] = {}
    for code, entry in evidence.items():
        if not isinstance(entry, dict):
            cleaned[code] = entry
            continue
        cleaned[code] = {
            k: v for k, v in entry.items()
            if k not in _EVIDENCE_DISPLAY_ONLY_FIELDS
        }
    return cleaned


async def _enrich_priority_evidence_display(
    db: AsyncSession,
    evidence: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Build denormalized display projection of priority_object_evidence.

    Adds 2 display fields per entry:
    - ``verified_by_name``: user.full_name lookup từ verified_by id.
    - ``document_file_path``: ProfileDocument.file_path lookup từ document_id.

    Returns NEW dict — does NOT mutate input. Caller assigns kết quả vào
    TRANSIENT attribute ``profile.priority_object_evidence_display`` (Pydantic
    schema field), NOT vào raw ORM column ``priority_object_evidence`` (sẽ
    trigger SQLAlchemy dirty flag + persist denormalized data xuống DB).
    """
    if not evidence:
        return {}

    user_ids = {
        e.get("verified_by")
        for e in evidence.values()
        if isinstance(e, dict) and e.get("verified_by")
    }
    doc_ids = {
        e.get("document_id")
        for e in evidence.values()
        if isinstance(e, dict) and e.get("document_id")
    }

    user_names: Dict[int, str] = {}
    if user_ids:
        rows = await db.execute(
            select(models.User.id, models.User.full_name)
            .where(models.User.id.in_(user_ids))
        )
        user_names = {row.id: row.full_name for row in rows}

    doc_paths: Dict[int, str] = {}
    if doc_ids:
        # ProfileDocument has only ``file_path`` (S3 path String 500) — NO
        # ``filename`` column exists. FE derives display filename via
        # path.split('/').pop() (basename extract). See spec V3 Section VI
        # "Schema verification" for optional fidelity upgrade path.
        rows = await db.execute(
            select(
                models.ProfileDocument.id,
                models.ProfileDocument.file_path,
            )
            .where(models.ProfileDocument.id.in_(doc_ids))
        )
        doc_paths = {row.id: row.file_path for row in rows if row.file_path}

    enriched: Dict[str, Dict[str, Any]] = {}
    for code, entry in evidence.items():
        if not isinstance(entry, dict):
            enriched[code] = entry
            continue
        e = dict(entry)
        if e.get("verified_by") and e["verified_by"] in user_names:
            e["verified_by_name"] = user_names[e["verified_by"]]
        if e.get("document_id") and e["document_id"] in doc_paths:
            # Pass full S3 path; FE extracts basename for display
            e["document_file_path"] = doc_paths[e["document_id"]]
        enriched[code] = e
    return enriched


async def _populate_priority_evidence_projections(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    documents: List[models.ProfileDocument],
) -> None:
    """Phase E.4 — populate 3 TRANSIENT priority evidence projections.

    Sets 3 transient attributes (NOT tracked by SQLAlchemy, KHÔNG persist):
    - ``priority_object_evidence_display``: enriched evidence dict với
      verified_by_name + document_file_path (per G3a write/display split).
    - ``missing_priority_evidence_codes``: UT codes ghi nhận nhưng chưa
      có file đính kèm (Decision #2 inline warning).
    - ``priority_evidence_documents``: per-UT document items cho DocumentsTab
      Priority section (G0a response contract clarification).

    G2 defensive: wrapped in try/except — bất kỳ lỗi nào (vd MissingGreenlet
    nếu caller chưa eager-load profile.documents) sẽ silent fallback empty
    defaults thay vì crash entire response. Log warning để monitor.

    Reads ``profile.priority_object_evidence`` raw JSONB (loose Dict[str, Dict])
    + ``profile.priority_object_codes`` list + ``documents`` filtered list +
    PriorityObjectConfig catalog lookup by academic_year.
    """
    evidence_raw = profile.priority_object_evidence or {}

    # 1. Enriched display projection (verified_by_name + document_file_path)
    try:
        enriched = await _enrich_priority_evidence_display(db, evidence_raw)
        # TRANSIENT attribute — read by Pydantic from_attributes via the
        # ``priority_object_evidence_display`` field on AdmissionProfileResponse.
        # Assigning to this Python attribute does NOT trigger SQLAlchemy dirty
        # flag (no column tracker), so router db.commit() does NOT persist.
        profile.priority_object_evidence_display = enriched
    except Exception as exc:  # noqa: BLE001 — defensive
        log.warning(
            "priority_object_evidence_display enrichment failed",
            profile_id=profile.id,
            error=str(exc),
        )
        profile.priority_object_evidence_display = None

    # 2. Missing priority evidence codes (Decision #2 inline warning)
    try:
        priority_codes = list(profile.priority_object_codes or [])
        if priority_codes:
            uploaded_codes = {
                doc.priority_sub_code
                for doc in documents
                if getattr(doc, "category", None) == "priority_evidence"
                and getattr(doc, "priority_sub_code", None)
            }
            profile.missing_priority_evidence_codes = sorted(
                set(priority_codes) - uploaded_codes
            )
        else:
            profile.missing_priority_evidence_codes = []
    except Exception as exc:  # noqa: BLE001 — defensive
        log.warning(
            "missing_priority_evidence_codes compute failed",
            profile_id=profile.id,
            error=str(exc),
        )
        profile.missing_priority_evidence_codes = []

    # 3. Priority evidence documents (G0a — DocumentsTab Priority section)
    try:
        priority_codes = list(profile.priority_object_codes or [])
        if priority_codes:
            # Load catalog cho academic_year — PriorityObjectConfig.evidence_doc_type
            # là text Việt sẵn (KHÔNG phải FK đến ConfigDocumentType).
            catalog_rows = await db.execute(
                select(
                    models.PriorityObjectConfig.sub_code,
                    models.PriorityObjectConfig.bonus_points,
                    models.PriorityObjectConfig.evidence_doc_type,
                )
                .where(
                    models.PriorityObjectConfig.academic_year == profile.academic_year,
                    models.PriorityObjectConfig.sub_code.in_(priority_codes),
                )
            )
            catalog_by_code = {
                row.sub_code: {
                    "bonus_points": float(row.bonus_points) if row.bonus_points else 0.0,
                    "evidence_doc_type": row.evidence_doc_type or "(Chưa có catalog)",
                }
                for row in catalog_rows
            }
            docs_by_code = {
                doc.priority_sub_code: doc
                for doc in documents
                if getattr(doc, "category", None) == "priority_evidence"
                and getattr(doc, "priority_sub_code", None)
            }
            items: List[Dict[str, Any]] = []
            for code in priority_codes:
                cat = catalog_by_code.get(code, {})
                doc = docs_by_code.get(code)
                evidence_entry = evidence_raw.get(code, {}) if isinstance(
                    evidence_raw.get(code), dict
                ) else {}
                items.append({
                    "sub_code": code,
                    "bonus_points": cat.get("bonus_points", 0.0),
                    "label": cat.get("evidence_doc_type", "(Chưa có catalog)"),
                    "document_id": doc.id if doc else None,
                    "document_file_path": doc.file_path if doc else None,
                    "status": "uploaded" if doc else "missing",
                    "verification_status": evidence_entry.get("status"),
                })
            profile.priority_evidence_documents = items
        else:
            profile.priority_evidence_documents = []
    except Exception as exc:  # noqa: BLE001 — defensive
        log.warning(
            "priority_evidence_documents compute failed",
            profile_id=profile.id,
            error=str(exc),
        )
        profile.priority_evidence_documents = []


async def _populate_response_fields(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    current_user: Optional[models.User],
    *,
    documents: Optional[List[models.ProfileDocument]] = None,
) -> None:
    """Populate transient computed fields on a profile for API response serialization.

    Call this AFTER ``await db.flush()`` and BEFORE returning from any mutation
    function whose return value is serialized via ``AdmissionProfileResponse``.
    Without this call, computed fields (``permissions``, ``available_actions``,
    ``eligibility_status``, ``step_status``, ``completion_percent``,
    ``validation_errors``, ``assigned_officer_name``, ``assigned_reviewer_name``)
    silently fall back to schema defaults — making mutation responses diverge
    from subsequent ``GET`` responses.

    Args:
        db: AsyncSession used to (optionally) load fresh documents.
        profile: AdmissionProfile mutated in-place by ``_compute_frontend_fields``.
        current_user: Acting user. May be ``None`` for system callbacks (e.g. a
            future payment gateway hitting ``record_application_fee_payment``
            without a user context). When ``None`` the helper is a no-op:
            computed fields stay at schema defaults, which is acceptable for
            non-user-facing flows because there is no UI rendering that needs
            ``permissions``.
        documents: Optional pre-loaded list of ``ProfileDocument``. If ``None``
            the helper fetches them via ``AdmissionRepository.get_all_documents``.
            Pass when documents are already loaded (e.g. after
            ``reload_profile_with_lead``) to avoid a redundant query.

    Requires ``profile.lead`` (with nested ``lead.assigned_officer``) and
    ``profile.assigned_reviewer`` to already be eager-loaded by the caller —
    use the nested ``selectinload`` pattern from ``update_profile`` or the
    ``get_admission_for_manager`` / ``get_admission_for_user`` dependencies.
    Missing eager-loads will silently produce ``null`` denormalized name fields
    rather than crash, because ``_compute_frontend_fields`` uses
    ``profile.__dict__.get(...)``.
    """
    if current_user is None:
        # System callback path: no role/permissions to compute. Skip silently.
        return

    # P0 hotfix multi-NV (8d) — DEFENSIVE choices eager-load at the async
    # chokepoint. deps.py get_admission_for_* (IDOR) + admissions_v2 reload
    # helpers preload lead/reviewer but NOT choices; _compute_frontend_fields
    # → _validate_scores + submit-perm + _compute_completion_percent now read
    # profile.choices for multi-NV, and a lazy access from that sync code
    # raises MissingGreenlet. Inject the eager-loaded list as a *committed*
    # value (does NOT mark the instance dirty, does NOT re-lazy) so EVERY
    # mutation response (approve/reject/override/submit/v2 helpers) is covered
    # without touching each dependency. Skip when already loaded (GET paths
    # eager-load via _choices_eager_load_options).
    if getattr(profile, "uses_choice_engine", False):
        import sqlalchemy as _sa
        from sqlalchemy.orm.attributes import set_committed_value

        if "choices" in _sa.inspect(profile).unloaded:
            from app.repositories.admission_profile_choice_repository import (
                AdmissionProfileChoiceRepository,
            )
            _fresh_choices = await AdmissionProfileChoiceRepository(
                db
            ).list_by_profile(profile.id)
            set_committed_value(profile, "choices", _fresh_choices)

    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Populate transient score fields (average_score, total_score, snapshot_score,
    # admission_scores). _compute_frontend_fields → _validate_scores reads these
    # via direct attribute access and would AttributeError on a freshly DB-loaded
    # profile. Mirror update_profile's pattern: fetch fresh scores then compute.
    fresh_scores = await admission_repo.get_profile_scores(profile.id)
    _calculate_and_update_totals(profile, scores=fresh_scores)

    if documents is None:
        documents = await admission_repo.get_all_documents(profile.id)

    # ADM-031 round 10: resolve verifier display names in a single batched
    # SELECT so the documents_checklist response carries verified_by_name
    # without N+1.
    verifier_names = await _resolve_verifier_names(db, documents)
    _compute_frontend_fields(profile, current_user, documents, verifier_names)

    # Refine the tentative minor_correction permission flag against the
    # live AdmissionPath allowlist. Must run AFTER _compute_frontend_fields
    # since it reads profile.permissions and writes available_actions.
    await _resolve_minor_correction_state(db, profile, current_user)

    # Q9 #07 Phase E.4 — workbench audit timeline.
    # Last 20 priority_audit_log rows DESC, JOIN user để denormalize
    # actor_name. Empty list khi profile chưa có intervention nào.
    profile.priority_audit_log = await _load_priority_audit_log(db, profile.id)

    # Q9 #07 Phase E.4 — 3 priority evidence transient projections:
    # priority_object_evidence_display (enriched), missing_priority_evidence_codes
    # (Decision #2 inline warning), priority_evidence_documents (G0a DocumentsTab).
    # G2 defensive: helper wraps each compute in try/except → no crash if
    # documents lazy-load fails.
    await _populate_priority_evidence_projections(db, profile, documents)

    # TUITION_PREPAY_FASTTRACK finding #1 — flag học phí trả trước chưa hoàn
    # khi hồ sơ đã rejected/withdrawn (giữ-chỗ rồi từ chối/rút). Parity:
    # also set on the GET path (``get_profile``) which does NOT call this
    # helper — keep both in lockstep.
    await _populate_unrefunded_payment_flag(db, profile)


async def _populate_unrefunded_payment_flag(
    db: AsyncSession,
    profile: models.AdmissionProfile,
) -> None:
    """Set transient ``has_unrefunded_payment`` for the FE warning badge.

    A profile can be charged + collect a PREPAID tuition while ``submitted``
    (hold-spot flow). If it is later ``rejected`` (manager) or ``withdrawn``
    (candidate) — both valid from ``submitted`` — any money already collected
    becomes orphaned: it is NOT auto-refunded and is easy to forget. This flag
    lets ops see "cần hoàn tiền" on the detail page (refund stays manual via
    the existing maker-checker flow).

    ``SUM(fee.paid_amount)`` is the currently-HELD amount: a processed refund
    decrements ``paid_amount`` (``payment_service.process_approved_refund``),
    so the sum is exactly the unrefunded balance.

    Cost guard: ONLY queries when ``status in (rejected, withdrawn)``; every
    other status short-circuits to ``False`` with no DB hit. Idempotent — safe
    to call from both ``_populate_response_fields`` (mutations) and
    ``get_profile`` (GET detail) for parity.
    """
    if profile.status not in ("rejected", "withdrawn"):
        profile.has_unrefunded_payment = False
        return

    from app.repositories.fee_repository import FeeRepository

    total_paid = await FeeRepository(db).sum_paid_amount_by_profile(profile.id)
    profile.has_unrefunded_payment = total_paid > 0


async def _load_priority_audit_log(
    db: AsyncSession,
    profile_id: int,
    limit: int = 20,
) -> list[Dict[str, Any]]:
    """Load most recent priority_audit_log rows for the workbench timeline.

    LEFT JOIN with `user` so SET NULL on actor (account deleted) still keeps
    the audit row visible — actor_name resolves to None instead of dropping
    the row.

    Returns a list of dicts matching the `PriorityAuditEntry` schema shape so
    Pydantic's `from_attributes` can serialize directly from a transient
    attribute without persisting another ORM hop.
    """
    stmt = (
        select(
            models.PriorityAuditLog.id,
            models.PriorityAuditLog.action_type,
            models.PriorityAuditLog.actor_id,
            models.User.full_name.label("actor_name"),
            models.PriorityAuditLog.old_value,
            models.PriorityAuditLog.new_value,
            models.PriorityAuditLog.audit_metadata,
            models.PriorityAuditLog.created_at,
        )
        .select_from(models.PriorityAuditLog)
        .outerjoin(
            models.User,
            models.User.id == models.PriorityAuditLog.actor_id,
        )
        .where(models.PriorityAuditLog.profile_id == profile_id)
        .order_by(models.PriorityAuditLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [dict(row._mapping) for row in result.all()]


async def _create_admission_milestone_consultation(
    db: AsyncSession,
    lead: models.Lead,
    event: str,
    actor: Optional[models.User] = None,
    profile_id: Optional[int] = None,
    student_code: Optional[str] = None,
    reason: Optional[str] = None,
    fallback_officer_id: Optional[int] = None,
) -> None:
    """
    Create system consultation record for admission milestone.

    Following the Golden Rule:
    🔒 No Admission Event may occur without:
        1. Being tied to a Consultation Status
        2. Being tied to a Pipeline Stage
        3. Creating a Consultation record (even if SYSTEM-generated)

    This function:
    1. Looks up the event projection from ADMISSION_EVENT_PROJECTIONS
    2. Creates a SYSTEM consultation record
    3. Updates lead.pipeline_stage_id and lead.consultation_status_id
    4. Syncs lead.status via sync_lead_status_from_consultation()
    5. Logs state change to lead_status_history

    Args:
        db: Database session
        lead: Lead object to update
        event: Admission event identifier (e.g., "profile_submitted")
        actor: User who triggered the event (for audit trail)
        profile_id: Optional admission profile ID (for note template)
        student_code: Optional student code (for enrollment event)
        reason: Optional reason (for rejection/override events)

    Raises:
        ValueError: If event not found in ADMISSION_EVENT_PROJECTIONS

    Note:
        - This function does NOT commit - caller must commit
        - Respects terminal state guard (won't overwrite "converted" unless allowed)
        - Creates consultation with method="system" for filtering
    """
    from ..core.admission_event_mapping import validate_projection
    from ..core.status_mapping import sync_lead_status_from_consultation
    from .lead_service import _log_lead_state_change, _get_current_lead_state

    # Get canonical projection for this event
    projection = validate_projection(event)

    # Terminal state guard: Skip if lead already converted (unless allowed)
    if projection.skip_if_converted and lead.status == "converted":
        log.warning(
            "Skipping admission milestone consultation: lead already converted",
            lead_id=lead.id,
            admission_event=event,
            current_status="converted",
            attempted_stage=projection.pipeline_stage_id,
            attempted_status=projection.consultation_status_id,
        )
        return

    # SL1 regression guard: on a submit/resubmit milestone for a lead that
    # already carries a finance overlay (prepay application fee → sts13, or the
    # HK1 tuition lifecycle → sts14/sts10/sts18), we STILL record the milestone
    # consultation below (Golden Rule audit + consultation_count) but must NOT
    # downgrade the lead pipeline back to sts07 ("Đã tiếp nhận"). This helper is
    # the CANONICAL lead writer on submit (it runs before the officer-independent
    # sync_lead_from_admission fallback), so the guard MUST live here — the sync
    # guard alone is a no-op on the officer path because the lead would already
    # be at sts07 by the time sync runs. Other events (approve/reject/enroll/...)
    # are legitimate progressions and are intentionally NOT preserved.
    from .lead_admission_sync import (
        SUBMIT_FLOOR_EVENTS,
        FEE_OVERLAY_LEAD_STATUSES,
    )
    preserve_lead_overlay = (
        event in SUBMIT_FLOOR_EVENTS
        and lead.consultation_status_id in FEE_OVERLAY_LEAD_STATUSES
    )

    # Capture old state for history logging
    old_state = _get_current_lead_state(lead)

    # Load consultation status object for sync
    consultation_status = await db.get(models.ConsultationStatus, projection.consultation_status_id)
    if not consultation_status:
        log.error(
            "ConsultationStatus not found for admission event",
            admission_event=event,
            consultation_status_id=projection.consultation_status_id,
        )
        raise ResourceNotFoundError(
            f"Consultation status {projection.consultation_status_id} not found. "
            f"Please check consultation_status.csv seeding."
        )

    # Build consultation note from template
    note_template = projection.system_note_template
    note = note_template.format(
        profile_id=profile_id or "N/A",
        student_code=student_code or "N/A",
        reason=reason or "N/A"
    )

    # Create SYSTEM consultation record
    # Resolution order: actor > lead.assigned_officer > fallback_officer_id
    officer_id = (
        actor.id if actor
        else lead.assigned_officer_id
        or fallback_officer_id
    )
    if officer_id is None:
        # Graceful skip: the magic-link confirm path is applicant-driven; we
        # must not fail their request because an internal ownership field is
        # empty. Ops needs a loud warning to go triage the orphan lead.
        # Every other caller of this helper has either an `actor` or an
        # `assigned_officer_id`, so in practice this only fires during the
        # confirm flow when the lead was approved without an officer assigned.
        log.warning(
            "Skipping admission milestone consultation: no officer resolvable. "
            "Lead pipeline stage/status not synced for this event — ops must "
            "assign an officer and re-sync manually.",
            lead_id=lead.id,
            lead_status=lead.status,
            lead_assigned_officer_id=lead.assigned_officer_id,
            profile_id=profile_id,
            admission_event=event,
            actor_user_id=actor.id if actor else None,
            fallback_officer_id=fallback_officer_id,
        )
        return
    system_consultation = models.Consultation(
        lead_id=lead.id,
        officer_id=officer_id,
        consultation_status_id=projection.consultation_status_id,
        consultation_date=datetime.now(timezone.utc),
        method="system",  # ✅ Special marker for auto-generated records
        notes=note,
        duration_minutes=0,  # System consultations have no duration
    )
    db.add(system_consultation)

    if preserve_lead_overlay:
        # Milestone recorded for audit, but the lead keeps its finance overlay
        # (sts13/sts14/sts10/sts18) — do NOT downgrade it to the submit status.
        log.info(
            "SL1 guard: recorded submit milestone but preserved lead finance "
            "overlay (not downgrading to sts07)",
            lead_id=lead.id,
            admission_event=event,
            preserved_status=lead.consultation_status_id,
            milestone_status=projection.consultation_status_id,
            profile_id=profile_id,
        )
        return

    # Update lead pipeline (stage + status)
    lead.consultation_status_id = projection.consultation_status_id
    lead.pipeline_stage_id = projection.pipeline_stage_id

    # Sync lead.status from consultation_status (Hybrid Approach)
    sync_lead_status_from_consultation(lead, consultation_status)

    # Update lead timestamp
    lead.updated_at = datetime.now(timezone.utc)

    # Log state change to lead_status_history
    new_state = _get_current_lead_state(lead)
    await _log_lead_state_change(
        db=db,
        lead=lead,
        old_state=old_state,
        new_state=new_state,
        changed_by=actor,
        reason=f"Admission event: {event}",
    )

    log.info(
        "Admission milestone consultation created",
        lead_id=lead.id,
        admission_event=event,
        stage_id=projection.pipeline_stage_id,
        stage_name=projection.stage_name,
        status_id=projection.consultation_status_id,
        status_name=projection.consultation_name,
        profile_id=profile_id,
        actor_id=actor.id if actor else None,
    )


def _extract_allowed_subject_codes(admission_path) -> List[str]:
    """
    Extract flat list of all allowed subject codes from criteria's subject groups.

    Critical for applied_rules snapshot to ensure deterministic scoring.
    Returns sorted list of unique subject codes from ALL linked subject groups.

    Args:
        admission_path: AdmissionPath object with loaded criteria and subject_group_mappings

    Returns:
        Sorted list of subject codes (e.g., ["chemistry", "english", "math", "physics"])

    Example:
        >>> path = get_admission_path_with_relations(path_id=1)
        >>> _extract_allowed_subject_codes(path)
        ["chemistry", "english", "literature", "math", "physics"]
    """
    if not admission_path or not admission_path.criteria:
        log.warning(
            "Cannot extract subject codes: admission_path or criteria is None",
            path_id=admission_path.id if admission_path else None,
        )
        return []

    subject_codes = set()
    for mapping in admission_path.criteria.subject_group_mappings:
        if mapping.subject_group:
            for group_mapping in mapping.subject_group.subject_mappings:
                if group_mapping.subject:
                    subject_codes.add(group_mapping.subject.code)

    return sorted(list(subject_codes))


def _serialize_subject_groups(admission_path) -> List[Dict[str, Any]]:
    """
    Serialize subject groups for audit trail in applied_rules.

    Preserves the original group structure for compliance and debugging.

    **Backward-compat contract (PR6 Step 1, 2026-04-19):**
    - `subjects` stays a flat list of codes — existing clients keep working.
    - `weights` is a NEW parallel field: `{subject_code: coefficient}`.
      Default 1.0 per subject = no-op (plain sum). The weighted scoring
      logic that consumes these values will land in PR6 Step 2.

    Args:
        admission_path: AdmissionPath object with loaded criteria and subject_group_mappings

    Returns:
        List of subject group dictionaries with code, name, subjects, weights.

    Example:
        >>> _serialize_subject_groups(path)
        [
            {
                "code": "A00",
                "name": "Toán - Lý - Hóa",
                "subjects": ["math", "physics", "chemistry"],
                "weights": {"math": 2.0, "physics": 1.0, "chemistry": 1.0},
            },
            {
                "code": "D01",
                "name": "Toán - Văn - Anh",
                "subjects": ["math", "literature", "english"],
                "weights": {"math": 1.0, "literature": 1.0, "english": 1.0},
            }
        ]
    """
    if not admission_path or not admission_path.criteria:
        log.warning(
            "Cannot serialize subject groups: admission_path or criteria is None",
            path_id=admission_path.id if admission_path else None,
        )
        return []

    groups = []
    for mapping in admission_path.criteria.subject_group_mappings:
        if mapping.subject_group:
            # Preserve ordered iteration (SubjectGroup.subject_mappings is
            # already ordered by position via the relationship config).
            subject_mappings = [
                m for m in mapping.subject_group.subject_mappings if m.subject
            ]
            groups.append({
                "code": mapping.subject_group.code,
                "name": mapping.subject_group.name,
                "subjects": [m.subject.code for m in subject_mappings],
                # Float conversion is intentional: applied_rules is a JSONB
                # snapshot; Decimal is not natively JSON-serializable and the
                # downstream audit / frontend consumers read plain numbers.
                "weights": {
                    m.subject.code: float(m.weight)
                    for m in subject_mappings
                },
            })

    return groups


def _merge_subject_weights(admission_path) -> Dict[str, float]:
    """Flatten per-subject weights across all subject groups of a path.

    Feeds the top-level ``applied_rules["subject_weights"]`` field that
    ``AdmissionScoringService.calculate_score`` reads at submit / re-score
    time. Keeping this parallel to the nested shape in
    ``_serialize_subject_groups`` lets the scoring engine look up weights
    with one dict access, without having to walk group structure.

    When a subject code appears in multiple groups of the same path
    (rare), the last group's weight wins. That's documented where this
    helper is called.

    Empty dict when the path has no criteria / groups — scoring falls
    back to plain sum (matches the no-retroactive guarantee).
    """
    if not admission_path or not admission_path.criteria:
        return {}

    merged: Dict[str, float] = {}
    for mapping in admission_path.criteria.subject_group_mappings:
        group = mapping.subject_group
        if not group:
            continue
        for m in group.subject_mappings:
            if m.subject:
                merged[m.subject.code] = float(m.weight)
    return merged


# ==============================================================================
# CRUD FUNCTIONS
# ==============================================================================

async def create_profile(
    db: AsyncSession,
    lead_id: int,
    admission_method_id: int,  # Required for relational AdmissionPath lookup
    admission_round_id: int,  # Round contract hardening (plan v4) — REQUIRED
    current_user: models.User,
    academic_year: int,  # Round contract hardening (plan v4) — REQUIRED
) -> models.AdmissionProfile:
    """
    Create new AdmissionProfile for a Lead.

    REFACTORED (Phase 2): Now uses AdmissionPath (relational) instead of JSONB.

    Workflow:
    1. Validate Lead exists and user has access (IDOR check)
    2. Check Lead has offering_id
    3. Check Lead doesn't already have admission_profile
    4. Find AdmissionPath for this offering + method
    5. Resolve documents via DocumentGroup (relational override logic)
    6. Build applied_rules snapshot from relational data
    7. Create AdmissionProfile with status='draft'

    Security:
    - IDOR: Lead.unit_id must equal current_user.unit_id
    - Business Rule: AdmissionPath must exist and be active
    - Uniqueness: Lead can only have one admission_profile

    Args:
        db: Database session
        lead_id: Lead ID
        admission_method_id: Admission method ID (e.g., hoc_ba, thpt)
        current_user: Current authenticated user

    Returns:
        Created AdmissionProfile

    Raises:
        ResourceNotFoundError: Lead, ProgramOffering, or AdmissionPath not found
        ResourceNotFoundError: User doesn't have access to this lead (IDOR protection)
        BadRequest: Lead already has profile, or path not active
    """
    # ✅ SPRINT 6: Use Repository for lead lookup
    from app.repositories import AdmissionRepository, OrganizationRepository
    from app.repositories.admission_path_repository import AdmissionPathRepository
    from app.services.admission_path_service import AdmissionPathService
    
    admission_repo = AdmissionRepository(db)
    org_repo = OrganizationRepository(db)
    path_repo = AdmissionPathRepository(db)
    path_service = AdmissionPathService(db)

    # Step 1: Get Lead with eager loading (prevent N+1)
    lead = await admission_repo.get_lead_with_offering(lead_id)

    if not lead:
        log.warning("Lead not found", lead_id=lead_id, user_id=current_user.id)
        raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

    # Step 2: IDOR Check (3-tier)
    if current_user.role != UserRole.ADMIN:
        if lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: User tried to create profile for lead in different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                lead_id=lead_id,
                lead_unit_id=lead.unit_id,
            )
            raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")

        # C1: Officer-level IDOR — block creating profile for lead assigned to another officer
        if current_user.role == UserRole.OFFICER:
            if lead.assigned_officer_id and lead.assigned_officer_id != current_user.id:
                log.warning(
                    "IDOR attempt: Officer tried to create profile for lead assigned to another officer",
                    user_id=current_user.id,
                    lead_id=lead_id,
                    assigned_officer_id=lead.assigned_officer_id,
                )
                raise ResourceNotFoundError(f"Lead with ID {lead_id} not found")
            # Auto-assign officer if NULL and same unit
            if lead.assigned_officer_id is None:
                lead.assigned_officer_id = current_user.id

    # ✅ SPRINT 7 FIX: Concurrency Control
    # Prevent race conditions where multiple requests create duplicate profiles
    async with acquire_redis_lock(f"lock:create_profile:{lead_id}", timeout=5):
        # Double-check inside lock (idempotency)
        # We need to re-fetch or check relationship if session was refreshed, 
        # but since we are in same session transaction, checking the validation below is fine 
        # IF we trust the session sync. 
        # Better: Re-query specifically for existence check to be safe.
        
        # Fresh idempotency check inside lock (race-safe — DB query).
        #
        # Wave 4 #15b hotfix: Wave 3-E composite UNIQUE
        # (lead_id, academic_year) is the new uniqueness rule, so this
        # race-safe check must scope to the target year. Using the
        # deprecated ``get_profile_by_lead_id`` (which returns the latest
        # year regardless) would falsely block creating a profile for
        # year N+1 when the lead has a profile for year N.
        #
        # Round contract hardening (plan v4, 2026-05-25 — F30): academic_year
        # is now a REQUIRED parameter, so the race-safe check scopes directly
        # to it. The old ``current_intake_year`` SystemConfig fallback (used
        # when academic_year was Optional/None) is removed.
        existing_profile = await admission_repo.get_profile_by_lead_year(
            lead_id, academic_year
        )
        if existing_profile:
            raise ConflictError(
                f"Lead {lead_id} already has an admission profile for "
                f"academic year {academic_year}"
            )

    # Lead-level eligibility gate (SINGLE SOURCE OF TRUTH shared with GET /leads/{id}).
    # Checks: already_has_profile, invalid_lead_status, consultation_terminal,
    # missing_offering, no_consultation, consultation_missing_status,
    # consultation_universal_status.
    # Role check skipped — IDOR enforced upstream by get_lead_for_user dep.
    # Wave 4 #15b: pass academic_year so the composite (lead_id, academic_
    # year) UNIQUE swap (PR #223 squash 15f52c8e) lets a lead create a new
    # profile for a different year while still blocking duplicates within
    # the same year. ``academic_year`` parameter on this function is
    # Optional — None falls back to current_intake_year config below.
    eligibility = await check_lead_level_admission_eligibility(
        db, lead, current_user, check_role=False, academic_year=academic_year
    )
    if not eligibility.eligible:
        code = eligibility.blocker_code
        msg = eligibility.blocker_message
        log.warning(
            "Admission creation blocked at lead-level eligibility",
            lead_id=lead_id,
            blocker_code=code,
            user_id=current_user.id,
        )
        if code == "already_has_profile":
            raise ConflictError(f"Lead {lead_id} already has an admission profile")
        elif code == "missing_offering":
            raise BadRequest(msg)
        elif code == "invalid_lead_status":
            raise BusinessRuleViolation(
                f"Cannot create admission profile for lead with status '{lead.status}'. "
                f"Lead must be in active pipeline (new, assigned, contacted, qualified) or be re-engaged."
            )
        elif code == "consultation_terminal":
            # Lead consultation is_final (e.g. sts20) — closed, must be re-opened first.
            raise BusinessRuleViolation(msg)
        else:
            # no_consultation | consultation_missing_status | consultation_universal_status
            raise BusinessRuleViolation(msg)

    # Step 5: Validate offering exists
    if not lead.offering:
        log.error(
            "ProgramOffering not found (data integrity issue)",
            lead_id=lead_id,
            offering_id=lead.offering_id,
        )
        raise ResourceNotFoundError(
            f"Program offering {lead.offering_id} not found"
        )

    # Step 6: Get published OfferingAcademicInfo for the (offering, year).
    #
    # Round contract hardening (plan v4, 2026-05-25 — F30): academic_year
    # is now REQUIRED, so we always bind to the specific (offering, year)
    # row and require it to be published. The legacy "first published"
    # fallback (the old ``else`` branch when academic_year was None) is
    # removed — a deterministic year is needed to validate the selected
    # round below (round.academic_year == academic_year).
    academic_info_list = await org_repo.get_academic_info_history(
        lead.offering_id,
        published_only=False,
    )

    academic_info = next(
        (
            info
            for info in academic_info_list
            if info.academic_year == academic_year
        ),
        None,
    )
    if not academic_info:
        log.warning(
            "No academic info found for offering+academic_year",
            offering_id=lead.offering_id,
            academic_year=academic_year,
        )
        raise BadRequest(
            f"Không tìm thấy năm học {academic_year} cho chương trình "
            f"này (offering {lead.offering_id}). Vui lòng kiểm tra "
            "cấu hình năm học hoặc chọn năm khác."
        )
    if not academic_info.is_published:
        log.warning(
            "academic_year requested but not published",
            offering_id=lead.offering_id,
            academic_year=academic_year,
            academic_info_id=academic_info.id,
        )
        raise BadRequest(
            f"Năm học {academic_year} của chương trình này chưa "
            "được công bố tuyển sinh. Vui lòng chọn năm khác hoặc "
            "liên hệ admin để công bố."
        )

    # Step 6b: Validate the explicitly-selected admission round.
    #
    # Round contract hardening (plan v4 Section A): the round is now
    # REQUIRED + validated up front, BEFORE building applied_rules, so the
    # 3-col path lookup binds the profile to the exact (round, offering,
    # method) tuple — no silent fallback to DOT_1 via ``.first()``.
    # Validate (in order): exists → matches the requested academic_year →
    # active → not archived. INSERT happens later so this runs before the
    # applied_rules immutability trigger ever sees the row (F46 — safe).
    from app.repositories.admission_round_repository import (
        AdmissionRoundRepository,
    )

    round_repo = AdmissionRoundRepository(db)
    admission_round = await round_repo.get_by_id(admission_round_id)
    if admission_round is None:
        log.warning(
            "Admission round not found",
            admission_round_id=admission_round_id,
            lead_id=lead_id,
        )
        raise BadRequest(
            f"Đợt tuyển sinh (round_id={admission_round_id}) không tồn tại."
        )
    if admission_round.academic_year != academic_year:
        log.warning(
            "Admission round academic_year mismatch",
            admission_round_id=admission_round_id,
            round_year=admission_round.academic_year,
            requested_year=academic_year,
        )
        raise BadRequest(
            f"Đợt tuyển sinh '{admission_round.round_code}' thuộc năm "
            f"{admission_round.academic_year}, không khớp năm {academic_year} "
            "đã chọn. Vui lòng chọn đợt đúng năm."
        )
    if not admission_round.is_active:
        log.warning(
            "Admission round is inactive",
            admission_round_id=admission_round_id,
        )
        raise BadRequest(
            f"Đợt tuyển sinh '{admission_round.round_code}' đang tạm dừng "
            "(inactive). Vui lòng chọn đợt khác."
        )
    if admission_round.archived_at is not None:
        log.warning(
            "Admission round is archived",
            admission_round_id=admission_round_id,
            archived_at=str(admission_round.archived_at),
        )
        raise BadRequest(
            f"Đợt tuyển sinh '{admission_round.round_code}' đã lưu trữ. "
            "Vui lòng chọn đợt khác."
        )

    # PR-2 (2026-05-28) — Round cutoff enforcement (SPEC §2.1.a Rule 1).
    # Block create_profile khi end_date đã qua. Raise RoundClosedError → 410
    # Gone. Strict: KHÔNG grace period, KHÔNG admin override ngầm; admin
    # extends qua POST /rounds/{id}/extend separate endpoint.
    assert_round_open(
        admission_round,
        context_hint="Liên hệ admin nếu cần extend đợt.",
    )

    # Step 7: Find AdmissionPath for this (round, offering, method).
    #
    # Round contract hardening (plan v4 Section A): 3-col lookup replaces
    # the old 2-col ``get_path_by_offering_and_method`` + ``.first()``,
    # which silently picked an arbitrary round (DOT_1 vs DOT_2) when both
    # existed for the same (offering, year, method). The helper eager-loads
    # admission_round so ``uses_choice_engine`` below reads
    # ``allow_multi_nv`` deterministically.
    admission_path = await path_repo.get_path_by_round_and_method(
        admission_round_id=admission_round_id,
        academic_info_id=academic_info.id,
        admission_method_id=admission_method_id,
    )

    if not admission_path:
        log.warning(
            "No admission path configured for round + offering + method",
            admission_round_id=admission_round_id,
            academic_info_id=academic_info.id,
            admission_method_id=admission_method_id,
        )
        raise BadRequest(
            f"Không có đường tuyển sinh (path) cấu hình cho đợt "
            f"'{admission_round.round_code}', năm {academic_year}, "
            f"phương thức (method_id={admission_method_id}). Vui lòng cấu "
            "hình đường tuyển sinh ở Admission Config trước khi tạo hồ sơ."
        )

    # ✅ FIX Finding 1.2: Check if Admission Method is Active
    # We need to access the admission_method relation from the path
    # Assuming path.admission_method is eager loaded in repository or exists
    # If not loaded, we rely on the repository ensuring it returns valid paths,
    # but explicit check is safer.
    # Since get_path_by_round_and_method eager-loads admission_method, we check here.
    if admission_path.admission_method and not admission_path.admission_method.is_active:
         log.warning(
            "Attempt to create profile with inactive admission method",
            method_id=admission_method_id,
            is_active=admission_path.admission_method.is_active
        )
         raise BadRequest(
            f"Phương thức tuyển sinh '{admission_path.admission_method.name}' đang tạm dừng hoặc không hoạt động."
        )

    # ✅ FIX Finding 1.2 (Strict): Validate Academic Year consistency (Lead Match Logic)
    # Ensure the profile created belongs to the same academic year as the Lead's recruitment cycle
    # Lead -> Offering -> AcademicInfo (from lead.offering_id)
    # Profile -> Path -> AcademicInfo
    # In this function, we derived path FROM lead's offering academic_info, so by definition they match.
    # However, if Lead has an explicit 'academic_year' field (denormalized), we shout compare.
    # Currently Lead model doesn't show 'academic_year', it links to Offering.
    # So the check `academic_info.id == lead.offering.current_academic_info_id` is implicit in Step 6 logic.
    
    # We add a guard to ensure we are not creating a profile for a PAST year if the lead is new
    # But since we use get_academic_info_history(published_only=False), we might pick an old one?
    # Step 6 logic: `info.is_published` -> likely the current active one.
    
    # Let's enforce that the selected academic_info is indeed the CURRENT one for the offering
    # unless specific override logic exists.
    if not academic_info.is_published:
         # Warn if creating profile for unpublished/draft academic year
         log.warning("Creating profile for unpublished academic year", academic_info_id=academic_info.id)
    else:
        # Check if year is closed? (Assuming 'is_active' or similar flag exists, or relying on published)
        pass

    if admission_path.status != "active":
        log.warning(
            "Admission path is not active",
            path_id=admission_path.id,
            path_status=admission_path.status,
        )
        raise BadRequest(
            f"Admission path is not active (status: {admission_path.status}). "
            "Only active paths can be used for profile creation."
        )

    # Step 8: Check offering_type_id for document resolution
    offering_type_id = lead.offering.offering_type_id
    if not offering_type_id:
        log.warning(
            "Program offering has no offering_type_id",
            offering_id=lead.offering_id,
        )
        raise BadRequest(
            f"Program offering {lead.offering_id} has no offering_type_id configured. "
            "Please run backfill script or configure offering type."
        )

    # Step 9: Resolve documents using DocumentGroup (relational override logic)
    resolved_docs, _ = await path_service.resolve_documents_for_path(
        path=admission_path,
        offering_type_id=offering_type_id
    )

    # Step 10: Build mandatory_docs from resolved documents
    mandatory_docs = [
        doc.document_type_code 
        for doc in resolved_docs 
        if doc.is_mandatory
    ]

    # Step 11: Load AdmissionPath with criteria (eager load)
    full_path = await path_repo.get_by_id_with_relations(admission_path.id)
    
    # Step 12: Build applied_rules from relational data (SNAPSHOT)
    # ✅ CRITICAL FIX: Complete snapshot with ALL scoring parameters
    # Per ADMISSION_PROCESSING_FLOW_ANALYSIS.md Section 6.1
    applied_rules = {
        # =========================================================================
        # GROUP 1: Basic Criteria (from AdmissionCriteria)
        # =========================================================================
        "min_gpa": float(full_path.criteria.min_gpa) if full_path and full_path.criteria and full_path.criteria.min_gpa is not None else None,
        "min_score": float(full_path.criteria.min_score) if full_path and full_path.criteria and full_path.criteria.min_score is not None else None,

        # =========================================================================
        # GROUP 2: Scoring Configuration (CRITICAL - was missing!)
        # =========================================================================
        # How to select subjects: "fixed" | "best_n" | "any_n"
        "subject_selection_mode": full_path.criteria.subject_selection_mode if full_path and full_path.criteria else "fixed",

        # How to calculate score: "sum" | "average" | "weighted"
        "scoring_method": full_path.criteria.scoring_method if full_path and full_path.criteria else "sum",

        # Number of subjects required (1, 2, 3, or None for flexible)
        "required_subject_count": full_path.criteria.required_subject_count if full_path and full_path.criteria else None,

        # Minimum score per subject (điểm liệt)
        "min_subject_score": float(full_path.criteria.min_subject_score) if full_path and full_path.criteria and full_path.criteria.min_subject_score is not None else None,

        # Maximum possible score (for display/normalization)
        "max_possible_score": float(full_path.criteria.max_possible_score) if full_path and full_path.criteria and full_path.criteria.max_possible_score is not None else None,

        # =========================================================================
        # GROUP 3: Subject Validation (CRITICAL - was missing!)
        # =========================================================================
        # Flat list of ALL allowed subject codes (for input validation)
        "allowed_subject_codes": _extract_allowed_subject_codes(full_path),

        # Original subject groups (for audit trail and fixed mode)
        "subject_groups": _serialize_subject_groups(full_path),

        # PR6 Step 2 (2026-04-19): top-level per-subject weight map. Frozen
        # at profile creation so later edits to SubjectGroupSubject.weight
        # don't retroactively re-score this profile. The nested
        # subject_groups[*].weights field above is for audit display;
        # this top-level field is what the scoring engine actually reads
        # at submit/re-score time (see _evaluate_admission_profile).
        #
        # Merge order across groups: last group wins on duplicate subject
        # codes. In the vast majority of configs, each allowed subject
        # appears in only one group of a given path anyway.
        "subject_weights": _merge_subject_weights(full_path),


        # =========================================================================
        # GROUP 4: Method Metadata (Updated Ticket #3)
        # =========================================================================
        "admission_method": admission_path.admission_method.code if admission_path.admission_method else None,
        "admission_method_id": admission_method_id,
        # Ticket #3: Explicit method type derivation
        # If no subject groups mapped -> "gpa_only" (Hoc ba 3 years)
        # If subject groups exist -> "subject_based" (Hoc ba 3 semesters / THPT / DGNL)
        "method_type": "subject_based" if full_path.criteria and full_path.criteria.subject_group_mappings else "gpa_only",

        # =========================================================================
        # GROUP 5: Document Requirements (Updated Ticket #4)
        # =========================================================================
        "mandatory_docs": mandatory_docs,
        "doc_configs": {
            doc.document_type_code: {
                "requires_upload": doc.requires_upload,
                "submission_format": doc.submission_format,
                "is_mandatory": doc.is_mandatory,
                "label": doc.document_type_name,
            }
            for doc in resolved_docs
        },
        # Ticket #4: Upload Configuration
        "upload_config": DEFAULT_UPLOAD_CONFIG,

        # =========================================================================
        # GROUP 6: Application Fee Configuration
        # =========================================================================
        "application_fee": float(admission_path.application_fee) if admission_path.application_fee else 0,
        "requires_application_fee": admission_path.requires_application_fee,
        "fee_status": "exempt" if not admission_path.requires_application_fee else "pending",
        # fee_status values: "exempt" (miễn phí), "pending" (chờ thanh toán), "paid" (đã thanh toán)

        # =========================================================================
        # GROUP 7: Metadata
        # =========================================================================
        "snapshot_source": "relational",
        "admission_path_id": admission_path.id,
        # Phase 2 v8.2 PR-2B v2 — snapshot admission_round_id từ path
        # để engine + cross-round queries không phải JOIN lại. Backfill
        # migration phase2_02_v2 đã populate cho legacy profiles.
        "admission_round_id": admission_path.admission_round_id,
        "academic_info_id": academic_info.id,
        # PR #6 — snapshot the path-level flag so later admin changes to
        # the path don't retroactively block (or unblock) submissions
        # for profiles created under the old rule. schema_version=2
        # marks the profile as post-migration; legacy profiles were
        # backfilled with schema_version=1 + flag=true by the alembic
        # revision aa1i2j3k4l5m.
        "schema_version": 2,
        "allow_unverified_submission": bool(
            getattr(admission_path, "allow_unverified_submission", False)
        ),

        # =====================================================================
        # GROUP 8: phase1_03 / phase1_02 wired (#184 Wave 1 PR-1B')
        # =====================================================================
        # Snapshot the audience filter + per-method quota + bonus rule
        # override at profile creation so later admin changes to the path
        # don't retroactively re-classify or re-cap profiles already in
        # flight. Read sites: scoring engine (bonus_rule_override
        # precedence), quota guard (method_quota tier-3 — Phase 2),
        # storefront audience filter (applicable_to legacy NULL fallback).
        # NULL passes through as None so consumers can rely on the
        # ``getattr`` / ``.get()`` is-None contract instead of probing
        # presence.
        "applicable_to": list(admission_path.applicable_to)
        if getattr(admission_path, "applicable_to", None)
        else None,
        "method_quota": getattr(admission_path, "method_quota", None),
        "bonus_rule_override": getattr(admission_path, "bonus_rule_override", None),
    }



    # Step 13: Validate applied_rules has content
    if not mandatory_docs and not applied_rules.get("min_gpa") and not applied_rules.get("min_score"):
        log.warning(
            "Admission path has no criteria or documents configured",
            path_id=admission_path.id,
        )
        # Allow profile creation but log warning (path might be minimal config)

    # Step 14: Determine academic_year
    academic_year = academic_info.academic_year
    
    log.info(
        "Creating profile with relational AdmissionPath",
        lead_id=lead_id,
        academic_year=academic_year,
        admission_path_id=admission_path.id,
        admission_method_id=admission_method_id,
        mandatory_docs_count=len(mandatory_docs),
    )
    
    # Step 14b: Lookup offering_admission_config for this path
    offering_config_id = None
    if admission_path.criteria_id:
        from sqlalchemy import select as sa_select
        oac_result = await db.execute(
            sa_select(models.OfferingAdmissionConfig.id).where(
                models.OfferingAdmissionConfig.academic_info_id == academic_info.id,
                models.OfferingAdmissionConfig.criteria_id == admission_path.criteria_id,
                models.OfferingAdmissionConfig.is_active == True,
            )
        )
        oac_row = oac_result.scalars().first()
        if oac_row:
            offering_config_id = oac_row

    # Phase 3 close-out 2026-05-14 — Q-P3-02 inherit multi-NV mode from
    # the round on profile creation. The DB column was added by
    # phase3_01 with server_default=false but no service path was
    # writing the True branch, so every new profile defaulted to
    # legacy single-NV regardless of round configuration. Round flag is
    # eager-loaded on ``admission_path.admission_round`` via the path
    # repository so no extra SELECT here.
    #
    # Fallback chain:
    #   round present + flag True  → True (Phase 3 multi-NV mode)
    #   round present + flag False → False (legacy preserved)
    #   round missing (data drift) → False (safe default, matches DB)
    inherit_multi_nv: bool = bool(
        getattr(getattr(admission_path, "admission_round", None), "allow_multi_nv", False)
    )

    # Step 15: Create AdmissionProfile
    new_profile = models.AdmissionProfile(
        lead_id=lead_id,
        academic_year=academic_year,
        status="draft",
        applied_rules=applied_rules,  # Snapshot from relational data
        family_info=[],
        academic_history=[],
        offering_admission_config_id=offering_config_id,
        uses_choice_engine=inherit_multi_nv,
        # Pre-fill from Lead
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
    )

    db.add(new_profile)
    try:
        await db.flush()  # Get ID without committing (router commits)
    except IntegrityError as e:
        log.error("IntegrityError during profile creation (race condition)", error=str(e))
        raise ConflictError(f"Lead {lead_id} already has an admission profile (detected at DB layer)")

    # Initial state row — Phase 1 PLAN line 1067 service contract:
    # every profile creation emits one ``NULL → draft`` row into
    # ``admission_profile_status_history``. This is the runtime
    # counterpart to the phase1_10 backfill which seeded one
    # initial-state row per pre-existing profile at migration time;
    # without this writer the audit trail would silently flat-line
    # the moment phase1_10 ships.
    from ..models.admission_profile_status_history import (
        AdmissionProfileStatusHistory,
    )
    from ..services.admission_state_service import (
        _resolve_status_history_actor,
    )

    initial_actor_fields = _resolve_status_history_actor(
        actor=current_user,
        source="api",
        profile_lead_id=new_profile.lead_id,
    )
    db.add(
        AdmissionProfileStatusHistory(
            profile_id=new_profile.id,
            from_status=None,  # NULL = initial state per model docstring
            to_status="draft",
            transition_reason=None,
            occurred_at=new_profile.created_at,
            metadata_={"source": "api", "initial_create": True},
            **initial_actor_fields,
        )
    )

    # Audit trail: log profile creation
    from ..services import audit_service
    await audit_service.log_created(
        db, "AdmissionProfile", new_profile.id,
        actor_user_id=current_user.id,
        new_values={"lead_id": lead_id, "status": "draft", "academic_year": new_profile.academic_year},
        source="api",
    )

    # Step 16: Initialize ProfileDocument records
    # Materialize a row for EVERY doc in the path snapshot (mandatory +
    # optional), not just ``mandatory_docs``. The GET response builds the
    # ``documents_checklist`` from the full ``doc_configs`` keyset (PR #394),
    # so an optional doc (``is_mandatory=false``, e.g. ``giay_xac_nhan_cu_tru``
    # / ``giay_kham_suc_khoe``) surfaces with a "Xác nhận bản giấy" action
    # button. Without a row, ``paper-submitted`` has nothing to update → 404,
    # and ``upload`` silently no-ops (orphan file). Materializing all path docs
    # restores the invariant "every doc_configs key ⇒ one category='path'
    # ProfileDocument row". Optional rows stay ``status=missing`` and never
    # block submit (``_validate_documents`` filters by ``mandatory_docs``).
    # Use the ``doc_configs`` keyset directly (not a list over ``resolved_docs``)
    # — it is the exact set GET renders, is inherently de-duplicated (dict
    # keys), and keeps this site symmetric with ``_reresolve_documents_snapshot``
    # (both feed the materializer ``list(doc_configs.keys())``).
    await admission_repo.initialize_documents_for_profile(
        profile_id=new_profile.id,
        document_type_codes=list(applied_rules["doc_configs"].keys()),
    )

    # Step 17: Reload with relationships for response
    new_profile = await admission_repo.reload_profile_with_lead(new_profile.id)

    # Populate transient computed fields so the create response matches GET.
    # Without this, permissions={}, available_actions=[], validation_errors=[],
    # and assigned_officer_name=None leak to the client, breaking any frontend
    # that trusts the create response without re-fetching (MEDIUM #2 followup —
    # commit 1528bc89 fixed the 10 state-changing mutations but missed create).
    # reload_profile_with_lead already eager-loads documents + lead.assigned_officer
    # + assigned_reviewer + student + subject_scores, so pass the loaded documents
    # to avoid a redundant get_all_documents() query inside the helper. The helper
    # also calls _calculate_and_update_totals() internally, so we don't need a
    # separate call here.
    await _populate_response_fields(
        db, new_profile, current_user, documents=new_profile.documents
    )

    # ✅ SYNC: Update lead consultation status to match admission status
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=new_profile,
        changed_by_user_id=current_user.id,
        reason="Admission profile created",
    )

    log.info(
        "Admission profile created (relational flow)",
        profile_id=new_profile.id,
        lead_id=lead_id,
        user_id=current_user.id,
        snapshot_source="relational",
        admission_path_id=admission_path.id,
        mandatory_docs_count=len(mandatory_docs),
    )

    # ✅ PIPELINE SYNC: Create system consultation for admission milestone
    if new_profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=new_profile.lead,
            event=_PROFILE_CREATED_EVENT,
            actor=current_user,
            profile_id=new_profile.id,
        )

    return new_profile



async def get_profiles(
    db: AsyncSession,
    skip: int,
    limit: int,
    current_user: models.User = None,
    unit_id: Optional[int] = None,
    search: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Tuple[List[models.AdmissionProfile], int]:
    """
    Get filtered list of admission profiles with total count.

    Security:
    - IDOR: Automatically filters by unit_id for non-admin users.
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # IDOR: 3-tier filtering (Admin=all, Manager=unit, Officer=assigned+unit)
    unit_filter, officer_filter = _resolve_idor_filters(current_user) if current_user else (unit_id, None)

    # Get profiles using repository with count
    profiles, total_count = await admission_repo.get_filtered_with_count(
        skip=skip,
        limit=min(limit, 100),
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        search=search,
        statuses=statuses,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        order=order,
    )

    # ADM-031 round 10: pre-resolve verifier names ACROSS all profiles in
    # one SELECT so the listing endpoint stays free of N+1 even when many
    # rows have verified documents.
    list_verifier_names: Dict[int, str] = {}
    if current_user and profiles:
        all_docs: list = []
        for profile in profiles:
            if hasattr(profile, "documents") and profile.documents:
                all_docs.extend(profile.documents)
        if all_docs:
            list_verifier_names = await _resolve_verifier_names(db, all_docs)

    # Hydrate computed fields (same as detail API) using eager-loaded relations
    for profile in profiles:
        _calculate_and_update_totals(profile)
        # documents already loaded via selectinload in get_filtered_with_count
        docs = profile.documents if hasattr(profile, "documents") else None
        if current_user:
            _compute_frontend_fields(
                profile, current_user, docs, list_verifier_names
            )

    # Batch-resolve minor_correction state for the page in ONE query rather
    # than N path lookups. This keeps the list endpoint at exactly one
    # extra round-trip regardless of page size, and keeps
    # `permissions.minor_correction` + `minor_correction_fields` in sync
    # with what detail returns. See _resolve_minor_correction_state for
    # the per-row contract.
    if current_user and profiles:
        from app.repositories import AdmissionPathRepository
        path_ids = {
            (p.applied_rules or {}).get("admission_path_id")
            for p in profiles
        }
        path_ids.discard(None)
        paths = await AdmissionPathRepository(db).get_by_ids(path_ids)
        path_by_id = {p.id: p for p in paths}
        for profile in profiles:
            pid = (profile.applied_rules or {}).get("admission_path_id")
            _apply_minor_correction_state(profile, path_by_id.get(pid))

    return profiles, total_count


async def get_profiles_for_export(
    db: AsyncSession,
    current_user: models.User,
    search: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[models.AdmissionProfile]:
    """
    Get profiles for CSV export — no page cap, lightweight hydration.

    Only computes completion_percent (needed by CSV) via _calculate_and_update_totals.
    Skips full _compute_frontend_fields (permissions, actions, step_status, etc.).
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    profiles, _ = await admission_repo.get_filtered_with_count(
        skip=0,
        limit=10_000,  # export cap
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        search=search,
        statuses=statuses,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        sort_by="created_at",
        order="desc",
    )

    # Lightweight hydration: totals/GPA + completion_percent, no permissions/actions
    for profile in profiles:
        _calculate_and_update_totals(profile)
        docs = profile.documents if hasattr(profile, "documents") else None
        profile.completion_percent = _compute_completion_percent(profile, docs)

    return profiles


async def get_status_counts(
    db: AsyncSession,
    current_user: models.User,
    search: Optional[str] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    """Get status counts for admission profiles (all filters except status)."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    return await admission_repo.get_status_counts(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        search=search,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
    )


async def get_admission_stats(
    db: AsyncSession,
    current_user: models.User,
    academic_year: Optional[int] = None,
) -> dict:
    """Get aggregate statistics for admission profiles with computed avg_completion."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    stats = await admission_repo.get_aggregate_stats(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
        academic_year=academic_year,
    )

    # Compute avg_completion over ALL profiles in scope (no sampling)
    total = stats.get("total_profiles", 0)
    if total > 0:
        completion_sum = 0
        fetched = 0
        batch_size = 500
        while fetched < total:
            batch, _ = await admission_repo.get_filtered_with_count(
                skip=fetched,
                limit=batch_size,
                unit_id=unit_filter,
                assigned_officer_id=officer_filter,
                academic_year=academic_year,
            )
            if not batch:
                break
            for p in batch:
                _calculate_and_update_totals(p)
                docs = p.documents if hasattr(p, "documents") else None
                completion_sum += _compute_completion_percent(p, docs)
            fetched += len(batch)
        stats["avg_completion"] = round(completion_sum / fetched, 1) if fetched > 0 else 0.0

    return stats


async def get_academic_years(
    db: AsyncSession,
    current_user: models.User,
) -> List[int]:
    """Get distinct academic years for the current user's scope."""
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_filter, officer_filter = _resolve_idor_filters(current_user)

    return await admission_repo.get_distinct_academic_years(
        unit_id=unit_filter,
        assigned_officer_id=officer_filter,
    )


async def get_profile(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Get AdmissionProfile by ID.

    Security:
    - IDOR: Check lead.unit_id == user.unit_id (unless admin)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user

    Returns:
        AdmissionProfile with relationships loaded + computed frontend fields

    Raises:
        ResourceNotFoundError: Profile not found
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
    """
    # ✅ SPRINT 6: Use Repository for profile retrieval
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

    if not profile:
        log.warning("Admission profile not found", profile_id=profile_id)
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check
    _check_idor_access(profile, current_user)

    log.debug(
        "Admission profile retrieved",
        profile_id=profile_id,
        user_id=current_user.id,
        status=profile.status,
    )

    # Calculate totals for response
    _calculate_and_update_totals(profile)
    
    # =========================================================================
    # Phase 7: Compute Frontend Thin Client Fields
    # =========================================================================
    # Fetch documents for completion calculation
    documents = await admission_repo.get_all_documents(profile_id)
    _compute_frontend_fields(
        profile,
        current_user,
        documents,
        await _resolve_verifier_names(db, documents),
    )

    # Refine minor_correction permission against live AdmissionPath config
    # (governance setting, not snapshotted) — keeps detail in lockstep
    # with list endpoint resolver above.
    await _resolve_minor_correction_state(db, profile, current_user)

    # Q9 #07 Phase E.4 — projections on GET path (parity with mutation
    # endpoints via ``_populate_response_fields``). Without these calls
    # ``priority_evidence_documents`` returns [] even when the profile has
    # ``priority_object_codes`` set, breaking DocumentsTab Priority section +
    # PriorityWorkbench § 3 UT cards on every GET. Smoke 2026-05-20 caught
    # this gap — projection logic existed (line 2264) but only fired from
    # ``_populate_response_fields`` callers, leaving the read-side dark.
    profile.priority_audit_log = await _load_priority_audit_log(db, profile.id)
    await _populate_priority_evidence_projections(db, profile, documents)

    # Parity with mutation responses (reject/withdraw go through
    # ``_populate_response_fields``): GET detail builds via
    # ``_compute_frontend_fields`` directly, so set the unrefunded-payment
    # flag here too — otherwise GET would default it to False.
    await _populate_unrefunded_payment_flag(db, profile)

    return profile


async def _reresolve_documents_snapshot(
    db: AsyncSession,
    profile: "models.AdmissionProfile",
    admission_repo,
    current_user: Optional["models.User"],
) -> None:
    """Re-resolve doc snapshot khi cultural/vocational đổi (feat audience).

    Bối cảnh (round-2 P0-A): submit check ``mandatory_docs`` từ SNAPSHOT, không
    re-resolve; cultural set qua update_profile vốn không re-resolve. Nếu không
    re-resolve khi cultural đổi → snapshot stale (thiếu học bạ/bằng TN theo
    audience) → submit qua eligibility (cultural đã set) nhưng doc không bắt buộc
    = REGRESSION. Hook này đóng lỗ đó.

    - CHỈ editable states {draft, rejected, revision_requested} (ngoài đó gate
      chặn → đóng băng, không cần block riêng).
    - INSERT-only DELTA qua ``add_path_documents_delta`` (P0-B: không vi phạm
      ``uq_profile_document_path``; không xóa upload).
    - MERGE applied_rules PER-KEY (round-3 invariant): chỉ ghi đè
      ``mandatory_docs``/``doc_configs``, GIỮ ``schema_version``/
      ``allow_unverified_submission``/``admission_path_id``/scoring (submit
      :4974-4978 raise nếu thiếu). KHÔNG bump schema_version (round-4 N1).
    - CONFIG_GAP đã nuốt nội bộ trong ``derive_audience_set`` (round-3 BLOCKER)
      → luôn ≥ tập văn hóa. Lỗi BẤT NGỜ (DB...) PROPAGATE (loud-fail) — KHÔNG
      im lặng giữ snapshot NỀN-only.
    - N5: ghi audit entry ``documents_reresolved`` (mutate snapshot không vào
      ``updated_fields`` của update_profile).
    """
    if profile.status not in ("draft", "rejected", "revision_requested"):
        return
    applied = profile.applied_rules or {}
    path_id = applied.get("admission_path_id")
    if path_id is None:
        return  # legacy / hồ sơ không có path snapshot → bỏ qua

    from .admission_path_service import AdmissionPathService
    from ..repositories.admission_path_repository import AdmissionPathRepository

    path = await AdmissionPathRepository(db).get_path_for_audience_reresolve(
        int(path_id)
    )
    if path is None or path.academic_info is None or path.academic_info.offering is None:
        return
    offering_type_id = path.academic_info.offering.offering_type_id
    if offering_type_id is None:
        return

    resolved, _ = await AdmissionPathService(db).resolve_documents_for_profile(
        profile, path, offering_type_id
    )
    new_mandatory = [d.document_type_code for d in resolved if d.is_mandatory]
    new_doc_configs = {
        d.document_type_code: {
            "requires_upload": d.requires_upload,
            "submission_format": d.submission_format,
            "is_mandatory": d.is_mandatory,
            "label": d.document_type_name,
        }
        for d in resolved
    }

    # Micro-opt: snapshot KHÔNG đổi (PATCH cultural set lại cùng giá trị, hoặc
    # audience không đổi bộ hồ sơ) → skip write/delta/audit. resolved.sort theo
    # display_order → list deterministic, so sánh list/dict an toàn.
    if new_mandatory == (applied.get("mandatory_docs") or []) and (
        new_doc_configs == (applied.get("doc_configs") or {})
    ):
        return

    old_mandatory = set(applied.get("mandatory_docs") or [])
    # Capture old keyset (mandatory + optional) BEFORE overwrite — the audit
    # below tracks the FULL doc_configs delta, not just mandatory.
    old_doc_codes = set((applied.get("doc_configs") or {}).keys())

    # MERGE per-key (giữ mọi key khác — KHÔNG gán dict mới).
    applied["mandatory_docs"] = new_mandatory
    applied["doc_configs"] = new_doc_configs
    profile.applied_rules = applied
    flag_modified(profile, "applied_rules")

    # DELTA INSERT ProfileDocument cho MỌI doc trong snapshot mới (mandatory +
    # optional), idempotent, không xóa upload. PHẢI dùng full doc_configs
    # keyset — KHÔNG chỉ ``new_mandatory`` — để optional doc cũng có row; nếu
    # không, paper-submitted/upload trên optional doc sẽ 404 / no-op (cùng
    # invariant với bước Initialize lúc tạo hồ sơ).
    await admission_repo.add_path_documents_delta(
        profile.id, list(new_doc_configs.keys())
    )

    # N5 — audit entry cho mutate snapshot. Tính delta trên TOÀN BỘ doc_configs
    # keyset (mandatory + optional), KHÔNG chỉ mandatory: delta INSERT giờ
    # materialize cả optional row, nên một thay đổi CHỈ-optional (thêm/bớt giấy
    # tùy chọn) cũng phải để lại dấu vết — nếu không sẽ có mutation tạo row mà
    # 0 audit entry. ``docs_added``/``docs_removed`` = full keyset; thêm
    # ``mandatory_added``/``mandatory_removed`` để giữ phân biệt độ quan trọng.
    new_doc_codes = set(new_doc_configs.keys())
    added = sorted(new_doc_codes - old_doc_codes)
    removed = sorted(old_doc_codes - new_doc_codes)
    mandatory_added = sorted(set(new_mandatory) - old_mandatory)
    mandatory_removed = sorted(old_mandatory - set(new_mandatory))
    if added or removed:
        from ..services import audit_service

        await audit_service.log_changes(
            db,
            "AdmissionProfile",
            profile.id,
            "documents_reresolved",
            changes={
                "reason": "audience_change",
                "cultural_education_level": getattr(
                    profile, "cultural_education_level", None
                ),
                "docs_added": added,
                "docs_removed": removed,
                "mandatory_added": mandatory_added,
                "mandatory_removed": mandatory_removed,
            },
            actor_user_id=current_user.id if current_user else None,
            source="system",
        )
    log.info(
        "documents_reresolved",
        profile_id=profile.id,
        mandatory_count=len(new_mandatory),
        added=added,
        removed=removed,
    )


async def update_profile(
    db: AsyncSession,
    profile_id: int,
    data: Dict[str, Any],
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Update AdmissionProfile (only when status='draft').

    Security:
    - IDOR: Check lead.unit_id == user.unit_id
    - State Locking: Only allow updates when status='draft'

    Performance:
    - Uses selectinload to prevent N+1 queries

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        data: Update data (from AdmissionProfileUpdate schema)
        current_user: Current authenticated user

    Returns:
        Updated AdmissionProfile

    Raises:
        ResourceNotFoundError: Profile not found
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'draft'
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    # Prevent Race Condition (Lost Update) by locking the row
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.repositories.admission_repository import (
        _choices_eager_load_options,
    )

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            # Eager load lead for IDOR check + nested assigned_officer for _compute_frontend_fields
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            # Eager load assigned_reviewer for _compute_frontend_fields
            selectinload(models.AdmissionProfile.assigned_reviewer),
            # P0 hotfix multi-NV — update_profile calls _compute_frontend_fields
            # directly (NOT via _populate_response_fields 8d), so eager-load
            # choices here too or the sync eligibility read MissingGreenlets.
            # selectinload uses separate SELECTs → compatible with FOR UPDATE.
            *_choices_eager_load_options(),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, current_user)

    # Initialize Repo
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # State Locking: Only draft, rejected, or revision_requested profiles can be updated
    if profile.status not in ["draft", "rejected", "revision_requested"]:
        log.warning(
            "Attempted to update locked profile",
            profile_id=profile_id,
            current_status=profile.status,
            user_id=current_user.id,
        )
        raise BadRequest(
            f"Cannot update profile with status '{profile.status}'. "
            "Only draft, rejected, or revision_requested profiles can be updated."
        )
    
    # Optimistic Locking: Check version matches
    if data.get("version") is not None and data["version"] != profile.version:
        log.warning(
            "Version mismatch during update (concurrent modification)",
            profile_id=profile_id,
            expected_version=data["version"],
            current_version=profile.version,
            user_id=current_user.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Update fields (only non-None values from schema)
    # Update fields (only non-None values from schema)
    if "citizen_id" in data and data["citizen_id"] is not None:
        new_citizen_id = data["citizen_id"]

        # ✅ Validate citizen_id uniqueness within same academic_year (if changed)
        if new_citizen_id != profile.citizen_id:
            # Check if new citizen_id already exists in same year
            duplicate_profile = await admission_repo.check_citizen_id_exists(
                citizen_id=new_citizen_id,
                academic_year=profile.academic_year,
                exclude_profile_id=profile.id
            )

            if duplicate_profile:
                log.warning(
                    "Cannot update citizen_id: Duplicate in same academic year",
                    profile_id=profile.id,
                    new_citizen_id=new_citizen_id,
                    academic_year=profile.academic_year,
                    duplicate_profile_id=duplicate_profile.id,
                )
                raise ConflictError(
                    f"CCCD {new_citizen_id} đã được sử dụng bởi hồ sơ khác "
                    f"trong năm {profile.academic_year} (ID: {duplicate_profile.id})"
                )

            # Check if already enrolled as student
            existing_student = await admission_repo.check_citizen_id_enrolled(new_citizen_id)
            if existing_student:
                log.warning(
                    "Cannot update citizen_id: Already enrolled as student",
                    profile_id=profile.id,
                    new_citizen_id=new_citizen_id,
                    student_code=existing_student.student_code,
                )
                raise ConflictError(
                    f"CCCD {new_citizen_id} đã được sử dụng bởi học viên "
                    f"(Mã SV: {existing_student.student_code})"
                )

        profile.citizen_id = new_citizen_id

    # Cross-field date invariants on the candidate state.
    # Schema's @model_validator only sees the trimmed payload (router dumps
    # via exclude_unset=True), so a request that updates ONLY
    # union_entry_date can leave the row in a state where union > party
    # (party already in DB). Build a candidate from DB attrs + payload
    # and run the same shared utility schema uses. Lesson reference:
    # feedback memory ``partial-update-loses-cross-field-invariants``.
    #
    # IMPORTANT: candidate must match setter semantics, NOT payload as-is.
    # The dob setter (~line 2627) skips when value is None (`is not None`
    # check), so a payload like ``{"dob": null, "union_entry_date": "..."}``
    # leaves the existing DB dob untouched. If we naively copied payload
    # null into the candidate, validate_logical_dates would skip the
    # dob ≤ union check (None short-circuits), then the setter would
    # preserve the original DB dob — re-introducing the same bypass we
    # are trying to fix. The entry-date setters DO accept None (they
    # clear the column), so candidate uses payload value as-is for those.
    from .admission_invariants import validate_logical_dates
    _date_keys = ("dob", "union_entry_date", "party_entry_date", "party_official_entry_date")
    if any(k in data for k in _date_keys):
        candidate_state: Dict[str, Any] = {}
        for _k in _date_keys:
            if _k not in data:
                candidate_state[_k] = getattr(profile, _k)
            elif _k == "dob" and data[_k] is None:
                # Setter ignores ``dob: null`` — preserve existing DB value
                # so the invariant runs against what will actually persist.
                candidate_state[_k] = getattr(profile, _k)
            else:
                candidate_state[_k] = data[_k]
        try:
            validate_logical_dates(candidate_state)
        except ValueError as exc:
            from app.utils.exceptions import ValidationError as _ValidationError
            raise _ValidationError(str(exc))

    # ✅ Sync with Lead: Full Name
    if "full_name" in data and data["full_name"] is not None:
        profile.full_name = data["full_name"]
        if profile.lead and data["full_name"].strip():
            profile.lead.full_name = data["full_name"]

    # ✅ Sync with Lead: Phone
    if "phone" in data and data["phone"] is not None:
        profile.phone = data["phone"]
        if profile.lead and data["phone"].strip():
            profile.lead.phone = data["phone"]

    # ✅ Sync with Lead: Email
    if "email" in data and data["email"] is not None:
        profile.email = data["email"]
        if profile.lead:
            profile.lead.email = data["email"]
    
    # Other fields
    if "dob" in data and data["dob"] is not None:
        profile.dob = data["dob"]
    
    if "gender" in data and data["gender"] is not None:
        profile.gender = data["gender"]
        
    if "permanent_province" in data: profile.permanent_province = data["permanent_province"]
    if "permanent_district" in data: profile.permanent_district = data["permanent_district"]
    if "permanent_ward" in data: profile.permanent_ward = data["permanent_ward"]
    if "permanent_residential_group" in data: profile.permanent_residential_group = data["permanent_residential_group"]
    if "permanent_street_address" in data: profile.permanent_street_address = data["permanent_street_address"]
    if "place_of_birth" in data: profile.place_of_birth = data["place_of_birth"]
    if "native_place" in data: profile.native_place = data["native_place"]
    if "social_insurance_number" in data: profile.social_insurance_number = data["social_insurance_number"]
    if "nationality" in data: profile.nationality = data["nationality"]
    if "ethnicity" in data: profile.ethnicity = data["ethnicity"]
    if "religion" in data: profile.religion = data["religion"]
    if "disability_type" in data: profile.disability_type = data["disability_type"]
    
    # Political date fields
    if "union_entry_date" in data: profile.union_entry_date = data["union_entry_date"]
    if "party_entry_date" in data: profile.party_entry_date = data["party_entry_date"]
    if "party_official_entry_date" in data: profile.party_official_entry_date = data["party_official_entry_date"]

    if "family_info" in data and data["family_info"] is not None:
        profile.family_info = data["family_info"]
        flag_modified(profile, "family_info")

    if "academic_history" in data and data["academic_history"] is not None:
        profile.academic_history = data["academic_history"]
        flag_modified(profile, "academic_history")

    # =========================================================================
    # Q9 #07 PR5 v1.3 phase1_09 — persist priority bonus fields from payload.
    # 2-field parallel design: cultural_education_level + vocational_qualification.
    # Legacy high_school_id / kv_resolved / area_resolution_reason DROPPED.
    # =========================================================================
    if "cultural_education_level" in data:
        profile.cultural_education_level = data["cultural_education_level"]
    if "vocational_qualification" in data and data["vocational_qualification"] is not None:
        profile.vocational_qualification = data["vocational_qualification"]
    if "permanent_commune_code" in data:
        _raw_cc = data["permanent_commune_code"]
        if _raw_cc:
            # PR-3: canonicalize to the CURRENT commune code. An officer may
            # enter an old (3-tier) code from a legacy document; store the
            # resolved current code so KV + records always use the canonical
            # commune. Unresolvable → keep raw (submit gate fail-closes on a
            # non-current code, forcing a current-mode re-pick).
            from app.repositories.administrative_repository import (
                AdministrativeRepository,
            )
            _resolved_cc = await AdministrativeRepository(db).resolve_current_ward_code(
                _raw_cc
            )
            profile.permanent_commune_code = _resolved_cc or _raw_cc
        else:
            profile.permanent_commune_code = _raw_cc
    if "area_resolution_basis" in data:
        profile.area_resolution_basis = data["area_resolution_basis"]
    if "priority_object_codes" in data and data["priority_object_codes"] is not None:
        profile.priority_object_codes = data["priority_object_codes"]
        flag_modified(profile, "priority_object_codes")
    if "priority_object_evidence" in data and data["priority_object_evidence"] is not None:
        # Phase E.4 G3 — strip display-only fields (verified_by_name +
        # document_file_path) trước khi persist vào JSONB column. Defensive
        # guard nếu FE PATCH lỡ gửi display fields (write schema extra=forbid
        # đã block tại Pydantic boundary, nhưng raw dict path qua model_dump
        # có thể bypass). Persist display fields gây schema drift on re-read.
        profile.priority_object_evidence = _strip_display_fields_from_evidence(
            data["priority_object_evidence"]
        )
        flag_modified(profile, "priority_object_evidence")
    # Note: priority_resolution_snapshot KHÔNG set qua candidate payload —
    # frozen at submit T1 + re-frozen at engine T6 (service-layer only).

    # ✅ Phase 6: Update Admission Scores
    if "admission_scores" in data and data["admission_scores"] is not None:
        # Extract subject scores map from Pydantic model dict
        # data["admission_scores"] is a dict (from model_dump)
        scores_data = data["admission_scores"]
        
        # Handle subject_scores
        if "subject_scores" in scores_data and scores_data["subject_scores"]:
            raw_scores = scores_data["subject_scores"]
            
            # Normalization (Business Logic): 
            # Ensure subject codes are lowercase and stripped of whitespace
            normalized_scores = {
                k.lower().strip(): v 
                for k, v in raw_scores.items() 
                if k and v is not None
            }
            
            await admission_repo.update_profile_scores(profile.id, normalized_scores)
            
            # Update snapshot rules/criteria if needed? 
            # No, scores are data, rules are config.
        
        # Handle GPA for gpa_only methods — persist to Lead.gpa
        if "gpa" in scores_data and scores_data["gpa"] is not None:
            gpa_value = float(scores_data["gpa"])
            if profile.lead:
                profile.lead.gpa = gpa_value


    # feat/document-group-audience-merge — re-resolve doc snapshot khi
    # cultural/vocational đổi (audience phụ thuộc 2 field này). Đặt sau khi
    # set cultural (:4055-4058) + scores, trước flush. CONFIG_GAP nuốt nội bộ
    # trong derive_audience_set → luôn ≥ tập văn hóa (round-3 BLOCKER).
    if ("cultural_education_level" in data) or ("vocational_qualification" in data):
        await _reresolve_documents_snapshot(db, profile, admission_repo, current_user)

    # Update timestamp and increment version
    profile.updated_at = datetime.now(timezone.utc)
    profile.version += 1

    # ✅ FIX #2.2: Handle Integrity Errors (Duplicate Citizen ID)
    from sqlalchemy.exc import IntegrityError
    try:
        await db.flush()  # Router commits
    except IntegrityError as e:
        # Rollback is optional here as router handles transaction, but good for clarity
        # await db.rollback() 
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        
        log.error(
            "Update failed due to integrity error",
            profile_id=profile.id,
            error=error_msg
        )

        if "citizen_id" in error_msg.lower():
            raise ConflictError(f"CCCD {profile.citizen_id} đã tồn tại trong hệ thống")
        elif "unique constraint" in error_msg.lower():
            raise ConflictError("Dữ liệu trùng lặp (CCCD hoặc thông tin đã tồn tại)")
        else:
            raise ConflictError(f"Vi phạm ràng buộc dữ liệu: {error_msg}")
    
    # ✅ Fix: Fetch fresh scores but do NOT assign to profile.subject_scores (avoid SA error)
    fresh_scores = await admission_repo.get_profile_scores(profile.id)

    # Calculate totals for response using fresh data
    _calculate_and_update_totals(profile, scores=fresh_scores)

    # ✅ Fix: Re-compute validation errors/status with new scores + fresh documents.
    # Must pass documents, otherwise _validate_documents() short-circuits (returns no doc errors)
    # and documents_checklist is rebuilt with all statuses = "missing", causing the response to
    # claim validation_errors=[] and eligibility="eligible" even when mandatory docs are missing
    # (or, conversely, showing "missing" for docs that are actually uploaded). See MEDIUM #1 in
    # the post-BUG-001 residual risks audit.
    documents = await admission_repo.get_all_documents(profile.id)
    _compute_frontend_fields(
        profile,
        current_user,
        documents,
        await _resolve_verifier_names(db, documents),
    )

    # Audit trail: log profile update with field-level changes
    from ..services import audit_service
    updated_fields = {k: v for k, v in data.items() if k not in ("version",)}
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "updated",
        changes={"updated_fields": list(updated_fields.keys()), "updated_by": current_user.id},
        actor_user_id=current_user.id,
        source="api",
    )

    log.info(
        "Admission profile updated",
        profile_id=profile_id,
        user_id=current_user.id,
        updated_fields=list(data.keys()),
    )

    return profile


def _calculate_and_update_totals(profile: models.AdmissionProfile, scores: list = None) -> None:
    """
    Calculate total_score and average_score from subject_scores.
    
    Args:
        profile: AdmissionProfile object
        scores: Optional explicit list of ProfileSubjectScore (overrides profile.subject_scores)
    
    Note: These fields are transient (not in DB) but required by Schema.
    """
    # P0 hotfix multi-NV (2026-06-04) — profile-level total/average/snapshot
    # are meaningless for multi-NV (scores live per-choice in
    # ProfileChoiceScore). The legacy branches below hard-set 0.00 when the
    # profile-level relation is empty → FE renders a fake "0.00 / Tổng điểm".
    # Set every profile-level score field to None (schema fields are
    # Optional) so the response renders "—" and the FE switches to per-NV
    # display (choice.computed_total_score). See plan step 6.
    if getattr(profile, "uses_choice_engine", False):
        profile.total_score = None
        profile.average_score = None
        profile.admission_scores = None
        profile.snapshot_score = None
        return

    # Use provided scores OR fallback to profile relationship
    # If scores arg is provided managed explicitly, use it.
    # Otherwise check if profile.subject_scores is loaded and populated.
    
    target_scores = scores if scores is not None else profile.subject_scores

    applied_rules = profile.applied_rules or {}
    method_type = applied_rules.get("method_type", "subject_based")

    # GPA-only methods: use Lead.gpa directly, no subject scores needed
    if method_type == "gpa_only":
        gpa_value = float(profile.lead.gpa) if (profile.lead and profile.lead.gpa) else 0.0
        profile.total_score = gpa_value
        profile.average_score = gpa_value
        scores_map = {s.subject.code: float(s.score) for s in target_scores} if target_scores else {}
        profile.admission_scores = {
            "subject_scores": scores_map,
            "total_score": gpa_value,
            "average_score": gpa_value,
            "gpa": gpa_value,
            "snapshot_score": None,
        }
        profile.snapshot_score = None
        return

    # STRICT RULE: Check required subject count
    required_count = applied_rules.get("required_subject_count") or 3

    current_count = len(target_scores) if target_scores else 0

    if current_count < required_count:
        # Incomplete scores -> Treat as 0.0 (Invalid)
        profile.total_score = 0.0
        profile.average_score = 0.0
        
        # Build map of partial scores for display, but totals are 0
        scores_map = {s.subject.code: float(s.score) for s in target_scores} if target_scores else {}

        # Transient field for response serialization (not a DB column)
        profile.admission_scores = {
            "subject_scores": scores_map,
            "total_score": 0.0,
            "average_score": 0.0,
            "gpa": 0.0,
            "snapshot_score": None
        }
        profile.snapshot_score = None
        return

    # Map scores to dict for service
    from decimal import Decimal
    target_scores_map = {s.subject.code: Decimal(str(s.score)) for s in target_scores}

    # ---------------------------------------------------------
    # IMPROVED LOGIC: Use AdmissionScoringService for calculation
    # ---------------------------------------------------------
    from .admission_scoring_service import AdmissionScoringService, ProfileStatus, SubjectSelectionMode, ScoringMethod
    from app.models.admission_config import AdmissionCriteria
    
    # 1. Reconstruct Criteria from Snapshot
    # Safe extraction of method code
    method_data = applied_rules.get("admission_method")
    if isinstance(method_data, dict):
        method_code = method_data.get("code", "SNAPSHOT")
    else:
        # Fallback if stored as string literal or None
        method_code = str(method_data) if method_data else "SNAPSHOT"

    snapshot_criteria = models.AdmissionCriteria(
        code=method_code,
        min_gpa=float(applied_rules.get("min_gpa") or 0),
        min_score=float(applied_rules.get("min_score") or 0),
        min_subject_score=float(applied_rules.get("min_subject_score") or 0),
        required_subject_count=applied_rules.get("required_subject_count"),
        subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
        scoring_method=applied_rules.get("scoring_method", "sum"),
    )
    
    # 2. Prepare allowed subjects
    allowed_subjects = applied_rules.get("allowed_subject_codes", [])
    # Removed legacy fallback - allowed_subjects must be populated in validation phase

    # PR6 Step 2 (2026-04-19): read frozen per-subject weights from the
    # snapshot. None/empty → scoring engine falls back to plain behavior,
    # which is the no-retroactive guarantee for pre-migration snapshots.
    subject_weights = applied_rules.get("subject_weights") or None

    # 3. Calculate using robust engine
    score_result = AdmissionScoringService.calculate_score(
        criteria=snapshot_criteria,
        subject_scores=target_scores_map,
        allowed_subjects=allowed_subjects,
        subject_weights=subject_weights,
    )
    
    # Update transient fields
    # Note: AdmissionScoreResult uses final_score (not total_score/average_score)
    final_score_value = float(score_result.final_score) if score_result.final_score is not None else 0.0
    profile.total_score = final_score_value
    
    # Compute average from selected scores
    # Note: AdmissionScoreResult uses `subject_scores` (not `selected_scores`)
    selected_scores_list = list(score_result.subject_scores.values()) if score_result.subject_scores else []
    if selected_scores_list:
        profile.average_score = sum(float(s) for s in selected_scores_list) / len(selected_scores_list)
    else:
        profile.average_score = 0.0

    # Transient fields for response serialization (not DB columns)
    snapshot_score = {
        "selected_subjects": score_result.selected_subjects,
        "selected_scores": {k: float(v) for k, v in score_result.subject_scores.items()},
        "status": score_result.status.value,
        "failure_reasons": score_result.failure_reasons
    }
    profile.admission_scores = {
        "subject_scores": {k: float(v) for k, v in target_scores_map.items()},
        "total_score": profile.total_score,
        "average_score": profile.average_score,
        "gpa": profile.average_score,
        "snapshot_score": snapshot_score
    }
    profile.snapshot_score = snapshot_score


# =============================================================================
# Q9 #07 Phase E.4 commit 5 fix-up — submit-time guard cho KV unresolved
# =============================================================================

# Phase E.4 commit 5 fix-up — submit guard FLIP từ blacklist sang whitelist
# success (reviewer P1: "nếu requires_manual_override is True thì block
# mặc định, chỉ pass các rule thành công rõ ràng").
#
# Pass-through CHỈ khi:
#   - rule_applied ∈ _KV_SUCCESS_RULE_APPLIED (engine resolve thành công)
#   - VÀ kv_resolved != None (snapshot có giá trị KV thực)
#
# Empty/None snapshot → pass defensive (engine T1 freeze fail infra; warning
# đã log ở freeze try/except). Mọi rule_applied khác / kv_resolved None →
# block với BadRequest tiếng Việt + guidance.
_KV_SUCCESS_RULE_APPLIED = frozenset({
    "longest_duration",
    "tiebreak_graduation_school",
    "commune_lookup",
    "manual_override",
})


def _kv_unresolved_error_message(
    snapshot: Optional[dict],
    profile_id: int,
) -> Optional[str]:
    """Return error message string nếu snapshot không emit engine success;
    None khi snapshot resolve thành công.

    Phase E.4 reviewer v4 2026-05-21 — KV unresolved giờ trả validation_error
    (not raise) để submit flow giữ status=draft + commit snapshot unresolved.
    Manager/admin sau đó có signal ``requires_manual_override=True`` trong
    snapshot persisted để override draft (gỡ deadlock fail-closed vs draft
    override gate).

    Pass paths (whitelist):
      - longest_duration / tiebreak_graduation_school / commune_lookup
        (engine resolve qua LICH_SU_THPT hoặc THUONG_TRU/COMMUNE_SPECIAL)
      - manual_override (admin/manager đã set KV thủ công pre-submit)

    Block paths (fail-closed mọi case khác — KHÔNG có defensive escape):
      - address_not_normalized / catalog_gap_* / insufficient_data /
        ambiguous_requires_manual / not_resolved / unknown future rules
      - kv_resolved is None mà rule trong whitelist (race)
      - Empty/None snapshot (freeze chưa chạy hoặc fail infra)

    Args:
        snapshot: profile.priority_resolution_snapshot (dict | None).
        profile_id: id cho log context.

    Returns:
        Error message tiếng Việt nếu unresolved; None nếu pass.
    """
    snapshot = snapshot or {}
    rule_applied = snapshot.get("rule_applied")
    kv_resolved = snapshot.get("kv_resolved")

    # Pass: rule trong success whitelist VÀ kv_resolved có giá trị.
    if rule_applied in _KV_SUCCESS_RULE_APPLIED and kv_resolved is not None:
        return None

    # Otherwise build error message — fail-closed default.
    if not snapshot:
        reason = "no_snapshot_present"
        log.info(
            "submit_blocked_kv_no_snapshot",
            profile_id=profile_id,
        )
    else:
        reason = (
            snapshot.get("reason")
            or snapshot.get("basis_reason")
            or rule_applied
            or "unknown"
        )
        log.info(
            "submit_blocked_kv_unresolved",
            profile_id=profile_id,
            rule_applied=rule_applied,
            kv_resolved=kv_resolved,
            reason=reason,
        )
    return (
        f"KV_UNRESOLVED ({rule_applied or 'no_rule_applied'}): engine không "
        f"xác định được khu vực ưu tiên cho hồ sơ này. Lý do: {reason}. "
        f"Vui lòng kiểm tra trình độ văn hóa, địa chỉ thường trú và lịch "
        f"sử học THPT, hoặc đề nghị quản lý ấn định KV thủ công trước "
        f"khi nộp."
    )


def _assert_kv_resolved_for_submit(
    snapshot: Optional[dict],
    profile_id: int,
) -> None:
    """Raise BadRequest wrapper trên ``_kv_unresolved_error_message``.

    Retained cho callers external (vd alternate flows). Submit-T1 path
    KHÔNG dùng wrapper này nữa — giờ collect error vào validation_errors
    list để commit snapshot unresolved (signal cho manager override draft).
    """
    err = _kv_unresolved_error_message(snapshot, profile_id)
    if err:
        raise BadRequest(err)


async def _validate_eligibility_all_choices(
    db: AsyncSession,
    profile: models.AdmissionProfile,
) -> None:
    """Q9 #07 Phase E.4 — eligibility gate per yêu cầu nghiệp vụ #5.

    Pipeline order (xem priority_service docstring): Eligibility → Exception
    → Auto basis → Resolve KV → Apply path bonus → Snapshot. Eligibility chạy
    TRƯỚC freeze để fail-fast khi cultural + vocational không match path
    target_level/admission_type.

    Behavior per flow:
      - ``uses_choice_engine=True`` (multi-NV): query choices với eager-load
        chain ``path → academic_info → offering → program``. Validate mỗi
        choice. Bất kỳ choice nào fail → raise BusinessRuleViolation (caller
        map sang BadRequest/422).
      - ``uses_choice_engine=False`` (legacy single-path): derive target từ
        ``profile.offering_admission_config_id`` chain. Nếu không có config →
        raise CONFIG_GAP_TARGET_LEVEL (fail-closed per nghiệp vụ).

    Reason codes (i18n key cho FE error display):
      - ``ELIGIBILITY_FAIL_<reason>`` cho từng choice
      - ``CONFIG_GAP_TARGET_LEVEL`` khi không derive được level/type

    Per yêu cầu nghiệp vụ #5: tuyệt đối KHÔNG fallback "so_cap" khi gap.

    Error-handling contract — intentional contrast với choice engine
    -----------------------------------------------------------------
    Helper này (submit-time gate) raises ``BusinessRuleViolation`` UNWRAPPED:
    bất kỳ ``derive_target_level_and_type`` CONFIG_GAP, validate_eligibility
    fail, hoặc multi-NV inconsistency → bubble lên router → 400/422. Submit
    fail-closed toàn bộ (Phase E.4 reviewer P0 fix — yêu cầu nghiệp vụ #5).

    Đối lập với ``admission_choice_engine_service._evaluate_single_choice``
    (engine T6 publish path) — chỗ đó WRAPS ``derive_target_level_and_type``
    + ``validate_eligibility`` trong try/except ``BusinessRuleViolation`` và
    convert thành per-choice ``reason_codes = ["CONFIG_GAP_TARGET_LEVEL:..."]``
    / ``["ELIGIBILITY_FAIL:..."]`` + ``status="rejected"`` để engine vẫn
    cascade qua các choice khác (1 choice rỗng config KHÔNG được block
    publish 4 choice còn lại).

    Tóm tắt:
      submit-time   : fail-closed → raise → toàn hồ sơ vào draft + validation_errors
      engine-T6     : per-choice  → reject reason_code → cascade tiếp choice sau
    """
    from sqlalchemy import select as _sel
    from sqlalchemy.orm import selectinload as _sel_in

    from .priority_service import (
        _make_path_shim_from_academic_info,
        derive_major_code,
        derive_target_level_and_type,
        validate_eligibility,
    )

    failures: list[str] = []
    # Phase E.4 commit 6 — Multi-NV consistency guard (yêu cầu nghiệp vụ #12):
    # collect target_level + admission_type per choice trong cùng loop. Sau
    # loop, raise BusinessRuleViolation MULTI_NV_INCONSISTENT nếu khác nhau.
    # MVP: block submit; per-choice KV snapshot defer Phase F.
    targets_seen: set[str] = set()
    types_seen: set[str] = set()
    choices_summary: list[str] = []

    if profile.uses_choice_engine:
        # Load choices với eager chain cho derive_target_level_and_type
        choices_stmt = (
            _sel(models.AdmissionProfileChoice)
            .where(
                models.AdmissionProfileChoice.admission_profile_id == profile.id
            )
            .options(
                _sel_in(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.academic_info)
                .selectinload(models.OfferingAcademicInfo.offering)
                .selectinload(models.ProgramOffering.program)
                .selectinload(models.MajorProgram.degree_level_ref),
                _sel_in(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.academic_info)
                .selectinload(models.OfferingAcademicInfo.offering)
                .selectinload(models.ProgramOffering.offering_type_config),
            )
            .order_by(models.AdmissionProfileChoice.display_order)
        )
        choices_result = await db.execute(choices_stmt)
        choices = choices_result.scalars().all()

        for choice in choices:
            path = choice.admission_path
            target_level, admission_type = derive_target_level_and_type(path)
            targets_seen.add(target_level)
            types_seen.add(admission_type)
            choices_summary.append(
                f"NV{choice.display_order}={target_level}/{admission_type}"
            )
            ok, reason = validate_eligibility(
                profile, target_level, admission_type, derive_major_code(path)
            )
            if not ok:
                failures.append(
                    f"NV{choice.display_order} ({target_level}/{admission_type}): "
                    f"{reason}"
                )

        # Phase E.4 commit 6 — Multi-NV consistency check (yêu cầu nghiệp vụ #12).
        # KHI có > 1 choice và target/admission_type khác nhau → block submit
        # với guidance tách hồ sơ. Snapshot KV freeze ở submit dùng NV1 làm
        # primary (commit 5); per-choice snapshot defer Phase F — nên multi-NV
        # khác basis tạo race conditions cho engine T6 + audit ambiguity.
        if len(choices) >= 2 and (len(targets_seen) > 1 or len(types_seen) > 1):
            raise BusinessRuleViolation(
                "MULTI_NV_INCONSISTENT: hồ sơ đa nguyện vọng có các nguyện "
                f"vọng KHÔNG đồng nhất bậc đào tạo hoặc hệ đào tạo "
                f"({', '.join(choices_summary)}). Đợt MVP chỉ hỗ trợ các "
                f"nguyện vọng cùng (target_level, admission_type) để engine "
                f"tính khu vực ưu tiên + chính sách bonus thống nhất. Vui "
                f"lòng tách thành nhiều hồ sơ riêng (mỗi hồ sơ 1 bậc/hệ) "
                f"hoặc chọn lại các nguyện vọng đồng nhất."
            )
    else:
        # Legacy non-multi-NV: lookup từ offering_admission_config chain.
        config_id = profile.offering_admission_config_id
        if config_id is None:
            raise BusinessRuleViolation(
                "CONFIG_GAP_TARGET_LEVEL: hồ sơ không có offering_admission_config_id "
                "và uses_choice_engine=False — không thể xác định bậc đào tạo. "
                "Vui lòng cấu hình config trước khi submit."
            )
        config_stmt = (
            _sel(models.OfferingAdmissionConfig)
            .where(models.OfferingAdmissionConfig.id == config_id)
            .options(
                _sel_in(models.OfferingAdmissionConfig.academic_info)
                .selectinload(models.OfferingAcademicInfo.offering)
                .selectinload(models.ProgramOffering.program)
                .selectinload(models.MajorProgram.degree_level_ref),
                _sel_in(models.OfferingAdmissionConfig.academic_info)
                .selectinload(models.OfferingAcademicInfo.offering)
                .selectinload(models.ProgramOffering.offering_type_config),
            )
        )
        config = (await db.execute(config_stmt)).scalar_one_or_none()
        if config is None:
            raise BusinessRuleViolation(
                f"CONFIG_GAP_TARGET_LEVEL: offering_admission_config_id="
                f"{config_id} không tồn tại."
            )
        # Build pseudo-path stub để reuse derive_target_level_and_type
        # (helper đọc __dict__['academic_info']); shared helper centralize
        # pattern (xem priority_service._make_path_shim_from_academic_info).
        shim = _make_path_shim_from_academic_info(config.academic_info)
        target_level, admission_type = derive_target_level_and_type(shim)  # type: ignore[arg-type]
        ok, reason = validate_eligibility(
            profile, target_level, admission_type, derive_major_code(shim)
        )
        if not ok:
            failures.append(
                f"Legacy single-path ({target_level}/{admission_type}): {reason}"
            )

    if failures:
        raise BusinessRuleViolation(
            "ELIGIBILITY_FAIL: " + "; ".join(failures)
        )


async def _audit_warning_dismissed_if_missing(
    db: AsyncSession,
    profile_id: int,
    profile: models.AdmissionProfile,
    current_user: Optional[models.User],
) -> None:
    """Q9 #07 Phase E.4 Decision #2 — audit row khi officer submit với UT
    codes ghi nhận nhưng chưa upload minh chứng.

    Computes missing_priority_evidence_codes inline (query ProfileDocument
    cho category='priority_evidence' rows), then INSERTs PriorityAuditLog
    với action_type='ut_evidence_warning_dismissed' nếu non-empty.

    NOT eligibility gate (Decision #2): officer có quyền verify "Hồ sơ
    giấy"; just track cho post-hoc thanh tra audit trail. CHECK constraint
    ck_priority_audit_log_action_type extended in migration q9_07_e4b
    accepts this action type.

    Defensive try/except: failure không block submit (audit gap acceptable
    vs profile submit blocked). Structlog warning cho ops monitoring.

    Extracted from submit_and_evaluate cho unit test isolation (PR-4
    audit cycle 2026-05-20).
    """
    try:
        from sqlalchemy import select as _sel
        priority_codes = list(profile.priority_object_codes or [])
        missing_codes: list[str] = []
        if priority_codes:
            docs_q = await db.execute(
                _sel(
                    models.ProfileDocument.priority_sub_code,
                ).where(
                    models.ProfileDocument.profile_id == profile_id,
                    models.ProfileDocument.category == "priority_evidence",
                    models.ProfileDocument.priority_sub_code.is_not(None),
                )
            )
            uploaded_codes = {row.priority_sub_code for row in docs_q}
            missing_codes = sorted(set(priority_codes) - uploaded_codes)

        if missing_codes:
            db.add(
                models.PriorityAuditLog(
                    profile_id=profile_id,
                    action_type="ut_evidence_warning_dismissed",
                    actor_id=current_user.id if current_user else None,
                    old_value=None,
                    new_value={"missing_codes": missing_codes},
                    audit_metadata={
                        "submit_status": "submitted",
                        "missing_count": len(missing_codes),
                        "actor_role": (
                            current_user.role if current_user else "magic_link"
                        ),
                    },
                )
            )
            log.info(
                "submit_audit_warning_dismissed",
                profile_id=profile_id,
                missing_codes=missing_codes,
                actor_id=current_user.id if current_user else None,
            )
    except Exception as audit_exc:  # noqa: BLE001 — defensive: never block submit
        log.warning(
            "ut_evidence_warning_dismissed_audit_failed",
            profile_id=profile_id,
            error=str(audit_exc),
            reason=(
                "Decision #2 audit row insert failed during submit; "
                "profile still submits but post-hoc audit gap exists."
            ),
        )


async def _is_current_era_ward(db: AsyncSession, commune_code: Optional[str]) -> bool:
    """True iff ``commune_code`` is a CURRENT-era (2-tier, ``valid_to IS NULL``)
    ward node in ``administrative_nodes``.

    Gap #3 submit gate uses this: a legacy / stale / missing code → False, so
    submit fail-closes and forces re-selecting the post-2025 commune. This
    guarantees the stored ``permanent_commune_code`` is the canonical current
    code KV resolution + records rely on (never a deprecated 3-tier code).
    """
    code = (commune_code or "").strip()
    if not code:
        return False
    from sqlalchemy import select as _sel
    from app.models.administrative_node import (
        AdministrativeLevel,
        AdministrativeNode,
    )
    result = await db.execute(
        _sel(AdministrativeNode.id)
        .where(
            AdministrativeNode.code == code,
            AdministrativeNode.level == AdministrativeLevel.WARD,
            AdministrativeNode.valid_to.is_(None),
            AdministrativeNode.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def submit_and_evaluate(
    db: AsyncSession,
    profile_id: int,
    current_user: Optional[models.User],
    *,
    acknowledge_missing_docs: bool = False,
    document_debt_reason: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """
    Submit AdmissionProfile for evaluation (auto-approve or return errors).

    Validation Rules (against SNAPSHOT applied_rules):
    1. admission_scores.gpa >= applied_rules.min_gpa
    2. All mandatory_docs have status='uploaded' and file_path not null
    3. citizen_id is unique across admission_profile and student tables
    4. JSON structures are valid (already validated by Pydantic)

    Security:
    - IDOR: Check lead.unit_id == user.unit_id (bypassed if current_user=None;
      magic-link path verifies CCCD before invoking).
    - Snapshot: Use applied_rules ONLY (never query ProgramOffering)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        current_user: Current authenticated user, or None for magic-link
            self-service candidate path (CCCD already verified upstream).
        acknowledge_missing_docs: Fast-track C1 — when True AND the actor is
            staff (officer/manager/admin) AND ``document_debt_reason`` is set
            AND the only outstanding errors are truly-missing mandatory
            documents, the profile transitions to ``submitted`` and a
            ``document_debt`` snapshot is recorded. Candidate/magic-link
            (current_user=None) can never use this. Defaults False (original
            no-body behaviour: missing docs block submit).
        document_debt_reason: Officer's reason for allowing the document debt;
            required when ``acknowledge_missing_docs`` is honoured.

    Returns:
        Tuple of (result_dict, post_commit_callback):
        - result_dict shape unchanged from V2:
            * {"status": "submitted", "message": ..., "validation_errors": None}
            * {"status": "draft", "message": None, "validation_errors": [...]}
        - post_commit_callback: async no-arg callable. Router MUST await
          AFTER db.commit(). None when validation failed (status="draft" —
          no notification fanout for unsuccessful submit). When status=
          "submitted", fires APPLICATION_STATUS_CHANGED + ADMISSION_PROFILE_
          SUBMITTED with the same payload shape the router built in V2.
          Closing over actor_id/actor_name/lead_id captured at flush time
          keeps the dispatch independent of post-commit DB state.

    Raises:
        ResourceNotFoundError: Profile not found
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'draft'
    """
    # ✅ CRITICAL FIX #2: Add pessimistic lock to prevent race conditions
    # Scenario: 2 officers submit same profile simultaneously
    # Without lock: Both pass status check, both update to "submitted"
    # With lock: Second request waits, then fails status check
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Use selectinload to avoid "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))  # ✅ Eager load Lead
        .with_for_update()  # ✅ CRITICAL: Acquire row lock
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check (after lock acquired)
    _check_idor_access(profile, current_user)

    # Initialize repository for document/citizen_id checks
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Phase 3 close-out 2026-05-14 — multi-NV profiles MUST carry at
    # least one ``AdmissionProfileChoice`` before submit. Without this
    # gate a candidate could submit an empty multi-NV profile, transition
    # straight to ``reviewing``, then a manager's later publish-result
    # call would invoke ``evaluate_cascade`` on an empty ``profile.choices``
    # list — the for-loop iterates zero times and the engine silently
    # returns ``CascadeResult(final_status='rejected')``, marking the
    # candidate rejected without any human review.
    #
    # Counting via a scalar query (NOT loading the relation) keeps the
    # FOR UPDATE lock semantics clean and avoids an eager-load that
    # would otherwise require a relationship-aware lock variant.
    if profile.uses_choice_engine:
        from sqlalchemy import func as sa_func, select as sa_select
        choice_count_result = await db.execute(
            sa_select(sa_func.count(models.AdmissionProfileChoice.id)).where(
                models.AdmissionProfileChoice.admission_profile_id == profile.id
            )
        )
        choice_count = choice_count_result.scalar_one()
        if choice_count == 0:
            raise BadRequest(
                "Hồ sơ đa nguyện vọng phải có ít nhất 1 nguyện vọng trước khi nộp. "
                "Vui lòng thêm nguyện vọng tại bước Điểm & Điều kiện."
            )

    # Must be in draft status
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot submit profile with status '{profile.status}'. "
            "Only draft profiles can be submitted."
        )

    # PR-2 (2026-05-28) — Round cutoff enforcement (SPEC §2.1.a Rule 1).
    # Block submit khi round.end_date đã qua. create_profile() đã gate
    # tại create-time, nhưng candidate có thể create rồi đợi qua end_date
    # mới submit → second gate ở đây bảo vệ. Fail-fast trước eligibility/
    # doc/score validation để tiết kiệm cycles + clear 410 error message.
    #
    # PR review nit #2: extracted inline 20-line lookup → admission_repo
    # helper. Removes ugly sa_select_cutoff aliases (function-local name
    # collision dodge against top-level select/selectinload imports).
    #
    # PR review nit #3: legacy profile mà applied_rules thiếu
    # admission_path_id bypass gate (silent skip). Per memory
    # phase3-multi-nv-partial-enablement-2026-05-14 còn ~10 legacy profile
    # — log warning để ops grep + backfill manual nếu cần.
    cutoff_round = await admission_repo.get_round_for_profile_cutoff(profile)
    if cutoff_round is not None:
        assert_round_open(
            cutoff_round,
            context_hint="Liên hệ admin nếu cần extend đợt.",
        )
    else:
        log.warning(
            "submit_cutoff_skipped_missing_path_in_applied_rules",
            profile_id=profile.id,
            applied_rules_keys=sorted((profile.applied_rules or {}).keys()),
            reason=(
                "applied_rules thiếu admission_path_id → cutoff gate skip "
                "(legacy profile pre-snapshot era). Ops: grep log để backfill "
                "manual nếu round đã đóng."
            ),
        )

    # Q9 #07 Phase E.4 — eligibility gate per yêu cầu nghiệp vụ #5: chặn TOÀN BỘ
    # hồ sơ submit không match cultural + vocational vs target_level/admission_type
    # của path/config. Trước fix: gate đặt trong if uses_choice_engine → 9/11 dev
    # profile legacy single-path bypass (reviewer finding 2026-05-21).
    #
    # Helper handle 2 flow:
    #   - uses_choice_engine=True (multi-NV): loop choices.admission_path
    #   - uses_choice_engine=False (legacy): profile.offering_admission_config chain
    #
    # Pipeline order: Eligibility → Exception → Auto basis → Resolve KV → Apply
    # bonus → Snapshot (xem priority_service docstring). Tuyệt đối KHÔNG fallback
    # "so_cap" khi thiếu target_level config — raise CONFIG_GAP_TARGET_LEVEL.
    await _validate_eligibility_all_choices(db, profile)

    errors: List[str] = []

    # Get applied_rules (snapshot)
    applied_rules = profile.applied_rules or {}
    mandatory_docs = applied_rules.get("mandatory_docs", [])
    
    # ========================================
    # Phase 6: Dynamic Admission Scoring Validation (Refactored)
    # ========================================

    method_type = applied_rules.get("method_type", "subject_based")

    if profile.uses_choice_engine:
        # =====================================================================
        # P0 hotfix multi-NV — per-NV data-completeness gate.
        # =====================================================================
        # Scores live per-choice in ProfileChoiceScore; the gpa_only /
        # subject-based branches below read profile-level ProfileSubjectScore
        # (always empty for multi-NV → a spurious "thiếu điểm" on every
        # submit). Gate on per-NV completeness instead: every choice carries
        # ≥ required combo subjects with valid numeric/range scores. NO
        # min_score / sàn here — the T6 publish cascade (evaluate_cascade)
        # applies the threshold per NV. ``with_for_update()`` above did NOT
        # eager choices, so fetch them fresh with the full eager chain the
        # helper walks (scores+subject + subject_group.subject_mappings).
        from app.repositories.admission_profile_choice_repository import (
            AdmissionProfileChoiceRepository,
        )
        from .admission_choice_engine_service import (
            validate_choice_scores_complete,
        )
        _choices = await AdmissionProfileChoiceRepository(db).list_by_profile(
            profile.id
        )
        errors.extend(validate_choice_scores_complete(_choices, applied_rules))
    elif method_type == "gpa_only":
        # =====================================================================
        # GPA-Only Branch: validate using Lead.gpa, no subject scores required
        # =====================================================================
        gpa_value = float(profile.lead.gpa) if (profile.lead and profile.lead.gpa) else None
        min_gpa = float(applied_rules.get("min_gpa") or 0)

        if gpa_value is None:
            errors.append("Chưa nhập GPA. Vui lòng nhập điểm trung bình trước khi nộp hồ sơ.")
        elif min_gpa > 0 and gpa_value < min_gpa:
            errors.append(
                f"Điểm xét tuyển không đạt: GPA không đạt: {gpa_value:.2f} < {min_gpa}"
            )
            log.warning(
                "GPA-only scoring validation failed",
                profile_id=profile.id,
                gpa=gpa_value,
                min_gpa=min_gpa,
            )
        else:
            log.info(
                "GPA-only scoring validation passed",
                profile_id=profile.id,
                gpa=gpa_value,
                min_gpa=min_gpa,
            )
    else:
        # =====================================================================
        # Subject-Based / Combined Branch (existing logic)
        # =====================================================================

        # Use AdmissionScoringService for robust validation (Best N, Min Score, etc.)
        from .admission_scoring_service import AdmissionScoringService, ProfileStatus, SubjectSelectionMode, ScoringMethod
        from app.models.admission_config import AdmissionCriteria

        # 1. Reconstruct Criteria from Snapshot (applied_rules)
        # ✅ FIX: Safe extraction of admission_method (can be string or dict in legacy data)
        method_data = applied_rules.get("admission_method")
        if isinstance(method_data, dict):
            method_code = method_data.get("code", "SNAPSHOT")
        else:
            method_code = str(method_data) if method_data else "SNAPSHOT"

        snapshot_criteria = models.AdmissionCriteria(
            code=method_code,
            min_gpa=float(applied_rules.get("min_gpa", 0)) if applied_rules.get("min_gpa") else None,
            min_score=float(applied_rules.get("min_score", 0)) if applied_rules.get("min_score") else None,
            min_subject_score=float(applied_rules.get("min_subject_score", 0)) if applied_rules.get("min_subject_score") else None,
            required_subject_count=applied_rules.get("required_subject_count"),
            subject_selection_mode=applied_rules.get("subject_selection_mode", "fixed"),
            scoring_method=applied_rules.get("scoring_method", "sum"),
        )

        # 2. Get Scores
        scores = await admission_repo.get_profile_scores(profile.id)
        subject_scores_map = {s.subject.code: Decimal(str(s.score)) for s in scores}

        # 3. Resolve Allowed Subjects
        allowed_subjects = applied_rules.get("allowed_subject_codes")

        if not allowed_subjects:
            log.warning(
                "Profile has incomplete snapshot - missing allowed_subject_codes. "
                "Using fallback to all scored subjects (legacy compatibility). "
                "This profile should be recreated for deterministic scoring.",
                profile_id=profile.id,
                lead_id=profile.lead_id,
                snapshot_source=applied_rules.get("snapshot_source"),
            )
            allowed_subjects = list(subject_scores_map.keys())

            if not allowed_subjects:
                raise BadRequest(
                    "Cannot evaluate profile: No subject scores found and snapshot has no subject whitelist. "
                    "Please add subject scores before submitting."
                )

        # 4. Calculate Score using Engine
        score_result = AdmissionScoringService.calculate_score(
            criteria=snapshot_criteria,
            subject_scores=subject_scores_map,
            allowed_subjects=allowed_subjects,
            subject_weights=applied_rules.get("subject_weights") or None,
        )

        # 5. Handle Validation Results
        if score_result.status != ProfileStatus.VALID:
            for reason in score_result.failure_reasons:
                errors.append(f"Điểm xét tuyển không đạt: {reason}")

            log.warning(
                "Scoring validation failed",
                profile_id=profile.id,
                reasons=score_result.failure_reasons,
                disqualification_codes=score_result.disqualification_codes
            )
        else:
            official_gpa = float(score_result.final_score) if score_result.final_score else 0.0
            log.info(
                "Scoring validation passed",
                profile_id=profile.id,
                final_score=official_gpa,
                selected_subjects=score_result.selected_subjects
            )

    # Validation 2: Check mandatory documents (using relational ProfileDocument).
    # PR #6 — honour the path-level allow_unverified_submission flag snapshotted
    # in applied_rules. Strict mode requires verified or paper_submitted; lax
    # mode (pre-PR default, grandfathered) also accepts uploaded-with-file.
    uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
    schema_version = applied_rules.get("schema_version", 1)
    if schema_version == 1:
        allow_unverified = bool(applied_rules.get("allow_unverified_submission", True))
    else:
        if "allow_unverified_submission" not in applied_rules:
            raise BusinessRuleViolation(
                f"Profile {profile.id} applied_rules missing allow_unverified_submission "
                f"(schema_version={schema_version}). create_profile must snapshot the flag."
            )
        allow_unverified = bool(applied_rules["allow_unverified_submission"])

    # Phase E.4 fix (smoke 2026-05-20, sibling to _validate_documents fix):
    # priority_evidence docs do NOT have a document_type_id FK (they map 1:1
    # với priority_object_codes via priority_sub_code, NOT via path's
    # mandatory_docs ConfigDocumentType catalog). Skip them before reading
    # doc.document_type.code or submit_and_evaluate crashes with
    # AttributeError on first priority evidence row.
    path_uploaded_docs = [
        doc for doc in uploaded_docs
        if doc.document_type is not None
        and getattr(doc, "category", None) != "priority_evidence"
    ]
    if allow_unverified:
        uploaded_doc_codes = {doc.document_type.code for doc in path_uploaded_docs}
        # Lax mode: anything not in uploaded_doc_codes has no file → truly missing.
        pending_verify_codes: set[str] = set()
    else:
        uploaded_doc_codes = {
            doc.document_type.code for doc in path_uploaded_docs
            if doc.status in ("verified", "paper_submitted")
        }
        # Strict mode: a mandatory doc with a file but status='uploaded' is
        # uploaded-but-pending-verify, NOT truly missing. Mirror
        # _validate_documents (:1114) so the nợ-giấy-tờ waiver only ever
        # waives TRULY-missing docs (B2) — unverified docs still block.
        pending_verify_codes = {
            doc.document_type.code for doc in path_uploaded_docs
            if doc.file_path and doc.status == "uploaded"
        }

    # Fast-track C1 — collect TRULY-missing mandatory doc codes + their error
    # messages separately so the submit-with-debt path can waive ONLY these
    # (uploaded-pending-verify errors stay in ``errors`` and keep blocking).
    missing_doc_codes: List[str] = []
    missing_doc_errors: List[str] = []
    for doc_code in mandatory_docs:
        if doc_code not in uploaded_doc_codes:
            doc = await admission_repo.get_document_by_type(profile.id, doc_code)
            label = doc.document_type.name if doc else doc_code
            if not allow_unverified and doc_code in pending_verify_codes:
                # Uploaded but not yet verified — NOT waivable; blocks submit.
                errors.append(
                    f"Tài liệu {label} ({doc_code}) chưa được xác minh. "
                    f"Liên hệ quản lý để verify trước khi nộp hồ sơ."
                )
            else:
                # Truly missing (no file). Waivable via document debt.
                missing_doc_codes.append(doc_code)
                missing_doc_errors.append(
                    f"Thiếu tài liệu bắt buộc: {label} ({doc_code})"
                )

    # Validation 3: Check citizen_id uniqueness
    if not profile.citizen_id:
        errors.append("Số CCCD/CMND chưa được nhập (citizen_id is null)")
    else:
        # Check in admission_profile table (other profiles IN THE SAME YEAR)
        duplicate_profile = await admission_repo.check_citizen_id_exists(
            citizen_id=profile.citizen_id,
            academic_year=profile.academic_year,  # ✅ UPDATED: Filter by year
            exclude_profile_id=profile.id
        )

        if duplicate_profile:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi hồ sơ khác "
                f"trong năm {profile.academic_year} (ID: {duplicate_profile.id})"
            )

        # Check in student table (already enrolled students)
        existing_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)

        if existing_student:
            errors.append(
                f"CCCD {profile.citizen_id} đã được sử dụng bởi học viên "
                f"(Mã SV: {existing_student.student_code})"
            )

    # Validation 4: Check Family Info (Fix Finding 1.7)
    if not profile.family_info:
        errors.append("Chưa nhập thông tin gia đình (Family Info is empty)")

    # Validation 5: Check Academic History (Fix Finding 1.7)
    if not profile.academic_history:
        errors.append("Chưa nhập quá trình học tập (Academic History is empty)")

    # Q9 #07 Phase E.4 reviewer v4 — KV freeze + assert chuyển từ "post if-errors
    # transition prep" lên đây để errors collect cho cả KV failure. Nếu raise
    # BadRequest trong transaction success path, router rollback snapshot →
    # manager/admin draft override gate KHÔNG thấy engine signal → deadlock.
    # Giải pháp: freeze runs unconditionally (collect signal vào snapshot),
    # errors list aggregate KV unresolved/resolution_failed, then `if errors:`
    # branch flushes snapshot + returns validation_errors. Snapshot persist
    # vào DB qua router commit → override draft sees requires_manual_override.
    #
    # Lazy import: priority_service imports app.models would create circular
    # dep at module load time of this service file.
    from .priority_service import (
        derive_profile_target_context,
        freeze_priority_snapshot as _freeze_kv,
    )

    try:
        target_ctx = await derive_profile_target_context(profile, db)
        await _freeze_kv(
            profile=profile,
            db=db,
            frozen_at_status="submitted_T1",
            resolved_by="system",
            target_level=target_ctx.get("target_level"),
            admission_type=target_ctx.get("admission_type"),
            eligibility=target_ctx.get("eligibility"),
            path_bonus_rule=target_ctx.get("path_bonus_rule"),
        )
    except (BadRequest, BusinessRuleViolation):
        # Domain errors từ helper (vd version conflict) → bubble lên router.
        raise
    except Exception as freeze_exc:  # noqa: BLE001
        log.error(
            "priority_snapshot_freeze_failed_at_submit",
            profile_id=profile_id,
            error=str(freeze_exc),
            error_type=type(freeze_exc).__name__,
        )
        errors.append(
            f"KV_RESOLUTION_FAILED: engine không hoàn tất resolve KV cho hồ "
            f"sơ này do lỗi hệ thống ({type(freeze_exc).__name__}). Vui lòng "
            f"thử lại; nếu lỗi tiếp diễn, báo admin kiểm tra catalog "
            f"(vn_commune_area_map, vn_school_kv_assignment) và cấu hình "
            f"path/method."
        )

    # KV unresolved check — collect message vào errors list (KHÔNG raise).
    # Snapshot freeze ở trên đã ghi requires_manual_override=True khi engine
    # cần manual; flush + commit ở `if errors:` branch persist signal đó cho
    # admin/manager override draft.
    kv_error = _kv_unresolved_error_message(
        profile.priority_resolution_snapshot, profile_id
    )
    if kv_error:
        errors.append(kv_error)

    # Gap #3 — applicant identity + permanent-address completeness (production
    # scope, locked 2026-05-26). Submit already gates citizen_id / family_info /
    # academic_history / docs / scores / KV but NOT name / phone / permanent
    # address. Scope: full_name + phone + permanent_province + permanent_ward.
    # NOT district (the 2025 2-tier reform dropped the district level — FE mode
    # "current" doesn't collect it, prod rows leave it empty). The ward must be a
    # CURRENT-era commune node (administrative_nodes valid_to IS NULL), not merely
    # present: a legacy-era code can't resolve KV and is a deprecated address, so
    # submit fail-closes and forces re-selecting the current commune.
    if not (profile.full_name or "").strip():
        errors.append("Chưa nhập họ tên thí sinh (full_name)")
    if not (profile.phone or "").strip():
        errors.append("Chưa nhập số điện thoại (phone)")
    if not (profile.permanent_province or "").strip():
        errors.append("Thiếu địa chỉ thường trú: Tỉnh/Thành phố")
    if not (profile.permanent_ward or "").strip():
        errors.append("Thiếu địa chỉ thường trú: Phường/Xã")
    elif not await _is_current_era_ward(db, profile.permanent_commune_code):
        errors.append(
            "Phường/Xã thường trú phải theo địa giới hiện hành (2 cấp, sau "
            "01/07/2025). Vui lòng chọn lại Phường/Xã hiện tại."
        )

    # =========================================================================
    # Fast-track prepay/giữ chỗ — submit-with-document-debt waiver (C1)
    # =========================================================================
    # SUBTRACTION (not enumeration): ``errors`` already holds EVERY blocking
    # validation error EXCEPT truly-missing mandatory docs (those were split
    # into ``missing_doc_errors`` / ``missing_doc_codes`` above). The early
    # hard ``raise`` gates (multi-NV-no-choice :5426, round cutoff :5454,
    # status!=draft :5433, eligibility :5483, atomic quota below) already
    # fired and are NOT document errors → still block regardless.
    #
    # We may transition to ``submitted`` + record a document_debt snapshot
    # ONLY when ALL of:
    #   - acknowledge_missing_docs is True
    #   - a non-empty document_debt_reason is supplied
    #   - the actor is STAFF (officer/manager/admin) — never candidate/
    #     magic-link (current_user=None) nor accountant/user roles
    #   - there is at least one truly-missing mandatory doc to waive
    #   - ``errors`` (all other validation) is empty
    # Otherwise the missing-doc errors are folded back into ``errors`` and the
    # profile stays in draft exactly as before (defaults reproduce old flow).
    _actor_is_staff = current_user is not None and current_user.role in (
        UserRole.OFFICER,
        UserRole.MANAGER,
        UserRole.ADMIN,
    )
    _reason_clean = (document_debt_reason or "").strip()
    _waive_document_debt = bool(
        acknowledge_missing_docs
        and _reason_clean
        and _actor_is_staff
        and missing_doc_codes
        and not errors
    )

    if _waive_document_debt:
        # Persist the debt snapshot on the dedicated column (NOT applied_rules
        # — see model comment / ardockeys01 trigger). The FE badge counts the
        # COMPUTED outstanding_debt_codes (codes ∩ docs still missing), so the
        # debt self-resolves once the owed docs are uploaded; this snapshot is
        # the audit record of "was once owed + why".
        profile.document_debt = {
            "codes": list(missing_doc_codes),
            "reason": _reason_clean,
            "by_user_id": current_user.id,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        log.info(
            "admission_submit_with_document_debt",
            profile_id=profile_id,
            user_id=current_user.id,
            waived_doc_codes=missing_doc_codes,
        )
    else:
        # Not a valid waiver → missing docs block submit like every other
        # error. Combine so the FE sees the full list (missing docs included).
        errors = errors + missing_doc_errors

    # ✅ CRITICAL FIX #1: Submit should transition to SUBMITTED, not APPROVED/REJECTED
    # Per ADMISSION_STATE_MACHINE: draft → submitted (wait for Manager approval)
    # Validation errors should NOT change status - stay in draft for user to fix
    if errors:
        # Keep in draft - user needs to fix validation errors
        await db.flush()  # No status change

        log.warning(
            "Admission profile submission failed - validation errors",
            profile_id=profile_id,
            user_id=current_user.id if current_user else None,
            errors_count=len(errors),
            errors=errors,
        )

        return (
            {
                "status": "draft",  # ✅ FIX: Stay in draft, not "rejected"
                "message": None,
                "validation_errors": errors,  # ✅ FIX: Match schema field name
            },
            None,  # No post-commit callback when validation failed
        )
    else:
        # Phase 2 v8.2 PR-2B v2 — Atomic submit per-path counter (SPEC
        # §4.1 line 4100-4107 pattern). Tier 2 quota guard: increment
        # admission_path.submission_count atomically, block if
        # round_quota exhausted. NULL round_quota = unbounded.
        # Backward-compat: legacy profiles (applied_rules KHÔNG có
        # admission_path_id) skip atomic increment.
        applied_rules_pre = profile.applied_rules or {}
        path_id_raw = applied_rules_pre.get("admission_path_id")
        if path_id_raw is not None:
            try:
                path_id_int = int(path_id_raw)
            except (TypeError, ValueError):
                path_id_int = None
            if path_id_int is not None:
                from sqlalchemy import text
                atomic_stmt = text(
                    "UPDATE admission_path "
                    "SET submission_count = submission_count + 1 "
                    "WHERE id = :path_id "
                    "  AND (round_quota IS NULL "
                    "       OR submission_count < round_quota) "
                    "RETURNING submission_count, round_quota"
                )
                inc_result = await db.execute(
                    atomic_stmt, {"path_id": path_id_int}
                )
                inc_row = inc_result.first()
                if inc_row is None:
                    log.warning(
                        "atomic_submit_blocked_quota_exhausted",
                        profile_id=profile.id,
                        admission_path_id=path_id_int,
                    )
                    raise BadRequest(
                        f"Đã đủ chỉ tiêu nộp hồ sơ cho đường tuyển sinh "
                        f"{path_id_int}. Vui lòng chọn đợt tuyển sinh khác "
                        f"hoặc liên hệ admin."
                    )

        # ✅ FIX: Submit validation passed → Move to SUBMITTED (not APPROVED).
        # transition() validates DRAFT → SUBMITTED via the state machine
        # and raises BusinessRuleViolation if illegal — caller maps to
        # 400 the same way BadRequest did before.
        #
        # ``skip_dispatch=True`` is retained: this function builds its
        # own ``_post_commit_dispatch`` callback at the bottom of the
        # success branch (V3 ``(result, callback)`` tuple contract,
        # post-magic-link wire FU). Letting state_transition() also
        # dispatch ADMISSION_PROFILE_SUBMITTED would duplicate the
        # event. The single source of truth lives in our callback so
        # APPLICATION_STATUS_CHANGED + ADMISSION_PROFILE_SUBMITTED
        # always fire side-by-side AFTER ``db.commit()``.

        # Q9 #07 Phase E.4 reviewer v4 — freeze + KV check đã chạy ở bước
        # validation phía trên. Nếu reach đây tức snapshot có rule_applied
        # success + kv_resolved set (whitelist pass). Atomic increment +
        # state transition chỉ fire khi đảm bảo no errors.

        try:
            profile, _ = await state_transition(
                db,
                profile,
                "submitted",
                actor=current_user,
                source="api",
                skip_dispatch=True,
            )
        except BusinessRuleViolation as e:
            raise BadRequest(str(e))

        # ✅ PIPELINE SYNC: Create system consultation for admission milestone
        if profile.lead:
            await _create_admission_milestone_consultation(
                db=db,
                lead=profile.lead,
                event="profile_submitted",
                actor=current_user,
                profile_id=profile_id,
            )

        # Q9 #07 Phase E.4 Decision #2 — audit row khi officer submit với
        # UT codes ghi nhận nhưng chưa upload minh chứng. Extracted helper
        # (audit_warning_dismissed_if_missing) cho unit test isolation.
        await _audit_warning_dismissed_if_missing(db, profile_id, profile, current_user)

        await db.flush()

        # Gap #2 fix — submit-sync fallback (mirror approve/reject/enroll).
        # _create_admission_milestone_consultation above SKIPS the lead pipeline
        # update when no officer is resolvable (magic-link submit → actor=None,
        # of a lead whose assigned_officer_id is also None). sync_lead_from_admission
        # is officer-independent, so it still floors the lead to sts07
        # ("Đã tiếp nhận") in that case. When the milestone DID run (officer
        # resolvable) the lead is already at sts07 and this is an idempotent
        # no-op (sync skips when consultation_status_id already == target).
        if profile.lead:
            from .lead_admission_sync import sync_lead_from_admission

            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=current_user.id if current_user else None,
                reason="Auto-sync on profile submit (magic-link/no-officer fallback)",
            )

        log.info(
            "Admission profile submitted successfully",
            profile_id=profile_id,
            user_id=current_user.id if current_user else None,
            citizen_id=profile.citizen_id,
        )

        # Capture payload fields at flush time so the post-commit
        # callback does not depend on the session staying loaded.
        # Mirrors the V2 router shape (admissions.py post-#293) so the
        # candidate magic-link flow and the officer dashboard flow
        # produce identical APPLICATION_STATUS_CHANGED + ADMISSION_
        # PROFILE_SUBMITTED notifications. ``actor_id``/``actor_name``
        # fall back to None/"Hệ thống (magic-link)" when current_user
        # is the magic-link self-service path (Item Magic-Link FU).
        from .notification_dispatcher import (
            safe_dispatch as _safe_dispatch,
            rooms_for_lead as rooms_for_lead_helper,
        )

        _capture_lead_id = profile.lead_id
        _capture_lead = profile.lead  # eager-loaded above via selectinload
        _capture_actor_id = current_user.id if current_user else None
        _capture_actor_name = (
            (current_user.full_name or current_user.username)
            if current_user
            else "Hệ thống (magic-link)"
        )
        _capture_submitted_at_iso = (
            profile.updated_at.isoformat()
            if profile.updated_at
            else datetime.now(timezone.utc).isoformat()
        )
        _capture_rooms = rooms_for_lead_helper(_capture_lead)

        async def _post_commit_dispatch() -> None:
            await _safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": _capture_lead_id,
                    "old_status": "draft",
                    "new_status": "submitted",
                    "actor_id": _capture_actor_id,
                    "actor_name": _capture_actor_name,
                },
                dedupe_key=f"admission_profile_submitted:{profile_id}",
                rooms=_capture_rooms,
            )
            await _safe_dispatch(
                db=db,
                event=SystemEvents.ADMISSION_PROFILE_SUBMITTED,
                payload={
                    "application_id": profile_id,
                    "lead_id": _capture_lead_id,
                    "old_status": "draft",
                    "new_status": "submitted",
                    "actor_id": _capture_actor_id,
                    "submitted_at_iso": _capture_submitted_at_iso,
                },
                dedupe_key=f"admission:{profile_id}:submitted",
                rooms=_capture_rooms,
            )

        return (
            {
                "status": "submitted",  # ✅ FIX: submitted status
                "message": "Hồ sơ đã được nộp thành công. Chờ phê duyệt từ Manager.",
                "validation_errors": None,  # ✅ FIX: Match schema field name
            },
            _post_commit_dispatch,
        )


async def get_document_file_for_download(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    document_id: int,
    actor_user_id: int,
    actor_ip: Optional[str] = None,
    actor_user_agent: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Resolve a downloadable file for a ProfileDocument under ``profile``.

    PR1 Commit 1 (A01/A05/A09). IDOR is enforced upstream by the router dep
    ``get_admission_for_user_read`` (3-tier scope, fake-404). Here we
    additionally:

    - bind the document to the authorized profile (``doc.profile_id ==
      profile.id``) and require a real ``file_path`` — any miss raises
      ``ResourceNotFoundError`` (→404) so existence is never leaked;
    - apply a defense-in-depth path guard so a tampered ``file_path`` can
      never escape ``uploads/admissions/{profile.id}/``;
    - derive ``media_type`` from a server-controlled extension allowlist
      (ProfileDocument persists no MIME type — never trust a stored/client
      value);
    - record a ``downloaded`` audit row (Gap 1 — A09). It is flushed here;
      the router commits it before the FileResponse streams.

    Returns ``(abs_path, safe_basename, media_type)``.
    """
    import os
    from app.repositories import AdmissionRepository

    repo = AdmissionRepository(db)
    doc = await repo.get_document_by_id(document_id)
    if doc is None or doc.profile_id != profile.id or not doc.file_path:
        raise ResourceNotFoundError("Document not found")

    base_dir = f"uploads/admissions/{profile.id}"
    abs_path = _resolve_under(base_dir, doc.file_path)
    if abs_path is None or not os.path.isfile(abs_path):
        log.warning(
            "admission document download: file missing or path invalid",
            profile_id=profile.id,
            document_id=document_id,
            file_path=doc.file_path,
        )
        raise ResourceNotFoundError("Document not found")

    # media_type from a server-controlled extension allowlist (Gap 3 —
    # A05/A03). Extension is set from sniffed magic bytes at upload time, so
    # it is trustworthy; no persisted/client MIME value is ever used.
    ext = os.path.splitext(abs_path)[1].lower()
    media_type = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(ext, "application/octet-stream")

    # safe_basename: strip CR/LF so the filename can't smuggle header content
    # (Starlette still applies RFC-compliant Content-Disposition encoding).
    safe_basename = os.path.basename(abs_path).replace("\r", "").replace("\n", "")

    # Audit (Gap 1 — A09): record who downloaded which document. db.flush is
    # inside log_document_action; the router commits before streaming.
    from .document_audit_service import log_document_action, DocumentAction
    await log_document_action(
        db=db,
        profile_document_id=doc.id,
        action=DocumentAction.DOWNLOADED,
        actor_user_id=actor_user_id,
        ip_address=actor_ip,
        user_agent=actor_user_agent,
    )

    return abs_path, safe_basename, media_type


async def upload_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    file: Any,  # UploadFile
    current_user: models.User,
    actual_submission_format: Optional[str] = None,
) -> tuple[models.AdmissionProfile, Callable]:
    """
    Upload a document for an admission profile.

    Workflow:
    1. Verify access (IDOR).
    2. Verify profile status (draft/rejected/revision_requested).
    3. Verify doc_code exists in ProfileDocument.
    4. Stage file to ``uploads/admissions/{id}/.staging.{uuid}.{ext}``
       (NOT yet at the final path the DB will reference).
    5. Update ProfileDocument with the FINAL ``file_path`` it will live
       at after promotion + ``status='uploaded'`` + format.
    6. Re-compute validation_summary, audit-log the upload.

    ADM-007: filesystem mutations must not become permanent before the
    DB commit. The service writes to a staging path and the caller
    receives a ``finalize(committed: bool)`` callback that does the
    real promotion (or cleanup) AFTER the router's ``db.commit()``
    settles. See the return shape below.

    IMPORTANT: This function does NOT commit the transaction. Router
    must call ``await db.commit()`` and then ``await finalize(True)``;
    on commit failure the router must call ``await finalize(False)``
    instead. The caller-side pattern lives in
    ``app/routers/admissions.py::upload_document``.

    Args:
        actual_submission_format: Type of document submitted (original | certified_copy | photo)
            User must declare what type of physical document they scanned/uploaded.

    Returns:
        Tuple of:
          - ``AdmissionProfile`` with updated validation_summary.
          - ``finalize(committed: bool)`` async callback. When
            ``committed=True``: rename staging → final, then delete
            the previous file (if any). When ``committed=False``:
            delete the staging file. Idempotent best-effort: each
            branch checks ``os.path.exists`` before acting and never
            raises on the cleanup branch.

    Security:
    - Path Traversal: filename sanitization (inherent in modern frameworks but good practice)
    - File Type: Should be validated at Router level generally, but here we accept generic
    """
    # Initialize repository
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    profile = await get_profile(db, profile_id, current_user)

    # BR1 (2026-04-29): the profile-state guard now lives inside
    # ``DocumentActionPolicy`` (see ``APPLICANT_DOC_MUTATION_STATES``)
    # so the FE flag and BE gate stay in lockstep automatically.
    # The previous hand-rolled ``profile.status not in [draft, rejected,
    # revision_requested]`` check would also reject ``submitted`` /
    # ``resubmitted`` — a real workflow bug since applicants do post
    # missing evidence between submit and the manager's first review.

    # Find document record early — needed for doc_status-based guard check.
    doc_record = await admission_repo.get_document_by_type(profile_id, doc_code)
    if not doc_record:
        raise BadRequest(f"Document code '{doc_code}' not found in profile documents")

    _authorize_document_action(
        action="upload",
        profile=profile,
        doc_status=doc_record.status,
        doc_code=doc_code,
        current_user=current_user,
    )

    # File validation constants
    ALLOWED_CONTENT_TYPES = ["application/pdf", "image/jpeg", "image/png"]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Validate file type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise BadRequest(
            f"Invalid file type '{file.content_type}'. "
            "Allowed: PDF, JPG, PNG"
        )

    # Validate file size (read file to check size)
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning

    if file_size > MAX_FILE_SIZE:
        # W7-B.c2 fix 2026-05-16: precise byte/MB display.
        # `:.1f` rounded 10485761 bytes (10MB + 1 byte) → "10.0MB"
        # giống max → user confused "tại sao reject?". Use exact bytes
        # + 3-decimal MB so display KHÁC visually từ max.
        size_mb_exact = file_size / (1024 * 1024)
        max_mb_exact = MAX_FILE_SIZE / (1024 * 1024)
        raise BadRequest(
            f"File too large: {file_size:,} bytes ({size_mb_exact:.3f}MB). "
            f"Maximum allowed: {MAX_FILE_SIZE:,} bytes ({max_mb_exact:.0f}MB)."
        )

    # ADM-019: content_type and extension are client-controlled. Sniff
    # the first bytes of the actual stream and reject mismatches so an
    # attacker cannot upload a .exe with content_type=application/pdf.
    sniffed_kind = _sniff_document_signature(file.file)
    if sniffed_kind is None:
        raise BadRequest(
            "Tệp tải lên không phải PDF, JPG hoặc PNG hợp lệ "
            "(magic bytes không khớp)."
        )
    expected_content_type = {
        "pdf": "application/pdf",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }[sniffed_kind]
    if file.content_type != expected_content_type:
        raise BadRequest(
            f"Content-Type '{file.content_type}' không khớp nội dung "
            f"thực tế ({expected_content_type})."
        )

    # doc_record was already fetched above for the authz guard — no need to re-query.

    # Prepare file paths with security measures
    import os
    import shutil
    import uuid

    upload_dir = f"uploads/admissions/{profile_id}"
    os.makedirs(upload_dir, exist_ok=True)

    # ADM-007: capture the previous file path so the post-commit
    # callback can delete it. We do NOT delete it here — that would
    # make the FS change permanent before the DB commit settles.
    old_file_path = doc_record.file_path

    # ADM-019: extension is taken from the sniffed content, not from
    # the client-supplied filename, so we never fall back to ".bin" on
    # an official document upload.
    extension_for_kind = {"pdf": ".pdf", "jpeg": ".jpg", "png": ".png"}
    file_extension = extension_for_kind[sniffed_kind]

    unique_id = uuid.uuid4().hex[:12]
    unique_filename = f"{doc_code}_{unique_id}{file_extension}"
    final_path = f"{upload_dir}/{unique_filename}"
    # ADM-007: stage to a sibling path in the same directory so the
    # post-commit promotion is a single ``os.rename`` (atomic on the
    # same filesystem). Hidden by leading ``.staging.`` prefix so it
    # does not show up in casual ``ls`` of the uploads dir.
    staging_path = f"{upload_dir}/.staging.{unique_id}{file_extension}"

    # PR1 Commit 1 (defense-in-depth — A05): doc_code is bound to a catalog
    # ConfigDocumentType, but still guard the built paths so neither the final
    # nor staging path can escape this profile's upload dir.
    for _candidate in (final_path, staging_path):
        if _resolve_under(upload_dir, _candidate) is None:
            log.critical(
                "🚨 PATH TRAVERSAL ATTEMPT (admission document upload)",
                profile_id=profile_id,
                doc_code=doc_code,
                candidate=_candidate,
            )
            raise BadRequest("Invalid file path detected.")

    # Stage the file to the staging path. If this fails, clean up the
    # partially-written staging file before raising — we never let
    # filesystem state diverge from "no upload happened".
    try:
        with open(staging_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(
            "File staging failed",
            error=str(e),
            profile_id=profile_id,
            staging_path=staging_path,
        )
        if os.path.exists(staging_path):
            try:
                os.remove(staging_path)
            except OSError:  # pragma: no cover — best-effort cleanup
                pass
        raise BadRequest("Failed to save file")

    # ADM-007: from this point on, the staging file is on disk.
    # Anything that raises BEFORE we return ``finalize`` to the router
    # would leak the staging file (the router never sees the callback
    # to clean it up). Wrap the entire post-staging block — DB
    # update, flush, refresh, frontend-field compute, audit log —
    # so any exception triggers a best-effort cleanup before
    # re-raising the original error.
    try:
        # Update ProfileDocument record to point at the FINAL path.
        # The staging file lives at ``staging_path`` until
        # ``finalize(True)`` renames it; readers that hit the DB
        # before commit + finalize will see ``final_path`` but the
        # file will not exist there yet. That is acceptable because
        # the only caller that observes this window is the router
        # itself (between ``db.flush`` and ``db.commit``), and routers
        # do not serve reads to clients in that window.
        uploaded_at_dt = datetime.now(timezone.utc)
        await admission_repo.update_document_status(
            profile_id=profile_id,
            document_type_code=doc_code,
            status="uploaded",
            file_path=final_path,
            uploaded_at=uploaded_at_dt.isoformat(),
            actual_submission_format=actual_submission_format
        )

        profile.updated_at = uploaded_at_dt

        await db.flush()

        # ✅ G2 (ADM-032 partial) — populate full response contract so the
        # mutation response carries permissions / available_actions /
        # eligibility_status / completion_percent etc. matching a
        # subsequent GET. Replaces the previous stand-alone
        # ``_compute_frontend_fields`` call which only set part of the
        # frontend computed surface and left FE having to refetch.
        from app.repositories import AdmissionRepository
        admission_repo_refresh = AdmissionRepository(db)
        documents = await admission_repo_refresh.get_all_documents(profile_id)
        await _populate_response_fields(
            db, profile, current_user, documents=documents
        )

        # ✅ AUDIT LOG: Track document upload
        from .document_audit_service import log_document_upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_record.id,
            actor_user_id=current_user.id,
            old_status=doc_record.status if doc_record.status != "uploaded" else "missing",
            new_file_path=final_path,
            original_filename=file.filename or "unknown",
            file_size_bytes=file_size,
            content_type=file.content_type,
            old_file_path=old_file_path,
            declared_format=actual_submission_format,
        )
    except Exception as exc:
        # Service blew up between stage-write and return-finalize.
        # The router is never going to see ``finalize`` so we own the
        # cleanup ourselves. Best-effort — never mask the original
        # exception.
        log.error(
            "ADM-007 upload service failed after staging write; "
            "cleaning staging file before re-raising",
            error=str(exc),
            profile_id=profile_id,
            staging_path=staging_path,
        )
        if os.path.exists(staging_path):
            try:
                os.remove(staging_path)
            except OSError as cleanup_error:
                log.warning(
                    "Failed to clean staging file after service error",
                    staging_path=staging_path,
                    cleanup_error=str(cleanup_error),
                )
        raise

    log.info(
        "Document staged with audit log (awaiting commit)",
        profile_id=profile_id,
        doc_code=doc_code,
        staging_path=staging_path,
        final_path=final_path,
        user_id=current_user.id,
    )

    async def finalize(committed: bool) -> None:
        """ADM-007 file-ops finalize callback.

        - ``committed=True``: rename staging → final, then delete the
          previous file (if any). If the rename fails (disk full,
          permission, race), we raise so the router can surface a 500
          and the operator can investigate. The old file is kept in
          place on rename failure so the user can re-upload without
          first losing their existing copy.
        - ``committed=False``: delete the staging file. Best-effort:
          warns on failure, never raises (the router is unwinding).

        Idempotent: each branch checks ``os.path.exists`` before
        acting so a double-call (rare, but possible if the router
        retries) does not raise.
        """
        if not committed:
            if os.path.exists(staging_path):
                try:
                    os.remove(staging_path)
                    log.info(
                        "Staging file cleaned up after rollback",
                        staging_path=staging_path,
                    )
                except OSError as e:
                    log.warning(
                        "Failed to clean staging file after rollback",
                        staging_path=staging_path,
                        error=str(e),
                    )
            return

        # committed=True: promote staging → final. Use ``os.replace``
        # rather than ``os.rename`` so the semantics are atomic across
        # both POSIX and Windows even when the destination already
        # exists (rare, but possible if the same uuid collides on a
        # retry).
        try:
            if os.path.exists(staging_path):
                os.replace(staging_path, final_path)
                log.info(
                    "Document file promoted from staging post-commit",
                    final_path=final_path,
                )
            elif not os.path.exists(final_path):
                # Neither staging nor final exists — something has gone
                # very wrong (concurrent finalize, or the staging file
                # was removed out-of-band). Surface as an error rather
                # than silently leaving the DB pointing at a missing
                # file.
                raise OSError(
                    f"ADM-007 finalize: neither staging nor final "
                    f"file exists for profile={profile_id} "
                    f"doc={doc_code}"
                )
            # else: final already exists (idempotent re-call) — nothing
            # to do. Continue to old-file cleanup below.
        except OSError as e:
            log.error(
                "ADM-007 finalize promote failed; old file kept intact",
                staging_path=staging_path,
                final_path=final_path,
                old_file_path=old_file_path,
                error=str(e),
            )
            raise

        # Old-file delete is best-effort: the new file is already in
        # place + DB committed, so a leftover old file is at worst
        # storage waste, not a correctness issue.
        if old_file_path and old_file_path != final_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                log.info(
                    "Old document file deleted post-commit",
                    old_path=old_file_path,
                )
            except OSError as e:
                log.warning(
                    "Failed to delete old file post-commit",
                    old_path=old_file_path,
                    error=str(e),
                )

    return profile, finalize


# =============================================================================
# Q9 #07 Phase E.4 — Priority evidence document upload (PR-2 Item #1)
# =============================================================================


async def upload_priority_evidence_document(
    db: AsyncSession,
    profile_id: int,
    sub_code: str,
    file: Any,  # UploadFile
    current_user: models.User,
) -> tuple[models.AdmissionProfile, Callable]:
    """Upload UT evidence document cho 1 sub_code (Phase E.4 PR-2).

    Sibling function của upload_document (path docs). Reason for sibling
    instead of extending: ADM-007 staging/finalize semantics + DocumentAction
    Policy guards trên path docs khác với priority evidence (catalog-driven
    không phải FK ConfigDocumentType).

    Workflow:
    1. Profile authz qua get_profile() (IDOR).
    2. Profile status guard via APPLICANT_DOC_MUTATION_STATES.
    3. sub_code MUST be in profile.priority_object_codes (officer ghi nhận
       diện UT TRƯỚC khi scan giấy).
    4. sub_code MUST exist trong PriorityObjectConfig catalog year.
    5. File validation: PDF/JPG/PNG + ≤10MB + magic-byte sniff (mirror
       upload_document).
    6. Stage file to ``.staging.{uuid}.{ext}`` (ADM-007 — promote post-commit).
    7. Find-or-create ProfileDocument row (category='priority_evidence',
       priority_sub_code=sub_code, document_type_id=NULL).
    8. Return (profile, finalize_callback) tuple. Router commits THEN calls
       finalize(committed=True) to promote staging → final. Commit fail →
       finalize(False) cleans staging.

    Returns:
        (AdmissionProfile, async finalize callback). See upload_document
        docstring for finalize contract details.

    Raises:
        ResourceNotFoundError: profile IDOR fail.
        BusinessRuleViolation: status guard / sub_code not in codes /
            sub_code not in catalog.
        BadRequest: file type / size / magic byte mismatch.
    """
    from app.repositories import AdmissionRepository
    from .admission_document_policy import APPLICANT_DOC_MUTATION_STATES

    admission_repo = AdmissionRepository(db)

    profile = await get_profile(db, profile_id, current_user)

    # Guard 1: profile must be in writeable state
    if profile.status not in APPLICANT_DOC_MUTATION_STATES:
        raise BusinessRuleViolation(
            f"Cannot upload priority evidence trong status '{profile.status}'. "
            f"Allowed: {sorted(APPLICANT_DOC_MUTATION_STATES)}."
        )

    # Guard 2: sub_code MUST be in profile.priority_object_codes
    # Officer ghi nhận diện UT TRƯỚC qua AdmissionProfileUpdate, mới scan giấy.
    priority_codes = list(profile.priority_object_codes or [])
    if sub_code not in priority_codes:
        raise BusinessRuleViolation(
            f"Sub-code '{sub_code}' không có trong profile.priority_object_codes "
            f"{priority_codes}. Officer phải ghi nhận diện UT trước khi upload "
            f"minh chứng."
        )

    # Guard 3: sub_code MUST exist trong catalog year
    catalog_check = await db.execute(
        select(models.PriorityObjectConfig.id)
        .where(
            models.PriorityObjectConfig.academic_year == profile.academic_year,
            models.PriorityObjectConfig.sub_code == sub_code,
        )
    )
    if catalog_check.scalar_one_or_none() is None:
        raise BusinessRuleViolation(
            f"Sub-code '{sub_code}' không có trong PriorityObjectConfig "
            f"catalog year {profile.academic_year}. Admin cần seed config."
        )

    # File validation (mirror upload_document)
    ALLOWED_CONTENT_TYPES = ["application/pdf", "image/jpeg", "image/png"]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise BadRequest(
            f"Invalid file type '{file.content_type}'. Allowed: PDF, JPG, PNG"
        )

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_FILE_SIZE:
        size_mb_exact = file_size / (1024 * 1024)
        max_mb_exact = MAX_FILE_SIZE / (1024 * 1024)
        raise BadRequest(
            f"File too large: {file_size:,} bytes ({size_mb_exact:.3f}MB). "
            f"Maximum allowed: {MAX_FILE_SIZE:,} bytes ({max_mb_exact:.0f}MB)."
        )

    sniffed_kind = _sniff_document_signature(file.file)
    if sniffed_kind is None:
        raise BadRequest(
            "Tệp tải lên không phải PDF, JPG hoặc PNG hợp lệ (magic bytes không khớp)."
        )
    expected_content_type = {
        "pdf": "application/pdf",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }[sniffed_kind]
    if file.content_type != expected_content_type:
        raise BadRequest(
            f"Content-Type '{file.content_type}' không khớp nội dung thực tế "
            f"({expected_content_type})."
        )

    # Find existing priority_evidence row (for re-upload scenario)
    existing_doc_q = await db.execute(
        select(models.ProfileDocument).where(
            models.ProfileDocument.profile_id == profile_id,
            models.ProfileDocument.category == "priority_evidence",
            models.ProfileDocument.priority_sub_code == sub_code,
        )
    )
    doc_row = existing_doc_q.scalar_one_or_none()

    # File path setup (mirror upload_document ADM-007 staging pattern)
    import os
    import shutil
    import uuid

    upload_dir = f"uploads/admissions/{profile_id}"
    os.makedirs(upload_dir, exist_ok=True)

    old_file_path = doc_row.file_path if doc_row else None

    extension_for_kind = {"pdf": ".pdf", "jpeg": ".jpg", "png": ".png"}
    file_extension = extension_for_kind[sniffed_kind]

    unique_id = uuid.uuid4().hex[:12]
    unique_filename = f"priority_{sub_code}_{unique_id}{file_extension}"
    final_path = f"{upload_dir}/{unique_filename}"
    staging_path = f"{upload_dir}/.staging.{unique_id}{file_extension}"

    # PR1 Commit 1 (defense-in-depth — A05): sub_code is constrained to the
    # PriorityObjectConfig catalog above, but still guard the built paths so a
    # malformed catalog sub_code can never escape the upload dir.
    for _candidate in (final_path, staging_path):
        if _resolve_under(upload_dir, _candidate) is None:
            log.critical(
                "🚨 PATH TRAVERSAL ATTEMPT (admission priority evidence upload)",
                profile_id=profile_id,
                sub_code=sub_code,
                candidate=_candidate,
            )
            raise BadRequest("Invalid file path detected.")

    # Stage file
    try:
        with open(staging_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(
            "Priority evidence file staging failed",
            error=str(e),
            profile_id=profile_id,
            sub_code=sub_code,
            staging_path=staging_path,
        )
        if os.path.exists(staging_path):
            try:
                os.remove(staging_path)
            except OSError:
                pass
        raise BadRequest("Failed to save file")

    # Post-staging: DB mutations wrapped in cleanup guard (mirror upload_document)
    try:
        uploaded_at_dt = datetime.now(timezone.utc)

        if doc_row is None:
            # Create new priority_evidence ProfileDocument row.
            # document_type_id=NULL acceptable per Phase E.4 q9_07_e4a migration
            # (ck_path_requires_doc_type fires only khi category='path').
            doc_row = models.ProfileDocument(
                profile_id=profile_id,
                document_type_id=None,
                category="priority_evidence",
                priority_sub_code=sub_code,
                status="uploaded",
                file_path=final_path,
                uploaded_at=uploaded_at_dt,
            )
            db.add(doc_row)
        else:
            # Re-upload: replace file. Reset status to 'uploaded' nếu was
            # rejected/verified (officer phải verify lại sau re-upload).
            doc_row.file_path = final_path
            doc_row.status = "uploaded"
            doc_row.uploaded_at = uploaded_at_dt
            doc_row.verified_at = None
            doc_row.verified_by = None
            doc_row.rejected_at = None
            doc_row.rejected_by = None
            doc_row.rejection_reason = None

            # P1 fix (audit cycle PR-2): re-upload MUST also reset evidence
            # JSONB status. Engine reads bonus eligibility từ
            # ``priority_object_evidence[code].status == 'verified'``
            # (priority_override_service._recompute_ut_verified_bucket line 380
            # + admissions_v2.preview_priority_kv line 795). Nếu chỉ reset
            # document_row mà KHÔNG touch JSONB → file mới uploaded nhưng
            # engine vẫn tính bonus theo verify cũ → stale bonus contract
            # violation.
            #
            # Re-upload semantics: file changed → officer phải re-verify.
            # Reset evidence entry về pending + clear verifier/rejecter
            # metadata + clear paper_only_verification flag. Preserve
            # requested_at (candidate claim timestamp unchanged).
            evidence_dict = dict(profile.priority_object_evidence or {})
            prev_entry = dict(evidence_dict.get(sub_code) or {})
            prev_status = prev_entry.get("status")
            if prev_status in ("verified", "rejected"):
                evidence_dict[sub_code] = {
                    "status": "pending",
                    "document_id": None,
                    "requested_at": prev_entry.get("requested_at"),
                    "verified_by": None,
                    "verified_at": None,
                    "reject_reason": None,
                    "paper_only_verification": False,
                }
                profile.priority_object_evidence = _strip_display_fields_from_evidence(
                    evidence_dict
                )

                # Recompute ut_verified_bucket — if reset code was the applied
                # verified, bucket falls back to next-highest verified (or null).
                # Lazy import to avoid circular (priority_override_service
                # imports from admission_service at top).
                from app.services.priority_override_service import (
                    _recompute_ut_verified_bucket,
                )
                new_bucket = await _recompute_ut_verified_bucket(db, profile)
                snapshot = dict(profile.priority_resolution_snapshot or {})
                snapshot["ut_verified_bucket"] = new_bucket
                profile.priority_resolution_snapshot = snapshot

                # Version bump — JSONB mutation requires optimistic lock advance
                # so concurrent verify/reject sees stale token + retries.
                profile.version += 1

                log.info(
                    "Priority evidence re-upload reset JSONB status",
                    profile_id=profile_id,
                    sub_code=sub_code,
                    prev_status=prev_status,
                    bucket_after=new_bucket.get("applied_code"),
                    version_after=profile.version,
                )

        profile.updated_at = uploaded_at_dt
        await db.flush()

        # Populate response fields (transient projections)
        documents = await admission_repo.get_all_documents(profile_id)
        await _populate_response_fields(
            db, profile, current_user, documents=documents
        )
    except Exception as exc:
        log.error(
            "Priority evidence upload service failed after staging write; "
            "cleaning staging file before re-raising",
            error=str(exc),
            profile_id=profile_id,
            sub_code=sub_code,
            staging_path=staging_path,
        )
        if os.path.exists(staging_path):
            try:
                os.remove(staging_path)
            except OSError as cleanup_error:
                log.warning(
                    "Failed to clean staging file after service error",
                    staging_path=staging_path,
                    cleanup_error=str(cleanup_error),
                )
        raise

    log.info(
        "Priority evidence staged (awaiting commit)",
        profile_id=profile_id,
        sub_code=sub_code,
        staging_path=staging_path,
        final_path=final_path,
        user_id=current_user.id,
    )

    async def finalize(committed: bool) -> None:
        """ADM-007 file-ops finalize callback for priority evidence upload."""
        if not committed:
            if os.path.exists(staging_path):
                try:
                    os.remove(staging_path)
                    log.info(
                        "Priority evidence staging file cleaned up after rollback",
                        staging_path=staging_path,
                    )
                except OSError as e:
                    log.warning(
                        "Failed to clean priority evidence staging file after rollback",
                        staging_path=staging_path,
                        error=str(e),
                    )
            return

        # committed=True: promote staging → final.
        try:
            if os.path.exists(staging_path):
                os.replace(staging_path, final_path)
                log.info(
                    "Priority evidence file promoted from staging post-commit",
                    final_path=final_path,
                )
            elif not os.path.exists(final_path):
                raise OSError(
                    f"ADM-007 finalize: neither staging nor final file "
                    f"exists for profile={profile_id} sub_code={sub_code}"
                )
        except OSError as e:
            log.error(
                "Priority evidence finalize promote failed; old file kept intact",
                staging_path=staging_path,
                final_path=final_path,
                old_file_path=old_file_path,
                error=str(e),
            )
            raise

        # Best-effort old file cleanup post-commit
        if old_file_path and old_file_path != final_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                log.info(
                    "Old priority evidence file deleted post-commit",
                    old_path=old_file_path,
                )
            except OSError as e:
                log.warning(
                    "Failed to delete old priority evidence file post-commit",
                    old_path=old_file_path,
                    error=str(e),
                )

    return profile, finalize


async def confirm_document_format(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    format_type: str,
    current_user: models.User,
) -> models.AdmissionProfile:
    """
    Confirm physical format of a document and mark as verified.

    This performs the full verification workflow:
    1. Updates verified_format (original | certified_copy | photo)
    2. Sets status to 'verified'
    3. Records verification timestamp and officer
    4. Re-computes validation_summary with updated document status

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        format_type: original | certified_copy | photo
        current_user: Officer performing verification

    Returns:
        AdmissionProfile with updated validation_summary

    Raises:
        ResourceNotFoundError: Document not found
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # 1. Access Check
    profile = await get_profile(db, profile_id, current_user)

    # PR #5 guard — same rule matrix as the can_verify flag on documents_checklist.
    existing = await admission_repo.get_document_by_type(profile_id, doc_code)
    if not existing:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found")
    _authorize_document_action(
        action="verify",
        profile=profile,
        doc_status=existing.status,
        doc_code=doc_code,
        current_user=current_user,
    )

    # 2. Verify Document Format (full verification)
    doc = await admission_repo.confirm_document_format(
        profile_id=profile_id,
        document_type_code=doc_code,
        verified_format=format_type,
        officer_id=current_user.id,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found")

    await db.flush()

    # 3. G2 (ADM-032 partial) — full response contract parity. See
    # commit message: returning AdmissionProfile from a mutation
    # without _populate_response_fields leaves permissions /
    # available_actions / eligibility_status at schema defaults, so
    # the FE has to refetch via GET to render the row correctly.
    documents = await admission_repo.get_all_documents(profile_id)
    await _populate_response_fields(
        db, profile, current_user, documents=documents
    )

    # ✅ AUDIT LOG: Track document verification
    from .document_audit_service import log_document_verification
    await log_document_verification(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status="uploaded",
        verified_format=format_type,
    )

    log.info(
        "Document verified with audit log",
        profile_id=profile_id,
        doc_code=doc_code,
        verified_format=format_type,
        officer_id=current_user.id,
        officer_email=current_user.email,
    )

    return profile


async def mark_paper_submitted(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    current_user: models.User,
    actual_submission_format: Optional[str] = None,
    graduation_proof_kind: Optional[str] = None,
    supplement_due_date: Optional[date] = None,
) -> models.AdmissionProfile:
    """
    Mark a document as paper submitted (officer confirms receipt).

    For documents where requires_upload=false.
    Only officers/managers/admins can mark paper submitted.
    PR #13: graduation_proof_kind/supplement_due_date chỉ áp cho giấy tốt
    nghiệp THPT (bằng chính thức / giấy tạm thời + hạn bổ sung).

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        current_user: Current authenticated user (must be officer+)
        actual_submission_format: Type of document submitted (original | certified_copy | photo)

    Returns:
        AdmissionProfile with updated validation_summary

    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Document requires upload (not paper submission)
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # BR1 (2026-04-29): profile-state guard delegated to
    # ``DocumentActionPolicy`` (see ``APPLICANT_DOC_MUTATION_STATES``).
    # The previous hand-rolled set ``[draft, submitted, rejected,
    # resubmitted]`` was a different shape from the policy's
    # ``[draft, rejected, revision_requested]`` — a dead-code mismatch
    # that this unification closes.

    # Get document to capture old status
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "missing"

    # Single source of truth — same matrix as can_mark_paper_submitted
    # on the response (requires_upload=false, status=missing, owning
    # officer in scope, profile in APPLICANT_DOC_MUTATION_STATES).
    _authorize_document_action(
        action="paper_submitted",
        profile=profile,
        doc_status=old_status,
        doc_code=doc_code,
        current_user=current_user,
    )

    # PR #13 — graduation proof chỉ áp cho giấy TN THPT; doc khác bỏ qua 2
    # field. Giấy TN THPT BẮT BUỘC phân loại khi ghi nhận.
    _grad_kind = graduation_proof_kind
    _grad_due = supplement_due_date
    if doc_code != "bang_tot_nghiep_thpt":
        _grad_kind = None
        _grad_due = None
    else:
        # The graduation doc MUST be classified on receipt. Defaulting (e.g.
        # to official_diploma) would risk silently recording a provisional
        # cert as an official diploma — the candidate would owe the diploma
        # but the system would show no "nợ bằng" debt, no badge and no way to
        # clear it. Require the kind explicitly. The FE dialog always sends
        # it (RadioGroup forces a choice); this closes the gap for raw API /
        # Swagger / old clients that omit it.
        if _grad_kind is None:
            raise ValidationError(
                "Cần chọn loại giấy tốt nghiệp (bằng chính thức / giấy tạm "
                "thời) khi ghi nhận giấy tốt nghiệp THPT."
            )
        if _grad_kind not in ("official_diploma", "provisional_cert"):
            raise ValidationError("graduation_proof_kind không hợp lệ")
        if _grad_kind == "provisional_cert" and _grad_due is None:
            raise ValidationError(
                "Cần nhập hạn bổ sung cho Giấy CN tốt nghiệp tạm thời"
            )

    # Mark paper submitted
    doc = await admission_repo.mark_paper_submitted(
        profile_id=profile_id,
        document_type_code=doc_code,
        officer_id=current_user.id,
        actual_submission_format=actual_submission_format,
        graduation_proof_kind=_grad_kind,
        supplement_due_date=_grad_due,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    await db.flush()

    # ✅ AUDIT LOG: Track paper submission
    from .document_audit_service import log_paper_submission
    await log_paper_submission(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        declared_format=actual_submission_format,
        graduation_proof_kind=_grad_kind,
        supplement_due_date=_grad_due,
    )

    # G2 (ADM-032 partial) — full response contract parity. Mirrors
    # the upload_document / confirm_document_format pattern so the
    # mutation response includes permissions / available_actions etc.
    documents = await admission_repo.get_all_documents(profile_id)
    await _populate_response_fields(
        db, profile, current_user, documents=documents
    )

    log.info(
        "Document paper submitted confirmed with audit log",
        profile_id=profile_id,
        doc_code=doc_code,
        officer_id=current_user.id,
    )

    return profile


async def update_graduation_proof_kind(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    new_kind: str,
    current_user: models.User,
) -> models.AdmissionProfile:
    """PR #13 — officer ghi nhận đã nhận BẰNG CHÍNH THỨC (provisional→official).

    Dùng khi thí sinh bổ sung bằng chính thức cho hồ sơ trước đó nộp Giấy CN
    tốt nghiệp tạm thời. KHÔNG đổi status; official_diploma → xoá hạn bổ sung.

    Auth: ``get_profile`` đã chặn IDOR scope (officer=assigned+unit /
    manager=unit / admin all). Thêm 2 guard mirror ``_authorize_document_action``
    mà sibling endpoints (paper-submit/verify/reject/reset) áp:
    - **BR2 is_extra**: doc đã rớt khỏi ``doc_configs`` snapshot = read-only.
    - **doc-status**: chỉ cập nhật khi giấy ĐÃ được ghi nhận
      (``paper_submitted`` / ``verified``) — không stamp lên doc chưa nhận.
    Chỉ nhận ``official_diploma``: giấy tạm thời + hạn bổ sung ghi qua paper-
    submit (mang theo hạn); endpoint này không có field hạn nên nhận
    provisional_cert sẽ tạo "nợ bằng" hạn NULL mà query nhắc bỏ sót.
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # get_profile eager-loads documents.document_type + enforces IDOR scope.
    profile = await get_profile(db, profile_id, current_user)

    if doc_code != "bang_tot_nghiep_thpt":
        raise BusinessRuleViolation("Chỉ áp dụng cho giấy tốt nghiệp THPT")
    if new_kind != "official_diploma":
        raise BusinessRuleViolation(
            "Endpoint chỉ ghi nhận bằng chính thức; giấy tạm thời + hạn bổ "
            "sung được ghi qua thao tác nhận giấy."
        )

    # Locate the graduation doc in the eager-loaded snapshot (no extra query).
    doc_before = next(
        (
            d
            for d in profile.documents
            if d.document_type and d.document_type.code == doc_code
        ),
        None,
    )
    if not doc_before:
        raise ResourceNotFoundError(
            f"Document code '{doc_code}' not found in profile documents"
        )

    # BR2 (fix 2026-06-09) — extras (dropped from doc_configs) are read-only.
    # Dùng doc_configs keyset (mandatory + optional) cho NHẤT QUÁN 1 định nghĩa
    # "extra" với builder + _authorize_document_action. Vô hại với
    # bang_tot_nghiep_thpt (luôn mandatory) — chỉ tránh drift về sau.
    applied_rules = profile.applied_rules or {}
    doc_configs = applied_rules.get("doc_configs") or {}
    if doc_code not in doc_configs:
        raise PermissionDeniedError(
            f"Document '{doc_code}' is no longer in the current admission "
            f"path's document config (extra / evidence-only)."
        )

    # Coherence — only a RECEIVED graduation doc can be upgraded to official.
    status = doc_before.status
    if status not in ("paper_submitted", "verified"):
        raise BusinessRuleViolation(
            "Chỉ cập nhật loại giấy khi đã ghi nhận giấy tốt nghiệp."
        )

    doc = await admission_repo.update_graduation_proof(
        profile_id=profile_id,
        document_type_code=doc_code,
        new_kind=new_kind,
    )
    if not doc:
        raise ResourceNotFoundError(
            f"Document code '{doc_code}' not found in profile documents"
        )

    await db.flush()

    from .document_audit_service import log_graduation_proof_update
    await log_graduation_proof_update(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        status=status,
        new_kind=new_kind,
    )

    # Reuse the eager-loaded collection (mutated in-place via the identity
    # map) instead of re-querying all documents.
    await _populate_response_fields(
        db, profile, current_user, documents=profile.documents
    )

    log.info(
        "Graduation proof kind updated",
        profile_id=profile_id,
        doc_code=doc_code,
        new_kind=new_kind,
        officer_id=current_user.id,
    )

    return profile


async def list_pending_diploma_profiles(
    db: AsyncSession,
    current_user: models.User,
    due_before: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """PR #13.7 — danh sách hồ sơ còn "nợ bằng" (Giấy CN tốt nghiệp tạm thời).

    IDOR scope qua ``_resolve_idor_filters`` (admin all / manager unit /
    officer assigned). ``due_before`` lọc hồ sơ có hạn bổ sung <= ngày — query
    nhắc officer follow-up thí sinh bổ sung bằng chính thức. Casbin admits
    officer/manager/admin; accountant denied at the gateway.
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    unit_id, assigned_officer_id = _resolve_idor_filters(current_user)
    profiles = await admission_repo.list_profiles_with_pending_diploma(
        unit_id=unit_id,
        assigned_officer_id=assigned_officer_id,
        due_before=due_before,
    )

    items: List[Dict[str, Any]] = []
    for profile in profiles:
        grad_doc = next(
            (
                d
                for d in profile.documents
                if d.document_type
                and d.document_type.code == "bang_tot_nghiep_thpt"
                and d.graduation_proof_kind == "provisional_cert"
            ),
            None,
        )
        lead = profile.lead
        officer = lead.assigned_officer if lead else None
        items.append(
            {
                "profile_id": profile.id,
                "candidate_name": lead.full_name if lead else None,
                "phone": lead.phone if lead else None,
                "status": profile.status,
                "supplement_due_date": (
                    grad_doc.supplement_due_date if grad_doc else None
                ),
                "assigned_officer_name": (
                    officer.full_name if officer else None
                ),
            }
        )
    return items


async def reject_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    reason: str,
    current_user: models.User,
) -> tuple[Dict[str, Any], Any]:
    """
    Reject a document with reason.
    
    User will need to re-upload or resubmit.
    Only officers/managers/admins can reject documents.
    
    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        reason: Rejection reason (required)
        current_user: Current authenticated user (must be officer+)
        
    Returns:
        Tuple of (updated_doc_item, post_commit_callback)
        
    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Reason not provided
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    
    if not reason or not reason.strip():
        raise BadRequest("Rejection reason is required")
    
    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # BR1 (2026-04-29): enrolled-state block delegated to
    # ``DocumentActionPolicy`` (see ``REVIEWER_DOC_MUTATION_BLOCKED_STATES``).
    # Single source of truth — same matrix as can_reject on the response.

    # Get document to capture old status
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "unknown"

    _authorize_document_action(
        action="reject",
        profile=profile,
        doc_status=old_status,
        doc_code=doc_code,
        current_user=current_user,
    )

    # Reject document
    doc = await admission_repo.reject_document(
        profile_id=profile_id,
        document_type_code=doc_code,
        officer_id=current_user.id,
        reason=reason.strip(),
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    await db.flush()

    # ✅ AUDIT LOG: Track document rejection
    from .document_audit_service import log_document_rejection
    await log_document_rejection(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        reason=reason.strip(),
    )

    response_data = {
        "code": doc_code,
        "status": "rejected",
        "rejection_reason": reason.strip(),
        "rejected_at": doc.rejected_at.isoformat() if doc.rejected_at else None,
        "rejected_by_id": current_user.id,
    }

    async def _post_commit():
        log.info(
            "Document rejected with audit log",
            profile_id=profile_id,
            doc_code=doc_code,
            reason=reason,
            officer_id=current_user.id,
        )

    return response_data, _post_commit


async def reset_document(
    db: AsyncSession,
    profile_id: int,
    doc_code: str,
    current_user: models.User,
) -> tuple[models.AdmissionProfile, Callable]:
    """
    Reset a document to 'missing' status (undo submission).

    Use case: User accidentally clicked "Đã nộp" or uploaded wrong file.
    Allows simple undo without complex audit trail.

    ADM-007: filesystem deletion is deferred to a post-commit
    callback. The old file stays on disk until the router's
    ``db.commit()`` settles; if commit fails the file remains on disk
    and the rolled-back DB still references it, which keeps DB and FS
    consistent. The caller-side pattern lives in
    ``app/routers/admissions.py::reset_document_endpoint``.

    Permissions (DocumentActionPolicy = single source of truth):
    - Officer (owning): reset trên hồ sơ draft / rejected / revision_requested
      (gỡ submission CỦA CHÍNH MÌNH: uploaded/paper_submitted/rejected;
      OWNER_DOC_MUTATION_STATES). KHÔNG reset doc đã ``verified`` ("đã duyệt thì
      không cho chỉnh sửa"); KHÔNG reset khi submitted/resubmitted (đang chờ
      reviewer) hay approved/enrolled.
    - Manager (in-scope) / Admin: reset bất kỳ doc non-missing (kể cả verified)
      trừ hồ sơ enrolled.
    - verify/reject vẫn reviewer-only (review ≠ sửa nội dung).

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        doc_code: Document type code
        current_user: Current authenticated user

    Returns:
        Tuple of:
          - ``AdmissionProfile`` with updated validation_summary.
          - ``finalize(committed: bool)`` async callback. When
            ``committed=True``: delete the previous file (if any).
            When ``committed=False``: no-op — the service never
            mutated the filesystem, so there is nothing to undo.
            Idempotent best-effort.

    Raises:
        ResourceNotFoundError: Document not found
        BadRequest: Cannot reset (e.g., profile is enrolled)
    """
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)

    # Get profile for access check
    profile = await get_profile(db, profile_id, current_user)

    # BR1 (2026-04-29): enrolled-state block delegated to
    # ``DocumentActionPolicy`` (see ``REVIEWER_DOC_MUTATION_BLOCKED_STATES``).
    # Single source of truth — same matrix as can_reset on the response.

    # Get document to capture old status and file path before reset
    doc_before = await admission_repo.get_document_by_type(profile_id, doc_code)
    old_status = doc_before.status if doc_before else "unknown"
    old_file_path = doc_before.file_path if doc_before else None

    _authorize_document_action(
        action="reset",
        profile=profile,
        doc_status=old_status,
        doc_code=doc_code,
        current_user=current_user,
    )

    # Reset document
    doc = await admission_repo.reset_document(
        profile_id=profile_id,
        document_type_code=doc_code,
    )

    if not doc:
        raise ResourceNotFoundError(f"Document code '{doc_code}' not found in profile documents")

    # ✅ AUDIT LOG: Track document reset
    from .document_audit_service import log_document_reset
    await log_document_reset(
        db=db,
        profile_document_id=doc.id,
        actor_user_id=current_user.id,
        old_status=old_status,
        old_file_path=old_file_path,
        reason="User requested reset",
    )

    # ADM-007: defer the file delete to the post-commit callback. If
    # commit fails the file stays on disk and the rolled-back DB still
    # references it — DB ↔ FS remain consistent. The deletion only
    # becomes visible to the world after ``db.commit()`` settles.

    await db.flush()

    # G2 (ADM-032 bundled) — full response contract parity. Mirrors
    # upload_document / confirm_document_format / mark_paper_submitted
    # so the mutation response includes permissions / available_actions
    # etc. Was missed in PR #169 (only 3/4 services switched to
    # _populate_response_fields).
    documents = await admission_repo.get_all_documents(profile_id)
    await _populate_response_fields(
        db, profile, current_user, documents=documents
    )

    log.info(
        "Document reset staged (awaiting commit)",
        profile_id=profile_id,
        doc_code=doc_code,
        user_id=current_user.id,
        old_file_path=old_file_path,
    )

    async def finalize(committed: bool) -> None:
        """ADM-007 reset finalize callback.

        - ``committed=True``: delete the old file if it exists. Best
          effort — log a warning on failure (storage waste, not a
          correctness issue).
        - ``committed=False``: no-op. The service never wrote to the
          filesystem, so there is nothing to undo.

        Idempotent: ``os.path.exists`` check before unlink.
        """
        if not committed:
            return

        if old_file_path:
            import os

            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                    log.info(
                        "Document file deleted post-commit during reset",
                        file_path=old_file_path,
                    )
                except OSError as e:
                    log.warning(
                        "Failed to delete document file post-commit",
                        error=str(e),
                        file_path=old_file_path,
                    )

    return profile, finalize


async def _lock_admission_profile_for_write(
    db: AsyncSession, profile_id: int,
) -> models.AdmissionProfile:
    """
    ADM-013: Acquire the profile-row write lock AND return a freshly
    loaded ORM instance.

    All three state-changing flows that race on a single
    AdmissionProfile — magic-link confirm, admin override, admin
    finalize — must acquire the profile lock FIRST so Postgres can
    serialise them via row locking instead of falling back on the
    optimistic version check alone.

    Earlier shape returned ``None`` and only acquired the row lock.
    That left a hole: a non-router caller that loaded ``profile``
    *before* waiting on the lock would block on the SELECT, then
    continue reading ``profile.status`` / ``profile.version`` from
    the **stale** in-memory ORM instance. The lock would be honoured
    on disk but the service body would still mutate against pre-lock
    column values. ``populate_existing=True`` closes that hole by
    refreshing the column values on the instance already in this
    session's identity map; the returned object IS the same Python
    instance the caller passed in (when they share a session) but
    with fresh column data.

    Eager loads mirror the router dependency chains
    (``get_admission_for_manager`` / ``get_admission_for_user``) so
    downstream code (``_populate_response_fields``, lead/officer
    sync) can still read ``profile.lead.assigned_officer`` and
    ``profile.assigned_reviewer`` without firing async lazy loads.

    Args:
        db: AsyncSession holding the transaction.
        profile_id: Profile ID to lock.

    Returns:
        The locked + freshly populated ``AdmissionProfile``.

    Raises:
        ResourceNotFoundError: Profile no longer exists. Defensive —
            the router dep usually catches this earlier.
    """
    from sqlalchemy import select as _select
    from sqlalchemy.orm import selectinload

    stmt = (
        _select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    locked = result.scalar_one_or_none()
    if locked is None:
        raise ResourceNotFoundError(
            f"Admission profile {profile_id} not found"
        )
    return locked


async def _perform_enrollment_core(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> tuple[models.AdmissionProfile, Dict[str, Any], bool, str]:
    """
    Locked + idempotent enrollment business core.

    Owns the ``SELECT ... FOR UPDATE`` fetch + state mutation that used
    to live inline in ``enroll_student()``. Both ``enroll_student()`` and
    ``finalize_profile()`` delegate here so finalize's lock/idempotency
    semantics are identical to enroll's — accepting a pre-loaded ORM
    object would have silently dropped that lock.

    Returns ``(profile, result_dict, idempotent_skip, pre_status)``:
    - ``profile``: the locked + mutated (or already-enrolled) profile
    - ``result_dict``: ``{student_id, student_code, enrollment_date}``
    - ``idempotent_skip``: True if profile was already enrolled and no
      state change happened — callers MUST NOT re-dispatch notifications
      in that case (would double-fire on retry).
    - ``pre_status``: profile.status snapshotted BEFORE the enrollment
      mutation. Mirrors what router used to capture via a separate
      ``db.get()`` call before invoking the service. For idempotent
      skips, this is "enrolled" (the already-final state).

    See ``enroll_student()`` docstring for ACID flow + security gates;
    this helper is the body of that function.
    """
    # Initialize repository
    from app.repositories import AdmissionRepository
    from sqlalchemy import select
    admission_repo = AdmissionRepository(db)

    # ✅ CRITICAL FIX #2 & #3: Acquire row lock and check state atomically
    # Scenario: Admin enrolls profile while Lead confirms via magic link
    # Without lock: Both can modify status simultaneously
    # With lock: Operations are serialized
    from sqlalchemy.orm import selectinload
    
    # Use selectinload to avoid "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))  # ✅ Eager load Lead
        .with_for_update()  # ✅ CRITICAL: Lock row for enrollment
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check (after lock acquired)
    _check_idor_access(profile, current_user)

    # ✅ HIGH PRIORITY FIX #7: Idempotency check - return existing student if already enrolled
    # MUST be BEFORE status check to handle idempotent requests correctly
    # Prevents duplicate student creation if endpoint is called multiple times
    # This can happen if:
    # - Client retries on network timeout
    # - Multiple admins click "Enroll" simultaneously (despite lock, status is already 'enrolled')
    # - Background job + manual action race
    if profile.status == "enrolled":
        # Profile already enrolled - return existing student (idempotent operation)
        if profile.student:
            log.info(
                "Idempotent enroll: Profile already enrolled, returning existing student",
                profile_id=profile_id,
                student_id=profile.student.id,
                student_code=profile.student.student_code,
            )
            return (
                profile,
                {
                    "student_id": profile.student.id,
                    "student_code": profile.student.student_code,
                    "enrollment_date": profile.student.enrollment_date,
                },
                True,  # idempotent_skip — caller MUST NOT re-dispatch
                "enrolled",  # pre_status — already-final state
            )
        else:
            # Data inconsistency: status is 'enrolled' but no student record exists
            log.error(
                "CRITICAL: Profile status is 'enrolled' but no student record found",
                profile_id=profile_id,
                status=profile.status,
            )
            raise ConflictError(
                f"Data inconsistency: Profile {profile_id} is marked as enrolled "
                "but has no associated student record. Please contact system administrator."
            )

    # Must be in approved or confirmed status
    # 'confirmed' = Lead confirmed via magic link, ready to enroll
    # ✅ CRITICAL FIX #1.1: Enforce State Machine (APPROVED -> CONFIRMED -> ENROLLED)
    # Prevents skipping confirmation step
    from .admission_state_machine import validate_transition
    
    try:
        validate_transition(profile.status, "enrolled")
    except ValueError as e:
        log.warning(
            "Invalid state transition for enrollment",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if profile.status not in ("confirmed", "overridden"):
         # Double check (redundant with validate_transition but keeps specific error message clear)
         # Actually validate_transition handles this, but we keep this block if we want custom message
         # However, for strict compliance, let's rely on validate_transition or re-raise cleaner error
         pass # validate_transition already checked this

    # ✅ FEE GATE (Phase 6): Verify tuition fee is paid/waived before enrollment
    # Per FINANCE_MODULE_DESIGN.md Section 5.3 - Gate 2 (Tuition Fee Gate)
    # Only enforced when ENABLE_FEE_VERIFICATION feature flag is True
    from app.config import settings
    if settings.ENABLE_FEE_VERIFICATION:
        await check_enrollment_fee_eligibility(db, profile_id)
        log.info(
            "Fee gate passed for enrollment",
            profile_id=profile_id,
            user_id=current_user.id,
        )

    # ✅ CRITICAL FIX #3: Final citizen_id duplicate check INSIDE transaction
    # Prevents race condition where 2 enrolls pass validation check but both create Student
    # Check must be AFTER acquiring lock but BEFORE creating Student record
    if not profile.citizen_id:
        raise BadRequest("Cannot enroll: Profile has no citizen_id")

    duplicate_student = await admission_repo.check_citizen_id_enrolled(profile.citizen_id)
    if duplicate_student:
        log.error(
            "CRITICAL: Citizen ID duplicate detected at enrollment time",
            profile_id=profile_id,
            citizen_id=profile.citizen_id,
            existing_student_code=duplicate_student.student_code,
            existing_student_id=duplicate_student.id,
        )
        raise ConflictError(
            f"Cannot enroll: Citizen ID {profile.citizen_id} is already enrolled "
            f"as student {duplicate_student.student_code}. "
            "This profile may have been enrolled through a different process."
        )

    # ACID Transaction with Savepoint
    try:
        async with db.begin_nested():  # Savepoint (not full transaction)
            # Step 1: Generate unique student_code with distributed lock
            year = datetime.now(timezone.utc).year
            student_code = None

            # Redis distributed lock to prevent concurrent generation collisions
            async with acquire_redis_lock(
                key=f"student_code_gen:{year}",
                timeout=10,
                max_retries=50
            ) as lock_acquired:
                if not lock_acquired:
                    log.error(
                        "Failed to acquire lock for student_code generation",
                        profile_id=profile_id,
                        year=year
                    )
                    raise ConflictError(
                        "Too many concurrent enrollment requests. Please try again in a few seconds."
                    )

                for attempt in range(10):  # Retry up to 10 times
                    random_digits = random.randint(0, 9999)
                    candidate_code = f"SV{year}{random_digits:04d}"

                    # ✅ SPRINT 6: Use Repository for uniqueness check
                    from app.repositories import AdmissionRepository
                    admission_repo_inner = AdmissionRepository(db)
                    
                    if not await admission_repo_inner.check_student_code_exists(candidate_code):
                        student_code = candidate_code
                        break

                if not student_code:
                    log.error(
                        "Failed to generate unique student_code after 10 attempts",
                        profile_id=profile_id,
                    )
                    raise BadRequest(
                        "Cannot generate unique student code. Please try again."
                    )

            # Step 2: Create Student
            student = models.Student(
                admission_profile_id=profile.id,
                student_code=student_code,
                enrollment_date=datetime.now(timezone.utc),
            )
            db.add(student)
            await db.flush()  # Get student.id

            # Step 3: Create StudentDocument records
            # Step 3b: Copy ProfileDocument records to StudentDocument (relational approach)
            uploaded_docs = await admission_repo.get_uploaded_documents(profile.id)
            for profile_doc in uploaded_docs:
                # Use uploaded_at from ProfileDocument or fallback to now
                uploaded_at = profile_doc.uploaded_at or datetime.now(timezone.utc)

                doc = models.StudentDocument(
                    student_id=student.id,
                    doc_type=profile_doc.document_type.code,
                    file_path=profile_doc.file_path,
                    is_verified=False,  # Default: pending verification
                    uploaded_at=uploaded_at,
                )
                db.add(doc)

            # Step 4: Update AdmissionProfile status — caller still
            # captures pre-transition status because the function
            # returns a 4-tuple including ``_old_status_for_enroll``
            # for downstream notification dispatch by the router.
            _old_status_for_enroll = profile.status

            # ADMISSION_ENROLLED is an outbox event; transition() INSERTs
            # the NotificationOutbox row in this same transaction (the
            # savepoint), so the row commits atomically with the
            # student/student-document writes above. ``transition_callback``
            # is None for outbox events — caller does not need to
            # thread it through.
            #
            # Phase 1 hotfix-2: rename ``student_code`` →
            # ``student_id`` to match the seeded ADMISSION_ENROLLED
            # template's ``$student_id`` placeholder. The display
            # value is the human-readable student code (e.g.
            # ``SV20262469``); naming aligned with the template's
            # operator-facing variable convention.
            profile, _ = await state_transition(
                db,
                profile,
                "enrolled",
                actor=current_user,
                source="api",
                event_metadata={"student_id": student_code},
            )

            # Step 5: ✅ PIPELINE SYNC: Create system consultation for enrollment milestone
            await _create_admission_milestone_consultation(
                db=db,
                lead=profile.lead,
                event="profile_enrolled",
                actor=current_user,
                profile_id=profile_id,
                student_code=student_code,
            )

            await db.flush()

            # ✅ SYNC: Update lead consultation status to match admission status (enrolled → sts11)
            from .lead_admission_sync import sync_lead_from_admission
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=current_user.id,
                reason="Student enrolled successfully",
            )
            # Savepoint auto-commits here if no errors

        log.info(
            "Student enrolled successfully",
            student_id=student.id,
            student_code=student.student_code,
            profile_id=profile_id,
            lead_id=profile.lead_id,
            user_id=current_user.id,
        )

        return (
            profile,
            {
                "student_id": student.id,
                "student_code": student.student_code,
                "enrollment_date": student.enrollment_date,
            },
            False,  # real mutation happened — caller should dispatch
            _old_status_for_enroll,  # pre_status snapshotted before mutation
        )

    except IntegrityError as e:
        # Savepoint auto-rollback
        error_msg = str(e.orig)

        log.error(
            "Enrollment failed due to integrity error",
            profile_id=profile_id,
            error=error_msg,
        )

        # Parse error message
        if "student_code" in error_msg.lower():
            raise ConflictError(
                f"Student code {student_code} already exists"
            )
        elif "citizen_id" in error_msg.lower():
            raise ConflictError(
                f"Citizen ID {profile.citizen_id} is already enrolled"
            )
        else:
            raise ConflictError(
                "Enrollment failed due to data conflict. Please try again."
            )


async def enroll_student(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Tuple[Dict[str, Any], Optional[Callable]]:
    """
    Enroll student — public wrapper around ``_perform_enrollment_core``.

    Returns ``(result_dict, post_commit_callback)``. Caller (router
    or ``finalize_profile``) MUST commit the outer DB transaction
    and then ``await callback()`` if non-None.

    Idempotent re-enrollment (profile already in 'enrolled' state):
    returns the existing student dict and ``callback=None`` — no
    notification re-fires on retry, no commission re-evaluation.

    See ``_perform_enrollment_core()`` for the ACID flow + security
    gates documentation that used to live on this function.

    Bundle: ``admission_enroll`` — paired
    APPLICATION_STATUS_CHANGED + LEAD_STATUS_CHANGED. Mirrors router
    admissions.py:1111+1129 (paired) + 1144 (commission).
    """
    profile, result_dict, idempotent_skip, pre_status = await _perform_enrollment_core(
        db, profile_id, current_user,
    )

    # Idempotent re-enrollment: do not re-dispatch + do not re-evaluate
    # commission. Return existing student with no callback so the caller
    # treats the call as a pure read.
    if idempotent_skip:
        return result_dict, None

    # Path C / Arch-3: paired notification bundle + commission callback.
    # ``pre_status`` mirrors what the router used to capture via a
    # separate ``db.get()`` before the service call. Payload + dedupe
    # key shapes are byte-for-byte identical to admissions.py:1111+1129.
    pre_status_for_payload = pre_status
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": pre_status_for_payload,
                    "new_status": "enrolled",
                    "student_id": result_dict["student_id"],
                    "student_code": result_dict["student_code"],
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"student_enrolled:{result_dict['student_id']}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": pre_status_for_payload,
                    "new_status": "sts11",
                    "actor_id": current_user.id,
                    "actor_name": current_user.full_name or current_user.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts11",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_enroll", intents=intents,
        )
        bundle_callback = bundle.callback

    commission_callback = None
    if profile.lead_id:
        captured_lead_id = profile.lead_id
        captured_actor_id = current_user.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, pre_status_for_payload, "sts11", captured_actor_id,
            )

        commission_callback = _commission_callback

    final_callback = compose_post_commit_callbacks(
        label="admission_enroll",
        callbacks=[bundle_callback, commission_callback],
    )

    return result_dict, final_callback


# ==============================================================================
# DELETE PROFILE (implemented at line ~2691)
# ==============================================================================

# ==============================================================================
# STATE MACHINE TRANSITIONS (Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
# ==============================================================================

async def approve_profile(
    db: AsyncSession,
    profile_id: int,
    approver: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Approve admission profile (Manager/Admin action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → APPROVED
    - State validation via admission_state_machine module
    - Version checking for optimistic locking
    - Returns (result, post_commit_callback) pattern

    Architecture Compliance:
    - No HTTPException (use Domain Exceptions)
    - No Request/Response imports
    - Return callback for side effects
    - Router calls db.commit()

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        approver: User performing approval
        data: ApproveRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, approver)
    from .admission_state_machine import validate_transition

    # W7-A.1 fix 2026-05-16: VERSION CHECK MUST RUN BEFORE STATE VALIDATION.
    # Before: 2 reviewers approve concurrently with same version=N. First
    # commits status→approved; second acquires lock, finds status=approved,
    # validate_transition("approved","approved") fails → 400 BadRequest.
    # Wrong status: 400 misleads FE retry logic (think "invalid input"
    # → show validation error). After fix: version check first → 409
    # ConflictError → FE can show "refresh and retry" UX correctly.
    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=approver.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE VALIDATION (Business Rule) — only after version match confirmed
    try:
        validate_transition(profile.status, "approved")
    except ValueError as e:
        log.warning(
            "Invalid state transition for approve",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # ✅ APPLICATION FEE CHECK
    # Per PHASE_WORKFLOW.md: Profile can only be approved if fee is paid or exempt
    applied_rules = profile.applied_rules or {}
    requires_fee = applied_rules.get("requires_application_fee", False)
    fee_status = applied_rules.get("fee_status", "exempt")

    if requires_fee and fee_status == "pending":
        log.warning(
            "Attempt to approve profile with unpaid application fee",
            profile_id=profile.id,
            fee_status=fee_status,
            approver_id=approver.id,
        )
        raise BadRequest(
            "Không thể duyệt hồ sơ: Lệ phí xét tuyển chưa được thanh toán. "
            "Vui lòng xác nhận thanh toán lệ phí trước khi duyệt hồ sơ."
        )

    # Fast-track nợ giấy tờ (C1.5) — APPROVE GATE. A profile submitted with a
    # document debt may NOT be approved until every owed doc is VERIFIED (or
    # paper_submitted). Computed from the persisted ``document_debt`` snapshot ∩
    # docs-not-yet-verified, via the same helper the FE-facing
    # ``_compute_frontend_fields`` uses (so the disabled button + the server
    # gate agree). Profiles without a debt snapshot have no outstanding codes →
    # this is a no-op (no regression). Runs BEFORE the irreversible quota
    # increment so a blocked approve never consumes a seat.
    _approve_outstanding = await _outstanding_debt_for_approval(db, profile)
    if _approve_outstanding:
        log.warning(
            "Attempt to approve profile with outstanding document debt",
            profile_id=profile.id,
            approver_id=approver.id,
            outstanding_debt_codes=_approve_outstanding,
        )
        raise BusinessRuleViolation(
            "Hồ sơ còn nợ giấy tờ chưa bổ sung/xác minh đủ, không thể "
            "duyệt. Cần verify đủ giấy tờ trước khi duyệt."
        )

    # ADM-026: quota gate. Locks the OfferingAcademicInfo row before
    # counting committed seats so concurrent approve calls cannot blow the
    # cap. Admin can override with bypass_quota + bypass_reason; manager
    # gets 403; missing reason gets 400.
    await _assert_quota_or_bypass(
        db,
        profile,
        approver,
        bypass_quota=bool(data.get("bypass_quota", False)),
        bypass_reason=data.get("bypass_reason"),
        transition="approve",
    )

    # STATE CHANGE — caller still captures old_status for the legacy
    # bundle + commission callback below.
    _old_status_for_audit = profile.status

    profile, transition_callback = await state_transition(
        db,
        profile,
        "approved",
        actor=approver,
        reason=data.get("notes"),
        source="api",
        extra_fields={
            "approved_at": datetime.now(timezone.utc),
            "approved_by_id": approver.id,
            "approval_notes": data.get("notes"),
        },
    )

    # ✅ PIPELINE SYNC: Create system consultation for approval milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_approved",
            actor=approver,
            profile_id=profile.id,
        )

    await db.flush()  # Flush, don't commit! Router commits.

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, approver)

    # ✅ SYNC: Update lead consultation status to match admission status (approved → sts09)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=approver.id,
        reason="Admission profile approved",
    )

    log.info(
        "Admission profile approved",
        profile_id=profile.id,
        approver_id=approver.id,
        previous_status=profile.status,
        citizen_id=profile.citizen_id,
    )

    # Path C / Arch-3: paired notification bundle + commission callback.
    # Mirrors router admissions.py:1504+1519 (paired dispatch) + 1534
    # (commission). new_status="approved" / lead "sts09".
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": _old_status_for_audit,
                    "new_status": "approved",
                    "actor_id": approver.id,
                    "actor_name": approver.full_name or approver.username,
                },
                dedupe_key=f"admission_profile_approved:{profile_id}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": _old_status_for_audit,
                    "new_status": "sts09",
                    "actor_id": approver.id,
                    "actor_name": approver.full_name or approver.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts09",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_approve", intents=intents,
        )
        bundle_callback = bundle.callback

    commission_callback = None
    if profile.lead_id:
        captured_lead_id = profile.lead_id
        captured_old = _old_status_for_audit
        captured_actor_id = approver.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, captured_old, "sts09", captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Profile approved notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_approve",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback, transition_callback],
    )

    return profile, final_callback


async def reject_profile(
    db: AsyncSession,
    profile_id: int,
    rejector: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Reject admission profile (Manager/Admin action).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → REJECTED
    - Reason is MANDATORY (validated in schema, min 10 chars)
    - State validation via admission_state_machine module
    - Returns (result, post_commit_callback) pattern

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        rejector: User performing rejection
        data: RejectRequest data (reason - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK)
    _check_idor_access(profile, rejector)

    from .admission_state_machine import validate_transition

    # W7-A.1 fix 2026-05-16: VERSION CHECK BEFORE STATE VALIDATION
    # (same rationale as approve_profile — racing reviewer should see
    # 409 ConflictError, not 400 "Invalid transition").
    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch in reject",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=rejector.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE VALIDATION — only after version match confirmed
    try:
        validate_transition(profile.status, "rejected")
    except ValueError as e:
        log.warning(
            "Invalid state transition for reject",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # BUSINESS RULE: Reason is mandatory (already validated by schema)
    if not data.get("reason"):
        raise BadRequest("Rejection reason is required (min 10 characters)")

    # STATE CHANGE — caller still captures old_status for the legacy
    # bundle + commission callback below.
    _old_status_for_audit = profile.status

    profile, transition_callback = await state_transition(
        db,
        profile,
        "rejected",
        actor=rejector,
        reason=data["reason"],
        source="api",
        extra_fields={
            "rejected_at": datetime.now(timezone.utc),
            "rejected_by_id": rejector.id,
            "rejection_reason": data["reason"],
        },
    )

    # ✅ PIPELINE SYNC: Create system consultation for rejection milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_rejected",
            actor=rejector,
            profile_id=profile.id,
            reason=data["reason"],
        )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, rejector)

    # ✅ SYNC: Update lead consultation status to match admission status (rejected → sts16)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=rejector.id,
        reason=f"Admission profile rejected: {data['reason'][:50]}",
    )

    log.info(
        "Admission profile rejected",
        profile_id=profile.id,
        rejector_id=rejector.id,
        reason_length=len(data["reason"]),
    )

    # TUITION_PREPAY_FASTTRACK finding #1 — surface orphaned prepaid tuition.
    # ``_populate_response_fields`` above already computed the flag; only hit
    # the DB for the exact amount when there IS something held (rare path).
    # We do NOT block reject — refund stays manual via the maker-checker flow.
    if getattr(profile, "has_unrefunded_payment", False):
        from app.repositories.fee_repository import FeeRepository

        _total_paid = await FeeRepository(db).sum_paid_amount_by_profile(profile.id)
        log.warning(
            "Profile reject với khoản học phí chưa hoàn",
            profile_id=profile.id,
            total_paid=str(_total_paid),
            status=profile.status,
        )

    # Path C / Arch-3: paired notification bundle + commission callback.
    # Mirrors router admissions.py:1606+1621 (paired dispatch) + 1636
    # (commission). new_status="rejected" / lead "sts16".
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": _old_status_for_audit,
                    "new_status": "rejected",
                    "actor_id": rejector.id,
                    "actor_name": rejector.full_name or rejector.username,
                },
                dedupe_key=f"admission_profile_rejected:{profile_id}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": _old_status_for_audit,
                    "new_status": "sts16",
                    "actor_id": rejector.id,
                    "actor_name": rejector.full_name or rejector.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts16",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_reject", intents=intents,
        )
        bundle_callback = bundle.callback

    commission_callback = None
    if profile.lead_id:
        captured_lead_id = profile.lead_id
        captured_old = _old_status_for_audit
        captured_actor_id = rejector.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, captured_old, "sts16", captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Profile rejected notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_reject",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback, transition_callback],
    )

    return profile, final_callback


async def request_revision(
    db: AsyncSession,
    profile_id: int,
    reviewer: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Request revision of admission profile (Manager/Admin action).

    Transition: SUBMITTED/RESUBMITTED -> REVISION_REQUESTED
    Uses dedicated columns (revision_requested_at/by/reason) separate from rejection.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        reviewer: User requesting revision
        data: RevisionRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    _check_idor_access(profile, reviewer)

    from .admission_state_machine import validate_transition

    # W7-A.1 fix 2026-05-16: VERSION CHECK BEFORE STATE VALIDATION.
    if data["version"] != profile.version:
        log.warning(
            "Optimistic locking conflict: Version mismatch in revision request",
            profile_id=profile.id,
            expected_version=data["version"],
            actual_version=profile.version,
            user_id=reviewer.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    try:
        validate_transition(profile.status, "revision_requested")
    except ValueError as e:
        log.warning(
            "Invalid state transition for revision request",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if not data.get("reason"):
        raise BadRequest("Revision reason is required (min 10 characters)")

    # Caller still captures old_status for the legacy notification
    # bundle + commission callback below; transition() also captures
    # internally for its own audit + ADMISSION_* dispatch payload.
    _old_status_for_audit = profile.status

    # Phase 1 hotfix-2: ``extra_fields`` writes onto AdmissionProfile
    # columns; it does NOT flow into the dispatch payload. The seeded
    # ADMISSION_REVISION_REQUESTED template references
    # ``$revision_reason`` so we mirror the value into
    # ``event_metadata`` (which IS merged into payload by
    # transition()) to avoid the literal ``$revision_reason`` leaking
    # into rendered messages.
    profile, transition_callback = await state_transition(
        db,
        profile,
        "revision_requested",
        actor=reviewer,
        reason=data["reason"],
        source="api",
        extra_fields={
            "revision_requested_at": datetime.now(timezone.utc),
            "revision_requested_by_id": reviewer.id,
            "revision_reason": data["reason"],
        },
        event_metadata={"revision_reason": data["reason"]},
    )

    # PIPELINE SYNC: Create system consultation for revision milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_revision_requested",
            actor=reviewer,
            profile_id=profile.id,
            reason=data["reason"],
        )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, reviewer)

    # SYNC: Update lead consultation status (revision_requested -> sts17)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=reviewer.id,
        reason=f"Admission profile revision requested: {data['reason'][:50]}",
    )

    log.info(
        "Admission profile revision requested",
        profile_id=profile.id,
        reviewer_id=reviewer.id,
        reason_length=len(data["reason"]),
    )

    # Path C / Arch-3: paired notification bundle + commission callback.
    # Mirrors router admissions.py:1696+1711 (paired dispatch) + 1725
    # (commission). new_status="revision_requested" / lead "sts17".
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": _old_status_for_audit,
                    "new_status": "revision_requested",
                    "actor_id": reviewer.id,
                    "actor_name": reviewer.full_name or reviewer.username,
                },
                dedupe_key=f"admission_profile_revision:{profile_id}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": _old_status_for_audit,
                    "new_status": "sts17",
                    "actor_id": reviewer.id,
                    "actor_name": reviewer.full_name or reviewer.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts17",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_request_revision", intents=intents,
        )
        bundle_callback = bundle.callback

    commission_callback = None
    if profile.lead_id:
        captured_lead_id = profile.lead_id
        captured_old = _old_status_for_audit
        captured_actor_id = reviewer.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, captured_old, "sts17", captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Profile revision requested notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_request_revision",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback, transition_callback],
    )

    return profile, final_callback


# ==============================================================================
# APPLICATION FEE MANAGEMENT
# ==============================================================================

_MONEY_QUANT = Decimal("0.01")
_BACKFILL_IDEMPOTENCY_PREFIX = "appfee:backfill:"


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_MONEY_QUANT)
    except (InvalidOperation, TypeError, ValueError):
        raise BadRequest("Invalid application fee amount")


def _money_text(value: Any) -> str:
    return format(_money(value), "f")


def _assert_money_equal(actual: Any, expected: Decimal, label: str) -> None:
    if _money(actual) != expected:
        raise ConflictError(f"Inconsistent application fee ledger: {label}")


def _receipt_from_payment_data(payment_data: Dict[str, Any]) -> str:
    receipt = str(payment_data.get("transaction_id") or "").strip()
    if not 6 <= len(receipt) <= 80:
        raise BadRequest("transaction_id must be 6-80 characters after trimming")
    return receipt


def _expected_application_fee(applied_rules: Dict[str, Any]) -> Decimal:
    if "application_fee" not in applied_rules:
        raise BadRequest("Application fee amount is missing from profile rules")
    expected = _money(applied_rules.get("application_fee"))
    if expected <= 0:
        raise BadRequest("Application fee amount must be greater than 0")
    return expected


def _is_bcrypt_hash(value: Any) -> bool:
    text = str(value or "")
    return (
        len(text) >= 50
        and (
            text.startswith("$2a$")
            or text.startswith("$2b$")
            or text.startswith("$2y$")
        )
    )


async def _get_system_application_fee_user(db: AsyncSession) -> models.User:
    result = await db.execute(
        select(models.User).where(models.User.username == "system")
    )
    system_user = result.scalar_one_or_none()
    if system_user is None:
        raise ConflictError("Technical user 'system' is not configured")

    fingerprint_ok = (
        system_user.status == "inactive"
        and system_user.role == UserRole.USER
        and system_user.email == "system@qlts.internal"
        and system_user.unit_id is None
        and system_user.current_assignment_id is None
        and _is_bcrypt_hash(system_user.password_hash)
    )
    if not fingerprint_ok:
        raise ConflictError("Technical user 'system' fingerprint is invalid")

    active_assignment = await db.execute(
        select(models.UserUnitAssignment.id)
        .where(
            models.UserUnitAssignment.user_id == system_user.id,
            models.UserUnitAssignment.is_active == True,  # noqa: E712
        )
        .limit(1)
    )
    if active_assignment.scalar_one_or_none() is not None:
        raise ConflictError("Technical user 'system' has an active unit assignment")

    return system_user


async def _get_cash_payment_method(db: AsyncSession):
    from app.models.finance import PaymentMethod

    result = await db.execute(
        select(PaymentMethod).where(
            PaymentMethod.code == "cash",
            PaymentMethod.is_active == True,  # noqa: E712
            PaymentMethod.is_online == False,  # noqa: E712
        )
    )
    methods = result.scalars().all()
    if len(methods) != 1:
        raise ConflictError("Cash payment method is not configured exactly once")
    return methods[0]


async def _load_application_fee(db: AsyncSession, profile_id: int):
    from app.models.finance import Fee, Invoice, Payment

    result = await db.execute(
        select(Fee)
        .where(
            Fee.admission_profile_id == profile_id,
            Fee.fee_type == "application",
        )
        .options(
            selectinload(Fee.invoices)
            .selectinload(Invoice.payments)
            .selectinload(Payment.method),
        )
        .order_by(Fee.id)
    )
    fees = result.scalars().unique().all()
    if len(fees) > 1:
        raise ConflictError("Multiple application fee rows exist for this profile")
    return fees[0] if fees else None


async def _load_fee_transactions(db: AsyncSession, fee_id: int) -> List[Any]:
    from app.models.finance import PaymentTransaction

    result = await db.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.fee_id == fee_id)
        .options(
            selectinload(PaymentTransaction.payment),
            selectinload(PaymentTransaction.fee),
        )
        .order_by(PaymentTransaction.id)
    )
    return result.scalars().unique().all()


async def _find_transaction_by_key(db: AsyncSession, idempotency_key: str):
    from app.models.finance import PaymentTransaction

    result = await db.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.idempotency_key == idempotency_key)
        .options(
            selectinload(PaymentTransaction.fee),
            selectinload(PaymentTransaction.payment),
        )
    )
    return result.scalar_one_or_none()


async def _assert_receipt_not_used_by_other_profile(
    db: AsyncSession,
    profile_id: int,
    idempotency_key: str,
    receipt: str,
) -> None:
    existing = await _find_transaction_by_key(db, idempotency_key)
    if existing is None:
        return
    existing_profile_id = (
        existing.fee.admission_profile_id
        if existing.fee is not None
        else None
    )
    if existing_profile_id != profile_id:
        raise ConflictError(f"Biên lai {receipt} đã dùng cho hồ sơ khác")


def _assert_paid_fee_fields(fee: Any, expected: Decimal) -> None:
    if fee.status != "paid":
        raise ConflictError("Inconsistent application fee ledger: fee status")
    if fee.fee_type != "application":
        raise ConflictError("Inconsistent application fee ledger: fee type")
    _assert_money_equal(fee.base_amount, expected, "fee base_amount")
    _assert_money_equal(fee.total_discount, Decimal("0"), "fee total_discount")
    _assert_money_equal(fee.final_amount, expected, "fee final_amount")
    _assert_money_equal(fee.paid_amount, expected, "fee paid_amount")
    _assert_money_equal(fee.waived_amount, Decimal("0"), "fee waived_amount")
    if fee.semester_no is not None:
        raise ConflictError("Inconsistent application fee ledger: fee semester_no")
    if fee.installment_plan_id is not None:
        raise ConflictError(
            "Inconsistent application fee ledger: fee installment_plan"
        )


def _assert_paid_invoice_fields(invoice: Any, fee: Any, expected: Decimal) -> None:
    if invoice.fee_id != fee.id:
        raise ConflictError("Inconsistent application fee ledger: invoice fee_id")
    if invoice.status != "paid":
        raise ConflictError("Inconsistent application fee ledger: invoice status")
    _assert_money_equal(invoice.amount, expected, "invoice amount")
    _assert_money_equal(invoice.paid_amount, expected, "invoice paid_amount")
    _assert_money_equal(invoice.penalty_amount, Decimal("0"), "invoice penalty_amount")
    if invoice.installment_no != 1:
        raise ConflictError(
            "Inconsistent application fee ledger: invoice installment_no"
        )
    if invoice.invoice_number != f"APP-{fee.id}":
        raise ConflictError("Inconsistent application fee ledger: invoice_number")


def _assert_paid_payment_fields(
    payment: Any,
    invoice: Any,
    expected: Decimal,
    system_user_id: int,
) -> None:
    if payment.invoice_id != invoice.id:
        raise ConflictError("Inconsistent application fee ledger: payment invoice_id")
    if payment.status != "verified":
        raise ConflictError("Inconsistent application fee ledger: payment status")
    _assert_money_equal(payment.amount, expected, "payment amount")
    if payment.method is None or payment.method.code != "cash":
        raise ConflictError("Inconsistent application fee ledger: payment method")
    if not payment.method.is_active or payment.method.is_online:
        raise ConflictError(
            "Inconsistent application fee ledger: payment method flags"
        )
    if payment.created_by_id == payment.verified_by_id:
        raise ConflictError("Inconsistent application fee ledger: self approval")
    if payment.verified_by_id != system_user_id:
        raise ConflictError("Inconsistent application fee ledger: verifier")
    if payment.intent_id is not None:
        raise ConflictError("Inconsistent application fee ledger: payment intent")
    if payment.verified_at is None:
        raise ConflictError("Inconsistent application fee ledger: verified_at")
    if payment.rejected_by_id is not None or payment.rejection_reason is not None:
        raise ConflictError("Inconsistent application fee ledger: rejection fields")


def _assert_paid_transaction_fields(
    transaction: Any,
    fee: Any,
    payment: Any,
    expected: Decimal,
    system_user_id: int,
    receipt_key: str,
) -> None:
    if transaction.payment_id != payment.id:
        raise ConflictError(
            "Inconsistent application fee ledger: transaction payment_id"
        )
    if transaction.fee_id != fee.id:
        raise ConflictError("Inconsistent application fee ledger: transaction fee_id")
    if transaction.transaction_type != "payment":
        raise ConflictError("Inconsistent application fee ledger: transaction type")
    _assert_money_equal(transaction.amount, expected, "transaction amount")
    _assert_money_equal(
        transaction.balance_before,
        expected,
        "transaction balance_before",
    )
    _assert_money_equal(
        transaction.balance_after,
        Decimal("0"),
        "transaction balance_after",
    )
    gateway_response = transaction.gateway_response or {}
    if gateway_response.get("verification_mode") not in {"policy_auto", "backfill"}:
        raise ConflictError("Inconsistent application fee ledger: verification mode")
    if transaction.performed_by_id != system_user_id:
        raise ConflictError("Inconsistent application fee ledger: performed_by")
    if transaction.external_reference != payment.reference_code:
        raise ConflictError("Inconsistent application fee ledger: external reference")
    allowed_keys = {receipt_key, f"{_BACKFILL_IDEMPOTENCY_PREFIX}{fee.id}"}
    if transaction.idempotency_key not in allowed_keys:
        raise ConflictError("Inconsistent application fee ledger: receipt key")


async def _paid_chain_state(
    db: AsyncSession,
    fee: Any,
    expected: Decimal,
    system_user_id: int,
    receipt_key: str,
) -> str:
    if fee is None:
        return "missing"

    _assert_paid_fee_fields(fee, expected)
    transactions = await _load_fee_transactions(db, fee.id)
    invoices = list(fee.invoices or [])

    if len(invoices) > 1:
        raise ConflictError("Multiple application fee invoices exist")
    if not invoices:
        if transactions:
            raise ConflictError("Application fee transaction exists without invoice")
        return "missing"

    invoice = invoices[0]
    _assert_paid_invoice_fields(invoice, fee, expected)
    payments = list(invoice.payments or [])
    if len(payments) > 1:
        raise ConflictError("Multiple application fee payments exist")
    if not payments:
        if transactions:
            raise ConflictError("Application fee transaction exists without payment")
        return "missing"

    payment = payments[0]
    _assert_paid_payment_fields(payment, invoice, expected, system_user_id)
    if len(transactions) > 1:
        raise ConflictError("Multiple application fee transactions exist")
    if not transactions:
        return "missing"

    _assert_paid_transaction_fields(
        transactions[0],
        fee,
        payment,
        expected,
        system_user_id,
        receipt_key,
    )
    return "consistent"


async def _create_or_repair_paid_chain(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    fee: Any,
    expected: Decimal,
    receipt: str,
    receipt_key: str,
    recorded_by: models.User,
    system_user: models.User,
    cash_method: Any,
    now: datetime,
):
    from app.models.finance import Fee, Invoice, Payment, PaymentTransaction

    created_fee = fee is None
    if fee is None:
        fee = Fee(
            admission_profile_id=profile.id,
            fee_type="application",
            academic_year=profile.academic_year,
            semester_no=None,
            base_amount=expected,
            total_discount=Decimal("0"),
            final_amount=expected,
            paid_amount=expected,
            waived_amount=Decimal("0"),
            status="paid",
            installment_plan_id=None,
            calculated_by_id=recorded_by.id,
            calculated_at=now,
            last_payment_at=now,
            notes="Application fee collected via admissions workflow",
        )
        db.add(fee)
        await db.flush()

    invoices = [] if created_fee else list(fee.invoices or [])
    invoice = invoices[0] if invoices else None
    created_invoice = invoice is None
    if invoice is None:
        invoice = Invoice(
            fee_id=fee.id,
            invoice_number=f"APP-{fee.id}",
            installment_no=1,
            amount=expected,
            paid_amount=expected,
            penalty_amount=Decimal("0"),
            due_date=now.date(),
            status="paid",
            issued_at=now,
            paid_at=now,
            issued_by_id=recorded_by.id,
            notes="Application fee invoice",
        )
        db.add(invoice)
        await db.flush()

    payments = [] if created_invoice else list(invoice.payments or [])
    payment = payments[0] if payments else None
    if payment is None:
        payment = Payment(
            invoice_id=invoice.id,
            method_id=cash_method.id,
            amount=expected,
            reference_code=receipt,
            status="verified",
            payment_date=now,
            verified_at=now,
            created_by_id=recorded_by.id,
            verified_by_id=system_user.id,
            rejected_by_id=None,
            rejection_reason=None,
            intent_id=None,
            notes="Application fee cash collection auto-verified by policy",
        )
        db.add(payment)
        await db.flush()

    transactions = await _load_fee_transactions(db, fee.id)
    if not transactions:
        transaction = PaymentTransaction(
            payment_id=payment.id,
            fee_id=fee.id,
            transaction_type="payment",
            amount=expected,
            balance_before=expected,
            balance_after=Decimal("0"),
            external_reference=receipt,
            gateway_response={
                "verification_mode": "policy_auto",
                "receipt": receipt,
                "amount": _money_text(expected),
                "recorded_by_id": recorded_by.id,
                "verified_by_id": system_user.id,
            },
            idempotency_key=receipt_key,
            performed_by_id=system_user.id,
            notes="Application fee payment",
            created_at=now,
        )
        db.add(transaction)
        await db.flush()

    return fee


async def record_application_fee_payment(
    db: AsyncSession,
    profile_id: int,
    payment_data: Dict[str, Any],
    recorded_by: Optional[models.User] = None,
) -> tuple[models.AdmissionProfile, Any]:
    """
    Record application fee payment for an admission profile.

    This function is called when:
    1. Payment gateway callback confirms payment
    2. Manual payment confirmation by admin

    Flow:
    - Profile must be in "draft" or "submitted" status
    - Updates applied_rules.fee_status to "paid"
    - Syncs lead to sts13 (Đã hoàn lệ phí xét tuyển)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        payment_data: Payment information (transaction_id, amount, paid_at, etc.)
        recorded_by: User who recorded the payment (optional for system callbacks)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        ResourceNotFoundError: Profile not found
        BadRequest: Profile doesn't require fee or already paid
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # Check profile status — only allow fee payment for draft/submitted profiles
    if profile.status not in ("draft", "submitted"):
        raise BadRequest(
            f"Cannot record fee payment for profile in '{profile.status}' status. "
            "Only draft or submitted profiles accept fee payments."
        )

    # Check fee requirement
    applied_rules = profile.applied_rules or {}
    requires_fee = applied_rules.get("requires_application_fee", False)
    current_fee_status = applied_rules.get("fee_status", "exempt")

    if not requires_fee:
        raise BadRequest(
            "This admission profile does not require application fee payment"
        )

    if current_fee_status == "exempt":
        raise BadRequest("Application fee is exempt and cannot be collected")
    if current_fee_status not in ("pending", "paid"):
        raise BadRequest(
            f"Cannot collect application fee in '{current_fee_status}' state"
        )
    if recorded_by is None:
        raise BadRequest(
            "Application fee cash collection requires an authenticated actor"
        )

    raw_method_code = payment_data.get("payment_method_code") or "cash"
    method_code = str(raw_method_code).strip().casefold()
    if method_code != "cash":
        raise BadRequest("Application fee collection is cash-only")

    expected = _expected_application_fee(applied_rules)
    amount = _money(payment_data.get("amount"))
    from ..schemas.finance import MAX_AMOUNT
    if amount <= 0 or amount > _money(MAX_AMOUNT):
        raise BadRequest("Application fee amount is out of range")
    if amount != expected:
        raise BadRequest("Payment amount must match the configured application fee")

    receipt = _receipt_from_payment_data(payment_data)
    from app.utils.fee_receipt import canonical_receipt_key
    receipt_key = canonical_receipt_key(receipt)
    system_user = await _get_system_application_fee_user(db)
    if recorded_by.id == system_user.id:
        raise BadRequest("Technical user 'system' cannot be the payment recorder")
    cash_method = await _get_cash_payment_method(db)
    await _assert_receipt_not_used_by_other_profile(
        db,
        profile_id=profile_id,
        idempotency_key=receipt_key,
        receipt=receipt,
    )

    fee = await _load_application_fee(db, profile_id)
    chain_state = await _paid_chain_state(
        db,
        fee,
        expected,
        system_user_id=system_user.id,
        receipt_key=receipt_key,
    )

    now = datetime.now(timezone.utc)
    if chain_state == "missing":
        try:
            async with db.begin_nested():
                fee = await _load_application_fee(db, profile_id)
                await _create_or_repair_paid_chain(
                    db=db,
                    profile=profile,
                    fee=fee,
                    expected=expected,
                    receipt=receipt,
                    receipt_key=receipt_key,
                    recorded_by=recorded_by,
                    system_user=system_user,
                    cash_method=cash_method,
                    now=now,
                )
        except IntegrityError as exc:
            log.warning(
                "Application fee ledger create hit integrity race; reconciling",
                profile_id=profile_id,
                receipt_key=receipt_key,
                error=str(exc),
            )

        await _assert_receipt_not_used_by_other_profile(
            db,
            profile_id=profile_id,
            idempotency_key=receipt_key,
            receipt=receipt,
        )
        fee = await _load_application_fee(db, profile_id)
        chain_state = await _paid_chain_state(
            db,
            fee,
            expected,
            system_user_id=system_user.id,
            receipt_key=receipt_key,
        )
        if chain_state != "consistent":
            raise ConflictError("Application fee ledger could not be reconciled")

    did_transition_to_paid = current_fee_status != "paid"
    if did_transition_to_paid:
        payment_snapshot = {
            "transaction_id": receipt,
            "amount": _money_text(expected),
            "payment_method_code": "cash",
            "paid_at": now.isoformat(),
            "recorded_by": recorded_by.id,
        }

        applied_rules["fee_status"] = "paid"
        applied_rules["fee_paid_at"] = now.isoformat()
        applied_rules["fee_payment_data"] = payment_snapshot
        # Use a new dict to trigger JSONB change detection.
        profile.applied_rules = {**applied_rules}
        flag_modified(profile, "applied_rules")
        profile.updated_at = now

        # ✅ SYNC: Update lead to sts13 (Đã hoàn lệ phí xét tuyển)
        from .lead_admission_sync import sync_lead_fee_paid
        await sync_lead_fee_paid(
            db=db,
            profile=profile,
            changed_by_user_id=recorded_by.id,
            reason="Application fee payment confirmed",
        )

        await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, recorded_by)

    log.info(
        "Application fee payment recorded",
        profile_id=profile_id,
        lead_id=profile.lead_id,
        amount=_money_text(expected),
        transaction_id=receipt,
        recorded_by=recorded_by.id,
        did_transition_to_paid=did_transition_to_paid,
    )

    # Resolve notification payload while the session is still open — the
    # post_commit closure runs after db.commit() and cannot lazy-load.
    # unit_id is required for the unit_managers resolver path (declared in
    # the event catalog's allowed_resolvers).
    _officer_id = (
        profile.lead.assigned_officer_id
        if profile.lead is not None
        else None
    )
    _unit_id = profile.lead.unit_id if profile.lead is not None else None
    _notify_payload = {
        "application_id": profile_id,
        "lead_id": profile.lead_id,
        "unit_id": _unit_id,
        "officer_id": _officer_id,
        "amount": _money_text(expected),
        "transaction_id": receipt,
        "actor_id": recorded_by.id,
        "actor_name": (
            recorded_by.full_name or recorded_by.username
        ),
    }
    _db = db
    _rooms = rooms_for_admission(profile)

    async def post_commit():
        if not did_transition_to_paid:
            return

        from app.services.notification_dispatcher import safe_dispatch
        from app.core.events import SystemEvents

        # dedupe_key intentionally omitted — safe_dispatch() renders the
        # canonical key from the catalog's dedup_key_template
        # ("app:${application_id}:fee_paid"), keeping dedup contract in one
        # place.
        await safe_dispatch(
            db=_db,
            event=SystemEvents.APPLICATION_FEE_PAID,
            payload=_notify_payload,
            rooms=_rooms,
        )

    return profile, post_commit


async def check_application_fee_status(
    db: AsyncSession,
    profile_id: int,
) -> Dict[str, Any]:
    """
    Check application fee status for a profile.

    Returns:
        Dict with fee status information
    """
    from app.repositories import AdmissionRepository
    repo = AdmissionRepository(db)

    profile = await repo.get_by_id(profile_id)
    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    applied_rules = profile.applied_rules or {}

    return {
        "profile_id": profile_id,
        "requires_fee": applied_rules.get("requires_application_fee", False),
        "fee_amount": applied_rules.get("application_fee", 0),
        "fee_status": applied_rules.get("fee_status", "exempt"),
        "fee_paid_at": applied_rules.get("fee_paid_at"),
        "can_approve": (
            applied_rules.get("fee_status") in ("paid", "exempt")
        ),
    }


async def resubmit_profile(
    db: AsyncSession,
    profile_id: int,
    officer: Optional[models.User],
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Resubmit profile.

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Transitions: REJECTED → RESUBMITTED (officer dashboard path)
                   REVISION_REQUESTED → RESUBMITTED (candidate magic-link
                   self-service; state edge already in ALLOWED_TRANSITIONS).
    - Officer fixes issues and resubmits for Manager review, OR candidate
      resubmits via magic-link after the manager requested a revision.
    - Optional notes about what was fixed.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        officer: User performing resubmit. ``None`` for candidate
            magic-link self-service path (CCCD already verified upstream).
            Audit/notification user-attribution fields fall back to
            null/system-labelled values when ``None``.
        data: ResubmitRequest data (notes)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch
    """
    # ✅ CRITICAL FIX #1.2: Pessimistic Locking (Row Lock)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update() # Lock the row
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR Check (MOVED CHECK AFTER LOCK). Bypassed when officer is None
    # (magic-link path verifies CCCD).
    _check_idor_access(profile, officer)

    # Actor attribution capture (officer dashboard vs. magic-link
    # self-service). All downstream audit/notification consumers
    # already accept Optional ids; the human-readable label is used
    # only in notification payloads.
    _actor_id: Optional[int] = officer.id if officer else None
    _actor_name: str = (
        (officer.full_name or officer.username)
        if officer
        else "Ứng viên (magic-link)"
    )

    from .admission_state_machine import validate_transition

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "resubmitted")
    except ValueError as e:
        log.warning(
            "Invalid state transition for resubmit",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # VERSION CHECK
    if data.get("version") is not None and data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # STATE CHANGE — caller still captures old_status for the legacy
    # bundle + commission callback below; transition() also captures
    # internally for audit + ADMISSION_* dispatch.
    _old_status_for_audit = profile.status

    profile, transition_callback = await state_transition(
        db,
        profile,
        "resubmitted",
        actor=officer,
        reason=data.get("notes"),
        source="api",
        extra_fields={
            "resubmitted_at": datetime.now(timezone.utc),
            "resubmitted_by_id": _actor_id,
            "resubmit_notes": data.get("notes"),
        },
    )

    # Clear reviewer assignment on resubmit (manager can re-claim)
    old_reviewer = profile.assigned_reviewer_id
    if old_reviewer:
        from ..services import audit_service as _audit_svc
        await _audit_svc.log_changes(
            db, "AdmissionProfile", profile.id, "reviewer_cleared",
            changes={
                "assigned_reviewer_id": {"old": old_reviewer, "new": None},
                "assigned_at": {"old": str(profile.assigned_at) if profile.assigned_at else None, "new": None},
            },
            actor_user_id=_actor_id,
            source="api",
        )
    profile.assigned_reviewer_id = None
    profile.assigned_at = None

    # Capture lead consultation status BEFORE the milestone so we can tell
    # whether the lead actually moved. The SL1 guard may preserve a finance
    # overlay (sts13/sts14/sts10/sts18) instead of flooring to sts07.
    _old_lead_cs = profile.lead.consultation_status_id if profile.lead else None

    # ✅ PIPELINE SYNC: Create system consultation for resubmission milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_resubmitted",
            actor=officer,
            profile_id=profile.id,
        )

    # ✅ SYNC: Update lead consultation status to match admission status (resubmitted → sts07)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=_actor_id,
        reason=f"Profile resubmitted: {(data.get('notes') or 'No notes')[:50]}",
    )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, officer)

    log.info(
        "Admission profile resubmitted",
        profile_id=profile.id,
        officer_id=_actor_id,
    )

    # Path C / Arch-3: paired notification bundle + commission callback.
    # Mirrors router admissions.py:1796+1811 (paired dispatch) + 1824
    # (commission). new_status="resubmitted" / lead "sts07".
    # Did the lead actually change consultation status? The SL1 guard preserves
    # a finance overlay (sts13/sts14/sts10/sts18) instead of flooring to sts07,
    # so on that path the lead did NOT move — we must not broadcast a phantom
    # LEAD_STATUS_CHANGED nor run commission bookkeeping for a non-transition.
    _new_lead_cs = profile.lead.consultation_status_id if profile.lead else None
    _lead_status_changed = bool(_new_lead_cs) and _new_lead_cs != _old_lead_cs

    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": _old_status_for_audit,
                    "new_status": "resubmitted",
                    "actor_id": _actor_id,
                    "actor_name": _actor_name,
                },
                dedupe_key=f"admission_profile_resubmitted:{profile_id}",
                rooms=rooms_for_admission(profile),
            ),
        ]
        # Only broadcast a lead status change when the lead actually moved
        # (suppressed when the SL1 guard preserved a finance overlay).
        if _lead_status_changed:
            intents.append(
                NotificationIntent(
                    event=SystemEvents.LEAD_STATUS_CHANGED,
                    payload={
                        "lead_id": profile.lead_id,
                        "lead_name": f"Profile #{profile_id}",
                        "old_status": _old_status_for_audit,
                        "new_status": _new_lead_cs,
                        "actor_id": _actor_id,
                        "actor_name": _actor_name,
                    },
                    dedupe_key=f"lead_status_changed:{profile.lead_id}:{_new_lead_cs}",
                    rooms=rooms_for_admission(profile),
                )
            )
        bundle = await dispatch_bundle(
            db, bundle_label="admission_resubmit", intents=intents,
        )
        bundle_callback = bundle.callback

    commission_callback = None
    # Commission attribution requires a real actor AND an actual lead status
    # change. sts07 itself doesn't forward-trigger commissions, but regression
    # bookkeeping records the cancelling actor. Skip for the magic-link
    # candidate path and when the SL1 guard preserved the overlay (no move).
    if profile.lead_id and _actor_id is not None and _lead_status_changed:
        captured_lead_id = profile.lead_id
        captured_old = _old_status_for_audit
        captured_new = _new_lead_cs
        captured_actor_id = _actor_id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, captured_old, captured_new, captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Profile resubmitted notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_resubmit",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback, transition_callback],
    )

    return profile, final_callback


async def override_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    admin: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Override normal flow (Admin only, with audit).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: APPROVED → OVERRIDDEN
    - Admin only (enforced by router)
    - Reason MANDATORY (min 10 chars, for audit)
    - Full audit logging required

    Args:
        db: Database session
        profile: AdmissionProfile
        admin: Admin user performing override
        data: OverrideRequest data (reason, bypass_rules)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from .admission_state_machine import validate_transition

    # ADM-013: explicit profile-first FOR UPDATE lock before reading
    # ``profile.status`` / ``profile.version`` and before deleting
    # confirmation tokens. The helper returns a freshly populated ORM
    # instance via ``populate_existing=True`` so we read post-lock
    # column values even if the caller passed a stale instance loaded
    # before the lock was waited on (non-router callers; tests).
    profile = await _lock_admission_profile_for_write(db, profile.id)

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "overridden")
    except ValueError as e:
        log.warning(
            "Invalid state transition for override",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # BUSINESS RULE: Reason is mandatory (already validated by schema)
    if not data.get("reason"):
        raise BadRequest("Override reason is required (min 10 characters)")

    # ADM-015: schema makes ``version`` required (REQUIRED + ge=1), so we
    # compare directly. The previous ``data.get("version") is not None``
    # guard silently skipped the check whenever the field was absent —
    # which was *always*, because OverrideRequest didn't expose it. If
    # the schema/router ever drift again the KeyError below fails loud
    # instead of giving a false sense of optimistic locking.
    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # ADM-014: capture pre-mutation state for the audit row written
    # below via ``log_changes`` (richer than the standard
    # ``log_status_change``); ``skip_audit=True`` on transition() avoids
    # writing a duplicate status-only audit row.
    _audit_old_status = profile.status
    _audit_old_version = profile.version

    # STATE CHANGE — overridden maps to ADMISSION_DECISION_ADMITTED (T7)
    # with ``override=True`` payload metadata so consumers can
    # distinguish admin force-approve from the regular approve path.
    profile, transition_callback = await state_transition(
        db,
        profile,
        "overridden",
        actor=admin,
        reason=data["reason"],
        source="api",
        extra_fields={
            "overridden_at": datetime.now(timezone.utc),
            "overridden_by_id": admin.id,
            "override_reason": data["reason"],
        },
        event_metadata={
            "override": True,
            "override_reason": data["reason"],
            "bypass_rules": list(data.get("bypass_rules") or []),
        },
        skip_audit=True,  # log_changes below covers the change-set
    )

    # Invalidate stale magic-link tokens (profile leaving approved state)
    from app.repositories import AdmissionRepository
    await AdmissionRepository(db).invalidate_existing_tokens(profile.id)

    # ✅ PIPELINE SYNC: Create system consultation for override milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_overridden",
            actor=admin,
            profile_id=profile.id,
            reason=data["reason"],
        )

    # ✅ SYNC: Update lead consultation status to match admission status (overridden → sts09)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=admin.id,
        reason=f"Admin override: {data['reason'][:50]}",
    )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, admin)

    # AUDIT LOG (per AUTHORIZATION_DECISIONS.md Decision 11) — ADM-014:
    # admin override is a bypass action that absolutely needs durable audit
    # in entity_audit_log, not just runtime log.warning. The fields below
    # mirror what claim/unclaim/approve/reject already write.
    from ..services import audit_service
    await audit_service.log_changes(
        db,
        "AdmissionProfile",
        profile.id,
        "overridden",
        changes={
            "status": {"old": _audit_old_status, "new": "overridden"},
            "version": {"old": _audit_old_version, "new": profile.version},
            "override_reason": {"old": None, "new": data["reason"]},
            "bypass_rules": {
                "old": None,
                "new": list(data.get("bypass_rules") or []),
            },
            "overridden_by_id": {"old": None, "new": admin.id},
        },
        actor_user_id=admin.id,
        reason=data["reason"],
        source="api",
    )

    # Keep the warning log too — useful for live alerting / SIEM, separate
    # from the durable DB row.
    log.warning(
        "AUDIT: Admin override action",
        profile_id=profile.id,
        admin_id=admin.id,
        admin_email=admin.email,
        reason=data["reason"],
        bypass_rules=data.get("bypass_rules", []),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # POST-COMMIT CALLBACK
    # Compliance alerting is delivered via the router-level
    # APPLICATION_STATUS_CHANGED dispatch (routers/admissions.py in
    # override_admission, around line 1909) with new_status="overridden".
    # Admins can configure notification rules with condition filters
    # (e.g. {"new_status": "overridden"}) targeting compliance-team users.
    # This closure remains as a hook for future service-level side effects.
    async def _post_commit_hook():
        """No-op hook; compliance alerting runs in the router after commit."""
        log.debug(
            "Post-commit hook: override (alerting handled by router dispatch)",
            profile_id=profile.id,
        )

    # ADMISSION_DECISION_ADMITTED is an outbox event so transition_callback
    # is None for the override path; compose for symmetry with the other
    # status-change service functions and so a future routing change to
    # best-effort would surface a callback to the router automatically.
    post_commit = compose_post_commit_callbacks(
        label="admission_override",
        callbacks=[_post_commit_hook, transition_callback],
    )

    return profile, post_commit


async def claim_review(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    reviewer: models.User,
    expected_version: Optional[int] = None
):
    """
    Manager claims a profile for review (Assignment Workflow).

    Business Rules:
    1. Status MUST be 'submitted' (cannot claim draft/approved) # ADMISSION_RULE_008
    2. Profile must NOT be already claimed by someone else
    3. Version check (optimistic locking)
    """
    if profile.status not in ['submitted', 'resubmitted']:
        raise BusinessRuleViolation(
            f"Cannot claim profile in status '{profile.status}'. Only submitted/resubmitted profiles can be claimed."
        )

    # 3. Version Check (CRITICAL FIX: Prevent Race Condition)
    if expected_version is not None and profile.version != expected_version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    if profile.assigned_reviewer_id:
        if profile.assigned_reviewer_id == reviewer.id:
            # Idempotent success (already claimed by self).
            # Still populate transient computed fields so the response matches
            # what a fresh GET would return — router holds the same `profile`
            # reference via the dependency.
            await _populate_response_fields(db, profile, reviewer)
            return

        # Already claimed by someone else
        raise BusinessRuleViolation(
            "Profile is already claimed by another reviewer"
        )

    # STATE CHANGE
    profile.assigned_reviewer_id = reviewer.id
    profile.assigned_at = datetime.now(timezone.utc)
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, reviewer)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "claimed",
        changes={
            "assigned_reviewer_id": {"old": None, "new": reviewer.id},
            "assigned_at": {"old": None, "new": str(profile.assigned_at)},
        },
        actor_user_id=reviewer.id,
        source="api",
    )

    log.info(
        "Profile claimed for review",
        profile_id=profile.id,
        reviewer_id=reviewer.id,
    )


async def unclaim_review(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    current_user: models.User,
    expected_version: Optional[int] = None,
):
    """
    Unclaim a profile from review (Manager self-unclaim or Admin override).

    Business Rules:
    1. Profile must have an assigned reviewer
    2. Only assigned reviewer can unclaim (Admin can unclaim anyone)
    3. Version check (optimistic locking)
    """
    from app.utils.exceptions import BusinessRuleViolation

    if expected_version is not None and profile.version != expected_version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    if profile.assigned_reviewer_id is None:
        raise BusinessRuleViolation("No reviewer to unclaim")

    if current_user.role != UserRole.ADMIN:
        if profile.assigned_reviewer_id != current_user.id:
            raise BusinessRuleViolation("Only assigned reviewer or Admin can unclaim")

    old_reviewer = profile.assigned_reviewer_id
    old_at = profile.assigned_at

    profile.assigned_reviewer_id = None
    profile.assigned_at = None
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, current_user)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_changes(
        db, "AdmissionProfile", profile.id, "unclaimed",
        changes={
            "assigned_reviewer_id": {"old": old_reviewer, "new": None},
            "assigned_at": {"old": str(old_at) if old_at else None, "new": None},
        },
        actor_user_id=current_user.id,
        source="api",
    )

    log.info(
        "Profile unclaimed from review",
        profile_id=profile.id,
        unclaimed_by=current_user.id,
        previous_reviewer=old_reviewer,
    )


async def finalize_profile(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    admin: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Finalize enrollment (Admin only, creates Student record).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: OVERRIDDEN/CONFIRMED → ENROLLED
    - Admin only (enforced by router)
    - Triggers student record creation (delegates to enroll_student)

    Args:
        db: Database session
        profile: AdmissionProfile
        admin: Admin user performing finalization
        data: FinalizeRequest data (empty)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition
        ConflictError: Version mismatch or enrollment conflict
    """
    from .admission_state_machine import validate_transition

    # ADM-013: explicit profile-first FOR UPDATE lock before reading
    # ``profile.status`` / ``profile.version``. Helper rebinds to a
    # freshly populated ORM instance (``populate_existing=True``) so
    # version + state validation never read pre-lock stale columns
    # from a non-router caller. The downstream
    # ``_perform_enrollment_core`` re-locks defensively as well, so a
    # version mismatch or state-machine error here is an early bail
    # under the same row lock contract used by override + confirm.
    profile = await _lock_admission_profile_for_write(db, profile.id)

    # STATE VALIDATION
    try:
        validate_transition(profile.status, "enrolled")
    except ValueError as e:
        log.warning(
            "Invalid state transition for finalize",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    # ADM-015: FinalizeRequest now requires ``version`` (ge=1). Direct
    # compare; KeyError fails loud if the schema ever drops the field.
    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # ADM-026: quota gate at finalize. Profile is already in a
    # quota-occupying status (confirmed/overridden) at this point, so the
    # transition into ``enrolled`` is net-zero on the count — but we still
    # re-assert in case someone bypassed the approve gate or quota was
    # reduced after approve. Locking the offering row also serializes
    # concurrent finalize calls.
    await _assert_quota_or_bypass(
        db,
        profile,
        admin,
        bypass_quota=bool(data.get("bypass_quota", False)),
        bypass_reason=data.get("bypass_reason"),
        transition="finalize",
    )

    # Path C / Arch-3: delegate to shared `_perform_enrollment_core` (NOT
    # `enroll_student`) so finalize owns its own bundle without
    # double-dispatching the enroll bundle. Core handles the locked fetch +
    # student creation + state mutation; finalize just builds the
    # finalize-specific notification + commission callback.
    profile_id = profile.id
    locked_profile, enrollment_result, idempotent_skip, pre_status = (
        await _perform_enrollment_core(db, profile_id, admin)
    )

    log.info(
        "Admission profile finalized (enrolled)",
        profile_id=profile_id,
        admin_id=admin.id,
        student_code=enrollment_result["student_code"],
    )

    # Reload profile to get updated status (for response shape)
    from app.repositories import AdmissionRepository
    admission_repo = AdmissionRepository(db)
    profile = await admission_repo.reload_profile_with_lead(profile_id)

    # Populate transient computed fields so the mutation response matches GET.
    # reload_profile_with_lead already eager-loads documents, so reuse them.
    await _populate_response_fields(db, profile, admin, documents=profile.documents)

    # Idempotent re-finalize (profile already in 'enrolled' state): skip
    # bundle + commission to avoid double-firing notifications on retry.
    if idempotent_skip:
        async def _audit_only():
            log.info(
                "Post-commit: Enrollment finalized (idempotent skip)",
                profile_id=profile_id,
                student_code=enrollment_result["student_code"],
            )
        return profile, _audit_only

    # Paired notification bundle (sites admissions.py:2099+2114)
    bundle_callback = None
    if locked_profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": locked_profile.lead_id,
                    "old_status": pre_status,
                    "new_status": "enrolled",
                    "actor_id": admin.id,
                    "actor_name": admin.full_name or admin.username,
                },
                dedupe_key=f"admission_profile_finalized:{profile_id}",
                rooms=rooms_for_admission(locked_profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": locked_profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": pre_status,
                    "new_status": "sts11",
                    "actor_id": admin.id,
                    "actor_name": admin.full_name or admin.username,
                },
                dedupe_key=f"lead_status_changed:{locked_profile.lead_id}:sts11",
                rooms=rooms_for_admission(locked_profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_finalize", intents=intents,
        )
        bundle_callback = bundle.callback

    # Commission callback (router site admissions.py:2127)
    commission_callback = None
    if locked_profile.lead_id:
        captured_lead_id = locked_profile.lead_id
        captured_actor_id = admin.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, pre_status, "sts11", captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Enrollment finalized notification",
            profile_id=profile_id,
            student_code=enrollment_result["student_code"],
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_finalize",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback],
    )

    return profile, final_callback


def _remove_profile_upload_dir(profile_id: int) -> None:
    """Best-effort removal of a deleted profile's entire upload directory.

    All of a profile's uploads — path documents, priority-evidence files and
    the hidden ``.staging.{uuid}`` temp files — live under
    ``uploads/admissions/{id}/`` and can never escape it (see
    ``upload_document``). ``profile_document`` rows cascade-delete with the
    profile, but the files and the now-empty directory are not touched by the
    DB. ``shutil.rmtree`` drops docs + staging + the directory in one shot
    (the per-file loop used to leak staging files and the empty dir).

    A leftover file is storage waste, not a correctness issue — and this runs
    AFTER the delete commits — so EVERY failure is swallowed (post-commit
    cleanup must never raise and turn a successful delete into a 500).
    """
    import shutil

    upload_dir = f"uploads/admissions/{profile_id}"
    try:
        shutil.rmtree(upload_dir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 — best-effort, must never raise
        log.warning(
            "Failed to remove profile upload dir post-commit",
            upload_dir=upload_dir,
            error=str(e),
        )


# Lead consultation status the ``profile_created`` milestone moves a lead to
# (== ADMISSION_TO_LEAD_STATUS_MAP["draft"] in lead_admission_sync.py).
# IMPORTANT: sts06 is ALSO reachable via ``lead_agrees`` / a manual "Đồng ý
# tư vấn" — so being at sts06 does NOT imply this profile caused it. A revert
# must confirm the *most recent* lead status change was the profile-created
# bump (see delete_profile), otherwise it would mis-attribute an independent
# sts06 and silently demote the lead.
_CREATE_MILESTONE_STATUS = "sts06"

# Admission milestone event that bumps a lead to _CREATE_MILESTONE_STATUS.
# Shared by create_profile (fires the milestone) and delete_profile (detects it
# in the latest LeadStatusHistory.reason) so a rename can't silently desync them.
_PROFILE_CREATED_EVENT = "profile_created"


def _resolve_lead_revert_status(
    has_other_profile: bool,
    current_consultation_status_id: Optional[str],
    prev_consultation_status_id: Optional[str],
    prev_is_terminal_or_negative: bool = False,
) -> Optional[str]:
    """Decide which consultation status a lead reverts to when its last draft
    profile is deleted — or ``None`` to leave the lead untouched.

    Pure policy (no DB) so the rule is exhaustively unit-testable. Revert ONLY
    when ALL hold:
      * the lead has NO other admission profile (this was the last one), AND
      * the lead is still exactly at the create-milestone status (sts06) — i.e.
        nothing advanced it further (another profile's submit, an officer
        manual change, fee payment, …), AND
      * we know the status held BEFORE creation, it differs from sts06 (a
        self-revert would be a no-op), AND
      * that prior status is NOT terminal/negative — deleting a draft must
        never re-close a lead (e.g. a lost lead reopened to sts06 then a
        draft created+deleted should stay at sts06, not regress to sts20/
        "Đã ngừng tư vấn").
    """
    if has_other_profile:
        return None
    if current_consultation_status_id != _CREATE_MILESTONE_STATUS:
        return None
    if not prev_consultation_status_id:
        return None
    if prev_consultation_status_id == _CREATE_MILESTONE_STATUS:
        return None
    if prev_is_terminal_or_negative:
        return None
    return prev_consultation_status_id


async def delete_profile(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> Tuple[bool, Callable[[], Awaitable[None]], Optional[dict]]:
    """
    Delete AdmissionProfile (only when status='draft').

    Security:
    - IDOR: Check lead.unit_id == user.unit_id (unless admin)
    - State Locking: Only draft profiles can be deleted

    Behavior:
    - Conditionally reverts the lead's consultation status to its
      pre-creation value — ONLY when this was the lead's last profile AND
      the lead is still at the create-milestone status (sts06). Otherwise
      the lead status is preserved (it advanced on its own or another
      profile justifies it).
    - Keeps ALL existing consultation history (real data); ADDS a system
      consultation record noting the deletion, plus a LeadStatusHistory
      row when a revert actually happens.
    - Maintains full audit trail in timeline

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() after this function returns.

    Args:
        db: AsyncSession for database operations
        profile_id: AdmissionProfile ID to delete
        current_user: Current authenticated user

    Returns:
        Tuple of (True, post_commit_callback, lead_revert_delta):
        - post_commit_callback: removes the profile's upload dir (best-effort);
          MUST be awaited by the router AFTER ``db.commit()``.
        - lead_revert_delta: ``None``, or a dict
          ``{old_status, new_status, old_stage, new_stage}`` when the lead's
          status was reverted — the router uses it to dispatch
          LEAD_STATUS_CHANGED post-commit.

    Raises:
        ResourceNotFoundError: Profile not found
        ResourceNotFoundError: User doesn't have access (IDOR protection - returns 404)
        BadRequest: Status is not 'draft'
    """
    from app.repositories import AdmissionRepository

    admission_repo = AdmissionRepository(db)

    # Get profile with lead (for IDOR check)
    profile = await admission_repo.get_profile_by_id_with_lead(profile_id)

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR check
    _check_idor_access(profile, current_user)

    # State check: Only draft profiles can be deleted
    if profile.status != "draft":
        raise BadRequest(
            f"Cannot delete profile with status '{profile.status}'. "
            "Only draft profiles can be deleted."
        )

    lead = profile.lead
    lead_id = profile.lead_id

    # Serialize concurrent deletes on the SAME lead. Without this, two
    # simultaneous last-profile deletes each see the other profile still
    # present (READ COMMITTED) → both skip the revert → lead stuck at sts06
    # with zero profiles. Locking the lead row makes the count + revert
    # decision below run one-at-a-time per lead.
    await db.execute(
        select(models.Lead.id).where(models.Lead.id == lead_id).with_for_update()
    )

    # ==========================================================================
    # LEAD STATUS REVERT (conditional) + deletion consultation record
    # ==========================================================================
    # Creating a draft profile bumps the lead to sts06 "Đồng ý tư vấn" via the
    # ``profile_created`` milestone. Deleting that draft undoes the bump — but
    # ONLY when it is provably safe:
    #   (a) the lead has NO other admission profile left, AND
    #   (b) the lead's MOST RECENT status change was THIS profile's create bump
    #       (latest LeadStatusHistory row: new==sts06 + reason profile_created).
    #       This one check rules out both mis-attribution traps: a lead already
    #       at sts06 before creation (lead_agrees / manual) writes NO history
    #       row on create, and any intervening status change makes the create
    #       bump no longer the latest row — both ⇒ no revert, AND
    #   (c) the pre-creation status is known, differs from sts06, and is NOT
    #       terminal/negative (never re-close a lead by deleting a draft).
    # Consultation history is always KEPT (real data); we only ADD a system
    # record per the Golden Rule, plus a LeadStatusHistory row on revert.
    from ..core.status_mapping import sync_lead_status_from_consultation
    from .lead_service import _get_current_lead_state, _log_lead_state_change
    from ..models.pipeline import OutcomeTypeEnum

    _status_at_delete = lead.consultation_status_id

    # Only OTHER DRAFT profiles justify keeping the lead at the create milestone
    # (sts06 ↔ status 'draft' in ADMISSION_TO_LEAD_STATUS_MAP). A submitted/
    # approved/enrolled profile advanced the lead (caught by the latest-history
    # check below), and a completed prior-year profile (create dedups per
    # (lead_id, academic_year), so a re-engaged lead keeps old-year rows) is
    # historical — neither should block the revert.
    _other_draft_count = await db.scalar(
        select(func.count())
        .select_from(models.AdmissionProfile)
        .where(
            models.AdmissionProfile.lead_id == lead_id,
            models.AdmissionProfile.id != profile_id,
            models.AdmissionProfile.status == "draft",
        )
    )

    # The pre-creation status is recoverable ONLY when the lead's most recent
    # status change is this profile's create bump (sts06 also comes from
    # lead_agrees / manual consultation, so we must not key on sts06 alone).
    _latest_history = await db.scalar(
        select(models.LeadStatusHistory)
        .where(models.LeadStatusHistory.lead_id == lead_id)
        .order_by(models.LeadStatusHistory.id.desc())
        .limit(1)
    )
    _prev_status_id = None
    if (
        _latest_history is not None
        and _latest_history.new_consultation_status_id == _CREATE_MILESTONE_STATUS
        and _PROFILE_CREATED_EVENT in (_latest_history.reason or "")
    ):
        _prev_status_id = _latest_history.old_consultation_status_id

    # Load the candidate target once (reused on apply) + flag terminal/negative
    # so the policy helper can refuse to re-close a lead.
    _target_cs = None
    _prev_is_terminal_or_negative = False
    if _prev_status_id and _prev_status_id != _CREATE_MILESTONE_STATUS:
        # Only columns (stage_id / is_final / outcome_type) are read below, so a
        # bare db.get suffices — no need to eager-load the .stage relationship.
        _target_cs = await db.get(models.ConsultationStatus, _prev_status_id)
        if _target_cs is None:
            _prev_status_id = None  # unknown status — cannot revert safely
        else:
            _prev_is_terminal_or_negative = (
                bool(_target_cs.is_final)
                or _target_cs.outcome_type == OutcomeTypeEnum.negative
            )

    _revert_target = _resolve_lead_revert_status(
        has_other_profile=bool(_other_draft_count),
        current_consultation_status_id=lead.consultation_status_id,
        prev_consultation_status_id=_prev_status_id,
        prev_is_terminal_or_negative=_prev_is_terminal_or_negative,
    )

    reverted_status_id = None
    lead_revert_delta = None
    if _revert_target and _target_cs is not None:
        _old_state = _get_current_lead_state(lead)
        _old_stage_id = lead.pipeline_stage_id
        lead.consultation_status_id = _revert_target
        lead.pipeline_stage_id = _target_cs.stage_id
        sync_lead_status_from_consultation(lead, _target_cs)
        _new_state = _get_current_lead_state(lead)
        await _log_lead_state_change(
            db=db,
            lead=lead,
            old_state=_old_state,
            new_state=_new_state,
            changed_by=current_user,
            reason=f"Hoàn trạng thái sau khi xóa hồ sơ draft #{profile_id}",
        )
        reverted_status_id = _revert_target
        # Surfaced to the router so it dispatches LEAD_STATUS_CHANGED
        # post-commit (lead pipeline subscribers must see the revert).
        lead_revert_delta = {
            "old_status": _status_at_delete,
            "new_status": _revert_target,
            "old_stage": _old_stage_id,
            "new_stage": _target_cs.stage_id,
        }

    if reverted_status_id:
        _deletion_note = (
            f"[HỆ THỐNG] Hồ sơ xét tuyển #{profile_id} đã bị xóa — "
            "hoàn trạng thái tư vấn về trước khi tạo hồ sơ."
        )
    else:
        _deletion_note = (
            f"[HỆ THỐNG] Hồ sơ xét tuyển đã bị xóa - Profile #{profile_id}"
        )

    # Golden Rule: every admission event gets a consultation record. Stamp it
    # with the status the lead held AT deletion time (pre-revert), so the
    # timeline reflects the state when the action happened.
    system_consultation = models.Consultation(
        lead_id=lead_id,
        officer_id=current_user.id,
        consultation_status_id=_status_at_delete,
        consultation_date=datetime.now(timezone.utc),
        method="system",
        notes=_deletion_note,
        duration_minutes=0,
    )
    db.add(system_consultation)

    # Update lead timestamp
    lead.updated_at = datetime.now(timezone.utc)

    log.info(
        "Profile deletion consultation record created",
        lead_id=lead_id,
        profile_id=profile_id,
        status_at_delete=_status_at_delete,
        reverted_status_id=reverted_status_id,
        actor_id=current_user.id,
    )

    # Audit trail: log deletion
    from ..services import audit_service
    await audit_service.log_deleted(
        db, "AdmissionProfile", profile.id,
        actor_user_id=current_user.id,
        old_values={"lead_id": profile.lead_id, "status": profile.status},
        source="api",
    )

    # Delete the profile (profile_document rows cascade via FK ondelete=CASCADE).
    await db.delete(profile)
    await db.flush()

    log.info(
        "Admission profile deleted",
        profile_id=profile_id,
        lead_id=lead_id,
        user_id=current_user.id,
    )

    async def _post_commit_cleanup() -> None:
        # Drop the whole upload dir only after the delete is durably committed.
        _remove_profile_upload_dir(profile_id)

    return True, _post_commit_cleanup, lead_revert_delta


# ==============================================================================
# WITHDRAWAL
# ==============================================================================


async def withdraw_profile(
    db: AsyncSession,
    profile_id: int,
    actor: Optional[models.User],
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Withdraw admission profile.

    Allowed from: DRAFT, SUBMITTED, REJECTED, RESUBMITTED, REVISION_REQUESTED
    (state machine enforces — see ALLOWED_TRANSITIONS)
    Target: WITHDRAWN (final state)

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        actor: User performing withdrawal. ``None`` for candidate
            magic-link self-service path (CCCD already verified upstream).
            Audit/notification user-attribution fields fall back to
            null/system-labelled values when ``None``.
        data: WithdrawRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Invalid state transition or missing reason
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    # IDOR bypass when actor=None (magic-link path verifies CCCD).
    _check_idor_access(profile, actor)

    # Actor attribution capture (officer dashboard vs. magic-link
    # self-service). All downstream audit/notification consumers
    # already accept Optional ids; the human-readable label is used
    # only in notification payloads.
    _actor_id: Optional[int] = actor.id if actor else None
    _actor_name: str = (
        (actor.full_name or actor.username)
        if actor
        else "Ứng viên (magic-link)"
    )

    from .admission_state_machine import validate_transition

    try:
        validate_transition(profile.status, "withdrawn")
    except ValueError as e:
        log.warning(
            "Invalid state transition for withdraw",
            profile_id=profile.id,
            current_status=profile.status,
            error=str(e),
        )
        raise BadRequest(str(e))

    if not data.get("reason"):
        raise BadRequest("Withdrawal reason is required")

    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Caller still captures old_status for the legacy bundle below.
    _old_status_for_audit = profile.status

    # Phase 1 hotfix-2 + magic-link FU: enrich payload với ``from_status``
    # + ``withdrawn_by_role`` so the seeded ADMISSION_WITHDRAWN template's
    # placeholders resolve at render time. ``actor=None`` (magic-link
    # candidate self-service) maps to role "system" for the template.
    profile, transition_callback = await state_transition(
        db,
        profile,
        "withdrawn",
        actor=actor,
        reason=data["reason"],
        source="api",
        event_metadata={
            "from_status": _old_status_for_audit,
            "withdrawn_by_role": (actor.role if actor else "system"),
            "reason": data["reason"],
        },
    )

    # PIPELINE SYNC: Create system consultation for withdrawal milestone
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_withdrawn",
            actor=actor,
            profile_id=profile.id,
            reason=data["reason"],
        )

    await db.flush()

    # SYNC: Update lead consultation status (withdrawn → sts08)
    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=_actor_id,
        reason=f"Admission profile withdrawn: {data['reason'][:50]}",
    )

    log.info(
        "Admission profile withdrawn",
        profile_id=profile.id,
        actor_id=_actor_id,
        old_status=_old_status_for_audit,
    )

    # TUITION_PREPAY_FASTTRACK finding #1 — flag + warn về học phí trả trước
    # chưa hoàn khi rút hồ sơ. ``withdraw_profile`` không gọi
    # ``_populate_response_fields`` (response tối giản theo thiết kế), nên set
    # cờ trực tiếp qua helper nhẹ để mutation response có parity với GET. KHÔNG
    # chặn rút — hoàn tiền vẫn thủ công qua maker-checker.
    await _populate_unrefunded_payment_flag(db, profile)
    if getattr(profile, "has_unrefunded_payment", False):
        from app.repositories.fee_repository import FeeRepository

        _total_paid = await FeeRepository(db).sum_paid_amount_by_profile(profile.id)
        log.warning(
            "Profile withdraw với khoản học phí chưa hoàn",
            profile_id=profile.id,
            total_paid=str(_total_paid),
            status=profile.status,
        )

    # Path C / Arch-3: build atomic notification bundle for the paired
    # transition (APPLICATION_STATUS_CHANGED + LEAD_STATUS_CHANGED).
    # Withdraw is the one paired flow that does NOT have a commission
    # check (withdrawn lead does not trigger commission); only the
    # bundle callback is composed.
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": _old_status_for_audit,
                    "new_status": "withdrawn",
                    "actor_id": _actor_id,
                    "actor_name": _actor_name,
                },
                dedupe_key=f"admission_profile_withdrawn:{profile_id}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": _old_status_for_audit,
                    "new_status": "sts08",
                    "actor_id": _actor_id,
                    "actor_name": _actor_name,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts08",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_withdraw", intents=intents,
        )
        bundle_callback = bundle.callback

    async def _audit_log_callback():
        """Existing post-commit log preserved for parity."""
        log.info(
            "Post-commit: Profile withdrawn notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_withdraw",
        callbacks=[_audit_log_callback, bundle_callback, transition_callback],
    )

    return profile, final_callback


# ==============================================================================
# MINOR CORRECTION (post-approval governed update)
# ==============================================================================

async def apply_minor_correction(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    payload: "MinorCorrectionRequest",  # forward-ref to avoid import cycle below
    current_user: models.User,
) -> Tuple[models.AdmissionProfile, Dict[str, Any]]:
    """Apply a post-approval correction governed by SAFE catalog ∩ per-path allowlist.

    Contract:
    - ``profile`` MUST be eager-loaded with ``lead.assigned_officer`` and
      ``assigned_reviewer`` (router calls ``get_admission_for_user`` which
      already does this + ``with_for_update`` lock).
    - Returns ``(profile, socket_envelope)``. The router commits, then
      uses ``socket_envelope["payload"]`` + ``["rooms"]`` for a
      ``safe_dispatch`` post-commit. We do NOT dispatch here because the
      bundle pattern is overkill — minor correction emits one
      broadcast-only event with no DB rule.

    Status whitelist (NOT blacklist) — only ``approved`` and ``confirmed``
    accept corrections. ``draft`` / ``submitted`` go through update_profile;
    ``rejected`` / ``revision_requested`` use resubmit; ``enrolled`` /
    ``overridden`` / ``withdrawn`` / ``dropped`` are out of scope for v1.

    Order of checks matters — defence in depth:
    1. Status whitelist (cheapest)
    2. Optimistic version (avoids wasted parsing on stale request)
    3. Path resolution (live, never snapshotted) → effective allowlist
    4. HARD_DENY check BEFORE allowlist check so a hard-denied key
       always rejects with the same message regardless of path config
    5. Per-field type parse + business-rule check
    6. Diff old vs normalized new — empty diff means caller resent the
       same values; reject so admin doesn't see noise audit rows.
    """
    # Local import: schema lives in same package, but defining the
    # forward-ref string above keeps the type hint happy if the schema
    # module is imported at a different time.
    from ..schemas.admission import MinorCorrectionRequest  # noqa: F401
    from ..services import audit_service

    # 1. Status whitelist — admitted-like (legacy approved/overridden +
    # choice-engine admitted) plus confirmed.
    if not (is_admitted_like(profile) or profile.status == "confirmed"):
        raise BusinessRuleViolation(
            "Hiệu chỉnh chỉ áp dụng cho hồ sơ đã duyệt (approved) hoặc đã xác nhận (confirmed)"
        )

    # 2. Optimistic lock — pattern khớp admission_service.py:2424 / 4091 /
    # 4309 / 4501 / 4877 (approve / reject / etc).
    if payload.version != profile.version:
        raise ConflictError(
            f"Expected version {payload.version}, but current version is "
            f"{profile.version}. Refresh and try again."
        )

    # 3. Resolve effective allowlist live from AdmissionPath.
    # admission_path_id sits in applied_rules snapshot (admission_service.py:1956).
    path_id = (profile.applied_rules or {}).get("admission_path_id")
    if not path_id:
        raise BusinessRuleViolation(
            "Hồ sơ thiếu admission_path_id trong applied_rules — không thể hiệu chỉnh"
        )

    from ..repositories import AdmissionPathRepository
    path = await AdmissionPathRepository(db).get_by_id(path_id)
    if path is None:
        raise BusinessRuleViolation(
            "AdmissionPath gắn với hồ sơ đã bị xoá — không thể hiệu chỉnh"
        )

    effective_allowlist = SAFE_MINOR_CORRECTION_FIELDS & set(
        path.minor_correction_allowed_fields or []
    )
    if not effective_allowlist:
        raise BusinessRuleViolation(
            "AdmissionPath chưa bật field nào cho hiệu chỉnh — liên hệ admin"
        )

    # 4. Hard-deny first — even if a future bug puts a hard-denied key
    # in the path config, this check still rejects.
    requested = set(payload.changes.keys())
    hard_denied = requested & HARD_DENY_FIELDS
    if hard_denied:
        raise ValidationError(
            f"Các trường sau không thể sửa qua flow hiệu chỉnh: {sorted(hard_denied)}"
        )

    not_allowed = requested - effective_allowlist
    if not_allowed:
        raise ValidationError(
            f"Các trường sau không nằm trong allowlist của path này: {sorted(not_allowed)}"
        )

    # 5. Per-field parse + normalize, business-rule check.
    from pydantic import ValidationError as PydanticValidationError

    normalized: Dict[str, Any] = {}
    for field_key, raw_value in payload.changes.items():
        try:
            normalized[field_key] = parse_and_normalize(field_key, raw_value)
        except PydanticValidationError as exc:
            # Surface the first error message in human-readable form.
            errors = exc.errors()
            first_msg = errors[0]["msg"] if errors else "invalid value"
            raise ValidationError(f"{field_key}: {first_msg}")

        biz_err = post_parse_business_check(field_key, normalized[field_key])
        if biz_err:
            raise ValidationError(biz_err)

    # 5b. Cross-field invariants on the candidate state (existing DB
    # values overlaid with normalized changes). Delegate to shared
    # utility — same rules schema's @model_validator runs, plus a few
    # the schema can't see because partial dump strips DB-only fields.
    # Lesson reference: feedback memory
    # ``partial-update-loses-cross-field-invariants``.
    from .admission_invariants import validate_logical_dates
    candidate_state = {
        "dob": profile.dob,  # HARD_DENY → always original DB value
        "union_entry_date": normalized.get(
            "union_entry_date", profile.union_entry_date
        ),
        "party_entry_date": normalized.get(
            "party_entry_date", profile.party_entry_date
        ),
        "party_official_entry_date": normalized.get(
            "party_official_entry_date", profile.party_official_entry_date
        ),
    }
    try:
        validate_logical_dates(candidate_state)
    except ValueError as exc:
        raise ValidationError(str(exc))

    # 6. Diff — compare AFTER normalization so e.g. "2025-09-01" parsing
    # to datetime(2025,9,1) doesn't false-diff against an existing
    # datetime(2025,9,1). Apply only fields that actually changed.
    diff: Dict[str, Dict[str, Any]] = {}
    for field_key, new_val in normalized.items():
        old_val = getattr(profile, field_key)
        if old_val != new_val:
            diff[field_key] = {
                "old": safe_serialize(old_val),
                "new": safe_serialize(new_val),
            }
            setattr(profile, field_key, new_val)

    if not diff:
        raise BusinessRuleViolation(
            "Không có thay đổi nào — giá trị mới trùng giá trị cũ"
        )

    # 7. Version bump + flush
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # 8. Audit log — past-tense action keeps log_changes convention.
    await audit_service.log_changes(
        db,
        entity_type="AdmissionProfile",
        entity_id=profile.id,
        action="minor_corrected",
        changes=diff,
        actor_user_id=current_user.id,
        reason=payload.reason,
    )

    # 9. Pre-resolve socket envelope IN-TRANSACTION while profile.lead is
    # still loaded. Router will safe_dispatch post-commit so a network /
    # socket glitch never rolls back the business mutation.
    socket_envelope = {
        "payload": {
            "application_id": profile.id,
            "lead_id": profile.lead_id,
            "changed_fields": sorted(diff.keys()),  # KEYS ONLY — no PII
            "actor_id": current_user.id,
            "corrected_at": datetime.now(timezone.utc).isoformat(),
        },
        # Required because catalog marks the event privacy="sensitive";
        # dispatcher fail-closed guard would block a no-rooms emit.
        "rooms": rooms_for_admission(profile),
    }

    # 10. Re-populate response fields. Pass documents=None — get_admission_for_user
    # eager-loaded lead/officer/reviewer but NOT documents, so passing
    # profile.documents would lazy-load (MissingGreenlet). The helper
    # falls through to AdmissionRepository.get_all_documents.
    # NOTE: _populate_response_fields calls _resolve_minor_correction_state
    # at its tail (see plumbing in next section), so we DO NOT call the
    # resolver again here — would be one wasted path query.
    await _populate_response_fields(db, profile, current_user, documents=None)

    return profile, socket_envelope


async def mark_student_dropped(
    db: AsyncSession,
    profile_id: int,
    actor: models.User,
    data: Dict[str, Any],
) -> tuple[models.AdmissionProfile, Any]:
    """
    Mark an enrolled student as dropped out (Manager/Admin action).

    Side-channel: status stays "enrolled", sets is_dropped=True.
    Milestone consultation handles lead sync to sts12.

    Args:
        db: Database session
        profile_id: AdmissionProfile ID
        actor: User marking the drop
        data: DropStudentRequest data (reason - required, version - required)

    Returns:
        Tuple of (updated_profile, post_commit_callback)

    Raises:
        BadRequest: Profile not enrolled or already dropped
        ConflictError: Version mismatch
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(f"Admission profile {profile_id} not found")

    _check_idor_access(profile, actor)

    # W7-A.1 fix 2026-05-16: VERSION CHECK BEFORE STATE GUARDS.
    # Race on drop: 2 admins click "mark dropped" concurrently with same
    # version. First commits; second should see 409, not 400 "Student is
    # already marked as dropped" — that wording suggests data error,
    # actually it's a race.
    if data["version"] != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {data['version']}, but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Guard: Must be enrolled
    if profile.status != "enrolled":
        raise BadRequest(
            f"Cannot mark as dropped: profile is in '{profile.status}' status. "
            "Only enrolled students can be marked as dropped."
        )

    # Guard: Already dropped
    if profile.is_dropped:
        raise BadRequest("Student is already marked as dropped out.")

    if not data.get("reason"):
        raise BadRequest("Drop reason is required (min 10 characters)")

    # Side-channel: DO NOT change profile.status (stays "enrolled")
    profile.is_dropped = True
    profile.dropped_at = datetime.now(timezone.utc)
    profile.dropped_by_id = actor.id
    profile.dropped_reason = data["reason"]
    profile.version += 1
    profile.updated_at = datetime.now(timezone.utc)

    # PIPELINE SYNC: Milestone consultation handles lead sync to sts12/stg07
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="student_dropped",
            actor=actor,
            profile_id=profile.id,
        )

    await db.flush()

    # Populate transient computed fields so the mutation response matches GET.
    await _populate_response_fields(db, profile, actor)

    # Audit trail
    from ..services import audit_service
    await audit_service.log_status_change(
        db, "AdmissionProfile", profile.id,
        old_status="enrolled", new_status="enrolled (dropped)",
        actor_user_id=actor.id,
        reason=data["reason"],
        source="api",
    )

    log.info(
        "Student marked as dropped",
        profile_id=profile.id,
        actor_id=actor.id,
    )

    # Path C / Arch-3: paired notification bundle.
    # NOTE: profile.status stays "enrolled" but the notification +
    # commission semantics treat this as a lead-status transition
    # sts11 (đã nhập học) -> sts12 (đã thôi học). Router payload at
    # admissions.py:2386+2401 uses literal "enrolled" / "enrolled_dropped"
    # for the application-side and "sts11" / "sts12" for the lead-side;
    # we preserve those exact strings here.
    bundle_callback = None
    if profile.lead_id:
        intents = [
            NotificationIntent(
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile_id,
                    "lead_id": profile.lead_id,
                    "old_status": "enrolled",
                    "new_status": "enrolled_dropped",
                    "actor_id": actor.id,
                    "actor_name": actor.full_name or actor.username,
                },
                dedupe_key=f"admission_profile_dropped:{profile.id}",
                rooms=rooms_for_admission(profile),
            ),
            NotificationIntent(
                event=SystemEvents.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": profile.lead_id,
                    "lead_name": f"Profile #{profile_id}",
                    "old_status": "sts11",
                    "new_status": "sts12",
                    "actor_id": actor.id,
                    "actor_name": actor.full_name or actor.username,
                },
                dedupe_key=f"lead_status_changed:{profile.lead_id}:sts12",
                rooms=rooms_for_admission(profile),
            ),
        ]
        bundle = await dispatch_bundle(
            db, bundle_label="admission_drop_student", intents=intents,
        )
        bundle_callback = bundle.callback

    # Commission callback — SPECIAL CASE: literal sts11 -> sts12 args
    # (NOT the generic _old_status / _new_lead_status template). Profile
    # status stays "enrolled"; the lead transition is the meaningful one
    # for commission purposes. Router today calls with these exact args
    # at admissions.py:2415.
    commission_callback = None
    if profile.lead_id:
        captured_lead_id = profile.lead_id
        captured_actor_id = actor.id

        async def _commission_callback():
            await safe_check_commission_on_status_change(
                db, captured_lead_id, "sts11", "sts12", captured_actor_id,
            )

        commission_callback = _commission_callback

    async def _audit_log_callback():
        log.info(
            "Post-commit: Student dropped notification",
            profile_id=profile.id,
        )

    final_callback = compose_post_commit_callbacks(
        label="admission_drop_student",
        callbacks=[_audit_log_callback, bundle_callback, commission_callback],
    )

    return profile, final_callback


# ==============================================================================
# CONFIRMATION TOKEN FUNCTIONS (Magic Link)
# ==============================================================================


async def generate_action_magic_link(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    action: str,
) -> models.AdmissionConfirmationToken:
    """Generate magic link token cho 1 trong 3 actions self-service
    candidate: submit / resubmit / withdraw (W2-1 fix Wave 7 2026-05-16).

    Mirror semantic của ``generate_confirmation_token`` (action='confirm')
    nhưng:
    - Generic — accept ``action`` param
    - State validation per-action (vs confirmation-eligible only)
    - KHÔNG có Celery email task (officer copy URL từ FE dialog →
      share manual qua Zalo/SMS — pattern reuse SendConfirmationButton).
      Email auto-send Celery task có thể wire FU sau khi product clarify
      template Vietnamese cho từng action.

    State validation per action (mirror CONSUME-side magic_link_service
    handler precheck, fail-fast trước khi token generated):
    - submit:    profile.status == 'draft'
    - resubmit:  profile.status == 'revision_requested'
    - withdraw:  profile.status in (draft, submitted, reviewing, rejected,
                                    resubmitted, revision_requested,
                                    waitlisted)

    Args:
        db: Database session
        profile: AdmissionProfile
        action: One of submit | resubmit | withdraw (NOT confirm —
                use generate_confirmation_token cho confirm path)

    Returns:
        AdmissionConfirmationToken row (single per profile, overwrites
        any existing — officer chỉ tạo 1 active magic-link tại 1 thời
        điểm cho mỗi candidate).

    Raises:
        BadRequest: action invalid hoặc profile.status không phù hợp
    """
    import secrets
    from datetime import timedelta, datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository

    if action not in ("submit", "resubmit", "withdraw"):
        raise BadRequest(
            f"Action '{action}' không hỗ trợ. Chỉ chấp nhận: "
            "submit, resubmit, withdraw. Dùng /send-confirmation cho confirm."
        )

    # State validation per action — mirror magic_link_service handler
    # precheck cho fast-fail UX (avoid generating link rồi candidate
    # click → 400 state mismatch).
    status = profile.status
    if action == "submit" and status != "draft":
        raise BadRequest(
            f"Chỉ tạo magic-link 'submit' khi hồ sơ ở trạng thái 'draft'. "
            f"Trạng thái hiện tại: '{status}'."
        )
    if action == "resubmit" and status != "revision_requested":
        raise BadRequest(
            f"Chỉ tạo magic-link 'resubmit' khi hồ sơ ở trạng thái "
            f"'revision_requested'. Trạng thái hiện tại: '{status}'."
        )
    if action == "withdraw" and status not in (
        "draft", "submitted", "reviewing", "rejected",
        "resubmitted", "revision_requested", "waitlisted",
    ):
        raise BadRequest(
            f"Hồ sơ ở trạng thái '{status}' không thể tạo magic-link "
            f"'withdraw' (hồ sơ đã ở trạng thái cuối)."
        )

    # Generate secure token + repo upsert with action_type
    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS
    )
    repo = AdmissionRepository(db)
    token_obj = await repo.create_confirmation_token(
        profile_id=profile.id,
        token=token_value,
        expires_at=expires_at,
        action_type=action,
    )

    log.info(
        "Magic-link token generated for action",
        profile_id=profile.id,
        action=action,
        token_id=token_obj.id,
        expires_at=expires_at.isoformat(),
    )

    return token_obj


async def generate_confirmation_token(
    db: AsyncSession,
    profile: models.AdmissionProfile,
) -> tuple[models.AdmissionConfirmationToken, callable]:
    """
    Generate magic link confirmation token for approved profile.
    
    Called by: approve_profile() or send_confirmation endpoint.
    
    Args:
        db: Database session
        profile: Approved AdmissionProfile
        
    Returns:
        Tuple of (token_object, email_callback)
        
    Raises:
        BadRequest: Profile status is not 'approved'
    """
    import secrets
    from datetime import timedelta, datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository
    
    # Validate profile status — confirmation-eligible only (legacy
    # ``approved`` + choice-engine ``admitted``). ``overridden`` is
    # intentionally excluded: the admin-override transition routes
    # directly to ``enrolled`` and must NOT surface a candidate-facing
    # confirmation flow.
    if not is_confirmation_eligible(profile):
        raise BadRequest(
            f"Cannot generate confirmation token for profile with status '{profile.status}'. "
            "Only approved/admitted profiles can receive confirmation links."
        )

    # ADM-023 / Q9-C2 (2026-04-29): per-profile resend cap. The same
    # entry point handles initial issuance (auto-fired by approve)
    # AND operator-driven resends; cap=3 means each profile gets one
    # automatic + two manual resends per 24h before requiring support.
    # Fail-closed when Redis is down (None) so a brittle cache is not
    # an excuse to lift the spam cap — see resend_limit module
    # docstring for the rationale.
    from .admission_confirmation_resend_limit import (
        consume_resend_quota,
        RESEND_CAP_PER_24H,
    )
    count = await consume_resend_quota(profile.id)
    if count is None:
        raise BadRequest(
            "Tạm thời không thể gửi lại liên kết xác nhận do hệ thống đang "
            "bận. Vui lòng thử lại sau ít phút."
        )
    if count > RESEND_CAP_PER_24H:
        # Audit: persistent record so ops can correlate user reports
        # with the cap. Run on a separate session so the row survives
        # the BadRequest rollback.
        from ..database import AsyncSessionLocal
        from ..services import audit_service

        try:
            async with AsyncSessionLocal() as audit_db:
                await audit_service.log_audit(
                    audit_db,
                    entity_type="AdmissionProfile",
                    entity_id=profile.id,
                    action="confirmation_resend_rate_limited",
                    actor_user_id=None,
                    changes={
                        "attempt_count_in_window": {"old": None, "new": count},
                        "cap": {"old": None, "new": RESEND_CAP_PER_24H},
                    },
                    reason="Per-profile 24h resend cap reached",
                    source="magic_link",
                )
                await audit_db.commit()
        except Exception as audit_err:  # noqa: BLE001 — best-effort audit
            log.error(
                "Resend rate-limit audit write FAILED",
                profile_id=profile.id,
                error=str(audit_err),
            )

        raise BadRequest(
            f"Đã gửi lại liên kết {RESEND_CAP_PER_24H} lần trong 24 giờ qua. "
            "Vui lòng liên hệ phòng tuyển sinh nếu cần hỗ trợ thêm."
        )

    # Generate secure token
    token_value = secrets.token_urlsafe(32)  # 256-bit entropy
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS
    )

    # Create token via repository
    repo = AdmissionRepository(db)
    token_obj = await repo.create_confirmation_token(
        profile_id=profile.id,
        token=token_value,
        expires_at=expires_at,
    )
    
    log.info(
        "Confirmation token generated",
        profile_id=profile.id,
        token_id=token_obj.id,
        expires_at=expires_at.isoformat(),
    )
    
    # Post-commit callback for sending email
    async def _send_email_callback():
        from ..tasks.email_tasks import send_magic_link_confirmation_task

        lead = profile.lead
        if not lead or not lead.email:
            log.warning(
                "Skip magic-link email: no lead or email",
                profile_id=profile.id,
                token_id=token_obj.id,
            )
            return

        try:
            confirm_url = (
                f"{settings.FRONTEND_URL.rstrip('/')}/confirm/{token_obj.token}"
            )
            send_magic_link_confirmation_task.delay(
                email_to=lead.email,
                confirm_url=confirm_url,
                lead_name=lead.full_name or "Học viên",
                expires_at_iso=token_obj.expires_at.isoformat(),
                expires_days=settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS,
                lang="vi",
            )
            log.info(
                "POST-COMMIT: queued magic link email",
                profile_id=profile.id,
                token_id=token_obj.id,
            )
        except Exception as e:
            # Non-fatal: token đã commit, HTTP response phải thành công.
            # Operator có thể manual re-send qua POST /admissions/{id}/send-confirmation.
            log.error(
                "POST-COMMIT: failed to enqueue magic link email",
                profile_id=profile.id,
                token_id=token_obj.id,
                error=str(e),
                exc_info=True,
            )

    return token_obj, _send_email_callback


async def get_token_info(
    db: AsyncSession,
    token_value: str,
) -> dict:
    """
    Get token info for frontend to display confirmation form.
    
    Called by: GET /confirm/{token}
    
    Args:
        db: Database session
        token_value: Token string from URL
        
    Returns:
        Dict with token status info for ConfirmTokenInfoResponse
        
    Raises:
        ResourceNotFoundError: Token not found
    """
    from datetime import datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository
    
    repo = AdmissionRepository(db)
    token_obj = await repo.get_token_by_value(token_value)
    
    if not token_obj:
        raise ResourceNotFoundError("Invalid or expired confirmation link")
    
    now = datetime.now(timezone.utc)
    is_expired = token_obj.expires_at < now
    is_locked = token_obj.locked_at is not None
    is_used = token_obj.confirmed_at is not None
    attempts_remaining = max(0, settings.ADMISSION_CONFIRM_MAX_ATTEMPTS - token_obj.attempt_count)
    
    # Get lead name from profile
    profile_name = "Học viên"
    if token_obj.profile and token_obj.profile.lead:
        profile_name = token_obj.profile.lead.full_name or profile_name
    
    # Token is only valid if profile is still in a confirmation-eligible
    # state (legacy ``approved`` + choice-engine ``admitted``).
    # ``overridden`` is excluded — admin force-approval skips the
    # candidate confirmation step (state machine: overridden → enrolled).
    profile_not_approved = (
        token_obj.profile is not None
        and not is_confirmation_eligible(token_obj.profile)
    )

    return {
        "valid": not (is_expired or is_locked or is_used or profile_not_approved),
        "expired": is_expired,
        "locked": is_locked,
        "already_used": is_used,
        "attempts_remaining": attempts_remaining,
        "profile_name": profile_name,
        "expires_at": token_obj.expires_at,
    }


async def verify_and_confirm(
    db: AsyncSession,
    token_value: str,
    last_digits: str,
    token_obj: Optional[models.AdmissionConfirmationToken] = None,
) -> tuple[models.AdmissionProfile, callable]:
    """
    Verify CCCD and confirm admission via token.

    Called by: POST /confirm/{token}  (legacy single-action surface)
               POST /api/v2/admissions/magic-link/confirm/{token}  (v2 multi-action)

    Steps:
    1. Validate token (exists, not expired, not used, not locked)
    2. Verify last 4 digits of citizen_id
    3. If match: confirm profile, mark token used
    4. If mismatch: increment attempts, lock if exceeded

    Args:
        db: Database session
        token_value: Token string from URL
        last_digits: Last 4 digits of CCCD from user input
        token_obj: H3 review FU (2026-05-14) — caller may pass a
            pre-fetched + locked token row (e.g. magic_link_service has
            already invoked ``get_token_for_confirm`` to apply rate
            limits + action-enum matching). When provided, the helper
            skips the second round-trip lock acquisition and reuses
            the caller's locked snapshot. Identity-map semantics make
            this safe within the same ``AsyncSession``. If ``None``
            (legacy default), behaviour unchanged.

    Returns:
        Tuple of (updated_profile, notification_callback)

    Raises:
        ResourceNotFoundError: Token not found
        BadRequest: Token expired/used/locked or CCCD mismatch
    """
    from datetime import datetime, timezone
    from app.config import settings
    from app.repositories import AdmissionRepository

    # Repo is used unconditionally further below for
    # ``increment_token_attempts`` regardless of whether the caller
    # pre-fetched the locked token row.
    repo = AdmissionRepository(db)

    # H3 review FU (2026-05-14): skip the second ``get_token_for_confirm``
    # round-trip when the caller already holds the locked row. ADM-013
    # 3-step profile-first lock semantics still hold because the caller's
    # fetch ran inside the same session/transaction (identity map keeps
    # the locked row in scope until commit/rollback).
    if token_obj is None:
        # ADM-013: ``get_token_for_confirm`` performs a profile-first
        # 3-step lock (resolve profile_id → SELECT profile FOR UPDATE →
        # SELECT token FOR UPDATE → re-validate FK) so confirm shares
        # the same lock order as override/finalize. The token row +
        # ``token_obj.profile`` are both locked when we proceed below;
        # mutations land under the same row lock.
        token_obj = await repo.get_token_for_confirm(token_value)

    if not token_obj:
        raise ResourceNotFoundError("Invalid or expired confirmation link")

    now = datetime.now(timezone.utc)

    # Check token status
    if token_obj.confirmed_at is not None:
        raise BadRequest("This confirmation link has already been used")

    if token_obj.locked_at is not None:
        raise BadRequest(
            "This confirmation link has been locked due to too many failed attempts. "
            "Please contact support for assistance."
        )

    if token_obj.expires_at < now:
        raise BadRequest("This confirmation link has expired. Please request a new link.")

    # ADM-023 (2026-04-29): hybrid cooldown gate. Sliding ``lock_until``
    # is set on every failed attempt by the cooldown ladder; serving a
    # retry while it's still in the future would defeat the brute-force
    # defence. Distinct from ``locked_at`` (hard lock) above —
    # ``lock_until`` clears itself by passage of time, ``locked_at``
    # only by an admin.
    if token_obj.lock_until is not None and token_obj.lock_until > now:
        retry_in_seconds = int((token_obj.lock_until - now).total_seconds())
        raise BadRequest(
            f"Quá nhiều lần nhập sai. Vui lòng thử lại sau {retry_in_seconds} giây."
        )

    # Get profile and verify CCCD
    profile = token_obj.profile
    if not profile or not profile.citizen_id:
        raise BadRequest("Profile data is incomplete. Please contact support.")

    # Verify last 4 digits
    expected_digits = profile.citizen_id[-settings.ADMISSION_CONFIRM_CCCD_DIGITS:]

    if last_digits != expected_digits:
        # ADM-023 (2026-04-29): hybrid cooldown ladder + hard-lock at 30.
        # Step 1 — bump the attempt counter. We pass HARD_LOCK_THRESHOLD
        # (30) instead of the legacy ``ADMISSION_CONFIRM_MAX_ATTEMPTS``
        # (5) so the repo helper's "lock when count >= max" branch
        # fires at the SAME threshold the ladder uses for hard lock.
        # Without this, the legacy 5-attempt lock would short-circuit
        # the ladder before the 30/120/1440-minute cooldowns ever
        # kicked in. The legacy setting is kept for the FE
        # "attempts_remaining" display only.
        from .admission_confirmation_cooldown import (
            HARD_LOCK_THRESHOLD,
            cooldown_minutes_for,
            is_hard_lock,
        )
        await repo.increment_token_attempts(token_obj, HARD_LOCK_THRESHOLD)
        from datetime import timedelta as _timedelta

        if is_hard_lock(token_obj.attempt_count):
            # Hard lock. ``locked_at`` may have been set already by the
            # repo helper at the legacy MAX_ATTEMPTS threshold; either
            # way we mirror it here so audit + ``lock_count`` always
            # advance on the actual hard-lock crossing.
            if token_obj.locked_at is None:
                token_obj.locked_at = now
            token_obj.lock_count = (token_obj.lock_count or 0) + 1
            token_obj.lock_until = None  # superseded by hard lock

            # Audit so compliance can reconstruct who attempted to brute
            # force which profile, when. ``actor_user_id=None`` because
            # the magic-link path is public/applicant-driven.
            from ..services import audit_service
            await audit_service.log_audit(
                db,
                entity_type="AdmissionConfirmationToken",
                entity_id=token_obj.id,
                action="confirmation_hard_locked",
                actor_user_id=None,
                changes={
                    "attempt_count": {
                        "old": None,
                        "new": token_obj.attempt_count,
                    },
                    "lock_count": {
                        "old": None,
                        "new": token_obj.lock_count,
                    },
                    "profile_id": {"old": None, "new": profile.id},
                },
                reason="≥30 failed CCCD attempts",
                source="magic_link",
            )

            # Operator awareness: dispatch hard-lock event so
            # officer/manager can proactively reach out and unlock.
            # The router commits the BadRequest-side mutations (audit
            # + locked_at + lock_count) at the ``except BadRequest``
            # branch, so the dispatch's post-commit callback also runs
            # AFTER that commit. We attach the callback to the
            # exception and the router awaits it before raising the
            # HTTP error — without this hand-off browser realtime +
            # email enqueue would never happen.
            from .notification_dispatcher import dispatch as _dispatch
            from .notification_dispatcher import rooms_for_admission
            hard_lock_cb = None
            try:
                _, hard_lock_cb = await _dispatch(
                    db=db,
                    event=SystemEvents.ADMISSION_CONFIRMATION_HARD_LOCKED,
                    payload={
                        "application_id": profile.id,
                        "token_id": token_obj.id,
                        "attempt_count": token_obj.attempt_count,
                        "lock_count": token_obj.lock_count,
                        "locked_at_iso": token_obj.locked_at.isoformat()
                        if token_obj.locked_at
                        else now.isoformat(),
                        "lead_id": profile.lead_id,
                        "lead_name": (
                            profile.lead.full_name
                            if profile.lead
                            else "Học viên"
                        ),
                    },
                    rooms=rooms_for_admission(profile),
                )
            except Exception as dispatch_err:  # noqa: BLE001 — best-effort
                # Dispatch failure must NOT block the hard-lock
                # response — the audit row is already written
                # in-txn so compliance is captured. Notification is
                # operator-courtesy, not safety-critical.
                log.error(
                    "Magic-link hard-lock dispatch failed",
                    token_id=token_obj.id,
                    profile_id=profile.id,
                    error=str(dispatch_err),
                )

            log.warning(
                "Magic-link hard lock triggered",
                token_id=token_obj.id,
                profile_id=profile.id,
                attempt_count=token_obj.attempt_count,
                lock_count=token_obj.lock_count,
            )
            exc = BadRequest(
                "Liên kết xác nhận đã bị khóa do quá nhiều lần nhập sai. "
                "Vui lòng liên hệ phòng tuyển sinh để được mở khóa."
            )
            # Hand the post-commit callback back to the router. The
            # router commits the BadRequest-side mutations (the
            # ``except BadRequest`` branch in admissions.py
            # ``confirm_admission_via_magic_link`` already does
            # ``await db.commit()`` then raises) and we want the
            # notification fanout to run AFTER that commit, not
            # before — otherwise the notification can reference
            # state that hasn't been persisted yet.
            if hard_lock_cb is not None:
                exc.post_commit_callback = hard_lock_cb  # type: ignore[attr-defined]
            raise exc

        cooldown_min = cooldown_minutes_for(token_obj.attempt_count) or 0
        token_obj.lock_until = now + _timedelta(minutes=cooldown_min)
        attempts_remaining = max(
            0, settings.ADMISSION_CONFIRM_MAX_ATTEMPTS - token_obj.attempt_count
        )

        log.warning(
            "CCCD verification failed",
            token_id=token_obj.id,
            profile_id=profile.id,
            attempt_count=token_obj.attempt_count,
            cooldown_minutes=cooldown_min,
            attempts_remaining=attempts_remaining,
        )
        raise BadRequest(
            f"Incorrect CCCD digits. {attempts_remaining} attempts remaining."
        )
    
    # CCCD matches — validate profile state before confirming
    from .admission_state_machine import validate_transition

    if not is_confirmation_eligible(profile):
        log.warning(
            "Magic-link confirm rejected: profile not in confirmation-eligible state",
            profile_id=profile.id,
            current_status=profile.status,
            token_id=token_obj.id,
        )
        raise BadRequest(
            "Liên kết xác nhận không còn hiệu lực. "
            "Hồ sơ đã được xử lý hoặc trạng thái đã thay đổi."
        )

    # state_transition validates ``profile.status → "confirmed"`` via
    # the state machine; it raises ``BusinessRuleViolation`` (not the
    # ``ValueError`` the legacy validate_transition raised), so the
    # caller maps to BadRequest with the same message. Pre-transition
    # status capture moves into transition() — the helper handles both
    # legacy ``approved`` and choice-engine ``admitted`` upstream
    # consistently for the audit row + ADMISSION_CONFIRMED dispatch
    # payload's ``old_status`` field.
    try:
        # Phase 1 hotfix-2: same pattern as revision_requested —
        # ``extra_fields`` writes the column, ``event_metadata``
        # mirrors the value into the dispatch payload so the
        # seeded ADMISSION_CONFIRMED template's ``$confirmed_via``
        # placeholder resolves at render time.
        profile, transition_callback = await state_transition(
            db,
            profile,
            "confirmed",
            actor=None,  # public flow, no authenticated actor
            reason="Magic-link confirmation",
            source="magic_link",
            extra_fields={
                "confirmed_at": now,
                "confirmed_via": "magic_link",
            },
            event_metadata={"confirmed_via": "magic_link"},
        )
    except BusinessRuleViolation as e:
        raise BadRequest(str(e))

    # Mark token as consumed (no longer changes profile status)
    await repo.mark_token_used(token_obj)

    # PIPELINE SYNC: milestone consultation + lead sync
    if profile.lead:
        await _create_admission_milestone_consultation(
            db=db,
            lead=profile.lead,
            event="profile_confirmed",
            actor=None,  # public flow, no authenticated actor
            profile_id=profile.id,
            fallback_officer_id=profile.approved_by_id,
        )

    from .lead_admission_sync import sync_lead_from_admission
    await sync_lead_from_admission(
        db=db,
        profile=profile,
        changed_by_user_id=None,
        reason="Applicant confirmed via magic link",
    )

    await db.flush()

    log.info(
        "Admission confirmed via magic link",
        profile_id=profile.id,
        token_id=token_obj.id,
        confirmed_at=now.isoformat(),
    )

    # Post-commit callback: email applicant "confirmed successfully + next steps".
    # Internal admin/officer fanout is handled separately by the router-level
    # APPLICATION_STATUS_CHANGED dispatch — no duplication.
    async def _notification_callback():
        from ..tasks.email_tasks import send_admission_confirmed_notification_task

        if not profile.lead or not profile.lead.email:
            log.info(
                "POST-COMMIT: skip confirmation success email (no lead/email)",
                profile_id=profile.id,
                lead_id=profile.lead_id,
            )
            return

        try:
            send_admission_confirmed_notification_task.delay(
                email_to=profile.lead.email,
                lead_name=profile.lead.full_name or "Học viên",
                confirmed_at_iso=profile.confirmed_at.isoformat(),
                lang="vi",
            )
            log.info(
                "POST-COMMIT: queued confirmation success email",
                profile_id=profile.id,
                lead_id=profile.lead_id,
            )
        except Exception as e:
            # Non-fatal: status đã commit thành 'confirmed', HTTP phải thành công.
            log.error(
                "POST-COMMIT: failed to enqueue confirmation success email",
                profile_id=profile.id,
                lead_id=profile.lead_id,
                error=str(e),
                exc_info=True,
            )

    final_callback = compose_post_commit_callbacks(
        label="admission_confirm_magic_link",
        callbacks=[_notification_callback, transition_callback],
    )

    return profile, final_callback


# ==============================================================================
# BULK ACTION FUNCTIONS
# ==============================================================================

async def bulk_approve(
    db: AsyncSession,
    items: List[Dict[str, Any]],
    approver: models.User,
    notes: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Callable]]:
    """
    Bulk approve multiple admission profiles.

    Uses the same business guards as single approve_profile:
    - State machine validation
    - Optimistic locking (version check per item)
    - Application fee gate
    - Milestone consultation + lead sync
    - Audit trail

    Each item that fails is skipped individually; does NOT rollback the batch.

    Path C / Arch-3: per-profile paired notification bundle
    (``admission_bulk_approve``) + commission callback are composed into a
    single mega-callback. Router awaits the mega-callback after commit.

    Args:
        db: Database session
        items: List of dicts with profile_id and version
        approver: User performing the approval
        notes: Optional approval notes

    Returns:
        Tuple of ``(result_dict, post_commit_callback)``. ``result_dict``
        keys: ``success_count, failed_count, failed_ids, errors, message``.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from .admission_state_machine import validate_transition
    from .lead_admission_sync import sync_lead_from_admission
    from ..services import audit_service

    if approver.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can approve profiles")

    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}
    per_profile_callbacks: List[Optional[Callable]] = []
    bundle_persist_results: List[str] = []

    for item in items:
        profile_id = item["profile_id"]
        expected_version = item["version"]
        try:
            # Pessimistic lock + eager load lead
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            result = await db.execute(stmt)
            profile = result.scalar_one_or_none()

            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # IDOR check
            _check_idor_access(profile, approver)

            # State machine validation
            try:
                validate_transition(profile.status, "approved")
            except ValueError as e:
                failed_ids.append(profile_id)
                errors[profile_id] = str(e)
                continue

            # Optimistic locking
            if expected_version != profile.version:
                failed_ids.append(profile_id)
                errors[profile_id] = (
                    f"Version mismatch: expected {expected_version}, "
                    f"actual {profile.version}. Refresh and retry."
                )
                continue

            # Application fee gate
            applied_rules = profile.applied_rules or {}
            requires_fee = applied_rules.get("requires_application_fee", False)
            fee_status = applied_rules.get("fee_status", "exempt")
            if requires_fee and fee_status == "pending":
                failed_ids.append(profile_id)
                errors[profile_id] = "Lệ phí xét tuyển chưa được thanh toán"
                continue

            # Fast-track nợ giấy tờ (C1.5) — same approve gate as single
            # approve_profile: a profile with an unresolved document debt may
            # NOT be (bulk-)approved. Per-item skip (not a batch abort) to match
            # the other bulk gates. No-op for profiles without a debt snapshot.
            _bulk_outstanding = await _outstanding_debt_for_approval(db, profile)
            if _bulk_outstanding:
                failed_ids.append(profile_id)
                errors[profile_id] = (
                    "Hồ sơ còn nợ giấy tờ chưa bổ sung/xác minh đủ, "
                    "không thể duyệt."
                )
                continue

            # ADM-026: per-item quota gate. Per-item bypass fields let admin
            # selectively override the cap for some profiles in the batch
            # while letting others fail-fast. Errors map to per-item
            # ``errors[profile_id]`` so the batch keeps moving (matches
            # existing bulk error shape used for state/version/fee gates).
            try:
                await _assert_quota_or_bypass(
                    db,
                    profile,
                    approver,
                    bypass_quota=bool(item.get("bypass_quota", False)),
                    bypass_reason=item.get("bypass_reason"),
                    transition="bulk_approve",
                    source="bulk_api",
                )
            except (BusinessRuleViolation, PermissionDeniedError, ValidationError) as quota_err:
                failed_ids.append(profile_id)
                errors[profile_id] = str(quota_err)
                continue

            # STATE CHANGE — caller still captures old_status for the
            # legacy bundle + commission callback below.
            now = datetime.now(timezone.utc)
            _old_status = profile.status

            profile, transition_callback = await state_transition(
                db,
                profile,
                "approved",
                actor=approver,
                reason=notes,
                source="bulk_api",
                extra_fields={
                    "approved_at": now,
                    "approved_by_id": approver.id,
                    "approval_notes": notes,
                },
            )

            # Milestone consultation
            if profile.lead:
                await _create_admission_milestone_consultation(
                    db=db,
                    lead=profile.lead,
                    event="profile_approved",
                    actor=approver,
                    profile_id=profile.id,
                )

            # Lead sync
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=approver.id,
                reason="Admission profile approved (bulk)",
            )

            # Per-profile bundle + commission (Path C / Arch-3)
            bundle_callback = None
            if profile.lead_id:
                intents = [
                    NotificationIntent(
                        event=SystemEvents.APPLICATION_STATUS_CHANGED,
                        payload={
                            "application_id": profile.id,
                            "lead_id": profile.lead_id,
                            "old_status": _old_status,
                            "new_status": "approved",
                            "actor_id": approver.id,
                            "actor_name": approver.full_name or approver.username,
                        },
                        dedupe_key=f"admission_profile_approved:{profile.id}",
                        rooms=rooms_for_admission(profile),
                    ),
                    NotificationIntent(
                        event=SystemEvents.LEAD_STATUS_CHANGED,
                        payload={
                            "lead_id": profile.lead_id,
                            "lead_name": f"Profile #{profile.id}",
                            "old_status": _old_status,
                            "new_status": "sts09",
                            "actor_id": approver.id,
                            "actor_name": approver.full_name or approver.username,
                        },
                        dedupe_key=f"lead_status_changed:{profile.lead_id}:sts09",
                        rooms=rooms_for_admission(profile),
                    ),
                ]
                bundle = await dispatch_bundle(
                    db, bundle_label="admission_bulk_approve", intents=intents,
                )
                bundle_callback = bundle.callback
                bundle_persist_results.append(bundle.persist_status)

            commission_callback = None
            if profile.lead_id:
                # Bind eagerly via default args to avoid late-binding gotcha
                # (closure over loop variables captures the LAST iteration).
                async def _commission_callback(
                    p_id=profile.lead_id,
                    old=_old_status,
                    actor_id=approver.id,
                ):
                    await safe_check_commission_on_status_change(
                        db, p_id, old, "sts09", actor_id,
                    )

                commission_callback = _commission_callback

            per_profile_cb = compose_post_commit_callbacks(
                label=f"admission_bulk_approve:{profile.id}",
                callbacks=[bundle_callback, commission_callback, transition_callback],
            )
            per_profile_callbacks.append(per_profile_cb)

            success_count += 1

        except ResourceNotFoundError:
            failed_ids.append(profile_id)
            errors[profile_id] = "Profile not found"
        except Exception as e:
            failed_ids.append(profile_id)
            errors[profile_id] = _safe_bulk_error_message(
                e,
                bulk_label="admission_bulk_approve",
                profile_id=profile_id,
                actor_id=approver.id,
            )

    await db.flush()

    log.info(
        "notification_bulk_bundle_summary",
        extra={
            "event": "notification_bulk_bundle_summary",
            "bulk_label": "admission_bulk_approve",
            "profile_count": len(items),
            "bundle_ok_count": bundle_persist_results.count("ok"),
            "bundle_rolled_back_count": bundle_persist_results.count("rolled_back"),
        },
    )

    mega_callback = compose_post_commit_callbacks(
        label="admission_bulk_approve",
        callbacks=per_profile_callbacks,
    )

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Approved {success_count} of {len(items)} profiles",
    }, mega_callback


async def bulk_reject(
    db: AsyncSession,
    items: List[Dict[str, Any]],
    rejector: models.User,
    reason: str,
) -> Tuple[Dict[str, Any], Optional[Callable]]:
    """
    Bulk reject multiple admission profiles.

    Uses the same business guards as single reject_profile:
    - State machine validation
    - Optimistic locking (version check per item)
    - Milestone consultation + lead sync
    - Audit trail

    Each item that fails is skipped individually; does NOT rollback the batch.

    Path C / Arch-3: per-profile paired notification bundle
    (``admission_bulk_reject``) + commission callback are composed into a
    single mega-callback. Router awaits the mega-callback after commit.

    Args:
        db: Database session
        items: List of dicts with profile_id and version
        rejector: User performing the rejection
        reason: Rejection reason (required)

    Returns:
        Tuple of ``(result_dict, post_commit_callback)``. ``result_dict``
        keys: ``success_count, failed_count, failed_ids, errors, message``.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from .admission_state_machine import validate_transition
    from .lead_admission_sync import sync_lead_from_admission
    from ..services import audit_service

    if rejector.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can reject profiles")

    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}
    per_profile_callbacks: List[Optional[Callable]] = []
    bundle_persist_results: List[str] = []

    for item in items:
        profile_id = item["profile_id"]
        expected_version = item["version"]
        try:
            # Pessimistic lock + eager load lead
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            result = await db.execute(stmt)
            profile = result.scalar_one_or_none()

            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # IDOR check
            _check_idor_access(profile, rejector)

            # State machine validation
            try:
                validate_transition(profile.status, "rejected")
            except ValueError as e:
                failed_ids.append(profile_id)
                errors[profile_id] = str(e)
                continue

            # Optimistic locking
            if expected_version != profile.version:
                failed_ids.append(profile_id)
                errors[profile_id] = (
                    f"Version mismatch: expected {expected_version}, "
                    f"actual {profile.version}. Refresh and retry."
                )
                continue

            # STATE CHANGE — caller still captures old_status for the
            # legacy bundle + commission callback below.
            now = datetime.now(timezone.utc)
            _old_status = profile.status

            profile, transition_callback = await state_transition(
                db,
                profile,
                "rejected",
                actor=rejector,
                reason=reason,
                source="bulk_api",
                extra_fields={
                    "rejected_at": now,
                    "rejected_by_id": rejector.id,
                    "rejection_reason": reason,
                },
            )

            # Milestone consultation
            if profile.lead:
                await _create_admission_milestone_consultation(
                    db=db,
                    lead=profile.lead,
                    event="profile_rejected",
                    actor=rejector,
                    profile_id=profile.id,
                    reason=reason,
                )

            # Lead sync
            await sync_lead_from_admission(
                db=db,
                profile=profile,
                changed_by_user_id=rejector.id,
                reason=f"Admission profile rejected (bulk): {reason[:50]}",
            )

            # Per-profile bundle + commission (Path C / Arch-3)
            bundle_callback = None
            if profile.lead_id:
                intents = [
                    NotificationIntent(
                        event=SystemEvents.APPLICATION_STATUS_CHANGED,
                        payload={
                            "application_id": profile.id,
                            "lead_id": profile.lead_id,
                            "old_status": _old_status,
                            "new_status": "rejected",
                            "actor_id": rejector.id,
                            "actor_name": rejector.full_name or rejector.username,
                        },
                        dedupe_key=f"admission_profile_rejected:{profile.id}",
                        rooms=rooms_for_admission(profile),
                    ),
                    NotificationIntent(
                        event=SystemEvents.LEAD_STATUS_CHANGED,
                        payload={
                            "lead_id": profile.lead_id,
                            "lead_name": f"Profile #{profile.id}",
                            "old_status": _old_status,
                            "new_status": "sts16",
                            "actor_id": rejector.id,
                            "actor_name": rejector.full_name or rejector.username,
                        },
                        dedupe_key=f"lead_status_changed:{profile.lead_id}:sts16",
                        rooms=rooms_for_admission(profile),
                    ),
                ]
                bundle = await dispatch_bundle(
                    db, bundle_label="admission_bulk_reject", intents=intents,
                )
                bundle_callback = bundle.callback
                bundle_persist_results.append(bundle.persist_status)

            commission_callback = None
            if profile.lead_id:
                async def _commission_callback(
                    p_id=profile.lead_id,
                    old=_old_status,
                    actor_id=rejector.id,
                ):
                    await safe_check_commission_on_status_change(
                        db, p_id, old, "sts16", actor_id,
                    )

                commission_callback = _commission_callback

            per_profile_cb = compose_post_commit_callbacks(
                label=f"admission_bulk_reject:{profile.id}",
                callbacks=[bundle_callback, commission_callback, transition_callback],
            )
            per_profile_callbacks.append(per_profile_cb)

            success_count += 1

        except ResourceNotFoundError:
            failed_ids.append(profile_id)
            errors[profile_id] = "Profile not found"
        except Exception as e:
            failed_ids.append(profile_id)
            errors[profile_id] = _safe_bulk_error_message(
                e,
                bulk_label="admission_bulk_reject",
                profile_id=profile_id,
                actor_id=rejector.id,
            )

    await db.flush()

    log.info(
        "notification_bulk_bundle_summary",
        extra={
            "event": "notification_bulk_bundle_summary",
            "bulk_label": "admission_bulk_reject",
            "profile_count": len(items),
            "bundle_ok_count": bundle_persist_results.count("ok"),
            "bundle_rolled_back_count": bundle_persist_results.count("rolled_back"),
        },
    )

    mega_callback = compose_post_commit_callbacks(
        label="admission_bulk_reject",
        callbacks=per_profile_callbacks,
    )

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Rejected {success_count} of {len(items)} profiles",
    }, mega_callback


async def bulk_assign(
    db: AsyncSession,
    profile_ids: List[int],
    officer_id: int,
    assigner: models.User,
) -> Dict[str, Any]:
    """
    Bulk assign profiles to an officer (updates lead.assigned_officer_id).

    Security:
    - Manager/Admin can assign within their unit
    - IDOR: Verifies each profile is accessible to user

    Args:
        db: Database session
        profile_ids: List of profile IDs to assign
        officer_id: ID of the officer to assign to
        assigner: User performing the assignment

    Returns:
        Dict with success_count, failed_count, failed_ids, errors, message
    """
    if assigner.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError("Only Managers or Admins can assign profiles")

    # Verify officer exists
    officer = await db.get(models.User, officer_id)
    if not officer:
        raise ResourceNotFoundError("Officer not found")

    # Target must actually be an active officer. lead_service enforces the
    # same rule on direct/auto assignment; bulk assign used to accept any
    # in-unit user and would silently set lead.assigned_officer_id to a
    # manager/admin/inactive account — leaving workload metrics and
    # downstream officer-scoped queries in a confused state.
    if officer.role != UserRole.OFFICER:
        raise BadRequest("Target user is not an officer")
    if getattr(officer, "status", None) != "active":
        raise BadRequest("Target officer is not active")

    # M4: Validate officer unit matches assigner unit (Admin bypass)
    if assigner.role != UserRole.ADMIN:
        if officer.unit_id != assigner.unit_id:
            raise BadRequest("Cannot assign to officer from different unit")

    success_count = 0
    failed_ids = []
    errors: Dict[int, str] = {}

    # ADM-011: lock the **lead** row (the row we actually write to —
    # ``lead.assigned_officer_id``) so two concurrent admission
    # ``bulk_assign`` calls on the same profile serialise. Sister
    # service ``bulk_approve`` (line ~7826) already runs under
    # ``with_for_update()`` on the profile; ``bulk_assign`` was
    # missed when written. Pre-fix, the racing bulk_assign's commit
    # would overwrite without error / log warn and the audit chain
    # would record ``old=NULL`` (stale read). See memory
    # ``project_adm_011_030_audit``.
    #
    # **SCOPE**: this fix protects bulk_assign vs bulk_assign. Other
    # lead-assignment paths (e.g.
    # ``lead_service.assign_lead_manually``) currently read via
    # plain ``get_lead_by_id`` without a row lock — they could still
    # race against a concurrent bulk_assign at the read-old-state
    # phase. Tightening those callers to take ``Lead FOR UPDATE``
    # before the read is tracked separately as a follow-up; it does
    # NOT happen here.
    #
    # **Sort ascending** before the loop so every concurrent
    # bulk_assign caller takes locks in the same global order —
    # eliminates the AB-BA deadlock cycle two managers bulk-assigning
    # the same set in different orders would otherwise create.
    #
    # **``with_for_update(of=models.Lead)``** scopes the lock to the
    # lead table only. Without ``of=...``, Postgres locks every table
    # touched by the JOIN (i.e. would also lock
    # ``admission_profile`` rows) — needlessly broad and would
    # interfere with concurrent doc/status/score mutations on the
    # same profile that don't conflict with assignment.
    for profile_id in sorted(profile_ids):
        try:
            # Step 1: lock the lead row (the row we actually write
            # to). ``populate_existing=True`` forces SQLAlchemy to
            # overwrite any cached identity-map state with fresh DB
            # data — necessary because under concurrent contention
            # the lock may release with the row at a newer committed
            # version than what the session's snapshot had cached.
            stmt = (
                select(models.Lead)
                .join(
                    models.AdmissionProfile,
                    models.Lead.id == models.AdmissionProfile.lead_id,
                )
                .where(models.AdmissionProfile.id == profile_id)
                .with_for_update(of=models.Lead)
                .execution_options(populate_existing=True)
            )
            lead_locked = (await db.execute(stmt)).scalar_one_or_none()
            if not lead_locked:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # Step 2: load profile (no lock — assignment doesn't write
            # to profile fields). ``populate_existing`` ensures any
            # cached profile object also gets refreshed.
            profile_stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .execution_options(populate_existing=True)
            )
            profile = (await db.execute(profile_stmt)).scalar_one_or_none()
            if not profile:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue
            # Pin the locked lead row onto the profile so the audit
            # log + IDOR check below read the freshly-locked state,
            # not whatever SQLAlchemy lazily-loaded earlier.
            profile.lead = lead_locked

            # IDOR check for non-admin (return "not found" to prevent enumeration)
            if assigner.role != UserRole.ADMIN and profile.lead.unit_id != assigner.unit_id:
                failed_ids.append(profile_id)
                errors[profile_id] = "Profile not found"
                continue

            # Update lead assignment + bump ``lead.version``. The
            # version bump is the optimistic-lock signal a UI client
            # uses to detect "someone else updated this lead" — every
            # other lead writer in the codebase bumps it (see
            # ``lead_service.py`` patterns), and skipping it here
            # would let a stale-snapshot client overwrite our
            # assignment without the version-mismatch guard kicking in.
            #
            # ``profile.version`` is **not** bumped — assignment writes
            # to the lead row, not the profile row. Profile version
            # semver tracks profile-level mutations (status / scores /
            # applied_rules); bumping it on assignment would force
            # unrelated optimistic-lock UI callers
            # (approve/update/etc.) to re-fetch, which is
            # over-aggressive cache invalidation.
            _old_officer_id = profile.lead.assigned_officer_id
            profile.lead.assigned_officer_id = officer_id
            profile.lead.version = (profile.lead.version or 1) + 1
            success_count += 1

            # Audit trail
            from ..services import audit_service
            await audit_service.log_changes(
                db, "Lead", profile.lead.id, "assigned",
                changes={"assigned_officer_id": {"old": _old_officer_id, "new": officer_id}},
                actor_user_id=assigner.id,
                source="bulk_api",
            )

        except Exception as e:
            failed_ids.append(profile_id)
            errors[profile_id] = _safe_bulk_error_message(
                e,
                bulk_label="admission_bulk_assign",
                profile_id=profile_id,
                actor_id=assigner.id,
            )

    await db.flush()

    return {
        "success_count": success_count,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids,
        "errors": errors if errors else None,
        "message": f"Assigned {success_count} of {len(profile_ids)} profiles to officer",
    }
