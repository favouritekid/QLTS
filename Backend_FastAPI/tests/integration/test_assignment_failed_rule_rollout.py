"""The lead_assignment_failed fallback has to actually reach the database.

Editing NOTIFICATION_SEED_DEFAULTS changes nothing on an environment that is
already seeded, and on a brand new database the migration runs BEFORE the sync
script and finds no row to fix. Both paths are exercised here against real
PostgreSQL, and the assertions go through deserialize_resolver on what the DB
holds — comparing Python constants would pass even if nothing were written.
"""
import json
from copy import deepcopy

import pytest
from sqlalchemy import select, text

from app import models
from app.core.events import SystemEvents
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS
from app.services.notification_resolvers import (
    ActorExcludedResolver,
    FirstNonEmptyResolver,
    UnitManagersResolver,
)
from app.services.notification_rule_loader import deserialize_resolver

import importlib.util
from pathlib import Path

# alembic/versions is not a package, so load the revision by path. Importing the
# real module (rather than restating its constants here) is the point: if the
# migration's OLD/NEW config drifts, these tests move with it instead of passing
# against a stale copy.
_MIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "e1safety20260912_lead_assignment_failed_fallback.py"
)
_spec = importlib.util.spec_from_file_location("_e1safety_migration", _MIG_PATH)
_mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig)

pytestmark = pytest.mark.asyncio

EVENT = "lead_assignment_failed"
OLD = _mig.OLD_CONFIG
NEW = _mig.NEW_CONFIG
CUSTOM = {"resolver_type": "all_admins", "params": {}}

# Written out HERE, independently of the migration module. If the migration ever
# narrows OLD_CONFIGS, importing its constant would make these tests narrow with
# it and the regression would pass unnoticed.
LEGACY_WRAPPED = {
    "resolver_type": "actor_excluded",
    "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
}
LEGACY_BARE = {"resolver_type": "unit_managers", "params": {}}
ALL_LEGACY = [LEGACY_WRAPPED, LEGACY_BARE]


async def _run_swap(db, frm, to):
    """Async driver around the migration's OWN decision function.

    ``rows_needing_update`` is imported from the revision module, so the rule
    that decides WHICH rows change is the real one — break it and these tests go
    red. Only the SQL wiring is restated here (alembic needs a sync connection);
    that part is covered separately by running the real upgrade/downgrade/upgrade
    against a database.
    """
    rule_rows = (
        await db.execute(
            text("SELECT id, recipient_config FROM notification_rule WHERE event = :e"),
            {"e": EVENT},
        )
    ).fetchall()
    rule_ids = [r[0] for r in rule_rows]
    # Uses the migration's OWN decision function, not a copy of it.
    for rid in _mig.rows_needing_update(rule_rows, frm):
        await db.execute(
            text(
                "UPDATE notification_rule SET recipient_config = CAST(:c AS JSON) "
                "WHERE id = :i"
            ),
            {"c": json.dumps(to), "i": rid},
        )
    if not rule_ids:
        return
    action_rows = (
        await db.execute(
            text(
                "SELECT id, recipient_config FROM notification_action "
                "WHERE rule_id = ANY(:r) AND recipient_config IS NOT NULL"
            ),
            {"r": rule_ids},
        )
    ).fetchall()
    for aid in _mig.rows_needing_update(action_rows, frm):
        await db.execute(
            text(
                "UPDATE notification_action SET recipient_config = CAST(:c AS JSON) "
                "WHERE id = :i"
            ),
            {"c": json.dumps(to), "i": aid},
        )


async def _rule(db):
    return (
        await db.execute(
            select(models.NotificationRule).where(
                models.NotificationRule.event == EVENT
            )
        )
    ).scalars().first()


async def _actions(db, rule_id):
    return (
        await db.execute(
            select(models.NotificationAction).where(
                models.NotificationAction.rule_id == rule_id
            )
        )
    ).scalars().all()


def _assert_is_fallback_chain(config):
    """Load it the way the dispatcher does, not by comparing dicts."""
    resolver = deserialize_resolver(config)
    assert isinstance(resolver, FirstNonEmptyResolver), (
        f"config did not build a fallback chain: {config}"
    )
    assert len(resolver.resolvers) == 2
    assert all(isinstance(r, ActorExcludedResolver) for r in resolver.resolvers)
    assert isinstance(resolver.resolvers[0].inner_resolver, UnitManagersResolver), (
        "manager tier must come first"
    )


class TestMigrationAgainstExistingRows:
    async def test_old_rule_with_null_action_is_upgraded(self, db, seeded_dependencies):
        rule = await _rule(db)
        assert rule is not None, "sync should have created the rule"
        rule.recipient_config = deepcopy(OLD)
        for action in await _actions(db, rule.id):
            action.recipient_config = None
        await db.flush()

        await _run_swap(db, OLD, NEW)
        await db.flush()
        await db.refresh(rule)

        _assert_is_fallback_chain(rule.recipient_config)
        for action in await _actions(db, rule.id):
            assert action.recipient_config is None, (
                "NULL means 'inherit the rule' and must be left alone"
            )

    async def test_action_level_override_is_upgraded_too(
        self, db, seeded_dependencies
    ):
        """The dispatcher prefers action.recipient_config over the rule, so an
        action still carrying the old default would keep resolving to
        unit_managers no matter what the rule says."""
        rule = await _rule(db)
        rule.recipient_config = deepcopy(OLD)
        actions = await _actions(db, rule.id)
        assert actions, "rule has no actions; test would prove nothing"
        actions[0].recipient_config = deepcopy(OLD)
        await db.flush()

        await _run_swap(db, OLD, NEW)
        await db.flush()
        await db.refresh(actions[0])

        _assert_is_fallback_chain(actions[0].recipient_config)

    async def test_operator_customisation_is_not_overwritten(
        self, db, seeded_dependencies
    ):
        rule = await _rule(db)
        rule.recipient_config = deepcopy(CUSTOM)
        actions = await _actions(db, rule.id)
        actions[0].recipient_config = deepcopy(CUSTOM)
        await db.flush()

        await _run_swap(db, OLD, NEW)
        await db.flush()
        await db.refresh(rule)
        await db.refresh(actions[0])

        assert rule.recipient_config == CUSTOM, "operator rule config was clobbered"
        assert actions[0].recipient_config == CUSTOM, "operator action config was clobbered"

    async def test_running_upgrade_twice_changes_nothing_more(
        self, db, seeded_dependencies
    ):
        rule = await _rule(db)
        rule.recipient_config = deepcopy(OLD)
        await db.flush()

        await _run_swap(db, OLD, NEW)
        await db.flush()
        await db.refresh(rule)
        first = deepcopy(rule.recipient_config)

        await _run_swap(db, OLD, NEW)
        await db.flush()
        await db.refresh(rule)

        assert rule.recipient_config == first, "second run was not a no-op"

    async def test_downgrade_leaves_post_upgrade_operator_edits_alone(
        self, db, seeded_dependencies
    ):
        rule = await _rule(db)
        rule.recipient_config = deepcopy(OLD)
        await db.flush()
        await _run_swap(db, OLD, NEW)
        await db.flush()

        # Operator then customises it further.
        await db.refresh(rule)
        rule.recipient_config = deepcopy(CUSTOM)
        await db.flush()

        await _run_swap(db, NEW, OLD)  # downgrade
        await db.flush()
        await db.refresh(rule)

        assert rule.recipient_config == CUSTOM, (
            "downgrade reverted a config the operator wrote after the upgrade"
        )


class TestLegacyConfigShapes:
    """Two producers wrote this rule over time and they did not agree.

    NOTIFICATION_SEED_DEFAULTS / reset_notification_rules_dev wrote the
    actor_excluded wrapper; sync_notification_rules built a BARE resolver from
    the catalog default. An environment bootstrapped by the second is exactly
    the one a migration matching only the first would skip - reporting success
    while changing nothing.
    """

    @pytest.mark.parametrize("legacy", ALL_LEGACY, ids=["wrapped", "bare"])
    async def test_every_known_legacy_rule_shape_is_upgraded(
        self, db, seeded_dependencies, legacy
    ):
        rule = await _rule(db)
        rule.recipient_config = deepcopy(legacy)
        for action in await _actions(db, rule.id):
            action.recipient_config = None
        await db.flush()

        await _run_swap(db, ALL_LEGACY, NEW)
        await db.flush()
        await db.refresh(rule)

        _assert_is_fallback_chain(rule.recipient_config)

    @pytest.mark.parametrize("legacy", ALL_LEGACY, ids=["wrapped", "bare"])
    async def test_every_known_legacy_action_override_is_upgraded(
        self, db, seeded_dependencies, legacy
    ):
        rule = await _rule(db)
        rule.recipient_config = deepcopy(legacy)
        actions = await _actions(db, rule.id)
        assert actions, "rule has no actions; test would prove nothing"
        actions[0].recipient_config = deepcopy(legacy)
        await db.flush()

        await _run_swap(db, ALL_LEGACY, NEW)
        await db.flush()
        await db.refresh(actions[0])

        _assert_is_fallback_chain(actions[0].recipient_config)

    def test_migration_declares_every_legacy_shape_this_file_knows_about(self):
        """Drift guard, deliberately comparing in this direction.

        These constants are written independently above. If the migration drops
        one, this fails here rather than silently skipping environments.
        """
        for shape in ALL_LEGACY:
            assert shape in _mig.OLD_CONFIGS, (
                f"migration no longer upgrades a known legacy shape: {shape}"
            )


class TestBootstrapFailsClosed:
    """A broken safety config must stop startup, not downgrade it silently."""

    def test_missing_recipient_config_raises_instead_of_falling_back(
        self, monkeypatch
    ):
        from app.core.events import SystemEvents
        import app.scripts.sync_notification_rules as sync_mod

        broken = dict(sync_mod.NOTIFICATION_SEED_DEFAULTS)
        broken[SystemEvents.LEAD_ASSIGNMENT_FAILED] = {"recipient_config": None}
        monkeypatch.setattr(sync_mod, "NOTIFICATION_SEED_DEFAULTS", broken)

        with pytest.raises(RuntimeError) as exc:
            sync_mod._recipient_config_for("lead_assignment_failed", "unit_managers")
        assert "recipient_config" in str(exc.value)

    def test_structurally_invalid_config_also_fails(self, monkeypatch):
        """Truthy is not usable.

        ``first_nonempty`` with no resolver list passes every emptiness check
        and then explodes at DISPATCH time - by which point the row is already
        in the database and the only symptom is an alert that never arrives.
        """
        from app.core.events import SystemEvents
        import app.scripts.sync_notification_rules as sync_mod

        broken = dict(sync_mod.NOTIFICATION_SEED_DEFAULTS)
        broken[SystemEvents.LEAD_ASSIGNMENT_FAILED] = {
            "recipient_config": {"resolver_type": "first_nonempty", "params": {}}
        }
        monkeypatch.setattr(sync_mod, "NOTIFICATION_SEED_DEFAULTS", broken)

        with pytest.raises(RuntimeError) as exc:
            sync_mod._recipient_config_for("lead_assignment_failed", "unit_managers")
        assert "usable resolver" in str(exc.value)

    def test_unknown_resolver_name_in_seed_also_fails(self, monkeypatch):
        from app.core.events import SystemEvents
        import app.scripts.sync_notification_rules as sync_mod

        broken = dict(sync_mod.NOTIFICATION_SEED_DEFAULTS)
        broken[SystemEvents.LEAD_ASSIGNMENT_FAILED] = {
            "recipient_config": {"resolver_type": "no_such_resolver", "params": {}}
        }
        monkeypatch.setattr(sync_mod, "NOTIFICATION_SEED_DEFAULTS", broken)

        with pytest.raises(RuntimeError):
            sync_mod._recipient_config_for("lead_assignment_failed", "unit_managers")

    def test_event_without_a_seed_default_still_uses_the_catalog(self, monkeypatch):
        """Most events have no seed entry and that is legitimate - only a
        BROKEN entry is fatal."""
        import app.scripts.sync_notification_rules as sync_mod

        cfg = sync_mod._recipient_config_for("definitely_not_an_event", "all_admins")
        assert cfg == {"resolver_type": "all_admins", "params": {}}


class TestFreshBootstrap:
    async def test_sync_on_an_empty_database_produces_the_fallback_chain(
        self, db, seeded_dependencies
    ):
        """On a new database the migration runs first and finds nothing, so the
        sync script is the only thing that can get this right. It used to build
        the config from EVENT_CATALOG.default_resolver — a single resolver name,
        which cannot express a chain — and the fallback was silently lost."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        rule = await _rule(db)
        if rule is not None:
            for action in await _actions(db, rule.id):
                await db.delete(action)
            await db.delete(rule)
            await db.flush()
        assert await _rule(db) is None

        await sync_notification_rules(db)
        await db.flush()

        fresh = await _rule(db)
        assert fresh is not None, "sync did not create the rule"
        _assert_is_fallback_chain(fresh.recipient_config)

    def test_seed_default_and_migration_target_agree(self):
        """Two places describe the same config; if they drift, one environment
        silently gets a different recipient set from the other."""
        seeded = NOTIFICATION_SEED_DEFAULTS[SystemEvents.LEAD_ASSIGNMENT_FAILED][
            "recipient_config"
        ]
        assert seeded == NEW, "seed defaults and migration NEW_CONFIG diverged"
