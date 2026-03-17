#!/usr/bin/env python3
"""
Fix 2-level administrative nodes using GSO JSON as source of truth.

Source: ThangLeQuoc/vietnamese-provinces-database (QĐ 19/2025/QĐ-TTg)
File:   /tmp/vn_units_gso.json (downloaded from GitHub)

What this script does:
1. DELETE all existing 2-level wards (district_code IS NULL)
2. For each of the 34 GSO provinces:
   a. If province code exists (from old tree) → UPDATE name if renamed
   b. If province code is new → INSERT new province record
3. INSERT 3,321 wards from GSO with correct province_code

What this script does NOT touch:
- Old 3-level tree (districts + 3-level wards) — these are correct
- Old province records with valid_to=2025-06-30 — kept for historical lookup

Usage:
    # Ensure GSO JSON is in container
    docker compose cp /tmp/vn_units_gso.json backend:/tmp/vn_units_gso.json

    # Run fix
    docker compose exec backend python -m scripts.seeds.fix_2level_from_gso

    # Or dry-run
    docker compose exec backend python -m scripts.seeds.fix_2level_from_gso --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel

# =============================================================================
# CONFIG
# =============================================================================

GSO_JSON_PATH = "/tmp/vn_units_gso.json"
NEW_VALID_FROM = date(2025, 7, 1)


def load_gso_data(path: str) -> list[dict]:
    """Load and validate GSO JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_wards = sum(len(p.get("Wards", [])) for p in data)
    print(f"  GSO: {len(data)} provinces, {total_wards} wards")

    if len(data) != 34:
        print(f"  ⚠️  Expected 34 provinces, got {len(data)}")
    if total_wards < 3300:
        print(f"  ⚠️  Expected ~3321 wards, got {total_wards}")

    return data


async def run_fix(db: AsyncSession, gso_data: list[dict], dry_run: bool):
    """Main fix logic."""

    # -----------------------------------------------------------------
    # STEP 1: Snapshot current state
    # -----------------------------------------------------------------
    result = await db.execute(text(
        "SELECT COUNT(*) FROM administrative_nodes "
        "WHERE level = 'WARD' AND district_code IS NULL"
    ))
    old_2level_count = result.scalar()

    result = await db.execute(text(
        "SELECT code, name, id FROM administrative_nodes WHERE level = 'PROVINCE'"
    ))
    existing_provinces = {r[0]: {"name": r[1], "id": r[2]} for r in result.fetchall()}

    print(f"\n  Current state:")
    print(f"    Provinces in DB:    {len(existing_provinces)}")
    print(f"    2-level wards in DB: {old_2level_count}")

    # -----------------------------------------------------------------
    # STEP 2: Delete existing 2-level wards
    # -----------------------------------------------------------------
    print(f"\n  Step 1: Delete existing 2-level wards...")
    if not dry_run:
        result = await db.execute(text(
            "DELETE FROM administrative_nodes "
            "WHERE level = 'WARD' AND district_code IS NULL"
        ))
        print(f"    Deleted {result.rowcount} wards")
    else:
        print(f"    [DRY RUN] Would delete {old_2level_count} wards")

    # -----------------------------------------------------------------
    # STEP 3: Ensure all 34 GSO provinces exist with correct names
    # -----------------------------------------------------------------
    print(f"\n  Step 2: Sync provinces...")
    province_id_map = {}  # code → db id
    created_provinces = 0
    renamed_provinces = 0

    for gso_prov in gso_data:
        code = gso_prov["Code"]
        gso_name = gso_prov["FullName"]

        if code in existing_provinces:
            db_prov = existing_provinces[code]
            province_id_map[code] = db_prov["id"]

            # Check if name needs update (province was renamed in merger)
            if db_prov["name"] != gso_name:
                renamed_provinces += 1
                print(f"    RENAME: {code} '{db_prov['name']}' → '{gso_name}'")
                if not dry_run:
                    # Create new province record for the new era
                    # Keep old record intact for 3-level backward compat
                    node = AdministrativeNode(
                        code=code, name=gso_name,
                        level=AdministrativeLevel.PROVINCE,
                        parent_id=None, path=code,
                        province_code=code, district_code=None, ward_code=None,
                        valid_from=NEW_VALID_FROM, valid_to=None, is_active=True,
                    )
                    db.add(node)
                    await db.flush()
                    province_id_map[code] = node.id
        else:
            # New province code (shouldn't happen with current 34 GSO codes
            # since they all reuse old codes, but handle gracefully)
            created_provinces += 1
            print(f"    CREATE: {code} '{gso_name}'")
            if not dry_run:
                node = AdministrativeNode(
                    code=code, name=gso_name,
                    level=AdministrativeLevel.PROVINCE,
                    parent_id=None, path=code,
                    province_code=code, district_code=None, ward_code=None,
                    valid_from=NEW_VALID_FROM, valid_to=None, is_active=True,
                )
                db.add(node)
                await db.flush()
                province_id_map[code] = node.id

    print(f"    Renamed: {renamed_provinces}, Created: {created_provinces}")

    # -----------------------------------------------------------------
    # STEP 4: Insert 2-level wards from GSO
    # -----------------------------------------------------------------
    print(f"\n  Step 3: Insert 2-level wards from GSO...")
    total_wards = 0

    for gso_prov in gso_data:
        prov_code = gso_prov["Code"]
        prov_id = province_id_map.get(prov_code)

        if not prov_id:
            print(f"    ⚠️  No province ID for {prov_code}, skipping {len(gso_prov.get('Wards', []))} wards")
            continue

        for ward in gso_prov.get("Wards", []):
            ward_code = ward["Code"]
            ward_name = ward["FullName"]
            path = f"{prov_code}/{ward_code}"

            if not dry_run:
                node = AdministrativeNode(
                    code=ward_code, name=ward_name,
                    level=AdministrativeLevel.WARD,
                    parent_id=prov_id, path=path,
                    province_code=prov_code, district_code=None,
                    ward_code=ward_code,
                    valid_from=NEW_VALID_FROM, valid_to=None, is_active=True,
                )
                db.add(node)

            total_wards += 1

    if not dry_run:
        await db.flush()
    print(f"    Inserted {total_wards} wards")

    # -----------------------------------------------------------------
    # STEP 5: Verify
    # -----------------------------------------------------------------
    if not dry_run:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM administrative_nodes "
            "WHERE level = 'WARD' AND district_code IS NULL"
        ))
        new_count = result.scalar()

        result = await db.execute(text(
            "SELECT COUNT(DISTINCT province_code) FROM administrative_nodes "
            "WHERE level = 'WARD' AND district_code IS NULL"
        ))
        prov_count = result.scalar()

        print(f"\n  Verification:")
        print(f"    2-level wards: {new_count} (expected {total_wards})")
        print(f"    Across provinces: {prov_count} (expected {len(gso_data)})")

        if new_count != total_wards:
            print(f"    ⚠️  Ward count mismatch!")
        if prov_count != len(gso_data):
            print(f"    ⚠️  Province count mismatch!")

    return total_wards


async def main():
    parser = argparse.ArgumentParser(description="Fix 2-level admin nodes from GSO")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--json-path", default=GSO_JSON_PATH, help="Path to GSO JSON")
    args = parser.parse_args()

    print("=" * 60)
    print("🔧 FIX 2-LEVEL ADMINISTRATIVE NODES (GSO Source)")
    print("=" * 60)
    print(f"   Source: {args.json_path}")
    print(f"   Mode:   {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    gso_data = load_gso_data(args.json_path)

    async with AsyncSessionLocal() as db:
        try:
            total = await run_fix(db, gso_data, args.dry_run)

            if not args.dry_run:
                await db.commit()
                print(f"\n{'=' * 60}")
                print(f"✅ DONE — {total} wards inserted from GSO")
                print(f"{'=' * 60}")
            else:
                await db.rollback()
                print(f"\n{'=' * 60}")
                print(f"🔍 DRY RUN complete — no changes made")
                print(f"{'=' * 60}")

        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(main())
