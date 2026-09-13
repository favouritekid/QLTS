# Hai cổng chặn nightly regression — B1 (submit hồ sơ) và B2 (import lead)

> **Trạng thái:** CHƯA SỬA. Cả hai nằm ở **runtime / dữ liệu**, không phải ở test.
> Chúng cần PR riêng có cổng deploy riêng.
> **Đo ngày:** 13-09-2026, trên `main = 7e67fe46ee6350bd3f97f645170d48791897a7ea`.

Tài liệu này tồn tại vì bốn trong sáu suite của *Nightly Regression Tests* **không thể
xanh** cho tới khi hai lỗi dưới đây được gỡ, và vì lý do ấy không đọc ra được từ
thông điệp lỗi trên CI. Bản vá test (PR #629) chỉ làm chúng đỏ **đúng chỗ, có chẩn
đoán**; nó cố ý không nới assertion để che.

| Suite | Chặn bởi |
|---|---|
| `admission-lifecycle` | B1 |
| `finance-lifecycle` | B1 |
| `lead-to-admission-workflow` (từ test 9) | B1 |
| `lead-workflow` (test 6 ⇒ tests 7–10 không chạy) | B2 |
| `bugfix-regression` | — (đã xanh 9/9) |
| `smoke` | — (đã xanh) |

---

## B1 — `POST /api/admissions/{id}/submit` không thể thành công trên CSDL mới

### Triệu chứng

```
Submit errors: ["KV_UNRESOLVED (manual_override): … Lý do: admin_set_kv_directly …",
                "Phường/Xã thường trú phải theo địa giới hiện hành (2 cấp, sau 01/07/2025)…"]
```

### Nguyên nhân 1 — dữ liệu danh mục không tái lập được từ kho

Trên một CSDL vừa `alembic upgrade head` + `scripts/seed_from_xlsx`:

```
administrative_nodes = 0    current_era = 0
vn_school            = 0    vn_commune_area_map = 0
```

Mọi nhánh giải KV đều fail-closed khi các bảng này rỗng:

- CĐ chính quy + `graduated_thpt` đi nhánh `LICH_SU_THPT`, đòi tra được
  `academic_history[].school_id` — `priority_service.py:652-672` — mà **`vn_school` rỗng**.
- Nhánh `THUONG_TRU` / `COMMUNE_SPECIAL` đòi `vn_commune_area_map` — **rỗng**.
- `_is_current_era_ward` đòi `administrative_nodes` có node đương thời — **rỗng**;
  bỏ trống ward thì vướng validator *"Thiếu địa chỉ thường trú"*.

**Vì sao seed không cứu được:** `scripts/seeds/seed_administrative_nodes` đọc
`Documents/Seeding data/data province/ward_mappings.sql`. Tệp đó **chưa từng tồn tại
trong git** — `git log --all -- '<đường dẫn>'` trả rỗng — và
`app/scripts/build_kv_table_dak_lak.py:29` đọc nó từ `/tmp/ward_mappings.sql`,
tức một đường dẫn cục bộ trên máy ai đó. `scripts/seed_from_xlsx.py:1285` chỉ **in
hướng dẫn** chạy nó; workflow nightly không gọi.

> ⚠️ Hệ quả rộng hơn CI: dữ liệu danh mục hành chính hiện **không dựng lại được từ
> kho**. Ai dựng môi trường từ đầu — máy mới, khôi phục sau sự cố — sẽ không có nó.

### Nguyên nhân 2 — mâu thuẫn trong cùng một tệp, khiến override thủ công vô hiệu

Đường thoát sản phẩm là `POST /api/v2/admissions/{id}/override-priority-kv`
(admin/manager). Nó trả **200**, nhưng **không có tác dụng**:

`app/services/priority_service.py:599-607` — nhánh `MANUAL`:

```python
if basis == "MANUAL":
    # Caller phải đã set kv_resolved trong snapshot trước khi gọi engine;
    # engine trả None để báo "không tự resolve, dùng existing kv_resolved".
    return None, _meta_base(rule_applied="manual_override", …)
```

Hợp đồng: **`None` nghĩa là GIỮ giá trị cũ.**

`app/services/priority_service.py:851-859` — `freeze_priority_snapshot`:

```python
kv_resolved, meta = await resolve_kv_for_profile(profile, db, …)
rule_applied = meta.get("rule_applied")
snapshot: dict[str, Any] = {
    "kv_resolved": kv_resolved,        # ← chính cái None ở trên
    "rule_applied": rule_applied,
    …
}
```

Hiện thực: **`None` được ghi thẳng vào snapshot mới**, xoá mất `kv_resolved` mà
`priority_override_service.override_kv` vừa đặt.

Lượt freeze lúc submit vì thế dựng snapshot `rule_applied="manual_override",
kv_resolved=None`. Mà whitelist của `_kv_unresolved_error_message`
(`admission_service.py:6224-6284`) đòi **cả hai**: `rule_applied` nằm trong
`{longest_duration, tiebreak_graduation_school, commune_lookup, manual_override}`
**và** `kv_resolved != None`. Nên hồ sơ quay lại `draft`.

Đây là deadlock mà memory `admission-kv-freeze-wipe-manual-override` đã ghi; nay có
căn cứ mã tới từng dòng.

### Phạm vi sửa (PR riêng)

1. Đưa dữ liệu danh mục hành chính vào kho hoặc một artifact dựng lại được, **và**
   thêm bước seed vào `.github/workflows/nightly-regression.yml`.
2. Vá `freeze_priority_snapshot`: khi `rule_applied == "manual_override"` và engine
   trả `None`, **giữ** `kv_resolved` đang có trong
   `profile.priority_resolution_snapshot` thay vì ghi đè bằng `None`.
3. Ca kiểm ngược bắt buộc: override KV → submit → snapshot phải còn `kv_resolved`.
   Gỡ bản vá ⇒ ca phải ĐỎ.

---

## B2 — `POST /api/leads/import` chết trên mọi CSDL mới

### Triệu chứng

```
400 {"detail":"System configuration error: Initial lead status not found.",
     "error_code":"HTTP_400"}
```

### Nguyên nhân

`app/services/status_helper.py:46-67` — `StatusHelper.get_initial_status` tìm:

```python
ConsultationStatus.legacy_status == "new"  AND  ConsultationStatus.is_final == False
```

Nhưng sau `alembic upgrade head`:

- `alembic/versions/zq6w7x8y9z0a1_seed_operational_baseline.py:146` chèn `sts00`
  (`NOT_CONTACTED`) với `legacy_status = **NULL**`;
- `alembic/versions/zb1h2i3j4k5l6_fix_consultation_status_legacy_and_funnel.py:59`
  đẩy `sts02` từ `'new'` sang `'contacted'`;
- dòng gán lại `'new'` ở `zb1h2i3j4k5l6:128` nằm trong **`downgrade()`**, không phải
  `upgrade()`;
- `seed_10b_trang_thai` bỏ qua vì bảng đã có 21 hàng.

Đo trên CSDL mới:

```sql
SELECT count(*) FILTER (WHERE legacy_status = 'new') , count(*)
FROM consultation_status;
--  0 | 21
```

⇒ `get_initial_status()` trả `None`.

### Vết loang — 5 nơi gọi, không chỉ đường import

```
app/services/collaborator_service.py:490
app/services/lead_service.py:1183
app/services/lead_service.py:2784
app/services/lead_service.py:4526
app/services/status_helper.py:212   (get_initial_status_id)
```

### ⚠️ Giới hạn của phép đo này

Đây là lỗi của **CSDL MỚI** — thứ CI dựng mỗi đêm. **Chưa đo CSDL production**, nên
**không** kết luận production hỏng: bảng `consultation_status` trên production đi qua
cùng chuỗi migration nhưng với dữ liệu có sẵn, có thể còn hàng `legacy_status='new'`
từ trước. Việc cần làm trước tiên là **đo prod**, rồi mới chọn cách vá.

### Phạm vi sửa (PR riêng)

1. Đo production: `SELECT id, code, legacy_status, is_final FROM consultation_status
   WHERE legacy_status = 'new' OR id = 'sts00';`
2. Tuỳ kết quả: migration đặt `sts00.legacy_status='new'`, **hoặc** đổi
   `get_initial_status` sang tra theo `code='NOT_CONTACTED'` (ổn định hơn
   `legacy_status`, vốn là cột tương thích ngược).
3. Nếu đổi hàm thì rà **cả 5** nơi gọi — luật *"vá một nhánh thì còn bốn"*.
4. Ca kiểm ngược: trên CSDL mới, `POST /api/leads/import` phải 2xx; gỡ bản vá ⇒ ĐỎ.

---

## Vì sao không sửa chung với PR #629

PR #629 là **test-only**. Hai lỗi trên nằm ở service, migration và dữ liệu seed —
mỗi thứ đều đi qua cổng deploy. Gộp chúng vào một PR test sẽ làm mất khả năng lùi
riêng từng phần, và làm một thay đổi runtime đi kèm một diff test lớn mà người duyệt
khó tách. Sửa test để che chúng thì còn tệ hơn: bốn suite sẽ xanh trong khi hai
đường sản phẩm thật vẫn hỏng.
