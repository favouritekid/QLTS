# SMS Marketing Module — Thiết kế triển khai

> Trạng thái: **v4 schema + ĐANG CODE PR-1 (Codex review R1–R3 xong)** — cập nhật 2026-06-11 (gốc 2026-05-26). User/chủ dự án **AUTHORIZE GO** (xác nhận đủ evidence L1–L4 + lịch sử vận hành không vấn đề PL). PR-1 schema (12 model + migration + regression test) commit branch `sms/pr1-schema`, CHƯA push.
> **v4 (2026-06-11)** sửa các blocker của v3: token có thể tái xuất nhưng không lưu plaintext; consent marketing fail-closed + ledger bất biến; landing opt-out chỉ là kênh bổ sung, không thay thế kênh từ chối qua SMS/điện thoại; DNC/consent attestation gắn với từng `build_revision`; file export có lifecycle/idempotency; loại các field Phase 1.5 khỏi migration lõi.
> Scope: **SMS Marketing Contact + Campaign Export + Click Tracking + (Phase 2) Deep Engagement + Lead Consultation Link**. KHÔNG phải campaign upload số tạm thời. Liên hệ là thực thể bền vững, dùng lại qua nhiều campaign.
>
> **Chia 2 phase**:
> - **Phase 1 (core — ship trước)**: **chỉ SMS quảng cáo tuyển sinh**. Quản lý nhóm liên hệ → import kèm bằng chứng đồng ý → campaign chọn nhóm → build snapshot + render cá nhân hóa + short-link riêng → preflight 160/70 → export Excel per nhà mạng đúng format mẫu → **click tracking cơ bản** → report click ngày/tháng/năm → suppression/opt-out toàn cục. **KHÔNG đụng §16 hoặc PR-7.**
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
6. **Suppression/opt-out toàn cục** theo `phone_normalized`, áp dụng mọi campaign sau.

Hệ quả cốt lõi: vì QLTS không tự gửi, **QLTS không kiểm soát trực tiếp SMS trả lời**. Do đó:
- Kênh từ chối hợp lệ phải do nhà mạng/đơn vị vận hành cung cấp qua **SMS hoặc cuộc gọi**, có quy trình xác nhận ngay và đồng bộ về QLTS.
- Nút landing page và thao tác admin chỉ là **kênh bổ sung**, không được mô tả là kênh thay thế nghĩa vụ trên.
- Không có bằng chứng vận hành kênh từ chối + đối soát DNC thì **không được production export**.

---

## 2. Quyết định đã chốt

### 2.1 Nghiệp vụ
| # | Quyết định | Hệ quả kỹ thuật |
|---|---|---|
| 1 | Liên hệ bền vững, **duy nhất toàn hệ thống theo `phone_normalized`** | `sms_contact.phone_normalized` UNIQUE |
| 2 | 1 liên hệ thuộc **nhiều nhóm** | bảng N-N `sms_contact_group_member` |
| 3 | Campaign chọn **1+ nhóm**; build tạo **snapshot** | `sms_campaign_group` + `sms_campaign_recipient` (snapshot fields) |
| 4 | Contact ở nhiều nhóm được chọn → **gửi 1 lần trong mỗi build revision** | UNIQUE `(campaign_id, build_revision, phone_normalized_snapshot)` |
| 5 | Snapshot **đóng băng** tại thời điểm build; nhóm/contact đổi sau không ảnh hưởng campaign đã build | mọi field dùng để gửi đều là `*_snapshot` |
| 6 | Cá nhân hóa qua biến `{name}`/`{full_name}`/`{link}`; **`{link}` tùy chọn** (chỉ bắt buộc khi `external` + có `landing_url` — xem B5 §14) | render per-recipient; validate biến |
| 7 | Phân loại nhà mạng theo prefix — **chỉ để khớp format upload**, KHÔNG đảm bảo nhà mạng hiện tại (MNP). **Chấp nhận rủi ro** | `sms_prefix_carrier_rule` + bucket `unknown` |
| 8 | Export Excel **đúng format mẫu**, tách file per nhà mạng, filename `{Nhóm}-{Campaign}-{NhàMạng}.xlsx` | §8 |
| 9 | Quyền **Phase 1 = chỉ admin**; **Phase 2 thêm officer** (tạo link tư vấn 1-1 + xem interest cho lead trong scope IDOR) | Endpoint Phase 1 dùng `RequireAdmin`/`require_admin`; Casbin là lớp bổ sung, không thay hard role gate (§16.6) |

### 2.2 Bảo mật / Compliance
- Short code base62×9. DB lưu `token_hash` = **HMAC-SHA256(code, `SMS_TOKEN_HASH_SECRET`)** để lookup và `token_ciphertext` = **Fernet(code, active key trong `SMS_TOKEN_ENCRYPTION_KEYS`)** để tái xuất. Không lưu plaintext trong DB/log/message snapshot.
- Token hash secret, token encryption key-ring và `SMS_IP_HASH_SECRET` là các secret tách biệt; production startup fail-fast nếu thiếu. Chỉ bỏ key cũ sau khi mọi batch/link tương ứng hết hạn.
- `rendered_message_skeleton` chỉ lưu sentinel cố định cho `{link}`; raw code chỉ tồn tại ngắn hạn trong memory khi build/export và trong file export private.
- File export (phone + raw short code) lưu **ngoài public webroot**; chỉ tải qua endpoint admin.
- Click event **không lưu IP thô/prefix** → `ip_hash` HMAC bằng `SMS_IP_HASH_SECRET`.
- External redirect: **validate allowlist khi tạo campaign + kiểm tra lại trước redirect**.
- Landing default `qlts_hosted`; `external` cần warning/confirmation.
- **Consent marketing fail-closed**: chỉ `marketing_consent_status='granted'` và có event/proof hợp lệ mới được build/export. `implied_lead`, `unknown`, partner list không bằng chứng đều bị loại.
- **Suppression/opt-out toàn cục** theo `phone_normalized`, áp mọi campaign sau; re-check ngay trong transaction export.
- Export bị chặn cho tới khi consent/DNC/channel-opt-out attestation khớp `build_revision`.
- Public `/r/{code}` **rate-limit theo IP + unknown-token/global cap**; response generic, không lộ token tồn tại.
- Nginx/app access log không được ghi raw code trong path; response public có `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Robots-Tag: noindex`.
- Bot/link-preview clicks **flag + không tính CTR chính**.

---

## 3. Sơ đồ luồng

```
[Admin] tạo nhóm (parent/student/teacher/lead/custom)
   │
   ├── upload liên hệ vào nhóm (full_name, phone, note)
   │     → contact unique theo phone_normalized; có thì add membership, chưa thì tạo
   │     → ghi sms_contact_import_batch (counts + consent evidence)
   │     → append sms_marketing_consent_event nếu có bằng chứng opt-in hợp lệ
   ▼
[Admin] tạo campaign: nội dung (biến {name}/{link}), landing_type+url
   ├── chọn 1+ nhóm  (sms_campaign_group)
   ▼
[BUILD] (service)
   1. gom member của các nhóm đã chọn → dedupe theo phone_normalized (gửi 1 lần)
   2. SNAPSHOT contact (full_name/phone/note + group_ids đóng góp)
   3. fail-closed contact chưa consent; loại số trong sms_opt_out/external suppression
   4. phân loại carrier theo prefix mobile → bucket (unknown nếu không khớp)
   5. nếu template có {link}: sinh short_code base62×9; lưu hash + ciphertext
   6. render `rendered_message_skeleton` với sentinel link cố định; không lưu raw code
   7. chèn `[QC]` + hướng dẫn từ chối SMS/điện thoại; đo ký tự/encoding/segments
   8. tăng `build_revision`; mọi xác nhận revision cũ hết hiệu lực
   ▼
[PREFLIGHT] tổng / hợp lệ / loại (opt-out/invalid/over_limit) / phân bố nhà mạng
   ▼
[Admin xác nhận DNC + consent + kênh từ chối] cho đúng build_revision
   │  + export CHẶN nếu còn recipient over_limit (hard gate B1) → admin sửa template
   ▼
[EXPORT] Excel per nhà mạng (Sheet1, no header, data từ row 2, A=84xxx text, B=nội dung text)
   → filename {Nhóm}-{Campaign}-{NhàMạng}.xlsx (sanitize) → lưu NGOÀI webroot
   ▼
[Admin] upload lên hệ thống nhà mạng (NGOÀI QLTS) → bấm "Đã bàn giao" per nhà mạng
   ▼
[Người nhận] bấm link → GET /r/{code} → ghi click (ip_hash, bot flag) → 302 redirect
   │                                          qlts_hosted → /lp/{code} (nút "Hủy nhận tin")
   │                                          external → landing_url (chỉ nếu host ∈ allowlist)
   ▼
[REPORT] click theo ngày/tháng/năm × campaign × nhóm × nhà mạng;
         danh sách liên hệ đã click (human_click_count, first/last_human_clicked_at); CTR loại bot
```

---

## 4. Data model Phase 1 (12 bảng)

> **⚠ Schema đã cập nhật theo Codex review R1–R3 — NGUỒN CHUẨN = code branch `sms/pr1-schema`.** Delta so với bảng mô tả bên dưới: (1) `sms_marketing_consent_event.contact_id` + `sms_contact_import_batch.group_id` = **SET NULL** (không CASCADE) để giữ ledger/audit khi xóa; (2) `sms_click_event` **BỎ** `campaign_id`/`contact_id` denormalize (derive qua JOIN recipient — tránh gắn sai); (3) consent_event **thêm `revoke_source`** + `basis`/`disclosure_version`/`proof_reference` nullable, CHECK tách grant vs revoke theo `event_type`; (4) consent fail-closed dùng `length(btrim(coalesce(x,'')))>0` (chặn NULL + rỗng + three-valued-logic); (5) `recipient` CHECK token-triplet; (6) `import_batch` CHECK count non-âm + 4 invariant; (7) seed bỏ 055/087 (MVNO→unknown); (8) **R4**: token_hash phải đúng **64 ký tự** + ciphertext/key_version non-rỗng; revoke event **cấm** `disclosure_version`/`proof_reference` (no grant-data).
>
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
| `marketing_consent_status` | String(20) NOT NULL default `unknown` | unknown / granted / revoked; CHECK |
| `marketing_consented_at` | DateTime tz NULL | thời điểm opt-in gần nhất |
| `marketing_consent_basis` | String(30) NULL | explicit_form / signed_form / recorded_call / imported_proof |
| `marketing_consent_proof_ref` | String(512) NULL | tham chiếu bằng chứng; không chứa secret |
| `consent_disclosure_version` | String(50) NULL | phiên bản câu chữ đã đồng ý |
| `last_handed_off_at` | DateTime tz NULL | lần gần nhất số này thuộc batch đã được admin xác nhận bàn giao; dùng frequency-cap như proxy |
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
| `group_id` | FK sms_contact_group **SET NULL** NULL, index | nhóm đích; SET NULL khi xóa group (giữ audit import — R2) |
| `file_name` | String(255) NULL | |
| `file_sha256` | String(64) NULL | |
| `source_label` | String(255) NULL | |
| `consent_basis` | String(30) NULL | chỉ nhận explicit_form / signed_form / recorded_call / imported_proof |
| `consent_disclosure_version` | String(50) NULL | bắt buộc nếu lô tạo consent event |
| `consent_proof_ref` | String(512) NULL | bắt buộc nếu lô tạo consent event |
| `consent_obtained_at` | DateTime tz NULL | bắt buộc nếu lô tạo consent event |
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

> Logic import: normalize + **validate mobile-only** (helper hiện tại còn chấp nhận số bàn nên service phải kiểm prefix di động); invalid/landline thì skip. Contact đã tồn tại được tái dùng, không ghi đè identity. Nếu import kèm đủ consent evidence thì append một `sms_marketing_consent_event` dưới row lock và cập nhật latest-state trên contact; thiếu bằng chứng thì contact giữ `unknown` và không đủ điều kiện build.
>
> **Bất biến count (anchor test PR-2)**: `valid_count` = hợp lệ & duy nhất trong file. → `row_count = valid_count + invalid_count + duplicate_contact_count`; `skipped_count = invalid_count + duplicate_contact_count`; `added_member_count + existing_member_count = valid_count`; `inserted_contact_count ≤ valid_count` (reused = `valid_count − inserted_contact_count`).

### 4.5 `sms_prefix_carrier_rule` (config, seed idempotent)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `prefix` | String(4) UNIQUE | "032","086",… (3 ký tự đầu, gồm số `0`) |
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
| `status` | String(20) default 'draft' | draft → ready → exported → handed_off → closed; CHECK |
| `frequency_cap_days` | Integer NULL | trần tần suất (ngày) cho campaign này; NULL = dùng `SMS_FREQUENCY_CAP_DAYS` mặc định (§18.D1) |
| `sms_template` | Text NOT NULL | chứa `{name}`/`{full_name}`/`{link}` |
| `landing_type` | String(20) NOT NULL default 'qlts_hosted' | qlts_hosted / external; CHECK |
| `landing_url` | Text NULL | bắt buộc nếu external; host phải ∈ allowlist (§6.2) |
| `landing_headline` | String(200) NULL | tiêu đề trang `qlts_hosted` (vd "Thông báo tuyển sinh 2026") — §19 |
| `landing_body` | Text NULL | nội dung chính trang (plain text render xuống dòng; **KHÔNG HTML** — chống XSS) — §19 |
| `landing_cta_label` | String(100) NULL | nhãn nút CTA (vd "Đăng ký tư vấn"); NULL = ẩn CTA |
| `landing_cta_url` | Text NULL | đích CTA; nếu external host phải ∈ allowlist (§6.2) như `landing_url` |
| `build_revision` | Integer NOT NULL default 0 | tăng sau mỗi build; CHECK `>=0` |
| `link_expires_at` | DateTime tz NULL | sau mốc này public link trả response generic hết hạn |
| `optout_instruction_snapshot` | String(160) NULL | hướng dẫn từ chối qua SMS/điện thoại đã chèn vào tin cuối |
| `consent_checked_at` | DateTime tz NULL | xác nhận evidence của toàn recipient |
| `consent_checked_by_id` | FK user NULL | |
| `consent_reference` | String(512) NULL | tham chiếu báo cáo kiểm |
| `consent_checked_build_revision` | Integer NULL | phải bằng `build_revision` |
| `dnc_checked_at` | DateTime tz NULL | mốc đối soát DNC |
| `dnc_checked_by_id` | FK user NULL | |
| `dnc_reference` | String(512) NULL | nguồn/case/report đối soát thực tế |
| `dnc_checked_build_revision` | Integer NULL | phải bằng `build_revision` |
| `optout_channel_checked_at` | DateTime tz NULL | bằng chứng kênh SMS/điện thoại đang hoạt động |
| `optout_channel_checked_by_id` | FK user NULL | |
| `optout_channel_reference` | String(512) NULL | ticket/test-call/provider reference |
| `optout_channel_checked_build_revision` | Integer NULL | phải bằng `build_revision` |
| `created_by_id` | FK user NULL | |
| `created_at`, `updated_at`, `handed_off_marked_at` | DateTime tz | |

> **Transition `status`**: tạo = `draft`; build thành công → `ready`; tạo đủ batch → `exported`; admin xác nhận đã bàn giao/upload đủ batch → `handed_off`; đóng → `closed`. QLTS không có DLR nên không dùng trạng thái `sent`/`delivered`. Rebuild chỉ được phép khi chưa có batch `handed_off`; revision cũ chưa bàn giao bị invalidated. Sau khi đã bàn giao, muốn thay nội dung/audience phải tạo campaign mới để giữ audit.

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
| `build_revision` | Integer NOT NULL | revision của snapshot |
| `contact_id` | FK sms_contact **SET NULL** NULL | snapshot giữ kể cả khi contact bị xoá |
| `group_ids_snapshot` | ARRAY(Integer) NOT NULL (GIN index) | nhóm đã chọn đóng góp contact này |
| `full_name_snapshot` | String(255) NOT NULL | |
| `phone_normalized_snapshot` | String(20) NOT NULL | mobile `0xxxxxxxxx` |
| `phone_international_snapshot` | String(20) NOT NULL | `84xxxxxxxxx` (xuất Excel) |
| `note_snapshot` | Text NULL | |
| `carrier_bucket` | String(20) NOT NULL | viettel … unknown |
| `token_hash` | String(64) NULL | **HMAC-SHA256(short_code, SMS_TOKEN_HASH_SECRET)**; NULL nếu template không có `{link}` |
| `token_ciphertext` | Text NULL | Fernet ciphertext của code; NULL nếu không có `{link}` |
| `token_key_version` | String(32) NULL | chọn key trong key-ring |
| `rendered_message_skeleton` | Text NULL | tin cuối dùng sentinel cố định cho link; KHÔNG chứa raw code |
| `message_length` | Integer NULL | |
| `encoding` | String(8) NULL | GSM7 / UCS2 |
| `segments` | Integer NULL | |
| `is_over_limit` | Boolean default FALSE | vượt 1 segment |
| `excluded_reason` | String(30) NULL | no_consent / opted_out / dnc_suppressed / frequency_capped / over_limit / missing_data / NULL; CHECK |
| `invalidated_at` | DateTime tz NULL | revision cũ chưa bàn giao bị vô hiệu khi rebuild |
| `handed_off_at` | DateTime tz NULL | set khi batch tương ứng được xác nhận bàn giao |
| `raw_click_count` | Integer default 0 | tổng click GỒM bot (audit) |
| `human_click_count` | Integer default 0 | click loại bot — **đây mới là "đã click" hiển thị cho người dùng** |
| `first_human_clicked_at` | DateTime tz NULL | lần click thật đầu (denormalize dashboard) |
| `last_human_clicked_at` | DateTime tz NULL | lần click thật cuối |
| `created_at` | DateTime tz | |

Constraint & index (⚠ **viết tay trong migration**, xem cảnh báo §4 intro):
- **UNIQUE `(campaign_id, build_revision, phone_normalized_snapshot)`** → gửi 1 lần trong một revision.
- **partial UNIQUE `(token_hash)` WHERE `token_hash IS NOT NULL`** → resolve short-link + chống đụng token. `postgresql_where`.
- **GIN index** trên `group_ids_snapshot`; query phải dùng `group_ids_snapshot @> ARRAY[:group_id]::integer[]`. `= ANY(...)` không tận dụng GIN theo pattern đã được repo ghi nhận.
- **composite index `(campaign_id, build_revision, carrier_bucket)`** → export/preflight.

### 4.9 `sms_campaign_export_batch`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `campaign_id` | FK CASCADE, index | |
| `build_revision` | Integer NOT NULL | |
| `group_id` | FK sms_contact_group NULL | NULL nếu export gộp nhiều nhóm (B2 — gộp per carrier) |
| `group_name_snapshot` | String(200) NULL | nhãn filename: 1 nhóm→tên nhóm; nhiều nhóm→`NhomA+NhomB+N` (B2) |
| `carrier_bucket` | String(20) | nhà mạng của file |
| `recipient_count` | Integer | |
| `file_name` | String(255) | `{Nhóm}-{Campaign}-{NhàMạng}.xlsx` (đã sanitize) |
| `storage_path` | String(512) NULL | **NGOÀI public webroot** (§11.7) |
| `file_sha256` | String(64) NULL | |
| `file_size_bytes` | BigInteger NULL | |
| `expires_at` | DateTime tz NULL | mốc hết hạn re-download |
| `purged_at` | DateTime tz NULL | mốc đã xoá file (retention) |
| `status` | String(20) default 'pending' | pending / generated / handed_off / failed / purged / invalidated; CHECK |
| `failure_reason` | Text NULL | lỗi tạo/ghi file đã sanitize |
| `invalidated_at` | DateTime tz NULL | suppression/consent/rebuild làm batch không còn hợp lệ |
| `generated_by_id` | FK user NULL | |
| `generated_at` | DateTime tz NULL | |
| `marked_handed_off_at` | DateTime tz NULL | bấm "Đã bàn giao" per nhà mạng |

Constraint: **UNIQUE `(campaign_id, build_revision, carrier_bucket)`**. Gọi export lại cùng revision trả batch `generated` hiện có; không sinh file/token mới.

### 4.10 `sms_click_event`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `recipient_id` | FK sms_campaign_recipient CASCADE, index | khóa thật; campaign/contact DERIVE qua JOIN recipient (R3 bỏ denormalize — tránh gắn sai campaign/contact) |
| `clicked_at` | DateTime tz, index | |
| `ip_hash` | String(64) NULL | **HMAC-SHA256(ip, `SMS_IP_HASH_SECRET`)**; KHÔNG lưu IP thô/prefix |
| `user_agent` | String(512) NULL | |
| `is_suspected_bot` | Boolean default FALSE | scanner/link-preview/prefetch |
| `bot_reason` | String(50) NULL | known_scanner_ua / prefetch_head / instant_after_send |

> Mỗi click 1 row (gồm bot — giữ audit). **CTR chính = COUNT(DISTINCT recipient_id) WHERE `is_suspected_bot=FALSE` / tổng recipient `handed_off_at IS NOT NULL`**. File chỉ được tạo nhưng chưa bàn giao không được tính vào mẫu số.

### 4.11 `sms_opt_out` (toàn cục)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | Integer PK | |
| `phone_normalized` | String(20) **UNIQUE** NOT NULL | khóa toàn cục |
| `source` | String(30) NOT NULL | landing_optout / manual / sms_reply / phone_call / external_suppression |
| `campaign_id` | FK NULL | campaign dẫn tới opt-out |
| `contact_id` | FK sms_contact SET NULL NULL | |
| `revoked_by_id` | FK user NULL | ai ghi (manual) |
| `source_reference` | String(512) NULL | provider ticket/file/call reference |
| `observed_at` | DateTime tz NOT NULL | thời điểm nhận từ chối/nguồn suppression |
| `reason` | Text NULL | |
| `created_at` | DateTime tz | |

> Đây là latest global suppression, không phải consent history. Build và export đều phải loại số trong bảng; nếu suppression xuất hiện sau khi file được tạo nhưng trước bàn giao, batch phải `invalidated` và build/export lại.

### 4.12 `sms_marketing_consent_event` (ledger bất biến)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BigInteger PK | |
| `contact_id` | FK sms_contact **SET NULL** NULL, index | ledger sống sót khi xóa contact (R1) |
| `phone_normalized_snapshot` | String(20) NOT NULL | bằng chứng vẫn đọc được nếu contact đổi/xóa |
| `event_type` | String(20) NOT NULL | granted / revoked; CHECK |
| `basis` | String(30) NULL | cách GRANT (NULL khi revoke); CHECK grant theo event_type (R3) |
| `revoke_source` | String(30) NULL | nguồn REVOKE: sms_reply/landing_optout/manual/phone_call/external_suppression (NULL khi grant) (R3) |
| `disclosure_version` | String(50) NULL | non-rỗng khi grant; NULL khi revoke (R3) |
| `proof_reference` | String(512) NULL | non-rỗng khi grant (R3) |
| `occurred_at` | DateTime tz NOT NULL | thời điểm sự kiện thực |
| `recorded_by_id` | FK user NULL | actor ghi nhận |
| `import_batch_id` | FK sms_contact_import_batch SET NULL NULL | nguồn import nếu có |
| `metadata_json` | JSONB NULL | metadata tối thiểu, không chứa secret/PII thừa |
| `created_at` | DateTime tz | |

> Ledger append-only: API không UPDATE/DELETE event. Latest-state trên `sms_contact` chỉ là projection để lọc nhanh; service cập nhật projection và append event trong cùng transaction. Re-import không được tự biến `unknown` thành `granted` nếu thiếu đủ disclosure/proof/time.

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

Phân loại lúc build: lấy **3 ký tự đầu gồm số `0`** (`phone_normalized_snapshot[:3]`) → tra rule active → `carrier_bucket`; không khớp → `unknown`.

---

## 6. Short-link, token & resolve

### 6.1 Token & resolve
- **Token**: base62 (`[0-9A-Za-z]`) × 9 (~54 bit). Token là bearer capability gắn với recipient, vì vậy không dùng lại token và không rút ngắn.
- **Sinh** (chỉ khi template có `{link}`): `secrets.choice` ×9; tính `token_hash = HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET)` và `token_ciphertext = Fernet(code, key-ring[SMS_TOKEN_ACTIVE_KEY_VERSION])`; đụng unique hash → retry N lần.
- **Lưu DB**: hash để lookup + ciphertext để re-download. `rendered_message_skeleton` dùng sentinel cố định như `__SMS_LINK__`; export decrypt code và thay sentinel trong memory. Không ghi raw code vào model repr, exception, audit log hoặc application log.
- **Key lifecycle**: production fail-fast nếu thiếu key; `token_key_version` chọn key trong key-ring. Chỉ bỏ key cũ sau khi mọi link/batch tương ứng đã hết hạn và file đã purge.
- **Resolve** `GET /r/{code}`:
  1. Reject code sai charset/length trước DB; rate-limit theo IP + global/unknown-token bucket (Redis fail-closed).
  2. `HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET)` → tra `recipient.token_hash`.
  3. Không thấy/hết hạn/recipient đã invalidated → response generic, cùng shape/status policy; không log raw path.
  4. Thấy → ghi `sms_click_event` (ip_hash + đánh giá bot) + cập nhật denormalized: luôn `raw_click_count++`; nếu **không** phải bot thì thêm `human_click_count++` + `first/last_human_clicked_at` → **302 redirect**: `qlts_hosted`→`/lp/{code}`; `external`→`landing_url` (chỉ nếu host ∈ allowlist, ngược lại 404 + log).

> `GET /r/{code}` là GET → CSRF không áp dụng. Tuy nhiên đây vẫn là public bearer URL: mọi response có `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Robots-Tag: noindex`; external CTA dùng `rel="noreferrer"`.

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
**⚠ Đo trên TIN CUỐI CÙNG, không phải body**: Phase 1 luôn là quảng cáo, tin thực gửi = `[QC] ` + body render + **hướng dẫn từ chối qua SMS/điện thoại** + link landing bổ sung nếu có. `measure()` chạy trên skeleton đã thay sentinel bằng một URL có chiều dài cố định bằng URL thực. Trước khi đo, chạy smart-encoding substitution (§18.C2).

**Chốt B1 — hard gate (không loại âm thầm)**: tin **vượt 1 segment** → đánh dấu `is_over_limit=TRUE` + `excluded_reason='over_limit'` ở build/preflight, NHƯNG **export bị CHẶN (400)** nếu còn bất kỳ recipient `over_limit` — buộc admin rút gọn template (hoặc rút gọn dữ liệu) trước khi export. Lý do: với SMS marketing, loại âm thầm vài người tên dài dễ gây sai nghiệp vụ. (Cờ `allow_multipart` trên campaign = DEFER nếu sau này muốn cho phép multi-segment.) Preflight report: tổng/hợp lệ/loại theo từng lý do (kèm **danh sách dòng over_limit** để admin biết sửa)/phân bố nhà mạng; gợi ý template không dấu để ở GSM-7 — nâng thành **toggle "bỏ dấu"** ở §18.C1.

---

## 8. Export Excel (đúng format mẫu)

### 8.1 Format file (đã kiểm từ mẫu nhà mạng)
- `.xlsx` (openpyxl), **1 nhà mạng = 1 file**.
- Sheet name: **`Sheet1`**.
- **Không có header**. Dữ liệu bắt đầu từ **row 2** (row 1 để trống theo mẫu).
- **Cột A**: số điện thoại `84xxxxxxxxx` — định dạng **text** (`cell.number_format='@'`) để không bị Excel cắt số 0 / chuyển scientific.
- **Cột B**: nội dung SMS đã render — định dạng **text**.
- Chỉ chứa recipient của đúng `build_revision`, `excluded_reason IS NULL`, thuộc `carrier_bucket` tương ứng và vẫn pass consent/suppression re-check tại thời điểm export.

### 8.2 Filename
`{TenNhom}-{TenChienDich}-{TenNhaMang}.xlsx`, **sanitize**:
- Bỏ ký tự không hợp lệ filename (`\ / : * ? " < > |`), thay khoảng trắng/ký tự lạ bằng `-` hoặc `_`.
- Chuẩn hóa dấu tiếng Việt (tùy chọn) để tránh lỗi hệ thống nhà mạng kén unicode.
- Giới hạn độ dài tổng (vd ≤ 120 ký tự); cắt phần tên nếu quá dài, giữ đủ phân biệt.
- `TenNhom` = `export_batch.group_name_snapshot`. **Chốt B2 — MVP**: campaign chọn nhiều nhóm → export **gộp per nhà mạng** (recipient dedupe gửi-1-lần), `group_id=NULL`, `group_name_snapshot` = ghép tên các nhóm dạng `NhomA+NhomB` (≥3 nhóm → `NhomA+NhomB+N` với N = số nhóm còn lại). Campaign 1 nhóm → `group_id` = nhóm đó, `group_name_snapshot` = tên nhóm. *(Muốn file RIÊNG từng nhóm trong cùng campaign = DEFER: cần thêm `owner_group_id` trên recipient + đổi quy tắc gán nhóm sở hữu — báo lại để chỉnh schema.)*

### 8.3 Lưu trữ
File lưu **ngoài public webroot** (§11.7), `storage_path` + `file_sha256` + `expires_at`. Tải qua endpoint admin hard-gated `RequireAdmin` + verify sha256. `/app/private_exports/sms` phải được tạo với owner phù hợp và gắn persistent/private volume trong Compose/deploy; không dựa vào writable layer của container.

Export idempotent theo `(campaign_id, build_revision, carrier_bucket)`. Quy trình side-effect:
1. Service lock/find-or-create batch `pending`, chỉ `flush`, trả `(batch, post_commit_callback)`.
2. Router commit business transaction trước.
3. Callback được await, mở DB session mới, sinh file vào temp path cùng filesystem, fsync/tính sha256, atomic rename.
4. Transaction ngắn cập nhật batch `generated`; lỗi → `failed`, cleanup temp. Không dùng DB session đã commit trong callback.
5. Retry cùng revision trả batch `generated` hiện có; concurrent caller bị unique/row lock gom về cùng batch. Cleanup job dọn temp/orphan + batch hết hạn.

### 8.4 Gate export (fail-closed)
`POST .../export` từ chối (400) nếu:
- `consent_checked_build_revision`, `dnc_checked_build_revision` hoặc `optout_channel_checked_build_revision` khác `campaign.build_revision`;
- reference tương ứng rỗng hoặc kênh SMS/điện thoại chưa được test/attest;
- còn recipient `over_limit`;
- bất kỳ recipient exportable nào không còn consent `granted` hoặc đã có suppression/opt-out mới.

Re-check cuối chạy dưới transaction/lock thích hợp trước khi tạo batch. Nếu suppression thay đổi sau khi file đã tạo nhưng trước bàn giao, batch `invalidated`; không cho download/mark handed-off cho tới khi rebuild/export lại.

---

## 9. Reports (click theo ngày/tháng/năm)

`GET /api/sms/reports/clicks?group_id=&campaign_id=&carrier=&date_from=&date_to=&granularity=day|month|year`

- **Nguồn**: `sms_click_event` JOIN `sms_campaign_recipient`.
- **Bucket thời gian**: theo `granularity` (date_trunc day/month/year trên `clicked_at`).
- **Lọc**:
  - `campaign_id` → trực tiếp.
  - `carrier` → `recipient.carrier_bucket`.
  - `group_id` → `recipient.group_ids_snapshot @> ARRAY[:group_id]::integer[]` (dùng GIN).
  - `date_from/date_to` → khoảng `clicked_at`.
- **Số đo**:
  - `total_clicks` (gồm bot), `human_clicks` (`is_suspected_bot=FALSE`).
  - `distinct_contacts_clicked` (distinct recipient non-bot).
  - `recipients_handed_off` (mẫu số) → **CTR chính = distinct non-bot / recipients_handed_off**.
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
| PATCH | `/api/sms/contacts/{id}` | sửa identity/note; không sửa consent ledger |
| POST | `/api/sms/contacts/{id}/consent-events` | append granted/revoked kèm disclosure/proof/time |
| GET | `/api/sms/contacts/{id}/consent-events` | xem ledger consent |
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
| POST | `/api/sms/campaigns/{id}/attestations` | ghi consent/DNC/opt-out-channel reference cho đúng revision |
| POST | `/api/sms/campaigns/{id}/export` | sinh Excel per nhà mạng (gate DNC) |
| GET | `/api/sms/campaigns/{id}/exports/{batch_id}/download` | tải file (auth) |
| POST | `/api/sms/campaigns/{id}/exports/{batch_id}/mark-handed-off` | xác nhận đã bàn giao/upload ngoài QLTS |
| GET | `/api/sms/campaigns/{id}/dashboard` | CTR + danh sách click |

**Reports**
| GET | `/api/sms/reports/clicks?group_id=&campaign_id=&carrier=&date_from=&date_to=&granularity=day\|month\|year` | report tổng hợp click |

**Opt-out**
| POST | `/api/sms/opt-out/manual` | admin ghi opt-out |
| GET | `/api/sms/opt-out` | danh sách opt-out |
| **POST** | **`/api/public/sms/opt-out`** | public — opt-out từ landing (body `{code}`) |

**Public**
| **GET** | **`/r/{code}`** | public — resolve short-link → click + redirect |
| **GET** | **`/api/public/sms/landing/{code}`** | public — **read-only** (no side-effect, `Cache-Control: no-store`): trả landing config campaign (headline/body/cta + school_name + consent_notice + `already_opted_out`). KHÔNG trả PII recipient. §19 |

> `/api/public/sms/opt-out` + `/api/public/sms/landing/{code}` dưới `/api/public/` → **CSRF-exempt sẵn** (csrf.py:60). `/r/{code}` GET → không bị CSRF.

---

## 11. Tích hợp hạ tầng (điểm chạm đã verify)

### 11.1 Models — `Backend_FastAPI/app/models/sms/`
Submodule (pattern `finance/`): `contact_group.py`, `contact.py`, `contact_group_member.py`, `contact_import_batch.py`, `prefix_carrier_rule.py`, `campaign.py`, `campaign_group.py`, `campaign_recipient.py`, `campaign_export_batch.py`, `click_event.py`, `opt_out.py`, `marketing_consent_event.py` (**12 model**). **Bắt buộc** import vào `app/models/__init__.py` + `__all__` để alembic autogenerate thấy.

### 11.2 Router — `app/main.py`
- `sms.router` (admin) declare prefix `/api/sms` → `include_router(sms.router)`.
- `sms_public.router` (opt-out) declare `/api/public/sms`.
- `sms_shortlink.router` declare `/r` → `include_router(sms_shortlink.router)` (cùng pattern public router hiện có; không dựa vào line number dễ drift).

### 11.3 Nginx — `nginx/conf.d/default.conf.template`
Thêm location riêng **TRƯỚC** catch-all `location /`. Không dùng access log mặc định vì `$request` chứa raw code:
```nginx
# --- SMS short-link resolver (về backend, KHÔNG về frontend) ---
location /r/ {
    access_log off;
    limit_req zone=general burst=30 nodelay;
    proxy_pass http://backend;
    proxy_read_timeout 30s;
    add_header Referrer-Policy "no-referrer" always;
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex" always;
}

# Landing API cũng chứa code trong path.
location /api/public/sms/landing/ {
    access_log off;
    limit_req zone=general burst=30 nodelay;
    proxy_pass http://backend;
    add_header Referrer-Policy "no-referrer" always;
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex" always;
}

# Frontend landing URL cũng mang bearer code trong path.
location /lp/ {
    access_log off;
    proxy_pass http://frontend;
    add_header Referrer-Policy "no-referrer" always;
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex" always;
}
```
`/lp/{code}` vẫn proxy về Next.js nhưng cần location riêng như trên để tắt raw-path access log và gắn security headers.

Ngoài Nginx, cấu hình Uvicorn/Gunicorn/app exception logging phải redact route `/r/*`, `/lp/*`, `/api/public/sms/landing/*`. Không gọi exception handler hiện tại theo cách ghi nguyên `request.url.path` cho các route này.

### 11.4 CSRF — không cần sửa
opt-out dưới `/api/public/` (exempt sẵn); `/r/{code}` là GET.

### 11.5 Authorization
Phase 1 endpoint admin dùng `RequireAdmin`/`require_admin` làm hard role gate. Casbin admin wildcard hiện có chỉ là lớp policy bổ sung; không dùng wildcard làm bằng chứng duy nhất cho admin-only contract.

### 11.6 Thư viện — `openpyxl==3.1.5`, `pandas==2.3.3` đã có. Phone: `app/utils/phone_helpers.py` (`normalize_vietnam_phone`, `validate_vietnam_phone`, `to_zalo_phone`).

### 11.7 Lưu trữ file export (PII) — KHÔNG public
Repo hiện chỉ public `/static/uploads/`; route public `/uploads/` đã bị loại. File export chứa phone + raw short code nên lưu tại `/app/private_exports/sms/{campaign_id}/{build_revision}/...`, tuyệt đối không nằm dưới `/app/uploads` hoặc `/app/static`.

PR hạ tầng phải:
- tạo directory/owner cho user chạy backend;
- khai báo private persistent volume hoặc object storage private trong dev/prod;
- không thêm Nginx `location` public;
- download qua `RequireAdmin`, kiểm `status='generated'`, expiry, sha256 và revision chưa invalidated;
- cleanup 7-30 ngày, dọn temp/orphan và set `purged_at`.

### 11.8 Quan hệ với `NotificationConsent` đã tồn tại
Hệ thống **đã có** `app/models/notification_consent.py` (`NotificationConsent`) track `channel='sms'`, unique `(channel, source_type, source_id)`, có `normalized_phone` + `consent_status` granted/revoked; và `NotificationChannel.SMS='sms'` (event_groups.py:307, "future feature").
- **Giữ riêng**: `NotificationConsent` = notification giao dịch per entity; `sms_marketing_consent_event` = bằng chứng marketing theo phone/contact; `sms_opt_out` = suppression marketing toàn cục.
- Marketing opt-out **không tự revoke notification giao dịch** nếu chưa có quyết định nghiệp vụ/pháp lý riêng. Build marketing chỉ đọc marketing consent + suppression, không suy diễn từ role hoặc lead status.

### 11.9 Tái dùng đã verify (Explore 2026-06-11)
`phone_helpers` (normalize/to_zalo_phone), Redis rate-limit (`magic_link_rate_limit`), openpyxl+StreamingResponse (`leads.py`), Casbin `get_lead_for_user` (IDOR officer Phase 2), Celery beat (job dọn file export + sweep smart-segment §18.D2), KPI date-bucket pattern (report click §9) — đều có sẵn, dùng lại không xây mới.

---

## 12. Tái sử dụng vs xây mới

| Tái sử dụng (có sẵn) | Xây mới |
|---|---|
| `phone_helpers.normalize_vietnam_phone` / `to_zalo_phone` | 12 model + schema + repo + service + router |
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
| **PR-1: Schema** | **12 model** Phase 1 + register `__init__.py`/`__all__` + create/seed migrations based on current head. Viết tay partial UNIQUE token, GIN array, composite/unique build-revision indexes và CHECK constraints. Không thêm smart-segment/holdout field. | — |
| **PR-2: Contact Management BE** | CRUD groups/contacts, membership, import mobile-only, consent evidence validation, append-only `sms_marketing_consent_event`, projection latest-state dưới row lock | PR-1 |
| **PR-3: Campaign Build BE** | Build revisioned snapshot; consent/suppression filter; HMAC+Fernet token; skeleton render; `[QC]` non-removable; hướng dẫn từ chối SMS/điện thoại; preflight tin cuối; invalidate attestations revision cũ | PR-2 |
| **PR-4: Export BE** | Idempotent batch state machine, private persistent storage, atomic temp→rename, re-check consent/suppression/DNC, re-download, mark-handed-off, cleanup/orphan recovery | PR-3 + launch gate DNC/channel |
| **PR-5: Tracking/Landing/Reports BE** | Public resolve hardened, token-safe logs/headers/rate limits, landing opt-out bổ sung, reports lấy mẫu số handed-off, Nginx sanitized locations | PR-3,4 |
| **PR-6: Frontend** | Contact/consent UI, campaign/preflight, 3 attestation gates, export lifecycle, report, landing mobile-first; không hiển thị delivered/sent | PR-2..5 |
| **PR-7 (Phase 1.5): Smart segment + Conversion** | Migration có chủ đích cho smart segment/holdout nếu được duyệt; conversion attribution dựa trên handed-off events | PR-5 |

Mỗi PR: type-check + test local trước push (`test-before-push`); FE PR Chrome MCP smoke (`chrome-mcp-pre-push-smoke`); xin phép push từng lần (`push-approval-required`).

---

## 14. Trạng thái quyết định thiết kế

> **Verdict: GO (user/chủ dự án authorize 2026-06-11)** — override BLOCK hard-review trước; user xác nhận đủ evidence L1–L4 + lịch sử vận hành không vấn đề PL. PR-1 schema đã code + qua 3 vòng Codex review (R1–R3) trên `sms/pr1-schema` (CHƯA push). Reference L1–L4 trỏ vào `proof_reference`/`source_reference`/attestation khi build campaign thật.

### Launch gate bắt buộc
- **L1 — Consent source contract**: mẫu disclosure, loại proof chấp nhận, retention và chủ sở hữu nghiệp vụ; không chấp nhận `implied_lead`.
- **L2 — DNC workflow**: xác định cơ chế kiểm tra thực tế, nguồn/reference, freshness và cách đồng bộ suppression. Không tuyên bố “import-filter fail-closed” khi chưa biết có file/API hợp lệ.
- **L3 — Opt-out operation**: số/kênh SMS hoặc điện thoại ghi trong tin, người/đơn vị tiếp nhận, SLA xác nhận ngay và quy trình sync vào `sms_opt_out`. Landing chỉ bổ sung.
- **L4 — Data protection/deployment**: hồ sơ đánh giá tác động xử lý dữ liệu trước production; retention; production secrets/key-ring; private export storage; token-safe logging.

### Đã CHỐT
- **B1 — `over_limit` = hard gate** ✅: build/preflight đánh dấu từng dòng `over_limit`; **export CHẶN (400)** nếu còn bất kỳ recipient over_limit → admin rút gọn template. Không loại âm thầm. Cờ `allow_multipart` = DEFER. (§7.2, §8.4)
- **B2 — Multi-group = gộp per carrier** ✅: cho chọn nhiều nhóm, export gộp per nhà mạng (dedupe gửi-1-lần), `group_name_snapshot` = `NhomA+NhomB+N`. File riêng từng nhóm = DEFER (cần `owner_group_id`). (§8.2)
- **B4 — Excel format** ✅ ĐÓNG: mẫu đã kiểm — Sheet1, no header, data từ row 2, A=`84xxxxxxxxx` text, B=nội dung text. Không còn là open question. *(Khuyến nghị vẫn lưu 1 file mẫu vào `Documents/samples/` làm anchor cho test PR-4.)*
- **Token lookup + re-export** ✅: base62×9, HMAC hash + Fernet ciphertext + skeleton; secret tách biệt với IP. (§2.2, §6.1)

### Đã CHỐT (bổ sung 2026-05-26)
- **B3 — Re-import contact trùng phone = GIỮ IDENTITY, APPEND CONSENT EVENT** ✅: không ghi đè `full_name`/`note`; chỉ append consent event nếu lô có đủ proof/disclosure/time.
- **B5 — `{link}` tùy chọn, NHƯNG `external` có `landing_url` thì BẮT BUỘC `{link}`** ✅:
  - `{link}` nói chung là tùy chọn — không có `{link}` → SMS thuần (không redirect/không tracking), preflight cảnh báo "không đo được click".
  - **Ràng buộc validate (P2-2)**: nếu `landing_type='external'` **và** có `landing_url` mà template **thiếu** `{link}` → **lỗi 400** ("đã đặt link đích external nhưng nội dung không có `{link}` để người nhận bấm tới"). Tránh `landing_url` vô nghĩa.
  - `qlts_hosted` thiếu `{link}` → chỉ cảnh báo (không chặn).

### Đã CHỐT (sửa sau hard review 2026-06-11)
- **B6 — Phase 1 chỉ quảng cáo** ✅: `[QC]` auto-prepend non-removable. Không cho admin tự gắn `transactional` để bypass consent/DNC; notification giao dịch đi qua module/approval riêng.
- **B7 — Hai lớp opt-out** ✅: hướng dẫn SMS/điện thoại trong tin là launch gate; landing opt-out QLTS là lớp bổ sung và vẫn ghi suppression toàn cục.
- **B8 — DNC fail-closed theo revision** ✅: export cần reference đối soát thực tế cho đúng `build_revision`; import external suppression chỉ là một implementation option, không tự chứng minh đã kiểm DNC.
- **B9 — Đòn bẩy chi phí tiếng Việt** ✅: toggle "bỏ dấu" (C1) + smart-encoding substitution (C2); preflight đo **tin cuối** (gồm `[QC]`+footer). §18.C.
- **B10 — Scope discipline** ✅: frequency-cap + fallback ở core; smart-segment/holdout để PR-7 với migration riêng sau khi core ổn định.
- **A/B short-link (D5)** = DEFER (user chưa ưu tiên; cần `variant` column khi làm).

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
> **Mở rộng từ landing Phase 1 (§19)** — giữ nguyên header/opt-out/NĐ13, bổ sung danh mục ngành + dwell tracking.
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
- Officer tạo consult link cho lead → tìm contact theo `normalize(lead.phone)`; chưa có → có thể tạo contact (`source_label='lead_consult'`) nhưng `marketing_consent_status` vẫn `unknown`. Consult 1-1 không tự cấp consent marketing campaign.
- **Tab "Quan tâm ngành" trong trang chi tiết lead**: lead → normalize phone → contact → `sms_contact_program_interest` xếp theo `total_dwell_seconds` desc. Hiển thị vd: "C (5ph) · B (2ph) · A (30s)".

### 16.6 Quyền (mở rộng từ "chỉ admin" của Phase 1)
- **Admin**: toàn quyền (danh bạ/nhóm/campaign/export/report tổng + xem mọi interest).
- **Officer**: chỉ (1) **tạo consult link** cho lead trong phạm vi IDOR của mình (tái dùng `get_lead_for_user`), (2) **xem tab interest** của lead mình (read-only). KHÔNG tạo campaign/danh bạ.
- Casbin: thêm policy officer trên `POST /api/sms/leads/{id}/consult-link` + `GET /api/sms/leads/{id}/interests`; admin route vẫn dùng hard admin gate.

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
Deep behavior tracking gắn đích danh là mục đích xử lý dữ liệu riêng, không được suy diễn từ consent marketing SMS. Phase 2 cần disclosure/consent riêng, retention rõ ràng và cập nhật hồ sơ đánh giá tác động trước khi bật. Vẫn `ip_hash`, không IP thô.

### 16.10 Open question Phase 2 (chốt khi tới Phase 2)
- **P2-Q1**: consult link có cho phép officer chọn landing/ngành hiển thị riêng, hay luôn danh mục đầy đủ? → Đề xuất MVP Phase 2: danh mục đầy đủ.
- **P2-Q2 ✅ CHỐT** (research 2026-06-11): `interest_score(contact, program) = normalize( Σ_các_view  dwell_factor × recency_weight )` với `dwell_factor(s)=min(s/DWELL_CAP, 1.0)`, `recency_weight(t)=exp(-Δdays/HALF_LIFE)`, `normalize(x)=x/(x+K)`; `DWELL_CAP/HALF_LIFE/K` **config-driven** (mặc định 180s / 14 ngày / tune). Frequency tự gấp vào (cộng dồn view), recency ưu tiên gần đây, dwell = cường độ (capped chống gian lận). Nguồn: Dynamic Yield affinity + Dotdigital weighting curve. **KHÔNG ML** (volume chưa đủ ngưỡng — Klaviyo cần ≥500 khách/180 ngày mới bật predictive). Chi tiết §18.F.
- **P2-Q3**: retention dữ liệu interest (giữ bao lâu)? → Đề xuất: giữ aggregate dài hạn (profile), event chi tiết dọn sau N tháng.

---

## 17. Ghi chú pháp lý

> Không phải tư vấn pháp lý. Đây là **checkpoint thiết kế** hỗ trợ tuân thủ; trách nhiệm thuộc người vận hành.

**Cơ sở (nguồn nhà nước)**:
- **NĐ 91/2020/NĐ-CP** chống tin nhắn/email/cuộc gọi rác: quảng cáo bằng tin nhắn yêu cầu **đồng ý trước** + **kiểm tra Danh sách không quảng cáo (DNC)**. Nguồn: vanban.chinhphu.vn — https://vanban.chinhphu.vn/default.aspx?docid=200773&pageid=27160
- **Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15**, hiệu lực **2026-01-01**: marketing chỉ được dùng dữ liệu cá nhân khi có consent; phải có kênh từ chối, ngừng quảng cáo sau từ chối và lưu bằng chứng consent. Nguồn: https://vanban.chinhphu.vn/?classid=1&docid=214590&orggroupid=1&pageid=27160
- **NĐ 356/2025/NĐ-CP**, hiệu lực **2026-01-01**, quy định chi tiết Luật Bảo vệ dữ liệu cá nhân. Nguồn: https://vanban.chinhphu.vn/?docid=216387&pageid=27160
- NĐ 91 Điều 16 quy định việc từ chối nhận tin nhắn quảng cáo qua **SMS hoặc cuộc gọi** và phải xác nhận ngay. Landing web không được dùng làm kênh thay thế duy nhất.

**Checkpoint trong hệ thống**:
1. **Gate export theo revision**: consent, DNC và opt-out channel attestation đều phải khớp `build_revision` (§8.4).
2. **Consent trail**: append-only `sms_marketing_consent_event`; contact chỉ giữ latest-state projection.
3. **Tôn trọng opt-out**: `sms_opt_out` khóa phone toàn cục; build/export re-check; batch cũ bị invalidated.
4. **Tối thiểu hoá dữ liệu**: click dùng `ip_hash`; file export PII ngoài webroot + retention ngắn.
5. **Nhãn `[QC]`**: Phase 1 auto-prepend non-removable.
6. **Hướng dẫn từ chối trong tin**: SMS/điện thoại vận hành ngoài QLTS + landing bổ sung.
7. **Hồ sơ đánh giá tác động xử lý dữ liệu**: hoàn thành trước production; cập nhật theo thay đổi và chu kỳ luật định.
8. **Hợp đồng bên xử lý**: nếu nhà mạng/đơn vị upload xử lý thay QLTS, phải có hợp đồng và phân định trách nhiệm/bảo mật.

Yêu cầu compliance L1-L4 (consent/DNC/opt-out-channel/DPIA) vẫn áp dụng cho mỗi campaign quảng cáo. **User/chủ dự án đã ATTEST đủ evidence + authorize GO (2026-06-11)** → không còn block triển khai; reference điền vào `proof_reference`/`source_reference`/attestation khi build campaign thật. (Nguyên tắc giữ nguyên: tính năng kỹ thuật không tự biến quy trình vận hành chưa có thành tuân thủ — evidence phải có thật.)

---

## 18. Phụ lục product/analytics (đã hiệu chỉnh bởi v4)

> **Provenance**: nghiên cứu product/CPaaS/CDP ngày 2026-06-11. Các nhận định pháp lý cũ dựa riêng vào NĐ 13 đã được **thay thế** bởi §17 và launch gate v4.
> **Scope**: chỉ C1/C2/C3/C4, frequency-cap và fallback thuộc core. Smart segment, holdout, conversion và profiling thuộc PR-7/Phase 2, có migration/consent review riêng.
> **Ưu tiên**: **B = compliance P0** (nghĩa vụ luật VN plan đang hở) · **C = đòn bẩy chi phí** (tiếng Việt = UCS-2 70 ký tự, QLTS trả tiền per-segment ở cổng nhà mạng) · **D = engagement/analytics** (toàn bộ là pre-export filter — hợp mô hình export, KHÔNG cần real-time).

### B. Compliance P0 (quyết định v4)

**B0.1 — Nhãn `[QC]` đầu tin quảng cáo**
- Phase 1 chỉ xử lý quảng cáo; service **auto-prepend** `[QC] ` non-removable.
- Không có `message_category` do admin chọn. Tin giao dịch đi qua notification flow/template approval riêng.
- ⚠ Nhãn ngốn ký tự trong ngân sách 70 (UCS-2) → preflight đo **tin cuối** (§7.2 đã sửa).

**B0.2 — Hướng dẫn từ chối TRONG tin**
- Tin cuối phải có hướng dẫn từ chối qua **SMS hoặc điện thoại** lấy từ config/attestation đã test, ví dụ `TC QC: <số/kênh đã phê duyệt>`.
- Link landing `{link}` có thể kèm nút hủy để tăng khả năng tiếp cận, nhưng là kênh bổ sung. Không dùng câu “landing thay reply STOP”.

**B0.3 — DNC = gate có evidence theo build revision**
- Checkbox đơn thuần không đủ. Phải lưu source/reference/timestamp/actor và revision được kiểm.
- Import external suppression là một adapter khả dĩ; chỉ triển khai khi nguồn file/API thực tế được xác nhận. Nếu chưa có cơ chế kiểm DNC thì production export bị block.

**B0-lite (ghi chú vận hành, warning không chặn)**:
- **Khung giờ**: tin QC chỉ ~07:00–22:00 (nhiều nhà mạng siết 08:00–20:00 ICT). QLTS không gửi → **warning tại export**.
- **Brandname/template đăng ký**: nội dung + brandname phải khớp template đã đăng ký với nhà mạng (~5 tuần duyệt) nếu không cổng từ chối upload. Đăng ký nằm ngoài QLTS (admin lo) — nhưng nội dung QLTS sinh **phải tương thích** (Open Q3 §18.J).

### C. Đòn bẩy chi phí (tiếng Việt = UCS-2)
> Phát hiện CPaaS then chốt: GSM-7 chứa `à é ö ü` NHƯNG thiếu `ă â ê ô ơ ư đ` + mọi nguyên âm mang thanh (`ế ữ ạ…`) → **tiếng Việt có dấu LUÔN UCS-2 = 70 ký tự/segment**. 1 chữ `ư`/`đ` kéo cả tin 160→70, gấp đôi chi phí.

- **C1 — Toggle "bỏ dấu" → GSM-7 (giảm ~½ chi phí)**: nâng "gợi ý" §7.2 thành feature per-campaign. De-accent chuẩn (NFD → strip combining marks → case riêng `đ→d/Đ→D`), KHÔNG Telex digraph (khó đọc với phụ huynh). **Cảnh báo UX**: giảm trang trọng → admin chủ động chọn, không auto.
- **C2 — Smart-encoding substitution (free, bật mặc định)**: thay look-alike về GSM trước khi đếm (smart-quote→`'`, em-dash→`-`, NBSP→space). Chống copy-paste Word âm thầm đẩy UCS-2. Khác C1: không đụng dấu tiếng Việt → luôn an toàn.
- **C3 — Per-carrier click = proxy deliverability**: vì không DLR, carrier nào click≈0 → nghi file bị nhà mạng filter / upload lỗi. Cảnh báo trong dashboard (cách duy nhất "thấy" lỗi giao hàng).
- **C4 — Analytics N/A markers**: dashboard hiển thị rõ `delivery/open/bounce = N/A (gửi qua cổng nhà mạng)`. Metric chủ lực: **unique CTR**, **opt-out rate**, **list-growth** (consent mới theo thời gian).

### D. Engagement & analytics (pre-export filter)

- **D1 — Frequency cap**: `sms_contact.last_handed_off_at` + `sms_campaign.frequency_cap_days` (NULL=global). Build loại số thuộc batch đã bàn giao trong N ngày. File chỉ generated không được coi là đã gửi.
- **D2 — Smart segment động (PR-7)**: nếu được duyệt, PR-7 thêm migration cho `group_type='smart'` + `dynamic_rule`; không có trong core PR-1.
- **D4 — Holdout/lift (PR-7)**: nếu được duyệt, PR-7 thêm `holdout_percent`/`is_holdout` và allocation deterministic. Không dùng các cột này trong Phase 1 core.
- **D6 — Fallback + drop-broken-rows (SMS export irreversible)**: mỗi biến có fallback bắt buộc (`{name}`→"Quý phụ huynh/học sinh"); thiếu data nghiêm trọng / `{link}` rỗng → `excluded_reason='missing_data'` (không ghi tin vỡ vào file đã upload nhà mạng). Validate rendered không còn placeholder sót + preview 5 dòng mẫu từ chính segment (Braze `abort_message` analog).
- **D3 — Conversion/attribution (PR-7, chỉ query, không schema SMS)**: window-join send-log ↔ chuyển trạng thái lead/profile (vd "nộp hồ sơ trong 14–30 ngày sau campaign C"). Chu kỳ tuyển sinh dài → window 14–30 ngày (không phải 3 ngày như retail).

### E. Quan hệ với `NotificationConsent` (chi tiết §11.8)
Giữ marketing consent/suppression riêng với notification giao dịch. Không tự revoke hoặc grant chéo giữa hai domain nếu chưa có quyết định nghiệp vụ riêng.

### F. Công thức `interest_score` Phase 2 (chốt P2-Q2)
```
interest_score(contact, program) = normalize( Σ_các_view  dwell_factor(v) × recency_weight(v) )
  dwell_factor(s)   = min(s / DWELL_CAP, 1.0)        # cap 180s → 1 phiên dài không vô hạn
  recency_weight(t) = exp(-Δdays / HALF_LIFE)        # HALF_LIFE 14 ngày
  normalize(x)      = x / (x + K)                    # squash 0–1
```
Config-driven (`SMS_INTEREST_DWELL_CAP/_HALF_LIFE/_K`). Frequency tự gấp vào (cộng dồn view), recency ưu tiên gần đây, dwell = cường độ (capped chống gian lận). Nguồn: Dynamic Yield affinity + Dotdigital weighting curve. **KHÔNG ML**. **Compliance**: profiling đích danh cần consent/mục đích riêng và cập nhật hồ sơ đánh giá tác động theo §17.

### G. Phân chia schema v4
| Bảng | Thêm | Mục đích |
|---|---|---|
| Core PR-1 | consent ledger, hash+cipher token, build revision, attestation revisions, batch lifecycle, handed-off timestamp | correctness/security/compliance |
| PR-7 migration | smart group rule, holdout allocation/variant fields nếu được duyệt | không khóa schema core bằng feature chưa triển khai |

Config Phase 1: `SMS_TOKEN_HASH_SECRET`, `SMS_TOKEN_ENCRYPTION_KEYS`, `SMS_TOKEN_ACTIVE_KEY_VERSION`, `SMS_IP_HASH_SECRET`, `SMS_ALLOWED_REDIRECT_DOMAINS`, `SMS_FREQUENCY_CAP_DAYS`, `SMS_OPTOUT_INSTRUCTION`. Production fail-fast nếu thiếu secret/kênh bắt buộc. Phase 2 thêm `SMS_SESSION_TOKEN_HASH_SECRET` và `SMS_INTEREST_DWELL_CAP`/`_HALF_LIFE`/`_K`.

### H. Roadmap cập nhật
Xem §13. Code PR-1..N tiến hành theo **user GO (L1-L4 đã attest, 2026-06-11)**; PR-7 không ảnh hưởng migration core.

### I. Nguồn (platform reference)
- **CPaaS** (data-model & segment encoding): Twilio (Message resource snapshot, Link Shortening + `event_type:preview`, Advanced Opt-Out, Smart Encoding), Bird, Vonage, Plivo, Sinch, Telnyx.
- **Consumer SMS** (UX & compliance baked-in): Attentive (Two-Tap, Send-Time AI, Analytics), Postscript (Flow Builder, fuzzy opt-out, Add-Reply-STOP), Klaviyo (Smart Opt-in, Smart Sending, A/B auto-winner), SimpleTexting/EZTexting.
- **CDP/journey/affinity**: Braze (Dynamic Segmentation, Liquid `default`, frequency capping, conversion window), Iterable (lift formula), Customer.io (Object+relationship), MoEngage (RFM 11-bucket), Dynamic Yield + Dotdigital (affinity weighting curve).
- **Compliance VN**: nguồn quyết định là §17 (NĐ 91/2020, Luật 91/2025/QH15, NĐ 356/2025/NĐ-CP).

### J. Open question = launch blocker, không chờ tới lúc code
- **Q1**: cổng nhà mạng có tự thêm `[QC]` không? Mặc định QLTS prepend; chỉ thay đổi sau test file thật và approval.
- **Q2**: cơ chế DNC thực tế là file, API hay tra cứu vận hành? Phải chốt owner/freshness/reference trước GO.
- **Q3**: brandname/template đã đăng ký với từng cổng chưa?
- **Q4**: kênh SMS/điện thoại từ chối nào sẽ được in trong tin, ai trực và sync vào QLTS trong SLA nào?

---

## 19. Landing page Phase 1 — spec chi tiết

> Landing QLTS là trang nội dung và kênh opt-out **bổ sung**. Nghĩa vụ kênh từ chối qua SMS/điện thoại được xử lý bởi launch gate L3; không dùng landing để thay thế.

### 19.1 Vai trò & 2 chế độ
`/r/{code}` (backend) ghi click + 302 → `/lp/{code}` (Next.js). Trang lấy nội dung qua `GET /api/public/sms/landing/{code}` (read-only, no-store).

| `landing_type` | Hành vi | Opt-out trên trang |
|---|---|---|
| `qlts_hosted` (mặc định) | `/r/{code}` → `/lp/{code}`: hiển thị **content campaign** (headline/body/CTA) + section opt-out | ✅ nút "Hủy nhận tin" |
| `external` | `/r/{code}` → 302 **thẳng** `landing_url` (host ∈ allowlist) | không có nút QLTS; kênh SMS/điện thoại trong tin vẫn bắt buộc |

**Khuyến nghị**: mặc định `qlts_hosted` để giữ content/opt-out bổ sung trong QLTS. `external` chỉ được dùng với allowlist + confirmation; `[QC]`, consent/DNC gate và hướng dẫn từ chối SMS/điện thoại vẫn áp dụng đầy đủ.

### 19.2 Nội dung & layout (mobile-first)
Đa số mở trên điện thoại → 1 cột, fast-load, không asset nặng. Thứ tự trên → dưới:
1. **Header**: logo + tên trường (nhận diện thương hiệu → tăng tin cậy, chống nghi lừa đảo).
2. **Headline** (`landing_headline`).
3. **Body** (`landing_body`): plain text render xuống dòng — **KHÔNG render HTML** (chống XSS vì nội dung do admin nhập). Nếu cần định dạng → markdown nhẹ qua sanitizer whitelist (bold/list).
4. **CTA chính** (`landing_cta_label`/`_url`, nếu có): nút nổi bật ("Đăng ký tư vấn" → form nội bộ, hoặc "Xem chi tiết" → microsite allowlist). Ẩn nếu NULL.
5. **Divider** → **Section opt-out** (cuối trang): "Bạn nhận tin này vì đã đăng ký/quan tâm tuyển sinh. Không muốn nhận nữa?" + nút **"Hủy nhận tin"**.
6. **Footer**: thông báo xử lý dữ liệu ngắn, thông tin liên hệ + link chính sách.

**Fallback**: campaign không điền `landing_headline/body` → trang tối giản (header + "Cảm ơn bạn đã quan tâm tuyển sinh [Trường]." + section opt-out + footer). Vẫn hợp lệ về opt-out.

### 19.3 Opt-out flow
1. Bấm "Hủy nhận tin" → confirm ("Bạn chắc chắn muốn ngừng nhận tin?").
2. Đồng ý → `POST /api/public/sms/opt-out {code}` (rate-limit theo IP như `/r`).
3. Server: HMAC(code) → tra recipient → ghi `sms_opt_out` (`source='landing_optout'`, `phone_normalized` từ snapshot, `contact_id`, `campaign_id`). **Idempotent** (UNIQUE phone → lần 2 vẫn success).
4. UI thay section opt-out bằng **"Đã hủy nhận tin. Bạn sẽ không nhận tin quảng cáo từ [Trường] nữa."**
5. Mở lại `/lp/{code}` sau đó → `already_opted_out=true` → hiển thị sẵn trạng thái đã hủy.

### 19.4 API `GET /api/public/sms/landing/{code}`
- **Read-only, KHÔNG side-effect**. Header `Cache-Control: no-store` + `X-Robots-Tag: noindex` + `Referrer-Policy: no-referrer`.
- Resolve `HMAC(code)` → `sms_campaign_recipient.token_hash` (Phase 2 mở rộng tra thêm `sms_consult_link`). Không thấy → 404.
- Response (**KHÔNG lộ PII recipient** — phòng code bị share):
```json
{
  "school_name": "Trường …",
  "headline": "Thông báo tuyển sinh 2026",
  "body": "…",
  "cta_label": "Đăng ký tư vấn", "cta_url": "https://…",
  "consent_notice": "…",
  "already_opted_out": false
}
```
- Click thật đã ghi ở `/r/{code}` (302 vào đây) → landing GET **không ghi click lần nữa** (tránh nhân đôi).

### 19.5 Bảo mật & lỗi
- `code` không hợp lệ/hết hạn → trang **404 thân thiện** ("Liên kết không hợp lệ hoặc đã hết hạn"), không lộ chi tiết.
- `landing_cta_url` external → **re-check allowlist** lúc render giống `/r` (§6.2); ngoài allowlist → ẩn CTA + log.
- Rate-limit cả GET landing + POST opt-out; unknown-token/global cap fail-closed.
- Không log raw code tại Nginx/Uvicorn/Gunicorn/app exception; log `token_fingerprint` nếu cần correlation.
- `no-store` + `noindex` + `no-referrer`; CTA external dùng `rel="noreferrer"`.

### 19.6 Tác động schema / PR
- **PR-1 schema**: `landing_headline`/`landing_body`/`landing_cta_label`/`landing_cta_url` nằm trong core schema (§4.6).
- **PR-3 validate**: Phase 1 luôn áp `[QC]`/consent/DNC/opt-out channel; URL external → allowlist.
- **PR-5 API**: `GET /api/public/sms/landing/{code}` read-only + `POST opt-out` (đã có).
- **PR-6 FE**: trang `/lp/{code}` theo §19.2 + opt-out §19.3 + fallback tối giản + mobile-first.
- **Phase 2 (§16.1)** mở rộng trang này (thêm danh mục ngành + dwell), giữ nguyên header/opt-out/footer.
