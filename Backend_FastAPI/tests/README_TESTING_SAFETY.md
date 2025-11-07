# 🚨 Testing Safety Guidelines

## CRITICAL: Database Safety

### ⚠️ Tests WILL DROP ALL TABLES

Our test suite automatically **drops and recreates all database tables** before each test function. This ensures test isolation and clean state.

**This means:**
- ❌ **NEVER** point `DATABASE_URL` in `.env.test` to production database
- ❌ **NEVER** use a shared development database for testing
- ✅ **ALWAYS** use `:memory:` database or dedicated test database

---

## Safety Checks (Automatic)

The test suite includes **automatic safety checks** that will **BLOCK tests** from running if:

### Check 1: APP_ENV Verification
```python
if APP_ENV != "test":
    FAIL: "Tests will NOT run to prevent production database deletion!"
```

### Check 2: DATABASE_URL Verification
```python
if DATABASE_URL does not contain ":memory:" or "test":
    FAIL: "Database URL does not appear to be a test database!"
```

---

## Configuration Files

### `.env.test` (For Testing)
```bash
APP_ENV=test
DATABASE_URL=sqlite+aiosqlite:///:memory:  # ✅ Safe: in-memory database
```

**DO NOT change `DATABASE_URL` to:**
- `sqlite:///./qlts.db` ❌ File-based production database
- `postgresql://user:pass@localhost/qlts_db` ❌ Production PostgreSQL
- Any other non-memory, non-test database ❌

### `.env` (For Development/Production)
```bash
APP_ENV=development
DATABASE_URL=sqlite:///./qlts.db  # OK for development
```

**This file is IGNORED during tests.** Tests always use `.env.test`.

---

## How Tests Work

### 1. Environment Loading
```
conftest.py (line 24): os.environ["APP_ENV"] = "test"
↓
config.py: Detects APP_ENV="test" → loads .env.test
↓
settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
```

### 2. Safety Check
```
setup_test_database fixture:
  ↓
_verify_test_database_safety():
  ✓ Check APP_ENV == "test"
  ✓ Check DATABASE_URL is safe
  ↓
PASS → Continue with tests
FAIL → Block tests, show error
```

### 3. Database Operations
```
For EACH test function:
  1. DROP all tables
  2. CREATE all tables (fresh)
  3. Run test
  4. DROP all tables (cleanup)
```

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Using production database for tests
```bash
# In .env.test
DATABASE_URL=postgresql://user:pass@localhost/qlts_production  # ❌ WRONG!
```
**Result:** All production data will be DELETED! 💀

### ❌ Mistake 2: Sharing database between dev and test
```bash
# In .env.test
DATABASE_URL=sqlite:///./qlts.db  # ❌ WRONG! This is your dev database
```
**Result:** Your development data will be lost every test run!

### ❌ Mistake 3: Running tests without conftest
```bash
python tests/routers/test_something.py  # ❌ Might bypass safety checks
```
**Always run:** `pytest tests/`

---

## What If I Accidentally Deleted Production Data?

If you already lost data:

1. **Check backups:** Restore from database backups
2. **Check git history:** Some data might be in fixtures or migration files
3. **Contact team:** Others might have copies

**Prevention:**
- ✅ Always use `:memory:` for tests
- ✅ Regular production backups
- ✅ Never commit `.env` files to git
- ✅ Use separate database servers for test/dev/prod

---

## Testing Safely

### ✅ SAFE: Running tests
```bash
cd Backend_FastAPI
pytest tests/                          # Uses .env.test automatically
pytest tests/routers/test_auth.py -v  # Single test file
```

### ✅ SAFE: Debugging tests
```bash
pytest tests/ -v --pdb  # Drop into debugger on failure
pytest tests/ -k "test_login"  # Run specific test by name
```

### ⚠️ CHECK FIRST: Running app
```bash
# Make sure you're NOT in test mode!
echo $APP_ENV  # Should NOT be "test"

# Check .env file
cat .env | grep DATABASE_URL  # Should be your dev database

# Then run
uvicorn app.main:app --reload
```

---

## Summary

| Action | Safe? | Why |
|--------|-------|-----|
| `pytest tests/` with `.env.test` having `:memory:` | ✅ YES | In-memory database, no files touched |
| `pytest tests/` with `.env.test` pointing to test DB | ✅ YES | If database name contains "test" |
| `pytest tests/` with `.env.test` pointing to prod DB | ❌ NO | Will delete production data! |
| Running app with `APP_ENV=test` | ⚠️ CAREFUL | App will use test config |

---

## Need Help?

If you're unsure about your test configuration:

1. Check current environment:
   ```bash
   cat .env.test | grep -E "APP_ENV|DATABASE_URL"
   ```

2. Verify safety:
   ```python
   # Should see safety check messages
   pytest tests/ -v -s | grep "Safety check"
   ```

3. Ask team before changing test database configuration!

---

**Last updated:** 2025-11-07
**Maintainer:** Development Team
