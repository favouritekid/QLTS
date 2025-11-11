# Testing Guide for 3-Tier Architecture Refactoring

## 📋 Prerequisites

Before running tests, ensure you have:

1. ✅ **Database migrated** to Phase 2
   ```bash
   cd /home/user/QLTS/Backend_FastAPI
   alembic upgrade head
   ```

2. ✅ **Required Python packages** installed
   ```bash
   pip install httpx  # For API testing
   ```

## 🚀 Quick Start

### Step 1: Seed Sample Data

Run the data seeding script to populate your database with test data:

```bash
cd /home/user/QLTS/Backend_FastAPI
python seed_sample_data.py
```

**What it creates:**
- 3 Major Programs (Level 1): Công nghệ Thông tin, Quản trị Kinh doanh, Kế toán
- 6 Program Offerings (Level 2): Various offering types (Chính quy, Liên thông, Từ xa)
- 12 Academic Info records (Level 3): For current year and next year
- 3 Sample Leads: With different offering assignments

**Expected output:**
```
============================================================================
SUMMARY
============================================================================
✅ Programs (Level 1):              3
✅ Offerings (Level 2):             6
✅ Academic Info (Level 3):         12
✅ Sample Leads:                    3
```

### Step 2: Start Backend Server

In a **separate terminal**, start the FastAPI server:

```bash
cd /home/user/QLTS/Backend_FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Wait until you see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

### Step 3: Run API Tests

In your **original terminal**, run the comprehensive test suite:

```bash
python test_phase4_api.py
```

## 📊 Test Coverage

The test script covers:

### ✅ Test Suite 1: Organization Endpoints
- GET `/api/organization-units` - Verify 3-tier tree structure
- GET `/api/organization-units/tree-with-aggregation` - Verify aggregation stats
- GET `/api/programs?unitId=X` - Verify program filtering

### ✅ Test Suite 2: Program Offering Endpoints (Level 2)
- GET `/api/programs/{program_id}/offerings` - List offerings for a program
- Verify offering structure (offering_type, program_id, etc.)

### ✅ Test Suite 3: Academic Info Endpoints (Level 3)
- GET `/api/offerings/{offering_id}/academic-info` - Get academic history
- GET `/api/offerings/{offering_id}/academic-info/{year}` - Get by specific year
- GET `/api/offerings/{offering_id}/academic-info/current` - Get current published info
- Verify academic info structure (year, tuition, quota, admission_criteria)

### ✅ Test Suite 4: Lead Endpoints
- GET `/api/leads` - Paginated lead list
- GET `/api/leads?offering_id=X` - Filter leads by offering
- GET `/api/leads/{lead_id}` - Lead detail view
- Verify leads have `offering` field (NOT `major`)

### ✅ Test Suite 5: Deprecated Endpoints
- Verify `/api/majors` returns 404 (removed)
- Verify `/api/majors/{id}/academic-info` returns 404 (removed)

## 📈 Expected Results

### ✅ Success (All Tests Pass)

```
============================================================================
TEST SUMMARY
============================================================================

Total Tests:   25+
Passed:        25+
Failed:        0
Pass Rate:     100.0%

============================================================================
✅ ALL TESTS PASSED!

The 3-tier architecture refactoring is working correctly.
You can proceed to Phase 5 (Frontend refactoring).
============================================================================
```

### ❌ Failure (Some Tests Fail)

If any tests fail, you'll see detailed error messages:

```
❌ FAIL - 1.1a Verify 'major_programs' field exists in unit
      Found: ['id', 'name', 'type', 'majors', 'children']
```

**Common issues:**
1. **Server not running**: Start uvicorn server first
2. **Database not migrated**: Run `alembic upgrade head`
3. **No sample data**: Run `python seed_sample_data.py`
4. **Port conflict**: Check if port 8000 is available

## 🔧 Manual Testing (Optional)

If you prefer manual testing with curl or a REST client:

### Test 3-Tier Hierarchy

```bash
# Get organization units with full 3-tier structure
curl http://localhost:8000/api/organization-units | jq

# Expected structure:
# {
#   "id": 1,
#   "name": "Unit Name",
#   "major_programs": [           # ← Level 1
#     {
#       "id": 1,
#       "name": "Program Name",
#       "code": "7480201",
#       "offerings": [              # ← Level 2
#         {
#           "id": 1,
#           "offering_type": "Chính quy",
#           "academic_info_history": [  # ← Level 3
#             {
#               "id": 1,
#               "academic_year": 2025,
#               "tuition_fee_per_year": 15000000
#             }
#           ]
#         }
#       ]
#     }
#   ]
# }
```

### Test Offerings

```bash
# Get offerings for program ID 1
curl http://localhost:8000/api/programs/1/offerings | jq

# Get current academic info for offering ID 1
curl http://localhost:8000/api/offerings/1/academic-info/current | jq
```

### Test Leads with offering_id

```bash
# Get all leads
curl http://localhost:8000/api/leads | jq

# Filter by offering_id
curl "http://localhost:8000/api/leads?offering_id=1" | jq
```

### Test Deprecated Endpoints (Should Return 404)

```bash
# Old endpoint - should return 404
curl -i http://localhost:8000/api/majors
# Expected: HTTP/1.1 404 Not Found

# Old endpoint - should return 404
curl -i http://localhost:8000/api/admin/majors
# Expected: HTTP/1.1 404 Not Found
```

## 🐛 Troubleshooting

### Database Connection Error

```
ERROR: could not connect to server: Connection refused
```

**Solution:** Start PostgreSQL:
```bash
sudo systemctl start postgresql
# or for Docker:
docker-compose up -d postgres
```

### ImportError: No module named 'httpx'

```
ModuleNotFoundError: No module named 'httpx'
```

**Solution:** Install httpx:
```bash
pip install httpx
```

### Server Already Running Error

```
ERROR:    [Errno 98] Address already in use
```

**Solution:** Kill existing process or use different port:
```bash
# Find process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use different port
uvicorn app.main:app --reload --port 8001
# Then update API_BASE_URL in test script
```

### No Sample Data

```
Test 1.1a Verify 'major_programs' field exists in unit
      Found: ['id', 'name', 'type', 'children']
```

**Solution:** Seed sample data:
```bash
python seed_sample_data.py
```

## 📝 Next Steps

After all tests pass:

1. ✅ **Review test results** - Make sure all 3-tier relationships work
2. ✅ **Test additional endpoints** - Try admin endpoints (requires authentication)
3. ✅ **Proceed to Phase 5** - Frontend refactoring for Next.js
4. ✅ **Update documentation** - Document new API endpoints for your team

## 🎯 Phase 5 Preview

Once backend testing is complete, you'll need to refactor:

**Frontend (Next.js):**
- `types/organization.types.ts` - Update types for 3-tier
- `hooks/useOrganization.ts` - Update API calls
- `components/admin/organization/MajorListTab.tsx` - 3-level tree UI
- `AcademicInfoManagement.tsx` - Support for offerings
- Create `ProgramOfferingDialog.tsx` - New component

**API Changes Summary:**
```diff
- GET /api/majors
+ GET /api/programs

- GET /api/majors/{major_id}/academic-info
+ GET /api/programs/{program_id}/offerings
+ GET /api/offerings/{offering_id}/academic-info
+ GET /api/offerings/{offering_id}/academic-info/current

- major_id in Lead
+ offering_id in Lead
```

---

**Happy Testing! 🚀**
