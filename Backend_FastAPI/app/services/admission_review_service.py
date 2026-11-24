# app/services/admission_review_service.py
"""GĐ2-B đợt 2 (L3a) — dịch vụ GHI của lần xét nháp: tạo (E1), lưu điểm sàn (E4), huỷ (E5); và phần ĐỌC dựng phản hồi của E2, E3,
E7, E8, E9 (hợp đồng API GĐ2-B bản 4 ``b877fba1…``; đặc tả bản 4 ``6247a1a8…`` §5, §6.8; kế hoạch triển khai 21-11 §1 đợt 2; biên
bản K1–K4 21-11 — K3: kiểm vai ở ``deps`` TRƯỚC, 404 ở dịch vụ SAU kiểm dạng / trùng).

Chạy kiểm hồ sơ (E6) ở ``admission_review_run_service.run_evaluate`` (L3b) — cổng "lần xét còn chạy được" đi qua CÙNG
:func:`require_session_action` của module này.

THỨ TỰ KHOÁ (đặc tả §6.8; thứ tự toàn hệ ở ``app.core.review_year_lock``: ngành → loại hình → NĂM → DÒNG LẦN XÉT → học vụ → bảng):

* E1 tạo: khoá năm (độc quyền) → đọc đợt + bảng chỉ tiêu → ``seq_no`` lớn nhất + 1 → chèn. Hai lệnh tạo cùng năm nối tiếp nhau;
  UNIQUE(năm, ``seq_no``) là lớp cuối.
* E4 lưu sàn: đọc năm của lần xét (KHÔNG khoá — năm không bao giờ đổi, trigger) → khoá năm (CHIA SẺ — quyết định owner 23-11) →
  dòng lần xét ``FOR UPDATE`` → kiểm ``draft`` + ``version`` → đọc năm / cờ xoá của học vụ (DƯỚI khoá năm, không khoá dòng) → xoá +
  chèn sàn → ``version`` + 1. Cùng khoá năm mà ``PATCH`` dời năm học vụ lấy ĐỘC QUYỀN (năm cũ + mới, tăng dần —
  ``organization_service.update_academic_info``) ⇒ hai việc nối tiếp: bên đến sau nhận lỗi NGHIỆP VỤ (``review_floor_bad_member`` /
  ``ACADEMIC_INFO_IN_REVIEW_FLOOR``), không bao giờ lỗi CSDL (P3). Hai E4 cùng lần xét nối tiếp ở dòng lần xét (409 STALE).
* E5 huỷ: khoá năm (CHIA SẺ) → dòng lần xét ``FOR UPDATE`` → kiểm → XOÁ MỌI SÀN (lần xét còn ``draft`` — trigger cho phép) →
  chuyển ``cancelled`` — MỘT giao dịch (P4). Phải chạy ``read committed`` (mặc định của ứng dụng; trigger ``QLC04`` chặn mức khác).
  E4 / E5 chia sẻ ⇒ không chặn người đọc chia sẻ cùng năm (ghi nhận Quyết định, F230); E1 giữ độc quyền (cấp ``seq_no``).

Không khoá bảng tiền / hồ sơ khi giữ khoá năm. Dịch vụ thuần: không import FastAPI; ném lỗi miền (``admission_review_errors``); chỉ
``flush`` — router commit. Hàm ghi trả ``(kết quả, callback sau commit)`` (không có việc sau commit ⇒ ``None``). Log chỉ id + số đếm
+ mã — không họ tên, CCCD, lý do huỷ (lý do nằm trong vết ``entity_audit_log``).
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.review_year_lock import lock_review_year, lock_review_years_shared
from app.models.admission_review import REVIEW_RUN_DONE, REVIEW_SESSION_CANCELLED, REVIEW_SESSION_DRAFT, REVIEW_TABS
from app.repositories import admission_review_repository as review_repo
from app.services import admission_review_errors as errors
from app.services.admission_quota_table_service import read_quota_fingerprint
from app.services.admission_review_rules import format_score

log = structlog.get_logger(__name__)

#: Vết ``entity_audit_log`` của lần xét (``entity_id`` = id lần xét). Chỉ id + số + mã; lý do huỷ ở cột ``reason``.
AUDIT_ENTITY = "admission_review_session"
AUDIT_ACTION_CREATED = "created"
AUDIT_ACTION_FLOORS_REPLACED = "floors_replaced"
AUDIT_ACTION_CANCELLED = "cancelled"

# ── available_actions (hợp đồng §4.2) — MỘT nguồn cho cờ của phản hồi VÀ cổng ghi của E4 / E5 / E6 ──────────────────────
ACTION_EDIT_FLOORS = "edit_floors"
ACTION_RUN_EVALUATE = "run_evaluate"
ACTION_CANCEL = "cancel"


def session_actions(status: str) -> List[str]:
    """Thao tác làm được trên lần xét theo trạng thái: ``draft`` ⇒ sửa sàn + chạy kiểm + huỷ; ``cancelled`` (cuối) ⇒ không gì.
    MỘT nguồn (khuôn ``admission_quota_table_service.quota_table_actions``): cờ ``available_actions`` của ``SessionOut`` VÀ cổng
    :func:`require_session_action` của E4 / E5 / E6 — GĐ2-C thêm trạng thái (``locked``, ``signed``) thì thêm VÀO ĐÂY để nút và cổng
    đổi cùng nhau. Trạng thái lạ ⇒ rỗng (fail-closed)."""
    if status == REVIEW_SESSION_DRAFT:
        return [ACTION_EDIT_FLOORS, ACTION_RUN_EVALUATE, ACTION_CANCEL]
    return []


def require_session_action(status: str, action: str) -> None:
    """Cổng ghi: ``action`` không có trong :func:`session_actions` của ``status`` ⇒ 409 ``REVIEW_SESSION_NOT_DRAFT`` {``status``}."""
    if action not in session_actions(status):
        raise errors.review_session_not_draft(status)


def floor_member_accepted(academic_info: Any, academic_year: int) -> bool:
    """Vị từ thành viên điểm sàn của E4: học vụ (có hàng) ĐÚNG năm của lần xét VÀ chưa xoá mềm. Sai ⇒ học vụ vào
    ``review_floor_bad_member``. MỘT nguồn cho E4 (:func:`replace_floors`) và cờ ``floor_accepted`` của E10 (phụ lục HĐ4 E10 —
    "E4 nhận được"; đính chính thiết kế giao diện 24-11 §3). Đọc ``academic_year`` + ``is_deleted`` — có ở hàng của
    ``review_repo.read_academic_info_years`` lẫn ``admission_review_rules.AcademicInfoFacts``."""
    return int(academic_info.academic_year) == int(academic_year) and not academic_info.is_deleted


def round_accepts_new_session(admission_round: Any) -> bool:
    """E1 — đợt nhận lần xét mới ⇔ CHƯA lưu trữ (``archived_at`` trống). Đợt Ngừng (``is_active = false``) VẪN chọn được (owner G1
    24-11, ``QUYET-DINH-OWNER-GIAO-DIEN-GD2-B-CON-LAI-VA-THU-KY-2026-11-24.md`` §1; đính chính thiết kế giao diện §5 "G1 (c)")."""
    return admission_round.archived_at is None


# ── tiện ích ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _page(items: List[Dict[str, Any]], total: int, page: int, page_size: int) -> Dict[str, Any]:
    """Trang (hợp đồng §1.6): ``total_pages`` = trần(total / page_size); trang vượt cuối ⇒ ``items`` rỗng."""
    return {
        "items": items,
        "total": int(total),
        "page": int(page),
        "page_size": int(page_size),
        "total_pages": (int(total) + int(page_size) - 1) // int(page_size),
    }


def _offset(page: int, page_size: int) -> int:
    return (int(page) - 1) * int(page_size)


def _floors_json(floors: Iterable[Tuple[int, Decimal]]) -> List[Dict[str, Any]]:
    """Danh sách sàn cho vết (chỉ id học vụ + mức — không dữ liệu cá nhân), sắp id tăng."""
    return [
        {"offering_academic_info_id": int(oai), "floor_score": format_score(Decimal(score))}
        for oai, score in sorted(floors, key=lambda x: int(x[0]))
    ]


async def _audit(
    db: AsyncSession,
    session_id: int,
    action: str,
    actor_user_id: int,
    *,
    old_value: Any = None,
    new_value: Any = None,
    reason: Optional[str] = None,
) -> None:
    from app.services.audit_service import log_audit

    await log_audit(
        db,
        AUDIT_ENTITY,
        int(session_id),
        action,
        actor_user_id=actor_user_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        source="api",
    )


async def quota_table_state(db: AsyncSession, academic_year: int) -> Dict[str, Any]:
    """Bảng chỉ tiêu năm HIỆN TẠI ``{status, version, quota_fingerprint}`` — dấu đọc bằng ĐÚNG hàm của bảng chỉ tiêu
    (``admission_quota_table_service.read_quota_fingerprint`` — một nguồn với GET bảng và ``RunInputs.quota_table``). Lần xét luôn
    có bảng của năm (khoá ngoại RESTRICT) ⇒ thiếu bảng là dữ liệu hỏng ⇒ lỗi (500), không trả cấu trúc giả."""
    row = await review_repo.read_quota_table_state(db, academic_year)
    if row is None:
        raise RuntimeError("Năm %d của lần xét không có bảng chỉ tiêu (khoá ngoại bị vượt)." % int(academic_year))
    return {
        "status": row.status,
        "version": int(row.version),
        "quota_fingerprint": await read_quota_fingerprint(db, academic_year),
    }


def config_changed_since_run(inputs: Mapping[str, Any], *, session_version: int, quota_table: Mapping[str, Any]) -> bool:
    """``RunOut.config_changed_since_run`` (hợp đồng §3.3) — tính LÚC GET: ``version`` lần xét, hoặc trạng thái / ``version`` / dấu
    chỉ tiêu của bảng chỉ tiêu HIỆN TẠI khác đầu vào đã chụp của run."""
    chup = inputs.get("quota_table") or {}
    return (
        inputs.get("session_version") != int(session_version)
        or chup.get("status") != quota_table["status"]
        or chup.get("version") != quota_table["version"]
        or chup.get("quota_fingerprint") != quota_table["quota_fingerprint"]
    )


def run_summary_out(run: Any, *, session_version: int, quota_table: Mapping[str, Any]) -> Dict[str, Any]:
    """``RunSummaryOut`` (hợp đồng §3.4)."""
    summary = run.summary if isinstance(run.summary, Mapping) else None
    return {
        "id": int(run.id),
        "kind": run.kind,
        "status": run.status,
        "rule_version": run.rule_version,
        "requested_by_user_id": int(run.requested_by_user_id),
        "requested_at": run.requested_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "tab_counts": dict(summary["tab_counts"]) if summary is not None else None,
        "config_changed_since_run": config_changed_since_run(
            run.inputs, session_version=session_version, quota_table=quota_table
        ),
    }


def run_out(run: Any, *, session_version: int, quota_table: Mapping[str, Any]) -> Dict[str, Any]:
    """``RunOut`` (hợp đồng §3.3). ``inputs`` / ``summary`` / ``quota_view`` trả NGUYÊN GIÁ TRỊ đã ghi khi chạy (bất biến — mức sàn
    là ẢNH CHỤP ``inputs.floors``, KHÔNG đọc bảng sàn hiện tại: P4, BT45)."""
    return {
        "id": int(run.id),
        "session_id": int(run.session_id),
        "kind": run.kind,
        "status": run.status,
        "rule_version": run.rule_version,
        "requested_by_user_id": int(run.requested_by_user_id),
        "requested_at": run.requested_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "error_code": run.error_code,
        "inputs": run.inputs,
        "summary": run.summary,
        "quota_view": run.quota_view,
        "config_changed_since_run": config_changed_since_run(
            run.inputs, session_version=session_version, quota_table=quota_table
        ),
    }


def _round_out(rnd: Any) -> Dict[str, Any]:
    return {"id": int(rnd.id), "round_code": rnd.round_code, "round_name": rnd.round_name}


def _floor_out(r: Any) -> Dict[str, Any]:
    return {
        "offering_academic_info_id": int(r.offering_academic_info_id),
        "floor_score": format_score(r.floor_score),
        "major_code": r.major_code,
        "major_name": r.major_name,
        "offering_type": r.offering_type,
        "annual_admission_quota": r.annual_admission_quota,
        "group_code": r.group_code,
        "is_deleted": bool(r.is_deleted),
        "updated_by_user_id": int(r.updated_by_user_id),
        "updated_at": r.updated_at,
    }


async def build_session_out(db: AsyncSession, session: models.AdmissionReviewSession) -> Dict[str, Any]:
    """``SessionOut`` (hợp đồng §3.1). ``floors`` đọc THẲNG bảng sàn (không đặt ``[]`` theo trạng thái — lần xét đã huỷ có 0 dòng
    sàn do E5 xoá + trigger chặn huỷ khi còn sàn; đọc thẳng để một lỗi ở hai lớp ấy hiện ra chứ không bị che)."""
    sid, year = int(session.id), int(session.academic_year)
    rnd = (await review_repo.read_rounds(db, [session.admission_round_id]))[int(session.admission_round_id)]
    qt = await quota_table_state(db, year)
    floors = [_floor_out(r) for r in await review_repo.list_floors_detail(db, sid)]
    latest = (await review_repo.latest_runs(db, [sid])).get(sid)
    done_id = (await review_repo.latest_done_run_ids(db, [sid])).get(sid)
    return {
        "id": sid,
        "academic_year": year,
        "admission_round": _round_out(rnd),
        "seq_no": int(session.seq_no),
        "status": session.status,
        "version": int(session.version),
        "created_by_user_id": int(session.created_by_user_id),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "cancelled_by_user_id": session.cancelled_by_user_id,
        "cancelled_at": session.cancelled_at,
        "cancel_reason": session.cancel_reason,
        "quota_table": qt,
        "floors": floors,
        "latest_run": (
            run_summary_out(latest, session_version=int(session.version), quota_table=qt) if latest is not None else None
        ),
        "latest_done_run_id": done_id,
        "available_actions": session_actions(session.status),
    }


async def _session_or_404(db: AsyncSession, session_id: int) -> models.AdmissionReviewSession:
    session = await review_repo.get_session(db, session_id)
    if session is None:
        raise errors.review_session_not_found()
    return session


async def _locked_session(db: AsyncSession, session_id: int) -> Tuple[int, models.AdmissionReviewSession]:
    """Thứ tự khoá E4 / E5 (đặc tả §6.8): năm của lần xét đọc KHÔNG khoá (không có ⇒ 404) → KHOÁ NĂM chế độ CHIA SẺ → dòng lần xét
    ``FOR UPDATE``. MỘT chỗ khoá cho cả E4 lẫn E5.

    CHIA SẺ, không độc quyền (quyết định owner 23-11 ``QUYET-DINH-OWNER-GD2B-KHOA-NAM-E4-E5-CHIA-SE``): E4 / E5 KHÔNG đổi tập học vụ
    của năm; chúng cần (1) nối tiếp với ``PATCH`` dời năm học vụ — ``PATCH`` lấy bản ĐỘC QUYỀN năm cũ + mới, xung đột với chia sẻ ⇒
    vẫn nối tiếp (P3, P4); (2) năm / cờ xoá học vụ đứng yên khi E4 đọc — mọi đường đổi chúng đều lấy bản ĐỘC QUYỀN. Hai E4 / E5
    cùng lần xét nối tiếp ở KHOÁ DÒNG lần xét (người sau thấy ``version`` mới ⇒ 409 STALE). Bản độc quyền từng chặn mọi người đọc
    chia sẻ cùng năm (ghi nhận Quyết định; F230: Phê duyệt / Rút chờ, Công bố / Chuyển chờ / Trả về Nháp nhận 409 "thử lại") suốt lúc
    E4 / E5 giữ HOẶC xếp hàng chờ khoá. Không bao giờ nâng lên độc quyền trong cùng giao dịch (``app.core.review_year_lock``)."""
    year = await review_repo.read_session_year(db, session_id)
    if year is None:
        raise errors.review_session_not_found()
    await lock_review_years_shared(db, [int(year)])
    session = await review_repo.lock_session(db, session_id)
    if session is None:  # không xảy ra (trigger cấm xoá lần xét) — giữ fail-closed
        raise errors.review_session_not_found()
    return int(year), session


# ═══════════════════════════════════════════ E1 — tạo ═══════════════════════════════════════════
async def create_session(
    db: AsyncSession, *, academic_year: int, admission_round_id: int, actor_user_id: int
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """E1 — tạo lần xét ``draft`` / ``version`` 1. Lỗi (thứ tự): 400 ``review_round_invalid`` (đợt không có / khác năm) → 400
    ``review_round_archived`` (đợt đã lưu trữ — :func:`round_accepts_new_session`; phụ lục HĐ4 E10 §G1) → 409
    ``REVIEW_QUOTA_TABLE_MISSING`` (năm chưa có bảng chỉ tiêu). Đợt sai VÀ chưa có bảng ⇒ 400 trước (phụ lục K1–K4, điểm 4)."""
    year = int(academic_year)
    await lock_review_year(db, year)
    rnd = (await review_repo.read_rounds(db, [admission_round_id])).get(int(admission_round_id))
    if rnd is None or int(rnd.academic_year) != year:
        raise errors.review_round_invalid(admission_round_id)
    if not round_accepts_new_session(rnd):
        raise errors.review_round_archived(admission_round_id)
    if await review_repo.read_quota_table_state(db, year) is None:
        raise errors.review_quota_table_missing(year)
    seq_no = await review_repo.max_seq_no(db, year) + 1
    session = await review_repo.insert_session(
        db, academic_year=year, admission_round_id=int(admission_round_id), seq_no=seq_no, created_by_user_id=actor_user_id
    )
    await _audit(
        db,
        session.id,
        AUDIT_ACTION_CREATED,
        actor_user_id,
        new_value={"academic_year": year, "admission_round_id": int(admission_round_id), "seq_no": seq_no, "version": 1},
    )
    out = await build_session_out(db, session)
    log.info("admission_review_session_created", session_id=int(session.id), academic_year=year, seq_no=seq_no,
             actor_id=actor_user_id)
    return out, None


# ═══════════════════════════════════════════ E2 / E3 — đọc lần xét ═══════════════════════════════════════════
async def list_sessions(
    db: AsyncSession, *, academic_year: Optional[int], status: Optional[str], page: int, page_size: int
) -> Dict[str, Any]:
    """E2 — trang ``SessionListItemOut``, sắp năm GIẢM rồi ``seq_no`` GIẢM (repository)."""
    items, total = await review_repo.list_sessions(
        db, academic_year=academic_year, status=status, offset=_offset(page, page_size), limit=page_size
    )
    ids = [int(s.id) for s in items]
    counts = await review_repo.floor_counts(db, ids)
    latest = await review_repo.latest_runs(db, ids)
    rounds = await review_repo.read_rounds(db, [s.admission_round_id for s in items])
    states: Dict[int, Dict[str, Any]] = {}
    for year in sorted({int(s.academic_year) for s in items if int(s.id) in latest}):
        states[year] = await quota_table_state(db, year)
    out = []
    for s in items:
        sid = int(s.id)
        run = latest.get(sid)
        out.append(
            {
                "id": sid,
                "academic_year": int(s.academic_year),
                "admission_round": _round_out(rounds[int(s.admission_round_id)]),
                "seq_no": int(s.seq_no),
                "status": s.status,
                "version": int(s.version),
                "created_by_user_id": int(s.created_by_user_id),
                "created_at": s.created_at,
                "floor_count": counts.get(sid, 0),
                "latest_run": (
                    run_summary_out(run, session_version=int(s.version), quota_table=states[int(s.academic_year)])
                    if run is not None
                    else None
                ),
            }
        )
    return _page(out, total, page, page_size)


async def get_session_out(db: AsyncSession, session_id: int) -> Dict[str, Any]:
    """E3 — ``SessionOut``; không có ⇒ 404 ``review_session_not_found``."""
    return await build_session_out(db, await _session_or_404(db, session_id))


# ═══════════════════════════════════════════ E4 — thay toàn bộ điểm sàn ═══════════════════════════════════════════
async def replace_floors(
    db: AsyncSession,
    session_id: int,
    *,
    version: int,
    floors: Sequence[Tuple[int, Decimal]],
    actor_user_id: int,
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """E4 — thay TOÀN BỘ điểm sàn (mảng rỗng = xoá hết); ``version`` + 1. Lỗi đúng thứ tự hợp đồng §2 E4 (sau 422 của pydantic):
    400 ``review_floor_duplicate`` → 404 → (khoá năm, khoá dòng lần xét) → 409 ``REVIEW_SESSION_NOT_DRAFT`` → 409
    ``REVIEW_SESSION_STALE`` → 400 ``review_floor_bad_member`` (không có / đã xoá mềm / khác năm — đọc DƯỚI khoá năm, liệt kê đủ,
    tăng dần). Lỗi ⇒ không ghi gì (router không commit)."""
    pairs = [(int(oai), Decimal(score)) for oai, score in floors]
    trung = [oai for oai, n in Counter(oai for oai, _ in pairs).items() if n > 1]
    if trung:
        raise errors.review_floor_duplicate(trung)
    year, session = await _locked_session(db, session_id)
    require_session_action(session.status, ACTION_EDIT_FLOORS)
    if int(session.version) != int(version):
        raise errors.review_session_stale(int(session.version))
    gui = {oai for oai, _ in pairs}
    hop_le = {
        int(r.id)
        for r in await review_repo.read_academic_info_years(db, sorted(gui))
        if floor_member_accepted(r, year)
    }
    sai = gui - hop_le
    if sai:
        raise errors.review_floor_bad_member(sai, year)
    cu = await review_repo.delete_floors(db, session_id)
    moi = sorted(pairs)
    await review_repo.insert_floors(
        db, session_id=session_id, academic_year=year, floors=moi, updated_by_user_id=actor_user_id
    )
    # Giá trị CŨ chụp TRƯỚC ``update_session``: câu ``UPDATE`` ORM (``synchronize_session`` mặc định) GHI giá trị mới vào chính đối
    # tượng ``session`` trong identity map ⇒ đọc ``session.version`` SAU câu ấy là số MỚI — vết từng ghi ``old_value.version`` =
    # ``new_value.version`` (CI 23-11, ``test_e4_thay_toan_bo_san…``: 3 ≠ 2). Số trong CSDL vẫn đúng + 1 một lần.
    phien_ban_cu = int(session.version)
    phien_ban = phien_ban_cu + 1
    await review_repo.update_session(db, session_id, {"version": phien_ban})
    await _audit(
        db,
        session_id,
        AUDIT_ACTION_FLOORS_REPLACED,
        actor_user_id,
        old_value={"version": phien_ban_cu, "floors": _floors_json(cu)},
        new_value={"version": phien_ban, "floors": _floors_json(moi)},
    )
    await db.refresh(session)
    out = await build_session_out(db, session)
    log.info("admission_review_floors_replaced", session_id=int(session_id), version=phien_ban, floor_count=len(moi),
             released_count=len(cu), actor_id=actor_user_id)
    return out, None


# ═══════════════════════════════════════════ E5 — huỷ lần xét nháp ═══════════════════════════════════════════
async def cancel_session(
    db: AsyncSession, session_id: int, *, version: int, reason: str, actor_user_id: int
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """E5 — huỷ lần xét nháp, MỘT giao dịch (P4): khoá năm → dòng lần xét → kiểm ``draft`` + ``version`` → XOÁ MỌI SÀN (khi lần
    xét còn ``draft``) → ``cancelled`` (cuối, ``version`` + 1) → vết (lý do + danh sách sàn đã giải phóng). Run cũ không bị chạm
    (mức sàn đã dùng nằm trong ``inputs.floors`` của run). Lỗi: 404 → 409 ``REVIEW_SESSION_NOT_DRAFT`` → 409 ``REVIEW_SESSION_STALE``."""
    _, session = await _locked_session(db, session_id)
    require_session_action(session.status, ACTION_CANCEL)
    if int(session.version) != int(version):
        raise errors.review_session_stale(int(session.version))
    da_giai_phong = await review_repo.delete_floors(db, session_id)
    # Chụp TRƯỚC ``update_session`` (cùng lý do E4 ở trên): sau câu ``UPDATE`` ORM, ``session.version`` / ``session.status`` đã là
    # giá trị MỚI (``cancelled``) ⇒ vết sẽ ghi trạng thái cũ = ``cancelled``.
    cu = {"version": int(session.version), "status": session.status}
    phien_ban = cu["version"] + 1
    await review_repo.update_session(
        db,
        session_id,
        {
            "status": REVIEW_SESSION_CANCELLED,
            "version": phien_ban,
            "cancelled_by_user_id": int(actor_user_id),
            "cancelled_at": func.now(),
            "cancel_reason": reason,
        },
    )
    await _audit(
        db,
        session_id,
        AUDIT_ACTION_CANCELLED,
        actor_user_id,
        old_value=cu,
        new_value={"version": phien_ban, "status": REVIEW_SESSION_CANCELLED, "released_floors": _floors_json(da_giai_phong)},
        reason=reason,
    )
    await db.refresh(session)
    out = await build_session_out(db, session)
    log.info("admission_review_session_cancelled", session_id=int(session_id), version=phien_ban,
             released_count=len(da_giai_phong), actor_id=actor_user_id)
    return out, None


# ═══════════════════════════════════════════ E6 (phản hồi) / E7 / E8 / E9 — đọc run ═══════════════════════════════════════════
async def run_out_for(db: AsyncSession, session_id: int, run: Any) -> Dict[str, Any]:
    """``RunOut`` của một run vừa chạy (E6) — cùng hàm dựng với E8."""
    session = await _session_or_404(db, session_id)
    return run_out(run, session_version=int(session.version), quota_table=await quota_table_state(db, session.academic_year))


async def list_runs(db: AsyncSession, session_id: int, *, page: int, page_size: int) -> Dict[str, Any]:
    """E7 — trang ``RunSummaryOut`` của một lần xét, sắp ``id`` GIẢM; lần xét không có ⇒ 404."""
    session = await _session_or_404(db, session_id)
    items, total = await review_repo.list_runs(db, session_id, offset=_offset(page, page_size), limit=page_size)
    qt = await quota_table_state(db, session.academic_year) if items else None
    return _page(
        [run_summary_out(r, session_version=int(session.version), quota_table=qt) for r in items], total, page, page_size
    )


async def _run_or_404(db: AsyncSession, session_id: int, run_id: int) -> Tuple[models.AdmissionReviewSession, Any]:
    """Lần xét không có ⇒ 404 ``review_session_not_found``; run không có HOẶC thuộc lần xét khác ⇒ 404 ``review_run_not_found`` —
    CÙNG thân (không lộ run có tồn tại ở lần xét khác)."""
    session = await _session_or_404(db, session_id)
    run = await review_repo.get_run(db, session_id, run_id)
    if run is None:
        raise errors.review_run_not_found()
    return session, run


async def get_run_out(db: AsyncSession, session_id: int, run_id: int) -> Dict[str, Any]:
    """E8 — ``RunOut``."""
    session, run = await _run_or_404(db, session_id, run_id)
    return run_out(run, session_version=int(session.version), quota_table=await quota_table_state(db, session.academic_year))


def _score_parts(row: Any) -> Optional[Dict[str, Any]]:
    parts = (row.subject_total, row.area_score, row.object_score, row.priority_total)
    if all(p is None for p in parts):
        return None
    return {
        "subject_total": format_score(row.subject_total),
        "area": format_score(row.area_score),
        "object": format_score(row.object_score),
        "priority_total": format_score(row.priority_total),
    }


def _considered_choice(row: Any) -> Optional[Dict[str, Any]]:
    if row.considered_choice_id is None:
        return None
    return {
        "choice_id": int(row.considered_choice_id),
        "display_order": int(row.considered_display_order),
        "offering_academic_info_id": int(row.considered_offering_academic_info_id),
        "offering_id": int(row.considered_offering_id),
        "admission_path_id": int(row.considered_admission_path_id),
        "major_code": row.considered_major_code,
        "major_name": row.considered_major_name,
        "offering_type": row.considered_offering_type,
    }


def row_out(row: Any, person: Any) -> Dict[str, Any]:
    """``RowOut`` (hợp đồng §3.5). ``full_name`` / ``unit_id`` từ ``person`` (đọc lúc GET); mọi trường khác từ dòng ĐÃ GHI của run
    (bất biến — điểm dạng chuỗi qua ``admission_review_rules.format_score``). Danh sách mã sắp tăng (hợp đồng §1.4)."""
    return {
        "profile_id": int(row.profile_id),
        "full_name": person.full_name if person is not None else None,
        "unit_id": person.unit_id if person is not None else None,
        "profile_status": row.profile_status,
        "tab": row.tab,
        "reason_codes": sorted(row.reason_codes or []),
        "flags": sorted(row.flags or []),
        "decision_hints": sorted(row.decision_hints or []),
        "document_gaps": row.document_gaps,
        "considered_choice": _considered_choice(row),
        "review_total": format_score(row.review_total),
        "score_parts": _score_parts(row),
        "floor_score": format_score(row.floor_score),
        "rank_in_major": row.rank_in_major,
        "within_seats": row.within_seats,
        "ethnic_priority_state": row.ethnic_priority_state,
        "per_choice": list(row.per_choice or []),
        "prior_year_findings": list(row.prior_year_findings or []),
        "row_hash": row.row_hash,
    }


async def list_rows(
    db: AsyncSession,
    session_id: int,
    run_id: int,
    *,
    tab: Optional[str],
    offering_academic_info_id: Optional[int],
    reason_code: Optional[str],
    flag: Optional[str],
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    """E9 — trang dòng kết quả (lọc kết hợp VÀ; thứ tự cố định — repository) + ``tab_counts`` của CẢ run (từ ``summary`` đã ghi).
    Run chưa xong ⇒ 409 ``REVIEW_RUN_NOT_DONE`` (chỉ có khi chạy nền — GĐ2-C)."""
    _, run = await _run_or_404(db, session_id, run_id)
    if run.status != REVIEW_RUN_DONE:
        raise errors.review_run_not_done(run.status)
    rows, total = await review_repo.list_rows(
        db,
        run_id,
        tab=tab,
        offering_academic_info_id=offering_academic_info_id,
        reason_code=reason_code,
        flag=flag,
        offset=_offset(page, page_size),
        limit=page_size,
    )
    people = await review_repo.read_profile_people(db, [r.profile_id for r in rows])
    out = _page([row_out(r, people.get(int(r.profile_id))) for r in rows], total, page, page_size)
    counts = {t: 0 for t in REVIEW_TABS}
    counts.update({str(k): int(v) for k, v in ((run.summary or {}).get("tab_counts") or {}).items()})
    out["tab_counts"] = counts
    return out
