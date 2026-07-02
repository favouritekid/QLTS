# SCOPE — PR-7 / SMS Phase 2: Deep Engagement + Đo quan tâm ngành

> Nguồn thiết kế: `SMS_MARKETING_MODULE_DESIGN.md` §16 (đã chốt đầy đủ, kể cả công thức interest_score §16.10-P2-Q2 / §18.F). Đây là bản scope thực thi.

## 0. Mục tiêu (khớp ý tưởng owner)
Gắn link vào SMS → khách vào landing → **đo hành động + ngành thực sự quan tâm** → biết "ai quan tâm ngành nào" → officer tư vấn cá nhân + admin thống kê ngành hot. (Không chỉ "ai bấm link" như Phase 1.)

## 1. Đã có (Phase 1) vs sẽ thêm (Phase 2)
| | Phase 1 (đã ship) | Phase 2 (PR-7 này) |
|---|---|---|
| Landing | 1 trang: headline/body/1-CTA/opt-out | **2 tầng**: danh mục ngành → **trang từng ngành** |
| Đo | click link (CTR) | **dwell (thời gian xem) từng ngành** + lượt xem |
| Kết quả | ai bấm link | **hồ sơ "ngành quan tâm" per contact** (interest_score) |
| Officer | — | **link tư vấn 1-1** + **tab "Quan tâm ngành" ở lead** |
| Report | CTR ngày/tháng/năm | + **ngành nóng** theo campaign/nhóm/thời gian |

## 2. Cách đo (§16.2) — KHÔNG cần ML, KHÔNG IntersectionObserver
Mỗi ngành = **1 URL riêng** `/lp/{code}/nganh/{program_id}` → đo **time-on-page chuẩn qua heartbeat**:
- Vào `/lp/{code}` → tạo **session** (bearer token, lưu hash).
- Click ngành → sang trang ngành → ghi **program-view** + bắt đầu dwell.
- Heartbeat định kỳ (JS) cộng `dwell_seconds` cho trang đang xem; rời trang → chốt.
- Bot không chạy JS → không heartbeat → tự loại.
- **Tín hiệu chính = tổng dwell/ngành** (click chỉ phụ).

## 3. Data model (§16.4) — 4 bảng
1. **`sms_landing_session`** — 1 lượt xem landing (contact_id, source campaign/consult, session_token_hash UNIQUE, started/heartbeat/ended, active_seconds, ip_hash, ua, is_bot).
2. **`sms_program_view`** — 1 lượt xem trang ngành (session_id, contact_id, major_program_id, program_name_snapshot, dwell_seconds, sequence_no).
3. **`sms_contact_program_interest`** — hồ sơ tổng hợp (UNIQUE(contact_id, major_program_id), view_count, total_dwell_seconds, first/last_interest_at, interest_score). ← **giá trị nghiệp vụ chính**.
4. **`sms_consult_link`** — link tư vấn officer↔lead (lead_id, contact_id, created_by officer, token_hash partial-UNIQUE, click counters, expires_at).

**Khóa thống nhất = `contact_id`**: campaign recipient & consult link đều resolve về 1 contact → interest gộp theo contact → lead xem qua match phone.

## 4. interest_score (§16.10-P2-Q2, ĐÃ CHỐT — không cần quyết lại)
`interest_score = normalize( Σ_view dwell_factor × recency_weight )`
- `dwell_factor(s) = min(s/DWELL_CAP, 1)` · `recency_weight(t)=exp(-Δdays/HALF_LIFE)` · `normalize(x)=x/(x+K)`
- Config (mặc định): `SMS_INTEREST_DWELL_CAP=180s` · `_HALF_LIFE=14 ngày` · `_K=tune`. Frequency tự cộng dồn, recency ưu tiên gần, dwell = cường độ (capped chống gian lận).

## 5. API (§16.7)
- Public: `GET /landing/{code}` (đọc, +danh mục ngành, no session) · `POST /landing/{code}/session` (tạo session, trả raw token 1 lần) · `POST /program-view` · `POST /heartbeat`.
- Officer: `POST /leads/{id}/consult-link` (scope IDOR) · `GET /leads/{id}/interests`.
- Admin: `GET /reports/program-interest` · `GET /contacts/{id}/interests`.
- `/r/{code}` resolve mở rộng: tra recipient trước, không thấy → consult_link.

## 6. Lộ trình PR con (§16.8) + đề xuất thứ tự
| PR con | Nội dung | Ghi chú |
|---|---|---|
| **P2-1 Schema** | 4 bảng + migration + config secret `SMS_SESSION_TOKEN_HASH_SECRET`+dwell config | nền |
| **P2-2 Deep tracking BE** | landing resolve mở rộng + session/program-view/heartbeat + aggregate interest_score + report program-interest | **lõi đo lường** |
| **P2-4a FE tracking** | landing 2 tầng (`/lp/{code}` danh mục + `/lp/{code}/nganh/{id}` heartbeat JS) + admin report ngành | **thấy được kết quả** |
| **P2-3 Consult BE** | officer consult-link (IDOR) + `/leads/{id}/interests` + Casbin officer | add-on tư vấn |
| **P2-4b FE consult** | tab "Quan tâm ngành" ở lead detail + nút officer "Tạo link tư vấn" | add-on |

→ **MVP đo-quan-tâm** = P2-1 + P2-2 + P2-4a (bỏ consult trước cũng chạy được thống kê ngành). Consult (P2-3/P2-4b) làm sau nếu cần.

## 7. Tái dùng (§16.3, §18.E) — KHÔNG xây mới
- Ngành: `MajorProgram`/`ProgramOffering` (đã có), catalog `GET /api/public/admissions/programs`.
- Token/hash/Fernet, `ip_hash`, rate-limit, `/r/{code}` resolve, landing §19 (giữ header/opt-out/footer), Celery beat (dọn), KPI date-bucket (report).

## 8. ⚠️ RÀO PHÁP LÝ (§16.9) — GATE trước khi BẬT prod (không phải code)
Deep tracking đích danh = **mục đích xử lý dữ liệu RIÊNG**, KHÔNG suy diễn từ consent marketing SMS. Trước khi bật prod cần (owner/pháp lý lo):
1. **Disclosure/consent riêng** cho việc theo dõi hành vi (thông báo trên landing + cơ sở).
2. **Chính sách retention** rõ ràng (P2-Q3).
3. Cập nhật **hồ sơ đánh giá tác động** (DPIA).
→ Tôi **code được feature** ngay; nhưng **bật dùng thật** phải qua bước compliance này.

## 9. Quyết định cần owner chốt
- **D1 — Phạm vi PR-7 lần này:** (a) **MVP đo-quan-tâm** (P2-1+P2-2+P2-4a, chưa consult) — khuyến nghị; hay (b) **đầy đủ §16** (thêm consult officer + tab lead).
- **D2 — P2-Q1 (consult link):** officer luôn thấy **danh mục đầy đủ** (đề xuất MVP) hay chọn ngành riêng? (chỉ cần nếu làm consult)
- **D3 — P2-Q3 (retention):** giữ **aggregate profile dài hạn** + xoá **event chi tiết sau N tháng** — N = ? (đề xuất 12 tháng)
- **D4 — Compliance §16.9:** ai lo disclosure/consent + DPIA? (owner) — code không chờ, nhưng bật prod thì chờ.

---
**Đề xuất của tôi:** làm **D1=(a) MVP đo-quan-tâm** trước (P2-1→P2-2→P2-4a) — đúng trọng tâm ý owner ("đo quan tâm ngành"), gọn, thấy kết quả nhanh; consult officer để đợt sau. Bắt đầu bằng **P2-1 (Schema)**.
