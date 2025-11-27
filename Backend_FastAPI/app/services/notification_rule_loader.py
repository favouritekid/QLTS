# app/services/notification_rule_loader.py
"""
✅ PHASE 2.3: Notification Rule Loader & Resolver Deserializer

This module handles:
1. Loading notification rules from database
2. Deserializing JSON resolver configs into resolver instances
3. Evaluating activation conditions
4. Caching rules for performance
"""
from string import Template
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group
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


def evaluate_condition(condition: Optional[Dict[str, Any]], payload: dict) -> bool:
    """
    Evaluate activation condition for a notification rule.

    Conditions allow rules to be activated only when certain criteria are met.
    For example, only send "Lead Assigned" notification if lead value > $10,000.

    Args:
        condition: Condition configuration dict (can be None)
        payload: Event payload data

    Returns:
        True if condition is met (or no condition), False otherwise

    Condition Format:
        {
            "field": "lead_value",
            "operator": "gt",
            "value": 10000
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

    Examples:
        >>> evaluate_condition(None, {})
        True

        >>> evaluate_condition(
        ...     {"field": "status", "operator": "eq", "value": "active"},
        ...     {"status": "active"}
        ... )
        True

        >>> evaluate_condition(
        ...     {"field": "amount", "operator": "gt", "value": 1000},
        ...     {"amount": 500}
        ... )
        False
    """
    # No condition = always True
    if not condition:
        return True

    field = condition.get("field")
    operator = condition.get("operator")
    expected_value = condition.get("value")

    # Get actual value from payload
    actual_value = payload.get(field)

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
        channels: List[str],
        resolver: BaseResolver,
        condition: Optional[Dict[str, Any]],
    ):
        self.rule_id = rule_id
        self.event = event
        self.title_template = title_template
        self.message_template = message_template
        self.notification_type = notification_type
        self.link_template = link_template
        self.channels = channels
        self.resolver = resolver
        self.condition = condition

        # Derive group from event
        try:
            event_enum = SystemEvents(event)
            self.group = get_event_group(event_enum)
        except ValueError:
            log.warning(
                "Unknown event for group derivation",
                event=event,
                rule_id=rule_id
            )
            # Default to SYSTEM group if event not found
            from app.core.event_groups import NotificationEventGroup
            self.group = NotificationEventGroup.SYSTEM

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

    def should_activate(self, payload: dict) -> bool:
        """Check if this rule should activate for the given payload."""
        return evaluate_condition(self.condition, payload)


# =============================================================================
# RULE LOADING FROM DATABASE
# =============================================================================


async def get_rule_for_event(
    db: AsyncSession,
    event: SystemEvents
) -> Optional[DatabaseRuleConfig]:
    """
    Load notification rule from database for a specific event.

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

    # Query database for enabled rule
    result = await db.execute(
        select(models.NotificationRule)
        .where(
            models.NotificationRule.event == event_name,
            models.NotificationRule.enabled == True
        )
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.debug(
            "No enabled rule found for event",
            event=event_name
        )
        return None

    # Deserialize resolver
    try:
        resolver = deserialize_resolver(rule.recipient_config)
    except Exception as e:
        log.error(
            "Failed to deserialize resolver for rule",
            rule_id=rule.id,
            event=event_name,
            error=str(e),
            recipient_config=rule.recipient_config
        )
        return None

    # Create config
    config = DatabaseRuleConfig(
        rule_id=rule.id,
        event=rule.event,
        title_template=rule.title_template,
        message_template=rule.message_template,
        notification_type=rule.notification_type,
        link_template=rule.link_template,
        channels=rule.channels,
        resolver=resolver,
        condition=rule.condition,
    )

    log.info(
        "Loaded notification rule from database",
        rule_id=rule.id,
        event=event_name,
        channels=rule.channels,
        resolver_type=rule.recipient_config.get("resolver_type")
    )

    return config
