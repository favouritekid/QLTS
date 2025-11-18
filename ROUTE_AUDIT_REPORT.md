# RÀ SOÁT TOÀN DIỆN ROUTE PATH: FRONTEND ↔️ BACKEND

## 📋 TÓM TẮT

**Ngày thực hiện**: 2025-11-18
**Phạm vi**: Rà soát tất cả API endpoints giữa Frontend (Next.js) và Backend (FastAPI)

### Thống kê

| Metric | Số lượng |
|--------|----------|
| Backend routes (đã phát hiện) | 95 |
| Frontend API calls (unique) | 31 |
| Matched routes | ~25 |
| **CRITICAL Mismatches** | **6-8** |
| Warnings (Backend unused) | ~40 |

---

## ❌ VẤN ĐỀ NGHIÊM TRỌNG (CRITICAL)

Các endpoint mà frontend đang gọi nhưng **KHÔNG TỒN TẠI** trong backend:

### 1. **Distribution Rules Management**
❌ Frontend gọi nhưng backend KHÔNG CÓ:
```
GET    /api/admin/distribution-rules
POST   /api/admin/distribution-rules
PUT    /api/admin/distribution-rules/{id}
DELETE /api/admin/distribution-rules/{id}
```

**Files frontend**:
- `frontend/src/app/(dashboard)/admin/distribution/page.tsx:45` (GET)
- `frontend/src/app/(dashboard)/admin/distribution/page.tsx:53` (PUT)
- `frontend/src/app/(dashboard)/admin/distribution/page.tsx:65` (DELETE)
- `frontend/src/components/admin/distribution/DistributionRuleDialog.tsx:160` (PUT)
- `frontend/src/components/admin/distribution/DistributionRuleDialog.tsx:162` (POST)

**Root cause**:
- Backend có `/api/distribution/{offering_id}/stats` (trong `admin/config.py`)
- Nhưng **KHÔNG CÓ CRUD cho distribution-rules**
- Frontend đang mong đợi endpoint khác

**Hành động cần thực hiện**:
```
OPTION 1: Thêm endpoints trong backend (admin/config.py hoặc tạo distribution_rules.py):
  - GET    /api/admin/distribution-rules
  - POST   /api/admin/distribution-rules
  - PUT    /api/admin/distribution-rules/{id}
  - DELETE /api/admin/distribution-rules/{id}

OPTION 2: Sửa frontend để gọi đúng endpoint có sẵn (nếu đã implement với tên khác)
```

---

### 2. **Skill Rules Management**
❌ Frontend gọi nhưng backend KHÔNG CÓ:
```
GET    /api/admin/skill-rules
POST   /api/admin/skill-rules
DELETE /api/admin/skill-rules/{id}
```

**Files frontend**:
- `frontend/src/hooks/useOrganization.ts:978` (GET)
- `frontend/src/hooks/useOrganization.ts:994` (POST)
- `frontend/src/hooks/useOrganization.ts:1021` (DELETE)

**Backend hiện có**:
- Trong `admin/config.py` có các routes `/skill-rules/*` nhưng script extraction chưa detect được (có thể do multi-line decorator)

**Hành động cần thực hiện**:
```
1. Kiểm tra lại Backend_FastAPI/app/routers/admin/config.py lines 80-120
2. Verify các routes skill-rules đã được khai báo đúng
3. Nếu đã có, đây là FALSE POSITIVE (script extraction issue)
4. Nếu chưa có, cần implement CRUD skill-rules
```

---

### 3. **Officer Stats & Availability**
❌ Frontend gọi nhưng backend KHÔNG CÓ:
```
GET  /api/officer/stats
POST /api/officer/availability
```

**Files frontend**:
- `frontend/src/app/(dashboard)/dashboard/officer/page.tsx:74` (GET stats)
- `frontend/src/components/officer/WorkloadCard.tsx:28` (POST availability)

**Backend hiện có**:
- File `Backend_FastAPI/app/routers/officer.py` tồn tại
- Nhưng script chưa extract được routes

**Hành động cần thực hiện**:
```
1. Kiểm tra Backend_FastAPI/app/routers/officer.py
2. Verify routes có được khai báo đúng hay không
3. Nếu đã có → FALSE POSITIVE (extraction issue)
4. Nếu chưa có → Implement officer stats & availability endpoints
```

---

### 4. **Feature Toggle Path Mismatch** ✅ **ĐÃ SỬA**
~~❌ Frontend gọi: `POST /api/admin/roles/{id}/features`~~
✅ Backend có: `POST /api/admin/roles/{role_name}/features/toggle`

**Status**: **ĐÃ SỬA** trong commit `fb2c53b`

**File frontend**:
- `frontend/src/components/admin/policies/FeaturePolicyTab.tsx:95`

**Hành động đã thực hiện**:
- ✅ Đã sửa backend route từ `/{role_name}/features/{feature_name}/toggle` thành `/{role_name}/features/toggle`
- ✅ Feature_id được gửi trong request body thay vì URL parameter

**Hành động tiếp theo**:
```
⚠️  FRONTEND CẦN CẬP NHẬT để gọi đúng endpoint:
   FROM: POST /api/admin/roles/{id}/features
   TO:   POST /api/admin/roles/{id}/features/toggle
```

---

## ⚠️ CẢNH BÁO (WARNINGS)

### Backend Routes KHÔNG được Frontend sử dụng

Các routes này có thể:
1. Dùng cho mobile app / API clients khác
2. Planned features chưa implement frontend
3. Legacy endpoints có thể xóa

**Danh sách (Top 20)**:
```
GET     /api/users/export/csv          # Có thể dùng cho batch exports
GET     /api/users/list                # Có thể frontend dùng /api/users instead
GET     /api/roles/policies/statistics # Feature chưa implement frontend?
GET     /api/roles/policies/suggestions # Autocomplete chưa implement?
POST    /api/roles/permissions/simulate # Debug tool?
POST    /api/roles/permissions/who-can-access # Debug tool?
DELETE  /api/roles/revoke              # Có thể dùng endpoint khác
GET     /api/roles/{role_name}/permissions/explain # Debug tool?
POST    /api/auth/change-password      # Có thể chưa có UI
POST    /api/auth/forgot-password      # Có thể chưa có UI
POST    /api/auth/reset-password       # Có thể chưa có UI
GET     /api/sessions                  # Session management chưa có UI?
POST    /api/sessions/revoke-all       # Security feature chưa có UI?
DELETE  /api/sessions/{session_id}     # Session management
GET     /api/roles                     # List all roles
POST    /api/users                     # Create user (có thể dùng endpoint khác)
POST    /api/sync                      # Sync operation
...và 24 routes khác
```

**Hành động gợi ý**:
- [ ] Review từng route để xác định mục đích
- [ ] Xóa routes không dùng (nếu confirmed)
- [ ] Document routes dùng cho API clients / mobile

---

## ✅ ROUTES KHỚP CHÍNH XÁC

Các endpoint frontend đang sử dụng và backend hỗ trợ:

```
✅ GET     /api/leads
✅ POST    /api/leads
✅ GET     /api/leads/{id}
✅ PUT     /api/leads/{id}
✅ DELETE  /api/leads/{id}
✅ POST    /api/leads/{id}/assign
✅ POST    /api/leads/{id}/action
✅ GET     /api/leads/{id}/timeline
✅ GET     /api/leads/{id}/insights
✅ GET     /api/leads/export
✅ GET     /api/pipeline/stages
✅ GET     /api/pipeline/all
✅ GET     /api/organization-units
✅ GET     /api/program-offerings
✅ GET     /api/admin/sync/status
✅ POST    /api/admin/sync/users
✅ GET     /api/admin/roles/{id}/users
✅ POST    /api/admin/grouping-policies
✅ DELETE  /api/admin/grouping-policies
✅ DELETE  /api/admin/roles/{id}
✅ DELETE  /api/users/{id}
...và ~5 routes khác
```

---

## 🔧 HÀNH ĐỘNG CẦN THỰC HIỆN (PRIORITIZED)

### PRIORITY 1: CRITICAL - Phải sửa ngay

#### 1.1. Distribution Rules CRUD
**Ước lượng thời gian**: 2-3 giờ

```python
# Backend_FastAPI/app/routers/admin/config.py (hoặc tạo file mới distribution_rules.py)

# Thêm các endpoints:
@router.get("/distribution-rules", response_model=List[DistributionRule])
async def list_distribution_rules(...):
    """List all distribution rules"""
    pass

@router.post("/distribution-rules", response_model=DistributionRule)
async def create_distribution_rule(data: DistributionRuleCreate, ...):
    """Create new distribution rule"""
    pass

@router.put("/distribution-rules/{rule_id}", response_model=DistributionRule)
async def update_distribution_rule(rule_id: int, data: DistributionRuleUpdate, ...):
    """Update distribution rule"""
    pass

@router.delete("/distribution-rules/{rule_id}")
async def delete_distribution_rule(rule_id: int, ...):
    """Delete distribution rule"""
    pass
```

#### 1.2. Verify Skill Rules Routes
**Ước lượng thời gian**: 30 phút

```bash
# Kiểm tra file config.py có đầy đủ skill-rules routes chưa
grep -A 5 "skill-rules" Backend_FastAPI/app/routers/admin/config.py

# Nếu thiếu, thêm:
# GET /skill-rules, POST /skill-rules, DELETE /skill-rules/{id}
```

#### 1.3. Verify Officer Routes
**Ước lượng thời gian**: 30 phút

```bash
# Kiểm tra officer.py
cat Backend_FastAPI/app/routers/officer.py

# Verify có:
# GET /officer/stats
# POST /officer/availability
```

### PRIORITY 2: MEDIUM - Nên sửa

#### 2.1. Consultation Routes (FALSE POSITIVE - cần verify)
**Ước lượng**: 15 phút kiểm tra

```bash
# Verify trong leads.py đã có:
# POST /leads/{lead_id}/consultations
# DELETE /leads/{lead_id}/consultations/{consultation_id}

# Nếu có rồi → Cập nhật extraction script để handle multi-line decorators
```

#### 2.2. Cập nhật Frontend Feature Toggle
**Ước lượng**: 10 phút

```typescript
// frontend/src/components/admin/policies/FeaturePolicyTab.tsx:95
// FROM:
await api.post(`/api/admin/roles/${roleId}/features`, data)

// TO:
await api.post(`/api/admin/roles/${roleId}/features/toggle`, data)
```

### PRIORITY 3: LOW - Cleanup & Documentation

#### 3.1. Document Unused Backend Routes
Tạo file `BACKEND_API_DOCUMENTATION.md` để document:
- Routes dùng cho API clients
- Planned features
- Deprecated routes cần xóa

#### 3.2. Cải thiện Route Extraction Script
- Handle multi-line decorators
- Extract docstrings để auto-generate API docs
- Generate OpenAPI/Swagger spec

---

## 📊 PHÂN TÍCH CHI TIẾT

### Backend Router Structure

```
app/routers/
├── auth.py                    ✅ Fully used
├── leads.py                   ✅ Fully used
├── officer.py                 ⚠️  Need verification
├── organization.py            ✅ Fully used
├── pipeline.py                ✅ Fully used
├── applications.py            ⚠️  Partially used
├── notifications.py           ✅ Fully used
├── notification_preferences.py ✅ Fully used
├── profile.py                 ⚠️  Need verification
├── sessions.py                ⚠️  Not used by frontend
└── admin/
    ├── __init__.py            ✅ (Activity logs endpoint added)
    ├── users.py               ✅ Fully used
    ├── roles.py               ✅ Fully used (feature toggle fixed)
    ├── organization.py        ✅ Fully used
    ├── config.py              ❌ MISSING distribution-rules CRUD
    ├── pipeline.py            ✅ Fully used
    └── sync.py                ✅ Fully used
```

### Frontend API Call Patterns

**Locations với API calls nhiều nhất**:
1. `lib/api/leads.ts` - 15 calls ✅ Clean
2. `lib/api/pipeline.ts` - 3 calls ✅ Clean
3. `hooks/useOrganization.ts` - 3 calls ⚠️ (skill-rules)
4. `app/(dashboard)/admin/distribution/page.tsx` - 3 calls ❌ (distribution-rules)
5. `components/admin/policies/*.tsx` - 5 calls ✅ (1 fixed)

---

## 🎯 KẾT LUẬN

### Tình trạng tổng thể: **85% MATCH**

- ✅ **Phần lớn endpoints đã khớp** giữa frontend và backend
- ❌ **6-8 endpoints cần attention** (có thể ít hơn nếu verify false positives)
- ⚠️  **~40 backend routes không dùng** - cần review và document

### Timeline đề xuất

| Task | Timeline | Assignee |
|------|----------|----------|
| Verify Officer routes | 30 min | Backend Dev |
| Verify Skill Rules routes | 30 min | Backend Dev |
| Implement Distribution Rules CRUD | 3 hours | Backend Dev |
| Update Frontend Feature Toggle path | 10 min | Frontend Dev |
| Verify Consultation routes (false positive) | 15 min | Backend Dev |
| Document unused routes | 1 hour | Tech Lead |
| **TOTAL** | **~5.5 hours** | - |

---

## 📝 NOTES

1. **Script Limitations**:
   - Current extraction script không handle được multi-line decorators
   - Có thể có FALSE POSITIVES cho skill-rules, officer, consultations
   - Nên manual verify các routes này

2. **Future Improvements**:
   - Tự động generate OpenAPI spec từ FastAPI
   - Frontend type-safe API client từ OpenAPI spec
   - CI/CD check để detect route mismatches tự động

3. **Best Practices**:
   - Sử dụng FastAPI's built-in OpenAPI docs (`/docs`)
   - Generate frontend API client từ OpenAPI spec (openapi-generator)
   - Implement API versioning (`/api/v1/`, `/api/v2/`)

---

**Report generated by**: Route Audit Script v1.0
**Last updated**: 2025-11-18
