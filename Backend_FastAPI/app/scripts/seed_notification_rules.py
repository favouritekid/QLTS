"""
Seed default notification rules for the notification_rule table.

Catalog-driven since Wave 1 (2026-04-21): data sources are
 - `app.core.event_catalog.EVENT_CATALOG` for `channels` + `link_template`
   (via `default_channels` + `link_strategy`)
 - `app.core.notification_seed_defaults.NOTIFICATION_SEED_DEFAULTS` for
   `title_template`, `message_template`, `notification_type`, and the
   pre-serialized `recipient_config` (preserves composite / actor_excluded
   resolver shapes that catalog's single-string `default_resolver` cannot
   round-trip).

The script remains insert-only — if a rule already exists for an event
(matched by `event` column), it is skipped and not overwritten. This
preserves admin-UI customizations made after initial seed (e.g. the
Zalo action enrichment on `consultation_reminder` in prod).

Usage:
    python -m app.scripts.seed_notification_rules

Requirements:
    - notification_rule table exists (migration k6l7m8n9o0p1 or later)
    - Run once after the migration, or any time to add rules for
      newly-introduced events.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models
from app.config import settings
from app.core.event_catalog import EVENT_CATALOG
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS

log = structlog.get_logger(__name__)


async def seed_notification_rules():
    """
    Seed notification_rule table with default configurations.
    """
    log.info("Starting notification rules seeding process")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(models.NotificationRule.event))
        existing_events = {row[0] for row in result.fetchall()}

        log.info("Found existing rules", count=len(existing_events))

        created_count = 0
        skipped_count = 0

        for event, defaults in NOTIFICATION_SEED_DEFAULTS.items():
            event_name = event.value

            if event_name in existing_events:
                log.debug("Skipping existing rule", event_name=event_name)
                skipped_count += 1
                continue

            catalog_entry = EVENT_CATALOG.get(event)
            if catalog_entry is None:
                log.error(
                    "Missing catalog entry for seeded event, skipping",
                    event_name=event_name,
                )
                continue

            link_template = catalog_entry.link_strategy

            # Wave 4b (2026-04-21): the legacy `channels` compat column was
            # dropped; runtime channels are derived from per-action rows
            # (this script does not seed actions; call sites that need
            # per-action delivery should use sync_notification_rules.py).
            rule = models.NotificationRule(
                event=event_name,
                title_template=defaults["title_template"],
                message_template=defaults["message_template"],
                notification_type=defaults["notification_type"],
                link_template=link_template,
                recipient_config=defaults["recipient_config"],
                condition=None,
                enabled=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            session.add(rule)
            created_count += 1

            log.info(
                "Created notification rule",
                event_name=event_name,
                resolver_type=defaults["recipient_config"]["resolver_type"],
                catalog_default_channels=[str(ch) for ch in catalog_entry.default_channels],
            )

        await session.commit()

        log.info(
            "Notification rules seeding completed",
            created=created_count,
            skipped=skipped_count,
            total=len(NOTIFICATION_SEED_DEFAULTS),
        )

    await engine.dispose()


if __name__ == "__main__":
    """Run seeding script."""
    asyncio.run(seed_notification_rules())
