# scripts/get_db_info.py
"""
Script to get database info for seeding configuration.
Run with: python scripts/get_db_info.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
import psycopg2

# Get database URL from settings
DATABASE_URL = settings.DATABASE_URL

print(f"📌 DATABASE_URL from settings: {DATABASE_URL[:50]}...")

# Parse DATABASE_URL (format: postgresql+asyncpg://user:pass@host:port/db)
# Remove async prefix for psycopg2
url = DATABASE_URL.replace("postgresql+asyncpg://", "").replace("postgresql://", "")

# Parse user:pass@host:port/db
auth_host, db = url.rsplit("/", 1)
auth, host_port = auth_host.rsplit("@", 1)
user, password = auth.split(":", 1)
if ":" in host_port:
    host, port = host_port.split(":", 1)
else:
    host = host_port
    port = "5432"

print(f"🔌 Connecting to database: {host}:{port}/{db}")

try:
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=db,
        user=user,
        password=password
    )
    cursor = conn.cursor()
    
    print("\n" + "="*60)
    print("📊 DATABASE INFO FOR SEEDING")
    print("="*60)
    
    # 1. Pipeline Stages
    print("\n🔹 PIPELINE STAGES:")
    cursor.execute('SELECT id, name, "order" FROM pipeline_stage ORDER BY "order"')
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row}")
    
    # 2. Organization Units
    print("\n🔹 ORGANIZATION UNITS:")
    cursor.execute("SELECT id, name, type FROM organization_unit WHERE is_active = true")
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row}")
    
    # 3. Program Offerings
    print("\n🔹 PROGRAM OFFERINGS:")
    cursor.execute("""
        SELECT po.id, mp.name as program_name, po.offering_type 
        FROM program_offering po
        LEFT JOIN major_program mp ON po.program_id = mp.id
        WHERE po.is_active = true
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row}")
    
    # 4. Officers
    print("\n🔹 OFFICERS (role=officer/manager):")
    cursor.execute("""
        SELECT id, full_name, email, role 
        FROM "user" 
        WHERE role IN ('officer', 'manager')
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row}")
    
    # 5. Consultation Statuses
    print("\n🔹 CONSULTATION STATUSES:")
    cursor.execute("""
        SELECT id, name, stage_id, outcome_type, is_universal 
        FROM consultation_status 
        ORDER BY stage_id, id
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row}")
    
    # 6. Existing Sources
    print("\n🔹 EXISTING SOURCES IN USE:")
    cursor.execute("SELECT DISTINCT source FROM lead")
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(f"   {row}")
    else:
        print("   (no leads yet)")
    
    print("\n" + "="*60)
    print("✅ Done! Copy the output above and send it back.")
    print("="*60)
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
