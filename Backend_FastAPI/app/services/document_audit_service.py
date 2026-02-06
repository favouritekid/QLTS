# app/services/document_audit_service.py
"""
Document Audit Logging Service.

Purpose:
    Provides centralized logging for all document operations.
    Maintains compliance-ready audit trail.

Usage:
    Called from admission_service.py after document operations:
    - upload_document() → log_document_action("uploaded", ...)
    - confirm_document_format() → log_document_action("verified", ...)
    - reject_document() → log_document_action("rejected", ...)
    - reset_document() → log_document_action("reset", ...)
"""

from typing import Optional, Dict, Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from .. import models

log = structlog.get_logger(__name__)


# =============================================================================
# ACTION CONSTANTS
# =============================================================================

class DocumentAction:
    """Document action types."""
    UPLOADED = "uploaded"
    VERIFIED = "verified"
    REJECTED = "rejected"
    RESET = "reset"
    PAPER_SUBMITTED = "paper_submitted"
    DELETED = "deleted"


# =============================================================================
# MAIN LOGGING FUNCTION
# =============================================================================

async def log_document_action(
    db: AsyncSession,
    profile_document_id: int,
    action: str,
    actor_user_id: int,
    old_status: Optional[str] = None,
    new_status: Optional[str] = None,
    old_file_path: Optional[str] = None,
    new_file_path: Optional[str] = None,
    original_filename: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    content_type: Optional[str] = None,
    reason: Optional[str] = None,
    declared_format: Optional[str] = None,
    verified_format: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """
    Log a document action to the audit trail.

    Args:
        db: Database session
        profile_document_id: ID of the ProfileDocument
        action: Action type (uploaded, verified, rejected, reset, etc.)
        actor_user_id: User who performed the action
        old_status: Status before the action
        new_status: Status after the action
        old_file_path: Previous file path (for re-uploads)
        new_file_path: New file path (for uploads)
        original_filename: Original filename from user
        file_size_bytes: File size in bytes
        content_type: MIME type of uploaded file
        reason: Reason for rejection/reset
        declared_format: User declared format
        verified_format: Officer verified format
        extra_data: Additional context data
        ip_address: Client IP address
        user_agent: Client user agent

    Returns:
        Created DocumentAuditLog record

    Example:
        await log_document_action(
            db=db,
            profile_document_id=doc.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=current_user.id,
            old_status="missing",
            new_status="uploaded",
            new_file_path=file_path,
            original_filename=file.filename,
            file_size_bytes=file_size,
            content_type=file.content_type,
        )
    """
    audit_log = models.DocumentAuditLog(
        profile_document_id=profile_document_id,
        action=action,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status=new_status,
        old_file_path=old_file_path,
        new_file_path=new_file_path,
        original_filename=original_filename,
        file_size_bytes=file_size_bytes,
        content_type=content_type,
        reason=reason,
        declared_format=declared_format,
        verified_format=verified_format,
        extra_data=extra_data or {},
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=datetime.now(timezone.utc),
    )

    db.add(audit_log)
    await db.flush()

    log.info(
        "Document action logged",
        audit_log_id=audit_log.id,
        profile_document_id=profile_document_id,
        action=action,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status=new_status,
    )

    return audit_log


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def log_document_upload(
    db: AsyncSession,
    profile_document_id: int,
    actor_user_id: int,
    old_status: str,
    new_file_path: str,
    original_filename: str,
    file_size_bytes: int,
    content_type: str,
    old_file_path: Optional[str] = None,
    declared_format: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """Log a document upload action."""
    return await log_document_action(
        db=db,
        profile_document_id=profile_document_id,
        action=DocumentAction.UPLOADED,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status="uploaded",
        old_file_path=old_file_path,
        new_file_path=new_file_path,
        original_filename=original_filename,
        file_size_bytes=file_size_bytes,
        content_type=content_type,
        declared_format=declared_format,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_document_verification(
    db: AsyncSession,
    profile_document_id: int,
    actor_user_id: int,
    old_status: str,
    verified_format: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """Log a document verification action."""
    return await log_document_action(
        db=db,
        profile_document_id=profile_document_id,
        action=DocumentAction.VERIFIED,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status="verified",
        verified_format=verified_format,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_document_rejection(
    db: AsyncSession,
    profile_document_id: int,
    actor_user_id: int,
    old_status: str,
    reason: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """Log a document rejection action."""
    return await log_document_action(
        db=db,
        profile_document_id=profile_document_id,
        action=DocumentAction.REJECTED,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status="rejected",
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_document_reset(
    db: AsyncSession,
    profile_document_id: int,
    actor_user_id: int,
    old_status: str,
    old_file_path: Optional[str] = None,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """Log a document reset action."""
    return await log_document_action(
        db=db,
        profile_document_id=profile_document_id,
        action=DocumentAction.RESET,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status="missing",
        old_file_path=old_file_path,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def log_paper_submission(
    db: AsyncSession,
    profile_document_id: int,
    actor_user_id: int,
    old_status: str,
    declared_format: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> models.DocumentAuditLog:
    """Log a paper submission confirmation action."""
    return await log_document_action(
        db=db,
        profile_document_id=profile_document_id,
        action=DocumentAction.PAPER_SUBMITTED,
        actor_user_id=actor_user_id,
        old_status=old_status,
        new_status="paper_submitted",
        declared_format=declared_format,
        ip_address=ip_address,
        user_agent=user_agent,
    )
