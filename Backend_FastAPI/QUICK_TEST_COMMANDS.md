# Quick Test Commands for PHASE 2A

## ⚡ TL;DR - Copy & Paste These Commands

### For WSL/Linux Users (You!)

```bash
# 1. Navigate to Backend directory
cd /mnt/d/QLTS/Backend_FastAPI

# 2. Activate virtual environment (REQUIRED!)
source venv/bin/activate

# 3. Install test dependencies (one-time setup)
pip install httpx pytest pytest-asyncio fakeredis redis sqlalchemy

# 4. Run all PHASE 2A tests
python -m pytest tests/routers/admin/ -v

# OR use simplified script
bash run_tests_simple.sh
```

---

## 📋 Detailed Commands

### Setup (One-Time)

```bash
# Navigate to project
cd /mnt/d/QLTS/Backend_FastAPI

# Activate venv
source venv/bin/activate

# You should see (venv) in your prompt:
# (venv) hapham@Ideapad-hp:/mnt/d/QLTS/Backend_FastAPI$

# Install ONLY test dependencies (avoid conflicts)
pip install httpx pytest pytest-asyncio fakeredis redis
```

### Run Tests

```bash
# Make sure venv is activated first!
source venv/bin/activate

# Run all admin tests (48 tests)
python -m pytest tests/routers/admin/ -v

# Run with coverage
python -m pytest tests/routers/admin/ --cov=app/routers/admin --cov-report=html -v

# Run only users tests (21 tests)
python -m pytest tests/routers/admin/test_users.py -v

# Run only roles tests (27 tests)
python -m pytest tests/routers/admin/test_roles.py -v

# Run a single test
python -m pytest tests/routers/admin/test_users.py::test_create_user_success -v
```

### Using Simplified Script

```bash
# Activate venv first!
source venv/bin/activate

# Run all tests
bash run_tests_simple.sh

# With verbose output
bash run_tests_simple.sh --verbose

# With coverage
bash run_tests_simple.sh --coverage

# Only users tests
bash run_tests_simple.sh --users

# Only roles tests
bash run_tests_simple.sh --roles
```

---

## ❌ Common Errors & Fixes

### Error: `./run_phase2a_tests.sh: cannot execute: required file not found`

**Cause**: WSL filesystem permissions issue

**Fix**: Use `bash` explicitly:
```bash
bash run_phase2a_tests.sh
# OR
bash run_tests_simple.sh
```

### Error: `ModuleNotFoundError: No module named 'httpx'`

**Cause**: Dependencies not installed OR venv not activated

**Fix**:
```bash
# 1. Activate venv (MOST IMPORTANT!)
source venv/bin/activate

# 2. Install test dependencies
pip install httpx pytest pytest-asyncio fakeredis redis

# 3. Run tests again
python -m pytest tests/routers/admin/ -v
```

### Error: `Cannot uninstall PyYAML, RECORD file not found`

**Cause**: Conflict between system packages and pip

**Fix**: Don't use `run_phase2a_tests.sh` (it tries to install all dependencies).
Use `run_tests_simple.sh` or direct pytest commands instead:
```bash
# Use this instead
bash run_tests_simple.sh

# OR
python -m pytest tests/routers/admin/ -v
```

### Error: `sqlalchemy.exc.CompileError: Can't emit DROP CONSTRAINT`

**Cause**: Old code without constraint name fix

**Fix**: Pull latest changes:
```bash
git pull origin claude/refactoring-execution-plan-015j9PAMoSNW4qbrVgJhnpUc

# Verify fix is applied
grep "fk_user_current_assignment" app/models/user.py
# Should return: name="fk_user_current_assignment",
```

### Error: Virtual environment not activated

**Symptoms**:
- Tests run but fail with import errors
- pip installs to wrong location
- Commands not found

**Fix**:
```bash
# Activate venv
source venv/bin/activate

# Verify activation - you should see (venv) prefix:
# (venv) hapham@Ideapad-hp:...$

# Also verify Python location:
which python
# Should output: /mnt/d/QLTS/Backend_FastAPI/venv/bin/python

# Verify packages:
pip list | grep httpx
# Should show: httpx  x.x.x
```

---

## ✅ Success Criteria

### Expected Output

```bash
$ python -m pytest tests/routers/admin/ -v

platform linux -- Python 3.12.x, pytest-8.4.2, pluggy-1.6.0
collected 48 items

tests/routers/admin/test_users.py::test_create_user_success PASSED          [ 2%]
tests/routers/admin/test_users.py::test_get_all_users PASSED                [ 4%]
...
tests/routers/admin/test_roles.py::test_assign_duplicate_role_fails PASSED  [100%]

============================== 48 passed in 12.34s ==============================
```

### What to Check

✅ All 48 tests pass (no failures)
✅ Execution time: 10-20 seconds
✅ No import errors
✅ No database errors
✅ No permission errors

---

## 🚀 Quick Reference

| Task | Command |
|------|---------|
| Activate venv | `source venv/bin/activate` |
| Run all tests | `python -m pytest tests/routers/admin/ -v` |
| Run with coverage | `python -m pytest tests/routers/admin/ --cov=app/routers/admin --cov-report=html` |
| Run users tests | `python -m pytest tests/routers/admin/test_users.py -v` |
| Run roles tests | `python -m pytest tests/routers/admin/test_roles.py -v` |
| Run single test | `python -m pytest tests/routers/admin/test_users.py::test_create_user_success -v` |
| Use simple script | `bash run_tests_simple.sh` |
| With coverage | `bash run_tests_simple.sh --coverage` |

---

## 📝 Step-by-Step Walkthrough

### First Time Setup

```bash
# Step 1: Go to project directory
cd /mnt/d/QLTS/Backend_FastAPI

# Step 2: Check if venv exists
ls -la venv/
# If not exists, create it:
# python3 -m venv venv

# Step 3: Activate venv (CRITICAL!)
source venv/bin/activate

# Step 4: Install test dependencies
pip install httpx pytest pytest-asyncio fakeredis redis sqlalchemy

# Step 5: Verify installation
python -c "import httpx, pytest; print('✅ Test dependencies installed!')"
```

### Every Time You Run Tests

```bash
# Step 1: Navigate to project
cd /mnt/d/QLTS/Backend_FastAPI

# Step 2: Activate venv (if not already activated)
source venv/bin/activate

# Step 3: Run tests
python -m pytest tests/routers/admin/ -v

# Done! ✅
```

---

## 🆘 Still Having Issues?

### Check Environment

```bash
# 1. Verify venv is activated
echo $VIRTUAL_ENV
# Should output: /mnt/d/QLTS/Backend_FastAPI/venv

# 2. Verify Python version
python --version
# Should be Python 3.11 or 3.12

# 3. Verify pytest is installed
pytest --version
# Should show pytest version

# 4. Verify httpx is installed
python -c "import httpx; print(httpx.__version__)"
# Should print version number

# 5. Verify database is accessible
python -c "from app.database import engine; print('✅ DB connection OK')"
```

### Get Detailed Error Info

```bash
# Run with maximum verbosity
python -m pytest tests/routers/admin/ -vv --tb=long

# Run with debug output
python -m pytest tests/routers/admin/ -vv --tb=long --showlocals

# Run and stop at first failure
python -m pytest tests/routers/admin/ -x -vv
```

### Contact Support

If still failing after trying all fixes:

1. Copy full error output
2. Check which command you ran
3. Verify venv activation
4. Check git branch: `git branch --show-current`
5. Check latest commit: `git log -1 --oneline`

---

## 📚 Additional Resources

- **Full testing guide**: `PHASE2A_AUTOMATED_TESTING.md`
- **Setup guide**: `PHASE2A_TEST_SETUP_GUIDE.md`
- **Completion summary**: `PHASE2A_COMPLETION_SUMMARY.md`

---

## Summary

**Simplest way to run tests**:

```bash
cd /mnt/d/QLTS/Backend_FastAPI
source venv/bin/activate
python -m pytest tests/routers/admin/ -v
```

That's it! 🎉
