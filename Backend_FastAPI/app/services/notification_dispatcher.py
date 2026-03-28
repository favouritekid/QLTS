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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# from sqlalchemy import and_, cast, insert, select, String (removed - using repository)
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group, NotificationChannel
from app.database import (
    safe_redis_lpush, safe_redis_ltrim, safe_redis_expire,
    safe_redis_exists, safe_redis_set, safe_redis_incr,
)
from app.services.notification_registry import get_event_config, NotificationConfig
from app.services import notification_preference_service
from app.repositories import NotificationRepository, NotificationTemplateRepository
# ✅ PHASE 2.3: Import database rule loader
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
    link = Template(template.link_template).safe_substitute(payload) if template.link_template else fallback_snapshot.get("link")

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
    ("lead_id", "lead"),
    ("profile_id", "admission_profile"),
    ("admission_profile_id", "admission_profile"),
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
) -> None:
    """
    ✅ REAL-TIME SYNC: Emit domain event via Socket.IO for instant UI refresh.
    
    This broadcasts to ALL connected clients, enabling real-time data sync:
    - Frontend receives event (e.g., "lead_created")
    - React Query invalidates relevant queries
    - UI automatically refetches fresh data
    
    Race condition prevention:
    - Includes timestamp for event ordering
    - Includes event_id for deduplication
    - Only called AFTER transaction commit (data is persisted)
    
    Args:
        event: SystemEvents enum (e.g., LEAD_CREATED, CONSULTATION_UPDATED)
        payload: Event payload to send to clients
    """
    from app.socket_manager import sio
    
    try:
        # Create event data with timestamp for race condition handling
        event_data = {
            **payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": f"{event.value}:{payload.get('lead_id', payload.get('consultation_id', 'unknown'))}:{int(datetime.now().timestamp() * 1000)}",
        }
        
        # Broadcast to all connected clients
        await sio.emit(event.value, event_data)
        
        log.info(
            "Domain event broadcast",
            event_type=event.value,
            payload_keys=list(payload.keys())
        )
    except Exception as e:
        # Non-critical failure - log warning but don't raise
        log.warning(
            "Failed to emit domain event (non-critical)",
            event_type=event.value,
            error=str(e)
        )


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
                event=event,
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


async def dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification event.

    This is the main entry point for the event-driven notification system.
    It handles the complete flow from event to notification delivery.

    Args:
        db: Async database session
        event: The system event to dispatch
        payload: Event payload with data for resolution and templates.
                 Caller is responsible for sanitizing user-facing values.
                 Template rendering uses string.Template.safe_substitute()
                 which leaves unresolved $placeholders as-is (safe).
        dedupe_key: Optional key for deduplication (e.g., "lead_assigned:123:456")
                   If provided, prevents duplicate notifications for same key+user
        skip_preference_check: If True, skip user preference filtering
                              Use for critical system notifications

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().

    Flow:
        1. Lookup event config from registry
        2. Resolve recipients using configured resolver
        3. Filter recipients by preferences (unless skipped)
        4. Apply deduplication logic
        5. Bulk insert notifications
        6. Flush (caller commits)
        7. Return post-commit callback for channel delivery

    Example:
        notification_ids, callback = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={
                "lead_id": 123,
                "officer_id": 456,
                "lead_name": "John Doe",
                "actor_id": 789
            },
            dedupe_key="lead_assigned:123:456"
        )
        await db.commit()
        if callback:
            await callback()
    """
    log.info(
        "Dispatching notification event",
        event_type=event.value,
        dedupe_key=dedupe_key,
        payload_keys=list(payload.keys())
    )

    # Step 1: ✅ PHASE 2.3: Load rule from database (or fallback to hardcoded registry)
    # Try database first for visual management
    config = await get_rule_for_event(db, event)
    rule_source = "database" if config else None

    # Fallback to hardcoded registry if no database rule
    if not config:
        config = get_event_config(event)
        rule_source = "registry" if config else None

    if not config:
        log.warning(
            "No notification rule found for event (still emitting domain event for UI sync)",
            event_type=event.value,
            checked_sources=["database", "registry"]
        )
        # ✅ IMPORTANT: Still emit domain event for real-time UI refresh
        # Notification rules are for per-user notifications
        # Domain events are for broadcasting data changes to ALL clients
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)

        return [], _domain_only_callback

    log.info(
        "Loaded notification rule",
        event_type=event.value,
        rule_source=rule_source,
        rule_id=getattr(config, 'rule_id', None),
        channels=config.channel_values
    )

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
                await _emit_domain_event(event, payload)
            return [], _domain_only_callback

    # Step 2: Resolve recipients
    try:
        user_ids = await config.resolver.resolve_users(db, payload)
    except Exception as e:
        log.error(
            "Failed to resolve users for event (still emitting domain event)",
            event_type=event.value,
            error=str(e),
            resolver=config.resolver.__class__.__name__
        )
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)
        return [], _domain_only_callback

    if not user_ids:
        log.info("No recipients resolved for event (still emitting domain event)", event_type=event.value)
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)
        return [], _domain_only_callback

    log.info(
        "Recipients resolved successfully",
        event_type=event.value,
        recipient_count=len(user_ids)
    )

    # Step 3: Per-action preference filtering (Phase C0: actions are runtime truth)
    # Build a dict of {channel: [user_ids]} so each action/channel gets its own recipient list.
    # Inbox Notification rows are created for users who have browser enabled.
    group = get_event_group(event)
    channel_recipient_map: Dict[str, List[int]] = {}

    # Use actions (runtime truth) to determine channels
    action_configs = config.actions  # List[ActionConfig]

    if skip_preference_check:
        for action in action_configs:
            channel_recipient_map[action.channel] = list(user_ids)
    else:
        for action in action_configs:
            if action.channel not in channel_recipient_map:
                filtered = await notification_preference_service.filter_users_by_group(
                    db=db,
                    user_ids=user_ids,
                    group=group.value,
                    channel=action.channel,
                )
                channel_recipient_map[action.channel] = filtered

    # Step 3.5: Cooldown + Rate limit (Phase C2)
    from app.config import settings as _settings

    for ch in list(channel_recipient_map.keys()):
        cooled = []
        for uid in channel_recipient_map[ch]:
            # Cooldown: skip if same event+user+channel sent recently
            cooldown_key = f"notif:cooldown:{event.value}:{uid}:{ch}"
            if await safe_redis_exists(cooldown_key):
                continue

            # Rate limit: skip if user exceeded per-hour cap
            rate_key = f"notif:rate:{uid}"
            count = await safe_redis_incr(rate_key)
            if count == 1:
                await safe_redis_expire(rate_key, 3600)
            if count and count > _settings.NOTIFICATION_RATE_LIMIT_PER_HOUR:
                log.debug("Rate limited", user_id=uid, count=count)
                continue

            cooled.append(uid)
            # Set cooldown after passing all checks
            await safe_redis_set(
                cooldown_key, "1", ex=_settings.NOTIFICATION_COOLDOWN_SECONDS,
            )
        channel_recipient_map[ch] = cooled

    # Phase C1: Inbox Notification rows are ONLY for browser recipients.
    # Non-browser channels (email, zalo, sms) use payload_snapshot via worker —
    # they do NOT depend on Notification rows.
    inbox_user_ids = sorted(set(channel_recipient_map.get("browser", [])))

    # All recipients across all channels (for short-circuit check)
    all_recipients = set()
    for ids in channel_recipient_map.values():
        all_recipients.update(ids)

    if not all_recipients:
        log.info(
            "All recipients filtered out by per-channel preferences (still emitting domain event)",
            event_type=event.value,
            group=group.value
        )
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)
        return [], _domain_only_callback

    log.info(
        "Recipients after per-channel preference filtering",
        event_type=event.value,
        channel_counts={ch: len(ids) for ch, ids in channel_recipient_map.items()},
    )

    # Step 4: Apply deduplication to each channel + inbox
    if dedupe_key:
        # Dedup each channel's recipient list
        for ch in channel_recipient_map:
            channel_recipient_map[ch] = await _apply_deduplication(
                db, channel_recipient_map[ch], dedupe_key
            )

        # Re-derive inbox from deduped browser list
        original_inbox_count = len(inbox_user_ids)
        inbox_user_ids = sorted(set(channel_recipient_map.get("browser", [])))

        # Re-check all recipients
        all_recipients = set()
        for ids in channel_recipient_map.values():
            all_recipients.update(ids)

        if not all_recipients:
            log.info(
                "All recipients filtered out by deduplication (still emitting domain event)",
                event_type=event.value,
                dedupe_key=dedupe_key
            )
            async def _domain_only_callback():
                await _emit_domain_event(event, payload)
            return [], _domain_only_callback

        log.info(
            "Recipients after deduplication",
            event_type=event.value,
            original_inbox_count=original_inbox_count,
            deduplicated_inbox_count=len(inbox_user_ids),
        )

    # Step 5: Render notification content
    title = config.render_title(payload)
    message = config.render_message(payload)
    link = config.render_link(payload)

    # Determine notification type (can be overridden by payload for alerts)
    notification_type = payload.get("severity", config.notification_type)

    # Build data payload for notification (exclude large fields)
    notification_data = {
        "event": event.value,
        "group": config.group.value,
        **{k: v for k, v in payload.items() if k not in ["message", "description"]}
    }
    if dedupe_key:
        notification_data["dedupe_key"] = dedupe_key

    # Step 6: Bulk insert inbox Notification rows (for browser-eligible users only)
    notification_ids = []
    if inbox_user_ids:
        notification_ids = await _bulk_create_notifications(
            db=db,
            user_ids=inbox_user_ids,
            title=title,
            message=message,
            notification_type=notification_type,
            link=link,
            data=notification_data
        )

    # Phase C1: notification_ids can be empty (no browser recipients) while
    # other channels still have recipients. Only short-circuit if truly nothing.
    if not notification_ids and not any(channel_recipient_map.values()):
        log.error(
            "Failed to create notifications and no channel recipients for event",
            event_type=event.value
        )
        async def _empty_callback():
            pass
        return [], _empty_callback

    # Step 6.5: Create NotificationDelivery rows for tracking (Phase C0: action-based)
    from app.services import notification_delivery_service
    notification_id_map = dict(zip(inbox_user_ids, notification_ids)) if notification_ids else {}

    # Extract source context from payload for delivery tracking
    _source_type, _source_id = _extract_source_from_payload(event, payload)

    # Build action maps: {channel -> step/template/delay/config} from actions
    _channel_step_map = {a.channel: a.step for a in action_configs}
    _channel_template_map = {a.channel: a.template_code for a in action_configs}
    _action_delay_map = {a.channel: a.delay_minutes for a in action_configs}
    _action_config_map = {a.channel: a.config for a in action_configs if a.config}

    # Phase C1/G2: Build per-channel payload snapshot.
    # Base snapshot has rendered content. Channel-specific config (e.g. zalo_template_id)
    # is merged from ActionConfig.config so the worker has everything it needs.
    _base_snapshot = {
        "title": title,
        "message": message,
        "link": link,
        "type": notification_type,
    }

    # Phase E2: Pre-fetch templates referenced by action template_code
    _action_template_map = await _resolve_action_templates(db, action_configs)

    _channel_snapshot_map: Dict[str, dict] = {}
    for ch in channel_recipient_map:
        # Phase E2: If the action for this channel has a template_code that
        # resolved to a real template, render from that template instead of
        # the rule-level defaults.
        tpl_code = _channel_template_map.get(ch)
        tpl_obj = _action_template_map.get(tpl_code) if tpl_code else None

        if tpl_obj:
            ch_snapshot = _render_template_snapshot(tpl_obj, payload, _base_snapshot)
            log.debug(
                "Using per-action template for channel snapshot",
                channel=ch,
                template_code=tpl_code,
            )
        else:
            ch_snapshot = dict(_base_snapshot)
            # M7: Log when action has template_code but template not found/resolved
            if tpl_code:
                log.warning(
                    "Action template_code set but template not resolved — using rule defaults",
                    channel=ch,
                    template_code=tpl_code,
                    event=event.value,
                )

        ch_config = _action_config_map.get(ch)
        if ch_config:
            # Merge channel config into snapshot, rendering placeholders in template_data
            merged = {**ch_snapshot, **ch_config}
            # P1: Render {placeholder} values inside zalo_template_data from payload
            merged = _render_channel_config_placeholders(merged, payload)
            _channel_snapshot_map[ch] = merged
        else:
            _channel_snapshot_map[ch] = ch_snapshot

    try:
        channel_delivery_ids = await notification_delivery_service.create_deliveries_for_dispatch(
            db=db,
            event=event.value,
            channel_recipient_map=channel_recipient_map,
            notification_id_map=notification_id_map,
            dedupe_key=dedupe_key,
            payload_snapshot=_base_snapshot,
            channel_snapshot_map=_channel_snapshot_map,
            source_type=_source_type,
            source_id=_source_id,
            rule_id=config.rule_id if hasattr(config, 'rule_id') else None,
            channel_step_map=_channel_step_map,
            channel_template_map=_channel_template_map,
            action_delay_map=_action_delay_map,
        )
    except Exception as e:
        log.error(
            "Failed to create delivery records (non-critical)",
            event_type=event.value,
            error=str(e),
        )
        channel_delivery_ids = {}
        try:
            await db.rollback()
        except Exception:
            pass

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
                    event=event.value,
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
            # (e.g. collaborator with linked user_id), create an internal
            # delivery row instead of an external one.
            if recipient.recipient_kind == "internal" and recipient.user_id:
                ch = action.channel
                ch_snapshot = _channel_snapshot_map.get(ch, _base_snapshot)
                delay_minutes = _action_delay_map.get(ch, 0)
                int_scheduled_for = None
                if delay_minutes > 0:
                    from datetime import timedelta
                    int_scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

                from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
                repo = NotificationDeliveryRepository(db)
                fallback_ids = await repo.bulk_create_deliveries([{
                    "notification_id": notification_id_map.get(recipient.user_id),
                    "event": event.value,
                    "channel": ch,
                    "recipient_kind": "internal",
                    "user_id": recipient.user_id,
                    "source_type": recipient.source_type,
                    "source_id": recipient.source_id,
                    "status": "queued",
                    "dedupe_key": dedupe_key,
                    "payload_snapshot": ch_snapshot,
                    "rule_id": config.rule_id if hasattr(config, 'rule_id') else None,
                    "action_step": _channel_step_map.get(ch),
                    "template_code": _channel_template_map.get(ch),
                    "scheduled_for": int_scheduled_for,
                }])
                if fallback_ids:
                    channel_delivery_ids.setdefault(ch, []).extend(fallback_ids)
                log.info(
                    "External resolver returned internal user, created internal delivery",
                    event_type=event.value,
                    channel=ch,
                    user_id=recipient.user_id,
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

            ch_snapshot = _channel_snapshot_map.get(action.channel, _base_snapshot)
            delay_minutes = _action_delay_map.get(action.channel, 0)
            ext_scheduled_for = None
            if delay_minutes > 0:
                from datetime import timedelta
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
                dedupe_key=dedupe_key,
                payload_snapshot=ch_snapshot,
                rule_id=config.rule_id if hasattr(config, 'rule_id') else None,
                action_step=_channel_step_map.get(action.channel),
                template_code=_channel_template_map.get(action.channel),
                scheduled_for=ext_scheduled_for,
            )
            if ext_ids:
                _external_delivery_ids.setdefault(action.channel, []).extend(ext_ids)
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
            )

    # Merge external delivery IDs into channel_delivery_ids for worker enqueueing
    for ch, ext_ids in _external_delivery_ids.items():
        channel_delivery_ids.setdefault(ch, []).extend(ext_ids)

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

        # Step 7.25: ✅ REAL-TIME SYNC: Emit domain event for UI refresh
        await _emit_domain_event(event, payload)

        # Step 7.5: ✅ PHASE 1.2: Prepend new notifications to inbox cache
        # Only cache for browser-eligible users (bell icon / dropdown).
        # notification_ids[i] matches inbox_user_ids[i], so filter both lists
        # to only browser-eligible users.
        browser_set = set(channel_recipient_map.get("browser", []))
        if notification_ids and browser_set:
            browser_notif_pairs = [
                (uid, nid)
                for uid, nid in zip(inbox_user_ids, notification_ids)
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

            if browser_recipients and notification_ids:
                notifications = []
                repo = NotificationRepository(db)
                notifications = await repo.get_by_ids(notification_ids)

                ch_name, ch_result, error_msg = await _send_via_channel(
                    channel_name="browser",
                    notifications=notifications,
                    recipient_ids=browser_recipients,
                    context=payload,
                    event=event.value,
                )

                # Update browser delivery statuses
                if browser_del_ids:
                    if ch_result is None and error_msg is None:
                        await notification_delivery_service.mark_delivery_ids_skipped(
                            db, browser_del_ids,
                            error_reason="channel_not_implemented",
                        )
                    elif error_msg:
                        await notification_delivery_service.mark_delivery_ids_failed(
                            db, browser_del_ids, error_reason=error_msg,
                        )
                    elif ch_result:
                        uid_to_did = dict(zip(browser_recipients, browser_del_ids))
                        sent_ids = [
                            uid_to_did[uid]
                            for uid in browser_recipients
                            if uid not in ch_result.failed_ids and uid in uid_to_did
                        ]
                        if sent_ids:
                            await notification_delivery_service.mark_delivery_ids_sent(
                                db, sent_ids,
                            )
                        failed_ids = [
                            uid_to_did[uid]
                            for uid in ch_result.failed_ids
                            if uid in uid_to_did
                        ]
                        if failed_ids:
                            await notification_delivery_service.mark_delivery_ids_failed(
                                db, failed_ids,
                                error_reason=ch_result.error_message or "delivery_failed",
                            )

                await db.commit()

        except Exception as e:
            log.error(
                "Browser inline delivery failed",
                event_type=event.value,
                error=str(e),
                fallback="Browser notifications failed but inbox rows are in DB",
            )

        # Step 8b: Non-browser channels — enqueue to Celery worker
        try:
            from app.tasks.delivery_tasks import execute_notification_delivery

            worker_enqueued = 0
            for channel_name, del_ids in channel_delivery_ids.items():
                if channel_name == "browser":
                    continue  # Already handled inline
                if not del_ids:
                    continue

                delay_minutes = _action_delay_map.get(channel_name, 0)
                countdown = delay_minutes * 60  # 0 for immediate

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
                    channels=[
                        ch for ch in channel_delivery_ids
                        if ch != "browser" and channel_delivery_ids[ch]
                    ],
                )

        except Exception as e:
            log.error(
                "Failed to enqueue worker deliveries (non-critical)",
                event_type=event.value,
                error=str(e),
                fallback="Delivery rows are in DB as queued, can be retried",
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
    data: dict
) -> List[int]:
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

    Returns:
        List of created notification IDs
    """
    notification_ids = []
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
            chunk_ids = await repo.bulk_create(values)
            notification_ids.extend(chunk_ids)

            log.debug(
                "Bulk notification insert successful",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(chunk_ids),
                notification_type=notification_type
            )

        except Exception as e:
            log.error(
                "Failed to bulk insert notifications chunk",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(chunk),
                error=str(e),
                notification_type=notification_type
            )
            # Rollback to clear session error state so subsequent
            # operations (delivery tracking, other chunks) can proceed.
            try:
                await db.rollback()
            except Exception:
                pass
            # Continue with other chunks

    log.info(
        "Bulk notification creation completed",
        total_created=len(notification_ids),
        total_recipients=len(user_ids),
        notification_type=notification_type
    )

    return notification_ids


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
            event=event,
            notification_count=len(notification_ids),
            channels=channels,
            queue="notifications"
        )

    except Exception as e:
        log.error(
            "Failed to queue Celery broadcast task",
            event=event,
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
        user_ids: List of user IDs who received notifications
        notification_ids: List of notification IDs that were created (in same order as user_ids)

    Note:
        Bulk notifications create one notification per user in same order as user_ids list.
        We prepend notification_ids[i] to cache for user_ids[i].
    """
    if len(user_ids) != len(notification_ids):
        log.warning(
            "Mismatch between user_ids and notification_ids length, skipping cache prepend",
            user_count=len(user_ids),
            notification_count=len(notification_ids)
        )
        return

    try:
        # Prepend each notification to the corresponding user's inbox cache
        for user_id, notification_id in zip(user_ids, notification_ids):
            cache_key = f"{INBOX_CACHE_KEY_PREFIX}:{user_id}"

            # LPUSH to prepend notification ID to front of list
            await safe_redis_lpush(cache_key, str(notification_id))

            # LTRIM to keep only first 100 items
            await safe_redis_ltrim(cache_key, 0, INBOX_CACHE_MAX_SIZE - 1)

            # Set/refresh TTL
            await safe_redis_expire(cache_key, INBOX_CACHE_TTL)

        log.info(
            "Inbox cache prepend successful",
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
    dedupe_key: Optional[str] = None
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification to a specific user.

    Convenience wrapper that ensures the user_id is in the payload
    for SpecificUsersResolver.

    Args:
        db: Database session
        user_id: Target user ID
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_id"] = user_id
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_to_users(
    db: AsyncSession,
    user_ids: List[int],
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a notification to multiple specific users.

    Convenience wrapper that ensures user_ids is in the payload
    for SpecificUsersResolver.

    Args:
        db: Database session
        user_ids: Target user IDs
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key

    Returns:
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_ids"] = user_ids
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_system_alert(
    db: AsyncSession,
    severity: str,
    message: str,
    action_url: Optional[str] = None,
    user_ids: Optional[List[int]] = None
) -> Tuple[List[int], Optional[Callable]]:
    """
    Dispatch a system alert to all users or specific users.

    Convenience wrapper for SYSTEM_ALERT event.

    Args:
        db: Database session
        severity: Alert severity (info, warning, error)
        message: Alert message
        action_url: Optional URL for action
        user_ids: Optional list of specific users (default: all users)

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

    return await dispatch(
        db=db,
        event=SystemEvents.SYSTEM_ALERT,
        payload=payload,
        skip_preference_check=(severity == "error")  # Don't skip critical alerts
    )


# ============================================================================
# SAFE DISPATCH — Router-level helper (commit + callback in one call)
# ============================================================================

async def safe_dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
) -> List[int]:
    """
    Dispatch + commit + callback in one call. Use in router layer only.

    Wraps the full dispatch pattern: tuple unpacking, db.commit() for
    notification records, and callback execution (socket.io/email delivery).
    Errors are logged but never raised — notifications are non-critical.

    Args:
        db: Async database session (transaction should already be committed
            for main business data before calling this)
        event: The system event to dispatch
        payload: Event payload with data for resolution and templates
        dedupe_key: Optional deduplication key
        skip_preference_check: Skip user preference filtering

    Returns:
        List of created notification IDs (empty on failure)
    """
    try:
        notif_ids, notif_cb = await dispatch(
            db=db,
            event=event,
            payload=payload,
            dedupe_key=dedupe_key,
            skip_preference_check=skip_preference_check,
        )
        await db.commit()
        if notif_cb:
            await notif_cb()
        return notif_ids
    except Exception as e:
        log.warning(
            "Notification dispatch failed (non-critical)",
            event=event.value,
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
