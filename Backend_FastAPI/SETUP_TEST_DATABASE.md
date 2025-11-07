# 🔧 Hướng dẫn Setup Database Test

## 📋 Tóm tắt vấn đề đã khắc phục

### Vấn đề ban đầu:
```
❌ Dangerous patterns detected: ['/qlts_dev']
❌ Tests will NOT run to prevent production database deletion!
```

### Nguyên nhân:
File `.env.test` dòng 28 có giá trị placeholder:
```bash
DATABASE_URL="postgresql+asyncpg://your_test_user:admintest@192.168.0.120:5432/your_test_db_name"
```

Tên database `your_test_db_name` **KHÔNG chứa từ "test"** → bị safety check chặn!

### Giải pháp:
Đã cập nhật `.env.test` dòng 29 thành:
```bash
DATABASE_URL="postgresql+asyncpg://postgres:admintest@192.168.0.120:5432/qlts_test"
```

---

## 🚀 Các bước setup (thực hiện theo thứ tự)

### Bước 1: Tạo database test trong PostgreSQL

**Cách 1: Sử dụng psql từ máy có quyền truy cập PostgreSQL server**

```bash
# Kết nối và tạo database
PGPASSWORD=admintest psql -h 192.168.0.120 -U postgres -p 5432 -c "CREATE DATABASE qlts_test WITH OWNER = postgres ENCODING = 'UTF8';"

# Kiểm tra database đã tạo
PGPASSWORD=admintest psql -h 192.168.0.120 -U postgres -p 5432 -l | grep qlts
```

**Cách 2: Sử dụng pgAdmin hoặc GUI tool**

1. Kết nối đến PostgreSQL server: `192.168.0.120:5432`
2. Login với user `postgres`, password `admintest`
3. Right-click "Databases" → Create → Database
4. Database name: `qlts_test`
5. Owner: `postgres`
6. Encoding: `UTF8`
7. Save

**Cách 3: Từ terminal trên server PostgreSQL**

```bash
sudo -u postgres psql
CREATE DATABASE qlts_test WITH OWNER = postgres ENCODING = 'UTF8';
\l  -- kiểm tra danh sách databases
\q  -- thoát
```

---

### Bước 2: Kiểm tra kết nối database test

```bash
cd Backend_FastAPI

# Chạy script kiểm tra cấu hình
python verify_test_config.py
```

**Output mong muốn:**
```
✅ TẤT CẢ KIỂM TRA THÀNH CÔNG
✓ APP_ENV: test
✓ DATABASE_URL: postgresql+asyncpg://postgres:admintest@192.168.0.120:5432/qlts_test
  ✅ OK: Database name chứa 'test' (an toàn)
```

---

### Bước 3: Chạy tests

```bash
cd Backend_FastAPI
pytest tests/ -v
```

**Hoặc chạy từng test file:**

```bash
# Test authentication
pytest tests/routers/test_auth.py -v

# Test WebSocket security
pytest tests/routers/test_websocket_security.py -v
```

---

## ✅ Checklist hoàn thành

- [x] Cập nhật `.env.test` với database name chứa "test"
- [x] Tạo script `verify_test_config.py` để kiểm tra cấu hình
- [x] Tạo script `create_test_db.sql` để tạo database
- [ ] **Tạo database `qlts_test` trong PostgreSQL** ← BẠN CẦN LÀM BƯỚC NÀY
- [ ] **Chạy `python verify_test_config.py`** để xác nhận
- [ ] **Chạy `pytest tests/ -v`** để verify tests pass

---

## 🔐 Cơ chế Safety Check

File `tests/conftest.py` có hàm `_verify_test_database_safety()` kiểm tra:

### ✅ An toàn (được phép chạy tests):
- `DATABASE_URL="sqlite+aiosqlite:///:memory:"` (in-memory)
- `DATABASE_URL="postgresql://...@.../qlts_test"` (chứa "test")
- `DATABASE_URL="postgresql://...@.../my_test_db"` (chứa "test")

### ❌ Nguy hiểm (bị chặn):
- `DATABASE_URL="postgresql://...@.../qlts_dev"` (development)
- `DATABASE_URL="postgresql://...@.../qlts_prod"` (production)
- `DATABASE_URL="postgresql://...@.../qlts_production"`
- `DATABASE_URL="postgresql://...@.../your_test_db_name"` (không chứa "test")

---

## 🎯 Lý do cần database riêng cho test

**⚠️  QUAN TRỌNG:** Tests sẽ **XÓA TẤT CẢ TABLES** trước mỗi test!

```python
# tests/conftest.py - chạy trước mỗi test function
@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_database(manage_engine):
    _verify_test_database_safety()  # ← Kiểm tra an toàn TRƯỚC

    async with engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.drop_all)    # ← XÓA TẤT CẢ
        await conn.run_sync(AppBase.metadata.create_all)  # ← TẠO LẠI
```

**Điều này có nghĩa:**
- ✅ Mỗi test có database sạch, không bị ảnh hưởng bởi test khác
- ✅ Test isolation hoàn toàn
- ❌ **KHÔNG BAO GIỜ** dùng database production hoặc development cho tests!

---

## 📝 Cấu trúc databases trong project

```
PostgreSQL Server (192.168.0.120:5432)
├── qlts_dev          → Development (dùng cho .env)
│   ├── users         → Data thật của bạn
│   ├── sessions      → ✅ AN TOÀN không bị tests xóa
│   └── ...
│
└── qlts_test         → Testing (dùng cho .env.test)
    ├── (empty)       → Tests sẽ tạo/xóa tables liên tục
    └── ...           → ❌ KHÔNG LƯU DATA THẬT Ở ĐÂY!
```

---

## 🆘 Troubleshooting

### ⚠️ Lỗi: "Dangerous patterns detected" (QUAN TRỌNG NHẤT!)

**Triệu chứng:**
```bash
pytest tests/ -v
→ 🚨 Dangerous patterns detected: ['/qlts_dev']

python debug_local_env.py
→ ✅ SAFETY CHECK WOULD PASS!
```

**Nguyên nhân:** Plugin `pytest-dotenv` tự động load `.env` TRƯỚC conftest.py!

**Giải pháp:**
```bash
# Kiểm tra
pip list | grep dotenv

# Nếu thấy pytest-dotenv → Uninstall ngay!
pip uninstall pytest-dotenv

# Chạy lại tests
pytest tests/ -v
```

**Chi tiết:** Xem `PYTEST_DOTENV_CONFLICT.md` để hiểu rõ vấn đề!

---

### Lỗi: Database name không chứa "test"

**Nguyên nhân:** Database name không chứa "test" hoặc chứa pattern nguy hiểm

**Giải pháp:**
1. Kiểm tra file `.env.test` dòng 29
2. Đảm bảo `DATABASE_URL` chứa database name có chữ "test"
3. Chạy `python verify_test_config.py` để xác nhận

### Lỗi: "FATAL: database 'qlts_test' does not exist"

**Nguyên nhân:** Chưa tạo database test

**Giải pháp:** Thực hiện Bước 1 (tạo database)

### Lỗi: "connection refused" khi tạo database

**Nguyên nhân:**
- PostgreSQL server không chạy
- Firewall chặn port 5432
- IP/port không đúng
- User/password không đúng

**Giải pháp:**
```bash
# Kiểm tra PostgreSQL đang chạy
sudo systemctl status postgresql

# Kiểm tra port có mở không
telnet 192.168.0.120 5432

# Kiểm tra trong pg_hba.conf có cho phép kết nối từ client machine
```

### Tests vẫn xóa data development

**KHÔNG THỂ XẢY RA NỮA** vì:
1. Safety check chặn database không có "test" trong tên
2. Safety check chặn các pattern nguy hiểm (/qlts_dev, /qlts_prod)
3. `conftest.py` đã set `APP_ENV=test` → luôn load `.env.test`
4. Không có hardcoded database URL trong code

---

## 📚 Files liên quan

```
Backend_FastAPI/
├── .env                           # Development/production config
├── .env.test                      # ✅ Test config (đã cập nhật)
├── .env.example                   # Template for .env
├── .env.test.example              # Template for .env.test
├── verify_test_config.py          # ✅ Script kiểm tra cấu hình
├── create_test_db.sql             # ✅ Script tạo database
├── SETUP_TEST_DATABASE.md         # ✅ Tài liệu này
├── tests/
│   ├── conftest.py                # ✅ Có safety check
│   └── README_TESTING_SAFETY.md   # ✅ Tài liệu chi tiết về testing safety
└── app/
    └── config.py                  # ✅ Không có hardcoded values
```

---

## 🎉 Kết luận

Sau khi hoàn thành các bước trên:

✅ Database test được tách biệt hoàn toàn với development/production
✅ Safety check đảm bảo không xóa nhầm database
✅ Tests có thể chạy an toàn với fresh database mỗi lần
✅ Cấu hình rõ ràng, không có hardcoded values

**Câu hỏi?** Xem thêm `tests/README_TESTING_SAFETY.md`
