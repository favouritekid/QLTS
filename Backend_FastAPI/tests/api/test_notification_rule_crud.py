# tests/api/test_notification_rule_crud.py
"""
PR3.5: Notification Rule CRUD API runtime tests.

Tests the full HTTP path: router → service → repository → DB → cache.
Uses only HTTP client (no direct DB access) — pure API contract tests.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestNotificationRuleCrudApi:
    """CRUD operations via the HTTP API."""

    async def test_create_rule_blocked_for_broadcast_event(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """broadcast_only events must be rejected."""
        resp = await client.post(
            "/api/notification-rules",
            json={
                "event": "lead_updated",
                "title_template": "Test",
                "message_template": "Test",
                "channels": ["browser"],
                "recipient_config": {"resolver_type": "lead_owner", "params": {}},
            },
            headers=admin_token_headers,
        )
        assert resp.status_code == 400
        assert "not a configurable user event" in resp.json()["detail"]

    async def test_create_rule_blocked_for_internal_future_event(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """internal_future events must be rejected."""
        resp = await client.post(
            "/api/notification-rules",
            json={
                "event": "payment_overdue",
                "title_template": "Test",
                "message_template": "Test",
                "channels": ["browser"],
                "recipient_config": {"resolver_type": "specific_users", "params": {}},
            },
            headers=admin_token_headers,
        )
        assert resp.status_code == 400
        assert "not a configurable user event" in resp.json()["detail"]

    async def test_metadata_returns_only_user_events(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """Metadata API must return only user-class events with resolver/link info."""
        resp = await client.get(
            "/api/notification-rules/metadata",
            headers=admin_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        event_keys = {e["event"] for e in data["events"]}

        # broadcast_only excluded
        assert "lead_updated" not in event_keys
        assert "unit_created" not in event_keys
        # internal_future excluded
        assert "payment_overdue" not in event_keys
        assert "ctv_lead_converted" not in event_keys
        # user events present
        assert "lead_assigned" in event_keys
        assert "lead_created" in event_keys

        # Check new fields from PR1
        lead_assigned = next(e for e in data["events"] if e["event"] == "lead_assigned")
        assert "allowed_resolvers" in lead_assigned
        assert isinstance(lead_assigned["allowed_resolvers"], list)
        assert "link_strategy" in lead_assigned

    async def test_list_rules_returns_paginated(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """List endpoint returns paginated rules."""
        resp = await client.get(
            "/api/notification-rules?page=1&page_size=10",
            headers=admin_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_count" in data
        assert "rules" in data
        assert isinstance(data["rules"], list)

    async def test_toggle_rule_via_api(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """Toggle endpoint flips enabled status."""
        # Get a rule first
        list_resp = await client.get(
            "/api/notification-rules?page=1&page_size=1",
            headers=admin_token_headers,
        )
        rules = list_resp.json().get("rules", [])
        if not rules:
            pytest.skip("No rules in DB")

        rule_id = rules[0]["id"]
        original_enabled = rules[0]["enabled"]

        # Toggle
        resp = await client.patch(
            f"/api/notification-rules/{rule_id}/toggle",
            headers=admin_token_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] != original_enabled

        # Toggle back
        await client.patch(
            f"/api/notification-rules/{rule_id}/toggle",
            headers=admin_token_headers,
        )

    async def test_delete_active_event_rule_blocked(
        self, client: AsyncClient, admin_token_headers: dict,
    ):
        """Deleting a rule for an active catalog event must return 400."""
        # Find a rule for a known active event
        list_resp = await client.get(
            "/api/notification-rules?event=system_alert&page=1&page_size=1",
            headers=admin_token_headers,
        )
        rules = list_resp.json().get("rules", [])
        if not rules:
            pytest.skip("No system_alert rule")

        resp = await client.delete(
            f"/api/notification-rules/{rules[0]['id']}",
            headers=admin_token_headers,
        )
        assert resp.status_code == 400
        assert "Cannot delete" in resp.json()["detail"]
