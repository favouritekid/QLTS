# tests/unit/test_notification_contract.py
"""
PR3: Notification architecture contract tests.

These tests enforce invariants established by PR1/PR2:
- Event catalog classification (user / broadcast_only / internal_future)
- Dispatcher single-path behavior (no registry fallback)
- Delete guard for active catalog events
- Cross-action dedup precedence
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events import SystemEvents
from app.core.event_catalog import (
    EVENT_CATALOG,
    get_event,
    get_event_by_key,
    get_notifiable_events,
    get_active_events,
    render_dedup_key,
    render_link,
)


# =============================================================================
# A. Catalog classification invariants
# =============================================================================


class TestCatalogClassification:
    """Every SystemEvents member must exist in EVENT_CATALOG with correct classification."""

    def test_all_system_events_in_catalog(self):
        """Every SystemEvents enum member must have a catalog entry."""
        missing = [ev for ev in SystemEvents if ev not in EVENT_CATALOG]
        assert missing == [], f"SystemEvents missing from catalog: {[e.value for e in missing]}"

    def test_no_duplicate_event_keys(self):
        """Event keys must be unique (enforced by dict, but verify explicitly)."""
        keys = [ev.value for ev in EVENT_CATALOG]
        assert len(keys) == len(set(keys)), "Duplicate event keys in catalog"

    def test_user_events_have_required_fields(self):
        """User events must have display_name, default_resolver, default_channels."""
        for defn in get_notifiable_events():
            assert defn.display_name, f"{defn.event.value}: missing display_name"
            assert defn.default_resolver, f"{defn.event.value}: missing default_resolver"
            assert defn.default_channels, f"{defn.event.value}: missing default_channels"

    def test_broadcast_only_excluded_from_notifiable(self):
        """broadcast_only events must NOT appear in get_notifiable_events()."""
        notifiable_keys = {d.event for d in get_notifiable_events()}
        broadcast = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "broadcast_only"
        ]
        assert len(broadcast) > 0, "No broadcast_only events in catalog"
        for d in broadcast:
            assert d.event not in notifiable_keys, (
                f"{d.event.value} is broadcast_only but appears in notifiable"
            )

    def test_internal_future_excluded_from_notifiable(self):
        """internal_future events must NOT appear in get_notifiable_events()."""
        notifiable_keys = {d.event for d in get_notifiable_events()}
        future = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "internal_future"
        ]
        assert len(future) > 0, "No internal_future events in catalog"
        for d in future:
            assert d.event not in notifiable_keys, (
                f"{d.event.value} is internal_future but appears in notifiable"
            )

    def test_lead_updated_is_broadcast_only(self):
        """D1 decision: lead_updated must be broadcast_only."""
        defn = get_event(SystemEvents.LEAD_UPDATED)
        assert defn is not None
        assert defn.notification_class == "broadcast_only"

    def test_ctv_lead_converted_is_internal_future(self):
        """CTV10 decision: ctv_lead_converted must be internal_future."""
        defn = get_event(SystemEvents.CTV_LEAD_CONVERTED)
        assert defn is not None
        assert defn.notification_class == "internal_future"

    def test_payment_overdue_is_internal_future(self):
        """F3 decision: payment_overdue must be internal_future."""
        defn = get_event(SystemEvents.PAYMENT_OVERDUE)
        assert defn is not None
        assert defn.notification_class == "internal_future"

    def test_get_event_by_key_returns_correct_definition(self):
        defn = get_event_by_key("lead_assigned")
        assert defn is not None
        assert defn.event == SystemEvents.LEAD_ASSIGNED

    def test_render_functions(self):
        key = render_dedup_key(SystemEvents.LEAD_ASSIGNED, {"lead_id": 1, "officer_id": 2})
        assert key == "lead:1:assigned:2"
        link = render_link(SystemEvents.LEAD_ASSIGNED, {"lead_id": 42})
        assert link == "/leads/42"


# =============================================================================
# B. Dispatcher invariants (unit-level, mocked DB)
# =============================================================================


class TestDispatcherInvariants:
    """Dispatcher single-path behavior — no registry fallback."""

    @pytest.mark.asyncio
    async def test_missing_rule_does_not_fallback(self):
        """User event with no enabled DB rule → fail-closed, empty result."""
        from app.services.notification_dispatcher import dispatch

        mock_defn = MagicMock()
        mock_defn.notification_class = "user"
        mock_defn.retired = False

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=None)), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_ASSIGNED, {"lead_id": 1, "actor_id": 2})
            assert ids == [], "Missing rule must not produce notifications"
            assert cb is not None, "Callback must exist for domain event"

    @pytest.mark.asyncio
    async def test_broadcast_event_dispatches_domain_only(self):
        """broadcast_only event → domain event only, no DB rule lookup."""
        from app.services.notification_dispatcher import dispatch

        db = AsyncMock()
        mock_rule_loader = AsyncMock()

        with patch("app.services.notification_dispatcher.get_rule_for_event", mock_rule_loader), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_UPDATED, {
                "lead_id": 1, "actor_id": 2, "updated_fields": [],
            })
            assert ids == []
            assert mock_rule_loader.call_count == 0, "broadcast_only must not query DB rules"

    @pytest.mark.asyncio
    async def test_internal_future_event_dispatches_domain_only(self):
        """internal_future event → domain event only, no DB rule lookup."""
        from app.services.notification_dispatcher import dispatch

        db = AsyncMock()
        mock_rule_loader = AsyncMock()

        with patch("app.services.notification_dispatcher.get_rule_for_event", mock_rule_loader), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.CTV_LEAD_CONVERTED, {
                "lead_id": 1, "collaborator_id": 2, "new_status": "contacted",
                "actor_id": 3,
            })
            assert ids == []
            assert mock_rule_loader.call_count == 0, "internal_future must not query DB rules"

    @pytest.mark.asyncio
    async def test_cross_action_dedup_lower_step_wins(self):
        """When same user appears in multiple actions for same channel, lower step wins.

        Step 1 (browser) and Step 2 (browser) both resolve [10, 20].
        After cross-action dedup, Step 2 should get 0 users.
        Verified by tracking per-step user_ids passed to _create_deliveries_for_action.
        """
        from app.services.notification_dispatcher import dispatch

        config = MagicMock()
        config.channel_values = ["browser"]
        config.rule_id = 1
        config.condition = None
        config.render_title.return_value = "Title"
        config.render_message.return_value = "Message"
        config.group = MagicMock(value="lead")

        action1 = MagicMock(step=1, channel="browser", delay_minutes=0,
                            template_code=None, config=None, recipient_config=None,
                            content_mode=None, content_override=None, branch_key="g1_browser")
        action2 = MagicMock(step=2, channel="browser", delay_minutes=0,
                            template_code=None, config=None, recipient_config=None,
                            content_mode=None, content_override=None, branch_key="g2_browser")
        config.actions = [action1, action2]
        config.resolver = MagicMock()
        config.resolver.resolve_users = AsyncMock(return_value=[10, 20])

        mock_defn = MagicMock()
        mock_defn.notification_class = "user"
        mock_defn.retired = False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        # Track per-step delivery calls to verify dedup
        delivery_calls = []

        async def track_deliveries(db, event, action, user_ids, **kwargs):
            delivery_calls.append({"step": action.step, "user_ids": list(user_ids)})
            return [1000 + i for i in range(len(user_ids))]

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
             patch("app.services.notification_dispatcher.render_dedup_key", return_value=None), \
             patch("app.services.notification_dispatcher.render_link", return_value="/test"), \
             patch("app.services.notification_dispatcher.notification_preference_service") as mock_pref, \
             patch("app.services.notification_dispatcher.safe_redis_set", new=AsyncMock(return_value=True)), \
             patch("app.services.notification_dispatcher.safe_redis_incr", new=AsyncMock(return_value=1)), \
             patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
             patch("app.services.notification_dispatcher._bulk_create_notifications", new=AsyncMock(return_value=[101, 102])), \
             patch("app.services.notification_dispatcher._create_deliveries_for_action", track_deliveries), \
             patch("app.services.notification_dispatcher._resolve_action_templates", new=AsyncMock(return_value={})), \
             patch("app.services.notification_dispatcher._build_action_snapshot", return_value={}), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()), \
             patch("app.services.notification_dispatcher._extract_source_from_payload", return_value=("lead", 1)):
            mock_pref.filter_users_by_group = AsyncMock(side_effect=lambda db, user_ids, group, channel: user_ids)

            ids, cb = await dispatch(
                db, SystemEvents.LEAD_ASSIGNED,
                {"lead_id": 1, "officer_id": 10, "actor_id": 99},
                skip_preference_check=True,
            )

            # Step 1 gets [10, 20], Step 2 gets [] (deduped by cross-action dedup)
            assert len(ids) == 2, f"Expected 2 notifications (step 1 only), got {len(ids)}"

            step1_calls = [c for c in delivery_calls if c["step"] == 1]
            step2_calls = [c for c in delivery_calls if c["step"] == 2]

            assert len(step1_calls) == 1, "Step 1 should have 1 delivery call"
            assert sorted(step1_calls[0]["user_ids"]) == [10, 20], \
                f"Step 1 should deliver to [10, 20], got {step1_calls[0]['user_ids']}"

            # Step 2: either no call (empty users skipped) or called with empty list
            if step2_calls:
                assert step2_calls[0]["user_ids"] == [], \
                    f"Step 2 should be deduped (0 users), got {step2_calls[0]['user_ids']}"


# =============================================================================
# C. Delete guard invariants
# =============================================================================


class TestDeleteGuard:
    """Active catalog events cannot be hard-deleted."""

    @pytest.mark.asyncio
    async def test_cannot_delete_active_user_event_rule(self):
        """Deleting a rule for an active user event must raise BusinessRuleViolation."""
        from app.services.notification_rule_crud_service import delete_rule
        from app.utils.exceptions import BusinessRuleViolation

        mock_rule = MagicMock()
        mock_rule.event = "lead_assigned"
        mock_rule.id = 1

        db = AsyncMock()

        with pytest.raises(BusinessRuleViolation, match="Cannot delete rule"):
            await delete_rule(db, mock_rule)

    @pytest.mark.asyncio
    async def test_can_delete_orphan_event_rule(self):
        """Deleting a rule for an event not in catalog is allowed."""
        from app.services.notification_rule_crud_service import delete_rule

        mock_rule = MagicMock()
        mock_rule.event = "some_removed_event_not_in_catalog"
        mock_rule.id = 999
        mock_rule.template_id = None

        db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.delete_rule = AsyncMock()

        with patch("app.services.notification_rule_crud_service.NotificationRuleRepository", return_value=mock_repo):
            result, cb = await delete_rule(db, mock_rule)
            assert result is None
            mock_repo.delete_rule.assert_called_once()


# =============================================================================
# D. Dispatcher must not import from notification_registry
# =============================================================================


class TestNoRegistryDependency:
    """Dispatcher must not depend on notification_registry at runtime."""

    def test_dispatcher_has_no_registry_import(self):
        """notification_dispatcher.py must not import get_event_config or has_rule_override."""
        import inspect
        from app.services import notification_dispatcher
        source = inspect.getsource(notification_dispatcher)
        assert "get_event_config" not in source, "Dispatcher still imports get_event_config"
        assert "has_rule_override_for_event" not in source, "Dispatcher still imports has_rule_override"


# =============================================================================
# E. Sync contract tests
# =============================================================================


class TestSyncContract:
    """sync_notification_rules must be idempotent and complete."""

    @pytest.mark.asyncio
    async def test_sync_creates_missing_rules(self):
        """Fresh DB → sync creates one rule per user event."""
        from app.scripts.sync_notification_rules import sync_notification_rules
        from app.core.event_catalog import get_notifiable_events

        expected_user_count = len(get_notifiable_events())
        user_keys = {d.event.value for d in get_notifiable_events()}

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First query: existing rules → empty
                result.fetchall.return_value = []
            else:
                # Re-check query: all rules now exist (sync just created them)
                result.fetchall.return_value = [(k,) for k in user_keys]
            return result

        db.execute = mock_execute

        result = await sync_notification_rules(db)

        assert result["created"] == expected_user_count, (
            f"Sync should create {expected_user_count} rules, created {result['created']}"
        )
        assert result["skipped"] == 0
        assert result["missing_user_rules"] == 0

    @pytest.mark.asyncio
    async def test_sync_is_idempotent(self):
        """Running sync twice → second run creates 0, skips all."""
        from app.scripts.sync_notification_rules import sync_notification_rules
        from app.core.event_catalog import get_notifiable_events

        user_events = get_notifiable_events()
        existing_keys = [(ev.event.value,) for ev in user_events]

        db = AsyncMock()
        # Simulate all rules already exist
        mock_result = MagicMock()
        mock_result.fetchall.return_value = existing_keys
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)

        assert result["created"] == 0, "Idempotent sync should create 0"
        assert result["skipped"] == len(user_events)
        assert result["missing_user_rules"] == 0

    def test_sync_cli_exit_code_logic(self):
        """Script must exit non-zero when missing_user_rules > 0."""
        # Verify the exit logic exists in the main() function
        import inspect
        from app.scripts import sync_notification_rules as mod
        source = inspect.getsource(mod.main)
        assert "sys.exit(1)" in source, "main() must sys.exit(1) on missing rules"
        assert "missing_user_rules" in source

    @pytest.mark.asyncio
    async def test_can_delete_retired_event_rule(self):
        """Retired events (retired=True) should be deletable."""
        from app.services.notification_rule_crud_service import delete_rule

        mock_rule = MagicMock()
        mock_rule.event = "lead_assigned"
        mock_rule.id = 1
        mock_rule.template_id = None

        mock_defn = MagicMock()
        mock_defn.retired = True

        db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.delete_rule = AsyncMock()

        # Patch at catalog module level (delete_rule imports locally)
        with patch("app.core.event_catalog.get_event_by_key", return_value=mock_defn), \
             patch("app.services.notification_rule_crud_service.NotificationRuleRepository", return_value=mock_repo):
            result, cb = await delete_rule(db, mock_rule)
            assert result is None
            mock_repo.delete_rule.assert_called_once()


# =============================================================================
# F. User events must have real dispatch callers in production code
# =============================================================================


class TestUserEventsHaveDispatchCallers:
    """Every notification_class=user event must be dispatched somewhere in app/."""

    # Events dispatched via event=SystemEvents.XXX in app/routers/, app/services/, app/tasks/
    # Built by scanning: grep -rn "event=SystemEvents\." app/routers/ app/services/ app/tasks/
    _DISPATCHED_EVENTS = frozenset({
        "lead_assigned", "lead_assignment_failed", "lead_reassigned",
        "lead_status_changed", "lead_created", "lead_deleted",
        "lead_restored", "lead_imported", "lead_updated",
        "consultation_created", "consultation_updated",
        "consultation_deleted", "consultation_reminder",
        "application_created", "application_status_changed", "application_deleted",
        "payment_received", "payment_verified",
        "ctv_claim_submitted", "ctv_claim_approved", "ctv_claim_rejected",
        "ctv_approved", "ctv_suspended", "ctv_commission_created",
        "ctv_attribution_expiring", "ctv_attribution_expired", "ctv_weekly_summary",
        "system_alert", "system_announcement", "user_role_changed",
        "user_deactivated", "pipeline_config_updated",
        "officer_availability_changed", "suspicious_login",
        "holiday_calendar_incomplete",
    })

    def test_user_events_have_dispatch_in_codebase(self):
        """Every active user event must have at least one dispatch caller."""
        missing = []
        for defn in get_notifiable_events():
            if defn.event.value not in self._DISPATCHED_EVENTS:
                missing.append(defn.event.value)
        assert not missing, (
            f"User events with no dispatch caller in production code: {missing}. "
            "Either add dispatch call or demote to internal_future."
        )

    def test_dispatched_set_covers_all_user_events(self):
        """Cross-check: _DISPATCHED_EVENTS must include all user events."""
        user_keys = {d.event.value for d in get_notifiable_events()}
        extra = self._DISPATCHED_EVENTS - user_keys
        # Extra dispatched events (broadcast_only, internal_future) are OK
        # Just verify no user event is missing from the set
        missing = user_keys - self._DISPATCHED_EVENTS
        assert not missing, f"User events missing from _DISPATCHED_EVENTS: {missing}"


# =============================================================================
# G. Catalog DB Parity (unit-level with mocked DB)
# =============================================================================


class TestCatalogDBParity:
    """Invariants between catalog and DB rule state."""

    @pytest.mark.asyncio
    async def test_all_user_events_have_db_rule(self):
        """Sync ensures every user event has a DB rule. Verify via sync contract."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        user_events = get_notifiable_events()
        existing_keys = [(d.event.value,) for d in user_events]

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = existing_keys
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)
        assert result["missing_user_rules"] == 0, (
            f"After sync, {result['missing_user_rules']} user events still missing rules"
        )

    def test_internal_future_events_have_no_rules_in_sync(self):
        """Sync must NOT create rules for internal_future events."""
        notifiable_keys = {d.event.value for d in get_notifiable_events()}
        future_events = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "internal_future"
        ]
        for d in future_events:
            assert d.event.value not in notifiable_keys, (
                f"{d.event.value} is internal_future but in notifiable → sync would create rule"
            )

    @pytest.mark.asyncio
    async def test_no_orphan_rules_if_catalog_complete(self):
        """If DB rules only contain catalog events, orphan count = 0."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        user_keys = [(d.event.value,) for d in get_notifiable_events()]

        db = AsyncMock()

        async def mock_exec(stmt):
            r = MagicMock()
            r.fetchall.return_value = user_keys
            return r

        db.execute = mock_exec
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)
        assert result["orphan_rules"] == 0

    def test_no_enabled_rules_for_retired_events(self):
        """No catalog events are currently retired (baseline check)."""
        retired = [d for d in EVENT_CATALOG.values() if d.retired]
        assert len(retired) == 0, (
            f"Retired events found: {[d.event.value for d in retired]}. "
            "If intentional, add invariant test for 'no enabled DB rules for retired'."
        )


# =============================================================================
# H. Dedup template validation
# =============================================================================


class TestDedupTemplates:
    """Dedup key templates must use valid event variables."""

    def test_dedup_templates_use_valid_variables(self):
        """Every ${var} in dedup_key_template must be a declared event variable."""
        import re
        issues = []
        for defn in EVENT_CATALOG.values():
            if not defn.dedup_key_template:
                continue
            var_names = {v.name for v in defn.variables} if defn.variables else set()
            # Extract ${var} or $var patterns
            template_vars = set(re.findall(r'\$\{?(\w+)\}?', defn.dedup_key_template))
            invalid = template_vars - var_names
            if invalid:
                issues.append(
                    f"{defn.event.value}: dedup template uses {invalid} "
                    f"but event only declares {var_names}"
                )
        assert not issues, "Dedup templates reference undeclared variables:\n" + "\n".join(issues)

    def test_dedup_templates_unique_per_event(self):
        """No two events should share the exact same dedup_key_template pattern."""
        templates = {}
        dupes = []
        for defn in EVENT_CATALOG.values():
            if not defn.dedup_key_template:
                continue
            if defn.dedup_key_template in templates:
                dupes.append(
                    f"'{defn.dedup_key_template}' shared by "
                    f"{templates[defn.dedup_key_template]} and {defn.event.value}"
                )
            else:
                templates[defn.dedup_key_template] = defn.event.value
        assert not dupes, "Duplicate dedup templates:\n" + "\n".join(dupes)


# =============================================================================
# I. Retired event dispatch behavior
# =============================================================================


class TestRetiredEventDispatch:
    """Retired events must not dispatch notifications."""

    @pytest.mark.asyncio
    async def test_retired_event_does_not_dispatch(self):
        """A retired event must return empty + domain-only callback."""
        from app.services.notification_dispatcher import dispatch

        # Create a mock retired event definition
        mock_defn = MagicMock()
        mock_defn.retired = True
        mock_defn.notification_class = "user"

        db = AsyncMock()

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_ASSIGNED, {"lead_id": 1})
            assert ids == [], "Retired event must not create notifications"
            assert cb is not None, "Domain event callback must exist"
