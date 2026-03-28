# tests/unit/test_condition_context.py
"""Phase 2: Unit tests for condition context builder — analyze + build."""
import pytest
from app.services.notification_condition_context import (
    analyze_condition, build_evaluation_context,
    _PAYLOAD_PROJECTABLE, _ENRICHMENT_FIELDS,
)
from app.core.events import SystemEvents


class TestAnalyzeCondition:
    """analyze_condition returns correct (projection_ns, enrichment_ns)."""

    def test_none_condition(self):
        proj, enrich = analyze_condition(None)
        assert proj == set()
        assert enrich == set()

    def test_empty_condition(self):
        proj, enrich = analyze_condition({})
        assert proj == set()
        assert enrich == set()

    def test_flat_field_no_namespace(self):
        cond = {"field": "lead_id", "operator": "eq", "value": 42}
        proj, enrich = analyze_condition(cond)
        assert proj == set()
        assert enrich == set()

    def test_event_namespace_projection_only(self):
        cond = {"field": "event.new_status_id", "operator": "eq", "value": "x"}
        proj, enrich = analyze_condition(cond)
        assert "event" in proj
        assert "event" not in enrich

    def test_actor_name_projection_only(self):
        """actor.name is projectable from payload, no enrichment needed."""
        cond = {"field": "actor.name", "operator": "eq", "value": "Admin"}
        proj, enrich = analyze_condition(cond)
        assert "actor" in proj
        assert "actor" not in enrich

    def test_actor_role_needs_enrichment(self):
        """actor.role is NOT in payload, needs DB lookup."""
        cond = {"field": "actor.role", "operator": "eq", "value": "admin"}
        proj, enrich = analyze_condition(cond)
        assert "actor" in proj
        assert "actor" in enrich

    def test_lead_source_needs_enrichment(self):
        cond = {"field": "lead.source", "operator": "eq", "value": "web"}
        proj, enrich = analyze_condition(cond)
        assert "lead" in proj
        assert "lead" in enrich

    def test_compound_merges_namespaces(self):
        cond = {
            "operator": "and",
            "conditions": [
                {"field": "actor.role", "operator": "eq", "value": "admin"},
                {"field": "event.new_status_id", "operator": "eq", "value": "x"},
            ],
        }
        proj, enrich = analyze_condition(cond)
        assert proj == {"actor", "event"}
        assert enrich == {"actor"}


class TestBuildEvaluationContextProjection:
    """build_evaluation_context projection (no DB)."""

    @pytest.mark.asyncio
    async def test_empty_ns_returns_payload(self):
        payload = {"lead_id": 42, "actor_id": 1}
        result = await build_evaluation_context(None, SystemEvents.LEAD_CREATED, payload, set(), set())
        assert result is payload  # same object, zero overhead

    @pytest.mark.asyncio
    async def test_event_namespace_projection(self):
        payload = {"old_status": "new", "new_status": "contacted", "lead_id": 1}
        result = await build_evaluation_context(
            None, SystemEvents.LEAD_STATUS_CHANGED, payload, {"event"}, set()
        )
        assert result["event"]["old_status_id"] == "new"
        assert result["event"]["new_status_id"] == "contacted"
        # flat keys preserved
        assert result["old_status"] == "new"

    @pytest.mark.asyncio
    async def test_actor_namespace_projection(self):
        payload = {"actor_id": 1, "actor_name": "Admin"}
        result = await build_evaluation_context(
            None, SystemEvents.LEAD_CREATED, payload, {"actor"}, set()
        )
        assert result["actor"]["id"] == 1
        assert result["actor"]["name"] == "Admin"

    @pytest.mark.asyncio
    async def test_lead_namespace_projection(self):
        payload = {"lead_id": 42, "lead_name": "Test", "officer_id": 5}
        result = await build_evaluation_context(
            None, SystemEvents.LEAD_ASSIGNED, payload, {"lead"}, set()
        )
        assert result["lead"]["id"] == 42
        assert result["lead"]["name"] == "Test"
        assert result["lead"]["officer_id"] == 5

    @pytest.mark.asyncio
    async def test_event_unit_id_for_imported(self):
        payload = {"unit_id": 10, "total_imported": 50, "filename": "x.csv", "actor_id": 1, "actor_name": "Admin"}
        result = await build_evaluation_context(
            None, SystemEvents.LEAD_IMPORTED, payload, {"event"}, set()
        )
        assert result["event"]["unit_id"] == 10
        assert result["event"]["total_imported"] == 50
        assert result["event"]["filename"] == "x.csv"
