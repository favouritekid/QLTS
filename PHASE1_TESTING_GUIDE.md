# 🧪 PHASE 1 - TESTING GUIDE
## Custom Exception System Verification

**Branch:** `claude/phase1-exceptions-015egCFQ21Xe8128c7oMVHby`
**Commit:** `d1ee87d` - feat(exceptions): Implement comprehensive custom exception system

---

## ✅ Pre-requisites

Ensure you have the following installed:
- Python 3.11+
- Virtual environment activated
- All dependencies installed

```bash
cd Backend_FastAPI
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 🔍 Test Plan

### **Step 1: Verify Exception Module Imports**

Test that the new exception module loads without errors:

```bash
cd Backend_FastAPI
python -c "from app.utils.exceptions import *; print('✅ Exception module loaded successfully')"
```

**Expected Output:**
```
✅ Exception module loaded successfully
```

If you see any import errors, check:
- FastAPI is installed: `pip list | grep fastapi`
- All dependencies are up to date: `pip install -r requirements.txt --upgrade`

---

### **Step 2: Run Exception Unit Tests**

Run the comprehensive exception test suite:

```bash
cd Backend_FastAPI
pytest tests/utils/test_exceptions.py -v --tb=short
```

**Expected Output:**
```
tests/utils/test_exceptions.py::TestBaseAppException::test_default_values PASSED
tests/utils/test_exceptions.py::TestBaseAppException::test_custom_detail PASSED
tests/utils/test_exceptions.py::TestBaseAppException::test_with_context PASSED
...
tests/utils/test_exceptions.py::TestExceptionIntegration::test_exception_chaining PASSED

======================== 35+ passed in 0.XX s ========================
```

**If tests fail:**
- Check the error message carefully
- Verify Python version: `python --version` (should be 3.11+)
- Ensure pytest is installed: `pip install pytest`

---

### **Step 3: Verify Middleware Integration**

Test that exception handlers register correctly:

```bash
cd Backend_FastAPI
python -c "
from fastapi import FastAPI
from app.middleware import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
print(f'✅ Registered {len(app.exception_handlers)} exception handlers')
"
```

**Expected Output:**
```
INFO [app.middleware.exception_handlers]: ✅ Exception handlers registered successfully
✅ Registered 20+ exception handlers
```

---

### **Step 4: Test Exception Handler Responses**

Create a temporary test file to verify HTTP responses:

```bash
cd Backend_FastAPI
cat > test_exception_responses.py << 'EOF'
"""Temporary test to verify exception handler responses"""
import asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.middleware import register_exception_handlers
from app.utils.exceptions import (
    UserNotFoundError,
    ValidationError,
    CacheServiceError
)

app = FastAPI()
register_exception_handlers(app)

@app.get("/test-404")
async def test_404():
    raise UserNotFoundError("User 123 not found")

@app.get("/test-400")
async def test_400():
    raise ValidationError("Invalid email format")

@app.get("/test-500")
async def test_500():
    raise CacheServiceError("Redis connection failed")

client = TestClient(app)

def test_user_not_found():
    response = client.get("/test-404")
    assert response.status_code == 404
    data = response.json()
    assert data["error_code"] == "USER_NOT_FOUND"
    assert "User 123" in data["detail"]
    print("✅ 404 UserNotFoundError: OK")

def test_validation_error():
    response = client.get("/test-400")
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    print("✅ 400 ValidationError: OK")

def test_cache_service_error():
    response = client.get("/test-500")
    assert response.status_code == 500
    data = response.json()
    assert data["error_code"] == "CACHE_ERROR"
    print("✅ 500 CacheServiceError: OK")

if __name__ == "__main__":
    test_user_not_found()
    test_validation_error()
    test_cache_service_error()
    print("\n🎉 All exception handler tests passed!")
EOF

python test_exception_responses.py
rm test_exception_responses.py  # Cleanup
```

**Expected Output:**
```
✅ 404 UserNotFoundError: OK
✅ 400 ValidationError: OK
✅ 500 CacheServiceError: OK

🎉 All exception handler tests passed!
```

---

### **Step 5: Test Application Startup**

Verify the application starts without errors:

```bash
cd Backend_FastAPI

# Quick startup test (will fail if config missing, but that's OK)
python -c "
import sys
sys.path.insert(0, '.')
try:
    from app.main import app
    print('✅ Application imports successfully')
    print(f'✅ App title: {app.title}')
    print(f'✅ Exception handlers registered: {len(app.exception_handlers)}')
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
"
```

**Expected Output:**
```
INFO [app.main]: ✅ Custom exception handlers registered
✅ Application imports successfully
✅ App title: QLTS Project API with FastAPI
✅ Exception handlers registered: 20+
```

**Note:** You may see database/Redis connection errors - that's OK for this test. We're only checking that the exception system loads.

---

### **Step 6: Run Full Test Suite (Optional)**

Run all existing tests to ensure backward compatibility:

```bash
cd Backend_FastAPI
pytest tests/ -v --tb=short -k "not test_" --collect-only
# This will show all test files

# Run specific test modules
pytest tests/routers/test_auth_api.py -v
pytest tests/services/test_user_service.py -v
```

**Expected:** All existing tests should still pass (exception handlers are backward compatible)

---

## 🐛 Troubleshooting

### **Issue: ModuleNotFoundError: No module named 'fastapi'**

**Solution:**
```bash
pip install fastapi
# Or reinstall all dependencies
pip install -r requirements.txt
```

---

### **Issue: ImportError in app.middleware**

**Solution:**
Check that the `__init__.py` file exists:
```bash
ls -la Backend_FastAPI/app/middleware/
# Should show: __init__.py and exception_handlers.py
```

If missing, the files may not have been committed. Re-checkout the branch:
```bash
git checkout claude/phase1-exceptions-015egCFQ21Xe8128c7oMVHby
git pull origin claude/phase1-exceptions-015egCFQ21Xe8128c7oMVHby
```

---

### **Issue: Tests fail with "context" attribute errors**

**Solution:**
The custom exceptions have been updated. Ensure you're on the correct branch:
```bash
git status
git log --oneline -1
# Should show: d1ee87d feat(exceptions): Implement comprehensive custom exception system
```

---

## ✅ Success Criteria

All tests **MUST PASS** before proceeding to TASK 1.3:

- [ ] Exception module imports without errors
- [ ] All 35+ unit tests pass
- [ ] Exception handlers register successfully (20+ handlers)
- [ ] HTTP responses have correct status codes and error_codes
- [ ] Application starts without import errors
- [ ] Existing tests still pass (backward compatibility)

---

## 📊 Test Results Template

Copy this and fill in your results:

```
=== PHASE 1 EXCEPTION SYSTEM TEST RESULTS ===

Date: ___________
Tester: ___________
Branch: claude/phase1-exceptions-015egCFQ21Xe8128c7oMVHby
Commit: d1ee87d

[ ] Step 1: Exception module imports         PASS / FAIL
[ ] Step 2: Unit tests (35+ tests)           PASS / FAIL
[ ] Step 3: Middleware registration          PASS / FAIL
[ ] Step 4: Exception handler responses      PASS / FAIL
[ ] Step 5: Application startup              PASS / FAIL
[ ] Step 6: Existing tests (optional)        PASS / FAIL / SKIPPED

Notes:
_______________________________________________
_______________________________________________

Status: READY FOR TASK 1.3 / ISSUES FOUND
```

---

## 🚀 Next Steps

**If all tests PASS:**
✅ Proceed to **TASK 1.3: Refactor user_service.py**

```bash
git checkout claude/phase1-exceptions-015egCFQ21Xe8128c7oMVHby
# Ready for next task!
```

**If any tests FAIL:**
❌ Report issues and we'll fix them before continuing

---

## 📞 Need Help?

If you encounter any issues:

1. **Check the error message** - Most errors are self-explanatory
2. **Verify dependencies** - Run `pip list` and compare with requirements.txt
3. **Check Python version** - Run `python --version` (need 3.11+)
4. **Review the commit** - Ensure you're on the correct branch and commit
5. **Ask Claude** - Share the error output and I'll help debug

---

**Good luck with testing! 🎯**
