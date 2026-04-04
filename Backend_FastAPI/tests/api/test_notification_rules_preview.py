"""
API tests for POST /api/notification-rules/preview.

Locks the core PR2 preview contract:
- unknown events return 404
- non-user events are rejected with 400
- rendered_link always comes from code-owned catalog strategy
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestNotificationRulePreviewApi:
    async def test_preview_rejects_unknown_event(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        response = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "not_a_real_event",
                "title_template": "Test",
                "message_template": "Test",
                "sample_payload": {},
                "actions": [],
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Unknown event: not_a_real_event"

    async def test_preview_rejects_non_user_event(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        response = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "lead_updated",
                "title_template": "Lead updated",
                "message_template": "Lead #$lead_id updated",
                "sample_payload": {"lead_id": "123"},
                "actions": [],
            },
        )

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Event 'lead_updated' is not a configurable user event."
        )

    async def test_preview_uses_code_owned_link_render(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        response = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "lead_assigned",
                "title_template": "Lead duoc phan cong: $lead_name",
                "message_template": "Lead #$lead_id da duoc giao",
                "sample_payload": {
                    "lead_id": "123",
                    "lead_name": "Nguyen Van A",
                },
                "actions": [
                    {
                        "step": 1,
                        "channel": "browser",
                        "content_mode": "inline_override",
                        "content_override": {
                            "title_template": "Override title: $lead_name",
                            "message_template": "Override message for $lead_id",
                            "link_template": "/evil/path/should/not/win",
                        },
                        "delay_minutes": 0,
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["event"] == "lead_assigned"
        assert data["rendered_link"] == "/leads/123"
        assert data["link_strategy"] == "/leads/${lead_id}"
        assert len(data["actions"]) == 1
        assert data["actions"][0]["rendered_title"] == "Override title: Nguyen Van A"
        assert data["actions"][0]["rendered_message"] == "Override message for 123"
        assert data["actions"][0]["rendered_link"] == "/leads/123"
