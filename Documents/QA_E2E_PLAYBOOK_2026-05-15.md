# QA E2E PLAYBOOK — Chrome MCP Dev Local
**Created**: 2026-05-15 · **Wave 2 expanded**: 2026-05-16
**Target**: dev local stack (FE `http://localhost:3000`, BE `http://localhost:8000`)
**Mục tiêu**: phát hiện **gaps / RBAC / IDOR / Thin-Client violations** trên 4 personas + cross-cutting workflows.
**Output**: findings ghi vào `Documents/QA_E2E_FINDINGS_2026-05-15.md`.

## Index
- §0 Pre-flight (env, accounts, test data)
- §1 Persona A — Admin
- §2 Persona B — Officer (B-flow happy path + C/D edge cases + E RBAC + F Thin-Client)
- §3 Persona C — Accountant
- §4 Cross-persona RBAC matrix
- §5 IDOR matrix
- §6 Cross-cutting probes (realtime / errors / mobile)
- §7 Cleanup
- §8 Success criteria
- §H Persona M — **Manager** (unit-scope, claim, bulk ops, request-revision)
- §I Finance E2E (fee → invoice → payment → refund → accounting period)
- §J Multi-NV Result Publishing (publish-result engine cascade, waitlist, admin-rollback)
- §K Magic-link self-service (3 actions, resend cooldown ladder, generate-side gap)
- §L Notifications (rules, templates, delivery ops, consent, channel prefs)
- §M KPI tracking (plan setup, monthly snapshot, dashboards)
- §N Bulk + Import/Export (lead CSV import, partial success, admission bulk)
- §O CTV + Commission (self-reg, claim/approve, commission policy)
- §P Cross-cutting (optimistic locking 409, audit log, Socket.IO realtime, sessions)

---

## 0. PRE-FLIGHT (verify trước khi mở browser)

### 0.1 Docker stack health
```
docker compose ps      # 6 services: backend / frontend / postgres / redis / celery-worker / celery-beat ALL healthy
```
- Backend health: `curl -s http://localhost:8000/api/health/ready`
- FE serve: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/login` → 200

### 0.2 Ground-truth test data (đã audit DB 2026-05-15)

**Round multi-NV** (chính cho B-flow):
- `id=1`, `academic_year=2026`, `round_code=DOT_1`, `is_active=true`, `allow_multi_nv=true`
- ⚠️ Kịch bản gốc viết DOT_2 — đó là sai; DOT_2 (id=5) `allow_multi_nv=false`. **Toàn bộ playbook dùng DOT_1.**

**Round single-NV legacy** (cho C-flow):
- `id=11`, `round_code=E2E_TEST`, `is_active=true`, `allow_multi_nv=false`  ← dùng cho C1 single-NV
- Hoặc id=5 DOT_2 nếu cần "đã từng" tên DOT_2

**Active path multi-NV (DOT_1)**:
- `id=106` "Y sỹ đa khoa 2026 – Chính quy – Học bạ" — 6 sg_config
- `id=109` "Chăn nuôi thú y 2026 – Chính quy – Học bạ"
- `id=112` "Điều dưỡng 2026 – Chính quy – Học bạ"
- (32 active paths trong DOT_1)

**Lead happy path (chưa có profile)**:
- `id=410` "Chị Sương" — assigned officer 16, unit 14, status=contacted

**Existing profiles cho edge cases (officer 16)**:
| Profile id | Status | Use for |
|---|---|---|
| 17 / 18 / 20 | draft | B5–B12 (edit + submit), D7 concurrent edit |
| 16 | rejected | D1 resubmit cycle |
| 15 | resubmitted | D1d Manager review-after-resubmit |
| 19 / 23 | withdrawn | F1 final-state lock verify |

**Cross-officer (cho admin/manager test)**:
| Profile id | Status | Officer |
|---|---|---|
| 39 | submitted | 18 vothithuthuhien (unit 14) |
| 22 | enrolled | 18 vothithuthuhien (unit 14) |

### 0.3 Test accounts (password `@Abc12345!` — đã reset 2026-05-15)

| Persona | User id | Username | Email | Role | unit_id | Login URL |
|---|---|---|---|---|---|---|
| **A · Admin** | 15 | `admin` | hapham1388@gmail.com | admin | 12 | `/login` |
| **B · Officer** | 16 | `nguyenhuuhieu` | hieu9993@gmail.com | officer | 14 | `/login` |
| **C · Accountant** | 24 | `kpahdrim` | hdrim0405@gmail.com | accountant | 15 | `/login` |
| **M · Manager** | 34 | `manager_qa` | manager_qa@qlts.local | manager | 14 | `/login` |

> ⚠️ Admin account = chính account của user (hapham1388@gmail.com). Sau khi E2E xong, user có thể tự đổi password lại qua `/settings/security` hoặc giữ `@Abc12345!` cho session test tiếp theo.

### 0.4 Chrome MCP tool playbook cheat sheet
| Mục đích | Tool sequence |
|---|---|
| Mở page mới | `mcp__chrome-devtools__new_page` → `navigate_page` |
| Snapshot DOM (để target nodeId/UID) | `mcp__chrome-devtools__take_snapshot` |
| Click button | snapshot → `click(uid)` |
| Điền form | `fill_form([{name,value}])` hoặc `fill(uid,value)` |
| Verify response API | `list_network_requests` → `get_network_request(url)` |
| Catch FE error | `list_console_messages` |
| Screenshot bằng chứng gap | `take_screenshot(format=png)` |
| Wait stable | `wait_for(text)` hoặc `wait_for(time)` |

### 0.5 Findings file template — tạo trước khi chạy
```markdown
# QA E2E FINDINGS — 2026-05-15
## Severity legend
- 🟥 **Blocker** — page crash / data loss / RBAC bypass / IDOR leak
- 🟧 **Major** — feature broken / wrong response / thin-client violation
- 🟨 **Minor** — UX glitch / inconsistent label / missing affordance
- 🟦 **Info** — nice-to-have / cosmetic

## Findings
| # | Severity | Persona | Step | Title | Evidence | Repro |
|---|---|---|---|---|---|---|
| 1 | … | … | … | … | screenshot/url | … |
```

---

## 1. PERSONA A — ADMIN (id=15)

### A.0 Login
1. Navigate `/login`
2. Fill `username=admin`, `password=@Abc12345!`
3. Submit → expect redirect `/dashboard` (admin landing)
4. **Probe**: `take_screenshot` sidebar — verify đầy đủ menu admin (Users, Organization, Admission Config, KPI, Notifications, Audit Logs, Monitoring, Distribution, Policies, System Config, Backfill Queue)

### A.1 Admin sees ALL admissions (no scope filter)
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.1.1 | Navigate `/admissions` | Hiển thị ≥7 profiles (toàn DB, không scope unit) | `list_network_requests` → `GET /api/admissions` không có `?unit_id=` |
| A.1.2 | Mở profile 39 (officer khác) | Detail load 200 | network: `GET /api/admissions/39` 200, KHÔNG 404 |
| A.1.3 | Mở profile 22 (enrolled, officer khác) | Read-only badge "Đã nhập học" | – |

### A.2 Admin Round/Path config (`/admin/admission-config`)
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.2.1 | Navigate `/admin/admission-config` | Tabs Rounds / Paths / Criteria / Subjects | – |
| A.2.2 | Tab "Rounds" → thấy 8 rounds | DOT_1/2026 row có badge "Multi-NV" | network: `GET /api/v2/admin/years/2026/rounds` |
| A.2.3 | Click "Tạo đợt thử" → modal | Form: year, code, name, allow_multi_nv toggle | – |
| A.2.4 | Cancel modal | KHÔNG tạo round mới | – |
| A.2.5 | Click "Extend" trên round đã active | Dialog xác nhận extension | network: `POST /api/v2/admin/rounds/{id}/extend` (nếu submit) |
| A.2.6 | Tab "Paths" → filter round=DOT_1 | 32 active paths hiển thị | network: `GET /api/admission-config/paths?round_id=1` (hoặc tương đương) |
| A.2.7 | Click "Y sỹ đa khoa Học bạ" (id=106) | PathBasicInfo + sg_config matrix | – |
| A.2.8 | **Thin-Client probe**: scroll PathBasicInfo → có nút "Edit"? | Nếu có nút Edit thì backend trả `permissions.can_edit_path=true`? | `list_network_requests` GET path-detail — check body có `permissions` key không. Memory `fe-thin-client-compliance-2026-05-14` flag `PathBasicInfo.tsx:88` dùng `user?.role === "admin"` thay vì permission flag. |

### A.3 Admin Users (`/admin/users`)
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.3.1 | Navigate `/admin/users` | List ≥10 users, có column Role/Unit/Status | network: `GET /api/admin/users` |
| A.3.2 | Filter role=officer | 6 officer rows | – |
| A.3.3 | Click row officer 16 → `/admin/users/16` | Detail load, có tab "Permissions" / "Sessions" | – |
| A.3.4 | Click "Reset password" → confirm dialog | API call `POST /api/admin/users/16/reset-password` (hoặc tương đương) | – |
| A.3.5 | Cancel dialog | KHÔNG reset password thật | – |

### A.4 Admin-only workflow: Override admission
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.4.1 | Navigate `/admissions/39` (submitted) | Profile load | – |
| A.4.2 | Trong AdmissionActions, tìm button "Override" / "Phê duyệt vượt cấp" | Phải có (admin only) | `take_snapshot` — list buttons |
| A.4.3 | Click Override → dialog | Form `reason` required | – |
| A.4.4 | Nhập reason ngắn (5 ký tự) → submit | Validation: reason min length | – |
| A.4.5 | Nhập reason ≥20 ký tự → submit | 200, status → `overridden` | network: `POST /api/admissions/39/override` |
| A.4.6 | **Rollback test**: click "Hoàn tác override" (nếu có) | – | – |

### A.5 Admin-only: Admission Backfill Queue
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.5.1 | Navigate `/admin/admission-backfill-queue` | Page load, có table exceptions | network: `GET /api/v2/admin/admission-backfill-exceptions` |
| A.5.2 | Sidebar có link tới page này không? | Memory `phase3-admin-backfill-queue-no-nav` — KHÔNG có sidebar entry, admin phải gõ URL. **Confirm hoặc xóa landmine khỏi memory.** | – |
| A.5.3 | Nếu có exception rows: click resolve | network: `PATCH /api/v2/admin/admission-backfill-exceptions/{id}/resolve` | – |
| A.5.4 | Bulk-resolve button | network: `POST /api/v2/admin/admission-backfill-exceptions/bulk-resolve` | – |

### A.6 Admin-only: Finalize enrollment
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.6.1 | Navigate profile state `confirmed` (nếu có) hoặc tạo bằng cách publish-result + send-confirmation flow trước | – | – |
| A.6.2 | Click "Finalize" / "Hoàn tất nhập học" | network: `POST /api/admissions/{id}/finalize`, status → `enrolled`, student row tạo | – |
| A.6.3 | Verify `_compute_frontend_fields` post-finalize: `permissions.can_edit=false` cho tất cả role | `get_network_request` → check `permissions` block | – |

### A.7 Admin sees Casbin policies (`/admin/policies`)
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.7.1 | Navigate `/admin/policies` | Casbin rule list | – |
| A.7.2 | Filter role=accountant | DENY rules cho /admissions/*/claim, /publish-result, /choices | – |
| A.7.3 | Click "Reload Casbin" | network: `POST /api/v2/admin/casbin/reload` 200 | – |

### A.8 Admin Notifications config
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.8.1 | `/admin/notification-rules` | List rules | – |
| A.8.2 | `/admin/notification-templates` | List templates | – |
| A.8.3 | `/admin/notification-consents` | List consents | – |
| A.8.4 | `/admin/notification-deliveries` | Outbox + delivery log | – |

### A.9 Audit log review
| Step | Action | Expected | Probe |
|---|---|---|---|
| A.9.1 | `/admin/audit-logs` | Recent entries | – |
| A.9.2 | Sau khi Officer thực hiện B-flow → log entries xuất hiện | network: `GET /api/admin/audit-logs?actor_id=16` | – |

### A.10 Admin logout
1. Avatar menu → Logout
2. Verify redirect `/login`
3. `list_network_requests` → `POST /api/auth/logout` 200
4. `list_console_messages` — phải KHÔNG có error
5. Try navigate `/admissions` → bounce về `/login`

---

## 2. PERSONA B — OFFICER (id=16 nguyenhuuhieu, unit 14)

> Đây là kịch bản chính. Phase 1–4 = happy path multi-NV. D-block = edge cases. E-block = limits.

### B.0 Login
1. `/login` → username `nguyenhuuhieu`, password `@Abc12345!`
2. Expect redirect `/dashboard/officer` (route-config.ts:137 — officer redirect)
3. **Thin-Client probe**: dashboard có hiển thị widgets per backend response không? Memory flag — `dashboard/page.tsx` dùng `initialUser?.role === "admin"` để chia view. Acceptable cho routing nhưng ghi nhận.

---

### Phase 1 — TẠO HỒ SƠ (B1–B4)

| Step | Action | Endpoint | Expected | RBAC/IDOR/ThinClient probe |
|---|---|---|---|---|
| B1 | Navigate `/leads/410` | `GET /api/leads/410` | Lead detail "Chị Sương" load 200 | – |
| B2 | Tìm button "Tạo hồ sơ tuyển sinh" | – | Button hiển thị (lead chưa có profile) | `take_snapshot` — verify uid của button |
| B3 | Click → modal "Tạo hồ sơ" | – | Cascading dropdown round → path | – |
| B3a | Chọn round DOT_1/2026 | – | Path options populate (32 active) | network: `GET /api/admission-config/paths/by-round/1` |
| B3b | Chọn path id=106 (Y sỹ Học bạ) | – | – | – |
| B3c | Submit | `POST /api/admissions {lead_id:410, admission_path_id:106}` | 201, redirect `/admissions/{new_id}`, `status=draft`, `uses_choice_engine=true`, `applied_rules.admission_path_id=106` | `get_network_request` — assert response body có `uses_choice_engine: true` |
| B4 | Auto-redirect `/admissions/{new_id}` | – | Stepper 7 bước, currentStep=1, badge "Nháp" | `list_console_messages` — không error |

---

### Phase 2 — NHẬP THÔNG TIN (B5–B12a)

| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| B5 | Step 1 cá nhân: họ tên, CCCD 12 số, DOB, giới tính, dân tộc, tôn giáo, hộ khẩu | `PUT /api/admissions/{id}` body partial | 200, toast "Đã lưu" | – |
| B5a | **CCCD invalid** (11 số) | – | 422 ValidationError | – |
| B5b | **CCCD duplicate** (đã tồn tại) | – | 409 DuplicateResourceError | – |
| B6 | Step 2 gia đình: thêm 1 row cha (name/phone/relationship) | `PUT /api/admissions/{id}` body family_info array | family_info JSONB updated | – |
| B6a | Save với phone format sai (chữ) | – | 422 | – |
| B7 | Step 3 học tập: tên trường THPT, năm tốt nghiệp 2023, GPA 8.0 | `PUT /api/admissions/{id}` body academic_history | – | – |
| B8 | Step 4 Điểm | – | Render **MultiNvScoresTab** (uses_choice_engine=true) | `take_snapshot` — phải KHÔNG thấy form legacy single-NV |
| B8a | Click "Thêm nguyện vọng" → AddChoiceDialog | – | Cascading path → sg_config | – |
| B8a-1 | Chọn path id=106 → sg_config "B00" | – | 3 score inputs cho subjects Toán/Hóa/Sinh | network: `GET /api/v2/admissions/{id}/choices/options` hoặc tương đương |
| B8b | Nhập điểm 8.5/8.0/7.5 → submit | `POST /api/v2/admissions/{id}/choices` | 201, list refresh "(1/5)" | `get_network_request` — assert choice_id returned |
| B8c | (optional) Thêm NV2: path 112 "Điều dưỡng" + sg D01 | `POST .../choices` | 201, "(2/5)" | – |
| B8d | Sửa điểm NV1: pencil icon → EditScoresDialog → math 8.5→9.0 onBlur | `PATCH /api/v2/admissions/{id}/choices/{cid}/scores` | 200, badge revert nếu lỗi | – |
| B8d-1 | **Edge**: nhập 11.0 (vượt scale 10) | – | 422 ValidationError | – |
| B8d-2 | **Edge**: nhập "abc" | – | UI block, KHÔNG gửi request | – |
| B8e | Drag NV2 lên đầu (reorder) | `PATCH /api/v2/admissions/{id}/choices/{cid}` body `{display_order:1}` | 200 | – |
| B8f | Xoá NV1 (Trash icon) → AlertDialog confirm | `DELETE /api/v2/admissions/{id}/choices/{cid}` | 200, list "(1/5)" | – |
| B8g | Add lại NV1 để có 2 NV | – | – | – |
| B9 | Step 5 tài liệu: upload CCCD (.pdf 1MB) | `POST /api/admissions/{id}/documents/CCCD/upload` multipart | 200, badge "Đã upload" | network: response body trả `permissions.can_upload`/`can_reject` |
| B9a | Upload doc paper-only "Giấy ưu tiên" → click "Đánh dấu nộp giấy" | `POST .../documents/{code}/paper-submitted` | 200 | – |
| B9b | **Edge upload .exe** | `POST .../upload` | 415 hoặc 422 ValidationError | – |
| B9c | **Edge upload >10MB** | – | 413 (nginx limit) | – |
| B10 | Step 6 học phí: hiển thị tuition fee read-only | `GET /api/fees/calculate` hoặc `GET /api/fees/summary/{id}` | Số tiền hiển thị | – |
| B11 | Step 7 "Kiểm tra toàn bộ" | – | Nếu thiếu → tab "Vấn đề cần sửa(N)" có chip count + link tới step lỗi | – |
| B11a | Sau khi fix → revalidate | – | `eligibility_status=eligible` | – |
| B12 | Click "Nộp hồ sơ" | `POST /api/admissions/{id}/submit` | 200, `status=submitted`, `submitted_at` set, event `ADMISSION_PROFILE_SUBMITTED` dispatched | network: response có `permissions.can_edit=false` |
| B12a | **Edge** Submit khi 0 NV | – | 400 BusinessRuleViolation "Hồ sơ đa nguyện vọng phải có ít nhất 1 nguyện vọng" | Re-test sau khi B8f xoá hết NV |

---

### Phase 3 — CHỜ XÉT DUYỆT (B13–B16)

| Step | Action | Expected | Probe |
|---|---|---|---|
| B13 | Profile state=submitted, badge "Chờ duyệt" | UI ALL fields disabled | `take_snapshot` — verify fields `disabled` attr |
| B14 | **RBAC probe**: tìm button "Phê duyệt"/"Từ chối"/"Công bố kết quả" | KHÔNG hiển thị (officer DENY) | `take_snapshot` — list buttons; KHÔNG có nút admin/manager |
| B14a | Direct API attack: `POST /api/admissions/{id}/approve` | 403 Forbidden (Casbin) | Use `evaluate_script` để chạy fetch trực tiếp từ console |
| B15 | Click "Nhận xét duyệt" (claim) | `POST /api/admissions/{id}/claim` 200 | `assigned_reviewer_id=16` |
| B15a | Click "Bỏ nhận" | `POST /api/admissions/{id}/unclaim` 200 | – |
| B16 | (Wait) Switch persona Admin → publish-result để test B17 | – | – |

---

### Phase 4 — KẾT QUẢ ĐÃ CÔNG BỐ (B17–B22) — *cần Admin support*

> **Lưu ý**: officer KHÔNG publish được. Sau B12 → logout officer → login Admin → `POST /api/v2/admissions/{id}/publish-result` body `{notes}` → relogin Officer cho phần còn lại.

| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| B17 | (Admin đã publish) Officer mở profile | – | Badge "Trúng tuyển" hoặc "Trên Waitlist" hoặc "Không trúng" | – |
| B17a | Mỗi NV có DecisionBadge | – | NV1=admitted/NV2=skip HOẶC NV1=rejected/NV2=admitted | `take_screenshot` |
| B18 | Bell icon → thấy notification "Hồ sơ {id} có kết quả" | `GET /api/notifications` | Entry mới | – |
| B19 | Click "Gửi liên kết xác nhận" | `POST /api/admissions/{id}/send-confirmation` | 200, response trả `confirm_url`, dialog hiển thị link copy | – |
| B19a | Copy link → mở incognito → confirm magic link | `POST /api/admissions/confirm/{token}` | Page confirm page load, status → `confirmed` | – |
| B20 | Re-load Officer view | – | Badge "Đã xác nhận" | – |
| B21 | Officer xem profile | – | Tất cả tab read-only ngoại trừ Documents (nếu cấu hình) | – |
| B22 | (Switch Admin) Finalize → student row tạo | `POST /api/admissions/{id}/finalize` | status=`enrolled` | – |

---

### C-Block — Single-NV LEGACY (cho profile có `uses_choice_engine=false`)

Dùng round id=11 E2E_TEST (allow_multi_nv=false) hoặc admin trực tiếp tạo profile single-NV.

| Step | Action | Expected | Probe |
|---|---|---|---|
| C1 | Tạo profile mới với round E2E_TEST (single-NV) | `uses_choice_engine=false` | `get_network_request` |
| C1a | Step 4 render legacy form (NOT MultiNvScoresTab) | Dropdown "Phương thức xét tuyển" + "Tổ hợp môn" + score inputs theo subjects của tổ hợp | – |
| C2 | Submit → Admin/Manager click "Phê duyệt" trực tiếp (KHÔNG qua publish-result/cascade) | `POST /api/admissions/{id}/approve` body `{notes, version}`, status submitted → approved | – |
| C3 | Officer "Gửi liên kết xác nhận" như B19 | – | – |

---

### D-Block — EDGE CASES

#### D1 — Resubmit sau reject
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D1a | Profile id=16 đang `rejected` (officer 16) | `GET /api/admissions/16` | Banner "Bị từ chối" + reason hiển thị |
| D1b | Click "Nộp lại hồ sơ" (sau khi sửa field) | `POST /api/admissions/16/resubmit` body `{notes, version}` | 200, status → `resubmitted` |
| D1c | **Edge**: resubmit với version stale | – | 409 ConflictError |
| D1d | Switch Admin → review lại từ `resubmitted` | – | Admin có nút approve/reject |

#### D2 — Revision requested
> Profile state này KHÔNG có sẵn trong DB officer 16. Switch Admin tạo bằng cách: chọn profile submitted → click "Yêu cầu chỉnh sửa".
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D2a | (Admin) `POST /api/admissions/{id}/request-revision` body `{reason}` | – | state submitted → `revision_requested` |
| D2b | Officer mở profile | – | Banner reason + fields editable |
| D2c | Edit + Save | `PUT /api/admissions/{id}` | 200 (state vẫn `revision_requested`) |
| D2d | Click "Nộp lại" | `POST /api/admissions/{id}/resubmit` | state → `resubmitted` |

#### D3 — Minor correction (sau approve/confirm)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D3a | Profile state `approved` hoặc `confirmed` | – | – |
| D3b | Tab Documents/Personal → click "Hiệu chỉnh nhỏ" | – | MinorCorrectionDialog mở |
| D3c | Dropdown field — chỉ field ∈ `admission_path.minor_correction_allowed_fields` (JSONB allowlist) hiện | – | – |
| D3d | Submit | `POST /api/admissions/{id}/minor-correction` body `{version, reason, changes}` | 200, audit log entry |
| D3d-1 | **Edge**: gửi field ngoài allowlist (direct API) | – | 400 BusinessRuleViolation |

#### D4 — Withdraw applicant-initiated
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D4a | Profile draft/submitted/approved | – | – |
| D4b | Click "Rút hồ sơ" → dialog reason | `POST /api/admissions/{id}/withdraw` body `{reason}` | state → `withdrawn` (final) |
| D4c | Sau withdraw → tất cả button workflow disabled | – | `permissions.can_*` all false |

#### D5 — Magic-link timeout/resend
| Step | Action | Expected |
|---|---|---|
| D5a | Sau B19 send-confirmation → candidate chưa click sau 168h | Token expired |
| D5b | Officer click "Gửi lại link" lần 1 | Cooldown 5 phút bắt đầu |
| D5c | Click resend trong cooldown | UI block + tooltip "Chờ X phút" |
| D5d | Sau cooldown → resend 5/30/120/1440 ladder; cap 3 resend/24h | Hard-lock 30 lần |
| D5e | Copy-link button luôn available | Clipboard URL có token |
| D5f | **Known landmine**: per memory `magic-link-consume-shipped-generate-gap`, multi-action magic-link GENERATE endpoint chưa wire (consume side OK). Verify FE có button "Gửi link rút hồ sơ" / "Đổi ngành" cho candidate không. **Predict**: GAP. |

#### D6 — Validation block submit
| Step | Action | Expected |
|---|---|---|
| D6a | Step 7 "Kiểm tra toàn bộ" với profile thiếu document | `validation_errors[]` returned |
| D6b | Tab "Vấn đề cần sửa(N)" — count + grouped errors per step + click → redirect step có lỗi | – |
| D6c | Examples: missing CCCD doc, GPA < min, sai format CCCD, missing family | – |

#### D7 — Concurrent edit (optimistic locking)
| Step | Action | Expected |
|---|---|---|
| D7a | Mở profile id=17 ở Tab A (browser tab 1) | version=N |
| D7b | Mở cùng profile ở Tab B (incognito hoặc 2nd browser) | version=N |
| D7c | Tab A save → version N→N+1 | 200 |
| D7d | Tab B save (vẫn version=N) | 409 ConflictError, toast "Hồ sơ vừa được chỉnh sửa bởi người khác" |
| D7e | Tab B refresh → load N+1 → merge → save | 200 |

#### D8 — IDOR protection
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D8a | Officer truy cập `/admissions/39` (profile của officer 18, cùng unit 14) | `GET /api/admissions/39` | **Hmm**: 200 hay 404? Theo AUTHORIZATION_GUIDELINES, officer chỉ thấy assigned_to_self HOẶC cùng unit (tier 3). Cần verify behavior. |
| D8b | Officer truy cập `/admissions/{id_unit_khác}` | – | 404 (NOT 403) |
| D8c | Direct API `POST /api/v2/admissions/{id_unit_khác}/choices` | – | 404 ResourceNotFoundError |
| D8d | Direct API `PATCH /api/admissions/{id_unit_khác}` | – | 404 |

#### D9 — Add-choice gates fail
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| D9a | Add NV thứ 6 (max=5) | `POST .../choices` | 400 BusinessRuleViolation "Đã đạt tối đa 5 nguyện vọng" |
| D9b | Add NV trên profile của round `allow_multi_nv=false` (legacy) | – | 400 "Đợt {code} chỉ cho phép 1 nguyện vọng/hồ sơ" |
| D9c | Add NV trên profile state ≠ (draft, revision_requested) | – | 400 state guard |
| D9d | Add NV với `path_subject_group_config_id` không thuộc `admission_path_id` (direct API tamper) | – | 400 invariant fail |
| D9e | Add NV trùng (path, sg_config) | – | 409 UNIQUE constraint |

#### D10 — Document workflow edge
| Step | Action | Expected |
|---|---|---|
| D10a | Upload .exe | 415/422 ValidationError |
| D10b | Upload >10MB | 413 nginx |
| D10c | Manager (switch persona) verify-format → state `Verified`; reject với reason → `Rejected` | Officer thấy badge update + có thể re-upload |
| D10d | Officer reset document (nếu cho phép) | `POST .../documents/{code}/reset` 200 |

---

### E-Block — OFFICER LIMITS (RBAC matrix)

Mục đích: probe TỪNG endpoint forbidden cho officer. Dùng `evaluate_script` để fetch trực tiếp:
```js
fetch('http://localhost:8000/api/admissions/39/approve', {
  method:'POST',
  headers:{'Content-Type':'application/json','Authorization':'Bearer '+localStorage.getItem('access_token')},
  body:JSON.stringify({notes:'test',version:1})
}).then(r=>r.status)
```
Expected: **403 Forbidden** trên TẤT CẢ rows dưới đây.

| # | Endpoint | Method | Officer expected |
|---|---|---|---|
| E1 | `/api/admissions/39/approve` | POST | 403 |
| E2 | `/api/admissions/39/reject` | POST | 403 |
| E3 | `/api/admissions/39/request-revision` | POST | 403 |
| E4 | `/api/v2/admissions/39/publish-result` | POST | 403 |
| E5 | `/api/v2/admissions/39/waitlist-promote` | POST | 403 |
| E6 | `/api/admissions/39/override` | POST | 403 |
| E7 | `/api/admissions/39/finalize` | POST | 403 |
| E8 | `/api/admissions/39/drop` | POST | 403 |
| E9 | `/api/admissions/bulk/approve` | POST | 403 |
| E10 | `/api/admissions/bulk/reject` | POST | 403 |
| E11 | `/api/admissions/bulk/assign` | POST | 403 |
| E12 | `/api/admissions/39/documents/CCCD/verify-format` | PATCH | 403 |
| E13 | `/api/admissions/39/documents/CCCD/reject` | POST | 403 |
| E14 | `/api/payments` (record cash) | POST | 403 |
| E15 | `/api/payments/1/verify` | PUT | 403 |
| E16 | `/api/admin/users` | POST | 403 |
| E17 | `/api/v2/admin/years/2026/rounds` | POST | 403 |
| E18 | `/api/admission-config/paths` | POST | 403 |
| E19 | `/api/leads/bulk-assign` | POST | 403 (chỉ manager+) |
| E20 | `/api/leads/import` | POST | 403 (chỉ manager+) |

**Nếu BẤT KỲ row nào trả 200/201 → 🟥 BLOCKER RBAC bypass.**
**Nếu trả 404 (vì IDOR scope) thay vì 403 → ✅ acceptable per AUTHORIZATION_GUIDELINES.**

---

### F-Block — Thin-Client violations probe (Officer perspective)

| # | Component | File:Line | Probe action | Expected |
|---|---|---|---|---|
| F1 | SmartHeader | `frontend/src/components/officer/dashboard/SmartHeader.tsx:87` — `canChangeScope = user?.role === "manager"\|"admin"` | Login officer → load dashboard → thấy "Change scope" button không? | KHÔNG (vì officer ≠ manager/admin). **Known landmine** — DEFER (cần BE permission flag). |
| F2 | SmartConsultationStatusSelector | `frontend/src/components/common/selectors/SmartConsultationStatusSelector.tsx:145` — `isPrivileged = userRole === "admin"\|"manager"` | Officer mở Lead → status dropdown — privileged options hidden không? | – |
| F3 | OfficerDashboardClient | `OfficerDashboardClient.tsx:88` — role check | – | – |
| F4 | guideline page | `/guideline` route — ironic page về thin-client | Navigate `/guideline` | Verify content hiển thị guidelines (officer được xem) |
| F5 | KPI pages | `kpi-setup/page.tsx:31`, `kpi-hub/page.tsx:39` | Officer navigate `/admin/kpi-setup` | Bounce hoặc 403 — verify route guard |

---

## 3. PERSONA C — ACCOUNTANT (id=24 kpahdrim, unit 15)

### C.0 Login
1. `/login` → `kpahdrim` / `@Abc12345!`
2. Expect redirect `/dashboard` (NOT `/dashboard/officer`)
3. Sidebar: Finance modules visible, Admin pages KHÔNG hiển thị

### C.1 Finance Fees view (`/finance/fees`)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.1.1 | Navigate `/finance/fees` | `GET /api/fees` | List fees |
| C.1.2 | Mở fee detail | `GET /api/fees/{id}` | Detail load |
| C.1.3 | Click "Miễn giảm" / Waive | `POST /api/fees/{id}/waive` body `{reason}` | 200 |
| C.1.4 | **Edge** waive without reason | – | 422 |

### C.2 Invoices (`/finance/invoices`)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.2.1 | Navigate `/finance/invoices` | `GET /api/invoices` | List |
| C.2.2 | Click "Tạo hóa đơn" → form | `POST /api/invoices` | 201 |
| C.2.3 | Click "Phát hành" (issue) | `PUT /api/invoices/{id}/issue` | 200 |
| C.2.4 | Click "Hủy hóa đơn" (cancel) | `PUT /api/invoices/{id}/cancel` | **🟥 PROBE**: accountant có quyền cancel không? Per audit cancel = manager+ only. Expect 403. |

### C.3 Payments (`/finance/payments`)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.3.1 | Navigate `/finance/payments` | `GET /api/payments` | List |
| C.3.2 | Click "Ghi nhận thanh toán tiền mặt" → form | `POST /api/payments` body `{profile_id, amount, method:cash}` | 201 |
| C.3.3 | Pending payment → click "Xác nhận" | `PUT /api/payments/{id}/verify` | 200 |
| C.3.4 | Pending payment → click "Từ chối" | `PUT /api/payments/{id}/reject` | 200 |
| C.3.5 | Tạo "Payment intent" cho online | `POST /api/payments/intents` | 200 |

### C.4 Refunds
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.4.1 | `/finance/refunds` (nếu page exist) | `GET /api/refunds` | List |
| C.4.2 | "Yêu cầu hoàn tiền" | `POST /api/refunds/request` | 201 |
| C.4.3 | **Known landmine** REFUND_PROCESSED event dormant per memory — check notification fired không sau refund processed | – | – |

### C.5 Accounting periods
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.5.1 | `/finance/accounting` | `GET /api/accounting/periods` | List periods |
| C.5.2 | Close period | `POST /api/accounting/periods/{id}/close` | 200 |

### C.6 Installment plans
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| C.6.1 | Profile có installment | `GET /api/installment-plans/by-profile/{id}` | List schedule |
| C.6.2 | Trigger reminder | – | – |

### C.7 Accountant LIMITS — RBAC matrix
| # | Endpoint | Method | Accountant expected |
|---|---|---|---|
| C.7.1 | `/api/admissions/{id}/approve` | POST | 403 |
| C.7.2 | `/api/admissions/{id}/reject` | POST | 403 |
| C.7.3 | `/api/v2/admissions/{id}/publish-result` | POST | 403 |
| C.7.4 | `/api/v2/admissions/{id}/claim` | POST | 403 |
| C.7.5 | `/api/v2/admissions/{id}/choices` (CRUD) | POST | 403 |
| C.7.6 | `/api/admissions/{id}/request-revision` | POST | 403 |
| C.7.7 | `/api/admin/users` | POST | 403 |
| C.7.8 | `/api/leads/bulk-assign` | POST | 403 |

### C.8 IDOR
| Step | Action | Expected |
|---|---|---|
| C.8.1 | Accountant truy cập `/payments/{id}` của profile khác unit | 404 hoặc scoped to admin/unit |
| C.8.2 | Accountant truy cập `/finance/invoices?profile_id={khác unit}` | – |

### C.9 Thin-Client probe accountant
| Step | Component | Expected |
|---|---|---|
| C.9.1 | Sidebar: button "Tạo hồ sơ tuyển sinh", "Phê duyệt", "Override" | KHÔNG hiển thị |
| C.9.2 | Direct navigate `/admissions/17/edit` (officer 16 profile) | 404 redirect hoặc page show với fields disabled (read-only) |

---

## 4. CROSS-PERSONA — RBAC MATRIX cross-check

Sau khi chạy A/B/C → run script tổng hợp:

| Endpoint | Method | Admin | Manager (skip — không có user) | Officer | Accountant |
|---|---|---|---|---|---|
| POST `/api/admissions` | create | ✅ | – | ✅ | ❌ 403 |
| POST `/api/admissions/{id}/approve` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/admissions/{id}/override` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/admissions/{id}/finalize` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/v2/admissions/{id}/publish-result` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/v2/admissions/{id}/choices` | – | ✅ | – | ✅ (own/unit) | ❌ 403 |
| POST `/api/payments` | – | ✅ | – | ❌ 403 | ✅ |
| PUT `/api/payments/{id}/verify` | – | ✅ | – | ❌ 403 | ✅ |
| POST `/api/admin/users` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/v2/admin/years/{y}/rounds` | – | ✅ | – | ❌ 403 | ❌ 403 |
| POST `/api/admission-config/paths` | – | ✅ | – | ❌ 403 | ❌ 403 |
| GET `/api/admissions` | – | ALL | unit-scoped | assigned+unit | ❌ 403 hoặc empty |

**Output**: bảng final với checkmark/X từ thực tế test.

---

## 5. CROSS-PERSONA — IDOR MATRIX

Test scenarios: officer 16 (unit 14) truy cập tài nguyên khác unit/khác officer.

| Test | Resource | Expected |
|---|---|---|
| I1 | GET profile officer 16 → profile_id của officer 18 cùng unit 14 (vd id=39) | **Behavior?** Officer-as-self only? hay unit-wide? Tier 3 nói assigned + unit. Verify thật. |
| I2 | GET profile officer 16 → profile_id của unit khác (vd unit 15/19) | 404 |
| I3 | GET lead officer 16 → lead của officer khác cùng unit | 200 (cùng unit) hoặc 404 |
| I4 | GET lead officer 16 → lead unit khác | 404 |
| I5 | POST choice profile_id của unit khác | 404 |
| I6 | PUT /api/admissions/{id_khác_unit} | 404 |
| I7 | PATCH choice của profile khác unit | 404 |
| I8 | Accountant GET payment của profile khác unit | Scoped? 404? |
| I9 | Officer GET /api/admin/users/{id} (admin endpoint) | 403 |
| I10 | Officer GET /api/v2/admin/admission-backfill-exceptions | 403 |

**Critical**: per AUTHORIZATION_GUIDELINES, IDOR → **404** (không 403) để không leak resource existence.

---

## 6. CROSS-CUTTING PROBES

### 6.1 Real-time / Socket.IO
- Trong khi Officer đang edit profile 17 (Tab A), Admin trong Tab B sửa same profile → Tab A có toast realtime "Profile đã thay đổi" không?
- Memory `adm-032-doc-mutations-realtime` — 5 doc mutations emit `data_updated` event. Verify FE silent invalidate (300ms debounce).

### 6.2 Error toasts UX
- Mọi 403/404/409 phải hiển thị toast tiếng Việt rõ ràng, không leak stack trace
- Check `list_console_messages` — KHÔNG có raw error object

### 6.3 Mobile responsive (optional, tách `/mobile-audit` skill nếu cần)
- Resize 375x812 → critical pages load đúng

### 6.4 Performance hot paths
- `/admissions/{id}` load time < 2s
- `/admin/audit-logs` paginated, KHÔNG load all rows

---

## 7. POST-E2E CLEANUP

| # | Item |
|---|---|
| 1 | Profile mới tạo từ B3 (id ≥ 40) — nếu state `draft` thì delete OK; nếu submitted/approved/etc cần discussion với user (production-like data?) |
| 2 | Choice rows mới tạo (cleanup theo profile) |
| 3 | Documents uploaded — file storage cleanup `Backend_FastAPI/uploads/` |
| 4 | Payment/Invoice rows nếu tạo trong C-flow |
| 5 | Audit log entries — KHÔNG cleanup (giữ làm bằng chứng) |
| 6 | Reset password admin id=15 về cũ nếu user yêu cầu (hiện đang `@Abc12345!`) |
| 7 | Resend cap counter cho magic-link — reset Redis key nếu cần |

---

## 8. SUCCESS CRITERIA

Playbook xanh khi:
- ✅ B1–B22 happy path hoàn thành end-to-end (profile từ draft → enrolled)
- ✅ D1–D10 edge cases trả error code đúng spec
- ✅ E-block officer & C.7 accountant — 100% endpoints trả 403/404
- ✅ I1–I10 IDOR matrix — 100% trả 404 (không phải 403/200)
- ✅ F-block thin-client: minimum 0 NEW violations (known landmines SmartHeader/SmartConsultationStatusSelector OK ghi nhận)
- ✅ Console không có uncaught error
- ✅ Network: không có request 5xx

Findings ≥ 1 🟥 hoặc ≥ 3 🟧 → playbook FAIL, gửi report user trước khi tiếp tục.

---

## APPENDIX A — Quick login curl

```bash
# Admin
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=@Abc12345!" | jq .access_token

# Officer
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=nguyenhuuhieu&password=@Abc12345!" | jq .access_token

# Accountant
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=kpahdrim&password=@Abc12345!" | jq .access_token
```

## APPENDIX B — Endpoint reference (verified 2026-05-15)

**Admissions legacy** (prefix `/api/admissions`):
- CRUD: GET/POST/PUT/DELETE `/`, `/{id}`
- Workflow: `/submit`, `/approve`, `/reject`, `/request-revision`, `/resubmit`, `/minor-correction`, `/override`, `/withdraw`, `/finalize`, `/drop`, `/enroll`
- Claim: `/claim`, `/unclaim`
- Docs: `/documents/{code}/upload|paper-submitted|verify-format|reject|reset`
- Bulk: `/bulk/approve|reject|assign`
- Magic-link consume: `/confirm/{token}` (GET + POST)
- Confirmation send: `/send-confirmation`
- Stats: `/stats`, `/status-counts`, `/academic-years`, `/fee-status`, `/record-fee-payment`

**Admissions v2 multi-NV** (prefix `/api/v2/admissions`):
- Choices: POST `/{id}/choices` (create choice). PATCH/DELETE `/{id}/choices/{cid}`, PATCH `/{id}/choices/{cid}/scores`. **NO `GET /{id}/choices` endpoint** — choices read qua `GET /api/admissions/{id}` `.choices[]` field (eager-loaded by `_choices_eager_load_options()` chain). F13 verified 2026-05-16 — old table listing GET was incorrect.
- Result: `/{id}/publish-result` (T6 1-click), `/{id}/waitlist-promote` (T10), `/{id}/waitlist-reject` (T11 — shipped Wave 5 2026-05-16), `/{id}/admin-rollback` (T17)
- Note: **no explicit T2 `/start-review` endpoint** — publish_result auto-transitions `submitted → reviewing → engine cascade` atomic. State machine giữ `reviewing` làm intermediate state (F12 verified 2026-05-16 — không phải drift).

**Multi-action magic-link** (prefix `/api/v2/admissions/magic-link`):
- Consume side wired; **generate side GAP** per memory.

**Admin v2** (`/api/v2/admin/*`):
- `years/{year}/rounds` CRUD + `/rounds/{id}/extend`
- `casbin/reload`, `system-config`
- `admission-backfill-exceptions/*`

**Config** (`/api/admission-config/*`):
- `paths` (manager+), `criteria`, `subjects`, `years` (officer+)

**Finance**:
- `/api/fees` (officer+ read, `/calculate` self-profile, `/waive` accountant+)
- `/api/invoices` (accountant+ create/issue, manager+ cancel)
- `/api/payments` (accountant record cash, accountant/manager verify-reject, officer+ create intent)
- `/api/refunds` (accountant+)
- `/api/accounting/periods` (accountant+)

**Leads** (`/api/leads/*`):
- CRUD officer+, `/check-duplicate` officer+, `/bulk-assign` manager+, `/import` manager+, `/export` manager+, `/timeline|/insights|/audit-logs` officer+

---

# WAVE 2 EXPANSION — Sections H to P (added 2026-05-16)

## §H. PERSONA M — MANAGER (id=34 manager_qa, unit 14)

> Manager là persona quan trọng nhất bị thiếu trong Wave 1. Manager khác admin: scope theo unit (14 = Phòng Tuyển Sinh), KHÔNG cross-unit. Khác officer: thấy ALL profile/lead trong unit (officer chỉ thấy assigned).

### H.0 Login + scope verify
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.0.1 | Navigate `/login` → manager_qa / @Abc12345! | POST `/api/auth/login` | 200, role=manager, unit_id=14 | – |
| H.0.2 | Redirect `/dashboard` (NOT /dashboard/officer) | – | Manager landing có "Team dashboard" widgets | snapshot sidebar: Lead List + Pipeline + Admission + Finance (read) + Audit Logs |
| H.0.3 | Sidebar **không có**: Backfill Queue, Notification Templates (admin-only) | – | Verify role gate | snapshot |
| H.0.4 | Sidebar **có**: Lead Distribution Rules, KPI Hub (read) | – | – | – |

### H.1 Unit-scope IDOR contract
Mục đích: manager 14 see ALL profiles/leads of unit 14, KHÔNG see unit 15/19.

| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.1.1 | GET `/api/admissions` | – | List ALL profiles có lead.unit_id=14 (≥7 profiles officer 16 + officer 18) | network — count >=7 |
| H.1.2 | GET `/api/admissions/17` (officer 16's draft) | – | 200, full detail (unit-wide) | – |
| H.1.3 | GET `/api/admissions/39` (officer 18's submitted) | – | 200, full detail | – |
| H.1.4 | GET `/api/admissions/{id}` của unit khác (cần seed) | – | **404** (cross-unit IDOR) | – |
| H.1.5 | GET `/api/leads?page_size=10` | – | Trả leads of unit 14 only (NOT 391 of all units) | network count |
| H.1.6 | GET `/api/leads/{id}` cross-unit | – | **404** | – |

### H.2 Claim/unclaim workflow
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.2.1 | Mở `/admissions/39` (submitted, no reviewer assigned) | – | Button "Nhận duyệt" visible | – |
| H.2.2 | Click "Nhận duyệt" → confirm | `POST /api/admissions/39/claim` body `{version}` | 200, `assigned_reviewer_id=34`, badge "Bạn đang xét" | network response |
| H.2.3 | Refresh → button đổi thành "Bỏ nhận" | – | – | – |
| H.2.4 | **Race**: 2nd browser tab manager khác (admin) click claim → 409 ConflictError | – | – | – |
| H.2.5 | Click "Bỏ nhận" | `POST /api/admissions/39/unclaim` | 200, `assigned_reviewer_id=null` | – |
| H.2.6 | Officer (switch persona) cũng có thể claim (per Casbin) — admin/manager/officer all allowed? Verify | – | – | – |

### H.3 Approve / Reject workflow (single)
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.3.1 | Manager claim profile 39 trước | – | – | – |
| H.3.2 | Click "Phê duyệt (vượt điều kiện)" (vì bypass_warning=true) | – | AlertDialog F7 hiện | – |
| H.3.3 | Cancel dialog → KHÔNG approve | – | state vẫn submitted | – |
| H.3.4 | Tạo profile khác state submitted, eligible → approve clean | `POST /api/admissions/{id}/approve` body `{notes, version}` | 200, state → approved, `approved_by_id=34`, `approved_at` set | – |
| H.3.5 | Click "Từ chối" → dialog nhập reason ≥20 ký tự | `POST /api/admissions/{id}/reject` body `{reason, version}` | 200, state → rejected, `rejection_reason` saved | – |
| H.3.6 | **Edge**: reject reason 5 ký tự | – | 422 ValidationError | – |

### H.4 Request revision workflow
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.4.1 | Profile state submitted → click "Yêu cầu sửa" | – | Dialog nhập reason | – |
| H.4.2 | Submit reason | `POST /api/admissions/{id}/request-revision` body `{reason, version}` | 200, state → revision_requested, `revision_reason` saved | – |
| H.4.3 | Switch persona Officer (chính chủ) → mở profile → fields editable | – | Banner reason hiển thị | – |
| H.4.4 | Officer sửa + click "Nộp lại" | `POST /api/admissions/{id}/resubmit` | state → resubmitted | – |
| H.4.5 | Manager review again | – | Cycle close | – |

### H.5 Bulk operations
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.5.1 | `/admissions` list → checkbox 3 profiles draft cùng unit | – | Action bar hiển thị "Đã chọn 3" | – |
| H.5.2 | Click "Bulk approve" → confirm | `POST /api/admissions/bulk/approve` body `{profile_ids:[...], notes}` | 200, response `{succeeded:[], failed:[{id, reason}]}` | network — count partial success |
| H.5.3 | **Edge**: bulk approve profile thuộc unit khác → bị silently skip | – | failed array contains skipped ids | – |
| H.5.4 | **Edge**: bulk approve profile state ≠ submitted/resubmitted → state guard fail | – | failed array | – |
| H.5.5 | `POST /api/admissions/bulk/reject` body `{profile_ids, reason}` | – | Same shape | – |
| H.5.6 | `POST /api/admissions/bulk/assign` reviewer_id | – | All bulk-claimed (assigned_reviewer_id set) | – |

### H.6 Lead bulk-assign
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.6.1 | `/leads` list → multi-select 5 leads unit 14 | – | Action bar | – |
| H.6.2 | Click "Phân lại officer" → chọn officer 18 | `POST /api/leads/bulk-assign` body `{lead_ids:[], officer_id:18}` | 200, all 5 leads `assigned_officer_id=18` | – |
| H.6.3 | **Quota check**: nếu officer 18 đạt max_capacity → bulk skip | – | – | – |
| H.6.4 | **Edge**: bulk-assign cross-unit lead → forbidden hoặc silent skip | – | – | – |

### H.7 Lead distribution rules
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| H.7.1 | Navigate `/admin/distribution` | – | List rules | – |
| H.7.2 | Manager allowed read-only? hay create? Per policy template | – | Verify per role | – |
| H.7.3 | Trigger distribution preview | `GET /api/leads/distribution-preview` | – | – |

### H.8 Manager dashboard
| Step | Action | Expected |
|---|---|---|
| H.8.1 | Navigate `/dashboard` (manager view) | Team KPI widgets: team total, distribution, avg processing time |
| H.8.2 | KPI hub click | Per-officer breakdown |
| H.8.3 | Audit logs button | Manager can xem audit logs cho unit 14 |

### H.9 Manager DENY matrix (RBAC)
Manager KHÔNG được phép:
| Endpoint | Method | Expected |
|---|---|---|
| `/api/admin/users` POST | – | 403 (admin only create) |
| `/api/v2/admin/years/{y}/rounds` POST | – | 403 |
| `/api/admission-config/paths/{id}/activate` POST | – | 403 (per template comment "Admin only activate") |
| `/api/admissions/{id}/override` POST | – | **TEST**: per template line 393, manager CÓ override → expect 200/400 state-machine, NOT 403 |
| `/api/admissions/{id}/finalize` POST | – | 403 (admin only per Decision 10) |
| `/api/v2/admin/admission-backfill-exceptions` GET | – | 403 |
| `/api/v2/admin/casbin/reload` POST | – | 403 |
| `/api/admin/policies` POST | – | 403 |

---

## §I. FINANCE END-TO-END

> Maker-checker pattern: accountant record/issue → manager verify. Test bằng 2 personas tuần tự.

### I.0 Pre-condition
- Tìm profile state `approved`/`confirmed`/`enrolled` để tính fee — DB query: `SELECT id FROM admission_profile WHERE status IN ('approved','confirmed','enrolled');`
- Hoặc dùng admin override profile 42 → approved trước

### I.1 Fee calculate (officer / accountant)
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| I.1.1 | Login officer 16 → profile có state approved (cần setup) | – | – | – |
| I.1.2 | Profile detail → Step 6 Học phí → button "Tính học phí" | `POST /api/fees/calculate` body `{profile_id, installment_plan_id}` | 201, fee row created với `status=pending` | network — return fee.id |
| I.1.3 | Verify GET `/api/fees/summary/{profile_id}` | – | Fee summary: tuition, discount, payable | – |
| I.1.4 | **Edge**: profile state ≠ approved/confirmed/enrolled | – | 400 BusinessRuleViolation | – |
| I.1.5 | **Edge**: officer KHÔNG own profile → 404 IDOR | – | – | – |

### I.2 Discount / Waive (accountant / manager)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.2.1 | Switch accountant → mở fee detail | `GET /api/fees/{id}` | 200 |
| I.2.2 | Click "Miễn giảm" → form `{discount_type, amount, reason}` | `POST /api/fees/{id}/waive` | 200, fee.discount_amount updated |
| I.2.3 | **Edge**: discount > fee.total_amount → 422 | – | – |
| I.2.4 | Manager click "Hủy fee" | `POST /api/fees/{id}/cancel` body `{reason}` | 200, status → cancelled |
| I.2.5 | **Edge**: cancel fee đã có invoice issued → 400 BusinessRuleViolation | – | – |
| I.2.6 | Recalculate | `POST /api/fees/{id}/recalculate` | – |

### I.3 Invoice issue (accountant)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.3.1 | Fee detail → click "Tạo hóa đơn" | `POST /api/invoices` body `{fee_id, due_date, ...}` | 201, invoice.status=draft |
| I.3.2 | Click "Phát hành" | `PUT /api/invoices/{id}/issue` | 200, invoice.status=issued, invoice_number generated |
| I.3.3 | **Edge**: issue twice → 400 already issued | – | – |
| I.3.4 | Manager click "Hủy hóa đơn" (cancel) | `PUT /api/invoices/{id}/cancel` body `{reason}` | 200 (manager+ only per template line 431) |
| I.3.5 | Click "Áp dụng phạt trễ" | `POST /api/invoices/{id}/apply-penalty` | – |
| I.3.6 | **Edge**: accountant tries cancel → 403 (manager only) | – | – |

### I.4 Payment record + verify (maker-checker)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.4.1 | Accountant `/finance/payments` → "Ghi nhận thanh toán tiền mặt" | `POST /api/payments` body `{invoice_id, amount, method:cash, ...}` | 201, payment.status=pending |
| I.4.2 | **Edge**: amount > invoice.balance → 422 | – | – |
| I.4.3 | Same accountant verify own payment? | `PUT /api/payments/{id}/verify` | Per business rule (maker=checker allowed?) — verify behavior |
| I.4.4 | Switch manager → verify pending payment | `PUT /api/payments/{id}/verify` | 200, status=verified, invoice.balance decreased |
| I.4.5 | Manager reject payment | `PUT /api/payments/{id}/reject` body `{reason}` | 200, status=rejected |
| I.4.6 | Create payment intent (online) | `POST /api/payments/intents` | 200, returns redirect_url |
| I.4.7 | Get intent status | `GET /api/payments/intents/{id}` | – |
| I.4.8 | Webhook callback gateway (simulate VNPay IPN) | `POST /api/payments/callback/vnpay` | 200 hoặc signature fail → 401 |

### I.5 Refund flow
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.5.1 | Accountant request refund | `POST /api/refunds/request` body `{payment_id, amount, reason}` | 201, refund.status=pending |
| I.5.2 | Manager approve refund | `POST /api/refunds/{id}/approve` | 200, status=approved |
| I.5.3 | Accountant process refund | `PUT /api/refunds/{id}/process` body `{transaction_ref}` | 200, status=processed |
| I.5.4 | Verify REFUND_PROCESSED notification fired (per memory dormant flag — known gap) | – | Check `/api/notifications` officer/applicant; if no notification → 🟦 expected gap |

### I.6 Accounting period close
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.6.1 | Admin navigate `/finance/accounting` | `GET /api/accounting/periods` | List periods (open/closed) |
| I.6.2 | Click "Tạo kỳ" (admin) | `POST /api/accounting/periods` body `{period_code, start_date, end_date}` | 201, status=open |
| I.6.3 | **Edge**: tạo period overlap → 409 | – | – |
| I.6.4 | Click "Đóng kỳ" | `PUT /api/accounting/periods/{id}/close` | 200, status=closed, snapshot tạo |
| I.6.5 | After close: tạo invoice/payment trong period đó | – | 400 — period closed, không tạo được |
| I.6.6 | View period summary | `GET /api/accounting/periods/{id}/summary` | Aggregated revenue/refund/AR |

### I.7 Installment plan setup
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.7.1 | Admin `/admin/installment-plans` → list | `GET /api/installment-plans` | List plans (FULL/TWO_TERM/QUARTERLY etc.) |
| I.7.2 | Plan detail | `GET /api/installment-plans/{id}` | Schedule per semester |
| I.7.3 | Per-semester partial-block (memory `semester-tuition-refactor`) — test ember rule | – | Verify discount no carry-over |

### I.8 Tuition discount management
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| I.8.1 | Admin `/admin/tuition-discount` | – | List discount policies |
| I.8.2 | CRUD discount policy | – | – |

### I.9 Finance dashboard
| Step | Action | Endpoint |
|---|---|---|
| I.9.1 | Navigate `/finance` (accountant) | `GET /api/finance/dashboard` |
| I.9.2 | Verify widgets: revenue today, pending payments count, overdue invoices | – |

---

## §J. MULTI-NV RESULT PUBLISHING ENGINE

> Chỉ áp dụng cho profile `uses_choice_engine=true` (DOT_1 multi-NV). Sau Manager/Admin publish → engine cascade auto-evaluate từng NV theo priority.

### J.0 Pre-condition
- Profile multi-NV, state submitted/resubmitted, ≥1 choice, scores đầy đủ. Profile 42 sau khi nhập scores + submit qua officer.

### J.1 Publish-result trigger
| Step | Action | Endpoint | Expected | Probe |
|---|---|---|---|---|
| J.1.1 | Manager/Admin mở profile 42 (sau khi officer submit) | – | Button "Công bố kết quả" visible (vì uses_choice_engine=true) | – |
| J.1.2 | Click → AlertDialog cảnh báo "Hành động không thể hoàn tác" | – | – | – |
| J.1.3 | Confirm | `POST /api/v2/admissions/42/publish-result` body `{notes?}` | 200, state submitted→reviewing→result_published, engine cascade per NV | network — response trả `choices_decisions[]` |
| J.1.4 | Profile detail tự refresh | – | Header status badge "Đã công bố" hoặc "Trúng tuyển" | – |
| J.1.5 | Mỗi NV có DecisionBadge: admitted/waitlisted/rejected/skip | – | snapshot choice list — color badges | – |

### J.2 Engine cascade scenarios
| Scenario | Setup | Expected |
|---|---|---|
| J.2.1 All admit | 2 NV cùng pass eligibility | NV1=admitted, NV2=skip (engine chỉ chọn ưu tiên cao nhất) |
| J.2.2 NV1 reject, NV2 admit | NV1 GPA thấp, NV2 GPA ổn | NV1=rejected, NV2=admitted |
| J.2.3 All reject | Cả 2 fail | profile.status = rejected, choices both rejected |
| J.2.4 NV1 waitlist, NV2 admit | NV1 đầy quota, NV2 ổn | NV1=waitlisted (rank set), NV2=admitted |
| J.2.5 All waitlist | Tất cả NV đầy | profile state có thể "Trên waitlist" |

### J.3 Waitlist promote
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| J.3.1 | Profile có choice waitlist → manager click "Lên waitlist" | `POST /api/v2/admissions/{id}/waitlist-promote` body `{choice_id}` | 200, choice.decision=admitted, profile state update |
| J.3.2 | **Edge**: promote choice không trong waitlist → 400 | – | – |
| J.3.3 | Accountant try → 403 (per Casbin deny block) | – | – |

### J.4 Waitlist reject
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| J.4.1 | Click "Loại khỏi waitlist" | `POST /api/v2/admissions/{id}/waitlist-reject` body `{choice_id, reason}` | 200, choice.decision=rejected |

### J.5 Admin-rollback (T17)
> KHÔNG REVERSIBLE — rollback xóa toàn bộ decisions, profile về state draft.

| Step | Action | Endpoint | Expected |
|---|---|---|---|
| J.5.1 | Admin mở profile state result_published/admitted | – | Button "Rollback về Nháp" (admin only) | – |
| J.5.2 | Click → dialog cảnh báo "Mất tất cả decisions" | – | – |
| J.5.3 | Confirm | `POST /api/v2/admissions/{id}/admin-rollback` body `{reason}` | 200, state → draft, all choices.decision=pending |
| J.5.4 | Manager try → 403 (admin only) | – | – |
| J.5.5 | Officer try → 403 | – | – |

### J.6 Score snapshot status verify
| Step | Action | Expected |
|---|---|---|
| J.6.1 | Sau publish-result, GET profile | `score_snapshot_status` cho mỗi choice: passing/failing |
| J.6.2 | `eligibility_check_result` per choice (JSONB) chứa: required_subject_count, scoring_method, computed_score |

### J.7 Edge cases
- Engine timeout (DB lock contention) → state stays submitted, transactional rollback
- Profile thiếu choice → 400 "Hồ sơ đa nguyện vọng phải có ít nhất 1 nguyện vọng" (B12a)
- All choices rejected: state → rejected; vs at least 1 admitted: state → result_published

---

## §K. MAGIC-LINK SELF-SERVICE

> Memory `magic-link-consume-shipped-generate-gap-2026-05-15`: consume side wired, GENERATE side gap (no BE endpoint cho 3 actions self-service multi-action). Re-verify trong run này.

### K.1 Generate magic-link (officer/manager send to candidate)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| K.1.1 | Profile state admitted/confirmed → officer click "Gửi liên kết xác nhận" | `POST /api/admissions/{id}/send-confirmation` body `{action?:confirm}` | 200, response trả `confirm_url` |
| K.1.2 | Verify token created in DB: `SELECT * FROM admission_confirmation_token WHERE admission_profile_id={id}` | – | 1 row with action=confirm, ttl 168h |
| K.1.3 | **Multi-action probe**: gửi cho action=withdraw / change-program | – | Verify endpoint accept hay reject (per memory: generate side gap, có thể 400) |

### K.2 Consume magic-link (public, no auth)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| K.2.1 | Mở incognito → navigate `/magic-link/confirm/{token}` | `GET /api/admissions/confirm/{token}` | 200, page load với profile preview |
| K.2.2 | Verify CCCD last 3 digits → submit | `POST /api/admissions/confirm/{token}` body `{cccd_partial:'999'}` | 200, state admitted → confirmed |
| K.2.3 | **Edge**: CCCD sai | – | 401 unauthorized |
| K.2.4 | **Edge**: token expired (TTL > 168h) | – | 410 Gone |
| K.2.5 | **Edge**: token đã dùng | – | 409 already used |
| K.2.6 | Multi-action consume (withdraw): /api/v2/admissions/magic-link/withdraw/{token} | – | Per memory consume side OK |
| K.2.7 | Multi-action consume (change-program) | – | – |

### K.3 Resend cooldown ladder (memory `adm-023-028-magic-link`)
| Step | Action | Expected |
|---|---|---|
| K.3.1 | Click resend lần 1 | Cooldown 5 phút |
| K.3.2 | Click trong 5 phút | UI block + tooltip "Chờ X phút" |
| K.3.3 | Sau 5 phút resend lần 2 | Cooldown 30 phút |
| K.3.4 | Lần 3 | Cooldown 120 phút |
| K.3.5 | Lần 4+ | 1440 phút |
| K.3.6 | Hard-lock sau 30 lần | 423 Locked |
| K.3.7 | Cap 3/24h | 429 TooManyRequests |

### K.4 Copy-link
| Step | Action | Expected |
|---|---|---|
| K.4.1 | Dialog "Gửi liên kết" có button "Copy link" | Clipboard chứa confirm_url full token |

### K.5 Reminder beat (Celery)
| Step | Action | Expected |
|---|---|---|
| K.5.1 | Sau X giờ candidate chưa click → reminder gửi tự động | Check celery_beat schedule + outbox |
| K.5.2 | Pre-flight gate `lead_contact` action — nếu chưa setup → reminder block | Verify guard |

---

## §L. NOTIFICATIONS (Rules / Templates / Delivery / Consent)

### L.1 Admin Notification Rules CRUD
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| L.1.1 | Admin `/admin/notification-rules` | `GET /api/notification-rules` | List rules |
| L.1.2 | Click "Tạo rule" → form (event, channel, template, recipient) | – | – |
| L.1.3 | `GET /api/notification-rules/metadata` | – | Returns events list, channels, resolver_types cho form builder |
| L.1.4 | Submit create | `POST /api/notification-rules` | 201, rule row created |
| L.1.5 | Edit rule | `PUT /api/notification-rules/{id}` | 200 |
| L.1.6 | Disable rule | `PATCH /api/notification-rules/{id}` body `{is_enabled:false}` | – |
| L.1.7 | Delete rule | `DELETE /api/notification-rules/{id}` | 204 |
| L.1.8 | **Edge**: rule reference event không tồn tại trong SystemEvents enum → 400 | – | – |

### L.2 Templates
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| L.2.1 | `/admin/notification-templates` | `GET /api/notification-templates` | List |
| L.2.2 | CRUD template (subject, body, variables list) | – | – |
| L.2.3 | Preview template với dummy data | `POST /api/notification-templates/{id}/preview` | Returns rendered email/zalo body |
| L.2.4 | Test send (admin) | `POST /api/notification-templates/{id}/test-send` body `{recipient}` | 200, message sent |

### L.3 Delivery Ops
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| L.3.1 | `/admin/notification-deliveries` | `GET /api/notification-deliveries` | Outbox table |
| L.3.2 | Filter by status (pending/sent/failed) | – | – |
| L.3.3 | Click "Retry failed" cho 1 row | `POST /api/notification-deliveries/{id}/retry` | 200 |
| L.3.4 | Verify worker pickup → outbox row → sent | Celery log | – |

### L.4 Consent management
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| L.4.1 | `/admin/notification-consents` | `GET /api/notification-consents` | List user consent (email/zalo/sms toggle) |
| L.4.2 | User self-service `/settings/notifications` (or similar) | – | Toggle per channel |
| L.4.3 | If consent=false cho zalo → rule fire vẫn skip zalo channel | – | Verify outbox count = email only |

### L.5 Channel preferences impact
| Scenario | Setup | Expected delivery |
|---|---|---|
| L.5.1 | User A consent email=on, zalo=off; rule channels [email, zalo] | Email sent, Zalo skipped |
| L.5.2 | User B consent email=off, zalo=on | Email skipped, Zalo sent |
| L.5.3 | Critical notification (override_critical=true trong rule) | Sent regardless of consent |

### L.6 Inbox bell
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| L.6.1 | Officer click bell icon | `GET /api/notifications?page=1&page_size=10&unread_only=true` | Unread count badge |
| L.6.2 | Click notification → mark read | `POST /api/notifications/mark-as-read` body `{notification_ids:[]}` | – |
| L.6.3 | "Mark all as read" | `POST /api/notifications/mark-all-as-read` | – |
| L.6.4 | Delete notification | `DELETE /api/notifications/{id}` | 204 |

---

## §M. KPI TRACKING & DASHBOARDS

### M.1 KPI plan setup (admin)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| M.1.1 | `/admin/kpi-setup` | `GET /api/kpi-setup/` | List plans |
| M.1.2 | Tạo plan: metric (e.g., "admissions_approved"), period (month), target_value | `POST /api/kpi-plans` | 201 |
| M.1.3 | Assign plan to officer 16 | – | – |
| M.1.4 | Plan-month config: per month target có thể khác nhau | – | – |

### M.2 KPI hub (admin)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| M.2.1 | `/admin/kpi-hub` | – | Aggregated KPI view all officers |
| M.2.2 | Per-officer breakdown | – | – |

### M.3 Officer dashboard widgets
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| M.3.1 | Login officer 16 → `/dashboard/officer` | `GET /api/officer/dashboard` | Widget: assigned leads count, KPI progress, availability |
| M.3.2 | `GET /api/officer/stats` | – | Daily/weekly stats |
| M.3.3 | `GET /api/officer/leaderboard` | – | Team ranking |
| M.3.4 | `GET /api/officer/upcoming-activities` | – | Calendar events |
| M.3.5 | Toggle availability | `POST /api/officer/availability` | 200 |
| M.3.6 | `GET /api/officer/my-kpi-plan` | – | Assigned KPI plans + actual |
| M.3.7 | `GET /api/officer/recommendations` (Phase 7) | – | Recommended next actions |

### M.4 Monthly snapshot (Celery)
| Step | Action | Expected |
|---|---|---|
| M.4.1 | Wait for celery_beat trigger (monthly_snapshot task) | snapshot rows tạo trong kpi_monthly_snapshot |
| M.4.2 | Officer dashboard refresh → actual_value updated | – |
| M.4.3 | **Edge**: trigger manually qua admin | – |

### M.5 Manager team dashboard
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| M.5.1 | Manager `/dashboard` | – | Team KPI aggregated |
| M.5.2 | `GET /api/officer/team-stats` | – | Per officer stats for manager |

---

## §N. BULK OPERATIONS + IMPORT/EXPORT

### N.1 Lead import CSV
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| N.1.1 | Manager `/leads` → "Import" → download template | `GET /api/leads/import/template` | CSV template file |
| N.1.2 | Upload CSV 5 leads valid | `POST /api/leads/import` multipart | 200, `LeadImportResult{success_count:5, error_count:0}` |
| N.1.3 | Upload CSV với 3 valid + 2 invalid (sai format phone) | – | `{success_count:3, error_count:2, errors:[{row,field,message}]}` |
| N.1.4 | Upload CSV > 10MB | – | 413 nginx |
| N.1.5 | Upload .exe (sai format) | – | 415/422 |
| N.1.6 | Officer thử import | – | 200 per policy template (officer cũng có /api/leads/import POST) HOẶC 403 — verify hành vi |

### N.2 Lead export
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| N.2.1 | Manager `/leads` → "Export CSV" | `GET /api/leads/export/csv` | File download |
| N.2.2 | "Export Excel" | `GET /api/leads/export/excel` | – |
| N.2.3 | Export với filter (status, unit) | `GET /api/leads/export?status=qualified&unit_id=14` | Filtered results |
| N.2.4 | Officer export | – | Per policy (officer template có /api/leads/export GET) |

### N.3 Lead bulk-delete (manager+)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| N.3.1 | Multi-select 3 leads → "Xóa hàng loạt" | `POST /api/leads/bulk-delete` body `{lead_ids}` | 200, soft-delete (deleted_at set) |
| N.3.2 | Verify audit log entries per lead | – | – |

### N.4 Admission bulk
- Đã cover ở §H.5

### N.5 Admission profile export (nếu có)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| N.5.1 | Manager `/admissions` → "Export" | `GET /api/admissions/export` | File OR 404 if not implemented (gap) |

---

## §O. CTV (COLLABORATOR) + COMMISSION

### O.1 Public self-registration
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.1.1 | Incognito navigate `/register-ctv` | – | Form public |
| O.1.2 | Submit form (name, phone, email, bank info) | `POST /api/collaborators/register` (public) | 201, CTV row status=pending |
| O.1.3 | Redirect `/register-ctv/success` | – | – |

### O.2 Admin approve CTV
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.2.1 | Admin `/admin/collaborators` | `GET /api/collaborators` | List CTV |
| O.2.2 | Filter status=pending | – | – |
| O.2.3 | Click "Phê duyệt" | `POST /api/collaborators/{id}/approve` | 200, CTV → active, User account auto-created với role=collaborator |
| O.2.4 | CTV nhận email với password tạm | – | Verify notification fired |
| O.2.5 | Suspend CTV | `POST /api/collaborators/{id}/suspend` | – |
| O.2.6 | Reactivate | `POST /api/collaborators/{id}/reactivate` | – |

### O.3 CTV self-service
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.3.1 | CTV login → `/ctv` dashboard | – | Earnings, leads submitted, commission status |
| O.3.2 | Submit new lead | `POST /api/ctv/leads` body `{full_name, phone, offering_id, ...}` | 201, lead row referrer_id=ctv.id |
| O.3.3 | View claimed leads | `GET /api/ctv/leads` | – |

### O.4 Lead claim (CTV claim lead pool)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.4.1 | CTV claim lead unassigned | `POST /api/ctv/leads/{id}/claim` | 201, lead_claim row pending |
| O.4.2 | Admin review claim | `POST /api/collaborators/{id}/review-lead-claim` body `{lead_id, decision:approve, notes}` | – |
| O.4.3 | Approve → lead.referrer_id set, CTV eligible commission | – | – |
| O.4.4 | Reject → claim void | – | – |

### O.5 Commission policy (admin)
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.5.1 | `/admin/commission-policies` | `GET /api/commission-policies` | List |
| O.5.2 | CRUD policy: per program rate, fixed amount, tiered | `POST /api/commission-policies` | 201 |

### O.6 Commission record
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| O.6.1 | Trigger: lead → enrolled → commission record auto-created | – | Verify DB `commission_record` table |
| O.6.2 | Admin `/admin/commissions` | `GET /api/commissions` | List records |
| O.6.3 | Approve/pay record | – | status pending → approved → paid |
| O.6.4 | CTV view own commissions | `GET /api/ctv/commissions` | – |

---

## §P. CROSS-CUTTING WORKFLOWS

### P.1 Optimistic locking matrix
Probe each mutate endpoint with stale `version` to test 409 ConflictError:

| Endpoint | Has version field | Expected if stale |
|---|---|---|
| `PUT /api/admissions/{id}` | yes | 409 |
| `POST /api/admissions/{id}/approve` | yes | 409 |
| `POST /api/admissions/{id}/reject` | yes | 409 |
| `POST /api/admissions/{id}/override` | yes (per memory ADM-015) | 409 |
| `POST /api/admissions/{id}/claim` | yes | 409 |
| `POST /api/admissions/{id}/resubmit` | yes | 409 |
| `POST /api/admissions/bulk/approve` | ❓ — known gap per audit | TEST: per-profile version check OR none |
| `POST /api/admissions/bulk/reject` | ❓ | – |

### P.2 Audit log verify
| Action | Expected entity_audit_log entry |
|---|---|
| Admission approve | row {entity=admission_profile, action=approved, actor_id, old.status='submitted', new.status='approved'} |
| Profile override | row với reason mandatory |
| Fee waive | row finance audit |
| Payment verify | maker-checker audit |
| Lead bulk-assign | N rows (per lead) |
| Document upload | row |
| Magic-link consume | row action=confirmed_via_magic_link |

Probe: `GET /api/admin/audit-logs?actor_id={id}&entity_type=admission_profile` → count match expected.

### P.3 Socket.IO real-time
| Step | Action | Expected |
|---|---|---|
| P.3.1 | Tab A officer mở profile 42 | Socket connect |
| P.3.2 | Tab B admin edit profile 42 (PUT) | `data_updated` event fire |
| P.3.3 | Tab A receive event → query invalidate (300ms debounce per memory `adm-032-doc-mutations-realtime`) | UI refresh |
| P.3.4 | Cross-unit event scope: officer unit 14 KHÔNG receive event của profile unit 19 | Verify scope filter |

### P.4 Sessions + login history
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| P.4.1 | Login officer | – | Suspicious login alert nếu IP/device mới (per snapshot) |
| P.4.2 | `/settings/security` → active sessions | `GET /api/sessions` | List sessions per device |
| P.4.3 | Revoke 1 session | `DELETE /api/sessions/{id}` | 204 |
| P.4.4 | Revoke all (except current) | `POST /api/sessions/revoke-all` | – |
| P.4.5 | Login history | `GET /api/security/login-history` | List với IP, location, device, risk_score |
| P.4.6 | "Not me" report | `POST /api/security/not-me` body `{login_id}` | 200 |

### P.5 Lead pipeline stage transitions
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| P.5.1 | Lead status: new → contacted → qualified → interested → enrolled/declined | `PATCH /api/leads/{id}/status` body `{status, notes}` | 200 |
| P.5.2 | `POST /api/leads/{id}/action` body `{action_type, payload}` | – | – |
| P.5.3 | Allowed-next-status enforcement | `GET /api/pipeline/allowed-next-statuses?from={status}` | List valid next states |
| P.5.4 | **Edge**: skip stage (qualified → enrolled trực tiếp) | – | 400 BusinessRuleViolation |

### P.6 Consultation status
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| P.6.1 | `GET /api/leads/{id}/consultations` | – | List |
| P.6.2 | Create consultation | `POST /api/leads/{id}/consultations` body `{status, content, next_action}` | 201 |
| P.6.3 | Update | `PUT /api/leads/{id}/consultations/{cid}` | – |
| P.6.4 | Delete own | `DELETE /api/leads/{id}/consultations/{cid}` | – |
| P.6.5 | SmartConsultationStatusSelector privileged options (per F2 thin-client probe) | – | Verify admin/manager see extra |

### P.7 Admission survey/feedback
| Step | Action | Endpoint | Expected |
|---|---|---|---|
| P.7.1 | Profile state enrolled → survey trigger | – | Survey link sent |
| P.7.2 | Applicant submit feedback | `POST /api/admissions/{id}/survey` (verify exist) | – |

---

## SUCCESS CRITERIA — Wave 2 expanded

Playbook xanh khi:
- ✅ Wave 1: B1-B22 happy path + RBAC matrix + IDOR matrix pass
- ✅ Wave 2 sections H/I/J/K/L/M/N/O/P: ≥80% scenarios pass, 0 new BLOCKER, ≤3 new MAJOR
- ✅ Manager persona unit-scope verified (H.1)
- ✅ Finance maker-checker pattern OK (I.4)
- ✅ Multi-NV publish-result engine cascade tested ≥3 scenarios (J.2)
- ✅ Magic-link consume side full cycle (K.2); generate side gap documented nếu vẫn tồn tại
- ✅ Notification rule trigger → delivery → mark-read end-to-end (L.1+L.6)
- ✅ Bulk operations partial success handling (H.5 + N.1)
- ✅ Audit log entries verify ≥5 mutation actions (P.2)
- ✅ Optimistic locking 409 ≥3 endpoints (P.1)

---

*End of Wave 2 expansion.*

---

# WAVE 3 BUG-HUNTING — §Q (2026-05-16)

Allow mutation mode. 4 nhóm scenarios.

## §Q.1 ADVERSARIAL

### Q.1.1 Mass-assignment tampering
| # | Endpoint | Payload | Expected | Bug |
|---|---|---|---|---|
| Q.1.1a | PUT /api/admissions/42 | `{status:"approved",approved_by_id:15}` | 422/ignored | Flipped without /approve |
| Q.1.1b | PUT /api/admissions/42 | `{academic_year:2030}` | 422/ignored | Year overwritten |
| Q.1.1c | PUT /api/admissions/42 | `{applied_rules:{allow_unverified_submission:true}}` | 422/ignored | Bypass flag escalated |
| Q.1.1d | PUT /api/admissions/42 | `{is_dropped:true}` | 422/ignored | Drop via PUT |
| Q.1.1e | PATCH choices/14 | `{decision:"admitted",waitlist_rank:1}` | 422 | Officer admits manually |

### Q.1.2 IDOR escalation
| # | Test | Expected |
|---|---|---|
| Q.1.2a | Officer 16 PATCH /api/v2/admissions/39/choices/{any} | 404 |
| Q.1.2c | Accountant DELETE /api/v2/admissions/42/choices/{cid} | 403 |
| Q.1.2d | Officer GET /api/admin/audit-logs?actor_id=15 | 403 hoặc filtered |
| Q.1.2e | Officer PUT /api/users/me `{role:"admin"}` | 422/ignored |

### Q.1.3 SQL injection
| # | Test | Expected |
|---|---|---|
| Q.1.3a | GET /api/admissions?search=' OR '1'='1 | 200 normal |
| Q.1.3b | GET /api/leads?search=test'); DROP TABLE lead;-- | 200 escaped |
| Q.1.3c | GET /api/admin/users?role=officer' UNION... | 200 normal, no leak |

### Q.1.4 XSS
| # | Test | Expected |
|---|---|---|
| Q.1.4a | PUT family_info name=`<script>alert(1)</script>` → re-GET | HTML escaped |
| Q.1.4b | PUT notes/consultation với XSS payload | Sanitized |

### Q.1.5 Token/session
| # | Test | Expected |
|---|---|---|
| Q.1.5a | Use access_token sau logout | 401 |
| Q.1.5b | JWT tamper role officer→admin | 401 sig invalid |
| Q.1.5c | Reuse old refresh_token | 401 |

### Q.1.6 CSRF
| # | Test | Expected |
|---|---|---|
| Q.1.6a | POST mutate không X-CSRF-Token | 403 |
| Q.1.6b | Stale CSRF | 403 |

## §Q.2 EDGE CASES

### Q.2.1 Field validation
| # | Field | Values | Expected |
|---|---|---|---|
| Q.2.1a-d | CCCD | 3 chars / 15 chars / whitespace / unicode digits | 422 |
| Q.2.1e-g | full_name | "" / 1000 chars / "🎓📚" | 422/422/200 |
| Q.2.1h-j | phone | "0123" / 13 digits / "+84..." | 422 |
| Q.2.1k-n | dob | 1900 / 2030 / 0001 / invalid date | 422 |

### Q.2.2 Score boundary
| # | Values | Expected |
|---|---|---|
| Q.2.2a-f | -1 / 10.01 / "abc" / null / [] / 100 items | 422 |

### Q.2.3 Pagination
| # | Test | Expected |
|---|---|---|
| Q.2.3a-e | page=0 / -1 / page_size=10000 / page=99999 / sort_by=invalid | 422 hoặc 200 empty |

### Q.2.4 Bulk limits
| # | profile_ids | Expected |
|---|---|---|
| Q.2.4a-d | [] / dup / 1000 items / non-existent | 422 / partial |

### Q.2.5 File upload
| # | Test | Expected |
|---|---|---|
| Q.2.5a-f | 0-byte / 10MB exact / +1 byte / MIME spoof / path traversal / unicode name | per spec |

## §Q.3 STATE MACHINE

### Q.3.1 Risky transitions
| # | Transition | Expected |
|---|---|---|
| Q.3.1a | CONFIRMED→DRAFT (admin rollback) | 200 + audit + tokens invalidated |
| Q.3.1b | APPROVED→DRAFT | 200 + audit |
| Q.3.1c | ENROLLED→DRAFT | 400 (final) |
| Q.3.1d | WITHDRAW from CONFIRMED | per business |

### Q.3.2 Invalid jumps
| From → To | Expected |
|---|---|
| draft→approved | 400 |
| draft→enrolled | 400 |
| submitted→enrolled | 400 |
| approved→rejected | 400 |
| rejected→approved | 400 |
| withdrawn→any | 400 (final) |
| enrolled→any | 400 (final) |

### Q.3.3 Concurrent race
| # | Test | Expected |
|---|---|---|
| Q.3.3a | 2 admins approve concurrent | 1 success + 1 409 |
| Q.3.3b | Approve + reject race | 409 |
| Q.3.3c | Magic-link confirm + admin override race | 1 wins |

## §Q.4 DATA INTEGRITY

### Q.4.1 N+1 audit
- GET /api/admissions?page_size=50 timing — <500ms expected

### Q.4.2 FK cascade
- DELETE profile có choices → cascade or 409
- DELETE lead có profile → cascade or 409

### Q.4.3 Audit log gap
| Action | Expected entry |
|---|---|
| Choice CRUD | entity_audit_log row |
| Approve / Override | row với old/new |
| Document upload | row |

### Q.4.4 Optimistic locking matrix
| Endpoint | version check? |
|---|---|
| POST /admissions/bulk/approve | **UNKNOWN — probe** |
| PATCH /v2/admissions/{id}/choices/{cid} | **UNKNOWN — probe** |

### Q.4.5 Magic-link race
- 2 candidates click cùng token → 1 success + 1 400 already used
- Token expired exact lúc consume → 410 Gone

### Q.4.6 Webhook
- POST Zalo webhook không signature → 401
- Invalid HMAC → 401

### Q.4.7 Celery idempotency
- Enrollment task retry → 1 student record
- Notification dispatch x2 same dedupe_key → single

## §Q.5 RATE LIMIT
- POST /api/auth/login spam 100 → 429
- Magic-link generate spam → cooldown
- Magic-link consume wrong CCCD spam → hard-lock

## Success criteria
- 0 BLOCKER mới
- ≤ 3 MAJOR mới
- Resolve 5 HIGH-RISK: webhook sig, CONFIRMED→DRAFT cleanup, bulk-approve version, N+1 list, Celery idempotency

*End of §Q.*

---

# WAVE 6 — §R/§S/§T (a11y · mobile · performance) 2026-05-16

## §R UI Accessibility

### R.1 Lighthouse a11y audit (key pages)
- `/login`, `/dashboard/officer`, `/admissions`, `/admissions/{id}`, `/leads/{id}`, `/admin/users`
- Target: score ≥ 90/100. Detail trong `chrome-devtools-mcp-*/report.html`

### R.2 Custom DOM probe per page
- 0 images không `alt`
- 0 buttons không text/aria-label
- 0 inputs orphan (không label + không aria-label + không wrapped in label)
- Heading hierarchy không skip (h1 → h2 → h3, not h1 → h4)
- `<html lang="vi">` present
- Landmarks: `<main>`, `<nav>`, `<header>` exist
- Skip-link `<a href="#main-content">` present

### R.3 Keyboard navigation
- Tab through entire form → all inputs reachable, focus visible outline
- Esc closes dialogs
- Enter submits forms
- Arrow keys navigate dropdowns + tabs

### R.4 Color contrast
- Text < 18px need contrast ≥ 4.5:1
- Probe Lighthouse contrast audit + manual check status badges

## §S Mobile Responsive

### S.1 Viewport matrix
| Device | Width × Height | DPR | Touch |
|---|---|---|---|
| iPhone SE | 375×667 | 2 | yes |
| iPhone 13 | 390×844 | 3 | yes |
| iPhone 13 Pro Max | 428×926 | 3 | yes |
| iPad mini | 768×1024 | 2 | yes |
| iPad Pro | 1024×1366 | 2 | yes |

### S.2 Checks per viewport
- Body không có horizontal scroll
- Sticky bottom action bar fit trong width
- Modal/Dialog fit (max-width responsive)
- Touch targets ≥ 44×44 (Apple HIG)
- Sidebar collapse to hamburger ở <768px
- Form fields stack vertically (single-column)
- Tab nav scroll horizontally khi quá nhiều tabs
- Table không overflow (responsive table or card view)

### S.3 Mobile-specific probes
- Pull-to-refresh không trigger reload trang khi đang trong dialog
- Keyboard pop-up không che submit button
- Click-to-call link tel: + email link mailto:
- Bottom safe area iPhone X+ (notch padding)

## §T Performance

### T.1 API timing matrix (5 runs each, report p50/p95)
| Endpoint | Target p95 | Cold cache OK |
|---|---|---|
| GET /api/admissions list | < 200ms | < 500ms |
| GET /api/admissions/{id} | < 100ms | < 200ms |
| GET /api/leads list | < 200ms | < 500ms |
| GET /api/notifications | < 50ms | < 100ms |
| GET /api/officer/dashboard | < 300ms | < 800ms |
| GET /api/admin/users | < 150ms | < 500ms |

### T.2 Page load (Chrome MCP performance_start_trace)
- LCP target: < 2500ms (good), < 1200ms (fast)
- FID/INP: < 100ms
- CLS: < 0.1
- TTFB: < 600ms
- Trace cho profile detail + admissions list + officer dashboard

### T.3 Large payload stress
- GET /api/admissions?page_size=100 ≥ 500 profiles → response time + memory
- GET /api/leads?page_size=100 with 391 leads — gzip on?
- File upload 10MB document — measure end-to-end

### T.4 N+1 detection
- GET /api/admissions với selectinload → single query
- GET /api/leads với assigned_officer denormalized hoặc joined
- Profile detail có lazy-load tab data → measure tab switch latency

### T.5 Cache hit/miss
- First call cold → measure cold timing
- 4 subsequent calls → cache warm timing
- Compare delta (>10x = cache effective)

## Success criteria
- A11y: ≥ 90/100 trên 5 key pages, 0 orphan input, 0 missing alt
- Mobile: 0 horizontal scroll, ≥44px touch targets, modal fit
- Performance: LCP < 2500ms, p95 < 500ms cho all read endpoints

*End of Wave 6 §R/§S/§T*
