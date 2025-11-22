# tests/services/test_notification_resolvers.py
"""
Unit tests for notification resolvers.

These tests verify that resolvers correctly determine notification recipients
based on event payloads and database state.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.notification_resolvers import (
    LeadOwnerResolver,
    UnitStaffResolver,
    UnitManagersResolver,
    AllUsersResolver,
    AllAdminsResolver,
    SpecificUsersResolver,
    CompositeResolver,
    ActorExcludedResolver,
)


# =============================================================================
# LEAD OWNER RESOLVER TESTS
# =============================================================================

class TestLeadOwnerResolver:
    """Tests for LeadOwnerResolver."""

    @pytest.fixture
    def resolver(self):
        return LeadOwnerResolver()

    @pytest.mark.asyncio
    async def test_resolve_with_officer_id_in_payload(self, resolver):
        """Should return officer_id directly from payload."""
        db = AsyncMock()
        payload = {"lead_id": 1, "officer_id": 42}

        result = await resolver.resolve_users(db, payload)

        assert result == [42]
        # DB should not be queried when officer_id is provided
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_with_lead_id_lookup(self, resolver):
        """Should query lead to find assigned officer."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 123
        db.execute.return_value = mock_result

        payload = {"lead_id": 1}
        result = await resolver.resolve_users(db, payload)

        assert result == [123]
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_with_no_assigned_officer(self, resolver):
        """Should return empty list if lead has no assigned officer."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        payload = {"lead_id": 1}
        result = await resolver.resolve_users(db, payload)

        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_with_missing_payload(self, resolver):
        """Should return empty list if neither lead_id nor officer_id provided."""
        db = AsyncMock()
        payload = {}

        result = await resolver.resolve_users(db, payload)

        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_fail_safe_on_exception(self, resolver):
        """Should return empty list on database error."""
        db = AsyncMock()
        db.execute.side_effect = Exception("Database error")

        payload = {"lead_id": 1}
        result = await resolver.resolve_users(db, payload)

        assert result == []


# =============================================================================
# UNIT STAFF RESOLVER TESTS
# =============================================================================

class TestUnitStaffResolver:
    """Tests for UnitStaffResolver."""

    @pytest.fixture
    def resolver(self):
        return UnitStaffResolver()

    @pytest.mark.asyncio
    async def test_resolve_unit_staff(self, resolver):
        """Should return all staff in a unit."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,), (2,), (3,)]
        db.execute.return_value = mock_result

        payload = {"unit_id": 10}
        result = await resolver.resolve_users(db, payload)

        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_resolve_with_exclude_user(self, resolver):
        """Should exclude specific user from results."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,), (2,), (3,)]
        db.execute.return_value = mock_result

        payload = {"unit_id": 10, "exclude_user_id": 2}
        result = await resolver.resolve_users(db, payload)

        assert result == [1, 3]
        assert 2 not in result

    @pytest.mark.asyncio
    async def test_resolve_without_unit_id(self, resolver):
        """Should return empty list if unit_id not provided."""
        db = AsyncMock()
        payload = {}

        result = await resolver.resolve_users(db, payload)

        assert result == []


# =============================================================================
# UNIT MANAGERS RESOLVER TESTS
# =============================================================================

class TestUnitManagersResolver:
    """Tests for UnitManagersResolver."""

    @pytest.fixture
    def resolver(self):
        return UnitManagersResolver()

    @pytest.mark.asyncio
    async def test_resolve_managers_only(self, resolver):
        """Should return only manager/admin users."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(10,), (20,)]
        db.execute.return_value = mock_result

        payload = {"unit_id": 5}
        result = await resolver.resolve_users(db, payload)

        assert result == [10, 20]


# =============================================================================
# ALL USERS RESOLVER TESTS
# =============================================================================

class TestAllUsersResolver:
    """Tests for AllUsersResolver."""

    @pytest.fixture
    def resolver(self):
        return AllUsersResolver()

    @pytest.mark.asyncio
    async def test_resolve_all_active_users(self, resolver):
        """Should return all active users."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,), (2,), (3,), (4,)]
        db.execute.return_value = mock_result

        payload = {}
        result = await resolver.resolve_users(db, payload)

        assert result == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_resolve_with_exclusions(self, resolver):
        """Should exclude specified users."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,), (3,), (4,)]
        db.execute.return_value = mock_result

        payload = {"exclude_user_ids": [2]}
        result = await resolver.resolve_users(db, payload)

        assert 2 not in result


# =============================================================================
# ALL ADMINS RESOLVER TESTS
# =============================================================================

class TestAllAdminsResolver:
    """Tests for AllAdminsResolver."""

    @pytest.fixture
    def resolver(self):
        return AllAdminsResolver()

    @pytest.mark.asyncio
    async def test_resolve_admin_users(self, resolver):
        """Should return only admin users."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(100,), (200,)]
        db.execute.return_value = mock_result

        payload = {}
        result = await resolver.resolve_users(db, payload)

        assert result == [100, 200]


# =============================================================================
# SPECIFIC USERS RESOLVER TESTS
# =============================================================================

class TestSpecificUsersResolver:
    """Tests for SpecificUsersResolver."""

    @pytest.fixture
    def resolver(self):
        return SpecificUsersResolver()

    @pytest.mark.asyncio
    async def test_resolve_user_ids_list(self, resolver):
        """Should return user_ids from payload."""
        db = AsyncMock()
        payload = {"user_ids": [1, 2, 3]}

        result = await resolver.resolve_users(db, payload)

        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_resolve_single_user_id(self, resolver):
        """Should return single user_id from payload."""
        db = AsyncMock()
        payload = {"user_id": 42}

        result = await resolver.resolve_users(db, payload)

        assert result == [42]

    @pytest.mark.asyncio
    async def test_resolve_empty_without_users(self, resolver):
        """Should return empty list if no users specified."""
        db = AsyncMock()
        payload = {"some_other_field": "value"}

        result = await resolver.resolve_users(db, payload)

        assert result == []


# =============================================================================
# COMPOSITE RESOLVER TESTS
# =============================================================================

class TestCompositeResolver:
    """Tests for CompositeResolver."""

    @pytest.mark.asyncio
    async def test_merge_results_from_multiple_resolvers(self):
        """Should combine results from all inner resolvers."""
        resolver1 = AsyncMock()
        resolver1.resolve_users.return_value = [1, 2]

        resolver2 = AsyncMock()
        resolver2.resolve_users.return_value = [3, 4]

        composite = CompositeResolver([resolver1, resolver2])
        db = AsyncMock()
        payload = {}

        result = await composite.resolve_users(db, payload)

        assert set(result) == {1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_dedupe_overlapping_results(self):
        """Should deduplicate overlapping user IDs."""
        resolver1 = AsyncMock()
        resolver1.resolve_users.return_value = [1, 2, 3]

        resolver2 = AsyncMock()
        resolver2.resolve_users.return_value = [2, 3, 4]

        composite = CompositeResolver([resolver1, resolver2])
        db = AsyncMock()
        payload = {}

        result = await composite.resolve_users(db, payload)

        assert set(result) == {1, 2, 3, 4}
        assert len(result) == 4  # No duplicates


# =============================================================================
# ACTOR EXCLUDED RESOLVER TESTS
# =============================================================================

class TestActorExcludedResolver:
    """Tests for ActorExcludedResolver."""

    @pytest.mark.asyncio
    async def test_exclude_actor_from_results(self):
        """Should remove actor_id from inner resolver results."""
        inner = AsyncMock()
        inner.resolve_users.return_value = [1, 2, 3, 4]

        excluded = ActorExcludedResolver(inner)
        db = AsyncMock()
        payload = {"actor_id": 2}

        result = await excluded.resolve_users(db, payload)

        assert result == [1, 3, 4]
        assert 2 not in result

    @pytest.mark.asyncio
    async def test_no_exclusion_without_actor_id(self):
        """Should return all results if no actor_id in payload."""
        inner = AsyncMock()
        inner.resolve_users.return_value = [1, 2, 3]

        excluded = ActorExcludedResolver(inner)
        db = AsyncMock()
        payload = {}

        result = await excluded.resolve_users(db, payload)

        assert result == [1, 2, 3]
