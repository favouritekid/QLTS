"""Tests for implied Zalo consent auto-grant helper.

Core invariants locked here:

1. ``granted_by`` (FK → user.id, nullable) MUST never be coerced to 0. Caller
   passes None when no user actor exists (CTV claim with unlinked user,
   backfill script). 0 would violate the FK.
2. Helper returns bool so callers can count true successes vs failures.
3. Any exception from upsert_consent is swallowed (non-blocking) and the
   helper returns False.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import notification_consent_service


def _make_lead(**overrides):
    defaults = dict(
        id=42,
        phone="0901234567",
        source="website",
        created_via="api",
        created_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGrantImpliedZaloConsent:
    @pytest.mark.asyncio
    async def test_grants_when_lead_has_phone(self):
        lead = _make_lead()
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            result = await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=7,
            )
        assert result is True
        assert mock_upsert.await_count == 1
        kwargs = mock_upsert.await_args.kwargs
        assert kwargs["actor_id"] == 7
        data = kwargs["data"]
        assert data == {
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 42,
            "normalized_phone": "84901234567",
            "consent_status": "granted",
            "consent_source": "implied_by_registration",
            "notes": (
                "Lead đăng ký 2026-04-19 qua source=website "
                "created_via=api. NĐ 13/2023 Đ.17.2."
            ),
        }

    @pytest.mark.asyncio
    async def test_returns_false_when_no_phone(self):
        lead = _make_lead(phone=None)
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            result = await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )
        assert result is False
        mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_phone_empty_string(self):
        lead = _make_lead(phone="")
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            result = await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )
        assert result is False
        mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_and_swallows_upsert_errors(self):
        """Lead creation must not fail if consent grant hits an error."""
        lead = _make_lead()
        db = AsyncMock()
        with patch.object(
            notification_consent_service,
            "upsert_consent",
            new=AsyncMock(side_effect=Exception("db down")),
        ):
            result = await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_default_fallbacks_when_source_fields_missing(self):
        lead = SimpleNamespace(
            id=99, phone="+84912345678", created_at=None,
        )
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            result = await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=None,
            )
        assert result is True
        assert mock_upsert.await_count == 1
        kwargs = mock_upsert.await_args.kwargs
        # actor_id=None must pass through as None (FK is nullable) — NOT 0.
        assert kwargs["actor_id"] is None
        assert kwargs["data"]["normalized_phone"] == "84912345678"
        assert "source=unknown" in kwargs["data"]["notes"]
        assert "created_via=unknown" in kwargs["data"]["notes"]
        assert "Lead đăng ký N/A" in kwargs["data"]["notes"]

    @pytest.mark.asyncio
    async def test_actor_id_none_passes_through_as_none(self):
        """Regression: must NOT coerce None to 0 (would violate user.id FK)."""
        lead = _make_lead()
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=None,
            )
        assert mock_upsert.await_args.kwargs["actor_id"] is None


class TestUpsertConsentGrantedByPropagation:
    """upsert_consent must forward actor_id to data['granted_by'] verbatim."""

    @pytest.mark.asyncio
    async def test_granted_by_none_when_actor_none(self):
        db = AsyncMock()
        fake_repo = AsyncMock()
        with patch.object(
            notification_consent_service,
            "NotificationConsentRepository",
            return_value=fake_repo,
        ):
            await notification_consent_service.upsert_consent(
                db,
                data={
                    "channel": "zalo",
                    "source_type": "lead",
                    "source_id": 1,
                    "consent_status": "granted",
                },
                actor_id=None,
            )
        called_data = fake_repo.upsert_latest.await_args.args[0]
        assert called_data["granted_by"] is None

    @pytest.mark.asyncio
    async def test_granted_by_set_when_actor_provided(self):
        db = AsyncMock()
        fake_repo = AsyncMock()
        with patch.object(
            notification_consent_service,
            "NotificationConsentRepository",
            return_value=fake_repo,
        ):
            await notification_consent_service.upsert_consent(
                db,
                data={
                    "channel": "zalo",
                    "source_type": "lead",
                    "source_id": 1,
                    "consent_status": "granted",
                },
                actor_id=5,
            )
        called_data = fake_repo.upsert_latest.await_args.args[0]
        assert called_data["granted_by"] == 5
