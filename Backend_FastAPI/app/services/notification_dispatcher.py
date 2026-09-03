# app/services/notification_dispatcher.py
"""
✅ NOTIFICATION 2.0 - Central Event Bus with Multi-Channel Support

The dispatcher is the entry point for publishing events. It handles:
1. Database/Registry rule lookup
2. Condition evaluation (database rules only)
3. Recipient resolution
4. Preference filtering
5. Deduplication
6. Bulk notification creation
7. Database commit
8. ✅ NOTIFICATION 2.0: Multi-channel delivery via Channel Infrastructure

Transaction Safety:
- All database operations are committed BEFORE any notifications are sent
- Channels send notifications immediately after DB commit
- If DB commit fails, no notifications are sent (prevents ghost notifications)

Channel Delivery:
- Uses unified Channel Infrastructure (Strategy Pattern)
- Each channel (socket, email, zalo, sms) handles its own delivery
- Channels are independent - failure in one doesn't affect others
- Channel results logged for monitoring

Usage:
    from app.services.notification_dispatcher import dispatch

    notification_ids = await dispatch(
        db=db,
        event=SystemEvents.LEAD_ASSIGNED,
        payload={
            "lead_id": 123,
            "officer_id": 456,
            "actor_id": 789,
            "lead_name": "John Doe"
        }
    )
"""
import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group, NotificationChannel
from app.database import (
    safe_redis_lpush, safe_redis_ltrim, safe_redis_expire,
    safe_redis_exists, safe_redis_set, safe_redis_incr,
)
from app.core.event_catalog import get_event, render_dedup_key, render_link
from app.services import notification_preference_service
from app.repositories import NotificationRepository, NotificationTemplateRepository
# ✅ PR1: Single-path — catalog + DB rule only, no registry fallback
from app.services.notification_rule_loader import get_rule_for_event

log = structlog.get_logger(__name__)

# ✅ PHASE 1.2: Import cache config from notification_service
from app.services.notification_service import (
    INBOX_CACHE_KEY_PREFIX,
    INBOX_CACHE_MAX_SIZE,
    INBOX_CACHE_TTL,
)

# Chunk size for bulk insert (to avoid overwhelming the DB)
BULK_INSERT_CHUNK_SIZE = 100


# =============================================================================
# CHANNEL CONFIG PLACEHOLDER RENDERING (Phase C1/P1)
# =============================================================================

def _render_channel_config_placeholders(
    snapshot: dict,
    payload: dict,
) -> dict:
    """
    Render $placeholder values inside channel-specific config fields.

    Uses string.Template.safe_substitute — same pattern as render_title/render_message
    in DatabaseRuleConfig. Renders string values in any *_template_data dict.

    Placeholder syntax: $lead_name or ${lead_name} (standard string.Template).
    Unresolved placeholders are left as-is (safe_substitute).

    Example:
        config: {"zalo_template_data": {"customer": "$lead_name", "phone": "$lead_phone"}}
        payload: {"lead_name": "Nguyen Van A", "lead_phone": "0901234567"}
        → {"zalo_template_data": {"customer": "Nguyen Van A", "phone": "0901234567"}}
    """
    from string import Template

    result = dict(snapshot)

    # Render placeholders in any *_template_data dict
    for key in list(result.keys()):
        if key.endswith("_template_data") and isinstance(result[key], dict):
            rendered = {}
            for k, v in result[key].items():
                if isinstance(v, str) and "$" in v:
                    rendered[k] = Template(v).safe_substitute(payload)
                else:
                    rendered[k] = v
            result[key] = rendered

    return result


# =============================================================================
# PHASE E2: PER-ACTION TEMPLATE RESOLUTION
# =============================================================================

async def _resolve_action_templates(
    db: AsyncSession,
    action_configs: List[Any],
) -> Dict[str, "models.NotificationTemplate"]:
    """
    Pre-fetch NotificationTemplate objects for actions that have template_code.

    Returns a dict of {template_code: NotificationTemplate} for all distinct
    template_codes found in the action list.  Templates that don't exist in the
    database are silently skipped (a warning is logged).

    This is called once per dispatch so template lookup is O(distinct codes)
    rather than O(channels).
    """
    codes = {a.template_code for a in action_configs if a.template_code}
    if not codes:
        return {}

    repo = NotificationTemplateRepository(db)
    result: Dict[str, models.NotificationTemplate] = {}
    for code in codes:
        try:
            tpl = await repo.get_by_template_code(code)
            if tpl:
                result[code] = tpl
            else:
                # H6: Distinguish "not found" (expected) from DB error
                log.warning(
                    "Action template_code not found — using rule defaults",
                    template_code=code,
                    resolution="not_found",
                )
        except Exception as e:
            # H6: DB error is unexpected — log at ERROR level
            log.error(
                "DB error fetching template — using rule defaults",
                template_code=code,
                resolution="db_error",
                error=str(e),
            )
    return result


def _render_template_snapshot(
    template: "models.NotificationTemplate",
    payload: dict,
    fallback_snapshot: dict,
) -> dict:
    """
    Render title/message/link from a NotificationTemplate using payload
    placeholders, then return a snapshot dict compatible with _base_snapshot.

    Falls back to the provided fallback_snapshot values for any fields the
    template does not define.
    """
    from string import Template

    title = Template(template.title_template).safe_substitute(payload) if template.title_template else fallback_snapshot.get("title", "")
    message = Template(template.message_template).safe_substitute(payload) if template.message_template else fallback_snapshot.get("message", "")
    # PR1: link is code-owned — always use catalog link from fallback, ignore template.link_template
    link = fallback_snapshot.get("link")

    return {
        "title": title,
        "message": message,
        "link": link,
        "type": fallback_snapshot.get("type", "info"),
    }


# =============================================================================
# SOURCE EXTRACTION — Derive source_type/source_id from event + payload
# =============================================================================

# Payload key -> source_type mapping.  Order matters: first match wins.
_SOURCE_KEYS = [
    # admission_profile keys first — more specific than lead_id
    ("application_id", "admission_profile"),
    ("profile_id", "admission_profile"),
    ("admission_profile_id", "admission_profile"),
    # general keys
    ("lead_id", "lead"),
    ("collaborator_id", "collaborator"),
    ("user_id", "user"),
]


def _extract_source_from_payload(
    event: SystemEvents,
    payload: dict,
) -> tuple:
    """
    Best-effort extraction of (source_type, source_id) from event payload.

    Returns (None, None) if no recognisable key is found.
    """
    for key, source_type in _SOURCE_KEYS:
        val = payload.get(key)
        if val is not None:
            try:
                return source_type, int(val)
            except (ValueError, TypeError):
                continue
    return None, None


# =============================================================================
# DOMAIN EVENT EMITTER - Real-time UI Refresh
# =============================================================================

async def _emit_domain_event(
    event: SystemEvents,
    payload: dict,
    *,
    rooms: Optional[List[str]] = None,
) -> None:
    """
    ✅ REAL-TIME SYNC: Emit domain event via Socket.IO for instant UI refresh.

    Behavior (PR #2 — socket scoping, PII leak mitigation):

    - When `settings.SOCKET_SCOPED_EMIT=True` (default):
      * Sensitive events (`event_catalog.is_public_event(event)` is False)
        REQUIRE a non-empty ``rooms`` list. Calling without rooms logs a
        security error and **skips the emit entirely** (fail-closed) — a
        silent global broadcast would leak lead/applicant PII to every
        connected client.
      * Public events (org/pipeline/system-announcement config) MAY pass
        ``rooms=None`` and still broadcast globally — intended for
        all-users config metadata.
      * When ``rooms`` is a non-empty list, the event is emitted once per
        room. Duplicate rooms are de-duplicated to avoid double-fire.

    - When `settings.SOCKET_SCOPED_EMIT=False` (legacy escape hatch):
      ``rooms`` is ignored and every event broadcasts globally. Intended
      only for emergency rollback without redeploy.

    Race condition prevention (unchanged):
    - Includes timestamp for event ordering
    - Includes event_id for deduplication
    - Only called AFTER transaction commit (data is persisted)

    Args:
        event: SystemEvents enum (e.g., LEAD_CREATED, CONSULTATION_UPDATED)
        payload: Event payload to send to clients
        rooms: Optional list of Socket.IO room names to target. Required for
               sensitive events when scoping is enabled; None triggers the
               public/legacy broadcast path.
    """
    from app.socket_manager import sio
    from app.config import settings
    from app.core.event_catalog import is_public_event

    scoped_mode = getattr(settings, "SOCKET_SCOPED_EMIT", True)
    event_data = {
        **payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": f"{event.value}:{payload.get('lead_id', payload.get('consultation_id', 'unknown'))}:{int(datetime.now().timestamp() * 1000)}",
    }

    if scoped_mode:
        target_rooms = [r for r in (rooms or []) if r]
        # Fail-closed: sensitive events with no rooms = security bug, do not emit
        if not target_rooms and not is_public_event(event):
            log.error(
                "Sensitive event broadcast blocked: missing rooms",
                event_type=event.value,
                payload_keys=list(payload.keys()),
                reason="SOCKET_SCOPED_EMIT enabled; event is sensitive and no rooms provided",
            )
            return

        try:
            if target_rooms:
                # De-dupe so the same room receives the event once even if
                # helpers overlap (e.g. assigned officer also belongs to unit).
                seen = set()
                for room in target_rooms:
                    if room in seen:
                        continue
                    seen.add(room)
                    await sio.emit(event.value, event_data, room=room)
                log.info(
                    "Domain event emitted (scoped)",
                    event_type=event.value,
                    rooms=sorted(seen),
                    payload_keys=list(payload.keys()),
                )
            else:
                # Public event with no rooms → global broadcast is intended
                await sio.emit(event.value, event_data)
                log.info(
                    "Domain event broadcast (public)",
                    event_type=event.value,
                    payload_keys=list(payload.keys()),
                )
        except Exception as e:  # pragma: no cover — non-critical
            log.warning(
                "Failed to emit domain event (non-critical)",
                event_type=event.value,
                error=str(e),
            )
        return

    # Legacy path — SOCKET_SCOPED_EMIT disabled (rollback escape hatch)
    try:
        await sio.emit(event.value, event_data)
        log.info(
            "Domain event broadcast (legacy global)",
            event_type=event.value,
            payload_keys=list(payload.keys()),
        )
    except Exception as e:  # pragma: no cover — non-critical
        log.warning(
            "Failed to emit domain event (non-critical)",
            event_type=event.value,
            error=str(e),
        )


# =============================================================================
# ROOM HELPERS — Socket.IO scoping for domain events with lead/applicant PII
# =============================================================================
#
# These helpers build the `rooms=` list for `_emit_domain_event` so that
# sensitive events (admission mutations, lead/consultation updates, finance
# transactions) reach only the users who legitimately need realtime sync:
#
#   * `role_admin`                             — admin users (global visibility)
#   * `unit_<lead.unit_id>`                    — manager/officer in the owning unit
#   * `user_room_<lead.assigned_officer_id>`   — assigned officer across units
#
# Caller responsibility: eager-load `profile.lead` (selectinload) before
# calling `rooms_for_admission`. The helper returns `["role_admin"]` only
# if the lead relationship or its scoping fields are unavailable — in that
# case admins still see the event while unit/officer targeting is skipped.


def rooms_for_admission(profile) -> List[str]:
    """Compute Socket.IO rooms for an admission-scoped event.

    Returns a list containing `role_admin` + (if available) the owning
    unit's room and the assigned officer's personal room.
    """
    rooms: List[str] = ["role_admin"]
    lead = getattr(profile, "lead", None) if profile is not None else None
    if lead is not None:
        unit_id = getattr(lead, "unit_id", None)
        if unit_id is not None:
            rooms.append(f"unit_{unit_id}")
        officer_id = getattr(lead, "assigned_officer_id", None)
        if officer_id is not None:
            rooms.append(f"user_room_{officer_id}")
    return rooms


def rooms_for_lead(lead) -> List[str]:
    """Compute Socket.IO rooms for a lead-scoped event.

    Mirror of `rooms_for_admission` for events that carry a Lead row
    directly (e.g. LEAD_CREATED, LEAD_ASSIGNED).
    """
    rooms: List[str] = ["role_admin"]
    if lead is not None:
        unit_id = getattr(lead, "unit_id", None)
        if unit_id is not None:
            rooms.append(f"unit_{unit_id}")
        officer_id = getattr(lead, "assigned_officer_id", None)
        if officer_id is not None:
            rooms.append(f"user_room_{officer_id}")
    return rooms


def rooms_for_user(user_id: Optional[int]) -> List[str]:
    """Rooms for user-targeted sensitive events (USER_DEACTIVATED, USER_ROLE_CHANGED).

    Admin visibility + the target user's personal inbox. No unit scoping —
    user-centric events do not derive from an admission/lead tree.

    NOTE: SUSPICIOUS_LOGIN used to be on this list but moved off in
    Option-B Commit 7 — it now uses preference-gated rooms computed
    inside ``dispatch()`` (see ``_compute_suspicious_login_rooms``) and
    explicitly omits ``role_admin`` because the event targets the actor
    user, not the admin community.
    """
    rooms: List[str] = ["role_admin"]
    if user_id is not None:
        rooms.append(f"user_room_{user_id}")
    return rooms


def rooms_for_finance_review(
    profile, recipient_user_ids: Optional[List[int]] = None
) -> List[str]:
    """Rooms cho event tài chính nội bộ ĐỔI NGÀNH (chờ / đã xác nhận).

    Event ``privacy="sensitive"`` + ``SOCKET_SCOPED_EMIT`` ⇒ ``rooms=`` BẮT BUỘC
    non-empty, nếu rỗng domain emit bị bỏ hoàn toàn (fail-closed). Kế toán +
    admin thấy realtime; cộng room cá nhân từng recipient (officer ở event
    CONFIRMED) + unit của hồ sơ. ``role_accountant``/``role_admin`` là auto-join
    room theo role (socket_manager).
    """
    rooms: List[str] = ["role_admin", "role_accountant"]
    lead = getattr(profile, "lead", None) if profile is not None else None
    if lead is not None:
        unit_id = getattr(lead, "unit_id", None)
        if unit_id is not None:
            rooms.append(f"unit_{unit_id}")
    for uid in (recipient_user_ids or []):
        rooms.append(f"user_room_{uid}")
    return rooms


# ---------------------------------------------------------------------------
# Option-B Commit 7 — SUSPICIOUS_LOGIN socket gating
# ---------------------------------------------------------------------------
# The dispatcher has multiple ``_emit_domain_event`` callsites:
#
#   * Early branches (lines ~673/700/751/801/912): rule missing /
#     non-user class / config error / no recipients / all recipients
#     filtered. At these points the per-channel preference filter
#     hasn't run yet — for SUSPICIOUS_LOGIN we'd be emitting to whatever
#     ``rooms`` the caller passed (typically ``rooms_for_user`` =
#     ``role_admin`` + ``user_room_<uid>``), bypassing preference.
#   * Final branch (~line 1243): runs AFTER preference filter has built
#     ``channel_recipient_map``. For SUSPICIOUS_LOGIN we use that map's
#     ``browser`` entry to derive rooms — only users who opted into
#     ``security``/``browser`` see the socket bump.
#
# Plan v10 (V8.P0 + V9.P0): early branches SKIP emit for SUSPICIOUS_LOGIN,
# final branch emits only ``user_room_<eligible>`` and OMITS ``role_admin``.


def _is_suspicious_login_event(event: "SystemEvents") -> bool:
    """Single predicate so the early-branch skip logic doesn't drift."""
    return event == SystemEvents.SUSPICIOUS_LOGIN


def _compute_suspicious_login_rooms(
    channel_recipient_map: Dict[str, List[int]],
) -> List[str]:
    """Build the room list for a SUSPICIOUS_LOGIN emit at the final branch.

    Only users whose ``security`` group + ``browser`` channel preference
    is enabled appear in ``channel_recipient_map["browser"]`` (after
    Step 3's preference filter). We turn each eligible user_id into
    their personal ``user_room_<uid>`` and return that list — no
    ``role_admin``, no unit rooms.

    Empty list is meaningful: ``_emit_domain_event`` is fail-closed for
    sensitive events with empty rooms (line ~281), so the emit is
    skipped entirely. That is the correct UX: if the actor has disabled
    the browser channel, no banner bump fires.
    """
    eligible_browser_user_ids = channel_recipient_map.get("browser", [])
    return [f"user_room_{uid}" for uid in eligible_browser_user_ids]


def _all_role_rooms() -> List[str]:
    """Rooms covering every authenticated role.

    For genuinely all-hands broadcasts (SYSTEM_ALERT, system-wide
    announcements). Derives the room list from ``UserRole`` enum so a
    new role added to the enum (e.g. ``COLLABORATOR``) auto-picks up
    here — eliminates the hardcoded-list drift risk where adding a
    role + forgetting to update one broadcast site causes a silent
    delivery gap to that role.

    Format mirrors ``socket_manager.connect`` auto-join: each
    authenticated socket joins ``role_<value>`` (e.g. ``role_admin``,
    ``role_collaborator``). Sticking to ``UserRole`` as source of
    truth means the helper stays self-correcting.
    """
    from app.core.constants import UserRole
    return [f"role_{role.value}" for role in UserRole]


async def _send_via_channel(
    channel_name: str,
    notifications: List[Any],
    recipient_ids: List[int],
    context: dict,
    event: str
) -> Tuple[str, Optional[Any], Optional[str]]:
    """
    ✅ NOTIFICATION 2.0 - PHASE 3.1: Send notifications via a single channel with error handling.

    Helper function for parallel channel delivery using asyncio.gather().

    Args:
        channel_name: Name of the channel ("browser", "email", etc.)
        notifications: List of notification objects to send
        recipient_ids: List of recipient user IDs
        context: Event payload context
        event: Event name for logging

    Returns:
        Tuple of (channel_name, ChannelResult or None, error_message or None)
        - On success: (channel_name, ChannelResult, None)
        - On failure: (channel_name, None, error_message)
    """
    try:
        from app.services.notification_channels import get_channel

        channel = get_channel(channel_name)
        if channel is None:
            # Channel is known but not yet implemented (e.g. zalo, sms)
            log.info(
                "Channel not yet implemented, skipping delivery",
                channel=channel_name,
                event_type=event,
                recipient_count=len(recipient_ids),
            )
            return (channel_name, None, None)  # Not an error — just not ready

        result = await channel.send(
            notifications=notifications,
            recipient_ids=recipient_ids,
            context=context
        )
        return (channel_name, result, None)

    except ValueError as e:
        # Unknown channel (not registered)
        return (channel_name, None, f"Unknown channel: {str(e)}")
    except Exception as e:
        # Channel send failed
        return (channel_name, None, f"Delivery failed: {str(e)}")


def _build_action_snapshot(
    action,
    config,
    payload: dict,
    template_map: Dict[str, Any],
    notification_type: str = "info",
    catalog_link: str | None = None,
) -> dict:
    """Build content snapshot for a single action based on content_mode.

    PR1: link is always code-owned (catalog_link), never from DB/template/override.
    """
    mode = getattr(action, 'content_mode', None) or "inherit_default"

    base_snapshot = {
        "title": config.render_title(payload),
        "message": config.render_message(payload),
        "link": catalog_link,  # PR1: code-owned, not config.render_link
        "type": notification_type,
    }

    if mode == "inherit_default":
        return base_snapshot

    elif mode == "template_override":
        tpl_code = action.template_code
        tpl = template_map.get(tpl_code) if tpl_code else None
        if tpl:
            rendered = _render_template_snapshot(tpl, payload, base_snapshot)
            rendered["type"] = notification_type
            return rendered
        log.warning("template_code not resolved, using rule defaults",
                   step=action.step, template_code=tpl_code)
        return base_snapshot

    elif mode == "inline_override":
        override = getattr(action, 'content_override', None) or {}
        from string import Template
        return {
            "title": Template(override.get("title_template", "")).safe_substitute(payload) or base_snapshot["title"],
            "message": Template(override.get("message_template", "")).safe_substitute(payload) or base_snapshot["message"],
            "link": base_snapshot.get("link"),  # PR1: code-owned, ignore inline link_template
            "type": notification_type,
        }

    elif mode == "channel_native":
        raw_config = dict(getattr(action, 'config', None) or {})
        rendered = _render_channel_config_placeholders(raw_config, payload)
        return {**base_snapshot, **rendered}

    else:
        return base_snapshot


async def _create_deliveries_for_action(
    db: AsyncSession,
    event: str,
    action,
    user_ids: List[int],
    notification_id_map: Dict[int, int],
    dedupe_key: Optional[str] = None,
    payload_snapshot: Optional[dict] = None,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    rule_id: Optional[int] = None,
) -> List[int]:
    """Create delivery rows for a single action's recipients."""
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

    now = datetime.now(timezone.utc)
    delay = action.delay_minutes or 0
    scheduled_for = (now + timedelta(minutes=delay)) if delay > 0 else None

    deliveries_data = []
    for uid in user_ids:
        deliveries_data.append({
            "notification_id": notification_id_map.get(uid),
            "event": event,
            "channel": action.channel,
            "recipient_kind": "internal",
            "user_id": uid,
            "source_type": source_type,
            "source_id": source_id,
            "status": "queued",
            "dedupe_key": dedupe_key,
            "payload_snapshot": payload_snapshot,
            "rule_id": rule_id,
            "action_step": action.step,
            "template_code": action.template_code,
            "scheduled_for": scheduled_for,
        })

    if not deliveries_data:
        return []

    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_create_deliveries(deliveries_data)


async def _apply_delivery_deduplication(
    db: AsyncSession,
    user_ids: List[int],
    dedupe_key: str,
    channel: str,
) -> List[int]:
    """Filter out users who already have a delivery row with same dedupe_key + channel."""
    if not user_ids or not dedupe_key:
        return user_ids
    try:
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        existing = await repo.find_existing_user_ids_by_dedupe(user_ids, dedupe_key, channel)
        return [uid for uid in user_ids if uid not in existing]
    except Exception as e:
        log.warning("Delivery dedup failed, proceeding without dedup", error=str(e))
        return user_ids


def _validate_only_channels(only_channels: Optional[List[str]]) -> None:
    """Fail-fast validation for the ``only_channels`` dispatch filter.

    ``None`` = no restriction (default). A non-empty list must contain only
    canonical channels — ``validate_channels_for_write`` raises ``ValueError``
    on a typo (e.g. ``["brower"]``) or legacy ``"socket"``. An EMPTY list also
    raises: silently filtering every action out would swallow a security
    notification (e.g. suspicious-login). MUST be called BEFORE
    ``safe_dispatch``'s try/except, which absorbs all exceptions and would
    otherwise turn a typo into a silent zero-notification dispatch.
    """
    if only_channels is None:
        return
    if not only_channels:
        raise ValueError(
            "only_channels must be a non-empty list of canonical channels; "
            "use None for no restriction."
        )
    from app.services.notification_channels import validate_channels_for_write
    validate_channels_for_write(only_channels)  # raises on unknown / 'socket'


async def dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
    strict: bool = False,
    rooms: Optional[List[str]] = None,
    only_channels: Optional[List[str]] = None,
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification event — caller-controlled transaction.

    USE THIS when the caller owns the DB transaction and needs to commit
    business data together with notification records atomically, OR when
    the caller needs the post-commit callback (e.g., service returning
    ``(result, callback)`` per architecture V3).

    DO NOT USE for fire-and-forget notifications after main business commit.
    Use ``safe_dispatch()`` for that pattern instead.

    Args:
        db: Async database session (caller owns transaction)
        event: The system event to dispatch
        payload: Event payload with data for resolution and templates.
                 Caller is responsible for sanitizing user-facing values.
                 Template rendering uses string.Template.safe_substitute()
                 which leaves unresolved $placeholders as-is (safe).
        dedupe_key: Optional key for deduplication (e.g., "lead_assigned:123:456")
                   If provided, prevents duplicate notifications for same key+user
        skip_preference_check: If True, skip user preference filtering
                              Use for critical system notifications
        strict: Quyết định điều gì xảy ra khi pha ghi bền hỏng.
                ``True``  — ngoại lệ NỔI LÊN caller; caller phải bọc
                            ``db.begin_nested()`` để savepoint hấp thụ
                            (``dispatch_bundle`` làm đúng thế).
                ``False`` — hỏng ở pha tạo Notification CHA HUỶ CẢ SỰ KIỆN:
                            trả ``([], callback chỉ emit domain)``. KHÔNG
                            còn dữ liệu một phần, và KHÔNG còn
                            ``db.rollback()`` nội bộ nào (đã gỡ 2026-09-02
                            — nó cuộn về GỐC và nuốt cả giao dịch của
                            caller). Hỏng ở pha delivery thì đi tiếp sang
                            action kế, vì mỗi lần ghi có savepoint riêng.
        rooms: Optional Socket.IO rooms for the realtime domain emit.
               Required for sensitive events (admission/lead/finance/user
               PII) when ``settings.SOCKET_SCOPED_EMIT=True``; public
               events (org/pipeline config) may pass None and broadcast.
               Use ``rooms_for_admission(profile)`` / ``rooms_for_lead(lead)``
               / ``rooms_for_user(user_id)`` helpers at the call site.
        only_channels: Optional whitelist of canonical channels. When set,
                       only actions whose channel is in this list are
                       dispatched (in-app + external alike); the rest are
                       dropped. ``None`` (default) = all channels per the
                       rule. Used to gate low-risk suspicious-login to
                       browser-only without a per-action condition system.

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller MUST call ``await db.commit()`` then ``await callback()``.

    Contract:
        - Caller owns transaction: service flushes, caller commits
        - Caller runs callback AFTER commit (socket.io, email, worker enqueue)
        - On exception: caller handles rollback
        - Với ``strict=False``, lỗi pha CHA KHÔNG nổi lên: ``dispatch`` trả
          ``[]`` kèm callback chỉ emit domain. Caller phân biệt bằng danh
          sách rỗng, KHÔNG bằng exception.
        - When ``strict=True``: persistence errors propagate; the caller
          (typically ``dispatch_bundle``) must wrap the call in
          ``db.begin_nested()`` so the savepoint absorbs the rollback
          instead of the outer transaction.

    Example (service pattern)::

        notification_ids, callback = await dispatch(db=db, event=..., payload=...)
        await db.commit()
        if callback:
            await callback()

    See also: ``safe_dispatch()`` for the convenience wrapper.
    """
    log.info(
        "Dispatching notification event",
        event_type=event.value,
        dedupe_key=dedupe_key,
        payload_keys=list(payload.keys())
    )

    # Validate the channel filter up-front (fail-fast). Done here AND in
    # safe_dispatch (before its swallowing try) so a typo never silently
    # filters every action out.
    _validate_only_channels(only_channels)

    # Step 1: PR1 single-path — catalog + DB rule, no registry fallback
    from app.utils.exceptions import NotificationConfigError

    definition = get_event(event)
    if not definition or definition.retired:
        log.warning("Unknown or retired event, skip dispatch", event_type=event.value)
        async def _domain_only_callback():
            # Option-B Commit 7: SUSPICIOUS_LOGIN early branches skip the
            # domain emit entirely because preference filter hasn't run
            # yet and the rooms here would bypass user choice. Other
            # events continue to emit so data-sync listeners (LEAD_*,
            # ADMISSION_*) keep working.
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (unknown/retired event)",
                    event_type=event.value,
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    if definition.notification_class != "user":
        # broadcast_only / internal_future — domain event only, no user notification
        log.debug("Non-user event, domain-only dispatch",
                  event_type=event.value, cls=definition.notification_class)
        async def _domain_only_callback():
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (non-user class)",
                    event_type=event.value,
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    # Load DB rule (single source for user events)
    try:
        config = await get_rule_for_event(db, event)
    except NotificationConfigError as e:
        log.error("Config error loading rule, skip dispatch",
                  event_type=event.value, error=str(e))
        async def _domain_only_callback():
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (config error)",
                    event_type=event.value, error=str(e),
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    if not config:
        log.error(
            "No enabled DB rule for active user event (fail-closed)",
            event_type=event.value,
        )
        async def _domain_only_callback():
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (no enabled rule)",
                    event_type=event.value,
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    rule_source = "database"

    log.info(
        "Loaded notification rule",
        event_type=event.value,
        rule_source=rule_source,
        rule_id=getattr(config, 'rule_id', None),
        channels=config.channel_values
    )

    # v5: Inject ``is_self_action`` derived field so admins can add a
    # condition like ``is_self_action eq false`` to suppress notifications
    # when the actor and the recipient are the same person (officer
    # self-assigns a lead → don't spam themselves).
    #
    # We compute this from payload alone (NOT from resolver output) so it
    # is available before condition eval. Currently only events whose
    # payload contains both ``actor_id`` and ``officer_id`` are covered —
    # that's LEAD_ASSIGNED today. Other events that want this filter can
    # adopt by including ``officer_id`` in their payload, or via a future
    # field-vs-field condition operator.
    if "is_self_action" not in payload:
        actor_id = payload.get("actor_id")
        officer_id = payload.get("officer_id")
        if isinstance(actor_id, int) and isinstance(officer_id, int):
            payload["is_self_action"] = (actor_id == officer_id)

    # Step 1.5: ✅ PHASE 2.3: Check activation condition (database rules only)
    # Phase 2: Build evaluation context (nested dicts) for condition evaluation
    if rule_source == "database" and hasattr(config, 'should_activate'):
        if config.condition:
            from app.services.notification_condition_context import (
                analyze_condition, build_evaluation_context,
            )
            proj_ns, enrich_ns = analyze_condition(config.condition)
            eval_context = await build_evaluation_context(
                db, event, payload, proj_ns, enrich_ns,
            )
        else:
            eval_context = payload
        if not config.should_activate(eval_context):
            log.info(
                "Notification rule condition not met, skipping dispatch",
                event_type=event.value,
                rule_id=config.rule_id,
                condition=config.condition
            )
            async def _domain_only_callback():
                if _is_suspicious_login_event(event):
                    log.info(
                        "SUSPICIOUS_LOGIN early-branch skip (condition not met)",
                        event_type=event.value,
                    )
                    return
                await _emit_domain_event(event, payload, rooms=rooms)
            return [], _domain_only_callback

    # Step 2: Phase 3b — per-action recipient resolution
    from app.services.notification_rule_loader import deserialize_resolver

    rule_resolver = config.resolver
    action_configs = config.actions  # List[ActionConfig]
    if only_channels is not None:
        # Restrict to the requested channels (already validated above).
        # Reassigning action_configs HERE — before has_external_actions and
        # every downstream action loop (internal resolution, external
        # resolver, enqueue) — propagates the filter to all paths, so no
        # non-selected channel can leak a delivery through any branch.
        action_configs = [a for a in action_configs if a.channel in only_channels]
    action_user_map: Dict[int, List[int]] = {}  # step -> user_ids

    # Pre-compute: does ANY non-browser action have external_resolver?
    has_external_actions = any(
        a.channel != "browser" and a.config and a.config.get("external_resolver")
        for a in action_configs
    )

    for action in action_configs:
        # Phase 3c: external-only actions (have external_resolver in config but no
        # recipient_config) should NOT resolve internal users — they're handled
        # entirely by the external resolution path (Step 6.6).
        is_external_only = (
            not action.recipient_config
            and action.config
            and action.config.get("external_resolver")
        )

        if is_external_only:
            resolved = []  # No internal users — external path handles delivery
        elif action.recipient_config:
            try:
                action_resolver = deserialize_resolver(action.recipient_config)
                resolved = await action_resolver.resolve_users(db, payload)
            except Exception as e:
                # PR1: fail branch — do NOT fallback to rule_resolver
                log.error("Action resolver failed, skipping branch (no fallback)",
                          step=action.step, channel=action.channel, error=str(e))
                resolved = []
        else:
            try:
                resolved = await rule_resolver.resolve_users(db, payload)
            except Exception as e:
                log.error("Rule resolver failed", error=str(e))
                resolved = []
        action_user_map[action.step] = resolved

    all_internal_user_ids = sorted(set(uid for uids in action_user_map.values() for uid in uids))

    if not all_internal_user_ids and not has_external_actions:
        log.info("No recipients resolved for event (still emitting domain event)", event_type=event.value)
        async def _domain_only_callback():
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (no recipients resolved)",
                    event_type=event.value,
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    log.info(
        "Recipients resolved (per-action)",
        event_type=event.value,
        action_counts={s: len(u) for s, u in action_user_map.items()},
        total=len(all_internal_user_ids),
    )

    # Step 3: Phase 3b — per-action preference filtering
    group = get_event_group(event)
    action_filtered_map: Dict[int, List[int]] = {}

    for action in action_configs:
        action_users = action_user_map.get(action.step, [])
        if skip_preference_check:
            action_filtered_map[action.step] = list(action_users)
        else:
            if action_users:
                filtered = await notification_preference_service.filter_users_by_group(
                    db=db, user_ids=action_users, group=group.value, channel=action.channel,
                )
                action_filtered_map[action.step] = filtered
            else:
                action_filtered_map[action.step] = []

    # Step 3.2: PR1 — cross-action user dedup (step order = precedence)
    from collections import defaultdict
    seen_by_channel: Dict[str, set] = defaultdict(set)
    for action in sorted(action_configs, key=lambda a: a.step):
        users = action_filtered_map.get(action.step, [])
        deduped = [uid for uid in users if uid not in seen_by_channel[action.channel]]
        if len(users) != len(deduped):
            log.info("Cross-action dedup", step=action.step, channel=action.channel,
                     original=len(users), after=len(deduped))
        seen_by_channel[action.channel].update(deduped)
        action_filtered_map[action.step] = deduped

    # PR1: Fall back to catalog dedup_key if caller didn't supply one
    if not dedupe_key:
        dedupe_key = render_dedup_key(event, payload)

    # Union by channel for inbox + short-circuit
    channel_recipient_map: Dict[str, List[int]] = {}
    for action in action_configs:
        users = action_filtered_map.get(action.step, [])
        existing = channel_recipient_map.get(action.channel, [])
        channel_recipient_map[action.channel] = sorted(set(existing + users))

    # Step 3.5: Phase 3b — action-scoped cooldown + rate limit
    # Cooldown key includes dedupe_key when available so that different
    # transitions of the same event (e.g., draft→submitted vs submitted→approved
    # both using APPLICATION_STATUS_CHANGED) don't block each other.
    from app.config import settings as _settings

    for action in action_configs:
        users = action_filtered_map.get(action.step, [])
        cooled = []
        _cd_suffix = f":{dedupe_key}:step{action.step}" if dedupe_key else f":{action.step}"
        for uid in users:
            cooldown_key = f"notif:cooldown:{event.value}:{uid}:{action.channel}{_cd_suffix}"
            # 1.9c: Atomic SET NX — eliminates race window between EXISTS + SET
            acquired = await safe_redis_set(
                cooldown_key, "1", nx=True, ex=_settings.NOTIFICATION_COOLDOWN_SECONDS
            )
            if not acquired:
                continue  # user already in cooldown
            rate_key = f"notif:rate:{uid}"
            count = await safe_redis_incr(rate_key)
            if count == 1:
                await safe_redis_expire(rate_key, 3600)
            if count and count > _settings.NOTIFICATION_RATE_LIMIT_PER_HOUR:
                continue
            cooled.append(uid)
        action_filtered_map[action.step] = cooled

    # Step 4: Phase 3b — action-scoped dedup
    action_dedupe_keys: Dict[int, Optional[str]] = {}
    if dedupe_key:
        for action in action_configs:
            users = action_filtered_map.get(action.step, [])
            action_dedupe_key = f"{dedupe_key}:step{action.step}"
            if action.channel == "browser":
                deduped = await _apply_deduplication(db, users, action_dedupe_key)
            else:
                deduped = await _apply_delivery_deduplication(db, users, action_dedupe_key, action.channel)
            action_filtered_map[action.step] = deduped
            action_dedupe_keys[action.step] = action_dedupe_key
    else:
        for action in action_configs:
            action_dedupe_keys[action.step] = None

    # Re-union after cooldown/dedup
    channel_recipient_map = {}
    for action in action_configs:
        users = action_filtered_map.get(action.step, [])
        existing = channel_recipient_map.get(action.channel, [])
        channel_recipient_map[action.channel] = sorted(set(existing + users))

    inbox_user_ids = sorted(set(channel_recipient_map.get("browser", [])))

    # Short-circuit #1
    all_recipients = set()
    for ids in channel_recipient_map.values():
        all_recipients.update(ids)

    if not all_recipients and not has_external_actions:
        log.info("All recipients filtered out (still emitting domain event)",
                event_type=event.value, group=group.value)
        async def _domain_only_callback():
            if _is_suspicious_login_event(event):
                log.info(
                    "SUSPICIOUS_LOGIN early-branch skip (all recipients filtered)",
                    event_type=event.value, group=group.value,
                )
                return
            await _emit_domain_event(event, payload, rooms=rooms)
        return [], _domain_only_callback

    log.info(
        "Recipients after filtering/cooldown/dedup",
        event_type=event.value,
        channel_counts={ch: len(ids) for ch, ids in channel_recipient_map.items()},
    )

    # Step 5: Render notification content
    # PR1: title/message from DB rule, link from catalog (code-owned)
    title = config.render_title(payload)
    message = config.render_message(payload)
    link = render_link(event, payload)  # code-owned, ignore DB link_template

    # Determine notification type (can be overridden by payload for alerts)
    notification_type = payload.get("severity", config.notification_type)

    # Build data payload for notification (exclude large fields)
    notification_data = {
        "event": event.value,
        "group": config.group.value,
        **{k: v for k, v in payload.items() if k not in ["message", "description"]}
    }
    if dedupe_key:
        # Phase 3b: use action-scoped dedupe key for browser action
        browser_action = next((a for a in action_configs if a.channel == "browser"), None)
        notification_data["dedupe_key"] = action_dedupe_keys.get(browser_action.step) if browser_action else dedupe_key

    # Step 6: Bulk insert inbox Notification rows (for browser-eligible users only)
    notification_id_map: Dict[int, int] = {}
    if inbox_user_ids:
        try:
            # Savepoint CẤP SỰ KIỆN, bao trọn CẢ vòng lặp chunk bên trong
            # ``_bulk_create_notifications``. Savepoint cấp-chunk (bản trước)
            # cho một bảo đảm sai: với hơn 100 người nhận, chunk 1 release
            # xong rồi chunk 2 hỏng thì hàng của chunk 1 vẫn nằm trong giao
            # dịch ngoài, và khối dọn hàng mồ côi phía dưới KHÔNG chạy tới
            # (đường ``except`` này ``return`` trước nó) ⇒ commit ra hàng mồ côi.
            async with db.begin_nested():
                notification_id_map = await _bulk_create_notifications(
                    db=db,
                    user_ids=inbox_user_ids,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    link=link,
                    data=notification_data,
                    strict=strict,
                )
        except Exception as e:
            # Hỏng ở pha CHA thì huỷ cả sự kiện. Đi tiếp sẽ dùng một danh
            # sách ID thiếu/lệch so với ``inbox_user_ids`` và sinh delivery
            # trỏ sai người nhận hoặc trỏ vào hàng không tồn tại.
            #
            # Phiên còn dùng được ở đây là nhờ ``async with db.begin_nested()``
            # NGAY TRÊN — savepoint cấp sự kiện đã ``ROLLBACK TO`` trước khi
            # tới đây. KHÔNG phải nhờ repository: ``bulk_create`` đã bỏ
            # savepoint riêng, có chủ ý (xem chú thích ở đó).
            log.error(
                "Failed to create parent notifications — aborting event",
                event_type=event.value,
                recipient_count=len(inbox_user_ids),
                error=str(e),
                strict=strict,
            )
            if strict:
                raise

            async def _abort_callback():
                await _emit_domain_event(event, payload, rooms=rooms)

            return [], _abort_callback

    # ``notification_ids`` chỉ còn là DẪN XUẤT của bản đồ có chủ quyền.
    # Mọi quan hệ user ↔ notification phải đi qua ``notification_id_map``.
    notification_ids = list(notification_id_map.values())

    # Phase C1: notification_ids can be empty (no browser recipients) while
    # other channels still have recipients. Only short-circuit if truly nothing.
    if not notification_ids and not any(channel_recipient_map.values()) and not has_external_actions:
        log.error(
            "Failed to create notifications and no channel recipients for event",
            event_type=event.value
        )
        async def _empty_callback():
            pass
        return [], _empty_callback

    # (Bản đồ đã được dựng từ ``RETURNING user_id, id`` ở trên — KHÔNG
    # ``dict(zip(inbox_user_ids, notification_ids))``: thứ tự RETURNING của
    # bulk insert không có bảo đảm hình thức, ghép theo vị trí sẽ gán
    # notification của người này cho người kia.)
    _source_type, _source_id = _extract_source_from_payload(event, payload)

    # Phase E2: Pre-fetch templates for per-action rendering
    _action_template_map = await _resolve_action_templates(db, action_configs)

    # Phase 3b: per-action delivery rows
    from app.services import notification_delivery_service
    action_delivery_map: Dict[int, List[int]] = {}
    channel_delivery_ids: Dict[str, List[int]] = {}
    # Những ``notification`` cha ĐÃ có ít nhất một hàng delivery đi kèm.
    # Đếm trong bộ nhớ chứ không truy vấn lại: rẻ hơn một round-trip mỗi
    # lượt dispatch, và đúng cả khi phiên là đối tượng giả trong test.
    _notif_da_giao: set = set()
    # user_id -> delivery_id cho kênh browser. Dựng NGAY tại chỗ ghi, nơi
    # thứ tự người nhận và thứ tự delivery chắc chắn khớp nhau.
    _browser_uid_to_did: Dict[int, int] = {}

    for action in action_configs:
        action_users = action_filtered_map.get(action.step, [])
        if not action_users:
            continue

        snapshot = _build_action_snapshot(
            action, config, payload, _action_template_map,
            notification_type=notification_type,
            catalog_link=link,
        )

        try:
            delivery_ids = await _create_deliveries_for_action(
                db=db, event=event.value, action=action,
                user_ids=action_users, notification_id_map=notification_id_map,
                dedupe_key=action_dedupe_keys.get(action.step),
                payload_snapshot=snapshot,
                source_type=_source_type, source_id=_source_id,
                rule_id=config.rule_id if hasattr(config, 'rule_id') else None,
            )
            action_delivery_map[action.step] = delivery_ids
            channel_delivery_ids.setdefault(action.channel, []).extend(delivery_ids)
            # CHỈ kênh ``browser``. Hàng ``Notification`` LÀ hàng inbox —
            # nó chỉ được tạo khi có người nhận kênh browser
            # (``inbox_user_ids = channel_recipient_map["browser"]``). Một
            # action ``email`` ghi được delivery KHÔNG chứng minh chuông của
            # người đó có đường giao; đếm cả kênh khác sẽ để lại hàng inbox
            # không ai giao được mà vẫn coi là hợp lệ.
            if action.channel == "browser":
                _notif_da_giao.update(
                    notification_id_map[_u] for _u in action_users
                    if notification_id_map.get(_u) is not None
                )
                # ``_create_deliveries_for_action`` dựng ``deliveries_data``
                # theo đúng thứ tự ``user_ids``, và ``bulk_create_deliveries``
                # giữ nguyên thứ tự ấy — nên ghép ở ĐÂY là an toàn.
                _browser_uid_to_did.update(zip(action_users, delivery_ids))
        except Exception as e:
            log.error("Failed to create delivery rows for action",
                     step=action.step, channel=action.channel, error=str(e),
                     strict=strict)
            if strict:
                # Bundle atomicity: a delivery_row insert failure would
                # leave Notification rows in the savepoint without their
                # paired delivery_rows. Re-raise so the caller's
                # SAVEPOINT rolls back the whole bundle and the outer
                # business txn survives. Non-strict callers keep the
                # best-effort skip for legacy parity.
                raise

    # Step 6.6: External recipient resolution (Phase C1/G3)
    # For non-browser actions with external_resolver in config, resolve external
    # contacts and create external delivery rows.
    _external_delivery_ids: Dict[str, List[int]] = {}
    for action in action_configs:
        if action.channel == "browser":
            continue  # Browser is internal-only
        if not action.config or "external_resolver" not in action.config:
            continue

        ext_resolver_type = action.config["external_resolver"]
        try:
            from app.services.notification_recipients import EXTERNAL_RESOLVER_REGISTRY

            resolver_fn = EXTERNAL_RESOLVER_REGISTRY.get(ext_resolver_type)
            if not resolver_fn:
                log.warning(
                    "Unknown external resolver type",
                    resolver_type=ext_resolver_type,
                    event_type=event.value,
                )
                continue

            # Determine source ID from payload
            _ext_source_key_map = {
                "lead_contact": "lead_id",
                "admission_contact": ("profile_id", "admission_profile_id"),
                "collaborator_contact": "collaborator_id",
            }
            source_keys = _ext_source_key_map.get(ext_resolver_type, ())
            if isinstance(source_keys, str):
                source_keys = (source_keys,)

            source_id_val = None
            for sk in source_keys:
                source_id_val = payload.get(sk)
                if source_id_val is not None:
                    break

            if source_id_val is None:
                continue

            recipient = await resolver_fn(db, int(source_id_val))
            if not recipient:
                continue

            # FP2: Collaborator fallback — if resolver returns an internal user
            # (e.g. collaborator with linked user_id), apply same filters as
            # normal internal path before creating delivery.
            if recipient.recipient_kind == "internal" and recipient.user_id:
                uid = recipient.user_id
                ch = action.channel

                # Phase 3b fix: apply preference/cooldown/dedup to internal fallback
                # 1. Preference check
                if not skip_preference_check:
                    pref_filtered = await notification_preference_service.filter_users_by_group(
                        db=db, user_ids=[uid], group=group.value, channel=ch,
                    )
                    if not pref_filtered:
                        log.debug("Internal fallback user filtered by preference",
                                 user_id=uid, channel=ch)
                        continue

                # 2. Cooldown check — atomic SET NX (1.9c)
                _fb_cd_suffix = f":{dedupe_key}:step{action.step}" if dedupe_key else f":{action.step}"
                cooldown_key = f"notif:cooldown:{event.value}:{uid}:{ch}{_fb_cd_suffix}"
                fb_acquired = await safe_redis_set(
                    cooldown_key, "1", nx=True, ex=_settings.NOTIFICATION_COOLDOWN_SECONDS
                )
                if not fb_acquired:
                    log.debug("Internal fallback user in cooldown", user_id=uid)
                    continue

                # 3. Dedup check
                _action_dk = action_dedupe_keys.get(action.step)
                if _action_dk:
                    if ch == "browser":
                        deduped = await _apply_deduplication(db, [uid], _action_dk)
                    else:
                        deduped = await _apply_delivery_deduplication(db, [uid], _action_dk, ch)
                    if not deduped:
                        log.debug("Internal fallback user deduped", user_id=uid)
                        continue

                # Cooldown already set atomically via SET NX above

                ch_snapshot = _build_action_snapshot(action, config, payload, _action_template_map, notification_type=notification_type, catalog_link=link)
                delay_minutes = action.delay_minutes or 0
                int_scheduled_for = None
                if delay_minutes > 0:
                    int_scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

                from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
                repo = NotificationDeliveryRepository(db)
                fallback_ids = await repo.bulk_create_deliveries([{
                    "notification_id": notification_id_map.get(uid),
                    "event": event.value,
                    "channel": ch,
                    "recipient_kind": "internal",
                    "user_id": uid,
                    "source_type": recipient.source_type,
                    "source_id": recipient.source_id,
                    "status": "queued",
                    "dedupe_key": _action_dk,
                    "payload_snapshot": ch_snapshot,
                    "rule_id": config.rule_id if hasattr(config, 'rule_id') else None,
                    "action_step": action.step,
                    "template_code": action.template_code,
                    "scheduled_for": int_scheduled_for,
                }])
                if fallback_ids:
                    channel_delivery_ids.setdefault(ch, []).extend(fallback_ids)
                    action_delivery_map.setdefault(action.step, []).extend(fallback_ids)
                    # KHÔNG cộng vào ``_notif_da_giao``: vòng lặp external
                    # đã ``continue`` với ``action.channel == "browser"``, nên
                    # nhánh fallback này chỉ tạo delivery cho kênh KHÁC browser.
                log.info(
                    "External resolver returned internal user, created internal delivery",
                    event_type=event.value,
                    channel=ch,
                    user_id=uid,
                    resolver=ext_resolver_type,
                )
                continue

            # Determine destination based on channel (external recipients)
            destination = None
            if action.channel in ("zalo", "sms"):
                destination = recipient.destination_phone
            elif action.channel == "email":
                destination = recipient.destination_email

            if not destination:
                continue

            # External cooldown — check-then-set (no race concern for external)
            _ext_cd_suffix = f":{dedupe_key}:step{action.step}" if dedupe_key else f":{action.step}"
            ext_cooldown_key = f"notif:cooldown:{event.value}:{destination}:{action.channel}{_ext_cd_suffix}"
            if await safe_redis_exists(ext_cooldown_key):
                log.info(
                    "External delivery skipped (cooldown)",
                    event_type=event.value, channel=action.channel,
                    destination=destination,
                )
                continue

            # External dedup: skip if delivery row with same dedupe_key+channel+destination exists
            ext_dedupe_key = action_dedupe_keys.get(action.step)
            if ext_dedupe_key:
                from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
                _dedup_repo = NotificationDeliveryRepository(db)
                if await _dedup_repo.exists_external_delivery(ext_dedupe_key, action.channel, destination):
                    log.info(
                        "External delivery skipped (dedup)",
                        event_type=event.value, channel=action.channel,
                        destination=destination, dedupe_key=ext_dedupe_key,
                    )
                    continue

            ch_snapshot = _build_action_snapshot(action, config, payload, _action_template_map, notification_type=notification_type)
            delay_minutes = action.delay_minutes or 0
            ext_scheduled_for = None
            if delay_minutes > 0:
                ext_scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

            ext_ids = await notification_delivery_service.prepare_external_deliveries(
                db=db,
                event=event.value,
                channel=action.channel,
                recipients=[{
                    "source_type": recipient.source_type,
                    "source_id": recipient.source_id,
                    "destination": destination,
                }],
                dedupe_key=action_dedupe_keys.get(action.step),
                payload_snapshot=ch_snapshot,
                rule_id=config.rule_id if hasattr(config, 'rule_id') else None,
                action_step=action.step,
                template_code=action.template_code,
                scheduled_for=ext_scheduled_for,
            )
            if ext_ids:
                # Set cooldown only after successful delivery
                await safe_redis_set(ext_cooldown_key, "1", ex=_settings.NOTIFICATION_COOLDOWN_SECONDS)
                _external_delivery_ids.setdefault(action.channel, []).extend(ext_ids)
                action_delivery_map.setdefault(action.step, []).extend(ext_ids)
                log.info(
                    "External delivery rows created",
                    event_type=event.value,
                    channel=action.channel,
                    resolver=ext_resolver_type,
                    count=len(ext_ids),
                )

        except Exception as e:
            log.warning(
                "External recipient resolution failed (non-critical)",
                event_type=event.value,
                channel=action.channel,
                resolver_type=ext_resolver_type,
                error=str(e),
                strict=strict,
            )
            if strict:
                # Bundle atomicity parity: external deliveries persist
                # rows via ``prepare_external_deliveries`` (line ~997),
                # so a failure here is not purely a resolver lookup
                # miss — it can also be an insert failure that would
                # leave a partially-persisted bundle. Surface it so the
                # SAVEPOINT rolls back. Legacy callers keep the
                # non-critical skip.
                raise

    # Merge external delivery IDs into channel_delivery_ids for worker enqueueing
    for ch, ext_ids in _external_delivery_ids.items():
        channel_delivery_ids.setdefault(ch, []).extend(ext_ids)

    # ✅ 2026-09-02: KHÔNG để lại ``notification`` mồ côi.
    #
    # Với savepoint theo từng lần ghi, một action hỏng nay chỉ cuộn phần
    # của nó — nghĩa là hàng ``notification`` cha VẪN SỐNG. Nếu không
    # action nào ghi được delivery cho nó thì đó là chuông đỏ trong inbox
    # mà không đường nào giao, và không dấu vết kiểm toán nào giải thích.
    # Không ràng buộc nào của CSDL canh quan hệ này, nên phải canh ở đây.
    if notification_ids:
        _mo_coi = [n for n in notification_ids if n not in _notif_da_giao]
        if _mo_coi:
            log.warning(
                "Rolling back orphan notifications (no delivery row created)",
                event_type=event.value,
                orphan_count=len(_mo_coi),
            )
            await db.execute(
                sa_delete(models.Notification)
                .where(models.Notification.id.in_(_mo_coi))
            )
            # ⚠️ Phải cập nhật ĐỒNG BỘ cả ba cấu trúc dẫn xuất. Bản trước chỉ
            # thu gọn ``notification_ids`` rồi vẫn ``zip()`` nó với
            # ``inbox_user_ids`` NGUYÊN VẸN ở bước nạp cache inbox — ghép lệch
            # một bậc: [u1,u2] ↔ [n1,n2] mà chỉ n2 sống sót thì thành u1 ↔ n2,
            # tức ID notification của u2 bị đẩy vào ``user_inbox:u1``.
            # ``notification_id_map`` là nguồn chuẩn; hai danh sách chỉ là
            # dẫn xuất và phải theo nó.
            _mo_coi_set = set(_mo_coi)
            notification_id_map = {
                _u: _n for _u, _n in notification_id_map.items()
                if _n not in _mo_coi_set
            }
            notification_ids = [
                n for n in notification_ids if n not in _mo_coi_set
            ]
            inbox_user_ids = [
                _u for _u in inbox_user_ids if _u in notification_id_map
            ]

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback with all post-commit actions
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Notifications committed successfully",
            event_type=event.value,
            notification_count=len(notification_ids),
            notification_type=notification_type,
            channel_counts={ch: len(ids) for ch, ids in channel_recipient_map.items()},
        )

        # Step 7.25: ✅ REAL-TIME SYNC: Emit domain event for UI refresh.
        # Option-B Commit 7: SUSPICIOUS_LOGIN computes its rooms from
        # ``channel_recipient_map["browser"]`` — only users who passed
        # the security/browser preference filter receive the banner
        # bump. role_admin is NOT included (this is an actor-targeted
        # event, not an admin alert). If no eligible users remain,
        # ``_compute_suspicious_login_rooms`` returns ``[]`` and
        # ``_emit_domain_event``'s fail-closed guard skips the emit.
        if _is_suspicious_login_event(event):
            emit_rooms = _compute_suspicious_login_rooms(channel_recipient_map)
            if not emit_rooms:
                log.info(
                    "SUSPICIOUS_LOGIN socket emit skipped (no browser-eligible recipients)",
                    event_type=event.value,
                )
            else:
                await _emit_domain_event(event, payload, rooms=emit_rooms)
        else:
            await _emit_domain_event(event, payload, rooms=rooms)

        # Step 7.5: ✅ PHASE 1.2: Prepend new notifications to inbox cache
        # Chỉ nạp cache cho người nhận kênh browser (chuông / dropdown).
        #
        # Dẫn xuất từ ``notification_id_map`` chứ KHÔNG ``zip()`` hai danh
        # sách theo vị trí: bất biến "notification_ids[i] ứng với
        # inbox_user_ids[i]" vỡ ngay khi khối dọn hàng mồ côi bỏ bớt một
        # phần tử, và hệ quả là ghi ID của người này vào inbox người kia.
        browser_set = set(channel_recipient_map.get("browser", []))
        if notification_id_map and browser_set:
            browser_notif_pairs = [
                (uid, nid)
                for uid, nid in notification_id_map.items()
                if uid in browser_set
            ]
            if browser_notif_pairs:
                b_uids, b_nids = zip(*browser_notif_pairs)
                await _prepend_to_inbox_cache(list(b_uids), list(b_nids))

        # ✅ Phase C1: Split delivery paths — browser inline, non-browser via worker
        # Step 8a: Browser channel — inline (real-time requirement)
        try:
            browser_del_ids = channel_delivery_ids.get("browser", [])
            browser_recipients = channel_recipient_map.get("browser", [])

            if browser_recipients and notification_id_map:
                repo = NotificationRepository(db)
                _bset = set(browser_recipients)
                _ids_browser = [
                    _n for _u, _n in notification_id_map.items() if _u in _bset
                ]
                # ``owner_user_id=None`` TƯỜNG MINH: các ID này vừa do chính
                # lượt dispatch tạo ra trong cùng giao dịch, chủ quyền đã biết.
                notifications = await repo.get_by_ids(
                    _ids_browser, owner_user_id=None
                )

                ch_name, ch_result, error_msg = await _send_via_channel(
                    channel_name="browser",
                    notifications=notifications,
                    recipient_ids=browser_recipients,
                    context=payload,
                    event=event.value,
                )

                # 1.9b: Use separate session for delivery status updates
                # to avoid nested commit on caller's session
                # KHÔNG ``zip(browser_recipients, browser_del_ids)``:
                # ``browser_recipients`` đã được ``sorted()`` ở bước hợp nhất
                # kênh, còn ``browser_del_ids`` nối theo thứ tự action rồi
                # theo thứ tự resolver trả về — hai thứ tự KHÁC nhau, nên
                # ghép theo vị trí sẽ đánh dấu ``sent``/``failed`` lên hàng
                # delivery của NGƯỜI KHÁC. Dùng bản đồ dựng tại chỗ ghi.
                uid_to_did = _browser_uid_to_did
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as _delivery_db:
                    if browser_del_ids:
                        from app.services import notification_delivery_service as _nds
                        if ch_result is None and error_msg is None:
                            await _nds.mark_delivery_ids_skipped(
                                _delivery_db, browser_del_ids,
                                error_reason="channel_not_implemented",
                            )
                        elif error_msg:
                            await _nds.mark_delivery_ids_failed(
                                _delivery_db, browser_del_ids, error_reason=error_msg,
                            )
                        elif ch_result:
                            sent_ids_2 = [
                                uid_to_did[uid]
                                for uid in browser_recipients
                                if uid not in ch_result.failed_ids and uid in uid_to_did
                            ]
                            if sent_ids_2:
                                await _nds.mark_delivery_ids_sent(_delivery_db, sent_ids_2)
                            failed_ids_2 = [
                                uid_to_did[uid]
                                for uid in ch_result.failed_ids
                                if uid in uid_to_did
                            ]
                            if failed_ids_2:
                                await _nds.mark_delivery_ids_failed(
                                    _delivery_db, failed_ids_2,
                                    error_reason=ch_result.error_message or "delivery_failed",
                                )
                    await _delivery_db.commit()

        except Exception as e:
            log.error(
                "Browser inline delivery failed",
                event_type=event.value,
                error=str(e),
                fallback="Browser notifications failed but inbox rows are in DB",
            )

        # Step 8b: Phase 3b — enqueue per action with action-specific delay
        try:
            from app.tasks.delivery_tasks import execute_notification_delivery

            worker_enqueued = 0
            for action in action_configs:
                if action.channel == "browser":
                    continue
                del_ids = action_delivery_map.get(action.step, [])
                if not del_ids:
                    continue
                delay = action.delay_minutes or 0
                countdown = delay * 60
                for did in del_ids:
                    execute_notification_delivery.apply_async(
                        args=[did],
                        countdown=countdown,
                    )
                    worker_enqueued += 1

            if worker_enqueued:
                log.info(
                    "Non-browser deliveries enqueued to worker",
                    event_type=event.value,
                    enqueued_count=worker_enqueued,
                )

        except Exception as e:
            log.error(
                "Failed to enqueue worker deliveries (non-critical)",
                event_type=event.value,
                error=str(e),
            )

    return notification_ids, _post_commit


async def _apply_deduplication(
    db: AsyncSession,
    user_ids: List[int],
    dedupe_key: str
) -> List[int]:
    """
    Filter out users who already have a notification with the same dedupe_key.

    This prevents duplicate notifications when the same event is dispatched
    multiple times (e.g., retries, race conditions).

    Args:
        db: Database session
        user_ids: List of user IDs to check
        dedupe_key: The deduplication key

    Returns:
        Filtered list of user IDs who don't have the notification yet
    """
    try:
        # Find users who already have notification with this dedupe_key
        # The dedupe_key is stored in the data JSON column
        repo = NotificationRepository(db)
        existing_user_ids = await repo.get_by_dedupe_key(user_ids, dedupe_key)

        # Return users who don't have the notification yet
        filtered_ids = [uid for uid in user_ids if uid not in existing_user_ids]

        if existing_user_ids:
            log.debug(
                "Deduplication applied",
                dedupe_key=dedupe_key,
                original_count=len(user_ids),
                duplicate_count=len(existing_user_ids),
                remaining_count=len(filtered_ids)
            )

        return filtered_ids

    except Exception as e:
        log.warning(
            "Deduplication check failed, proceeding without deduplication",
            dedupe_key=dedupe_key,
            error=str(e),
            user_count=len(user_ids)
        )
        # On failure, proceed without deduplication to avoid losing notifications
        return user_ids


async def _bulk_create_notifications(
    db: AsyncSession,
    user_ids: List[int],
    title: str,
    message: str,
    notification_type: str,
    link: Optional[str],
    data: dict,
    strict: bool = False,
) -> Dict[int, int]:
    """
    Bulk insert notifications for multiple users.

    Uses SQLAlchemy Core insert for efficiency with large recipient lists.
    Processes in chunks to avoid DB timeout.

    Args:
        db: Database session
        user_ids: List of recipient user IDs
        title: Notification title
        message: Notification message
        notification_type: Type (info, success, warning, error)
        link: Optional navigation link
        data: Additional data payload
        strict: Ở TẦNG NÀY chỉ còn là một trường log. Hỏng chunk LUÔN được
                ném ra, kể cả ``strict=False`` — quyết định huỷ hay đi
                tiếp thuộc về ``dispatch()``, tầng mở savepoint cấp sự
                kiện bao trọn vòng lặp chunk này. Đường ``db.rollback()``
                cũ đã gỡ: nó cuộn về GỐC chứ không về savepoint, nên nó
                xoá luôn dữ liệu nghiệp vụ của caller.

    Returns:
        ``{user_id: notification_id}`` hợp nhất qua MỌI chunk. Quan hệ này
        đến thẳng từ ``RETURNING user_id, id`` của từng lệnh INSERT, KHÔNG
        từ vị trí trong danh sách — thứ tự RETURNING của bulk insert không
        có bảo đảm hình thức.
    """
    ket_qua: Dict[int, int] = {}
    now = datetime.now(timezone.utc)

    repo = NotificationRepository(db)

    # Process in chunks
    for i in range(0, len(user_ids), BULK_INSERT_CHUNK_SIZE):
        chunk = user_ids[i:i + BULK_INSERT_CHUNK_SIZE]

        # Build insert values
        values = [
            {
                "user_id": user_id,
                "type": notification_type,
                "title": title,
                "message": message,
                "link": link,
                "data": data,
                "is_read": False,
                "created_at": now
            }
            for user_id in chunk
        ]

        try:
            # Use repository for bulk insert
            cap_chunk = await repo.bulk_create(values)
            # Fail-closed: tập người nhận trả về phải BẰNG CHÍNH XÁC tập
            # người nhận đã gửi đi — so ĐỊNH DANH, không suy từ lực lượng.
            #
            # Bản trước chỉ đếm số hàng và số user duy nhất, nên
            # ``chunk=[u1,u2]`` với kết quả ``[(u1,n1),(u3,n2)]`` LỌT: đúng
            # hai hàng, đúng hai user duy nhất — mà u2 biến mất và u3 (ngoài
            # tập) lọt vào bản đồ chủ quyền. Với một bất biến sở hữu thì
            # lực lượng không thay được định danh.
            #
            # Ba vế, ba chế độ hỏng khác nhau:
            #   1. sai SỐ LƯỢNG        — RETURNING hụt/thừa hàng
            #   2. trả TRÙNG user_id   — cùng user_id hai lần
            #   3. sai THÀNH VIÊN      — đủ số nhưng lệch tập
            #
            # Vế 1 và vế 2 CHỈ sống khi ``user_ids`` có phần tử trùng: nếu
            # đầu vào đã duy nhất thì chúng bị vế 3 bao hàm. Chỗ gọi sản
            # phẩm DUY NHẤT (``dispatch``) truyền ``sorted(set(...))`` nên
            # hôm nay chỉ vế 3 gác một đường thật — hai vế kia là hợp đồng
            # phòng thủ cho caller TƯƠNG LAI. Nói rõ để người đọc sau
            # không tưởng cả ba đang canh cùng một thứ.
            # Mỗi vế có một ca kiểm ngược RIÊNG (BT13); không vế nào thừa.
            #
            # KHÔNG kiểm ``notification_id`` duy nhất: ``Notification.id`` là
            # khoá chính, nên id trùng không có chế độ hỏng khả dĩ — thêm
            # vào chỉ là một dòng không phép kiểm nào canh được.
            # Dùng `elif` để thông điệp nói ĐÚNG vế nào vỡ. Ba vế cùng một
            # câu chữ thì `pytest.raises(match=…)` không phân biệt được, và
            # tính cô lập của từng ca kiểm ngược chỉ còn là lập luận của
            # người viết chứ không phải thứ ca test khẳng định.
            _user_tra_ve = [u for u, _ in cap_chunk]
            _tap_tra_ve = set(_user_tra_ve)
            if len(cap_chunk) != len(chunk):
                _ve_vo = "sai SỐ LƯỢNG"
            elif len(_tap_tra_ve) != len(_user_tra_ve):
                _ve_vo = "trả TRÙNG user_id"
            elif _tap_tra_ve != set(chunk):
                _ve_vo = "sai THÀNH VIÊN"
            else:
                _ve_vo = None
            if _ve_vo is not None:
                raise RuntimeError(
                    "bulk_create %s: trả %d cặp / %d người nhận, %d user_id "
                    "duy nhất; tập trả về %r, tập đã gửi %r — quan hệ chủ "
                    "quyền không dựng được"
                    % (_ve_vo, len(cap_chunk), len(chunk), len(_tap_tra_ve),
                       sorted(_tap_tra_ve), sorted(set(chunk)))
                )
            ket_qua.update(cap_chunk)

            log.debug(
                "Bulk notification insert successful",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(cap_chunk),
                notification_type=notification_type
            )

        except Exception as e:
            log.error(
                "Failed to bulk insert notifications chunk",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(chunk),
                error=str(e),
                notification_type=notification_type,
                strict=strict,
            )
            # 2026-09-02: NÉM RA trong MỌI trường hợp, kể cả non-strict.
            #
            # Trước đây nhánh non-strict gọi ``await db.rollback()`` ngay
            # tại đây. ``Session.rollback()`` cuộn về GỐC chứ không về
            # savepoint, nên nó xoá luôn dữ liệu nghiệp vụ của người gọi —
            # chính docstring của hàm này đã cảnh báo điều đó. Sáu chỗ gọi
            # ``dispatch()`` có bọc ``begin_nested()`` mà không truyền
            # ``strict=True`` đều tin rằng savepoint bảo vệ họ; nó không.
            #
            # Ném ra để ``dispatch`` quyết định — đó là tầng biết ranh giới
            # của MỘT SỰ KIỆN, và là tầng đã mở savepoint bao trọn cả vòng
            # lặp chunk này. Hỏng khi tạo Notification CHA phải huỷ cả pha:
            # ``continue`` ở đây sẽ để chunk trước sống sót thành hàng mồ
            # côi, và đi tiếp với danh sách ID thiếu/lệch so với
            # ``inbox_user_ids``.
            #
            # ⚠️ Savepoint nằm ở TẦNG GỌI, không phải ở repository. Đừng gỡ
            # ``async with db.begin_nested()`` trong ``dispatch`` vì tin rằng
            # repository tự lo — nó không, và đó là cách lỗ hổng tái sinh.
            raise

    log.info(
        "Bulk notification creation completed",
        total_created=len(ket_qua),
        total_recipients=len(user_ids),
        notification_type=notification_type
    )

    return ket_qua


async def _emit_notifications_immediate(
    db: AsyncSession,
    notification_ids: List[int]
):
    """
    Emit Socket.IO notifications immediately for real-time delivery.

    This function sends notifications to connected users via Socket.IO
    without waiting for Celery task processing. This ensures users see
    toast notifications instantly.

    Args:
        db: Database session
        notification_ids: List of notification IDs to emit

    Note:
        This function only handles Socket.IO emission. Email delivery
        is still handled by the Celery task for proper queueing.
    """
    if not notification_ids:
        return

    try:
        from app.socket_manager import sio

        # Fetch notifications from database
        result = await db.execute(
            select(models.Notification)
            .where(models.Notification.id.in_(notification_ids))
        )
        notifications = result.scalars().all()

        if not notifications:
            log.warning(
                "No notifications found for immediate Socket.IO emit",
                requested_ids=notification_ids
            )
            return

        # Emit each notification to the user's Socket.IO room
        emitted_count = 0
        failed_count = 0
        for notification in notifications:
            try:
                room_name = f"user_room_{notification.user_id}"
                await sio.emit(
                    "notification",
                    {
                        "id": notification.id,
                        "type": notification.type,
                        "title": notification.title,
                        "message": notification.message,
                        "link": notification.link,
                        "data": notification.data,
                        "created_at": notification.created_at.isoformat()
                        if notification.created_at else None,
                        "is_read": notification.is_read,
                    },
                    room=room_name
                )
                emitted_count += 1
            except Exception as e:
                failed_count += 1
                log.warning(
                    "Failed to emit notification via Socket.IO",
                    notification_id=notification.id,
                    user_id=notification.user_id,
                    room=room_name,
                    error=str(e)
                )

        log.info(
            "Socket.IO immediate emission completed",
            emitted_count=emitted_count,
            failed_count=failed_count,
            total_notifications=len(notifications)
        )

    except Exception as e:
        log.error(
            "Failed to emit immediate Socket.IO notifications",
            error=str(e),
            notification_count=len(notification_ids)
        )
        raise


def _dispatch_broadcast_task(
    notification_ids: List[int],
    channels: List[str],
    event: str
):
    """
    Dispatch Celery task to broadcast notifications.

    This function queues the notification delivery for async processing.
    Email sending happens in the Celery worker. Socket.IO is sent immediately
    before this task is queued (see _emit_notifications_immediate).

    Args:
        notification_ids: List of notification IDs to broadcast
        channels: List of channels to use (browser, email, sms)
        event: Event name for logging/metrics
    """
    try:
        from app.celery_utils import celery_app

        # Queue the broadcast task
        celery_app.send_task(
            "broadcast_notification_task",
            kwargs={
                "notification_ids": notification_ids,
                "channels": channels,
                "event": event
            },
            queue="notifications"  # Use dedicated queue if available
        )

        log.info(
            "Celery broadcast task queued successfully",
            event_type=event,
            notification_count=len(notification_ids),
            channels=channels,
            queue="notifications"
        )

    except Exception as e:
        log.error(
            "Failed to queue Celery broadcast task",
            event_type=event,
            error=str(e),
            notification_count=len(notification_ids)
        )
        raise


async def _prepend_to_inbox_cache(user_ids: List[int], notification_ids: List[int]):
    """
    ✅ PHASE 1.2: Prepend new notification IDs to user inbox caches.

    This keeps cache warm after creating new notifications, avoiding cache miss
    on next read.

    Strategy:
    - For each user, prepend their notification ID(s) to their inbox cache
    - Trim cache to max 100 items
    - Set TTL to 7 days

    Args:
        user_ids: danh sách user nhận thông báo
        notification_ids: ID tương ứng, ``notification_ids[i]`` thuộc về
            ``user_ids[i]``

    ⚠️ Hàm này ăn hai danh sách SONG SONG THEO VỊ TRÍ, nên nó chỉ đúng khi
    người gọi đã có sẵn quan hệ chủ quyền và giải nén ra hai danh sách từ
    CÙNG một nguồn. Chỗ gọi duy nhất làm đúng thế:
    ``zip(*browser_notif_pairs)`` với ``browser_notif_pairs`` dựng từ
    ``notification_id_map.items()``.

    KHÔNG được truyền vào đây hai danh sách đến từ hai nguồn khác nhau —
    ví dụ ``inbox_user_ids`` cạnh kết quả ``RETURNING`` của một bulk
    INSERT. Thứ tự ``RETURNING`` không có bảo đảm hình thức, và ghép lệch
    ở đây có nghĩa là đẩy ID thông báo của người này vào inbox người kia.
    Phép kiểm độ dài bên dưới KHÔNG bắt được ca ấy: hai danh sách lệch
    nội dung vẫn có thể bằng nhau về độ dài.
    """
    if len(user_ids) != len(notification_ids):
        log.warning(
            "Mismatch between user_ids and notification_ids length, skipping cache prepend",
            user_count=len(user_ids),
            notification_count=len(notification_ids)
        )
        return

    try:
        from app.database import safe_redis_pipeline

        # Use Redis pipeline to batch all operations (E1 fix: N+1 → 1 round-trip)
        PIPELINE_BATCH_SIZE = 500  # Flush pipeline every 500 users to avoid huge buffers
        for batch_start in range(0, len(user_ids), PIPELINE_BATCH_SIZE):
            batch_end = min(batch_start + PIPELINE_BATCH_SIZE, len(user_ids))
            async with safe_redis_pipeline(transaction=False) as pipe:
                for user_id, notification_id in zip(
                    user_ids[batch_start:batch_end],
                    notification_ids[batch_start:batch_end]
                ):
                    cache_key = f"{INBOX_CACHE_KEY_PREFIX}:{user_id}"
                    pipe.lpush(cache_key, str(notification_id))
                    pipe.ltrim(cache_key, 0, INBOX_CACHE_MAX_SIZE - 1)
                    pipe.expire(cache_key, INBOX_CACHE_TTL)
                await pipe.execute()

        log.info(
            "Inbox cache prepend successful (pipelined)",
            user_count=len(user_ids),
            notification_count=len(notification_ids),
            cache_max_size=INBOX_CACHE_MAX_SIZE,
            cache_ttl_seconds=INBOX_CACHE_TTL
        )

    except Exception as e:
        # Log but don't fail - cache prepend is non-critical
        log.warning(
            "Failed to prepend notifications to inbox cache",
            error=str(e),
            user_count=len(user_ids),
            notification_count=len(notification_ids),
            exc_info=True
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def dispatch_to_user(
    db: AsyncSession,
    user_id: int,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    rooms: Optional[List[str]] = None,
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification to a specific user.

    Convenience wrapper that ensures the user_id is in the payload
    for SpecificUsersResolver. Default Socket.IO scope is the target
    user's personal room + admins (``rooms_for_user``) — callers may
    override via ``rooms=`` if the event needs broader/narrower targeting.

    Args:
        db: Database session
        user_id: Target user ID
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key
        rooms: Optional explicit Socket.IO rooms override.

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_id"] = user_id
    effective_rooms = rooms if rooms is not None else rooms_for_user(user_id)
    return await dispatch(db, event, payload, dedupe_key, rooms=effective_rooms)


async def dispatch_to_users(
    db: AsyncSession,
    user_ids: List[int],
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    rooms: Optional[List[str]] = None,
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification to multiple specific users.

    Convenience wrapper that ensures user_ids is in the payload for
    SpecificUsersResolver. Default Socket.IO scope emits to each target
    user's personal room + admins.

    Args:
        db: Database session
        user_ids: Target user IDs
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key
        rooms: Optional explicit Socket.IO rooms override.

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_ids"] = user_ids
    if rooms is None:
        effective_rooms: List[str] = ["role_admin"]
        for uid in user_ids or []:
            if uid is not None:
                effective_rooms.append(f"user_room_{uid}")
    else:
        effective_rooms = rooms
    return await dispatch(db, event, payload, dedupe_key, rooms=effective_rooms)


async def dispatch_system_alert(
    db: AsyncSession,
    severity: str,
    message: str,
    action_url: Optional[str] = None,
    user_ids: Optional[List[int]] = None,
    rooms: Optional[List[str]] = None,
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a system alert to all users or specific users.

    Convenience wrapper for SYSTEM_ALERT event. SYSTEM_ALERT is classified
    as sensitive (see event_catalog): payloads carry severity + targeted
    action URLs that must not leak across unrelated users. When callers
    provide ``user_ids`` the default scope is those users' personal rooms
    plus admins; when targeting all users (``user_ids=None``) the caller
    must pass ``rooms=`` explicitly — otherwise the fail-closed guard in
    ``_emit_domain_event`` blocks the broadcast.

    Args:
        db: Database session
        severity: Alert severity (info, warning, error)
        message: Alert message
        action_url: Optional URL for action
        user_ids: Optional list of specific users (default: all users)
        rooms: Optional explicit Socket.IO rooms override.

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload = {
        "severity": severity,
        "message": message,
        "action_url": action_url or ""
    }

    if user_ids:
        payload["user_ids"] = user_ids

    if rooms is not None:
        effective_rooms: Optional[List[str]] = rooms
    elif user_ids:
        effective_rooms = ["role_admin"] + [f"user_room_{uid}" for uid in user_ids if uid is not None]
    else:
        # All-users alert has no implicit scope — caller must opt in via ``rooms``
        # or flip the event to public in the catalog. Leave None so the
        # fail-closed guard surfaces the misconfiguration.
        effective_rooms = None

    return await dispatch(
        db=db,
        event=SystemEvents.SYSTEM_ALERT,
        payload=payload,
        skip_preference_check=(severity == "error"),  # Don't skip critical alerts
        rooms=effective_rooms,
    )


# ============================================================================
# SAFE DISPATCH — Router-level helper (commit + callback in one call)
# ============================================================================

def log_dispatch_failure(db, exc, *, logger=None, **truong) -> bool:
    """Ghi log một lượt dispatch hỏng — và nói SỰ THẬT về giao dịch.

    Trước 2026-09-02, ba chỗ gọi (``lead_service`` ×2, ``officer_service``)
    đều ghi thẳng ``"Dispatch failed, business data preserved"`` trong khối
    ``except``. Câu ấy được SUY RA từ việc ngoại lệ đã bị bắt, chứ không
    được ĐO. Đã đo bằng SQL echo: ngoại lệ bị bắt nhưng phiên đã chết
    (``PendingRollbackError``), nên ``db.commit()`` của router sau đó đổ và
    dữ liệu nghiệp vụ KHÔNG hề được giữ. Dòng log nói ngược với sự thật.

    ``Session.is_active`` là False đúng khi giao dịch đang ở trạng thái bắt
    buộc phải rollback — tức là câu khẳng định kia sai. Trả về True nếu
    phiên còn dùng được, để người gọi tự quyết nếu cần.

    Đây là MỘT nguồn chuẩn: đừng chép câu log ấy ra chỗ thứ tư.
    """
    _log = logger if logger is not None else log
    try:
        con_dung_duoc = bool(db.sync_session.is_active)
    except Exception:
        con_dung_duoc = False

    if con_dung_duoc:
        _log.warning(
            "Dispatch failed; caller transaction remains active "
            "(business persistence NOT asserted)",
            error=str(exc),
            **truong,
        )
    else:
        _log.error(
            "Dispatch failed; caller transaction requires rollback",
            error=str(exc),
            **truong,
        )
    return con_dung_duoc


async def safe_dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
    rooms: Optional[List[str]] = None,
    only_channels: Optional[List[str]] = None,
) -> List[int]:
    """
    Fire-and-forget dispatch — commits + runs callback + swallows errors.

    USE THIS in **router after-commit blocks** for non-critical notifications
    that must never crash the main request flow. The caller's business data
    must already be committed before calling this.

    DO NOT USE when notification records must be part of the same transaction
    as business data. Use ``dispatch()`` for that pattern instead.

    Contract:
        - Owns its own commit: flushes + commits notification records
        - Runs callback (socket.io, email, worker enqueue)
        - Logs and swallows ALL exceptions — never raises
        - On failure: rolls back to keep session usable for subsequent ops

    Typical usage (router after business commit)::

        await db.commit()                    # business data committed
        await safe_dispatch(db=db, ...)      # notification — best effort

    Args:
        db: Async database session (business data already committed)
        event: The system event to dispatch
        payload: Event payload with data for resolution and templates
        dedupe_key: Optional deduplication key
        skip_preference_check: Skip user preference filtering
        only_channels: Optional whitelist of canonical channels — drop all
            other actions. ``None`` = all channels. Validated before the
            try/except so a typo raises instead of silently dropping.

    Returns:
        List of created notification IDs (empty on failure)

    See also: ``dispatch()`` for the caller-controlled transaction variant.
    """
    # Validate the channel filter BEFORE the try/except below — that block
    # swallows ALL exceptions and returns []. A typo inside dispatch() would
    # be absorbed and silently drop the notification; validating here makes
    # it raise loudly to the caller instead.
    _validate_only_channels(only_channels)
    try:
        notif_ids, notif_cb = await dispatch(
            db=db,
            event=event,
            payload=payload,
            dedupe_key=dedupe_key,
            skip_preference_check=skip_preference_check,
            rooms=rooms,
            only_channels=only_channels,
        )
        await db.commit()
        if notif_cb:
            await notif_cb()
        return notif_ids
    except Exception as e:
        log.warning(
            "Notification dispatch failed (non-critical)",
            event_type=event.value,
            dedupe_key=dedupe_key,
            error=str(e),
        )
        # Rollback to clear session error state (PendingRollbackError)
        # so the caller's session remains usable for subsequent operations.
        try:
            await db.rollback()
        except Exception:
            pass
        return []


# ============================================================================
# DISPATCH EVENT — B2.3 wrapper around outbox + safe_dispatch
# ============================================================================


async def dispatch_event(
    db: AsyncSession,
    *,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    rooms: Optional[List[str]] = None,
) -> Optional[Callable[[], Awaitable[None]]]:
    """B2.3 — single API for the admission notification surface.

    Routes between two paths based on ``EVENT_CATALOG[event]``:

    1. ``requires_outbox=True`` (the 7 critical milestone events from
       B2.1 § PLAN 3.3.d): INSERTs a ``NotificationOutbox`` row in the
       **caller's transaction** and returns ``None``. The Celery beat
       task ``dispatch_pending_outbox`` (T0-4a skeleton today; B2.4 /
       T0-4b ships the real worker body) drains the table out-of-band
       post-commit.

    ``rooms`` (thêm 20-08-2026): danh sách phòng Socket.IO cho sự kiện nhạy
    cảm. Nhánh best-effort chuyển thẳng xuống ``safe_dispatch``; nhánh outbox
    BỎ QUA vì worker tự suy phòng lúc drain (lý do đầy đủ ở thân hàm).

    ⚠️ Không truyền ``rooms`` cho một sự kiện nhạy cảm đi đường best-effort thì
    ``_emit_domain_event`` **bỏ hẳn lượt emit** — fail-closed, im lặng. Đó
    chính là lỗi mọi ``ADMISSION_*`` best-effort qua ``state_transition`` mắc
    phải trước bản vá này.

    2. ``requires_outbox=False`` (the 5 best-effort events): returns a
       post-commit callback that the router awaits **after** ``await
       db.commit()``. The callback delegates to ``safe_dispatch()`` —
       that's the right primitive for "router after-commit, fire-and-
       forget" per the doc on lines 1864-1866.

    Why ``safe_dispatch()`` and not ``dispatch(strict=True)`` in the
    best-effort callback (resolves the doc drift caught during B2.3
    contract verification — see DAILY_LOG entry 2026-05-03):

    - The callback runs **outside** the caller's transaction (post-
      commit). There is no outer business transaction left to protect
      with ``begin_nested()``, so the ``strict=True`` requirement from
      memory ``dispatch-bundle-strict-required`` does not apply.
    - ``safe_dispatch()`` already owns its own commit + swallows errors,
      which is exactly what a post-commit fire-and-forget caller wants.
    - ``ADMISSION_REFACTOR_RISK_REVIEW.md`` PATCH-11 mentions
      ``safe_dispatch(strict=True)`` — that wording is itself drift:
      ``safe_dispatch()`` does not accept a ``strict`` parameter
      (ground-truth signature on lines 1853-1859 above; verified during
      B2.3 implementation). The ground-truth signatures of the two
      primitives govern; aspirational doc notes do not.

    Outbox path uses ``dedupe_key`` as the ``idempotency_key`` column
    on the ``notification_outbox`` table (the DB column keeps the
    canonical end-to-end dedupe-contract noun; the API arg name keeps
    the dispatcher convention). Best-effort path forwards
    ``dedupe_key`` to ``safe_dispatch()`` as-is.

    Args:
        db: Caller's async DB session. Outbox INSERT lands in this
            session's transaction (caller commits). The best-effort
            callback captures this same session and uses it post-commit.
        event: The system event — ``SystemEvents`` enum member, NOT a
            raw string. The catalog is keyed by enum identity.
        payload: Event-specific data — forwarded to the dispatcher /
            stored on the outbox row.
        dedupe_key: End-to-end dedupe key. **Required** for outbox
            events (becomes the row's ``idempotency_key``); forwarded
            as-is for best-effort events.

    Returns:
        ``None`` for outbox events (caller commits, worker dispatches
        later).

        ``Callable[[], Awaitable[None]]`` for best-effort events. The
        router MUST ``await callback()`` after ``await db.commit()``
        (per service / router pattern V3, ``CLAUDE.md`` Rule 5).

    Raises:
        ValueError: If ``event`` is not a key in ``EVENT_CATALOG``
                    (covers unknown events and non-enum inputs — the
                    catalog dict only matches ``SystemEvents`` enum
                    identities), or if ``requires_outbox=True`` but
                    ``dedupe_key`` is missing.

    Service caller pattern (B2.3 wrapper; #16 will wire
    ``state_service.transition()`` through this).

    The example below uses ``<OUTBOX_EVENT>`` and ``<DECISION_KEY>``
    as placeholders so the coverage grep
    (``check_notification_event_coverage.py``) does not pick this
    docstring up as a fake dispatch site. A real call passes a
    concrete ``SystemEvents`` enum member (e.g. one of the seven
    ``requires_outbox=True`` admission events in the B2.1 catalog)::

        notif_callback = await dispatch_event(
            db,
            event=SystemEvents.<OUTBOX_EVENT>,
            payload={"profile_id": profile.id, "choice_priority": 1},
            dedupe_key=f"<DECISION_KEY>:{profile.id}:1",
        )
        # Service body returns (result, post_commit_callback) where
        # post_commit_callback awaits notif_callback if non-None.
    """
    # SystemEvents is ``(str, Enum)`` so a raw string with a matching value
    # would dict-lookup successfully via __hash__/__eq__. That hides bugs
    # downstream (``event.value`` / ``event.name`` access on a string blows
    # up with AttributeError far from the call site). Reject non-enum input
    # at the front door so the contract is enforced positively.
    if not isinstance(event, SystemEvents):
        raise ValueError(
            f"dispatch_event: event must be a SystemEvents enum member; "
            f"got {type(event).__name__} {event!r}. The catalog is keyed "
            "by enum identity even though SystemEvents derives from str."
        )

    event_def = get_event(event)
    if event_def is None:
        raise ValueError(
            f"dispatch_event: event {event.name} is not in EVENT_CATALOG. "
            "Add a catalog entry before calling dispatch_event for this "
            "SystemEvents member."
        )

    if event_def.requires_outbox:
        if dedupe_key is None:
            raise ValueError(
                f"dispatch_event: event {event.name} has requires_outbox=True; "
                "dedupe_key is required (becomes the outbox `idempotency_key`)."
            )
        # ``rooms`` CỐ Ý không đi vào hàng outbox, kể cả khi người gọi truyền.
        #
        # Worker ``dispatch_pending_outbox`` tự suy phòng lúc drain — nó import
        # ``rooms_for_admission`` / ``rooms_for_lead`` / ``rooms_for_user`` và
        # nạp lại thực thể từ DB (``notification_outbox_tasks.py``). Đó là
        # đường đúng: giữa lúc INSERT và lúc drain, hồ sơ có thể được chuyển
        # đơn vị hay đổi officer phụ trách, và một ảnh chụp ``rooms`` nằm trong
        # ``payload`` sẽ phát sự kiện tới **đơn vị cũ** — tức rò dữ liệu sang
        # nhóm không còn quyền xem.
        #
        # Cũng vì thế KHÔNG raise khi có ``rooms``: người gọi ở tầng service
        # không biết (và không nên biết) sự kiện nào ``requires_outbox``, nên
        # truyền ``rooms`` cho MỌI sự kiện là cách gọi đúng. Nhánh này bỏ qua
        # nó có chủ đích, và ``test_outbox_khong_luu_rooms_vao_payload`` khoá
        # điều đó lại.
        db.add(
            models.NotificationOutbox(
                event_code=event.value,
                payload=payload,
                idempotency_key=dedupe_key,
            )
        )
        return None

    # Best-effort path — return a post-commit callback that delegates
    # to safe_dispatch. Capture context via closure so the router can
    # invoke the callback without re-passing args.
    #
    # ``rooms`` đi qua đúng ở đây. Thiếu nó, ``_emit_domain_event`` gặp một sự
    # kiện nhạy cảm không có phòng và **bỏ hẳn lượt emit** (fail-closed khi
    # ``SOCKET_SCOPED_EMIT=True``) — DB vẫn đúng, chỉ realtime im lặng biến mất.
    captured_db = db
    captured_event = event
    captured_payload = payload
    captured_dedupe = dedupe_key
    captured_skip = event_def.bypass_consent_check
    captured_rooms = rooms

    async def post_commit_callback() -> None:
        await safe_dispatch(
            db=captured_db,
            event=captured_event,
            payload=captured_payload,
            dedupe_key=captured_dedupe,
            skip_preference_check=captured_skip,
            rooms=captured_rooms,
        )

    return post_commit_callback
