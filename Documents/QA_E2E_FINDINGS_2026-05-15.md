# QA E2E FINDINGS — 2026-05-15 → 2026-05-16

**Stack**: dev local · FE `http://localhost:3000` · BE `http://localhost:8000`
**Playbook**: [`QA_E2E_PLAYBOOK_2026-05-15.md`](./QA_E2E_PLAYBOOK_2026-05-15.md)
**Run by**: Chrome MCP browser automation
**Personas tested**: A · Admin (id=15) · B · Officer (id=16 nguyenhuuhieu) · C · Accountant (id=24 kpahdrim)
**Test artifact**: profile #42 (lead 410 "Chị Sương", path 146 multi-NV, draft) — chưa cleanup

## Severity legend
- 🟥 **Blocker** — page crash / data loss / RBAC bypass / IDOR leak / feature inoperable
- 🟧 **Major** — feature broken / wrong response / thin-client violation / contract drift
- 🟨 **Minor** — UX glitch / inconsistent label / missing affordance
- 🟦 **Info** — known landmine / memory drift / nice-to-have

---

## 🔥 EXECUTIVE SUMMARY (read first)

| # | Sev | Area | Title |
|---|---|---|---|
| F1 | 🟥 | Multi-NV CREATE flow | `applied_rules.admission_round_id` bị Pydantic schema strip → AddChoiceDialog báo "Không xác định được đợt xét tuyển hiện tại" → multi-NV không add NV được |
| F2 | 🟥 | Multi-NV RBAC | Casbin policy `/api/v2/admissions/*/choices` POST/PATCH/DELETE **CHƯA SEED** vào `casbin_rule` table; chỉ admin pass được qua wildcard `/*`. Officer (chính chủ profile) → 403 |
| F3 | 🟥 | Data leak — PII | Officer + Accountant `GET /api/admin/users` → 200, trả full PII (email, phone, mfa_enabled, password_reset_required, unit_id) cho 18 user kể cả admin |
| F4 | 🟧 | Thin-Client violation | Sidebar Officer leak admin nav "Backfill Queue" → click bị FE route guard bounce (defense-in-depth OK), nhưng nav build từ hardcode list không phải permission flag |
| F5 | 🟧 | API contract drift | Pydantic response schema strip 8 keys khỏi `applied_rules` so với DB JSONB: `admission_round_id`, `round_code`, `fee_status`, `method_quota`, `applicable_to`, `application_fee`, `subject_weights`, `bonus_rule_override`, `requires_application_fee` (matches memory `service-explicit-dict-field-drop-pattern`) |
| F6 | 🟧 | Permissions block incomplete | `permissions` payload thiếu key `override` cho admin trên submitted profile → UI không thể show Override button → admin chỉ có thể override qua direct API |
| F7 | 🟧 | Workflow safety | Profile 39 status=`submitted` nhưng `eligibility_status=ineligible` + 7 validation errors (bypass via `allow_unverified_submission=true`). UI hiển thị neutral "Chờ duyệt" không cảnh báo bypass — admin click Approve sẽ approve hồ sơ không đủ điều kiện một cách im lặng |
| F8 | 🟧 | Accountant scope unclear | `GET /api/admissions` cho accountant trả lỗi `"Unexpected role 'accountant' for admission access"` — defensive code wording cho thấy accountant chưa được model trong scoping logic chính thức của admission service |
| F9 | 🟧 | Lead PII leak | Accountant `GET /api/leads` → 200 với 391 leads, lộ phone+source+offering — accountant không cần list này |
| F10 | 🟨 | Validation order | E2/E3/E8/E20 trả 422 (validation) thay vì 403 — body validation chạy trước Casbin → leak schema cho user không quyền |
| F11 | 🟦 | Memory drift | `phase3-admin-backfill-queue-no-nav` đã stale — sidebar admin **CÓ** entry Backfill Queue (uid sidebar 6_67) |
| F12 | 🟦 | State machine doc drift | Allowed transitions submitted → reviewing vẫn còn (qua error msg "Allowed transitions from submitted: approved, draft, rejected, **reviewing**, revision_requested, withdrawn") dù refactor 2026-05-15 nói bỏ `reviewing` cho multi-NV; legacy single-NV còn dùng |
| F13 | 🟦 | Endpoint audit | `GET /api/v2/admissions/{id}/choices` → **405 Method Not Allowed** (route không tồn tại); choices đọc qua `GET /api/admissions/{id}` `.choices[]`. Playbook + Explore agent table cũ có sai. |

---

## DETAIL — ALL FINDINGS

### 🟥 F1 · Multi-NV CREATE flow blocker — `admission_round_id` stripped from response

**Reproduce**:
1. Login officer 16 (nguyenhuuhieu / @Abc12345!)
2. Navigate `/leads/410` → click "Tạo hồ sơ tuyển sinh"
3. Form → chọn năm 2026 + path "Xét học bạ THPT" → Submit
4. Profile #42 tạo OK → status=draft, `uses_choice_engine=true`, redirect `/admissions/42`
5. Tab "Điểm & Điều kiện" (Step 4) → "Danh sách nguyện vọng (0/5)" với button "Thêm nguyện vọng"
6. Click "Thêm nguyện vọng" → AddChoiceDialog mở
7. **Dialog hiển thị error**: > "Không xác định được đợt xét tuyển hiện tại của hồ sơ. Liên hệ quản trị viên."
8. Button "Thêm nguyện vọng" disabled, không có dropdown cascading

**Root cause**:
- DB `admission_profile.applied_rules` JSONB **DOES** contain `admission_round_id=1` for profile 42 (verified via psql)
- API response `GET /api/admissions/42` returns `applied_rules.admission_round_id = null`
- 8 keys total stripped from response (see F5)
- FE đọc `applied_rules.admission_round_id` để fetch danh sách path/sg_config khả dụng → null → error toast

**Evidence**:
- DB query: `SELECT applied_rules->>'admission_round_id' FROM admission_profile WHERE id=42;` → `1`
- API response: `applied_rules_keys` count = 20; DB JSONB keys count = 28; missing 8 keys including `admission_round_id`
- Affects ALL profiles (verified profiles 16, 17, 18, 20, 23, 42)
- Lưu ý: profile 16 có 2 choice rows trong DB (created 2026-05-15 05:16 + 06:25) — có thể được tạo qua direct DB insert hoặc khi bug chưa exist

**Suspected location**: `Backend_FastAPI/app/schemas/admission.py` — Pydantic schema cho `applied_rules` field declare model thay vì `Dict[str, Any]` → strip không-declared keys

**Fix direction**:
- Option A: Schema dùng `Dict[str, Any]` cho `applied_rules` (forward-compat)
- Option B: Add missing keys vào AppliedRulesResponse schema explicitly
- Match pattern memory `service-explicit-dict-field-drop-pattern` từ PR #294/#295

---

### 🟥 F2 · Multi-NV RBAC blocker — Casbin policy missing in DB

**Reproduce** (officer 16 owner of profile 42):
```js
fetch('http://localhost:8000/api/v2/admissions/42/choices', {
  method:'POST', credentials:'include',
  headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
  body: JSON.stringify({admission_path_id:146, path_subject_group_config_id:12, scores:[{subject_code:'math',score:8.5}], display_order:1})
})
// → 403 PERMISSION_DENIED "You do not have permission for this action."
```

**Root cause**:
```sql
-- Casbin DB has 0 rows for /v2/admissions/*/choices for ANY role except admin (via wildcard /*)
SELECT v0,v1,v2 FROM casbin_rule WHERE ptype='p' AND v1 LIKE '%v2/admissions%' ORDER BY v0,v1,v2;
-- Returns: 10 rows (publish-result, waitlist-promote, waitlist-reject, claim, request-revision, admin-rollback)
-- NO entries for /api/v2/admissions/*/choices
```

**Yet** `policy_templates.py` lines 182, 191-194 declare these rules:
```python
{"subject": "{role}", "object": "/api/v2/admissions/*/choices",           "action": "GET"},
{"subject": "{role}", "object": "/api/v2/admissions/*/choices",           "action": "POST"},
{"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "DELETE"},
{"subject": "{role}", "object": "/api/v2/admissions/*/choices/*",         "action": "PATCH"},
{"subject": "{role}", "object": "/api/v2/admissions/*/choices/*/scores",  "action": "PATCH"},
```

→ **Sync script chưa chạy** sau khi update template, hoặc seed logic skip nhóm này.

**Verified**: Admin → 422 (passed Casbin via wildcard, schema validation failed) — confirms BE endpoint exists, only Casbin missing.

**Fix direction**: Run `app/scripts/sync_casbin_policies.py` (hoặc tương đương) để re-seed từ template. Add CI guard so policy table và template không drift.

**Combined impact F1 + F2**: Multi-NV CREATE flow hoàn toàn không operable cho officer trên dev local. Cả FE blocker (F1) lẫn BE blocker (F2) đều blocking. Sửa F1 mà chưa sửa F2 → vẫn fail.

---

### 🟥 F3 · PII data leak — Officer + Accountant list /api/admin/users

**Reproduce** (officer 16):
```
GET /api/admin/users?page_size=2 → 200 OK
{
  "total_count": 18,
  "users": [{
    "username":"admin", "email":"hapham1388@gmail.com",
    "full_name":"Phạm Thái Hà", "role":"admin", "id":15,
    "phone_number":null, "unit_id":12, "skills":null,
    "availability_status":"available", "max_capacity":100,
    "password_reset_required":false, "mfa_enabled":false  // ← security info exposure
  }, ...]
}
```

Same for accountant 24.

**Casbin policy**:
```sql
SELECT v0,v1,v2 FROM casbin_rule WHERE v1='/api/admin/users' AND v2='GET';
-- role:officer, role:accountant, role:manager — all GET allowed
```

→ Intentional Casbin allow (likely cho user-picker dropdown), nhưng response shape leak quá nhiều:
- `email` (PII)
- `phone_number` (PII)
- `mfa_enabled` (security info — useful targeted attacks)
- `password_reset_required` (info disclosure)

**Fix direction**:
- Tạo `UserPickerSchema` (id, full_name, unit_id, role, avatar_url) cho officer/accountant
- Giữ full schema cho manager/admin

---

### 🟧 F4 · Thin-Client violation — Officer sidebar leak "Backfill Queue"

**Reproduce**:
1. Login officer 16
2. Quan sát sidebar (uid=6_20 in snapshot) → **Backfill Queue** link xuất hiện
3. Click → URL change `/admin/admission-backfill-queue` nhưng FE route guard bounce về `/dashboard/officer`
4. Direct API `GET /api/v2/admin/admission-backfill-exceptions` → 403 (BE đúng)

**Root cause**: Sidebar build từ static role-based list (không phải permission flag từ BE). Memory `fe-thin-client-compliance-2026-05-14` đã flag SmartHeader/SmartConsultationStatusSelector/PathBasicInfo nhưng SIDEBAR config chưa được audit.

**Fix direction**: Sidebar nav phải đọc từ `/api/users/me` permissions block hoặc dedicated `/api/nav/items` endpoint trả filtered list.

---

### 🟧 F5 · API contract drift — `applied_rules` schema drops 8 keys

**Evidence**:
| Key | DB JSONB (profile 42) | API response |
|---|---|---|
| `admission_round_id` | `1` | **null** ← root cause F1 |
| `round_code` | NULL | not in response |
| `fee_status` | present | **MISSING** |
| `method_quota` | present | **MISSING** |
| `applicable_to` | present | **MISSING** |
| `application_fee` | present | **MISSING** |
| `subject_weights` | present | **MISSING** |
| `bonus_rule_override` | present | **MISSING** |
| `requires_application_fee` | present | **MISSING** |

**Cross-profile**: All 5 profiles tested (16, 17, 18, 20, 42) have `applied_rules_keys.length=20` despite DB having 28 keys.

**Reference**: memory `service-explicit-dict-field-drop-pattern` — đã có anchor template từ PR #294/#295 cho service explicit-dict drop. Cùng pattern, ở schema response layer thay vì service input layer.

---

### 🟧 F6 · Override action không expose qua permissions

**Reproduce** (admin):
```
GET /api/admissions/39
permissions: {edit, save, submit, approve, reject, publish_result, request_revision, resubmit, enroll, send_confirmation, drop, claim, unclaim, assign_officer, calculate_fee, delete, minor_correction, view}
// NO `override` key

available_actions: ["approve","reject","request_revision","claim","assign_officer","view"]
// NO `override`
```

But endpoint `/api/admissions/{id}/override` tồn tại + admin có Casbin permission. Admin chỉ override được qua direct API call (không discoverable trong UI).

**Test**: Direct call admin POST /api/admissions/39/override:
```
{"detail":"Invalid transition: submitted → overridden. Allowed transitions from submitted: approved, draft, rejected, reviewing, revision_requested, withdrawn"}
```
→ State machine cũng KHÔNG cho phép `submitted → overridden`. Vậy override chỉ valid từ approved/confirmed? Nếu vậy thì permission flag phải reflect state.

**Fix direction**: Add `override` vào permissions block + state-machine matrix; UI render Override button khi `permissions.override=true`.

---

### 🟧 F7 · Profile submitted with eligibility=ineligible + neutral UI

**Profile 39** (officer 18):
```json
{
  "status": "submitted",
  "eligibility_status": "ineligible",
  "validation_errors": ["Thiếu họ tên", "Thiếu DOB", "Thiếu giới tính", "Thiếu QT", "Thiếu DT", "Thiếu SĐT", "Thiếu nơi sinh"],
  "applied_rules.allow_unverified_submission": true
}
```

**UI**:
- Heading: "Hồ sơ #39 — Chưa có tên" (full_name=null)
- Status badge: "Chờ duyệt" (neutral)
- Banner: "Hồ sơ đang chờ xét duyệt" (no warning về bypass eligibility)
- Admin có button "Phê duyệt" (uid=3_102) hoạt động bình thường
- Tab "Vấn đề cần sửa (7)" có hiển thị nhưng không block approve flow

**Risk**: Admin có thể vô tình approve profile với 7 lỗi data → tạo student row với name=null + missing required fields. Nên có dialog cảnh báo "⚠️ Hồ sơ chưa đủ điều kiện (7 lỗi). Tiếp tục approve?" trước khi gọi `/approve`.

---

### 🟧 F8 · Accountant `/api/admissions` returns "Unexpected role" error

```
GET /api/admissions
→ 403 {"detail":"Unexpected role 'accountant' for admission access","error_code":"PERMISSION_DENIED"}
```

Wording **"Unexpected role"** chỉ ra defensive `else: raise` trong scope-resolver code. Accountant không được tính đến khi build admission scoping logic. Nếu intentional thì error message nên rõ "Accountant role không có scope admission list".

Implication: Accountant không thể list admissions để chọn profile_id khi tạo invoice/payment → workflow đi qua /finance/payments với input thủ công thay vì list-pick. Workflow gap.

---

### 🟧 F9 · Lead list PII leak cho accountant

```
GET /api/leads → 200, 391 leads
[{"full_name":"Nguyễn Viết Tín","phone":"0981208013","source":"website","unit_id":14,"offering_id":76,...}]
```

Accountant không cần list 391 leads với phone+source. Nên scope tương tự admission (không cho accountant).

---

### 🟨 F10 · Validation chạy trước Casbin → schema leak

| Probe | Status | Detail |
|---|---|---|
| E2 reject body `{reason:'x'}` | 422 | Field validation: reason min length |
| E3 request-revision `{reason:'x'}` | 422 | Field validation |
| E8 drop body `{reason:'x'}` | 422 | Field validation |
| E20 leads import body `{}` | 422 | Field validation |

→ Pydantic body validation chạy trước Casbin check. User không có quyền vẫn nhận info về schema (field min length, required fields). Minor info leak. Best practice: Casbin trước → validation sau.

---

### 🟦 F11 · Memory drift `phase3-admin-backfill-queue-no-nav`

Memory ghi: "/admin/admission-backfill-queue PR #275 Bundle 3 deployed prod KHÔNG có sidebar entry; admin phải gõ URL — track FU thêm SidebarLink trong System group"

Thực tế: sidebar admin **đã có** entry "Backfill Queue" (uid=2_67/4_67). Memory cần update: SidebarLink ĐÃ thêm.

---

### 🟦 F12 · State machine `reviewing` state vẫn còn

Per memory `phase3-pr-3a-shipped` và refactor 2026-05-15: bỏ T2 start-review cho multi-NV.

Direct API test admin POST /override on submitted profile trả error msg:
> "Allowed transitions from submitted: approved, draft, rejected, **reviewing**, revision_requested, withdrawn"

→ `allowed_transitions` table vẫn cho phép `submitted → reviewing`. Có thể chỉ legacy single-NV dùng. Cần check `allowed_transitions` config + cleanup nếu intent là bỏ hoàn toàn.

---

### 🟦 F13 · Endpoint inventory drift

- `GET /api/v2/admissions/{id}/choices` → **405 Method Not Allowed** (route không exist)
- Choices đọc qua `GET /api/admissions/{id}` field `.choices[]`
- Earlier Explore agent table table và playbook section APPENDIX B liệt kê GET endpoint này — **sai**
- Cần update playbook & doc

---

## RBAC matrix — Officer (verified)

| # | Endpoint | Method | Result | Note |
|---|---|---|---|---|
| E1 | /api/admissions/39/approve | POST | ✅ 403 + clear msg | – |
| E2 | /api/admissions/39/reject | POST | ⚠️ 422 | F10 schema leak |
| E3 | /api/admissions/39/request-revision | POST | ⚠️ 422 | F10 |
| E4 | /api/v2/admissions/39/publish-result | POST | ✅ 404 | IDOR — cross-officer profile |
| E5 | /api/v2/admissions/39/waitlist-promote | POST | ✅ 404 | IDOR |
| E6 | /api/admissions/39/override | POST | ✅ 403 | – |
| E7 | /api/admissions/39/finalize | POST | ✅ 403 | – |
| E8 | /api/admissions/39/drop | POST | ⚠️ 422 | F10 |
| E9 | /api/admissions/bulk/approve | POST | ✅ 403 + msg | – |
| E10 | /api/admissions/bulk/reject | POST | ✅ 403 | – |
| E11 | /api/admissions/bulk/assign | POST | ✅ 403 | – |
| E12 | /api/admissions/39/documents/CCCD/verify-format | PATCH | ✅ 403 | – |
| E14 | /api/payments | POST | ✅ 403 | – |
| E16 | /api/admin/users | POST | ✅ 403 | – |
| E17 | /api/v2/admin/years/2026/rounds | POST | ✅ 403 | – |
| E18 | /api/admission-config/paths | POST | ✅ 403 | – |
| E19 | /api/leads/bulk-assign | POST | ✅ 403 | – |
| E20 | /api/leads/import | POST | ⚠️ 422 | F10 |
| F-multi-NV | /api/v2/admissions/42/choices (own profile) | POST | 🟥 403 | F2 — should be 200 |

## RBAC matrix — Accountant (verified)

| # | Endpoint | Method | Result | Note |
|---|---|---|---|---|
| C.7.1 | /api/admissions/39/approve | POST | ✅ 403 | – |
| C.7.2 | /api/admissions/39/reject | POST | ✅ 403 | – |
| C.7.3 | /api/v2/admissions/39/publish-result | POST | ✅ 404 | IDOR scope |
| C.7.4 | /api/v2/admissions/39/claim | POST | ✅ 404 | – |
| C.7.5 | /api/v2/admissions/42/choices | POST | ✅ 404 | IDOR scope (also F2 underneath) |
| Finance | /api/payments | POST | ⚠️ 422 | passed Casbin, validation needs invoice_id |
| Finance | /api/payments/1/verify | PUT | ✅ 404 | passed Casbin, payment doesn't exist |
| Finance | /api/invoices | POST | ⚠️ 405 | route not POST? check audit |
| Admin | /api/admin/users | GET | 🟥 200 + PII | F3 |
| Admin | /api/v2/admin/admission-backfill-exceptions | GET | ✅ 403 | – |
| Admission list | /api/admissions | GET | 🟧 403 + "Unexpected role" | F8 |
| Lead list | /api/leads | GET | 🟧 200 + PII | F9 |

---

## IDOR matrix — Officer 16 (unit 14)

| # | Resource | Expected | Got |
|---|---|---|---|
| I2 | Profile 39 (officer 18, same unit 14) | 404 | ✅ 404 |
| I2b | Profile 22 (officer 18, enrolled, same unit) | 404 | ✅ 404 |
| I3 | Lead 411 (cross-officer same unit) | 404 | ✅ 404 |
| I9 | /api/admin/users (admin endpoint) | 403/empty | 🟥 200 + PII |
| I10 | /api/v2/admin/admission-backfill-exceptions | 403 | ✅ 403 |

**Key insight**: Officer scope là **per-officer (assigned only)**, NOT per-unit. Kịch bản gốc giả định "Tier 3: assigned + unit" — sai. Officer 16 không thấy được profile officer 18 cùng unit. Cập nhật `AUTHORIZATION_GUIDELINES.md` nếu cần.

---

## Thin-Client compliance — verified observations

| Component | Status | Note |
|---|---|---|
| Profile detail action buttons | ✅ Compliant | Render từ `permissions` + `available_actions` block |
| Sidebar nav | 🟧 Violation | Static role-based list, leak Backfill Queue cho officer (F4) |
| `permissions.override` | 🟧 Missing | F6 |
| SmartHeader (memory) | 🟧 Defer | Đã ghi nhận trước, chưa fix |
| SmartConsultationStatusSelector (memory) | – | Chưa probe trong run này |
| PathBasicInfo (memory) | – | Chưa probe trong run này |

---

## Step-by-step execution log

- **Day 1 (2026-05-15)**
- 11:03 Login admin via cookie session (carry-over từ phiên trước). Token `access_token` hợp lệ, role=admin, user_id=15.
- 11:04 A.1 ✅ Admin `/admissions` thấy 10 profiles toàn DB (3 draft + 2 submitted + 1 enrolled + 1 rejected + 1 resubmitted + 2 withdrawn). No scope filter.
- 11:04 A.1.2 Mở profile 39 (officer 18) → 200, fields disabled. Permissions block PRESENT (thin-client compliant). 4 action buttons: Phê duyệt / Từ chối / Yêu cầu sửa / Nhận duyệt. **Override button missing** → F6.
- 11:04 Capture response → analyze → eligibility=ineligible, allow_unverified=true → F7.
- 11:05 Direct API admin override on profile 39 → 400 Invalid transition (state machine block) → confirms F6 + reveals F12.
- 11:08 A.5 ✅ Backfill Queue page load OK, sidebar entry present → F11 memory drift.
- 11:10 Logout admin → login officer (nguyenhuuhieu).
- 11:11 Officer redirected `/dashboard/officer`. Sidebar shows "Backfill Queue" link → F4 thin-client violation.
- 11:11 Click Backfill → FE route guard bounce → URL stays `/dashboard/officer`. Defense-in-depth OK. Backend GET 403.
- 11:13 B1 ✅ Lead 410 "Chị Sương" loaded.
- 11:13 B2 ✅ Click "Tạo hồ sơ tuyển sinh" → modal `/admissions/create?lead_id=410`.
- 11:14 B3 ✅ Form: only 1 path "Xét học bạ THPT" available (filtered by lead offering). Select + submit.
- 11:14 B4 ✅ Profile #42 created, status=draft, `uses_choice_engine=true`, admission_path_id=146 (Kỹ thuật chế biến món ăn — Học bạ).
- 11:15 Step 4 → "Danh sách nguyện vọng (0/5)", click "Thêm nguyện vọng".
- 11:15 🟥 BLOCKER F1: Dialog opens with error "Không xác định được đợt xét tuyển hiện tại của hồ sơ. Liên hệ quản trị viên."
- 11:16 Investigate API: response `applied_rules.admission_round_id = null`. DB JSONB `admission_round_id = 1`. Schema strip 8 keys → root cause F1 + F5.
- 11:17 Test direct API POST choice → 403 PERMISSION_DENIED → F2.
- 11:17 Audit Casbin DB: 0 rows for `/v2/admissions/*/choices` (any role except admin via wildcard). policy_templates.py declares them. Sync gap → F2.
- 11:18 Admin via curl: POST choice → 422 (passed Casbin, validation). Confirms F2 scope.
- **Day 2 (2026-05-16)** — token expiry → re-login officer
- 09:xx Re-login officer. Run E-block + I-block comprehensive probe (24 endpoints, 1 script).
- 09:xx Find F3 PII leak via `/api/admin/users`.
- 09:xx Login accountant via curl. Run accountant RBAC matrix (12 endpoints).
- 09:xx Find F8 accountant scope error + F9 lead PII leak + F3 confirm cho accountant.
- 09:xx Wrap-up: write findings file.

---

## Test artifacts created (cleanup needed)

| Item | Note |
|---|---|
| Profile #42 (lead 410, draft, multi-NV) | Created in this run; choices=0 vì F1+F2 block. User decide cleanup hay giữ làm fixture |
| Admin password reset to `@Abc12345!` | User account hapham1388@gmail.com. Per user authorization. Reset back nếu cần |
| Officer/Accountant passwords reset | Same |
| `/tmp/admin.cookies`, `/tmp/acc.cookies` | Throwaway curl cookies — auto-cleanup |
| Audit log entries | Giữ làm bằng chứng |

---

## Recommendations (priority)

1. 🔥 **F2 Casbin sync**: Run `scripts/sync_casbin_policies.py` (or equivalent) ngay → unblock multi-NV cho officer/manager. Add CI check policy_templates ↔ casbin_rule parity.
2. 🔥 **F1 + F5 Pydantic schema**: Fix `applied_rules` schema drop 8 keys → multi-NV CREATE flow operable trên FE. Add anchor test: dump DB JSONB keys vs API response keys.
3. 🔴 **F3 PII leak**: Tạo lightweight `UserPickerSchema` cho officer/accountant; full schema only manager+. Update Casbin response shape OR wrap response per role.
4. 🟧 **F4 Sidebar permission-driven**: Backend trả nav allowlist trong `/api/users/me` permissions hoặc dedicated endpoint. FE filter sidebar accordingly.
5. 🟧 **F6 Override discoverability**: Add `override` to permissions block + state machine; render UI button when allowed.
6. 🟧 **F7 Bypass UX warning**: Banner orange/yellow trên submitted-but-ineligible profile + confirmation dialog trước khi approve.
7. 🟧 **F8 Accountant scope**: Define officially accountant admission scope (likely: profile có invoice/payment liên quan). Replace "Unexpected role" defensive code.
8. 🟧 **F9 Accountant lead scope**: Restrict `/api/leads` cho accountant or scope to profile-linked leads only.
9. 🟨 **F10 Validation order**: Move Casbin check trước Pydantic body validation (FastAPI dependency order trick).
10. 🟦 **F11/F12/F13 Doc/Memory hygiene**: Update memory + AUTHORIZATION_GUIDELINES + Explore agent endpoint table.

---

## Coverage stats

| Block | Steps planned | Steps run | Pass | Fail / Block | Skip |
|---|---|---|---|---|---|
| A · Admin | 10 sections (~30 steps) | 5 sections (A.0/A.1/A.4/A.5) | 4 | 1 (F6, F7) | A.2/A.3/A.6/A.7/A.8/A.9 |
| B · Officer Phase 1-2 | 12 steps (B1-B12) | 5 (B1-B4, B8) | 4 | 1 BLOCKER (B8a F1) | B5-B7, B8b-B12 (gated by F1) |
| B · Officer Phase 3-4 | 10 steps | 0 | – | – | gated |
| C · Single-NV legacy | 3 steps | 0 | – | – | skipped (low value vs blockers) |
| D · Edge cases | 35 steps | 0 | – | – | skipped (gated) |
| E · Officer RBAC matrix | 20 endpoints | 19 | 14 ✅ + 4 ⚠️ + 1 🟥 | F2 + F10 | E13/E15 not run |
| F · Thin-Client probes | 5 components | 1 (sidebar) | 0 | 1 (F4) | rest |
| C · Accountant | 9 sections | 1 (C.7 RBAC matrix) | 8 ✅ + 4 ⚠️/🟧 | F3, F8, F9 | C.1-C.6 |
| Cross-persona RBAC | matrix 12×3 | partial | – | – | – |
| IDOR matrix | 10 | 5 | 4 | 1 (F3) | – |

**Decision**: Stop run sau khi confirm F1+F2 BLOCKER. Continuing không tạo thêm value vì multi-NV inoperable; happy path B5-B22 không thể run end-to-end. Switch sang đo audit surface (RBAC + IDOR matrix) cho thông tin lớn hơn — done.

---

*End of findings.*
