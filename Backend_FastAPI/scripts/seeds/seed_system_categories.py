# scripts/seeds/seed_system_categories.py
import asyncio
import sys
import os
import csv
import re
import unicodedata

# Add parent dir to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.config import ConfigSystemCategory

# Path to the CSV file
# Calculate path relative to project root (Backend_FastAPI)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_FILE_PATH = os.path.join(PROJECT_ROOT, "..", "Documents", "Seeding data", "data system categories.csv")

# =============================================================================
# DATA DEFINITIONS (Hardcoded fallback for Provinces)
# =============================================================================

# 63 Tỉnh thành Việt Nam (Standardized Codes)
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

def slugify(value, max_length=50):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    converts spaces to underscores, and truncates to max_length.
    """
    if not value or not isinstance(value, str):
        return ""
    
    # Normalize unicode characters to their closest ASCII representation
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = value.lower().strip()
    value = re.sub(r'[^\w\s-]', '', value)
    value = re.sub(r'[-\s]+', '_', value)
    
    # Ensure uppercase code
    code = value.upper()
    
    # Truncate if necessary to fit DB column
    if len(code) > max_length:
        code = code[:max_length]
        
    return code

def read_csv_data(filepath):
    """
    Reads the CSV file and extracts unique lists for each category.
    Handles potential BOM and formatting issues.
    """
    categories = {
        "ethnicity": set(),
        "nationality": set(),
        "religion": set(),
        "disability_type": set(),
        # "family_type" removed as requested
    }
    
    if not os.path.exists(filepath):
        print(f"⚠️ CSV file not found at {filepath}. Skipping CSV seed.")
        return {}

    print(f"  📖 Reading data from {filepath}...")
    try:
        # Use utf-8-sig to handle BOM if present
        with open(filepath, mode='r', encoding='utf-8-sig') as csvfile:
            # Using semi-colon delimiter
            reader = csv.DictReader(csvfile, delimiter=';')
            
            row_count = 0
            for row in reader:
                row_count += 1
                
                # Helper to safely clean values
                def clean(val):
                    if not val:
                        return None
                    # Clean newlines and extra spaces
                    return val.replace('\n', ' ').strip()

                # ETHNICITIES
                val = clean(row.get("ETHNICITIES"))
                if val: categories["ethnicity"].add(val)
                
                # NATIONALITIES
                val = clean(row.get("NATIONALITIES"))
                if val: categories["nationality"].add(val)

                # RELIGIONS
                val = clean(row.get("RELIGIONS"))
                if val: categories["religion"].add(val)

                # DISABILITY_TYPES
                val = clean(row.get("DISABILITY_TYPES"))
                if val: categories["disability_type"].add(val)
                
            print(f"     Processed {row_count} rows.")

    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return {}
    
    # Convert sets to list of dicts with code/name, ensuring unique codes
    result = {}
    
    for key, names in categories.items():
        result[key] = []
        seen_codes = set()
        
        # Sort names specifically to ensure consistency
        sorted_names = sorted(list(names))
        
        for name in sorted_names:
            if not name: continue
            
            # Truncate Name to 255 (DB limit)
            if len(name) > 255:
                print(f"⚠️ Warning: Truncating name '{name}' to 255 chars")
                name = name[:255]

            code = slugify(name)
            
            # Special case for "Khác" (Other)
            if "KHAC" in code or name.lower() == "khác":
                code = "OTHER"
            
            # Handle empty code from weird chars
            if not code:
                print(f"⚠️ Warning: Skipping item with empty code derived from '{name}'")
                continue
                
            # Handle Code Collision
            if code in seen_codes:
                # Append a suffix to make it unique
                original_code = code
                counter = 1
                while code in seen_codes:
                    suffix = f"_{counter}"
                    # Truncate base to make room for suffix if needed
                    base_len = 50 - len(suffix)
                    code = f"{original_code[:base_len]}{suffix}"
                    counter += 1
                print(f"⚠️ Warning: Resolved code collision for '{name}' -> '{code}'")
            
            seen_codes.add(code)
            result[key].append({"code": code, "name": name})
            
    return result

async def seed_categories(db: AsyncSession, category_type: str, items: list) -> int:
    """Seed a specific category type."""
    if not items:
        # print(f"  ℹ️ No items to seed for {category_type}")
        return 0
        
    print(f"  🌱 Seeding {category_type} ({len(items)} items)...")
    
    count = 0
    updated_count = 0
    
    for idx, item in enumerate(items):
        try:
            # Check existing by (type, code) unique constraint
            stmt = select(ConfigSystemCategory).where(
                ConfigSystemCategory.type == category_type,
                ConfigSystemCategory.code == item["code"]
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update name if needed
                if existing.name != item["name"]:
                    existing.name = item["name"]
                    updated_count += 1
            else:
                # Create new
                new_cat = ConfigSystemCategory(
                    type=category_type,
                    code=item["code"],
                    name=item["name"],
                    display_order=idx + 1,
                    is_active=True
                )
                db.add(new_cat)
                count += 1
                
        except Exception as e:
            print(f"❌ Error processing {item['code']}: {e}")
            raise e
            
    await db.flush()
    if updated_count > 0:
        print(f"     - Created: {count}, Updated: {updated_count}")
        return count + updated_count
    return count

async def main():
    print("=" * 60)
    print("🌱 SEEDING SYSTEM CATEGORIES")
    print("=" * 60)
    
    # Read from CSV
    csv_data = read_csv_data(CSV_FILE_PATH)
    
    if not csv_data and not PROVINCES:
        print("❌ No data found to seed.")
        return

    async with AsyncSessionLocal() as db:
        try:
            total_updates = 0
            
            # Seed from CSV keys
            # Explicit order for clarity
            keys_to_seed = ["ethnicity", "nationality", "religion", "disability_type"]
            
            for key in keys_to_seed:
                if key in csv_data:
                    items = csv_data[key]
                    
                    # Special handling: Prepend "Không" (NONE) for religion and disability_type
                    if key == "religion":
                        # Add "Không" as first option if not already present (check by name)
                        if not any(item["name"].lower() == "không" for item in items):
                            items = [{"code": "NONE", "name": "Không"}] + items
                    elif key == "disability_type":
                        # Add "Không" as first option if not already present (check by name)
                        if not any(item["name"].lower() == "không" for item in items):
                            items = [{"code": "NONE", "name": "Không"}] + items
                    
                    total_updates += await seed_categories(db, key, items)
            
            # Seed Province (Hardcoded)
            total_updates += await seed_categories(db, "province", PROVINCES)
            
            await db.commit()
            print("\n✅ Seeding complete!")
            print(f"   Total operations (inserts/updates): {total_updates}")
            
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error during seeding transaction: {e}")
            raise e

if __name__ == "__main__":
    asyncio.run(main())
