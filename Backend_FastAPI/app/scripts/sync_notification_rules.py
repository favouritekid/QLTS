"""
Sync notification rules from event catalog to database.

Ensures every ``notification_class="user"`` event has a corresponding
DB rule.  Idempotent — safe to run on every deploy.

Usage:
    python -m app.scripts.sync_notification_rules

Exit codes:
    0 — sync completed, all user events covered
    1 — sync completed but missing_user_rules > 0 (fail-closed)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from typing import Any, Dict

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models
from app.config import settings
from app.core.event_catalog import EVENT_CATALOG, get_notifiable_events
from app.core.events import SystemEvents

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Resolver serialisation — same logic as seed_notification_rules.py
# ---------------------------------------------------------------------------

def _resolver_type_for_default(default_resolver: str) -> Dict[str, Any]:
    """Build minimal recipient_config JSON from catalog default_resolver string."""
    return {"resolver_type": default_resolver, "params": {}}


# ---------------------------------------------------------------------------
# Default template for newly-synced rules (Vietnamese)
# ---------------------------------------------------------------------------

def _get_template(defn) -> tuple:
    """Return (title_template, message_template) for a new DB rule.

    Title: catalog display_name (literal, not placeholder).
    Message: generic Vietnamese description based on category, using only
    variables the event actually declares to avoid unresolved $placeholders.
    """
    title = defn.display_name
    var_names = {v.name for v in defn.variables} if defn.variables else set()

    # Curated templates for specific events that need richer messaging than
    # the generic category fallback. Added in PR A (finance payment event
    # parity): PAYMENT_REJECTED surfaces rejection reason to the maker so
    # they can act on it.
    #
    # REFUND_PROCESSED is intentionally not curated here — it is tagged
    # notification_class="internal_future" because the refund flow has no
    # router endpoint yet. sync_notification_rules only seeds rules for
    # user-class events (via get_notifiable_events), so a curated template
    # here would be unreachable. Restore + promote when the refund router
    # ships.
    if defn.event == SystemEvents.PAYMENT_REJECTED:
        return (
            "Thanh toán bị từ chối",
            "Khoản thanh toán $amount đã bị từ chối. Lý do: $rejection_reason",
        )
    if defn.event == SystemEvents.FEE_FULLY_PAID:
        return (
            "Học phí thanh toán đủ",
            "Học phí kỳ $semester_no với số tiền $amount đã được thanh toán đầy đủ.",
        )
    if defn.event == SystemEvents.INVOICE_ISSUED:
        return (
            "Hóa đơn được phát hành",
            "Hóa đơn $invoice_number với số tiền $amount đã phát hành. Hạn: $due_date.",
        )
    if defn.event == SystemEvents.PAYMENT_OVERDUE:
        return (
            "Thanh toán quá hạn",
            "Hóa đơn $invoice_number với số tiền $amount đã quá hạn $days_overdue ngày.",
        )
    if defn.event == SystemEvents.APPLICATION_FEE_PAID:
        return (
            "Lệ phí xét tuyển đã thanh toán",
            "Hồ sơ #$application_id đã thanh toán lệ phí xét tuyển $amount.",
        )

    # Build message from available variables — safe fallback per category
    cat = defn.category
    if cat == "lead" and "lead_id" in var_names:
        msg = "Có hoạt động mới liên quan đến lead #$lead_id."
    elif cat == "consultation" and "consultation_id" in var_names:
        msg = "Có hoạt động mới liên quan đến tư vấn #$consultation_id."
    elif cat == "application" and "application_id" in var_names:
        msg = "Có hoạt động mới liên quan đến hồ sơ #$application_id."
    elif cat == "system" and "message" in var_names:
        msg = "$message"
    elif cat == "security":
        msg = "Phát hiện hoạt động bảo mật đáng ngờ."
    elif cat == "ctv" and "collaborator_id" in var_names:
        msg = "Có hoạt động CTV mới."
    elif cat == "finance":
        msg = "Có hoạt động tài chính mới."
    elif cat == "pipeline":
        msg = "Cấu hình pipeline đã thay đổi."
    else:
        # Generic fallback — always safe
        msg = defn.description or "Thông báo mới."

    return (title, msg)


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

async def sync_notification_rules(db) -> Dict[str, int]:
    """
    Sync catalog → DB rules.

    For each ``notification_class="user"`` event:
      - If DB rule exists → skip
      - If DB rule missing → create with catalog defaults

    Returns dict: {created, skipped, orphan_rules, missing_user_rules}
    """
    notifiable = get_notifiable_events()
    notifiable_keys = {d.event.value for d in notifiable}

    # Existing rules in DB
    result = await db.execute(select(models.NotificationRule.event))
    existing_events = {row[0] for row in result.fetchall()}

    created = 0
    skipped = 0

    for defn in notifiable:
        event_key = defn.event.value
        if event_key in existing_events:
            skipped += 1
            continue

        title_tpl, msg_tpl = _get_template(defn)
        # Wave 4b (2026-04-21): the legacy `channels` compat column was
        # dropped; runtime channels are derived from per-action rows.
        rule = models.NotificationRule(
            event=event_key,
            title_template=title_tpl,
            message_template=msg_tpl,
            notification_type="info",
            link_template=None,  # PR2: link is code-owned (catalog), not DB-stored
            recipient_config=_resolver_type_for_default(defn.default_resolver),
            condition=None,
            enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(rule)
        await db.flush()  # need rule.id for actions

        # Wave 4b: seed default actions from catalog channels (the legacy
        # synthesize-from-`channels` fallback in the loader is gone, so
        # rules without action rows would dispatch nothing). Each
        # default channel becomes one inherit_default action; admins can
        # customize the workflow afterwards via the rule editor.
        for step, channel in enumerate(defn.default_channels, start=1):
            db.add(models.NotificationAction(
                rule_id=rule.id,
                step=step,
                channel=str(channel),
                content_mode="inherit_default",
            ))

        created += 1
        log.info(
            "Created notification rule",
            event_type=event_key,
            seeded_actions=[str(c) for c in defn.default_channels],
        )

    await db.commit()

    # Wave 4b (2026-04-21) — safety-net action backfill.
    # After dropping the `channels` compat column, any enabled rule
    # that lacks `NotificationAction` rows dispatches zero
    # notifications (the loader's synthesize-from-channels fallback
    # is gone). The Alembic migration does a one-shot backfill from
    # the compat column right before dropping it, but we repeat the
    # work here using catalog `default_channels` to cover:
    #   - dev DBs that had the earlier drop-only migration applied
    #   - rules that somehow end up without actions in the future
    # Idempotent: only touches rules that currently have zero actions.
    action_backfilled = await _backfill_missing_actions(db)

    # Re-check: any user event still missing?
    result2 = await db.execute(select(models.NotificationRule.event))
    after_events = {row[0] for row in result2.fetchall()}
    missing_user_rules = len(notifiable_keys - after_events)

    # Orphan rules = DB rules for events not in catalog at all
    all_catalog_keys = {ev.value for ev in EVENT_CATALOG}
    orphan_rules = len(existing_events - all_catalog_keys)

    summary = {
        "created": created,
        "skipped": skipped,
        "rules_backfilled": action_backfilled,
        "orphan_rules": orphan_rules,
        "missing_user_rules": missing_user_rules,
    }

    if orphan_rules > 0:
        log.warning("Orphan DB rules found (events not in catalog)", count=orphan_rules)
    if missing_user_rules > 0:
        log.error("User events still missing DB rules after sync!", count=missing_user_rules)

    log.info("Notification rules sync completed", **summary)
    return summary


async def _backfill_missing_actions(db) -> int:
    """Seed default NotificationAction rows for enabled rules that have none.

    Uses catalog `default_channels` for the event. Skips rules whose
    event is not in the catalog (orphan rules) or whose catalog entry
    has no default channels — those cannot be safely synthesized.

    After the DB backfill, invalidates the per-event rule cache so any
    environment that had cached an actionless rule under the buggy
    pre-backfill release (e.g. during the f3582513 window) picks up
    the freshly-seeded actions on next dispatch instead of serving the
    stale cache entry.
    """
    from app.services.notification_rule_loader import invalidate_rule_cache

    stmt = (
        select(models.NotificationRule)
        .outerjoin(
            models.NotificationAction,
            models.NotificationAction.rule_id == models.NotificationRule.id,
        )
        .where(models.NotificationRule.enabled == True)  # noqa: E712
        .group_by(models.NotificationRule.id)
        .having(func.count(models.NotificationAction.id) == 0)
    )
    result = await db.execute(stmt)
    orphan_rules = result.scalars().all()

    if not orphan_rules:
        return 0

    seeded_event_names: list[str] = []
    for rule in orphan_rules:
        try:
            event_enum = SystemEvents(rule.event)
        except ValueError:
            log.warning(
                "Cannot backfill actions: unknown event",
                rule_id=rule.id,
                event_name=rule.event,
            )
            continue
        defn = EVENT_CATALOG.get(event_enum)
        if defn is None or not defn.default_channels:
            log.warning(
                "Cannot backfill actions: no catalog default_channels",
                rule_id=rule.id,
                event_name=rule.event,
            )
            continue
        for step, channel in enumerate(defn.default_channels, start=1):
            db.add(models.NotificationAction(
                rule_id=rule.id,
                step=step,
                channel=str(channel),
                content_mode="inherit_default",
            ))
        seeded_event_names.append(rule.event)
        log.info(
            "Backfilled default actions for orphan rule",
            rule_id=rule.id,
            event_name=rule.event,
            seeded_channels=[str(c) for c in defn.default_channels],
        )

    if not seeded_event_names:
        return 0

    await db.commit()

    # Invalidate cache for every backfilled event so dispatchers that
    # cached the actionless rule re-read from DB on next call.
    for event_name in seeded_event_names:
        try:
            await invalidate_rule_cache(event_name)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Failed to invalidate rule cache after backfill",
                event_name=event_name,
                error=str(exc),
            )

    return len(seeded_event_names)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as db:
        result = await sync_notification_rules(db)
        print(f"Sync result: {result}")

    await engine.dispose()

    if result.get("missing_user_rules", 0) > 0:
        print(f"ERROR: {result['missing_user_rules']} user events still missing rules")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
