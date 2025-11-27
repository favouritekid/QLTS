# Notification System Migration - Deployment Guide

## Overview

This guide covers deploying and testing the notification system migration from hardcoded rules to database-driven visual management.

## What's Been Implemented

### Phase 1: Performance & Monitoring ✅
- **1.1 Thundering Herd Protection**: Rate limiting, exponential backoff, staggered reconnection
- **1.2 Redis Memory Management**: Inbox caching (100 items, 7-day TTL), cache-first pattern
- **1.3 Monitoring**: Metrics endpoint, structured logging with structlog

### Phase 2: Visual Notification Management ✅
- **2.1 Database Schema**: `notification_rule` table with migration and model
- **2.2 Backend API**: 6 CRUD endpoints (list, get, create, update, toggle, delete)
- **2.3 Backend Logic**: Resolver deserializer, condition evaluator, database integration
- **2.4 Frontend UI**: React Query hooks, NotificationRuleForm, NotificationRuleList, admin page

---

## Deployment Steps

### Step 1: Run Database Migration

```bash
cd Backend_FastAPI

# Run Alembic migration to create notification_rule table
alembic upgrade head
```

**Expected Output:**
```
INFO  [alembic.runtime.migration] Running upgrade xxxx -> k6l7m8n9o0p1, add notification_rule table
```

**Verify Migration:**
```sql
-- Connect to your database and run:
SELECT * FROM alembic_version;
-- Should show: k6l7m8n9o0p1

-- Check table exists:
\d notification_rule
-- Should show all columns: id, event, title_template, message_template, etc.
```

---

### Step 2: Seed Notification Rules

The seed script populates the database with default notification rules from the existing hardcoded registry.

```bash
cd Backend_FastAPI

# Run seed script
python -m app.scripts.seed_notification_rules
```

**Expected Output:**
```
INFO     Seeding notification rules from hardcoded registry...
INFO     ✅ Created rule: lead_assigned
INFO     ✅ Created rule: lead_assignment_failed
INFO     ✅ Created rule: consultation_reminder
...
INFO     ✅ Seeded 15 notification rules successfully!
```

**Verify Seeding:**
```sql
-- Count rules
SELECT COUNT(*) FROM notification_rule;
-- Should return: 15 (or number of events in your registry)

-- View some rules
SELECT id, event, notification_type, enabled, channels
FROM notification_rule
LIMIT 5;
```

---

### Step 3: Restart Backend Server

```bash
cd Backend_FastAPI

# Stop existing server (Ctrl+C if running)

# Start with uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Verify Backend:**
- Navigate to: `http://localhost:8000/docs`
- Check for `/api/notification-rules` endpoints in Swagger UI
- Try GET `/api/notification-rules` (requires admin authentication)

---

### Step 4: Start Frontend

```bash
cd frontend

# Install dependencies (if not already done)
npm install

# Start development server
npm run dev
```

**Verify Frontend:**
- Navigate to: `http://localhost:3000`
- Login as admin user
- Go to: `http://localhost:3000/admin/notification-rules`

---

## Testing the Features

### Test 1: View Notification Rules

1. Login as **admin** user
2. Navigate to **Admin → Notification Rules** (or `/admin/notification-rules`)
3. **Expected**: See table with all seeded notification rules
4. **Verify**:
   - Total count matches seeded rules
   - All columns display correctly (Event, Title, Type, Channels, Resolver)
   - Color-coded badges for notification types

### Test 2: Toggle Enable/Disable

1. Find any rule (e.g., "Lead Assigned")
2. Click the **toggle switch** to disable
3. **Expected**:
   - Optimistic update (instant UI change)
   - Success toast: "Rule 'lead_assigned' disabled"
   - Toggle switch shows disabled state
4. Toggle again to re-enable
5. **Verify**:
   - Rule status persists after page refresh
   - Check database: `SELECT enabled FROM notification_rule WHERE event = 'lead_assigned';`

### Test 3: Create New Rule

1. Click **"Create Rule"** button
2. Fill in form:
   - **Event**: `system_alert`
   - **Title Template**: `System Alert: $severity`
   - **Message Template**: `$message`
   - **Notification Type**: `warning`
   - **Link Template**: `/admin/monitoring` (optional)
   - **Channels**: Check `browser` and `email`
   - **Recipient Resolver**: Select `all_admins`
   - **Condition**: Enable and set:
     - Field: `severity`
     - Operator: `eq`
     - Value: `critical`
   - **Enabled**: Toggle ON
3. Click **"Create Rule"**
4. **Expected**:
   - Success toast: "Notification rule created successfully"
   - Dialog closes
   - New rule appears in table
5. **Verify**:
   - Check database: `SELECT * FROM notification_rule WHERE event = 'system_alert';`
   - Verify `recipient_config` JSON: `{"resolver_type": "all_admins", "params": {}}`
   - Verify `condition` JSON: `{"field": "severity", "operator": "eq", "value": "critical"}`

### Test 4: Edit Existing Rule

1. Find any rule and click **Edit icon** (pencil)
2. Modify fields (e.g., change title template)
3. Click **"Update Rule"**
4. **Expected**:
   - Success toast: "Notification rule updated successfully"
   - Changes reflected in table
5. **Verify**: Database reflects changes

### Test 5: Delete Rule

1. Find any non-critical rule and click **Delete icon** (trash)
2. Confirm deletion in dialog
3. **Expected**:
   - Success toast: "Rule deleted successfully"
   - Rule removed from table
4. **Verify**: `SELECT * FROM notification_rule WHERE id = X;` returns no rows

### Test 6: End-to-End Notification Flow

1. Create a test event (e.g., assign a lead to an officer)
2. **Verify notification system**:
   - Check backend logs for:
     ```
     INFO     Loaded notification rule from database
              rule_id=1 event=lead_assigned channels=['browser', 'email']
     ```
   - Check user receives notification:
     - Browser notification in UI
     - Database: `SELECT * FROM notification WHERE user_id = X ORDER BY created_at DESC LIMIT 1;`
3. **Test condition-based rules**:
   - Create rule with condition (e.g., `amount > 1000`)
   - Trigger event with `amount = 500` → No notification
   - Trigger event with `amount = 1500` → Notification sent

---

## Monitoring & Debugging

### Backend Logs (Structured Logging)

Look for structured log entries:

```json
{
  "event": "notification_dispatched",
  "notification_id": 123,
  "user_id": 45,
  "event": "lead_assigned",
  "rule_source": "database",
  "channels": ["browser", "email"],
  "resolver_type": "lead_owner",
  "timestamp": "2025-11-27T10:30:00Z"
}
```

### Notification Metrics Endpoint

```bash
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/api/monitoring/notifications/metrics
```

**Expected Response:**
```json
{
  "total_notifications": {
    "all_time": 1523,
    "last_24h": 42,
    "last_7d": 189,
    "last_30d": 678
  },
  "by_type": {
    "info": 890,
    "success": 412,
    "warning": 187,
    "error": 34
  },
  "by_status": {
    "read": 1102,
    "unread": 421
  },
  "cache_performance": {
    "hit_rate": 0.87,
    "total_inbox_keys": 156,
    "avg_items_per_inbox": 23.4
  },
  "top_recipients": [
    {"user_id": 12, "count": 89},
    {"user_id": 34, "count": 67}
  ]
}
```

### Database Queries for Troubleshooting

```sql
-- Check which rules are enabled
SELECT event, enabled, channels
FROM notification_rule
WHERE enabled = true;

-- Check recent notifications
SELECT id, user_id, type, title, created_at
FROM notification
ORDER BY created_at DESC
LIMIT 10;

-- Check notification rule with complex resolver
SELECT event, recipient_config
FROM notification_rule
WHERE recipient_config->>'resolver_type' = 'composite';

-- Check rules with conditions
SELECT event, condition
FROM notification_rule
WHERE condition IS NOT NULL;
```

---

## Rollback Plan

If issues occur, you can rollback:

### 1. Disable Database Rules (Fallback to Hardcoded Registry)

The system is designed with fallback support. If database rules fail to load, it automatically falls back to the hardcoded registry in `notification_registry.py`.

**Verify Fallback:**
```python
# In Backend_FastAPI/app/services/notification_dispatcher.py
# Lines 41-46 show the fallback logic:

config = await get_rule_for_event(db, event)  # Try database first
if not config:
    config = get_event_config(event)  # Fallback to registry
```

### 2. Disable All Database Rules Temporarily

```sql
-- Disable all database rules
UPDATE notification_rule SET enabled = false;
```

This forces all notifications to use the hardcoded registry.

### 3. Rollback Migration (Last Resort)

```bash
cd Backend_FastAPI

# Rollback to previous migration
alembic downgrade -1

# This will drop the notification_rule table
```

**⚠️ Warning**: This deletes all notification rules from database!

---

## Performance Considerations

### Redis Cache Monitoring

```bash
# Connect to Redis
redis-cli

# Check notification inbox cache
KEYS notification:inbox:*

# Check specific user's inbox
LRANGE notification:inbox:123 0 -1

# Check cache TTL
TTL notification:inbox:123

# Cache statistics
INFO stats
```

### Rate Limiting

Notification endpoints are rate-limited:
- **GET /api/notifications**: 60 requests/minute (production), 10000/minute (test)

**Test Rate Limit:**
```bash
# Send rapid requests
for i in {1..70}; do
  curl -H "Authorization: Bearer TOKEN" http://localhost:8000/api/notifications
done
```

Expected: 429 Too Many Requests after 60 requests

---

## Common Issues & Solutions

### Issue 1: "Rule already exists" error when creating

**Cause**: Each event can only have ONE rule in the database.

**Solution**:
- Edit existing rule instead of creating new one
- Or delete existing rule first

### Issue 2: Notification not sent

**Debug Checklist:**
1. Check rule is enabled: `SELECT enabled FROM notification_rule WHERE event = 'XXX';`
2. Check condition evaluation (if applicable)
3. Check resolver logs in backend
4. Check notification created in database: `SELECT * FROM notification ORDER BY created_at DESC;`
5. Check WebSocket connection for real-time delivery

### Issue 3: Form validation errors

**Common causes:**
- Missing required fields (event, title, message)
- No channels selected
- Invalid resolver configuration

### Issue 4: Migration fails

**Solution:**
```bash
# Check current migration version
alembic current

# Check migration history
alembic history

# Force stamp to specific version
alembic stamp head
```

---

## Next Steps (Optional Enhancements)

### Phase 3: Advanced Features (Not Yet Implemented)

1. **Template Management UI**
   - Template variables autocomplete
   - Template preview with sample data
   - Validation before saving

2. **Visual Condition Builder**
   - Drag-and-drop condition building
   - Multiple conditions with AND/OR logic
   - Condition testing against sample payloads

3. **Analytics Dashboard**
   - Notification delivery success rates
   - User engagement metrics (read rates, click-through)
   - Rule performance comparison

4. **Rule Versioning**
   - Track rule changes over time
   - Rollback to previous versions
   - Audit log of rule modifications

---

## Support

For issues or questions:
1. Check backend logs: `tail -f backend.log`
2. Check structured logs for notification events
3. Query database for notification_rule and notification tables
4. Review Swagger UI at `/docs` for API documentation

---

## Summary Checklist

- [ ] Database migration completed (`alembic upgrade head`)
- [ ] Notification rules seeded (`python -m app.scripts.seed_notification_rules`)
- [ ] Backend server restarted
- [ ] Frontend running and accessible
- [ ] Admin page loads at `/admin/notification-rules`
- [ ] Can view existing rules
- [ ] Can toggle enable/disable
- [ ] Can create new rule
- [ ] Can edit existing rule
- [ ] Can delete rule
- [ ] End-to-end notification flow works
- [ ] Metrics endpoint returns data
- [ ] Structured logging visible in backend logs

**Congratulations!** The notification system migration is complete! 🎉
