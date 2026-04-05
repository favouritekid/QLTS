# tests/unit/test_condition_metadata_parity.py
"""Phase 2: Parity tests — condition_fields defined, operators valid, paths resolvable."""
import pytest
from app.core.events import SystemEvents
from app.core.event_metadata import (
    EVENT_METADATA_REGISTRY, ConditionField,
    _OPS_STRING, _OPS_NUMERIC, _OPS_BOOLEAN, _OPS_ARRAY,
)

# All 13 Phase 1 events
PHASE1_EVENTS = [
    SystemEvents.LEAD_CREATED, SystemEvents.LEAD_ASSIGNED,
    SystemEvents.LEAD_ASSIGNMENT_FAILED, SystemEvents.LEAD_REASSIGNED,
    SystemEvents.LEAD_STATUS_CHANGED, SystemEvents.LEAD_UPDATED,
    SystemEvents.LEAD_DELETED, SystemEvents.LEAD_RESTORED,
    SystemEvents.LEAD_IMPORTED,
    SystemEvents.CONSULTATION_CREATED, SystemEvents.CONSULTATION_UPDATED,
    SystemEvents.CONSULTATION_DELETED, SystemEvents.CONSULTATION_REMINDER,
]

OPERATOR_SETS_BY_TYPE = {
    "string": set(_OPS_STRING),
    "integer": set(_OPS_NUMERIC),
    "float": set(_OPS_NUMERIC),
    "datetime": set(_OPS_NUMERIC),
    "boolean": set(_OPS_BOOLEAN),
    "array": set(_OPS_ARRAY),
}


class TestConditionFieldsExist:
    """Every Phase 1 event must have condition_fields defined."""

    def test_all_phase1_events_have_condition_fields(self):
        missing = []
        for event in PHASE1_EVENTS:
            meta = EVENT_METADATA_REGISTRY.get(event)
            assert meta is not None, f"{event.value} not in registry"
            if not meta.condition_fields:
                missing.append(event.value)
        assert not missing, f"Events with empty condition_fields: {missing}"


class TestConditionFieldOperatorPolicy:
    """Operators must match type policy."""

    def test_operators_match_type(self):
        violations = []
        for event in PHASE1_EVENTS:
            meta = EVENT_METADATA_REGISTRY.get(event)
            if not meta or not meta.condition_fields:
                continue
            for cf in meta.condition_fields:
                expected = OPERATOR_SETS_BY_TYPE.get(cf.type)
                if expected is None:
                    violations.append(f"{event.value}: unknown type '{cf.type}' for {cf.path}")
                    continue
                actual = set(cf.operators)
                if actual != expected:
                    violations.append(
                        f"{event.value}: {cf.path} (type={cf.type}) operators {actual} != expected {expected}"
                    )
        assert not violations, "Operator policy violations:\n" + "\n".join(violations)


class TestLeadImportedNoLeadFields:
    """LEAD_IMPORTED must NOT have lead.* condition fields."""

    def test_no_lead_namespace(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.LEAD_IMPORTED]
        lead_fields = [cf.path for cf in meta.condition_fields if cf.path.startswith("lead.")]
        assert not lead_fields, f"LEAD_IMPORTED should not have lead.* fields: {lead_fields}"

    def test_has_event_unit_id(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.LEAD_IMPORTED]
        paths = {cf.path for cf in meta.condition_fields}
        assert "event.unit_id" in paths

    def test_has_event_total_imported(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.LEAD_IMPORTED]
        paths = {cf.path for cf in meta.condition_fields}
        assert "event.total_imported" in paths


class TestConsultationReminderNoActor:
    """CONSULTATION_REMINDER must NOT have actor.* condition fields."""

    def test_no_actor_namespace(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.CONSULTATION_REMINDER]
        actor_fields = [cf.path for cf in meta.condition_fields if cf.path.startswith("actor.")]
        assert not actor_fields, f"CONSULTATION_REMINDER should not have actor.* fields: {actor_fields}"


class TestLeadStatusChangedHasEventFields:
    """LEAD_STATUS_CHANGED must have event-specific condition fields."""

    def test_has_status_fields(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.LEAD_STATUS_CHANGED]
        paths = {cf.path for cf in meta.condition_fields}
        assert "event.old_status_id" in paths
        assert "event.new_status_id" in paths
        assert "event.old_stage_id" in paths
        assert "event.new_stage_id" in paths

    def test_status_fields_are_string_type(self):
        meta = EVENT_METADATA_REGISTRY[SystemEvents.LEAD_STATUS_CHANGED]
        for cf in meta.condition_fields:
            if cf.path in ("event.old_status_id", "event.new_status_id", "event.old_stage_id", "event.new_stage_id"):
                assert cf.type == "string", f"{cf.path} should be string, got {cf.type}"
