# 🐛 PYTEST-DOTENV CONFLICT - Root Cause Analysis

## ⚠️ CRITICAL ISSUE DISCOVERED

### Problem Summary

**Symptom:**
```bash
pytest tests/ -v
→ 🚨 SAFETY CHECK FAILED! 🚨
→ Dangerous patterns detected: ['/qlts_dev']
```

**But:**
```bash
python debug_local_env.py
→ ✅ SAFETY CHECK WOULD PASS!
→ DATABASE_URL = your_test_db_name (contains "test")
```

### Root Cause: `pytest-dotenv` Plugin

The `pytest-dotenv` plugin **automatically loads `.env` file BEFORE `conftest.py` runs**!

#### Execution Order (causing the bug):

```
┌─────────────────────────────────────────────────────────────┐
│ 1. pytest-dotenv plugin loads .env                         │
│    → Sets DATABASE_URL="...qlts_dev" in shell environment  │
├─────────────────────────────────────────────────────────────┤
│ 2. conftest.py runs                                         │
│    → Sets APP_ENV="test"                                    │
├─────────────────────────────────────────────────────────────┤
│ 3. config.py loads                                          │
│    → Detects APP_ENV=test → tries to load .env.test        │
│    → But DATABASE_URL already in environment (from step 1)  │
│    → Pydantic uses environment variable (higher priority!)  │
│    → Result: DATABASE_URL="...qlts_dev" (WRONG!)           │
└─────────────────────────────────────────────────────────────┘
```

#### Why `python debug_local_env.py` works:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Script runs                                              │
│    → No pytest-dotenv plugin                                │
│    → No .env auto-loading                                   │
├─────────────────────────────────────────────────────────────┤
│ 2. Script sets APP_ENV=test                                 │
├─────────────────────────────────────────────────────────────┤
│ 3. config.py loads                                          │
│    → Detects APP_ENV=test → loads .env.test                │
│    → DATABASE_URL from .env.test (CORRECT!)                │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Solution

### Option 1: Uninstall pytest-dotenv (RECOMMENDED)

We don't need this plugin because `conftest.py` already handles environment setup correctly.

```bash
# Uninstall the plugin
pip uninstall pytest-dotenv

# Verify it's removed
pip list | grep dotenv
# Should only see: python-dotenv (this one is OK to keep)
```

### Option 2: Disable pytest-dotenv in pytest.ini

If you need to keep the plugin for other reasons, disable it:

```ini
# pytest.ini
[pytest]
env_files =
# Empty = don't load any .env file automatically
```

Or configure it to load .env.test:

```ini
# pytest.ini
[pytest]
env_files = .env.test
```

**⚠️ Warning:** Option 2 is NOT recommended because:
- conftest.py already sets APP_ENV=test before loading
- Having two mechanisms loading env files can cause conflicts

### Option 3: Remove DATABASE_URL from .env (temporary workaround)

Move DATABASE_URL from `.env` to shell environment or docker-compose:

```bash
# .env - remove DATABASE_URL line temporarily
# Run app with:
DATABASE_URL="postgresql://...qlts_dev" python -m uvicorn app.main:app
```

**⚠️ Warning:** This is not ideal for development workflow.

---

## 📋 Checklist to Fix

- [ ] **Step 1:** Uninstall pytest-dotenv
  ```bash
  pip uninstall pytest-dotenv
  ```

- [ ] **Step 2:** Verify it's removed
  ```bash
  pip list | grep dotenv
  # Should NOT see pytest-dotenv
  ```

- [ ] **Step 3:** Run debug script to confirm
  ```bash
  python debug_local_env.py
  # Should show: ✅ SAFETY CHECK WOULD PASS!
  ```

- [ ] **Step 4:** Run pytest
  ```bash
  pytest tests/ -v
  # Should now PASS without safety check errors!
  ```

- [ ] **Step 5:** Update requirements if needed
  ```bash
  # If you have requirements.txt with pytest-dotenv, remove it
  # Regenerate:
  pip freeze > requirements.txt
  ```

---

## 🔍 How to Detect This Issue

### Check if pytest-dotenv is installed:

```bash
pip list | grep dotenv
```

**Problem:**
```
pytest-dotenv    0.5.2  ← THIS CAUSES THE BUG!
python-dotenv    1.1.1  ← This is OK
```

**Fixed:**
```
python-dotenv    1.1.1  ← Only this one
```

### Check pytest.ini:

```bash
cat pytest.ini
```

Look for:
```ini
[pytest]
env_files = .env  ← PROBLEM! Will auto-load .env
```

---

## 📚 Why We Don't Need pytest-dotenv

Our codebase already has **proper environment management**:

1. **conftest.py** (tests/conftest.py:22-23)
   - Sets `APP_ENV=test` BEFORE any imports
   - Ensures test environment isolation

2. **config.py** (app/config.py:10-15)
   - Dynamically selects `.env` vs `.env.test` based on APP_ENV
   - No hardcoded env file paths

3. **pydantic-settings** (app/config.py:154-160)
   - Handles env file loading
   - Respects priority: environment > .env file > defaults

**Adding pytest-dotenv on top breaks this carefully designed system!**

---

## 🎯 Technical Deep Dive

### Pydantic-settings Priority (by design):

```
Priority (High → Low):
┌──────────────────────────────────────┐
│ 1. Shell environment variables      │ ← pytest-dotenv sets here!
├──────────────────────────────────────┤
│ 2. Specified env_file (.env.test)   │ ← Our code uses this
├──────────────────────────────────────┤
│ 3. Default values                    │
└──────────────────────────────────────┘
```

When pytest-dotenv loads `.env`:
- Sets `DATABASE_URL=qlts_dev` as **environment variable** (priority 1)
- Our code loads `.env.test` (priority 2)
- Pydantic uses priority 1 → **ignores** .env.test!

### pytest-dotenv Loading Mechanism

```python
# pytest-dotenv loads .env VERY EARLY in pytest lifecycle
# Before conftest.py, before fixtures, before tests

# Pseudocode:
def pytest_configure(config):
    load_dotenv(".env")  # ← Happens FIRST!
    # Now conftest.py runs...
```

This is **incompatible** with our dynamic env file selection!

---

## ✅ Verification

After uninstalling pytest-dotenv, verify:

### 1. Environment isolation works:

```bash
# Terminal 1 - Development
DATABASE_URL="...qlts_dev" python -m uvicorn app.main:app
# Uses .env (development database)

# Terminal 2 - Testing
pytest tests/ -v
# Uses .env.test (test database)
# ✅ No conflict!
```

### 2. Safety check works:

```bash
pytest tests/routers/test_websocket_security.py -v
# Should see:
# INFO [conftest.py]: Verified os.getenv('APP_ENV') = test
# ✅ Safety check passed: APP_ENV=test, DB_URL=...your_test_db_name
```

### 3. Debug script confirms:

```bash
python debug_local_env.py
# ✅ SAFETY CHECK WOULD PASS!
# ✓ settings.DATABASE_URL = ...your_test_db_name
```

---

## 📖 Related Documentation

- `CHECK_ENV.md` - Environment troubleshooting guide
- `SETUP_TEST_DATABASE.md` - Test database setup
- `tests/README_TESTING_SAFETY.md` - Testing safety guidelines
- `debug_local_env.py` - Environment debugging script

---

## 🎉 Summary

**Problem:** pytest-dotenv auto-loads `.env` → overrides `.env.test`
**Impact:** Tests use development database instead of test database
**Risk:** Production data deletion!
**Solution:** Uninstall pytest-dotenv
**Verification:** Run `python debug_local_env.py` and `pytest tests/ -v`

**Our environment management is already perfect - don't add conflicting tools!** ✅
