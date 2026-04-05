# app/services/notification_resolvers.py
"""
Notification Resolvers - Strategy Pattern for determining notification recipients.

Resolvers are responsible for translating event payloads into lists of user IDs
who should receive the notification. Each resolver implements a specific strategy
for resolving recipients based on the event type and payload.

Key Design Principles:
1. FAIL-SAFE: Resolvers must never raise exceptions. If resolution fails,
   log a warning and return an empty list.
2. ASYNC: All database queries must be async SQLAlchemy.
3. BULK-FRIENDLY: Resolvers should be efficient for bulk operations.

Usage:
    from app.services.notification_resolvers import LeadOwnerResolver

    resolver = LeadOwnerResolver()
    user_ids = await resolver.resolve_users(db, payload)
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Set

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole

log = logging.getLogger(__name__)


class BaseResolver(ABC):
    """
    Abstract base class for notification resolvers.

    All resolvers must implement the resolve_users method and follow
    the fail-safe design principle.
    """

    @abstractmethod
    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        """
        Resolve the list of user IDs who should receive the notification.

        Args:
            db: Async database session
            payload: Event payload containing data needed for resolution

        Returns:
            List of user IDs to notify. Empty list if resolution fails.
        """
        pass

    def _log_warning(self, message: str, **kwargs):
        """Log a warning with context. Used for fail-safe error handling."""
        log.warning(
            f"[{self.__class__.__name__}] {message}",
            extra=kwargs
        )

    def _log_info(self, message: str, **kwargs):
        """Log info with context."""
        log.info(
            f"[{self.__class__.__name__}] {message}",
            extra=kwargs
        )


class LeadOwnerResolver(BaseResolver):
    """
    Resolves the owner (assigned officer) of a lead.

    Expected payload keys:
        - lead_id: int (to look up the assigned officer)
        - officer_id: int (direct specification, takes precedence)

    Returns:
        - [officer_id] if officer is assigned
        - [] if lead has no assigned officer or lookup fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            # First check if officer_id is directly provided
            officer_id = payload.get("officer_id")
            if officer_id:
                self._log_info(
                    f"Resolved officer_id={officer_id} from payload directly"
                )
                return [officer_id]

            # Otherwise, look up from lead_id
            lead_id = payload.get("lead_id")
            if not lead_id:
                self._log_warning(
                    "Neither officer_id nor lead_id provided in payload",
                    payload_keys=list(payload.keys())
                )
                return []

            # Query lead to get assigned officer
            result = await db.execute(
                select(models.Lead.assigned_officer_id)
                .where(models.Lead.id == lead_id)
            )
            assigned_officer_id = result.scalar_one_or_none()

            if not assigned_officer_id:
                self._log_info(
                    f"Lead {lead_id} has no assigned officer"
                )
                return []

            self._log_info(
                f"Resolved officer_id={assigned_officer_id} for lead_id={lead_id}"
            )
            return [assigned_officer_id]

        except Exception as e:
            self._log_warning(
                f"Failed to resolve lead owner: {str(e)}",
                payload=payload
            )
            return []


class UnitStaffResolver(BaseResolver):
    """
    Resolves all staff members in a unit.

    Expected payload keys:
        - unit_id: int (required)
        - roles: List[str] (optional, filter by roles, default: all active)
        - exclude_user_id: int (optional, exclude this user from results)

    Returns:
        - List of user IDs in the unit with active assignments
        - [] if unit_id not provided or query fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            unit_id = payload.get("unit_id")
            if not unit_id:
                self._log_warning(
                    "unit_id not provided in payload",
                    payload_keys=list(payload.keys())
                )
                return []

            roles = payload.get("roles")  # Optional role filter
            exclude_user_id = payload.get("exclude_user_id")

            # Build query for active unit assignments
            query = select(models.UserUnitAssignment.user_id).where(
                and_(
                    models.UserUnitAssignment.unit_id == unit_id,
                    models.UserUnitAssignment.is_active == True  # noqa: E712
                )
            )

            # Filter by roles if specified
            if roles:
                query = query.where(models.UserUnitAssignment.role.in_(roles))

            result = await db.execute(query)
            user_ids = [row[0] for row in result.fetchall()]

            # Exclude specific user if requested
            if exclude_user_id and exclude_user_id in user_ids:
                user_ids.remove(exclude_user_id)

            self._log_info(
                f"Resolved {len(user_ids)} staff members for unit_id={unit_id}",
                roles=roles
            )
            return user_ids

        except Exception as e:
            self._log_warning(
                f"Failed to resolve unit staff: {str(e)}",
                payload=payload
            )
            return []


class UnitManagersResolver(BaseResolver):
    """
    Resolves managers and admins in a unit.

    Expected payload keys:
        - unit_id: int (required)
        - exclude_user_id: int (optional)

    Returns:
        - List of user IDs with manager/admin roles in the unit
        - [] if unit_id not provided or query fails
    """

    MANAGER_ROLES = [UserRole.MANAGER, UserRole.ADMIN]

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            unit_id = payload.get("unit_id")
            if not unit_id:
                self._log_warning(
                    "unit_id not provided in payload",
                    payload_keys=list(payload.keys())
                )
                return []

            exclude_user_id = payload.get("exclude_user_id")

            # Query managers/admins in the unit
            query = select(models.UserUnitAssignment.user_id).where(
                and_(
                    models.UserUnitAssignment.unit_id == unit_id,
                    models.UserUnitAssignment.is_active == True,  # noqa: E712
                    models.UserUnitAssignment.role.in_(self.MANAGER_ROLES)
                )
            )

            result = await db.execute(query)
            user_ids = [row[0] for row in result.fetchall()]

            # Exclude specific user if requested
            if exclude_user_id and exclude_user_id in user_ids:
                user_ids.remove(exclude_user_id)

            self._log_info(
                f"Resolved {len(user_ids)} managers for unit_id={unit_id}"
            )
            return user_ids

        except Exception as e:
            self._log_warning(
                f"Failed to resolve unit managers: {str(e)}",
                payload=payload
            )
            return []


class DormResidentsResolver(BaseResolver):
    """
    Resolves all residents of a dormitory.

    Expected payload keys:
        - dorm_id: int (required)
        - room_id: int (optional, filter by specific room)

    Note: This is a placeholder for future Dorm module integration.
    Currently returns empty list until Dorm models are implemented.

    Returns:
        - List of user IDs who are residents
        - [] if dorm_id not provided or query fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            dorm_id = payload.get("dorm_id")
            if not dorm_id:
                self._log_warning(
                    "dorm_id not provided in payload",
                    payload_keys=list(payload.keys())
                )
                return []

            # TODO: Implement when Dorm module is available
            # For now, check if DormResident model exists
            if not hasattr(models, "DormResident"):
                self._log_info(
                    "DormResident model not yet implemented, returning empty list"
                )
                return []

            # Future implementation:
            # room_id = payload.get("room_id")
            # query = select(models.DormResident.user_id).where(
            #     models.DormResident.dorm_id == dorm_id
            # )
            # if room_id:
            #     query = query.where(models.DormResident.room_id == room_id)
            # result = await db.execute(query)
            # return [row[0] for row in result.fetchall()]

            return []

        except Exception as e:
            self._log_warning(
                f"Failed to resolve dorm residents: {str(e)}",
                payload=payload
            )
            return []


class DormStaffResolver(BaseResolver):
    """
    Resolves dorm management staff.

    Expected payload keys:
        - dorm_id: int (optional, filter by specific dorm)

    Note: This is a placeholder for future Dorm module integration.

    Returns:
        - List of user IDs who are dorm staff
        - [] if query fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            # TODO: Implement when Dorm module is available
            if not hasattr(models, "DormStaff"):
                self._log_info(
                    "DormStaff model not yet implemented, returning empty list"
                )
                return []

            return []

        except Exception as e:
            self._log_warning(
                f"Failed to resolve dorm staff: {str(e)}",
                payload=payload
            )
            return []


class AllUsersResolver(BaseResolver):
    """
    Resolves all active users in the system.

    Expected payload keys:
        - exclude_user_ids: List[int] (optional, users to exclude)
        - roles: List[str] (optional, filter by roles)

    Use sparingly - this can generate a large number of notifications.

    Returns:
        - List of all active user IDs
        - [] if query fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            exclude_user_ids = payload.get("exclude_user_ids", [])
            roles = payload.get("roles")

            # Build base query for active users
            query = select(models.User.id).where(
                models.User.status == "active"
            )

            # Filter by roles if specified
            if roles:
                query = query.where(models.User.role.in_(roles))

            # Exclude specific users
            if exclude_user_ids:
                query = query.where(~models.User.id.in_(exclude_user_ids))

            # Safety cap to prevent OOM on large user bases
            ALL_USERS_CAP = 5000
            query = query.limit(ALL_USERS_CAP)

            result = await db.execute(query)
            user_ids = [row[0] for row in result.fetchall()]

            if len(user_ids) >= ALL_USERS_CAP:
                self._log_warning(
                    f"AllUsersResolver hit cap ({ALL_USERS_CAP}). Some users may not receive notification.",
                    roles=roles,
                    excluded_count=len(exclude_user_ids),
                    cap=ALL_USERS_CAP,
                )
            else:
                self._log_info(
                    f"Resolved {len(user_ids)} active users",
                    roles=roles,
                    excluded_count=len(exclude_user_ids)
                )
            return user_ids

        except Exception as e:
            self._log_warning(
                f"Failed to resolve all users: {str(e)}",
                payload=payload
            )
            return []


class AllAdminsResolver(BaseResolver):
    """
    Resolves all admin users in the system.

    Expected payload keys:
        - exclude_user_id: int (optional, user to exclude)

    Returns:
        - List of all admin user IDs
        - [] if query fails
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            exclude_user_id = payload.get("exclude_user_id")

            # Query admin users
            query = select(models.User.id).where(
                and_(
                    models.User.status == "active",
                    models.User.role == UserRole.ADMIN
                )
            )

            if exclude_user_id:
                query = query.where(models.User.id != exclude_user_id)

            result = await db.execute(query)
            user_ids = [row[0] for row in result.fetchall()]

            self._log_info(f"Resolved {len(user_ids)} admin users")
            return user_ids

        except Exception as e:
            self._log_warning(
                f"Failed to resolve admins: {str(e)}",
                payload=payload
            )
            return []


class SpecificUsersResolver(BaseResolver):
    """
    Returns specific user IDs from the payload.

    Expected payload keys:
        - user_ids: List[int] (required)
        - user_id: int (alternative, single user)

    Useful for events where the recipients are already known.

    Returns:
        - List of user IDs from payload
        - [] if no user IDs provided
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            # Check for user_ids list first
            user_ids = payload.get("user_ids", [])
            if user_ids:
                self._log_info(f"Resolved {len(user_ids)} specific users from payload")
                return user_ids

            # Fallback to single user_id
            user_id = payload.get("user_id")
            if user_id:
                self._log_info(f"Resolved single user_id={user_id} from payload")
                return [user_id]

            self._log_warning(
                "Neither user_ids nor user_id provided in payload",
                payload_keys=list(payload.keys())
            )
            return []

        except Exception as e:
            self._log_warning(
                f"Failed to resolve specific users: {str(e)}",
                payload=payload
            )
            return []


class CompositeResolver(BaseResolver):
    """
    Combines multiple resolvers, merging their results.

    This allows an event to notify multiple groups of users
    (e.g., both the assigned officer AND unit managers).

    Usage:
        resolver = CompositeResolver([
            LeadOwnerResolver(),
            UnitManagersResolver()
        ])
        user_ids = await resolver.resolve_users(db, payload)
    """

    def __init__(self, resolvers: List[BaseResolver]):
        """
        Initialize with a list of resolvers to combine.

        Args:
            resolvers: List of BaseResolver instances
        """
        self.resolvers = resolvers

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            all_user_ids: Set[int] = set()

            for resolver in self.resolvers:
                user_ids = await resolver.resolve_users(db, payload)
                all_user_ids.update(user_ids)

            result = list(all_user_ids)
            self._log_info(
                f"Composite resolver merged {len(result)} unique users "
                f"from {len(self.resolvers)} resolvers"
            )
            return result

        except Exception as e:
            self._log_warning(
                f"Failed in composite resolution: {str(e)}",
                payload=payload
            )
            return []


class ActorExcludedResolver(BaseResolver):
    """
    Wrapper resolver that excludes the actor from results.

    Many events should not notify the user who triggered them.
    This wrapper removes the actor_id from any resolver's results.

    Usage:
        resolver = ActorExcludedResolver(UnitStaffResolver())
        user_ids = await resolver.resolve_users(db, payload)
        # payload["actor_id"] will be excluded from results
    """

    def __init__(self, inner_resolver: BaseResolver):
        """
        Initialize with an inner resolver to wrap.

        Args:
            inner_resolver: The resolver to wrap
        """
        self.inner_resolver = inner_resolver

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            user_ids = await self.inner_resolver.resolve_users(db, payload)

            actor_id = payload.get("actor_id")
            if actor_id and actor_id in user_ids:
                user_ids.remove(actor_id)
                self._log_info(f"Excluded actor_id={actor_id} from results")

            return user_ids

        except Exception as e:
            self._log_warning(
                f"Failed in actor-excluded resolution: {str(e)}",
                payload=payload
            )
            return []


class CollaboratorUserResolver(BaseResolver):
    """
    Resolves the user linked to a collaborator.

    Expected payload keys:
        - collaborator_id (int): Required - ID of the collaborator
        - user_id (int): Optional - Direct user_id if available (avoids DB query)

    Returns:
        [user_id] if collaborator has a linked user, [] otherwise.

    Fail-safe: Returns empty list on any error.
    """

    async def resolve_users(
        self,
        db: AsyncSession,
        payload: dict
    ) -> List[int]:
        try:
            # Fast path: user_id already in payload
            user_id = payload.get("user_id")
            if user_id:
                return [user_id]

            # Slow path: query collaborator
            collaborator_id = payload.get("collaborator_id")
            if not collaborator_id:
                self._log_warning("Missing collaborator_id in payload")
                return []

            from app.models.collaborator import Collaborator
            result = await db.execute(
                select(Collaborator.user_id).where(
                    Collaborator.id == collaborator_id,
                    Collaborator.user_id.isnot(None),
                    Collaborator.deleted_at.is_(None),
                )
            )
            uid = result.scalar_one_or_none()
            if uid:
                return [uid]
            return []
        except Exception as e:
            self._log_warning(f"Failed to resolve collaborator user: {e}")
            return []


# Singleton instances for common resolvers (can be reused)
lead_owner_resolver = LeadOwnerResolver()
unit_staff_resolver = UnitStaffResolver()
unit_managers_resolver = UnitManagersResolver()
collaborator_user_resolver = CollaboratorUserResolver()
dorm_residents_resolver = DormResidentsResolver()
dorm_staff_resolver = DormStaffResolver()
all_users_resolver = AllUsersResolver()
all_admins_resolver = AllAdminsResolver()
specific_users_resolver = SpecificUsersResolver()


# ============================================
# ✅ NOTIFICATION 2.0: RESOLVER REGISTRY
# ============================================
# Maps metadata resolver_type strings to resolver instances


RESOLVER_REGISTRY = {
    # Lead/Application resolvers
    "assigned_officer": lead_owner_resolver,
    "lead_owner": lead_owner_resolver,  # Alias

    # Unit resolvers
    "unit_staff": unit_staff_resolver,
    "unit_officers": unit_staff_resolver,  # Alias
    "unit_managers": unit_managers_resolver,
    "all_managers": unit_managers_resolver,  # Alias

    # Dorm resolvers
    "dorm_residents": dorm_residents_resolver,
    "dorm_staff": dorm_staff_resolver,

    # Collaborator resolvers
    "collaborator_user": collaborator_user_resolver,

    # Global resolvers
    "all_users": all_users_resolver,
    "all_officers": all_users_resolver,  # Filtered by roles param
    "all_admins": all_admins_resolver,
    "specific_users": specific_users_resolver,
}


def get_resolver(resolver_type: str) -> Optional[BaseResolver]:
    """
    Get resolver instance by type name.

    Args:
        resolver_type: Resolver type from metadata (e.g., "assigned_officer")

    Returns:
        Resolver instance or None if not found

    Example:
        resolver = get_resolver("assigned_officer")
        if resolver:
            user_ids = await resolver.resolve_users(db, payload)
    """
    return RESOLVER_REGISTRY.get(resolver_type)
