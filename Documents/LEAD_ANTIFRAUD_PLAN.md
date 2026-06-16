# KẾ HOẠCH CHỐNG GIAN LẬN LEAD — SĐT / NGUỒN / CTV

> Hardening sau điều tra "officer gian lận sửa SĐT/nguồn của lead được phân phối tự động".
> Soạn: 2026-06-16. Trạng thái: **PLAN — chưa code.**

---

## 0. TL;DR

- Điều tra toàn diện 3 vector gian lận (V1 hoa hồng CTV, V2 bắt cóc SĐT, V3 thổi nguồn).
- **Truy vết prod (read-only) ngày 2026-06-16: KHÔNG tìm thấy bằng chứng gian lận gây hại.**
  `commission_record` trống 100%; không có SĐT bị gom; 4 lead referrer đều hợp lệ từ lúc tạo.
- **Nhưng 3 lỗ hổng cấu trúc vẫn còn nguyên** → khắc phục phòng ngừa, **ưu tiên làm TRƯỚC khi module commission đi vào hoạt động**.
- Hướng đã chốt: **V1 = soft-warn + audit đầy đủ**, **V2 = audit + giám sát** (đều nhẹ, hợp solo-dev).
- Khối lượng: **2 PR** (~2.5–3.5 ngày). PR-1 (P0) độc lập, ship ngay.

---

## 1. Kết quả điều tra prod (bằng chứng nền)

Truy vết qua SSH `qlts_production` (read-only, mask PII), 2026-06-16:

| Vector | Phát hiện | Kết luận |
|--------|-----------|----------|
| **V1 — Hoa hồng CTV khống** | `commission_record` **0 row** toàn hệ thống. 4 lead có `referrer_id` (67,90,91,93) đều `n_updates=0` (referrer gắn lúc tạo, không sửa sau) — đúng luồng smart-referral fast-path. | ✅ Sạch / chưa khai thác |
| **V2 — Bắt cóc SĐT** | 15 lần đổi `phone` + 43 lần đổi `phone2`, mỗi officer trên lead của mình. **Không SĐT nào bị gom cho >1 lead.** | ✅ Không dấu hiệu |
| **V3 — Đổi nguồn** | 35 lần đổi `source`; `ksorhohon` 24 lần/1 ngày (website→social/other, giống dọn data); vài lần →referral **không kèm referrer_id** (không trigger hoa hồng). | 🟡 Bất thường nhẹ, không ra tiền |

**Giới hạn:** vì `referrer_id` **không** nằm trong audit log, không thể loại trừ 100% kịch bản "gán CTV rồi gỡ" trong quá khứ — nhưng `commission_record` trống là bằng chứng mạnh chưa có thiệt hại.

---

## 2. Mô hình đe dọa & lỗ hổng cấu trúc

Officer được phân lead tự động có quyền `PUT /api/leads/{id}` (Casbin `policy_templates.py:120`) và sửa lead **được phân cho mình** (`lead_service.py:1325-1329`). Các lỗ hổng:

| # | Lỗ hổng | Vị trí | Hệ quả |
|---|---------|--------|--------|
| L1 | `referrer_id` **không** có trong snapshot audit | `lead_service.py:614-630` (`_get_lead_audit_state`) | Gán/đổi CTV **không để lại dấu vết** → gian lận hoa hồng vô hình |
| L2 | Officer tự gán `referrer_id` sau auto-assign; tự động set `source='referral'` | `lead_service.py:1556-1574` | Mở khóa dòng tiền hoa hồng cho CTV đồng phạm (commission trigger theo `referrer_id`) |
| L3 | `source` **không** validate theo enum | `schemas/lead.py:257`; `models/lead.py:99` (String(50)) | Nhập nguồn tùy ý; đổi →`referral` thổi `lead_score` (referral=30đ) |
| L4 | Đổi `phone` tự do trên lead active (chỉ chặn ở trạng thái terminal sts20) | `lead_service.py:1389-1404` | Bắt cóc/cô lập lead; lan sang AdmissionProfile (sync `:1699-1715`) |
| L5 | Docstring sai sự thật "chỉ Admin/Manager" | `routers/leads.py:720` | Hiểu nhầm bề mặt tấn công |

**Đã loại trừ (không phải lỗ hổng):** đổi `consultation_status_id`/`pipeline_stage_id` (chặn cứng `:1549-1553`); đổi `assigned_officer_id` (ngoài whitelist `:78-97`); tự gọi `/assign` (Casbin manager-only).

---

## 3. Quyết định thiết kế (đã chốt với user)

- **V1 (CTV/nguồn → hoa hồng): Soft-warn + audit đầy đủ.** Không đổi workflow officer; vá điểm mù audit + đánh dấu đậm hành vi nhạy cảm để giám sát.
- **V2 (SĐT): Audit + giám sát.** Giữ quyền sửa; tận dụng audit sẵn có + thêm phát hiện bất thường + (FE) lịch sử SĐT.
- **V3 (nguồn): Validate enum.** Chặn giá trị rác (gộp vào PR-1).
- Nguyên tắc xuyên suốt: **không thêm `SystemEvents` mới** (theo `Backend_FastAPI/CLAUDE.md` — tốn catalog+rule row); cảnh báo đi qua **audit log + script giám sát**, realtime-notify để defer.

---

## 4. Phạm vi & thứ tự PR

| PR | Nội dung | Ưu tiên | Ước tính | Phụ thuộc |
|----|----------|---------|----------|-----------|
| **PR-1** | Audit completeness + validate `source` + sửa docstring | **P0** | ~1 ngày | độc lập, ship trước |
| **PR-2** | Soft-warn V1 (flag hành vi nhạy cảm) + script giám sát V1/V2/V3 | P1 | ~1.5–2 ngày | sau PR-1 |
| (opt) | FE: hiển thị "Lịch sử SĐT" của lead (đọc audit-logs) | P2 | ~0.5 ngày | sau PR-1 |

> Có thể gộp PR-1+PR-2 thành 1 PR (giảm overhead CI, theo `solo-dev-batch-prs`) — nhưng PR-1 đủ giá trị độc lập và **nên ship gấp trước khi bật commission**, nên tách là hợp lý.

---

## 5. PR-1 (P0) — Audit completeness + validate source + docstring

**Mục tiêu:** mọi thay đổi `referrer_id` để lại dấu vết; chặn nguồn rác; sửa tài liệu sai. Rẻ, không đổi nghiệp vụ.

### 5.1 Bịt điểm mù audit (L1)
`lead_service.py:614-630` — thêm field vào `_get_lead_audit_state()`:
```python
"referrer_id": lead.referrer_id,          # ← BẮT BUỘC (vector hoa hồng)
"validity_status": lead.validity_status,  # ← hữu ích: commission gate theo validity
# lead_score / is_hot_lead: KHÔNG thêm (derived, gây audit noise mỗi lần đổi gpa/source)
```
→ Tự động: thay đổi `referrer_id` sẽ vào `changes` JSONB của audit "updated" hiện có (`:1724-1740`), không cần code thêm.

### 5.2 Validate `source` theo enum (L3)
`schemas/lead.py` — `LeadUpdate.source` (line 257) **và** `LeadCreate.source`: thêm validator reject giá trị ngoài `LeadSourceEnum` (`models/lead.py:48-57`). Reuse enum, không hardcode:
```python
@field_validator("source")
@classmethod
def validate_source(cls, v):
    if v is None: return v
    allowed = {e.value for e in LeadSourceEnum}
    if v not in allowed:
        raise ValueError(f"Nguồn không hợp lệ. Cho phép: {', '.join(sorted(allowed))}")
    return v
```
> Lưu ý: kiểm tra dữ liệu prod hiện có giá trị `source` nào ngoài enum không trước khi siết (tránh vỡ lead cũ). Truy vết đã thấy toàn giá trị enum hợp lệ — nhưng xác nhận lại bằng `SELECT DISTINCT source FROM lead`.

### 5.3 Sửa docstring sai (L5)
`routers/leads.py:720` — `"""Cập nhật một Lead (chỉ Admin/Manager)."""` → mô tả đúng: officer sửa được lead **được phân cho mình**; Admin/Manager sửa theo scope.

### 5.4 Test PR-1
- Unit: update `referrer_id` → có row `entity_audit_log` với key `referrer_id` trong `changes`.
- Unit: `source` ngoài enum → `ValidationError` (400).
- Regression: cập nhật lead bình thường vẫn pass; audit vẫn ghi phone/source như cũ.

---

## 6. PR-2 (P1) — Soft-warn V1 + script giám sát

**Mục tiêu:** đánh dấu đậm hành vi nhạy cảm (không chặn) + công cụ phát hiện bất thường định kỳ.

### 6.1 Soft-warn khi officer "mở khóa hoa hồng" sau auto-assign (L2)
Trong `update_lead`, sau khối xử lý `referrer_id` (`lead_service.py:1556-1574`), thêm phát hiện hành vi nhạy cảm:
- Điều kiện cờ: actor là **officer** (`updated_by.role == OFFICER`) **và** lead **đã auto-assign** (`db_lead.assigned_officer_id` set từ trước) **và** (`referrer_id` chuyển `NULL→X` **hoặc** `source` chuyển sang `'referral'`).
- Hành động (soft, không raise):
  1. `log.warning("lead_referral_set_after_autoassign", lead_id, actor_id, old_referrer, new_referrer, old_source, new_source)`.
  2. Ghi 1 audit entry **đánh dấu** qua `audit_service.log_audit(..., action="flagged", reason="referrer/source set sau auto-assign", source="api")` (cột `reason` + `action` đã có — `audit_service.py:62-117`).
- **Không** chặn thao tác (đúng quyết định soft-warn).

### 6.2 Script giám sát (pattern `app/scripts/audit_*.py`, ref PR #397)
Tạo `app/scripts/audit_lead_fraud_signals.py` — chạy tay / cron nhẹ, in báo cáo (mask PII):
- **V1:** lead có `referrer_id` mà CTV `managed_by_officer_id == assigned_officer_id` **VÀ** có audit `flagged`/đổi `source→referral` (phân biệt gán-sau vs referral-gốc); đối chiếu `commission_record` nếu có.
- **V2:** officer đổi `phone`/`phone2` ≥ N lần / cửa sổ thời gian; cùng 1 `phone_new` cho >1 lead (gom số).
- **V3:** officer đổi `source` hàng loạt; tỉ lệ →`referral` cao.
- Output: bảng `actor → tín hiệu → số lần`, kèm `lead_id` để soát thủ công.

### 6.3 Test PR-2
- Unit: officer set `referrer_id` trên lead đã assign → có audit `action="flagged"` + log.warning; thao tác vẫn thành công (không 4xx).
- Unit: admin/manager làm điều tương tự → **không** flag (chỉ officer).
- Script: seed vài lead/audit giả → script in đúng tín hiệu.

---

## 7. (Optional, P2) FE — Lịch sử SĐT

Endpoint `/api/leads/{id}/audit-logs` đã tồn tại + officer có quyền GET (`policy_templates.py:130`). FE thêm mục "Lịch sử số điện thoại" trong timeline/detail lead: lọc audit có key `phone`/`phone2` trong `changes`, hiển thị `cũ → mới`, ai sửa, khi nào. Tăng khả năng tự-soát, răn đe. Defer nếu cần ship nhanh.

---

## 8. Rollout & verify

1. PR-1 merge + deploy (no migration, code-only) → **làm trước khi bật bất kỳ `commission_policy` nào.**
2. Sau deploy PR-1: smoke — officer đổi `referrer_id` 1 lead dev → xác nhận audit có `referrer_id`; thử `source="xxx"` → bị reject.
3. PR-2 merge + deploy → chạy `audit_lead_fraud_signals.py` trên prod (read-only) làm baseline.
4. Lịch giám sát: chạy script định kỳ (vd tuần/lần) hoặc trước mỗi kỳ chốt hoa hồng.

---

## 9. Out of scope / defer

- **Maker-checker gán CTV** (đã cân nhắc, user chọn soft-warn) — để dành nếu tương lai phát hiện lạm dụng thật.
- **Khóa/maker-checker đổi SĐT theo trạng thái** (V2 mức cao) — defer; hiện chỉ audit + giám sát.
- **Realtime notify manager** khi có cờ — defer (tránh thêm `SystemEvents`); dùng script giám sát trước.
- **Backfill audit lịch sử `referrer_id`** quá khứ — không khả thi (dữ liệu không tồn tại); chấp nhận điểm mù lịch sử, chỉ vá từ nay.

---

## 10. Quyết định mở (cần xác nhận khi code)

1. **Ngưỡng giám sát V2/V3** (N lần đổi / cửa sổ) — đề xuất mặc định: phone ≥3 lần/30 ngày, source→referral bất kỳ lần nào sau auto-assign. Tinh chỉnh theo baseline thật.
2. **Thêm `lead_score`/`is_hot_lead` vào audit?** — mặc định KHÔNG (noise). Bật nếu muốn truy vết thổi điểm chi tiết.
3. **Gộp PR-1+PR-2 hay tách?** — đề xuất tách (PR-1 ship gấp trước commission).
