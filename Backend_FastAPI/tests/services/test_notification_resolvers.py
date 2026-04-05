# tests/services/test_notification_resolvers.py
"""
Integration tests for notification resolvers.

These tests verify that resolvers correctly determine notification recipients
based on event payloads and real database state.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.services.notification_resolvers import (
    LeadOwnerResolver,
    UnitStaffResolver,
    UnitManagersResolver,
    AllUsersResolver,
    AllAdminsResolver,
    CollaboratorUserResolver,
    SpecificUsersResolver,
    CompositeResolver,
    ActorExcludedResolver,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestNotificationResolvers:
    """Integration tests for notification resolvers using real database."""

    # =========================================================================
    # LEAD OWNER RESOLVER
    # =========================================================================

    async def test_lead_owner_resolver_direct_officer_id(self, db: AsyncSession):
        """Should return officer_id directly from payload if provided."""
        resolver = LeadOwnerResolver()
        payload = {"lead_id": 1, "officer_id": 42}

        result = await resolver.resolve_users(db, payload)

        assert result == [42]

    async def test_lead_owner_resolver_db_lookup(
        self, 
        db: AsyncSession, 
        seeded_lead: models.Lead
    ):
        """Should query lead to find assigned officer from real DB."""
        resolver = LeadOwnerResolver()
        payload = {"lead_id": seeded_lead.id}

        result = await resolver.resolve_users(db, payload)

        assert result == [seeded_lead.assigned_officer_id]
        assert seeded_lead.assigned_officer_id is not None

    async def test_lead_owner_resolver_no_officer(
        self, 
        db: AsyncSession, 
        unassigned_lead: models.Lead
    ):
        """Should return empty list if lead has no assigned officer."""
        resolver = LeadOwnerResolver()
        payload = {"lead_id": unassigned_lead.id}

        result = await resolver.resolve_users(db, payload)

        assert result == []

    # =========================================================================
    # UNIT STAFF RESOLVER
    # =========================================================================

    async def test_unit_staff_resolver(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should resolve all staff members in a unit."""
        # Arrange - get officer and their unit
        officer = await db.get(models.User, officer_user_in_db["id"])
        unit_id = officer.unit_id

        # Seed UserUnitAssignment (source of truth for resolver)
        assignment = models.UserUnitAssignment(
            user_id=officer.id,
            unit_id=unit_id,
            role=UserRole.OFFICER,
            is_active=True
        )
        db.add(assignment)
        await db.commit()

        resolver = UnitStaffResolver()
        payload = {"unit_id": unit_id}

        # Act
        result = await resolver.resolve_users(db, payload)

        # Assert
        assert officer.id in result
        assert len(result) >= 1

    async def test_unit_staff_resolver_exclude_actor(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should exclude specific user if requested."""
        officer = await db.get(models.User, officer_user_in_db["id"])
        unit_id = officer.unit_id

        # Seed assignment
        assignment = models.UserUnitAssignment(
            user_id=officer.id,
            unit_id=unit_id,
            role=UserRole.OFFICER,
            is_active=True
        )
        db.add(assignment)
        await db.commit()

        resolver = UnitStaffResolver()
        payload = {"unit_id": unit_id, "exclude_user_id": officer.id}

        result = await resolver.resolve_users(db, payload)

        assert officer.id not in result

    # =========================================================================
    # UNIT MANAGERS RESOLVER
    # =========================================================================

    async def test_unit_managers_resolver(
        self, 
        db: AsyncSession, 
        manager_user_in_db: dict
    ):
        """Should resolve managers/admins in a unit."""
        manager = await db.get(models.User, manager_user_in_db["id"])
        unit_id = manager.unit_id

        # Seed Assignment
        assignment = models.UserUnitAssignment(
            user_id=manager.id,
            unit_id=unit_id,
            role=UserRole.MANAGER,
            is_active=True
        )
        db.add(assignment)
        await db.commit()

        resolver = UnitManagersResolver()
        payload = {"unit_id": unit_id}

        result = await resolver.resolve_users(db, payload)

        assert manager.id in result

    # =========================================================================
    # GLOBAL RESOLVERS
    # =========================================================================

    async def test_all_users_resolver(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        admin_user_in_db: dict
    ):
        """Should resolve all active users."""
        resolver = AllUsersResolver()
        payload = {}

        result = await resolver.resolve_users(db, payload)

        assert officer_user_in_db["id"] in result
        assert admin_user_in_db["id"] in result
        assert len(result) >= 2

    async def test_all_admins_resolver(
        self, 
        db: AsyncSession, 
        admin_user_in_db: dict,
        officer_user_in_db: dict
    ):
        """Should resolve only admin users."""
        resolver = AllAdminsResolver()
        payload = {}

        result = await resolver.resolve_users(db, payload)

        assert admin_user_in_db["id"] in result
        assert officer_user_in_db["id"] not in result

    async def test_specific_users_resolver(self, db: AsyncSession):
        """Should return user_ids from payload."""
        resolver = SpecificUsersResolver()
        payload = {"user_ids": [10, 20, 30]}

        result = await resolver.resolve_users(db, payload)

        assert result == [10, 20, 30]

    async def test_collaborator_user_resolver_direct_user_id(self, db: AsyncSession):
        """Should reuse user_id from payload without extra DB lookup."""
        resolver = CollaboratorUserResolver()

        result = await resolver.resolve_users(db, {"user_id": 77})

        assert result == [77]

    # =========================================================================
    # COMPOSITE & WRAPPER RESOLVERS
    # =========================================================================

    async def test_composite_resolver(self, db: AsyncSession):
        """Should merge results from multiple resolvers."""
        class MockResolver:
            def __init__(self, ids): self.ids = ids
            async def resolve_users(self, db, payload): return self.ids

        resolver = CompositeResolver([
            MockResolver([1, 2]),
            MockResolver([2, 3])
        ])

        result = await resolver.resolve_users(db, {})
        assert set(result) == {1, 2, 3}
        assert len(result) == 3

    async def test_actor_excluded_resolver(self, db: AsyncSession):
        """Should remove actor_id from results."""
        class MockResolver:
            async def resolve_users(self, db, payload): return [1, 2, 3]

        resolver = ActorExcludedResolver(MockResolver())
        payload = {"actor_id": 2}

        result = await resolver.resolve_users(db, payload)

        assert result == [1, 3]
        assert 2 not in result
