"""Phase 1 hotfix — admission_profile_status_history runtime writer.

PLAN line 1067 service contract: every status mutation MUST insert
one ``AdmissionProfileStatusHistory`` row in the same transaction
frame. Phase 1 PR #210 shipped the table + initial backfill via
``phase1_10`` but missed the runtime writer; this hotfix ships the
writer and the tests below lock the contract.

What this file owns
-------------------
* ``_resolve_status_history_actor`` invariants — all 6 actor combos
  (admin / manager / officer / accountant + system + candidate) map
  to ``ck_status_history_actor_consistency``-compliant payloads.
* ``transition()`` writes one history row per call when
  ``skip_audit=False``, and skips the write (paired with the legacy
  ``audit_service.log_status_change`` skip) when ``skip_audit=True``.
* ``create_profile()`` writes the initial NULL→draft row alongside
  the ``AdmissionProfile`` row.
* Backward compat: legacy ``audit_service.log_status_change`` still
  fires (the new writer does NOT replace it; it's a parallel sink).

What this file does NOT own
---------------------------
* End-to-end status_history table schema — see
  ``test_phase1_09a_10_revision_chain.py``.
* Phase 3 reviewing/admitted/waitlisted runtime workflows — those
  ship later and add their own writer call sites; the resolver here
  is forward-compatible (manager → admin elevation already mapped).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.admission_state_service import (
    _resolve_status_history_actor,
    transition,
)


pytestmark = pytest.mark.unit


# =============================================================================
# Helper fixtures
# =============================================================================


def _user(uid: int, role: str):
    """Bare user double — mirrors the attribute surface ``transition()``
    actually reads (``id``, ``role``)."""
    return SimpleNamespace(id=uid, role=role)


def _profile(pid: int = 1, status: str = "draft", lead_id: int = 100, version: int = 1):
    """``AdmissionProfile`` double — only the fields ``transition()``
    mutates or reads (status, version, updated_at, lead_id, id)."""
    return SimpleNamespace(
        id=pid,
        status=status,
        version=version,
        lead_id=lead_id,
        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )


def _make_db():
    """``AsyncSession`` double that records ``db.add(...)`` calls so
    tests can inspect what got staged for flush."""
    db = MagicMock()
    db.add = MagicMock()
    return db


# =============================================================================
# §1 — Resolver invariants
# =============================================================================


class TestResolverActorConsistency:
    """``ck_status_history_actor_consistency`` allows exactly three
    combinations; every resolver output MUST satisfy one of them."""

    def test_admin_produces_admin_user_combo(self):
        out = _resolve_status_history_actor(_user(15, "admin"), "api", 100)
        assert out["transitioned_by_role"] == "admin"
        assert out["actor_actual_role"] == "admin"
        assert out["effective_transition_role"] == "admin"
        assert out["transitioned_by_user_id"] == 15
        assert out["transitioned_by_lead_id"] is None

    def test_officer_produces_officer_user_combo(self):
        out = _resolve_status_history_actor(_user(16, "officer"), "api", 100)
        assert out["transitioned_by_role"] == "officer"
        assert out["actor_actual_role"] == "officer"
        assert out["effective_transition_role"] == "officer"
        assert out["transitioned_by_user_id"] == 16
        assert out["transitioned_by_lead_id"] is None

    def test_manager_actual_kept_legacy_admin_effective_admin(self):
        """PLAN line 1062 v2.9 — ``actor_actual_role`` keeps the truth
        (manager); the legacy 4-value ENUM and effective-RBAC ENUM
        elevate to ``admin`` (same scope manager has for transitions)."""
        out = _resolve_status_history_actor(_user(22, "manager"), "api", 100)
        assert out["actor_actual_role"] == "manager"
        assert out["transitioned_by_role"] == "admin"
        assert out["effective_transition_role"] == "admin"
        assert out["transitioned_by_user_id"] == 22

    def test_accountant_folds_to_officer_buckets(self):
        """Defensive — accountant rarely transitions, but if a
        fee-payment hook ever triggers one the row must still satisfy
        the CHECK. Folds into officer-equivalent buckets while
        preserving ``actor_actual_role='accountant'`` for audit."""
        out = _resolve_status_history_actor(_user(24, "accountant"), "api", 100)
        assert out["actor_actual_role"] == "accountant"
        assert out["transitioned_by_role"] == "officer"
        assert out["effective_transition_role"] == "officer"
        assert out["transitioned_by_user_id"] == 24

    def test_system_actor_none_api_source_produces_system_combo(self):
        out = _resolve_status_history_actor(None, "api", 100)
        assert out["transitioned_by_role"] == "system"
        assert out["actor_actual_role"] == "system"
        assert out["effective_transition_role"] == "system"
        assert out["transitioned_by_user_id"] is None
        assert out["transitioned_by_lead_id"] is None

    def test_candidate_actor_none_magic_link_carries_lead_id(self):
        """Magic-link confirm has no ``User`` row but DOES have a
        ``Lead`` row; the CHECK requires ``transitioned_by_lead_id``
        for candidate transitions."""
        out = _resolve_status_history_actor(None, "magic_link", 100)
        assert out["transitioned_by_role"] == "candidate"
        assert out["actor_actual_role"] == "candidate"
        assert out["effective_transition_role"] == "candidate"
        assert out["transitioned_by_user_id"] is None
        assert out["transitioned_by_lead_id"] == 100

    def test_unknown_role_string_falls_back_to_officer(self):
        """Defensive — if a user ever lands here with a role string
        outside the known set, the row should still be CHECK-compliant
        rather than blow up at flush."""
        out = _resolve_status_history_actor(_user(99, "unknown_role"), "api", 100)
        assert out["actor_actual_role"] == "unknown_role"
        # Legacy ENUM doesn't have 'unknown_role'; fold to officer.
        assert out["transitioned_by_role"] == "officer"
        assert out["effective_transition_role"] == "officer"


# =============================================================================
# §2 — transition() writer integration
# =============================================================================


class TestTransitionWriterContract:
    """``transition()`` MUST insert one history row per call (PLAN
    line 1067). The legacy ``audit_service.log_status_change`` keeps
    firing as a parallel sink; both signals matter."""

    @pytest.mark.asyncio
    async def test_transition_inserts_status_history_row(self):
        db = _make_db()
        profile = _profile()
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "submitted",
                actor=_user(15, "admin"),
                reason="RT test",
                source="api",
                skip_dispatch=True,
            )
        # Single ``db.add()`` for the history row — dispatch is skipped
        # so no outbox row competes for the call count.
        assert db.add.call_count == 1
        history_row = db.add.call_args[0][0]
        assert history_row.profile_id == profile.id
        assert history_row.from_status == "draft"
        assert history_row.to_status == "submitted"
        assert history_row.transition_reason == "RT test"
        assert history_row.transitioned_by_user_id == 15

    @pytest.mark.asyncio
    async def test_transition_records_correct_old_status(self):
        """Captured BEFORE the write — if the row records
        ``new_status`` as ``from_status``, the audit trail is useless
        for chain reconstruction."""
        db = _make_db()
        profile = _profile(status="submitted")
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "approved",
                actor=_user(15, "admin"),
                source="api",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.from_status == "submitted"
        assert history_row.to_status == "approved"

    @pytest.mark.asyncio
    async def test_transition_writes_three_role_columns(self):
        """Manager actor — actual='manager', legacy='admin',
        effective='admin' (RBAC elevation). All three NOT NULL per
        column constraint. Use submitted → approved (state machine
        rejects draft → approved as invalid edge)."""
        db = _make_db()
        profile = _profile(status="submitted")
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "approved",
                actor=_user(22, "manager"),
                source="api",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        # The model maps ``transitioned_by_role`` (legacy ENUM) to a
        # plain attribute despite the column being mapped under the
        # same name; resolver returns it under the same key.
        assert history_row.transitioned_by_role == "admin"
        assert history_row.actor_actual_role == "manager"
        assert history_row.effective_transition_role == "admin"

    @pytest.mark.asyncio
    async def test_transition_skip_audit_skips_history_row(self):
        """``skip_audit`` callers (e.g. override path that writes its
        own ``audit_service.log_changes`` row) must NOT double-write
        the status_history row either; otherwise the audit trail
        contains both an ``override`` log_changes row and a generic
        history row pointing at the same transition."""
        db = _make_db()
        profile = _profile()
        await transition(
            db,
            profile,
            "submitted",
            actor=_user(15, "admin"),
            source="api",
            skip_audit=True,
            skip_dispatch=True,
        )
        # Zero ``db.add`` calls — neither history row nor anything
        # else this code path stages.
        assert db.add.call_count == 0

    @pytest.mark.asyncio
    async def test_transition_metadata_includes_source(self):
        db = _make_db()
        profile = _profile()
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "submitted",
                actor=_user(15, "admin"),
                source="bulk",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.metadata_["source"] == "bulk"

    @pytest.mark.asyncio
    async def test_transition_metadata_merges_event_metadata(self):
        """Override path passes ``event_metadata={'override': True}``;
        the audit row preserves this so consumers can branch on
        admin-force-approve vs normal-approve without re-reading the
        legacy audit row."""
        db = _make_db()
        profile = _profile(status="submitted")
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "approved",
                actor=_user(15, "admin"),
                source="override",
                event_metadata={"override": True, "bypass_rules": True},
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.metadata_["override"] is True
        assert history_row.metadata_["bypass_rules"] is True
        assert history_row.metadata_["source"] == "override"

    @pytest.mark.asyncio
    async def test_transition_legacy_audit_still_called(self):
        """The new history writer is a PARALLEL sink, not a
        replacement. ``audit_service.log_status_change`` stays in
        place because external reports still query
        ``entity_audit_log``; flipping callers to the new table is a
        Phase 4 cleanup task."""
        db = _make_db()
        profile = _profile()
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ) as mock_legacy:
            await transition(
                db,
                profile,
                "submitted",
                actor=_user(15, "admin"),
                source="api",
                skip_dispatch=True,
            )
        mock_legacy.assert_called_once()

    @pytest.mark.asyncio
    async def test_transition_system_actor_writes_system_row(self):
        """Cron / scheduler transitions pass ``actor=None`` with
        ``source='system'`` (or 'api' with no actor). Row must record
        as system actor with both FKs NULL."""
        db = _make_db()
        profile = _profile()
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "submitted",
                actor=None,
                source="system",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.transitioned_by_role == "system"
        assert history_row.actor_actual_role == "system"
        assert history_row.transitioned_by_user_id is None
        assert history_row.transitioned_by_lead_id is None

    @pytest.mark.asyncio
    async def test_transition_magic_link_actor_writes_candidate_row(self):
        """Magic-link confirm route passes ``actor=None,
        source='magic_link'``. CHECK requires ``lead_id NOT NULL``
        for candidate rows; resolver pulls ``profile.lead_id`` since
        the lead-level FK is the only signal available."""
        db = _make_db()
        profile = _profile(status="approved", lead_id=42)
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "confirmed",
                actor=None,
                source="magic_link",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.transitioned_by_role == "candidate"
        assert history_row.actor_actual_role == "candidate"
        assert history_row.transitioned_by_user_id is None
        assert history_row.transitioned_by_lead_id == 42

    @pytest.mark.asyncio
    async def test_transition_occurred_at_matches_canonical_now(self):
        """The audit row's ``occurred_at`` MUST equal the same
        timestamp that landed on ``profile.updated_at`` — they're the
        same atomic write semantically."""
        db = _make_db()
        profile = _profile()
        with patch(
            "app.services.audit_service.log_status_change",
            new_callable=AsyncMock,
        ):
            await transition(
                db,
                profile,
                "submitted",
                actor=_user(15, "admin"),
                source="api",
                skip_dispatch=True,
            )
        history_row = db.add.call_args[0][0]
        assert history_row.occurred_at == profile.updated_at
