# tests/integration/test_document_audit_log.py
"""
Integration tests for Document Admission and Audit Logging.

Tests:
1. Document operations create audit logs
2. Audit log content is correct for each operation
3. Audit log tracks status transitions
4. Audit log preserves file metadata

Operations tested:
- upload_document → DocumentAction.UPLOADED
- confirm_document_format → DocumentAction.VERIFIED
- reject_document → DocumentAction.REJECTED
- reset_document → DocumentAction.RESET
- mark_paper_submitted → DocumentAction.PAPER_SUBMITTED
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.document_audit_service import (
    DocumentAction,
    log_document_action,
    log_document_upload,
    log_document_verification,
    log_document_rejection,
    log_document_reset,
    log_paper_submission,
)


pytestmark = pytest.mark.asyncio


# ==============================================================================
# TEST FIXTURES
# ==============================================================================


@pytest_asyncio.fixture
async def audit_test_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a test user for audit tests."""
    from app.security import get_password_hash

    timestamp = datetime.now().timestamp()

    user = models.User(
        username=f"audit_test_user_{timestamp:.0f}",
        email=f"audit_test_{timestamp:.0f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="Audit Test User",
        role="officer",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def audit_test_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    audit_test_user: models.User,
) -> models.Lead:
    """Create a test lead for audit tests."""
    timestamp = datetime.now().timestamp()

    lead = models.Lead(
        full_name="Audit Test Lead",
        phone="0909999001",
        email=f"audit_lead_{timestamp:.0f}@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=audit_test_user.id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        consultation_count=1,
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def audit_test_profile(
    db: AsyncSession,
    audit_test_lead: models.Lead,
) -> models.AdmissionProfile:
    """Create a test admission profile for audit tests."""
    timestamp = datetime.now().timestamp()

    profile = models.AdmissionProfile(
        lead_id=audit_test_lead.id,
        status="draft",
        citizen_id=f"9{timestamp:.0f}"[:12],
        version=1,
        applied_rules={"min_gpa": 6.0, "mandatory_docs": ["BIRTH_CERT"]},
        academic_year=2025,
        full_name=audit_test_lead.full_name,
        phone=audit_test_lead.phone,
        email=audit_test_lead.email,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


@pytest_asyncio.fixture
async def audit_test_document_type(db: AsyncSession) -> models.ConfigDocumentType:
    """Create a test document type."""
    timestamp = datetime.now().timestamp()

    doc_type = models.ConfigDocumentType(
        code=f"AUDIT_TEST_DOC_{timestamp:.0f}",
        name=f"Audit Test Document {timestamp:.0f}",
        description="Document for audit testing",
        display_order=100,
        is_active=True,
    )
    db.add(doc_type)
    await db.flush()
    await db.refresh(doc_type)
    return doc_type


@pytest_asyncio.fixture
async def audit_test_profile_document(
    db: AsyncSession,
    audit_test_profile: models.AdmissionProfile,
    audit_test_document_type: models.ConfigDocumentType,
) -> models.ProfileDocument:
    """Create a test profile document."""
    profile_doc = models.ProfileDocument(
        profile_id=audit_test_profile.id,
        document_type_id=audit_test_document_type.id,
        status="missing",
    )
    db.add(profile_doc)
    await db.flush()
    await db.refresh(profile_doc)
    return profile_doc


# ==============================================================================
# TEST: DocumentAction CONSTANTS
# ==============================================================================


class TestDocumentActionConstants:
    """Test DocumentAction constant values."""

    def test_action_constants_exist(self):
        """All document action constants should be defined."""
        assert DocumentAction.UPLOADED == "uploaded"
        assert DocumentAction.VERIFIED == "verified"
        assert DocumentAction.REJECTED == "rejected"
        assert DocumentAction.RESET == "reset"
        assert DocumentAction.PAPER_SUBMITTED == "paper_submitted"
        assert DocumentAction.DELETED == "deleted"


# ==============================================================================
# TEST: log_document_action - Main Logging Function
# ==============================================================================


class TestLogDocumentAction:
    """Test the main log_document_action function."""

    async def test_creates_audit_log_record(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should create a DocumentAuditLog record."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=audit_test_user.id,
            old_status="missing",
            new_status="uploaded",
        )

        assert audit_log is not None
        assert audit_log.id is not None
        assert audit_log.profile_document_id == audit_test_profile_document.id
        assert audit_log.action == "uploaded"
        assert audit_log.actor_user_id == audit_test_user.id

    async def test_stores_status_transition(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should track status transitions."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.VERIFIED,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            new_status="verified",
        )

        assert audit_log.old_status == "uploaded"
        assert audit_log.new_status == "verified"

    async def test_stores_file_metadata(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should store file metadata."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=audit_test_user.id,
            new_file_path="/uploads/test/doc.pdf",
            original_filename="my_document.pdf",
            file_size_bytes=1024000,
            content_type="application/pdf",
        )

        assert audit_log.new_file_path == "/uploads/test/doc.pdf"
        assert audit_log.original_filename == "my_document.pdf"
        assert audit_log.file_size_bytes == 1024000
        assert audit_log.content_type == "application/pdf"

    async def test_stores_rejection_reason(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should store rejection reason."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.REJECTED,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            new_status="rejected",
            reason="Document is blurry and unreadable",
        )

        assert audit_log.reason == "Document is blurry and unreadable"

    async def test_stores_format_information(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should store declared and verified formats."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.VERIFIED,
            actor_user_id=audit_test_user.id,
            declared_format="original",
            verified_format="certified_copy",
        )

        assert audit_log.declared_format == "original"
        assert audit_log.verified_format == "certified_copy"

    async def test_stores_extra_data(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should store extra data as JSON."""
        extra = {"source": "mobile_app", "version": "1.2.3"}

        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=audit_test_user.id,
            extra_data=extra,
        )

        assert audit_log.extra_data == extra

    async def test_stores_client_context(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should store IP and user agent for security audit."""
        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=audit_test_user.id,
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        )

        assert audit_log.ip_address == "192.168.1.100"
        assert "Mozilla" in audit_log.user_agent

    async def test_sets_created_at_timestamp(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_action should set created_at timestamp."""
        before = datetime.now(timezone.utc)

        audit_log = await log_document_action(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            action=DocumentAction.UPLOADED,
            actor_user_id=audit_test_user.id,
        )

        after = datetime.now(timezone.utc)

        assert audit_log.created_at is not None
        assert before <= audit_log.created_at <= after


# ==============================================================================
# TEST: Convenience Functions
# ==============================================================================


class TestLogDocumentUpload:
    """Test log_document_upload convenience function."""

    async def test_creates_upload_audit_log(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_upload should create proper audit log."""
        audit_log = await log_document_upload(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="missing",
            new_file_path="/uploads/test/birth_cert.pdf",
            original_filename="giay_khai_sinh.pdf",
            file_size_bytes=512000,
            content_type="application/pdf",
            declared_format="original",
        )

        assert audit_log.action == DocumentAction.UPLOADED
        assert audit_log.new_status == "uploaded"
        assert audit_log.old_status == "missing"
        assert audit_log.original_filename == "giay_khai_sinh.pdf"
        assert audit_log.file_size_bytes == 512000

    async def test_tracks_reupload_with_old_file_path(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_upload should track old file path on re-upload."""
        audit_log = await log_document_upload(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="rejected",
            new_file_path="/uploads/test/birth_cert_v2.pdf",
            original_filename="giay_khai_sinh_v2.pdf",
            file_size_bytes=520000,
            content_type="application/pdf",
            old_file_path="/uploads/test/birth_cert_v1.pdf",
        )

        assert audit_log.old_file_path == "/uploads/test/birth_cert_v1.pdf"
        assert audit_log.new_file_path == "/uploads/test/birth_cert_v2.pdf"


class TestLogDocumentVerification:
    """Test log_document_verification convenience function."""

    async def test_creates_verification_audit_log(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_verification should create proper audit log."""
        audit_log = await log_document_verification(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            verified_format="original",
        )

        assert audit_log.action == DocumentAction.VERIFIED
        assert audit_log.old_status == "uploaded"
        assert audit_log.new_status == "verified"
        assert audit_log.verified_format == "original"


class TestLogDocumentRejection:
    """Test log_document_rejection convenience function."""

    async def test_creates_rejection_audit_log(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_rejection should create proper audit log with reason."""
        audit_log = await log_document_rejection(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            reason="Hình ảnh bị mờ, không đọc được thông tin",
        )

        assert audit_log.action == DocumentAction.REJECTED
        assert audit_log.old_status == "uploaded"
        assert audit_log.new_status == "rejected"
        assert audit_log.reason == "Hình ảnh bị mờ, không đọc được thông tin"


class TestLogDocumentReset:
    """Test log_document_reset convenience function."""

    async def test_creates_reset_audit_log(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_document_reset should create proper audit log."""
        audit_log = await log_document_reset(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            old_file_path="/uploads/test/wrong_file.pdf",
            reason="User uploaded wrong document",
        )

        assert audit_log.action == DocumentAction.RESET
        assert audit_log.old_status == "uploaded"
        assert audit_log.new_status == "missing"
        assert audit_log.old_file_path == "/uploads/test/wrong_file.pdf"
        assert audit_log.reason == "User uploaded wrong document"


class TestLogPaperSubmission:
    """Test log_paper_submission convenience function."""

    async def test_creates_paper_submission_audit_log(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """log_paper_submission should create proper audit log."""
        audit_log = await log_paper_submission(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="missing",
            declared_format="original",
        )

        assert audit_log.action == DocumentAction.PAPER_SUBMITTED
        assert audit_log.old_status == "missing"
        assert audit_log.new_status == "paper_submitted"
        assert audit_log.declared_format == "original"


# ==============================================================================
# TEST: Audit Log Query and Retrieval
# ==============================================================================


class TestAuditLogRetrieval:
    """Test retrieving audit logs from database."""

    async def test_audit_logs_linked_to_document(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """Audit logs should be queryable by profile_document_id."""
        # Create multiple audit logs
        await log_document_upload(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="missing",
            new_file_path="/uploads/test/doc1.pdf",
            original_filename="doc1.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )

        await log_document_verification(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="uploaded",
            verified_format="original",
        )

        await db.flush()

        # Query audit logs
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.profile_document_id == audit_test_profile_document.id)
            .order_by(models.DocumentAuditLog.created_at)
        )
        logs = result.scalars().all()

        assert len(logs) == 2
        assert logs[0].action == DocumentAction.UPLOADED
        assert logs[1].action == DocumentAction.VERIFIED

    async def test_audit_log_has_actor_relationship(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """Audit log should have relationship to actor user."""
        audit_log = await log_document_upload(
            db=db,
            profile_document_id=audit_test_profile_document.id,
            actor_user_id=audit_test_user.id,
            old_status="missing",
            new_file_path="/uploads/test/doc.pdf",
            original_filename="doc.pdf",
            file_size_bytes=100000,
            content_type="application/pdf",
        )

        await db.flush()

        # Query with actor relationship
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.id == audit_log.id)
            .options(selectinload(models.DocumentAuditLog.actor))
        )
        log_with_actor = result.scalar_one()

        assert log_with_actor.actor is not None
        assert log_with_actor.actor.id == audit_test_user.id
        assert log_with_actor.actor.email == audit_test_user.email


# ==============================================================================
# TEST: Full Document Lifecycle Audit Trail
# ==============================================================================


class TestDocumentLifecycleAudit:
    """Test complete document lifecycle creates proper audit trail."""

    async def test_full_document_lifecycle_audit_trail(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """
        Full lifecycle: missing → uploaded → rejected → uploaded → verified
        Should create 4 audit log entries.
        """
        doc_id = audit_test_profile_document.id
        user_id = audit_test_user.id

        # Step 1: Upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=user_id,
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
            actor_user_id=user_id,
            old_status="uploaded",
            reason="Image quality too low",
        )

        # Step 3: Re-upload
        await log_document_upload(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=user_id,
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
            actor_user_id=user_id,
            old_status="uploaded",
            verified_format="original",
        )

        await db.flush()

        # Query all audit logs for this document
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.profile_document_id == doc_id)
            .order_by(models.DocumentAuditLog.created_at)
        )
        logs = result.scalars().all()

        # Verify audit trail
        assert len(logs) == 4

        # Log 1: Upload
        assert logs[0].action == DocumentAction.UPLOADED
        assert logs[0].old_status == "missing"
        assert logs[0].new_status == "uploaded"

        # Log 2: Rejection
        assert logs[1].action == DocumentAction.REJECTED
        assert logs[1].old_status == "uploaded"
        assert logs[1].new_status == "rejected"
        assert logs[1].reason == "Image quality too low"

        # Log 3: Re-upload
        assert logs[2].action == DocumentAction.UPLOADED
        assert logs[2].old_status == "rejected"
        assert logs[2].new_status == "uploaded"
        assert logs[2].old_file_path == "/uploads/v1.pdf"

        # Log 4: Verification
        assert logs[3].action == DocumentAction.VERIFIED
        assert logs[3].old_status == "uploaded"
        assert logs[3].new_status == "verified"
        assert logs[3].verified_format == "original"

    async def test_paper_submission_lifecycle(
        self,
        db: AsyncSession,
        audit_test_profile_document: models.ProfileDocument,
        audit_test_user: models.User,
    ):
        """
        Paper submission lifecycle: missing → paper_submitted → reset → paper_submitted
        """
        doc_id = audit_test_profile_document.id
        user_id = audit_test_user.id

        # Step 1: Paper submitted
        await log_paper_submission(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=user_id,
            old_status="missing",
            declared_format="original",
        )

        # Step 2: Reset (officer made mistake)
        await log_document_reset(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=user_id,
            old_status="paper_submitted",
            reason="Marked wrong document as submitted",
        )

        # Step 3: Paper submitted again (correct document)
        await log_paper_submission(
            db=db,
            profile_document_id=doc_id,
            actor_user_id=user_id,
            old_status="missing",
            declared_format="certified_copy",
        )

        await db.flush()

        # Query all audit logs
        result = await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.profile_document_id == doc_id)
            .order_by(models.DocumentAuditLog.created_at)
        )
        logs = result.scalars().all()

        assert len(logs) == 3
        assert logs[0].action == DocumentAction.PAPER_SUBMITTED
        assert logs[0].declared_format == "original"
        assert logs[1].action == DocumentAction.RESET
        assert logs[2].action == DocumentAction.PAPER_SUBMITTED
        assert logs[2].declared_format == "certified_copy"
