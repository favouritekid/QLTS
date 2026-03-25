# app/services/notification_rule_crud_service.py
"""
Notification Rule CRUD Service - CRUD operations for notification rules.

Complies with Pattern A: Router → Service → Repository
"""
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.utils.exceptions import BadRequest
from app.repositories import NotificationRuleRepository
from .notification_rule_loader import invalidate_rule_cache, derive_channels_from_actions, ActionConfig

log = structlog.get_logger(__name__)


def _validate_actions_c0(actions) -> None:
    """
    Validate NotificationAction constraints for Phase C0.

    C0 rules:
      - delay_minutes must be 0 (delayed execution not yet supported)
      - steps must be contiguous 1..n
      - no duplicate steps
      - no duplicate channels within same rule
    """
    if not actions:
        return

    steps = set()
    channels = set()
    for action in actions:
        step = action.step if hasattr(action, 'step') else action.get('step')
        channel = action.channel if hasattr(action, 'channel') else action.get('channel')
        delay = action.delay_minutes if hasattr(action, 'delay_minutes') else action.get('delay_minutes', 0)

        if delay and delay > 0:
            raise BadRequest(
                f"Phase C0: delayed actions not yet supported (step {step} has delay_minutes={delay}). "
                "All actions must have delay_minutes=0."
            )

        template_code = action.template_code if hasattr(action, 'template_code') else action.get('template_code')
        if template_code:
            raise BadRequest(
                f"Phase C0: per-action template_code not yet supported (step {step}). "
                "Use rule-level template_id instead."
            )

        if step in steps:
            raise BadRequest(f"Duplicate step number: {step}")
        steps.add(step)

        if channel in channels:
            raise BadRequest(
                f"Duplicate channel '{channel}' in rule actions. "
                "Phase C0 requires unique channels per rule."
            )
        channels.add(channel)

    # Verify steps are contiguous 1..n
    if steps and steps != set(range(1, len(steps) + 1)):
        raise BadRequest(
            f"Action steps must be contiguous 1..{len(steps)}, got: {sorted(steps)}"
        )


async def get_rules(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    event: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Tuple[List[models.NotificationRule], int]:
    """
    Get paginated list of notification rules with filters.
    """
    repo = NotificationRuleRepository(db)
    return await repo.list_rules(skip, limit, event, enabled)


    # Events that are broadcast-only and must NOT have user notification rules
BROADCAST_ONLY_EVENTS = frozenset({
    "unit_created", "unit_updated", "unit_deleted",
    "program_created", "program_updated", "program_deleted",
    "offering_created", "offering_updated", "offering_deleted",
})


async def create_rule(
    db: AsyncSession,
    rule_data: schemas.NotificationRuleCreate,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Create a new notification rule.
    """
    # Reject broadcast-only events — these are domain events, not user notifications
    if rule_data.event in BROADCAST_ONLY_EVENTS:
        raise BadRequest(
            f"Event '{rule_data.event}' is broadcast-only and cannot have notification rules. "
            "Organization events are domain broadcasts, not user notifications."
        )

    repo = NotificationRuleRepository(db)

    # Check if rule already exists for this event
    existing_rule = await repo.get_by_event(rule_data.event)
    if existing_rule:
        raise BadRequest(
            f"Notification rule for event '{rule_data.event}' already exists (ID: {existing_rule.id})"
        )

    # Phase C0: Validate action constraints
    _validate_actions_c0(rule_data.actions)

    # Phase C0: Derive channels from actions if actions are provided
    if rule_data.actions:
        derived = [a.channel for a in rule_data.actions]
        # Dedupe preserving order
        seen = set()
        rule_data.channels = [c for c in derived if not (c in seen or seen.add(c))]

    # Create rule via repository
    new_rule = await repo.create_with_actions(rule_data)

    # Create post-commit callback
    rule_id = new_rule.id
    event_type = new_rule.event
    template_id = rule_data.template_id
    actions_count = len(rule_data.actions)

    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache for this event
        await invalidate_rule_cache(event_type)

        log.info(
            "Created notification rule",
            rule_id=rule_id,
            event_type=event_type,
            template_id=template_id,
            actions_count=actions_count
        )

    return new_rule, _post_commit


async def update_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
    rule_update: schemas.NotificationRuleUpdate,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Update an existing notification rule.
    """
    repo = NotificationRuleRepository(db)
    old_template_id = rule.template_id
    updated_fields = []

    # Update basic fields (exclude actions + channels — channels is derived from actions)
    update_data = rule_update.model_dump(exclude_unset=True, exclude={"actions", "channels"})
    for field, value in update_data.items():
        if value is not None:
            setattr(rule, field, value)
            updated_fields.append(field)

    # Handle actions update
    if rule_update.actions is not None:
        _validate_actions_c0(rule_update.actions)
        await repo.delete_actions(rule.id)
        await repo.add_actions(rule.id, rule_update.actions)
        updated_fields.append("actions")
        # Phase C0: Sync channels from actions
        derived = [a.channel for a in rule_update.actions]
        seen = set()
        rule.channels = [c for c in derived if not (c in seen or seen.add(c))]
        if "channels" not in updated_fields:
            updated_fields.append("channels")

    # Update usage_count if template_id changed
    if "template_id" in updated_fields:
        new_template_id = rule.template_id
        if old_template_id:
            await repo.update_template_usage(old_template_id, -1)
        if new_template_id:
            await repo.update_template_usage(new_template_id, 1)

    if updated_fields:
        await db.flush()
        await db.refresh(rule)

    # Create post-commit callback
    rule_id = rule.id
    event_type = rule.event
    template_changed = "template_id" in updated_fields

    async def _post_commit():
        """Execute after router commits the transaction."""
        await invalidate_rule_cache(event_type)

        if updated_fields:
            log.info(
                "Updated notification rule",
                rule_id=rule_id,
                event_type=event_type,
                updated_fields=updated_fields,
                template_changed=template_changed
            )
        else:
            log.info(
                "No fields to update for notification rule",
                rule_id=rule_id
            )

    return rule, _post_commit


async def toggle_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
) -> Tuple[models.NotificationRule, Callable]:
    """
    Toggle enabled/disabled status of a notification rule.
    """
    repo = NotificationRuleRepository(db)
    old_status = rule.enabled
    rule.enabled = not rule.enabled

    await db.flush()
    await db.refresh(rule)

    # Create post-commit callback
    rule_id = rule.id
    event_type = rule.event
    new_status = rule.enabled

    async def _post_commit():
        """Execute after router commits the transaction."""
        await invalidate_rule_cache(event_type)

        log.info(
            "Toggled notification rule status",
            rule_id=rule_id,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status
        )

    return rule, _post_commit


async def delete_rule(
    db: AsyncSession,
    rule: models.NotificationRule,
) -> Tuple[None, Callable]:
    """
    Delete a notification rule.
    """
    repo = NotificationRuleRepository(db)
    rule_id = rule.id
    event_type = rule.event
    template_id = rule.template_id

    await repo.delete_rule(rule)

    async def _post_commit():
        """Execute after router commits the transaction."""
        await invalidate_rule_cache(event_type)

        log.info(
            "Deleted notification rule",
            rule_id=rule_id,
            event_type=event_type,
            template_id=template_id
        )

    return None, _post_commit
