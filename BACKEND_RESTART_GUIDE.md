# 🔄 Backend Restart Guide - Fix Enum Error

## 🐛 Problem
Error: `invalid input value for enum outcome_type_enum: "NEUTRAL"`

This error occurs because:
1. Backend code has been updated with enum fixes
2. Backend server is still running OLD code
3. **Server needs to restart** to load new code

---

## ✅ Solution: Restart Backend

### Option 1: Docker Compose (Recommended)

```bash
# Navigate to backend directory
cd /home/user/QLTS/Backend_FastAPI

# Restart backend service
docker-compose restart backend

# OR rebuild and restart (if code changes significant)
docker-compose up -d --build backend

# Check logs to verify restart
docker-compose logs -f backend
```

### Option 2: Manual Python Process

```bash
# Find and kill existing backend process
pkill -f "uvicorn.*main:app"

# OR find PID manually
ps aux | grep "uvicorn.*main"
# Then kill: kill -9 <PID>

# Start backend again
cd /home/user/QLTS/Backend_FastAPI
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Option 3: Systemd Service (if configured)

```bash
sudo systemctl restart qlts-backend
# OR
sudo systemctl restart fastapi

# Check status
sudo systemctl status qlts-backend
```

### Option 4: PM2 (if using PM2)

```bash
pm2 restart qlts-backend
# OR
pm2 restart all

# Check logs
pm2 logs qlts-backend
```

---

## 🔍 Verify Backend is Running with New Code

After restart, check logs for debug messages:

```bash
# Docker logs
docker-compose logs -f backend | grep -i "outcome_type"

# OR manual logs
tail -f /var/log/qlts-backend.log | grep -i "outcome_type"
```

You should see debug logs like:
```
[debug] Converting outcome_type original_value=NEUTRAL original_type=OutcomeTypeEnum
[debug] Converted outcome_type converted_value=neutral
```

---

## 🧪 Test the Fix

### 1. Test with curl:

```bash
curl -X POST http://localhost:8000/api/admin/consultation-statuses \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test_status_001",
    "name": "Test Status",
    "color_code": "#3B82F6",
    "stage_id": "stg01",
    "outcome_type": "neutral",
    "is_final_status": false
  }'
```

Expected response: HTTP 200 with created status (NOT 500 error)

### 2. Test from Frontend:

1. Open http://localhost:3000/admin/pipeline
2. Go to "Consultation Statuses" tab
3. Click "Add Status"
4. Fill in form:
   - ID: test_002
   - Name: Test Status 2
   - Color: Any color
   - Stage: Select any stage
   - Outcome Type: Neutral
   - Final Status: Unchecked
5. Click "Create"

Expected: Success toast, no CORS error, no 500 error

---

## 🚨 Troubleshooting

### Issue: CORS Error
```
Access to XMLHttpRequest blocked by CORS policy
```

**Solution:** Backend not running or running on wrong port
```bash
# Check if port 8000 is listening
lsof -i :8000
netstat -tulpn | grep 8000

# Restart backend and ensure it binds to 0.0.0.0:8000
```

### Issue: Still getting "NEUTRAL" error

**Check 1:** Verify code is actually updated
```bash
cd /home/user/QLTS/Backend_FastAPI
git log --oneline -1
# Should show: "fix: Add comprehensive enum handling..."

cat app/services/pipeline_service.py | grep -A 20 "CRITICAL FIX"
# Should show the new conversion logic
```

**Check 2:** Backend is using old code cache
```bash
# Clear Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete

# Then restart backend
```

**Check 3:** Wrong Python environment
```bash
# Check which Python is running
ps aux | grep uvicorn

# Should use venv Python, not system Python
# If wrong, activate correct venv:
source venv/bin/activate  # or your venv path
python -m uvicorn app.main:app --reload
```

---

## 📊 Expected Backend Logs After Fix

When you create a consultation status, you should see:

```
2025-11-15T06:00:00.000000Z [debug] Converting outcome_type
    original_value=OutcomeTypeEnum.NEUTRAL
    original_type=OutcomeTypeEnum

2025-11-15T06:00:00.000000Z [debug] Converted outcome_type
    converted_value=neutral

2025-11-15T06:00:00.000000Z [info] Created new consultation status, cache invalidated
    status_id=test_002
```

**NO MORE:**
```
[error] invalid input value for enum outcome_type_enum: "NEUTRAL"
```

---

## 🎯 Quick Checklist

- [ ] Git pull latest code (commit: 4721d0a)
- [ ] Restart backend service
- [ ] Check backend logs (no errors on startup)
- [ ] Test curl request (returns 200)
- [ ] Test frontend form (no CORS/500 errors)
- [ ] Verify debug logs show lowercase conversion
- [ ] Create actual consultation status successfully

---

## 🔗 Related Commits

- `4721d0a` - fix: Add comprehensive enum handling with debug logging
- `d9958a4` - fix: Enforce lowercase enum values for outcome_type
- `fa0b140` - fix: Critical fixes and enhancements for Transition Matrix

---

**Last Updated:** 2025-11-15
**Status:** ✅ Fix committed, pending backend restart
