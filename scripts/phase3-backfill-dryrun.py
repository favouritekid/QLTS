#!/usr/bin/env python3
"""
Phase 3 backfill dry-run scaffolding.

Plan ref: noble-launching-cocoa.md v0.3 + Phần 3.3 backfill spec
Memory: phase3-plan-locked

Usage:
    docker compose exec backend python scripts/phase3-backfill-dryrun.py \
        --dry-run \
        --chunk-size 1000 \
        --output /tmp/backfill_dryrun_report.json

Output: JSON report với:
- profiles_eligible_count: số profile có selected_subject_group_id NOT NULL
- exception_count_by_type: dict keyed by actual exception_type strings từ DB
  (verified Phase 1 #12: AMBIGUOUS_SELECTED_GROUP — KHÔNG phải AMBIGUOUS_SUBJECT_GROUP_SELECTION như v0.1 viết sai)
- choice_inserts_projected: số rows admission_profile_choice sẽ insert
- score_inserts_projected: số rows profile_choice_score sẽ insert
- estimated_runtime_seconds: based on chunk size + IO latency

Run trên dev DB clone từ prod backup (memory `solo-cutover-simple-data-import`).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# This script is a SKELETON — Day 1 prep 2026-05-12.
# Finalize Day 28 pre-Wave-B deploy với actual SQL backfill queries.
#
# PR-3A (Day 2-3 2026-05-13/14) ship full backfill migration SQL trong
# phase3_01 migration body. This script reuses queries từ PR-3A migration
# với dry-run flag (BEGIN; ... ROLLBACK;).


async def count_eligible_profiles(session) -> int:
    """COUNT profile với selected_subject_group_id IS NOT NULL — eligible cho backfill."""
    # Skeleton: PR-3A will provide real query
    # SELECT COUNT(*) FROM admission_profile
    # WHERE selected_subject_group_id IS NOT NULL
    #   AND uses_choice_engine = false  -- legacy profiles only
    raise NotImplementedError("PR-3A migration body sẽ provide query")


async def count_exceptions_by_type(session) -> dict[str, int]:
    """Project exception counts grouped by actual DB exception_type strings.

    Known exception_types (verified from Phase 1 migrations):
    - AMBIGUOUS_SELECTED_GROUP (phase1_12 line 212)
    - Phase 1 M-1-09a có thể seed thêm: INVALID_GPA_VALUE, MISSING_GPA_OVERALL,
      INVALID_GRADUATION_YEAR, MISSING_GRADUATION_YEAR

    Phase 3 backfill ship thêm exception_type khác nếu phát sinh logic mới —
    return dict runtime KHÔNG hardcode enum.
    """
    raise NotImplementedError("PR-3A migration body sẽ provide queries")


async def project_choice_inserts(session) -> int:
    """Estimate số rows admission_profile_choice sẽ insert sau backfill."""
    raise NotImplementedError("PR-3A migration body sẽ provide query")


async def project_score_inserts(session) -> int:
    """Estimate số rows profile_choice_score (1 per subject per choice)."""
    raise NotImplementedError("PR-3A migration body sẽ provide query")


async def estimate_runtime(eligible_count: int, chunk_size: int) -> float:
    """Estimate runtime based on chunked execution + IO latency."""
    chunks = (eligible_count + chunk_size - 1) // chunk_size
    # Assume ~2s per chunk (1000 rows) — adjust after PR-3A dev DB test
    seconds_per_chunk = 2.0
    return chunks * seconds_per_chunk


async def main(args: argparse.Namespace) -> int:
    # Open async session (skeleton — use app/db.py session factory)
    # from app.db import async_session_factory
    # async with async_session_factory() as session:
    #     ...
    print("Phase 3 backfill dry-run scaffold — SKELETON Day 1 prep")
    print("Finalize Day 28 với queries từ PR-3A migration body")
    print("")
    print(f"Args: chunk_size={args.chunk_size}, dry_run={args.dry_run}")
    print(f"Output: {args.output}")

    report = {
        "run_at": datetime.utcnow().isoformat() + "Z",
        "dry_run": args.dry_run,
        "chunk_size": args.chunk_size,
        "status": "SKELETON — not yet executable",
        "profiles_eligible_count": None,
        "exception_count_by_type": {
            "AMBIGUOUS_SUBJECT_GROUP_SELECTION": None,
            "INSUFFICIENT_DATA_FOR_BACKFILL": None,
        },
        "choice_inserts_projected": None,
        "score_inserts_projected": None,
        "estimated_runtime_seconds": None,
    }

    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Skeleton report written to {args.output}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 3 backfill dry-run")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Run in dry-run mode (BEGIN; ... ROLLBACK;)")
    parser.add_argument("--chunk-size", type=int, default=1000,
                        help="Rows per chunk (default 1000)")
    parser.add_argument("--output", type=str, default="/tmp/backfill_dryrun_report.json",
                        help="Output JSON report path")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
