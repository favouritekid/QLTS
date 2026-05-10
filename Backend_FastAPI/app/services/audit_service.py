# app/services/audit_service.py
"""
Generic Entity Audit Service.

Provides utility functions for tracking field-level changes across any entity.
This is a protocol-independent service that can be called from routers, services,
or background tasks.

Usage Examples:
    # Log a single field change
    await audit_service.log_field_change(
        db, "AdmissionProfile", 123, "status",
        old_value="draft", new_value="submitted",
        actor_user_id=current_user.id, source="api"
    )

    # Log multiple field changes (bulk update)
    await audit_service.log_changes(
        db, "AdmissionProfile", 123, "updated",
        changes={"status": {"old": "draft", "new": "submitted"},
                 "submitted_at": {"old": None, "new": "2026-01-26T10:00:00Z"}},
        actor_user_id=current_user.id, source="api"
    )

    # Log entity creation
    await audit_service.log_created(
        db, "NotificationRule", 456,
        actor_user_id=current_user.id,
        new_values={"event": "admission_submitted", "enabled": True}
    )

    # Log entity deletion
    await audit_service.log_deleted(
        db, "NotificationRule", 456,
        actor_user_id=current_user.id,
        old_values={"event": "admission_submitted", "enabled": True}
    )

    # Auto-detect changes between two model states
    changes = audit_service.detect_changes(old_profile, new_profile, fields=["status", "submitted_at"])
    if changes:
        await audit_service.log_changes(db, "AdmissionProfile", profile.id, "updated", changes=changes, ...)
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from typing import Any, Dict, List, Optional, Union

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

log = structlog.get_logger(__name__)


# =========================================================================
# CORE LOGGING FUNCTIONS
# =========================================================================

async def log_audit(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    action: str,
    *,
    actor_user_id: Optional[int] = None,
    field_name: Optional[str] = None,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
    changes: Optional[Dict[str, Dict[str, Any]]] = None,
    reason: Optional[str] = None,
    source: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Create a generic audit log entry.

    This is the low-level function. Prefer using the convenience functions
    (log_field_change, log_changes, log_created, log_deleted) for common patterns.

    Args:
        db: Database session
        entity_type: Model/table name (e.g., "AdmissionProfile")
        entity_id: Primary key of the affected record
        action: Action type (created, updated, deleted, status_changed, etc.)
        actor_user_id: User who performed the action (None for system)
        field_name: Specific field changed (None for bulk operations)
        old_value: Previous value (JSON-serializable)
        new_value: New value (JSON-serializable)
        changes: Full changeset for bulk updates
        reason: Human-readable reason
        source: Change source (api, admin_panel, system, migration)
        ip_address: Client IP
        user_agent: Client user agent

    Returns:
        The created EntityAuditLog record
    """
    audit_log = models.EntityAuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        field_name=field_name,
        old_value=_serialize_value(old_value),
        new_value=_serialize_value(new_value),
        # Recursive serialize để JSON column nhận date/Decimal/UUID inside dict.
        changes=_serialize_value(changes) if changes is not None else None,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=datetime.now(timezone.utc),
    )

    db.add(audit_log)
    await db.flush([audit_log])

    log.info(
        "Audit log created",
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field_name=field_name,
        actor_user_id=actor_user_id,
    )

    return audit_log


# =========================================================================
# CONVENIENCE FUNCTIONS
# =========================================================================

async def log_field_change(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
    source: str = "api",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Log a single field change.

    Example:
        await log_field_change(
            db, "AdmissionProfile", 123, "status",
            old_value="draft", new_value="submitted",
            actor_user_id=user.id
        )
    """
    return await log_audit(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action="updated",
        actor_user_id=actor_user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_changes(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    action: str,
    changes: Dict[str, Dict[str, Any]],
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
    source: str = "api",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Log multiple field changes in a single audit entry.

    Example:
        await log_changes(
            db, "AdmissionProfile", 123, "updated",
            changes={
                "status": {"old": "draft", "new": "submitted"},
                "submitted_at": {"old": None, "new": "2026-01-26T10:00:00Z"}
            },
            actor_user_id=user.id
        )
    """
    return await log_audit(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        changes=changes,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_created(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    *,
    actor_user_id: Optional[int] = None,
    new_values: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    source: str = "api",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Log entity creation.

    Example:
        await log_created(
            db, "NotificationRule", 456,
            actor_user_id=user.id,
            new_values={"event": "admission_submitted", "enabled": True}
        )
    """
    return await log_audit(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action="created",
        actor_user_id=actor_user_id,
        new_value=new_values,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_deleted(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    *,
    actor_user_id: Optional[int] = None,
    old_values: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    source: str = "api",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Log entity deletion (or soft delete).

    Example:
        await log_deleted(
            db, "NotificationRule", 456,
            actor_user_id=user.id,
            old_values={"event": "admission_submitted", "enabled": True}
        )
    """
    return await log_audit(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action="deleted",
        actor_user_id=actor_user_id,
        old_value=old_values,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_status_change(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    old_status: str,
    new_status: str,
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
    source: str = "api",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.EntityAuditLog:
    """
    Log a status change specifically.

    Example:
        await log_status_change(
            db, "AdmissionProfile", 123,
            old_status="draft", new_status="submitted",
            actor_user_id=user.id,
            reason="User submitted application"
        )
    """
    return await log_audit(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action="status_changed",
        actor_user_id=actor_user_id,
        field_name="status",
        old_value=old_status,
        new_value=new_status,
        reason=reason,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# =========================================================================
# CHANGE DETECTION UTILITIES
# =========================================================================

def detect_changes(
    old_obj: Any,
    new_obj: Any,
    fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Detect changes between two objects (dicts or model instances).

    Args:
        old_obj: Previous state (dict or model with __dict__)
        new_obj: New state (dict or model with __dict__)
        fields: Only compare these fields (None = all fields)
        exclude_fields: Exclude these fields from comparison

    Returns:
        Dict of changes: {field: {"old": old_val, "new": new_val}, ...}
        Empty dict if no changes detected.

    Example:
        changes = detect_changes(
            {"status": "draft", "name": "John"},
            {"status": "submitted", "name": "John"},
            fields=["status", "name"]
        )
        # Returns: {"status": {"old": "draft", "new": "submitted"}}
    """
    old_dict = _to_dict(old_obj)
    new_dict = _to_dict(new_obj)

    exclude_fields = exclude_fields or []
    exclude_fields.extend(["updated_at", "created_at", "_sa_instance_state"])

    if fields:
        compare_fields = [f for f in fields if f not in exclude_fields]
    else:
        # Compare all common keys
        compare_fields = [
            k for k in set(old_dict.keys()) | set(new_dict.keys())
            if k not in exclude_fields
        ]

    changes = {}
    for field in compare_fields:
        old_val = old_dict.get(field)
        new_val = new_dict.get(field)

        if old_val != new_val:
            changes[field] = {
                "old": _serialize_value(old_val),
                "new": _serialize_value(new_val),
            }

    return changes


def extract_audit_fields(
    obj: Any,
    fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Extract field values from an object for audit logging.

    Args:
        obj: Object to extract from (dict or model)
        fields: Only extract these fields (None = all)
        exclude_fields: Exclude these fields

    Returns:
        Dict of field:value pairs
    """
    obj_dict = _to_dict(obj)

    exclude_fields = exclude_fields or []
    exclude_fields.extend(["_sa_instance_state"])

    if fields:
        result = {k: obj_dict.get(k) for k in fields if k not in exclude_fields}
    else:
        result = {k: v for k, v in obj_dict.items() if k not in exclude_fields}

    return {k: _serialize_value(v) for k, v in result.items()}


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert object to dict."""
    if isinstance(obj, dict):
        return obj
    # Check for Pydantic v2 first (model_dump method)
    if hasattr(obj, "model_dump"):
        method = getattr(obj, "model_dump")
        if callable(method):
            return method()
    # Check for Pydantic v1 (dict method)
    if hasattr(obj, "dict"):
        method = getattr(obj, "dict")
        if callable(method):
            try:
                return method()
            except TypeError:
                pass
    # Fall back to __dict__ for regular objects
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {}


# Pass 2 hard-review BM-3: max recursion depth cho _serialize_value để
# tránh stack overflow trên malformed JSONB payload (circular ref hoặc
# deeply nested adversarial input). 10 levels đủ cho audit changes thực
# tế (typical: 2-3 levels: changes → field → list); sentinel "[truncated:
# depth_exceeded]" giúp admin debug nếu hit limit.
_MAX_SERIALIZE_DEPTH = 10
_DEPTH_SENTINEL = "[truncated: depth_exceeded]"


def _serialize_value(value: Any, _depth: int = 0) -> Any:
    """Serialize a value for JSON storage.

    Handles datetime, date, Decimal, UUID, enum, list/dict recursively
    (with depth cap _MAX_SERIALIZE_DEPTH cho BM-3 stack safety).
    JSON column raw INSERT raise TypeError với date/Decimal nếu skip.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    # `date` MUST come AFTER `datetime` vì datetime là subclass của date.
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if _depth >= _MAX_SERIALIZE_DEPTH:
        # Truncate sentinel instead of recursing further. Audit log
        # vẫn ghi được, admin debug bằng sentinel marker.
        return _DEPTH_SENTINEL
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v, _depth + 1) for k, v in value.items()}
    # For enums and other types
    if hasattr(value, "value"):
        return value.value
    return str(value)
