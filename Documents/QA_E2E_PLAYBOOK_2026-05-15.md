# QA E2E PLAYBOOK — Chrome MCP Dev Local
**Created**: 2026-05-15
**Target**: dev local stack (FE `http://localhost:3000`, BE `http://localhost:8000`)
**Mục tiêu**: phát hiện **gaps / RBAC / IDOR / Thin-Client violations** trên 3 personas.
**Output**: findings ghi vào `Documents/QA_E2E_FINDINGS_2026-05-15.md` (tạo khi chạy).

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
- Choices: POST/GET `/{id}/choices`, PATCH/DELETE `/{id}/choices/{cid}`, PATCH `/{id}/choices/{cid}/scores`
- Result: `/{id}/publish-result`, `/{id}/waitlist-promote`, `/{id}/waitlist-reject`, `/{id}/admin-rollback`

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

*End of playbook.*
