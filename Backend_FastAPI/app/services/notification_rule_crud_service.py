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
from app.repositories import NotificationRuleRepository, NotificationTemplateRepository
from .notification_rule_loader import invalidate_rule_cache, derive_channels_from_actions, ActionConfig
from app.services.notification_rule_loader import OPERATOR_ALIASES, FIELD_ALIASES_GLOBAL, FIELD_ALIASES_PER_EVENT, _resolve_field_alias
from app.core.event_metadata import EVENT_METADATA_REGISTRY
from app.core.events import SystemEvents

log = structlog.get_logger(__name__)


_VALID_EXTERNAL_RESOLVERS = frozenset({
    "lead_contact", "admission_contact", "collaborator_contact",
})


def _validate_zalo_action_config(step: int, config) -> None:
    """Validate Zalo action config — requires zalo_template_id."""
    if not config or not isinstance(config, dict):
        raise BadRequest(
            f"Action step {step}: channel 'zalo' requires config with 'zalo_template_id'. "
            "Example: {\"zalo_template_id\": \"abc123\"}"
        )
    if not config.get("zalo_template_id"):
        raise BadRequest(
            f"Action step {step}: channel 'zalo' requires 'zalo_template_id' in config."
        )
    ext_resolver = config.get("external_resolver")
    if ext_resolver:
        _validate_external_resolver(step, ext_resolver)


def _validate_external_resolver(step: int, resolver_type: str) -> None:
    """Validate external_resolver is a known type."""
    if resolver_type not in _VALID_EXTERNAL_RESOLVERS:
        raise BadRequest(
            f"Action step {step}: unknown external_resolver '{resolver_type}'. "
            f"Valid resolvers: {sorted(_VALID_EXTERNAL_RESOLVERS)}"
        )


def _validate_actions(actions) -> None:
    """
    Validate NotificationAction constraints (synchronous checks only).

    Rules:
      - C1: delay_minutes >= 0 allowed (worker handles delayed execution)
      - steps must be contiguous 1..n
      - no duplicate steps
      - no duplicate channels within same rule

    Note: template_code existence + channel support is validated asynchronously
    by _validate_action_template_codes() which must be called separately.
    """
    if not actions:
        return

    steps = set()
    channels = set()
    for action in actions:
        step = action.step if hasattr(action, 'step') else action.get('step')
        channel = action.channel if hasattr(action, 'channel') else action.get('channel')
        delay = action.delay_minutes if hasattr(action, 'delay_minutes') else action.get('delay_minutes', 0)

        if delay is not None and delay < 0:
            raise BadRequest(
                f"delay_minutes must be >= 0 (step {step} has delay_minutes={delay})."
            )

        if step in steps:
            raise BadRequest(f"Duplicate step number: {step}")
        steps.add(step)

        if channel in channels:
            raise BadRequest(
                f"Duplicate channel '{channel}' in rule actions. "
                "Each channel must be unique within a rule."
            )
        channels.add(channel)

        # FP3: Channel-specific config validation
        config = action.config if hasattr(action, 'config') else action.get('config')
        if channel == "zalo":
            _validate_zalo_action_config(step, config)
        elif config and isinstance(config, dict):
            # Validate external_resolver for any channel that has it
            ext_resolver = config.get("external_resolver")
            if ext_resolver:
                _validate_external_resolver(step, ext_resolver)

    # Verify steps are contiguous 1..n
    if steps and steps != set(range(1, len(steps) + 1)):
        raise BadRequest(
            f"Action steps must be contiguous 1..{len(steps)}, got: {sorted(steps)}"
        )


async def _validate_action_template_codes(
    db: AsyncSession,
    actions,
) -> None:
    """
    Phase E2: Validate template_code references in actions.

    For each action that specifies a template_code:
      1. The template must exist in the database.
      2. The template's supported_channels must include the action's channel.

    Raises BadRequest on validation failure.
    """
    if not actions:
        return

    repo = NotificationTemplateRepository(db)

    for action in actions:
        step = action.step if hasattr(action, 'step') else action.get('step')
        channel = action.channel if hasattr(action, 'channel') else action.get('channel')
        template_code = action.template_code if hasattr(action, 'template_code') else action.get('template_code')

        if not template_code:
            continue

        template = await repo.get_by_template_code(template_code)
        if not template:
            raise BadRequest(
                f"Action step {step}: template_code '{template_code}' does not exist."
            )

        # Check channel support
        supported = template.supported_channels or []
        if channel not in supported:
            raise BadRequest(
                f"Action step {step}: template '{template_code}' does not support "
                f"channel '{channel}'. Supported channels: {supported}"
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


def _canonicalize_condition(condition: dict | None, event: str) -> dict | None:
    """Recursively normalize operators AND field paths in condition tree."""
    if not condition:
        return condition
    if "conditions" in condition:  # compound
        return {
            **condition,
            "operator": condition["operator"],
            "conditions": [_canonicalize_condition(c, event) for c in condition["conditions"]],
        }
    op = condition.get("operator", "")
    field = condition.get("field", "")
    return {
        **condition,
        "operator": OPERATOR_ALIASES.get(op, op),
        "field": _resolve_field_alias(field, event),
    }


def _validate_condition_fields(condition: dict | None, allowed_paths: set) -> list:
    """Return list of invalid field paths (recursive for compound)."""
    if not condition:
        return []
    errors = []
    if "conditions" in condition:
        for sub in condition.get("conditions", []):
            errors.extend(_validate_condition_fields(sub, allowed_paths))
        return errors
    field = condition.get("field", "")
    if field and field not in allowed_paths:
        errors.append(f"Unknown condition field: '{field}'")
    return errors


def _validate_condition_operators(condition: dict | None, field_operator_map: dict) -> list:
    """Return list of invalid operator usages (recursive for compound)."""
    if not condition:
        return []
    errors = []
    if "conditions" in condition:
        for sub in condition.get("conditions", []):
            errors.extend(_validate_condition_operators(sub, field_operator_map))
        return errors
    field = condition.get("field", "")
    op = OPERATOR_ALIASES.get(condition.get("operator", ""), condition.get("operator", ""))
    allowed_ops = field_operator_map.get(field)
    if allowed_ops is not None and op not in allowed_ops:
        errors.append(f"Operator '{op}' not allowed for field '{field}' (allowed: {allowed_ops})")
    return errors


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

    # Phase 2: Canonicalize condition (normalize operators + field paths)
    rule_data.condition = _canonicalize_condition(rule_data.condition, rule_data.event) if rule_data.condition else None

    # Phase 2: Validate condition fields and operators against event metadata
    if rule_data.condition:
        try:
            event_enum = SystemEvents(rule_data.event)
            event_meta = EVENT_METADATA_REGISTRY.get(event_enum)
            if event_meta and event_meta.condition_fields:
                allowed_paths = {cf.path for cf in event_meta.condition_fields}
                field_errors = _validate_condition_fields(rule_data.condition, allowed_paths)
                if field_errors:
                    raise BadRequest(f"Invalid condition fields: {'; '.join(field_errors)}")

                field_op_map = {cf.path: cf.operators for cf in event_meta.condition_fields}
                op_errors = _validate_condition_operators(rule_data.condition, field_op_map)
                if op_errors:
                    raise BadRequest(f"Invalid condition operators: {'; '.join(op_errors)}")
        except ValueError:
            pass  # Unknown event, skip validation

    repo = NotificationRuleRepository(db)

    # Check if rule already exists for this event
    existing_rule = await repo.get_by_event(rule_data.event)
    if existing_rule:
        raise BadRequest(
            f"Notification rule for event '{rule_data.event}' already exists (ID: {existing_rule.id})"
        )

    # Validate action constraints (sync checks)
    _validate_actions(rule_data.actions)

    # Phase E2: Validate template_code references (async DB lookup)
    await _validate_action_template_codes(db, rule_data.actions)

    # Phase C1: channels is ALWAYS derived from actions (input ignored)
    if rule_data.actions:
        derived = [a.channel for a in rule_data.actions]
        seen = set()
        rule_data.channels = [c for c in derived if not (c in seen or seen.add(c))]
    else:
        rule_data.channels = []

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

    # Phase 2: If condition is being updated, canonicalize and validate
    if 'condition' in update_data and update_data['condition'] is not None:
        event_name = rule.event
        update_data['condition'] = _canonicalize_condition(update_data['condition'], event_name)

        try:
            event_enum = SystemEvents(event_name)
            event_meta = EVENT_METADATA_REGISTRY.get(event_enum)
            if event_meta and event_meta.condition_fields:
                allowed_paths = {cf.path for cf in event_meta.condition_fields}
                field_errors = _validate_condition_fields(update_data['condition'], allowed_paths)
                if field_errors:
                    raise BadRequest(f"Invalid condition fields: {'; '.join(field_errors)}")

                field_op_map = {cf.path: cf.operators for cf in event_meta.condition_fields}
                op_errors = _validate_condition_operators(update_data['condition'], field_op_map)
                if op_errors:
                    raise BadRequest(f"Invalid condition operators: {'; '.join(op_errors)}")
        except ValueError:
            pass  # Unknown event, skip validation

    for field, value in update_data.items():
        if value is not None:
            setattr(rule, field, value)
            updated_fields.append(field)

    # Handle actions update
    if rule_update.actions is not None:
        _validate_actions(rule_update.actions)
        # Phase E2: Validate template_code references (async DB lookup)
        await _validate_action_template_codes(db, rule_update.actions)
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
