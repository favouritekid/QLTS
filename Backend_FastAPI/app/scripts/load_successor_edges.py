"""Load successor merger edges (legacy_code → current_code) into
``administrative_nodes.successor_ward_code``.

PR-2 cross-era lineage: the migration ``kv_add_successor_20260526`` backfills
the IDENTITY edges (wards whose code survived). This script loads the explicit
MERGED-AWAY edges (legacy code → the new commune code), per-province batch,
from a CSV produced off the province KV file.

CSV columns: ``legacy_code,current_code[,audit_old_to_new]``

Idempotent (re-running re-sets the same successor). Fail-soft per row:
* validates ``current_code`` IS a current-era ward (valid_to IS NULL) — else
  the row is rejected (would create a dangling successor).
* updates only LEGACY ward rows (valid_to IS NOT NULL) for ``legacy_code``.

Usage (inside backend container, CSV bind-mounted):

    docker compose run --rm --no-deps backend \\
        python -m app.scripts.load_successor_edges --csv /path/successor_edges.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv

from sqlalchemy import text

from app.database import AsyncSessionLocal


async def load_edges(csv_path: str) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    applied = 0
    rejected_no_current = 0
    no_legacy_row = 0
    async with AsyncSessionLocal() as s:
        for r in rows:
            legacy_code = (r.get("legacy_code") or "").strip()
            current_code = (r.get("current_code") or "").strip()
            if not legacy_code or not current_code:
                continue
            valid_current = (await s.execute(
                text(
                    "SELECT 1 FROM administrative_nodes WHERE code=:c "
                    "AND level='WARD' AND valid_to IS NULL AND is_active=true LIMIT 1"
                ),
                {"c": current_code},
            )).first()
            if not valid_current:
                rejected_no_current += 1
                continue
            res = await s.execute(
                text(
                    "UPDATE administrative_nodes SET successor_ward_code=:cc "
                    "WHERE code=:lc AND level='WARD' AND valid_to IS NOT NULL"
                ),
                {"cc": current_code, "lc": legacy_code},
            )
            if res.rowcount:
                applied += res.rowcount
            else:
                no_legacy_row += 1
        await s.commit()

    return {
        "rows": len(rows),
        "applied": applied,
        "rejected_no_current_ward": rejected_no_current,
        "no_legacy_row_matched": no_legacy_row,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Load successor merger edges")
    ap.add_argument("--csv", required=True, help="Path to successor_edges CSV")
    args = ap.parse_args()
    result = asyncio.run(load_edges(args.csv))
    print(
        "Successor edges loaded: applied=%(applied)d rejected_no_current_ward=%(rejected_no_current_ward)d "
        "no_legacy_row_matched=%(no_legacy_row_matched)d (rows=%(rows)d)" % result
    )


if __name__ == "__main__":
    main()
