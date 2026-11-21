# app/services/admission_review_run_service.py
"""GĐ2-B — chạy "Kiểm hồ sơ" (run ``evaluate``) của MỘT lần xét nháp. **KHUNG (L2, đợt 1)** — thân do L3b (đợt 2) điền.

Luật thuần nằm ở ``app/services/admission_review_rules.py`` (L2); module này chỉ ĐỌC (một ảnh chụp, theo lô) và GHI (run + dòng).
Đặc tả GĐ2-B bản 4 §9.1 (cách chạy đồng bộ, API dạng "việc"), §6.8 (thứ tự khoá), §7.1 (bộ đếm); hợp đồng API bản 4 E6 (thứ tự
lỗi), §3.3 (``RunOut`` / ``RunInputs`` / ``RunSummary`` / ``QuotaView``), §6 (đồng thời), §7 (bất biến). Biên bản K1–K4 21-11:
K1 (đếm câu SQL của TOÀN BỘ run, kể cả bước tính lại KV F231 — nạp theo lô rồi dùng lại quy tắc tính), K2 (khoản HK1 = khoản
``tuition`` HK1 chưa huỷ có ``id`` lớn nhất — DÙNG LẠI ĐÚNG mệnh đề CTE ``hoc_phi`` của ``council_candidate_repository``).

Dịch vụ thuần: không import FastAPI; ném lỗi miền (``admission_review_errors`` — L1); router commit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Tuple

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


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
    ``evaluate_cascade``, ``publish_result``, ``freeze_priority_snapshot``, ``transition``, ``_assert_quota_or_bypass`` (test AST)."""
    raise NotImplementedError("GĐ2-B L3b (đợt 2) điền thân run_evaluate — L2 chỉ dựng khung.")
