# Hybrid Notification System - Quick Start Guide

**Đọc trong 5 phút** | **Cho: Developers & Admins**

---

## 🎯 Tổng Quan Nhanh

### Trước Đây (Old System)
```python
# ❌ Hardcoded trong code - Phải sửa code mỗi lần thay đổi
SystemEvents.LEAD_ASSIGNED: NotificationConfig(
    resolver=LeadOwnerResolver(),  # Cố định
    template={"title": "New Lead"}, # Cố định
    channels=["browser", "email"]   # Cố định
)
```

### Bây Giờ (Hybrid System)
```javascript
// ✅ Quản lý qua UI - Không cần sửa code
Admin UI → Create Rule:
- Event: "lead_assigned"
- Recipients: [LeadOwner, UnitManagers, CEO nếu giá trị > 100k]
- Channels: [Browser, Email, SMS nếu urgent]
- Conditions: IF priority = "high" AND value > 100000
```

---

## 🏗️ Kiến Trúc 3 Tầng

```
┌─────────────────────────────────────────────────────┐
│  1. RULES ENGINE (Drupal-style)                    │
│     • Visual rule builder                          │
│     • Event-Condition-Action pattern               │
│     • Database-driven (không cần sửa code)        │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│  2. HOOK SYSTEM (WordPress-style)                  │
│     • Plugin-style extensibility                   │
│     • Custom filters cho recipients/content        │
│     • Không ảnh hưởng core code                   │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│  3. CHANNEL MANAGER (Laravel-style)                │
│     • Multi-channel (Browser, Email, SMS, Slack)   │
│     • User preferences (per-user, per-type)        │
│     • Quiet hours, digest mode, rate limiting      │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 Use Cases - Ví Dụ Thực Tế

### Use Case 1: Lead Cao Giá Trị Cần Thông Báo CEO

**Yêu cầu:** Khi có lead > $100k, thông báo cho CEO qua tất cả channels

**Giải pháp với Hybrid System:**

**Cách 1: Qua Admin UI (Không cần code)**
```
1. Vào Admin → Notifications → Rules
2. Click "Create Rule"
3. Điền form:
   - Name: "High Value Lead - Notify CEO"
   - Event: "lead_created"
   - Condition: estimated_value > 100000
   - Recipients: Specific Users → Select CEO
   - Channels: Browser + Email + SMS
   - Priority: High (force all channels)
4. Save
✅ Done! Không cần deploy code.
```

**Cách 2: Qua Code Hook (Cho trường hợp phức tạp)**
```python
# app/hooks/custom/ceo_notification.py
from app.services.notification_hooks import recipient_filter

@recipient_filter("lead_created", priority=20)
async def add_ceo_for_high_value(recipients, payload, db):
    if payload.get("estimated_value", 0) > 100000:
        ceo = await db.get(User, 1)  # CEO user_id
        if ceo.id not in recipients:
            recipients.append(ceo.id)
    return recipients
```

### Use Case 2: Tắt Thông Báo Cuối Tuần

**Yêu cầu:** Không gửi consultation reminder vào cuối tuần

**Giải pháp:**
```python
# app/hooks/custom/no_weekend_reminders.py
from app.services.notification_hooks import should_send_filter
from datetime import datetime

@should_send_filter("consultation_reminder", priority=10)
async def no_weekend_reminders(user, payload, db):
    # Return False = don't send
    return datetime.now().weekday() < 5  # Mon-Fri only
```

### Use Case 3: Thông Báo Khác Nhau Theo Unit

**Yêu cầu:** Unit 1 gửi cho team lead, Unit 2 gửi cho tất cả staff

**Giải pháp qua UI:**
```
Rule 1:
- Name: "Unit 1 - Lead Created"
- Event: "lead_created"
- Condition: unit_id = 1
- Recipients: Specific Users → [Team Lead ID]

Rule 2:
- Name: "Unit 2 - Lead Created"
- Event: "lead_created"
- Condition: unit_id = 2
- Recipients: UnitStaffResolver
```

---

## 📋 Checklist Triển Khai

### Tuần 1-3: Backend Core
- [ ] Tạo database schema (4 tables mới)
- [ ] Implement Rule Engine với condition evaluation
- [ ] Implement Recipient Resolver V2
- [ ] Migrate rules từ registry cũ vào DB

### Tuần 4: Hook System
- [ ] Implement Hook Registry
- [ ] Tạo 5+ example hooks
- [ ] Document hook development guide

### Tuần 5: Channel Manager
- [ ] Implement multi-channel routing
- [ ] Add SMS support (Twilio)
- [ ] Add Slack support (Webhook)
- [ ] Implement rate limiting

### Tuần 6-7: Admin UI
- [ ] Rule management page (CRUD)
- [ ] Visual condition builder
- [ ] Recipient configuration UI
- [ ] Analytics dashboard

### Tuần 8: Performance
- [ ] Redis caching (rules, recipients, preferences)
- [ ] Database indexing
- [ ] Load testing (1000+ notifications/sec)

### Tuần 9-11: Testing & Deployment
- [ ] Unit tests (>80% coverage)
- [ ] E2E tests
- [ ] Staging deployment
- [ ] Production deployment với feature flag

---

## 🎨 Admin UI Preview

### Rule Builder Interface
```
┌──────────────────────────────────────────────────────────┐
│  Create Notification Rule                         [Save] │
├──────────────────────────────────────────────────────────┤
│  Basic Info                                              │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Rule Name: [High Priority Lead - Notify CEO      ]  ││
│  │ Module: [Lead ▼]  Event: [lead_created ▼]          ││
│  │ Priority: [20] ━━━●────────────── (Higher = First) ││
│  │ ☑ Active  ☐ Stop on Match                          ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
│  Conditions (IF-THEN Logic)                             │
│  ┌─────────────────────────────────────────────────────┐│
│  │ [AND ▼] Logic                                       ││
│  │                                                     ││
│  │ [priority        ▼] [equals ▼] [high       ]  [-]  ││
│  │ [estimated_value ▼] [>      ▼] [100000     ]  [-]  ││
│  │                                          [+ Add]     ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
│  Recipients (WHO receives)                              │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Type: [Composite ▼]  Strategy: [Merge ▼]           ││
│  │                                                     ││
│  │ Resolvers:                                          ││
│  │ • LeadOwnerResolver                            [-]  ││
│  │ • UnitManagersResolver                         [-]  ││
│  │ • Specific Users: CEO, Sales Director          [-]  ││
│  │                                          [+ Add]     ││
│  │                                                     ││
│  │ Filters:                                            ││
│  │ ☑ Exclude actor  ☑ Only active users               ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
│  Channels (HOW to deliver)                              │
│  ┌─────────────────────────────────────────────────────┐│
│  │ ☑ Browser  ☑ Email  ☑ SMS  ☐ Slack                ││
│  │ Priority: [High ▼] (Force all channels)            ││
│  │ ☐ Respect quiet hours  ☐ Respect digest           ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
│  [Preview with Sample Data]  [Test Rule]  [Save]        │
└──────────────────────────────────────────────────────────┘
```

---

## 📊 Performance Targets

| Metric | Current | Target | How to Achieve |
|--------|---------|--------|----------------|
| **Latency** |
| Rule evaluation | N/A | < 50ms | Caching + indexes |
| Notification delivery | 500ms | < 100ms | Async processing |
| **Throughput** |
| Notifications/sec | 50 | 1000+ | Bulk ops + Redis |
| **Reliability** |
| Delivery success rate | 95% | 99%+ | Retry + fallback |
| **Flexibility** |
| Time to add new rule | 1 hour | < 5 min | UI-based config |

---

## 🔧 API Examples

### Create Rule via API
```bash
curl -X POST /admin/notifications/rules \
  -H "Content-Type: application/json" \
  -d '{
    "rule_name": "High Value Lead - CEO Alert",
    "module": "lead",
    "event_type": "lead_created",
    "priority": 20,
    "conditions": {
      "logic": "AND",
      "rules": [
        {"field": "estimated_value", "operator": "greater_than", "value": 100000}
      ]
    },
    "recipients_config": {
      "type": "specific_users",
      "user_ids": [1]
    },
    "channels_config": {
      "enabled": ["browser", "email", "sms"],
      "priority": "high"
    }
  }'
```

### Dispatch Notification
```python
from app.services.notification_dispatcher import dispatch
from app.core.events import SystemEvents

# Tự động sử dụng Hybrid System
await dispatch(
    db=db,
    event=SystemEvents.LEAD_CREATED,
    payload={
        "lead_id": 123,
        "lead_name": "ABC Corp",
        "estimated_value": 150000,
        "priority": "high",
        "unit_id": 1,
        "actor_id": current_user.id
    }
)
# Rule Engine sẽ tự động:
# 1. Load rules cho "lead_created"
# 2. Check conditions (value > 100k? ✓)
# 3. Resolve recipients (CEO)
# 4. Apply hooks
# 5. Route channels (browser + email + SMS vì priority=high)
# 6. Send notifications
```

---

## 🆚 So Sánh: Trước vs. Sau

### Thêm Notification Mới

**Trước (Old System):**
```
1. Sửa notification_registry.py (15 phút)
2. Sửa notification_resolvers.py (10 phút)
3. Sửa SocketHandler.tsx (20 phút)
4. Test locally (10 phút)
5. Commit + Push (5 phút)
6. Deploy + Restart server (10 phút)
7. Test production (10 phút)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tổng: ~80 phút + Risk cao
```

**Sau (Hybrid System):**
```
1. Vào Admin UI
2. Click "Create Rule"
3. Fill form (3 phút)
4. Click "Preview" (30 giây)
5. Click "Save" (5 giây)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tổng: ~5 phút + Zero risk
```

### Thay Đổi Recipients

**Trước:** Sửa code → Deploy → Restart (30-60 phút)
**Sau:** Edit rule trong UI (2 phút)

### Debug Notification Issue

**Trước:** Đọc code + Log files (20-30 phút)
**Sau:** Admin UI → Analytics → Filter by event (2 phút)

---

## 🎓 Resources

### Documentation
- **Full Implementation Plan**: `/docs/HYBRID_NOTIFICATION_SYSTEM_IMPLEMENTATION_PLAN.md`
- **Database Schema**: `/docs/DATABASE_SCHEMA.md`
- **API Docs**: `/docs/API_DOCUMENTATION.md`
- **Hook Guide**: `/docs/HOOKS_GUIDE.md`

### Code Examples
- **Example Hooks**: `/app/hooks/examples/`
- **Example Rules**: `/scripts/seed_rules.py`
- **Example Tests**: `/tests/services/test_rule_engine.py`

### Support
- **Slack**: #hybrid-notification-system
- **Issues**: GitHub Issues
- **Email**: tech-lead@example.com

---

## ✅ Next Steps

1. **Đọc Full Plan**: `/docs/HYBRID_NOTIFICATION_SYSTEM_IMPLEMENTATION_PLAN.md`
2. **Setup Dev Environment**: Follow setup guide
3. **Review Database Schema**: Understand data model
4. **Experiment với Examples**: Run example hooks
5. **Attend Kickoff Meeting**: Get assigned tasks

---

**Last Updated**: 2025-11-26
**Version**: 1.0
**Status**: Ready for Implementation 🚀
