# Plan: Lead Reopen Workflow — mở lại lead sts20 (CONSULT_GIVEUP) có kiểm soát

> Trạng thái: **PLAN — chưa code.** Tiền đề: PR sts20 CONSULT_GIVEUP đã **MERGED
> (#390) + deploy prod** — chạy với `SLA_AUTO_GIVEUP_ENABLED=false` (beat CHƯA tự
> đóng) + gate chặn tạo hồ sơ từ lead consultation-terminal (`consultation_terminal`
> trong `check_lead_level_admission_eligibility`). `SLA_CONSULT_GIVEUP_DAYS` prod = 15.
>
> **Hai quyết định đã chốt (2026-06-09):**
> 1. **RULE #13.2 → mốc re-engage** (KHÔNG xóa history). Giữ `lead_status_history`
>    append-only; beat đóng lại được sau reopen nhờ mốc thời gian. Xem §4.
> 2. **Bản tối giản trước** (Phase A — manager/admin 1-click reopen). Đủ để bật
>    `SLA_AUTO_GIVEUP_ENABLED` an toàn. Luồng officer-request đầy đủ là Phase B.

## 1. Context / vì sao

`sts20 CONSULT_GIVEUP` là trạng thái **terminal cứng** (is_final=true, không có
transition ra). Khi lead sang sts20:
- Officer chỉ ghi được hoạt động liên hệ (universal), **không** re-engage status.
- **Không** tạo hồ sơ tuyển sinh (đã chặn bằng `consultation_terminal`).
- **Không** tạo lead mới cùng SĐT (lead sts20 chưa xóa → `uq_lead_phone_active`
  vẫn giữ SĐT).

→ Một lead "đã ngừng tư vấn" thực sự quay lại (đổi ý) hiện **không có đường mở
lại** qua nghiệp vụ. Cần quy trình **manager/admin mở lại có lý do + audit + chống
lạm dụng**; ở Phase B nâng lên **officer xin → manager/admin duyệt**.

**Liên hệ với rollout flag:** Điều kiện bật `SLA_AUTO_GIVEUP_ENABLED` (beat tự đóng)
một cách an toàn = **PR-A (reopen MVP) + chốt §9.1 (chặn "reopen lậu" qua
soft-delete)** — CẢ HAI nằm trong acceptance của PR-A. Đủ đường mở lại + bịt đường
lách thì beat tự đóng lead mới mới đảo được. Không cần chờ trọn Phase B.

## 2. Quyết định thiết kế (chốt)

- **Đường mở lại = sts20 → sts04** (KHÔNG về sts03/05/06). sts04 là điểm re-engage
  chuẩn; từ sts04 officer tiếp tục luồng tư vấn bình thường (sts04→sts03/05/06).
- **Reopen KHÔNG dùng FSM transition thường, KHÔNG seed `allowed_transition
  sts20→sts04`.** Nếu seed, manager đổi được sts20→sts04 qua `add_consultation`
  thường, bỏ qua kiểm soát. → Reopen là **service chuyên dụng** (mutate có guard +
  ghi history thủ công + set mốc re-engage).
- **Suy `lead.status` + `pipeline_stage_id` từ sts04 bằng `sync_lead_status`/
  `derive_lead_status`, rồi ĐỌC LẠI giá trị SAU sync để ghi history** — KHÔNG
  hardcode `'contacted'`/`'stg02'`. Tránh drift nếu quy tắc derive đổi (cùng bài học
  migration backfill PR sts20). Canonical hiện tại (chỉ để tham chiếu): sts04 →
  `status='contacted'`, `pipeline_stage_id='stg02'`. Chi tiết bước ở §5.
- **Lock khi mở lại**: `SELECT ... FOR UPDATE` trên lead row trong transaction
  (chống double-reopen / TOCTOU; pattern admin rollback lock #345). Re-check
  `consultation_status_id='sts20'` SAU khi đã lock.
- **Audit**: mỗi lần mở lại ghi `lead_status_history` (changed_by = reviewer) +
  `audit_service`. KHÔNG xóa bất kỳ history nào (xem §4).
- **Phạm vi quyền (IDOR 3 tầng)**: manager mở lại lead trong unit; admin toàn hệ
  thống. Dùng `get_lead_for_user` sẵn có → trả **404** (không 403) cho ngoài phạm
  vi. Phase B thêm officer-request + tầng scope cho approve/reject (xem §B).

## 3. Mốc re-engage + guard beat (nền tảng — cả Phase A và B dùng)

### 3.1 Cột mới `lead.consultation_reengaged_at`
- Kiểu `timestamptz`, NULL (mặc định). Set `= now()` mỗi lần reopen được duyệt.
- Lead hiện có → NULL → hành vi guard y hệt hiện tại (backfill = no-op).
- Migration alembic data-less (add column), `down_revision` = head tại thời điểm code.

### 3.2 Sửa RULE #13.2 (`execute_system_transition`, `fsm_engine.py`)
Hiện tại RULE #13.2 skip nếu **TỪNG** có history `new_consultation_status_id =
to_status`:
```python
# Hiện tại (semantics "EVER"):
WHERE lead_status_history.lead_id = :lead
  AND lead_status_history.new_consultation_status_id = :to_status
```
Đổi sang **"kể từ lần re-engage gần nhất"**: chỉ tính history sau mốc reopen.
```python
# Mới (semantics "since last re-engage"):
WHERE lead_status_history.lead_id = :lead
  AND lead_status_history.new_consultation_status_id = :to_status
  AND (
        lead.consultation_reengaged_at IS NULL          -- chưa reopen → như cũ
     OR lead_status_history.changed_at > lead.consultation_reengaged_at
  )
```
- Lead **chưa reopen** (cột NULL) → điều kiện đầu true → **hành vi không đổi** cho
  mọi transition/system event khác → **blast-radius tối thiểu**.
- Lead **đã reopen** → history sts20 cũ (changed_at < reengaged_at) bị bỏ qua →
  beat đóng lại được lần sau, **không cần xóa history**.

> ⚠ Đây là guard **dùng chung mọi system transition**. Bắt buộc:
> - Chạy **full FSM anchor matrix** (`test-fixture-drift-after-policy-refactor`).
> - Test riêng: reopen → stale lại ≥ `SLA_CONSULT_GIVEUP_DAYS` (prod 15) →
>   **beat đóng lại được** (history sts20 mới tạo, audit đủ cả 2 lần give-up).
> - Test hồi quy: lead chưa reopen vẫn skip đúng như cũ (idempotency các event khác
>   không vỡ).
> - **Lưu ý implement (B2):** `fsm_engine.py:~535` chỉ `SELECT FROM LeadStatusHistory`;
>   `lead` là object Python **in-memory** (truyền vào hàm), KHÔNG join bảng `lead`. Đọc
>   `lead.consultation_reengaged_at` bằng Python rồi: nếu `is not None` mới thêm
>   `AND LeadStatusHistory.changed_at > :reengaged_at` vào WHERE. KHÔNG viết SQL join
>   bảng `lead` — đoạn SQL ở §3.2 chỉ minh hoạ semantics, không phải query thật.

## 4. Vì sao mốc-thời-gian thay cho xóa history

Phương án cũ (xóa/supersede history `new='sts20'` khi approve) **phá audit
append-only**: mỗi vòng đóng→mở→đóng mất một lớp lịch sử give-up, mâu thuẫn chính
cảnh báo trong downgrade migration sts20 ("mất audit bất khả đảo"). Nguyên nhân
gốc là RULE #13.2 dùng semantics "EVER" — sai cho lead **cố ý** re-engage. Sửa
semantics (§3.2) giải đúng gốc, giữ nguyên mọi history. Đánh đổi: phải test guard
chung rộng hơn (chấp nhận, vì đã có anchor matrix).

## 5. State machine

```
Phase A (MVP):
  (lead sts20) --manager/admin REOPEN(reason)--> lead sts04 + reengaged_at=now

Phase B (đầy đủ, sau):
  (lead sts20) --officer REQUEST(reason)--> request[pending]
     request[pending] --manager/admin APPROVE--> approved + (REOPEN như trên)
     request[pending] --manager/admin REJECT(note)--> rejected (lead giữ sts20)
     request[pending] --officer CANCEL--> cancelled        (lead giữ sts20)
```

Guard REOPEN (lõi, dùng chung A/B), trong 1 transaction:
1. `SELECT lead ... FOR UPDATE`.
2. Re-check `lead.consultation_status_id == 'sts20'` (DB, không tin client) → nếu
   không: `BusinessRuleViolation`.
3. **Capture old state TRƯỚC khi đổi**: `old_cs='sts20'`,
   `old_status=lead.status` (canonical 'rejected'), `old_stage=lead.pipeline_stage_id`.
4. **Mutate + sync (KHÔNG gán literal status/stage)**: set
   `lead.consultation_status_id='sts04'`, `consultation_reengaged_at=now`,
   `updated_at=now`; gọi `sync_lead_status`/`derive_lead_status` để suy `lead.status`
   + `lead.pipeline_stage_id` từ sts04.
5. **Ghi history từ state đã capture + ĐỌC LẠI sau sync**: INSERT
   `lead_status_history` old=(`old_cs`, `old_status`, `old_stage`) →
   new=(`'sts04'`, `lead.status`, `lead.pipeline_stage_id` *sau* sync),
   `changed_by_user_id`=reviewer, reason='reopen: <lý do>'.
6. `audit_service` log.

## 6. Phase A — MVP (manager/admin 1-click)

### 6.0 Backend permission contract (BẮT BUỘC — để FE flag-driven)
FE hiện nút theo **permission flag từ API**, KHÔNG `user.role`. Phải mở rộng chỗ
populate `permissions`/`available_actions`/`action_blockers` của Lead detail
(`lead_service.py` `_attach...`, hiện chỉ có `create_admission` —
`permissions = {"create_admission": ...}`):
- `permissions["can_reopen"] = (lead.consultation_status_id == 'sts20')` **và** user
  là manager/admin (role-gate ở backend; FE chỉ đọc cờ).
- `action_blockers["can_reopen"]` = lý do khi false (vd `not_terminal` / `forbidden`).
- `available_actions` tự gồm `"can_reopen"` khi cờ true.
Thiếu bước này → FE rơi lại role-check hoặc thiếu nút (đúng lỗi đã chỉ ra).

### 6.1 Service `app/services/lead_reopen_service.py`
- `reopen_lead(db, lead_id, reviewer, reason) -> (lead, post_commit_cb)`
  - reason bắt buộc + min length (validate ở schema).
  - Lõi REOPEN §5. Trả callback (no-op ở MVP; chỗ cắm notification Phase C).
  - Raises domain exceptions (KHÔNG HTTPException).

### 6.2 Router `app/routers/leads.py` (hoặc tách `lead_reopen.py`) — dumb
- `POST /leads/{lead_id}/reopen` — body `{ reason }`.
- Dep IDOR: `get_lead_for_user` (manager unit / admin all → 404 ngoài phạm vi).
- Router commit + await callback.

### 6.3 Casbin (migration INSERT casbin_rule, nhớ `v3=eft`)
- `role:manager` / `role:admin` `POST /api/leads/{id}/reopen` allow.
- DENY chỉ ở LEAF roles nếu cần (`casbin-deny-parent-role-propagates`).
- (Officer KHÔNG có quyền ở Phase A — chỉ mở lại bởi manager/admin.)

### 6.4 Frontend
- Lead sts20: nút **"Mở lại tư vấn"** (hiện theo **permission flag từ API**, KHÔNG
  theo `user.role`) → dialog nhập lý do.
- Sau reopen: lead detail refetch → về sts04, các nút tư vấn trở lại. Mutation
  onSuccess invalidate lead detail + danh sách (`react-query-mutation-cache-parity`).

### 6.5 Test Phase A (one-off container — `local-test-oneoff-container-pattern`)
- reopen: lead sts20 → sts04 + `status` = giá trị SAU `sync_lead_status` (canonical
  'contacted' — verify qua helper, KHÔNG so literal) + `reengaged_at` set + history
  (changed_by=reviewer). Lead không sts20 → `BusinessRuleViolation`.
- `can_reopen` flag (§6.0): true cho manager/admin trên lead sts20; false + blocker
  cho lead không sts20.
- **beat đóng lại được** sau reopen rồi stale lại ≥ `SLA_CONSULT_GIVEUP_DAYS`
  (verify §3.2).
- IDOR: manager mở lead ngoài unit → 404; role:user/officer → 403 (Casbin).
- Race: 2 reopen song song → 1 thắng (FOR UPDATE).
- Full FSM anchor matrix (guard #13.2 đổi).

## 7. Phase B — luồng officer-request đầy đủ (sau Phase A)

Xây trên cùng lõi `reopen_lead`. Bổ sung:

### 7.1 Bảng `lead_reopen_request`
| cột | kiểu | ghi chú |
|---|---|---|
| id | PK | |
| lead_id | FK lead, NOT NULL, index | |
| requested_by_id | FK user, NOT NULL | officer xin mở |
| reason | Text, NOT NULL | lý do (validate min length) |
| status | String(20), NOT NULL, default 'pending' + **CHECK in (pending,approved,rejected,cancelled)** | |
| reviewed_by_id | FK user, NULL | manager/admin duyệt |
| review_note | Text, NULL | |
| created_at | tz, NOT NULL, server_default now() | |
| reviewed_at | tz, NULL | |
| unit_id | FK organization_unit, NOT NULL, index | **chỉ để filter/sort list** — KHÔNG phải nguồn phân quyền (xem 7.4) |

- **Partial unique** `uq_reopen_one_pending_per_lead` trên `(lead_id) WHERE
  status='pending'` → chặn 2 pending cùng lead (race-safe, chống spam).
- Index `(unit_id, status)` cho list duyệt.

### 7.2 Service (mở rộng `lead_reopen_service.py`)
- `request_reopen(db, lead_id, requested_by, reason)` — guard lead sts20 + chưa có
  pending (`ConflictError`).
- `approve_reopen(db, request_id, reviewer, note=None) -> (request, cb)` — re-check
  request pending + lead vẫn sts20 (FOR UPDATE cả request + lead) → gọi lõi
  `reopen_lead`; set request approved.
- `reject_reopen(db, request_id, reviewer, note) -> (request, cb)` — note bắt buộc;
  lead giữ sts20. **Trả callback** (notification REJECTED Phase C).
- `cancel_reopen(db, request_id, requester)` — requester tự hủy pending.
- `list_reopen_requests(db, user, status=...)` — IDOR-scoped.

### 7.3 Router + endpoints
- `POST /leads/{lead_id}/reopen-requests` (officer+; reason body).
- `GET /reopen-requests?status=pending` (manager/admin; scoped).
- `POST /reopen-requests/{id}/approve` (manager/admin).
- `POST /reopen-requests/{id}/reject` (manager/admin; note required).
- `DELETE /reopen-requests/{id}` (requester cancel).

### 7.4 IDOR cho approve/reject (điểm phải làm đúng)
`require_admin_or_manager` **chỉ check role, KHÔNG check unit**. Cần dependency
**`get_reopen_request_for_user`**: load request → lead → so `lead.unit_id` **hiện
tại** (KHÔNG dùng `unit_id` snapshot) → manager ngoài unit nhận **404**; admin all.
Thiếu tầng này = mọi manager duyệt được mọi request toàn hệ thống.

### 7.5 Casbin Phase B
- `role:officer` POST `/api/leads/{id}/reopen-requests` allow; DELETE
  `/api/reopen-requests/{id}` allow (cancel own).
- `role:manager`/`role:admin` GET `/api/reopen-requests`, POST `.../approve`,
  POST `.../reject` allow.

## 8. Notification (Phase C, tùy chọn)

Hạ tầng có sẵn (`SystemEvents` + `event_catalog` + `notification_rule` +
`dispatch`) — **không** tạo event system mới:
- `LEAD_REOPEN_REQUESTED` → manager unit (in-app + email).
- `LEAD_REOPEN_APPROVED` / `LEAD_REOPEN_REJECTED` → officer xin.
- Mỗi event: enum + catalog entry + **seed `notification_rule` row** (không có rule
  → fail-closed im lặng). Chạy full notification CI suite local
  (`notification-event-gate-required-locally`).

### 8.1 Beat auto-close notify + socket (GỘP vào đợt này — chốt 06-09 impact audit)

Hiện `sla_tasks.close_stale_rejected_leads` đóng lead **KHÔNG** dispatch/emit (manual
close qua `add_consultation` thì CÓ `CONSULTATION_CREATED` + `LEAD_STATUS_CHANGED` +
socket `rooms_for_lead`). Impact audit 06-09 chốt **defer + gộp vào đợt reopen** (lý do:
lead terminal ít ai xem lúc 03:30; thông báo chỉ có nghĩa khi officer có đường can
thiệp = reopen). Khi code reopen, bổ sung:
- **Báo officer** lead của họ bị hệ thống tự đóng — **in-app + socket only** (KHÔNG
  email/Zalo để tránh ồn). Tái dùng `LEAD_STATUS_CHANGED` hoặc event riêng
  `LEAD_AUTO_GIVEUP`; seed `notification_rule` (fail-closed).
- **Socket emit** để FE list/detail tự refresh thay vì phải F5.
- ⚠ ~100 lead/đợt backfill: dispatch trong vòng lặp phải **per-lead try** (không kéo
  cả task fail) + chạy SAU `session.commit()` của batch; cân nhắc chỉ in-app/socket.

## 9. Chống gian lận / lạm dụng

- Phase A: chỉ manager/admin mở lại. Phase B: officer **không** tự mở (bắt buộc
  duyệt) — chặn tự giảm tải / tự hồi sinh lead.
- Reason bắt buộc + min length; lưu nguyên văn để audit.
- 1 pending / lead (partial unique, Phase B) — chống spam.
- REOPEN re-check lead vẫn sts20 + FOR UPDATE (chống TOCTOU/double).
- Toàn bộ ghi `lead_status_history` + `audit_service`. **Không xóa history** (§4).
- IDOR 3 tầng (trả 404 không 403 — `AUTHORIZATION_GUIDELINES`).
- **Abuse tracking** (Phase D): đếm reopen request bị REJECT của 1 officer trong N
  ngày; vượt ngưỡng → flag (giống `collaborator.is_flagged`). Báo admin.

### 9.1 Vector giải phóng SĐT + tạo lại cùng số — **acceptance bắt buộc của PR-A**

> ⚠ **Sửa threat model (hard-review 2026-06-09).** Bản plan cũ giả định "officer
> **xóa** lead sts20 → giải phóng SĐT". SAI: `delete_lead` là **admin-only**
> (`lead_service.py:4201` enforce ở service + router Casbin) — officer KHÔNG xóa được
> lead nào. Mitigation (a) cũ ("chặn officer xóa lead terminal") vì thế **vô nghĩa**
> (officer vốn đã bị chặn xóa mọi lead). Cơ chế giải phóng SĐT cũng KHÔNG ở bảng `lead`:
> `uq_lead_phone_active` nằm trên bảng riêng **`lead_phone_identity(phone_normalized)
> WHERE deleted_at IS NULL`** (`lead_phone.py:34`, FK `ondelete=CASCADE`, cascade
> soft-delete khi xóa/đổi phone).

**Đường lách thật (officer làm được):** officer *assigned* **đổi số điện thoại** của
lead sts20 qua `PUT /leads/{id}` — `update_lead` cho phép officer assigned
(`lead_service.py:1291`); identity-lock (`:1334`) CHỈ khóa phone/email khi lead có
AdmissionProfile ở approved/rejected/enrolled, mà lead sts20 (đi từ sts04 "từ chối tư
vấn") gần như chắc chắn **chưa có** profile → KHÔNG bị khóa. Đổi phone →
`update_phone_identities` (`:1613`) soft-delete identity cũ → SĐT cũ được giải phóng →
officer `POST /leads` **tạo lead mới cùng SĐT** → lead mới ở sts00, **bỏ qua toàn bộ
audit/kiểm soát reopen** ("reopen lậu").

> ⚠⚠ **Sửa lần 2 (lúc bắt tay code 2026-06-09).** Ý "gate `create_lead` match SĐT lead
> sts20" (B-1 bản đầu) **KHÔNG bịt được vector**: sau khi officer đổi phone lead sts20
> X→Y, lead đó mang phone **Y** — query "lead sts20 có phone X" tìm thấy **rỗng**. Cơ
> chế giải phóng phá luôn cái link mà B-1 định bắt. Defense đúng phải **giữ cho SĐT
> không bị giải phóng khỏi lead terminal** ngay từ đầu.

**Defense đúng = B-2 (khóa SĐT trên lead terminal) — PRIMARY, bắt buộc PR-A:**
- **(B-2) Chặn đổi `phone`/`phone2` của lead consultation-terminal (sts20)** trong
  `update_lead` (đặt ngay sau identity-lock `:1334`; chỉ chặn khi giá trị thật sự đổi).
  Hệ quả dây chuyền bịt kín: SĐT **luôn khóa active** trên lead sts20 →
  `create_lead` (`:912` `check_phone_conflict`, global `deleted_at IS NULL`) **đã** raise
  `DuplicateResourceError` khi tạo trùng → officer **buộc phải reopen** (sts20→sts04, lúc
  đó mới đổi/tái dùng được). **Airtight cho đường officer** — không cần gate create_lead.
  - Lưu ý gồm **cả `phone2`** (cũng vào `lead_phone_identity`), KHÔNG chỉ `phone`.

**Rẻ, nên có (UX — không phải security gate):**
- **(B-1′) Cải thiện message `create_lead`**: khi `check_phone_conflict` trùng một lead
  **sts20 chưa xóa**, đổi message từ "trùng SĐT" chung → **gợi ý mở lại (reopen)** lead
  đó. Vì B-2 giữ SĐT luôn khóa trên lead sts20 nên B-1′ luôn có cơ hội kích hoạt đúng.

**Defer / optional:**
- Đường **admin-xóa** lead sts20 (giải phóng SĐT) → tạo lại: admin toàn quyền + có log
  `audit_service.log_deleted` → defense-in-depth tùy chọn (gate create_lead match lead
  sts20 **đã xóa**), KHÔNG bắt buộc PR-A.

## 10. PR breakdown (ước lượng)

| PR | Phase | Nội dung | ~ |
|---|---|---|---|
| PR-A | A (MVP) | cột `consultation_reengaged_at` + sửa RULE #13.2 (mốc) + `reopen_lead` + endpoint `/leads/{id}/reopen` + **permission contract `can_reopen` (§6.0)** + **guard "reopen lậu" §9.1 B-2 (khóa đổi phone/phone2 lead terminal) + B-1′ (message gợi ý reopen)** + Casbin manager/admin + FE nút/dialog + full FSM matrix | 2.5–3d |
| PR-B | B | bảng `lead_reopen_request` + officer-request/approve/reject/cancel + IDOR scope (7.4) + inbox FE | 2–2.5d |
| PR-C | C | notification events (requested/approved/rejected) | 1d |
| PR-D | D | abuse tracking + báo cáo admin | 0.5–1d |

**Bật `SLA_AUTO_GIVEUP_ENABLED` an toàn = PR-A TRỌN VẸN** (reopen MVP + guard §9.1 B-2
khóa đổi phone lead terminal + permission contract §6.0): manager mở lại được + beat đóng lại
được + audit đủ + không còn đường "reopen lậu". Phase B/C/D hoàn thiện luồng
officer-self-service.

## 11. Rủi ro / điểm review kỹ

- **Guard #13.2 đổi (§3.2)** là guard chung — phải full FSM anchor matrix + test
  hồi quy idempotency các event khác + test reopen→stale→đóng-lại. Đây là điểm
  review kỹ nhất của PR-A.
- **Vector "reopen lậu" (§9.1)** — đường thật = officer **đổi phone** lead sts20 rồi
  tạo lead mới cùng số (KHÔNG phải officer-xóa: `delete_lead` admin-only). Bắt buộc
  PR-A: **B-2 khóa đổi phone/phone2 trên lead terminal** (giữ SĐT khóa →
  `check_phone_conflict` hiện hữu tự chặn tạo trùng → buộc reopen). Gate-match-phone ở
  `create_lead` KHÔNG đủ (lead terminal mất phone sau giải phóng). Điểm review kỹ #2.
- **IDOR scope approve/reject (§7.4)** — Phase B bắt buộc dependency unit-scope, không
  chỉ role.
- **Không seed transition sts20→sts04** — nếu lỡ seed, bỏ qua được kiểm soát. Giữ
  reopen ở service chuyên dụng.
- **derive_lead_status** — gọi helper, không hardcode `'contacted'` (verify canonical
  sts04 = contacted/stg02).
- `uq_lead_phone_active` (trên bảng `lead_phone_identity`, KHÔNG phải `lead`) với
  **cùng** lead (reopen, không tạo mới) — an toàn; rủi ro chỉ ở nhánh giải-phóng-SĐT
  (officer đổi-phone hoặc admin-xóa) rồi tạo-lead-mới (§9.1).
- **Consultation records outcome sts20**: khi reopen lead về sts04, các consultation
  `status_id='sts20'` đã tạo (cả **manual** qua `add_consultation` LẪN **beat**
  `sla_tasks` — beat thêm Consultation hệ thống khi `assigned_officer_id` not null) vẫn
  ghi sts20 → xác nhận không lệch hiển thị/đếm (sts20 `counts_for_funnel=true`). (C2)
- **(C1) Assignment sau reopen**: beat KHÔNG reset `assigned_officer_id` → lead sts20
  giữ officer cũ → reopen về sts04 thì officer cũ nhận lại + workload sts04 phục hồi
  (assignment_service tính sts04 vào utilization). Đúng nghiệp vụ; reopen KHÔNG đụng
  assignment. Nếu lead đã mất assignment thì quyết định auto-assign hay để pending.
- **(C3) Index**: query #13.2 mới lọc `(lead_id, new_consultation_status_id,
  changed_at)` — hiện chỉ single-column index. Scale nhỏ (ít history/lead) → KHÔNG
  blocker; cân nhắc composite index khi tiện.
