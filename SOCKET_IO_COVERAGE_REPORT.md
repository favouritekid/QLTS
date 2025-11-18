# Socket.IO Events Coverage Report
**Generated:** 2025-11-18
**System:** QLTS Lead Management System

---

## Executive Summary

Socket.IO đã được triển khai trong **6/21 modules** (28.6% coverage), tập trung vào các chức năng real-time quan trọng:
- ✅ Authentication & Session Management
- ✅ User Management
- ✅ Organization Data
- ✅ Notifications
- ✅ Officer Availability
- ✅ Lead Reassignment

**Status:** 🟡 **Partial Coverage** - Các module quan trọng đã được triển khai, nhưng còn nhiều module chưa có real-time updates.

---

## 1. Socket.IO Events Implemented

### 1.1 Authentication & Session Events

**Module:** `app/services/session_service.py`, `app/services/user_service.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `force_logout_batch` | Server → Client | User-specific room | Force logout khi revoke session | ✅ Yes |
| `force_logout_all` | Server → Client | User-specific room | Force logout tất cả sessions khi đổi password | ✅ Yes |

**Use Cases:**
- Admin revoke 1 session cụ thể → Client nhận `force_logout_batch`
- User đổi password → Tất cả devices nhận `force_logout_all`

**Room Pattern:** `user_room_{user_id}`

---

### 1.2 User Management Events

**Module:** `app/services/user_service.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `data_updated` | Server → Broadcast | All clients | Thông báo khi có thay đổi user data | ✅ Yes |

**Use Cases:**
- Admin create/update/delete user
- Admin bulk delete users
- Admin sync users từ external system

**Payload Structure:**
```json
{
  "resource_type": "user",
  "operation": "create|update|delete|bulk_delete",
  "resource_id": 123,
  "resource_name": "John Doe"
}
```

**Broadcast:** ✅ Global (tất cả clients)

---

### 1.3 Organization Data Events

**Module:** `app/services/organization_service.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `data_updated` | Server → Broadcast | All clients | Thông báo khi có thay đổi org data | ❌ No |

**Use Cases:**
- Admin create/update/delete organization units
- Admin create/update/delete programs
- Admin create/update/delete offerings
- Admin create/update/delete academic info

**Payload Structure:**
```json
{
  "resource_type": "organization|program|offering|academic_info",
  "operation": "create|update|delete",
  "resource_id": 456,
  "resource_name": "Computer Science",
  "timestamp": "2025-11-18T10:30:00Z"
}
```

**Broadcast:** ✅ Global (tất cả clients)

---

### 1.4 Notification Events

**Module:** `app/routers/notifications.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `notification` | Server → Client | User-specific room | Gửi notification real-time | ❌ No |

**Use Cases:**
- Hệ thống tạo notification mới cho user
- User nhận notification ngay lập tức qua WebSocket

**Payload Structure:**
```json
{
  "id": 789,
  "type": "info|success|warning|error",
  "title": "Thông báo mới",
  "message": "Bạn có lead mới được assign",
  "link": "/leads/123",
  "data": {},
  "is_read": false,
  "created_at": "2025-11-18T10:30:00Z",
  "read_at": null
}
```

**Room Pattern:** `user_room_{user_id}`

---

### 1.5 Officer Availability Events

**Module:** `app/services/officer_service.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `officer_availability_changed` | Server → Broadcast | All clients | Thông báo officer thay đổi trạng thái | ❌ No |

**Use Cases:**
- Officer toggle availability status (available/busy/offline)
- Admin dashboard cập nhật real-time danh sách officers available

**Payload Structure:**
```json
{
  "officer_id": 10,
  "new_status": "available|busy|offline",
  "username": "officer_john",
  "unit_id": 5
}
```

**Broadcast:** ✅ Global (tất cả clients, admin dashboards filter theo unit)

---

### 1.6 Lead Reassignment Events

**Module:** `app/services/lead_service.py`, `app/socket_manager.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `lead_reassigned` | Server → Client | Old officer room | Thông báo lead bị transfer đi | ❌ No |
| `lead_transferred_in` | Server → Broadcast | All clients | Thông báo có lead mới transfer vào unit | ❌ No |

**Use Cases:**
- Admin/System thay đổi offering của lead → Auto reassign to new unit
- Old officer nhận thông báo lead bị remove
- New unit admin nhận thông báo có lead mới

**Payload Structure:**

**`lead_reassigned`:**
```json
{
  "lead_id": 999,
  "reason": "Offering changed from #5 to #10",
  "old_unit_id": 3,
  "new_unit_id": 7,
  "message": "Lead #999 has been transferred to another unit due to offering change.",
  "action": "remove_from_list"
}
```

**`lead_transferred_in`:**
```json
{
  "lead_id": 999,
  "reason": "Offering changed",
  "old_unit_id": 3,
  "new_unit_id": 7,
  "old_officer_id": 10,
  "message": "Lead #999 has been transferred from Unit #3.",
  "action": "refresh_unassigned_leads"
}
```

**Room Pattern:**
- `lead_reassigned`: `user_room_{old_officer_id}` (targeted)
- `lead_transferred_in`: Global broadcast

---

### 1.7 System Events

**Module:** `app/main.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `server_shutdown` | Server → Broadcast | All clients | Thông báo server sắp restart | ❌ No |

**Use Cases:**
- Graceful shutdown khi server restart
- Client hiển thị notification yêu cầu refresh page

**Payload Structure:**
```json
{
  "message": "Server is restarting. Please refresh in a moment."
}
```

**Broadcast:** ✅ Global (tất cả clients)

---

### 1.8 Client → Server Events

**Module:** `app/socket_manager.py`

| Event Name | Direction | Target | Purpose | Metrics |
|------------|-----------|--------|---------|---------|
| `connect` | Client → Server | - | Authenticate và join room | ✅ Yes |
| `disconnect` | Client → Server | - | Leave room và cleanup | ✅ Yes |
| `ping` | Client → Server | - | Keepalive heartbeat | ✅ Yes |
| `revalidate_auth` | Client → Server | - | Periodic session validation | ✅ Yes |
| `logout_confirmed` | Client → Server | - | Client xác nhận đã logout | ✅ Yes |

**Rate Limiting:** ✅ Yes (20 connections/minute per IP, Redis LUA script)

---

## 2. Modules WITHOUT Socket.IO

### 2.1 Critical Modules (High Priority)

❌ **Pipeline Management** (`app/services/pipeline_service.py`)
- **Impact:** Admin không nhận real-time updates khi thay đổi pipeline stages/statuses
- **Use Cases Cần Implement:**
  - Create/Update/Delete pipeline stages
  - Create/Update/Delete consultation statuses
  - Create/Delete allowed transitions

**Recommended Event:** `pipeline_config_updated`

---

❌ **Application Management** (`app/services/application_service.py`)
- **Impact:** Officers/Admins không thấy real-time updates về application status
- **Use Cases Cần Implement:**
  - Create/Update application
  - Application status change (pending → completed → passed/failed)
  - Document checklist updates

**Recommended Events:**
- `application_created`
- `application_status_changed`
- `application_documents_updated`

---

❌ **Lead Assignment** (`app/services/assignment_service.py`)
- **Impact:** Officers không nhận real-time notification khi được assign lead mới
- **Use Cases Cần Implement:**
  - Auto assignment complete
  - Manual assignment by admin
  - Assignment failed (no available officers)

**Recommended Events:**
- `lead_assigned` (to officer room)
- `assignment_failed` (to admin room)

---

### 2.2 Important Modules (Medium Priority)

❌ **Activity Logs** (`app/services/activity_service.py`)
- **Impact:** Admin dashboard không auto-refresh activity logs
- **Recommended Event:** `activity_logged`

❌ **Config Management** (`app/services/config_service.py`)
- **Impact:** Không auto-refresh khi admin thay đổi skill rules hoặc assignment config
- **Recommended Event:** `config_updated`

❌ **Distribution Service** (`app/services/distribution_service.py`)
- **Impact:** Không thấy real-time distribution stats
- **Recommended Event:** `distribution_stats_updated`

---

### 2.3 Low Priority Modules

❌ **Auth Service** (`app/services/auth_service.py`)
- Login/logout events → Already handled by session service

❌ **Role Management** (`app/services/role_service.py`)
- **Impact:** Minor, admin có thể refresh manually
- **Recommended Event:** `role_updated`

❌ **Notification Preferences** (`app/services/notification_preference_service.py`)
- **Impact:** Very low, preferences chỉ affect 1 user

❌ **Email Service** (`app/services/email_service.py`)
- Background tasks, không cần real-time

❌ **GeoIP Service** (`app/services/geoip_service.py`)
- Readonly, không cần real-time

❌ **Insights Service** (`app/services/insights_service.py`)
- Analytics, có thể polling

❌ **Casbin Service** (`app/services/casbin_service.py`)
- Permission changes → Có thể dùng `data_updated` event hiện có

---

## 3. Socket.IO Infrastructure

### 3.1 Connection Management

**File:** `app/socket_manager.py`

✅ **Features:**
- Cookie-based authentication (httpOnly `access_token`)
- User room management (`user_room_{user_id}`)
- Rate limiting (Redis LUA script, 20 conn/min)
- Session revalidation (5-minute interval)
- User blacklist check
- Graceful disconnect on password change
- Metrics tracking (Prometheus)

✅ **Security:**
- Token sanitization in logs
- Fail-closed rate limiting
- Session validation against Redis + DB
- User blacklist enforcement

---

### 3.2 Utility Functions

**File:** `app/socket_manager.py`

| Function | Purpose | Usage |
|----------|---------|-------|
| `emit_to_all(event, data)` | Broadcast to all clients | Organization updates |
| `emit_lead_reassigned(...)` | Targeted + broadcast for lead transfer | Lead service |

---

### 3.3 Metrics & Monitoring

**File:** `app/socket_metrics.py`

✅ **Prometheus Metrics:**
- `socket_connections_active` (Gauge)
- `socket_events_received_total` (Counter by event_type)
- `socket_events_emitted_total` (Counter by event_type)
- `socket_auth_failures_total` (Counter)
- `socket_emit_failures_total` (Counter by event_type)
- `socket_event_latency_seconds` (Histogram by event_type)

**Grafana Dashboard:** ❌ Not implemented yet

---

## 4. Coverage Analysis by Module Type

### 4.1 By Feature Area

| Feature Area | Coverage | Modules with Socket | Total Modules | Notes |
|--------------|----------|---------------------|---------------|-------|
| Authentication | ✅ 100% | 2/2 | 2 | session, user (auth part) |
| User Management | ✅ 100% | 1/1 | 1 | user_service |
| Organization | ✅ 100% | 1/1 | 1 | organization_service |
| Notifications | ✅ 100% | 1/1 | 1 | notifications (router) |
| Officer | ✅ 100% | 1/1 | 1 | officer_service |
| Lead Management | 🟡 50% | 1/2 | 2 | lead (reassign only), ❌ assignment |
| Application | ❌ 0% | 0/1 | 1 | application_service |
| Pipeline | ❌ 0% | 0/1 | 1 | pipeline_service |
| Configuration | ❌ 0% | 0/3 | 3 | config, distribution, role |
| System | ✅ 100% | 1/1 | 1 | main (shutdown event) |

---

### 4.2 By Priority

| Priority | Implemented | Not Implemented | Total |
|----------|-------------|-----------------|-------|
| **Critical** | 5 | 3 | 8 |
| **High** | 1 | 0 | 1 |
| **Medium** | 0 | 3 | 3 |
| **Low** | 0 | 9 | 9 |

**Critical Modules:**
- ✅ User Management (auth, session, CRUD)
- ✅ Organization Data
- ✅ Notifications
- ❌ Pipeline Management
- ❌ Application Management
- ❌ Lead Assignment

---

## 5. Recommendations

### 5.1 Immediate Actions (P0)

1. **Implement Lead Assignment Events**
   - `lead_assigned` → Officer nhận notification ngay lập tức
   - Target: `user_room_{officer_id}`
   - Impact: Trải nghiệm officer tốt hơn rất nhiều

2. **Implement Application Events**
   - `application_status_changed` → Officer/Admin thấy progress real-time
   - Target: Broadcast or officer-specific room
   - Impact: Tăng transparency trong quy trình xét hồ sơ

3. **Implement Pipeline Config Events**
   - `pipeline_config_updated` → Admin dashboard auto-refresh
   - Target: Broadcast to all admins
   - Impact: Tránh stale data khi nhiều admin cùng làm việc

---

### 5.2 Short-term Improvements (P1)

1. **Add Metrics to Missing Events**
   - `officer_availability_changed` → Add Prometheus counter
   - `lead_reassigned` / `lead_transferred_in` → Add metrics
   - Notification events → Add metrics

2. **Create Grafana Dashboard**
   - Visualize socket connection trends
   - Monitor event emit rates
   - Alert on high failure rates

3. **Document Frontend Integration**
   - Which components listen to which events
   - How to handle reconnection
   - Event payload schemas

---

### 5.3 Long-term Enhancements (P2)

1. **Implement Config Management Events**
   - Skill rules updates
   - Assignment config changes
   - Distribution rules changes

2. **Add Room-based Broadcasting**
   - Unit-specific rooms (`unit_room_{unit_id}`)
   - Role-specific rooms (`role_room_admin`, `role_room_officer`)
   - More targeted notifications instead of global broadcast

3. **Add Socket.IO Namespaces**
   - `/admin` namespace for admin-only events
   - `/officer` namespace for officer-only events
   - Better separation of concerns

---

## 6. Frontend Socket.IO Integration Status

### 6.1 Known Implementations

**File:** `frontend/src/lib/socket.ts` (assumption - needs verification)

✅ **Events Handled:**
- `force_logout_batch`
- `force_logout_all`
- `notification`
- `data_updated` (likely)

❌ **Events NOT Handled (likely):**
- `officer_availability_changed`
- `lead_reassigned`
- `lead_transferred_in`
- `server_shutdown`

**Action Required:** Audit frontend codebase to verify which events are actively handled.

---

## 7. Testing Coverage

### 7.1 Backend Tests

**File:** `Backend_FastAPI/tests/integration/workers/test_celery_worker.py`
- ❌ No Socket.IO integration tests found

**File:** `Backend_FastAPI/tests/security/test_websocket_security.py`
- ✅ Security tests exist

**Action Required:**
- Add integration tests for each socket event
- Test event payload structure
- Test room targeting correctness
- Test broadcast vs. targeted events

---

### 7.2 Frontend Tests

**Action Required:**
- Mock Socket.IO server in frontend tests
- Test event handlers
- Test reconnection logic
- Test error handling

---

## 8. Summary & Next Steps

### Overall Coverage: 🟡 28.6% (6/21 modules)

**Strengths:**
✅ Core authentication & session management fully covered
✅ Critical user data updates broadcast real-time
✅ Notification system works well
✅ Strong security (rate limiting, auth validation, metrics)

**Gaps:**
❌ Pipeline management không có real-time updates
❌ Application workflow không có real-time notifications
❌ Lead assignment hoàn thành không notify officer
❌ Config changes không broadcast

**Priority Actions:**
1. **Week 1:** Implement `lead_assigned` event (P0)
2. **Week 2:** Implement `application_status_changed` event (P0)
3. **Week 3:** Implement `pipeline_config_updated` event (P0)
4. **Week 4:** Add metrics to all existing events + Create Grafana dashboard

**Long-term Vision:**
- 80%+ coverage across all critical modules
- Room-based targeted broadcasting
- Namespace separation (admin/officer/public)
- Comprehensive frontend integration
- Full test coverage

---

**Report Generated:** 2025-11-18
**Next Review:** After implementing P0 actions
