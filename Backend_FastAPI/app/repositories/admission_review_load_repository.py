# app/repositories/admission_review_load_repository.py
"""GĐ2-B đợt 2 — các câu đọc THEO LÔ của run "Kiểm hồ sơ" (đề cương đợt 2 §2; hợp đồng bộ nạp
``logs-P5/cong-bo-ket-qua/gd2/gd2b/dot2/HOP-DONG-BO-NAP-THEO-LO-2026-11-22.md``).

Mọi hàm chạy trên kết nối của ảnh chụp ``REPEATABLE READ READ ONLY`` (``council_candidate_repository.read_only_transaction``);
tham số là MẢNG id / khoá ⇒ MỖI hàm = ĐÚNG MỘT câu SQL, kể cả khi mảng rỗng (số câu của một run không phụ thuộc số hồ sơ —
BT35). Không luật nghiệp vụ, không ghi gì. Câu nào là BẢN LÔ của một câu đọc từng hồ sơ thì ghi rõ câu gốc — test khoá bằng nhau
ở ``tests/integration/test_gd2b_bt35_toan_luot_db.py``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import any_, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import lazyload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression

from app import models
from app.models.admission_review import REVIEW_RUN_DONE, REVIEW_SESSION_DRAFT, REVIEW_TAB_AUTO
from app.models.council_document import EFFECTIVE_ROW_CONDITION

# ═══════════════════════════════ lần xét · bảng chỉ tiêu · học vụ ═══════════════════════════════
async def read_session(conn: AsyncConnection, session_id: int) -> Optional[Any]:
    """Lần xét (id, năm, đợt, trạng thái, version) — đọc lại TRONG ảnh chụp để kiểm ``draft`` + ``version`` (đặc tả §9.1)."""
    s = models.AdmissionReviewSession
    return (
        await conn.execute(
            select(s.id, s.academic_year, s.admission_round_id, s.status, s.version).where(s.id == session_id)
        )
    ).one_or_none()


async def read_quota_table(conn: AsyncConnection, academic_year: int) -> Optional[Any]:
    """Bảng chỉ tiêu của năm (trạng thái + version) — ``None`` = chưa có."""
    t = models.AdmissionQuotaTable
    return (
        await conn.execute(select(t.status, t.version).where(t.academic_year == academic_year))
    ).one_or_none()


async def read_groups(conn: AsyncConnection, academic_year: int) -> List[Any]:
    """Nhóm ngành của bảng chỉ tiêu năm, sắp id."""
    g = models.AdmissionQuotaGroup
    return list(
        (
            await conn.execute(
                select(g.id, g.code, g.name, g.ceiling).where(g.academic_year == academic_year).order_by(g.id)
            )
        ).all()
    )


async def read_group_members(conn: AsyncConnection, academic_year: int) -> List[Tuple[int, int]]:
    """``(id nhóm, id học vụ)`` của mọi thành viên nhóm năm."""
    m = models.AdmissionQuotaGroupMember
    return [
        (int(a), int(b))
        for a, b in (
            await conn.execute(
                select(m.group_id, m.offering_academic_info_id).where(m.academic_year == academic_year)
            )
        ).all()
    ]


async def read_academic_infos(
    conn: AsyncConnection, academic_year: int, extra_ids: Iterable[int]
) -> List[Any]:
    """Mọi học vụ của năm (kể cả đã xoá mềm — dấu chỉ tiêu tính cả cờ xoá) + các học vụ NGOÀI năm mà nguyện vọng trỏ tới, kèm
    loại hình / ngành (cờ Ngừng, mã, tên, nhãn loại hình lúc chạy). Nối trái: học vụ thiếu loại hình / ngành vẫn có hàng."""
    oai, po, mp = models.OfferingAcademicInfo, models.ProgramOffering, models.MajorProgram
    extra = sorted({int(i) for i in extra_ids})
    cond = oai.academic_year == academic_year
    if extra:
        cond = cond | oai.id.in_(extra)
    return list(
        (
            await conn.execute(
                select(
                    oai.id,
                    oai.academic_year,
                    oai.offering_id,
                    oai.annual_admission_quota,
                    oai.is_deleted,
                    po.is_active.label("offering_active"),
                    mp.is_active.label("major_active"),
                    mp.code.label("major_code"),
                    mp.name.label("major_name"),
                    po.offering_type.label("offering_type"),
                )
                .select_from(oai)
                .outerjoin(po, po.id == oai.offering_id)
                .outerjoin(mp, mp.id == po.program_id)
                .where(cond)
                .order_by(oai.id)
            )
        ).all()
    )


# ═══════════════════════════════ đồ thị ORM theo lô (owner Q3 22-11: KHÔNG chia khúc) ═══════════════════════════════
class UnsupportedBatchRelationship(ValueError):
    """Quan hệ không nạp được bằng MỘT câu tham số mảng (bảng trung gian / khoá ghép) — từ chối, không rơi về cách khác."""


def _edge_name(attr: Any) -> str:
    return "%s.%s" % (attr.class_.__name__, attr.key)


async def _load_edge(orm: Any, parents: Sequence[Any], attr: Any) -> List[Any]:
    """MỘT câu cho MỘT quan hệ của MỌI đối tượng cha: ``SELECT đích WHERE cột_nối = ANY(:mảng)`` (``lazyload('*')`` — không kéo
    quan hệ mặc định nào của lớp đích), rồi gán bằng ``set_committed_value`` (như ``selectinload`` gán, không đánh dấu thay
    đổi). Nhiều-một: gán đối tượng (``None`` khi khoá ngoại trống / không có hàng); một-nhiều: gán danh sách theo ``order_by`` của
    quan hệ rồi khoá chính. Trả các đối tượng đích (cha của tầng sau)."""
    prop = attr.property
    direction = prop.direction.name
    join = prop.primaryjoin
    simple_join = isinstance(join, BinaryExpression) and join.operator is operators.eq
    if (
        prop.secondary is not None
        or not simple_join
        or len(prop.local_remote_pairs) != 1
        or direction not in ("MANYTOONE", "ONETOMANY")
    ):
        # Điều kiện nối có thêm vế (lọc) / bảng trung gian / khoá ghép ⇒ một câu ``= ANY`` sẽ bỏ mất vế ấy ⇒ từ chối.
        raise UnsupportedBatchRelationship(_edge_name(attr))
    local_col, remote_col = prop.local_remote_pairs[0]
    local_key = prop.parent.get_property_by_column(local_col).key
    target = prop.mapper
    remote_key = target.get_property_by_column(remote_col).key
    values = sorted({getattr(p, local_key) for p in parents if getattr(p, local_key) is not None})
    stmt = (
        select(target.class_)
        .where(getattr(target.class_, remote_key) == any_(bindparam("ids", values, type_=ARRAY(remote_col.type))))
        .options(lazyload("*"))
    )
    if direction == "ONETOMANY" and prop.order_by:
        stmt = stmt.order_by(*prop.order_by)
    stmt = stmt.order_by(*target.primary_key)
    rows = list((await orm.execute(stmt)).scalars().all())
    if direction == "MANYTOONE":
        by_key = {getattr(t, remote_key): t for t in rows}
        for p in parents:
            set_committed_value(p, prop.key, by_key.get(getattr(p, local_key)))
        return rows
    groups: Dict[Any, List[Any]] = {}
    for t in rows:
        groups.setdefault(getattr(t, remote_key), []).append(t)
    for p in parents:
        items = groups.get(getattr(p, local_key), [])
        if prop.uselist:
            set_committed_value(p, prop.key, items)
        else:
            if len(items) > 1:
                raise UnsupportedBatchRelationship("%s: nhiều hàng cho quan hệ một-một" % _edge_name(attr))
            set_committed_value(p, prop.key, items[0] if items else None)
    return rows


async def load_relationship_paths(orm: Any, roots: Sequence[Any], paths: Sequence[Sequence[Any]]) -> int:
    """Nạp các đường quan hệ ``paths`` (vd ``admission_choice_engine_service.t6_profile_load_paths()``) cho mọi ``roots`` — MỖI
    CẠNH của cây đường (tiền tố chung chỉ nạp một lần) = ĐÚNG MỘT câu tham số mảng, kể cả khi mảng rỗng ⇒ số câu = số cạnh,
    KHÔNG theo số hồ sơ ở MỌI cỡ (khác ``selectinload``: SQLAlchemy chia khúc 500 khoá). Trả số câu đã gửi.

    Đối tượng gốc phải nạp với ``lazyload('*')`` (không kéo quan hệ mặc định). Quan hệ ngoài các đường này KHÔNG được nạp — chạm vào
    trong phiên async là lỗi (fail-closed), như khi thiếu ``selectinload``."""
    loaded: Dict[Tuple[str, ...], List[Any]] = {(): list(roots)}
    for attrs in paths:
        for depth in range(1, len(attrs) + 1):
            key = tuple(_edge_name(a) for a in attrs[:depth])
            if key not in loaded:
                loaded[key] = await _load_edge(orm, loaded[key[:-1]], attrs[depth - 1])
    return len(loaded) - 1


# ═══════════════════════════════ hồ sơ: phí · giấy · điểm môn ═══════════════════════════════
#: Mệnh đề chọn khoản học phí HK1 — CHÉP NGUYÊN chữ CTE ``hoc_phi`` của ``council_candidate_repository.SQL_PRINT_FIGURES`` (K2:
#: chưa huỷ, ``id`` lớn nhất). Test khoá: chuỗi này nằm NGUYÊN trong câu bản in + cùng khoản trên dữ liệu có khoản huỷ mới hơn.
SQL_HK1_TUITION_FILTER = "f.fee_type = 'tuition' AND f.status <> 'cancelled' AND f.semester_no = 1"
SQL_HK1_TUITION_ORDER = "ORDER BY f.admission_profile_id, f.id DESC"

SQL_TUITION_HK1 = text(
    """
SELECT DISTINCT ON (f.admission_profile_id)
       f.admission_profile_id AS pid, f.id AS fee_id, f.status::text AS status, f.paid_amount,
       f.resolved_major_id
FROM fee f
WHERE f.admission_profile_id = ANY(CAST(:pids AS integer[])) AND """
    + SQL_HK1_TUITION_FILTER
    + "\n"
    + SQL_HK1_TUITION_ORDER
)

SQL_APPLICATION_FEES = text(
    """
SELECT f.admission_profile_id AS pid, f.id AS fee_id, f.status::text AS status, f.paid_amount
FROM fee f
WHERE f.admission_profile_id = ANY(CAST(:pids AS integer[]))
  AND f.fee_type = 'application' AND f.status <> 'cancelled'
ORDER BY f.admission_profile_id, f.id
"""
)

#: Giấy THƯỜNG (``category = 'path'`` — tối đa một dòng / loại, ``uq_profile_document_path``) theo mã loại giấy.
SQL_PATH_DOCUMENTS = text(
    """
SELECT pd.profile_id AS pid, dt.code AS code, pd.id AS document_id, pd.status::text AS status,
       pd.row_version, pd.verified_format::text AS verified_format
FROM profile_document pd
JOIN config_document_type dt ON dt.id = pd.document_type_id
WHERE pd.profile_id = ANY(CAST(:pids AS integer[])) AND pd.category::text = 'path'
ORDER BY pd.profile_id, dt.code, pd.id
"""
)

#: Tổng điểm các môn của tổ hợp ĐÃ CHỌN của TỪNG nguyện vọng (``profile_choice_score`` ∩ môn của tổ hợp) — cùng phép cộng cột
#: ``tong_diem`` của bản in cho NV in (CTE ``mon`` / ``diem`` của ``SQL_PRINT_FIGURES``); test khoá bằng nhau trên NV in.
#: Không có điểm nào ⇒ vắng (``None``).
SQL_CHOICE_SUBJECT_TOTALS = text(
    """
SELECT c.id AS choice_id, sum(pcs.score) AS total
FROM admission_profile_choice c
JOIN path_subject_group_config psg ON psg.id = c.path_subject_group_config_id
JOIN profile_choice_score pcs ON pcs.admission_profile_choice_id = c.id
JOIN subject_group_subject sgs
     ON sgs.subject_group_id = psg.subject_group_id AND sgs.subject_id = pcs.subject_id
WHERE c.id = ANY(CAST(:ids AS integer[]))
GROUP BY c.id
"""
)


async def _rows(conn: AsyncConnection, stmt, **params) -> List[Any]:
    return list((await conn.execute(stmt, params)).all())


async def read_tuition_hk1(conn: AsyncConnection, pids: Sequence[int]) -> List[Any]:
    return await _rows(conn, SQL_TUITION_HK1, pids=[int(p) for p in pids])


async def read_application_fees(conn: AsyncConnection, pids: Sequence[int]) -> List[Any]:
    return await _rows(conn, SQL_APPLICATION_FEES, pids=[int(p) for p in pids])


async def read_path_documents(conn: AsyncConnection, pids: Sequence[int]) -> List[Any]:
    return await _rows(conn, SQL_PATH_DOCUMENTS, pids=[int(p) for p in pids])


async def read_choice_subject_totals(conn: AsyncConnection, choice_ids: Sequence[int]) -> Dict[int, Any]:
    return {
        int(r.choice_id): r.total
        for r in await _rows(conn, SQL_CHOICE_SUBJECT_TOTALS, ids=[int(c) for c in choice_ids])
    }


# ═══════════════════════════════ F231 · ưu tiên ═══════════════════════════════
#: Bản LÔ của ``priority_service._lookup_commune_kv``: hàng KV có hiệu lực TẠI 31-12 của năm (``effective_from <= 31-12`` và
#: ``effective_to`` trống hoặc SAU 31-12), mới nhất theo ``effective_from`` — cho MỌI cặp (mã xã, năm).
SQL_COMMUNE_KV = text(
    """
SELECT DISTINCT ON (k.code, k.year) k.code, k.year, m.area_code
FROM unnest(CAST(:codes AS text[]), CAST(:years AS integer[])) AS k(code, year)
JOIN vn_commune_area_map m
     ON m.commune_code = k.code
    AND m.effective_from <= make_date(k.year, 12, 31)
    AND (m.effective_to IS NULL OR m.effective_to > make_date(k.year, 12, 31))
ORDER BY k.code, k.year, m.effective_from DESC
"""
)

#: Bản LÔ của ``priority_service.lookup_kv_for_school_year``: ``effective_from_year <= năm`` và ``effective_to_year`` trống hoặc
#: ``>= năm`` — cho MỌI cặp (id trường, năm). Câu gốc ``LIMIT 1`` không sắp ⇒ nhiều hàng khớp thì cả hai cùng "một hàng bất kỳ".
SQL_SCHOOL_KV = text(
    """
SELECT DISTINCT ON (k.sid, k.year) k.sid, k.year, a.kv_code
FROM unnest(CAST(:sids AS integer[]), CAST(:years AS integer[])) AS k(sid, year)
JOIN vn_school_kv_assignment a
     ON a.school_id = k.sid
    AND a.effective_from_year <= k.year
    AND (a.effective_to_year IS NULL OR a.effective_to_year >= k.year)
ORDER BY k.sid, k.year
"""
)


async def read_commune_kv(conn: AsyncConnection, keys: Iterable[Tuple[str, int]]) -> Dict[Tuple[str, int], Optional[str]]:
    """``{(mã xã, năm): KV | None}`` cho ĐỦ mọi khoá hỏi (không có hàng ⇒ ``None``, như ``_lookup_commune_kv``)."""
    ks = sorted(set(keys))
    out: Dict[Tuple[str, int], Optional[str]] = {k: None for k in ks}
    for code, year, area in await _rows(
        conn, SQL_COMMUNE_KV, codes=[k[0] for k in ks], years=[int(k[1]) for k in ks]
    ):
        out[(code, int(year))] = area
    return out


async def read_school_kv(conn: AsyncConnection, keys: Iterable[Tuple[int, int]]) -> Dict[Tuple[int, int], Optional[str]]:
    """``{(id trường, năm): KV | None}`` cho ĐỦ mọi khoá hỏi (không có hàng ⇒ ``None``, như ``lookup_kv_for_school_year``)."""
    ks = sorted(set(keys))
    out: Dict[Tuple[int, int], Optional[str]] = {k: None for k in ks}
    for sid, year, kv in await _rows(
        conn, SQL_SCHOOL_KV, sids=[int(k[0]) for k in ks], years=[int(k[1]) for k in ks]
    ):
        out[(int(sid), int(year))] = kv
    return out


async def read_open_area_rates(conn: AsyncConnection, academic_year: int) -> List[Tuple[str, Any]]:
    """Mọi hàng mức KV ĐANG MỞ (``effective_to IS NULL``) của năm — ``(mã, điểm)``; cùng điều kiện ``select_open_priority_rates``."""
    m = models.PriorityAreaConfig
    return [
        (a, b)
        for a, b in (
            await conn.execute(
                select(m.area_code, m.bonus_points)
                .where(m.academic_year == academic_year, m.effective_to.is_(None))
                .order_by(m.area_code, m.id)
            )
        ).all()
    ]


async def read_open_object_rates(conn: AsyncConnection, academic_year: int) -> List[Tuple[str, Any]]:
    """Mọi hàng mức đối tượng ĐANG MỞ của năm — ``(mã, điểm)``."""
    m = models.PriorityObjectConfig
    return [
        (a, b)
        for a, b in (
            await conn.execute(
                select(m.sub_code, m.bonus_points)
                .where(m.academic_year == academic_year, m.effective_to.is_(None))
                .order_by(m.sub_code, m.id)
            )
        ).all()
    ]


# ═══════════════════════════════ cờ A13 · A19 ═══════════════════════════════
#: A13 (K4 + biên bản A13 + owner Q7 22-11): mọi hồ sơ ở năm tuyển sinh NHỎ HƠN ``:nam`` có khoá CCCD (CCCD đã xoá MỌI khoảng
#: trắng — mẫu ``:ws`` = ``admission_review_rules.CITIZEN_ID_WHITESPACE_PATTERN``, một định nghĩa với phía Python) thuộc mảng khoá
#: của các hồ sơ năm Y (nơi gọi tính bằng ``citizen_id_match_key``; khoá rỗng đã loại), kèm "có dòng Quyết định còn hiệu lực ghi
#: trong phần mềm" (biểu thức MỘT nguồn ``EFFECTIVE_ROW_CONDITION``). Lọc trạng thái chiếm chỗ là việc của luật
#: (``same_citizen_previous_year`` — một nguồn ``OCCUPYING_STATUSES``).
SQL_PRIOR_YEAR_PROFILES = text(
    """
SELECT k.match_key, prev.academic_year, prev.status::text AS status,
       EXISTS (SELECT 1 FROM council_decision_row
               WHERE profile_id = prev.id AND ("""
    + EFFECTIVE_ROW_CONDITION
    + """)) AS has_effective_decision
FROM admission_profile prev
CROSS JOIN LATERAL (SELECT regexp_replace(prev.citizen_id, CAST(:ws AS text), '', 'g') AS match_key) k
WHERE prev.academic_year < :nam AND k.match_key = ANY(CAST(:keys AS text[]))
ORDER BY k.match_key, prev.academic_year DESC, prev.id
"""
)

#: A19 (phụ lục điểm 1): hồ sơ ở tab ``auto`` của run ``done`` MỚI NHẤT của mỗi lần xét nháp KHÁC cùng năm.
SQL_OTHER_DRAFT_AUTO = text(
    """
WITH khac AS (
    SELECT s.id FROM admission_review_session s
    WHERE s.academic_year = :nam AND s.status = :nhap AND s.id <> :sid
),
moi_nhat AS (
    SELECT DISTINCT ON (r.session_id) r.id
    FROM admission_review_run r
    JOIN khac ON khac.id = r.session_id
    WHERE r.status = :xong
    ORDER BY r.session_id, r.id DESC
)
SELECT DISTINCT w.profile_id
FROM admission_review_row w
JOIN moi_nhat ON moi_nhat.id = w.run_id
WHERE w.tab = :tab
"""
)


async def read_prior_year_profiles(
    conn: AsyncConnection, *, academic_year: int, match_keys: Iterable[str], whitespace_pattern: str
) -> List[Any]:
    """Hàng ``(match_key, academic_year, status, has_effective_decision)`` của hồ sơ năm < ``academic_year`` theo khoá CCCD."""
    return await _rows(
        conn,
        SQL_PRIOR_YEAR_PROFILES,
        ws=whitespace_pattern,
        nam=int(academic_year),
        keys=sorted({k for k in match_keys if k}),
    )


async def read_other_draft_auto_profile_ids(conn: AsyncConnection, session_id: int, academic_year: int) -> List[int]:
    return [
        int(r[0])
        for r in await _rows(
            conn,
            SQL_OTHER_DRAFT_AUTO,
            nam=int(academic_year),
            nhap=REVIEW_SESSION_DRAFT,
            sid=int(session_id),
            xong=REVIEW_RUN_DONE,
            tab=REVIEW_TAB_AUTO,
        )
    ]


# ═══════════════════════════════ giao dịch chính (trước ảnh chụp) ═══════════════════════════════
async def document_type_exists(db: Any, code: str) -> bool:
    """Loại giấy ``code`` có trong ``config_document_type`` không (kiểm ``giay_xac_nhan_cu_tru`` — thiếu ⇒ 503)."""
    dt = models.ConfigDocumentType
    return bool((await db.execute(select(func.count()).select_from(dt).where(dt.code == code))).scalar_one())
