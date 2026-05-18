"""Phase B.1.a — Import 3 tỉnh Tây Nguyên THPT từ MOET 21/4/2025 vào DB.

Scope (per user 2026-05-18): focus 3 tỉnh chính trước (sẽ scale 60 còn lại sau):
  - Lâm Đồng (cũ, MOET mã 49)
  - Đắk Lắk (cũ, MOET mã 51)
  - Gia Lai (cũ, MOET mã 35)

Source: `Documents/reports/qd861_raw/master_thpt_21042025.xls` Sheet1 header=5

Strategy first-pass (Option 1 — naive, schema-compliant):
- 1 vn_school row per Excel row (no dedup for "trường trùng" — kept as-is)
- Composite key (moet_province_code zfill(3), moet_school_code) unique cho active
- Mã 800/900/801-804 → level='OTHER' (special pseudo entries)
- Real schools → level='THPT'
- DTNT column has value → is_dtnt=true
- 1 vn_school_kv_assignment per school: effective_from_year=2025, source='moet_2025'

Idempotent: upsert by (moet_province_code, moet_school_code) — re-run safe.

Run:
    docker compose exec backend python -m app.scripts.import_moet_schools_3_provinces \\
        --excel /tmp/master_thpt.xls

Defer to Phase B.1.b: smart dedup pairs (vd "THPT Lý Tự Trọng" Mã 052 + 107
cùng địa chỉ) thành 1 vn_school + 2 vn_school_kv_assignment với temporal years.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.vn_school import VnSchool, VnSchoolKvAssignment


TARGET_PROVINCES = ["Lâm Đồng", "Đắk Lắk", "Gia Lai"]
EFFECTIVE_YEAR = 2025
SOURCE = "moet_2025"
SPECIAL_SCHOOL_CODES = {"800", "801", "802", "803", "804", "900"}


def normalize_kv(s: str) -> str:
    """Map Excel 'Khu Vực' values to canonical KV1/KV2-NT/KV2/KV3."""
    if not s:
        return ""
    s = str(s).strip().upper().replace(" ", "")
    s = s.replace("-NT", "-NT")  # placeholder
    # Variants: KV1, KV-1, KV 1
    s = re.sub(r"KV[-\s]*", "KV", s)
    # Match KV1 / KV2 / KV3 / KV2NT
    m = re.match(r"^(KV[1-3])(NT)?$", s)
    if m:
        return f"{m.group(1)}-NT" if m.group(2) else m.group(1)
    return s


def is_special_school(ma_truong: str) -> bool:
    return str(ma_truong).strip() in SPECIAL_SCHOOL_CODES


def build_rows(df: pd.DataFrame) -> List[Dict]:
    """Filter target provinces + build dict rows."""
    sub = df[df["ten_tinh"].isin(TARGET_PROVINCES)].copy()
    rows = []
    for _, r in sub.iterrows():
        ma_t = str(r["ma_tinh"]).strip()
        ma_q = str(r["ma_huyen"]).strip() if pd.notna(r["ma_huyen"]) else None
        ma_tr = str(r["ma_truong"]).strip()
        kv = normalize_kv(r["khu_vuc"])

        rows.append({
            "moet_province_code": ma_t.zfill(3),
            "moet_district_code": ma_q.zfill(5) if ma_q else None,
            "moet_school_code": ma_tr,
            "name": str(r["ten_truong"]).strip(),
            "address": str(r["dia_chi"]).strip() if pd.notna(r["dia_chi"]) else None,
            "province": str(r["ten_tinh"]).strip(),
            "district": str(r["ten_huyen"]).strip() if pd.notna(r["ten_huyen"]) else None,
            "level": "OTHER" if is_special_school(ma_tr) else "THPT",
            "is_dtnt": pd.notna(r["dtnt"]) and str(r["dtnt"]).strip() != "",
            "kv_code": kv,
            "is_special": is_special_school(ma_tr),
        })
    return rows


async def upsert_one(
    db: AsyncSession, row: Dict, stats: Counter
) -> Tuple[int, bool]:
    """Upsert vn_school + ensure vn_school_kv_assignment exists.

    Returns: (school_id, inserted_new_school)
    """
    # Lookup existing by composite key (active)
    existing_q = await db.execute(
        select(VnSchool)
        .where(
            VnSchool.moet_province_code == row["moet_province_code"],
            VnSchool.moet_school_code == row["moet_school_code"],
            VnSchool.is_active.is_(True),
        )
        .limit(1)
    )
    school = existing_q.scalar_one_or_none()

    if school is None:
        school = VnSchool(
            moet_school_code=row["moet_school_code"],
            moet_province_code=row["moet_province_code"],
            moet_district_code=row["moet_district_code"],
            name=row["name"],
            address=row["address"],
            province=row["province"],
            district=row["district"],
            level=row["level"],
            is_dtnt=row["is_dtnt"],
            is_active=True,
        )
        db.add(school)
        await db.flush()
        stats["school_inserted"] += 1
        is_new = True
    else:
        # Update existing fields if drift
        changed = False
        for field in ("name", "address", "province", "district", "level", "is_dtnt", "moet_district_code"):
            if getattr(school, field) != row[field]:
                setattr(school, field, row[field])
                changed = True
        if changed:
            stats["school_updated"] += 1
        else:
            stats["school_skipped"] += 1
        is_new = False

    # KV assignment — check if (school_id, effective_from_year) overlaps
    kv_existing_q = await db.execute(
        select(VnSchoolKvAssignment)
        .where(
            VnSchoolKvAssignment.school_id == school.id,
            VnSchoolKvAssignment.effective_from_year == EFFECTIVE_YEAR,
        )
        .limit(1)
    )
    kv_existing = kv_existing_q.scalar_one_or_none()

    if kv_existing is None:
        db.add(VnSchoolKvAssignment(
            school_id=school.id,
            kv_code=row["kv_code"],
            effective_from_year=EFFECTIVE_YEAR,
            effective_to_year=None,
            source=SOURCE,
            notes=f"is_special={row['is_special']}",
        ))
        stats["kv_inserted"] += 1
    else:
        if kv_existing.kv_code != row["kv_code"]:
            kv_existing.kv_code = row["kv_code"]
            stats["kv_updated"] += 1
        else:
            stats["kv_skipped"] += 1

    return school.id, is_new


async def main_async(excel_path: Path):
    print(f"=== Phase B.1.a — Import 3 tỉnh THPT từ {excel_path} ===\n")

    df = pd.read_excel(excel_path, sheet_name="Sheet1", header=5)
    df.columns = ["stt", "ma_tinh", "ten_tinh", "ma_huyen", "ten_huyen",
                  "ma_truong", "ten_truong", "dia_chi", "khu_vuc", "dtnt"]
    rows = build_rows(df)
    print(f"Filtered {len(rows)} rows từ 3 tỉnh: {TARGET_PROVINCES}")

    by_province = Counter(r["province"] for r in rows)
    print(f"Per-province row count: {dict(by_province)}")

    by_kv = Counter(r["kv_code"] for r in rows)
    print(f"KV distribution: {dict(by_kv)}")

    special_count = sum(1 for r in rows if r["is_special"])
    dtnt_count = sum(1 for r in rows if r["is_dtnt"])
    print(f"Special pseudo (mã 800/801-804/900): {special_count}")
    print(f"DTNT flagged: {dtnt_count}\n")

    stats: Counter = Counter()
    async with AsyncSessionLocal() as db:
        for i, row in enumerate(rows):
            try:
                await upsert_one(db, row, stats)
            except Exception as e:
                stats["error"] += 1
                print(f"  ERROR row {i} ({row['name']}): {e}")
        await db.commit()

    print(f"\n=== Import done ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:<25} {v}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--excel",
        type=Path,
        default=Path("/tmp/master_thpt.xls"),
        help="Path to master MOET THPT Excel",
    )
    args = parser.parse_args(argv)
    asyncio.run(main_async(args.excel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
