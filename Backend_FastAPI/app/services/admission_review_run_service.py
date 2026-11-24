# app/services/admission_review_run_service.py
"""GĐ2-B — chạy "Kiểm hồ sơ" (run ``evaluate``) của MỘT lần xét nháp. Khung L2 (đợt 1); thân L3b (đợt 2 — bộ nạp theo lô).

Luật thuần nằm ở ``app/services/admission_review_rules.py`` (L2); module này chỉ ĐỌC (một ảnh chụp, theo lô) và GHI (run + dòng).
Đặc tả GĐ2-B bản 4 §9.1 (cách chạy đồng bộ, API dạng "việc"), §6.8 (thứ tự khoá), §7.1 (bộ đếm); hợp đồng API bản 4 E6 (thứ tự
lỗi), §3.3 (``RunOut`` / ``RunInputs`` / ``RunSummary`` / ``QuotaView``), §6 (đồng thời), §7 (bất biến). Biên bản K1–K4 21-11:
K1 (đếm câu SQL của TOÀN BỘ run, kể cả bước tính lại KV F231 — nạp theo lô rồi dùng lại quy tắc tính), K2 (khoản HK1 = khoản
``tuition`` HK1 chưa huỷ có ``id`` lớn nhất — DÙNG LẠI ĐÚNG mệnh đề CTE ``hoc_phi`` của ``council_candidate_repository``).

Dịch vụ thuần: không import FastAPI; ném lỗi miền (``admission_review_errors`` — L1); router commit.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Tuple

import structlog
from sqlalchemy import text

from app.config import settings
from app.core.advisory_lock_keys import REVIEW_RUN_NS
from app.models.admission_review import (
    REVIEW_RUN_DONE,
    REVIEW_RUN_KIND_EVALUATE,
    REVIEW_RUN_RUNNING,
)
from app.repositories import admission_review_load_repository as load_repo
from app.repositories import admission_review_repository as review_repo
from app.repositories.council_candidate_repository import read_only_transaction
from app.services import admission_review_errors as errors
from app.services import admission_review_loader as loader
from app.services import admission_review_rules as rules
from app.services import fee_gate_rules
from app.services.admission_review_service import ACTION_RUN_EVALUATE, require_session_action

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

log = structlog.get_logger(__name__)

#: Vết ``entity_audit_log`` của một run (chỉ id + số đếm + mã — không họ tên / CCCD; đặc tả §8).
AUDIT_ENTITY = "admission_review_run"
AUDIT_ACTION_DONE = "evaluate_done"
SQL_TRY_RUN_LOCK = text("SELECT pg_try_advisory_xact_lock(CAST(:ns AS integer), CAST(:k AS integer))")


async def run_evaluate(
    db: "AsyncSession",
    *,
    engine: "AsyncEngine",
    session_id: int,
    session_version: int,
    actor_user_id: int,
) -> Tuple[Any, Optional[Callable[[], Awaitable[None]]]]:
    """Chạy kiểm hồ sơ cho lần xét ``session_id`` (GĐ2-B: đồng bộ; API trả 202 kèm run ``done``). Trả ``(run, callback sau commit)``.

    Trình tự (đặc tả §9.1; mọi lỗi ⇒ KHÔNG có run, KHÔNG có dòng):

    1. **Giao dịch chính** (``db``): ``pg_try_advisory_xact_lock`` theo lần xét (vùng khoá mới ở ``core/advisory_lock_keys.py``) —
       bận ⇒ 409 ``REVIEW_RUN_IN_PROGRESS``; đọc lần xét: không có ⇒ 404; không ``draft`` ⇒ 409 ``REVIEW_SESSION_NOT_DRAFT``;
       ``version`` lệch ⇒ 409 ``REVIEW_SESSION_STALE``; chế độ cổng học phí: ``fee_gate_rules.require_fee_gate_mode`` —
       ``FeeGateModeInvalid`` ⇒ 503 ``admission_review_errors.fee_gate_mode_invalid()``; loại giấy
       ``admission_review_rules.RESIDENCE_PROOF_DOC_CODE`` không có trong ``config_document_type`` ⇒ 503
       ``residence_proof_doc_type_missing``. KHÔNG lấy khoá năm (§6.8).
    2. **MỘT ảnh chụp** ``REPEATABLE READ READ ONLY`` trên kết nối RIÊNG của ``engine`` (khuôn
       ``council_candidate_repository.read_only_transaction``): lần xét + điểm sàn (kiểm lại ``version``), bảng chỉ tiêu + dấu,
       bộ đếm theo từng học vụ cho CẢ NĂM một câu (``quota_occupancy_service`` — hàm mới) + ``count_by_group``, hồ sơ năm Y
       (gồm ``applied_rules`` nguyên), nguyện vọng, điểm môn theo tổ hợp NV (hàm đọc chung với bản in), giấy thường, phí (K2),
       KV F231 (``_resolve_area`` — theo lô, K1), luật cộng điểm đường xét (``_score_add_rules``), KV xã theo năm lần xét (bản theo
       lô của ``_lookup_commune_kv``), minh chứng diện ưu tiên đã duyệt, mức đối tượng đang mở của năm, hồ sơ cùng CCCD năm < Y
       (cờ A13), dòng ``auto`` của run ``done`` mới nhất của mỗi lần xét nháp KHÁC cùng năm (cờ A19). Mọi câu đọc theo LÔ —
       số câu SQL không tăng theo số hồ sơ (BT35).
    3. **Tính** bằng hàm thuần: dựng ``admission_review_rules.ProfileFacts`` / ``ChoiceFacts`` (``choice_check``,
       ``choice_gate_facts``) / ``RunFacts`` rồi ``evaluate_run`` ⇒ dòng + ``quota_view`` + ``summary``. ``PriorityRateNotConfigured``
       nổi lên ⇒ 503 (gộp mọi mã thiếu nếu muốn); ``ReviewInputError`` ⇒ 500 (dữ kiện tự mâu thuẫn — lỗi của lượt đọc).
    4. **Giao dịch chính**: dòng lần xét ``FOR UPDATE`` (ngắn), KIỂM LẠI còn ``draft`` (huỷ chen giữa ⇒ 409, không ghi gì); chèn run
       ``running`` (``rule_version = admission_review_rules.RULE_VERSION``; ``inputs`` = năm, ``session_version``,
       ``floors_snapshot(...)``, bảng chỉ tiêu, ``fee_gate_mode``, ``snapshot_at``) → chèn mọi dòng một câu
       (``ReviewRow.column_values()``) → ``done`` (``summary``, ``quota_view``, thời lượng 3 phần); vết ``entity_audit_log`` (chỉ id +
       số đếm + mã — không họ tên / CCCD). Router commit.

    KHÔNG đổi hồ sơ / nguyện vọng / giấy / phí; KHÔNG giữ chỗ; KHÔNG khoá dòng chỉ tiêu / học vụ / hồ sơ; KHÔNG gọi
    ``evaluate_cascade``, ``publish_result``, ``freeze_priority_snapshot``, ``transition``, ``_assert_quota_or_bypass`` (test AST).

    Đợt 2 (L3b): bước 2 là :func:`admission_review_loader.load_run_facts` (hợp đồng bộ nạp — số câu cố định); ghi dòng là MỘT câu
    nhiều dòng (``admission_review_repository.insert_rows``). Thời lượng ba phần (đọc / tính / ghi) đi vào log (chỉ id + số), cột
    ``duration_ms`` là tổng; hợp đồng API bản 4 chưa có chỗ cho ba phần (câu hỏi bàn giao)."""
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    # 1. Giao dịch chính: khoá thử theo lần xét → lần xét → chế độ học phí → loại giấy cư trú.
    if not (await db.execute(SQL_TRY_RUN_LOCK, {"ns": REVIEW_RUN_NS, "k": int(session_id)})).scalar_one():
        raise errors.review_run_in_progress()
    session = await review_repo.get_session(db, session_id)
    if session is None:
        raise errors.review_session_not_found()
    require_session_action(session.status, ACTION_RUN_EVALUATE)  # MỘT cổng với ``available_actions`` (hợp đồng §3.1)
    if int(session.version) != int(session_version):
        raise errors.review_session_stale(int(session.version))
    try:
        fee_gate_mode = fee_gate_rules.require_fee_gate_mode(settings.ADMISSION_FEE_GATE_MODE)
    except fee_gate_rules.FeeGateModeInvalid:
        raise errors.fee_gate_mode_invalid() from None
    if not await load_repo.document_type_exists(db, rules.RESIDENCE_PROOF_DOC_CODE):
        raise errors.residence_proof_doc_type_missing()

    # 2. MỘT ảnh chụp chỉ đọc trên kết nối riêng.
    async with read_only_transaction(engine) as (conn, snapshot):
        loaded = await loader.load_run_facts(
            conn, session_id=session_id, session_version=session_version, fee_gate_mode=fee_gate_mode
        )
    t_read = time.monotonic()

    # 3. Tính (thuần).
    evaluation = rules.evaluate_run(loaded.profiles, loaded.run)
    t_compute = time.monotonic()

    # 4. Giao dịch chính: khoá dòng lần xét, kiểm lại draft, ghi run + dòng + vết.
    locked = await review_repo.lock_session(db, session_id)
    if locked is None:
        raise errors.review_session_not_found()
    require_session_action(locked.status, ACTION_RUN_EVALUATE)  # huỷ chen giữa ⇒ 409, không ghi gì
    inputs = {
        "academic_year": loaded.academic_year,
        "session_version": loaded.session_version,
        "floors": rules.floors_snapshot(loaded.run.floors),
        "quota_table": loaded.quota_table,
        "fee_gate_mode": fee_gate_mode,
        "snapshot_at": snapshot.snapshot_at.isoformat(),
    }
    run = await review_repo.insert_run(
        db,
        session_id=session_id,
        kind=REVIEW_RUN_KIND_EVALUATE,
        status=REVIEW_RUN_RUNNING,
        rule_version=rules.RULE_VERSION,
        requested_by_user_id=actor_user_id,
        inputs=inputs,
        started_at=started_at,
    )
    await review_repo.insert_rows(db, run.id, [r.column_values() for r in evaluation.rows])
    finished_at = datetime.now(timezone.utc)
    duration_ms = max(int((finished_at - started_at).total_seconds() * 1000), 0)
    await review_repo.update_run(
        db,
        run.id,
        {
            "status": REVIEW_RUN_DONE,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "summary": evaluation.summary,
            "quota_view": evaluation.quota_view,
        },
    )
    from app.services.audit_service import log_audit

    await log_audit(
        db,
        AUDIT_ENTITY,
        run.id,
        AUDIT_ACTION_DONE,
        actor_user_id=actor_user_id,
        new_value={
            "session_id": int(session_id),
            "session_version": loaded.session_version,
            "rows_total": evaluation.summary["rows_total"],
            "tab_counts": evaluation.summary["tab_counts"],
            "rule_version": rules.RULE_VERSION,
        },
        source="api",
    )
    await db.refresh(run)
    t_write = time.monotonic()
    log.info(
        "admission_review_run_done",
        session_id=int(session_id),
        run_id=int(run.id),
        rows_total=evaluation.summary["rows_total"],
        read_ms=int((t_read - t0) * 1000),
        compute_ms=int((t_compute - t_read) * 1000),
        write_ms=int((t_write - t_compute) * 1000),
    )
    return run, None
