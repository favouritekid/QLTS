# WEBSITE LEAD INTAKE PLAN — tnpc.edu.vn → QLTS

> Tái tạo 2026-06-28 (bản gốc chốt 06-24 bị mất, chưa từng commit). Đã đối chiếu
> code hiện tại và áp quyết định của chủ dự án. Đồng bộ lại 11-09-2026 khi
> hợp nhất lên `fb500f0d`; mỗi chỗ đã sửa đều ghi ngày ngay tại mục đó.
> Memory nguồn: `website-lead-intake-tnpc`.

---

## 1. Mục tiêu

Kết nối website tuyển sinh **tnpc.edu.vn** (Trường CĐ Bách khoa Tây Nguyên — WordPress +
Flatsome + Formidable **Pro 6.32**) đẩy lead trực tiếp vào QLTS, song song với
luồng AppSheet hiện có (KHÔNG đụng action cũ).

---

## 2. Hiện trạng (verified code 2026-06-28)

- **KHÔNG có endpoint public tạo lead** — `POST /api/leads`, CTV submit, import đều cần auth.
- Enum `source.website` **đã tồn tại** (`models/lead.py`, `LeadSourceEnum`).
- **Đã có sẵn pattern public**: `app/routers/public_admissions.py` (prefix `/api/public/...`,
  `@limiter.limit`, không auth) → nhân bản cho intake.
- `lead_repository.get_by_phone()` + `check_phone_conflict()` — lọc `deleted_at`.
- `create_lead()` (`lead_service.py`) đã tự gọi `process_automatic_lead_assignment_task`
  → auto-assign chỉ-khi-tạo (đúng yêu cầu).
- `add_consultation()` (`lead_service.py`) **KHÔNG có tham số `skip_status_update`**
  — cờ này được tự set bởi `check_terminal_status_guard`. NHƯNG hàm **bắt buộc
  `officer_id`** và enforce "Officer phải được gán cho Lead này" → cần đường đi
  system cho lead officer NULL.
- `LeadCreate` (`schemas/lead.py`): `full_name`(req), `phone`(req, validate VN regex
  `^0(3|5|7|8|9|2)\d{8,9}$`), `email`(**optional** EmailStr), `source`(req),
  `education_level`(optional), `unit_id`(optional), `assigned_officer_id`(optional).
- Rate limiter (`core/rate_limits.py`): slowapi, key mặc định = IP (`get_remote_address`).
  Hỗ trợ key_func tùy biến per-decorator. `PUBLIC_CONTACT = 5/hour`.

---

## 3. Quyết định (chốt 06-24, cập nhật 06-28)

| # | Quyết định |
|---|-----------|
| D1 | ~~`unit_id = null`~~ **HỦY (review 06-28 P1#1)**. `unit_id=null` → auto-assign lọc `User.unit_id == lead_unit_id` (`assignment_service.py`, bước lọc pool theo `unit_id`) trả pool rỗng → set `AssignmentStatus.FAILED` (`assignment_service.py`, qua `StatusHelper.set_assignment_status`), lead treo không ai nhận. **THAY: D9** (default unit env). |
| D2 | Chỉ tích hợp **form 7** ("Học viên đăng ký toàn site") trước. |
| D3 | Hệ + ngành **gộp vào ghi chú**, KHÔNG auto-map offering. **✅ XÁC NHẬN LẠI 06-28** (user cân nhắc auto-map rồi BỎ): lead mới `offering_id = NULL`, ngành chỉ nằm trong note Consultation hệ thống; officer tự chọn ngành/nguyện vọng đúng khi tư vấn. Tránh sai định tuyến (offering→unit) + khóa hồ sơ theo ngành sai. |
| D4 | Chạy **song song AppSheet** — thêm API action #2 trỏ QLTS, giữ action cũ. |
| D5 | Form 7 **không có field email** → schema intake email **optional**. |
| D6 | Trùng SĐT → **upsert lead cũ** (update), KHÔNG tạo trùng. Update KHÔNG auto-assign lại (giữ officer). |
| **D7 (06-28)** | Lead give-up `sts20` / đã có hồ sơ → **chỉ ghi note + notification in-app, KHÔNG reopen pipeline**. |
| **D8 (06-28)** | Rate-limit: tính theo **API key**, cap cao (vì `wp_remote_post` server-side, mọi lead chung 1 IP). |
| **D9 (06-28, fix P1#1)** | **Routing dứt khoát qua default unit**: env `PUBLIC_INTAKE_DEFAULT_UNIT_ID` (int). Lead intake tạo với unit này → auto-assign tìm được officer cùng unit → phân công bình thường; noted-path + notification cũng resolve qua unit. **Env chưa set / unit không tồn tại → endpoint trả 503** (không tạo lead treo). Mapping ngành/hệ→unit là enhancement sau (D3 vẫn KHÔNG auto-map offering). |
| **D10 (06-28, fix P1#2, siết review-3)** | **Upsert race-safe + lookup CANONICAL**: (a) `pg_advisory_xact_lock(<ns>, hashtext(phone_normalized))` đầu transaction; (b) lookup lead qua **`LeadPhoneIdentity.phone_normalized`** (canonical, repo method MỚI `get_active_lead_by_phone_identity`) — KHÔNG dựa raw `Lead.phone/phone2` (lệch format/race surface khác). (c) Nếu vẫn tạo trùng, `create_lead` flush IntegrityError → **convert thành `DuplicateResourceError`** (lead_service.py/`_handle_lead_integrity_error`) → intake **catch `DuplicateResourceError`** (KHÔNG phải IntegrityError), reload bằng canonical identity rồi rẽ updated/noted. KHÔNG để 500/409 cho double-submit hợp lệ. Test double-submit đồng thời + raw-phone-lệch-format. |
| **D11 (06-28, fix P1#3)** | **Notification fallback dùng rule sẵn**: rule seed `CONSULTATION_CREATED` = `actor_excluded(composite(lead_owner, unit_managers))` (notification_seed_defaults.py) → tự fanout officer + quản lý đơn vị. `LeadOwnerResolver` (`notification_resolvers.py`) ưu tiên `payload.officer_id`. ⚠️ **SỬA 11-09:** câu gốc ghi "vì D9 cấp unit thật → `unit_managers` **luôn** resolve được kể cả officer NULL, KHÔNG cần rule mới". Cả hai vế đều SAI. `UnitManagersResolver` (`notification_resolvers.py`) trả **danh sách RỖNG** khi đơn vị không có manager/admin — và đo 11-09, unit 14 đúng là rỗng (xem §10). Có `unit_id` không bảo đảm có người nhận. Đây là **khoảng trống chặn activation**, cần một rule hoặc cơ chế giám sát bổ sung. |
| **D12 (06-28, fix P2)** | Verify `X-API-Key` bằng **FastAPI dependency** (raise 401) — chạy TRƯỚC thân hàm bọc `@limiter.limit` → 401 thật sự xảy ra trước khi đếm limit. Key chưa cấu hình → 503. |
| **D13 (06-28, CHỐT = option A)** | **Lead KHÔNG có cột `notes`** (407 = `Consultation.notes`). Khảo sát: `officer_summary` = ô "Đánh giá TV" truncate 1 dòng → LOẠI; `CRMInteraction` không nằm trong `get_lead_timeline` (lead_service.py chỉ gộp consultations+assignment_logs) → vô hình → LOẠI. **✅ CHỐT: `address`→`location`, `education`→`education_level`; hệ/ngành/ghi-chú → `Consultation` HỆ THỐNG** (officer_id=`get_system_user`, insert raw KHÔNG qua add_consultation → KHÔNG đổi pipeline/không reopen; status=current; **`method = SYSTEM_CONSULTATION_METHOD`**; **KHÔNG** gọi cache update — xem §5.2). Hiện ở tab Consultations + Timeline. **Sửa 11-09 khi hợp nhất lên `fb500f0d`:** bản chốt 06-28 ghi `method="website"` và chấp nhận `count +1`. Cả hai nay SAI — kho coi bản ghi do máy tạo là `SYSTEM_CONSULTATION_METHOD`, và 8+ truy vấn ở `insights_repository`/`lead_repository`/`officer_repository` loại chúng bằng `is_distinct_from(...)`. Một `method` mới mà phần còn lại chưa hiểu sẽ bị đếm là tư vấn THẬT: reset đồng hồ SLA auto-close, méo `consultation_count`, và có thể chiếm chỗ "cuộc tư vấn mới nhất" khiến officer mất quyền sửa/xoá cuộc thật trước đó. Nguồn website nay đánh dấu bằng tiền tố `[web]` trong `notes` — chỉ để chống lặp, không mang ngữ nghĩa phân quyền. `count` KHÔNG tăng. |

---

## 4. Map field form 7 → intake

> **Đo lại trực tiếp 11-09-2026** trên form sống tại `tnpc.edu.vn` (GET/DOM ẩn danh,
> không điền, không submit, không đăng nhập). Bảng 06-24 đã trôi ở ba chỗ, đánh dấu ⚠️
> bên dưới. Form là Formidable **id 7**, 21 field, nằm ngay trang chủ.

| Field ID | Nhãn form (đo 11-09) | Kiểu | Bắt buộc | → schema | Ghi chú |
|---|---|---|---|---|---|
| 49 | Họ và tên * | text | ✅ | `full_name` | |
| 51 | Số điện thoại * | tel | ✅ | `phone` | validate VN, normalize |
| 57 | Địa chỉ liên hệ | text | | `address` | → `lead.location` **và** gộp vào note. **Form KHÔNG có ô email** — `email` trong schema là optional và sẽ luôn trống |
| 55 | Bạn đã tốt nghiệp * | select (7 mục) | ✅ | `education_level_raw` | chuẩn hoá ở BE (xem §5) |
| 52 | Hệ xét tuyển * | select (3 mục) | ✅ | `he` | ⚠️ **ẩn theo điều kiện** — xem ghi chú dưới bảng |
| 53 | Ngành xét tuyển * | select (dropdown động) | ✅ | `nganh_xet` | ⚠️ **ẩn theo điều kiện**; lúc tải trang chỉ có 1 mục, nạp thêm sau khi chọn 52 |
| 56 | Ngành đăng ký * | text | ✅ | `nganh_dang_ky` | ⚠️ **ẩn theo điều kiện** |
| 59 | Ghi chú | textarea | | `extra_note` | |
| **63** | **Mã ngành** | text | | `extra_note` | ⚠️ **FIELD MỚI**, bảng 06-24 không có. Ghép vào `extra_note` kèm nhãn rõ: `Mã ngành: …` (xem §8). Nếu action body bỏ field này thì dữ liệu khách nhập sẽ mất mà không lỗi, không cảnh báo — hiện chưa chứng minh được action có tồn tại hay không. **KHÔNG** gộp vào `nganh_dang_ky` — một bên là MÃ, một bên là TÊN; và **KHÔNG** auto-map sang `offering` (D3) |
| 89 | honeypot (`frm_verify`) | text | | `hp` | có giá trị ⇒ coi là bot, KHÔNG tạo lead |

⚠️ **Field 90 không còn tồn tại.** Bảng 06-24 ghi honeypot là "89/90"; đo 11-09 chỉ còn
**một** honeypot là field 89.

⚠️ **`ak_hp_textarea` / `ak_js` là của Akismet, KHÔNG phải field API.** Đó là lớp chống
spam riêng của WordPress, nằm ngoài hợp đồng intake — đừng map nó sang `hp`.

⚠️ **52 / 53 / 56 bắt buộc NHƯNG ẩn theo điều kiện hiển thị**: chúng chỉ hiện sau khi
người dùng chọn field 55, nên một lượt gửi hợp lệ vẫn có thể thiếu chúng nếu người dùng
không đi hết nhánh. Backend **cố ý nhận chúng là optional** — đây không phải sơ suất:
bắt buộc ở BE sẽ biến một lượt đăng ký thật thành 422 chỉ vì logic hiển thị của form.

Chuẩn hoá `education_level`: THPT→`high_school` · Trung cấp/Cao đẳng→`diploma` ·
Đại học→`bachelor` · THCS/Khác→`other`.

`source` cố định = `"website"`.

**`ACTION_URL` = NOT_PROVEN · `HEADER_X_API_KEY` = NOT_PROVEN.** Form post về `admin-ajax`
của WordPress; việc đã có action chuyển tiếp sang QLTS hay chưa, và header `X-API-Key` đã
được đặt hay chưa, **chỉ xác minh được từ trang quản trị WordPress**. Lượt đo 11-09 là ẩn
danh nên không kết luận được — đừng ghi "đã nối" cho tới khi có người đọc được trang đó.


---

## 5. Thiết kế kỹ thuật

### 5.1 Schema — `app/schemas/public_lead_intake.py`
- `PublicLeadIntake`: `full_name`(req), `phone`(req, validate VN reuse phone_helpers),
  `email`(optional), `education_level_raw`(optional str → chuẩn hoá), `address`(optional),
  `he`/`nganh_xet`/`nganh_dang_ky`/`extra_note`(optional, gộp note), `hp`(honeypot, optional).
- `PublicLeadIntakeResult` — **NỘI BỘ, không trả ra caller**: `{ "status": "created" | "updated" | "noted", "lead_id": int }`. Chỉ dùng cho log và test.
- `PublicLeadIntakeAck` — **phản hồi CÔNG KHAI duy nhất**: `{ "status": "received" }`, cố định, không có `lead_id` và không lộ created/updated/noted.
  ⚠️ Đây là hợp đồng CHỐNG ENUMERATION: nếu caller phân biệt được `created` với `updated`/`noted` thì endpoint công khai trở thành công cụ dò "số điện thoại này đã có trong hệ thống chưa". Đừng trả `PublicLeadIntakeResult` ra ngoài, kể cả để "tiện debug".

### 5.2 Service — `app/services/public_lead_intake_service.py`
`intake_public_lead(db, data) -> tuple[result, post_commit_cb]` (KHÔNG nhận current_user):
1. Resolve & validate `default_unit_id = settings.PUBLIC_INTAKE_DEFAULT_UNIT_ID`; nếu
   None/không tồn tại → raise domain error → router map 503 (D9).
2. Normalize phone. **CHỖ CHỨA THÔNG TIN (D13 — option A, đã khảo sát UI):**
   - `address`→`Lead.location`; `education_level_raw`→`Lead.education_level` (chuẩn hoá).
   - `hệ + ngành_xét + ngành_đăng_ký + ghi_chú` → **1 record `Consultation` hệ thống** (insert raw,
     KHÔNG qua `add_consultation`): `officer_id = get_system_user(db).id`
     (`payment_import_service.get_system_user` → canonical `_get_system_application_fee_user`),
     `consultation_status_id = lead.consultation_status_id hiện tại` (tránh "Status #null" trên UI,
     KHÔNG đổi pipeline lead), `consultation_date = now`,
     **`method = SYSTEM_CONSULTATION_METHOD`** (xem D13 — KHÔNG dùng `"website"`),
     `notes = "[web] [Đăng ký qua website dd/mm/yyyy] Hệ: … | Ngành xét tuyển: … |
     Ngành đăng ký: … | Địa chỉ: … | Email: … | Ghi chú: …"` — đúng thứ tự mà
     `_build_intake_note` ghép. ⚠️ Mô tả cũ bỏ sót **địa chỉ, email và ngành đăng ký**;
     cả ba đều CÓ trong note. Phần `Email:` chỉ xuất hiện khi caller gửi `email` —
     form 7 hiện không có ô đó (§4).
     Tiền tố `[web]` là dấu NGUỒN, chỉ phục vụ chống lặp. Hiện ở tab Consultations
     + feed Timeline.
   - ✅ **Sửa 11-09:** bản chốt 06-28 dự kiến gọi
     `lead_cache_service.update_lead_cache(...)` sau khi chèn. Mã hiện hành **KHÔNG gọi**
     (`grep update_lead_cache` trong service = 0) và thế là ĐÚNG: bản ghi mang
     `SYSTEM_CONSULTATION_METHOD` nên aggregate hiện có đã tự loại nó —
     `consultation_count` KHÔNG tăng, `last_consultation_at` KHÔNG bị chiếm, nên không
     có gì phải đồng bộ lại. Không còn "defer lọc". Bất biến này được canh bằng ca
     `test_note_website_khong_bi_tinh_la_tu_van_that`.
3. **`pg_advisory_xact_lock(<intake_ns_const>, hashtext(phone_normalized))`** (D10) — serialize
   các request cùng SĐT trong cùng transaction frame.
4. Lookup lead qua **canonical identity** `repo.get_active_lead_by_phone_identity(phone_normalized)`
   (repo method MỚI: join `LeadPhoneIdentity` deleted_at NULL → `Lead` deleted_at NULL) — **KHÔNG**
   dùng `get_by_phone` raw (D10). Dưới lock:
   - **Không có** → `create_lead(db, LeadCreate(source="website", unit_id=default_unit_id, ...),
     created_by=None)` → auto-assign celery tìm officer cùng unit. `status="created"`.
     Bọc `try/except DuplicateResourceError` (create_lead đã convert IntegrityError→Duplicate qua `_handle_lead_integrity_error`) →
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
> `unit_id` (D9). ⚠️ **KHÔNG** suy ra rằng `unit_managers` vì thế mà luôn có người nhận: resolver trả rỗng khi đơn vị không có manager/admin (unit 14 hiện rỗng — §10). `actor_id=None`
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
`get_intake_key(request)` trả về **`intake_<sha256(X-API-Key)[:16]>`** (per-key) — băm
TRƯỚC, KHÔNG nhét khoá thô vào keyspace Redis. Thiếu header thì lùi về `get_client_ip`
(ưu tiên `X-Real-IP` do nginx ghi đè, không giả mạo được) — **không** dùng
`get_remote_address`: nó chưa từng được import trong `rate_limits.py`, và hop trái nhất
của `X-Forwarded-For` thì client tự prepend được. Verify key là **dependency** riêng
(5.3), KHÔNG nhồi vào key_func — đảm bảo 401 trước đếm limit.

---

## 6. Hạ tầng tái dùng (verified)
- **Canonical phone**: `LeadPhoneIdentity` (model `lead_phone.py`) — partial unique
  `uq_lead_phone_active` ON `phone_normalized` WHERE deleted_at IS NULL; `register_phone_identities`
  (`lead_repository.register_phone_identities`) tự chuẩn hoá `normalize_vietnam_phone`. **Intake lookup = repo method MỚI
  `get_active_lead_by_phone_identity` join identity→lead** (KHÔNG dùng `get_by_phone` raw cho intake).
- `create_lead` auto-assign celery (chỉ create); IntegrityError unique→`DuplicateResourceError` (`_handle_lead_integrity_error`).
- **Trường text trên Lead (đọc `models/lead.py`):** `location`(địa chỉ), `education_level`,
  `officer_summary`(ô "Đánh giá TV", truncate). **KHÔNG có `notes`.** Timeline lead (`get_lead_timeline`
  `lead_service.get_lead_timeline`) = `Consultation` + `assignment_logs` (CRMInteraction KHÔNG hiển thị).
- **System user**: `payment_import_service.get_system_user(db)` (→ canonical `_get_system_application_fee_user`).
- **Cache lead**: `lead_cache_service.update_lead_cache(db, lead_id, lead)` — **luồng intake KHÔNG gọi** (xem §5.2 và D13). Liệt kê ở đây chỉ để biết nó tồn tại: bản ghi website mang `SYSTEM_CONSULTATION_METHOD` nên aggregate đã tự loại, không có gì phải recompute.
- **Tạo Consultation raw**: `models.Consultation(lead_id, officer_id, consultation_status_id, consultation_date, method, notes)` + `db.add` + `db.flush([c])` (mẫu lead_service.py) — KHÔNG dùng `add_consultation` (tránh transition/guard).
- `phone_helpers.normalize_vietnam_phone` / `validate_vietnam_phone`.
- Hard-block sẵn: KHÔNG set trực tiếp `consultation_status_id`/`pipeline_stage_id`;
  `offering_id` đổi bị chặn nếu đã có AdmissionProfile.

---

## 7. Test (`tests/services/test_public_lead_intake.py`, lát **Tier 4**)
> ⚠️ **Đối chiếu 11-09:** mỗi mục dưới đây được đánh dấu ✅ nếu CÓ ca test khẳng định, và
> ⚠️ nếu chỉ là ý định chưa được canh. Bản 06-28 liệt kê tám mục như thể đã phủ hết —
> rà 37 hàm test thì **bốn khẳng định không có ca nào kiểm**. Ghi lại để không ai đọc
> danh sách này rồi tưởng nó là báo cáo độ phủ.
>
> ⚠️ `created`/`updated`/`noted` dưới đây là **kết quả NỘI BỘ của service** (`PublicLeadIntakeResult`, dùng cho log/test). HTTP response công khai LUÔN là `200 {"status": "received"}` — xem §5.1.

1. ✅ Tạo mới SĐT lạ → service trả `created`, lead `source=website`, **unit=default_unit** (`test_new_phone_creates_website_lead`), ⚠️ **NHƯNG "auto-assign tìm officer cùng unit (D9)" CHƯA có ca nào canh**: tác vụ Celery bị `patch` ở **ba vị trí** — helper dùng chung, ca HTTP happy-path và ca concurrency — tức phủ hết các đường tạo lead trong test, và **0 ca** khẳng định `assigned_officer_id`. Đúng đường đang có lỗ hổng quan sát ở §10 — nợ test. **+1 Consultation hệ thống (officer=system, `method = SYSTEM_CONSULTATION_METHOD`, `notes` mở đầu bằng `[web]` và chứa hệ/ngành) hiện trong timeline; pipeline lead KHÔNG đổi; và bản ghi này KHÔNG được tính vào `consultation_count`/`last_consultation_at`** (D13).
2. ✅ Upsert SĐT trùng (non-terminal) → `updated`, không trùng lead (`test_duplicate_phone_updates_not_creates`). ⚠️ Vế **"giữ unit/officer cũ"** CHƯA được khẳng định — ca chỉ assert `status` và số lead. Nợ test.
3. ✅ Lead terminal sts20 → `noted`, **pipeline KHÔNG đổi** (`test_terminal_lead_noted_not_reopened` + `test_pipeline_not_changed_by_intake`). ⚠️ Vế **"notif dispatch"** CHƯA được khẳng định — ca chỉ assert `status`. Nợ test.
4. ⚠️ **CHƯA CÓ CA TEST NÀY.** Mục gốc ghi "Officer NULL trên lead cũ (có unit) → notif fanout unit_managers (D11), không lỗi" như thể đã được canh. Rà 11-09: trong 37 hàm test **không có ca nào** kiểm đường đó. Và với unit 14 (0 manager/admin) thì fanout sẽ ra rỗng chứ không phải "tới quản lý đơn vị". Ghi lại đây như **nợ test**, không phải hạng mục đã xong.
5. ✅ **Double-submit đồng thời cùng SĐT** (D10) — `test_double_submit_dong_thoi_…`, hai session thật → đúng 1 lead, request 2 ra `updated`/`noted`, KHÔNG 500/409. Thêm ca: lookup CANONICAL hit khi raw `Lead.phone` lệch format nhưng `phone_normalized` trùng → ra `updated` (không tạo trùng); ca `create_lead` ném `DuplicateResourceError` → service catch + reload (không 409).
6. ✅ Sai/thiếu API key → **401**; key chưa cấu hình (env rỗng) → **503**; **`PUBLIC_INTAKE_DEFAULT_UNIT_ID` chưa set → 503** (D9).
7. ✅ Honeypot có giá trị → 200 giả, KHÔNG tạo lead (kèm ca khoảng trắng không bị coi là bot).
8. ✅ Phone sai định dạng VN → 422; email optional (form không gửi) → OK.

**Nợ test gom lại (4 khoảng trống, cần một cổng riêng — KHÔNG gộp vào PR này):**
auto-assign gán đúng officer cùng unit · upsert giữ nguyên unit/officer cũ ·
notif dispatch ở đường `noted` · officer NULL → fanout (mục 4). Ba trong bốn khoảng
trống này nằm đúng trên đường phân công — cùng chỗ với lỗ hổng quan sát ở §10.

---

## 8. Phía WordPress (form 7)

Formidable Pro → form 7 → Actions → **Add API** (action #2, giữ action cũ):

- **POST** `https://qlts.tnpc.edu.vn/api/public/leads/intake`
  (URL đích đã xác minh 11-09: `/health` trả 200 qua SNI thật, chứng thư
  `CN=qlts.tnpc.edu.vn` hạn 14-10-2026.)
- Header `X-API-Key: <PUBLIC_INTAKE_API_KEY>` — **BẮT BUỘC**. Thiếu hoặc sai ⇒ backend trả
  **401**; chưa cấu hình khoá ở phía backend ⇒ **503**.

  ⚠️ **Cách ĐẶT header này hiện `NOT_PROVEN`.** Action API chuẩn của Formidable dựng sẵn
  ô xác thực theo kiểu **Basic Auth**, không có ô nhập header tuỳ ý. Muốn gắn một header
  riêng thì phải qua filter `frm_api_request_args` ở phía WordPress, và filter đó **phải
  được giới hạn đúng action/URL** — nếu không, khoá sẽ bị gắn vào MỌI lời gọi API của mọi
  form, tức rò khoá sang bên thứ ba.

  ⛔ **Basic Auth KHÔNG thay thế được `X-API-Key`.** Backend chỉ đọc header đó
  (`verify_intake_api_key`); gửi Basic Auth mà không gửi `X-API-Key` thì kết quả là 401,
  không phải "đăng nhập bằng cách khác".

  Việc chốt cơ chế inject phải làm cùng lúc với việc đọc được trang quản trị WordPress —
  hai thứ này cùng một cổng.

  **`WORDPRESS_SECRET_STORAGE = NOT_PROVEN`** — chưa ai xác định hook sẽ lấy khoá TỪ ĐÂU.
  Bốn ràng buộc, phải chốt trước khi bật:

  - ⛔ **Không hard-code khoá** vào theme, code snippet, hay body của action. Theme và
    snippet nằm trong bản sao lưu WordPress, trong bản xuất, và trong tay bất kỳ ai có
    quyền sửa giao diện — phạm vi rộng hơn hẳn người được biết khoá.
  - ⛔ **Không ghi header ra log.** Một dòng `error_log` in `$args` là đủ để khoá nằm trong
    tệp log của máy chủ web.
  - ✅ Hook đọc khoá từ **cấu hình phía máy chủ** (hằng số trong `wp-config.php` hoặc biến
    môi trường), không từ CSDL WordPress nếu tránh được.
  - ✅ Hook **giới hạn đúng action/URL đích**; không giới hạn thì khoá bị gắn vào MỌI lời
    gọi API của mọi form.

  Xoay khoá phải làm được mà không sửa mã: đổi giá trị ở hai đầu (`.env.production` của
  QLTS và cấu hình máy chủ WordPress) rồi recreate — xem §9.
- Body map:

  | Field form | → khoá JSON |
  |---|---|
  | `[49]` | `full_name` |
  | `[51]` | `phone` |
  | `[57]` | `address` |
  | `[55 show]` | `education_level_raw` |
  | `[52 show]` | `he` |
  | `[53 show]` | `nganh_xet` |
  | `[56]` | `nganh_dang_ky` |
  | **`[63]` + `[59]`** | **`extra_note`** — ghép thành MỘT giá trị, giữ nhãn: `Mã ngành: [63] \| [59]` |
  | `[89]` | `hp` (honeypot) |

  ⚠️ **Field 63 "Mã ngành" phải có mặt trong body.** Nó là field mới (xem §4) và không có
  khoá riêng trong schema, nên nếu action body bỏ nó thì dữ liệu khách nhập **sẽ mất** —
  không lỗi, không cảnh báo. Ghép vào `extra_note` kèm nhãn rõ để officer đọc được trong
  ghi chú. KHÔNG gộp vào `nganh_dang_ky` (mã ≠ tên) và KHÔNG auto-map sang `offering` (D3).

  Nếu Formidable không ghép được hai shortcode vào một trường thì mới cân nhắc thêm trường
  `major_code` vào schema — đó là thay đổi mã, PR riêng.

- Ba field `[52]/[53]/[56]` ẩn theo điều kiện nên **có thể rỗng**; backend nhận optional,
  action không cần chặn.
- KHÔNG cần CORS (gọi server-side). Giữ UX "đăng ký thành công" (action chạy ngầm).

### Trạng thái xác minh

| Hạng mục | Trạng thái |
|---|---|
| URL đích của QLTS | ✅ **ĐÃ BIẾT** — `https://qlts.tnpc.edu.vn/api/public/leads/intake` |
| Action #2 đã tồn tại trong WordPress chưa | ❓ **NOT_PROVEN** |
| Header `X-API-Key` đã được đặt chưa | ❓ **NOT_PROVEN** |
| Cơ chế đặt header (Basic Auth ≠ header tuỳ ý; cần `frm_api_request_args` có giới hạn) | ❓ **NOT_PROVEN** |
| `WORDPRESS_SECRET_STORAGE` — hook sẽ đọc khoá TỪ ĐÂU | ❓ **NOT_PROVEN** |
| `PUBLIC_INTAKE_API_KEY` | ⛔ **ABSENT** trên production (đo 11-09) |
| `PUBLIC_INTAKE_DEFAULT_UNIT_ID` | ⛔ **ABSENT** trên production (đo 11-09) |

Phân biệt cho rõ: **URL đích thì đã biết**, nhưng **cấu hình action hiện tại bên WordPress
thì chưa ai xác minh** — lượt đo 11-09 là ẩn danh, không đăng nhập trang quản trị. Đừng ghi
"đã nối" cho tới khi có người đọc được Actions của form 7.

**Chờ chủ dự án cung cấp:** (1) giá trị `PUBLIC_INTAKE_API_KEY` — sinh/lưu/chuyển qua một
cổng RIÊNG, không đi qua stdout/argv/history; (2) `PUBLIC_INTAKE_DEFAULT_UNIT_ID` = đơn vị
nhận lead website (D9).
---

## 9. Deploy
- BE-only, **KHÔNG migration**, KHÔNG Casbin (endpoint public).
- Thêm hai biến vào `.env.production`:
  - `PUBLIC_INTAKE_API_KEY=<khoá>` — xem cảnh báo lưu trữ ở §8
  - `PUBLIC_INTAKE_DEFAULT_UNIT_ID=<id đơn vị>` (D9 — thiếu thì endpoint trả 503, an toàn)

  ⚠️ `restart` **không** đọc lại `env_file`: biến được nướng vào container lúc TẠO.
  Phải **recreate**. Ba service dùng `.env.production` là `backend`, `celery-worker`,
  `celery-beat`:

  ```bash
  docker compose -f docker-compose.yml --env-file .env.production \
      --profile production up -d --no-deps --wait backend celery-worker celery-beat
  ```

  ⛔ **KHÔNG viết `docker compose … up -d` kiểu rút gọn.** Thiếu `-f docker-compose.yml`
  thì Compose TỰ NẠP `docker-compose.override.yml` của DEV — đo thật đã cho ra backend
  chạy `uvicorn --reload`, `APP_ENV=development`, bind-mount mã nguồn, mà **không báo gì**.
  Thiếu `--no-deps` thì lệnh kéo theo cả postgres/redis; thiếu tên service thì nó cuốn cả
  nginx vào và thay container đang phục vụ bằng một cấu hình chưa đo lần nào.

  ⚠️ **`--wait` KHÔNG phải cổng nghiệm thu Celery.** `celery-worker` và
  `celery-beat` đều khai `healthcheck: disable: true` trong `docker-compose.yml`,
  nên `--wait` chỉ đợi chúng đạt trạng thái `running` — một worker khởi động rồi
  chết vì sai cấu hình vẫn đi qua được cổng này. Sau recreate **bắt buộc kiểm tay**
  bốn điều, và chỉ khi đủ cả bốn mới coi là nạp env xong:

  1. `backend` đạt **`healthy`** (health thật, không phải `running`).
  2. Đúng **một** worker trả `pong`, và nó nhận **cả hai** hàng đợi `default` +
     `celery` — sai hàng đợi thì tác vụ phân công nằm im, không có lỗi nào hiện ra.
  3. `celery-beat` giữ **nguyên PID và `StartedAt` qua hai lần lấy mẫu** cách nhau
     — beat crash-loop vẫn hiện `running` ở khoảng giữa hai lần khởi động lại.
  4. Cả ba service `RestartCount=0`, log không có `fatal`/`traceback` mới sau mốc
     recreate.

  Thiếu một trong bốn ⇒ activation CHƯA xong, dù `up -d` trả 0 và `--wait` im lặng.

  Backend và cả hai Celery cùng dùng `.env.production`, nên cân nhắc ghi env **trước**
  khi duyệt deployment để chỉ cutover MỘT lần (xem §10).
- Tuân: push/PR/merge/deploy **xin phép riêng từng lần** (memory `push-pr-deploy-needs-explicit-ok`).

---

## 10. Trạng thái
- [x] Repo: `get_active_lead_by_phone_identity(phone_normalized)` (canonical lookup, D10)
- [x] Service helper: insert Consultation hệ thống (system-user, raw, no-transition)
      (D13) — **KHÔNG** cache update, xem §5.2
- [x] Code BE (schema/service/router/config/rate-limit)
- [x] Test — **37 hàm test → 40 pytest node** (4 node do parametrize placeholder),
      gồm rate-limit động, bất biến aggregate, concurrency thật hai session, validator config
- [x] Local verify — full Tier 4 xanh, visibility guard đạt + kiểm ngược đỏ
- [x] Push nhánh + mở PR
- [ ] Chủ cung cấp `PUBLIC_INTAKE_API_KEY` + `PUBLIC_INTAKE_DEFAULT_UNIT_ID` — đo 11-09 trên
      production: **cả hai ABSENT**, nên sau deploy endpoint trả 503 (fail-closed đúng).
      ⚠️ Khoá phải sinh/lưu/chuyển qua một cổng RIÊNG, KHÔNG in ra stdout/argv/history.
- [ ] WP form 7 API action #2 — `ACTION_URL`/`HEADER_X_API_KEY` hiện **NOT_PROVEN** (xem §4)
- [ ] Deploy + set env — ⚠️ dùng `up -d`, **KHÔNG** `restart`: env được nướng vào container
      lúc TẠO. Cân nhắc ghi env TRƯỚC khi duyệt deployment để chỉ cutover một lần.

### 🔴 CHẶN ACTIVATION — thất bại phân công đang IM LẶNG

Đo trên production 11-09 (unit 14 "Phòng Tuyển Sinh", nơi lead website sẽ đổ về):

```
8 officer thuoc unit 14:  4 active, 4 banned
pool auto-assign thuc te = 3   (16 con 17 cho | 18 con 72 | 26 con 203)
officer 21: om 99 lead tren tran 50 -> vuot 49, bo can tai khong chon nua
tong cho trong con lai = 292
manager + admin trong unit 14 = 0
```

Luật thông báo đọc từ mã (`core/notification_seed_defaults.py`):

| Sự kiện | Người nhận | Với unit 14 |
|---|---|---|
| `LEAD_CREATED` (lead mới từ web) | `unit_managers` | **∅ không ai** |
| `LEAD_ASSIGNED` (Celery gán xong) | `lead_owner` | ✅ officer được báo |
| `LEAD_ASSIGNMENT_FAILED` | `unit_managers` | **∅ không ai** |

⇒ Đường THÀNH CÔNG có người nhận, nhưng **cả hai đầu của đường HỎNG thì không**: lead vừa
tạo không ai biết, và khi pool cạn 292 chỗ thì cảnh báo thất bại cũng không ai nhận. Cộng
với việc workflow deploy không gate Celery và log worker chỉ giữ ~3,6 ngày, đây là hỏng im
lặng đúng nghĩa. `CONSULTATION_CREATED` (D11) **không** cứu được: nó chỉ áp cho lead ĐÃ
tồn tại, không áp cho lead mới.

Ba hướng, **chưa chốt**:

1. Resolver có DỰ PHÒNG cho `LEAD_CREATED` + `LEAD_ASSIGNMENT_FAILED`: `unit_managers` rỗng
   thì rơi về admin hệ thống. Việc code, **PR riêng**, không gộp vào PR này.
2. Cảnh báo định kỳ "lead chưa được phân công quá N giờ" — bắt được CẢ ca Celery chết lẫn
   ca pool cạn, không phụ thuộc luật thông báo nào. Rẻ nhất và phủ rộng nhất.
3. Bổ nhiệm manager cho unit 14 — **không khuyến nghị chỉ để nhận thông báo**: role đó mang
   quyền duyệt hồ sơ và sửa phân công, rộng hơn nhiều so với nhu cầu.

❌ **Không** nâng `max_capacity` của officer 21 để "chữa": nó không làm Celery sống lại,
không tạo ra người nhận cảnh báo, và giao thêm việc cho người đã quá tải.

Quyết định này **chặn bước bật env**, nhưng **không chặn merge code** — code đang fail-closed
503 nên sau merge vẫn chưa có lead nào đi vào.
