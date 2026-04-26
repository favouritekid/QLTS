"""Unit tests for ``ZaloBotChannel`` (Step 8).

The channel is worker-only — these tests exercise ``execute_delivery``
with a mocked gateway and a stubbed repository so the focus is the
contract:
- Missing/inactive link → permanent ``no_zalo_bot_link`` error.
- Active link + gateway success → ``ChannelResult.success=True``
  carries the provider message id.
- Gateway failure → ``error_message`` prefixed with ``Zalo Bot error``
  for downstream classification.
- Body formatting truncates at 2000 chars and merges title + message.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notification_channels.zalo_bot_channel import (
    ZaloBotChannel,
    _MAX_TEXT_LENGTH,
    _format_text,
)
from app.gateways.zalo_bot import ZaloBotSendResult


def _delivery(
    *,
    delivery_id: int = 1,
    user_id: int | None = 42,
    payload: dict | None = None,
):
    return SimpleNamespace(
        id=delivery_id,
        user_id=user_id,
        payload_snapshot=payload or {"title": "Hi", "message": "Body"},
    )


@pytest.mark.unit
class TestFormatText:
    def test_merges_title_and_message_with_blank_line(self):
        body = _format_text({"title": "T", "message": "M"})
        assert body == "T\n\nM"

    def test_falls_back_to_message_only(self):
        body = _format_text({"title": "", "message": "Only message"})
        assert body == "Only message"

    def test_falls_back_to_title_only(self):
        body = _format_text({"title": "Only title", "message": ""})
        assert body == "Only title"

    def test_truncates_at_max_length(self):
        body = _format_text({"title": "", "message": "x" * (_MAX_TEXT_LENGTH + 50)})
        assert len(body) == _MAX_TEXT_LENGTH
        assert body.endswith("…")

    def test_at_limit_passes_through(self):
        body = _format_text({"title": "", "message": "x" * _MAX_TEXT_LENGTH})
        assert body == "x" * _MAX_TEXT_LENGTH


@pytest.mark.unit
@pytest.mark.asyncio
class TestExecuteDelivery:
    async def test_no_user_id_is_permanent(self):
        ch = ZaloBotChannel()
        result = await ch.execute_delivery(_delivery(user_id=None), db=AsyncMock())
        assert result.success is False
        assert result.error_message == "no_zalo_bot_link"

    async def test_no_active_link_is_permanent(self):
        repo = MagicMock()
        repo.get_active_by_user_id = AsyncMock(return_value=None)
        with patch(
            "app.repositories.staff_zalo_bot_link_repository.StaffZaloBotLinkRepository",
            return_value=repo,
        ):
            ch = ZaloBotChannel()
            result = await ch.execute_delivery(_delivery(), db=AsyncMock())
        assert result.success is False
        assert result.error_message == "no_zalo_bot_link"
        assert result.failed_ids == [42]

    async def test_active_link_happy_path(self):
        link = SimpleNamespace(chat_id="chat_alpha_xxxxxxxx", user_id=42)
        repo = MagicMock()
        repo.get_active_by_user_id = AsyncMock(return_value=link)

        gateway = MagicMock()
        gateway.send_message = AsyncMock(
            return_value=ZaloBotSendResult(success=True, message_id="m-007")
        )

        with patch(
            "app.repositories.staff_zalo_bot_link_repository.StaffZaloBotLinkRepository",
            return_value=repo,
        ), patch("app.gateways.zalo_bot.zalo_bot_gateway", gateway):
            ch = ZaloBotChannel()
            result = await ch.execute_delivery(_delivery(), db=AsyncMock())

        assert result.success is True
        assert result.sent_count == 1
        assert result.provider_message_id == "m-007"
        gateway.send_message.assert_awaited_once()
        sent_chat_id, sent_text = gateway.send_message.await_args.args
        assert sent_chat_id == "chat_alpha_xxxxxxxx"
        assert sent_text == "Hi\n\nBody"

    async def test_gateway_failure_maps_to_error_message(self):
        link = SimpleNamespace(chat_id="chat_x", user_id=42)
        repo = MagicMock()
        repo.get_active_by_user_id = AsyncMock(return_value=link)

        gateway = MagicMock()
        gateway.send_message = AsyncMock(
            return_value=ZaloBotSendResult(
                success=False, error_code=429, error_message="rate limited"
            )
        )

        with patch(
            "app.repositories.staff_zalo_bot_link_repository.StaffZaloBotLinkRepository",
            return_value=repo,
        ), patch("app.gateways.zalo_bot.zalo_bot_gateway", gateway):
            ch = ZaloBotChannel()
            result = await ch.execute_delivery(_delivery(), db=AsyncMock())

        assert result.success is False
        assert "Zalo Bot error 429" in result.error_message
        assert "rate limited" in result.error_message
        assert result.failed_ids == [42]

    async def test_empty_text_is_permanent(self):
        link = SimpleNamespace(chat_id="chat_x", user_id=42)
        repo = MagicMock()
        repo.get_active_by_user_id = AsyncMock(return_value=link)

        with patch(
            "app.repositories.staff_zalo_bot_link_repository.StaffZaloBotLinkRepository",
            return_value=repo,
        ):
            ch = ZaloBotChannel()
            result = await ch.execute_delivery(
                _delivery(payload={"title": "", "message": ""}), db=AsyncMock()
            )

        assert result.success is False
        assert result.error_message == "empty_text"


@pytest.mark.unit
@pytest.mark.asyncio
class TestSendBatch:
    async def test_send_always_errors(self):
        ch = ZaloBotChannel()
        res = await ch.send([], [1, 2, 3], context={})
        assert res.success is False
        assert "execute_delivery" in res.error_message


@pytest.mark.unit
class TestValidateConfig:
    def test_empty_config_is_valid(self):
        """zalo_bot needs no per-action config — link record carries target."""
        assert ZaloBotChannel().validate_config({}) is True
        assert ZaloBotChannel().validate_config(None) is True
