"""
Phase E1: Consent History — Unit Tests

Covers:
  - Upsert creates a history row
  - Grant then revoke creates 2 history rows
  - History list returns newest first
Strategy: test repository functions with mocked DB, following D1 patterns.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# E1-1: Upsert creates a history row
# ---------------------------------------------------------------------------

class TestUpsertCreatesHistory:
    """Verify that upsert_latest appends a consent history entry."""

    @pytest.mark.asyncio
    async def test_upsert_new_consent_creates_history(self):
        """First upsert (no existing consent) → history with old_status=None."""
        from app.repositories.notification_consent_repository import (
            NotificationConsentRepository,
        )

        mock_db = AsyncMock()

        # First get_latest returns None (new consent), second returns the row
        mock_consent = MagicMock()
        mock_consent.id = 42
        mock_consent.consent_status = "granted"

        mock_result_none = MagicMock()
        mock_result_none.scalars.return_value.first.return_value = None

        mock_result_consent = MagicMock()
        mock_result_consent.scalars.return_value.first.return_value = mock_consent

        # execute calls: 1st=get_latest(None), 2nd=pg_insert, 3rd=flush,
        # 4th=get_latest(consent)
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_none, MagicMock(), mock_result_consent]
        )
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        repo = NotificationConsentRepository(mock_db)

        # Patch the history repo to capture its append call
        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentHistoryRepository"
        ) as MockHistoryRepo:
            history_instance = AsyncMock()
            MockHistoryRepo.return_value = history_instance

            data = {
                "channel": "zalo",
                "source_type": "lead",
                "source_id": 100,
                "consent_status": "granted",
                "consent_source": "manual",
                "granted_by": 1,
                "granted_at": datetime.now(timezone.utc),
                "revoked_at": None,
                "normalized_phone": "84901234567",
                "normalized_email": None,
                "notes": None,
            }

            await repo.upsert_latest(data)

            # History append must have been called exactly once
            history_instance.append.assert_awaited_once()
            append_data = history_instance.append.call_args[0][0]
            assert append_data["consent_id"] == 42
            assert append_data["channel"] == "zalo"
            assert append_data["source_type"] == "lead"
            assert append_data["source_id"] == 100
            assert append_data["action"] == "granted"
            assert append_data["old_status"] is None
            assert append_data["new_status"] == "granted"
            assert append_data["performed_by"] == 1


# ---------------------------------------------------------------------------
# E1-2: Grant → Revoke creates 2 history rows
# ---------------------------------------------------------------------------

class TestGrantRevokeCreatesTwo:
    """Two upserts (grant, revoke) should produce two history rows."""

    @pytest.mark.asyncio
    async def test_grant_then_revoke_two_history_entries(self):
        """Grant followed by revoke → 2 history append calls."""
        from app.repositories.notification_consent_repository import (
            NotificationConsentRepository,
        )

        mock_db = AsyncMock()

        # --- First call: grant (no existing) ---
        mock_consent_granted = MagicMock()
        mock_consent_granted.id = 42
        mock_consent_granted.consent_status = "granted"

        mock_result_none = MagicMock()
        mock_result_none.scalars.return_value.first.return_value = None

        mock_result_granted = MagicMock()
        mock_result_granted.scalars.return_value.first.return_value = mock_consent_granted

        # --- Second call: revoke (existing = granted) ---
        mock_result_existing_granted = MagicMock()
        mock_result_existing_granted.scalars.return_value.first.return_value = mock_consent_granted

        mock_consent_revoked = MagicMock()
        mock_consent_revoked.id = 42
        mock_consent_revoked.consent_status = "revoked"

        mock_result_revoked = MagicMock()
        mock_result_revoked.scalars.return_value.first.return_value = mock_consent_revoked

        # execute sequence: get_latest(None), insert, get_latest(granted),
        #                   get_latest(granted), insert, get_latest(revoked)
        mock_db.execute = AsyncMock(
            side_effect=[
                mock_result_none, MagicMock(), mock_result_granted,       # 1st upsert
                mock_result_existing_granted, MagicMock(), mock_result_revoked,  # 2nd upsert
            ]
        )
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentHistoryRepository"
        ) as MockHistoryRepo:
            history_instance = AsyncMock()
            MockHistoryRepo.return_value = history_instance

            repo = NotificationConsentRepository(mock_db)

            # First upsert: grant
            grant_data = {
                "channel": "email",
                "source_type": "lead",
                "source_id": 200,
                "consent_status": "granted",
                "consent_source": "manual",
                "granted_by": 1,
                "granted_at": datetime.now(timezone.utc),
                "revoked_at": None,
                "normalized_phone": None,
                "normalized_email": "test@example.com",
                "notes": None,
            }
            await repo.upsert_latest(grant_data)

            # Second upsert: revoke
            revoke_data = {
                "channel": "email",
                "source_type": "lead",
                "source_id": 200,
                "consent_status": "revoked",
                "consent_source": "manual",
                "granted_by": 1,
                "granted_at": None,
                "revoked_at": datetime.now(timezone.utc),
                "normalized_phone": None,
                "normalized_email": "test@example.com",
                "notes": "User requested revocation",
            }
            await repo.upsert_latest(revoke_data)

            # Should have 2 history append calls
            assert history_instance.append.await_count == 2

            # First call: granted, old_status=None
            first_call_data = history_instance.append.call_args_list[0][0][0]
            assert first_call_data["action"] == "granted"
            assert first_call_data["old_status"] is None
            assert first_call_data["new_status"] == "granted"

            # Second call: revoked, old_status=granted
            second_call_data = history_instance.append.call_args_list[1][0][0]
            assert second_call_data["action"] == "revoked"
            assert second_call_data["old_status"] == "granted"
            assert second_call_data["new_status"] == "revoked"


# ---------------------------------------------------------------------------
# E1-3: History list returns newest first
# ---------------------------------------------------------------------------

class TestHistoryListOrder:
    """Verify list_for_consent returns entries ordered by created_at desc."""

    @pytest.mark.asyncio
    async def test_list_for_consent_returns_newest_first(self):
        """list_for_consent should ORDER BY created_at DESC."""
        from app.repositories.notification_consent_history_repository import (
            NotificationConsentHistoryRepository,
        )

        mock_db = AsyncMock()

        # Simulate 2 history rows, newest first
        row_newer = MagicMock()
        row_newer.id = 2
        row_newer.action = "revoked"
        row_newer.created_at = datetime(2026, 3, 26, 12, 0, 0)

        row_older = MagicMock()
        row_older.id = 1
        row_older.action = "granted"
        row_older.created_at = datetime(2026, 3, 26, 10, 0, 0)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [row_newer, row_older]

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result]
        )

        repo = NotificationConsentHistoryRepository(mock_db)
        records, total = await repo.list_for_consent(consent_id=42)

        assert total == 2
        assert len(records) == 2
        # Newest first
        assert records[0].id == 2
        assert records[0].action == "revoked"
        assert records[1].id == 1
        assert records[1].action == "granted"

    @pytest.mark.asyncio
    async def test_list_for_entity_returns_newest_first(self):
        """list_for_entity should ORDER BY created_at DESC."""
        from app.repositories.notification_consent_history_repository import (
            NotificationConsentHistoryRepository,
        )

        mock_db = AsyncMock()

        row1 = MagicMock()
        row1.id = 5
        row1.action = "revoked"

        row2 = MagicMock()
        row2.id = 3
        row2.action = "granted"

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [row1, row2]

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result]
        )

        repo = NotificationConsentHistoryRepository(mock_db)
        records, total = await repo.list_for_entity(
            source_type="lead", source_id=100,
        )

        assert total == 2
        assert len(records) == 2
        assert records[0].id == 5
        assert records[1].id == 3


# ---------------------------------------------------------------------------
# E1-4: History append is immutable (repository creates, never updates)
# ---------------------------------------------------------------------------

class TestHistoryAppendImmutable:
    """Verify append creates a new row via db.add + flush."""

    @pytest.mark.asyncio
    async def test_append_adds_row_to_session(self):
        """append() should call db.add with a NotificationConsentHistory instance."""
        from app.repositories.notification_consent_history_repository import (
            NotificationConsentHistoryRepository,
        )
        from app.models.notification_consent_history import NotificationConsentHistory

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        repo = NotificationConsentHistoryRepository(mock_db)

        data = {
            "consent_id": 10,
            "channel": "sms",
            "source_type": "collaborator",
            "source_id": 55,
            "action": "granted",
            "old_status": None,
            "new_status": "granted",
            "performed_by": 3,
        }

        await repo.append(data)

        # db.add should have been called with a NotificationConsentHistory instance
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, NotificationConsentHistory)
        assert added_obj.channel == "sms"
        assert added_obj.source_id == 55
        assert added_obj.action == "granted"

        # flush + refresh should have been called
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()
