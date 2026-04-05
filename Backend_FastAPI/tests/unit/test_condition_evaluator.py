# tests/unit/test_condition_evaluator.py
"""Phase 2: Unit tests for condition evaluator upgrades — path resolver, operator aliases, field aliases."""
import pytest
from app.services.notification_rule_loader import (
    evaluate_condition, _resolve_field, _resolve_field_alias,
    OPERATOR_ALIASES, FIELD_ALIASES_GLOBAL,
)


class TestResolveField:
    """_resolve_field: dotted path and flat key resolution."""

    def test_flat_key(self):
        assert _resolve_field("lead_id", {"lead_id": 42}) == 42

    def test_dotted_path(self):
        ctx = {"actor": {"role": "admin", "unit_id": 10}}
        assert _resolve_field("actor.role", ctx) == "admin"

    def test_deeply_nested(self):
        ctx = {"event": {"old_status_id": "new"}}
        assert _resolve_field("event.old_status_id", ctx) == "new"

    def test_missing_namespace(self):
        assert _resolve_field("actor.role", {"lead_id": 1}) is None

    def test_missing_leaf(self):
        ctx = {"actor": {"role": "admin"}}
        assert _resolve_field("actor.unit_id", ctx) is None

    def test_non_dict_intermediate(self):
        ctx = {"actor": "not_a_dict"}
        assert _resolve_field("actor.role", ctx) is None


class TestResolveFieldAlias:
    """_resolve_field_alias: legacy flat field to canonical path, event-aware."""

    def test_global_alias(self):
        assert _resolve_field_alias("new_status") == "event.new_status_id"
        assert _resolve_field_alias("actor_id") == "actor.id"
        assert _resolve_field_alias("lead_id") == "lead.id"

    def test_canonical_path_unchanged(self):
        assert _resolve_field_alias("actor.role") == "actor.role"
        assert _resolve_field_alias("event.new_status_id") == "event.new_status_id"

    def test_unit_id_default(self):
        assert _resolve_field_alias("unit_id") == "lead.unit_id"
        assert _resolve_field_alias("unit_id", "lead_created") == "lead.unit_id"

    def test_unit_id_lead_imported(self):
        assert _resolve_field_alias("unit_id", "lead_imported") == "event.unit_id"

    def test_unknown_field_unchanged(self):
        assert _resolve_field_alias("some_random_field") == "some_random_field"


class TestOperatorAliases:
    """Legacy symbolic operators normalize to canonical."""

    def test_all_aliases(self):
        assert OPERATOR_ALIASES["=="] == "eq"
        assert OPERATOR_ALIASES["!="] == "ne"
        assert OPERATOR_ALIASES[">"] == "gt"
        assert OPERATOR_ALIASES[">="] == "gte"
        assert OPERATOR_ALIASES["<"] == "lt"
        assert OPERATOR_ALIASES["<="] == "lte"


class TestEvaluateCondition:
    """evaluate_condition with Phase 2 upgrades."""

    def test_none_condition_returns_true(self):
        assert evaluate_condition(None, {}) is True

    def test_simple_eq_canonical(self):
        ctx = {"actor": {"role": "admin"}}
        cond = {"field": "actor.role", "operator": "eq", "value": "admin"}
        assert evaluate_condition(cond, ctx) is True

    def test_simple_eq_legacy_operator(self):
        """Legacy '==' operator should be normalized to 'eq'."""
        ctx = {"actor": {"role": "admin"}}
        cond = {"field": "actor.role", "operator": "==", "value": "admin"}
        assert evaluate_condition(cond, ctx) is True

    def test_simple_ne(self):
        ctx = {"actor": {"role": "officer"}}
        cond = {"field": "actor.role", "operator": "ne", "value": "admin"}
        assert evaluate_condition(cond, ctx) is True

    def test_dotted_path_miss(self):
        ctx = {"actor": {"role": "officer"}}
        cond = {"field": "actor.role", "operator": "eq", "value": "admin"}
        assert evaluate_condition(cond, ctx) is False

    def test_flat_field_backward_compat(self):
        """Legacy rules using flat keys still work."""
        ctx = {"lead_id": 42}
        cond = {"field": "lead_id", "operator": "eq", "value": 42}
        assert evaluate_condition(cond, ctx) is True

    def test_field_alias_normalization(self):
        """Legacy flat field aliases resolve to nested paths."""
        ctx = {"event": {"new_status_id": "contacted"}}
        cond = {"field": "new_status", "operator": "eq", "value": "contacted"}
        assert evaluate_condition(cond, ctx, event="lead_status_changed") is True

    def test_unit_id_alias_lead_imported(self):
        """unit_id → event.unit_id for lead_imported."""
        ctx = {"event": {"unit_id": 10}}
        cond = {"field": "unit_id", "operator": "eq", "value": 10}
        assert evaluate_condition(cond, ctx, event="lead_imported") is True

    def test_unit_id_alias_default(self):
        """unit_id → lead.unit_id for non-imported events."""
        ctx = {"lead": {"unit_id": 10}}
        cond = {"field": "unit_id", "operator": "eq", "value": 10}
        assert evaluate_condition(cond, ctx, event="lead_created") is True

    def test_compound_and_with_normalization(self):
        ctx = {"actor": {"role": "admin"}, "event": {"new_status_id": "contacted"}}
        cond = {
            "operator": "and",
            "conditions": [
                {"field": "actor.role", "operator": "==", "value": "admin"},
                {"field": "event.new_status_id", "operator": "eq", "value": "contacted"},
            ],
        }
        assert evaluate_condition(cond, ctx) is True

    def test_compound_or(self):
        ctx = {"actor": {"role": "officer"}}
        cond = {
            "operator": "or",
            "conditions": [
                {"field": "actor.role", "operator": "eq", "value": "admin"},
                {"field": "actor.role", "operator": "eq", "value": "officer"},
            ],
        }
        assert evaluate_condition(cond, ctx) is True

    def test_contains_operator(self):
        ctx = {"lead": {"source": "facebook_ads"}}
        cond = {"field": "lead.source", "operator": "contains", "value": "facebook"}
        assert evaluate_condition(cond, ctx) is True

    def test_in_operator(self):
        ctx = {"actor": {"role": "manager"}}
        cond = {"field": "actor.role", "operator": "in", "value": ["admin", "manager"]}
        assert evaluate_condition(cond, ctx) is True

    def test_missing_field_returns_false(self):
        ctx = {}
        cond = {"field": "actor.role", "operator": "eq", "value": "admin"}
        assert evaluate_condition(cond, ctx) is False
