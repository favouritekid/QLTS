"""CI-only post-seed backfill for fixture rows missing from the xlsx template.

The shared ``seed_data_template.xlsx`` ships an empty
``12_CauHinhTrinhDo`` sheet, so ``seed_from_xlsx`` inserts 0
``config_degree_level`` rows in CI. Without those rows, every
``MajorProgram`` ends up with ``degree_level_id = NULL`` and
admission submit fails with::

    400 BUSINESS_RULE_VIOLATION
    CONFIG_GAP_TARGET_LEVEL: MajorProgram chưa gán degree_level_id

Production is unaffected — it carries its own populated fixtures and
uses a different xlsx workbook. This script idempotently inserts the
three canonical degree-level rows and backfills the FK on
``major_program`` so the E2E nightly suites can submit profiles.

Run **after** ``seed_from_xlsx`` in the nightly-regression workflow.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import AsyncSessionLocal


# (code, name_vi, display_order) — order matches priority_service.py
# fail-closed target_level matcher (``cao_dang``, ``trung_cap``, ``so_cap``).
_DEGREE_LEVELS = [
    ("cao_dang", "Cao đẳng", 1),
    ("trung_cap", "Trung cấp", 2),
    ("so_cap", "Sơ cấp", 3),
]


async def backfill() -> int:
    inserted = 0
    updated = 0
    async with AsyncSessionLocal() as db:
        for code, name, order in _DEGREE_LEVELS:
            result = await db.execute(
                text(
                    "INSERT INTO config_degree_level "
                    "(code, name, display_order, is_active) "
                    "VALUES (:code, :name, :order, true) "
                    "ON CONFLICT (code) DO NOTHING RETURNING id"
                ),
                {"code": code, "name": name, "order": order},
            )
            if result.fetchone() is not None:
                inserted += 1

        # Backfill MajorProgram.degree_level_id where NULL. Default to
        # ``cao_dang`` because the E2E xlsx fixture's MajorProgram rows are
        # all CĐ-shaped (offering codes start with ``6...``). Manager UI
        # can re-assign per row in production.
        cao_dang_id = (
            await db.execute(
                text(
                    "SELECT id FROM config_degree_level WHERE code = 'cao_dang' LIMIT 1"
                )
            )
        ).scalar()
        if cao_dang_id is None:
            print("ERROR: cao_dang row missing after insert — aborting backfill")
            return 2

        result = await db.execute(
            text(
                "UPDATE major_program SET degree_level_id = :id "
                "WHERE degree_level_id IS NULL RETURNING id"
            ),
            {"id": cao_dang_id},
        )
        updated = len(result.fetchall())

        await db.commit()

    print(
        f"ci_post_seed_backfill: inserted={inserted} config_degree_level rows, "
        f"updated={updated} major_program rows with degree_level_id={cao_dang_id}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(backfill()))
