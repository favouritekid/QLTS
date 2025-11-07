# 🚨 DATABASE RECOVERY GUIDE - Hướng dẫn Khôi phục Database

## ⚠️ QUAN TRỌNG: Đọc kỹ trước khi thực hiện

Tài liệu này hướng dẫn khôi phục **CẤU TRÚC DATABASE** (tables, indexes, constraints) sau khi bị xóa nhầm bởi tests.

**LƯU Ý:** Migrations chỉ khôi phục được **STRUCTURE**, KHÔNG khôi phục được **DATA**!

---

## 📊 Tóm tắt Database Schema hiện tại

Dự án QLTS có 3 migrations (theo thứ tự):

### 1. **ec2713f8825b** - Initial migration (2025-10-26)
Tạo tất cả các bảng chính:

**Core Tables:**
- `organization_unit` - Đơn vị tổ chức (phòng ban)
- `user` - Người dùng (admins, officers)
- `pipeline_stage` - Giai đoạn trong pipeline tuyển sinh
- `consultation_status` - Trạng thái tư vấn

**Lead Management:**
- `lead` - Thông tin lead (học viên tiềm năng)
- `major` - Ngành học
- `consultation` - Buổi tư vấn
- `crm_interaction` - Tương tác CRM

**Configuration:**
- `lead_scoring_config` - Cấu hình tính điểm lead
- `officer_assignment_config` - Cấu hình phân công officer
- `skill_requirement_rule` - Quy tắc kỹ năng yêu cầu

**Tracking:**
- `assignment_log` - Lịch sử phân công
- `lead_status_history` - Lịch sử thay đổi trạng thái lead
- `application` - Hồ sơ ứng tuyển

### 2. **a1b2c3d4e5f6** - Add user_session table (2025-11-03)
Thêm bảng tracking sessions:
- `user_session` - Sessions của users (cho security audit)
  - Tracking: IP, device, browser, location
  - Security: suspicious flag, revoked status
  - Performance: multiple indexes

### 3. **bf0ce03e4900** - Optimize indexes (2025-11-05)
Tối ưu indexes cho user_session:
- Thay thế full indexes bằng partial indexes
- Tăng performance queries
- Giảm database size

---

## 🔧 PHƯƠNG PHÁP 1: Khôi phục bằng Alembic (KHUYẾN NGHỊ)

### Bước 1: Kiểm tra trạng thái hiện tại

```bash
cd /mnt/d/QLTS/Backend_FastAPI

# Kiểm tra Alembic version hiện tại
alembic current

# Xem lịch sử migrations
alembic history
```

### Bước 2: Upgrade database lên version mới nhất

```bash
# Chạy tất cả migrations từ đầu đến cuối
alembic upgrade head

# Output mong muốn:
# INFO  [alembic.runtime.migration] Running upgrade  -> ec2713f8825b, Initial migration
# INFO  [alembic.runtime.migration] Running upgrade ec2713f8825b -> a1b2c3d4e5f6, add user_session
# INFO  [alembic.runtime.migration] Running upgrade a1b2c3d4e5f6 -> bf0ce03e4900, optimize indexes
```

### Bước 3: Verify database structure

```bash
# PostgreSQL
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "\dt"

# Hoặc trong Python
python << EOF
from app.database import engine
from app.models.base import Base
import asyncio

async def check_tables():
    async with engine.begin() as conn:
        result = await conn.run_sync(
            lambda sync_conn: sync_conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        )
        tables = result.fetchall()
        print(f"Tables found: {len(tables)}")
        for table in tables:
            print(f"  - {table[0]}")

asyncio.run(check_tables())
EOF
```

**Kết quả mong muốn:** 17 tables
```
organization_unit
pipeline_stage
consultation_status
skill_requirement_rule
lead_scoring_config
major
officer_assignment_config
user
user_session           ← từ migration 2
lead
consultation
crm_interaction
lead_status_history
assignment_log
application
alembic_version        ← Alembic tracking table
```

---

## 🔧 PHƯƠNG PHÁP 2: Khôi phục thủ công bằng SQL

Nếu Alembic không hoạt động hoặc database bị corrupt hoàn toàn:

### Bước 1: Tạo script SQL từ models

```bash
cd /mnt/d/QLTS/Backend_FastAPI
python << EOF
from sqlalchemy.schema import CreateTable
from app.database import engine
from app.models.base import Base
import app.models  # Import all models

async def generate_sql():
    async with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            create_stmt = CreateTable(table).compile(conn.sync_connection)
            print(f"-- Table: {table.name}")
            print(str(create_stmt) + ";")
            print()

import asyncio
asyncio.run(generate_sql())
EOF
```

Copy output vào file `recreate_schema.sql` và chạy:

```bash
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev < recreate_schema.sql
```

### Bước 2: Tạo Alembic version entry

```bash
# Sau khi tạo tables thủ công, đánh dấu Alembic đã upgrade
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev << EOF
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DELETE FROM alembic_version;
INSERT INTO alembic_version VALUES ('bf0ce03e4900');  -- Latest migration
EOF
```

---

## 🔧 PHƯƠNG PHÁP 3: Recreate toàn bộ database

Nếu database bị hỏng hoàn toàn:

### Bước 1: Drop và Recreate database

```bash
# ⚠️  CẢNH BÁO: Lệnh này sẽ XÓA TOÀN BỘ database!
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -c "DROP DATABASE IF EXISTS qlts_dev;"
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -c "CREATE DATABASE qlts_dev WITH OWNER = postgres ENCODING = 'UTF8';"
```

### Bước 2: Chạy Alembic migrations

```bash
cd /mnt/d/QLTS/Backend_FastAPI
alembic upgrade head
```

---

## 📦 KHÔI PHỤC DATA (Nếu có Backup)

### Nếu có PostgreSQL backup file:

```bash
# Restore từ dump file
PGPASSWORD=admin pg_restore -h 192.168.88.125 -U postgres -d qlts_dev backup_file.dump

# Hoặc từ SQL file
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev < backup_file.sql
```

### Nếu có CSV/Excel data:

Sử dụng script import (xem section "Import Data from CSV" bên dưới).

---

## 🛡️ KHUYẾN NGHỊ BACKUP (Để tránh mất data trong tương lai)

### 1. Automatic Daily Backups

Tạo script backup tự động:

```bash
#!/bin/bash
# save as: backup_database.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/mnt/d/QLTS/Backups"
DB_NAME="qlts_dev"
DB_HOST="192.168.88.125"
DB_USER="postgres"
export PGPASSWORD="admin"

mkdir -p "$BACKUP_DIR"

# Backup với compression
pg_dump -h $DB_HOST -U $DB_USER -Fc $DB_NAME > "$BACKUP_DIR/${DB_NAME}_${DATE}.dump"

# Giữ chỉ 7 backups gần nhất
find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" -mtime +7 -delete

echo "Backup completed: ${DB_NAME}_${DATE}.dump"
```

Chạy tự động mỗi ngày:
```bash
chmod +x backup_database.sh

# Add to crontab (chạy mỗi ngày 2AM)
crontab -e
# Thêm dòng:
0 2 * * * /mnt/d/QLTS/backup_database.sh >> /mnt/d/QLTS/backup.log 2>&1
```

### 2. Pre-test Backup Hook

Tạo hook tự động backup trước khi chạy tests:

```python
# tests/conftest.py - Thêm vào đầu file

import subprocess
import datetime

def pytest_sessionstart(session):
    """Backup database before running tests."""
    if os.getenv("APP_ENV") != "test":
        return

    print("\n🔄 Creating backup before tests...")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"/mnt/d/QLTS/Backups/pre_test_{timestamp}.dump"

    # Backup production database
    cmd = [
        "pg_dump",
        "-h", "192.168.88.125",
        "-U", "postgres",
        "-Fc",
        "qlts_dev",
        "-f", backup_file
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = "admin"

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True)
        print(f"✅ Backup created: {backup_file}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Backup failed: {e}")
```

### 3. Git-track Schema Changes

Track schema as SQL for reference:

```bash
# Export current schema
PGPASSWORD=admin pg_dump -h 192.168.88.125 -U postgres -s qlts_dev > schema_snapshot.sql

# Commit to git
git add schema_snapshot.sql
git commit -m "docs: Update database schema snapshot"
```

### 4. Export Important Data to CSV

```python
# scripts/export_data.py
import pandas as pd
from sqlalchemy import text
from app.database import engine
import asyncio

async def export_all_tables():
    async with engine.begin() as conn:
        # Get all table names
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ))
        tables = [row[0] for row in result.fetchall()]

        for table in tables:
            if table == 'alembic_version':
                continue

            print(f"Exporting {table}...")
            result = await conn.execute(text(f"SELECT * FROM {table}"))
            rows = result.fetchall()
            columns = result.keys()

            df = pd.DataFrame(rows, columns=columns)
            df.to_csv(f"exports/{table}.csv", index=False)
            print(f"  ✓ Exported {len(rows)} rows")

asyncio.run(export_all_tables())
```

---

## 🔄 Import Data from CSV (Khôi phục data từ exports)

```python
# scripts/import_data.py
import pandas as pd
from sqlalchemy import text
from app.database import engine
import asyncio
import os

async def import_all_tables():
    export_dir = "exports"

    if not os.path.exists(export_dir):
        print(f"❌ Export directory not found: {export_dir}")
        return

    # Import order (respect foreign key constraints)
    import_order = [
        "organization_unit",
        "pipeline_stage",
        "consultation_status",
        "skill_requirement_rule",
        "user",
        "user_session",
        "major",
        "lead_scoring_config",
        "officer_assignment_config",
        "lead",
        "consultation",
        "crm_interaction",
        "lead_status_history",
        "assignment_log",
        "application",
    ]

    async with engine.begin() as conn:
        for table in import_order:
            csv_file = f"{export_dir}/{table}.csv"
            if not os.path.exists(csv_file):
                print(f"⚠️  Skipping {table} (file not found)")
                continue

            print(f"Importing {table}...")
            df = pd.read_csv(csv_file)

            # Convert to list of dicts
            records = df.to_dict('records')

            if not records:
                print(f"  ⚠️  No data in {table}")
                continue

            # Build INSERT statement
            columns = list(records[0].keys())
            placeholders = ", ".join([f":{col}" for col in columns])
            insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

            # Insert all records
            for record in records:
                await conn.execute(text(insert_sql), record)

            print(f"  ✓ Imported {len(records)} rows")

asyncio.run(import_all_tables())
```

---

## ✅ Verification Checklist

Sau khi khôi phục, verify:

- [ ] **Tables tồn tại:**
  ```bash
  PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "\dt"
  # Phải có 17 tables
  ```

- [ ] **Indexes tồn tại:**
  ```bash
  PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "\di"
  # Phải có ~40 indexes
  ```

- [ ] **Foreign keys hoạt động:**
  ```bash
  PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "\d user"
  # Xem foreign key constraints
  ```

- [ ] **Application có thể connect:**
  ```bash
  cd /mnt/d/QLTS/Backend_FastAPI
  python -c "from app.database import engine; import asyncio; asyncio.run(engine.connect())"
  # Không có lỗi
  ```

- [ ] **Alembic tracking đúng:**
  ```bash
  alembic current
  # Phải hiển thị: bf0ce03e4900 (head)
  ```

---

## 🚨 TÌM HIỂU NGUYÊN NHÂN GỐC

### Tại sao tests xóa production database?

1. **pytest-dotenv conflict** (đã fix)
   - Plugin auto-load `.env` trước `conftest.py`
   - Override `.env.test` settings
   - Tests chạy trên production database

2. **Thiếu safety checks** (đã fix)
   - `conftest.py` bây giờ có `_verify_test_database_safety()`
   - Chặn tests nếu DATABASE_URL không chứa "test"
   - Chặn patterns nguy hiểm: `/qlts_dev`, `/qlts_prod`

3. **`drop_all()` không có confirm** (đã fix)
   - Safety check chạy TRƯỚC `drop_all()`
   - Tests fail ngay nếu database không an toàn

### Làm sao tránh trong tương lai?

✅ **Đã implement:**
1. Safety checks trong `conftest.py`
2. Tách biệt `.env` và `.env.test`
3. Document `pytest-dotenv` conflict
4. Debug tools (`debug_local_env.py`)

🔧 **Nên làm thêm:**
1. Daily automatic backups
2. Pre-test backup hook
3. Export data to CSV định kỳ
4. Track schema in git

---

## 📚 Related Documentation

- `PYTEST_DOTENV_CONFLICT.md` - Giải thích conflict gây ra data loss
- `SETUP_TEST_DATABASE.md` - Setup test database đúng cách
- `tests/README_TESTING_SAFETY.md` - Testing safety guidelines
- `CHECK_ENV.md` - Environment troubleshooting

---

## 🆘 Need Help?

### Nếu migrations fail:

```bash
# Check Alembic version table
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "SELECT * FROM alembic_version;"

# Reset Alembic tracking
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev -c "DELETE FROM alembic_version;"

# Try upgrade again
alembic upgrade head
```

### Nếu foreign key constraints fail:

```bash
# Disable constraints temporarily
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
-- Your import commands here
COMMIT;
```

### Nếu có data conflicts:

```bash
# Reset sequences after import
PGPASSWORD=admin psql -h 192.168.88.125 -U postgres -d qlts_dev << EOF
SELECT setval(pg_get_serial_sequence('user', 'id'), COALESCE(MAX(id), 1)) FROM user;
SELECT setval(pg_get_serial_sequence('lead', 'id'), COALESCE(MAX(id), 1)) FROM lead;
-- Repeat for all tables with serial IDs
EOF
```

---

## 📊 Summary

| Phương pháp | Ưu điểm | Nhược điểm | Khi nào dùng |
|-------------|---------|------------|--------------|
| **Alembic upgrade** | Nhanh, tự động, đúng version | Chỉ restore structure | Database structure bị xóa |
| **SQL script** | Linh hoạt, có thể chỉnh sửa | Phức tạp, dễ sai | Alembic fail |
| **Recreate + upgrade** | Sạch sẽ, đảm bảo đúng | Xóa toàn bộ database | Database corrupt |
| **Restore backup** | Restore cả data | Cần có backup sẵn | Có backup file |
| **Import CSV** | Restore data từ exports | Chậm, cần đúng order | Có CSV exports |

**KHUYẾN NGHỊ:** Luôn có **backup tự động** để tránh mất data!
