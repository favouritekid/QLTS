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

# Officer + admin BOTH refuse to override these (data inconsistency risk).
_HARD_DENIED_STATUS: frozenset[str] = frozenset({
    "draft",
    "withdrawn",
    "dropped",
    "rejected",
})

_MIN_REASON_LEN = 20
_MAX_REASON_LEN = 500


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

    # ---- Step 3: Status whitelist (role-aware)
    is_admin = actor.role == "admin"
    is_officer_path = actor.role in ("officer", "manager")  # both treated as officer path

    if profile.status in _HARD_DENIED_STATUS:
        raise BusinessRuleViolation(
            f"Cannot override KV in '{profile.status}' state — profile "
            "is in draft/withdrawn/dropped/rejected and not eligible for "
            "manual KV intervention."
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
