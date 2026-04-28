"""Webhook router tests — Step 18.

Auth is a shared secret in ``X-Bot-Api-Secret-Token`` headers, set via
``settings.ZALO_BOT_WEBHOOK_SECRET``. The test patches the gateway and
``zalo_bot_link_service`` so we can drive the router branches without
hitting real Zalo / Redis link state.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import settings


SECRET = "test-webhook-secret-xyz"


def _payload(text: str, chat_id: str = "chat_alpha_xxxxxxxx") -> dict:
    """Real Zalo Bot Platform shape: ``event_name`` at TOP level, message
    nested under ``result``. Captured from a live webhook hit on
    2026-04-27 after initial smoke showed ignored_event for every command.
    """
    return {
        "event_name": "message.text.received",
        "result": {
            "message": {
                "chat": {"id": chat_id},
                "text": text,
                "from": {"display_name": "Officer A"},
            },
        },
    }


def _payload_legacy_nested(text: str, chat_id: str = "chat_alpha_xxxxxxxx") -> dict:
    """Legacy shape used by plan v5 examples — ``event_name`` nested under
    ``result``. The router now accepts this too via fallback so any future
    provider variant doesn't regress.
    """
    return {
        "result": {
            "event_name": "message.text.received",
            "message": {
                "chat": {"id": chat_id},
                "text": text,
                "from": {"display_name": "Officer A"},
            },
        }
    }


@pytest.fixture
def gateway_mock():
    gateway = AsyncMock()
    gateway.send_message = AsyncMock()
    with patch("app.gateways.zalo_bot.zalo_bot_gateway", gateway):
        yield gateway


@pytest.fixture
def link_service_mock():
    """Replace zalo_bot_link_service functions inside the router module."""
    with patch(
        "app.services.zalo_bot_link_service.verify_and_link",
        new=AsyncMock(),
    ) as verify, patch(
        "app.services.zalo_bot_link_service.unlink_by_chat_id",
        new=AsyncMock(),
    ) as unlink:
        yield verify, unlink


@pytest.fixture
def configured_secret(monkeypatch):
    monkeypatch.setattr(settings, "ZALO_BOT_WEBHOOK_SECRET", SECRET)
    yield SECRET


@pytest.mark.asyncio
class TestSecretGuard:
    async def test_missing_secret_header_returns_401(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        resp = await client.post("/api/webhooks/zalo-bot", json=_payload("/trangthai"))
        assert resp.status_code == 401

    async def test_wrong_secret_returns_401(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/trangthai"),
            headers={"X-Bot-Api-Secret-Token": "wrong"},
        )
        assert resp.status_code == 401

    async def test_empty_configured_secret_fails_closed(
        self, client: AsyncClient, monkeypatch, gateway_mock
    ):
        # Empty configured secret → fail-closed even if attacker presents
        # an empty string (which would otherwise pass compare_digest).
        monkeypatch.setattr(settings, "ZALO_BOT_WEBHOOK_SECRET", "")
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/trangthai"),
            headers={"X-Bot-Api-Secret-Token": ""},
        )
        assert resp.status_code == 401

    async def test_correct_secret_lets_request_through(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/trangthai"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestPayloadShape:
    async def test_invalid_json_returns_400(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            content=b"not-json",
            headers={
                "X-Bot-Api-Secret-Token": SECRET,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400

    async def test_non_text_event_ignored_with_200(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        body = {
            "event_name": "follow",
            "result": {
                "message": {"chat": {"id": "x"}, "text": "ignored"},
            },
        }
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=body,
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "ignored_event"
        gateway_mock.send_message.assert_not_awaited()

    async def test_top_level_event_name_is_recognized(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        """Real Zalo payload puts ``event_name`` at top level. Pre-fix the
        router only read it from ``result.event_name`` and silently
        ignored every real message — repro of 2026-04-27 smoke regression.
        """
        verify, _ = link_service_mock
        verify.return_value = (False, "invalid", None)
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienket ABC123"),  # uses top-level shape
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        # Must NOT be ignored_event — handler must reach verify_and_link
        assert resp.json().get("mode") != "ignored_event", (
            "top-level event_name not recognised → real Zalo traffic dropped silently"
        )

    async def test_legacy_nested_event_name_still_works(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        """Legacy shape (event_name nested under result) keeps working as
        a fallback, so any provider variant doesn't regress."""
        verify, _ = link_service_mock
        verify.return_value = (False, "invalid", None)
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload_legacy_nested("/lienket ABC123"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json().get("mode") != "ignored_event"

    async def test_empty_chat_or_text_noop(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        body = {
            "event_name": "message.text.received",
            "result": {
                "message": {"chat": {"id": ""}, "text": "x"},
            },
        }
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=body,
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "noop"


@pytest.mark.asyncio
class TestLienKietCommand:
    async def test_valid_code_calls_service_and_replies(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        verify, _ = link_service_mock
        verify.return_value = (True, "Liên kết thành công!", None)

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienket ABC123"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "mode": "verify_and_link", "linked": True}
        verify.assert_awaited_once()
        # Reply was forwarded to the user.
        gateway_mock.send_message.assert_awaited()
        sent_args = gateway_mock.send_message.await_args.args
        assert sent_args[1] == "Liên kết thành công!"

    async def test_invalid_format_does_not_call_service(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        verify, _ = link_service_mock
        # Lowercase + 3 chars — does not match [A-Z0-9]{6}.
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienket abc"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "bad_format"
        verify.assert_not_awaited()
        gateway_mock.send_message.assert_awaited()

    async def test_service_error_rollback_generic_reply(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        verify, _ = link_service_mock
        verify.side_effect = RuntimeError("boom")

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienket ABC123"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        # 200 so Zalo doesn't retry and double-consume the code.
        assert resp.status_code == 200
        assert resp.json()["mode"] == "service_error"
        # Reply must be generic — no stack trace, no "boom".
        sent_text = gateway_mock.send_message.await_args.args[1]
        assert "boom" not in sent_text
        assert "RuntimeError" not in sent_text
        assert "Lỗi hệ thống" in sent_text


@pytest.mark.asyncio
class TestUnlinkCommand:
    async def test_huylienket_calls_service(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        _, unlink = link_service_mock
        unlink.return_value = (True, "Đã huỷ liên kết.", None)

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/huylienket"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "unlink"
        unlink.assert_awaited_once()


@pytest.mark.asyncio
class TestLegacyCommandSpelling:
    """Backward-compat: accept the old (incorrect Vietnamese) spelling
    ``/lienkiet`` and ``/huylienkiet`` so staff who copied previous
    instruction text still link successfully. Canonical spelling is
    ``/lienket`` (liên kết without diacritics)."""

    async def test_legacy_lienkiet_still_routed(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        verify, _ = link_service_mock
        verify.return_value = (True, "Liên kết thành công!", None)

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienkiet ABC123"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "verify_and_link"
        verify.assert_awaited_once()

    async def test_legacy_huylienkiet_still_routed(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        _, unlink = link_service_mock
        unlink.return_value = (True, "Đã huỷ liên kết.", None)

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/huylienkiet"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "unlink"
        unlink.assert_awaited_once()


@pytest.mark.asyncio
class TestStatusCommand:
    async def test_trangthai_does_not_leak_user_id(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        # No active link → should reply "Chưa liên kết." with no other detail.
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/trangthai", chat_id="chat_unlinked_zzz"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["linked"] is False
        sent_text = gateway_mock.send_message.await_args.args[1]
        # Reply must not contain user_id or any number that could be one.
        assert "user_id" not in sent_text.lower()
        assert sent_text == "Chưa liên kết."


@pytest.mark.asyncio
class TestUnknownCommand:
    async def test_help_text_for_unknown(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("hello bot"),
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "help"
        sent_text = gateway_mock.send_message.await_args.args[1]
        assert "/lienket" in sent_text
        assert "/huylienket" in sent_text
        assert "/trangthai" in sent_text


@pytest.mark.asyncio
class TestReplyDeliveryFailure:
    """Pre-fix behaviour: ``send_message`` failures were silently
    discarded — webhook returned 200, link row was created, but the user
    saw nothing and operator log was empty. Lock in: webhook still
    returns 200 (so Zalo doesn't double-consume the code) but a warning
    with ``error_code`` + ``error_message`` is emitted."""

    async def test_api_failure_logs_warning_but_keeps_200(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock, caplog
    ):
        # Unique chat_id so the per-chat_id rate-limit counter (real
        # Redis, shared across tests in this module) doesn't push us
        # into the rate_limited branch before the verify path runs.
        from app.gateways.zalo_bot import ZaloBotSendResult

        verify, _ = link_service_mock
        verify.return_value = (True, "Liên kết thành công!", None)
        gateway_mock.send_message.return_value = ZaloBotSendResult(
            success=False, error_code=429, error_message="quota exceeded"
        )

        with caplog.at_level("WARNING"):
            resp = await client.post(
                "/api/webhooks/zalo-bot",
                json=_payload("/lienket ABC123", chat_id="chat_replyfail_uniq"),
                headers={"X-Bot-Api-Secret-Token": SECRET},
            )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "verify_and_link"
        assert resp.json()["linked"] is True
        # Operator must see the API-level failure — pre-fix it was lost.
        joined = " ".join(record.getMessage() for record in caplog.records)
        assert "zalo_bot reply send failed" in joined or "429" in joined

    async def test_api_success_does_not_log_warning(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock, caplog
    ):
        from app.gateways.zalo_bot import ZaloBotSendResult

        verify, _ = link_service_mock
        verify.return_value = (True, "Liên kết thành công!", None)
        gateway_mock.send_message.return_value = ZaloBotSendResult(
            success=True, message_id="msg_xyz"
        )

        with caplog.at_level("WARNING"):
            resp = await client.post(
                "/api/webhooks/zalo-bot",
                json=_payload("/lienket ABC123", chat_id="chat_replyok_uniq"),
                headers={"X-Bot-Api-Secret-Token": SECRET},
            )

        assert resp.status_code == 200
        joined = " ".join(record.getMessage() for record in caplog.records)
        assert "reply send failed" not in joined


@pytest.mark.asyncio
class TestRateLimit:
    @staticmethod
    def _patch_redis():
        """Patch the three Redis helpers the router uses for the rate
        limit path. ``safe_redis_set`` simulates ``SET NX EX`` semantics:
        truthy on first set, ``None`` on subsequent within window."""
        counters = {}
        notified = set()

        async def fake_incr(key, amount=1):
            counters[key] = counters.get(key, 0) + amount
            return counters[key]

        async def fake_expire(key, seconds):
            return True

        async def fake_set(key, value, ex=None, nx=False):
            if nx and key in notified:
                return None
            notified.add(key)
            return True

        return patch(
            "app.routers.zalo_bot_webhooks.safe_redis_incr",
            new=AsyncMock(side_effect=fake_incr),
        ), patch(
            "app.routers.zalo_bot_webhooks.safe_redis_expire",
            new=AsyncMock(side_effect=fake_expire),
        ), patch(
            "app.routers.zalo_bot_webhooks.safe_redis_set",
            new=AsyncMock(side_effect=fake_set),
        )

    async def test_eleventh_command_per_minute_rate_limited(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        incr_p, expire_p, set_p = self._patch_redis()
        with incr_p, expire_p, set_p:
            chat = "chat_burst_xxx"
            for _ in range(10):
                resp = await client.post(
                    "/api/webhooks/zalo-bot",
                    json=_payload("/trangthai", chat_id=chat),
                    headers={"X-Bot-Api-Secret-Token": SECRET},
                )
                assert resp.status_code == 200
                assert resp.json().get("mode") != "rate_limited"
            # 11th is throttled.
            resp = await client.post(
                "/api/webhooks/zalo-bot",
                json=_payload("/trangthai", chat_id=chat),
                headers={"X-Bot-Api-Secret-Token": SECRET},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rate_limited"

    async def test_rate_limited_replies_only_once_per_window(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        """Pre-fix: each rate-limited request still triggered a
        send_message reply, so an attacker blasting 1 chat at 100/min
        burned the Basic-plan quota in minutes (10 normal sends + 90
        rate-limit-reply sends per minute per chat). Lock in: at most
        one rate-limit reply per window — subsequent rate-limited hits
        are silently dropped."""
        incr_p, expire_p, set_p = self._patch_redis()
        with incr_p, expire_p, set_p:
            chat = "chat_amplify_xxx"
            # 30 hits — first 10 pass through (1 send each), 11..30 are
            # rate-limited (only the first should send a reply).
            for _ in range(30):
                await client.post(
                    "/api/webhooks/zalo-bot",
                    json=_payload("/trangthai", chat_id=chat),
                    headers={"X-Bot-Api-Secret-Token": SECRET},
                )

        # 10 status replies + exactly 1 rate-limit reply = 11 total.
        # Pre-fix this would have been 10 + 20 = 30 sends.
        assert gateway_mock.send_message.await_count == 11, (
            f"expected 11 sends (10 status + 1 once-only rate-limit), "
            f"got {gateway_mock.send_message.await_count} — "
            "rate-limit reply is amplifying quota use"
        )
