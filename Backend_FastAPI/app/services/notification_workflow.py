# app/services/notification_workflow.py
"""
✅ NOTIFICATION 2.0 - Multi-Step Workflow Executor

Executes notification rules with multi-step action workflows.
Handles sequential delivery across multiple channels with delays.

Architecture:
- Finds matching rules for an event
- Resolves recipients based on resolver_type
- Evaluates conditions
- Executes actions in sequence with delays
- Handles failures gracefully

Example:
    # Execute workflow for LEAD_ASSIGNED event
    await execute_notification_workflow(
        db=db,
        event=SystemEvents.LEAD_ASSIGNED,
        payload={"lead_id": 123, "officer_id": 456, "actor_id": 789}
    )

Multi-Step Example:
    Rule with 3 actions:
    1. Socket notification (immediate)
    2. Email notification (after 5 minutes)
    3. SMS reminder (after 60 minutes)
"""
import asyncio
import structlog
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_resolvers import RESOLVER_REGISTRY
from app.services.notification_channels import get_channel

log = structlog.get_logger(__name__)

# ============================================
# CONDITION EVALUATOR
# ============================================


def evaluate_condition(condition: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> bool:
    """
    Evaluate rule condition against event payload.

    Supports:
    - Simple conditions: {"field": "actor.role", "operator": "eq", "value": "manager"}
    - Compound conditions: {"operator": "and", "conditions": [...]}

    Args:
        condition: Condition object from rule
        payload: Event payload

    Returns:
        True if condition passes, False otherwise
    """
    if not condition:
        # No condition = always pass
        return True

    try:
        # Compound condition (AND/OR)
        if "operator" in condition and "conditions" in condition:
            operator = condition["operator"]
            conditions = condition["conditions"]

            if operator == "and":
                return all(evaluate_condition(c, payload) for c in conditions)
            elif operator == "or":
                return any(evaluate_condition(c, payload) for c in conditions)
            else:
                log.warning("Unknown compound operator", operator=operator)
                return False

        # Simple condition
        field = condition.get("field")
        operator = condition.get("operator")
        expected = condition.get("value")

        if not all([field, operator]):
            log.warning("Invalid condition structure", condition=condition)
            return False

        # Get actual value from payload (support nested fields like "actor.role")
        actual = payload
        for key in field.split("."):
            if isinstance(actual, dict):
                actual = actual.get(key)
            else:
                actual = None
                break

        # Evaluate based on operator
        if operator == "eq":
            return actual == expected
        elif operator == "ne":
            return actual != expected
        elif operator == "gt":
            return actual is not None and actual > expected
        elif operator == "gte":
            return actual is not None and actual >= expected
        elif operator == "lt":
            return actual is not None and actual < expected
        elif operator == "lte":
            return actual is not None and actual <= expected
        elif operator == "in":
            return actual in expected if expected else False
        elif operator == "not_in":
            return actual not in expected if expected else True
        elif operator == "contains":
            return expected in actual if isinstance(actual, (str, list)) else False
        else:
            log.warning("Unknown operator", operator=operator)
            return False

    except Exception as e:
        log.error("Condition evaluation failed", error=str(e), condition=condition)
        return False


# ============================================
# RECIPIENT RESOLVER
# ============================================


async def resolve_recipients(
    db: AsyncSession,
    resolver_type: str,
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> List[int]:
    """
    Resolve notification recipients.

    Args:
        db: Database session
        resolver_type: Type of resolver
        params: Resolver parameters from rule
        context: Event payload

    Returns:
        List of user IDs
    """
    try:
        # Get resolver instance from registry
        resolver = RESOLVER_REGISTRY.get(resolver_type)
        if not resolver:
            log.warning("Unknown resolver type", resolver_type=resolver_type)
            return []

        # Merge params and context into payload for resolver
        payload = {**context, **params}

        # Execute resolver
        user_ids = await resolver.resolve_users(db, payload)
        log.info("Resolved recipients", resolver_type=resolver_type, count=len(user_ids))
        return user_ids

    except Exception as e:
        log.error("Recipient resolution failed", error=str(e), resolver_type=resolver_type)
        return []


# ============================================
# ACTION EXECUTOR
# ============================================


async def execute_action(
    db: AsyncSession,
    action: models.NotificationAction,
    recipient_ids: List[int],
    payload: Dict[str, Any]
) -> Tuple[Dict[str, Any], Callable]:
    """
    Execute a single notification action.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        action: Action to execute
        recipient_ids: List of user IDs to notify
        payload: Event payload for template rendering

    Returns:
        Tuple of (result_dict, post_commit_callback)
    """
    try:
        log.info(
            "Executing action",
            step=action.step,
            channel=action.channel,
            recipients=len(recipient_ids)
        )

        # Get channel
        channel = get_channel(action.channel)

        # Create notification records
        notifications = []
        for user_id in recipient_ids:
            notification = models.Notification(
                user_id=user_id,
                type="info",  # Default type
                title=payload.get("title", "New Notification"),
                message=payload.get("message", ""),
                link=payload.get("link"),
                metadata=payload,
                created_at=datetime.now(timezone.utc)
            )
            notifications.append(notification)

        # Save to database
        db.add_all(notifications)
        await db.flush()

        # Send via channel (NOTE: Sending before commit - may need adjustment)
        result = await channel.send(
            notifications=notifications,
            recipient_ids=recipient_ids,
            context=payload
        )

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Action executed successfully",
                step=action.step,
                channel=action.channel,
                sent=result.sent_count,
                failed=len(result.failed_ids)
            )

        result_dict = {
            "success": result.success,
            "sent_count": result.sent_count,
            "failed_count": len(result.failed_ids),
            "failed_ids": result.failed_ids
        }

        return result_dict, _post_commit

    except Exception as e:
        log.error(
            "Action execution failed",
            step=action.step,
            channel=action.channel,
            error=str(e)
        )
        # ✅ Router will handle rollback
        result_dict = {
            "success": False,
            "error": str(e),
            "sent_count": 0,
            "failed_count": len(recipient_ids)
        }

        async def _empty_callback():
            pass

        return result_dict, _empty_callback


# ============================================
# WORKFLOW EXECUTOR
# ============================================


async def execute_workflow(
    db: AsyncSession,
    rule: models.NotificationRule,
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute complete notification workflow for a rule.

    Workflow steps:
    1. Evaluate condition
    2. Resolve recipients
    3. Execute actions in sequence with delays
    4. Track execution metrics

    Args:
        db: Database session
        rule: Notification rule to execute
        payload: Event payload

    Returns:
        Execution summary with metrics
    """
    start_time = datetime.now(timezone.utc)

    try:
        log.info("Starting workflow execution", rule_id=rule.id, event_name=rule.event)

        # Step 1: Evaluate condition
        if not evaluate_condition(rule.condition, payload):
            log.info("Condition not met, skipping workflow", rule_id=rule.id)
            return {
                "rule_id": rule.id,
                "status": "skipped",
                "reason": "condition_not_met"
            }

        # Step 2: Resolve recipients
        resolver_config = rule.recipient_config or {}
        resolver_type = resolver_config.get("resolver_type", "specific_users")
        resolver_params = resolver_config.get("params", {})

        recipient_ids = await resolve_recipients(
            db=db,
            resolver_type=resolver_type,
            params=resolver_params,
            context=payload
        )

        if not recipient_ids:
            log.info("No recipients resolved, skipping workflow", rule_id=rule.id)
            return {
                "rule_id": rule.id,
                "status": "skipped",
                "reason": "no_recipients"
            }

        # Step 3: Execute actions in sequence
        actions = sorted(rule.actions, key=lambda a: a.step)
        action_results = []

        for i, action in enumerate(actions):
            # Apply delay (skip for first action)
            if i > 0 and action.delay_minutes > 0:
                delay_seconds = action.delay_minutes * 60
                log.info(
                    "Applying delay",
                    step=action.step,
                    delay_minutes=action.delay_minutes
                )
                await asyncio.sleep(delay_seconds)

            # Execute action
            result = await execute_action(
                db=db,
                action=action,
                recipient_ids=recipient_ids,
                payload=payload
            )
            action_results.append(result)

        # Calculate metrics
        total_sent = sum(r.get("sent_count", 0) for r in action_results)
        total_failed = sum(r.get("failed_count", 0) for r in action_results)
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        log.info(
            "Workflow execution completed",
            rule_id=rule.id,
            actions=len(actions),
            total_sent=total_sent,
            total_failed=total_failed,
            duration_seconds=duration
        )

        return {
            "rule_id": rule.id,
            "status": "completed",
            "recipients": len(recipient_ids),
            "actions_executed": len(actions),
            "total_sent": total_sent,
            "total_failed": total_failed,
            "duration_seconds": duration,
            "action_results": action_results
        }

    except Exception as e:
        log.error(
            "Workflow execution failed",
            rule_id=rule.id,
            error=str(e)
        )
        return {
            "rule_id": rule.id,
            "status": "failed",
            "error": str(e)
        }


# ============================================
# PUBLIC API
# ============================================


async def execute_notification_workflow(
    db: AsyncSession,
    event: SystemEvents,
    payload: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Execute notification workflows for an event.

    Finds all enabled rules matching the event and executes them.

    Args:
        db: Database session
        event: System event that triggered notifications
        payload: Event payload for template rendering and conditions

    Returns:
        List of execution results for each rule

    Example:
        results = await execute_notification_workflow(
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
    try:
        log.info("Executing notification workflow", event_name=event.value)

        # Find enabled rules for this event
        result = await db.execute(
            select(models.NotificationRule)
            .where(
                and_(
                    models.NotificationRule.event == event.value,
                    models.NotificationRule.enabled == True
                )
            )
        )
        rules = result.scalars().all()

        if not rules:
            log.info("No enabled rules found for event", event_name=event.value)
            return []

        log.info("Found rules to execute", event_name=event.value, count=len(rules))

        # Execute each rule's workflow
        results = []
        for rule in rules:
            result = await execute_workflow(db, rule, payload)
            results.append(result)

        # Summary
        completed = sum(1 for r in results if r.get("status") == "completed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        failed = sum(1 for r in results if r.get("status") == "failed")

        log.info(
            "Workflow execution summary",
            event_type=event.value,
            total_rules=len(rules),
            completed=completed,
            skipped=skipped,
            failed=failed
        )

        return results

    except Exception as e:
        log.error(
            "Workflow execution failed",
            event_type=event.value,
            error=str(e)
        )
        return []
