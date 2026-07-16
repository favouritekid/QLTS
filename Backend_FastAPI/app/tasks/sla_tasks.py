# app/tasks/sla_tasks.py
"""
Lead lifecycle SLA Celery tasks.

Auto-closes stale rejected consultations: a lead left in sts04
(CONSULT_REJECTED, is_final=false so it stays re-engageable) that has had no
consultation activity for SLA_CONSULT_GIVEUP_DAYS is transitioned to sts20
(CONSULT_GIVEUP, terminal is_final=true). Because sts04 counts as non-final
workload (assignment_service BƯỚC 3-4), letting rejections pile up inflates an
officer's utilization above SAFETY_THRESHOLD and the balancer skips them; moving
genuinely-dead rejections to sts20 frees that load so auto-assign resumes.

Audit trail is the LeadStatusHistory row that execute_system_transition writes
(changed_by_user_id=NULL). No SystemEvents/notification dispatch by design.
"""
import logging
from datetime import datetime, timedelta, timezone

from ..celery_app import celery_app
from ..config import settings
from .utils import task_db_session, run_async_task

_default_log = logging.getLogger(__name__)


def stale_sts04_predicate(stmt, cutoff: datetime):
    """NGUỒN SỰ THẬT DUY NHẤT của "lead sts04 đã stale" — beat + test dùng CHUNG.

    Module-level (không phải closure trong close_stale_rejected_leads) để test
    import được thay vì chép tay lại điều kiện: hai bản chép đã từng lệch khỏi
    production mà suite vẫn xanh.

    Mốc "còn sống" = hoạt động MUỘN NHẤT giữa:
      - consultation_reengaged_at: mốc re-engage THỦ CÔNG (reopen sts20→sts04)
        — không ai ghi đè, kể cả recalc cache nightly;
      - last_consultation_at: recency tư vấn, do update_lead_cache dẫn xuất từ
        MAX(consultation_date).

    GREATEST chứ KHÔNG phải COALESCE: COALESCE lấy giá trị non-null ĐẦU TIÊN,
    nên reengaged (cố định tại lúc reopen) sẽ luôn thắng last_consultation_at
    mới hơn → lead được reopen rồi tư vấn tích cực vẫn bị đóng sau đúng `days`
    kể từ ngày reopen. GREATEST bỏ qua NULL (Postgres):
      chưa reopen         -> GREATEST(NULL, last) = last  (hồi quy: y hệt cũ)
      reopen, chưa tư vấn -> GREATEST(reengaged, NULL) = reengaged
      reopen rồi tư vấn   -> mốc muộn hơn thắng

    ⚠️ Fallback updated_at/created_at CHỈ với lead CHƯA từng reopen. Khi
    consultation_reengaged_at non-NULL (write-once, không ai clear) thì GREATEST
    luôn non-NULL nên COALESCE dừng ngay và KHÔNG bao giờ đọc updated_at nữa —
    có chủ đích: sửa vu vơ một field của lead không phải "hoạt động tư vấn" nên
    không được gia hạn SLA. Khoá bởi test_reopened_lead_ignores_updated_at_bump.
    """
    from sqlalchemy import func
    from .. import models

    return stmt.where(
        models.Lead.consultation_status_id == "sts04",
        models.Lead.deleted_at.is_(None),
        func.coalesce(
            func.greatest(
                models.Lead.consultation_reengaged_at,
                models.Lead.last_consultation_at,
            ),
            models.Lead.updated_at,
            models.Lead.created_at,
        ) < cutoff,
    )


async def close_stale_rejected_leads(
    session,
    *,
    cutoff: datetime,
    days: int,
    batch_size: int = 100,
    log: logging.Logger = _default_log,
    reason_tag: str = "sla_auto_giveup",
) -> dict:
    """
    Core body of the daily SLA auto-close, extracted from the Celery wrapper so
    tests can drive it with their own AsyncSession. Also reused by the one-shot
    backfill script (scripts/backfill_sts20_giveup.py, reason_tag=
    "backfill_sla_auto_giveup") so backfill and beat share ONE code path —
    status is derived by sync_lead_status (no hardcoded 'rejected' duplicating
    derive_lead_status), and reason_tag keeps the two distinguishable in audit.

    Snapshots the ids of stale sts04 leads (strict predicate), then per batch
    re-applies the FULL predicate (a lead re-engaged / soft-deleted / moved off
    sts04 since the snapshot is dropped) and runs execute_system_transition to
    sts20. The FSM engine validates the system transition and enforces
    idempotency (RULE #13).

    Counters are commit-accurate: a batch's tallies are folded into the result
    only AFTER its commit succeeds. A commit failure is caught, the session is
    rolled back, the batch's would-be transitions are counted as errors (they did
    NOT persist — the leads stay sts04 and are retried on the next daily run),
    and the loop continues so one bad batch never aborts the whole task.
    Returns {checked, transitioned, skipped, errors} with the invariant
    checked == transitioned + skipped + errors.
    """
    from sqlalchemy import select
    from .. import models
    from ..services.fsm_engine import execute_system_transition

    result = {"checked": 0, "transitioned": 0, "skipped": 0, "errors": 0}

    def _stale_predicate(stmt):
        # Delegate: giữ shim này để 2 call site dưới khỏi phải truyền cutoff.
        # Logic THẬT ở module-level stale_sts04_predicate (test import trực tiếp).
        return stale_sts04_predicate(stmt, cutoff)

    ids_result = await session.execute(
        _stale_predicate(select(models.Lead.id)).order_by(models.Lead.id)
    )
    lead_ids = [row[0] for row in ids_result.all()]
    result["checked"] = len(lead_ids)

    if not lead_ids:
        log.info("No stale sts04 leads to auto-close (cutoff=%s)", cutoff)
        return result

    log.info(
        "Found %d stale sts04 leads (cutoff=%s, days=%d)",
        len(lead_ids), cutoff.isoformat(), days,
    )

    for i in range(0, len(lead_ids), batch_size):
        batch = lead_ids[i:i + batch_size]
        # FOR UPDATE SKIP LOCKED closes the TOCTOU race with a concurrent
        # re-engage: it (a) row-locks each matched lead until our commit so a
        # user can't slip a newer consultation/status in between this read and
        # the write, (b) re-reads fresh state so a lead re-engaged BEFORE this
        # select no longer matches the sts04 predicate and is dropped, and
        # (c) skips a lead currently locked by a user's add_consultation
        # (which also uses FOR UPDATE) rather than blocking — the daily run
        # leaves it for next time instead of overwriting live edits.
        leads = (await session.execute(
            _stale_predicate(
                select(models.Lead).where(models.Lead.id.in_(batch))
            ).with_for_update(skip_locked=True)
        )).scalars().all()

        # Per-batch tallies; only folded into result after commit succeeds.
        # Leads dropped by the re-check (touched/deleted/re-engaged/locked since
        # snapshot) have no DB write, so they stay 'skipped' even if a later
        # commit fails.
        b_transitioned = 0
        b_errors = 0
        b_skipped = len(batch) - len(leads)

        for lead in leads:
            try:
                moved = await execute_system_transition(
                    session, lead, "sts20", reason=f"{reason_tag}_{days}d",
                )
                if moved:
                    b_transitioned += 1
                    # Record a system Consultation so the auto-close is visible
                    # in "Lịch sử tư vấn" (the lead timeline lists consultations,
                    # not LeadStatusHistory). method='system' (Consultation.method
                    # is a free String — keeps real-call stats clean). Needs an
                    # officer (Consultation.officer_id is NOT NULL); unassigned
                    # leads fall back to history-only (LeadStatusHistory still set).
                    if lead.assigned_officer_id is not None:
                        session.add(models.Consultation(
                            lead_id=lead.id,
                            officer_id=lead.assigned_officer_id,
                            consultation_status_id="sts20",
                            method="system",
                            notes=(
                                f"Hệ thống tự đóng: lead tồn ≥{days} ngày "
                                "không phản hồi (Đã ngừng tư vấn)."
                            ),
                        ))
                else:
                    b_skipped += 1  # idempotent skip (already sts20 / has history)
            except Exception as e:
                b_errors += 1
                log.warning("Lead %s: auto-close failed: %s", lead.id, e)

        try:
            await session.commit()
        except Exception as e:
            # Commit failed: the only persistent writes were the transitions, so
            # roll back and reclassify them as errors. b_skipped (re-check drops +
            # idempotent skips) had no write and stays accurate.
            await session.rollback()
            log.error(
                "Batch commit failed (rolled back), %d transitions -> errors: %s",
                b_transitioned, e,
            )
            b_errors += b_transitioned
            b_transitioned = 0

        result["transitioned"] += b_transitioned
        result["skipped"] += b_skipped
        result["errors"] += b_errors
        log.info(
            "Progress: %d/%d (transitioned=%d, skipped=%d, errors=%d)",
            min(i + batch_size, len(lead_ids)), len(lead_ids),
            result["transitioned"], result["skipped"], result["errors"],
        )

    return result


# ============================================================================
# Auto-close stale rejected leads (Daily — 03:30, after lead cache 00:05)
# ============================================================================
@celery_app.task(
    name="auto_close_stale_rejected_leads_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300,
)
def auto_close_stale_rejected_leads_task(self):
    """
    Celery Beat daily task — auto-close sts04 leads stale >= SLA_CONSULT_GIVEUP_DAYS.

    Thin wrapper around close_stale_rejected_leads (which holds the testable
    logic). autoretry_for covers snapshot-query failures; per-batch commit
    failures are handled inside and do NOT trigger a full-task retry.
    Returns {checked, transitioned, skipped, errors}.
    """
    task_name = "auto_close_stale_rejected_leads_task"
    task_log = logging.getLogger(task_name)

    # 2-step rollout gate: schedule stays registered, but do nothing until the
    # operator flips SLA_AUTO_GIVEUP_ENABLED=true. Manual close is unaffected.
    if not settings.SLA_AUTO_GIVEUP_ENABLED:
        task_log.info(
            "SLA auto-giveup disabled (SLA_AUTO_GIVEUP_ENABLED=false) — skipping."
        )
        return {
            "checked": 0, "transitioned": 0, "skipped": 0, "errors": 0,
            "disabled": True,
        }

    task_log.info("Starting auto-close of stale rejected (sts04) leads...")

    async def _run() -> dict:
        days = settings.SLA_CONSULT_GIVEUP_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with task_db_session() as session:
            return await close_stale_rejected_leads(
                session, cutoff=cutoff, days=days, log=task_log,
            )

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["checked", "transitioned", "skipped", "errors"],
    )

    task_log.info(
        "Auto-close stale rejected leads completed: checked=%d, transitioned=%d, "
        "skipped=%d, errors=%d",
        result["checked"], result["transitioned"], result["skipped"], result["errors"],
    )
    return result
