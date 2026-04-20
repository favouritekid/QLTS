# PR6 Merge / Deploy Checklist

**Scope**: V2 tech-debt PR6 — per-subject weighted scoring, 3 steps.
**Shipped commits** (origin/main, deployed):

```
42c30f40 fix: filter ScoreSnapshot to backend-selected subjects (Step 3 follow-up)
c98e8136 feat: weighted-scoring breakdown in ScoreSnapshot (Step 3 FE)
a521f3d0 fix: wire subject_weights into snapshot + runtime guard (Step 2 follow-up)
26063004 feat: weighted scoring formula (Step 2)
2523f1ec fix: mirror top-level subject_weights (Step 1 follow-up)
02dbf98a feat: per-subject weight contract (Step 1 BE + Zod)
```

---

## 1. Pre-merge gates (must be green)

### Backend

- [ ] `docker compose exec backend alembic heads` → `pr6a_subject_weight (head)`
- [ ] `docker compose exec backend python -m py_compile app/services/admission_service.py app/services/admission_scoring_service.py app/routers/admission_config.py`
- [ ] `docker compose exec backend python -m pytest tests/unit/services/test_pr6_subject_weights.py tests/unit/services/test_pr6_weighted_scoring.py -q` → **24 passed**
- [ ] Wider regression: `docker compose exec backend python -m pytest tests/api/test_admission_workflow_api.py -q` → **13 passed**

### Frontend

- [ ] `docker compose exec frontend npx vitest run "src/lib/zod/admissions.test.ts"` → **6 passed**
- [ ] `docker compose exec frontend npx vitest run "src/app/(dashboard)/admissions/[id]/_components/tabs/executive-summary/ScoreSnapshot.test.tsx"` → **8 passed**
- [ ] `docker compose exec frontend npm run type-check`
- [ ] `docker compose exec frontend npm run lint -- --quiet`
- [ ] `docker compose exec frontend sh -lc "cd /app && npx next build --webpack"`

### Git hygiene

- [ ] Untracked files không vào commit:
  - `2026-04-18-150058-ssh-sn-sng.txt`
  - `Documents/CONFIRMED_STATE_AUDIT_2026-04-18.md`
  - `Documents/PR6_MERGE_CHECKLIST.md` (doc này, OK commit riêng nếu muốn)
  - `qa_org_selector_verified.png`
  - `test-results/`

---

## 2. Post-deploy prod smoke

### Seed test data (prod DB)

1. Pick 1 `admission_method` test. Ví dụ `method_id=1` (`hoc_ba`).
2. Set weights trên subject group của criteria đó qua SQL (cần authorize):
   ```sql
   -- Ví dụ group A00 của method hoc_ba, Toán x2, Lý x1, Hóa x1
   UPDATE subject_group_subject
   SET weight = 2.0
   WHERE subject_group_id = <A00_ID>
     AND subject_id = (SELECT id FROM subject WHERE code = 'math');
   ```
3. Set `admission_criteria.scoring_method = 'weighted'` cho criteria liên quan.
4. Tạo 1 admission profile mới (qua UI hoặc SQL nếu không ảnh hưởng flow ops) trên path này. Nhớ profile phải có subject scores đủ.
5. Approve profile → trigger re-score path.

### Verify trên browser prod

- [ ] Mở profile detail → Executive Summary → `Snapshot Điểm Chuẩn`
- [ ] Thấy **5 cột**: `Môn học | Điểm | Hệ số | Điểm sau nhân | Trạng thái`
- [ ] Từng hàng `score × weight` khớp (ví dụ 8 × 2 = 16.00)
- [ ] `Tổng điểm` = giá trị BE return trong `profile.total_score`, KHÔNG phải FE tự cộng
- [ ] Note `(đã áp hệ số)` bên cạnh "Tổng điểm"
- [ ] Footer: `Phương thức: tính theo hệ số`

### Best_n mode smoke

- [ ] Profile có 4 môn submitted, `best_n` required_count=3
- [ ] Breakdown **chỉ hiện 3 môn** backend đã chọn
- [ ] Môn bị bỏ không xuất hiện
- [ ] `Tổng điểm` khớp với `snapshot_score.selected_subjects`

### Backward-compat smoke

- [ ] 1 profile `scoring_method=sum` — layout **3 cột** cũ, không có weight columns
- [ ] 1 profile `scoring_method=average` — layout **3 cột** cũ
- [ ] Snapshot pre-migration (nếu có) — không crash, degrade về 3-col

### GPA-only

- [ ] Profile `method_type=gpa_only` vẫn hiển thị message "chỉ xét học bạ (GPA)", không có table

---

## 3. Rollback plan

**Risk**: thấp — Step 3 FE-only, backend đã verified Step 2; migration `pr6a_subject_weight` idempotent (CHECK + DEFAULT 1.0, backward-compatible).

Nếu UI hiển thị sai totals trên 1 profile cụ thể:
- Revert commit `42c30f40` + `c98e8136` (2 commits FE) → layout về 3-col, không touch BE.
- Deploy lại.
- Backend vẫn tính weighted correctly — chỉ UI breakdown disappear.

Nếu BE tính sai:
- Revert `26063004` + `a521f3d0` (2 BE commits). Plus PR6 FE commits để không reference missing fields.
- Migration `pr6a_subject_weight` KHÔNG cần downgrade (cột `weight` default 1.0 ẩn hoàn toàn với scoring_method sum/average).

---

## 4. Known non-issues (đã document, không phải regression)

- `next build` warnings từ Prisma / OpenTelemetry import trace — tồn tại trước PR6, không blocker.
- `TestRaceCondition` 2/2 fail — harness artifact, closed 2026-04-17 (memory `admission-race-condition-investigation`).
- Local env dùng Resend sandbox — prod dùng Gmail SMTP; email test sẽ không work trên local profile mới.

---

## 5. Deferred items (không block merge)

Theo memory `pr6-weighted-scoring-unblock` step "Next up":

- Cho đến khi ops confirm weights config usable, chưa cần weight-editor UI cho admin (hiện weights chỉ set qua SQL / seed). Nếu cần, mở issue riêng.
- Migration siết `subject_group_subject.weight` range (hiện CHECK `weight > 0`, chưa có upper bound) — defer nếu không có use case yêu cầu.
- `subject_group_mappings` relationship order — reviewer Step 2 flag residual risk nếu duplicate subject codes cross groups trở thành pattern chính thức. Chưa có use case, giữ "last wins" + document.

---

**Sign-off**

Shipped: 2026-04-19
V2 tech-debt plan: 11/11 PRs ✅ CLOSED (PR6 unblocked and completed).
