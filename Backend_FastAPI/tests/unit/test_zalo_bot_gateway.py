"""Unit tests for ``ZaloBotGateway``.

The gateway is intentionally thin — these tests pin three contracts:
1. ``send_message`` enforces the 1..2000 char text bound up-front.
2. Errors never leak ``ZALO_BOT_TOKEN`` into log records or the result.
3. The success/error result shape stays stable for downstream consumers.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.gateways.zalo_bot import (
    MAX_TEXT_LENGTH,
    ZaloBotGateway,
    ZaloBotSendResult,
)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSendMessageTextBounds:
    async def test_empty_text_rejected_without_network(self):
        gw = ZaloBotGateway()
        with patch("httpx.AsyncClient") as m_client:
            res = await gw.send_message("chat_x", "")
        assert res.success is False
        assert "length" in res.error_message.lower()
        m_client.assert_not_called(), "must short-circuit before HTTP"

    async def test_text_at_limit_is_accepted(self):
        gw = ZaloBotGateway()
        text = "x" * MAX_TEXT_LENGTH

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": "m1"}}
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.gateways.zalo_bot.httpx.AsyncClient", return_value=mock_client):
            res = await gw.send_message("chat_x", text)

        assert res.success is True
        assert res.message_id == "m1"

    async def test_text_over_limit_rejected_without_network(self):
        gw = ZaloBotGateway()
        with patch("httpx.AsyncClient") as m_client:
            res = await gw.send_message("chat_x", "x" * (MAX_TEXT_LENGTH + 1))
        assert res.success is False
        m_client.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
class TestTokenLeakage:
    """The bot token is the credential — it MUST NOT appear in logs or
    in the ``ZaloBotSendResult.error_message`` returned to the caller.
    httpx's default ``str(exc)`` for transport errors embeds the request
    URL, which embeds the token, hence these guards.
    """

    async def test_transport_error_does_not_leak_token_in_result(self, monkeypatch):
        monkeypatch.setattr(settings, "ZALO_BOT_TOKEN", "super-secret-token-xyz")
        gw = ZaloBotGateway()

        # Simulate a transport-level error whose default repr would carry
        # the request URL (and thus the token).
        boom_url = (
            "https://bot-api.zaloplatforms.com/botsuper-secret-token-xyz/sendMessage"
        )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError(f"connect failed url={boom_url}")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.gateways.zalo_bot.httpx.AsyncClient", return_value=mock_client):
            res = await gw.send_message("chat_x", "hello")

        assert res.success is False
        assert "super-secret-token-xyz" not in res.error_message, (
            "token must never appear in error_message — caller logs may surface this"
        )
        # Caller should still get a useful error category.
        assert "ConnectError" in res.error_message

    async def test_transport_error_does_not_leak_token_in_logs(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "ZALO_BOT_TOKEN", "tok-no-leak-please-789")
        gw = ZaloBotGateway()

        boom_url = (
            "https://bot-api.zaloplatforms.com/bottok-no-leak-please-789/sendMessage"
        )
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ReadTimeout(f"timeout fetching {boom_url}")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with caplog.at_level(logging.DEBUG), \
             patch("app.gateways.zalo_bot.httpx.AsyncClient", return_value=mock_client):
            await gw.send_message("chat_x", "hello")

        joined = "\n".join(r.getMessage() for r in caplog.records)
        # caplog also captures structlog through stdlib bridge; check both
        # message body and any structured kwargs serialised into the record.
        for r in caplog.records:
            joined += " " + repr(getattr(r, "args", ""))
            joined += " " + repr(r.__dict__)
        assert "tok-no-leak-please-789" not in joined, (
            "token must never appear in log records — gateway logs only error_type"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestApiResponseShape:
    async def test_ok_false_carries_error_code_and_description(self):
        gw = ZaloBotGateway()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": False,
            "error_code": 429,
            "description": "rate limited",
        }
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.gateways.zalo_bot.httpx.AsyncClient", return_value=mock_client):
            res = await gw.send_message("chat_x", "hi")

        assert isinstance(res, ZaloBotSendResult)
        assert res.success is False
        assert res.error_code == 429
        assert res.error_message == "rate limited"
