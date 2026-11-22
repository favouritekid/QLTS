"""Truy cập dữ liệu GĐ1b — lô duyệt giấy (§5) + duyệt chéo tạm thời (§6).

Mỗi bước có thể cần dừng / bơm lỗi trong test hai phiên là MỘT hàm cấp module (gọi qua tên module từ dịch vụ ⇒ test bọc được):
``try_lock_batch``, ``batch_lock_alive``, ``unlock_batch``, ``batch_lock_held``, ``read_batch``, ``lock_batch_row``,
``cleanup_previews``, ``write_item_results``, ``write_busy_results``…

Kết nối giữ khoá lô (L): engine RIÊNG ``NullPool`` + ``AUTOCOMMIT`` (F374) — ``close()`` là ngắt vật lý, L không vào pool,
không treo "idle in transaction". Khoá phiên chỉ được coi là nhả khi ``pg_advisory_unlock`` trả ``true``; không thì huỷ
kết nối (``invalidate`` → ``terminate``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

import structlog
from sqlalchemy import and_, delete, func, literal_column, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app import models
from app.repositories.council_decision_repository import db_error_codes

log = structlog.get_logger(__name__)

#: SQLSTATE coi là "hồ sơ đang bận" (§5.4 bước 7): hết ``lock_timeout``, huỷ câu lệnh, bế tắc.
BUSY_SQLSTATES = frozenset({"55P03", "57014", "40P01"})

#: Hạn mỗi bước nhả khoá (giây) — §5.5 "shield + hạn 5 s".
RELEASE_TIMEOUT_S = 5.0

_LOCK_ENGINE = None
#: Giữ tham chiếu các tác vụ nhả khoá chạy nền (tránh bị thu gom khi người chờ bị huỷ).
_RELEASE_TASKS: set = set()


def is_busy_error(exc: BaseException) -> bool:
    sqlstate, _ = db_error_codes(exc)
    return sqlstate in BUSY_SQLSTATES


# ---------------------------------------------------------------------------------------------------------------------
# Kết nối L + khoá tư vấn của lô
# ---------------------------------------------------------------------------------------------------------------------
def lock_engine():
    """Engine của kết nối giữ khoá lô: ``NullPool`` + ``AUTOCOMMIT``, cùng URL / tham số với engine chính."""
    global _LOCK_ENGINE
    if _LOCK_ENGINE is None:
        from app.database import engine as main_engine

        _LOCK_ENGINE = create_async_engine(
            main_engine.url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
            connect_args={
                "command_timeout": 30,
                "server_settings": {
                    "application_name": "qlts_bulk_verify_lock",
                    "statement_timeout": "30000",
                },
            },
        )
    return _LOCK_ENGINE


@dataclass
class BatchLock:
    """Khoá PHIÊN ``(ns, k)`` đang giữ trên kết nối L."""

    conn: AsyncConnection
    ns: int
    k: int
    pid: int
    driver_connection: Any = None


_SQL_LOCK_PRESENT = (
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'"
    " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    " AND classid::bigint = :ns AND objid::bigint = :k AND objsubid = 2 AND granted{pid})"
)


async def try_lock_batch(ns: int, k: int) -> Optional[BatchLock]:
    """§5.3 bước 1: ``pg_try_advisory_lock(ns, k)`` trên một kết nối L MỚI. ``None`` = đang có người giữ (L đã đóng)."""
    conn = await lock_engine().connect()
    try:
        raw = await conn.get_raw_connection()
        driver = getattr(raw, "driver_connection", None)
        row = (
            await conn.execute(
                text("SELECT pg_try_advisory_lock(:ns, :k) AS ok, pg_backend_pid() AS pid"), {"ns": ns, "k": k}
            )
        ).one()
    except BaseException:
        await _discard(conn, None)
        raise
    if not row.ok:
        await _discard(conn, driver)
        return None
    return BatchLock(conn=conn, ns=ns, k=k, pid=int(row.pid), driver_connection=driver)


async def batch_lock_alive(lock: BatchLock) -> bool:
    """§5.4 bước 3: khoá còn do CHÍNH L giữ (lọc ``pid = pg_backend_pid()``). Chạy TRÊN L — L chết ⇒ ném lỗi."""
    return bool(
        (
            await lock.conn.execute(
                text(_SQL_LOCK_PRESENT.format(pid=" AND pid = pg_backend_pid()")), {"ns": lock.ns, "k": lock.k}
            )
        ).scalar()
    )


async def unlock_batch(lock: BatchLock) -> Any:
    """``pg_advisory_unlock(ns, k)`` trên L — trả nguyên giá trị (chỉ ``True`` mới là đã nhả)."""
    return (await lock.conn.execute(text("SELECT pg_advisory_unlock(:ns, :k)"), {"ns": lock.ns, "k": lock.k})).scalar()


async def batch_lock_held(db: AsyncSession, ns: int, k: int) -> bool:
    """§5.6: có ai đang giữ khoá lô không (cùng câu ``pg_locks``, KHÔNG lọc ``pid``). Lỗi ⇒ ném (người gọi trả ``unknown``)."""
    return bool((await db.execute(text(_SQL_LOCK_PRESENT.format(pid="")), {"ns": ns, "k": k})).scalar())


async def _discard(conn: AsyncConnection, driver: Any) -> None:
    """Huỷ kết nối L không xác nhận được: ``invalidate`` (đóng vật lý); vẫn lỗi ⇒ ``terminate`` trình điều khiển."""
    try:
        await asyncio.wait_for(conn.invalidate(), RELEASE_TIMEOUT_S)
        return
    except BaseException as exc:  # noqa: BLE001 — đường cứu cuối, không được để lọt
        log.warning("bulk_verify_lock_invalidate_failed", error_type=type(exc).__name__)
    try:
        if driver is not None:
            driver.terminate()
    except BaseException as exc:  # noqa: BLE001
        log.error("bulk_verify_lock_terminate_failed", error_type=type(exc).__name__)


async def _release_inner(lock: BatchLock) -> bool:
    try:
        ok = await asyncio.wait_for(unlock_batch(lock), RELEASE_TIMEOUT_S)
        if ok is not True:
            raise RuntimeError(f"pg_advisory_unlock returned {ok!r}")
        await asyncio.wait_for(lock.conn.close(), RELEASE_TIMEOUT_S)
        return True
    except BaseException as exc:  # noqa: BLE001 — mọi lỗi (kể cả huỷ) ⇒ huỷ kết nối, khoá nhả theo kết nối
        log.warning("bulk_verify_lock_release_failed", error_type=type(exc).__name__, pid=lock.pid)
        await _discard(lock.conn, lock.driver_connection)
        return False


async def release_batch_lock(lock: BatchLock) -> None:
    """§5.5 nhả khoá trong ``finally``: việc nhả chạy trong một tác vụ RIÊNG, người gọi chờ qua ``asyncio.shield`` ⇒ người
    gọi bị huỷ (kể cả huỷ lặp lại) thì việc nhả vẫn chạy tới cùng (unlock = true rồi close; không thì invalidate)."""
    task = asyncio.ensure_future(_release_inner(lock))
    _RELEASE_TASKS.add(task)
    task.add_done_callback(_RELEASE_TASKS.discard)
    await asyncio.shield(task)


# ---------------------------------------------------------------------------------------------------------------------
# Dòng lô / dòng mục
# ---------------------------------------------------------------------------------------------------------------------
async def read_batch(db: AsyncSession, batch_id: UUID) -> Optional[models.DocumentBulkBatch]:
    """Đọc KHÔNG khoá, làm mới đối tượng trong phiên (mỗi lần một câu riêng — READ COMMITTED)."""
    return (
        await db.execute(
            select(models.DocumentBulkBatch)
            .where(models.DocumentBulkBatch.batch_id == batch_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def read_batch_state(db: AsyncSession, batch_id: UUID) -> Optional[Tuple[str, bool]]:
    """(``status``, ``expires_at <= clock_timestamp()``) bằng MỘT câu mới."""
    row = (
        await db.execute(
            select(
                models.DocumentBulkBatch.status,
                (models.DocumentBulkBatch.expires_at <= func.clock_timestamp()).label("expired"),
            ).where(models.DocumentBulkBatch.batch_id == batch_id)
        )
    ).first()
    return None if row is None else (row.status, bool(row.expired))


async def lock_batch_row(db: AsyncSession, batch_id: UUID) -> Optional[Tuple[models.DocumentBulkBatch, bool]]:
    """``FOR UPDATE`` dòng lô + cờ hết hạn so với ``clock_timestamp()`` đọc SAU khi có khoá.

    PR-B lượt 4 (Codex lượt 3 điểm chặn 4 — rà cùng khuôn): biểu thức hạn đặt TRONG câu khoá có thể được PostgreSQL tính
    TRƯỚC lúc chờ khoá và trả nguyên giá trị ấy nếu dòng không bị sửa (giao dịch giữ khoá nhả mà không ghi) ⇒ bản xem trước
    hết hạn trong lúc chờ vẫn bị coi là còn hạn. Đồng hồ CSDL đọc bằng câu RIÊNG sau khi có khoá."""
    row = (
        await db.execute(
            select(models.DocumentBulkBatch)
            .where(models.DocumentBulkBatch.batch_id == batch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row, row.expires_at <= await db_clock(db)


async def db_clock(db: AsyncSession) -> datetime:
    return (await db.execute(select(func.clock_timestamp()))).scalar_one()


async def insert_batch(db: AsyncSession, values: Dict[str, Any], items: Sequence[Dict[str, Any]]) -> None:
    await db.execute(models.DocumentBulkBatch.__table__.insert().values(**values))
    if items:
        await db.execute(models.DocumentBulkBatchItem.__table__.insert(), list(items))


async def list_items(db: AsyncSession, batch_id: UUID) -> List[models.DocumentBulkBatchItem]:
    return list(
        (
            await db.execute(
                select(models.DocumentBulkBatchItem)
                .where(models.DocumentBulkBatchItem.batch_id == batch_id)
                .order_by(models.DocumentBulkBatchItem.profile_id, models.DocumentBulkBatchItem.document_row_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def item_counts(db: AsyncSession, batch_ids: Sequence[UUID]) -> Dict[UUID, Dict[str, int]]:
    """Số hồ sơ + số mục theo ``result`` cho nhiều lô (một câu)."""
    if not batch_ids:
        return {}
    t = models.DocumentBulkBatchItem
    rows = (
        await db.execute(
            select(
                t.batch_id,
                func.count(func.distinct(t.profile_id)).label("profiles"),
                func.count().filter(t.result == "recorded").label("recorded"),
                func.count().filter(t.result == "error").label("error"),
                func.count().filter(t.result == "not_processed").label("not_processed"),
                func.count().filter(t.result.is_(None)).label("pending"),
            )
            .where(t.batch_id.in_(list(batch_ids)))
            .group_by(t.batch_id)
        )
    ).all()
    return {
        r.batch_id: {
            "profiles": r.profiles,
            "recorded": r.recorded,
            "error": r.error,
            "not_processed": r.not_processed,
            "pending": r.pending,
        }
        for r in rows
    }


async def count_batch_items(db: AsyncSession, batch_id: UUID) -> int:
    """Số mục (giấy) ĐÃ LƯU của lô lúc xem trước = ``counts.documents`` đã trả cho người tạo."""
    t = models.DocumentBulkBatchItem
    return int((await db.execute(select(func.count()).select_from(t).where(t.batch_id == batch_id))).scalar_one())


async def profile_has_results(db: AsyncSession, batch_id: UUID, profile_id: int) -> bool:
    t = models.DocumentBulkBatchItem
    return bool(
        (
            await db.execute(
                select(func.count())
                .select_from(t)
                .where(t.batch_id == batch_id, t.profile_id == profile_id, t.result.is_not(None))
            )
        ).scalar()
    )


async def write_item_results(db: AsyncSession, batch_id: UUID, results: Sequence[Dict[str, Any]]) -> None:
    """Ghi dòng kết quả (``recorded`` / ``error``) — CÙNG giao dịch với giấy (§5.4 bước 6: có dòng kết quả ⇔ đã commit)."""
    t = models.DocumentBulkBatchItem.__table__
    for r in results:
        res = await db.execute(
            update(t)
            .where(t.c.batch_id == batch_id, t.c.document_row_id == r["document_row_id"], t.c.result.is_(None))
            .values(result=r["result"], reason_code=r.get("reason_code"), message=r.get("message"),
                    updated_at=func.clock_timestamp())
        )
        if res.rowcount != 1:
            raise RuntimeError("bulk item result not written exactly once")


async def write_busy_results(db: AsyncSession, batch_id: UUID, profile_id: int, message: str) -> None:
    """§5.4 bước 7: ``error`` / ``profile_busy`` cho mọi mục CHƯA có kết quả của MỘT hồ sơ."""
    t = models.DocumentBulkBatchItem.__table__
    await db.execute(
        update(t)
        .where(t.c.batch_id == batch_id, t.c.profile_id == profile_id, t.c.result.is_(None))
        .values(result="error", reason_code="profile_busy", message=message, updated_at=func.clock_timestamp())
    )


async def write_profile_error(
    db: AsyncSession, batch_id: UUID, profile_id: int, reason_code: str, message: str
) -> None:
    t = models.DocumentBulkBatchItem.__table__
    await db.execute(
        update(t)
        .where(t.c.batch_id == batch_id, t.c.profile_id == profile_id, t.c.result.is_(None))
        .values(result="error", reason_code=reason_code, message=message, updated_at=func.clock_timestamp())
    )


async def mark_remaining_not_processed(db: AsyncSession, batch_id: UUID, message: Optional[str]) -> int:
    t = models.DocumentBulkBatchItem.__table__
    res = await db.execute(
        update(t)
        .where(t.c.batch_id == batch_id, t.c.result.is_(None))
        .values(result="not_processed", message=message, updated_at=func.clock_timestamp())
    )
    return res.rowcount


async def set_batch_status(db: AsyncSession, batch_id: UUID, **values: Any) -> None:
    t = models.DocumentBulkBatch.__table__
    await db.execute(update(t).where(t.c.batch_id == batch_id).values(**values))


async def try_xact_lock_batch(db: AsyncSession, ns: int, k: int) -> bool:
    """Khoá GIAO DỊCH trên khoá lô — ``finalize`` (§5.7 bước 2), dọn bản xem trước (§5.2 bước 1). Tự nhả cuối giao dịch."""
    return bool((await db.execute(text("SELECT pg_try_advisory_xact_lock(:ns, :k)"), {"ns": ns, "k": k})).scalar())


async def set_local_lock_timeout(db: AsyncSession, ms: int) -> None:
    await db.execute(text(f"SET LOCAL lock_timeout = '{int(ms)}ms'"))


# ---------------------------------------------------------------------------------------------------------------------
# Xem trước: khoá theo người + dọn bản xem trước
# ---------------------------------------------------------------------------------------------------------------------
async def lock_preview_user(db: AsyncSession, ns_preview: int, user_id: int) -> None:
    """§5.2 bước 0: ``pg_advisory_xact_lock(ns_preview, user_id)`` — tự nhả cuối giao dịch."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:ns, :u)"), {"ns": ns_preview, "u": user_id})


async def cleanup_previews(db: AsyncSession, *, user_id: int, ns: int, keep: int, key_of) -> int:
    """§5.2 bước 1: CHỈ dòng ``previewed`` của CHÍNH người bấm; xoá dòng hết hạn, rồi dòng cũ nhất tới khi còn ≤ ``keep``.

    Chỉ xoá dòng khoá được bằng ``FOR UPDATE SKIP LOCKED`` VÀ ``pg_try_advisory_xact_lock(ns, k)`` = true ⇒ không đụng lô
    đang bị ``execute`` giữ. Dòng mục CASCADE theo khoá ngoại (chỉ lô ``previewed`` bị xoá). Trả số dòng đã xoá.
    """
    t = models.DocumentBulkBatch
    rows = (
        await db.execute(
            select(t.batch_id, (t.expires_at <= func.clock_timestamp()).label("expired"))
            .where(t.actor_user_id == user_id, t.status == "previewed")
            .order_by(t.created_at, t.batch_id)
            .with_for_update(skip_locked=True)
        )
    ).all()
    to_delete: List[UUID] = []
    live = [r.batch_id for r in rows if not r.expired]
    # Đếm cả dòng đang bị khoá dòng (SKIP LOCKED bỏ qua) — chúng vẫn chiếm chỗ.
    live_total = (
        await db.execute(
            select(func.count()).select_from(t).where(
                t.actor_user_id == user_id, t.status == "previewed", t.expires_at > func.clock_timestamp()
            )
        )
    ).scalar_one()
    for r in rows:
        if r.expired and await try_xact_lock_batch(db, ns, key_of(r.batch_id)):
            to_delete.append(r.batch_id)
    for bid in live:
        if live_total <= keep:
            break
        if await try_xact_lock_batch(db, ns, key_of(bid)):
            to_delete.append(bid)
            live_total -= 1
    if to_delete:
        await db.execute(delete(t).where(t.batch_id.in_(to_delete), t.status == "previewed"))
    return len(to_delete)


async def count_live_previews(db: AsyncSession, user_id: int) -> int:
    t = models.DocumentBulkBatch
    return (
        await db.execute(
            select(func.count()).select_from(t).where(
                t.actor_user_id == user_id, t.status == "previewed", t.expires_at > func.clock_timestamp()
            )
        )
    ).scalar_one()


# ---------------------------------------------------------------------------------------------------------------------
# Chọn hồ sơ (một nguồn với danh sách ``GET /api/admissions``)
# ---------------------------------------------------------------------------------------------------------------------
async def select_profile_ids(
    db: AsyncSession,
    *,
    coord: Dict[str, Any],
    statuses: Optional[Iterable[str]],
    profile_ids: Optional[Sequence[int]] = None,
    unit_id: Optional[int] = None,
    search: Optional[str] = None,
    major_ids: Optional[List[int]] = None,
    academic_year: Optional[int] = None,
    degree_level: Optional[str] = None,
    payment_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[int]:
    """Id hồ sơ khớp bộ lọc — điều kiện dựng bằng ``AdmissionRepository._build_base_conditions`` (hàm lọc dùng chung của
    danh sách / đếm theo trạng thái), cộng ràng buộc trạng thái và (tuỳ chọn) danh sách id."""
    from app.repositories.admission_repository import AdmissionRepository

    conditions, needs_join = AdmissionRepository(db)._build_base_conditions(
        unit_id=coord.get("unit_id") if unit_id is None else unit_id,
        assigned_officer_id=coord.get("assigned_officer_id"),
        search=search,
        major_ids=major_ids,
        academic_year=academic_year,
        degree_level=degree_level,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        assigned_officer_ids=coord.get("assigned_officer_ids"),
        assigned_reviewer_ids=coord.get("assigned_reviewer_ids"),
        unassigned=bool(coord.get("unassigned")),
    )
    if statuses is not None:
        statuses = list(statuses)
        if not statuses:
            return []
        conditions.append(models.AdmissionProfile.status.in_(statuses))
    if profile_ids is not None:
        conditions.append(models.AdmissionProfile.id.in_(list(profile_ids)))
    query = select(models.AdmissionProfile.id).join(models.Lead)
    if needs_join:
        query = query.join(
            models.ProgramOffering, models.Lead.offering_id == models.ProgramOffering.id
        ).join(models.MajorProgram, models.ProgramOffering.program_id == models.MajorProgram.id)
    query = query.where(and_(*conditions)).order_by(models.AdmissionProfile.id)
    return list((await db.execute(query)).scalars().all())


async def load_profiles_with_documents(db: AsyncSession, profile_ids: Sequence[int]) -> List[models.AdmissionProfile]:
    if not profile_ids:
        return []
    return list(
        (
            await db.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id.in_(list(profile_ids)))
                .options(
                    selectinload(models.AdmissionProfile.lead),
                    selectinload(models.AdmissionProfile.documents).selectinload(models.ProfileDocument.document_type),
                )
                .order_by(models.AdmissionProfile.id)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------------------------------------------------
# Khoá theo thứ tự chung §4.5 cho MỘT hồ sơ của lô (sau dòng lô)
# ---------------------------------------------------------------------------------------------------------------------
async def lock_grant_share(db: AsyncSession, grant_id: int) -> Optional[Tuple[models.DocumentCrossReviewGrant, bool]]:
    """Dòng quyền chéo ``FOR SHARE`` + ``still_valid`` = ``expires_at > clock_timestamp()`` đọc SAU khi có khoá.

    PR-B lượt 4 (Codex lượt 3 điểm chặn 4): ``still_valid`` từng tính TRONG câu ``SELECT … FOR SHARE`` — PostgreSQL có thể
    tính biểu thức ấy TRƯỚC lúc chờ khoá và trả lại nguyên giá trị nếu dòng không bị sửa (giao dịch giữ khoá nhả mà không
    ghi) ⇒ quyền hết hạn TRONG lúc chờ vẫn được coi là còn hạn. Nay đồng hồ CSDL đọc bằng câu RIÊNG sau khi có khoá (dòng đã
    khoá ⇒ ``expires_at`` đứng yên tới commit; đồng hồ là thời điểm quyết định)."""
    grant = (
        await db.execute(
            select(models.DocumentCrossReviewGrant)
            .where(models.DocumentCrossReviewGrant.id == grant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if grant is None:
        return None
    return grant, grant.expires_at > await db_clock(db)


async def lock_lead_share(db: AsyncSession, lead_id: int) -> Optional[models.Lead]:
    return (
        await db.execute(
            select(models.Lead)
            .where(models.Lead.id == lead_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def lock_documents(db: AsyncSession, profile_id: int, document_row_ids: Sequence[int]) -> Dict[int, int]:
    """Dòng giấy ``FOR UPDATE`` theo id TĂNG (thứ tự chung §4.5). Trả ``{id: row_version}`` các dòng còn tồn tại của hồ sơ
    (đọc DƯỚI khoá)."""
    if not document_row_ids:
        return {}
    rows = (
        await db.execute(
            select(models.ProfileDocument.id, models.ProfileDocument.row_version)
            .where(
                models.ProfileDocument.profile_id == profile_id,
                models.ProfileDocument.id.in_(list(document_row_ids)),
            )
            .order_by(models.ProfileDocument.id)
            .with_for_update()
        )
    ).all()
    return {r.id: r.row_version for r in rows}


async def lock_user_key_share(db: AsyncSession, user_id: int) -> Optional[Any]:
    """Dòng người dùng ``FOR KEY SHARE`` — khoá YẾU NHẤT vẫn xung đột với ``FOR UPDATE`` / ``DELETE`` của K4
    (``user_deletion_policy.assert_user_deletable``) nhưng KHÔNG chặn ``UPDATE`` thường của dòng ``user`` (đăng nhập, đổi
    thông tin = ``FOR NO KEY UPDATE``).

    Trả hàng ``(id, status, role, unit_id)`` đọc DƯỚI khoá; ``None`` = dòng không còn (đã xoá). Chỉ chọn CỘT, không nạp
    thực thể: đối tượng ``User`` của người gọi đang nằm trong phiên (``current_user``) — ``populate_existing`` trên thực thể
    sẽ làm hết hạn quan hệ đã nạp của nó ⇒ đọc sau đó thành lazy-load ⇒ MissingGreenlet.

    Vì không chặn ``UPDATE`` thường, khoá này cũng KHÔNG giữ được VAI / TRẠNG THÁI: đổi vai, khoá tài khoản vẫn commit
    được trong lúc khoá còn giữ. Đường nào quyết định GHI theo vai mà không giữ dòng quyền chéo phải dùng
    ``lock_user_role_share`` (chốt lô, Admin cấp quyền chéo).

    PR-B: duyệt chéo (lẻ / xem trước / §5.4) khoá người BẰNG khoá này, không ``FOR SHARE``: ``FOR KEY SHARE`` không xung
    đột ``UPDATE "user"`` (đổi vai / khoá Q4 giữ ``FOR NO KEY UPDATE`` rồi chờ dòng quyền; giao lead giữ lead ``FOR UPDATE``
    rồi ``UPDATE`` người được giao) ⇒ không vòng chờ. Đổi vai / khoá xếp hàng sau duyệt chéo ở DÒNG QUYỀN; vai đọc ở đây
    được kiểm lại bằng vị từ chung (``cross_grant_authorizes``) trên dòng quyền đang giữ ``FOR SHARE``."""
    return (
        await db.execute(
            select(models.User.id, models.User.status, models.User.role, models.User.unit_id)
            .where(models.User.id == user_id)
            .with_for_update(read=True, key_share=True)
        )
    ).first()


async def lock_user_key_share_entity(db: AsyncSession, user_id: int) -> Optional[models.User]:
    """Như :func:`lock_user_key_share` nhưng trả THỰC THỂ đọc lại (``populate_existing``) — cho lõi ``transition_document``
    (luật ``DocumentActionPolicy`` cần đối tượng ``User``), cùng khuôn :func:`lock_user_share`."""
    return (
        await db.execute(
            select(models.User)
            .where(models.User.id == user_id)
            .with_for_update(read=True, key_share=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def lock_user_role_share(db: AsyncSession, user_id: int) -> Optional[Any]:
    """Dòng người dùng ``FOR SHARE`` — chặn MỌI ``UPDATE`` / ``DELETE`` của dòng ấy tới hết giao dịch: đổi vai, khoá tài
    khoản (``FOR NO KEY UPDATE``) và K4 (``FOR UPDATE``) đều phải CHỜ. Vai + trạng thái đọc ở đây vì thế còn đúng tới lúc
    commit. MỘT hàm cho hai đường quyết định GHI theo VAI hiện hành (ghép PR-A + PR-B, 21-11):
    - chốt lô (PR-A, Codex 20-11): Admin chốt lô của người khác — người → lô, không giữ dòng quyền chéo;
    - Admin CẤP quyền chéo (PR-B, Q4): đọc người được cấp dưới khoá — giữ khoá này không chờ dòng nào khác ngoài dòng
      quyền mới chèn ⇒ không vòng chờ với đổi vai / khoá (người ``FOR NO KEY UPDATE`` → quyền ``FOR UPDATE``).
    - GĐ2-C C1: cổng Thư ký Hội đồng (``review_secretary_service.require_secretary_access``) đọc vai / trạng thái CHÍNH người
      gọi dưới khoá (Admin luôn là Thư ký — owner 22-11), rồi mới tới dòng quyền ``FOR SHARE`` (người → quyền).

    Không xung đột với ``FOR SHARE`` / ``FOR KEY SHARE`` khác (§5.4, khoá khoá-ngoại khi ghi ``finalized_by_user_id``).
    Trả hàng ``(id, status, role, unit_id)`` đọc DƯỚI khoá; ``None`` = dòng không còn (đã xoá). Chỉ chọn CỘT, không nạp
    thực thể — cùng lý do MissingGreenlet như ``lock_user_key_share``."""
    return (
        await db.execute(
            select(models.User.id, models.User.status, models.User.role, models.User.unit_id)
            .where(models.User.id == user_id)
            .with_for_update(read=True)
        )
    ).first()


async def lock_user_no_key_update(db: AsyncSession, user_id: int) -> Optional[Any]:
    """Dòng người dùng ``FOR NO KEY UPDATE`` — đúng khoá mà ``UPDATE "user"`` (đổi vai / trạng thái) sẽ lấy; lấy TRƯỚC khi
    khoá dòng quyền chéo (thứ tự toàn cục người → quyền). Không xung đột ``FOR KEY SHARE`` (khoá ngoại, duyệt chéo), xung
    đột ``FOR SHARE`` (cấp quyền chéo, chốt lô) ⇒ chờ giao dịch ấy commit. Trả hàng ``(id, role, status)`` đọc DƯỚI khoá
    (``None`` = dòng không còn) — Q4 quyết thu hồi bằng giá trị này, không bằng bản đọc từ đầu yêu cầu."""
    return (
        await db.execute(
            select(models.User.id, models.User.role, models.User.status)
            .where(models.User.id == user_id)
            .with_for_update(key_share=True)
        )
    ).first()


async def lock_user_for_update(db: AsyncSession, user_id: int) -> Optional[Any]:
    """Dòng người dùng ``FOR UPDATE`` — đúng khoá của ``DELETE`` (K4) và của ``UPDATE`` ĐỔI cột khoá (cột có chỉ mục duy
    nhất dùng được cho khoá ngoại: ``username``, ``email`` — ``user_deletion_policy.USER_KEY_COLUMNS``). Xung đột MỌI khoá
    dòng khác, kể cả ``FOR KEY SHARE`` của khoá ngoại. Trả hàng ``(id, role, status)`` đọc DƯỚI khoá; ``None`` = dòng không
    còn. Chỉ ``user_deletion_policy.lock_users_in_id_order`` gọi (thứ tự khoá dòng ``user`` ở MỘT nơi)."""
    return (
        await db.execute(
            select(models.User.id, models.User.role, models.User.status)
            .where(models.User.id == user_id)
            .with_for_update()
        )
    ).first()


async def lock_leads_share(db: AsyncSession, lead_ids: Sequence[int]) -> Dict[int, models.Lead]:
    """Lead ``FOR SHARE`` theo id TĂNG, đọc lại dưới khoá (``populate_existing``). Trả ``{id: Lead}`` các dòng còn."""
    if not lead_ids:
        return {}
    rows = (
        await db.execute(
            select(models.Lead)
            .where(models.Lead.id.in_(list(lead_ids)))
            .order_by(models.Lead.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return {r.id: r for r in rows}


async def lock_user_share(db: AsyncSession, user_id: int) -> Optional[models.User]:
    return (
        await db.execute(
            select(models.User)
            .where(models.User.id == user_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------------------------------------------------
# Danh sách lô (X3)
# ---------------------------------------------------------------------------------------------------------------------
async def list_batches(
    db: AsyncSession,
    *,
    actor_user_id: Optional[int],
    review_mode: Optional[str],
    window_days: int,
    after: Optional[Tuple[datetime, UUID]],
    limit: int,
    grant_unit_ids: Optional[Sequence[int]] = None,
) -> List[models.DocumentBulkBatch]:
    """Thứ tự ổn định ``created_at DESC, batch_id DESC``; con trỏ = (created_at, batch_id) của dòng cuối trang trước.
    ``grant_unit_ids`` (lô chéo): chỉ lô tạo bằng quyền ghi đơn vị thuộc danh sách này."""
    t = models.DocumentBulkBatch
    conds = [t.created_at >= func.clock_timestamp() - literal_column(f"interval '{int(window_days)} days'")]
    if actor_user_id is not None:
        conds.append(t.actor_user_id == actor_user_id)
    if review_mode is not None:
        conds.append(t.review_mode == review_mode)
    if grant_unit_ids is not None:
        g = models.DocumentCrossReviewGrant
        conds.append(t.grant_id.in_(select(g.id).where(g.unit_id.in_(list(grant_unit_ids)))))
    if after is not None:
        c_at, c_id = after
        conds.append(
            (t.created_at < c_at) | and_(t.created_at == c_at, t.batch_id < c_id)
        )
    return list(
        (
            await db.execute(
                select(t)
                .where(and_(*conds))
                .order_by(t.created_at.desc(), t.batch_id.desc())
                .limit(limit)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------------------------------------------------
# Duyệt chéo — quyền
# ---------------------------------------------------------------------------------------------------------------------
async def active_grants_for_user(db: AsyncSession, user_id: int) -> List[models.DocumentCrossReviewGrant]:
    """Quyền CÒN HIỆU LỰC của một người: chưa thu hồi, ``expires_at > clock_timestamp()``."""
    g = models.DocumentCrossReviewGrant
    return list(
        (
            await db.execute(
                select(g)
                .where(g.grantee_user_id == user_id, g.revoked_at.is_(None), g.expires_at > func.clock_timestamp())
                .order_by(g.id)
            )
        )
        .scalars()
        .all()
    )


async def list_grants(
    db: AsyncSession, *, active: Optional[bool], grantee_user_id: Optional[int], unit_id: Optional[int]
) -> List[Tuple[models.DocumentCrossReviewGrant, bool]]:
    g = models.DocumentCrossReviewGrant
    is_active = and_(g.revoked_at.is_(None), g.expires_at > func.clock_timestamp())
    q = select(g, is_active.label("is_active"))
    if active is True:
        q = q.where(is_active)
    elif active is False:
        q = q.where(~is_active)
    if grantee_user_id is not None:
        q = q.where(g.grantee_user_id == grantee_user_id)
    if unit_id is not None:
        q = q.where(g.unit_id == unit_id)
    return [(r[0], bool(r[1])) for r in (await db.execute(q.order_by(g.id.desc()).limit(500))).all()]


async def grant_unit_id(db: AsyncSession, grant_id: int) -> Optional[int]:
    """Đơn vị ghi trên một quyền chéo (đọc, không khoá) — đơn vị của lô chéo tạo bằng quyền ấy."""
    return (
        await db.execute(select(models.DocumentCrossReviewGrant.unit_id).where(models.DocumentCrossReviewGrant.id == grant_id))
    ).scalar_one_or_none()


async def own_grant_unit_id(db: AsyncSession, grant_id: int, grantee_user_id: int) -> Optional[int]:
    """Đơn vị ghi trên quyền ``grant_id`` NẾU quyền ấy cấp cho ``grantee_user_id`` (ở mọi trạng thái — kể cả đã thu hồi /
    hết hạn); quyền của người khác / không có ⇒ ``None``. Đọc, không khoá — chỉ để chọn 409 / 404 (owner câu 9)."""
    g = models.DocumentCrossReviewGrant
    return (
        await db.execute(select(g.unit_id).where(g.id == grant_id, g.grantee_user_id == grantee_user_id))
    ).scalar_one_or_none()


async def lock_active_grants_of_user_for_update(db: AsyncSession, user_id: int) -> List[models.DocumentCrossReviewGrant]:
    """Mọi quyền CHƯA thu hồi, CHƯA hết hạn (``clock_timestamp()``) của một người — ``FOR UPDATE`` theo id TĂNG (Q4).

    PR-B lượt 4 (rà cùng khuôn Codex lượt 3 điểm chặn 4): khoá mọi quyền CHƯA thu hồi, rồi lọc hạn bằng đồng hồ CSDL đọc
    SAU khi có khoá (câu riêng) — hạn đặt trong câu khoá có thể tính TRƯỚC lúc chờ."""
    g = models.DocumentCrossReviewGrant
    grants = list(
        (
            await db.execute(
                select(g)
                .where(g.grantee_user_id == user_id, g.revoked_at.is_(None))
                .order_by(g.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if not grants:
        return []
    now = await db_clock(db)
    return [x for x in grants if x.expires_at > now]


async def lock_grant_for_update(db: AsyncSession, grant_id: int) -> Optional[models.DocumentCrossReviewGrant]:
    return (
        await db.execute(
            select(models.DocumentCrossReviewGrant)
            .where(models.DocumentCrossReviewGrant.id == grant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def cross_queue_candidates(db: AsyncSession, *, unit_ids: Sequence[int], actor_id: int, statuses: Iterable[str]):
    """Giấy thường ``paper_submitted`` của hồ sơ chờ xét thuộc các đơn vị được cấp, lead chưa xoá mềm, KHÔNG phải lead do
    chính cán bộ chéo phụ trách. Luật cuối cùng (người nhận, hình thức, ngoài cấu hình) do ``document_review_rules.decide``."""
    if not unit_ids:
        return []
    p, d, ld = models.AdmissionProfile, models.ProfileDocument, models.Lead
    q = (
        select(d, p, ld)
        .join(p, p.id == d.profile_id)
        .join(ld, ld.id == p.lead_id)
        .where(
            d.category == "path",
            d.status == "paper_submitted",
            p.status.in_(list(statuses)),
            ld.deleted_at.is_(None),
            ld.unit_id.in_(list(unit_ids)),
            (ld.assigned_officer_id.is_(None)) | (ld.assigned_officer_id != actor_id),
        )
        .options(selectinload(d.document_type))
        .order_by(d.profile_id, d.id)
    )
    return list((await db.execute(q)).all())
