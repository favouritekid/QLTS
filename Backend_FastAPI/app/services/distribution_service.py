# app/services/distribution_service.py
"""
Lead Distribution Service - Weighted Round Robin với Redis Atomic Operations.

Chức năng:
- Phân phối Lead cho Unit dựa trên ProgramOffering
- Thuật toán Weighted Round Robin với Priority tiers
- Redis-backed cursor để tránh race condition
- Fallback an toàn khi Redis unavailable hoặc không có config

Performance:
- O(1) Redis INCR operation - no DB counting
- Circuit breaker protection via safe_redis_* wrappers
- Minimal DB queries (single SELECT with index)

Thread-safety:
- Redis INCR is atomic across all workers/processes
- No locks needed thanks to atomic increment
"""
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..config import settings
from ..database import redis_client, REDIS_BREAKER_EXCEPTIONS

log = structlog.get_logger(__name__)

# Redis key pattern for distribution cursor
DISTRIBUTION_CURSOR_KEY_PATTERN = "distribution:offering:{offering_id}:cursor"
# TTL for cursor keys (7 days - auto-cleanup stale offerings)
CURSOR_TTL_SECONDS = 7 * 24 * 60 * 60

# Fallback to this unit when no distribution config found
# User should set this to their default admissions unit ID
DEFAULT_ADMISSIONS_UNIT_ID = getattr(settings, 'DEFAULT_ADMISSIONS_UNIT_ID', 1)


async def get_target_unit_for_offering(
    db: AsyncSession,
    offering_id: int,
    fallback_unit_id: Optional[int] = None
) -> int:
    """
    Determine target Unit for a Lead based on Offering distribution configuration.

    Algorithm: Weighted Round Robin with Priority Tiers
    1. Load all active configs for offering, sorted by (priority ASC, weight DESC)
    2. Build weighted candidate list (e.g., Unit A appears 3 times if weight=3)
    3. Use Redis INCR to atomically get next index (cursor)
    4. Select unit using modulo on weighted list
    5. Validate unit has active officers (safety check)

    Redis Key: distribution:offering:{offering_id}:cursor
    - Value: Integer counter (increments on each lead)
    - TTL: 7 days (auto-reset for inactive offerings)

    Args:
        db: Async database session
        offering_id: ProgramOffering.id to distribute
        fallback_unit_id: Override default fallback unit (optional)

    Returns:
        int: Selected unit_id

    Raises:
        No exceptions - always returns a valid unit_id via fallback chain:
        1. Weighted Round Robin selection
        2. fallback_unit_id (if provided)
        3. DEFAULT_ADMISSIONS_UNIT_ID from settings

    Examples:
        # Offering with 2 units configured:
        # Unit 10 (weight=3, priority=1)
        # Unit 20 (weight=1, priority=1)
        # Weighted list: [10, 10, 10, 20]
        # Lead 1: cursor=0 -> Unit 10
        # Lead 2: cursor=1 -> Unit 10
        # Lead 3: cursor=2 -> Unit 10
        # Lead 4: cursor=3 -> Unit 20
        # Lead 5: cursor=4 -> Unit 10 (wraps around)
    """
    try:
        # === STEP 1: Load active distribution configs ===
        stmt = (
            select(models.OfferingDistributionConfig)
            .where(
                and_(
                    models.OfferingDistributionConfig.offering_id == offering_id,
                    models.OfferingDistributionConfig.is_active == True
                )
            )
            .order_by(
                models.OfferingDistributionConfig.priority.asc(),  # Lower priority number = higher priority
                models.OfferingDistributionConfig.weight.desc()     # Higher weight = more leads
            )
        )
        result = await db.execute(stmt)
        configs = result.scalars().all()

        if not configs:
            # No distribution config found - use fallback
            final_fallback = fallback_unit_id or DEFAULT_ADMISSIONS_UNIT_ID
            log.warning(
                "No active distribution config found for offering, using fallback unit",
                offering_id=offering_id,
                fallback_unit_id=final_fallback
            )
            return final_fallback

        log.debug(
            "Loaded distribution configs for offering",
            offering_id=offering_id,
            config_count=len(configs),
            configs=[
                {"unit_id": c.unit_id, "weight": c.weight, "priority": c.priority}
                for c in configs
            ]
        )

        # === STEP 2: Build weighted candidate list ===
        # Group by priority tiers first
        priority_tiers = {}
        for config in configs:
            priority = config.priority
            if priority not in priority_tiers:
                priority_tiers[priority] = []
            priority_tiers[priority].append(config)

        # Start with highest priority tier (lowest number)
        top_priority = min(priority_tiers.keys())
        top_tier_configs = priority_tiers[top_priority]

        # Build weighted list for top tier only
        # (Lower priority tiers are only used if top tier has no capacity - handled separately)
        weighted_units = []
        for config in top_tier_configs:
            # Repeat unit_id based on weight (e.g., weight=3 -> add 3 times)
            weighted_units.extend([config.unit_id] * config.weight)

        if not weighted_units:
            # Edge case: configs exist but weighted list is empty (all weights = 0?)
            final_fallback = fallback_unit_id or DEFAULT_ADMISSIONS_UNIT_ID
            log.error(
                "Weighted unit list is empty despite having configs. Using fallback.",
                offering_id=offering_id,
                configs_count=len(configs),
                fallback_unit_id=final_fallback
            )
            return final_fallback

        log.debug(
            "Built weighted unit list for top priority tier",
            offering_id=offering_id,
            priority=top_priority,
            weighted_units=weighted_units,
            total_slots=len(weighted_units)
        )

        # === STEP 3: Atomic cursor increment via Redis ===
        cursor_key = DISTRIBUTION_CURSOR_KEY_PATTERN.format(offering_id=offering_id)

        try:
            # Atomic increment (thread-safe across all workers)
            cursor_value = await redis_client.incr(cursor_key)

            # Set TTL on first increment (if key was just created)
            if cursor_value == 1:
                await redis_client.expire(cursor_key, CURSOR_TTL_SECONDS)

            log.debug(
                "Redis cursor incremented",
                offering_id=offering_id,
                cursor_key=cursor_key,
                cursor_value=cursor_value
            )

        except REDIS_BREAKER_EXCEPTIONS as e:
            # Redis unavailable - fallback to random selection
            import random
            cursor_value = random.randint(1, 10000)
            log.warning(
                "Redis unavailable for cursor increment, using random fallback",
                offering_id=offering_id,
                error=str(e),
                fallback_cursor=cursor_value
            )

        except Exception as e:
            # Unexpected error - fallback to cursor = 1
            cursor_value = 1
            log.error(
                "Unexpected error during Redis cursor increment, using cursor=1",
                offering_id=offering_id,
                error=str(e),
                exc_info=True
            )

        # === STEP 4: Select unit using modulo ===
        # Cursor starts at 1, so subtract 1 for 0-based indexing
        index = (cursor_value - 1) % len(weighted_units)
        selected_unit_id = weighted_units[index]

        log.info(
            "Unit selected via Weighted Round Robin",
            offering_id=offering_id,
            selected_unit_id=selected_unit_id,
            cursor_value=cursor_value,
            index=index,
            weighted_list_size=len(weighted_units)
        )

        # === STEP 5: Safety check - Unit has active officers ===
        # Pre-check to avoid assigning leads to units with no available officers
        # (Assignment service will handle this later, but early detection is better)
        officer_check_stmt = (
            select(models.User.id)
            .where(
                and_(
                    models.User.unit_id == selected_unit_id,
                    models.User.role == "officer",
                    models.User.status == "active"
                )
            )
            .limit(1)
        )
        officer_result = await db.execute(officer_check_stmt)
        has_active_officer = officer_result.scalar_one_or_none() is not None

        if not has_active_officer:
            log.warning(
                "Selected unit has no active officers. Lead will be marked as unassigned.",
                offering_id=offering_id,
                selected_unit_id=selected_unit_id
            )
            # Still return this unit - assignment service will handle "no officers" case
            # Alternative: Try next unit in weighted list (more complex logic)

        return selected_unit_id

    except Exception as e:
        # Catch-all: Return fallback unit on any unexpected error
        final_fallback = fallback_unit_id or DEFAULT_ADMISSIONS_UNIT_ID
        log.error(
            "Critical error in distribution logic, using fallback unit",
            offering_id=offering_id,
            error=str(e),
            fallback_unit_id=final_fallback,
            exc_info=True
        )
        return final_fallback


async def reset_distribution_cursor(offering_id: int) -> bool:
    """
    Reset distribution cursor for an offering (Admin utility).

    Useful when:
    - Distribution config weights are changed
    - Manual rebalancing is needed
    - Testing/debugging

    Args:
        offering_id: ProgramOffering.id to reset

    Returns:
        bool: True if cursor was deleted, False if it didn't exist or Redis error
    """
    cursor_key = DISTRIBUTION_CURSOR_KEY_PATTERN.format(offering_id=offering_id)

    try:
        deleted_count = await redis_client.delete(cursor_key)
        success = deleted_count > 0

        log.info(
            "Distribution cursor reset",
            offering_id=offering_id,
            cursor_key=cursor_key,
            was_deleted=success
        )
        return success

    except REDIS_BREAKER_EXCEPTIONS as e:
        log.error(
            "Failed to reset distribution cursor - Redis unavailable",
            offering_id=offering_id,
            error=str(e)
        )
        return False
    except Exception as e:
        log.error(
            "Unexpected error resetting distribution cursor",
            offering_id=offering_id,
            error=str(e),
            exc_info=True
        )
        return False


async def get_distribution_stats(db: AsyncSession, offering_id: int) -> dict:
    """
    Get current distribution statistics for an offering (Admin/Analytics).

    Returns:
        dict: {
            "offering_id": int,
            "cursor_value": int | None,  # Current cursor position
            "configs": [  # Active distribution configs
                {
                    "unit_id": int,
                    "unit_name": str,
                    "weight": int,
                    "priority": int,
                    "slots_in_cycle": int  # How many slots this unit occupies
                }
            ],
            "total_slots": int,  # Total weighted slots in distribution cycle
            "next_unit_id": int  # Which unit will get next lead
        }
    """
    try:
        # Load configs
        stmt = (
            select(models.OfferingDistributionConfig)
            .where(
                and_(
                    models.OfferingDistributionConfig.offering_id == offering_id,
                    models.OfferingDistributionConfig.is_active == True
                )
            )
            .order_by(
                models.OfferingDistributionConfig.priority.asc(),
                models.OfferingDistributionConfig.weight.desc()
            )
        )
        result = await db.execute(stmt)
        configs = result.scalars().all()

        if not configs:
            return {
                "offering_id": offering_id,
                "cursor_value": None,
                "configs": [],
                "total_slots": 0,
                "next_unit_id": None
            }

        # Build weighted list (same logic as get_target_unit_for_offering)
        weighted_units = []
        config_details = []
        for config in configs:
            slots = config.weight
            weighted_units.extend([config.unit_id] * slots)

            # Load unit name for display
            unit = await db.get(models.OrganizationUnit, config.unit_id)
            config_details.append({
                "unit_id": config.unit_id,
                "unit_name": unit.name if unit else "Unknown",
                "weight": config.weight,
                "priority": config.priority,
                "slots_in_cycle": slots
            })

        # Get current cursor value
        cursor_key = DISTRIBUTION_CURSOR_KEY_PATTERN.format(offering_id=offering_id)
        try:
            cursor_str = await redis_client.get(cursor_key)
            cursor_value = int(cursor_str) if cursor_str else None
        except Exception:
            cursor_value = None

        # Calculate next unit
        next_unit_id = None
        if cursor_value is not None and weighted_units:
            next_index = cursor_value % len(weighted_units)
            next_unit_id = weighted_units[next_index]

        return {
            "offering_id": offering_id,
            "cursor_value": cursor_value,
            "configs": config_details,
            "total_slots": len(weighted_units),
            "next_unit_id": next_unit_id
        }

    except Exception as e:
        log.error(
            "Error getting distribution stats",
            offering_id=offering_id,
            error=str(e),
            exc_info=True
        )
        return {
            "offering_id": offering_id,
            "error": str(e)
        }
