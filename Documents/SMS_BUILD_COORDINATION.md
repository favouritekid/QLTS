# SMS Marketing — Bảng điều phối build (Claude × Codex)

> **Nguồn sự thật chung cho 2 AI agent (Claude Code + Codex CLI) cùng build trên 1 repo local D:\QLTS.**
> Cả 2 agent **đọc file này TRƯỚC mỗi phiên** và **cập nhật §9 status sau mỗi PR**.
> Plan thiết kế gốc: **`Documents/SMS_MARKETING_MODULE_DESIGN.md`** (§1–§19). File này KHÔNG lặp lại thiết kế — nó trả lời: *agent nào làm gì, ở đâu, theo thứ tự nào, tránh giẫm chân ra sao, và luật repo bắt buộc.*
> Cập nhật: 2026-06-11. Trạng thái: **GO (user authorize) — PR-1 schema CODE XONG + qua 3 vòng Codex review (R1–R3), commit branch `sms/pr1-schema` CHƯA push.** Workflow: **Claude code TOÀN BỘ, Codex review TOÀN BỘ** (đổi từ chia owner cũ).
> Contract v4 trong `SMS_MARKETING_MODULE_DESIGN.md` supersede mọi chi tiết v3 còn sót: 12 model core, token HMAC+Fernet base62×9, consent ledger, revisioned attestations, `handed_off` thay `sent`, landing opt-out chỉ là kênh bổ sung.

---

## 0. TL;DR cho agent vừa vào phiên
1. **GATE ĐÃ MỞ (user GO 2026-06-11)**: user xác nhận đủ evidence L1–L4 + authorize triển khai. PR-1 đã code; push vẫn cần approval per-lần.
2. **Workflow MỚI (user chốt 2026-06-11)**: **Claude code TOÀN BỘ PR-1..7; Codex review TOÀN BỘ.** (Thay chia owner cũ Claude=PR-1/3/6/7, Codex=PR-2/4/5 ở §3/§7.)
3. **Mỗi agent 1 git worktree + branch riêng** (§2). **KHÔNG sửa file ngoài ranh giới của mình** (§3).
4. **Shared files** (`models/__init__.py`, `main.py`, migration, nginx) có protocol riêng.
5. **Mỗi PR**: author code → review chéo → user approve push → merge → agent kia rebase.
6. **Đọc §6 và design v4 trước khi code.**

---

## 1. Nguyên tắc phối hợp
1. **Author/Reviewer chéo** — mỗi PR 1 agent CODE, agent kia REVIEW (adversarial, §8) trước merge. Lợi ích lớn nhất của 2 model khác nhau = bắt bug chéo.
2. **Isolation bằng worktree + ranh giới file** (§2, §3) — models cố định sau PR-1 ⇒ ít conflict.
3. **Contract-first** (§5) — API contract chốt ngay sau PR-1 ⇒ PR-5 (public) và PR-6 (FE) build song song theo contract + mock.
4. **Shared doc này** = trạng thái + phân công + contract; cập nhật §9 sau mỗi bước.
5. **Gate người dùng giữ nguyên** (§6.5) — push-approval per-PR, Chrome MCP smoke (FE), CI 5-check. Không agent nào tự ý push/merge.

---

## 2. Cơ chế git (2 CLI local, cùng repo)

**Layout**:
- `D:\QLTS` = **main, giữ SẠCH** + nơi chạy **Docker stack** (postgres:5433, redis:6380, backend:8000, frontend:3000). Dùng để merge + chạy stack + smoke. **Không agent nào code trực tiếp ở đây.**
- **Claude worktree**: `git worktree add ../QLTS-sms-claude <branch>` → code ở `D:\QLTS-sms-claude`.
- **Codex worktree**: `git worktree add ../QLTS-sms-codex <branch>` → code ở `D:\QLTS-sms-codex`.

**Branch naming**: `sms/pr1-schema`, `sms/pr2-contact`, `sms/pr3-build`, `sms/pr4-export`, `sms/pr5-tracking`, `sms/pr6-fe`, `sms/pr7-segment`. Mỗi branch off `main` mới nhất.

**Test trong worktree** (KHÔNG chạy stack thứ 2 — tốn RAM/port): dùng **one-off container** mount code worktree + trỏ postgres của stack chính (`qlts_test` DB). Pattern đã có: memory `worktree-backend-oneoff-test-pattern` + `local-test-oneoff-container-pattern` + `docker-compose-override-db-url`. FE check: `fe-check.sh` (run `--rm --no-deps`, KHÔNG exec) + cần bind-mount src worktree (memory `fe-check-run-stale-src`).

**Merge order** (§4): mỗi PR xong → user duyệt → merge vào `main` → **agent kia `git fetch && git rebase origin/main`** worktree của mình trước khi tiếp.

**Quy tắc vàng**: nếu cần đụng file **ngoài ranh giới** của mình hoặc 1 **shared file** (§3.2) → **DỪNG, ghi vào §9 "cần phối hợp", báo user** — KHÔNG tự sửa rồi để conflict.

---

## 3. Ranh giới file (boundary matrix)

> Mục tiêu: 2 worktree gần như **không bao giờ sửa cùng 1 file**. Mỗi surface = file riêng. `models/sms/` cố định sau PR-1 nên chỉ đọc.

### 3.1 File riêng theo PR (an toàn, code thoải mái)
| PR | Owner | Thư mục/file ĐƯỢC sửa |
|---|---|---|
| PR-1 | Claude | `app/models/sms/*.py` (12 model) · `alembic/versions/sms*_*.py` (2 migration) · **wire skeleton** routers + `main.py` (§3.2) |
| PR-2 | Codex | `app/services/sms/contact_service.py` · `app/repositories/sms/contact_repository.py` · `app/schemas/sms/contact.py` · `app/routers/sms_contacts.py` |
| PR-3 | Claude | `app/services/sms/campaign_build_service.py` (+ helpers: render/preflight/carrier/encoding) · `app/repositories/sms/campaign_repository.py` · `app/schemas/sms/campaign.py` · `app/routers/sms_campaigns.py` |
| PR-4 | Codex | `app/services/sms/export_service.py` · `app/schemas/sms/export.py` · `app/routers/sms_export.py` (hoặc gộp vào sms_campaigns nếu Claude đã tạo — phối hợp §3.2) · `app/tasks/sms_tasks.py` (cleanup) |
| PR-5 | Codex | `app/services/sms/tracking_service.py` · `report_service.py` · `optout_service.py` · `landing_service.py` · `app/routers/sms_shortlink.py` (`/r`) · `app/routers/sms_public.py` (`/api/public/sms`) · `app/routers/sms_reports.py` · `nginx/conf.d/default.conf.template` (location /r/) |
| PR-6 | Claude | `frontend/src/app/(dashboard)/.../sms/**` · `frontend/src/app/lp/[code]/**` · `frontend/src/components/sms/**` · `frontend/src/lib/api/sms.ts` · `frontend/src/lib/zod/sms.ts` · `frontend/src/hooks/sms/**` |
| PR-7 | Claude | `app/services/sms/segment_service.py` · `conversion_report_service.py` · lead-detail interest tab (FE) · Casbin officer policy (Phase 2) |

> Tách service thành nhiều file nhỏ per-PR thay vì 1 `sms_service.py` khổng lồ — tránh god-file (bài học `system-bloat-assessment`) và tránh 2 agent đụng 1 file.

### 3.2 SHARED files — PROTOCOL bắt buộc (nguồn conflict #1)
| File | Ai được sửa | Quy tắc |
|---|---|---|
| `app/models/__init__.py` (+`__all__`) | **Chỉ PR-1 (Claude)** | PR-1 đăng ký đủ 12 model. PR khác KHÔNG đụng. Phase 2/PR-7 đăng ký model của migration riêng khi được duyệt. |
| `app/main.py` (`include_router`) | **Chỉ PR-1 (Claude)** | PR-1 tạo **router stub rỗng** cho cả 6 file router (`sms_contacts`, `sms_campaigns`, `sms_export`, `sms_shortlink`, `sms_public`, `sms_reports`) + include 1 lần. PR sau **chỉ thêm route vào file router của mình**, KHÔNG đụng main.py. |
| `alembic` head chain | **Chỉ PR-1 (Phase 1)** | Core gồm đúng schema v4 §4. Smart-segment/holdout không gộp sớm; PR-7 dùng migration riêng có chủ đích. |
| `app/core/deps.py` | Hạn chế tối đa | SMS Phase 1 admin-only dùng `RequireAdmin`/`require_admin` hard gate. Casbin wildcard không phải lớp bảo vệ duy nhất. PR-7 officer scope tái dùng `get_lead_for_user`. |
| `nginx/conf.d/default.conf.template` | **Chỉ PR-5 (Codex)** | Location `/r/` và landing API trước catch-all; access log không chứa raw code; thêm no-referrer/no-store/noindex. |
| `requirements.txt` | **Tránh thêm dep** | openpyxl/pandas/phone_helpers đã có. "Bỏ dấu" (C1) viết bằng `unicodedata.normalize('NFD')` + map `đ→d` — **KHÔNG cần lib mới**. Nếu thật sự cần dep → báo §9, 1 owner thêm, reviewer xác nhận. |
| `app/core/event_groups.py` | KHÔNG đụng Phase 1 | `NotificationChannel.SMS` đã có. SMS marketing **không** qua dispatch() (§6.3). |

---

## 4. Dependency graph + thứ tự thực thi

```
PR-1 Schema (Claude) ──┬─────────────────────────────────────────────► merge TRƯỚC TẤT CẢ
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
   PR-2 Contact (Codex)         PR-5 public-surface (Codex)  ← // song song
        │                        (/r, opt-out, landing API §19;
        ▼                         chỉ cần MODELS từ PR-1, không cần data PR-3)
   PR-3 Build (Claude) ──────────────┐
        │                            │
        ▼                            ▼
   PR-4 Export (Codex)        PR-5 reports (Codex)  ← cần recipient/click data từ PR-3
        └──────────────┬─────────────┘
                       ▼
                  PR-6 FE (Claude)  ← scaffolding sớm theo contract §5, ráp khi BE land
                       ▼
                  PR-7 Segment+Conversion (Claude)
```

**Điểm song song thật**:
- Sau PR-1 merge: **Codex bắt đầu PR-5 public-surface** (`/r` resolve + click event + bot filter + opt-out + landing API §19) — chỉ phụ thuộc models, **chạy // PR-2/PR-3 của Claude**.
- **PR-6 FE scaffolding** bắt đầu ngay khi contract §5 chốt (sau PR-1), fill dần khi API land.
- Sau PR-3 merge: **PR-4 (Codex) // phần reports của PR-5 (Codex)** — nhưng cùng owner Codex ⇒ Codex tự xếp.

**Nút thắt**: PR-1 (blocker tuyệt đối) và PR-3 (build sinh data cho PR-4/5/6). Ưu tiên Claude làm nhanh & sạch 2 PR này.

---

## 5. API contract (chốt sau PR-1 — PR-5 & PR-6 build theo)

> Lấy từ `SMS_MARKETING_MODULE_DESIGN.md` §10 + §19. Liệt kê đủ để Codex (public) + Claude (FE) build với mock TRƯỚC khi service land. **Sửa contract → báo §9 + ping bên kia.**

**Admin** (`/api/sms`, `RequireAdmin`): contact-groups CRUD + upload · contacts CRUD + consent events · campaigns CRUD + groups + `build` + `preflight` + revision attestations + `export` + `exports/{id}/download` + `mark-handed-off` + `dashboard` · reports.
**Public**:
- `GET /r/{code}` → 302 (click + bot filter) — §6.1.
- `GET /api/public/sms/landing/{code}` → **read-only, no-store, noindex, no-referrer**; resp không có PII recipient.
- `POST /api/public/sms/opt-out {code}` → idempotent, `source='landing_optout'` (§19.3).

**Hợp đồng dữ liệu then chốt** (để mock đúng):
- `code` = base62×9; DB lưu HMAC hash để lookup + Fernet ciphertext để re-export; raw code không nằm trong message snapshot/log.
- Click: IP dùng secret riêng; CTR chính = distinct non-bot / recipient đã `handed_off`.
- Preflight: fail-closed consent/suppression, đo tin cuối gồm `[QC]` + hướng dẫn từ chối SMS/điện thoại + optional landing link.

---

## 6. Luật QLTS BẮT BUỘC (đóng gói cho Codex — đọc kỹ)

> Codex không có context repo. Đây là rút gọn `CLAUDE.md` + `Backend_FastAPI/CLAUDE.md` + bài học đã tích lũy. **Vi phạm = kiến trúc sai / CI đỏ.** Đầy đủ: đọc 2 file CLAUDE.md đó.

### 6.1 Kiến trúc layer (V3.0)
- **Router** = dumb: chỉ input/output, gọi service, **`await db.commit()`**. KHÔNG `if/else` nghiệp vụ, KHÔNG `db.execute`.
- **deps.py** = mọi Auth/RBAC/IDOR. IDOR fail → **404 (không 403)**, dùng `get_[resource]_for_user`.
- **Service** = pure Python: **KHÔNG import fastapi** (no Request/Response/HTTPException). Raise **DomainException** (`ResourceNotFoundError`→404, `DuplicateResourceError`→409, `BusinessRuleViolation`→400…). Chỉ **`flush`**, KHÔNG commit. Trả `(result, post_commit_callback)` nếu có side-effect.
- **Repository** = data access (SQLAlchemy 2.0 `Mapped[]`). `selectinload` chống N+1.

### 6.2 SMS module KHÔNG qua notification dispatch
SMS marketing là export quảng cáo, không dùng `dispatch()`/`SystemEvents`/`notification_rule`. Marketing consent/suppression giữ riêng với `NotificationConsent` giao dịch; không tự grant/revoke chéo.

### 6.3 Migration (PR-1 — chí mạng)
- **VIẾT TAY** trong migration: partial UNIQUE `token_hash`; UNIQUE `(campaign_id, build_revision, phone_normalized_snapshot)`; GIN `group_ids_snapshot`; UNIQUE batch `(campaign_id, build_revision, carrier_bucket)`; CHECK status/range. Report group dùng `@>` để tận dụng GIN, không dùng `= ANY(...)`.
- `Mapped[]` SQLAlchemy 2.0 — **đọc model mẫu thật** `app/models/finance/` để match style + import `Base`. KHÔNG tự chế.
- Casbin INSERT (nếu có, PR-7) ptype='p' **phải có v3(eft)** — NULL → load_policy crash 500 (memory `casbin-insert-must-include-eft`).
- revision id ≤32 ký tự (vd `sms20260611_create`/`sms20260611_seed`).

### 6.4 Test
- Backend heavy/destructive → **one-off container** (`docker compose run --rm --no-deps backend`), KHÔNG `exec` lên live (contaminates `qlts_test`). Install `requirements-dev.txt` trước. `qlts_test` dùng `create_all()` không alembic.
- Anchor test PR-2: bất biến import count (`row=valid+invalid+dup`; `added+existing=valid`) — §4.4 design.
- FE: `scripts/fe-check.sh type-check|test|lint|build` (run `--rm`, KHÔNG exec — OOM kill dev). **Chạy LINT** không chỉ type-check (CI fail eslint, bài học PR #399).

### 6.5 Gates (KHÔNG agent nào tự vượt)
- **Push-approval per-PR**: commit ≠ push. **Chờ user duyệt diff trước mỗi push & merge** (memory `push-approval-required`, `review-gate-before-push-merge`). User là solo dev — KHÔNG đề xuất reviewer/Slack.
- **flake8** file đã sửa TRƯỚC khi trình review (net-zero E501 mới; file mới phải 0 lỗi).
- **FE PR**: Chrome MCP smoke local TRƯỚC push (memory `chrome-mcp-pre-push-smoke`).
- CI = 5-check; docs/script-only PR có thể không trigger BE/FE check (path-filter) — file này là docs, đừng tách PR docs riêng kỳ vọng CI xanh.

### 6.6 Tái dùng (đừng xây lại)
`app/utils/phone_helpers.py` (normalize/to_zalo; phải bổ sung mobile-only check vì helper chấp nhận landline) · Redis rate-limit pattern · existing Fernet pattern · openpyxl · `/api/public/` CSRF-exempt · `RequireAdmin` · Celery cleanup.

---

## 7. Bảng phân công PR chi tiết

> Mỗi PR khi BẮT ĐẦU: owner đổi status §9 → `🔨 đang code`. Xong → `👀 chờ review` → reviewer review → `✅ chờ user push` → merge → `🟢 merged`.

| PR | Owner | Reviewer | Nội dung (design §) | Checklist DONE |
|---|---|---|---|---|
| **PR-1 Schema** | Claude | Codex | 12 model v4 + create/seed migrations + register/wire | hash+cipher token ✓ · consent ledger ✓ · revision indexes/CHECK/GIN ✓ · migration roundtrip ✓ |
| **PR-2 Contact** | Codex | Claude | CRUD/import mobile-only + consent evidence + append-only ledger | invariant counts ✓ · no implicit consent ✓ · row-lock projection ✓ |
| **PR-3 Build** | Claude | Codex | revisioned snapshot, fail-closed consent/suppression, HMAC+Fernet token, skeleton, `[QC]`, opt-out instruction, preflight | no raw token persisted/logged ✓ · invalidate old pre-handoff revision ✓ · no rebuild after handoff ✓ |
| **PR-4 Export** | Codex | Claude | idempotent batch, atomic private file, revision gates, mark-handed-off, cleanup | re-check consent/suppression ✓ · retry stable ✓ · private volume ✓ |
| **PR-5 Tracking/Landing/Reports** | Codex | Claude | hardened public routes, supplementary opt-out, handed-off reports, sanitized Nginx/app logs | no raw code logs/referrer ✓ · unknown-token rate limit ✓ |
| **PR-6 FE** | Claude | Codex | consent proof UI, 3 attestation gates, batch lifecycle, landing | không hiển thị sent/delivered ✓ · Chrome smoke/ESLint ✓ |
| **PR-7 Segment+Conversion** | Claude | Codex | migration riêng cho smart segment/holdout nếu được user duyệt | không sửa ngược schema core ✓ · privacy review ✓ |

---

## 8. Review checklist chéo (reviewer chạy TRƯỚC khi OK merge)

**Mọi PR**: layer đúng (§6.1)? Service không import fastapi? Router commit/Service flush? IDOR 404? flake8 sạch? Test pass (one-off container)? Không đụng file ngoài ranh giới (§3)?

**Theo PR (điểm chí mạng cần soi)**:
- **PR-1**: 12 model? CHECK/index đúng? token ciphertext/key version? consent ledger append-only? no smart/holdout field?
- **PR-2**: mobile-only? re-import không ghi đè identity? consent thiếu proof giữ unknown? grant/revoke atomic?
- **PR-3**: skeleton không chứa raw code? HMAC/Fernet secret tách biệt? `[QC]` + SMS/phone instruction? revision invalidation?
- **PR-4**: idempotency? atomic rename/recovery? private persistent volume? re-check suppression ngay trước batch? handed-off semantics?
- **PR-5**: Nginx/app không log raw code? no-referrer/no-store/noindex? IP secret riêng? CTR denominator handed-off?
- **PR-6**: Chrome smoke thật (không chỉ compile)? ESLint (không chỉ tsc)? preflight counter khớp BE? mobile §19? mutation invalidate detail key?
- **PR-7**: Casbin officer policy có eft? smart query không full-scan lead? attribution window-join đúng (14-30d)?

---

## 9. Trạng thái + nhật ký phối hợp (CẬP NHẬT LIÊN TỤC)

**Trạng thái PR** (🔲 chưa bắt đầu · 🔨 đang code · 👀 chờ review · ✅ chờ user push · 🟢 merged):

| PR | Owner | Status | Branch | Ghi chú |
|---|---|---|---|---|
| PR-1 Schema | Claude | ✅ review R1–R3 xong, chờ user push | `sms/pr1-schema` | 075c8292+83fe00ca+a8d045ed+13634b46; 7/7 pytest + alembic check sạch + flake8 sạch |
| PR-2 Contact | Codex | 🔲 | `sms/pr2-contact` | chờ PR-1 merge |
| PR-3 Build | Claude | 🔲 | `sms/pr3-build` | chờ PR-2 merge |
| PR-4 Export | Codex | 🔲 | `sms/pr4-export` | chờ PR-3 merge |
| PR-5 Tracking/Landing | Codex | 🔲 | `sms/pr5-tracking` | public-surface // PR-2/3 sau PR-1 |
| PR-6 FE | Claude | 🔲 | `sms/pr6-fe` | scaffolding theo §5 sớm |
| PR-7 Segment+Conv | Claude | 🔲 | `sms/pr7-segment` | sau PR-5 |

**Mục "cần phối hợp"** (ghi vào đây khi cần đụng shared file / đổi contract / phát hiện schema thiếu):
- L1 consent source/proof/disclosure owner.
- L2 DNC mechanism/reference/freshness.
- L3 SMS/phone opt-out channel + SLA sync.
- L4 impact assessment, secrets/key-ring, private storage/log redaction.

**Nhật ký**:
- 2026-06-11 — Tạo file điều phối. Chốt: Codex CLI local, song song + review chéo, phân vai theo bảng. Chưa bootstrap worktree.
- 2026-06-11 — Hard review v4: BLOCK code; sửa token persistence, consent ledger, opt-out legal channel, DNC revision gate, export lifecycle, log leakage, 12-model core.
- 2026-06-11 — User AUTHORIZE GO (đủ evidence L1–L4). Workflow đổi: **Claude code all, Codex review all**.
- 2026-06-11 — PR-1 schema code xong (12 model + migration + regression test) + Codex review **R1** (consent CASCADE→SET NULL, seed bỏ MVNO 055/087), **R2** (5 CHECK/FK invariant: granted-proof, token-triplet, import group SET NULL, count invariant, comment parity), **R3** (empty-string `coalesce`/`btrim`, ledger `revoke_source`, click_event bỏ denorm campaign/contact, regression test 7/7, fix 3 lỗ three-valued-logic). Branch `sms/pr1-schema`, CHƯA push.
- 2026-06-11 — ⚠ Lưu ý: branch có commit lạ `81c3d5b0 fix(officer)` xen giữa R2/R3 (không thuộc SMS) — cần user xử lý trước khi squash-merge.

---

## 10. Bước tiếp theo
1. ✅ User/chủ dự án đã chốt L1-L4 (attest đủ evidence) 2026-06-11; reference điền vào proof_reference/source_reference/attestation khi build campaign.
2. User phát lệnh GO rõ ràng cho PR-1.
3. Sau GO mới bootstrap worktree/branch và xác nhận production config: token hash/encryption key-ring, IP hash secret, redirect allowlist, frequency cap, opt-out instruction, private storage.
4. Triển khai theo dependency graph; không mở PR-7 schema trước khi core ổn định.

> L1-L4 đã được user attest (GO 2026-06-11) → code tiến hành. Push/merge vẫn cần approval per-lần; compliance evidence phải có thật khi build campaign.
