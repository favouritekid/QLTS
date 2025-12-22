# tests/services/test_evaluate_condition.py
"""
Unit tests for notification rule condition evaluation.

Tests the evaluate_condition function with various operators and compound conditions.
"""
import pytest
from app.services.notification_rule_loader import evaluate_condition


class TestEvaluateCondition:
    """Unit tests for evaluate_condition function."""

    # =========================================================================
    # NO CONDITION
    # =========================================================================

    def test_no_condition_returns_true(self):
        """Should return True when condition is None."""
        assert evaluate_condition(None, {}) is True

    def test_empty_condition_returns_true(self):
        """Should return True when condition is empty dict."""
        assert evaluate_condition({}, {}) is True

    # =========================================================================
    # SIMPLE CONDITIONS - EQUALITY
    # =========================================================================

    def test_eq_operator_match(self):
        """Should return True when field equals expected value."""
        condition = {"field": "status", "operator": "eq", "value": "active"}
        payload = {"status": "active"}
        assert evaluate_condition(condition, payload) is True

    def test_eq_operator_no_match(self):
        """Should return False when field does not equal expected value."""
        condition = {"field": "status", "operator": "eq", "value": "active"}
        payload = {"status": "inactive"}
        assert evaluate_condition(condition, payload) is False

    def test_ne_operator_match(self):
        """Should return True when field is not equal to value."""
        condition = {"field": "status", "operator": "ne", "value": "deleted"}
        payload = {"status": "active"}
        assert evaluate_condition(condition, payload) is True

    def test_ne_operator_no_match(self):
        """Should return False when field equals the forbidden value."""
        condition = {"field": "status", "operator": "ne", "value": "deleted"}
        payload = {"status": "deleted"}
        assert evaluate_condition(condition, payload) is False

    # =========================================================================
    # SIMPLE CONDITIONS - COMPARISON
    # =========================================================================

    def test_gt_operator(self):
        """Should return True when field is greater than value."""
        condition = {"field": "amount", "operator": "gt", "value": 100}
        assert evaluate_condition(condition, {"amount": 150}) is True
        assert evaluate_condition(condition, {"amount": 100}) is False
        assert evaluate_condition(condition, {"amount": 50}) is False

    def test_gte_operator(self):
        """Should return True when field is greater than or equal to value."""
        condition = {"field": "amount", "operator": "gte", "value": 100}
        assert evaluate_condition(condition, {"amount": 150}) is True
        assert evaluate_condition(condition, {"amount": 100}) is True
        assert evaluate_condition(condition, {"amount": 50}) is False

    def test_lt_operator(self):
        """Should return True when field is less than value."""
        condition = {"field": "priority", "operator": "lt", "value": 5}
        assert evaluate_condition(condition, {"priority": 3}) is True
        assert evaluate_condition(condition, {"priority": 5}) is False
        assert evaluate_condition(condition, {"priority": 7}) is False

    def test_lte_operator(self):
        """Should return True when field is less than or equal to value."""
        condition = {"field": "priority", "operator": "lte", "value": 5}
        assert evaluate_condition(condition, {"priority": 3}) is True
        assert evaluate_condition(condition, {"priority": 5}) is True
        assert evaluate_condition(condition, {"priority": 7}) is False

    # =========================================================================
    # SIMPLE CONDITIONS - MEMBERSHIP
    # =========================================================================

    def test_in_operator(self):
        """Should return True when field value is in list."""
        condition = {"field": "source", "operator": "in", "value": ["web", "api", "mobile"]}
        assert evaluate_condition(condition, {"source": "web"}) is True
        assert evaluate_condition(condition, {"source": "api"}) is True
        assert evaluate_condition(condition, {"source": "email"}) is False

    def test_not_in_operator(self):
        """Should return True when field value is not in list."""
        condition = {"field": "status", "operator": "not_in", "value": ["deleted", "archived"]}
        assert evaluate_condition(condition, {"status": "active"}) is True
        assert evaluate_condition(condition, {"status": "deleted"}) is False

    # =========================================================================
    # SIMPLE CONDITIONS - STRING OPERATIONS
    # =========================================================================

    def test_contains_operator(self):
        """Should return True when field contains substring."""
        condition = {"field": "email", "operator": "contains", "value": "@example.com"}
        assert evaluate_condition(condition, {"email": "user@example.com"}) is True
        assert evaluate_condition(condition, {"email": "user@other.com"}) is False

    # =========================================================================
    # COMPOUND CONDITIONS - AND
    # =========================================================================

    def test_and_all_true(self):
        """Should return True when all AND conditions are met."""
        condition = {
            "operator": "and",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {"field": "amount", "operator": "gt", "value": 100}
            ]
        }
        payload = {"status": "active", "amount": 200}
        assert evaluate_condition(condition, payload) is True

    def test_and_one_false(self):
        """Should return False when any AND condition fails."""
        condition = {
            "operator": "and",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {"field": "amount", "operator": "gt", "value": 100}
            ]
        }
        payload = {"status": "active", "amount": 50}  # amount fails
        assert evaluate_condition(condition, payload) is False

    def test_and_empty_conditions(self):
        """Should return True for empty AND conditions array."""
        condition = {"operator": "and", "conditions": []}
        assert evaluate_condition(condition, {}) is True

    # =========================================================================
    # COMPOUND CONDITIONS - OR
    # =========================================================================

    def test_or_one_true(self):
        """Should return True when any OR condition is met."""
        condition = {
            "operator": "or",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "urgent"},
                {"field": "priority", "operator": "gt", "value": 8}
            ]
        }
        payload = {"status": "normal", "priority": 10}  # priority triggers
        assert evaluate_condition(condition, payload) is True

    def test_or_all_false(self):
        """Should return False when all OR conditions fail."""
        condition = {
            "operator": "or",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "urgent"},
                {"field": "priority", "operator": "gt", "value": 8}
            ]
        }
        payload = {"status": "normal", "priority": 5}
        assert evaluate_condition(condition, payload) is False

    def test_or_empty_conditions(self):
        """Should return True for empty OR conditions array."""
        condition = {"operator": "or", "conditions": []}
        assert evaluate_condition(condition, {}) is True

    # =========================================================================
    # NESTED COMPOUND CONDITIONS
    # =========================================================================

    def test_nested_compound_conditions(self):
        """Should handle deeply nested AND/OR conditions."""
        condition = {
            "operator": "and",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {
                    "operator": "or",
                    "conditions": [
                        {"field": "priority", "operator": "gt", "value": 5},
                        {"field": "source", "operator": "in", "value": ["web", "api"]}
                    ]
                }
            ]
        }
        
        # Active + high priority = True
        assert evaluate_condition(
            condition, 
            {"status": "active", "priority": 10, "source": "email"}
        ) is True
        
        # Active + web source = True
        assert evaluate_condition(
            condition, 
            {"status": "active", "priority": 1, "source": "web"}
        ) is True
        
        # Inactive = False (AND fails)
        assert evaluate_condition(
            condition, 
            {"status": "inactive", "priority": 10, "source": "web"}
        ) is False

    # =========================================================================
    # EDGE CASES
    # =========================================================================

    def test_missing_field_returns_false(self):
        """Should return False when field is missing from payload."""
        condition = {"field": "nonexistent", "operator": "eq", "value": "test"}
        assert evaluate_condition(condition, {"other": "value"}) is False

    def test_missing_operator_returns_false(self):
        """Should return False when operator is missing."""
        condition = {"field": "status", "value": "active"}  # No operator
        assert evaluate_condition(condition, {"status": "active"}) is False

    def test_unknown_operator_returns_false(self):
        """Should return False for unknown operators."""
        condition = {"field": "status", "operator": "regex", "value": ".*"}
        assert evaluate_condition(condition, {"status": "active"}) is False

    def test_missing_field_key_in_simple_condition(self):
        """Should return False when 'field' key is missing in simple condition."""
        condition = {"operator": "eq", "value": "active"}  # No field
        assert evaluate_condition(condition, {"status": "active"}) is False

    def test_type_coercion_in_comparison(self):
        """Should handle numeric comparisons correctly."""
        condition = {"field": "value", "operator": "gt", "value": 10}
        assert evaluate_condition(condition, {"value": 15}) is True
        assert evaluate_condition(condition, {"value": 10.5}) is True
        assert evaluate_condition(condition, {"value": 5}) is False

    def test_string_contains_on_non_string_field(self):
        """Should convert field to string for contains check."""
        condition = {"field": "code", "operator": "contains", "value": "123"}
        assert evaluate_condition(condition, {"code": 12345}) is True
        assert evaluate_condition(condition, {"code": 99999}) is False
