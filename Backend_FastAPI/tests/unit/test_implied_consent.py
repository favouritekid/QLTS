"""Tests for implied Zalo consent auto-grant helper."""
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
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=7,
            )
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
    async def test_skips_when_no_phone(self):
        lead = _make_lead(phone=None)
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )
        mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_phone_empty_string(self):
        lead = _make_lead(phone="")
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )
        mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_swallows_upsert_errors_non_blocking(self):
        """Lead creation must not fail if consent grant hits an error."""
        lead = _make_lead()
        db = AsyncMock()
        with patch.object(
            notification_consent_service,
            "upsert_consent",
            new=AsyncMock(side_effect=Exception("db down")),
        ):
            # Must not raise
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=1,
            )

    @pytest.mark.asyncio
    async def test_default_fallbacks_when_source_fields_missing(self):
        lead = SimpleNamespace(
            id=99, phone="+84912345678", created_at=None,
        )
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=None,
            )
        assert mock_upsert.await_count == 1
        kwargs = mock_upsert.await_args.kwargs
        assert kwargs["actor_id"] == 0
        assert kwargs["data"]["normalized_phone"] == "84912345678"
        assert "source=unknown" in kwargs["data"]["notes"]
        assert "created_via=unknown" in kwargs["data"]["notes"]
        assert "Lead đăng ký N/A" in kwargs["data"]["notes"]

    @pytest.mark.asyncio
    async def test_actor_id_none_defaults_to_zero(self):
        lead = _make_lead()
        db = AsyncMock()
        with patch.object(
            notification_consent_service, "upsert_consent", new=AsyncMock()
        ) as mock_upsert:
            await notification_consent_service.grant_implied_zalo_consent(
                db, lead, actor_id=None,
            )
        assert mock_upsert.await_args.kwargs["actor_id"] == 0
