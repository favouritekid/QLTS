"""ADM-007 regression suite: filesystem staging for document upload + reset.

Pins the contract that filesystem mutations never become permanent
before the DB commit settles. Covers four scenarios:

1. **Upload happy path** — service stages to ``.staging.{uuid}``,
   ``finalize(True)`` promotes to final + deletes old file.
2. **Upload rollback** — ``finalize(False)`` cleans the staging file
   and leaves the previous (old) file intact.
3. **Reset happy path** — ``finalize(True)`` deletes the old file
   after the DB commit settles.
4. **Reset rollback** — ``finalize(False)`` is a no-op; the old file
   remains on disk so it stays consistent with the rolled-back DB.
"""

import io
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.services import admission_service


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test data fixtures (mirrors the layout in test_document_operations.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def staging_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Admin user — sidesteps the document-action policy matrix that
    blocks officer overwrite/reset on already-uploaded docs. Auth
    matrix is exercised by other test files; here we focus solely on
    the ADM-007 filesystem-staging contract."""
    from app.security import get_password_hash

    ts = datetime.now().timestamp()
    user = models.User(
        username=f"staging_admin_{ts:.6f}",
        email=f"staging_admin_{ts:.6f}@test.com",
        password_hash=get_password_hash("testpass123"),
        full_name="ADM-007 Staging Admin",
        role="admin",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def staging_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    staging_user: models.User,
) -> models.Lead:
    ts = datetime.now().timestamp()
    lead = models.Lead(
        full_name="ADM-007 Staging Lead",
        phone=f"09{int(ts) % 10_000_000:07d}",
        email=f"staging_lead_{ts:.6f}@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=staging_user.id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        consultation_count=1,
        status="new",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def staging_doc_type(db: AsyncSession) -> models.ConfigDocumentType:
    ts = datetime.now().timestamp()
    doc_type = models.ConfigDocumentType(
        code=f"ADM007_DOC_{ts:.6f}",
        name=f"ADM-007 Doc {ts:.6f}",
        description="Document type for staging tests",
        display_order=300,
        is_active=True,
    )
    db.add(doc_type)
    await db.flush()
    await db.refresh(doc_type)
    return doc_type


@pytest_asyncio.fixture
async def staging_profile(
    db: AsyncSession,
    staging_lead: models.Lead,
) -> models.AdmissionProfile:
    ts = datetime.now().timestamp()
    profile = models.AdmissionProfile(
        lead_id=staging_lead.id,
        status="draft",
        citizen_id=f"7{int(ts * 1000) % 10**11:011d}"[:12],
        version=1,
        applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
        academic_year=2025,
        full_name=staging_lead.full_name,
        phone=staging_lead.phone,
        email=staging_lead.email,
    )
    db.add(profile)
    await db.flush()

    result = await db.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile.id)
        .options(selectinload(models.AdmissionProfile.lead))
    )
    return result.scalar_one()


def _make_upload_file(content: bytes = b"%PDF-1.4\nADM-007 test", filename: str = "doc.pdf") -> MagicMock:
    """Build a mock ``UploadFile`` carrying real bytes so the
    magic-byte sniff in ADM-019 still passes."""
    mock = MagicMock()
    mock.filename = filename
    mock.content_type = "application/pdf"
    mock.file = io.BytesIO(content)
    return mock


def _seed_old_file_on_disk(profile_id: int, doc_code: str) -> str:
    """Write a realistic 'previous upload' file on disk under the
    canonical uploads directory and return its path. Tests use this
    to simulate the case where the user has already uploaded once."""
    upload_dir = f"uploads/admissions/{profile_id}"
    os.makedirs(upload_dir, exist_ok=True)
    old_path = f"{upload_dir}/{doc_code}_old_existing.pdf"
    with open(old_path, "wb") as f:
        f.write(b"%PDF-1.4\nold content from a previous upload")
    return old_path


# ---------------------------------------------------------------------------
# 1. Upload — happy path
# ---------------------------------------------------------------------------


class TestUploadFinalizeTrue:
    async def test_promotes_staging_to_final_and_deletes_old_file(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
    ):
        # Seed an existing uploaded doc with a real file on disk.
        old_path = _seed_old_file_on_disk(
            staging_profile.id, staging_doc_type.code,
        )
        # Document was previously uploaded then REJECTED — file is
        # still on disk, status=rejected. This is the realistic
        # upload-over-existing-file scenario for the auth matrix
        # (upload allowed only on missing/rejected).
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="rejected",
            file_path=old_path,
            uploaded_at=datetime.now(timezone.utc),
            rejection_reason="too blurry",
        )
        db.add(existing)
        await db.flush()
        existing_doc_id = existing.id

        upload_file = _make_upload_file(content=b"%PDF-1.4\nNEW content")

        profile, finalize = await admission_service.upload_document(
            db=db,
            profile_id=staging_profile.id,
            doc_code=staging_doc_type.code,
            file=upload_file,
            current_user=staging_user,
            actual_submission_format="photo",
        )

        # Pre-finalize state: DB points at FINAL path, but only the
        # staging file exists on disk yet.
        await db.refresh(existing)
        final_path_in_db = existing.file_path
        assert final_path_in_db != old_path, (
            "DB must point at the new (final) path before finalize"
        )
        assert os.path.exists(old_path), (
            "Old file must still be on disk before finalize — service "
            "must NOT delete it"
        )
        assert not os.path.exists(final_path_in_db), (
            "Final path must not exist yet; staging holds the bytes"
        )

        # Locate staging file
        upload_dir = f"uploads/admissions/{staging_profile.id}"
        staging_files = [
            f for f in os.listdir(upload_dir) if f.startswith(".staging.")
        ]
        assert len(staging_files) == 1, (
            f"Exactly one staging file must exist; got {staging_files}"
        )

        # Promote
        await db.commit()
        await finalize(True)

        # Final exists, staging gone, old gone
        assert os.path.exists(final_path_in_db)
        with open(final_path_in_db, "rb") as f:
            assert f.read().startswith(b"%PDF-1.4\nNEW content")
        remaining_staging = [
            f for f in os.listdir(upload_dir) if f.startswith(".staging.")
        ]
        assert remaining_staging == [], "Staging file must be promoted, not left behind"
        assert not os.path.exists(old_path), "Old file must be deleted post-commit"

        # Cleanup
        if os.path.exists(final_path_in_db):
            os.remove(final_path_in_db)
        _ = existing_doc_id  # kept for symmetry / future assertions


# ---------------------------------------------------------------------------
# 2. Upload — rollback path
# ---------------------------------------------------------------------------


class TestUploadFinalizeFalse:
    async def test_cleans_staging_and_keeps_old_file_intact(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
    ):
        old_path = _seed_old_file_on_disk(
            staging_profile.id, staging_doc_type.code,
        )
        # Same rejected-doc scenario as the happy-path test.
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="rejected",
            file_path=old_path,
            uploaded_at=datetime.now(timezone.utc),
            rejection_reason="needs reupload",
        )
        db.add(existing)
        await db.flush()

        upload_file = _make_upload_file(content=b"%PDF-1.4\nrolled-back upload")

        _profile, finalize = await admission_service.upload_document(
            db=db,
            profile_id=staging_profile.id,
            doc_code=staging_doc_type.code,
            file=upload_file,
            current_user=staging_user,
        )

        upload_dir = f"uploads/admissions/{staging_profile.id}"
        staging_files = [
            f for f in os.listdir(upload_dir) if f.startswith(".staging.")
        ]
        assert len(staging_files) == 1
        staging_full = os.path.join(upload_dir, staging_files[0])

        # Simulate router catching a commit failure: rollback session,
        # then call finalize(False) for FS cleanup.
        await db.rollback()
        await finalize(False)

        assert not os.path.exists(staging_full), (
            "Staging file must be cleaned up on rollback path"
        )
        assert os.path.exists(old_path), (
            "Old file must remain intact when commit fails"
        )

        # Cleanup
        if os.path.exists(old_path):
            os.remove(old_path)

    async def test_service_failure_after_stage_write_cleans_staging_before_reraise(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
        monkeypatch,
    ):
        """ADM-007 review fix: if the service raises AFTER the staging
        write but BEFORE returning the ``finalize`` callback, the
        router will never see ``finalize(False)``. The service itself
        must clean the staging file in that path so an audit-log /
        repo failure does not leak ``.staging.*`` artefacts onto disk.
        """
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="missing",
        )
        db.add(existing)
        await db.flush()

        # Force ``log_document_upload`` to raise AFTER the upload
        # service has staged the file + flushed the DB row. This is
        # exactly the leak window the reviewer flagged.
        from app.services import document_audit_service as _audit_mod

        async def _boom(**_kwargs):
            raise RuntimeError("simulated audit-log failure")

        monkeypatch.setattr(_audit_mod, "log_document_upload", _boom)

        upload_file = _make_upload_file(content=b"%PDF-1.4\nleak-test bytes")

        upload_dir = f"uploads/admissions/{staging_profile.id}"
        before_staging = (
            [f for f in os.listdir(upload_dir) if f.startswith(".staging.")]
            if os.path.exists(upload_dir)
            else []
        )

        with pytest.raises(RuntimeError, match="simulated audit-log failure"):
            await admission_service.upload_document(
                db=db,
                profile_id=staging_profile.id,
                doc_code=staging_doc_type.code,
                file=upload_file,
                current_user=staging_user,
            )

        # After the service raised, the staging file from THIS call
        # must be gone — even though the router never received a
        # finalize callback to invoke.
        after_staging = (
            [f for f in os.listdir(upload_dir) if f.startswith(".staging.")]
            if os.path.exists(upload_dir)
            else []
        )
        assert after_staging == before_staging, (
            f"ADM-007: staging file leaked when service failed after "
            f"stage write. Before={before_staging}, After={after_staging}"
        )

    async def test_finalize_false_is_idempotent(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
    ):
        """Calling ``finalize(False)`` twice must not raise — staging
        already gone is the steady state we want, not an error."""
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="missing",
        )
        db.add(existing)
        await db.flush()

        upload_file = _make_upload_file()
        _profile, finalize = await admission_service.upload_document(
            db=db,
            profile_id=staging_profile.id,
            doc_code=staging_doc_type.code,
            file=upload_file,
            current_user=staging_user,
        )

        await db.rollback()
        await finalize(False)
        await finalize(False)  # second call must not raise

        upload_dir = f"uploads/admissions/{staging_profile.id}"
        if os.path.exists(upload_dir):
            staging_files = [
                f for f in os.listdir(upload_dir) if f.startswith(".staging.")
            ]
            assert staging_files == []


# ---------------------------------------------------------------------------
# 3. Reset — happy path
# ---------------------------------------------------------------------------


class TestResetFinalizeTrue:
    async def test_deletes_old_file_post_commit(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
    ):
        old_path = _seed_old_file_on_disk(
            staging_profile.id, staging_doc_type.code,
        )
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="uploaded",
            file_path=old_path,
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        await db.flush()
        existing_id = existing.id

        _profile, finalize = await admission_service.reset_document(
            db=db,
            profile_id=staging_profile.id,
            doc_code=staging_doc_type.code,
            current_user=staging_user,
        )

        # Service must NOT have deleted the file yet.
        assert os.path.exists(old_path), (
            "Reset must defer file delete to post-commit; service "
            "alone must not remove the file"
        )

        await db.commit()
        await finalize(True)

        # Post-finalize: file deleted, DB cleared.
        assert not os.path.exists(old_path)

        # Re-read doc state after commit
        async with db.bind.connect() as conn:
            from app.database import AsyncSessionLocal as _ASL
            async with _ASL() as fresh:
                result = await fresh.execute(
                    select(models.ProfileDocument).where(
                        models.ProfileDocument.id == existing_id,
                    )
                )
                refreshed = result.scalar_one()
                assert refreshed.status == "missing"
                assert refreshed.file_path is None


# ---------------------------------------------------------------------------
# 4. Reset — rollback path
# ---------------------------------------------------------------------------


class TestResetFinalizeFalse:
    async def test_keeps_file_when_commit_fails(
        self,
        db: AsyncSession,
        staging_profile: models.AdmissionProfile,
        staging_doc_type: models.ConfigDocumentType,
        staging_user: models.User,
    ):
        old_path = _seed_old_file_on_disk(
            staging_profile.id, staging_doc_type.code,
        )
        existing = models.ProfileDocument(
            profile_id=staging_profile.id,
            document_type_id=staging_doc_type.id,
            status="uploaded",
            file_path=old_path,
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        await db.flush()
        existing_id = existing.id

        _profile, finalize = await admission_service.reset_document(
            db=db,
            profile_id=staging_profile.id,
            doc_code=staging_doc_type.code,
            current_user=staging_user,
        )

        # Simulate the router's commit failing → rollback + finalize(False).
        await db.rollback()
        await finalize(False)

        assert os.path.exists(old_path), (
            "Reset rollback must keep the old file on disk; the "
            "rolled-back DB still references it"
        )

        # The DB rollback should have undone the status change too.
        # Re-fetch the document via a fresh session because db has rolled back.
        from app.database import AsyncSessionLocal as _ASL
        async with _ASL() as fresh:
            result = await fresh.execute(
                select(models.ProfileDocument).where(
                    models.ProfileDocument.id == existing_id,
                )
            )
            after_rollback = result.scalar_one_or_none()
            # The row may not exist post-rollback because db.add(existing)
            # was never committed in this test session — both branches
            # are acceptable for the rollback contract. What matters is
            # that no half-state remains: file present + DB says
            # "missing" would be the bug we're guarding against.
            if after_rollback is not None:
                assert after_rollback.status == "uploaded"
                assert after_rollback.file_path == old_path

        # Cleanup
        if os.path.exists(old_path):
            os.remove(old_path)
