# SMS Marketing Module — Thiết kế triển khai

> Trạng thái: **Thiết kế đã chốt (scope v2 — Contact Group)** — cập nhật 2026-05-26. VERDICT GO cho PR-1. Chờ triển khai (chưa code).
> Scope: **SMS Marketing Contact + Campaign Export + Click Tracking + (Phase 2) Deep Engagement + Lead Consultation Link**. KHÔNG phải campaign upload số tạm thời. Liên hệ là thực thể bền vững, dùng lại qua nhiều campaign.
>
> **Chia 2 phase**:
> - **Phase 1 (core — ship trước)**: **§1–§15 + §17 (pháp lý)**. Quản lý nhóm liên hệ → import → campaign chọn nhóm → build snapshot + render cá nhân hóa + short-link riêng → preflight 160/70 → export Excel per nhà mạng đúng format mẫu → **click tracking cơ bản** → report click ngày/tháng/năm → opt-out toàn cục. **KHÔNG đụng §16.**
> - **Phase 2 (sau core — toàn bộ §16)**: landing 2 tầng (danh mục ngành + trang từng ngành) → **đo thời gian ở lại từng ngành** → hồ sơ "ngành quan tâm" per contact → **link tư vấn 1-1 cho officer gửi lead** → tab interest trong trang lead. Mục đích kép: officer tư vấn cá nhân + thống kê ngành hot.
>
> **Gửi tự động qua SMS API = DEFER (admin tự upload lên hệ thống nhà mạng ngoài QLTS).**

---

## 1. Mục tiêu & nguyên tắc

QLTS **không trực tiếp gửi SMS**. Hệ thống:
1. Quản lý **danh bạ liên hệ** (contact) theo **nhóm** (parent/student/teacher/lead/custom) — bền vững, tái sử dụng.
2. Cho admin tạo **campaign** chọn 1+ nhóm, soạn nội dung **cá nhân hóa** (`{name}`/`{full_name}`/`{link}`), chỉ định link đích.
3. **Build** → snapshot recipient (dedupe theo số toàn campaign), render từng tin, sinh short-link riêng từng contact, đo GSM-7/UCS-2.
4. **Export** Excel **đúng format mẫu nhà mạng**, tách file theo nhà mạng. Admin upload + gửi ngoài QLTS.
5. **Tracking click** + **report** theo ngày/tháng/năm × campaign × nhóm × nhà mạng.
6. **Opt-out toàn cục** theo `phone_normalized`, áp dụng mọi campaign sau.

Hệ quả cốt lõi: vì QLTS không tự gửi, **reply STOP không tự về QLTS** → opt-out thu qua (a) nút landing page QLTS host, (b) admin ghi nhận thủ công.

---

## 2. Quyết định đã chốt

### 2.1 Nghiệp vụ
| # | Quyết định | Hệ quả kỹ thuật |
|---|---|---|
| 1 | Liên hệ bền vững, **duy nhất toàn hệ thống theo `phone_normalized`** | `sms_contact.phone_normalized` UNIQUE |
| 2 | 1 liên hệ thuộc **nhiều nhóm** | bảng N-N `sms_contact_group_member` |
| 3 | Campaign chọn **1+ nhóm**; build tạo **snapshot** | `sms_campaign_group` + `sms_campaign_recipient` (snapshot fields) |
| 4 | Contact ở nhiều nhóm được chọn → **gửi 1 lần** | UNIQUE `(campaign_id, phone_normalized_snapshot)` |
| 5 | Snapshot **đóng băng** tại thời điểm build; nhóm/contact đổi sau không ảnh hưởng campaign đã build | mọi field dùng để gửi đều là `*_snapshot` |
| 6 | Cá nhân hóa qua biến `{name}`/`{full_name}`/`{link}`; **`{link}` tùy chọn** (chỉ bắt buộc khi `external` + có `landing_url` — xem B5 §14) | render per-recipient; validate biến |
| 7 | Phân loại nhà mạng theo prefix — **chỉ để khớp format upload**, KHÔNG đảm bảo nhà mạng hiện tại (MNP). **Chấp nhận rủi ro** | `sms_prefix_carrier_rule` + bucket `unknown` |
| 8 | Export Excel **đúng format mẫu**, tách file per nhà mạng, filename `{Nhóm}-{Campaign}-{NhàMạng}.xlsx` | §8 |
| 9 | Quyền **Phase 1 = chỉ admin**; **Phase 2 thêm officer** (tạo link tư vấn 1-1 + xem interest cho lead trong scope IDOR) | Casbin `role:admin` wildcard + officer policy (§16.6) |

### 2.2 Bảo mật / Compliance (giữ nguyên từ v1)
- Không lưu raw short code trong DB — chỉ `token_hash` = **HMAC-SHA256(code, `SMS_TOKEN_HASH_SECRET`)** (partial UNIQUE). HMAC (không phải plain SHA256) vì token chỉ 7 ký tự → nếu DB lộ, plain hash brute-force offline được; HMAC với server secret chặn điều đó.
- File export (phone + raw short code) lưu **ngoài public webroot**; chỉ tải qua endpoint admin.
- Click event **không lưu IP thô** → `ip_hash` HMAC.
- External redirect: **validate allowlist khi tạo campaign + kiểm tra lại trước redirect**.
- Landing default `qlts_hosted`; `external` cần warning/confirmation.
- **Opt-out toàn cục** theo `phone_normalized`, áp mọi campaign sau.
- Export **bị chặn cho tới khi admin xác nhận DNC/consent** (`dnc_checked_*`).
- Số opt-out bị loại khi build/export.
- Public `/r/{code}` **rate-limit**.
- Bot/link-preview clicks **flag + không tính CTR chính**.

---

## 3. Sơ đồ luồng

```
[Admin] tạo nhóm (parent/student/teacher/lead/custom)
   │
   ├── upload liên hệ vào nhóm (full_name, phone, note)
   │     → contact unique theo phone_normalized; có thì add membership, chưa thì tạo
   │     → ghi sms_contact_import_batch (counts + consent_basis)
   ▼
[Admin] tạo campaign: nội dung (biến {name}/{link}), landing_type+url
   ├── chọn 1+ nhóm  (sms_campaign_group)
   ▼
[BUILD] (service)
   1. gom member của các nhóm đã chọn → dedupe theo phone_normalized (gửi 1 lần)
   2. SNAPSHOT contact (full_name/phone/note + group_ids đóng góp)
   3. loại số trong sms_opt_out (excluded_reason=opted_out)
   4. phân loại carrier theo prefix → bucket (unknown nếu không khớp)
   5. nếu template có {link}: sinh short_code base62×7 (UNIQUE), lưu token_hash
   6. render message per-recipient ({full_name}→tên, {link}→short url)
   7. đo ký tự + encoding + segments; vượt 1 segment → is_over_limit + excluded_reason=over_limit
   ▼
[PREFLIGHT] tổng / hợp lệ / loại (opt-out/invalid/over_limit) / phân bố nhà mạng
   ▼
[Admin xác nhận DNC/consent] → dnc_checked_at  (BẮT BUỘC trước export)
   │  + export CHẶN nếu còn recipient over_limit (hard gate B1) → admin sửa template
   ▼
[EXPORT] Excel per nhà mạng (Sheet1, no header, data từ row 2, A=84xxx text, B=nội dung text)
   → filename {Nhóm}-{Campaign}-{NhàMạng}.xlsx (sanitize) → lưu NGOÀI webroot
   ▼
[Admin] upload lên hệ thống nhà mạng (NGOÀI QLTS) → bấm "Đã upload" per nhà mạng
   ▼
[Người nhận] bấm link → GET /r/{code} → ghi click (ip_hash, bot flag) → 302 redirect
   │                                          qlts_hosted → /lp/{code} (nút "Hủy nhận tin")
   │                                          external → landing_url (chỉ nếu host ∈ allowlist)
   ▼
[REPORT] click theo ngày/tháng/năm × campaign × nhóm × nhà mạng;
         danh sách liên hệ đã click (human_click_count, first/last_human_clicked_at); CTR loại bot
```

---

## 4. Data model (11 bảng)

> Quy ước: `created_at`/`updated_at` = `DateTime(timezone=True)` `server_default=func.now()`; FK user `ondelete="SET NULL"`.
>
> ⚠ **Convention ORM (PR-1)**: dùng **SQLAlchemy 2.0 `Mapped[]` + `mapped_column`** — **đọc 1 model mẫu thật** (vd `app/models/finance/`) để match style + cách import `Base`, KHÔNG tự chế.
> ⚠ **Index đặc biệt phải VIẾT TAY trong migration** (autogenerate KHÔNG sinh đúng): mọi **partial UNIQUE** (mệnh đề `WHERE`) dùng `postgresql_where=sa.text(...)`; **GIN** dùng `postgresql_using="gin"`. Kiểm tra lại migration sau autogenerate, đừng tin máy sinh.

### 4.1 `sms_contact_group`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(200) NOT NULL | |
| `code` | String(50) UNIQUE NOT NULL | slug |
| `group_type` | String(20) NOT NULL | parent / student / teacher / lead / custom |
| `description` | Text NULL | |
| `is_active` | Boolean default TRUE | |
| `created_by_id` | FK user NULL | |
| `created_at`, `updated_at` | DateTime tz | |

### 4.2 `sms_contact`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `full_name` | String(255) NOT NULL | |
| `phone_raw` | String(32) | số gốc nhập |
| `phone_normalized` | String(20) **UNIQUE** NOT NULL | `0xxxxxxxxx` — duy nhất toàn hệ thống |
| `phone_international` | String(20) NOT NULL | `84xxxxxxxxx` (derive từ `to_zalo_phone`) |
| `note` | Text NULL | ghi chú đơn giản |
| `source_label` | String(255) NULL | nguồn liên hệ |
| `consent_basis` | String(30) NULL | implied_lead / event_collected / provided_by_partner / unknown |
| `consent_note` | Text NULL | |
| `created_by_id` | FK user NULL | |
| `created_at`, `updated_at` | DateTime tz | |

### 4.3 `sms_contact_group_member` (N-N)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `group_id` | FK sms_contact_group CASCADE, index | |
| `contact_id` | FK sms_contact CASCADE, index | |
| `note` | Text NULL | ghi chú riêng trong nhóm này (optional) |
| `added_by_id` | FK user NULL | |
| `created_at` | DateTime tz | |

Constraint: **UNIQUE `(group_id, contact_id)`**.

### 4.4 `sms_contact_import_batch` (audit import + consent trail)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `group_id` | FK sms_contact_group CASCADE, index | nhóm đích |
| `file_name` | String(255) NULL | |
| `file_sha256` | String(64) NULL | |
| `source_label` | String(255) NULL | |
| `consent_basis` | String(30) NULL | áp cho contact mới tạo từ lô |
| `consent_note` | Text NULL | |
| `row_count` | Integer | tổng dòng |
| `valid_count` | Integer | normalize hợp lệ |
| `invalid_count` | Integer | sai định dạng |
| `duplicate_contact_count` | Integer | trùng phone trong CHÍNH file upload |
| `existing_member_count` | Integer | contact đã là member nhóm này |
| `inserted_contact_count` | Integer | contact mới tạo (phone chưa từng có) |
| `added_member_count` | Integer | membership mới thêm |
| `skipped_count` | Integer | bỏ qua (invalid/duplicate) |
| `uploaded_by_id` | FK user NULL | |
| `created_at` | DateTime tz | |

> Logic import: với mỗi dòng — normalize phone → nếu invalid: `invalid_count++`, skip. Nếu phone đã tồn tại `sms_contact`: **tái dùng contact** (KHÔNG ghi đè full_name/note — xem Blocker B3), `inserted_contact_count` giữ nguyên; nếu phone mới: tạo contact (`inserted_contact_count++`). Sau đó thêm membership: nếu đã là member → `existing_member_count++`; nếu chưa → `added_member_count++`. Trùng phone trong cùng file → `duplicate_contact_count++` (chỉ xử lý lần đầu).
>
> **Bất biến count (anchor test PR-2)**: `valid_count` = hợp lệ & duy nhất trong file. → `row_count = valid_count + invalid_count + duplicate_contact_count`; `skipped_count = invalid_count + duplicate_contact_count`; `added_member_count + existing_member_count = valid_count`; `inserted_contact_count ≤ valid_count` (reused = `valid_count − inserted_contact_count`).

### 4.5 `sms_prefix_carrier_rule` (config, seed idempotent)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `prefix` | String(4) UNIQUE | "032","086",… (3 ký tự sau số 0) |
| `carrier_code` | String(20) | viettel/vinaphone/mobifone/vietnamobile/gmobile |
| `carrier_name` | String(50) | |
| `is_active` | Boolean default TRUE | |
| `note` | Text NULL | |
| `created_at`, `updated_at` | DateTime tz | |

> Docstring model BẮT BUỘC: *"Bảng này chỉ để khớp **định dạng file upload** của nhà mạng. Do MNP (chuyển mạng giữ số), đầu số chỉ phản ánh **mạng gốc**, KHÔNG phải mạng hiện tại. Không dùng để định tuyến chính xác. Số không khớp → bucket `unknown` kiểm tra thủ công. Rủi ro này được chấp nhận theo Quyết định #7."*

### 4.6 `sms_campaign`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(200) NOT NULL | |
| `code` | String(50) UNIQUE NOT NULL | |
| `status` | String(20) default 'draft' | draft → ready → exported → sent → closed |
| `sms_template` | Text NOT NULL | chứa `{name}`/`{full_name}`/`{link}` |
| `landing_type` | String(20) NOT NULL default 'qlts_hosted' | qlts_hosted / external |
| `landing_url` | Text NULL | bắt buộc nếu external; host phải ∈ allowlist (§6.2) |
| `dnc_checked_at` | DateTime tz NULL | mốc xác nhận DNC/consent (gate export) |
| `dnc_checked_by_id` | FK user NULL | |
| `dnc_reference` | String(255) NULL | |
| `created_by_id` | FK user NULL | |
| `created_at`, `updated_at`, `sent_marked_at` | DateTime tz | |

> **Transition `status`** (PR-3): tạo = `draft`; `build` thành công → `ready`; `export` (DNC + over_limit sạch) → `exported`; admin bấm "Đã upload" đủ các nhà mạng → `sent`; đóng → `closed`. Sửa campaign chỉ cho phép khi `draft`.

### 4.7 `sms_campaign_group`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `campaign_id` | FK sms_campaign CASCADE, index | |
| `group_id` | FK sms_contact_group CASCADE, index | |
| `created_at` | DateTime tz | |

Constraint: **UNIQUE `(campaign_id, group_id)`**.

### 4.8 `sms_campaign_recipient` (snapshot — bảng trung tâm)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `campaign_id` | FK sms_campaign CASCADE NOT NULL, index | |
| `contact_id` | FK sms_contact **SET NULL** NULL | snapshot giữ kể cả khi contact bị xoá |
| `group_ids_snapshot` | ARRAY(Integer) (GIN index) | nhóm đã chọn đóng góp contact này (report theo nhóm) |
| `full_name_snapshot` | String(255) | |
| `phone_normalized_snapshot` | String(20) NULL | `0xxxxxxxxx` |
| `phone_international_snapshot` | String(20) NULL | `84xxxxxxxxx` (xuất Excel) |
| `note_snapshot` | Text NULL | |
| `carrier_bucket` | String(20) NULL | viettel … unknown |
| `token_hash` | String(64) NULL | **HMAC-SHA256(short_code, SMS_TOKEN_HASH_SECRET)**; NULL nếu template không có `{link}` |
| `rendered_message` | Text NULL | tin đã render đầy đủ |
| `message_length` | Integer NULL | |
| `encoding` | String(8) NULL | GSM7 / UCS2 |
| `segments` | Integer NULL | |
| `is_over_limit` | Boolean default FALSE | vượt 1 segment |
| `excluded_reason` | String(20) NULL | opted_out / over_limit / NULL(=sẽ export). **`invalid_phone` = defensive-only**: build từ contact (đã normalize+validate khi import) gần như KHÔNG sinh ra → đừng viết nhánh xử lý invalid ở build |
| `raw_click_count` | Integer default 0 | tổng click GỒM bot (audit) |
| `human_click_count` | Integer default 0 | click loại bot — **đây mới là "đã click" hiển thị cho người dùng** |
| `first_human_clicked_at` | DateTime tz NULL | lần click thật đầu (denormalize dashboard) |
| `last_human_clicked_at` | DateTime tz NULL | lần click thật cuối |
| `created_at` | DateTime tz | |

Constraint & index (⚠ **viết tay trong migration**, xem cảnh báo §4 intro):
- **partial UNIQUE `(campaign_id, phone_normalized_snapshot)` WHERE `... IS NOT NULL`** → gửi 1 lần/campaign (Quyết định #4). `postgresql_where`.
- **partial UNIQUE `(token_hash)` WHERE `token_hash IS NOT NULL`** → resolve short-link + chống đụng token. `postgresql_where`.
- **GIN index** trên `group_ids_snapshot` → report theo nhóm (`:gid = ANY(group_ids_snapshot)`). `postgresql_using="gin"`.
- **composite index `(campaign_id, carrier_bucket)`** → tăng tốc export/preflight (lọc per campaign + nhà mạng). Thêm ngay PR-1 (tránh migration thứ hai).

### 4.9 `sms_campaign_export_batch`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `campaign_id` | FK CASCADE, index | |
| `group_id` | FK sms_contact_group NULL | NULL nếu export gộp nhiều nhóm (B2 — gộp per carrier) |
| `group_name_snapshot` | String(200) NULL | nhãn filename: 1 nhóm→tên nhóm; nhiều nhóm→`NhomA+NhomB+N` (B2) |
| `carrier_bucket` | String(20) | nhà mạng của file |
| `recipient_count` | Integer | |
| `file_name` | String(255) | `{Nhóm}-{Campaign}-{NhàMạng}.xlsx` (đã sanitize) |
| `storage_path` | String(512) NULL | **NGOÀI public webroot** (§9.7) |
| `file_sha256` | String(64) NULL | |
| `file_size_bytes` | BigInteger NULL | |
| `expires_at` | DateTime tz NULL | mốc hết hạn re-download |
| `purged_at` | DateTime tz NULL | mốc đã xoá file (retention) |
| `status` | String(20) default 'generated' | generated / uploaded |
| `generated_by_id` | FK user NULL | |
| `generated_at` | DateTime tz | |
| `marked_uploaded_at` | DateTime tz NULL | bấm "Đã upload" per nhà mạng |

### 4.10 `sms_click_event`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `recipient_id` | FK sms_campaign_recipient CASCADE, index | |
| `campaign_id` | FK, index | denormalize query nhanh |
| `contact_id` | FK sms_contact SET NULL NULL | |
| `clicked_at` | DateTime tz, index | |
| `ip_hash` | String(64) NULL | **HMAC-SHA256(ip, `SMS_TOKEN_HASH_SECRET`)** — dùng chung secret với token; KHÔNG lưu IP thô |
| `ip_prefix` | String(20) NULL | optional, vd `1.2.3.0/24` |
| `user_agent` | String(512) NULL | |
| `is_suspected_bot` | Boolean default FALSE | scanner/link-preview/prefetch |
| `bot_reason` | String(50) NULL | known_scanner_ua / prefetch_head / instant_after_send |

> Mỗi click 1 row (gồm bot — giữ audit). **CTR chính = COUNT(DISTINCT recipient_id) WHERE `is_suspected_bot=FALSE`** / tổng đã export. Denormalize lên recipient mỗi click: `raw_click_count` (mọi click) + `human_click_count`/`first_human_clicked_at`/`last_human_clicked_at` (chỉ click không phải bot).

### 4.11 `sms_opt_out` (toàn cục)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `phone_normalized` | String(20) **UNIQUE** NOT NULL | khóa toàn cục |
| `source` | String(20) NOT NULL | landing_optout / manual |
| `campaign_id` | FK NULL | campaign dẫn tới opt-out |
| `contact_id` | FK sms_contact SET NULL NULL | |
| `revoked_by_id` | FK user NULL | ai ghi (manual) |
| `reason` | Text NULL | |
| `created_at` | DateTime tz | |

> Áp dụng **mọi campaign sau**: bước build (§3.3) loại số có trong bảng này.

---

## 5. Seed `sms_prefix_carrier_rule` (migration idempotent)

```sql
INSERT INTO sms_prefix_carrier_rule (prefix, carrier_code, carrier_name, is_active, created_at, updated_at)
VALUES
  -- Viettel: 032-039, 086, 096, 097, 098
  ('032','viettel','Viettel',TRUE,NOW(),NOW()),('033','viettel','Viettel',TRUE,NOW(),NOW()),
  ('034','viettel','Viettel',TRUE,NOW(),NOW()),('035','viettel','Viettel',TRUE,NOW(),NOW()),
  ('036','viettel','Viettel',TRUE,NOW(),NOW()),('037','viettel','Viettel',TRUE,NOW(),NOW()),
  ('038','viettel','Viettel',TRUE,NOW(),NOW()),('039','viettel','Viettel',TRUE,NOW(),NOW()),
  ('086','viettel','Viettel',TRUE,NOW(),NOW()),('096','viettel','Viettel',TRUE,NOW(),NOW()),
  ('097','viettel','Viettel',TRUE,NOW(),NOW()),('098','viettel','Viettel',TRUE,NOW(),NOW()),
  -- VinaPhone: 081-085, 088, 091, 094
  ('081','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('082','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
  ('083','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('084','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
  ('085','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('088','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
  ('091','vinaphone','VinaPhone',TRUE,NOW(),NOW()),('094','vinaphone','VinaPhone',TRUE,NOW(),NOW()),
  -- MobiFone: 070, 076, 077, 078, 079, 089, 090, 093
  ('070','mobifone','MobiFone',TRUE,NOW(),NOW()),('076','mobifone','MobiFone',TRUE,NOW(),NOW()),
  ('077','mobifone','MobiFone',TRUE,NOW(),NOW()),('078','mobifone','MobiFone',TRUE,NOW(),NOW()),
  ('079','mobifone','MobiFone',TRUE,NOW(),NOW()),('089','mobifone','MobiFone',TRUE,NOW(),NOW()),
  ('090','mobifone','MobiFone',TRUE,NOW(),NOW()),('093','mobifone','MobiFone',TRUE,NOW(),NOW()),
  -- Vietnamobile: 052, 056, 058, 092
  ('052','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),('056','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),
  ('058','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),('092','vietnamobile','Vietnamobile',TRUE,NOW(),NOW()),
  -- Gmobile/khác: 059, 099 (+ 055, 087 nếu nhà mạng yêu cầu tách)
  ('059','gmobile','Gmobile',TRUE,NOW(),NOW()),('099','gmobile','Gmobile',TRUE,NOW(),NOW()),
  ('055','gmobile','Gmobile',TRUE,NOW(),NOW()),('087','gmobile','Gmobile',TRUE,NOW(),NOW())
ON CONFLICT (prefix) DO NOTHING;
```

Phân loại lúc build: 3 ký tự đầu sau số `0` của `phone_normalized_snapshot` → tra rule active → `carrier_bucket`; không khớp → `unknown`.

---

## 6. Short-link, token & resolve

### 6.1 Token & resolve
- **Token**: base62 (`[0-9A-Za-z]`) × 7. Không gian 62⁷ ≈ 3,52×10¹² → dư cho hàng triệu.
- **Sinh** (chỉ khi template có `{link}`): `secrets.choice` ×7; `token_hash = HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET)`; INSERT dựa trên partial UNIQUE `(token_hash) WHERE token_hash IS NOT NULL`; đụng → retry N lần.
- **Lưu DB**: chỉ `token_hash`. Raw `code` → file Excel + SMS.
- **`SMS_TOKEN_HASH_SECRET`**: env/secret server-side, KHÔNG commit. Đổi secret sẽ vô hiệu mọi link cũ (chấp nhận — link có vòng đời ngắn theo campaign).
- **Resolve** `GET /r/{code}`:
  1. **Rate-limit theo IP** (pattern Redis như `magic_link_rate_limit`).
  2. `HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET)` → tra `recipient.token_hash`.
  3. Không thấy → 404.
  4. Thấy → ghi `sms_click_event` (ip_hash + đánh giá bot) + cập nhật denormalized: luôn `raw_click_count++`; nếu **không** phải bot thì thêm `human_click_count++` + `first/last_human_clicked_at` → **302 redirect**: `qlts_hosted`→`/lp/{code}`; `external`→`landing_url` (chỉ nếu host ∈ allowlist, ngược lại 404 + log).

> `GET /r/{code}` là GET → CSRF không áp dụng.

### 6.2 Allowlist domain redirect (bắt buộc)
`/r/{code}` công khai → nếu redirect tùy ý sẽ thành open-redirector (phishing, kể cả khi admin account bị chiếm).
- **2 lớp kiểm tra**: (1) lúc tạo/sửa campaign external → parse host `landing_url`, từ chối 400 nếu ∉ allowlist; (2) lúc redirect → kiểm tra lại host.
- **Nguồn (MVP)**: env `SMS_ALLOWED_REDIRECT_DOMAINS` (CSV, vd `qlts.tnpc.edu.vn,tnpc.edu.vn`). Khớp exact host hoặc subdomain; chặn `@`, `//`, IP literal, scheme ≠ https.
- **DEFER**: bảng `sms_allowed_redirect_domain` nếu admin cần quản lý qua UI.

---

## 7. Biến cá nhân hóa + Preflight (160 / 70)

### 7.1 Biến template
Whitelist (chỉ field cấp contact, không có biến cấp nhóm):
- `{full_name}`, `{name}` → `full_name_snapshot`
- `{link}` → short url `https://qlts.tnpc.edu.vn/r/{code}`

Validate khi tạo/build: biến lạ (không thuộc whitelist) → lỗi 400. Nếu template **không có `{link}`** → campaign không tracking: không sinh token, `token_hash=NULL`, không click event; preflight cảnh báo "campaign này không đo được click". **Ngoại lệ chặn (B5/P2-2)**: `landing_type='external'` + có `landing_url` mà thiếu `{link}` → **lỗi 400** (landing_url vô nghĩa nếu không có gì để bấm tới).

### 7.2 Preflight (per-recipient — vì tên khác nhau → độ dài khác nhau)
```
GSM7_EXT = ^ { } \ [ ~ ] | €   (đếm = 2)
def measure(msg):
    if mọi char ∈ GSM7_BASIC ∪ GSM7_EXT:
        encoding="GSM7"; n=len(msg)+count(ext_chars); per_single,per_multi=160,153
    else:
        encoding="UCS2"; n=len(msg); per_single,per_multi=70,67   # tiếng Việt có dấu
    segments = 1 if n<=per_single else ceil(n/per_multi)
    is_over_limit = segments>1
```
**Chốt B1 — hard gate (không loại âm thầm)**: tin **vượt 1 segment** → đánh dấu `is_over_limit=TRUE` + `excluded_reason='over_limit'` ở build/preflight, NHƯNG **export bị CHẶN (400)** nếu còn bất kỳ recipient `over_limit` — buộc admin rút gọn template (hoặc rút gọn dữ liệu) trước khi export. Lý do: với SMS marketing, loại âm thầm vài người tên dài dễ gây sai nghiệp vụ. (Cờ `allow_multipart` trên campaign = DEFER nếu sau này muốn cho phép multi-segment.) Preflight report: tổng/hợp lệ/loại theo từng lý do (kèm **danh sách dòng over_limit** để admin biết sửa)/phân bố nhà mạng; gợi ý template không dấu để ở GSM-7.

---

## 8. Export Excel (đúng format mẫu)

### 8.1 Format file (đã kiểm từ mẫu nhà mạng)
- `.xlsx` (openpyxl), **1 nhà mạng = 1 file**.
- Sheet name: **`Sheet1`**.
- **Không có header**. Dữ liệu bắt đầu từ **row 2** (row 1 để trống theo mẫu).
- **Cột A**: số điện thoại `84xxxxxxxxx` — định dạng **text** (`cell.number_format='@'`) để không bị Excel cắt số 0 / chuyển scientific.
- **Cột B**: nội dung SMS đã render — định dạng **text**.
- Chỉ chứa recipient `excluded_reason IS NULL` (đã loại opt-out/invalid/over_limit), thuộc `carrier_bucket` tương ứng.

### 8.2 Filename
`{TenNhom}-{TenChienDich}-{TenNhaMang}.xlsx`, **sanitize**:
- Bỏ ký tự không hợp lệ filename (`\ / : * ? " < > |`), thay khoảng trắng/ký tự lạ bằng `-` hoặc `_`.
- Chuẩn hóa dấu tiếng Việt (tùy chọn) để tránh lỗi hệ thống nhà mạng kén unicode.
- Giới hạn độ dài tổng (vd ≤ 120 ký tự); cắt phần tên nếu quá dài, giữ đủ phân biệt.
- `TenNhom` = `export_batch.group_name_snapshot`. **Chốt B2 — MVP**: campaign chọn nhiều nhóm → export **gộp per nhà mạng** (recipient dedupe gửi-1-lần), `group_id=NULL`, `group_name_snapshot` = ghép tên các nhóm dạng `NhomA+NhomB` (≥3 nhóm → `NhomA+NhomB+N` với N = số nhóm còn lại). Campaign 1 nhóm → `group_id` = nhóm đó, `group_name_snapshot` = tên nhóm. *(Muốn file RIÊNG từng nhóm trong cùng campaign = DEFER: cần thêm `owner_group_id` trên recipient + đổi quy tắc gán nhóm sở hữu — báo lại để chỉnh schema.)*

### 8.3 Lưu trữ
File lưu **ngoài public webroot** (§9.7), `storage_path` + `file_sha256` + `expires_at`. Tải qua endpoint admin (auth + IDOR + verify sha256). Export đóng gói nhiều file (.zip) hoặc tải từng file per batch.

### 8.4 Gate export (DNC + over_limit)
`POST .../export` từ chối (400) nếu:
- `campaign.dnc_checked_at IS NULL` → UI bắt admin tick xác nhận đã kiểm tra DNC + cơ sở đồng ý → set `dnc_checked_at/_by/_reference`; **HOẶC**
- còn **bất kỳ recipient `excluded_reason='over_limit'`** (hard gate B1) → trả về số dòng vượt + gợi ý rút gọn template.

Chỉ khi cả 2 điều kiện sạch mới sinh file.

---

## 9. Reports (click theo ngày/tháng/năm)

`GET /api/sms/reports/clicks?group_id=&campaign_id=&carrier=&date_from=&date_to=&granularity=day|month|year`

- **Nguồn**: `sms_click_event` JOIN `sms_campaign_recipient`.
- **Bucket thời gian**: theo `granularity` (date_trunc day/month/year trên `clicked_at`).
- **Lọc**:
  - `campaign_id` → trực tiếp.
  - `carrier` → `recipient.carrier_bucket`.
  - `group_id` → `:group_id = ANY(recipient.group_ids_snapshot)` (GIN).
  - `date_from/date_to` → khoảng `clicked_at`.
- **Số đo**:
  - `total_clicks` (gồm bot), `human_clicks` (`is_suspected_bot=FALSE`).
  - `distinct_contacts_clicked` (distinct recipient non-bot).
  - `recipients_exported` (mẫu số) → **CTR chính = distinct non-bot / recipients_exported**.
- **Danh sách liên hệ đã click**: contact + `human_click_count`, `first_human_clicked_at`, `last_human_clicked_at` (từ recipient denormalized — **đã loại bot**). `raw_click_count` chỉ xem khi cần audit, không dùng làm "số người quan tâm".

Dashboard campaign (`GET /api/sms/campaigns/{id}/dashboard`): CTR + phân bố nhà mạng + danh sách số đã click của riêng campaign.

---

## 10. API endpoints (admin-only trừ public)

**Contact groups**
| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/sms/contact-groups` | tạo nhóm |
| GET | `/api/sms/contact-groups` | list |
| GET | `/api/sms/contact-groups/{id}` | chi tiết |
| PATCH | `/api/sms/contact-groups/{id}` | sửa |
| POST | `/api/sms/contact-groups/{id}/contacts/upload` | upload liên hệ vào nhóm (CSV/XLSX) → import_batch |
| GET | `/api/sms/contact-groups/{id}/contacts` | list contact trong nhóm |

**Contacts**
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/sms/contacts` | list/search toàn hệ thống |
| POST | `/api/sms/contacts` | tạo 1 liên hệ |
| PATCH | `/api/sms/contacts/{id}` | sửa (full_name/note/consent) |
| POST | `/api/sms/contacts/{id}/groups` | thêm contact vào nhóm |
| DELETE | `/api/sms/contacts/{id}/groups/{group_id}` | gỡ khỏi nhóm |

**Campaign**
| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/sms/campaigns` | tạo |
| GET | `/api/sms/campaigns` | list |
| GET | `/api/sms/campaigns/{id}` | chi tiết + preflight summary |
| PATCH | `/api/sms/campaigns/{id}` | sửa (chỉ khi draft) |
| POST | `/api/sms/campaigns/{id}/groups` | gắn nhóm vào campaign |
| DELETE | `/api/sms/campaigns/{id}/groups/{group_id}` | bỏ nhóm |
| POST | `/api/sms/campaigns/{id}/build` | snapshot + render + token + carrier + preflight |
| GET | `/api/sms/campaigns/{id}/preflight` | report đếm ký tự + phân bố |
| POST | `/api/sms/campaigns/{id}/export` | sinh Excel per nhà mạng (gate DNC) |
| GET | `/api/sms/campaigns/{id}/exports/{batch_id}/download` | tải file (auth) |
| POST | `/api/sms/campaigns/{id}/exports/{batch_id}/mark-uploaded` | khóa batch nhà mạng |
| GET | `/api/sms/campaigns/{id}/dashboard` | CTR + danh sách click |

**Reports**
| GET | `/api/sms/reports/clicks?group_id=&campaign_id=&carrier=&date_from=&date_to=&granularity=day\|month\|year` | report tổng hợp click |

**Opt-out**
| POST | `/api/sms/opt-out/manual` | admin ghi opt-out |
| GET | `/api/sms/opt-out` | danh sách opt-out |
| **POST** | **`/api/public/sms/opt-out`** | public — opt-out từ landing (body `{code}`) |

**Public**
| **GET** | **`/r/{code}`** | public — resolve short-link → click + redirect |

> `/api/public/sms/opt-out` dưới `/api/public/` → **CSRF-exempt sẵn** (csrf.py:60). `/r/{code}` GET → không bị CSRF.

---

## 11. Tích hợp hạ tầng (điểm chạm đã verify)

### 11.1 Models — `Backend_FastAPI/app/models/sms/`
Submodule (pattern `finance/`): `contact_group.py`, `contact.py`, `contact_group_member.py`, `contact_import_batch.py`, `prefix_carrier_rule.py`, `campaign.py`, `campaign_group.py`, `campaign_recipient.py`, `campaign_export_batch.py`, `click_event.py`, `opt_out.py` (**11 model**). **Bắt buộc** import vào `app/models/__init__.py` + `__all__` để alembic autogenerate thấy.

### 11.2 Router — `app/main.py`
- `sms.router` (admin) declare prefix `/api/sms` → `include_router(sms.router)`.
- `sms_public.router` (opt-out) declare `/api/public/sms`.
- `sms_shortlink.router` declare `/r` → `include_router(sms_shortlink.router)` (như `public_admissions.router` dòng 839 — không truyền `prefix="/api"`).

### 11.3 Nginx — `nginx/conf.d/default.conf.template`
Thêm `location /r/` **TRƯỚC** catch-all `location /` (dòng 183 — catch-all đẩy về frontend):
```nginx
# --- SMS short-link resolver (về backend, KHÔNG về frontend) ---
location /r/ {
    limit_req zone=general burst=30 nodelay;
    proxy_pass http://backend;
    proxy_read_timeout 30s;
}
```
`/lp/{code}` (landing qlts_hosted) là Next.js page → đi qua catch-all `/`, không cần thêm.

### 11.4 CSRF — không cần sửa
opt-out dưới `/api/public/` (exempt sẵn); `/r/{code}` là GET.

### 11.5 Casbin — admin wildcard `/*` đã cover `/api/sms/**`. Endpoint dùng `CasbinAuth`. Tùy chọn thêm `SMS_TEMPLATE` cho rõ tài liệu.

### 11.6 Thư viện — `openpyxl==3.1.5`, `pandas==2.3.3` đã có. Phone: `app/utils/phone_helpers.py` (`normalize_vietnam_phone`, `validate_vietnam_phone`, `to_zalo_phone`).

### 11.7 Lưu trữ file export (PII) — KHÔNG public
Nginx serve trực tiếp `/uploads/` + `/static/uploads/` (default.conf.template:156-168). File export chứa **phone + raw short_code** → lưu thư mục riêng vd `/app/private_exports/sms/{campaign_id}/...` (KHÔNG có `location` nginx). Chỉ tải qua endpoint admin (auth + IDOR + verify `file_sha256`). Job dọn theo `expires_at` → set `purged_at`. Retention ngắn (7-30 ngày).

---

## 12. Tái sử dụng vs xây mới

| Tái sử dụng (có sẵn) | Xây mới |
|---|---|
| `phone_helpers.normalize_vietnam_phone` / `to_zalo_phone` | 11 model + schema + repo + service + 3 router |
| openpyxl + StreamingResponse (pattern `leads.py:504`) | Contact import (dedupe global + membership) |
| `UploadFile` + pandas `dtype=str` (giữ số 0 đầu) | Snapshot builder + dedupe per-campaign |
| Redis rate-limit (`magic_link_rate_limit`) | Template variable render + preflight GSM-7/UCS-2 |
| `/api/public/` CSRF-exempt | Short-link `/r/{code}` + click tracking + bot filter |
| Casbin admin wildcard | Carrier classifier + Excel format mẫu + filename sanitize |
| Layer pattern (router commit / service flush / `(result, callback)`) | Reports day/month/year + opt-out toàn cục |

---

## 13. Lộ trình PR — Phase 1 / core (solo dev — batch hợp lý)

> Phase 2 (deep engagement + lead consultation) có roadmap riêng ở §16.8.

| PR | Nội dung | Phụ thuộc |
|---|---|---|
| **PR-1: Schema** | **11 model** (match `Mapped[]` 2.0 từ model mẫu thật) + `app/models/sms/` + đăng ký `__init__.py` + migration tạo bảng + migration seed carrier rules (revision id ≤32 ký tự, vd `sms20260527_create` / `sms20260527_seed`). ⚠ **VIẾT TAY** trong migration (autogenerate KHÔNG sinh đúng): partial UNIQUE `token_hash` + `(campaign_id, phone_normalized_snapshot)` (`postgresql_where`), GIN `group_ids_snapshot` (`postgresql_using="gin"`), composite `(campaign_id, carrier_bucket)`. Đã gồm sẵn dnc fields, file metadata, ip_hash/bot, raw/human click. **Tránh migration thứ hai.** | — |
| **PR-2: Contact Management BE** | CRUD `contact-groups` + `contacts`, membership add/remove, **import contacts vào nhóm** (dedupe global theo phone, tạo/tái dùng contact, `import_batch` counts) | PR-1 |
| **PR-3: Campaign Build BE** | CRUD campaign + gắn nhóm; **build** = gom member nhóm chọn → dedupe → snapshot → loại opt-out → carrier → token HMAC (`{link}`) → render biến → preflight GSM-7/UCS-2 (đánh dấu `over_limit`); validate allowlist landing + B5 `{link}` external | PR-2 |
| **PR-4: Export BE** | Excel per nhà mạng đúng format mẫu (Sheet1/no header/row 2/A=84xxx text/B text), filename `{Nhóm}-{Campaign}-{NhàMạng}.xlsx` sanitize + `group_name_snapshot` đa nhóm, private storage + sha256/expires, **gate export (DNC + hard gate over_limit)**, re-download, mark-uploaded, job dọn file hết hạn | PR-3 |
| **PR-5: Tracking/Opt-out/Reports BE** | `/r/{code}` resolve + rate-limit + click event (ip_hash, bot heuristics) + cập nhật recipient denormalized **`raw_click_count` + `human_click_count` + `first/last_human_clicked_at`** (tách bot khỏi số "đã click"); re-check allowlist trước redirect; `/api/public/sms/opt-out` + opt-out thủ công (toàn cục); reports day/month/year × campaign/nhóm/carrier; dashboard CTR (non-bot) | PR-3,4 |
| **PR-6: Frontend** | Contact groups + contact import UI; campaign wizard (variable picker/drag-drop {name}/{link}, preflight live counter, default `qlts_hosted` + confirm modal cho `external`); export/download per nhà mạng + bước xác nhận DNC; reports dashboard; trang `/lp/{code}` + nút "Hủy nhận tin" | PR-2..5 |

Mỗi PR: type-check + test local trước push (`test-before-push`); FE PR Chrome MCP smoke (`chrome-mcp-pre-push-smoke`); xin phép push từng lần (`push-approval-required`).

---

## 14. Trạng thái quyết định thiết kế

> **Verdict: GO cho PR-1 Schema** (2026-05-26). Schema/migration không bị chặn. **B1/B2/B3/B4/B5 đã CHỐT**; trong đó B3/B5 chỉ ảnh hưởng **hành vi service ở PR-2/PR-3** (không đụng schema PR-1).

### Đã CHỐT
- **B1 — `over_limit` = hard gate** ✅: build/preflight đánh dấu từng dòng `over_limit`; **export CHẶN (400)** nếu còn bất kỳ recipient over_limit → admin rút gọn template. Không loại âm thầm. Cờ `allow_multipart` = DEFER. (§7.2, §8.4)
- **B2 — Multi-group = gộp per carrier** ✅: cho chọn nhiều nhóm, export gộp per nhà mạng (dedupe gửi-1-lần), `group_name_snapshot` = `NhomA+NhomB+N`. File riêng từng nhóm = DEFER (cần `owner_group_id`). (§8.2)
- **B4 — Excel format** ✅ ĐÓNG: mẫu đã kiểm — Sheet1, no header, data từ row 2, A=`84xxxxxxxxx` text, B=nội dung text. Không còn là open question. *(Khuyến nghị vẫn lưu 1 file mẫu vào `Documents/samples/` làm anchor cho test PR-4.)*
- **Token hash = HMAC-SHA256** ✅: dùng `SMS_TOKEN_HASH_SECRET` thay plain SHA256 (chống brute-force offline token 7 ký tự). (§2.2, §6.1)

### Đã CHỐT (bổ sung 2026-05-26)
- **B3 — Re-import contact trùng phone = GIỮ BẢN ĐẦU** ✅: import lại số đã có → **KHÔNG ghi đè** `full_name`/`note`/`consent_basis` của contact cũ, chỉ thêm membership. Sửa tên qua `PATCH /contacts/{id}` thủ công. (Member-level `note` cho ghi chú riêng từng nhóm.)
- **B5 — `{link}` tùy chọn, NHƯNG `external` có `landing_url` thì BẮT BUỘC `{link}`** ✅:
  - `{link}` nói chung là tùy chọn — không có `{link}` → SMS thuần (không redirect/không tracking), preflight cảnh báo "không đo được click".
  - **Ràng buộc validate (P2-2)**: nếu `landing_type='external'` **và** có `landing_url` mà template **thiếu** `{link}` → **lỗi 400** ("đã đặt link đích external nhưng nội dung không có `{link}` để người nhận bấm tới"). Tránh `landing_url` vô nghĩa.
  - `qlts_hosted` thiếu `{link}` → chỉ cảnh báo (không chặn).

---

## 15. DEFER (phase sau)

- Gửi tự động qua SMS gateway API (Celery `sms_tasks.py` + delivery status).
- Import file opt-out từ nhà mạng (nếu nhà mạng trả report).
- `sms_opt_out_history` đầy đủ (pattern `notification_consent_history`).
- Interstitial QLTS cho `external` (nút opt-out trước khi redirect ngoài).
- Bảng `sms_allowed_redirect_domain` (admin quản lý allowlist qua UI).
- Đối soát DNC tự động + gửi bản tin 5656 (hiện thủ công, chỉ lưu `dnc_reference`).
- Cờ `allow_multipart` trên campaign (B1) + `owner_group_id` cho export per-group (B2) nếu nghiệp vụ cần.
- **Loại thủ công 1 recipient over_limit** (thay vì buộc sửa template) — hard gate B1 hiện buộc rút gọn template cho MỌI tên; nếu vướng tên quá dài cá biệt, cân nhắc endpoint "exclude thủ công" recipient. MVP: UI preflight phải chỉ rõ dòng nào over_limit để admin xử lý.

> **Deep engagement tracking + lead consultation link KHÔNG còn là DEFER** — đã nâng thành **Phase 2** có thiết kế đầy đủ ở §16.

---

## 16. Phase 2 — Deep Engagement Tracking + Lead Consultation Link

> Triển khai **sau** Phase 1 core. Mục đích kép: (a) officer tư vấn cá nhân từng lead; (b) admin thống kê ngành nào được quan tâm. Chỉ khả thi trên landing **`qlts_hosted`** (QLTS kiểm soát JS); landing `external` không deep-track được.

### 16.1 Mô hình landing 2 tầng
- **Landing chính** `/lp/{code}` — hiển thị **danh mục ngành** (tái dùng catalog `GET /api/public/admissions/programs`). Chỉ để chọn, KHÔNG phải nơi đo chính.
- **Landing từng ngành** `/lp/{code}/nganh/{program_id}` — mỗi ngành **một trang riêng**, render nội dung ngành (tái dùng dữ liệu `MajorProgram`/`ProgramOffering`). **Đây là nơi đo chính.**

### 16.2 Cách đo "ngành thực sự quan tâm"
Vì mỗi ngành là **một URL riêng** → đo **time-on-page chuẩn cho từng trang ngành** (heartbeat), KHÔNG cần IntersectionObserver:
- Vào `/lp/{code}` → mở **session**.
- Click ngành C → sang `/lp/{code}/nganh/C` → ghi **lượt xem ngành** + bắt đầu đo dwell trang đó.
- Rời trang ngành (quay lại danh mục / sang ngành khác / đóng) → chốt `dwell_seconds`.
- **Tín hiệu chính = tổng dwell** mỗi ngành; click chỉ là phụ. Ngành tổng dwell cao nhất = quan tâm nhất.
- Bot không chạy JS → không heartbeat → tự loại khỏi dwell.

### 16.3 Entity ngành (tái dùng, đã verify trong codebase)
- `MajorProgram` (`major_program`): `id`, `name`, `code`, `degree_level`, `is_active` — **ngành** thí sinh/phụ huynh quan tâm.
- `ProgramOffering` (`program_offering`): loại hình (chính quy/liên thông); `Lead.offering_id` đã trỏ vào đây.
- Danh mục công khai: `GET /api/public/admissions/programs` (catalog `degree_levels → programs → offerings`).

### 16.4 Data model Phase 2 (3 bảng tracking + 1 bảng consult link)

**`sms_landing_session`** — 1 lượt xem landing:
`id`, `contact_id` (FK NOT NULL — khóa thống nhất gắn interest), `source_type` (`campaign`/`consult`), `recipient_id` (FK sms_campaign_recipient NULL), `consult_link_id` (FK sms_consult_link NULL), `campaign_id` (NULL), **`session_token_hash`** (HMAC-SHA256 của session token, UNIQUE NOT NULL — KHÔNG lưu raw, xem P1-2 §16.7), `started_at`, `last_heartbeat_at`, `ended_at`, `active_seconds`, `ip_hash`, `user_agent`, `is_suspected_bot`.

> **session token = bearer token** → lưu hash giống short-code (chống giả lập engagement nếu DB/log lộ). Server sinh raw token, trả client 1 lần, lookup bằng `HMAC-SHA256(token, SMS_TOKEN_HASH_SECRET)`.

**`sms_program_view`** — mỗi lượt xem 1 trang ngành (đo dwell):
`id`, `session_id` (FK), `contact_id` (FK), `major_program_id` (FK SET NULL), `program_offering_id` (nullable), **`program_name_snapshot`**, `viewed_at`, `dwell_seconds` (chốt từ heartbeat trang ngành), `sequence_no`.

**`sms_contact_program_interest`** — hồ sơ sở thích tổng hợp per contact (giá trị nghiệp vụ chính):
`id`, `contact_id` (FK), `major_program_id` (FK), `view_count`, **`total_dwell_seconds`**, `first_interest_at`, `last_interest_at`, `interest_score`, **UNIQUE(contact_id, major_program_id)**. → Trả lời "liên hệ X quan tâm ngành gì nhất" xuyên mọi nguồn.

**`sms_consult_link`** — link tư vấn 1-1 officer gửi lead (ngoài campaign):
`id`, `lead_id` (FK lead), `contact_id` (FK sms_contact — match/ tạo từ phone lead), `created_by_id` (FK user = officer), `token_hash` (HMAC, partial UNIQUE), `landing_type`/`landing_url` (mặc định qlts_hosted danh mục), `raw_click_count`, `human_click_count`, `first_human_clicked_at`, `last_human_clicked_at`, `expires_at` NULL, `created_at`.

> **Khóa thống nhất = `contact_id`**: cả campaign recipient lẫn consult link đều resolve về 1 contact. Interest aggregate theo contact → lead xem qua match phone.

### 16.5 Liên kết Lead ↔ Contact (qua phone)
- Contact unique theo `phone_normalized`; lead có `phone`/`phone2`.
- Officer tạo consult link cho lead → tìm contact theo `normalize(lead.phone)`; chưa có → **tạo contact** (`source_label='lead_consult'`, `consent_basis='implied_lead'`).
- **Tab "Quan tâm ngành" trong trang chi tiết lead**: lead → normalize phone → contact → `sms_contact_program_interest` xếp theo `total_dwell_seconds` desc. Hiển thị vd: "C (5ph) · B (2ph) · A (30s)".

### 16.6 Quyền (mở rộng từ "chỉ admin" của Phase 1)
- **Admin**: toàn quyền (danh bạ/nhóm/campaign/export/report tổng + xem mọi interest).
- **Officer**: chỉ (1) **tạo consult link** cho lead trong phạm vi IDOR của mình (tái dùng `get_lead_for_user`), (2) **xem tab interest** của lead mình (read-only). KHÔNG tạo campaign/danh bạ.
- Casbin: thêm policy officer trên `POST /api/sms/leads/{id}/consult-link` + `GET /api/sms/leads/{id}/interests`; admin wildcard đã cover phần còn lại.

### 16.7 API Phase 2
**Public landing** (dưới `/api/public/sms/` → CSRF-exempt + rate-limit):
- `GET /api/public/sms/landing/{code}` → **chỉ đọc** (no side-effect): resolve code (campaign recipient HOẶC consult link) → trả landing config + danh mục ngành. **Bắt buộc** header `Cache-Control: no-store`. KHÔNG tạo session ở đây (P1-3: tránh prefetch/crawler tạo session rác).
- `POST /api/public/sms/landing/{code}/session` → **tạo session** (side-effect) → sinh `session_token` raw trả về client **1 lần**, lưu `session_token_hash`. Rate-limit + bot UA filter.
- `POST /api/public/sms/landing/{code}/program-view` `{major_program_id, offering_id?, session_token}` → ghi lượt xem ngành (server hash session_token để tra session).
- `POST /api/public/sms/landing/{code}/heartbeat` `{session_token, program_id?}` → cộng dwell (trang ngành đang xem).

**Officer (scope lead)**:
- `POST /api/sms/leads/{lead_id}/consult-link` → sinh consult link (trả raw `code` **1 lần** để officer copy gửi Zalo/tay).
- `GET /api/sms/leads/{lead_id}/interests` → interest của lead (qua contact match) — hoặc nhúng vào lead-detail response.

**Admin report**:
- `GET /api/sms/reports/program-interest?campaign_id=&group_id=&major_program_id=&date_from=&date_to=&granularity=` → ngành "nóng" theo campaign/nhóm/thời gian.
- `GET /api/sms/contacts/{id}/interests` → hồ sơ sở thích 1 contact.

**Resolve mở rộng** `/r/{code}`: tra `sms_campaign_recipient.token_hash` trước, không thấy → tra `sms_consult_link.token_hash`; cập nhật click tương ứng → 302 tới `/lp/{code}`.

### 16.8 Lộ trình PR Phase 2
| PR | Nội dung |
|---|---|
| **P2-1: Schema** | 4 bảng (`sms_landing_session`, `sms_program_view`, `sms_contact_program_interest`, `sms_consult_link`) + migration |
| **P2-2: Deep tracking BE** | landing resolve mở rộng + `program-view` + `heartbeat` (dwell) + cập nhật aggregate interest + report program-interest |
| **P2-3: Lead consultation BE** | officer tạo consult link (scope IDOR) + `/leads/{id}/interests` + Casbin officer policy + contact match/create từ lead |
| **P2-4: Frontend** | landing `/lp/{code}` (danh mục) + `/lp/{code}/nganh/{id}` (trang ngành + heartbeat JS) + nút "Hủy nhận tin"; tab "Quan tâm ngành" trong lead detail; nút officer "Tạo link tư vấn"; admin report ngành |

### 16.9 Compliance bổ sung Phase 2
Deep behavior tracking gắn đích danh = xử lý dữ liệu cá nhân (NĐ 13/2023). Landing nên có dòng thông báo nhẹ ("ghi nhận quan tâm để tư vấn phù hợp"). Vẫn `ip_hash`, không IP thô. `consent_basis` của contact đã có.

### 16.10 Open question Phase 2 (chốt khi tới Phase 2)
- **P2-Q1**: consult link có cho phép officer chọn landing/ngành hiển thị riêng, hay luôn danh mục đầy đủ? → Đề xuất MVP Phase 2: danh mục đầy đủ.
- **P2-Q2**: `interest_score` công thức cụ thể (trọng số dwell vs view_count vs recency)? → Đề xuất: ưu tiên `total_dwell_seconds`, tie-break `last_interest_at`.
- **P2-Q3**: retention dữ liệu interest (giữ bao lâu)? → Đề xuất: giữ aggregate dài hạn (profile), event chi tiết dọn sau N tháng.

---

## 17. Ghi chú pháp lý

> Không phải tư vấn pháp lý. Đây là **checkpoint thiết kế** hỗ trợ tuân thủ; trách nhiệm thuộc người vận hành.

**Cơ sở (nguồn nhà nước)**:
- **NĐ 91/2020/NĐ-CP** chống tin nhắn/email/cuộc gọi rác: quảng cáo bằng tin nhắn yêu cầu **đồng ý trước** + **kiểm tra Danh sách không quảng cáo (DNC)**. Nguồn: vanban.chinhphu.vn — https://vanban.chinhphu.vn/default.aspx?docid=200773&pageid=27160
- Người quảng cáo phải **gửi bản tin tới hệ thống tiếp nhận phản ánh tin nhắn rác (đầu số 5656)** theo hướng dẫn MIC. Nguồn: cspl.mic.gov.vn — https://cspl.mic.gov.vn/Pages/TinTuc/tinchitiet.aspx?tintucid=138202
- **NĐ 13/2023/NĐ-CP** bảo vệ dữ liệu cá nhân (xử lý số điện thoại, mục đích, lưu trữ).

**Checkpoint trong hệ thống**:
1. **Gate export theo DNC/consent**: campaign cần `dnc_checked_at/_by/_reference` trước export (§8.4).
2. **Consent trail**: `sms_contact.consent_basis/_note` + `sms_contact_import_batch.consent_basis/_note` ghi rõ nguồn & cơ sở đồng ý cho từng liên hệ/lô.
3. **Tôn trọng opt-out**: `sms_opt_out` (khóa phone, toàn cục) tự loại khỏi mọi đợt sau.
4. **Tối thiểu hoá dữ liệu**: click dùng `ip_hash`; file export PII ngoài webroot + retention ngắn.

**DEFER**: đối soát DNC tự động + gửi 5656 theo quy trình MIC — hiện thủ công ngoài QLTS, hệ thống lưu `dnc_reference` làm bằng chứng.
