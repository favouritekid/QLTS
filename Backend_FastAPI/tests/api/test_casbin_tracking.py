# tests/api/test_casbin_tracking.py
# -*- coding: utf-8 -*-
"""
Tests for Casbin Template Tracking Features

Tests the following features added in Casbin Rule Fixes:
1. Tracking columns (template_id, applied_at, applied_by) are filled
2. Drift detection handles _legacy and _manual gracefully
3. Auto-seed from policy_templates.py (unit test)
"""
import logging
from datetime import datetime, timedelta

import pytest
from casbin_async_sqlalchemy_adapter import CasbinRule
from httpx import AsyncClient
from sqlalchemy import select, text
from unittest.mock import AsyncMock, MagicMock, patch

from app.database import AsyncSessionLocal
from app.services.casbin_service import CasbinPolicyService
from app.casbin_config.policy_templates import SYSTEM_ROLES, apply_template, POLICY_TEMPLATES

# Import constants
try:
    from tests.fixtures.constants import AdminURLs
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_casbin_rule_with_tracking(ptype: str, v0: str, v1: str, v2: str):
    """Get casbin rule including tracking columns using raw SQL."""
    async with AsyncSessionLocal() as session:
        # Use raw SQL to query tracking columns that aren't in CasbinRule model
        result = await session.execute(
            text("""
                SELECT id, ptype, v0, v1, v2, v3, v4, v5,
                       template_id, applied_at, applied_by
                FROM casbin_rule
                WHERE ptype = :ptype AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
                LIMIT 1
            """),
            {"ptype": ptype, "v0": v0, "v1": v1, "v2": v2}
        )
        row = result.fetchone()
        if row is None:
            return None

        # Return a simple object with tracking attributes
        class CasbinRuleWithTracking:
            def __init__(self, row):
                self.id = row[0]
                self.ptype = row[1]
                self.v0 = row[2]
                self.v1 = row[3]
                self.v2 = row[4]
                self.v3 = row[5]
                self.v4 = row[6]
                self.v5 = row[7]
                self.template_id = row[8]
                self.applied_at = row[9]
                self.applied_by = row[10]

        return CasbinRuleWithTracking(row)


async def cleanup_test_policy(v0: str, v1: str, v2: str):
    """Clean up test policy from DB."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                DELETE FROM casbin_rule 
                WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
            """),
            {"v0": v0, "v1": v1, "v2": v2}
        )
        await session.commit()


# ============================================================================
# TEST: TRACKING COLUMNS ARE FILLED
# ============================================================================

@pytest.mark.asyncio
async def test_policy_tracking_columns_filled_on_create(
    client: AsyncClient,
    admin_token_headers: dict,
    admin_user_in_db: dict,
    setup_test_database,
):
    """
    Test that when a policy is added via API, tracking columns are filled:
    - template_id = '_manual'
    - applied_at = timestamp (not null)
    - applied_by = admin user ID
    """
    log.info("--- Running: test_policy_tracking_columns_filled_on_create ---")
    
    policy_payload = {
        "subject": "role:test_tracking",
        "object": "/api/test/tracking",
        "action": "GET",
    }
    
    try:
        # Create policy via API
        # Note: Correct URL is /api/admin/roles/policies, not AdminURLs.POLICIES
        response = await client.post(
            "/api/admin/roles/policies",
            json=policy_payload,
            headers=admin_token_headers
        )
        assert response.status_code == 201, f"Failed to create policy: {response.text}"
        
        # Verify tracking columns in DB
        rule = await get_casbin_rule_with_tracking(
            "p",
            policy_payload["subject"],
            policy_payload["object"],
            policy_payload["action"]
        )
        
        assert rule is not None, "Policy not found in DB"
        
        # Check tracking columns
        assert rule.template_id == "_manual", (
            f"Expected template_id='_manual', got '{rule.template_id}'"
        )
        assert rule.applied_at is not None, "applied_at should not be None"
        assert rule.applied_by == admin_user_in_db["id"], (
            f"Expected applied_by={admin_user_in_db['id']}, got {rule.applied_by}"
        )
        
        # Verify timestamp is recent (within last minute)
        now = datetime.utcnow()
        time_diff = now - rule.applied_at
        assert time_diff < timedelta(minutes=1), (
            f"applied_at should be recent, but diff is {time_diff}"
        )
        
        log.info("✅ Tracking columns correctly filled")
        
    finally:
        # Cleanup
        await cleanup_test_policy(
            policy_payload["subject"],
            policy_payload["object"],
            policy_payload["action"]
        )


# ============================================================================
# TEST: DRIFT DETECTION WITH _LEGACY
# ============================================================================

@pytest.mark.asyncio
async def test_drift_detection_handles_legacy_gracefully():
    """
    Test that detect_template_drift() handles '_legacy' template_id:
    - Should NOT raise KeyError
    - Should return has_drift=False with info message
    """
    log.info("--- Running: test_drift_detection_handles_legacy_gracefully ---")
    
    # Mock enforcer
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = [
        ["role:legacy_test", "/api/legacy", "GET"]
    ]
    
    # Create service with mock
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        # Call with _legacy template - should NOT crash
        result = await service.detect_template_drift("role:legacy_test", "_legacy")
        
        # Verify graceful handling
        assert result["has_drift"] is False, "Legacy should report no drift"
        assert "info" in result, "Should have info message"
        assert "Legacy" in result["info"], "Info should mention legacy"
        assert result["template_id"] == "_legacy"
        assert len(result.get("error", "")) == 0, "Should not have error"
        
        log.info(f"✅ Legacy handled gracefully: {result['info']}")


@pytest.mark.asyncio
async def test_drift_detection_handles_manual_gracefully():
    """
    Test that detect_template_drift() handles '_manual' template_id:
    - Should NOT raise KeyError
    - Should return has_drift=False with info message
    """
    log.info("--- Running: test_drift_detection_handles_manual_gracefully ---")
    
    # Mock enforcer
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = [
        ["role:manual_test", "/api/manual", "GET"]
    ]
    
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        # Call with _manual template - should NOT crash
        result = await service.detect_template_drift("role:manual_test", "_manual")
        
        # Verify graceful handling
        assert result["has_drift"] is False, "Manual should report no drift"
        assert "info" in result, "Should have info message"
        assert "Manual" in result["info"], "Info should mention manual"
        assert result["template_id"] == "_manual"
        
        log.info(f"✅ Manual handled gracefully: {result['info']}")


@pytest.mark.asyncio
async def test_drift_detection_unknown_template_returns_error():
    """
    Test that detect_template_drift() returns error for unknown templates.
    """
    log.info("--- Running: test_drift_detection_unknown_template_returns_error ---")
    
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = []
    
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        # Call with unknown template
        result = await service.detect_template_drift("role:test", "unknown_template_xyz")
        
        # Verify error handling
        assert result["has_drift"] is True, "Unknown template should report drift=True"
        assert "error" in result, "Should have error message"
        assert "not found" in result["error"].lower(), "Error should mention not found"
        assert result["drift_percentage"] == 100.0
        
        log.info(f"✅ Unknown template returns error: {result['error']}")


# ============================================================================
# TEST: POLICY TEMPLATES STRUCTURE
# ============================================================================

@pytest.mark.asyncio
async def test_system_roles_have_valid_templates():
    """
    Test that all SYSTEM_ROLES have valid template_id pointing to existing templates.
    """
    log.info("--- Running: test_system_roles_have_valid_templates ---")
    
    for role_config in SYSTEM_ROLES:
        role_name = role_config["name"]
        template_id = role_config.get("template_id")
        
        assert template_id is not None, f"Role {role_name} has no template_id"
        assert template_id in POLICY_TEMPLATES, (
            f"Role {role_name} has invalid template_id '{template_id}'"
        )
        
        # Verify template can be applied
        policies = apply_template(template_id, role_name)
        assert len(policies) > 0, f"Template {template_id} has no policies"
        
        log.info(f"  ✓ {role_name}: {len(policies)} policies from template '{template_id}'")
    
    log.info(f"✅ All {len(SYSTEM_ROLES)} system roles have valid templates")


@pytest.mark.asyncio
async def test_apply_template_replaces_role_placeholder():
    """
    Test that apply_template() correctly replaces {role} placeholder.
    """
    log.info("--- Running: test_apply_template_replaces_role_placeholder ---")
    
    role_name = "role:custom_test"
    policies = apply_template("officer", role_name)
    
    for policy in policies:
        assert policy["subject"] == role_name, (
            f"Subject should be {role_name}, got {policy['subject']}"
        )
        assert "{role}" not in policy["subject"], "Placeholder should be replaced"
    
    log.info(f"✅ Template correctly applied with {len(policies)} policies")


# ============================================================================
# TEST: DRIFT DETECTION WITH REAL TEMPLATES
# ============================================================================

@pytest.mark.asyncio
async def test_drift_detection_with_matching_db():
    """
    Test drift detection when DB matches template exactly.
    """
    log.info("--- Running: test_drift_detection_with_matching_db ---")
    
    # Get officer template policies
    officer_policies = apply_template("officer", "role:officer")
    
    # Mock enforcer with matching policies
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = [
        [p["subject"], p["object"], p["action"]]
        for p in officer_policies
    ]
    
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        result = await service.detect_template_drift("role:officer", "officer")
        
        assert result["has_drift"] is False, "Should have no drift when DB matches template"
        assert result["drift_percentage"] == 0
        assert len(result["missing_in_db"]) == 0
        assert len(result["extra_in_db"]) == 0
        
        log.info("✅ No drift when DB matches template")


@pytest.mark.asyncio
async def test_drift_detection_with_extra_policy():
    """
    Test drift detection when DB has extra policy not in template.
    """
    log.info("--- Running: test_drift_detection_with_extra_policy ---")
    
    # Get officer template policies
    officer_policies = apply_template("officer", "role:officer")
    
    # Add an extra policy not in template
    db_policies = [
        [p["subject"], p["object"], p["action"]]
        for p in officer_policies
    ]
    db_policies.append(["role:officer", "/api/extra/policy", "GET"])  # Extra!
    
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = db_policies
    
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        result = await service.detect_template_drift("role:officer", "officer")
        
        assert result["has_drift"] is True, "Should detect drift"
        assert len(result["extra_in_db"]) == 1, "Should have 1 extra policy"
        assert result["extra_in_db"][0]["object"] == "/api/extra/policy"
        assert len(result["missing_in_db"]) == 0, "Should have no missing policies"
        
        log.info(f"✅ Drift detected: {result['drift_percentage']}%")


@pytest.mark.asyncio  
async def test_drift_detection_with_missing_policy():
    """
    Test drift detection when DB is missing a policy from template.
    """
    log.info("--- Running: test_drift_detection_with_missing_policy ---")
    
    # Get officer template policies
    officer_policies = apply_template("officer", "role:officer")
    
    # Remove one policy from DB
    db_policies = [
        [p["subject"], p["object"], p["action"]]
        for p in officer_policies[:-1]  # Skip last one
    ]
    
    mock_enforcer = MagicMock()
    mock_enforcer.get_policy.return_value = db_policies
    
    async with AsyncSessionLocal() as session:
        service = CasbinPolicyService(session, mock_enforcer)
        
        result = await service.detect_template_drift("role:officer", "officer")
        
        assert result["has_drift"] is True, "Should detect drift"
        assert len(result["missing_in_db"]) == 1, "Should have 1 missing policy"
        assert len(result["extra_in_db"]) == 0, "Should have no extra policies"
        
        log.info(f"✅ Missing policy detected: {result['missing_in_db'][0]}")
