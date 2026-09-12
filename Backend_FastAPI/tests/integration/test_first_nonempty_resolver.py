"""first_nonempty resolver — the manager -> admin fallback for failure events.

Why this file exists: ``UnitManagersResolver`` returns ``[]`` for a unit with no
manager/admin. On ``LEAD_ASSIGNMENT_FAILED`` that means the one event whose
whole job is to say "a lead was lost" reaches nobody. These tests pin the
fallback, and — just as important — pin that it is a FALLBACK and not a union.
"""
import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.core.events import SystemEvents
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS
from app.security import get_password_hash
from app.services.notification_resolvers import (
    AllAdminsResolver,
    ActorExcludedResolver,
    BaseResolver,
    FirstNonEmptyResolver,
    UnitManagersResolver,
)
from app.services.notification_rule_loader import deserialize_resolver

pytestmark = pytest.mark.asyncio


async def _make_admin(db: AsyncSession, *, suffix: str, status: str = "active") -> models.User:
    user = models.User(
        username=f"fne_admin_{suffix}",
        email=f"fne_admin_{suffix}@test.com",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        status=status,
        full_name=f"FNE Admin {suffix}",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_unit_manager(db: AsyncSession, unit_id: int, *, suffix: str) -> models.User:
    user = models.User(
        username=f"fne_mgr_{suffix}",
        email=f"fne_mgr_{suffix}@test.com",
        password_hash=get_password_hash("MgrPass123!"),
        role="manager",
        status="active",
        full_name=f"FNE Manager {suffix}",
        unit_id=unit_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    # UnitManagersResolver reads UserUnitAssignment, NOT User.unit_id — seeding
    # only the column on User would make this test pass for the wrong reason.
    db.add(
        models.UserUnitAssignment(
            user_id=user.id,
            unit_id=unit_id,
            role=UserRole.MANAGER,
            is_active=True,
        )
    )
    await db.flush()
    return user


class _Boom(BaseResolver):
    """Tier that must never be reached. Raising is the point: asserting only on
    the final id list cannot tell a real short-circuit apart from "both tiers
    ran and happened to agree"."""

    def __init__(self):
        self.called = False

    async def resolve_users(self, db, payload):
        self.called = True
        raise AssertionError("later tier was evaluated despite an earlier match")


class _Fixed(BaseResolver):
    def __init__(self, ids):
        self._ids = ids
        self.calls = 0

    async def resolve_users(self, db, payload):
        self.calls += 1
        return list(self._ids)


class TestFirstNonEmptyOrdering:
    async def test_first_tier_with_users_short_circuits(self, db: AsyncSession):
        boom = _Boom()
        resolver = FirstNonEmptyResolver([_Fixed([7, 8]), boom])
        assert await resolver.resolve_users(db, {}) == [7, 8]
        assert boom.called is False, "second tier must not be evaluated at all"

    async def test_falls_through_only_while_tiers_are_empty(self, db: AsyncSession):
        empty = _Fixed([])
        second = _Fixed([11])
        resolver = FirstNonEmptyResolver([empty, second])
        assert await resolver.resolve_users(db, {}) == [11]
        assert empty.calls == 1 and second.calls == 1

    async def test_never_unions_tiers(self, db: AsyncSession):
        """The whole reason CompositeResolver could not be reused."""
        resolver = FirstNonEmptyResolver([_Fixed([1]), _Fixed([2, 3])])
        assert await resolver.resolve_users(db, {}) == [1]

    async def test_duplicates_within_a_tier_removed_order_kept(self, db: AsyncSession):
        resolver = FirstNonEmptyResolver([_Fixed([5, 4, 5, 4, 9])])
        assert await resolver.resolve_users(db, {}) == [5, 4, 9]

    async def test_all_tiers_empty_is_visible_not_silent(self, db: AsyncSession, caplog):
        """An empty recipient list on a failure event is itself a failure and
        must not be reported as a quiet success."""
        resolver = FirstNonEmptyResolver([_Fixed([]), _Fixed([])])
        with caplog.at_level(logging.ERROR):
            assert await resolver.resolve_users(db, {"unit_id": 1, "lead_id": 2}) == []
        assert any(r.levelno >= logging.ERROR for r in caplog.records), (
            "no ERROR logged — a 'nobody can be told' condition would be invisible"
        )


class TestFirstNonEmptyAgainstRealResolvers:
    async def test_unit_with_manager_gets_manager_only(
        self, db: AsyncSession, seeded_dependencies: dict
    ):
        unit_id = seeded_dependencies["unit_id"]
        manager = await _make_unit_manager(db, unit_id, suffix="present")
        admin = await _make_admin(db, suffix="present")

        resolver = FirstNonEmptyResolver(
            [UnitManagersResolver(), AllAdminsResolver()]
        )
        result = await resolver.resolve_users(db, {"unit_id": unit_id})

        assert manager.id in result
        assert admin.id not in result, (
            "admin tier must stay untouched while the unit has a manager"
        )

    async def test_unit_without_manager_falls_back_to_active_admins(
        self, db: AsyncSession, seeded_dependencies: dict
    ):
        """This is production unit 14: 0 manager, 0 admin in the unit."""
        unit_id = seeded_dependencies["unit_id"]
        admin = await _make_admin(db, suffix="fallback")

        resolver = FirstNonEmptyResolver(
            [UnitManagersResolver(), AllAdminsResolver()]
        )
        result = await resolver.resolve_users(db, {"unit_id": unit_id})

        assert admin.id in result, "empty manager tier must fall through to admins"

    async def test_banned_admin_is_not_a_recipient(
        self, db: AsyncSession, seeded_dependencies: dict
    ):
        unit_id = seeded_dependencies["unit_id"]
        active = await _make_admin(db, suffix="live")
        banned = await _make_admin(db, suffix="banned", status="banned")

        resolver = FirstNonEmptyResolver(
            [UnitManagersResolver(), AllAdminsResolver()]
        )
        result = await resolver.resolve_users(db, {"unit_id": unit_id})

        assert active.id in result
        assert banned.id not in result

    async def test_actor_excluded_applies_per_tier_so_fallback_still_fires(
        self, db: AsyncSession, seeded_dependencies: dict
    ):
        """The nesting order matters and this is the case that proves it.

        If actor_excluded wrapped the WHOLE chain, a unit whose only manager is
        the actor would resolve to [manager] then have it stripped -> empty, and
        the admin tier would never be consulted. Wrapping each tier instead lets
        the empty-after-exclusion manager tier fall through.
        """
        unit_id = seeded_dependencies["unit_id"]
        manager = await _make_unit_manager(db, unit_id, suffix="is_actor")
        admin = await _make_admin(db, suffix="rescue")

        resolver = FirstNonEmptyResolver(
            [
                ActorExcludedResolver(UnitManagersResolver()),
                ActorExcludedResolver(AllAdminsResolver()),
            ]
        )
        result = await resolver.resolve_users(
            db, {"unit_id": unit_id, "actor_id": manager.id}
        )

        assert manager.id not in result
        assert admin.id in result, (
            "sole manager being the actor must not silence the alert"
        )


class TestSeedConfigWiring:
    def test_assignment_failed_uses_fallback_chain(self):
        cfg = NOTIFICATION_SEED_DEFAULTS[SystemEvents.LEAD_ASSIGNMENT_FAILED][
            "recipient_config"
        ]
        assert cfg["resolver_type"] == "first_nonempty"
        tiers = cfg["params"]["resolvers"]
        assert len(tiers) == 2
        inner = [t["params"]["inner_resolver"]["resolver_type"] for t in tiers]
        assert inner == ["unit_managers", "all_admins"], (
            "order is the contract: managers first, admins only as fallback"
        )
        assert all(t["resolver_type"] == "actor_excluded" for t in tiers)

    def test_lead_created_is_deliberately_unchanged(self):
        """LEAD_CREATED must NOT fan out to all admins: every new website lead
        would page every admin. Only the FAILURE event gets the fallback."""
        cfg = NOTIFICATION_SEED_DEFAULTS[SystemEvents.LEAD_CREATED][
            "recipient_config"
        ]
        assert cfg == {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {"resolver_type": "unit_managers", "params": {}}
            },
        }

    def test_config_deserializes_into_the_real_resolver(self):
        cfg = NOTIFICATION_SEED_DEFAULTS[SystemEvents.LEAD_ASSIGNMENT_FAILED][
            "recipient_config"
        ]
        resolver = deserialize_resolver(cfg)
        assert isinstance(resolver, FirstNonEmptyResolver)
        assert len(resolver.resolvers) == 2
        assert all(isinstance(r, ActorExcludedResolver) for r in resolver.resolvers)

    def test_missing_resolvers_list_is_rejected_loudly(self):
        with pytest.raises(ValueError) as exc:
            deserialize_resolver({"resolver_type": "first_nonempty", "params": {}})
        assert "resolvers" in str(exc.value)

    def test_unknown_resolver_name_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            deserialize_resolver(
                {"resolver_type": "first_nonempty_typo", "params": {}}
            )
        assert "first_nonempty_typo" in str(exc.value)
