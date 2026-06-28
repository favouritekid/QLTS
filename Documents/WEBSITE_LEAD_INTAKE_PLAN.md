# WEBSITE LEAD INTAKE PLAN — tnpc.edu.vn → QLTS

> Tái tạo 2026-06-28 (bản gốc chốt 06-24 bị mất, chưa từng commit). Đã đối chiếu
> code hiện tại + sửa 3 điểm sai và áp quyết định mới của chủ dự án.
> Memory nguồn: `website-lead-intake-tnpc`.

---

## 1. Mục tiêu

Kết nối website tuyển sinh **tnpc.edu.vn** (Trường CĐ Bách khoa Tây Nguyên — WordPress +
Flatsome + Formidable **Pro 6.32**) đẩy lead trực tiếp vào QLTS, song song với
luồng AppSheet hiện có (KHÔNG đụng action cũ).

---

## 2. Hiện trạng (verified code 2026-06-28)

- **KHÔNG có endpoint public tạo lead** — `POST /api/leads`, CTV submit, import đều cần auth.
- Enum `source.website` **đã tồn tại** (`models/lead.py:50`).
- **Đã có sẵn pattern public**: `app/routers/public_admissions.py` (prefix `/api/public/...`,
  `@limiter.limit`, không auth) → nhân bản cho intake.
- `lead_repository.get_by_phone()` (:569) + `check_phone_conflict()` (:945) — lọc `deleted_at`.
- `create_lead()` (lead_service.py:793) đã tự gọi `process_automatic_lead_assignment_task`
  → auto-assign chỉ-khi-tạo (đúng yêu cầu).
- `add_consultation()` (:1908) **KHÔNG có tham số `skip_status_update`** — cờ này
  được tự set bởi `check_terminal_status_guard` (:1974). NHƯNG hàm **bắt buộc `officer_id`**
  và enforce "officer phải được gán" (:1945) → cần đường đi system cho lead officer NULL.
- `LeadCreate` (schemas/lead.py:246): `full_name`(req), `phone`(req, validate VN regex
  `^0(3|5|7|8|9|2)\d{8,9}$`), `email`(**optional** EmailStr), `source`(req),
  `education_level`(optional), `unit_id`(optional), `assigned_officer_id`(optional).
- Rate limiter (`core/rate_limits.py`): slowapi, key mặc định = IP (`get_remote_address`).
  Hỗ trợ key_func tùy biến per-decorator. `PUBLIC_CONTACT = 5/hour`.

---

## 3. Quyết định (chốt 06-24, cập nhật 06-28)

| # | Quyết định |
|---|-----------|
| D1 | ~~`unit_id = null`~~ **HỦY (review 06-28 P1#1)**. `unit_id=null` → auto-assign lọc `User.unit_id == lead_unit_id` (assignment_service.py:191) trả pool rỗng → set `AssignmentStatus.FAILED` (:216), lead treo không ai nhận. **THAY: D9** (default unit env). |
| D2 | Chỉ tích hợp **form 7** ("Học viên đăng ký toàn site") trước. |
| D3 | Hệ + ngành **gộp vào ghi chú**, KHÔNG auto-map offering. **✅ XÁC NHẬN LẠI 06-28** (user cân nhắc auto-map rồi BỎ): lead mới `offering_id = NULL`, ngành chỉ nằm trong note Consultation hệ thống; officer tự chọn ngành/nguyện vọng đúng khi tư vấn. Tránh sai định tuyến (offering→unit) + khóa hồ sơ theo ngành sai. |
| D4 | Chạy **song song AppSheet** — thêm API action #2 trỏ QLTS, giữ action cũ. |
| D5 | Form 7 **không có field email** → schema intake email **optional**. |
| D6 | Trùng SĐT → **upsert lead cũ** (update), KHÔNG tạo trùng. Update KHÔNG auto-assign lại (giữ officer). |
| **D7 (06-28)** | Lead give-up `sts20` / đã có hồ sơ → **chỉ ghi note + notification in-app, KHÔNG reopen pipeline**. |
| **D8 (06-28)** | Rate-limit: tính theo **API key**, cap cao (vì `wp_remote_post` server-side, mọi lead chung 1 IP). |
| **D9 (06-28, fix P1#1)** | **Routing dứt khoát qua default unit**: env `PUBLIC_INTAKE_DEFAULT_UNIT_ID` (int). Lead intake tạo với unit này → auto-assign tìm được officer cùng unit → phân công bình thường; noted-path + notification cũng resolve qua unit. **Env chưa set / unit không tồn tại → endpoint trả 503** (không tạo lead treo). Mapping ngành/hệ→unit là enhancement sau (D3 vẫn KHÔNG auto-map offering). |
| **D10 (06-28, fix P1#2, siết review-3)** | **Upsert race-safe + lookup CANONICAL**: (a) `pg_advisory_xact_lock(<ns>, hashtext(phone_normalized))` đầu transaction; (b) lookup lead qua **`LeadPhoneIdentity.phone_normalized`** (canonical, repo method MỚI `get_active_lead_by_phone_identity`) — KHÔNG dựa raw `Lead.phone/phone2` (lệch format/race surface khác). (c) Nếu vẫn tạo trùng, `create_lead` flush IntegrityError → **convert thành `DuplicateResourceError`** (lead_service.py:1208/`_handle_lead_integrity_error`) → intake **catch `DuplicateResourceError`** (KHÔNG phải IntegrityError), reload bằng canonical identity rồi rẽ updated/noted. KHÔNG để 500/409 cho double-submit hợp lệ. Test double-submit đồng thời + raw-phone-lệch-format. |
| **D11 (06-28, fix P1#3)** | **Notification fallback dùng rule sẵn**: rule seed `CONSULTATION_CREATED` = `actor_excluded(composite(lead_owner, unit_managers))` (notification_seed_defaults.py:130) → tự fanout officer + quản lý đơn vị. `LeadOwnerResolver` ưu tiên `payload.officer_id` (:96). Vì D9 cấp unit thật → `unit_managers` luôn resolve được kể cả officer NULL. KHÔNG cần rule mới. |
| **D12 (06-28, fix P2)** | Verify `X-API-Key` bằng **FastAPI dependency** (raise 401) — chạy TRƯỚC thân hàm bọc `@limiter.limit` → 401 thật sự xảy ra trước khi đếm limit. Key chưa cấu hình → 503. |
| **D13 (06-28, CHỐT = option A)** | **Lead KHÔNG có cột `notes`** (407 = `Consultation.notes`). Khảo sát: `officer_summary` = ô "Đánh giá TV" truncate 1 dòng → LOẠI; `CRMInteraction` không nằm trong `get_lead_timeline` (lead_service.py:2385 chỉ gộp consultations+assignment_logs) → vô hình → LOẠI. **✅ CHỐT: `address`→`location`, `education`→`education_level`; hệ/ngành/ghi-chú → `Consultation` HỆ THỐNG** (officer_id=`get_system_user`, insert raw KHÔNG qua add_consultation → KHÔNG đổi pipeline/không reopen; status=current; method="website"; cache update). Hiện ở tab Consultations + Timeline. Count +1 chấp nhận (defer lọc). |

---

## 4. Map field form 7 → intake (rà ẩn danh qua Chrome 06-24)

| Field ID | Nhãn form | → schema | Ghi chú |
|----------|-----------|----------|---------|
| 49 | Họ tên (req) | `full_name` | |
| 51 | SĐT tel (req) | `phone` | validate VN, normalize |
| 57 | Địa chỉ liên hệ (location) | `note` (gộp) | **KHÔNG phải email** — form không có email |
| 55 | "Bạn đã tốt nghiệp?" (THCS/THPT/TC/CĐ/ĐH/Khác) | `education_level` | chuẩn hoá BE (xem §5) |
| 52 | Hệ xét tuyển (CĐ/TC) | `note` (gộp) | |
| 53 | Ngành xét tuyển (dropdown động) | `note` (gộp) | |
| 56 | Ngành đăng ký (text) | `note` (gộp) | |
| 59 | Ghi chú | `note` (gộp) | |
| 89/90 | honeypot | reject nếu có giá trị | Formidable tự lọc, ta double-check |

Chuẩn hoá `education_level`: THPT→`high_school` · Trung cấp/Cao đẳng→`diploma` ·
Đại học→`bachelor` · THCS/Khác→`other`.

`source` cố định = `"website"`.

---

## 5. Thiết kế kỹ thuật

### 5.1 Schema — `app/schemas/public_lead_intake.py`
- `PublicLeadIntake`: `full_name`(req), `phone`(req, validate VN reuse phone_helpers),
  `email`(optional), `education_level_raw`(optional str → chuẩn hoá), `address`(optional),
  `he`/`nganh_xet`/`nganh_dang_ky`/`extra_note`(optional, gộp note), `hp`(honeypot, optional).
- `PublicLeadIntakeResult`: `{ "status": "created" | "updated" | "noted", "lead_id": int }`
  (KHÔNG trả PII — chỉ id + trạng thái xử lý).

### 5.2 Service — `app/services/public_lead_intake_service.py`
`intake_public_lead(db, data) -> tuple[result, post_commit_cb]` (KHÔNG nhận current_user):
1. Resolve & validate `default_unit_id = settings.PUBLIC_INTAKE_DEFAULT_UNIT_ID`; nếu
   None/không tồn tại → raise domain error → router map 503 (D9).
2. Normalize phone. **CHỖ CHỨA THÔNG TIN (D13 — option A, đã khảo sát UI):**
   - `address`→`Lead.location`; `education_level_raw`→`Lead.education_level` (chuẩn hoá).
   - `hệ + ngành_xét + ngành_đăng_ký + ghi_chú` → **1 record `Consultation` hệ thống** (insert raw,
     KHÔNG qua `add_consultation`): `officer_id = get_system_user(db).id`
     (payment_import_service.py:914 → canonical `_get_system_application_fee_user`),
     `consultation_status_id = lead.consultation_status_id hiện tại` (tránh "Status #null" trên UI,
     KHÔNG đổi pipeline lead), `consultation_date = now`, `method = "website"` (UI rơi về nhãn "Tư vấn"),
     `notes = "[Đăng ký web dd/mm] Hệ:… Ngành:… Ghi chú:…"`. Hiện ở tab Consultations + feed Timeline.
   - Sau insert + `db.flush([c])` → gọi `lead_cache_service.update_lead_cache(db, lead_id, lead)` giữ
     `consultation_count`/`last_consultation_at` nhất quán. ⚠️ Lưu ý: count tăng 1 (lead_score nhích nhẹ) —
     chấp nhận; nếu cần loại có thể lọc `method="website"` ở cache sau (defer).
3. **`pg_advisory_xact_lock(<intake_ns_const>, hashtext(phone_normalized))`** (D10) — serialize
   các request cùng SĐT trong cùng transaction frame.
4. Lookup lead qua **canonical identity** `repo.get_active_lead_by_phone_identity(phone_normalized)`
   (repo method MỚI: join `LeadPhoneIdentity` deleted_at NULL → `Lead` deleted_at NULL) — **KHÔNG**
   dùng `get_by_phone` raw (D10). Dưới lock:
   - **Không có** → `create_lead(db, LeadCreate(source="website", unit_id=default_unit_id, ...),
     created_by=None)` → auto-assign celery tìm officer cùng unit. `status="created"`.
     Bọc `try/except DuplicateResourceError` (create_lead đã convert IntegrityError→Duplicate ở :1208) →
     reload bằng canonical identity → rẽ nhánh updated/noted (không 409/500).
   - **Có, không terminal & chưa có hồ sơ** → update field rỗng (location/education nếu trống) +
     **insert Consultation hệ thống** (bước 2) ghi context "đăng ký lại qua web" (KHÔNG auto-assign lại,
     KHÔNG đổi pipeline, GIỮ unit/officer cũ). `status="updated"`.
   - **Có, terminal (sts20) hoặc đã có AdmissionProfile** → **insert Consultation hệ thống** (bước 2,
     officer_id=system, KHÔNG reopen vì insert raw) + `dispatch(SystemEvents.CONSULTATION_CREATED,
     payload=for_consultation_created(consult, lead, actor=None))` → rule sẵn fanout lead_owner +
     unit_managers (D11). `status="noted"`. (D7)
5. Trả `(result, post_commit_cb)` — router commit rồi await cb (notif fanout).

> ⚠️ Đường "noted" KHÔNG gọi `add_consultation` (hàm này enforce officer-assignment + cần status_id).
> Thay bằng append-note thấp tầng + `dispatch()` trực tiếp với payload thủ công; vì lead có
> `unit_id` (D9), `unit_managers` luôn resolve recipient kể cả `officer_id` NULL. `actor_id=None`
> ⇒ `actor_excluded` không loại ai (intake là hệ thống).

### 5.3 Router — `app/routers/public_leads.py`
- `POST /api/public/leads/intake`, **không auth nghiệp vụ**.
- **Dependency `verify_intake_api_key`** (D12): so `X-API-Key` với `settings.PUBLIC_INTAKE_API_KEY`
  bằng `hmac.compare_digest`. Key rỗng (chưa cấu hình) → **503**; sai/thiếu → **401**. Dependency
  chạy TRƯỚC thân hàm bọc `@limiter.limit` ⇒ 401/503 xảy ra trước khi đếm limit.
- `@limiter.limit(RateLimits.PUBLIC_INTAKE, key_func=get_intake_key)` — chỉ đếm cho request đã qua key.
- Honeypot: field `hp` có giá trị → trả 200 "ok" giả (không tạo lead).
- Map `DomainException`: unit chưa cấu hình → 503. **`DuplicateResourceError` KHÔNG được rò ra 409** —
  service đã catch + reload canonical (D10); nếu (cực hiếm) vẫn thoát ra thì là bug, không phải đường thường.
- Đăng ký router vào `main.py` (cạnh `public_admissions.router`).

### 5.4 Config — `config.py`
- `PUBLIC_INTAKE_API_KEY: str = ""`.
- `PUBLIC_INTAKE_DEFAULT_UNIT_ID: int | None = None` (D9).

### 5.5 Rate-limit (D8/D12)
Thêm `PUBLIC_INTAKE = "500/hour"` (test override) vào `RateLimits` + key_func
`get_intake_key(request)` trả về header `X-API-Key` (per-key). Verify key là **dependency**
riêng (5.3), KHÔNG nhồi vào key_func — đảm bảo 401 trước đếm limit.

---

## 6. Hạ tầng tái dùng (verified)
- **Canonical phone**: `LeadPhoneIdentity` (model `lead_phone.py`) — partial unique
  `uq_lead_phone_active` ON `phone_normalized` WHERE deleted_at IS NULL; `register_phone_identities`
  (repo:1574) tự chuẩn hoá `normalize_vietnam_phone`. **Intake lookup = repo method MỚI
  `get_active_lead_by_phone_identity` join identity→lead** (KHÔNG dùng `get_by_phone` raw cho intake).
- `create_lead` auto-assign celery (chỉ create); IntegrityError unique→`DuplicateResourceError` (:1208).
- **Trường text trên Lead (verified lead.py:70–381):** `location`(địa chỉ), `education_level`,
  `officer_summary`(ô "Đánh giá TV", truncate). **KHÔNG có `notes`.** Timeline lead (`get_lead_timeline`
  lead_service.py:2385) = `Consultation` + `assignment_logs` (CRMInteraction KHÔNG hiển thị).
- **System user**: `payment_import_service.get_system_user(db)` (→ canonical `_get_system_application_fee_user`).
- **Cache lead**: `lead_cache_service.update_lead_cache(db, lead_id, lead)` recompute count/score sau khi thêm consultation.
- **Tạo Consultation raw**: `models.Consultation(lead_id, officer_id, consultation_status_id, consultation_date, method, notes)` + `db.add` + `db.flush([c])` (mẫu lead_service.py:2118) — KHÔNG dùng `add_consultation` (tránh transition/guard).
- `phone_helpers.normalize_vietnam_phone` / `validate_vietnam_phone`.
- Hard-block sẵn: KHÔNG set trực tiếp `consultation_status_id`/`pipeline_stage_id`;
  `offering_id` đổi bị chặn nếu đã có AdmissionProfile.

---

## 7. Test (`tests/api/test_public_lead_intake.py`)
1. Tạo mới SĐT lạ → 200 `created`, lead `source=website`, **unit=default_unit**, auto-assign tìm officer cùng unit (D9), **+1 Consultation hệ thống (officer=system, method=website, notes chứa hệ/ngành) hiện trong timeline; pipeline lead KHÔNG đổi** (D13).
2. Upsert SĐT trùng (non-terminal) → `updated`, không trùng lead, **giữ unit/officer cũ**.
3. Lead terminal sts20 → `noted`, **pipeline KHÔNG đổi** (assert consultation_status_id giữ nguyên), notif dispatch.
4. **Officer NULL trên lead cũ (có unit)** → notif fanout **unit_managers** (D11), không lỗi.
5. **Double-submit đồng thời cùng SĐT** (D10) → đúng 1 lead, request 2 ra `updated`/`noted`, KHÔNG 500/409. Thêm ca: lookup CANONICAL hit khi raw `Lead.phone` lệch format nhưng `phone_normalized` trùng → ra `updated` (không tạo trùng); ca `create_lead` ném `DuplicateResourceError` → service catch + reload (không 409).
6. Sai/thiếu API key → **401**; key chưa cấu hình (env rỗng) → **503**; **`PUBLIC_INTAKE_DEFAULT_UNIT_ID` chưa set → 503** (D9).
7. Honeypot có giá trị → 200 giả, KHÔNG tạo lead.
8. Phone sai định dạng VN → 422; email optional (form không gửi) → OK.

---

## 8. Phía WordPress (form 7)
Formidable Pro → form 7 → Actions → **Add API** (action #2, giữ action cũ):
- POST `https://<backend-prod>/api/public/leads/intake`
- Header `X-API-Key: <PUBLIC_INTAKE_API_KEY>`
- Body map: [49]→full_name, [51]→phone, [57]→address, [55 show]→education_level_raw,
  [52 show]→he, [53 show]→nganh_xet, [56]→nganh_dang_ky, [59]→extra_note.
- KHÔNG cần CORS (server-side call). Giữ UX "đăng ký thành công" (action chạy ngầm).

**Chờ chủ dự án cung cấp:** (1) **URL backend prod**; (2) giá trị `PUBLIC_INTAKE_API_KEY`;
(3) **`PUBLIC_INTAKE_DEFAULT_UNIT_ID`** = đơn vị nhận lead website (D9).

---

## 9. Deploy
- BE-only, **KHÔNG migration**, KHÔNG Casbin (endpoint public).
- Thêm env vào `.env.production` (backend container) → **restart backend**:
  - `PUBLIC_INTAKE_API_KEY=<key>`
  - `PUBLIC_INTAKE_DEFAULT_UNIT_ID=<id đơn vị>` (D9 — thiếu thì endpoint trả 503, an toàn).
- Tuân: push/PR/merge/deploy **xin phép riêng từng lần** (memory `push-pr-deploy-needs-explicit-ok`).

---

## 10. Trạng thái
- [ ] Repo: `get_active_lead_by_phone_identity(phone_normalized)` (canonical lookup, D10)
- [ ] Service helper: insert Consultation hệ thống (system-user, raw, no-transition) + cache update (D13)
- [ ] Code BE (schema/service/router/config/rate-limit)
- [ ] Test
- [ ] Local verify
- [ ] (xin phép) push/PR
- [ ] WP form 7 API action #2
- [ ] Deploy + set env + restart
