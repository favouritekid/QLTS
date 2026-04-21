# app/services/notification_rule_loader.py
"""
✅ PHASE 2.3: Notification Rule Loader & Resolver Deserializer

This module handles:
1. Loading notification rules from database
2. Deserializing JSON resolver configs into resolver instances
3. Evaluating activation conditions
4. ✅ Caching rules for performance (Edge Case #6 fix)
"""
import json
from dataclasses import dataclass, field
from string import Template
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group
from app.database import safe_redis_get, safe_redis_set, safe_redis_delete
from app.services.notification_resolvers import (
    ActorExcludedResolver,
    AllAdminsResolver,
    AllUsersResolver,
    BaseResolver,
    CollaboratorUserResolver,
    CompositeResolver,
    DormResidentsResolver,
    DormStaffResolver,
    LeadOwnerResolver,
    SpecificUsersResolver,
    UnitManagersResolver,
    UnitStaffResolver,
)

log = structlog.get_logger(__name__)

# =============================================================================
# Phase 2: Operator & field alias maps for backward-compatible condition eval
# =============================================================================

# Phase 2: Operator aliases for legacy symbolic operators
OPERATOR_ALIASES = {
    "==": "eq", "!=": "ne",
    ">": "gt", ">=": "gte",
    "<": "lt", "<=": "lte",
}

# Phase 2: Legacy flat field -> canonical nested path (global, unambiguous)
FIELD_ALIASES_GLOBAL = {
    "new_status": "event.new_status_id",
    "old_status": "event.old_status_id",
    "old_stage": "event.old_stage_id",
    "new_stage": "event.new_stage_id",
    "lead_id": "lead.id",
    "lead_name": "lead.name",
    "officer_id": "lead.officer_id",
    "actor_id": "actor.id",
    "actor_name": "actor.name",
    "consultation_id": "consultation.id",
    "status_changed": "event.status_changed",
    "updated_fields": "event.updated_fields",
}

# Ambiguous aliases resolved per-event
FIELD_ALIASES_PER_EVENT = {
    "lead_imported": {"unit_id": "event.unit_id"},
    "_default": {"unit_id": "lead.unit_id"},
}


def _resolve_field_alias(field: str, event: str = "") -> str:
    """Resolve legacy flat field to canonical nested path, event-aware."""
    if field in FIELD_ALIASES_GLOBAL:
        return FIELD_ALIASES_GLOBAL[field]
    per_event = FIELD_ALIASES_PER_EVENT.get(event, FIELD_ALIASES_PER_EVENT["_default"])
    return per_event.get(field, field)


def _resolve_field(field: str, context: dict):
    """Resolve field value from evaluation context.
    Supports dotted paths (actor.role) and flat keys (lead_id).
    """
    if "." in field:
        parts = field.split(".")
        current = context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
    return context.get(field)


# =============================================================================
# ✅ FIX: Edge Case #6 - Redis Caching for Rules
# =============================================================================

# Cache configuration
RULE_CACHE_PREFIX = "notification_rule:"
RULE_CACHE_TTL = 3600  # 1 hour in seconds


async def invalidate_rule_cache(event: str) -> None:
    """
    Invalidate cached rule for a specific event.

    Call this after creating, updating, or deleting a notification rule.

    Args:
        event: Event name (e.g., "LEAD_ASSIGNED")
    """
    cache_key = f"{RULE_CACHE_PREFIX}{event}"
    try:
        await safe_redis_delete(cache_key)
        log.info("Invalidated rule cache", event_name=event, cache_key=cache_key)
    except Exception as e:
        log.warning("Failed to invalidate rule cache", event_name=event, error=str(e))


# =============================================================================
# RESOLVER DESERIALIZATION
# =============================================================================


def deserialize_resolver(config: Dict[str, Any]) -> BaseResolver:
    """
    Deserialize JSON resolver configuration into resolver instance.

    Args:
        config: Resolver configuration dict with structure:
            {
                "resolver_type": "lead_owner",
                "params": {}
            }

    Returns:
        Instantiated resolver object

    Raises:
        ValueError: If resolver_type is unknown

    Examples:
        >>> deserialize_resolver({"resolver_type": "lead_owner", "params": {}})
        LeadOwnerResolver()

        >>> deserialize_resolver({
        ...     "resolver_type": "actor_excluded",
        ...     "params": {
        ...         "inner_resolver": {
        ...             "resolver_type": "unit_managers",
        ...             "params": {}
        ...         }
        ...     }
        ... })
        ActorExcludedResolver(UnitManagersResolver())
    """
    resolver_type = config.get("resolver_type")
    params = config.get("params", {})

    # Map resolver types to classes
    resolver_map = {
        "lead_owner": LeadOwnerResolver,
        "unit_staff": UnitStaffResolver,
        "unit_managers": UnitManagersResolver,
        "all_admins": AllAdminsResolver,
        "all_users": AllUsersResolver,
        "specific_users": SpecificUsersResolver,
        "collaborator_user": CollaboratorUserResolver,
        "dorm_residents": DormResidentsResolver,
        "dorm_staff": DormStaffResolver,
    }

    # Handle composite resolver (multiple resolvers)
    if resolver_type == "composite":
        inner_resolvers_config = params.get("resolvers", [])
        inner_resolvers = [
            deserialize_resolver(r) for r in inner_resolvers_config
        ]
        return CompositeResolver(inner_resolvers)

    # Handle actor-excluded wrapper
    if resolver_type == "actor_excluded":
        inner_config = params.get("inner_resolver")
        if not inner_config:
            raise ValueError("ActorExcludedResolver requires inner_resolver in params")
        inner_resolver = deserialize_resolver(inner_config)
        return ActorExcludedResolver(inner_resolver)

    # Handle simple resolvers
    resolver_class = resolver_map.get(resolver_type)
    if not resolver_class:
        log.error(
            "Unknown resolver type",
            resolver_type=resolver_type,
            available_types=list(resolver_map.keys())
        )
        raise ValueError(f"Unknown resolver type: {resolver_type}")

    # Instantiate resolver (most resolvers don't take params in __init__)
    return resolver_class()


# =============================================================================
# CONDITION EVALUATION
# =============================================================================


def evaluate_condition(condition: Optional[Dict[str, Any]], payload: dict, event: str = "") -> bool:
    """
    Evaluate activation condition for a notification rule.

    Conditions allow rules to be activated only when certain criteria are met.
    For example, only send "Lead Assigned" notification if lead value > $10,000.

    Args:
        condition: Condition configuration dict (can be None)
        payload: Event payload data

    Returns:
        True if condition is met (or no condition), False otherwise

    Condition Formats:

    Simple condition:
        {
            "field": "lead_value",
            "operator": "gt",
            "value": 10000
        }

    Compound condition (nested AND/OR):
        {
            "operator": "and",  # or "or"
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {
                    "operator": "or",
                    "conditions": [
                        {"field": "priority", "operator": "gt", "value": 5},
                        {"field": "source", "operator": "in", "value": ["web", "api"]}
                    ]
                }
            ]
        }

    Supported operators:
        - eq: Equal
        - ne: Not equal
        - gt: Greater than
        - gte: Greater than or equal
        - lt: Less than
        - lte: Less than or equal
        - in: Value in list
        - not_in: Value not in list
        - contains: String contains substring

    Compound operators:
        - and: All sub-conditions must be true
        - or: At least one sub-condition must be true

    Examples:
        >>> evaluate_condition(None, {})
        True

        >>> evaluate_condition(
        ...     {"field": "status", "operator": "eq", "value": "active"},
        ...     {"status": "active"}
        ... )
        True

        >>> evaluate_condition(
        ...     {"operator": "and", "conditions": [
        ...         {"field": "status", "operator": "eq", "value": "active"},
        ...         {"field": "priority", "operator": "gt", "value": 5}
        ...     ]},
        ...     {"status": "active", "priority": 10}
        ... )
        True
    """
    # No condition = always True
    if not condition:
        return True

    # ✅ FIX: Handle compound conditions (AND/OR groups)
    operator = condition.get("operator")

    # Check if this is a compound condition (has "conditions" array)
    if "conditions" in condition and operator in ["and", "or"]:
        sub_conditions = condition.get("conditions", [])

        # Empty conditions array - default to True
        if not sub_conditions:
            log.debug("Empty conditions array, defaulting to True")
            return True

        # Recursively evaluate all sub-conditions
        try:
            if operator == "and":
                # ALL conditions must be true
                result = all(evaluate_condition(cond, payload, event) for cond in sub_conditions)
                log.debug(
                    "AND condition evaluated",
                    sub_count=len(sub_conditions),
                    result=result
                )
                return result
            elif operator == "or":
                # AT LEAST ONE condition must be true
                result = any(evaluate_condition(cond, payload, event) for cond in sub_conditions)
                log.debug(
                    "OR condition evaluated",
                    sub_count=len(sub_conditions),
                    result=result
                )
                return result
        except Exception as e:
            log.error(
                "Error evaluating compound condition",
                operator=operator,
                sub_conditions_count=len(sub_conditions),
                error=str(e)
            )
            return False

    # ✅ Handle simple conditions (original logic)
    # Phase 2: Normalize operator aliases (e.g. "==" -> "eq")
    operator = OPERATOR_ALIASES.get(operator, operator)

    field = condition.get("field")
    expected_value = condition.get("value")

    # Validate simple condition structure
    if not field:
        log.warning(
            "Simple condition missing 'field'",
            condition=condition
        )
        return False

    # Phase 2: Resolve legacy flat field names to canonical nested paths
    original_field = field
    field = _resolve_field_alias(field, event)

    # Get actual value from context (supports dotted paths like actor.role)
    actual_value = _resolve_field(field, payload)

    # Fallback: if alias resolved to dotted path but context is flat,
    # try original flat key for backward compat
    if actual_value is None and original_field != field:
        actual_value = payload.get(original_field)

    # Handle missing field
    if actual_value is None:
        log.debug(
            "Condition field not found in payload",
            field=field,
            payload_keys=list(payload.keys())
        )
        return False

    # Evaluate based on operator
    try:
        if operator == "eq":
            return actual_value == expected_value
        elif operator == "ne":
            return actual_value != expected_value
        elif operator == "gt":
            return actual_value > expected_value
        elif operator == "gte":
            return actual_value >= expected_value
        elif operator == "lt":
            return actual_value < expected_value
        elif operator == "lte":
            return actual_value <= expected_value
        elif operator == "in":
            return actual_value in expected_value
        elif operator == "not_in":
            return actual_value not in expected_value
        elif operator == "contains":
            return expected_value in str(actual_value)
        else:
            log.warning(
                "Unknown condition operator",
                operator=operator,
                field=field
            )
            return False
    except Exception as e:
        log.error(
            "Error evaluating condition",
            field=field,
            operator=operator,
            error=str(e)
        )
        return False


# =============================================================================
# ACTION CONFIGURATION (Phase C0)
# =============================================================================


@dataclass(frozen=True)
class ActionConfig:
    """
    Configuration for a single notification action step.

    Phase C0: actions are the runtime truth for channel delivery.
    Each action represents one channel + step in the delivery pipeline.
    """
    step: int
    channel: str
    delay_minutes: int = 0
    template_code: Optional[str] = None
    config: Optional[Dict[str, Any]] = field(default=None, hash=False)
    # Phase 3: delivery branch fields
    recipient_config: Optional[Dict[str, Any]] = field(default=None, hash=False)
    content_mode: Optional[str] = None
    content_override: Optional[Dict[str, Any]] = field(default=None, hash=False)
    branch_key: Optional[str] = None


def synthesize_actions_from_channels(channels: List[str]) -> List[ActionConfig]:
    """
    Create synthetic ActionConfig list from a channels array.

    Used for backward compatibility when a rule has channels but no
    NotificationAction rows (legacy rules before C0 migration).
    """
    return [
        ActionConfig(step=i, channel=ch, delay_minutes=0)
        for i, ch in enumerate(channels, start=1)
    ]


def derive_channels_from_actions(actions: List[ActionConfig]) -> List[str]:
    """
    Derive unique channel list from actions, preserving step order.

    Used to keep the top-level `channels` field in sync with actions.
    """
    seen: set = set()
    result: List[str] = []
    for a in sorted(actions, key=lambda x: x.step):
        if a.channel not in seen:
            result.append(a.channel)
            seen.add(a.channel)
    return result


# =============================================================================
# RULE CONFIGURATION CLASS
# =============================================================================


class DatabaseRuleConfig:
    """
    Configuration for a notification rule loaded from database.

    This class provides the same interface as NotificationConfig from the
    hardcoded registry, allowing seamless migration.
    """

    def __init__(
        self,
        rule_id: int,
        event: str,
        title_template: str,
        message_template: str,
        notification_type: str,
        link_template: Optional[str],
        resolver: BaseResolver,
        condition: Optional[Dict[str, Any]],
        priority: int = 100,
        dedup_key_template: Optional[str] = None,
        actions: Optional[List[ActionConfig]] = None,
    ):
        self.rule_id = rule_id
        self.event = event
        self.title_template = title_template
        self.message_template = message_template
        self.notification_type = notification_type
        self.link_template = link_template
        self.resolver = resolver
        self.condition = condition
        self.priority = priority
        self.dedup_key_template = dedup_key_template

        # Phase C0: actions are the runtime truth. Wave 4b dropped the
        # legacy `channels` compat column, so no synthesis from channels
        # is possible — actions must always be provided by the caller.
        self._actions = actions if actions else []

        # Derive group from event
        try:
            event_enum = SystemEvents(event)
            self.group = get_event_group(event_enum)
        except ValueError:
            log.warning(
                "Unknown event for group derivation",
                event_name=event,
                rule_id=rule_id
            )
            # Default to SYSTEM group if event not found
            from app.core.event_groups import NotificationEventGroup
            self.group = NotificationEventGroup.SYSTEM

    @property
    def actions(self) -> List[ActionConfig]:
        """Get action configs — the runtime truth for delivery pipeline."""
        return self._actions

    @property
    def channels(self) -> List[str]:
        """Derived from actions. Kept for backward compat."""
        return derive_channels_from_actions(self._actions)

    @property
    def channel_values(self) -> List[str]:
        """Alias for channels for interface compatibility with NotificationConfig."""
        return self.channels

    def render_title(self, payload: dict) -> str:
        """Render title template with payload data."""
        return Template(self.title_template).safe_substitute(payload)

    def render_message(self, payload: dict) -> str:
        """Render message template with payload data."""
        return Template(self.message_template).safe_substitute(payload)

    def render_link(self, payload: dict) -> Optional[str]:
        """Render link template with payload data if configured."""
        if not self.link_template:
            return None
        return Template(self.link_template).safe_substitute(payload)
    
    def render_dedup_key(self, payload: dict) -> Optional[str]:
        """Render deduplication key template with payload data."""
        if not self.dedup_key_template:
            return None
        return Template(self.dedup_key_template).safe_substitute(payload)

    def should_activate(self, payload: dict) -> bool:
        """Check if this rule should activate for the given payload."""
        return evaluate_condition(self.condition, payload, self.event)


# =============================================================================
# RULE LOADING FROM DATABASE
# =============================================================================


async def get_rule_for_event(
    db: AsyncSession,
    event: SystemEvents
) -> Optional[DatabaseRuleConfig]:
    """
    Load notification rule from database for a specific event.

    ✅ Uses Redis caching to reduce database load.

    Cache Strategy:
    - Cache raw rule data as JSON (1 hour TTL)
    - Deserialize resolver on each request (resolvers can't be serialized)
    - Invalidate cache on rule create/update/delete

    Args:
        db: Database session
        event: System event enum

    Returns:
        DatabaseRuleConfig if rule exists and is enabled, None otherwise

    Example:
        >>> rule = await get_rule_for_event(db, SystemEvents.LEAD_ASSIGNED)
        >>> if rule:
        ...     recipients = await rule.resolver.resolve_users(db, payload)
    """
    event_name = event.value
    cache_key = f"{RULE_CACHE_PREFIX}{event_name}"

    # ✅ Try to get from cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            rule_data = json.loads(cached_data)
            log.debug(
                "Rule loaded from cache",
                event_type=event_name,
                cache_key=cache_key
            )

            # Deserialize resolver (can't be cached)
            try:
                resolver = deserialize_resolver(rule_data["recipient_config"])
            except Exception as e:
                log.error(
                    "Failed to deserialize resolver from cache",
                    event_type=event_name,
                    error=str(e)
                )
                # Invalidate bad cache entry
                await safe_redis_delete(cache_key)
                # Fall through to DB query
            else:
                # Deserialize cached actions
                cached_actions = rule_data.get("actions")
                action_configs = None
                if cached_actions:
                    action_configs = [
                        ActionConfig(
                            step=a_data["step"],
                            channel=a_data["channel"],
                            delay_minutes=a_data.get("delay_minutes", 0),
                            template_code=a_data.get("template_code"),
                            config=a_data.get("config"),
                            recipient_config=a_data.get("recipient_config"),
                            content_mode=a_data.get("content_mode"),
                            content_override=a_data.get("content_override"),
                            branch_key=a_data.get("branch_key"),
                        )
                        for a_data in cached_actions
                    ]

                # Successfully loaded from cache
                config = DatabaseRuleConfig(
                    rule_id=rule_data["id"],
                    event=rule_data["event"],
                    title_template=rule_data["title_template"],
                    message_template=rule_data["message_template"],
                    notification_type=rule_data["notification_type"],
                    link_template=rule_data.get("link_template"),
                    resolver=resolver,
                    condition=rule_data.get("condition"),
                    actions=action_configs,
                )
                return config
    except Exception as e:
        log.warning(
            "Cache read failed, falling back to database",
            event_type=event_name,
            error=str(e)
        )

    # ✅ Query database for enabled rule (cache miss or error)
    # Phase C0: eager-load actions for action-based execution
    # 1.9d: eager-load template to avoid N+1 query
    result = await db.execute(
        select(models.NotificationRule)
        .options(
            selectinload(models.NotificationRule.actions),
            selectinload(models.NotificationRule.template),
        )
        .where(
            models.NotificationRule.event == event_name,
            models.NotificationRule.enabled == True
        )
    )
    # PR1: fail-fast on duplicate enabled rules — config error, not silent pick
    rules = result.scalars().all()
    if not rules:
        log.debug(
            "No enabled rule found for event",
            event_type=event_name
        )
        return None
    if len(rules) > 1:
        from app.utils.exceptions import NotificationConfigError
        rule_ids = [r.id for r in rules]
        log.error(
            "Multiple enabled rules for same event — config error",
            event_type=event_name,
            rule_ids=rule_ids,
        )
        raise NotificationConfigError(
            f"Event '{event_name}' has {len(rules)} enabled rules (IDs: {rule_ids}). "
            f"Expected exactly 1. Disable or delete duplicate rules."
        )
    rule = rules[0]

    # Deserialize resolver — explicit error, no silent None (1.9f)
    try:
        resolver = deserialize_resolver(rule.recipient_config)
    except Exception as e:
        from app.utils.exceptions import NotificationConfigError
        log.error(
            "Failed to deserialize resolver for rule",
            rule_id=rule.id,
            event_type=event_name,
            error=str(e),
            recipient_config=rule.recipient_config
        )
        raise NotificationConfigError(
            f"Rule {rule.id} ({event_name}) has invalid recipient_config: {e}"
        )

    # 1.9d: Use eager-loaded template relationship (no N+1)
    title_template = rule.title_template
    message_template = rule.message_template
    link_template = rule.link_template

    if rule.template_id and rule.template:
        template = rule.template
        title_template = template.title_template
        message_template = template.message_template
        link_template = template.link_template if not rule.link_template else rule.link_template
        log.debug(
            "Using eager-loaded template for rule",
            rule_id=rule.id,
            template_id=template.id,
        )
    elif rule.template_id:
        log.warning(
            "Template not found for rule (eager-load returned None), using rule templates",
            rule_id=rule.id,
            template_id=rule.template_id,
        )

    # Phase C0: Build ActionConfig list from DB actions (or synthesize from channels)
    db_actions = sorted(rule.actions, key=lambda a: a.step) if rule.actions else []
    if db_actions:
        action_configs = [
            ActionConfig(
                step=a.step,
                channel=a.channel,
                delay_minutes=a.delay_minutes,
                template_code=a.template_code,
                config=a.config,
                recipient_config=a.recipient_config,
                content_mode=a.content_mode,
                content_override=a.content_override,
                branch_key=a.branch_key,
            )
            for a in db_actions
        ]
    else:
        action_configs = None  # Will fall back to synthesize from channels

    # Create config
    config = DatabaseRuleConfig(
        rule_id=rule.id,
        event=rule.event,
        title_template=title_template,
        message_template=message_template,
        notification_type=rule.notification_type,
        link_template=link_template,
        resolver=resolver,
        condition=rule.condition,
        actions=action_configs,
    )

    # ✅ Cache the rule data for future requests
    try:
        # Serialize actions for cache
        actions_cache = [
            {"step": a.step, "channel": a.channel,
             "delay_minutes": a.delay_minutes,
             "template_code": a.template_code, "config": a.config,
             "recipient_config": a.recipient_config,
             "content_mode": a.content_mode,
             "content_override": a.content_override,
             "branch_key": a.branch_key}
            for a in config.actions
        ]

        rule_data = {
            "id": rule.id,
            "event": rule.event,
            "title_template": title_template,
            "message_template": message_template,
            "notification_type": rule.notification_type,
            "link_template": link_template,
            "actions": actions_cache,
            "recipient_config": rule.recipient_config,  # Will deserialize on each request
            "condition": rule.condition,
        }
        await safe_redis_set(
            cache_key,
            json.dumps(rule_data),
            ex=RULE_CACHE_TTL
        )
        log.debug(
            "Cached rule data",
            event_type=event_name,
            cache_key=cache_key,
            ttl=RULE_CACHE_TTL
        )
    except Exception as e:
        log.warning(
            "Failed to cache rule data",
            event_type=event_name,
            error=str(e)
        )

    log.info(
        "Loaded notification rule from database",
        rule_id=rule.id,
        event_type=event_name,
        action_count=len(config.actions),
        resolver_type=rule.recipient_config.get("resolver_type")
    )

    return config


    # has_rule_override_for_event() — REMOVED in PR1 (notification refactor).
    # Dispatcher no longer uses registry fallback; single-path via catalog + DB rule.
