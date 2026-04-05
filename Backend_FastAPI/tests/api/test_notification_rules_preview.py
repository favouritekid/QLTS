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

    # PR3.5: Expanded coverage

    async def test_preview_empty_actions_returns_default_browser(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """Empty actions list should return a single default browser preview."""
        resp = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "lead_created",
                "title_template": "New lead: $lead_name",
                "message_template": "Created by $actor_name",
                "sample_payload": {"lead_name": "Test", "actor_name": "Admin"},
                "actions": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["actions"]) == 1
        assert data["actions"][0]["channel"] == "browser"
        assert data["actions"][0]["step"] == 1
        assert data["actions"][0]["rendered_title"] == "New lead: Test"
        assert data["actions"][0]["rendered_message"] == "Created by Admin"

    async def test_preview_template_override_shows_indicator(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """template_override mode should show explicit indicator, not default content."""
        resp = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "lead_assigned",
                "title_template": "Default title",
                "message_template": "Default msg",
                "sample_payload": {"lead_id": "1"},
                "actions": [
                    {
                        "step": 1,
                        "channel": "email",
                        "content_mode": "template_override",
                        "template_code": "TPL_SOME_CODE",
                        "delay_minutes": 0,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        action = data["actions"][0]
        # Should show template indicator, NOT default content
        assert "Template" in action["rendered_title"] or "TPL_SOME_CODE" in action["rendered_title"]
        assert action["content_mode"] == "template_override"

    async def test_preview_multi_action_response_shape(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """Multiple actions should each get a preview with correct step/channel."""
        resp = await client.post(
            "/api/notification-rules/preview",
            headers=admin_token_headers,
            json={
                "event": "application_status_changed",
                "title_template": "Status: $new_status",
                "message_template": "App #$application_id changed",
                "sample_payload": {
                    "application_id": "42",
                    "new_status": "approved",
                    "lead_id": "7",
                },
                "actions": [
                    {"step": 1, "channel": "browser", "delay_minutes": 0},
                    {"step": 2, "channel": "email", "delay_minutes": 5,
                     "branch_key": "email_group"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["actions"]) == 2
        assert data["actions"][0]["step"] == 1
        assert data["actions"][0]["channel"] == "browser"
        assert data["actions"][1]["step"] == 2
        assert data["actions"][1]["channel"] == "email"
        assert data["actions"][1]["branch_key"] == "email_group"
        assert data["actions"][1]["delay_minutes"] == 5
        # Both should have rendered content
        assert "approved" in data["actions"][0]["rendered_title"]
        assert data["rendered_link"] is not None
