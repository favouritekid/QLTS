# tests/services/test_audit_service.py
"""
Unit tests for audit_service.py

Tests the generic entity audit logging functionality.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import audit_service
from app import models


# ============================================================================
# TEST: log_audit (core function)
# ============================================================================

class TestLogAudit:
    """Tests for the core log_audit function."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_audit_creates_entry_with_required_fields(self, mock_db):
        """Test that log_audit creates entry with required fields."""
        result = await audit_service.log_audit(
            db=mock_db,
            entity_type="Lead",
            entity_id=123,
            action="created",
        )

        assert isinstance(result, models.EntityAuditLog)
        assert result.entity_type == "Lead"
        assert result.entity_id == 123
        assert result.action == "created"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_audit_creates_entry_with_all_fields(self, mock_db):
        """Test that log_audit creates entry with all optional fields."""
        result = await audit_service.log_audit(
            db=mock_db,
            entity_type="Consultation",
            entity_id=456,
            action="updated",
            actor_user_id=10,
            field_name="status",
            old_value="draft",
            new_value="submitted",
            changes={"status": {"old": "draft", "new": "submitted"}},
            reason="User submitted the form",
            source="api",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert result.entity_type == "Consultation"
        assert result.entity_id == 456
        assert result.action == "updated"
        assert result.actor_user_id == 10
        assert result.field_name == "status"
        assert result.old_value == "draft"
        assert result.new_value == "submitted"
        assert result.changes == {"status": {"old": "draft", "new": "submitted"}}
        assert result.reason == "User submitted the form"
        assert result.source == "api"
        assert result.ip_address == "192.168.1.1"
        assert result.user_agent == "Mozilla/5.0"
        assert result.created_at is not None

    @pytest.mark.asyncio
    async def test_log_audit_sets_created_at_timestamp(self, mock_db):
        """Test that log_audit sets created_at to current UTC time."""
        before = datetime.now(timezone.utc)

        result = await audit_service.log_audit(
            db=mock_db,
            entity_type="Lead",
            entity_id=1,
            action="created",
        )

        after = datetime.now(timezone.utc)
        assert before <= result.created_at <= after


# ============================================================================
# TEST: log_field_change
# ============================================================================

class TestLogFieldChange:
    """Tests for log_field_change convenience function."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_field_change_creates_entry(self, mock_db):
        """Test log_field_change creates proper audit entry."""
        result = await audit_service.log_field_change(
            db=mock_db,
            entity_type="Lead",
            entity_id=100,
            field_name="email",
            old_value="old@example.com",
            new_value="new@example.com",
            actor_user_id=5,
        )

        assert result.entity_type == "Lead"
        assert result.entity_id == 100
        assert result.action == "updated"
        assert result.field_name == "email"
        assert result.old_value == "old@example.com"
        assert result.new_value == "new@example.com"
        assert result.actor_user_id == 5
        assert result.source == "api"

    @pytest.mark.asyncio
    async def test_log_field_change_with_custom_source(self, mock_db):
        """Test log_field_change with custom source."""
        result = await audit_service.log_field_change(
            db=mock_db,
            entity_type="Lead",
            entity_id=100,
            field_name="status",
            old_value="new",
            new_value="contacted",
            source="admin_panel",
        )

        assert result.source == "admin_panel"


# ============================================================================
# TEST: log_changes (bulk changes)
# ============================================================================

class TestLogChanges:
    """Tests for log_changes function (multiple field changes)."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_changes_creates_entry_with_changeset(self, mock_db):
        """Test log_changes stores multiple field changes."""
        changes = {
            "full_name": {"old": "John Doe", "new": "John Smith"},
            "phone": {"old": "0901234567", "new": "0907654321"},
            "email": {"old": None, "new": "john@example.com"},
        }

        result = await audit_service.log_changes(
            db=mock_db,
            entity_type="Lead",
            entity_id=200,
            action="updated",
            changes=changes,
            actor_user_id=3,
        )

        assert result.entity_type == "Lead"
        assert result.entity_id == 200
        assert result.action == "updated"
        assert result.changes == changes
        assert result.actor_user_id == 3

    @pytest.mark.asyncio
    async def test_log_changes_with_reason(self, mock_db):
        """Test log_changes with reason field."""
        result = await audit_service.log_changes(
            db=mock_db,
            entity_type="AdmissionProfile",
            entity_id=50,
            action="status_changed",
            changes={"status": {"old": "draft", "new": "submitted"}},
            reason="User submitted the application",
        )

        assert result.reason == "User submitted the application"


# ============================================================================
# TEST: log_created
# ============================================================================

class TestLogCreated:
    """Tests for log_created convenience function."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_created_creates_entry(self, mock_db):
        """Test log_created creates proper audit entry."""
        new_values = {
            "full_name": "Test User",
            "phone": "0901234567",
            "email": "test@example.com",
        }

        result = await audit_service.log_created(
            db=mock_db,
            entity_type="Lead",
            entity_id=999,
            actor_user_id=1,
            new_values=new_values,
        )

        assert result.entity_type == "Lead"
        assert result.entity_id == 999
        assert result.action == "created"
        assert result.actor_user_id == 1
        assert result.new_value == new_values

    @pytest.mark.asyncio
    async def test_log_created_without_actor(self, mock_db):
        """Test log_created with system action (no actor)."""
        result = await audit_service.log_created(
            db=mock_db,
            entity_type="Notification",
            entity_id=500,
            new_values={"event": "lead_created"},
        )

        assert result.actor_user_id is None
        assert result.action == "created"


# ============================================================================
# TEST: log_deleted
# ============================================================================

class TestLogDeleted:
    """Tests for log_deleted convenience function."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_deleted_creates_entry(self, mock_db):
        """Test log_deleted creates proper audit entry."""
        old_values = {
            "full_name": "Deleted User",
            "phone": "0901234567",
            "status": "active",
        }

        result = await audit_service.log_deleted(
            db=mock_db,
            entity_type="Lead",
            entity_id=888,
            actor_user_id=1,
            old_values=old_values,
            reason="User requested deletion",
        )

        assert result.entity_type == "Lead"
        assert result.entity_id == 888
        assert result.action == "deleted"
        assert result.actor_user_id == 1
        assert result.old_value == old_values
        assert result.reason == "User requested deletion"


# ============================================================================
# TEST: log_status_change
# ============================================================================

class TestLogStatusChange:
    """Tests for log_status_change convenience function."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_status_change_creates_entry(self, mock_db):
        """Test log_status_change creates proper audit entry."""
        result = await audit_service.log_status_change(
            db=mock_db,
            entity_type="AdmissionProfile",
            entity_id=777,
            old_status="draft",
            new_status="submitted",
            actor_user_id=5,
            reason="User submitted application",
        )

        assert result.entity_type == "AdmissionProfile"
        assert result.entity_id == 777
        assert result.action == "status_changed"
        assert result.field_name == "status"
        assert result.old_value == "draft"
        assert result.new_value == "submitted"
        assert result.actor_user_id == 5
        assert result.reason == "User submitted application"


# ============================================================================
# TEST: detect_changes
# ============================================================================

class TestDetectChanges:
    """Tests for detect_changes utility function."""

    def test_detect_changes_with_dicts(self):
        """Test detect_changes with dictionary objects."""
        old = {"name": "John", "email": "john@example.com", "phone": "123"}
        new = {"name": "John", "email": "john.doe@example.com", "phone": "123"}

        changes = audit_service.detect_changes(old, new)

        assert "email" in changes
        assert changes["email"]["old"] == "john@example.com"
        assert changes["email"]["new"] == "john.doe@example.com"
        assert "name" not in changes
        assert "phone" not in changes

    def test_detect_changes_no_changes(self):
        """Test detect_changes when objects are identical."""
        old = {"name": "John", "email": "john@example.com"}
        new = {"name": "John", "email": "john@example.com"}

        changes = audit_service.detect_changes(old, new)

        assert changes == {}

    def test_detect_changes_with_specific_fields(self):
        """Test detect_changes with specific fields filter."""
        old = {"name": "John", "email": "old@example.com", "phone": "111"}
        new = {"name": "Jane", "email": "new@example.com", "phone": "222"}

        # Only check name and email
        changes = audit_service.detect_changes(old, new, fields=["name", "email"])

        assert "name" in changes
        assert "email" in changes
        assert "phone" not in changes

    def test_detect_changes_with_exclude_fields(self):
        """Test detect_changes with excluded fields."""
        old = {"name": "John", "email": "old@example.com", "updated_at": "2024-01-01"}
        new = {"name": "Jane", "email": "old@example.com", "updated_at": "2024-01-02"}

        changes = audit_service.detect_changes(
            old, new, exclude_fields=["updated_at"]
        )

        assert "name" in changes
        assert "updated_at" not in changes

    def test_detect_changes_with_none_values(self):
        """Test detect_changes handles None values correctly."""
        old = {"name": "John", "phone": None}
        new = {"name": "John", "phone": "0901234567"}

        changes = audit_service.detect_changes(old, new)

        assert "phone" in changes
        assert changes["phone"]["old"] is None
        assert changes["phone"]["new"] == "0901234567"

    def test_detect_changes_serializes_datetime(self):
        """Test detect_changes serializes datetime values."""
        dt1 = datetime(2024, 1, 1, 12, 0, 0)
        dt2 = datetime(2024, 6, 15, 15, 30, 0)

        old = {"created_at": dt1}
        new = {"created_at": dt2}

        # Exclude the auto-excluded created_at and test with a custom datetime field
        old = {"scheduled_at": dt1}
        new = {"scheduled_at": dt2}

        changes = audit_service.detect_changes(old, new)

        assert "scheduled_at" in changes
        assert changes["scheduled_at"]["old"] == dt1.isoformat()
        assert changes["scheduled_at"]["new"] == dt2.isoformat()


# ============================================================================
# TEST: extract_audit_fields
# ============================================================================

class TestExtractAuditFields:
    """Tests for extract_audit_fields utility function."""

    def test_extract_audit_fields_from_dict(self):
        """Test extracting fields from a dictionary."""
        obj = {"name": "John", "email": "john@example.com", "phone": "123"}

        result = audit_service.extract_audit_fields(obj, fields=["name", "email"])

        assert result == {"name": "John", "email": "john@example.com"}
        assert "phone" not in result

    def test_extract_audit_fields_all_fields(self):
        """Test extracting all fields without filter."""
        obj = {"name": "John", "email": "john@example.com"}

        result = audit_service.extract_audit_fields(obj)

        assert "name" in result
        assert "email" in result

    def test_extract_audit_fields_with_exclude(self):
        """Test extracting fields with exclusions."""
        obj = {"name": "John", "password": "secret", "email": "john@example.com"}

        result = audit_service.extract_audit_fields(obj, exclude_fields=["password"])

        assert "name" in result
        assert "email" in result
        assert "password" not in result


# ============================================================================
# TEST: _serialize_value (internal helper)
# ============================================================================

class TestSerializeValue:
    """Tests for the internal _serialize_value function."""

    def test_serialize_none(self):
        """Test serializing None."""
        assert audit_service._serialize_value(None) is None

    def test_serialize_primitives(self):
        """Test serializing primitive types."""
        assert audit_service._serialize_value("hello") == "hello"
        assert audit_service._serialize_value(123) == 123
        assert audit_service._serialize_value(12.5) == 12.5
        assert audit_service._serialize_value(True) is True

    def test_serialize_datetime(self):
        """Test serializing datetime."""
        dt = datetime(2024, 6, 15, 12, 30, 45)
        assert audit_service._serialize_value(dt) == dt.isoformat()

    def test_serialize_list(self):
        """Test serializing list."""
        result = audit_service._serialize_value([1, 2, 3])
        assert result == [1, 2, 3]

    def test_serialize_dict(self):
        """Test serializing dict."""
        result = audit_service._serialize_value({"key": "value"})
        assert result == {"key": "value"}

    def test_serialize_enum(self):
        """Test serializing enum-like objects."""
        class MockEnum:
            value = "enum_value"

        result = audit_service._serialize_value(MockEnum())
        assert result == "enum_value"
