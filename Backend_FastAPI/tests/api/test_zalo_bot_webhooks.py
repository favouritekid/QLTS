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
            "result": {
                "event_name": "follow",
                "message": {"chat": {"id": "x"}, "text": "ignored"},
            }
        }
        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=body,
            headers={"X-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "ignored_event"
        gateway_mock.send_message.assert_not_awaited()

    async def test_empty_chat_or_text_noop(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        body = {
            "result": {
                "event_name": "message.text.received",
                "message": {"chat": {"id": ""}, "text": "x"},
            }
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
        verify.return_value = (True, "Liên kết thành công!")

        resp = await client.post(
            "/api/webhooks/zalo-bot",
            json=_payload("/lienkiet ABC123"),
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
            json=_payload("/lienkiet abc"),
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
            json=_payload("/lienkiet ABC123"),
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
    async def test_huylienkiet_calls_service(
        self, client: AsyncClient, configured_secret, gateway_mock, link_service_mock
    ):
        _, unlink = link_service_mock
        unlink.return_value = (True, "Đã huỷ liên kết.")

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
        assert "/lienkiet" in sent_text
        assert "/huylienkiet" in sent_text
        assert "/trangthai" in sent_text


@pytest.mark.asyncio
class TestRateLimit:
    async def test_eleventh_command_per_minute_rate_limited(
        self, client: AsyncClient, configured_secret, gateway_mock
    ):
        # Patch the symbols imported into the router module — patching
        # ``app.database`` would not redirect the router's local binding.
        counters = {}

        async def fake_incr(key, amount=1):
            counters[key] = counters.get(key, 0) + amount
            return counters[key]

        async def fake_expire(key, seconds):
            return True

        with patch(
            "app.routers.zalo_bot_webhooks.safe_redis_incr",
            new=AsyncMock(side_effect=fake_incr),
        ), patch(
            "app.routers.zalo_bot_webhooks.safe_redis_expire",
            new=AsyncMock(side_effect=fake_expire),
        ):
            chat = "chat_burst_xxx"
            # 10 commands pass.
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
