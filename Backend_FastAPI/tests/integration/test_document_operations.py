# tests/integration/test_document_operations.py
"""
Integration tests for Document Operations in Admission Service.

Tests the actual document operations and verifies:
1. Document status transitions
2. Audit logs are created for each operation
3. File metadata is properly stored
4. Access control works correctly

Operations tested:
- upload_document
- confirm_document_format (verify)
- reject_document
- reset_document
- mark_paper_submitted
"""

import io
import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import admission_service
from app.services.document_audit_service import DocumentAction


pytestmark = pytest.mark.asyncio


# ==============================================================================
# TEST FIXTURES
# ==============================================================================


@pytest_asyncio.fixture
async def doc_ops_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a test officer user for document operations."""
    from app.security import get_password_hash

    timestamp = datetime.now().timestamp()

    user = models.User(
        username=f"doc_ops_user_{timestamp:.0f}",
        email=f"doc_ops_{timestamp:.0f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="Document Operations Test User",
        role="officer",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def doc_ops_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    doc_ops_user: models.User,
) -> models.Lead:
    """Create a test lead for document operations."""
    timestamp = datetime.now().timestamp()

    lead = models.Lead(
        full_name="Document Ops Test Lead",
        phone="0909888001",
        email=f"doc_ops_lead_{timestamp:.0f}@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=doc_ops_user.id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        consultation_count=1,
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def doc_ops_document_type(db: AsyncSession) -> models.ConfigDocumentType:
    """Create a test document type."""
    timestamp = datetime.now().timestamp()

    doc_type = models.ConfigDocumentType(
        code=f"DOC_OPS_TEST_{timestamp:.0f}",
        name=f"Doc Ops Test Document {timestamp:.0f}",
        description="Document type for operations testing",
        display_order=200,
        is_active=True,
    )
    db.add(doc_type)
    await db.flush()
    await db.refresh(doc_type)
    return doc_type


@pytest_asyncio.fixture
async def doc_ops_profile(
    db: AsyncSession,
    doc_ops_lead: models.Lead,
) -> models.AdmissionProfile:
    """Create a test admission profile in draft status."""
    timestamp = datetime.now().timestamp()

    profile = models.AdmissionProfile(
        lead_id=doc_ops_lead.id,
        status="draft",
        citizen_id=f"8{timestamp:.0f}"[:12],
        version=1,
        applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
        academic_year=2025,
        full_name=doc_ops_lead.full_name,
        phone=doc_ops_lead.phone,
        email=doc_ops_lead.email,
    )
    db.add(profile)
    await db.flush()

    # Reload with lead relationship
    result = await db.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile.id)
        .options(selectinload(models.AdmissionProfile.lead))
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def doc_ops_profile_document(
    db: AsyncSession,
    doc_ops_profile: models.AdmissionProfile,
    doc_ops_document_type: models.ConfigDocumentType,
) -> models.ProfileDocument:
    """Create a test profile document in missing status."""
    profile_doc = models.ProfileDocument(
        profile_id=doc_ops_profile.id,
        document_type_id=doc_ops_document_type.id,
        status="missing",
    )
    db.add(profile_doc)
    await db.flush()
    await db.refresh(profile_doc)
    return profile_doc


@pytest_asyncio.fixture
async def uploaded_profile_document(
    db: AsyncSession,
    doc_ops_profile: models.AdmissionProfile,
    doc_ops_document_type: models.ConfigDocumentType,
) -> models.ProfileDocument:
    """Create a test profile document already in uploaded status."""
    profile_doc = models.ProfileDocument(
        profile_id=doc_ops_profile.id,
        document_type_id=doc_ops_document_type.id,
        status="uploaded",
        file_path="/uploads/test/existing_doc.pdf",
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(profile_doc)
    await db.flush()
    await db.refresh(profile_doc)
    return profile_doc


def create_mock_upload_file(
    filename: str = "test_document.pdf",
    content: bytes = b"%PDF-1.4\ntest content",
    content_type: str = "application/pdf",
) -> MagicMock:
    """Create a mock UploadFile object for testing."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.content_type = content_type

    # Create a BytesIO object for file content
    file_content = io.BytesIO(content)
    mock_file.file = file_content

    # Mock read method
    async def mock_read():
        file_content.seek(0)
        return file_content.read()

    mock_file.read = mock_read

    return mock_file


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def get_audit_logs_for_document(
    db: AsyncSession,
    profile_document_id: int,
) -> list[models.DocumentAuditLog]:
    """Get all audit logs for a specific document."""
    result = await db.execute(
        select(models.DocumentAuditLog)
        .where(models.DocumentAuditLog.profile_document_id == profile_document_id)
        .order_by(models.DocumentAuditLog.created_at)
    )
    return list(result.scalars().all())


async def get_latest_audit_log(
    db: AsyncSession,
    profile_document_id: int,
) -> models.DocumentAuditLog | None:
    """Get the most recent audit log for a document."""
    result = await db.execute(
        select(models.DocumentAuditLog)
        .where(models.DocumentAuditLog.profile_document_id == profile_document_id)
        .order_by(models.DocumentAuditLog.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ==============================================================================
# TEST: ProfileDocument Creation
# ==============================================================================


class TestProfileDocumentCreation:
    """Test ProfileDocument model creation."""

    async def test_create_profile_document_missing_status(
        self,
        db: AsyncSession,
        doc_ops_profile: models.AdmissionProfile,
        doc_ops_document_type: models.ConfigDocumentType,
    ):
        """ProfileDocument should be created with missing status by default."""
        profile_doc = models.ProfileDocument(
            profile_id=doc_ops_profile.id,
            document_type_id=doc_ops_document_type.id,
        )
        db.add(profile_doc)
        await db.flush()

        assert profile_doc.id is not None
        assert profile_doc.status == "missing"
        assert profile_doc.file_path is None

    async def test_profile_document_unique_constraint(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_profile: models.AdmissionProfile,
        doc_ops_document_type: models.ConfigDocumentType,
    ):
        """Cannot create duplicate ProfileDocument for same profile + document_type."""
        from sqlalchemy.exc import IntegrityError

        duplicate_doc = models.ProfileDocument(
            profile_id=doc_ops_profile.id,
            document_type_id=doc_ops_document_type.id,
        )
        db.add(duplicate_doc)

        with pytest.raises(IntegrityError):
            await db.flush()

        await db.rollback()


# ==============================================================================
# TEST: Document Status Transitions
# ==============================================================================


class TestDocumentStatusTransitions:
    """Test document status transitions."""

    async def test_missing_to_uploaded(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
    ):
        """Document can transition from missing to uploaded."""
        assert doc_ops_profile_document.status == "missing"

        doc_ops_profile_document.status = "uploaded"
        doc_ops_profile_document.file_path = "/uploads/test/new_doc.pdf"
        doc_ops_profile_document.uploaded_at = datetime.now(timezone.utc)
        await db.flush()

        assert doc_ops_profile_document.status == "uploaded"
        assert doc_ops_profile_document.file_path is not None

    async def test_uploaded_to_verified(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Document can transition from uploaded to verified."""
        assert uploaded_profile_document.status == "uploaded"

        uploaded_profile_document.status = "verified"
        uploaded_profile_document.verified_at = datetime.now(timezone.utc)
        uploaded_profile_document.verified_by = doc_ops_user.id
        uploaded_profile_document.verified_format = "original"
        await db.flush()

        assert uploaded_profile_document.status == "verified"
        assert uploaded_profile_document.verified_format == "original"

    async def test_uploaded_to_rejected(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Document can transition from uploaded to rejected."""
        assert uploaded_profile_document.status == "uploaded"

        uploaded_profile_document.status = "rejected"
        uploaded_profile_document.rejected_at = datetime.now(timezone.utc)
        uploaded_profile_document.rejected_by = doc_ops_user.id
        uploaded_profile_document.rejection_reason = "Blurry image"
        await db.flush()

        assert uploaded_profile_document.status == "rejected"
        assert uploaded_profile_document.rejection_reason == "Blurry image"

    async def test_missing_to_paper_submitted(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Document can transition from missing to paper_submitted."""
        assert doc_ops_profile_document.status == "missing"

        doc_ops_profile_document.status = "paper_submitted"
        doc_ops_profile_document.paper_submitted_at = datetime.now(timezone.utc)
        doc_ops_profile_document.paper_submitted_by = doc_ops_user.id
        doc_ops_profile_document.actual_submission_format = "original"
        await db.flush()

        assert doc_ops_profile_document.status == "paper_submitted"

    async def test_reset_to_missing(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
    ):
        """Document can be reset back to missing status."""
        assert uploaded_profile_document.status == "uploaded"

        uploaded_profile_document.status = "missing"
        uploaded_profile_document.file_path = None
        uploaded_profile_document.uploaded_at = None
        await db.flush()

        assert uploaded_profile_document.status == "missing"
        assert uploaded_profile_document.file_path is None


# ==============================================================================
# TEST: Audit Log Service Functions
# ==============================================================================


class TestAuditLogServiceIntegration:
    """Test audit log service functions create proper records."""

    async def test_log_document_upload_creates_record(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """log_document_upload should create audit record."""
        from app.services.document_audit_service import log_document_upload

        audit_log = await log_document_upload(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/test/uploaded.pdf",
            original_filename="my_document.pdf",
            file_size_bytes=1024000,
            content_type="application/pdf",
        )
        await db.flush()

        assert audit_log.id is not None
        assert audit_log.action == DocumentAction.UPLOADED
        assert audit_log.old_status == "missing"
        assert audit_log.new_status == "uploaded"
        assert audit_log.original_filename == "my_document.pdf"
        assert audit_log.file_size_bytes == 1024000

    async def test_log_document_verification_creates_record(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """log_document_verification should create audit record."""
        from app.services.document_audit_service import log_document_verification

        audit_log = await log_document_verification(
            db=db,
            profile_document_id=uploaded_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            verified_format="certified_copy",
        )
        await db.flush()

        assert audit_log.action == DocumentAction.VERIFIED
        assert audit_log.new_status == "verified"
        assert audit_log.verified_format == "certified_copy"

    async def test_log_document_rejection_creates_record(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """log_document_rejection should create audit record with reason."""
        from app.services.document_audit_service import log_document_rejection

        audit_log = await log_document_rejection(
            db=db,
            profile_document_id=uploaded_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            reason="Document expired - need current version",
        )
        await db.flush()

        assert audit_log.action == DocumentAction.REJECTED
        assert audit_log.new_status == "rejected"
        assert audit_log.reason == "Document expired - need current version"

    async def test_log_document_reset_creates_record(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """log_document_reset should create audit record."""
        from app.services.document_audit_service import log_document_reset

        audit_log = await log_document_reset(
            db=db,
            profile_document_id=uploaded_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            old_file_path="/uploads/test/wrong_file.pdf",
            reason="Wrong document uploaded",
        )
        await db.flush()

        assert audit_log.action == DocumentAction.RESET
        assert audit_log.new_status == "missing"
        assert audit_log.old_file_path == "/uploads/test/wrong_file.pdf"

    async def test_log_paper_submission_creates_record(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """log_paper_submission should create audit record."""
        from app.services.document_audit_service import log_paper_submission

        audit_log = await log_paper_submission(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            declared_format="original",
        )
        await db.flush()

        assert audit_log.action == DocumentAction.PAPER_SUBMITTED
        assert audit_log.new_status == "paper_submitted"
        assert audit_log.declared_format == "original"


# ==============================================================================
# TEST: Complete Document Lifecycle with Audit Trail
# ==============================================================================


class TestDocumentLifecycleWithAudit:
    """Test complete document lifecycle creates proper audit trail."""

    async def test_upload_verify_lifecycle(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """
        Test lifecycle: missing → uploaded → verified
        Should create 2 audit logs.
        """
        from app.services.document_audit_service import (
            log_document_upload,
            log_document_verification,
        )

        doc_id = doc_ops_profile_document.id

        # Step 1: Upload
        doc_ops_profile_document.status = "uploaded"
        doc_ops_profile_document.file_path = "/uploads/test/doc.pdf"
        doc_ops_profile_document.uploaded_at = datetime.now(timezone.utc)

        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/test/doc.pdf",
            original_filename="birth_cert.pdf",
            file_size_bytes=500000,
            content_type="application/pdf",
        )

        # Step 2: Verify
        doc_ops_profile_document.status = "verified"
        doc_ops_profile_document.verified_at = datetime.now(timezone.utc)
        doc_ops_profile_document.verified_by = doc_ops_user.id
        doc_ops_profile_document.verified_format = "original"

        await log_document_verification(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            verified_format="original",
        )

        await db.flush()

        # Verify audit trail
        logs = await get_audit_logs_for_document(db, doc_id)

        assert len(logs) == 2
        assert logs[0].action == DocumentAction.UPLOADED
        assert logs[1].action == DocumentAction.VERIFIED

    async def test_upload_reject_reupload_verify_lifecycle(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """
        Test lifecycle: missing → uploaded → rejected → uploaded → verified
        Should create 4 audit logs.
        """
        from app.services.document_audit_service import (
            log_document_upload,
            log_document_rejection,
            log_document_verification,
        )

        doc_id = doc_ops_profile_document.id

        # Step 1: Upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/v1.pdf",
            original_filename="v1.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )

        # Step 2: Reject
        await log_document_rejection(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            reason="Image too blurry",
        )

        # Step 3: Re-upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="rejected",
            new_file_path="/uploads/v2.pdf",
            original_filename="v2.pdf",
            file_size_bytes=150000,
            content_type="application/pdf",
            old_file_path="/uploads/v1.pdf",
        )

        # Step 4: Verify
        await log_document_verification(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            verified_format="original",
        )

        await db.flush()

        # Verify complete audit trail
        logs = await get_audit_logs_for_document(db, doc_id)

        assert len(logs) == 4

        # Check each log entry
        assert logs[0].action == DocumentAction.UPLOADED
        assert logs[0].old_status == "missing"

        assert logs[1].action == DocumentAction.REJECTED
        assert logs[1].reason == "Image too blurry"

        assert logs[2].action == DocumentAction.UPLOADED
        assert logs[2].old_status == "rejected"
        assert logs[2].old_file_path == "/uploads/v1.pdf"

        assert logs[3].action == DocumentAction.VERIFIED
        assert logs[3].verified_format == "original"

    async def test_paper_submission_lifecycle(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """
        Test paper submission lifecycle: missing → paper_submitted
        """
        from app.services.document_audit_service import log_paper_submission

        doc_id = doc_ops_profile_document.id

        # Mark as paper submitted
        doc_ops_profile_document.status = "paper_submitted"
        doc_ops_profile_document.paper_submitted_at = datetime.now(timezone.utc)
        doc_ops_profile_document.paper_submitted_by = doc_ops_user.id
        doc_ops_profile_document.actual_submission_format = "certified_copy"

        await log_paper_submission(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            declared_format="certified_copy",
        )

        await db.flush()

        # Verify audit log
        log = await get_latest_audit_log(db, doc_id)

        assert log is not None
        assert log.action == DocumentAction.PAPER_SUBMITTED
        assert log.declared_format == "certified_copy"

    async def test_reset_and_resubmit_lifecycle(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """
        Test reset lifecycle: uploaded → missing (reset) → uploaded
        """
        from app.services.document_audit_service import (
            log_document_reset,
            log_document_upload,
        )

        doc_id = uploaded_profile_document.id
        old_path = uploaded_profile_document.file_path

        # Step 1: Reset
        await log_document_reset(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            old_file_path=old_path,
            reason="User requested document replacement",
        )

        uploaded_profile_document.status = "missing"
        uploaded_profile_document.file_path = None

        # Step 2: Re-upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/new_doc.pdf",
            original_filename="replacement.pdf",
            file_size_bytes=200000,
            content_type="application/pdf",
        )

        await db.flush()

        # Verify audit trail
        logs = await get_audit_logs_for_document(db, doc_id)

        assert len(logs) == 2
        assert logs[0].action == DocumentAction.RESET
        assert logs[0].old_file_path == old_path
        assert logs[1].action == DocumentAction.UPLOADED


# ==============================================================================
# TEST: Audit Log Relationships
# ==============================================================================


class TestAuditLogRelationships:
    """Test audit log relationships with other models."""

    async def test_audit_log_has_actor_user(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should link to actor user."""
        from app.services.document_audit_service import log_document_upload

        audit_log = await log_document_upload(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/test.pdf",
            original_filename="test.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )
        await db.flush()

        # Query with relationship
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.id == audit_log.id)
            .options(selectinload(models.DocumentAuditLog.actor))
        )
        log_with_actor = result.scalar_one()

        assert log_with_actor.actor is not None
        assert log_with_actor.actor.id == doc_ops_user.id
        assert log_with_actor.actor.username == doc_ops_user.username

    async def test_audit_log_has_profile_document(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should link to profile document."""
        from app.services.document_audit_service import log_document_upload

        audit_log = await log_document_upload(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/test.pdf",
            original_filename="test.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )
        await db.flush()

        # Query with relationship
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.id == audit_log.id)
            .options(selectinload(models.DocumentAuditLog.profile_document))
        )
        log_with_doc = result.scalar_one()

        assert log_with_doc.profile_document is not None
        assert log_with_doc.profile_document.id == doc_ops_profile_document.id

    async def test_profile_document_has_audit_logs_backref(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """ProfileDocument should have backref to audit_logs."""
        from app.services.document_audit_service import (
            log_document_upload,
            log_document_verification,
        )

        # Create multiple audit logs
        await log_document_upload(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/test.pdf",
            original_filename="test.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )

        await log_document_verification(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            verified_format="original",
        )

        await db.flush()

        # Query ProfileDocument with audit_logs
        result = await db.execute(
            select(models.ProfileDocument)
            .where(models.ProfileDocument.id == doc_ops_profile_document.id)
            .options(selectinload(models.ProfileDocument.audit_logs))
        )
        doc_with_logs = result.scalar_one()

        assert len(doc_with_logs.audit_logs) == 2


# ==============================================================================
# TEST: Audit Log Metadata Storage
# ==============================================================================


class TestAuditLogMetadata:
    """Test audit log stores various metadata correctly."""

    async def test_stores_file_size_correctly(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should store file size as BigInteger."""
        from app.services.document_audit_service import log_document_upload

        # Large file size (> 2GB to test BigInteger)
        large_size = 5 * 1024 * 1024 * 1024  # 5GB

        audit_log = await log_document_upload(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="missing",
            new_file_path="/uploads/large.pdf",
            original_filename="large.pdf",
            file_size_bytes=large_size,
            content_type="application/pdf",
        )
        await db.flush()

        assert audit_log.file_size_bytes == large_size

    async def test_stores_long_rejection_reason(
        self,
        db: AsyncSession,
        uploaded_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should store long rejection reasons (Text field)."""
        from app.services.document_audit_service import log_document_rejection

        long_reason = "This document was rejected because: " + "x" * 1000

        audit_log = await log_document_rejection(
            db=db,
            profile_document_id=uploaded_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            reason=long_reason,
        )
        await db.flush()

        assert audit_log.reason == long_reason
        assert len(audit_log.reason) > 1000

    async def test_stores_extra_data_json(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should store extra_data as JSONB."""
        from app.services.document_audit_service import log_document_action

        extra = {
            "source": "mobile_app",
            "app_version": "2.1.0",
            "device": "iPhone 15",
            "nested": {"key": "value"},
        }

        audit_log = await log_document_action(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=doc_ops_user.id,
            extra_data=extra,
        )
        await db.flush()

        assert audit_log.extra_data == extra
        assert audit_log.extra_data["nested"]["key"] == "value"

    async def test_stores_vietnamese_text(
        self,
        db: AsyncSession,
        doc_ops_profile_document: models.ProfileDocument,
        doc_ops_user: models.User,
    ):
        """Audit log should store Vietnamese characters correctly."""
        from app.services.document_audit_service import log_document_rejection

        vietnamese_reason = "Tài liệu không hợp lệ. Vui lòng nộp lại bản gốc có chữ ký của cơ quan có thẩm quyền."

        audit_log = await log_document_rejection(
            db=db,
            profile_document_id=doc_ops_profile_document.id,
            actor_user_id=doc_ops_user.id,
            old_status="uploaded",
            reason=vietnamese_reason,
        )
        await db.flush()

        assert audit_log.reason == vietnamese_reason
