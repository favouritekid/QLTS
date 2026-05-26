# scripts/seeds/seed_administrative_nodes.py
"""
Seed script for administrative_nodes table with temporal versioning.

Data Source: Documents/Seeding data/data province/ward_mappings.sql

Logic:
    1. Use hardcoded 63 provinces with TCTK codes
    2. Parse ward_mappings.sql for ward data
    3. Create TWO separate trees:
       - tree_old: old_province_name -> Districts -> Wards (3-level, valid until 2025-06-30)
       - tree_new: new_province_name -> Wards (2-level, valid from 2025-07-01)
    4. Seed both trees to database

Key Dates:
    - 3-level (old): valid_from = 2008-08-01, valid_to = 2025-06-30
    - 2-level (new): valid_from = 2025-07-01, valid_to = NULL
"""

import asyncio
import sys
import os
import re
import unicodedata
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WARD_MAPPINGS_SQL_PATH = os.path.join(PROJECT_ROOT, "..", "Documents", "Seeding data", "data province", "ward_mappings.sql")

LEGACY_VALID_FROM = date(2008, 8, 1)
LEGACY_VALID_TO = date(2025, 6, 30)
NEW_VALID_FROM = date(2025, 7, 1)

# =============================================================================
# 63 PROVINCES - HARDCODED (TCTK Standard Codes)
# =============================================================================

PROVINCES = [
    {"code": "01", "name": "Hà Nội"},
    {"code": "02", "name": "Hà Giang"},
    {"code": "04", "name": "Cao Bằng"},
    {"code": "06", "name": "Bắc Kạn"},
    {"code": "08", "name": "Tuyên Quang"},
    {"code": "10", "name": "Lào Cai"},
    {"code": "11", "name": "Điện Biên"},
    {"code": "12", "name": "Lai Châu"},
    {"code": "14", "name": "Sơn La"},
    {"code": "15", "name": "Yên Bái"},
    {"code": "17", "name": "Hòa Bình"},
    {"code": "19", "name": "Thái Nguyên"},
    {"code": "20", "name": "Lạng Sơn"},
    {"code": "22", "name": "Quảng Ninh"},
    {"code": "24", "name": "Bắc Giang"},
    {"code": "25", "name": "Phú Thọ"},
    {"code": "26", "name": "Vĩnh Phúc"},
    {"code": "27", "name": "Bắc Ninh"},
    {"code": "30", "name": "Hải Dương"},
    {"code": "31", "name": "Hải Phòng"},
    {"code": "33", "name": "Hưng Yên"},
    {"code": "34", "name": "Thái Bình"},
    {"code": "35", "name": "Hà Nam"},
    {"code": "36", "name": "Nam Định"},
    {"code": "37", "name": "Ninh Bình"},
    {"code": "38", "name": "Thanh Hóa"},
    {"code": "40", "name": "Nghệ An"},
    {"code": "42", "name": "Hà Tĩnh"},
    {"code": "44", "name": "Quảng Bình"},
    {"code": "45", "name": "Quảng Trị"},
    {"code": "46", "name": "Thừa Thiên Huế"},
    {"code": "48", "name": "Đà Nẵng"},
    {"code": "49", "name": "Quảng Nam"},
    {"code": "51", "name": "Quảng Ngãi"},
    {"code": "52", "name": "Bình Định"},
    {"code": "54", "name": "Phú Yên"},
    {"code": "56", "name": "Khánh Hòa"},
    {"code": "58", "name": "Ninh Thuận"},
    {"code": "60", "name": "Bình Thuận"},
    {"code": "62", "name": "Kon Tum"},
    {"code": "64", "name": "Gia Lai"},
    {"code": "66", "name": "Đắk Lắk"},
    {"code": "67", "name": "Đắk Nông"},
    {"code": "68", "name": "Lâm Đồng"},
    {"code": "70", "name": "Bình Phước"},
    {"code": "72", "name": "Tây Ninh"},
    {"code": "74", "name": "Bình Dương"},
    {"code": "75", "name": "Đồng Nai"},
    {"code": "77", "name": "Bà Rịa - Vũng Tàu"},
    {"code": "79", "name": "Hồ Chí Minh"},
    {"code": "80", "name": "Long An"},
    {"code": "82", "name": "Tiền Giang"},
    {"code": "83", "name": "Bến Tre"},
    {"code": "84", "name": "Trà Vinh"},
    {"code": "86", "name": "Vĩnh Long"},
    {"code": "87", "name": "Đồng Tháp"},
    {"code": "89", "name": "An Giang"},
    {"code": "91", "name": "Kiên Giang"},
    {"code": "92", "name": "Cần Thơ"},
    {"code": "93", "name": "Hậu Giang"},
    {"code": "94", "name": "Sóc Trăng"},
    {"code": "95", "name": "Bạc Liêu"},
    {"code": "96", "name": "Cà Mau"},
]

# =============================================================================
# PROVINCE NAME MATCHING
# =============================================================================

def build_province_mapping() -> dict:
    """Build name -> code mapping with various formats."""
    mapping = {}
    for prov in PROVINCES:
        code, name = prov["code"], prov["name"]
        # Multiple variations
        mapping[name] = code
        mapping[name.lower()] = code
        mapping[f"Tỉnh {name}"] = code
        mapping[f"Thành phố {name}"] = code
        mapping[f"TP {name}"] = code
    
    # Special cases
    mapping["Thành phố Huế"] = "46"
    mapping["Huế"] = "46"
    mapping["Hoà Bình"] = "17"
    mapping["Tỉnh Hoà Bình"] = "17"
    
    return mapping


def get_province_code(prov_name: str, mapping: dict) -> tuple:
    """Get TCTK code. Returns (code, normalized_name) or (None, name)."""
    if not prov_name:
        return None, prov_name
    
    # Direct match
    if prov_name in mapping:
        return mapping[prov_name], prov_name
    
    # Lowercase
    if prov_name.lower() in mapping:
        return mapping[prov_name.lower()], prov_name
    
    # Strip prefix
    for prefix in ["Tỉnh ", "Thành phố ", "TP "]:
        if prov_name.startswith(prefix):
            clean = prov_name[len(prefix):]
            if clean in mapping:
                return mapping[clean], clean
    
    return None, prov_name

# =============================================================================
# SQL PARSING
# =============================================================================

def parse_ward_mappings_sql(filepath: str) -> list[dict]:
    """Parse ward_mappings.sql handling escaped quotes."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"SQL file not found: {filepath}")
    
    print(f"  📖 Reading {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    quoted = r"'((?:[^'\\]|\\.)*)'"
    pattern = (
        r"VALUES\s*\(\s*(\d+)\s*,\s*" +
        quoted + r"\s*,\s*" + quoted + r"\s*,\s*" + quoted + r"\s*,\s*" +
        quoted + r"\s*,\s*" + quoted + r"\s*,\s*" + quoted + r"\s*,\s*" + quoted
    )
    
    matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
    
    def unescape(s):
        return s.replace("\\'", "'").replace("\\\\", "\\")
    
    records = [{
        "old_ward_code": unescape(m[1]),
        "old_ward_name": unescape(m[2]),
        "old_district_name": unescape(m[3]),
        "old_province_name": unescape(m[4]),
        "new_ward_code": unescape(m[5]),
        "new_ward_name": unescape(m[6]),
        "new_province_name": unescape(m[7]),
    } for m in matches]
    
    print(f"     Parsed {len(records)} records")
    return records

# =============================================================================
# TREE BUILDING (DUAL TREE)
# =============================================================================

def build_trees(records: list[dict], mapping: dict) -> tuple:
    """
    Build two separate trees:
    - tree_old: old_province -> districts -> wards (3-level)
    - tree_new: new_province -> wards (2-level)
    """
    tree_old = {}
    tree_new = {}
    dist_counters = {}
    unmapped = set()
    
    for rec in records:
        old_prov_raw = rec["old_province_name"]
        new_prov_raw = rec["new_province_name"]
        dist_name = rec["old_district_name"]
        
        # === OLD PROVINCE (3-level) ===
        old_code, old_norm = get_province_code(old_prov_raw, mapping)
        if old_code:
            if old_norm not in tree_old:
                tree_old[old_norm] = {"code": old_code, "districts": {}}
                dist_counters[old_norm] = 0
            
            if dist_name not in tree_old[old_norm]["districts"]:
                dist_counters[old_norm] += 1
                dist_code = f"{old_code}_{dist_counters[old_norm]:03d}"
                tree_old[old_norm]["districts"][dist_name] = {"code": dist_code, "wards": []}
            
            if rec["old_ward_code"]:
                wards = tree_old[old_norm]["districts"][dist_name]["wards"]
                if not any(w["code"] == rec["old_ward_code"] for w in wards):
                    # PR-2: carry the authoritative successor (new_ward_code) so
                    # the legacy ward node resolves cross-era to its current commune.
                    wards.append({
                        "code": rec["old_ward_code"], "name": rec["old_ward_name"],
                        "successor": rec["new_ward_code"] or None,
                    })
        else:
            unmapped.add(old_prov_raw)
        
        # === NEW PROVINCE (2-level) ===
        new_code, new_norm = get_province_code(new_prov_raw, mapping)
        if new_code:
            if new_norm not in tree_new:
                tree_new[new_norm] = {"code": new_code, "wards": []}
            
            if rec["new_ward_code"]:
                wards = tree_new[new_norm]["wards"]
                if not any(w["code"] == rec["new_ward_code"] for w in wards):
                    wards.append({"code": rec["new_ward_code"], "name": rec["new_ward_name"]})
        else:
            unmapped.add(new_prov_raw)
    
    return tree_old, tree_new, unmapped

# =============================================================================
# DATABASE SEEDING
# =============================================================================

async def seed_old_provinces(db: AsyncSession, tree_old: dict) -> dict:
    """Seed provinces from tree_old (3-level structure)."""
    print("  🏙️ Seeding OLD PROVINCES (3-level)...")
    prov_map = {}
    
    for name, data in tree_old.items():
        node = AdministrativeNode(
            code=data["code"], name=name, level=AdministrativeLevel.PROVINCE,
            parent_id=None, path=data["code"],
            province_code=data["code"], district_code=None, ward_code=None,
            valid_from=LEGACY_VALID_FROM, valid_to=LEGACY_VALID_TO, is_active=True,
        )
        db.add(node)
        await db.flush()
        prov_map[name] = node.id
        data["db_id"] = node.id
    
    print(f"     Created {len(prov_map)} old provinces")
    return prov_map


async def seed_districts(db: AsyncSession, tree_old: dict, prov_map: dict) -> dict:
    """Seed districts (3-level structure)."""
    print("  🏘️ Seeding DISTRICTS...")
    dist_map = {}
    count = 0
    
    for prov_name, prov_data in tree_old.items():
        prov_id = prov_map[prov_name]
        prov_code = prov_data["code"]
        
        for dist_name, dist_data in prov_data["districts"].items():
            dist_code = dist_data["code"]
            path = f"{prov_code}/{dist_code}"
            
            node = AdministrativeNode(
                code=dist_code, name=dist_name, level=AdministrativeLevel.DISTRICT,
                parent_id=prov_id, path=path,
                province_code=prov_code, district_code=dist_code, ward_code=None,
                valid_from=LEGACY_VALID_FROM, valid_to=LEGACY_VALID_TO, is_active=True,
            )
            db.add(node)
            await db.flush()
            dist_map[(prov_name, dist_name)] = node.id
            dist_data["db_id"] = node.id
            count += 1
    
    print(f"     Created {count} districts")
    return dist_map


async def seed_wards_3level(db: AsyncSession, tree_old: dict, dist_map: dict) -> int:
    """Seed wards for 3-level structure."""
    print("  📍 Seeding WARDS (3-level, valid until 2025-06-30)...")
    count = 0
    
    for prov_name, prov_data in tree_old.items():
        prov_code = prov_data["code"]
        
        for dist_name, dist_data in prov_data["districts"].items():
            dist_id = dist_map[(prov_name, dist_name)]
            dist_code = dist_data["code"]
            
            for ward in dist_data["wards"]:
                path = f"{prov_code}/{dist_code}/{ward['code']}"
                node = AdministrativeNode(
                    code=ward["code"], name=ward["name"], level=AdministrativeLevel.WARD,
                    parent_id=dist_id, path=path,
                    province_code=prov_code, district_code=dist_code, ward_code=ward["code"],
                    valid_from=LEGACY_VALID_FROM, valid_to=LEGACY_VALID_TO, is_active=True,
                    # PR-2 cross-era lineage: legacy ward → current commune code.
                    successor_ward_code=ward.get("successor"),
                )
                db.add(node)
                count += 1
    
    await db.flush()
    print(f"     Created {count} wards")
    return count


async def seed_new_provinces(db: AsyncSession, tree_new: dict, existing_codes: set) -> dict:
    """Seed provinces from tree_new that don't exist yet."""
    print("  🏙️ Seeding NEW PROVINCES (2-level)...")
    prov_map = {}
    created = 0
    
    for name, data in tree_new.items():
        # Check if province already exists (from old tree)
        if data["code"] in existing_codes:
            # Get existing province ID - need to query for it
            stmt = text("SELECT id FROM administrative_nodes WHERE code = :code AND level = 'PROVINCE'")
            result = await db.execute(stmt.bindparams(code=data["code"]))
            row = result.first()
            if row:
                prov_map[name] = row[0]
                continue
        
        node = AdministrativeNode(
            code=data["code"], name=name, level=AdministrativeLevel.PROVINCE,
            parent_id=None, path=data["code"],
            province_code=data["code"], district_code=None, ward_code=None,
            valid_from=NEW_VALID_FROM, valid_to=None, is_active=True,
        )
        db.add(node)
        await db.flush()
        prov_map[name] = node.id
        existing_codes.add(data["code"])
        created += 1
    
    print(f"     Created {created} new provinces (+ reused existing)")
    return prov_map


async def seed_wards_2level(db: AsyncSession, tree_new: dict, prov_map: dict) -> int:
    """Seed wards for 2-level structure."""
    print("  📍 Seeding WARDS (2-level, valid from 2025-07-01)...")
    count = 0
    
    for prov_name, prov_data in tree_new.items():
        prov_id = prov_map.get(prov_name)
        if not prov_id:
            continue
        prov_code = prov_data["code"]
        
        for ward in prov_data["wards"]:
            path = f"{prov_code}/{ward['code']}"
            node = AdministrativeNode(
                code=ward["code"], name=ward["name"], level=AdministrativeLevel.WARD,
                parent_id=prov_id, path=path,
                province_code=prov_code, district_code=None, ward_code=ward["code"],
                valid_from=NEW_VALID_FROM, valid_to=None, is_active=True,
                # PR-2: current ward → itself (identity).
                successor_ward_code=ward["code"],
            )
            db.add(node)
            count += 1
    
    await db.flush()
    print(f"     Created {count} wards")
    return count


async def clear_existing_data(db: AsyncSession):
    """Clear existing data."""
    print("  🗑️ Clearing existing data...")
    await db.execute(text("TRUNCATE TABLE administrative_nodes RESTART IDENTITY CASCADE"))
    await db.flush()
    print("     Done")

# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("=" * 60)
    print("🌱 SEEDING ADMINISTRATIVE NODES (Dual Tree - Temporal)")
    print("=" * 60)
    print(f"   Source: {WARD_MAPPINGS_SQL_PATH}")
    print(f"   3-level: {LEGACY_VALID_FROM} to {LEGACY_VALID_TO}")
    print(f"   2-level: {NEW_VALID_FROM} onwards")
    print("=" * 60)
    
    mapping = build_province_mapping()
    records = parse_ward_mappings_sql(WARD_MAPPINGS_SQL_PATH)
    
    print("\n  🌳 Building trees...")
    tree_old, tree_new, unmapped = build_trees(records, mapping)
    
    if unmapped:
        print(f"\n  ⚠️ Unmapped provinces ({len(unmapped)}):")
        for p in sorted(unmapped)[:10]:
            print(f"      - {p}")
    
    old_districts = sum(len(p["districts"]) for p in tree_old.values())
    old_wards = sum(len(d["wards"]) for p in tree_old.values() for d in p["districts"].values())
    new_wards = sum(len(p["wards"]) for p in tree_new.values())
    
    print(f"\n     OLD: {len(tree_old)} provinces, {old_districts} districts, {old_wards} wards")
    print(f"     NEW: {len(tree_new)} provinces, {new_wards} wards")
    
    async with AsyncSessionLocal() as db:
        try:
            await clear_existing_data(db)
            
            # Seed OLD structure (3-level)
            old_prov_map = await seed_old_provinces(db, tree_old)
            dist_map = await seed_districts(db, tree_old, old_prov_map)
            await seed_wards_3level(db, tree_old, dist_map)
            
            # Seed NEW structure (2-level) - reuse provinces where possible
            existing_codes = {data["code"] for data in tree_old.values()}
            new_prov_map = await seed_new_provinces(db, tree_new, existing_codes)
            await seed_wards_2level(db, tree_new, new_prov_map)
            
            await db.commit()
            print("\n" + "=" * 60)
            print("✅ SEEDING COMPLETE!")
            print("=" * 60)
            
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(main())
