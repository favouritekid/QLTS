"""Phase B.1.b — Smart dedup + temporal split cho 3 tỉnh PoC THPT data.

Audit (Phase B.1.b Task #1) phát hiện 3 patterns dup pair:

* Pattern A (Gia Lai 038, Lâm Đồng 042): tên trường có suffix
  "(trước DD/MM/YYYY)" / "(từ DD/MM/YYYY)" — DATE tường minh
* Pattern B (Đắk Lắk 040): tên trường KHÔNG có suffix, dup theo
  (name, address gần giống) — boundary sáp nhập tỉnh 1/7/2025
* Pattern C: cluster 3+ entries cùng address (Lâm Đồng "53 Đào Duy Từ"
  12 trường) — FILTER OUT, defer manual review

Temporal split rule (per cluster of EXACTLY 2):

* Case A (both have DATE suffix):
    - "(trước YYYY)"  → effective_to_year   = YYYY - 1
    - "(từ YYYY)"      → effective_from_year = YYYY
* Case B (neither has suffix — Đắk Lắk):
    - Mã thấp  → effective_to_year   = 2024 (cutoff sáp nhập 1/7/2025)
    - Mã cao   → effective_from_year = 2025
* Case C (asymmetric — 1 có 1 không): SKIP, manual review needed

Pre-2025 entries get effective_from_year=2000 (sentinel covering all
realistic candidates born 1990s+).

Idempotent: re-run safe (detects already-split assignments via
effective_to_year IS NOT NULL on Mã thấp entries).

Run:
    docker compose exec backend python -m app.scripts.dedup_temporal_split --dry-run
    docker compose exec backend python -m app.scripts.dedup_temporal_split --apply
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.vn_school import VnSchool, VnSchoolKvAssignment


# Sentinel year covering all realistic candidates (born 1990s+, TN THPT 2008+).
PRE_BOUNDARY_FROM_YEAR = 2000

# Đắk Lắk sáp nhập tỉnh 1/7/2025 boundary
DAK_LAK_MERGER_CUTOFF_YEAR = 2024  # effective_to_year cho Mã thấp
DAK_LAK_MERGER_FROM_YEAR = 2025    # effective_from_year cho Mã cao

# Đắk Lắk pattern threshold: Mã code gap suggests post-merger code reissue.
# Audit Phase B.1.b confirmed all 24 Đắk Lắk dup pairs: low code < 90,
# high code >= 90 (vd 002+090, 062+100, 022+094).
DAK_LAK_LOW_CODE_MAX = 89
DAK_LAK_HIGH_CODE_MIN = 90

# Parse "(trước DD/MM/YYYY)" hoặc "(từ DD/MM/YYYY)"
DATE_SUFFIX_RE = re.compile(r"\((trước|từ)\s+(\d{1,2})/(\d{1,2})/(\d{4})\)")


def strip_date_suffix(name: str) -> str:
    """Remove '(trước DD/MM/YYYY)' / '(từ DD/MM/YYYY)' for clustering."""
    return DATE_SUFFIX_RE.sub("", name).strip()


def parse_date_suffix(name: str) -> Optional[Tuple[str, int]]:
    """Return (kind: 'trước'|'từ', year: int) or None."""
    m = DATE_SUFFIX_RE.search(name)
    if m:
        return (m.group(1), int(m.group(4)))
    return None


def normalize_address(addr: Optional[str]) -> str:
    """Normalize for fuzzy clustering: lowercase + collapse whitespace.
    Conservative — không strip cấp hành chính prefix để tránh false-merge."""
    if not addr:
        return ""
    return " ".join(addr.lower().split())


async def detect_clusters(db: AsyncSession) -> List[List[VnSchool]]:
    """Find clusters of schools cùng (province, base_name lowercase).

    Address NOT used (Đắk Lắk pairs có address khác do post-merger update
    cấp hành chính — vd "Tp. Buôn Ma Thuột" → "phường Tự An").
    Audit Phase B.1.b confirmed all dup pairs cùng (province, base_name)
    là same physical school regardless of address drift.

    False-merge risk mitigated by Mã code gap check trong determine_split:
    Đắk Lắk pattern requires Mã thấp < 90 + Mã cao >= 90 boundary, Gia
    Lai/Lâm Đồng case A requires explicit DATE suffix matching.

    Only THPT level (TT 05/2021 rule chỉ apply cấp 3).
    """
    q = await db.execute(
        select(VnSchool)
        .where(VnSchool.is_active.is_(True), VnSchool.level == "THPT")
        .order_by(VnSchool.moet_province_code, VnSchool.moet_school_code)
    )
    schools = list(q.scalars().all())

    clusters: dict[Tuple[str, str], List[VnSchool]] = defaultdict(list)
    for s in schools:
        base = strip_date_suffix(s.name).lower().strip()
        clusters[(s.moet_province_code, base)].append(s)

    return [c for c in clusters.values() if len(c) >= 2]


async def get_active_kv(
    db: AsyncSession, school_id: int
) -> Optional[VnSchoolKvAssignment]:
    """Fetch the moet_2025 KV assignment for this school (the one
    created by Phase B.1.a import). Returns None if missing."""
    q = await db.execute(
        select(VnSchoolKvAssignment)
        .where(
            VnSchoolKvAssignment.school_id == school_id,
            VnSchoolKvAssignment.source == "moet_2025",
        )
        .limit(1)
    )
    return q.scalar_one_or_none()


def determine_split(cluster: List[VnSchool]) -> Optional[dict]:
    """Decide temporal split for cluster of EXACTLY 2 entries.

    Returns: {
        'case': 'A' | 'B',
        'before': VnSchool,       # entry pre-boundary
        'after':  VnSchool,       # entry post-boundary
        'before_eff_from': int,   # effective_from_year cho before
        'before_eff_to': int,     # effective_to_year cho before (inclusive)
        'after_eff_from': int,    # effective_from_year cho after
        'after_eff_to': None,     # NULL = ongoing
    }
    or None if cluster cannot be split deterministically.
    """
    if len(cluster) != 2:
        return None

    s1, s2 = sorted(cluster, key=lambda s: s.moet_school_code)
    p1 = parse_date_suffix(s1.name)
    p2 = parse_date_suffix(s2.name)

    if p1 is not None and p2 is not None:
        # Case A: both have DATE suffix
        # Identify "trước" vs "từ"
        if p1[0] == "trước" and p2[0] == "từ":
            before, after = s1, s2
            year_before, year_after = p1[1], p2[1]
        elif p1[0] == "từ" and p2[0] == "trước":
            before, after = s2, s1
            year_before, year_after = p2[1], p1[1]
        else:
            # Both "trước" or both "từ" — ambiguous
            return None
        return {
            "case": "A",
            "before": before,
            "after": after,
            "before_eff_from": PRE_BOUNDARY_FROM_YEAR,
            "before_eff_to": year_before - 1,
            "after_eff_from": year_after,
            "after_eff_to": None,
        }

    if p1 is None and p2 is None:
        # Case B: Đắk Lắk no-suffix dup — verify Mã code gap pattern.
        # Audit confirmed: legitimate dup pairs have Mã thấp <= 89 + Mã cao >= 90
        # (boundary from MOET post-2025 reissue convention).
        try:
            code1 = int(s1.moet_school_code)
            code2 = int(s2.moet_school_code)
        except ValueError:
            # Non-numeric (vd "800", "K01") — defer manual
            return None

        if code1 <= DAK_LAK_LOW_CODE_MAX and code2 >= DAK_LAK_HIGH_CODE_MIN:
            return {
                "case": "B",
                "before": s1,
                "after": s2,
                "before_eff_from": PRE_BOUNDARY_FROM_YEAR,
                "before_eff_to": DAK_LAK_MERGER_CUTOFF_YEAR,
                "after_eff_from": DAK_LAK_MERGER_FROM_YEAR,
                "after_eff_to": None,
            }
        # Pair doesn't fit Đắk Lắk pattern — defer manual review
        return None

    # Case C: asymmetric (1 có suffix, 1 không) → manual review
    return None


async def apply_split(
    db: AsyncSession,
    split: dict,
    stats: Counter,
    dry_run: bool,
) -> None:
    """Update vn_school_kv_assignment rows theo temporal split decision.

    Idempotency: skip if before-entry already has effective_to_year set
    (means this cluster đã processed previous run).
    """
    before = split["before"]
    after = split["after"]
    case = split["case"]

    before_kv = await get_active_kv(db, before.id)
    after_kv = await get_active_kv(db, after.id)

    if before_kv is None or after_kv is None:
        stats[f"case_{case}_missing_kv"] += 1
        return

    # Idempotency: if before-entry already split, skip
    if (
        before_kv.effective_to_year is not None
        and before_kv.effective_from_year == split["before_eff_from"]
        and before_kv.effective_to_year == split["before_eff_to"]
    ):
        stats[f"case_{case}_already_split"] += 1
        return

    if dry_run:
        stats[f"case_{case}_would_split"] += 1
        print(
            f"  [DRY] case={case} "
            f"BEFORE: id={before.id} code={before.moet_school_code} "
            f"name={before.name[:50]!r} kv={before_kv.kv_code} "
            f"→ {split['before_eff_from']}-{split['before_eff_to']}"
        )
        print(
            f"  [DRY] case={case} "
            f"AFTER:  id={after.id} code={after.moet_school_code} "
            f"name={after.name[:50]!r} kv={after_kv.kv_code} "
            f"→ {split['after_eff_from']}-{split['after_eff_to'] or 'now'}"
        )
        return

    # Apply mutation
    before_kv.effective_from_year = split["before_eff_from"]
    before_kv.effective_to_year = split["before_eff_to"]
    if before_kv.notes:
        before_kv.notes = (
            f"{before_kv.notes} | dedup_temporal_split case={case} "
            f"(was effective_from=2025)"
        )
    else:
        before_kv.notes = f"dedup_temporal_split case={case}"

    after_kv.effective_from_year = split["after_eff_from"]
    after_kv.effective_to_year = split["after_eff_to"]
    if after_kv.notes:
        after_kv.notes = (
            f"{after_kv.notes} | dedup_temporal_split case={case}"
        )
    else:
        after_kv.notes = f"dedup_temporal_split case={case}"

    stats[f"case_{case}_split"] += 1


async def main_async(dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"=== Phase B.1.b — Smart dedup + temporal split ({mode}) ===\n")

    async with AsyncSessionLocal() as db:
        clusters = await detect_clusters(db)
        print(f"Found {len(clusters)} clusters (>=2 entries cùng province+base_name+addr)\n")

        stats: Counter = Counter()

        # Bucket by size
        by_size: dict[int, int] = defaultdict(int)
        for c in clusters:
            by_size[len(c)] += 1
        print("Cluster size distribution:")
        for size in sorted(by_size):
            print(f"  size={size}: {by_size[size]} clusters")
        print()

        # Process clusters of exactly 2
        for cluster in clusters:
            if len(cluster) != 2:
                stats[f"cluster_size_{len(cluster)}_skipped"] += 1
                continue

            split = determine_split(cluster)
            if split is None:
                stats["cluster_asymmetric_skipped"] += 1
                print(
                    f"  [SKIP asymmetric] {cluster[0].moet_province_code} "
                    f"{cluster[0].moet_school_code}+{cluster[1].moet_school_code} "
                    f"name={strip_date_suffix(cluster[0].name)[:50]!r}"
                )
                continue

            await apply_split(db, split, stats, dry_run)

        if not dry_run:
            await db.commit()
            print("\n=== COMMIT done ===")
        else:
            await db.rollback()
            print("\n=== DRY-RUN — no DB changes ===")

        print("\nStats:")
        for k, v in sorted(stats.items()):
            print(f"  {k:<35} {v}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview only")
    group.add_argument("--apply", action="store_true", help="Commit changes")
    args = parser.parse_args(argv)
    asyncio.run(main_async(dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
