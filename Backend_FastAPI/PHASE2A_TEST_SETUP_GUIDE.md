# PHASE 2A Test Setup & Troubleshooting

## Quick Fix: Test Dependencies Not Installed

### Problem
Tests failing with:
```
ModuleNotFoundError: No module named 'httpx'
```

### Solution

```bash
# Navigate to Backend_FastAPI directory
cd /home/user/QLTS/Backend_FastAPI

# Activate virtual environment (if not already activated)
source venv/bin/activate

# Install all dependencies including test dependencies
pip install -r requirements.txt

# Verify installation
python -c "import httpx, pytest; print('✅ Test dependencies installed')"
```

---

## Running Tests After Setup

### Quick Test (Single Test)

```bash
# Test if setup is working
pytest tests/routers/admin/test_users.py::test_get_all_users -v
```

**Expected output**:
```
tests/routers/admin/test_users.py::test_get_all_users PASSED [100%]
```

### Run All PHASE 2A Tests

```bash
# Using test runner script
./run_phase2a_tests.sh

# OR using pytest directly
pytest tests/routers/admin/ -v

# With coverage
./run_phase2a_tests.sh --coverage
```

---

## Common Issues & Fixes

### Issue 1: Virtual Environment Not Activated

**Symptom**:
```bash
bash: ./run_phase2a_tests.sh: Permission denied
```
OR dependencies not found even after `pip install`

**Fix**:
```bash
# Activate virtual environment
source venv/bin/activate

# You should see (venv) in your prompt
# (venv) user@machine:~/QLTS/Backend_FastAPI$

# Make script executable
chmod +x run_phase2a_tests.sh
```

---

### Issue 2: Database Connection Error

**Symptom**:
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Fix**:
```bash
# Ensure APP_ENV is set to 'test' (conftest.py should do this)
export APP_ENV=test

# Check if PostgreSQL test database is accessible
# In .env or test config, DATABASE_URL should point to test DB
```

---

### Issue 3: ForeignKey Constraint Error (FIXED)

**Symptom**:
```
sqlalchemy.exc.CompileError: Can't emit DROP CONSTRAINT for constraint ForeignKeyConstraint(...); it has no name
```

**Status**: ✅ **FIXED in commit af733ef**

The fix added explicit constraint name to `User.current_assignment_id`:
```python
ForeignKey(
    "user_unit_assignment.id",
    name="fk_user_current_assignment",  # ✅ Explicit name added
    ondelete="SET NULL",
    use_alter=True
)
```

**If you still see this error**:
```bash
# Pull latest changes
git pull origin claude/refactoring-execution-plan-015j9PAMoSNW4qbrVgJhnpUc

# Verify fix is applied
grep "fk_user_current_assignment" app/models/user.py
# Should return: name="fk_user_current_assignment",
```

---

### Issue 4: Casbin Enforcer Errors

**Symptom**:
```
AttributeError: 'State' object has no attribute 'enforcer'
```

**Fix**:
This is normal in test environment. The tests use mock enforcer from `conftest.py`.

**Verify conftest setup**:
```bash
# Check if conftest has Casbin setup
grep -A5 "enforcer" tests/conftest.py | head -20
```

---

### Issue 5: Tests Pass But Some Fail

**Symptom**:
Some tests pass but others fail randomly.

**Possible causes**:
1. Database state not cleaned between tests
2. Shared fixtures causing side effects
3. Race conditions

**Fix**:
```bash
# Run tests with verbose output to see which test fails
pytest tests/routers/admin/ -vv

# Run specific failing test in isolation
pytest tests/routers/admin/test_users.py::test_create_user_success -vv

# Check for database cleanup
# conftest.py should drop/create all tables per test
```

---

## Step-by-Step Testing Guide

### 1. Environment Setup

```bash
# 1. Navigate to project
cd /home/user/QLTS/Backend_FastAPI

# 2. Activate venv
source venv/bin/activate

# 3. Verify Python version (should be 3.12)
python --version

# 4. Install dependencies
pip install -r requirements.txt

# 5. Verify installation
python -c "import httpx, pytest, fakeredis; print('✅ All dependencies OK')"
```

### 2. Database Preparation

```bash
# Set test environment
export APP_ENV=test

# Verify database URL points to test DB (not production!)
# Check .env or .env.test file
grep DATABASE_URL .env.test
```

### 3. Run Tests

```bash
# Quick smoke test
pytest tests/routers/admin/test_users.py::test_get_all_users -v

# If smoke test passes, run all admin tests
pytest tests/routers/admin/ -v

# Expected: 48 passed in ~10-15 seconds
```

### 4. Review Results

**Successful run**:
```
================================ 48 passed in 12.34s ================================
```

**If failures occur**:
```bash
# Run with more verbosity
pytest tests/routers/admin/ -vv --tb=long

# Run specific test file
pytest tests/routers/admin/test_users.py -vv

# Run specific test
pytest tests/routers/admin/test_users.py::test_create_user_success -vv
```

---

## Debugging Failed Tests

### Get Detailed Error Information

```bash
# Full traceback
pytest tests/routers/admin/ -vv --tb=long

# Show local variables in traceback
pytest tests/routers/admin/ -vv --tb=long --showlocals

# Stop at first failure
pytest tests/routers/admin/ -x -vv
```

### Common Test Failures and Fixes

#### Authentication Failures (401)

**Symptom**: Tests return 401 Unauthorized

**Check**:
```python
# Verify admin_token_headers fixture is working
# In test, add debug print:
print(f"Headers: {admin_token_headers}")
```

**Fix**: Ensure `conftest.py` has proper token generation fixtures.

#### Permission Failures (403)

**Symptom**: Tests return 403 Forbidden

**Check**:
- Admin user has `role:admin` in Casbin
- Permissions are loaded in test enforcer

**Fix**: Verify Casbin enforcer initialization in `conftest.py`.

#### Database Errors

**Symptom**: IntegrityError, OperationalError

**Check**:
```bash
# Verify database is accessible
psql -U your_test_user -h 192.168.88.125 -d qlts_test -c "SELECT 1"
```

**Fix**: Ensure test database exists and is accessible.

---

## Performance Optimization

### Slow Tests (>60 seconds)

If tests take longer than expected:

```bash
# Run tests in parallel (requires pytest-xdist)
pip install pytest-xdist
pytest tests/routers/admin/ -n auto

# Run only fast tests (skip slow markers)
pytest tests/routers/admin/ -m "not slow"
```

### Reduce Test Output

```bash
# Minimal output
pytest tests/routers/admin/ -q

# Only show failures
pytest tests/routers/admin/ --tb=short -q
```

---

## Coverage Reports

### Generate HTML Coverage Report

```bash
# Run tests with coverage
./run_phase2a_tests.sh --coverage

# OR
pytest tests/routers/admin/ --cov=app/routers/admin --cov-report=html

# Open report
xdg-open htmlcov/index.html  # Linux
open htmlcov/index.html      # macOS
```

### Coverage Thresholds

**Target**: >80% line coverage for critical paths

**Check coverage**:
```bash
pytest tests/routers/admin/ --cov=app/routers/admin --cov-report=term-missing
```

---

## Success Criteria

### All Tests Should Pass

```bash
$ ./run_phase2a_tests.sh

========================================
PHASE 2A: Running Automated Tests
========================================

Checking dependencies...
Running tests: tests/routers/admin/

...

========================================
✅ All PHASE 2A tests passed!
========================================
```

### Expected Metrics

- **Total tests**: 48
- **Pass rate**: 100%
- **Execution time**: ~10-15 seconds
- **Coverage**: >80% for app/routers/admin/

---

## Next Steps After Tests Pass

1. **Commit any local changes**:
   ```bash
   git status
   git add .
   git commit -m "test: Verify PHASE 2A tests pass locally"
   ```

2. **Push to remote**:
   ```bash
   git push
   ```

3. **Setup CI/CD** (optional):
   Add to `.github/workflows/test.yml`:
   ```yaml
   - name: Run PHASE 2A Tests
     run: |
       cd Backend_FastAPI
       pip install -r requirements.txt
       pytest tests/routers/admin/ -v
   ```

4. **Proceed to PHASE 2B**:
   - Extract `organization.py` (12 endpoints)
   - Extract `config.py` (20 endpoints)
   - Follow same testing approach

---

## Support & Documentation

**Full testing guide**: `PHASE2A_AUTOMATED_TESTING.md`

**Test files**:
- `tests/routers/admin/test_users.py` - 21 tests
- `tests/routers/admin/test_roles.py` - 27 tests

**Related documentation**:
- `PHASE2A_COMPLETION_SUMMARY.md` - What was built
- `PHASE2A_TESTING_GUIDE.md` - Manual testing guide (if needed)

**Recent fixes**:
- Commit `af733ef`: Fixed ForeignKey constraint name issue

---

## Summary

### Before Running Tests

✅ Virtual environment activated
✅ Dependencies installed (`pip install -r requirements.txt`)
✅ APP_ENV=test
✅ Test database accessible
✅ Latest code pulled (includes constraint fix)

### Run Tests

```bash
./run_phase2a_tests.sh --coverage
```

### Expected Result

48/48 tests pass ✅ in ~10-15 seconds

**If tests fail**: Check this guide for troubleshooting steps!
