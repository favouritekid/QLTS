"""Zalo Bot Platform HTTP gateway.

Wraps the public Bot API at ``https://bot-api.zaloplatforms.com/bot<TOKEN>/<method>``.
Token comes from ``settings.ZALO_BOT_TOKEN`` and **must never** be logged
or surfaced in error messages — callers and logs must only see opaque
HTTP method names like ``sendMessage``.

Rate limit / retry policy is handled by the channel sender layer (Step 8),
not here. This module is intentionally thin: I/O, JSON, and a typed
result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

ZALO_BOT_API_BASE = "https://bot-api.zaloplatforms.com"
MAX_TEXT_LENGTH = 2000  # Zalo Bot Platform `sendMessage` text cap


@dataclass
class ZaloBotSendResult:
    success: bool
    message_id: Optional[str] = None
    error_code: int = 0
    error_message: str = ""


class ZaloBotGateway:
    """Stateless wrapper. Reads ``settings.ZALO_BOT_TOKEN`` per call so a
    test that monkey-patches the setting takes effect immediately.
    """

    def _api_url(self, method: str) -> str:
        return f"{ZALO_BOT_API_BASE}/bot{settings.ZALO_BOT_TOKEN}/{method}"

    @staticmethod
    def _safe_error_message(method: str, exc: Exception) -> str:
        """Return an error string that cannot accidentally contain the bot
        token. ``str(exc)`` is unsafe for httpx errors because the request
        URL (with embedded token) appears in the repr.
        """
        return f"{method} failed: {type(exc).__name__}"

    async def send_message(self, chat_id: str, text: str) -> ZaloBotSendResult:
        if not text or len(text) > MAX_TEXT_LENGTH:
            return ZaloBotSendResult(
                success=False,
                error_code=-1000,
                error_message=f"Text length invalid: {len(text) if text else 0}",
            )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._api_url("sendMessage"),
                    json={"chat_id": chat_id, "text": text},
                )
            data = resp.json()
            if data.get("ok"):
                return ZaloBotSendResult(
                    success=True,
                    message_id=data.get("result", {}).get("message_id"),
                )
            return ZaloBotSendResult(
                success=False,
                error_code=data.get("error_code", -1),
                error_message=data.get("description", "unknown_error"),
            )
        except httpx.TimeoutException:
            log.warning("Zalo Bot API timeout", method="sendMessage")
            return ZaloBotSendResult(
                success=False, error_code=-999, error_message="timeout"
            )
        except Exception as exc:
            # Log only the exception class name + method name. Never log
            # str(exc) because httpx serialises the full request URL —
            # which embeds the bot token — into repr.
            log.error(
                "Zalo Bot API failed",
                method="sendMessage",
                error_type=type(exc).__name__,
            )
            return ZaloBotSendResult(
                success=False,
                error_code=-998,
                error_message=self._safe_error_message("sendMessage", exc),
            )

    async def get_me(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._api_url("getMe"))
            data = resp.json()
            return data.get("result") if data.get("ok") else None
        except Exception as exc:
            log.warning(
                "Zalo Bot getMe failed",
                error_type=type(exc).__name__,
            )
            return None

    async def set_webhook(self, url: str, secret_token: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self._api_url("setWebhook"),
                    json={"url": url, "secret_token": secret_token},
                )
            return bool(resp.json().get("ok", False))
        except Exception as exc:
            log.warning(
                "Zalo Bot setWebhook failed",
                error_type=type(exc).__name__,
            )
            return False

    async def delete_webhook(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._api_url("deleteWebhook"))
            return bool(resp.json().get("ok", False))
        except Exception as exc:
            log.warning(
                "Zalo Bot deleteWebhook failed",
                error_type=type(exc).__name__,
            )
            return False


zalo_bot_gateway = ZaloBotGateway()
