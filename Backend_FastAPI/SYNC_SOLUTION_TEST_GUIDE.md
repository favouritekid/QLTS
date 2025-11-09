# 🧪 Test Guide: 4-Phase DB/Casbin Sync Solution

Complete testing guide for the DB/Casbin synchronization system.

---

## Prerequisites

1. **Backend Running**: `uvicorn app.main:app --reload` from `Backend_FastAPI/` directory
2. **Admin Access**: You need admin credentials to test
3. **Tools**: `curl`, `jq` (optional for pretty JSON), or use the Python test script

---

## Quick Start

### Option 1: Automated Testing (Recommended)

```bash
# Install dependencies (if needed)
pip install httpx rich

# Run automated test suite
python test_sync_solution.py --username admin --password your_password
```

### Option 2: Manual Testing with curl

Follow the tests below step by step.

---

## 🔐 Step 0: Get Access Token

```bash
# Login to get JWT token
TOKEN=$(curl -s -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=your_password" \
  | jq -r '.access_token')

echo "Token: $TOKEN"

# Use this token in all subsequent requests
```

---

## ✅ Phase 1: Prevention Test

**Goal**: Verify that `PUT /api/admin/users/{id}` syncs both DB and Casbin

### Test Steps:

```bash
# 1. Get list of users to find a test user
curl -X GET "http://localhost:8000/api/admin/users?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN" | jq '.users[0]'

# Note the user_id and current role
USER_ID=2  # Replace with actual user ID
ORIGINAL_ROLE="user"  # Replace with actual role

# 2. Update user role to 'manager'
curl -X PUT "http://localhost:8000/api/admin/users/$USER_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "role=manager"

# 3. Check sync status to verify no mismatch
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.mismatched_users[] | select(.user_id == '$USER_ID')'

# Expected: Empty result (no mismatch found)

# 4. Restore original role
curl -X PUT "http://localhost:8000/api/admin/users/$USER_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "role=$ORIGINAL_ROLE"
```

### ✅ Success Criteria:

- User role updated successfully
- No mismatch found in sync status
- Both DB and Casbin show the same role

### 📊 Check Backend Logs:

Look for these log entries:
```
Role changed in DB, syncing Casbin...
Casbin grouping policy synced successfully
```

---

## ✅ Phase 2: Auto-Correction Test

**Goal**: Verify that mismatches are auto-fixed during authentication

### Test Steps:

**Note**: This test requires manually creating a mismatch, which is difficult via API. Here's the conceptual approach:

1. **Create a mismatch** (requires direct Casbin/DB access):
   - Option A: Manually edit Casbin policy file
   - Option B: Use Casbin admin CLI to remove a grouping policy
   - Option C: Directly update DB `user.role` without updating Casbin

2. **Trigger auto-sync**:
   ```bash
   # Login as the user with mismatch
   curl -X POST "http://localhost:8000/api/auth/login" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=test_user&password=test_password"
   ```

3. **Check logs** for auto-sync:
   ```
   DB/Casbin role mismatch detected! Auto-syncing DB to Casbin.
   DB role auto-synced successfully
   ```

4. **Verify sync**:
   ```bash
   curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
     -H "Authorization: Bearer $TOKEN" | jq
   ```

### ✅ Success Criteria:

- Backend logs show mismatch detection
- Backend logs show successful auto-sync
- User can continue working with correct role
- No mismatch in final sync status

---

## ✅ Phase 3: Detection Test

**Goal**: Verify that `GET /api/admin/users/sync-status` correctly detects mismatches

### Test Steps:

```bash
# 1. Call sync status endpoint
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.'

# Expected response:
# {
#   "total_users": 10,
#   "synced_count": 9,
#   "out_of_sync_count": 1,
#   "mismatched_users": [
#     {
#       "user_id": 5,
#       "username": "john_doe",
#       "db_role": "user",
#       "casbin_role": "manager",
#       "all_casbin_roles": ["role:manager", "role:officer"]
#     }
#   ]
# }

# 2. Pretty print just the summary
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{total_users, synced_count, out_of_sync_count}'

# 3. List only mismatched users
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.mismatched_users[] | {user_id, username, db_role, casbin_role}'
```

### ✅ Success Criteria:

- Endpoint returns valid JSON
- Response contains all required fields
- Mismatch detection is accurate
- Multi-role users show all Casbin roles

---

## ✅ Phase 4: Remediation Test

**Goal**: Verify manual sync functionality via `POST /api/admin/users/sync`

### Test Steps:

```bash
# 1. Check current sync status
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{total_users, synced_count, out_of_sync_count}'

# 2a. Sync ALL users
curl -X POST "http://localhost:8000/api/admin/users/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": null}' \
  | jq '.'

# Expected response:
# {
#   "synced_count": 3,
#   "failed_count": 0,
#   "failed_users": []
# }

# OR

# 2b. Sync SPECIFIC users only
curl -X POST "http://localhost:8000/api/admin/users/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [2, 5, 7]}' \
  | jq '.'

# 3. Verify sync completed
curl -X GET "http://localhost:8000/api/admin/users/sync-status" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{total_users, synced_count, out_of_sync_count}'

# Expected: out_of_sync_count should be 0 or reduced
```

### ✅ Success Criteria:

- Sync operation completes successfully
- `synced_count` matches number of mismatched users
- `failed_count` is 0 (or known failures documented)
- Final sync status shows reduced/zero mismatches

### 📊 Check Backend Logs:

```
User role synced (user_id=5, old_role=user, new_role=manager)
User sync completed (synced=3, failed=0)
```

### 📊 Check Activity Log:

```bash
# Verify sync operation was logged
curl -X GET "http://localhost:8000/api/admin/activity-logs?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.items[] | select(.action == "sync_users")'
```

---

## 🎨 Frontend UI Testing

### Test the Sync Dashboard UI:

1. **Navigate to UI**:
   ```
   http://localhost:3000/admin/policies
   ```

2. **Click "Đồng bộ DB/Casbin" tab**

3. **Verify Dashboard Display**:
   - ✅ Shows total users count
   - ✅ Shows synced count (green)
   - ✅ Shows out-of-sync count (red)
   - ✅ Alert appears if mismatches found

4. **Test Mismatch Table**:
   - ✅ Lists all mismatched users
   - ✅ Shows DB role vs Casbin role
   - ✅ Shows all Casbin roles for multi-role users
   - ✅ Checkboxes work for selection

5. **Test Sync Actions**:
   - ✅ Select individual users → Click "Sync đã chọn"
   - ✅ Click "Sync tất cả" for bulk sync
   - ✅ Toast notification appears on success
   - ✅ Table refreshes after sync

6. **Test Edge Cases**:
   - ✅ No mismatches → Shows success alert
   - ✅ Refresh button updates data
   - ✅ Loading states display correctly

---

## 🧪 Creating Test Scenarios

### Scenario 1: Fresh System (No Mismatches)

**Setup**: Clean DB and Casbin
**Expected**: All phases pass, sync status shows 100% synced

### Scenario 2: Intentional Mismatch

**Setup**:
```sql
-- Manually update DB without touching Casbin
UPDATE users SET role = 'user' WHERE id = 5;
```

**Expected**:
- Phase 1: ✅ New updates sync correctly
- Phase 2: ✅ User #5 auto-syncs on next login
- Phase 3: ✅ Detects user #5 mismatch before login
- Phase 4: ✅ Manual sync fixes user #5

### Scenario 3: Multi-Role User

**Setup** (via Casbin admin):
```python
enforcer.add_grouping_policy("user:5", "role:manager")
enforcer.add_grouping_policy("user:5", "role:officer")
```

**Expected**:
- Sync status shows `casbin_role: "manager"` (highest priority)
- Shows `all_casbin_roles: ["role:manager", "role:officer"]`
- Sync operation picks highest priority role for DB

---

## 📋 Comprehensive Test Checklist

### Phase 1: Prevention
- [ ] Update role via PUT /users/{id}
- [ ] Verify DB updated
- [ ] Verify Casbin grouping policy added
- [ ] Verify old Casbin grouping removed
- [ ] Check backend logs for sync confirmation
- [ ] Verify no mismatch in sync status

### Phase 2: Auto-Correction
- [ ] Create manual mismatch
- [ ] Login as affected user
- [ ] Check logs for mismatch detection
- [ ] Check logs for auto-sync
- [ ] Verify DB updated to match Casbin
- [ ] Verify user continues with correct role

### Phase 3: Detection
- [ ] Call sync-status endpoint
- [ ] Verify response structure
- [ ] Verify counts are accurate
- [ ] Verify mismatch details are correct
- [ ] Test with zero mismatches
- [ ] Test with multiple mismatches

### Phase 4: Remediation
- [ ] Sync all users
- [ ] Verify sync count
- [ ] Verify no failed users
- [ ] Sync specific users only
- [ ] Verify selective sync works
- [ ] Check activity log entries
- [ ] Test UI dashboard
- [ ] Test UI checkboxes
- [ ] Test UI bulk actions

---

## 🐛 Troubleshooting

### Issue: "Permission denied" errors

**Solution**: Make sure you're using admin token:
```bash
# Verify token is valid and has admin role
curl -X GET "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq '.role'
```

### Issue: "No mismatches to test"

**Solution**: Create a test mismatch:
```sql
-- Connect to PostgreSQL
UPDATE users SET role = 'user' WHERE id = 5 LIMIT 1;
```

### Issue: Backend not responding

**Solution**: Check server status:
```bash
curl -X GET "http://localhost:8000/health"
```

### Issue: Casbin not loading policies

**Solution**: Check Casbin adapter connection and policy file permissions

---

## 📊 Success Metrics

After all tests pass, you should see:

1. **Phase 1**: 100% of role updates sync both systems
2. **Phase 2**: 100% of mismatches auto-fix on authentication
3. **Phase 3**: Accurate detection of all mismatches
4. **Phase 4**: Successful manual sync with 0 failures

**Overall Result**: A robust, defense-in-depth system that prevents, detects, and remediates DB/Casbin synchronization issues.

---

## 📝 Notes

- All tests should be run in a **development/staging** environment first
- Production testing should be done during maintenance windows
- Keep backups of both DB and Casbin policies before testing
- Monitor backend logs during all tests for detailed insights

---

## 🎯 Next Steps

After successful testing:

1. ✅ Deploy to staging environment
2. ✅ Run full test suite in staging
3. ✅ Monitor logs for any Phase 2 auto-sync triggers
4. ✅ Review Phase 3 detection results weekly
5. ✅ Use Phase 4 dashboard for proactive monitoring
6. ✅ Deploy to production with confidence

---

**Good luck with testing! 🚀**
