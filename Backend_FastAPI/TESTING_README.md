# Testing the 4-Phase DB/Casbin Sync Solution

## 📁 Test Files Overview

This directory contains comprehensive testing tools for the DB/Casbin synchronization system:

### 1. **`test_sync_solution.py`** - Automated Test Suite
   - **Purpose**: Fully automated integration testing
   - **Language**: Python (async/httpx)
   - **Features**:
     - Tests all 4 phases automatically
     - Rich console output with colors and tables
     - Detailed error reporting
     - Login automation

   **Usage**:
   ```bash
   # With credentials
   python test_sync_solution.py --username admin --password yourpass

   # With existing token
   python test_sync_solution.py --token YOUR_JWT_TOKEN
   ```

   **Dependencies**:
   ```bash
   pip install httpx rich
   ```

### 2. **`QUICK_TEST_COMMANDS.sh`** - Interactive Bash Functions
   - **Purpose**: Quick manual testing via shell functions
   - **Language**: Bash
   - **Features**:
     - Pre-built curl commands
     - Helper functions for common operations
     - Colored terminal output
     - Easy to use interactively

   **Usage**:
   ```bash
   # Load functions into your shell
   source QUICK_TEST_COMMANDS.sh

   # Login
   login admin mypassword

   # Run all tests
   run_all_tests

   # Quick operations
   sync_status
   sync_all
   sync_users 2 5 7
   ```

### 3. **`SYNC_SOLUTION_TEST_GUIDE.md`** - Complete Test Documentation
   - **Purpose**: Comprehensive testing manual
   - **Format**: Markdown documentation
   - **Contents**:
     - Step-by-step test procedures
     - curl command examples
     - Expected results
     - Success criteria
     - Troubleshooting guide
     - Frontend UI testing
     - Test scenarios and checklists

---

## 🚀 Quick Start

### Option 1: Automated (Fastest)

```bash
# Install dependencies
pip install httpx rich

# Run automated suite
python test_sync_solution.py --username admin --password yourpass
```

### Option 2: Interactive Shell

```bash
# Load helper functions
source QUICK_TEST_COMMANDS.sh

# Login
login admin yourpass

# Run tests
run_all_tests
```

### Option 3: Manual Testing

Follow the detailed guide in `SYNC_SOLUTION_TEST_GUIDE.md`

---

## 🧪 What Gets Tested

### ✅ Phase 1: Prevention
- Updates to `PUT /api/admin/users/{id}` sync both DB and Casbin
- No mismatches created by role updates
- Old Casbin roles are removed
- New Casbin roles are added
- Backend logs confirm sync

### ✅ Phase 2: Auto-Correction
- Login triggers auto-sync for mismatched users
- DB updates to match Casbin (source of truth)
- Users continue with correct roles
- No authentication failures
- Backend logs show auto-sync activity

### ✅ Phase 3: Detection
- `GET /sync-status` endpoint works
- Accurate mismatch detection
- Correct user counts
- Detailed mismatch information
- Multi-role users shown correctly

### ✅ Phase 4: Remediation
- `POST /sync` endpoint works
- Bulk sync functionality
- Selective user sync
- Activity logging
- UI dashboard displays correctly
- UI actions work properly

---

## 📊 Test Results Interpretation

### Expected Results (Clean System)

```json
{
  "total_users": 10,
  "synced_count": 10,
  "out_of_sync_count": 0,
  "mismatched_users": []
}
```

### Expected Results (After Intentional Mismatch)

```json
{
  "total_users": 10,
  "synced_count": 9,
  "out_of_sync_count": 1,
  "mismatched_users": [
    {
      "user_id": 5,
      "username": "test_user",
      "db_role": "user",
      "casbin_role": "manager",
      "all_casbin_roles": ["role:manager"]
    }
  ]
}
```

### Expected Results (After Manual Sync)

```json
{
  "synced_count": 1,
  "failed_count": 0,
  "failed_users": []
}
```

---

## 🐛 Common Issues

### "Backend not running"

**Solution**: Start backend server
```bash
cd /home/user/QLTS/Backend_FastAPI
uvicorn app.main:app --reload
```

### "Authentication failed"

**Solution**: Check credentials
```bash
# Verify admin user exists and password is correct
# Update login command with correct credentials
```

### "No mismatches to test"

**Solution**: This is actually good! It means the system is working.
- To test remediation, create an intentional mismatch via SQL:
  ```sql
  UPDATE users SET role = 'user' WHERE id = 5;
  ```

### "Permission denied"

**Solution**: Make sure you're using an admin token
```bash
# Verify role
curl -X GET "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq '.role'
```

---

## 📋 Test Checklist

Before considering testing complete:

- [ ] All 4 automated tests pass (Python script)
- [ ] Manual curl commands work
- [ ] Backend logs show sync operations
- [ ] Activity logs record sync actions
- [ ] Frontend UI displays correctly
- [ ] UI sync actions work
- [ ] No console errors in browser
- [ ] Mobile responsive layout works

---

## 🎯 Success Criteria

### Minimal Acceptance Criteria
- ✅ Phase 1 prevents new mismatches (100%)
- ✅ Phase 3 detects existing mismatches (100%)
- ✅ Phase 4 remediates mismatches (100%)

### Full Acceptance Criteria
- ✅ All 4 phases pass automated tests
- ✅ Manual testing confirms behavior
- ✅ UI works correctly
- ✅ Logs show expected messages
- ✅ No errors in backend or frontend
- ✅ Activity logging works
- ✅ Multi-role users handled correctly

---

## 📚 Additional Resources

- **Architecture**: See commit `d91c030` for implementation details
- **Code Review**: Check `user_service.py`, `admin.py`, `deps.py`
- **Frontend**: See `SyncDashboard.tsx` component
- **API Docs**: Visit `http://localhost:8000/docs` when server is running

---

## 💡 Tips

1. **Start Simple**: Begin with Phase 3 (Detection) to see current state
2. **Check Logs**: Always monitor backend logs during testing
3. **Use UI**: The dashboard provides the best visual feedback
4. **Test in Stages**: Don't test everything at once
5. **Keep Backups**: Test in dev/staging first

---

## 🔧 Customization

### Changing Base URL

Edit scripts to use different backend URL:

```bash
# In QUICK_TEST_COMMANDS.sh
BASE_URL="http://your-backend-url:8000"

# In test_sync_solution.py
BASE_URL = "http://your-backend-url:8000"
```

### Adding Custom Tests

Extend `test_sync_solution.py`:

```python
async def test_custom_scenario(self):
    """Your custom test"""
    # Your test code here
    pass
```

Add to `run_all_tests()`:
```python
results["custom"] = await self.test_custom_scenario()
```

---

## 📞 Support

If tests fail unexpectedly:

1. Check backend logs for detailed errors
2. Verify database connection
3. Verify Casbin adapter configuration
4. Check for conflicting policy rules
5. Review recent code changes

---

**Happy Testing! 🎉**

Last Updated: 2025-11-09
Version: 1.0.0
