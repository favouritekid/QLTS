"""
✅ PHASE 2.1: Seed default notification rules from existing registry.

This script populates the notification_rule table with default configurations
based on the hardcoded NOTIFICATION_REGISTRY. This allows administrators to
manage these rules via UI going forward.

Usage:
    python -m app.scripts.seed_notification_rules

Requirements:
    - Database must have notification_rule table (migration k6l7m8n9o0p1)
    - Run this script once after migration

Process:
    1. Read all events from NOTIFICATION_REGISTRY
    2. Convert each NotificationConfig to database format
    3. Serialize resolver configuration to JSON
    4. Insert into notification_rule table
    5. Skip if rule already exists for event
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models
from app.config import settings
from app.core.events import SystemEvents
from app.services.notification_registry import NOTIFICATION_REGISTRY
from app.services.notification_resolvers import (
    ActorExcludedResolver,
    AllAdminsResolver,
    AllUsersResolver,
    BaseResolver,
    CompositeResolver,
    DormResidentsResolver,
    DormStaffResolver,
    LeadOwnerResolver,
    SpecificUsersResolver,
    UnitManagersResolver,
    UnitStaffResolver,
)

log = structlog.get_logger(__name__)


def serialize_resolver(resolver: BaseResolver) -> Dict[str, Any]:
    """
    Convert resolver instance to JSON-serializable configuration.

    This function inspects the resolver type and extracts its configuration
    into a dictionary that can be stored in the database.

    Args:
        resolver: BaseResolver instance

    Returns:
        Dict with resolver_type and params

    Examples:
        LeadOwnerResolver() -> {"resolver_type": "lead_owner", "params": {}}
        SpecificUsersResolver() -> {"resolver_type": "specific_users", "params": {}}
        ActorExcludedResolver(UnitManagersResolver()) -> {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}}
        }
    """
    # Map resolver class to type string
    resolver_type_map = {
        LeadOwnerResolver: "lead_owner",
        UnitStaffResolver: "unit_staff",
        UnitManagersResolver: "unit_managers",
        AllAdminsResolver: "all_admins",
        AllUsersResolver: "all_users",
        SpecificUsersResolver: "specific_users",
        DormResidentsResolver: "dorm_residents",
        DormStaffResolver: "dorm_staff",
    }

    # Get resolver type
    resolver_class = type(resolver)

    # Handle composite resolvers (multiple resolvers)
    if isinstance(resolver, CompositeResolver):
        inner_resolvers = [serialize_resolver(r) for r in resolver.resolvers]
        return {
            "resolver_type": "composite",
            "params": {"resolvers": inner_resolvers}
        }

    # Handle actor-excluded wrapper
    if isinstance(resolver, ActorExcludedResolver):
        inner_resolver = serialize_resolver(resolver.resolver)
        return {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": inner_resolver}
        }

    # Handle simple resolvers
    resolver_type = resolver_type_map.get(resolver_class, "unknown")
    return {
        "resolver_type": resolver_type,
        "params": {}
    }


async def seed_notification_rules():
    """
    Seed notification_rule table with default configurations from registry.
    """
    log.info("Starting notification rules seeding process")

    # Create async engine and session
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Get existing rules to avoid duplicates
        result = await session.execute(select(models.NotificationRule.event))
        existing_events = {row[0] for row in result.fetchall()}

        log.info("Found existing rules", count=len(existing_events))

        # Iterate through registry
        created_count = 0
        skipped_count = 0

        for event, config in NOTIFICATION_REGISTRY.items():
            event_name = event.value

            # Skip if already exists
            if event_name in existing_events:
                log.debug("Skipping existing rule", event_name=event_name)
                skipped_count += 1
                continue

            # Serialize resolver
            try:
                recipient_config = serialize_resolver(config.resolver)
            except Exception as e:
                log.error(
                    "Failed to serialize resolver, skipping",
                    event_name=event_name,
                    error=str(e)
                )
                continue

            # Create rule
            rule = models.NotificationRule(
                event=event_name,
                title_template=config.template.get("title", ""),
                message_template=config.template.get("message", ""),
                notification_type=config.notification_type,
                link_template=config.link_template,
                channels=config.channels,
                recipient_config=recipient_config,
                condition=None,  # No conditions in hardcoded registry
                enabled=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            session.add(rule)
            created_count += 1

            log.info(
                "Created notification rule",
                event_name=event_name,
                resolver_type=recipient_config["resolver_type"],
                channels=config.channels
            )

        # Commit all rules
        await session.commit()

        log.info(
            "Notification rules seeding completed",
            created=created_count,
            skipped=skipped_count,
            total=len(NOTIFICATION_REGISTRY)
        )

    await engine.dispose()


if __name__ == "__main__":
    """Run seeding script."""
    asyncio.run(seed_notification_rules())
