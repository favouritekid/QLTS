"""PR-2 anchors: cross-era successor resolution + identity backfill.

* resolve_current_ward_code: legacy merged code → current code (and a profile
  therefore never persists the legacy code); current/survived → self; unmapped
  legacy / unknown / empty → None (fail-closed).
* identity backfill predicate (the migration's deterministic UPDATE): a ward
  whose code is still a current-era ward gets successor=self; a merged-away
  code (no current equivalent) stays NULL.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.models.administrative_node import AdministrativeLevel, AdministrativeNode
from app.repositories.administrative_repository import AdministrativeRepository

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as s:
        try:
            yield s
        finally:
            await s.rollback()
            await s.close()


def _ward(code, *, current, successor, dist=None):
    return AdministrativeNode(
        code=code, name=f"Ward {code}", level=AdministrativeLevel.WARD,
        path=f"99/{code}", province_code="99", district_code=dist, ward_code=code,
        valid_from=date(2025, 7, 1) if current else date(2010, 1, 1),
        valid_to=None if current else date(2025, 7, 1),
        is_active=True, successor_ward_code=successor,
    )


async def test_resolve_current_ward_code(db) -> None:
    db.add(_ward("CUR1", current=True, successor="CUR1"))                  # current identity
    db.add(_ward("LEGSAME", current=False, successor="LEGSAME"))           # legacy survived
    db.add(_ward("LEGMERG", current=False, successor="CUR1", dist="99_1")) # legacy merged → CUR1
    db.add(_ward("LEGNULL", current=False, successor=None, dist="99_1"))   # legacy unmapped
    await db.flush()
    repo = AdministrativeRepository(db)

    assert await repo.resolve_current_ward_code("CUR1") == "CUR1"      # current → self
    assert await repo.resolve_current_ward_code("LEGSAME") == "LEGSAME"  # survived → self
    # merged-away legacy → CURRENT code (caller stores this, never the legacy code)
    assert await repo.resolve_current_ward_code("LEGMERG") == "CUR1"
    assert await repo.resolve_current_ward_code("LEGNULL") is None     # unmapped → fail-closed
    assert await repo.resolve_current_ward_code("NOPE") is None        # unknown
    assert await repo.resolve_current_ward_code("") is None            # empty
    assert await repo.resolve_current_ward_code(None) is None          # None


async def test_identity_backfill_predicate(db) -> None:
    """Migration's identity UPDATE: code still current → successor=self;
    merged-away code (no current equivalent) → stays NULL."""
    db.add(_ward("C", current=True, successor=None))                 # current C
    db.add(_ward("C", current=False, successor=None, dist="99_1"))   # legacy same code (survived)
    db.add(_ward("M", current=False, successor=None, dist="99_1"))   # merged away (no current M)
    await db.flush()

    await db.execute(text(
        """
        UPDATE administrative_nodes a SET successor_ward_code = a.code
        WHERE a.level='WARD' AND EXISTS (
            SELECT 1 FROM administrative_nodes c
            WHERE c.level='WARD' AND c.valid_to IS NULL AND c.is_active=true AND c.code=a.code)
        """
    ))

    rows = (await db.execute(text(
        "SELECT code, (valid_to IS NULL) AS cur, successor_ward_code "
        "FROM administrative_nodes WHERE code IN ('C','M')"
    ))).all()
    by = {(r[0], r[1]): r[2] for r in rows}
    assert by[("C", True)] == "C"    # current C → self
    assert by[("C", False)] == "C"   # legacy survived → C
    assert by[("M", False)] is None  # merged away → still NULL (needs merger CSV)


async def test_get_current_ward_name(db) -> None:
    """PR-3 resolve endpoint helper: name of a CURRENT-era ward by code;
    legacy/unknown → None."""
    db.add(_ward("CURX", current=True, successor="CURX"))
    db.add(_ward("LEGX", current=False, successor="CURX", dist="99_1"))
    await db.flush()
    repo = AdministrativeRepository(db)
    assert await repo.get_current_ward_name("CURX") == "Ward CURX"
    assert await repo.get_current_ward_name("LEGX") is None  # legacy, not current
    assert await repo.get_current_ward_name("NOPE") is None
    assert await repo.get_current_ward_name("") is None
