# 🔍 Checklist - Tìm nguyên nhân lỗi "/qlts_dev"

## Bước 1: Kiểm tra shell environment variables

Chạy lệnh sau TRƯỚC KHI chạy pytest:

```bash
# Kiểm tra biến DATABASE_URL trong shell
echo $DATABASE_URL

# Kiểm tra tất cả biến môi trường liên quan
env | grep -E "(APP_ENV|DATABASE_URL|POSTGRES)"
```

**❌ Nếu có output** → Đây là vấn đề! Shell environment đang override .env.test!

**Giải pháp:**
```bash
# Xóa biến DATABASE_URL
unset DATABASE_URL

# Hoặc reset shell session
exec bash  # hoặc exec zsh

# Sau đó chạy lại pytest
cd Backend_FastAPI
pytest tests/ -v
```

---

## Bước 2: Kiểm tra file .env có tồn tại không

```bash
cd Backend_FastAPI

# Liệt kê tất cả file .env
ls -la .env*

# Xem nội dung .env (nếu tồn tại)
cat .env | grep DATABASE_URL

# Xem nội dung .env.test
cat .env.test | grep DATABASE_URL
```

**Nếu có file `.env` chứa `qlts_dev`:**
- Đảm bảo `.env` KHÔNG được load khi chạy tests
- Hoặc xóa/đổi tên file `.env` tạm thời:
  ```bash
  mv .env .env.backup
  ```

---

## Bước 3: Chạy debug script

```bash
cd Backend_FastAPI
python debug_local_env.py
```

Gửi toàn bộ output cho tôi!

---

## Bước 4: Kiểm tra cách bạn chạy pytest

**❌ SAI (có thể set biến environment):**
```bash
DATABASE_URL="..." pytest tests/
```

**✅ ĐÚNG:**
```bash
cd Backend_FastAPI
pytest tests/ -v
```

---

## Bước 5: Kiểm tra file .bashrc / .zshrc

Có thể bạn đã set `DATABASE_URL` trong file cấu hình shell:

```bash
# Kiểm tra .bashrc
grep DATABASE_URL ~/.bashrc

# Kiểm tra .zshrc
grep DATABASE_URL ~/.zshrc

# Kiểm tra .bash_profile
grep DATABASE_URL ~/.bash_profile
```

**Nếu tìm thấy** → Xóa dòng đó hoặc comment lại!

---

## Giải thích Priority của Pydantic-settings

Thứ tự load (từ cao đến thấp):

1. **Shell environment variables** ← HIGHEST (override tất cả!)
   ```bash
   export DATABASE_URL="..."  # ← override .env.test!
   ```

2. **File .env.test** (khi APP_ENV=test)
   ```bash
   DATABASE_URL="..."  # ← được override bởi shell env
   ```

3. **Default values** trong Settings class

**Vì vậy**: Nếu có `DATABASE_URL` trong shell environment → .env.test bị ignored!

---

## Debug Output mong muốn

Khi chạy `python debug_local_env.py`, bạn sẽ thấy:

```
✅ CORRECT OUTPUT:
✓ settings.DATABASE_URL = postgresql+asyncpg://your_test_user:admintest@192.168.0.120:5432/your_test_db_name
  • Contains 'test': True
  • Contains '/qlts_dev': False
✅ SAFETY CHECK WOULD PASS!
```

```
❌ WRONG OUTPUT (vấn đề của bạn):
✓ settings.DATABASE_URL = postgresql+asyncpg://postgres:admin@192.168.0.120:5432/qlts_dev
  • Contains 'test': False
  • Contains '/qlts_dev': True
❌ SAFETY CHECK WOULD FAIL!
```

---

## Quick Fix

Nếu muốn fix nhanh để chạy tests ngay:

```bash
# Reset environment
unset DATABASE_URL
unset APP_ENV

# Chạy tests
cd Backend_FastAPI
pytest tests/ -v
```

Hoặc chạy với env clean:

```bash
env -i HOME=$HOME PATH=$PATH SHELL=$SHELL bash
cd Backend_FastAPI
pytest tests/ -v
```
