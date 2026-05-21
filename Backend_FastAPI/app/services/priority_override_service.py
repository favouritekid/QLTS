# app/services/priority_override_service.py
"""Q9 #07 Phase E.2 + E.3 — Priority bonus officer/admin write-path.

Service-layer functions cho manual KV override (Phase E.2) + UT evidence
verify/reject (Phase E.3 — chưa ship Wave 2). Architectural rules
(per CLAUDE.md PART 7):

* No FastAPI imports — raise DomainExceptions, return (result, post_commit_cb)
* Router commits; service flushes only
* Dispatch via safe_dispatch inside post_commit closure (NOT in service body)
* Version guard FIRST (memory `version-guard-before-state-machine`)
* Status whitelist enforced before mutation
* Audit log INSERT row PER mutation (priority_audit_log table)

Snapshot mutation (override_kv):

  profile.priority_resolution_snapshot JSONB ← deep-merge {
      kv_resolved: new_value,
      pathway: 'manual',
      rule_applied: 'manual_override',
      manual_override_by: actor.id,
      manual_override_at: now ISO,
      manual_override_reason: reason,
      evidence_file_id: optional,
      frozen_at: now ISO (refresh on override),
      frozen_at_status: 'manual_override',
      resolved_by: actor.role  # 'officer' | 'admin'
  }
  profile.area_resolution_basis ← 'manual_override'
  profile.version += 1

Audit row (priority_audit_log):

  action_type='kv_manual_override'
  profile_id=profile.id
  actor_id=actor.id
  old_value={'kv_resolved': prev_kv, 'rule_applied': prev_rule}
  new_value={'kv_resolved': new_kv, 'rule_applied': 'manual_override',
             'reason': reason, 'evidence_file_id': evidence_file_id}
  metadata={'pathway_before': prev_pathway}

Chain-of-override semantics (Decision D1, plan v3):

* Snapshot OVERWRITES with LAST override (manual_override_* keys reflect
  the most recent actor + reason).
* Audit log PRESERVES full history — query timeline via composite index
  (profile_id, action_type, created_at DESC) for chain of N overrides.
* UI BEFORE→AFTER preview reads snapshot.kv_resolved AS current; audit
  log endpoint (Wave 5) surfaces full chain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.admission_service import _strip_display_fields_from_evidence
from app.utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


KvCode = Literal["KV1", "KV2-NT", "KV2", "KV3"]

# Officer can override only in these intermediate states. Admin bypasses
# whitelist but pays a confirmation tax for post-publish profiles
# (`acknowledge_post_publish=True` required for enrolled/approved/confirmed).
_OFFICER_ALLOWED_STATUS: frozenset[str] = frozenset({
    "submitted",
    "reviewing",
    "revision_requested",
})

# Officer NEVER overrides in these terminal-ish states. Admin can with
# `acknowledge_post_publish=True`.
_POST_PUBLISH_STATUS: frozenset[str] = frozenset({
    "approved",
    "confirmed",
    "enrolled",
    "overridden",
    "result_published",
    "admitted",
    "waitlisted",
})

# Phase E.4 commit 5 fix-up — KV override hard-deny matrix:
# Pre-fix: ``draft`` đứng cùng withdrawn/dropped/rejected → block toàn bộ
# override. Hậu quả: submit guard fail-closed (yêu cầu nghiệp vụ #7) raise
# KV_UNRESOLVED + message "yêu cầu quản lý ấn định KV thủ công trước khi
# nộp" → manager/admin KHÔNG có đường để fulfill yêu cầu đó vì profile
# vẫn draft. Deadlock.
#
# Fix: tách ``draft`` khỏi hard-deny generic. Override trên draft được
# allow CHỈ cho admin/manager + CHỈ khi engine đã emit signal unresolved
# (snapshot.requires_manual_override=True). Officer giữ refused toàn diện
# cho draft (kể cả engine signal) — hardening đầy đủ ở commit 7 (Casbin
# + service guard).
_HARD_DENIED_STATUS: frozenset[str] = frozenset({
    "withdrawn",
    "dropped",
    "rejected",
})

_MIN_REASON_LEN = 20
_MAX_REASON_LEN = 500

# UT evidence states & reject reason validation (Phase E.3)
_EVIDENCE_STATUSES: frozenset[str] = frozenset({"pending", "verified", "rejected"})
_MIN_REJECT_REASON_LEN = 10
_MAX_REJECT_REASON_LEN = 500

# Phase E.4 (smoke 2026-05-21) — UT verify/reject state guard.
#
# Original guard used a 3-state blocklist (draft / withdrawn / dropped),
# which permitted verify/reject in approved / confirmed / enrolled /
# result_published / admitted / waitlisted. Service recomputes
# ``ut_verified_bucket`` + bumps version on every mutation, so a verify
# late in the lifecycle silently shifts published UT bucket points after
# results were already committed (parity with the documents-policy
# concern blocking reviewer mutation post-enrolled at
# ``admission_document_policy.py``).
#
# Pattern mirrors ``_OFFICER_ALLOWED_STATUS`` + ``_POST_PUBLISH_STATUS``
# used by manual KV override above — same workflow shape (officer/admin
# write-path, version-bump, audit log), so same gate.

# Officer/manager/admin can verify/reject UT evidence in these
# intermediate review states. Includes ``resubmitted`` because re-
# submission flow legitimately reopens UT review.
_EVIDENCE_OFFICER_ALLOWED_STATUS: frozenset[str] = frozenset({
    "submitted",
    "reviewing",
    "revision_requested",
    "resubmitted",
})

# Officer NEVER mutates UT evidence in these terminal/published states
# because UT bucket is now part of a committed admission decision /
# student record. Admin can bypass with explicit
# ``acknowledge_post_publish=True`` (parity with KV override gate).
_EVIDENCE_POST_PUBLISH_STATUS: frozenset[str] = frozenset({
    "approved",
    "confirmed",
    "enrolled",
    "overridden",
    "result_published",
    "admitted",
    "waitlisted",
})

# Officer + admin BOTH refuse to verify/reject in these — there is no
# coherent meaning (draft = candidate still editing, withdrawn/dropped/
# rejected = no UT decision to record).
_EVIDENCE_HARD_DENIED_STATUS: frozenset[str] = frozenset({
    "draft",
    "withdrawn",
    "dropped",
    "rejected",
})

# Legacy alias retained — referenced by external callers; matches the
# original 3-state denial set.
_EVIDENCE_DENIED_STATUS: frozenset[str] = frozenset({
    "draft",
    "withdrawn",
    "dropped",
})


# ---------------------------------------------------------------------------
# Public service entrypoint
# ---------------------------------------------------------------------------


async def override_kv(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    kv_resolved: KvCode,
    reason: str,
    evidence_file_id: Optional[int],
    actor: models.User,
    expected_version: int,
    acknowledge_post_publish: bool = False,
) -> Tuple[models.AdmissionProfile, Callable[[], Awaitable[None]]]:
    """Manual KV override by officer or admin.

    Args:
        db: Async session — caller (router) commits.
        profile: AdmissionProfile (already IDOR-scoped via
            ``get_admission_for_user``).
        kv_resolved: New KV code one of ``{'KV1','KV2-NT','KV2','KV3'}``.
        reason: 20-500 char free-text justification (mandatory; persisted
            in snapshot + audit log).
        evidence_file_id: Optional FK to uploaded document supporting the
            override (no FK constraint in schema — soft reference).
        actor: ``User`` performing override. Role drives status whitelist
            enforcement (officer vs admin).
        expected_version: Client-supplied optimistic-lock token.
            Service raises ``ConflictError`` (router → 409) on mismatch.
        acknowledge_post_publish: Admin-only escape hatch for overriding
            post-publish profiles (enrolled/approved/confirmed/...).
            Officer always refused for these states.

    Returns:
        Tuple ``(updated_profile, post_commit_cb)``. Router MUST await
        ``post_commit_cb()`` AFTER ``db.commit()``.

    Raises:
        ConflictError (409): version mismatch.
        BusinessRuleViolation (400): hard-denied state (draft/withdrawn/...),
            invalid reason length, invalid kv_resolved value.
        PermissionError → router → 403: officer attempts post-publish
            override without admin role.
    """
    # ---- Step 1: Version guard FIRST (per memory `version-guard-before-state-machine`)
    if expected_version != profile.version:
        log.warning(
            "priority_override_service.version_conflict",
            profile_id=profile.id,
            expected_version=expected_version,
            current_version=profile.version,
            actor_id=actor.id,
        )
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, "
            f"but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # ---- Step 2: Validate inputs
    if kv_resolved not in ("KV1", "KV2-NT", "KV2", "KV3"):
        raise BusinessRuleViolation(
            f"Invalid kv_resolved '{kv_resolved}' — must be one of "
            "KV1, KV2-NT, KV2, KV3"
        )

    reason_clean = (reason or "").strip()
    if len(reason_clean) < _MIN_REASON_LEN:
        raise BusinessRuleViolation(
            f"Override reason must be at least {_MIN_REASON_LEN} characters "
            f"(got {len(reason_clean)})"
        )
    if len(reason_clean) > _MAX_REASON_LEN:
        raise BusinessRuleViolation(
            f"Override reason must not exceed {_MAX_REASON_LEN} characters "
            f"(got {len(reason_clean)})"
        )

    # ---- Step 3: Role-level deny — Phase E.4 commit 7 hardening
    # Yêu cầu nghiệp vụ #10 (chốt 2026-05-21): officer KHÔNG được override KV.
    # Manager/admin pre-publish allowed với reason + audit; admin-only cho
    # post-publish với acknowledge flag. Pre-commit 7: officer được override
    # cho submitted/reviewing/revision_requested → cần block toàn diện.
    # Service-level deny là defense-in-depth: Casbin migration q9_07_e4f cũng
    # remove role:officer policy row; UI permissions flag cũng đổi sang chỉ
    # admin/manager. Officer reach đây = bug router/permissions → raise.
    is_admin = actor.role == "admin"
    is_manager = actor.role == "manager"
    is_officer_path = actor.role == "manager"  # only manager treated as officer path
    if actor.role == "officer":
        log.warning(
            "officer_override_kv_attempt_denied",
            profile_id=profile.id,
            actor_id=actor.id,
            profile_status=profile.status,
        )
        raise BusinessRuleViolation(
            "Officer không được override KV. Chỉ manager hoặc admin được "
            "phép ấn định KV thủ công với lý do + audit. Vui lòng đề nghị "
            "quản lý xử lý hồ sơ này."
        )

    if profile.status in _HARD_DENIED_STATUS:
        raise BusinessRuleViolation(
            f"Cannot override KV in '{profile.status}' state — profile "
            "is in withdrawn/dropped/rejected and not eligible for "
            "manual KV intervention."
        )

    # Phase E.4 commit 5 fix-up — draft gate riêng (gỡ deadlock với submit
    # guard fail-closed). Cho admin/manager override draft CHỈ khi engine
    # đã emit signal unresolved; officer giữ refused draft (hardening đầy
    # đủ ở commit 7).
    if profile.status == "draft":
        if not (is_admin or is_manager):
            # Officer đã được block ở top (commit 7). Branch này còn cover các
            # role khác như accountant/user nếu Casbin lọt qua.
            raise BusinessRuleViolation(
                "Chỉ admin hoặc manager được phép override KV ở trạng thái "
                "draft. Vui lòng đề nghị quản lý xử lý hồ sơ này."
            )

        # Phase E.4 reviewer v5 2026-05-21 — RECOMPUTE LIVE thay vì trust snapshot
        # stale. Pre-fix: kiểm tra ``snapshot.requires_manual_override`` từ DB.
        # Edge case: officer sửa permanent_commune_code/cultural/history sau
        # khi submit fail → snapshot vẫn cũ → manager override draft pass dù
        # engine giờ resolve được. → sai nghiệp vụ (free-form override khi
        # engine có đường tự xử).
        # Fix: re-run resolve_kv_for_profile() với profile state hiện tại;
        # CHỈ allow override draft khi engine vẫn emit unresolved signal.
        # Lazy import (priority_service ↔ models circular dep at top-level).
        from .priority_service import (
            derive_profile_target_context,
            resolve_kv_for_profile,
        )

        live_target_ctx = await derive_profile_target_context(profile, db)
        _live_kv, live_meta = await resolve_kv_for_profile(
            profile,
            db,
            target_level=live_target_ctx.get("target_level"),
            admission_type=live_target_ctx.get("admission_type"),
        )
        if not live_meta.get("requires_manual_override"):
            log.info(
                "draft_override_refused_engine_resolved_live",
                profile_id=profile.id,
                actor_id=actor.id,
                live_rule_applied=live_meta.get("rule_applied"),
                live_basis=live_meta.get("basis"),
                snapshot_rule_applied=(
                    profile.priority_resolution_snapshot or {}
                ).get("rule_applied"),
            )
            raise BusinessRuleViolation(
                "Hồ sơ draft chỉ được override KV khi engine không xác định "
                f"được với dữ liệu hiện tại. Engine vừa tính lại và resolve "
                f"thành công (rule={live_meta.get('rule_applied')}, "
                f"basis={live_meta.get('basis')}). Nếu muốn áp KV khác, "
                f"submit hồ sơ trước (state submitted/reviewing/revision_requested "
                f"cho phép override thường lệ)."
            )

    if profile.status in _POST_PUBLISH_STATUS:
        if not is_admin:
            # Officer/manager refused post-publish; signal via
            # PermissionError so router maps to 403.
            raise PermissionError(
                f"Officer cannot override KV on '{profile.status}' "
                "profile — admin only for post-publish overrides."
            )
        # Admin path requires explicit acknowledgement flag.
        if not acknowledge_post_publish:
            raise BusinessRuleViolation(
                f"Profile is in post-publish state '{profile.status}'. "
                "Pass acknowledge_post_publish=true to confirm the "
                "override; this will be recorded in the audit log."
            )

    if (
        not is_admin
        and is_officer_path
        and profile.status not in _OFFICER_ALLOWED_STATUS
        and profile.status not in _POST_PUBLISH_STATUS
        and profile.status != "draft"  # draft handled by dedicated gate above
    ):
        # Catch-all guard for unexpected statuses (vd new state machine
        # state not in either whitelist). Fail-closed for officer path.
        raise BusinessRuleViolation(
            f"Cannot override KV in '{profile.status}' state — officer "
            "allowed only for submitted/reviewing/revision_requested."
        )

    # ---- Step 4: Snapshot a deep copy of current state for audit log
    prev_snapshot: dict[str, Any] = dict(profile.priority_resolution_snapshot or {})
    prev_kv = prev_snapshot.get("kv_resolved")
    prev_rule = prev_snapshot.get("rule_applied")
    prev_pathway = prev_snapshot.get("pathway")

    # ---- Step 5: Build new snapshot — overwrite with manual override metadata
    now_iso = datetime.now(timezone.utc).isoformat()
    new_snapshot: dict[str, Any] = {
        **prev_snapshot,  # preserve fields not part of override (breakdown, etc.)
        "kv_resolved": kv_resolved,
        "pathway": "manual",
        "rule_applied": "manual_override",
        "manual_override_by": actor.id,
        "manual_override_at": now_iso,
        "manual_override_reason": reason_clean,
        "evidence_file_id": evidence_file_id,
        "frozen_at": now_iso,
        "frozen_at_status": "manual_override",
        "resolved_by": "admin" if is_admin else "officer",
    }
    # Drop ambiguous engine-state keys that no longer apply post-override
    new_snapshot.pop("requires_manual_override", None)
    new_snapshot.pop("reason", None)

    profile.priority_resolution_snapshot = new_snapshot
    profile.area_resolution_basis = "manual_override"

    # ---- Step 6: INSERT audit log row
    audit_row = models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="kv_manual_override",
        actor_id=actor.id,
        old_value={
            "kv_resolved": prev_kv,
            "rule_applied": prev_rule,
            "pathway": prev_pathway,
        },
        new_value={
            "kv_resolved": kv_resolved,
            "rule_applied": "manual_override",
            "pathway": "manual",
            "reason": reason_clean,
            "evidence_file_id": evidence_file_id,
        },
        audit_metadata={
            "actor_role": actor.role,
            "profile_status": profile.status,
            "acknowledged_post_publish": (
                bool(acknowledge_post_publish)
                if profile.status in _POST_PUBLISH_STATUS
                else None
            ),
        },
    )
    db.add(audit_row)

    # ---- Step 7: Bump optimistic-lock version
    profile.version += 1

    # ---- Step 8: Dispatch via outbox (catalog requires_outbox=True for
    # PRIORITY_KV_OVERRIDDEN). dispatch_event INSERTs notification_outbox
    # row inside caller's transaction; worker drains post-commit. Per
    # B2.3 wrapper contract: this is the right primitive for outbox events
    # — raw safe_dispatch() would trip the
    # `raw-dispatch-of-outbox-event` coverage script gate.
    from app.services.notification_dispatcher import dispatch_event

    _payload = {
        "application_id": profile.id,
        "lead_id": profile.lead_id,
        "actor_id": actor.id,
        "actor_name": actor.full_name or actor.email,
        "kv_resolved": kv_resolved,
        "override_reason": reason_clean,
    }
    _dedupe_key = (
        f"priority:{profile.id}:kv_overridden:{kv_resolved}:{actor.id}:"
        f"{int(datetime.now(timezone.utc).timestamp())}"
    )
    post_commit = await dispatch_event(
        db,
        event=SystemEvents.PRIORITY_KV_OVERRIDDEN,
        payload=_payload,
        dedupe_key=_dedupe_key,
    )

    await db.flush()

    log.info(
        "priority_override_service.override_kv_success",
        profile_id=profile.id,
        actor_id=actor.id,
        actor_role=actor.role,
        prev_kv=prev_kv,
        new_kv=kv_resolved,
        version_after=profile.version,
        reason_len=len(reason_clean),
        outbox_dispatched=True,
    )

    # dispatch_event returns None for outbox events (router commits, worker
    # processes async). Wrap None into noop callback for router uniformity.
    async def _noop_callback() -> None:
        return None

    if post_commit is None:
        post_commit = _noop_callback

    return profile, post_commit


# ---------------------------------------------------------------------------
# UT evidence — verify + reject (Phase E.3)
# ---------------------------------------------------------------------------


async def _recompute_ut_verified_bucket(
    db: AsyncSession,
    profile: models.AdmissionProfile,
) -> dict[str, Any]:
    """Recompute ``ut_verified_bucket`` snapshot field after verify/reject.

    Engine T6 actual rate freeze (Phase E wireframe ut_verified_bucket key):
    MAX bonus_points across codes với ``priority_object_evidence[code].status
    == 'verified'``. If no verified codes, returns ``{applied_code: None,
    applied_rate: 0}``.

    Catalog rate lookup honors ``effective_from``/``effective_to`` window —
    same query shape as ``admissions_v2.preview_priority_kv``.
    """
    from datetime import date as _date
    from sqlalchemy import select as _sel
    from app.models.priority_config import PriorityObjectConfig

    evidence = profile.priority_object_evidence or {}
    submitted_codes = list(profile.priority_object_codes or [])
    verified_codes = [
        c
        for c in submitted_codes
        if isinstance(evidence.get(c), dict)
        and evidence[c].get("status") == "verified"
    ]

    if not verified_codes:
        return {"applied_code": None, "applied_rate": 0}

    # Academic year: fall back chain mirrors preview endpoint.
    academic_year = profile.academic_year or 2026
    today = _date.today()
    stmt = (
        _sel(PriorityObjectConfig.sub_code, PriorityObjectConfig.bonus_points)
        .where(
            PriorityObjectConfig.academic_year == academic_year,
            PriorityObjectConfig.sub_code.in_(verified_codes),
            PriorityObjectConfig.effective_from <= today,
        )
        .where(
            (PriorityObjectConfig.effective_to.is_(None))
            | (PriorityObjectConfig.effective_to > today)
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"applied_code": None, "applied_rate": 0}

    top = max(rows, key=lambda r: r[1])
    return {"applied_code": top[0], "applied_rate": float(top[1])}


async def _evidence_mutation_common_checks(
    profile: models.AdmissionProfile,
    sub_code: str,
    actor: models.User,
    expected_version: int,
    acknowledge_post_publish: bool = False,
) -> None:
    """Shared pre-mutation guard for verify + reject (Phase E.4 hotfix 3).

    Raises ConflictError on version mismatch (FIRST per memory
    `version-guard-before-state-machine`); BusinessRuleViolation on
    hard-denied status, post-publish without acknowledge, status outside
    the officer allowlist, invalid sub_code, or sub_code not in
    profile's submitted codes list. PermissionError when officer/manager
    attempts post-publish mutation (router maps to 403).

    State guard mirrors ``_OFFICER_ALLOWED_STATUS`` + ``_POST_PUBLISH_STATUS``
    used by ``override_kv`` above — UT bucket mutation has the same
    "snapshot-bumping post-decision" risk as a manual KV override.
    """
    if expected_version != profile.version:
        raise ConflictError(
            f"Profile was modified by another user. "
            f"Expected version {expected_version}, "
            f"but current version is {profile.version}. "
            "Please refresh and try again."
        )

    # Hard-denied: nobody can verify/reject here. Fail-closed.
    if profile.status in _EVIDENCE_HARD_DENIED_STATUS:
        raise BusinessRuleViolation(
            f"Cannot verify/reject UT evidence in '{profile.status}' state."
        )

    is_admin = getattr(actor, "role", None) == "admin"

    # Post-publish: officer/manager refused outright (403 at router).
    # Admin must opt in with explicit acknowledge_post_publish=True to
    # leave a clear audit trail entry.
    if profile.status in _EVIDENCE_POST_PUBLISH_STATUS:
        if not is_admin:
            raise PermissionError(
                f"Officer cannot verify/reject UT evidence on "
                f"'{profile.status}' profile — admin only for post-publish "
                "mutations."
            )
        if not acknowledge_post_publish:
            raise BusinessRuleViolation(
                f"Profile is in post-publish state '{profile.status}'. "
                "Pass acknowledge_post_publish=true to confirm the "
                "verify/reject; this will be recorded in the audit log."
            )

    # Catch-all: officer path must be in the allow list. Admin already
    # passed the post-publish gate above; here we only re-check officer.
    elif profile.status not in _EVIDENCE_OFFICER_ALLOWED_STATUS:
        raise BusinessRuleViolation(
            f"Cannot verify/reject UT evidence in '{profile.status}' state — "
            "allowed only for submitted/reviewing/revision_requested/resubmitted."
        )

    if not sub_code or not isinstance(sub_code, str):
        raise BusinessRuleViolation("sub_code is required and must be a string")

    submitted = list(profile.priority_object_codes or [])
    if sub_code not in submitted:
        raise BusinessRuleViolation(
            f"sub_code '{sub_code}' is not in profile's submitted codes "
            f"({submitted}); candidate must select diện first."
        )


async def verify_object_evidence(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    sub_code: str,
    document_id: Optional[int],
    actor: models.User,
    expected_version: int,
    acknowledge_post_publish: bool = False,
) -> Tuple[models.AdmissionProfile, Callable[[], Awaitable[None]]]:
    """Officer verifies UT evidence cho 1 sub_code (Phase E.3).

    Marks ``priority_object_evidence[sub_code]`` as ``status='verified'``
    with verifier metadata + optional ``document_id`` reference (per
    Decision D3 — candidate uploads via DocumentsTab, officer picks
    document từ existing profile.documents).

    Recomputes ``priority_resolution_snapshot.ut_verified_bucket`` (engine
    T6 actual rate freeze). Bumps version + INSERTs audit log + dispatches
    PRIORITY_OBJECT_VERIFIED event via outbox.

    Raises:
        ConflictError: version mismatch.
        BusinessRuleViolation: sub_code not submitted / hard-denied status /
            post-publish without acknowledge.
        PermissionError: officer/manager attempts post-publish mutation
            (router maps to 403).
    """
    await _evidence_mutation_common_checks(
        profile, sub_code, actor, expected_version,
        acknowledge_post_publish=acknowledge_post_publish,
    )

    # Phase E.4 PR-2 P1 fix (audit cycle 2026-05-20) — server-side document
    # binding. Spec: lookup ProfileDocument by (profile_id, category=
    # 'priority_evidence', priority_sub_code=sub_code) INSTEAD of trusting
    # client-supplied document_id blindly.
    #
    # Risk if KHÔNG fix: client gửi arbitrary document_id → audit ghi sai
    # paper_only_verification; cross-profile reference (vd document_id của
    # profile khác) → IDOR leak path metadata. FE currently hardcode
    # document_id=null sau upload → mọi verify rơi vào "Hồ sơ giấy" path
    # dù file đã scan vào hệ thống.
    #
    # 4 cases:
    # 1. Client null + no row → paper_only=True, doc_id=None (true paper-only)
    # 2. Client null + row exists → auto-bind doc_id=row.id, paper_only=False
    # 3. Client int + row.id match → bind doc_id=row.id, paper_only=False
    # 4. Client int + row.id mismatch (or no row) → BusinessRuleViolation
    from sqlalchemy import select as _sel
    doc_q = await db.execute(
        _sel(models.ProfileDocument).where(
            models.ProfileDocument.profile_id == profile.id,
            models.ProfileDocument.category == "priority_evidence",
            models.ProfileDocument.priority_sub_code == sub_code,
        )
    )
    doc_row = doc_q.scalar_one_or_none()

    if document_id is None:
        if doc_row is not None:
            # Case 2: auto-bind. FE chưa kịp re-fetch sau upload → server tự
            # link evidence với file đã upload. Tone neutral cho officer
            # workflow (không buộc client phải pass document_id explicit).
            actual_document_id = doc_row.id
            paper_only = False
        else:
            # Case 1: true paper-only — no file scanned yet. Officer verify
            # dựa hồ sơ giấy candidate đem đến. Decision #3 default case.
            actual_document_id = None
            paper_only = True
    else:
        if doc_row is None or doc_row.id != document_id:
            # Case 4: client lied or stale FE state. Refuse — server-side
            # truth wins.
            raise BusinessRuleViolation(
                f"document_id {document_id} không match priority evidence "
                f"row cho profile={profile.id} sub_code={sub_code} "
                f"(server row id={getattr(doc_row, 'id', None)}). Officer "
                f"phải verify đúng file đính kèm hoặc gửi null để verify "
                f"hồ sơ giấy."
            )
        # Case 3: client + server match. Bind explicit.
        actual_document_id = doc_row.id
        paper_only = False

    now_iso = datetime.now(timezone.utc).isoformat()
    evidence = dict(profile.priority_object_evidence or {})
    prev_entry = dict(evidence.get(sub_code) or {})

    evidence[sub_code] = {
        **prev_entry,
        "status": "verified",
        "verified_by": actor.id,
        "verified_at": now_iso,
        "document_id": actual_document_id,
        "paper_only_verification": paper_only,
        # Drop any stale reject_reason from prior reject cycle.
        "reject_reason": None,
    }
    # Phase E.4 G3 — strip display-only fields trước khi assign back vào
    # JSONB column. Defensive guard nếu prev_entry mang display fields leak
    # từ enriched projection.
    profile.priority_object_evidence = _strip_display_fields_from_evidence(evidence)

    # Recompute UT verified bucket (engine T6 actual rate)
    new_bucket = await _recompute_ut_verified_bucket(db, profile)
    snapshot = dict(profile.priority_resolution_snapshot or {})
    snapshot["ut_verified_bucket"] = new_bucket
    profile.priority_resolution_snapshot = snapshot

    audit_row = models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="ut_evidence_verified",
        actor_id=actor.id,
        old_value={"sub_code": sub_code, "status": prev_entry.get("status")},
        new_value={
            "sub_code": sub_code,
            "status": "verified",
            "document_id": actual_document_id,
            "paper_only_verification": paper_only,
        },
        audit_metadata={
            "actor_role": actor.role,
            "ut_verified_bucket": new_bucket,
            "paper_only_verification": paper_only,
        },
    )
    db.add(audit_row)
    profile.version += 1

    from app.services.notification_dispatcher import dispatch_event

    _payload = {
        "application_id": profile.id,
        "lead_id": profile.lead_id,
        "actor_id": actor.id,
        "actor_name": actor.full_name or actor.email,
        "sub_code": sub_code,
    }
    _dedupe_key = (
        f"priority:{profile.id}:ut_verified:{sub_code}:{actor.id}:"
        f"{int(datetime.now(timezone.utc).timestamp())}"
    )
    post_commit = await dispatch_event(
        db,
        event=SystemEvents.PRIORITY_OBJECT_VERIFIED,
        payload=_payload,
        dedupe_key=_dedupe_key,
    )

    await db.flush()

    log.info(
        "priority_override_service.verify_object_evidence_success",
        profile_id=profile.id,
        actor_id=actor.id,
        sub_code=sub_code,
        applied_code=new_bucket.get("applied_code"),
        applied_rate=new_bucket.get("applied_rate"),
        version_after=profile.version,
    )

    async def _noop_callback() -> None:
        return None

    return profile, (post_commit or _noop_callback)


async def reject_object_evidence(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    sub_code: str,
    reject_reason: str,
    actor: models.User,
    expected_version: int,
    acknowledge_post_publish: bool = False,
) -> Tuple[models.AdmissionProfile, Callable[[], Awaitable[None]]]:
    """Officer rejects UT evidence cho 1 sub_code (Phase E.3).

    Marks ``priority_object_evidence[sub_code]`` as ``status='rejected'``
    with ``reject_reason`` (min 10 / max 500 chars). Recomputes
    ``ut_verified_bucket`` — if the rejected code was the current applied
    verified code, the bucket recomputes to the next-highest verified
    code (or null if none remain).

    Per plan v3 Wave 3 spec line 245-247.

    Raises:
        ConflictError: version mismatch.
        BusinessRuleViolation: sub_code not submitted / reason length /
            hard-denied status / post-publish without acknowledge.
        PermissionError: officer/manager attempts post-publish mutation
            (router maps to 403).
    """
    await _evidence_mutation_common_checks(
        profile, sub_code, actor, expected_version,
        acknowledge_post_publish=acknowledge_post_publish,
    )

    reason_clean = (reject_reason or "").strip()
    if len(reason_clean) < _MIN_REJECT_REASON_LEN:
        raise BusinessRuleViolation(
            f"Reject reason must be at least {_MIN_REJECT_REASON_LEN} "
            f"characters (got {len(reason_clean)})"
        )
    if len(reason_clean) > _MAX_REJECT_REASON_LEN:
        raise BusinessRuleViolation(
            f"Reject reason must not exceed {_MAX_REJECT_REASON_LEN} "
            f"characters (got {len(reason_clean)})"
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    evidence = dict(profile.priority_object_evidence or {})
    prev_entry = dict(evidence.get(sub_code) or {})

    evidence[sub_code] = {
        **prev_entry,
        "status": "rejected",
        "verified_by": None,
        "verified_at": None,
        "reject_reason": reason_clean,
        "rejected_by": actor.id,
        "rejected_at": now_iso,
        # Phase E.4 — reject clears paper_only_verification (was relevant
        # only to verified status; rejection invalidates that flag).
        "paper_only_verification": False,
    }
    # Phase E.4 G3 — strip display-only fields trước khi assign back vào
    # JSONB column. Defensive guard nếu prev_entry mang display fields leak.
    profile.priority_object_evidence = _strip_display_fields_from_evidence(evidence)

    # Recompute UT verified bucket — if rejected code was applied verified,
    # bucket falls back to next-highest verified (or null if no verified left).
    new_bucket = await _recompute_ut_verified_bucket(db, profile)
    snapshot = dict(profile.priority_resolution_snapshot or {})
    snapshot["ut_verified_bucket"] = new_bucket
    profile.priority_resolution_snapshot = snapshot

    audit_row = models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="ut_evidence_rejected",
        actor_id=actor.id,
        old_value={"sub_code": sub_code, "status": prev_entry.get("status")},
        new_value={
            "sub_code": sub_code,
            "status": "rejected",
            "reject_reason": reason_clean,
        },
        audit_metadata={
            "actor_role": actor.role,
            "ut_verified_bucket": new_bucket,
        },
    )
    db.add(audit_row)
    profile.version += 1

    from app.services.notification_dispatcher import dispatch_event

    _payload = {
        "application_id": profile.id,
        "lead_id": profile.lead_id,
        "actor_id": actor.id,
        "actor_name": actor.full_name or actor.email,
        "sub_code": sub_code,
        "reject_reason": reason_clean,
    }
    _dedupe_key = (
        f"priority:{profile.id}:ut_rejected:{sub_code}:{actor.id}:"
        f"{int(datetime.now(timezone.utc).timestamp())}"
    )
    post_commit = await dispatch_event(
        db,
        event=SystemEvents.PRIORITY_OBJECT_REJECTED,
        payload=_payload,
        dedupe_key=_dedupe_key,
    )

    await db.flush()

    log.info(
        "priority_override_service.reject_object_evidence_success",
        profile_id=profile.id,
        actor_id=actor.id,
        sub_code=sub_code,
        applied_code_after=new_bucket.get("applied_code"),
        version_after=profile.version,
        reason_len=len(reason_clean),
    )

    async def _noop_callback() -> None:
        return None

    return profile, (post_commit or _noop_callback)


# =============================================================================
# Q9 #07 Phase E.4 — Untick UT cascade (G1 atomic, PR-2 Item #2)
# =============================================================================


async def untick_priority_evidence(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    sub_code: str,
    actor: models.User,
    expected_version: int,
    acknowledge_post_publish: bool = False,
) -> Tuple[models.AdmissionProfile, Callable[[bool], Awaitable[None]]]:
    """Untick UT code + cascade hard delete evidence file (Phase E.4 G1).

    Atomic 4-mutation contract (all within single DB transaction):
    1. JSONB update ``priority_object_codes`` — remove sub_code.
    2. JSONB update ``priority_object_evidence`` — remove sub_code entry.
       Uses ``_strip_display_fields_from_evidence`` defensive cleaner (G3).
    3. DELETE ``profile_document`` row (category='priority_evidence',
       priority_sub_code=sub_code) — if exists.
    4. INSERT ``priority_audit_log`` row (action_type='ut_evidence_untick').
    Plus: recompute ``ut_verified_bucket`` (bucket recompute matches reject
    semantics — if unticked code was applied verified, bucket falls back).

    S3 file cleanup is best-effort POST-commit via finalize callback (per
    ADM-007 staging/finalize pattern). Commit fail → finalize(False) skips
    delete → DB rollback restores doc row → S3 file still referenced.

    Args:
        db: AsyncSession.
        profile: Pre-loaded AdmissionProfile (caller resolves IDOR).
        sub_code: UT code to untick (must be in profile.priority_object_codes).
        actor: Officer/admin performing untick.
        expected_version: Optimistic-lock version (per memory
            `version-guard-before-state-machine` — runs FIRST).

    Returns:
        (profile, finalize(committed: bool) async callback). Caller MUST
        ``db.commit()`` then ``await finalize(True)`` to actually unlink S3
        file. On commit fail call ``await finalize(False)`` — best-effort
        cleanup with file still referenced (DB rollback safe).

    Raises:
        ConflictError: version mismatch.
        BusinessRuleViolation: sub_code not submitted / hard-denied status.

    Note: UI confirm dialog (Decision #4) is FE-side safety guard. Service
    layer assumes caller already confirmed — no double-prompt.
    """
    import os
    from sqlalchemy import select as _sel

    # Version + status + sub_code guards (reuse common helper)
    await _evidence_mutation_common_checks(
        profile, sub_code, actor, expected_version,
        acknowledge_post_publish=acknowledge_post_publish,
    )

    # Find ProfileDocument row to delete (if exists)
    doc_q = await db.execute(
        _sel(models.ProfileDocument).where(
            models.ProfileDocument.profile_id == profile.id,
            models.ProfileDocument.category == "priority_evidence",
            models.ProfileDocument.priority_sub_code == sub_code,
        )
    )
    doc_row = doc_q.scalar_one_or_none()
    file_path_to_unlink: Optional[str] = doc_row.file_path if doc_row else None

    # Capture old evidence entry for audit
    prev_evidence = profile.priority_object_evidence or {}
    prev_entry = dict(prev_evidence.get(sub_code) or {})
    had_document_id = prev_entry.get("document_id")

    # 1. Remove from priority_object_codes
    codes = list(profile.priority_object_codes or [])
    if sub_code in codes:
        codes.remove(sub_code)
    profile.priority_object_codes = codes

    # 2. Remove from priority_object_evidence — strip display fields trước assign
    evidence = dict(prev_evidence)
    evidence.pop(sub_code, None)
    profile.priority_object_evidence = _strip_display_fields_from_evidence(evidence)

    # 3. DELETE profile_document row (if exists)
    if doc_row is not None:
        await db.delete(doc_row)

    # Recompute UT verified bucket — if unticked was applied verified,
    # bucket recomputes to next-highest (mirror reject semantics).
    new_bucket = await _recompute_ut_verified_bucket(db, profile)
    snapshot = dict(profile.priority_resolution_snapshot or {})
    snapshot["ut_verified_bucket"] = new_bucket
    profile.priority_resolution_snapshot = snapshot

    # 4. INSERT priority_audit_log row
    audit_row = models.PriorityAuditLog(
        profile_id=profile.id,
        action_type="ut_evidence_untick",
        actor_id=actor.id,
        old_value={
            "sub_code": sub_code,
            "status": prev_entry.get("status"),
            "had_document": had_document_id is not None,
        },
        new_value={"sub_code": sub_code, "untick": True},
        audit_metadata={
            "actor_role": actor.role,
            "file_unlinked": file_path_to_unlink is not None,
            "ut_verified_bucket": new_bucket,
        },
    )
    db.add(audit_row)
    profile.version += 1

    await db.flush()

    log.info(
        "priority_override_service.untick_priority_evidence_success",
        profile_id=profile.id,
        actor_id=actor.id,
        sub_code=sub_code,
        had_document=had_document_id is not None,
        applied_code_after=new_bucket.get("applied_code"),
        version_after=profile.version,
    )

    async def finalize(committed: bool) -> None:
        """ADM-007 finalize callback — unlink S3 file post-commit.

        - committed=True: best-effort unlink file_path_to_unlink. File
          missing or unlink fail → log warning, không raise (the DB delete
          already settled; orphan file = storage waste, not correctness).
        - committed=False: skip. DB rollback restores doc_row → file still
          referenced → leave file alone.
        """
        if not committed:
            return
        if not file_path_to_unlink:
            return
        if os.path.exists(file_path_to_unlink):
            try:
                os.remove(file_path_to_unlink)
                log.info(
                    "Priority evidence file deleted post-commit (untick cascade)",
                    file_path=file_path_to_unlink,
                )
            except OSError as e:
                log.warning(
                    "Failed to unlink priority evidence file post-commit",
                    file_path=file_path_to_unlink,
                    error=str(e),
                )

    return profile, finalize
