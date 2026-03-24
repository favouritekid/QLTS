"""
Unit tests for AdmissionRepository document management methods.

Per JSONB_TO_RELATIONAL_MIGRATION_PLAN.md Section 4:
- Test initialize_documents_for_profile()
- Test get_document_by_type()
- Test update_document_status()
- Test get_uploaded_documents()

Coverage Target: 100% for new repository methods
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.admission_repository import AdmissionRepository
from app import models


class TestInitializeDocumentsForProfile:
    """Test initialize_documents_for_profile() method."""

    @pytest.mark.asyncio
    async def test_creates_documents_for_valid_codes(self):
        """Should create ProfileDocument records for each document type code."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        # Mock ConfigDocumentType records
        doc_type1 = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        doc_type2 = models.ConfigDocumentType(id=2, code="CCCD", name="CCCD")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [doc_type1, doc_type2]
        mock_db.execute.return_value = mock_result

        # Act
        created_docs = await repo.initialize_documents_for_profile(
            profile_id=123,
            document_type_codes=["HOC_BA", "CCCD"]
        )

        # Assert
        assert len(created_docs) == 2
        assert created_docs[0].profile_id == 123
        assert created_docs[0].document_type_id == 1
        assert created_docs[0].status == "missing"
        assert created_docs[0].file_path is None

        assert created_docs[1].profile_id == 123
        assert created_docs[1].document_type_id == 2

        # Verify db.add() was called for each document
        assert mock_db.add.call_count == 2
        assert mock_db.flush.call_count == 1

    @pytest.mark.asyncio
    async def test_handles_empty_codes_list(self):
        """Should handle empty document codes list."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        # Act
        created_docs = await repo.initialize_documents_for_profile(
            profile_id=123,
            document_type_codes=[]
        )

        # Assert
        assert len(created_docs) == 0
        assert mock_db.add.call_count == 0
        assert mock_db.flush.call_count == 1  # Still flushes

    @pytest.mark.asyncio
    async def test_ignores_invalid_codes(self):
        """Should skip document codes that don't exist in config_document_type."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        # Only one valid code returned
        doc_type1 = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [doc_type1]
        mock_db.execute.return_value = mock_result

        # Act
        created_docs = await repo.initialize_documents_for_profile(
            profile_id=123,
            document_type_codes=["HOC_BA", "INVALID_CODE"]
        )

        # Assert - only one document created
        assert len(created_docs) == 1
        assert created_docs[0].document_type_id == 1


class TestGetDocumentByType:
    """Test get_document_by_type() method."""

    @pytest.mark.asyncio
    async def test_returns_document_for_valid_code(self):
        """Should return ProfileDocument when profile_id and code match."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        profile_doc = models.ProfileDocument(
            id=10,
            profile_id=123,
            document_type_id=1,
            status="missing",
            document_type=doc_type
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = profile_doc
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_document_by_type(
            profile_id=123,
            document_type_code="HOC_BA"
        )

        # Assert
        assert result is not None
        assert result.id == 10
        assert result.profile_id == 123
        assert result.document_type.code == "HOC_BA"

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_code(self):
        """Should return None when document code doesn't exist."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_document_by_type(
            profile_id=123,
            document_type_code="INVALID_CODE"
        )

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_profile_id(self):
        """Should return None when profile_id doesn't match."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_document_by_type(
            profile_id=999,  # Wrong profile_id
            document_type_code="HOC_BA"
        )

        # Assert
        assert result is None


class TestUpdateDocumentStatus:
    """Test update_document_status() method."""

    @pytest.mark.asyncio
    async def test_updates_status_and_metadata(self):
        """Should update status, file_path, and uploaded_at."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        profile_doc = models.ProfileDocument(
            id=10,
            profile_id=123,
            document_type_id=1,
            status="missing",
            file_path=None,
            uploaded_at=None,
            document_type=doc_type
        )

        # Mock get_document_by_type to return the document
        with patch.object(repo, 'get_document_by_type', return_value=profile_doc):
            # Act
            result = await repo.update_document_status(
                profile_id=123,
                document_type_code="HOC_BA",
                status="uploaded",
                file_path="/uploads/hoc_ba.pdf",
                uploaded_at="2026-01-07T10:30:00Z"
            )

        # Assert
        assert result is not None
        assert result.status == "uploaded"
        assert result.file_path == "/uploads/hoc_ba.pdf"
        assert result.uploaded_at == datetime(2026, 1, 7, 10, 30, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_document(self):
        """Should return None when document doesn't exist."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        # Mock get_document_by_type to return None
        with patch.object(repo, 'get_document_by_type', return_value=None):
            # Act
            result = await repo.update_document_status(
                profile_id=123,
                document_type_code="INVALID_CODE",
                status="uploaded"
            )

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_status_only_update(self):
        """Should update status without file_path/uploaded_at."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        profile_doc = models.ProfileDocument(
            id=10,
            profile_id=123,
            document_type_id=1,
            status="uploaded",
            file_path="/old/path.pdf",
            uploaded_at="2026-01-01T00:00:00Z",
            document_type=doc_type
        )

        # Mock get_document_by_type to return the document
        with patch.object(repo, 'get_document_by_type', return_value=profile_doc):
            # Act
            result = await repo.update_document_status(
                profile_id=123,
                document_type_code="HOC_BA",
                status="verified"  # Status change only
            )

        # Assert
        assert result.status == "verified"
        # File path and uploaded_at should remain unchanged
        assert result.file_path == "/old/path.pdf"
        assert result.uploaded_at == "2026-01-01T00:00:00Z"


class TestGetUploadedDocuments:
    """Test get_uploaded_documents() method."""

    @pytest.mark.asyncio
    async def test_returns_only_uploaded_documents(self):
        """Should return only documents with status='uploaded' and file_path not null."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type1 = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        doc_type2 = models.ConfigDocumentType(id=2, code="CCCD", name="CCCD")

        uploaded_doc1 = models.ProfileDocument(
            id=1,
            profile_id=123,
            document_type_id=1,
            status="uploaded",
            file_path="/uploads/hoc_ba.pdf",
            document_type=doc_type1
        )
        uploaded_doc2 = models.ProfileDocument(
            id=2,
            profile_id=123,
            document_type_id=2,
            status="uploaded",
            file_path="/uploads/cccd.pdf",
            document_type=doc_type2
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [uploaded_doc1, uploaded_doc2]
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_uploaded_documents(profile_id=123)

        # Assert
        assert len(result) == 2
        assert all(doc.status == "uploaded" for doc in result)
        assert all(doc.file_path is not None for doc in result)

    @pytest.mark.asyncio
    async def test_excludes_missing_documents(self):
        """Should exclude documents with status='missing'."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # No uploaded docs
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_uploaded_documents(profile_id=123)

        # Assert
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_documents(self):
        """Should return empty list when no documents exist."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        # Act
        result = await repo.get_uploaded_documents(profile_id=999)

        # Assert
        assert len(result) == 0
        assert isinstance(result, list)


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_initialize_documents_with_duplicate_codes(self):
        """Should handle duplicate document codes gracefully."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [doc_type]
        mock_db.execute.return_value = mock_result

        # Act - duplicate codes
        created_docs = await repo.initialize_documents_for_profile(
            profile_id=123,
            document_type_codes=["HOC_BA", "HOC_BA"]  # Duplicate
        )

        # Assert - should still create only one document
        # (database will query for unique codes via IN clause)
        assert len(created_docs) == 1

    @pytest.mark.asyncio
    async def test_update_document_status_with_null_values(self):
        """Should handle None values for optional parameters."""
        # Arrange
        mock_db = AsyncMock()
        repo = AdmissionRepository(mock_db)

        doc_type = models.ConfigDocumentType(id=1, code="HOC_BA", name="Học bạ")
        profile_doc = models.ProfileDocument(
            id=10,
            profile_id=123,
            document_type_id=1,
            status="missing",
            file_path=None,
            uploaded_at=None,
            document_type=doc_type
        )

        # Mock get_document_by_type to return the document
        with patch.object(repo, 'get_document_by_type', return_value=profile_doc):
            # Act - None values for file_path and uploaded_at
            result = await repo.update_document_status(
                profile_id=123,
                document_type_code="HOC_BA",
                status="rejected",
                file_path=None,
                uploaded_at=None
            )

        # Assert
        assert result.status == "rejected"
        assert result.file_path is None
        assert result.uploaded_at is None
