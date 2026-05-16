# QA E2E FINDINGS — 2026-05-15 → 2026-05-16

## 🌊 WAVE 7 — State race + File upload edge + Notification delivery (2026-05-16 ~19:00 UTC+7)

### Scope

| Mini-wave | Coverage | Method |
|---|---|---|
| W7-A State machine race | §Q.3.3a/b: 2-reviewer concurrent approve, approve+reject | curl parallel POST |
| W7-B File upload edge | §Q.2.5a-f: 0-byte, 10MB exact, 10MB+1, MIME spoof, path traversal filename, unicode filename | curl multipart |
| W7-C Notification delivery | §L.1-L.6 + §Q.4.6: rules CRUD invalid event, replay, mark-read, consent, webhook sig | curl admin+manager |

### Pre-condition

- Stack healthy: backend / postgres / redis / celery up
- Admin (id=15) + Manager `manager_qa` (id=34) logged in, password `@Abc12345!`
- Probed profile id=39 (status=submitted, uses_choice_engine=false) for race test
- Probed profile id=42 (status=draft, 6 doc checklist items) for file upload test

### Findings summary

| # | Sev | Module | Title |
|---|---|---|---|
| **W7-C.1** | 🟥 → ✅ | Notification | **FIXED 2026-05-16** — `mark-as-read {"notification_ids":[]}` no-op (trước marking ALL unread). Fix: `notification_repository.py:112` `if notification_ids is not None`. Anchor `test_qa_wave7_notif_and_race.py::test_mark_as_read_empty_array_is_noop`. |
| **W7-A.1** | 🟧 → ✅ | Admission state machine | **FIXED 2026-05-16** — Racing reviewer nhận 409 ConflictError thay vì 400. Fix: swap version check BEFORE state validation trong 4 services (approve, reject, request_revision, mark_student_dropped). W7-A.2 (version semantics) resolved cùng. 3 anchor tests. |
| **W7-B.c2** | 🟦 | Frontend i18n | Lỗi 10MB+1 hiển thị "10.0MB (max 10MB)" — rounding gây confusing UX |
| **W7-C.2** | 🟦 | Doc/playbook | Endpoint replay là `/replay` không phải `/retry` — playbook §L.3.3 stale |
| **W7-A.2** | 🟦 | Schema | Field `version` trong approve/reject schema required nhưng NOT enforced — race phụ thuộc state machine catch |
| **Q.4.6** | 🟦 | Zalo webhook | Returns 200 bất kể signature valid/missing — **INTENTIONAL** per Zalo OA spec (anti-retry-storm), code documented |
| **W7-B.a-f** | ✅ | File upload | 0-byte/spoof rejected qua magic-byte sniff; 10MB exact OK; 10MB+1 rejected; path traversal + unicode filename **neutralized** bởi server-side `{doc_code}_{uuid}` rename |

---

### W7-C.1 🟥 MAJOR — mark-as-read empty array marks ALL

**Endpoint**: `POST /api/notifications/mark-as-read`
**Payload**: `{"notification_ids":[]}`
**Expected**: No-op (mark 0 notifications) OR 400 validation
**Actual**: Marks **ALL** unread notifications của user thành read

**Repro evidence (2 distinct users)**:
```
ADMIN (id=15): unread 176 before → POST {notification_ids:[]} → "Marked 176" → unread 0 after
MANAGER (id=34): unread 27 before → POST {notification_ids:[]} → "Marked 27" → unread 0 after
```

**Root cause** — `Backend_FastAPI/app/repositories/notification_repository.py:103-117`:
```python
async def get_unread_for_user(self, user_id, notification_ids=None):
    filters = [self.model.user_id == user_id, self.model.is_read == False]
    if notification_ids:           # ⚠️ empty list is falsy → ID filter skipped
        filters.append(self.model.id.in_(notification_ids))
    query = select(self.model).where(and_(*filters))
    ...  # returns ALL unread for user khi notification_ids=[]
```

**Risk**:
- Client UX: user click "Mark as read" với 0 checkbox selected → wipe toàn bộ inbox unread state
- Not destructive (only read flag flipped) nhưng **irreversible from UI** — không có "mark as unread" bulk endpoint
- Defensive: invariant `[] payload → 0 affected` bị vi phạm

**Fix** (1 line):
```python
if notification_ids is not None:   # explicit None check instead of truthy check
    filters.append(self.model.id.in_(notification_ids))
```
Hoặc reject empty list ở Pydantic schema: `notification_ids: List[int] = Field(min_length=1)`.

**Note**: Memory `feedback_audit_before_fix` — đã verify code path trước, không chỉ symptom. Cùng pattern có thể tồn tại ở `bulk_delete_notifications` — cần audit `repo.bulk_delete_for_user()` xem có falsy-list bug tương tự không.

---

### W7-A.1 🟧 MAJOR — Concurrent approve race returns wrong status code

**Endpoint**: `POST /api/admissions/{id}/approve`
**Setup**: Profile 39 status=submitted version=5; admin + manager fire approve concurrent (~120ms apart)

**Q.3.3a (2 reviewers approve)**:
```
ADMIN POST approve version=5 → 200 OK, profile v5→6 approved
MGR   POST approve version=5 → 400 "Invalid transition: approved → approved.
                                       Allowed transitions from approved: confirmed, draft, overridden"
```

**Q.3.3b (approve + reject race)**:
```
ADMIN POST approve version=8 → 200 OK, v8→9 approved
MGR   POST reject version=8  → 400 "Invalid transition: approved → rejected"
```

**Expected**: 409 Conflict / Version Mismatch (optimistic lock). Spec ở `app/utils/exceptions.py`:
```python
ConflictError → 409   # optimistic locking
```

**Actual**: 400 "Invalid transition" — state machine guard catches the race **after** the first request commits, but:
1. **Wrong HTTP status** (400 vs 409) misleads frontend retry logic. 409 = stale, refetch + retry; 400 = invalid input, show validation error.
2. **Wrong error message** — UX says "Hồ sơ đang ở trạng thái không hợp lệ" thay vì "Hồ sơ đã được xử lý bởi reviewer khác, vui lòng refresh"
3. **Version field was sent but NOT enforced** — second request had same version=5/8 as first; if state machine had bidirectional transitions (e.g., `approved↔approved` for re-approval), race would silently corrupt state without optimistic lock guard

**Linked**: W7-A.2 (version field semantics)

**Fix options**:
- Service `approve_admission`/`reject_admission` raise `ConflictError` (→409) khi `profile.version != payload.version` BEFORE state machine check
- Hoặc map state machine `BusinessRuleViolation` → 409 when source==target_after_other_commit

---

### W7-A.2 🟦 INFO — `version` field required nhưng không enforce optimistic lock

`schemas.AdmissionApproveRequest` (và Reject) required `version: int`. Race test sent same version twice → both passed schema, không có DB version check → race chỉ được catch bởi state machine (transition validation). Nếu transition allow same-status loop (hypothetical re-approve), 2 reviewers approve sẽ silently overwrite nhau, audit log có 2 rows nhưng `assigned_reviewer_id` chỉ giữ người commit cuối.

**Recommend**: Promote `version` to true optimistic lock — `UPDATE profile SET status=..., version=version+1 WHERE id=:id AND version=:current_v` returning row count; 0 rows → `ConflictError`.

---

### W7-B File upload edge — security posture STRONG ✅

| # | Test | Expected | Actual | Status |
|---|---|---|---|---|
| W7-B.a | 0-byte file Content-Type=pdf | 400 reject | 400 "magic bytes không khớp" | ✅ |
| W7-B.b | 10MB exact PDF | 200 accept | 200 OK | ✅ boundary inclusive |
| W7-B.c | 10MB+1 byte PDF | 400 reject | 400 "File too large (10.0MB). Max 10MB" | ✅ rejected |
| W7-B.d | PNG content claimed Content-Type=pdf | 400 reject | 400 "Content-Type 'application/pdf' không khớp nội dung thực tế (image/png)" | ✅ ADM-019 sniff |
| W7-B.e | filename=`../../../../etc/passwd` (valid PDF body) | 200, but stored at safe path | 200, stored at `uploads/admissions/42/cccd_6079f9b75cf4.pdf` | ✅ filename overridden |
| W7-B.f | filename=`hồ_sơ_📄.pdf` unicode + emoji | 200, sanitized | 200, stored at `uploads/admissions/42/giay_khai_sinh_8016378bdf2a.pdf` | ✅ same pattern |

**Hardening confirmed**:
- Magic-byte sniff (ADM-019) — rejects content/MIME mismatch
- Server-side `{doc_code}_{uuid12}.{sniffed_ext}` filename — client-supplied filename completely ignored
- Extension derived from sniffed kind (not from `.pdf`/`.exe` suffix)
- 10MB boundary inclusive (file_size > MAX_FILE_SIZE)

**Single minor cosmetic finding W7-B.c2** 🟦:
- 10MB+1 byte (= 10485761 byte) hiển thị "File too large (10.0MB). Maximum allowed: 10MB"
- "10.0MB" do `{:.1f}` rounding của `10485761/(1024*1024) ≈ 10.000001` → "10.0"
- Confusing vì user thấy size == limit nhưng vẫn bị reject
- Fix: hiển thị byte count exact hoặc `{:.3f}` precision: "File too large (10.000MB > 10MB)"

---

### W7-C Notification delivery probes

| # | Endpoint | Method | Status | Notes |
|---|---|---|---|---|
| L.1 | `GET /api/notification-rules?page_size=5` | List | 200 (77 rules) | ✅ |
| L.1.3 | `GET /api/notification-rules/metadata` | Schema | 200 (58 events, 5 channels) | zalo_bot=planned/internal, sms=planned |
| L.1.8 | `POST /api/notification-rules` event=invalid | Edge | **400 "Unknown event 'xxx'. Verify event name is a valid SystemEvents member."** | ✅ fail-closed |
| L.2 | `GET /api/notification-templates` | List | 200 (52 templates) | ✅ |
| L.3 | `GET /api/notification-deliveries?status=failed` | List | 200 (31 failed, all `circuit_breaker_open` for email channel) | 🟨 see L.3-INFO below |
| L.3.3 | `POST /api/notification-deliveries/4523/replay` | Retry | 200 "Delivery replayed and enqueued" | ✅ (playbook listed `/retry` — stale, see W7-C.2) |
| L.4 | `GET /api/notification-consents` | List | 200 (392 consents) | ✅ |
| L.6 | `GET /api/notifications?unread_only=true` | Inbox | 200 (admin 176 unread, mgr 27 unread before W7-C.1 wipe) | – |
| L.6.2 | `POST /mark-as-read {ids:[]}` | Edge | **200 marked ALL** | 🟥 W7-C.1 BUG |
| Q.4.6 | `POST /api/webhooks/zalo` no/invalid sig | Webhook | 200 "probe" mode | ℹ️ INTENTIONAL |

**L.3-INFO** 🟦: 31/31 failed deliveries có error `circuit_breaker_open` cho channel email — circuit breaker đang tripped trên SMTP provider, không có deliveries nào fail vì lý do khác (timeout/auth/bounce). Check `GET /api/notification-deliveries/circuit-breakers` để xem trạng thái breaker hiện tại + manual reset endpoint `POST /circuit-breakers/{channel}/reset`. Nếu breaker chronically open → escalate provider SMTP creds / quotas.

**Q.4.6** ℹ️ **NOT a bug**: Zalo webhook `POST /api/webhooks/zalo` returns 200 + `{status:ok,mode:probe}` cho unsigned + invalid-signature requests. Comment trong code (`zalo_webhooks.py:42-46`) giải thích đây là intentional per Zalo OA webhook spec — "endpoint phải return HTTP 200 within 2 seconds, signature verification optional". Best-effort: signature được log nhưng không reject. Nếu Zalo siết signature requirement, flip 1 gate ở line 69-74.

### W7-C.2 🟦 INFO — Playbook stale endpoint

Playbook §L.3.3 ghi `POST /api/notification-deliveries/{id}/retry` — endpoint thực tế là **`/replay`** (`notification_delivery_ops.py:253`). Update playbook để tránh confusion cho QA agent tiếp theo.

---

### Wave 7 success criteria recap

- ✅ 0 BLOCKER — no production crash / data corruption / auth bypass
- 🟥 1 MAJOR (W7-C.1) — mark-as-read empty array marks ALL (1-line fix)
- 🟧 1 MAJOR (W7-A.1) — wrong status code for concurrent approve race (UX + retry logic)
- 🟨 0 elevated
- 🟦 3 INFO — version semantic, error message rounding, playbook stale

### Suggested fix order

1. **W7-C.1** (urgent, 1-line) — `if notification_ids is not None` in `notification_repository.py:112`. Add anchor test `test_mark_as_read_empty_array_marks_zero()`. Audit `bulk_delete_for_user` for same pattern.
2. **W7-A.1** (medium) — promote `version` field to true optimistic lock in `approve_admission` + `reject_admission` services; raise `ConflictError(409)` on mismatch before state-machine guard fires.
3. **W7-B.c2** (cosmetic) — better error message formatting.
4. **W7-C.2** — sed playbook `/retry` → `/replay`.

---

## 🎨 WAVE 6 — §R/§S/§T a11y + mobile + performance (2026-05-16 ~17:00 UTC+7)

### Coverage matrix

| Section | Test | Result |
|---|---|---|
| §R.1 Lighthouse a11y `/admissions/42` | desktop snapshot | **86/100** (7 failed audits) |
| §R.2 Custom DOM probe | manual scan | 0 img/button/link issues; **2 orphan inputs** |
| §R.2 Landmarks | main/nav/banner/skip-link | ✅ all present + `lang="vi"` |
| §S.1 Mobile viewport 375×812 | emulated iPhone, no body overflow | ✅ |
| §S.2 Touch targets | sidebar nav < 44×44 | **🟧 8+ targets 36×36** |
| §S.2 Action bar mobile | sticky bottom w=549 > viewport 375 | **🟧 overflow ngang** |
| §S.2 Sidebar collapse | hamburger present | ✅ |
| §T.1 API timing 10 endpoints (5 runs each) | p50/p95 | mostly < 200ms ✅ |
| §T.1 /api/officer/dashboard cold | first call | 🟧 433ms (then 210ms warm) |
| §T.1 /api/admin/users cold | first call | 🟧 1.8s (then 44ms warm) |
| §T.2 LCP profile detail | trace | ✅ 1352ms (good range) |
| §T.2 CLS | trace | ✅ 0.04 (excellent <0.1) |
| §T.2 TTFB | trace | 381ms — borderline |

### NEW findings (6)

| # | Sev | Module | Title | Detail |
|---|---|---|---|---|
| **R-BUG-1** | 🟧 | Admission (Step 1 Personal) | **2 input orphan không label** | PUT /admissions/{id} Step 1 personal-info có 2 textboxes thiếu label/aria-label: "Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố" và "Số nhà, tên đường". Chỉ có placeholder. Screen reader user sẽ không biết field nào. Fix: add `<label>` hoặc `aria-label`. |
| **R-INFO-1** | 🟦 | Frontend global | Lighthouse a11y 86/100 — 7 audit fails | Cần inspect HTML report tại `chrome-devtools-mcp-Qd8qsF/report.html` để biết chi tiết 7 fails (color contrast, ARIA roles, focus order...). |
| **S-BUG-1** | 🟧 | Frontend layout | **Sticky action bar overflow ngang mobile** (375px viewport) | DIV `.flex items-center gap-3` w=549px > viewport 375px → users phải scroll ngang để thấy buttons. Trên iPhone SE/13 cũ unusable. Fix: action bar responsive (stack vertically <640px hoặc reduce button labels to icons). |
| **S-BUG-2** | 🟧 | Frontend sidebar | **Touch targets 32-36×36 < 44×44 Apple HIG** | Sidebar nav links 36×36, logo 32×32. Mobile tap accuracy thấp, accidental taps frequent. Fix: increase padding sidebar items mobile, hoặc collapse to hamburger ở all mobile widths (hiện vẫn show ở >mobile widths). |
| **T-INFO-1** | 🟨 | Backend | `/api/admin/users` cold path 1.8s | First call sau backend restart slow → cached subsequent calls 44ms (40x faster). Có thể do query không có index, Casbin re-init, hoặc lazy-loaded relationships. Phase 1 P2 audit recommended. |
| **T-INFO-2** | 🟨 | Backend | `/api/officer/dashboard` p95 433ms cold | Aggregation query (lead stats + KPI). Acceptable nhưng > 300ms target. Consider materialized view hoặc Redis cache 30s. |

### Strong scores

| Metric | Value | Target | Status |
|---|---|---|---|
| Lighthouse Best Practices | 100 | ≥90 | ✅ |
| Lighthouse a11y | 86 | ≥90 | 🟨 |
| LCP profile detail | 1352ms | <2500ms good / <1200ms fast | ✅ good |
| CLS profile detail | 0.04 | <0.1 | ✅ excellent |
| TTFB | 381ms | <600ms | ✅ |
| API list endpoints p95 | <115ms | <500ms | ✅ |
| API detail endpoints p95 | <61ms | <200ms | ✅ |
| API notifications | <25ms | <100ms | ✅ |
| Body overflow X mobile 375 | 0px | 0 | ✅ |
| Sidebar hamburger collapse | works | works | ✅ |
| `lang="vi"` page declaration | present | present | ✅ |
| Skip-link to main content | present | present | ✅ |

### Wave 6 execution log
- **16:50** Login officer + navigate /admissions/42 (after Wave 5 token expiry)
- **16:52** Lighthouse desktop snapshot: 86 a11y / 100 BP / 80 SEO. 7 failed audits.
- **16:53** Custom DOM probe: 0 img/button/link issues; 2 orphan inputs (address fields)
- **16:55** Mobile emulate 375×812: no body overflow, but action bar 549px overflow + 8 small touch targets
- **16:58** Performance API timing: 10 endpoints × 5 runs. Most <100ms. Outliers: dashboard 433ms cold, admin/users 1.8s cold.
- **17:00** Performance trace profile detail: LCP 1352ms (TTFB 381 + render 971), CLS 0.04

### Wave 6 follow-ups
1. **R-BUG-1 orphan inputs** 🟧 — add `<label htmlFor="...">` hoặc `aria-label` cho 2 address fields Step 1.
2. **S-BUG-1 action bar overflow mobile** 🟧 — responsive layout: icon-only mode <640px, hoặc 2-row stack.
3. **S-BUG-2 touch targets** 🟧 — increase padding sidebar mobile (min-height: 44px).
4. **T-INFO-1 admin/users cold 1.8s** 🟨 — profile query, add DB index nếu thiếu, hoặc warmup script.
5. **T-INFO-2 officer/dashboard 433ms** 🟨 — Redis cache 30s cho aggregation widgets.
6. **R-INFO-1 Lighthouse 7 fails** 🟦 — inspect HTML report cho detailed audit list.

---

## 🎯 WAVE 5 BUG HUNTING — §Q Adversarial (2026-05-16 ~16:00 UTC+7)

### Coverage matrix
33 scenarios across 4 categories. **32 mitigated · 1 minor bug · 1 minor leniency · 1 by-design info**.

| Section | Run | Pass | Bugs |
|---|---|---|---|
| §Q.1.1 Mass-assignment (status/year/applied_rules/is_dropped) | 4 | 4 ✅ | 0 |
| §Q.1.2 IDOR escalation (cross-officer PATCH/admin audit/role escalate) | 3 | 3 ✅ | 0 |
| §Q.1.3 SQL injection (OR 1=1, DROP TABLE, UNION SELECT password_hash) | 3 | 3 ✅ | 0 |
| §Q.1.5 JWT tamper (role officer→admin no re-sign) | 1 | 1 ✅ | 0 |
| §Q.1.6 CSRF (POST no X-CSRF-Token) | 1 | 1 ✅ | 0 |
| §Q.2.1 Field validation boundary | 8 | 6 ✅ + 1 ⚠️ + 1 🟧 | 1 |
| §Q.2.3 Pagination edge | 5 | 4 ✅ + 1 🟨 | 1 |
| §Q.2.4 Bulk schema discovery | 1 | 1 ✅ | 0 |
| §Q.3 State machine invalid jump | 2 | 2 ✅ | 0 |
| §Q.4.3 Audit log gap | 1 | 1 ✅ | 0 |
| §Q.4.4 Bulk version locking | 1 | 1 ✅ | 0 |
| §Q.4.5 Magic-link race (5 parallel) | 1 | 1 ✅ | 0 |
| §Q.4.6 Webhook signature | 2 | 2 🟦 by-design | 0 |
| §Q.5 Rate limit login spam | 1 | 1 ✅ (429 from req 3) | 0 |

### NEW findings (3)

| # | Sev | Module | Title | Detail |
|---|---|---|---|---|
| **Q-BUG-1** | 🟧 → ⚠️ | Admission | **NOT REPRODUCIBLE 2026-05-16** | Repro test (dev current HEAD post-W4-1 hotfix): PUT emoji+version → **200 OK**; PUT emoji+missing-version → **422 validation** (clear "Field required" message, KHÔNG phải 400 parse). Có thể QA hit transient state, hoặc đã fixed bởi unrelated change. Source FastAPI `routing.py:369` chỉ raise 400 khi `request.json()` fail (malformed JSON, not unicode content). |
| Q-INFO-1 | 🟨 → ✅ | Admission | **FIXED 2026-05-16** `GET /api/admissions?sort_by=invalid_field` → 200 silent ignore + `order=BAD` silent ignore. Fix: promote `sort_by: str` + `order: str` → `Literal[4 valid] + Literal["asc","desc"]` trong admissions.py:102-103. FastAPI auto-422 với clear "Input should be ..." message. Anchor `test_admissions_list_query_validation.py` (8 tests) lock. Mirror FE Zod `AdmissionListParams.sort_by` (đã sẵn enum) — không phá FE. |
| Q-INFO-2 | 🟦 | Notifications | Zalo webhook accept no-sig requests (BY DESIGN) | `zalo_webhooks.py:43-44`: Zalo OA spec không bắt buộc HMAC. Backend log `signature_present` cho observability. CAVEAT: nếu handler trigger state mutations, kẻ tấn công inject fake events được — audit handler logic riêng. |

### Strong defenses verified (33 probes)

| Attack vector | Mitigation |
|---|---|
| Mass-assignment | Pydantic schema whitelist — 4/4 extra fields silently ignored ✅ |
| SQL injection 3 payloads | SQLAlchemy parameterized; DB intact (lead 392 rows post-test) ✅ |
| JWT tamper role escalation | HMAC signature verification → 401 ✅ |
| CSRF | X-CSRF-Token required → 403 ✅ |
| IDOR cross-officer | 404 (NOT 403, per AUTHORIZATION_GUIDELINES) ✅ |
| Self-elevate via PUT /users/me | 405 Method Not Allowed ✅ |
| CCCD/phone/dob boundary | 422 validation ✅ |
| Pagination DoS page_size=10000 | 422 (le=100 schema) ✅ |
| Invalid state jump draft→enrolled/approved | 400 clean Vietnamese msg + allowed transitions ✅ |
| Bulk version locking | Per-item `{profile_id, version}` schema; per-item conflict ✅ |
| Magic-link double-consume race | ADM-013 lock + `confirmed_at` predicate → 1/5 success ✅ |
| Login bruteforce 20 attempts | Rate limit 429 from req 3 ✅ |
| Audit log | entity_audit_log: AdmissionProfile created/updated/status_changed với actor_user_id ✅ |

### Wave 5 execution log
- **15:45** Q.1.1 mass-assignment 4 fields → all silently ignored (verified post-GET)
- **15:47** Q.1.2/1.5/1.6: 403/401/405/422 đúng
- **15:50** Q.1.3 SQLi 3 payloads → 200 escaped, lead table intact
- **15:53** Q.2.1 emoji discovery → 400 parse error (BUG)
- **15:55** Q.2.4 bulk schema: `items: List[{profile_id, version}]` — W2-3 finding revisited
- **15:58** Q.4.5 magic-link race 5 parallel → 1 success + 4 already-used (ADM-013 lock perfect)
- **16:00** Q.4.6 webhook by-design per Zalo spec, downgrade HIGH→INFO
- **16:02** Q.5 rate limit → 429 from req 3

### Wave 5 test artifacts
- Profile 20: `draft` → `withdrawn` via Q.4.5 race test (consume succeeded). Restore SQL nếu cần.
- Profile 42: version bumped (3+ PUT), name="Nguyễn Văn Test" applied.
- Lead 392 (was 391) — 1 lead added during Wave 4 session.

### Wave 5 follow-ups (priority)
1. **Q-BUG-1 emoji parse** 🟧 — find body parser/Pydantic validator restricting 4-byte UTF-8. Likely 1-2 line fix.
2. **Q-INFO-1 sort_by** 🟨 — add `Literal["created_at","updated_at","status",...]` enum vào pagination schema (5-min).
3. **Q-INFO-2 Zalo webhook handler** 🟦 — audit `zalo_webhook` handler nội bộ; nếu có state mutation, add allowlist sender/app_id check.

---

## 🔬 WAVE 4 — Chrome MCP runtime re-test (2026-05-16 ~15:30 UTC+7)

### Browser-verified admission fixes

| # | Test | Evidence (snapshot UID) | Status |
|---|---|---|---|
| F4 | Officer sidebar không có "Backfill Queue" | uid=27_3..27_27 — sidebar 7 nav items + 5 recent pages (Performance Dashboard/39/42/Create/410), không có Backfill Queue | ✅ |
| F1+F2 | Profile 42 Step 4 → "Thêm nguyện vọng" dialog | uid=30_0 dialog "Thêm nguyện vọng NV4" + cascading dropdown "Ngành / Phương thức xét tuyển", KHÔNG còn error "Không xác định được đợt" | ✅ |
| F2 list | "Danh sách nguyện vọng (3/5)" với NV1+NV2+NV3 render đầy đủ | uid=29_4..29_55 — 3 choices với drag handles + edit/delete buttons; NV2+NV3 scores hiển thị `math/physics/chemistry` 7.00/7.50/8.00 và `math/chemistry/english` 7.00/7.50/8.00 | ✅ |
| W2-1 officer | "Gửi link rút hồ sơ" dialog mở với URL + Copy | uid=32_0 dialog "Liên kết rút hồ sơ tuyển sinh" + URL `http://localhost:3000/magic-link/withdraw/uXEM8R...` + Copy + Close. Expiry 23/5/2026 (7 ngày) | ✅ |
| W2-1 admin | Admin profile 39 also có "Gửi link rút hồ sơ" button | uid=33_220 visible cho admin trên submitted profile | ✅ |
| F6 | Admin trên profile 39 KHÔNG có Override button (status=submitted, only approved → overridden) | uid=33_215..219 chỉ có: Tiếp tục/Phê duyệt vượt điều kiện/Từ chối/Yêu cầu sửa/Nhận duyệt — không có Override (correct per state machine) | ✅ |
| F7 | Admin profile 39 banner ⚠️ + "Phê duyệt (vượt điều kiện)" | uid=33_140-148 banner "⚠️ Hồ sơ này được nộp trong chế độ bỏ qua xét duyệt sơ bộ" + 7 lỗi count; uid=33_216 button "Phê duyệt (vượt điều kiện)" với haspopup="dialog" | ✅ |

### 🟥 BLOCKER REGRESSION found + FIXED in Wave 4

| # | Sev | Title | Root Cause | Fix |
|---|---|---|---|---|
| **W4-1** | 🟥 → ✅ | **ALL admission GET endpoints 500 "invalid policy size"** | Casbin row id=924 `role:manager / /api/leads/export / GET` có v3 (eft) NULL. Casbin model `p = sub, obj, act, eft` requires 4 fields; NULL eft raises RuntimeError ở matcher. Row được insert trong wave fix W2-3 (PR #297 qae2e01) nhưng INSERT chỉ 4 cột (ptype, v0, v1, v2) thiếu v3. | **Operational** (dev): `UPDATE casbin_rule SET v3='allow' WHERE id=924`; reload Casbin → 200 OK. **Source fix** (PR hotfix qae2e02): (1) Patch qae2e01 source INSERT include v3='allow' cho fresh installs; (2) qae2e02 migration sweep `UPDATE WHERE v3 IS NULL` defense-in-depth cho existing envs (prod chạy chain qae2e01→qae2e02 → guarantee 0 NULL trước Casbin reload); (3) Anchor test `test_no_policy_rows_with_null_eft` query live DB ngăn future regression; (4) Memory `casbin-insert-must-include-eft` lock pattern. |

### Wave 4 execution log
- **15:25** Login officer → sidebar verified clean (F4)
- **15:26** Navigate `/admissions/42` → page CRASH với 500 error. Console: `API Error (500) ... <AdmissionDetailPageContent>` → ErrorBoundary catch
- **15:27** Probe BE: ALL profiles (16/17/18/20/39/42) → 500. Logs reveal: `RuntimeError: invalid policy size`
- **15:28** Audit casbin_rule: found row id=924 với v3 NULL (manager export endpoint, recent fix gone wrong).
- **15:29** Fix v3='allow' + reload Casbin → all profiles 200
- **15:30** Reload browser → profile 42 load OK; Step 4 → "(3/5)"; AddChoiceDialog NV4 mở OK; "Gửi link rút hồ sơ" dialog OK
- **15:32** Admin login → profile 39 → F7 banner + warning button OK

### Final admission status sau Wave 4

| Layer | Status |
|---|---|
| All Wave 1-2 admission BE fixes (F1, F2, F3, F5, F6, F7, F8) | ✅ Runtime-verified browser |
| Wave 3 user fix W2-1 (multi-action magic-link generate) | ✅ Runtime-verified browser (URL generated + copy dialog OK) |
| Wave 4 regression W4-1 (Casbin v3 NULL) | ✅ Fixed in DB + reload |
| **Admission module open bugs** | **0** |

### Wave 4 cleanup notes

- Row 924 trong casbin_rule có template_id=NULL (manual insert, không track template lineage). Cần verify `policy_templates.py` có entry tương ứng và sync proper format (`eft: "allow"`) khi seed lại từ template — nếu không sẽ tái xuất hiện sau lần reset Casbin tiếp theo.
- Profile 16 vẫn ở state `withdrawn` (sau Wave 3 magic-link consume test). Restore nếu cần data fixture cũ.
- Profile 42 hiện 3 choices (NV1 no-scores, NV2 A00, NV3 D07).

---

## 🔁 WAVE 3 RE-TEST — Admission module sau user fix (2026-05-16 ~11:30 UTC+7)

### Kết quả

| # | Sev | Status trước | Status sau re-test | Evidence |
|---|---|---|---|---|
| F1 | 🟥 | ✅ FIXED Wave 1 | ✅ STILL FIXED | Profile 42 API response: `applied_rules.admission_round_id=1`. Profile 39 trả null vì DB JSONB chỉ có 5 keys (created trước fix Wave 1) — NOT regression, là data legacy. |
| F2 | 🟥 | ✅ FIXED Wave 1 | ✅ STILL FIXED | Officer POST /api/v2/admissions/42/choices NV3 → 201 created (id=15) |
| F3 | 🟥 | ✅ FIXED Wave 1 | ✅ STILL FIXED | `/api/admin/users` officer view không có email/phone/mfa/password_reset |
| F5 | 🟧 | ✅ FIXED Wave 1 | ✅ STILL FIXED | Profile 42 applied_rules có đủ: fee_status=`exempt`, application_fee=0.0, subject_weights, bonus_rule_override |
| F6 | 🟧 | ✅ FIXED Wave 2 | ✅ STILL FIXED | Profile 42 `permissions.override=false` (correct vì status=draft, chỉ approved mới true) |
| F7 | 🟧 | ✅ FIXED Wave 2 | ✅ STILL FIXED | Profile 42 `bypass_warning=false` (correct vì allow_unverified=false) |
| F8 | 🟧 | ✅ FIXED Wave 2 | ✅ STILL FIXED | Accountant `GET /api/admissions` → 403 clean (Casbin gate) |
| **W2-1** | 🟧 OPEN | 🔴 OPEN | 🎉 **NEWLY FIXED** | Endpoint thực `POST /api/admissions/{id}/send-magic-link` (KHÁC địa chỉ tôi đoán `/api/v2/admissions/magic-link/{action}` trong Wave 2 audit). FE `SendMagicLinkButton.tsx` + hook `useSendMagicLink.ts` + 3 actions submit/resubmit/withdraw đã wired. Withdraw consume end-to-end OK: profile 16 status `rejected` → `withdrawn` sau khi confirm với last 4 CCCD. |
| F12 | 🟦 INFO | 🟦 INFO/dead | 🟦 BY DESIGN | `submitted → reviewing` transition vẫn còn trong allowed_transitions cho legacy single-NV path; multi-NV refactor 2026-05-15 chỉ remove `reviewing` khỏi cascade flow, không phải state machine. Acceptable. |
| F13 | 🟦 INFO | 🟦 INFO/doc | 🟦 BY DESIGN | `GET /api/v2/admissions/{id}/choices` vẫn 405. Choices đọc qua parent endpoint `GET /api/admissions/{id}` field `.choices[]`. Doc-only fix. |
| **W2-6** | 🟦 INFO | 🟦 dead policy | ⚠️ **FALSE ALARM** | Route `/api/v2/admissions/{profile_id}/waitlist-reject` thực sự **EXISTS** trong `admissions_v2.py:229`. Wave 2 audit sai do probe ở thời điểm Casbin chưa allow officer hoặc 422 schema validation bị nhầm thành 404. Verified: manager probe trả 422 (missing body fields), confirm route exist. Remove from "dead" list. |
| W2-7 | 🟦 sanity | ✅ STILL OK | – | Send-magic-link cross-officer IDOR: officer 16 → profile 22 (officer 18) → 404 ✅ |

### 🎉 Admission module: **11/11 findings RESOLVED**

| Status | Count |
|---|---|
| ✅ FIXED | 8 (F1, F2, F3, F5, F6, F7, F8, W2-1) |
| 🟦 BY DESIGN | 2 (F12, F13) |
| ⚠️ FALSE ALARM | 1 (W2-6 — route exists) |
| 🔴 OPEN | **0** |

### W2-1 fix details (verified live)
- BE endpoint: `POST /api/admissions/{id}/send-magic-link` body `{action: "submit"|"resubmit"|"withdraw"}` → returns `{magic_link_url, token_value, token_expires_at, sent_to_email, phone}`
- BE state-machine guards per action:
  - submit: chỉ cho draft
  - resubmit: chỉ cho revision_requested
  - withdraw: cho mọi state (verified trên rejected)
- BE IDOR: cross-officer profile → 404
- FE component: `SendMagicLinkButton.tsx` (line 30 import trong AdmissionActions.tsx)
- FE hook: `useSendMagicLink.ts` calls `/api/admissions/{profileId}/send-magic-link`
- Consume side: `POST /api/v2/admissions/magic-link/{action}/{token}` body `{cccd: "last4"}` → 200 (verified withdraw flow live)

### Wave 3 execution log
- **11:25** Restart backend → healthy
- **11:27** Probe `/api/v2/admissions/magic-link/withdraw` (Wave 2 audit guess) → 404. Investigate FE → tìm endpoint thật `POST /api/admissions/{id}/send-magic-link`.
- **11:28** W2-1 verified: withdraw 200, submit/resubmit 400 state-machine guards, IDOR 404, consume side end-to-end OK với CCCD 8017.
- **11:29** Sanity recheck F1-F8: all still fixed.
- **11:30** W2-6 re-investigate: route exists tại admissions_v2.py:229 — Wave 2 finding FALSE ALARM.
- **11:30** F12 confirm by design: legacy single-NV vẫn dùng reviewing state.

### Admission profiles state after Wave 3
- Profile 16: `rejected` → **`withdrawn`** (consume test changed state — test artifact, có thể restore nếu cần)
- Profile 42: `draft`, choices=3 (NV1 sg=12 B00 no scores, NV2 sg=71 A00 with scores, NV3 sg=42 D07 with scores)
- Profile 39: unchanged (legacy fixture với 5-key snapshot)

---



## 📊 FINDINGS BY MODULE — Tổng hợp theo nhóm

Tổng cộng **20 findings** qua 2 wave (Wave 1: F1-F13, Wave 2: W2-1 đến W2-7).
**Status**: ✅ 9 FIXED · 🔴 7 OPEN (cần fix) · 🟦 4 INFO/dead-policy/doc-drift

### 🎓 ADMISSION (10 findings — 6 fixed, 2 open, 2 info)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| F1 | 🟥 | ✅ FIXED | `applied_rules.admission_round_id` bị Pydantic schema strip | AddChoiceDialog báo "Không xác định được đợt xét tuyển hiện tại" → multi-NV không add NV được. Fix: include all keys vào schema. |
| F2 | 🟥 | ✅ FIXED | Casbin policy `/api/v2/admissions/*/choices` POST/PATCH/DELETE chưa seed | Officer 403 dù policy_templates.py declare. Fix: sync_casbin → 9 rules. |
| F5 | 🟧 | ✅ FIXED | `applied_rules` schema strip 8 keys (round_id, round_code, fee_status, method_quota, applicable_to, application_fee, subject_weights, bonus_rule_override, requires_application_fee) | Root của F1. Cùng fix Pydantic schema. |
| F6 | 🟧 | ✅ FIXED | `permissions` block thiếu key `override` | Admin không có UI button override. Fix: thêm `"override": status == "approved" and is_admin` vào `_compute_frontend_fields`. |
| F7 | 🟧 | ✅ FIXED | Bypass UX warning không hiển thị (allow_unverified_submission silent approve) | Admin approve silent profile thiếu data. Fix: BE `bypass_warning` flag + FE banner ⚠️ + AlertDialog confirmation. |
| F8 | 🟧 | ✅ FIXED | Accountant `/api/admissions` trả "Unexpected role" defensive msg | Replace bằng Casbin DENY (clean 403). Cleanup msg. |
| W2-1 | 🟧→✅ | **FIXED Wave 7 2026-05-16** | Multi-action magic-link GENERATE side. New endpoint `POST /api/admissions/{id}/send-magic-link` body `{action}` cho 3 actions submit/resubmit/withdraw. Service `generate_action_magic_link` + repo extended với action_type param. 3 permission flags `send_submit_link`/`send_resubmit_link`/`send_withdraw_link` mirror state precheck. Casbin policies seeded (officer+manager ALLOW, accountant DENY) via alembic phase3_06. FE `SendMagicLinkButton` per-action (reuse SendConfirmationButton copy-URL pattern). KHÔNG có Celery email auto-send — officer copy URL share manual qua Zalo/SMS như confirm flow. (`change-program` action defer riêng — chưa có route handler, ngoài scope Wave 7). |
| F13 | 🟦 | INFO/doc-drift | `GET /api/v2/admissions/{id}/choices` không tồn tại (405) | Choices đọc qua `GET /api/admissions/{id}` field `.choices[]`. Update playbook + Explore agent doc. |
| F12 | 🟦 | INFO/dead | State machine `reviewing` state vẫn còn trong allowed_transitions | Phase 3 multi-NV refactor 2026-05-15 dự kiến bỏ. Legacy single-NV còn dùng — cần cleanup nếu intent là bỏ hoàn toàn. |
| W2-6 | 🟦 | INFO/dead | `/api/v2/admissions/*/waitlist-reject` route đã removed nhưng policy entry vẫn còn | Dead policy. Cleanup template + DB. |
| W2-7 | 🟦 | SANITY OK | Send-confirmation IDOR sanity check | Officer 16 → profile 22 (officer 18 owned) → 404 (correct scope). Không phải bug. |

### 👥 LEAD (2 findings — 1 fixed, 1 open)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| F9 | 🟧 | ✅ FIXED | Accountant `GET /api/leads` lộ 391 leads + phone+source+offering | Casbin DENY 11 rules cho /api/leads* cho accountant. |
| W2-3 | 🟧→✅ | **FIXED 2026-05-16 follow-up PR** | `/api/leads/export/csv` + `/api/leads/export/excel` → 404 | **Root cause khác hypothesis ban đầu**: router thực tế tồn tại tại `/api/leads/export` single endpoint với `?format=csv\|excel\|json` query param (leads.py:315). Casbin MANAGER_TEMPLATE 2 entry sai path → 404 silent. Fix: replace 2 wrong entries by 1 correct `/api/leads/export GET`. Alembic `qae2e01` cleanup live DB. Anchor `test_qa_e2e_casbin_path_alignment.py` lock. |

### 💰 FINANCE (1 finding — open)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| W2-2 | 🟧→✅ | **FIXED 2026-05-16 follow-up PR** | `GET /api/refunds` → 404 — DEAD POLICY | Refunds module deferred per memory `finance-event-decisions` (REFUND_PROCESSED tagged internal_future, 0 prod traffic, router không có). Removed 4 dead entries (`/api/refunds`, `/api/refunds/{id}`, `/api/refunds/request`, `/api/refunds/{id}/process`) từ ACCOUNTANT_TEMPLATE. Alembic `qae2e01` cleanup live DB. Anchor `test_qa_e2e_casbin_path_alignment.py` lock. Promote khi router ships. |

### 🤝 CTV + COMMISSION (1 finding — open)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| W2-4 | 🟧→⚠️ | **FALSE ALARM 2026-05-16** | Probe `/api/commission-policies` → 404 nhưng đúng path actual là `/api/admin/commission-policies` (router internal prefix `/admin/commission-policies` + main.py mount `/api`). Casbin template (line 491-499) + FE Axios (`frontend/src/lib/api/commissions.ts:24`) đều dùng path đúng `/api/admin/commission-policies`. Probe ban đầu (W2-4) sai path. Live verify: `curl /api/admin/commission-policies` → 401 (route exists, auth required). No action needed. |

### 👤 USER / AUTH (2 findings — 1 fixed, 1 open)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| F3 | 🟥 | ✅ FIXED | PII leak `/api/admin/users` cho officer + accountant (email, phone, mfa_enabled, password_reset_required) | Tạo lightweight schema chỉ trả id/username/full_name/role/status/unit_id/avatar_url. Email/phone/mfa removed. |
| F10 | 🟨 → ✅ | **FIXED 2026-05-16 (Batch F PR #303)** | Audit kết luận scope nhỏ hơn báo cáo gốc: chỉ 3/4 routes ảnh hưởng. **E20 FALSE ALARM** — `/api/leads/import` officer Casbin ALLOW (per memory `lead-import-role-contract` — officer được import self-scoped); 422 với empty file là behavior đúng. **E2/E3/E8** confirmed: `reject` + `request-revision` + `drop` dùng `Depends(get_current_active_user)` + inline `if role not in [ADMIN,MANAGER]` check. FastAPI `solve_dependencies` parse Pydantic body TRƯỚC function body → officer 422 leak field names (`reason`, `version`, `notes`, `fields`). **Fix**: swap → `CasbinAuth` dep. Casbin enforce trong solve_dependencies phase 1, BEFORE body parse → officer/accountant nhận 403 PERMISSION_DENIED không leak schema. Manager/Admin (Casbin ALLOW) vẫn 422 nếu body invalid — behavior đúng. Anchor `test_admission_action_routes_casbin_first.py` (6 tests) lock 3 routes × 2 roles × empty body matrix. |

### 📊 KPI (1 finding — open)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| W2-5 | 🟨→⚠️ | **FALSE ALARM 2026-05-16** | Path `/api/kpi-setup/` không tồn tại (404 đúng — natural Not Found cho non-existent path). Actual route là `/api/admin/kpi-setup/coverage` (kpi_setup.py:14 prefix + main.py:811 include không thêm prefix). Live verify: officer hit đúng path `/api/admin/kpi-setup/coverage` → 401 (require_admin_or_manager raises 403 with auth; 401 with no auth). Probe ban đầu (W2-5) sai path. No action needed. |

### 🎨 FRONTEND / THIN-CLIENT (2 findings — 1 fixed, 1 info)

| # | Sev | Status | Title | Detail |
|---|---|---|---|---|
| F4 | 🟧 | ✅ FIXED | Sidebar Officer leak admin nav "Backfill Queue" | `useRecentPages.ts` write ANY visited URL vào localStorage, persist cross-login → admin URL từ phiên trước leak vào nav officer. Fix: filter recentPages bằng `useAuthStore` + `isPathAccessibleByRole()` helper. |
| F11 | 🟦 | INFO/memory-drift | Memory `phase3-admin-backfill-queue-no-nav` đã stale | Sidebar admin **CÓ** entry Backfill Queue (verified Wave 1). Memory cần update. |

---

## 🎯 PRIORITY ACTION ITEMS (cho 7 OPEN findings)

| Priority | Module | Finding | Effort | Recommendation |
|---|---|---|---|---|
| **P0** | Admission | W2-1 magic-link generate gap | 3-5 ngày | Wire `POST /api/v2/admissions/magic-link/withdraw` + `/change-program` BE; FE button trong send-confirmation dialog. Self-service Vital cho candidate UX. |
| **P1** | CTV | W2-4 commission 404 | 0.5 ngày | Grep `commissions.policy_router` + `record_router` xem internal prefix; sửa template/main.py để khớp. |
| **P1** | Finance | W2-2 refunds 404 | 0.5 ngày | Quyết định: (a) implement `GET /api/refunds`, hoặc (b) xóa policy entry nếu refunds defer. |
| **P2** | Lead | W2-3 leads export 404 | 1 ngày | Implement 2 endpoints `/api/leads/export/csv` + `/excel` (đã có template, FE button). |
| **P3** | KPI | W2-5 kpi-setup 404→403 | 5 phút | Đổi route guard từ generic 404 sang `require_admin_or_manager` để trả 403 clean. |
| **P3** | User/Auth | F10 validation order | 2-4h | Refactor FastAPI dependency order — Casbin check trước Pydantic body validation. |
| **P4** | Admission | F12 + W2-6 dead state/policy | 1-2h | Cleanup `allowed_transitions` `reviewing` (nếu legacy bỏ) + xóa `waitlist-reject` policy entry. |

**Defer (INFO only)**: F11 (memory update), F13 (doc update), W2-7 (sanity OK).

---

## 🌊 WAVE 2 EXPANSION — Sections H–P coverage (run 2026-05-16)

### Coverage matrix

| Section | Scenarios run | Pass | Issues found |
|---|---|---|---|
| §H Manager persona | 7 probes (login + unit-scope + DENY matrix + override transition) | 7 ✅ | 0 |
| §I Finance E2E | 7 endpoints (fees/invoices/payments/accounting/installments/refunds/dashboard) | 6 ✅ | 1 (refunds 404) |
| §J Multi-NV publish | publish-result + waitlist + admin-rollback denial | 3 ✅ | 1 (waitlist-reject route missing — known F13 extension) |
| §K Magic-link | send-confirmation IDOR + multi-action generate side | 1 ✅ + 2 expected gap | 1 (generate side gap confirmed) |
| §L Notifications | 7 admin endpoints (rules/templates/delivery/consent/preferences/inbox/metadata) | 7 ✅ | 0 |
| §M KPI | officer dashboard/stats/leaderboard/my-kpi-plan | 4 ✅ | 1 (kpi-setup 404 cho officer — minor) |
| §N Bulk + Import/Export | template + admission/leads export | 2 ✅ | 2 (leads export csv/excel 404) |
| §O CTV + Commission | collaborators + commission-policies + commissions | 1 ✅ | 2 (commission endpoints 404 — router prefix mystery) |
| §P Cross-cutting | optimistic locking 409 + sessions + login-history + pipeline | 5 ✅ | 0 |

**Score**: 36/43 scenarios passed (84%). 7 issues found (4 endpoint mismatches + 3 known gaps).

### NEW findings từ Wave 2

| # | Sev | Section | Title | Evidence |
|---|---|---|---|---|
| W2-1 | 🟧 | §K | **Multi-action magic-link GENERATE side vẫn GAP** — confirmed memory `magic-link-consume-shipped-generate-gap`. Endpoint `POST /api/v2/admissions/magic-link/withdraw` và `change-program` → 404. Consume side OK (router included), nhưng generate POST endpoint chưa wired. Candidate không thể tự-service withdraw / change-program từ email. | curl: `POST /api/v2/admissions/magic-link/withdraw` → 404; `POST /api/v2/admissions/magic-link/change-program` → 404 |
| W2-2 | 🟧 | §I | **GET /api/refunds → 404 "Not Found"** — Casbin policy ACCOUNTANT_TEMPLATE line 313 allow `/api/refunds GET`, nhưng route chưa exist. Dead policy entry. | curl accountant: `GET /api/refunds` → `{"detail":"Not Found","error_code":"HTTP_404"}` |
| W2-3 | 🟧 | §N | **Leads export endpoints 404** — `/api/leads/export/csv` và `/api/leads/export/excel` không tồn tại. Manager template line 382-383 allow nhưng router chưa implement. Manager click "Export CSV" sẽ fail im lặng. | curl manager: 404 cho cả 2 endpoints. `grep -nE '"/.*"' leads.py | grep -i export` → 0 results |
| W2-4 | 🟧 | §O | **Commission endpoints 404** — `/api/commission-policies` và `/api/commissions` → 404 dù `commissions.policy_router` + `commissions.record_router` được include trong main.py:790-791. Có thể router internal prefix khác (e.g., `/cms-policies` thay vì `/commission-policies`). Admin click "Hoa hồng" sẽ thấy page rỗng. | curl admin: 404 cả 2; main.py xác nhận router included tại `/api` prefix; cần grep router file để xem actual prefix |
| W2-5 | 🟨 | §M | **GET /api/kpi-setup/ trả 404 cho officer** thay vì 403 — endpoint scope admin/manager (`require_admin_or_manager`). 404 leak existence nhỏ; preferred 403 với "Admin or Manager access required". | curl officer: `GET /api/kpi-setup/` → 404 |
| W2-6 | 🟦 | §J | **`/api/v2/admissions/*/waitlist-reject` route đã removed** (per policy template comment line 346-348) nhưng policy entry vẫn còn. Extension của F13 — dead policy. | curl officer/manager: 404 |
| W2-7 | 🟦 | §K | Send-confirmation IDOR works correctly: officer 16 → profile 22 (officer 18 owned) → 404. Sanity OK. | – |

### Wave 2 PASS highlights

- ✅ **§H Manager persona end-to-end OK**: login, unit-scope, claim/unclaim, bulk approve/reject, request-revision, override allowed (passed Casbin, 400 state-machine), 6/6 DENY matrix
- ✅ **§P.1 Optimistic locking VERIFIED**: `PUT /api/admissions/17` với version=1 (stale, current=6) → **409 Conflict** với clean Vietnamese msg "Profile was modified by another user. Expected version 1, but current version is 6. Please refresh and try again."
- ✅ **§L Notifications**: tất cả 7 admin endpoints (rules/metadata/templates/deliveries/consents/preferences/inbox) trả 200
- ✅ **§I Finance**: 6/7 endpoints trả 200, đã empty data nhưng route hoạt động
- ✅ **§M KPI Officer dashboard**: 4 endpoints (dashboard/stats/leaderboard/my-kpi-plan) trả 200 đầy đủ
- ✅ **§N admission export**: `/api/admissions/export` → 200 (Wave 1 audit guess wrong)

### Wave 2 execution log (~01:50-02:10 UTC+7)

- **01:50** Seed manager_qa (id=34, unit 14, role=manager). Verify login OK.
- **01:55** §H Manager probes: 391 leads unit 14 (false alarm cross-unit — only unit 14 has leads); 11 admissions visible (cross-officer same-unit OK); override on rejected → 400 state-machine; DENY 6/6 (admin/users 422 = passes Casbin per template wildcard); finalize 403.
- **02:00** §I Finance: fees/invoices/payments/accounting/installments/dashboard OK; **refunds 404**.
- **02:03** §J Multi-NV: profile 42 submit fail (validation: missing scores NV1 + unverified docs — strict mode); admin publish-result 400 (state=draft); officer waitlist-promote 403 + admin-rollback 403; **waitlist-reject 404 (route removed)**.
- **02:05** §K Magic-link: officer send-confirmation profile 22 → 404 IDOR; **multi-action generate /magic-link/withdraw + /change-program 404 — gap confirmed**.
- **02:07** §L Notifications: all 7 admin endpoints 200 ✅.
- **02:08** §M KPI: officer 4/5 endpoints 200; **kpi-setup 404**.
- **02:09** §N: import/template 200; **leads export csv/excel 404**; admissions/export 200.
- **02:10** §O CTV: collaborators 200; **commission-policies + commissions 404**.
- **02:11** §P: optimistic locking 409 verified; sessions + login-history + pipeline endpoints OK.

### Wave 2 cleanup

| Item | Note |
|---|---|
| manager_qa user (id=34) | New test account; bạn có thể giữ hoặc delete sau audit |
| Profile 42 state | Still draft (validation fail prevents submit). NV1 chưa nhập scores, NV2 có scores. Documents chưa verify. |

---





## ✅ FINAL STATUS — ALL 9 FINDINGS RESOLVED (2026-05-16, sau Wave 2 fix)

| # | Sev | Title | Status | Fix |
|---|---|---|---|---|
| F1 | 🟥→✅ | applied_rules.admission_round_id stripped | **FIXED Wave 1** | Pydantic schema include all keys |
| F2 | 🟥→✅ | Casbin /v2/admissions/*/choices missing | **FIXED Wave 1** | Sync casbin_rule rows |
| F3 | 🟥→✅ | PII leak /api/admin/users | **FIXED Wave 1** | Lightweight schema cho officer/accountant |
| F4 | 🟧→✅ | Sidebar Backfill Queue leak cho officer | **FIXED Wave 2** | `useRecentPages.ts` filter recent pages by user role |
| F5 | 🟧→✅ | applied_rules schema strip 8 keys | **FIXED Wave 1** | Cùng F1 fix |
| F6 | 🟧→✅ | permissions thiếu key `override` | **FIXED Wave 2** | `_compute_frontend_fields` thêm `"override": status == "approved" and is_admin` |
| F7 | 🟧→✅ | Bypass UX warning thiếu | **FIXED Wave 2** | BE thêm `bypass_warning` flag; FE banner ⚠️ + AlertDialog confirmation trước Approve |
| F8 | 🟧→✅ | Accountant /api/admissions "Unexpected role" | **FIXED Wave 2** | Casbin DENY rules cho accountant; defensive msg cleanup |
| F9 | 🟧→✅ | Accountant /api/leads PII leak (391 leads) | **FIXED Wave 2** | Casbin DENY rules cho /api/leads + nested endpoints |

### Wave 2 verification (browser + curl, 2026-05-16 ~01:30 UTC+7)

**F4 sidebar** — Officer dashboard reload:
- BEFORE: sidebar uid=18_27 link "Backfill Queue"
- AFTER: snapshot uid=21_4..21_27 — KHÔNG còn link Backfill Queue. Recent pages list giờ chỉ {42, Create, 410} đều accessible cho officer.

**F6 override** — `GET /api/admissions/39` (admin):
- BEFORE: permissions = 16 keys, không có `override`
- AFTER: permissions có `"override": false` (correct: status=submitted không cho phép override; chỉ approved → overridden mới true)

**F7 bypass_warning** — Browser admin → /admissions/39:
- BE response: `"bypass_warning": true` returned
- FE banner uid=24_140-148: "⚠️ Hồ sơ này được nộp trong chế độ bỏ qua xét duyệt sơ bộ" + 7 lỗi count + "Vui lòng xem tab 'Vấn đề cần sửa' trước khi phê duyệt."
- Approve button text changed: "Phê duyệt" → "**Phê duyệt (vượt điều kiện)**" với haspopup="dialog"
- Click → AlertDialog uid=25_0: heading "⚠️ Hồ sơ chưa đủ điều kiện" + bullet list 7 errors + 2 buttons "Để tôi xem lại" / "Vẫn phê duyệt"

**F8 + F9 accountant DENY** — curl accountant probe:
| Endpoint | Before | After |
|---|---|---|
| GET /api/admissions | 403 "Unexpected role 'accountant'" | **403 clean** (Casbin gate) |
| GET /api/admissions/39 | 200 với data | **403 clean** |
| GET /api/leads | 200 với 391 leads + phone | **403 clean** |
| GET /api/leads/410 | 200 với PII | **404** (bị Casbin deny + IDOR scope) |
| GET /api/leads/410/timeline | 200 | **404** |
| GET /api/admin/users | 200 (sanitized — F3 already done) | 200 (kept allow per design) |

### Code changes summary

**BE**:
- `Backend_FastAPI/app/services/admission_service.py`:
  - Line ~1497: thêm `"override": status == "approved" and is_admin,` cho permissions
  - Line ~1576: thêm `bypass_warning` boolean field computed sau eligibility
  - Line ~249: replace "Unexpected role" defensive msg bằng Vietnamese role-neutral msg
- `Backend_FastAPI/app/schemas/admission.py`:
  - Thêm `bypass_warning: bool` field trong `AdmissionProfileResponse`
- `Backend_FastAPI/app/casbin_config/policy_templates.py`:
  - ACCOUNTANT_TEMPLATE B1 deny block: thêm 23 deny rules cho /api/admissions* + /api/leads*

**FE**:
- `frontend/src/hooks/useRecentPages.ts`:
  - Thêm `findItemInNavigation()` + `isPathAccessibleByRole()` helpers
  - Hook đọc `useAuthStore` → filter `recentPages` qua `useMemo`
- `frontend/src/lib/zod/admissions.ts`:
  - Thêm `bypass_warning: z.boolean().default(false)` vào schema
- `frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionDetailClient.tsx`:
  - Render warning banner khi `profile.bypass_warning === true`
- `frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionActions.tsx`:
  - Wrap Approve button trong AlertDialog confirmation khi `bypass_warning`; button text đổi "Phê duyệt (vượt điều kiện)"

**DB**:
- 23 INSERT rows vào `casbin_rule` (template_id='accountant_f8_f9') — accountant deny cho admissions/leads endpoints
- POST /api/v2/admin/casbin/reload → policy_count=255 in-memory refreshed
- Backend container restart cho code changes pick up

### Final score
- **9/9 findings RESOLVED** (3/3 BLOCKERS Wave 1 + 1/6 MAJOR Wave 1 + 5/5 remaining Wave 2)
- **Multi-NV happy path**: ✅ End-to-end works
- **3 personas RBAC matrix**: ✅ All denials clean (Casbin-gated, no defensive code leaks)
- **Thin-Client compliance**: ✅ Sidebar permission-driven; bypass UX surface qua BE flag, không phải FE inference

---

## 🔁 RE-TEST RESULTS (2026-05-16, sau fix của user)

| # | Sev | Title | Status | Evidence |
|---|---|---|---|---|
| **F1** | 🟥→✅ | applied_rules.admission_round_id stripped | **FIXED** | `GET /api/admissions/42` → `applied_rules.admission_round_id=1` (was null). FE AddChoiceDialog mở thành công với cascading dropdown. |
| **F2** | 🟥→✅ | Casbin policy /v2/admissions/*/choices missing | **FIXED** | DB casbin_rule có 9 rows: officer GET/POST/PATCH/DELETE allow + accountant POST/PATCH/DELETE deny. Officer 16 POST choice trên profile 42 → 201 Created (NV2 id=14). |
| **F3** | 🟥→✅ | PII leak via /api/admin/users | **FIXED** | Officer + Accountant response giờ chỉ có: id, username, full_name, role, status, unit_id, avatar_url, skills, availability_status. **REMOVED**: email, phone_number, mfa_enabled, password_reset_required, max_capacity. |
| **F5** | 🟧→✅ | applied_rules schema strip 8 keys | **FIXED** | 29 keys returned (was 20). Tất cả 9 missing keys khôi phục đầy đủ. |
| F4 | 🟧 | Sidebar leak Backfill Queue cho officer | ❌ **NOT FIXED** | Re-snapshot officer dashboard sidebar uid=17_27 + 18_27 vẫn còn link "Backfill Queue". |
| F6 | 🟧 | permissions thiếu key `override` | ❌ **NOT FIXED** | Re-test admin GET /api/admissions/39 → permissions vẫn không có `override` (16 keys: edit/save/submit/approve/reject/publish_result/request_revision/resubmit/enroll/send_confirmation/drop/claim/unclaim/assign_officer/calculate_fee/delete/minor_correction/view). available_actions không có "override". |
| F7 | 🟧 | Bypass UX warning không hiển thị | ❌ **NOT FIXED** (BE) | Profile 39: `eligibility_status=ineligible` + `allow_unverified_submission=true` — payload không đổi. UI side chưa probe lại nhưng backend không có warning flag mới. |
| F8 | 🟧 | Accountant /api/admissions trả "Unexpected role" | ❌ **NOT FIXED** | curl accountant `GET /api/admissions` → 403 same defensive error msg. |
| F9 | 🟧 | Accountant /api/leads PII leak | ❌ **NOT FIXED** | curl accountant `GET /api/leads` → 200 với 391 leads gồm phone+source+offering. |
| F10 | 🟨 | Body validation chạy trước Casbin | ⏭️ skipped | Không re-test. |
| F11 | 🟦 | Memory drift backfill-queue-no-nav | ⏭️ N/A | Memory note only. |
| F12 | 🟦 | State machine `reviewing` legacy | ⏭️ skipped | Không re-test. |
| F13 | 🟦 | GET /api/v2/admissions/{id}/choices không tồn tại | ⏭️ doc fix | Audit doc. |

**Điểm số**: 4/9 actionable findings FIXED (3/3 BLOCKERS + 1/6 MAJOR).
**Multi-NV happy path**: ✅ End-to-end works cho officer (create profile → view multi-NV tab → add choice qua API → UI render đúng "(2/5)" với drag handles + edit/delete buttons + dialog cascading).

### Re-test execution log
- **00:35** DB query confirms F2 — 9 Casbin rules cho /v2/admissions/*/choices (officer allow, accountant deny).
- **00:40** Probe browser officer session: F1 + F5 + F2 + F3 cùng lúc → cả 4 fixed.
- **00:48** Insert NV2 thành công via API (sg_config 71 = A00). Choice id=14, decision=pending.
- **00:50** FE reload `/admissions/42` Step 4 → "Danh sách nguyện vọng (2/5)" hiển thị đầy đủ NV1+NV2 với scores + badges + edit/delete UI.
- **00:51** Click "Thêm nguyện vọng" → dialog "Thêm nguyện vọng NV3" mở với cascading dropdown "Ngành / Phương thức xét tuyển". KHÔNG còn error "Không xác định được đợt xét tuyển".
- **00:55** curl admin probe profile 39: F6 permissions vẫn thiếu `override`, F7 backend payload không đổi.
- **00:55** curl accountant probe: F8 vẫn "Unexpected role", F9 vẫn list 391 leads với PII, F3 confirmed fixed.

### Test artifacts (current state)
- Profile #42: choice rows = 2 (id=12 sg=B00 không có scores; id=14 sg=A00 có scores math/physics/chemistry)
- Lead 410: assigned officer 16, profile 42 attached
- Stack vẫn dev local healthy

---


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
| F12 | 🟦→✅ | State machine doc drift | **CLARIFIED 2026-05-16 Wave 6**: `reviewing` state KHÔNG bị bỏ — Wave 2 commit a7ab21d0 (publish-result simplified flow) chỉ bỏ explicit T2 start-review ENDPOINT/BUTTON, nhưng state machine giữ `reviewing` làm intermediate. publish_result() giờ auto-transition `submitted → reviewing → engine cascade` atomic internal. Allowed transitions error msg đúng — không phải drift. |
| F13 | 🟦→✅ | Endpoint audit | **VERIFIED 2026-05-16 Wave 6**: choices đọc qua `GET /api/admissions/{id}` `.choices[]` (eager-loaded via `_choices_eager_load_options()` chain). KHÔNG có endpoint `GET /api/v2/admissions/{id}/choices` (405 đúng). Playbook updated. |
| T11 | 🟥→✅ | Waitlist reject (NEW Wave 5+6) | Implement T11 endpoint `POST /api/v2/admissions/{id}/waitlist-reject` (manager/admin manually finalize NV dự bị → trượt). BE: service + router + schema + event + PAIR map + alembic phase3_04 (accountant DENY) + phase3_05 (NotificationRule seed). FE: API + hook + 2 buttons + AuditReasonDialog wire trong ChoiceListEditor (cả T10 promote cùng wire). |

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
