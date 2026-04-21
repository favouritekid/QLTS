# tests/unit/test_audit_service.py
"""
Unit tests for Generic Entity Audit Service.

Tests the audit logging utilities including:
- Core logging functions
- Convenience functions (log_field_change, log_created, etc.)
- Change detection utilities
- Value serialization
"""

# Note: overlaps partially with tests/services/test_audit_service.py.
# That file is legacy/misplaced mock-based coverage and is pending dedicated consolidation.
# See Documents/WAVE7_TEST_AUDIT_SERVICE_INVESTIGATION.md for the classification decision.

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from enum import Enum

from app.services.audit_service import (
    log_audit,
    log_field_change,
    log_changes,
    log_created,
    log_deleted,
    log_status_change,
    detect_changes,
    extract_audit_fields,
    _serialize_value,
    _to_dict,
)


class TestSerializeValue:
    """Test _serialize_value helper function."""

    def test_serializes_none(self):
        assert _serialize_value(None) is None

    def test_serializes_primitives(self):
        assert _serialize_value("hello") == "hello"
        assert _serialize_value(123) == 123
        assert _serialize_value(45.67) == 45.67
        assert _serialize_value(True) is True
        assert _serialize_value(False) is False

    def test_serializes_datetime(self):
        dt = datetime(2026, 1, 26, 10, 30, 0, tzinfo=timezone.utc)
        result = _serialize_value(dt)
        assert result == "2026-01-26T10:30:00+00:00"

    def test_serializes_list(self):
        result = _serialize_value([1, "two", 3.0])
        assert result == [1, "two", 3.0]

    def test_serializes_nested_list(self):
        result = _serialize_value([[1, 2], [3, 4]])
        assert result == [[1, 2], [3, 4]]

    def test_serializes_dict(self):
        result = _serialize_value({"a": 1, "b": "two"})
        assert result == {"a": 1, "b": "two"}

    def test_serializes_nested_dict(self):
        result = _serialize_value({"outer": {"inner": "value"}})
        assert result == {"outer": {"inner": "value"}}

    def test_serializes_enum(self):
        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        result = _serialize_value(Status.ACTIVE)
        assert result == "active"

    def test_serializes_unknown_type_to_string(self):
        class CustomClass:
            def __str__(self):
                return "custom_string"

        result = _serialize_value(CustomClass())
        assert result == "custom_string"


class TestToDict:
    """Test _to_dict helper function."""

    def test_dict_passthrough(self):
        original = {"a": 1, "b": 2}
        result = _to_dict(original)
        assert result == original

    def test_object_with_dict(self):
        class SimpleObject:
            def __init__(self):
                self.name = "test"
                self.value = 123
                self._private = "hidden"

        obj = SimpleObject()
        result = _to_dict(obj)
        assert result == {"name": "test", "value": 123}
        assert "_private" not in result

    def test_pydantic_like_model(self):
        class PydanticLike:
            def model_dump(self):
                return {"field1": "value1", "field2": "value2"}

        obj = PydanticLike()
        result = _to_dict(obj)
        assert result == {"field1": "value1", "field2": "value2"}

    def test_empty_object_returns_empty_dict(self):
        result = _to_dict(123)  # int has no __dict__
        assert result == {}


class TestDetectChanges:
    """Test detect_changes utility function."""

    def test_detects_single_change(self):
        old = {"status": "draft", "name": "John"}
        new = {"status": "submitted", "name": "John"}

        changes = detect_changes(old, new)

        assert changes == {"status": {"old": "draft", "new": "submitted"}}

    def test_detects_multiple_changes(self):
        old = {"status": "draft", "name": "John", "email": "john@old.com"}
        new = {"status": "submitted", "name": "John", "email": "john@new.com"}

        changes = detect_changes(old, new)

        assert "status" in changes
        assert "email" in changes
        assert "name" not in changes

    def test_no_changes_returns_empty_dict(self):
        old = {"status": "draft", "name": "John"}
        new = {"status": "draft", "name": "John"}

        changes = detect_changes(old, new)

        assert changes == {}

    def test_filters_by_fields(self):
        old = {"status": "draft", "name": "John", "email": "john@old.com"}
        new = {"status": "submitted", "name": "Jane", "email": "john@new.com"}

        changes = detect_changes(old, new, fields=["status"])

        assert "status" in changes
        assert "name" not in changes
        assert "email" not in changes

    def test_excludes_fields(self):
        old = {"status": "draft", "updated_at": "2026-01-01"}
        new = {"status": "submitted", "updated_at": "2026-01-26"}

        changes = detect_changes(old, new, exclude_fields=["updated_at"])

        assert "status" in changes
        assert "updated_at" not in changes

    def test_auto_excludes_timestamp_fields(self):
        old = {"status": "draft", "created_at": "2026-01-01", "updated_at": "2026-01-01"}
        new = {"status": "submitted", "created_at": "2026-01-01", "updated_at": "2026-01-26"}

        changes = detect_changes(old, new)

        assert "status" in changes
        assert "created_at" not in changes
        assert "updated_at" not in changes

    def test_handles_none_values(self):
        old = {"field": None}
        new = {"field": "value"}

        changes = detect_changes(old, new)

        assert changes == {"field": {"old": None, "new": "value"}}

    def test_handles_new_field(self):
        old = {"status": "draft"}
        new = {"status": "draft", "submitted_at": "2026-01-26"}

        changes = detect_changes(old, new, fields=["status", "submitted_at"])

        assert changes == {"submitted_at": {"old": None, "new": "2026-01-26"}}

    def test_handles_removed_field(self):
        old = {"status": "draft", "temp_field": "value"}
        new = {"status": "draft"}

        changes = detect_changes(old, new, fields=["status", "temp_field"])

        assert changes == {"temp_field": {"old": "value", "new": None}}


class TestExtractAuditFields:
    """Test extract_audit_fields utility function."""

    def test_extracts_all_fields(self):
        obj = {"name": "John", "email": "john@test.com", "status": "active"}

        result = extract_audit_fields(obj)

        assert result == {"name": "John", "email": "john@test.com", "status": "active"}

    def test_extracts_specific_fields(self):
        obj = {"name": "John", "email": "john@test.com", "status": "active"}

        result = extract_audit_fields(obj, fields=["name", "status"])

        assert result == {"name": "John", "status": "active"}
        assert "email" not in result

    def test_excludes_fields(self):
        obj = {"name": "John", "password": "secret", "status": "active"}

        result = extract_audit_fields(obj, exclude_fields=["password"])

        assert "name" in result
        assert "status" in result
        assert "password" not in result

    def test_serializes_datetime(self):
        dt = datetime(2026, 1, 26, 10, 0, 0, tzinfo=timezone.utc)
        obj = {"created_at": dt, "name": "John"}

        result = extract_audit_fields(obj, fields=["created_at", "name"])

        assert result["created_at"] == "2026-01-26T10:00:00+00:00"


class TestLogAudit:
    """Test log_audit core function."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_creates_audit_log_entry(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_audit_log = MagicMock()
            mock_models.EntityAuditLog.return_value = mock_audit_log

            result = await log_audit(
                mock_db,
                entity_type="AdmissionProfile",
                entity_id=123,
                action="updated",
                actor_user_id=1,
                field_name="status",
                old_value="draft",
                new_value="submitted",
            )

            mock_models.EntityAuditLog.assert_called_once()
            mock_db.add.assert_called_once_with(mock_audit_log)
            mock_db.flush.assert_called_once()
            assert result == mock_audit_log

    @pytest.mark.asyncio
    async def test_passes_all_parameters(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_audit_log = MagicMock()
            mock_models.EntityAuditLog.return_value = mock_audit_log

            await log_audit(
                mock_db,
                entity_type="NotificationRule",
                entity_id=456,
                action="created",
                actor_user_id=2,
                changes={"field": {"old": "a", "new": "b"}},
                reason="Test reason",
                source="admin_panel",
                ip_address="192.168.1.1",
                user_agent="TestAgent/1.0",
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["entity_type"] == "NotificationRule"
            assert call_kwargs["entity_id"] == 456
            assert call_kwargs["action"] == "created"
            assert call_kwargs["actor_user_id"] == 2
            assert call_kwargs["changes"] == {"field": {"old": "a", "new": "b"}}
            assert call_kwargs["reason"] == "Test reason"
            assert call_kwargs["source"] == "admin_panel"
            assert call_kwargs["ip_address"] == "192.168.1.1"
            assert call_kwargs["user_agent"] == "TestAgent/1.0"


class TestConvenienceFunctions:
    """Test convenience logging functions."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_field_change(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_models.EntityAuditLog.return_value = MagicMock()

            await log_field_change(
                mock_db,
                "AdmissionProfile", 123, "status",
                old_value="draft", new_value="submitted",
                actor_user_id=1
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["action"] == "updated"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "draft"
            assert call_kwargs["new_value"] == "submitted"

    @pytest.mark.asyncio
    async def test_log_changes(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_models.EntityAuditLog.return_value = MagicMock()

            changes = {
                "status": {"old": "draft", "new": "submitted"},
                "submitted_at": {"old": None, "new": "2026-01-26"},
            }

            await log_changes(
                mock_db,
                "AdmissionProfile", 123, "updated",
                changes=changes,
                actor_user_id=1
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["action"] == "updated"
            assert call_kwargs["changes"] == changes

    @pytest.mark.asyncio
    async def test_log_created(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_models.EntityAuditLog.return_value = MagicMock()

            await log_created(
                mock_db,
                "NotificationRule", 456,
                actor_user_id=1,
                new_values={"event": "test", "enabled": True}
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["action"] == "created"
            assert call_kwargs["new_value"] == {"event": "test", "enabled": True}

    @pytest.mark.asyncio
    async def test_log_deleted(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_models.EntityAuditLog.return_value = MagicMock()

            await log_deleted(
                mock_db,
                "NotificationRule", 456,
                actor_user_id=1,
                old_values={"event": "test", "enabled": True}
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["action"] == "deleted"
            assert call_kwargs["old_value"] == {"event": "test", "enabled": True}

    @pytest.mark.asyncio
    async def test_log_status_change(self, mock_db):
        with patch("app.services.audit_service.models") as mock_models:
            mock_models.EntityAuditLog.return_value = MagicMock()

            await log_status_change(
                mock_db,
                "AdmissionProfile", 123,
                old_status="draft", new_status="submitted",
                actor_user_id=1,
                reason="User submitted application"
            )

            call_kwargs = mock_models.EntityAuditLog.call_args[1]
            assert call_kwargs["action"] == "status_changed"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "draft"
            assert call_kwargs["new_value"] == "submitted"
            assert call_kwargs["reason"] == "User submitted application"


class TestAuditServiceIntegration:
    """Integration-style tests for audit service workflow."""

    def test_workflow_detect_and_log_changes(self):
        """Test typical workflow: detect changes then prepare for logging."""
        # Simulate before/after states
        old_profile = {
            "id": 123,
            "status": "draft",
            "citizen_id": "123456789012",
            "submitted_at": None,
            "updated_at": "2026-01-25T10:00:00Z",
        }
        new_profile = {
            "id": 123,
            "status": "submitted",
            "citizen_id": "123456789012",
            "submitted_at": "2026-01-26T10:00:00Z",
            "updated_at": "2026-01-26T10:00:00Z",
        }

        # Detect changes (excluding auto-updated fields)
        changes = detect_changes(
            old_profile, new_profile,
            exclude_fields=["updated_at", "id"]
        )

        # Verify detected changes
        assert "status" in changes
        assert "submitted_at" in changes
        assert "citizen_id" not in changes  # unchanged
        assert "updated_at" not in changes  # excluded
        assert "id" not in changes  # excluded

        # Changes format is ready for log_changes
        assert changes["status"]["old"] == "draft"
        assert changes["status"]["new"] == "submitted"

    def test_extract_fields_for_created_log(self):
        """Test extracting relevant fields for creation audit."""
        new_rule = {
            "id": 456,
            "event": "admission_submitted",
            "enabled": True,
            "template_id": 1,
            "created_at": datetime(2026, 1, 26, tzinfo=timezone.utc),
        }

        # Extract only relevant fields
        audit_values = extract_audit_fields(
            new_rule,
            fields=["event", "enabled", "template_id"]
        )

        assert audit_values == {
            "event": "admission_submitted",
            "enabled": True,
            "template_id": 1,
        }
