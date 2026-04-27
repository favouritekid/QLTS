# tests/api/test_notification_event_groups_api.py
"""
HTTP contract tests for /api/notifications/event-groups{,/metadata}.

Wave 2 #6 (2026-04-27): broadcast-only groups (e.g. ``organization``)
must not appear in responses, and PATCH must reject them. Previously
the service fell back to ``defaults.get(channel, True)`` for groups
not in ``DEFAULT_GROUP_CHANNELS``, so Organization rendered as a
tunable row with all channels checked.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestNotificationEventGroupsApi:
    """Contract tests for event-groups preferences endpoints."""

    async def test_event_groups_response_excludes_organization(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        """GET /event-groups: response must not include `organization`
        in either the metadata `groups` list or the `preferences` dict.
        """
        resp = await client.get(
            "/api/notifications/event-groups",
            headers=admin_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        group_ids = {g["id"].lower() for g in body["groups"]}
        assert "organization" not in group_ids, (
            "Organization is broadcast-only; must not be returned to the "
            "settings UI as a tunable row"
        )

        preference_keys = {k.lower() for k in body["preferences"].keys()}
        assert "organization" not in preference_keys, (
            "Organization preferences should not be served — they would "
            "default to all-channels-checked via the legacy fallback"
        )

    async def test_event_groups_metadata_excludes_organization(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        """GET /event-groups/metadata: same exclusion applies to the
        metadata-only endpoint used by the settings UI to render the
        category list.
        """
        resp = await client.get(
            "/api/notifications/event-groups/metadata",
            headers=admin_token_headers,
        )
        assert resp.status_code == 200, resp.text
        groups = resp.json()
        ids = {g["id"].lower() for g in groups}
        assert "organization" not in ids

    async def test_patch_event_group_rejects_organization(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        """PATCH /event-groups must reject `organization` with 400 even
        though the enum value still exists. Pin the API surface so a
        stale UI cannot accidentally write a preference row that the
        dispatcher will never honor anyway.
        """
        resp = await client.patch(
            "/api/notifications/event-groups",
            headers=admin_token_headers,
            json={
                "event_group": "organization",
                "channel": "browser",
                "enabled": False,
            },
        )
        assert resp.status_code == 400, resp.text
        detail = resp.json().get("detail", "")
        assert "not user-tunable" in detail or "organization" in detail.lower()

    async def test_patch_event_group_accepts_tunable_group(
        self,
        client: AsyncClient,
        admin_token_headers: dict,
    ):
        """Sanity: a tunable group (e.g. `lead`) still works after the
        validator change."""
        resp = await client.patch(
            "/api/notifications/event-groups",
            headers=admin_token_headers,
            json={
                "event_group": "lead",
                "channel": "browser",
                "enabled": False,
            },
        )
        assert resp.status_code == 200, resp.text

        # Restore default to keep test isolation lossless
        await client.patch(
            "/api/notifications/event-groups",
            headers=admin_token_headers,
            json={
                "event_group": "lead",
                "channel": "browser",
                "enabled": True,
            },
        )
