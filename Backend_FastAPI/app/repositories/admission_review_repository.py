# app/repositories/admission_review_repository.py
"""GĐ2-B — truy cập dữ liệu THUẦN cho bốn bảng lần xét (``admission_review_session``, ``admission_review_floor``,
``admission_review_run``, ``admission_review_row``). Đặc tả GĐ2-B bản 4 §4.2, §6.8; hợp đồng API bản 4 §2, §3.

KHÔNG luật nghiệp vụ: không kiểm trạng thái ``draft``, không so ``version``, không quyết lỗi nào, không lấy khoá năm — dịch vụ
(``admission_review_service`` / ``admission_review_run_service``, đợt 2) làm, theo ĐÚNG thứ tự khoá của đặc tả §6.8 (khoá năm →
:func:`lock_session` → …). Bất biến CSDL do trigger giữ (``app/models/admission_review_ddl.py``) — hàm ở đây không lách được.

Không ``commit`` (router commit). Mỗi bước có thể cần chen / bơm lỗi trong test hai phiên là MỘT hàm cấp module (gọi qua tên
module ⇒ test bọc được — khuôn ``document_bulk_repository``).

Hai loại kết nối: ``AsyncSession`` (giao dịch chính của request) cho hàm trả ĐỐI TƯỢNG ORM; hàm đọc viết bằng ``select`` cột
(trả ``Row``) chạy được trên cả ``AsyncSession`` lẫn ``AsyncConnection`` của ảnh chụp chỉ đọc
(``council_candidate_repository.read_only_transaction``) — ghi rõ ở từng hàm.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from sqlalchemy import case, delete, func, insert, select, text, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app import models
from app.models.admission_review import REVIEW_RUN_DONE, REVIEW_TABS

Executor = Union[AsyncSession, AsyncConnection]

S = models.AdmissionReviewSession
F = models.AdmissionReviewFloor
R = models.AdmissionReviewRun
W = models.AdmissionReviewRow


# ---------------------------------------------------------------------------------------------------------------------
# Lần xét
# ---------------------------------------------------------------------------------------------------------------------
async def read_session_year(db: Executor, session_id: int) -> Optional[int]:
    """Năm của lần xét (KHÔNG khoá) — để lấy khoá năm TRƯỚC khi khoá dòng (§6.8). An toàn vì năm của lần xét không bao giờ đổi
    (trigger ``admission_review_session_guard``). ``None`` = không có lần xét."""
    return (await db.execute(select(S.academic_year).where(S.id == session_id))).scalar_one_or_none()


async def get_session(db: AsyncSession, session_id: int) -> Optional[models.AdmissionReviewSession]:
    """Đọc một lần xét, KHÔNG khoá."""
    return (await db.execute(select(S).where(S.id == session_id))).scalar_one_or_none()


async def lock_session(db: AsyncSession, session_id: int) -> Optional[models.AdmissionReviewSession]:
    """Dòng lần xét ``FOR UPDATE`` (đọc lại giá trị mới nhất vào phiên — ``populate_existing``). ``None`` = không có."""
    return (
        await db.execute(
            select(S).where(S.id == session_id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def max_seq_no(db: Executor, academic_year: int) -> int:
    """``seq_no`` lớn nhất của năm (gồm lần xét đã huỷ); chưa có ⇒ 0. Gọi SAU khoá năm (E1) để hai lệnh tạo nối tiếp nhau."""
    return int(
        (await db.execute(select(func.coalesce(func.max(S.seq_no), 0)).where(S.academic_year == academic_year))).scalar_one()
    )


async def insert_session(
    db: AsyncSession,
    *,
    academic_year: int,
    admission_round_id: int,
    seq_no: int,
    created_by_user_id: int,
) -> models.AdmissionReviewSession:
    """Chèn một lần xét ``draft`` / ``version`` 1 (mặc định của bảng), ``flush`` để có ``id`` + mốc giờ do CSDL đặt."""
    obj = S(
        academic_year=int(academic_year),
        admission_round_id=int(admission_round_id),
        seq_no=int(seq_no),
        created_by_user_id=int(created_by_user_id),
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def update_session(db: Executor, session_id: int, values: Mapping[str, Any]) -> None:
    """``UPDATE`` một lần xét với đúng các cột trong ``values`` (dịch vụ quyết giá trị — vd ``version = version + 1``,
    ba cột huỷ). ``updated_at`` = ``now()`` nếu ``values`` không đặt."""
    vals = dict(values)
    vals.setdefault("updated_at", func.now())
    await db.execute(update(S).where(S.id == session_id).values(**vals))


async def list_sessions(
    db: AsyncSession,
    *,
    academic_year: Optional[int] = None,
    status: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
) -> Tuple[List[models.AdmissionReviewSession], int]:
    """Trang lần xét, sắp ``academic_year`` GIẢM rồi ``seq_no`` GIẢM (hợp đồng §2 E2) + tổng số dòng khớp lọc."""
    dk = []
    if academic_year is not None:
        dk.append(S.academic_year == academic_year)
    if status is not None:
        dk.append(S.status == status)
    total = int((await db.execute(select(func.count()).select_from(S).where(*dk))).scalar_one())
    items = list(
        (
            await db.execute(
                select(S).where(*dk).order_by(S.academic_year.desc(), S.seq_no.desc()).offset(offset).limit(limit)
            )
        ).scalars()
    )
    return items, total


# ---------------------------------------------------------------------------------------------------------------------
# Điểm sàn
# ---------------------------------------------------------------------------------------------------------------------
async def list_floors(db: Executor, session_id: int) -> List[Row]:
    """Điểm sàn của một lần xét, sắp ``offering_academic_info_id`` TĂNG (hợp đồng §3.1). Mỗi ``Row``:
    ``offering_academic_info_id``, ``floor_score`` (``Decimal``), ``updated_by_user_id``, ``updated_at``. Chạy được trong ảnh chụp
    chỉ đọc của lượt chạy."""
    return list(
        (
            await db.execute(
                select(F.offering_academic_info_id, F.floor_score, F.updated_by_user_id, F.updated_at)
                .where(F.session_id == session_id)
                .order_by(F.offering_academic_info_id)
            )
        ).all()
    )


async def delete_floors(db: Executor, session_id: int) -> List[Tuple[int, Decimal]]:
    """Xoá MỌI dòng sàn của lần xét; trả ``(id học vụ, mức)`` đã xoá, sắp id học vụ tăng (vết "sàn đã giải phóng" của E5;
    E4 thay toàn bộ). Trigger chặn nếu lần xét không ``draft``."""
    rows = (
        await db.execute(
            delete(F).where(F.session_id == session_id).returning(F.offering_academic_info_id, F.floor_score)
        )
    ).all()
    return sorted(((int(a), b) for a, b in rows), key=lambda x: x[0])


async def insert_floors(
    db: Executor,
    *,
    session_id: int,
    academic_year: int,
    floors: Sequence[Tuple[int, Decimal]],
    updated_by_user_id: int,
) -> None:
    """Chèn các dòng sàn ``(id học vụ, mức)`` — MỘT câu (nhiều giá trị). Không kiểm gì: trùng / sai năm / lần xét không nháp do
    UNIQUE / khoá ngoại ghép / trigger chặn; dịch vụ kiểm trước để báo lỗi nghiệp vụ."""
    if not floors:
        return
    await db.execute(
        insert(F),
        [
            {
                "session_id": int(session_id),
                "academic_year": int(academic_year),
                "offering_academic_info_id": int(oai),
                "floor_score": score,
                "updated_by_user_id": int(updated_by_user_id),
            }
            for oai, score in floors
        ],
    )


async def floor_counts(db: Executor, session_ids: Sequence[int]) -> Dict[int, int]:
    """Số dòng sàn theo lần xét (``floor_count`` của E2). Lần xét không có sàn không có khoá trong kết quả."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(F.session_id, func.count()).where(F.session_id.in_(list(session_ids))).group_by(F.session_id)
        )
    ).all()
    return {int(s): int(n) for s, n in rows}


async def sessions_with_floor_for_academic_info(db: Executor, academic_info_id: int) -> List[Row]:
    """Mọi lần xét đang có dòng sàn cho học vụ ``academic_info_id``, sắp ``seq_no`` rồi ``id`` TĂNG. Mỗi ``Row``: ``session_id``,
    ``seq_no``, ``academic_year``, ``status``. Dịch vụ chọn lần cần báo (vd ``seq_no`` nhỏ nhất của lần xét nháp —
    ``ACADEMIC_INFO_IN_REVIEW_FLOOR``)."""
    return list(
        (
            await db.execute(
                select(S.id.label("session_id"), S.seq_no, S.academic_year, S.status)
                .join(F, F.session_id == S.id)
                .where(F.offering_academic_info_id == academic_info_id)
                .order_by(S.seq_no, S.id)
            )
        ).all()
    )


# ---------------------------------------------------------------------------------------------------------------------
# Lượt chạy
# ---------------------------------------------------------------------------------------------------------------------
async def insert_run(
    db: AsyncSession,
    *,
    session_id: int,
    kind: str,
    status: str,
    rule_version: str,
    requested_by_user_id: int,
    inputs: Mapping[str, Any],
    started_at: Any = None,
) -> models.AdmissionReviewRun:
    """Chèn một lượt (trigger chỉ cho tạo ở ``queued`` / ``running``; CHECK đòi ``started_at`` khi ``running``), ``flush`` để có
    ``id``. ``inputs`` phải đã là JSON thuần (số / chuỗi / danh sách / object)."""
    obj = R(
        session_id=int(session_id),
        kind=kind,
        status=status,
        rule_version=rule_version,
        requested_by_user_id=int(requested_by_user_id),
        started_at=started_at,
        inputs=dict(inputs),
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def update_run(db: Executor, run_id: int, values: Mapping[str, Any]) -> None:
    """``UPDATE`` một lượt với đúng các cột trong ``values`` (vd chuyển ``done`` + ``finished_at`` / ``duration_ms`` / ``summary`` /
    ``quota_view``). Trigger chặn chuyển sai chiều / sửa lượt đã xong."""
    await db.execute(update(R).where(R.id == run_id).values(**dict(values)))


async def get_run(db: AsyncSession, session_id: int, run_id: int) -> Optional[models.AdmissionReviewRun]:
    """Một lượt THUỘC lần xét ``session_id`` (không thuộc ⇒ ``None`` — cùng kết quả với "không có")."""
    return (
        await db.execute(select(R).where(R.id == run_id, R.session_id == session_id))
    ).scalar_one_or_none()


async def list_runs(
    db: AsyncSession, session_id: int, *, offset: int = 0, limit: int = 20
) -> Tuple[List[models.AdmissionReviewRun], int]:
    """Trang lượt chạy của một lần xét, sắp ``id`` GIẢM (hợp đồng §2 E7) + tổng."""
    total = int((await db.execute(select(func.count()).select_from(R).where(R.session_id == session_id))).scalar_one())
    items = list(
        (
            await db.execute(select(R).where(R.session_id == session_id).order_by(R.id.desc()).offset(offset).limit(limit))
        ).scalars()
    )
    return items, total


async def latest_runs(db: AsyncSession, session_ids: Sequence[int]) -> Dict[int, models.AdmissionReviewRun]:
    """Lượt MỚI NHẤT (``id`` lớn nhất, mọi trạng thái) của từng lần xét — ``latest_run`` của E2 / E3."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(R)
            .where(R.session_id.in_(list(session_ids)))
            .distinct(R.session_id)
            .order_by(R.session_id, R.id.desc())
        )
    ).scalars()
    return {int(r.session_id): r for r in rows}


async def latest_done_run_ids(db: Executor, session_ids: Sequence[int]) -> Dict[int, int]:
    """``id`` của lượt ``done`` mới nhất từng lần xét — ``latest_done_run_id`` của E3. Lần xét chưa có lượt xong không có khoá."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(R.session_id, func.max(R.id))
            .where(R.session_id.in_(list(session_ids)), R.status == REVIEW_RUN_DONE)
            .group_by(R.session_id)
        )
    ).all()
    return {int(s): int(r) for s, r in rows}


# ---------------------------------------------------------------------------------------------------------------------
# Dòng kết quả
# ---------------------------------------------------------------------------------------------------------------------
#: Cột chèn của ``admission_review_row`` (mọi cột trừ ``id`` / ``run_id``) — MỌI dòng đưa vào :func:`insert_rows` phải có ĐÚNG tập
#: khoá này (= ``admission_review_rules.ReviewRow.column_values``; test khoá bằng nhau).
ROW_INSERT_COLUMNS: Tuple[str, ...] = tuple(c.name for c in W.__table__.columns if c.name not in ("id", "run_id"))


class RowColumnsMismatch(ValueError):
    """Một dòng thiếu / thừa cột so với :data:`ROW_INSERT_COLUMNS` — từ chối cả lô, KHÔNG ghi gì (fail-closed)."""


def _quoted(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


#: GĐ2-B đợt 2 (Codex 22-11 mục D P1): MỘT câu ``INSERT … SELECT`` nhiều dòng THẬT ở phía PostgreSQL — cả lô đi trong MỘT tham số
#: ``jsonb`` (mảng object), mỗi phần tử đổi thành một hàng ``admission_review_row`` bằng ``jsonb_populate_record`` (KIỂU CỘT lấy từ
#: CHÍNH bảng — không chép danh sách kiểu), ghi theo thứ tự lô (``WITH ORDINALITY``). Số tham số = 2, không theo số dòng (không chạm
#: trần 32 767 tham số của giao thức); driver gọi ``execute`` MỘT lần (không ``executemany``). JSON ``null`` ⇒ SQL NULL (như
#: ``none_as_null``); mảng JSON ⇒ ``TEXT[]``; chuỗi số ⇒ ``NUMERIC`` đúng giá trị.
SQL_INSERT_ROWS = text(
    "INSERT INTO admission_review_row (run_id, "
    + ", ".join(_quoted(c) for c in ROW_INSERT_COLUMNS)
    + ")\nSELECT CAST(:run_id AS integer), "
    + ", ".join("r." + _quoted(c) for c in ROW_INSERT_COLUMNS)
    + "\nFROM jsonb_array_elements(CAST(:rows AS jsonb)) WITH ORDINALITY AS e(item, ord)"
    + "\nCROSS JOIN LATERAL jsonb_populate_record(NULL::admission_review_row, e.item) AS r"
    + "\nORDER BY e.ord"
)


def _json_value(value: Any) -> Any:
    """``Decimal`` ⇒ chuỗi (giữ ĐÚNG giá trị — không qua ``float``); kiểu khác ngoài JSON ⇒ ``TypeError`` (không đoán)."""
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("Giá trị không ghi được vào JSON lô dòng: %s" % type(value).__name__)


async def insert_rows(db: Executor, run_id: int, rows: Sequence[Mapping[str, Any]]) -> None:
    """Chèn các dòng của MỘT lượt bằng MỘT câu SQL nhiều dòng (:data:`SQL_INSERT_ROWS`) — số câu KHÔNG tăng theo số hồ sơ, và
    PostgreSQL thực thi ĐÚNG MỘT câu (không phải ``executemany`` = N lần thực thi phía máy chủ — Codex 22-11 mục D P1; BT35, K1).

    Mọi dòng phải có ĐỦ :data:`ROW_INSERT_COLUMNS` (``None`` ghi thành NULL) — thiếu / thừa cột ⇒ :class:`RowColumnsMismatch` TRƯỚC
    khi gửi câu nào (khoá vắng trong JSON sẽ thành NULL âm thầm ⇒ phải chặn ở đây). Giá trị JSON phải đã là JSON thuần. Trigger chỉ
    cho chèn khi lượt ``running``; CHECK giữ dạng dòng."""
    if not rows:
        return
    cot = set(ROW_INSERT_COLUMNS)
    values = []
    for i, r in enumerate(rows):
        khoa = set(r)
        if khoa != cot:
            raise RowColumnsMismatch(
                "Dòng %d thiếu cột %s, thừa cột %s" % (i, sorted(cot - khoa), sorted(khoa - cot))
            )
        values.append({k: r[k] for k in ROW_INSERT_COLUMNS})
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=_json_value)
    await db.execute(SQL_INSERT_ROWS, {"run_id": int(run_id), "rows": payload})


def _row_filters(
    run_id: int,
    *,
    tab: Optional[str],
    offering_academic_info_id: Optional[int],
    reason_code: Optional[str],
    flag: Optional[str],
) -> list:
    dk = [W.run_id == run_id]
    if tab is not None:
        dk.append(W.tab == tab)
    if offering_academic_info_id is not None:
        dk.append(W.considered_offering_academic_info_id == offering_academic_info_id)
    if reason_code is not None:
        dk.append(W.reason_codes.contains([reason_code]))
    if flag is not None:
        dk.append(W.flags.contains([flag]))
    return dk


#: Thứ tự tab cố định của E9 (``auto``, ``needs_decision``, ``not_passed``, ``ineligible``); tab lạ (C nới) xếp cuối.
_TAB_ORDER = case({t: i for i, t in enumerate(REVIEW_TABS)}, value=W.tab, else_=len(REVIEW_TABS))


async def list_rows(
    db: AsyncSession,
    run_id: int,
    *,
    tab: Optional[str] = None,
    offering_academic_info_id: Optional[int] = None,
    reason_code: Optional[str] = None,
    flag: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> Tuple[List[models.AdmissionReviewRow], int]:
    """Trang dòng (đối tượng ORM — cần ``AsyncSession``) của một lượt + tổng khớp lọc (lọc kết hợp bằng VÀ — hợp đồng §2 E9).
    Thứ tự CỐ ĐỊNH: tab; trong ``auto`` /
    ``needs_decision``: ``considered_major_code``, ``considered_offering_academic_info_id``, ``review_total`` GIẢM; cuối cùng LUÔN
    ``profile_id`` TĂNG — chỉ để phân trang ổn định, KHÔNG phải luật phá hoà (dòng ``not_passed`` / ``ineligible`` có ba khoá giữa
    là NULL — CHECK ``ck_admission_review_row_placed`` — nên chỉ còn ``profile_id``)."""
    dk = _row_filters(
        run_id, tab=tab, offering_academic_info_id=offering_academic_info_id, reason_code=reason_code, flag=flag
    )
    total = int((await db.execute(select(func.count()).select_from(W).where(*dk))).scalar_one())
    q = (
        select(W)
        .where(*dk)
        .order_by(
            _TAB_ORDER,
            W.considered_major_code.asc().nulls_last(),
            W.considered_offering_academic_info_id.asc().nulls_last(),
            W.review_total.desc().nulls_last(),
            W.profile_id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list((await db.execute(q)).scalars()), total


async def tab_counts(db: Executor, run_id: int) -> Dict[str, int]:
    """Số dòng theo tab của CẢ lượt (``tab_counts`` của E9 / ``summary``). Tab không có dòng không có khoá."""
    rows = (await db.execute(select(W.tab, func.count()).where(W.run_id == run_id).group_by(W.tab))).all()
    return {str(t): int(n) for t, n in rows}


# ---------------------------------------------------------------------------------------------------------------------
# GĐ2-B đợt 2 (L3a + L4) — đọc phụ cho dịch vụ ghi và phản hồi của 9 API (hợp đồng API bản 4 §3). Không khoá, không luật.
# ---------------------------------------------------------------------------------------------------------------------
async def read_rounds(db: Executor, round_ids: Sequence[int]) -> Dict[int, Row]:
    """Đợt tuyển sinh theo id — mỗi ``Row``: ``id``, ``academic_year``, ``round_code``, ``round_name``, ``archived_at`` (E1 chặn đợt đã
    lưu trữ — ``admission_review_service.round_accepts_new_session``). Id không có không có khoá."""
    ids = sorted({int(i) for i in round_ids})
    if not ids:
        return {}
    o = models.OfferingAdmissionRound
    rows = (
        await db.execute(
            select(o.id, o.academic_year, o.round_code, o.round_name, o.archived_at).where(o.id.in_(ids))
        )
    ).all()
    return {int(r.id): r for r in rows}


async def read_quota_table_state(db: Executor, academic_year: int) -> Optional[Row]:
    """Trạng thái + ``version`` HIỆN TẠI của bảng chỉ tiêu năm (KHÔNG khoá). ``None`` = năm chưa có bảng."""
    t = models.AdmissionQuotaTable
    return (
        await db.execute(select(t.status, t.version).where(t.academic_year == academic_year))
    ).one_or_none()


async def read_academic_info_years(db: Executor, academic_info_ids: Sequence[int]) -> List[Row]:
    """``id``, ``academic_year``, ``is_deleted`` của các học vụ (id không có thì không có hàng) — E4 kiểm thành viên. KHÔNG khoá
    dòng: E4 gọi SAU khoá năm của lần xét (mọi lệnh dời năm / xoá mềm học vụ cũng giữ khoá năm ⇒ giá trị đứng yên tới commit)."""
    ids = sorted({int(i) for i in academic_info_ids})
    if not ids:
        return []
    oai = models.OfferingAcademicInfo
    return list(
        (await db.execute(select(oai.id, oai.academic_year, oai.is_deleted).where(oai.id.in_(ids)).order_by(oai.id))).all()
    )


async def list_floors_detail(db: Executor, session_id: int) -> List[Row]:
    """Điểm sàn của một lần xét kèm nhãn HIỆN TẠI của học vụ (``FloorOut`` — hợp đồng §3.1), sắp ``offering_academic_info_id``
    TĂNG. Mỗi ``Row``: ``offering_academic_info_id``, ``floor_score``, ``updated_by_user_id``, ``updated_at``, ``major_code``,
    ``major_name``, ``offering_type``, ``annual_admission_quota``, ``is_deleted``, ``group_code`` (nhóm của bảng chỉ tiêu cùng năm —
    UNIQUE một học vụ một nhóm; nối trái: không thuộc nhóm ⇒ ``None``)."""
    oai, po, mp = models.OfferingAcademicInfo, models.ProgramOffering, models.MajorProgram
    m, g = models.AdmissionQuotaGroupMember, models.AdmissionQuotaGroup
    return list(
        (
            await db.execute(
                select(
                    F.offering_academic_info_id,
                    F.floor_score,
                    F.updated_by_user_id,
                    F.updated_at,
                    mp.code.label("major_code"),
                    mp.name.label("major_name"),
                    po.offering_type.label("offering_type"),
                    oai.annual_admission_quota,
                    oai.is_deleted,
                    g.code.label("group_code"),
                )
                .select_from(F)
                .join(oai, oai.id == F.offering_academic_info_id)
                .outerjoin(po, po.id == oai.offering_id)
                .outerjoin(mp, mp.id == po.program_id)
                .outerjoin(m, (m.offering_academic_info_id == oai.id) & (m.academic_year == F.academic_year))
                .outerjoin(g, g.id == m.group_id)
                .where(F.session_id == session_id)
                .order_by(F.offering_academic_info_id)
            )
        ).all()
    )


async def read_profile_people(db: Executor, profile_ids: Sequence[int]) -> Dict[int, Row]:
    """Họ tên + đơn vị HIỆN TẠI của hồ sơ (E9 ``full_name`` / ``unit_id`` — đọc lúc GET, không bất biến). Đơn vị = ``lead.unit_id``
    (cột kiểm quyền của hồ sơ). Hồ sơ không còn ⇒ không có khoá. KHÔNG đọc CCCD / điện thoại / ngày sinh."""
    ids = sorted({int(i) for i in profile_ids})
    if not ids:
        return {}
    p, lead = models.AdmissionProfile, models.Lead
    rows = (
        await db.execute(
            select(p.id, p.full_name, lead.unit_id).select_from(p).outerjoin(lead, lead.id == p.lead_id).where(p.id.in_(ids))
        )
    ).all()
    return {int(r.id): r for r in rows}
