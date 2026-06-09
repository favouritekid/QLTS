# Runbook deploy: sts20 CONSULT_GIVEUP (2-step rollout)

> Branch: `feat/sts20-consult-giveup`. Mục tiêu: deploy **không phá hủy** — seed
> status + transitions để đóng tay hoạt động ngay, nhưng **KHÔNG** auto-đóng lead
> nào cho tới khi chủ động bật (sau khi workflow mở lại lead sẵn sàng / đã quan
> sát đủ). Khớp quyết định "phương án 1" (2026-06-09).

## Nguyên tắc an toàn

- Migration `sts20_consult_giveup_20260609` **chỉ seed** status + 2 transition —
  **không** backfill. Deploy migration là an toàn, đảo được.
- Beat `auto_close_stale_rejected_leads_task` **early-return** khi
  `SLA_AUTO_GIVEUP_ENABLED=false` (mặc định). Schedule vẫn đăng ký (03:30) nhưng
  không làm gì.
- Đóng lead cũ = bước **thủ công, có dryrun**: `scripts/backfill_sts20_giveup.py`.
- Đóng tay (manager/admin chọn "Đã ngừng tư vấn") **không** bị gate — hoạt động
  ngay sau migration.

## Bước 0 — Backup + tập dượt trên dev (BẮT BUỘC trước prod)

1. **Backup prod** (read-only, cần approval SSH — `reference: ssh-prod-access`):
   ```
   pg_dump -Fc <prod_db> > sts20_predeploy_$(date +%Y%m%d).dump
   ```
2. **Import vào dev** (cold cutover style — `solo-cutover-simple-data-import`):
   restore dump vào `qlts_dev`.
3. **Tập dượt trên dev**:
   - `docker compose exec backend alembic upgrade head`
     → log phải in `consultation_status + 2 transitions seeded. Backfill ...
       INTENTIONALLY NOT run`.
   - Verify: `consultation_status` có sts20; 2 transition `sts04->sts20`; **0**
     lead `consultation_status_id='sts20'`; lead sts04 giữ nguyên (chưa đóng).
   - **Đóng tay**: login manager/admin → 1 lead sts04 → "Đã ngừng tư vấn" + lý do
     → lead thành sts20 (smoke đã verify trên dev 2026-06-09).
   - **Dryrun backfill**: `python scripts/backfill_sts20_giveup.py` → in số lead
     sẽ đóng (KHÔNG đóng). Đối chiếu kỳ vọng (~prod count).
   - (tuỳ chọn) `--apply` trên dev để tập dượt đóng + verify beat khi bật.
   - **Rollback thử**: `alembic downgrade -1` → mọi lead sts20 về sts04, status
     removed (in WARNING destructive). `alembic upgrade head` lại.
4. Chỉ deploy prod khi **mọi thứ trên dev ổn**.

## Bước 1 — Deploy prod (an toàn, không auto-đóng)

1. Env prod: **để** `SLA_AUTO_GIVEUP_ENABLED=false` (mặc định — hoặc không set).
   Tuỳ chọn đặt `SLA_CONSULT_GIVEUP_DAYS` (mặc định 30).
2. Deploy backend image mới (`deploy-mechanics-canonical`). Entrypoint chạy
   `alembic upgrade head` → seed status + transitions. **Không lead nào bị đóng.**
3. Smoke prod (read-only + 1 thao tác đóng tay nếu muốn): route mới load,
   `/health` 200, manager đóng tay 1 lead test (nếu có) hoạt động.
4. Beat/worker khởi động lại → task `auto_close_stale_rejected_leads_task` đã đăng
   ký nhưng **disabled** (log "SLA auto-giveup disabled ... skipping" mỗi 03:30).

→ Tại đây: tính năng "đóng tay" sống; **tự động chưa kích hoạt**. Reopen workflow
có thể phát triển song song.

## Bước 2 — Bật tự động (khi reopen sẵn sàng / đã quan sát đủ)

1. **Chạy backfill 1 lần** (đóng lead cũ tồn đọng), có dryrun trước:
   ```
   docker compose exec backend python scripts/backfill_sts20_giveup.py          # dryrun
   docker compose exec backend python scripts/backfill_sts20_giveup.py --apply  # gõ "yes"
   ```
   In `history rows=N, leads moved sts04->sts20=N`. Idempotent (chạy lại = 0).
2. **Bật beat**: set env `SLA_AUTO_GIVEUP_ENABLED=true` → restart `celery-beat` +
   `celery-worker`. Từ 03:30 hôm sau, beat đóng lead sts04 mới tồn ≥ ngưỡng.
3. Verify: query prod `consultation_status_id='sts20'` count tăng đúng; workload
   officer (vd Hiệu id=16) tụt dưới 0.8.

## Rollback

- **Trước khi bật tự động**: gỡ migration `alembic downgrade -1` an toàn (chưa lead
  nào sts20 trừ đóng tay; downgrade revert hết về sts04 + xóa history sts20).
- **Sau khi đã backfill/bật beat**: downgrade vẫn chạy nhưng **DESTRUCTIVE** — đẩy
  TẤT CẢ lead sts20 (gồm beat-moved) về sts04 + xóa audit sts20. Cân nhắc; ưu tiên
  tắt flag (`SLA_AUTO_GIVEUP_ENABLED=false`) + ngừng backfill thay vì downgrade.

## Ghi chú

- Migration `_giveup_days`/env: script backfill đọc `settings.SLA_CONSULT_GIVEUP_DAYS`
  (cùng nguồn beat) — giữ env nhất quán giữa lần chạy script và cấu hình beat.
- Lead sts20 = terminal: chưa có đường mở lại tới khi ship
  `Documents/LEAD_REOPEN_WORKFLOW_PLAN.md`. Vì vậy backfill + bật beat nên SAU khi
  reopen lên (hoặc chấp nhận tường minh).
- Quy mô: predicate backfill/beat seq-scan trên `lead` (~vài chục–trăm row hiện
  tại). Nếu bảng lead lớn về sau, cân nhắc partial index
  `(consultation_status_id, last_consultation_at) WHERE deleted_at IS NULL`.
