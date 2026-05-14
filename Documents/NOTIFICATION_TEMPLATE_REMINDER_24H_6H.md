# Magic-link confirmation reminder — Email templates (Phương án 2a)

**Status**: Email-only wire-up. ZNS Zalo deferred until trường có
template_id approved.

## Variables truyền từ `check_admission_confirmation_reminders_task`

| Tên | Ví dụ |
|---|---|
| `lead_name` | "Nguyễn Văn A" |
| `application_id` | `42` |
| `lead_id` | `108` |
| `expires_at_iso` | `"2026-05-01T08:00:00+00:00"` |
| `hours_remaining` | `24` (hoặc `6`) |
| `confirm_url` | `https://qlts.tnpc.edu.vn/admissions/confirm/<token>` |

Substitution syntax: `$variable_name` (giống
`TPL_CONSULTATION_REMINDER_V1`).

---

## Template 1 — `TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1`

**Mục đích**: Nhắc applicant 24h trước khi magic-link hết hạn.

**Title**:
```
[QLTS] Còn $hours_remaining giờ để xác nhận hồ sơ tuyển sinh
```

**Message** (text/plain VN):
```
Chào $lead_name,

Hồ sơ tuyển sinh của bạn cần được xác nhận trong vòng
$hours_remaining giờ tới (hết hạn lúc $expires_at_iso).

Nhấn vào liên kết bên dưới và nhập số CCCD/CMND để xác nhận:

$confirm_url

Sau khi liên kết hết hạn, hồ sơ sẽ tạm dừng và bạn cần liên hệ
phòng tuyển sinh để được hỗ trợ.

Trân trọng,
Phòng Tuyển sinh QLTS
```

**Link template**: `$confirm_url`

**Variables JSON**:
```json
["lead_name", "hours_remaining", "expires_at_iso", "confirm_url"]
```

---

## Template 2 — `TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1`

**Mục đích**: Nhắc applicant 6h trước hết hạn (tone gấp hơn).

**Title**:
```
[QLTS GẤP] Chỉ còn $hours_remaining giờ để xác nhận hồ sơ
```

**Message**:
```
Chào $lead_name,

Đây là nhắc nhở cuối cùng. Hồ sơ tuyển sinh sẽ hết hạn xác nhận
trong $hours_remaining giờ ($expires_at_iso).

Vui lòng xác nhận ngay tại liên kết:

$confirm_url

Nếu liên kết đã được sử dụng, vui lòng bỏ qua email này. Nếu cần
hỗ trợ khẩn, liên hệ Phòng Tuyển sinh.

Trân trọng,
Phòng Tuyển sinh QLTS
```

**Link template**: `$confirm_url`

**Variables JSON**:
```json
["lead_name", "hours_remaining", "expires_at_iso", "confirm_url"]
```

---

## SQL — INSERT 2 templates + UPDATE wire

> ⚠️ Run trên PROD **chỉ sau khi user duyệt nội dung** ở trên.
> Mỗi statement idempotent: re-run an toàn (`ON CONFLICT DO NOTHING`
> + `WHERE template_code IS NULL` predicate).
>
> **Smoke status (2026-04-30)**:
> - Step 1+2 đã chạy thử trên local `qlts_dev`. INSERT 2 templates
>   thành công (ids 76+77). 4 actions wire xong, verify output match
>   expected.
> - Action IDs `92, 93, 94, 95` ở dưới là **prod**. Trên local IDs
>   khác (`382, 383, 384, 385`). Khi run prod, dùng IDs prod như
>   trong block bên dưới.

```sql
-- Step 1: Insert 2 email templates
INSERT INTO notification_template (
  template_code, name, description, title_template, message_template,
  link_template, variables, category, is_system, supported_channels,
  allowed_events, template_type, created_at, updated_at
) VALUES (
  'TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1',
  'Nhắc xác nhận hồ sơ — 24h',
  'Email nhắc applicant 24h trước khi magic-link hết hạn',
  '[QLTS] Còn $hours_remaining giờ để xác nhận hồ sơ tuyển sinh',
  E'Chào $lead_name,\n\nHồ sơ tuyển sinh của bạn cần được xác nhận trong vòng\n$hours_remaining giờ tới (hết hạn lúc $expires_at_iso).\n\nNhấn vào liên kết bên dưới và nhập số CCCD/CMND để xác nhận:\n\n$confirm_url\n\nSau khi liên kết hết hạn, hồ sơ sẽ tạm dừng và bạn cần liên hệ\nphòng tuyển sinh để được hỗ trợ.\n\nTrân trọng,\nPhòng Tuyển sinh QLTS',
  '$confirm_url',
  '["lead_name","hours_remaining","expires_at_iso","confirm_url"]'::json,
  'application',
  true,
  '["email"]'::jsonb,
  '["admission_confirmation_reminder_24h"]'::jsonb,
  'system',
  now(), now()
)
ON CONFLICT (template_code) DO NOTHING;

INSERT INTO notification_template (
  template_code, name, description, title_template, message_template,
  link_template, variables, category, is_system, supported_channels,
  allowed_events, template_type, created_at, updated_at
) VALUES (
  'TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1',
  'Nhắc xác nhận hồ sơ — 6h (gấp)',
  'Email nhắc applicant 6h trước khi magic-link hết hạn',
  '[QLTS GẤP] Chỉ còn $hours_remaining giờ để xác nhận hồ sơ',
  E'Chào $lead_name,\n\nĐây là nhắc nhở cuối cùng. Hồ sơ tuyển sinh sẽ hết hạn xác nhận\ntrong $hours_remaining giờ ($expires_at_iso).\n\nVui lòng xác nhận ngay tại liên kết:\n\n$confirm_url\n\nNếu liên kết đã được sử dụng, vui lòng bỏ qua email này. Nếu cần\nhỗ trợ khẩn, liên hệ Phòng Tuyển sinh.\n\nTrân trọng,\nPhòng Tuyển sinh QLTS',
  '$confirm_url',
  '["lead_name","hours_remaining","expires_at_iso","confirm_url"]'::json,
  'application',
  true,
  '["email"]'::jsonb,
  '["admission_confirmation_reminder_6h"]'::jsonb,
  'system',
  now(), now()
)
ON CONFLICT (template_code) DO NOTHING;

-- Step 2: Wire 4 actions (id 92, 93, 94, 95) với external_resolver=lead_contact
-- + template_code. Note: Action 93 (zalo 24h) + 95 (zalo 6h) wire
-- template_code = NULL nhưng giữ external_resolver, sẵn sàng cho khi
-- ZNS template được Zalo duyệt.

UPDATE notification_action SET
  template_code = 'TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1',
  config = '{"external_resolver": "lead_contact"}'::json
WHERE id = 92  -- 24h email
  AND template_code IS NULL;

UPDATE notification_action SET
  config = '{"external_resolver": "lead_contact"}'::json
WHERE id = 93  -- 24h zalo (template_code chờ ZNS approved)
  AND config IS NULL;

UPDATE notification_action SET
  template_code = 'TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1',
  config = '{"external_resolver": "lead_contact"}'::json
WHERE id = 94  -- 6h email
  AND template_code IS NULL;

UPDATE notification_action SET
  config = '{"external_resolver": "lead_contact"}'::json
WHERE id = 95  -- 6h zalo (template_code chờ ZNS approved)
  AND config IS NULL;

-- Step 3: Verify wire
SELECT a.id, r.event, a.channel, a.template_code, a.config::jsonb
FROM notification_action a JOIN notification_rule r ON r.id = a.rule_id
WHERE r.event IN ('admission_confirmation_reminder_24h',
                  'admission_confirmation_reminder_6h')
ORDER BY r.event, a.channel;
```

**Expected verify output**:
```
 id |              event                  | channel | template_code                                | config
----+-------------------------------------+---------+----------------------------------------------+-------------------------------------------
 92 | admission_confirmation_reminder_24h | email   | TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1   | {"external_resolver": "lead_contact"}
 93 | admission_confirmation_reminder_24h | zalo    | (null)                                       | {"external_resolver": "lead_contact"}
 94 | admission_confirmation_reminder_6h  | email   | TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1    | {"external_resolver": "lead_contact"}
 95 | admission_confirmation_reminder_6h  | zalo    | (null)                                       | {"external_resolver": "lead_contact"}
```

---

## Sau khi apply

1. **Beat task next 30min** sẽ scan token sắp hết hạn. Hiện tại 0
   token pending → vẫn không gửi gì (đúng — không có applicant chờ).
2. **Khi applicant đầu tiên click "Send confirmation"** → token tạo →
   tới mốc 24h hoặc 6h trước expiry sẽ gửi email tới `lead.email`.
3. **Channel zalo** sẽ skip (template_code NULL → dispatcher fail-soft).
   Khi user submit ZNS template + có template_id → INSERT row template
   thứ 3 + UPDATE action 93/95 `template_code` thì zalo tự lên live.

## Smoke test sau apply

```sql
-- Snapshot trước khi tạo profile thử (không cần làm trên prod nếu không
-- muốn dirty data; chạy trên local là đủ).
SELECT COUNT(*) FROM admission_confirmation_token;

-- Sau khi 1 profile thử click "Send confirmation":
SELECT id, expires_at, reminder_24h_sent_at, reminder_6h_sent_at
FROM admission_confirmation_token ORDER BY id DESC LIMIT 1;

-- Sau 30min kể từ khi token còn 24h-->0h:
SELECT * FROM notification_delivery
WHERE notification_type LIKE '%confirmation%'
ORDER BY created_at DESC LIMIT 5;
```
