# app/services/admission_quota_table_service.py
"""GĐ2-A — bảng chỉ tiêu năm / nhóm ngành: xem, thay nội dung, khoá, mở khoá (đặc tả GĐ2 bản 3 §1, §3, §4 bước 1, §10,
§11; ca biên B14–B17, B20, D13, D14). Dịch vụ THUẦN: không import FastAPI, ném lỗi miền, chỉ ``flush`` — router commit.

Con số nghiệp vụ (chỉ tiêu ngành, trần nhóm) CHỈ đến từ dữ liệu Admin nhập; dịch vụ không tự tính, không đặt mặc định.

Tầng chủ sở hữu:
  * "bảng đã khoá thì không đổi" — trigger CSDL (``app/models/admission_quota_ddl.py``); kiểm trạng thái ở đây chỉ để
    trả 409 rõ trước khi ghi (lớp phụ);
  * ràng buộc dữ liệu (trần ≥ 0, mã nhóm không trùng trong năm, một ngành một nhóm, cùng năm) — CHECK / UNIQUE / khoá
    ngoại ghép trong CSDL; kiểm ở đây để báo đủ danh sách sai trong MỘT lần (lớp phụ);
  * ai được làm — Casbin + ``deps.require_quota_table_admin`` (chỉ Admin).

THỨ TỰ KHOÁ (một giao dịch): khoá năm ``pg_advisory_xact_lock(REVIEW_YEAR_NS, năm)`` → [GĐ2-F1] ``FOR SHARE`` MỌI học vụ của
năm (+ học vụ thành viên gửi lên), id tăng dần, MỘT câu (:func:`read_quota_fingerprint`) → học vụ sẽ đổi chỉ tiêu ``FOR UPDATE``
(``quota_occupancy_service.lock_quota_cells``, id tăng dần, MỘT câu — chỉ NÂNG khoá trên dòng đã giữ ``FOR SHARE``, không lấy
dòng mới xen giữa) → dòng ``admission_quota_table`` ``FOR UPDATE``. Học vụ TRƯỚC bảng: đường sửa chỉ tiêu có sẵn
(``PATCH /api/admin/academic-info/{id}`` → ``organization_service.update_academic_info``) khoá dòng học vụ (UPDATE) rồi trigger
khoá dòng bảng ``FOR SHARE`` — cùng chiều ⇒ không vòng chờ. Khoá bảng: khoá năm → ``FOR SHARE`` học vụ của năm → dòng bảng.
Mở khoá chỉ khoá năm + dòng bảng.

[GĐ2-F1 — điểm chặn Codex] DẤU CHỈ TIÊU (``quota_fingerprint``): đường sửa học vụ cũ đổi ``annual_admission_quota`` mà KHÔNG
tăng ``version`` của bảng ⇒ chỉ ``version`` không đỡ được "A mở bảng, B sửa ở trang cũ, A lưu bản cũ ⇒ ghi đè B" (kể cả năm
CHƯA có bảng, ``version`` 0). GET trả dấu = băm (:func:`quota_fingerprint_of`) của (id, chỉ tiêu) MỌI học vụ của năm (NULL ≠ 0);
PUT / khoá BẮT BUỘC gửi lại dấu lúc mở; dịch vụ đọc lại các dòng ấy ``FOR SHARE`` SAU khoá năm, TRƯỚC khi ghi — lệnh sửa cũ
đang dở phải commit xong trước rồi mới đọc giá trị mới — lệch ⇒ 409 ``quota_table_stale``. ``FOR SHARE`` chặn cả lệnh sửa đang
dở (``UPDATE`` giữ khoá dòng xung đột ``FOR SHARE``) lẫn lệnh sửa đến SAU (``UPDATE`` chờ tới khi ta commit ⇒ giá trị của họ nằm
SAU bản ta ghi, không bị đè).

Vết: mỗi lần sửa / khoá / mở khoá một dòng ``entity_audit_log`` (``entity_type='admission_quota_table'``, ``entity_id`` =
năm, người, giờ, lý do mở khoá) — cùng giao dịch. Log ứng dụng chỉ năm + số đếm.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog
from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.advisory_lock_keys import REVIEW_YEAR_NS
from app.models.admission_quota_table import QUOTA_TABLE_DRAFT, QUOTA_TABLE_LOCKED
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import ConflictError, ResourceNotFoundError, ValidationError

log = structlog.get_logger(__name__)

AUDIT_ENTITY = "admission_quota_table"

#: Câu báo theo mã lý do (mã tiếng Anh — quy ước owner 17-11).
MESSAGES: Dict[str, str] = {
    "quota_table_stale": (
        "Bảng chỉ tiêu hoặc chỉ tiêu ngành của năm đã được sửa ở nơi khác (bảng này hoặc trang cấu hình học vụ) sau khi bạn "
        "mở — hãy tải lại rồi làm lại."
    ),
    "quota_table_locked": "Bảng chỉ tiêu năm này đã khoá — Admin mở khoá (có lý do) trước khi sửa.",
    "quota_table_already_locked": "Bảng chỉ tiêu năm này đã khoá rồi.",
    "quota_table_not_locked": "Bảng chỉ tiêu năm này chưa khoá — không có gì để mở khoá.",
    "quota_table_member_quota_missing": (
        "Có ngành trong bảng chưa có chỉ tiêu năm — nhập chỉ tiêu cho mọi ngành thành viên trước khi khoá."
    ),
}


#: GĐ2-F1 — thao tác trên bảng ĐANG CÓ của năm (giao diện hiện nút theo ``available_actions`` của phản hồi).
ACTION_EDIT = "edit"
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"


def quota_table_actions(status: str) -> List[str]:
    """GĐ2-F1 — MỘT nguồn cho cờ ``available_actions`` của phản hồi VÀ cổng trạng thái của ``replace_quota_table`` (sửa),
    ``lock_quota_table`` (khoá), ``unlock_quota_table`` (mở khoá): bảng ``draft`` ⇒ sửa + khoá; ``locked`` ⇒ chỉ mở khoá.
    Năm CHƯA có bảng không qua hàm này (GET 404; PUT ``version`` 0 tạo mới). GĐ2-C thêm điều kiện mở khoá (năm có lần xét
    đã khoá) thì thêm VÀO ĐÂY để nút và cổng đổi cùng nhau."""
    if status == QUOTA_TABLE_LOCKED:
        return [ACTION_UNLOCK]
    if status == QUOTA_TABLE_DRAFT:
        return [ACTION_EDIT, ACTION_LOCK]
    return []


class QuotaTableConflict(ConflictError):
    """409 có mã lý do (``reason_code``) + dữ liệu công khai (chỉ id / số)."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(
            detail=MESSAGES.get(reason_code, reason_code),
            public_payload={"reason_code": reason_code, **(payload or {})},
        )
        self.reason_code = reason_code
        self.error_code = reason_code.upper()


def _not_found(academic_year: int, quota_fingerprint: Optional[str] = None) -> ResourceNotFoundError:
    payload: Dict[str, Any] = {"reason_code": "quota_table_not_found"}
    if quota_fingerprint is not None:
        # GĐ2-F1: năm CHƯA có bảng vẫn có dấu chỉ tiêu — giao diện gửi lại khi tạo bảng (``version`` 0).
        payload["quota_fingerprint"] = quota_fingerprint
    return ResourceNotFoundError(detail="Năm %d chưa có bảng chỉ tiêu." % academic_year, public_payload=payload)


#: GĐ2-F1 — tiền tố phiên bản công thức dấu chỉ tiêu (đổi công thức ⇒ đổi tiền tố ⇒ mọi dấu cũ lệch — an toàn).
QUOTA_FINGERPRINT_PREFIX = "qfp-v1"


def quota_fingerprint_of(rows: Iterable[Tuple[int, Optional[int]]]) -> str:
    """GĐ2-F1 — MỘT hàm băm ổn định cho dấu chỉ tiêu (dùng cho GET và cho kiểm ở PUT / khoá): sha256 hex của danh sách
    ``(offering_academic_info.id, annual_admission_quota)`` đã sắp theo id. NULL ghi là ``null`` — KHÁC ``0`` (trống ≠ 0,
    quyết định owner 19-11 câu 4)."""
    phan = []
    for oai_id, quota in sorted(((int(i), q) for i, q in rows), key=lambda x: x[0]):
        phan.append("%d=%s" % (oai_id, "null" if quota is None else "%d" % int(quota)))
    return hashlib.sha256(("%s|%s" % (QUOTA_FINGERPRINT_PREFIX, ",".join(phan))).encode("ascii")).hexdigest()


async def read_quota_fingerprint(
    db: AsyncSession, academic_year: int, *, lock: bool, also_lock_ids: Iterable[int] = ()
) -> str:
    """GĐ2-F1 — dấu chỉ tiêu của năm, đọc từ CSDL: MỌI dòng ``offering_academic_info`` có ``academic_year = năm`` (kể cả đã
    xoá mềm; học vụ mới / dời năm cũng làm dấu đổi). ``lock=True`` ⇒ MỘT câu ``FOR SHARE`` id tăng dần, gồm thêm
    ``also_lock_ids`` (thành viên gửi lên — có thể khác năm, dịch vụ báo 400 sau) để bước ``lock_quota_cells`` sau đó chỉ NÂNG
    khoá trên dòng đã giữ, không lấy dòng mới xen giữa ⇒ không vòng chờ với giao dịch khoá học vụ theo id tăng dần. Dấu chỉ
    tính dòng có năm = ``năm`` theo giá trị đọc SAU khoá (dòng vừa bị dời năm không còn tính)."""
    oai = models.OfferingAcademicInfo
    extra = sorted({int(x) for x in also_lock_ids})
    cond = oai.academic_year == academic_year
    if extra:
        cond = or_(cond, oai.id.in_(extra))
    stmt = select(oai.id, oai.academic_year, oai.annual_admission_quota).where(cond).order_by(oai.id)
    if lock:
        stmt = stmt.with_for_update(read=True)
    rows = (await db.execute(stmt)).all()
    return quota_fingerprint_of((r.id, r.annual_admission_quota) for r in rows if r.academic_year == academic_year)


def _check_quota_fingerprint(expected: str, current: str, *, current_version: int) -> None:
    """Dấu gửi lên (lúc mở) ≠ dấu đọc lại dưới khoá ⇒ chỉ tiêu ngành của năm đã đổi ở nơi khác ⇒ 409, không ghi gì."""
    if expected != current:
        raise QuotaTableConflict("quota_table_stale", {"current_version": int(current_version)})


async def lock_review_year(db: AsyncSession, academic_year: int) -> None:
    """"Khoá năm" của GĐ2 (``REVIEW_YEAR_NS``) — khoá GIAO DỊCH, nhả khi commit / rollback. Lấy TRƯỚC mọi khoá dòng."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": REVIEW_YEAR_NS, "k": int(academic_year)}
    )


async def _table_for_update(db: AsyncSession, academic_year: int) -> Optional[models.AdmissionQuotaTable]:
    t = models.AdmissionQuotaTable
    return (
        await db.execute(
            select(t)
            .where(t.academic_year == academic_year)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _check_version(table: Optional[models.AdmissionQuotaTable], expected: int) -> None:
    current = 0 if table is None else int(table.version)
    if current != int(expected):
        raise QuotaTableConflict("quota_table_stale", {"current_version": current})


async def _audit(db: AsyncSession, academic_year: int, action: str, actor_id: int, *, changes=None, reason=None):
    from app.services.audit_service import log_audit

    await log_audit(
        db,
        AUDIT_ENTITY,
        academic_year,
        action,
        actor_user_id=actor_id,
        changes=changes,
        reason=reason,
        source="api",
    )


# ═══════════════════════════════ đọc ═══════════════════════════════════════════════════════
async def get_quota_table(db: AsyncSession, academic_year: int) -> Dict[str, Any]:
    """Bảng chỉ tiêu của năm + nhóm + thành viên + chỉ tiêu ngành hiện tại + số chỗ đã dùng của từng nhóm (THAM KHẢO —
    :func:`quota_occupancy_service.count_by_group`). Năm chưa có bảng ⇒ 404."""
    t = models.AdmissionQuotaTable
    table = (await db.execute(select(t).where(t.academic_year == academic_year))).scalar_one_or_none()
    quota_fingerprint = await read_quota_fingerprint(db, academic_year, lock=False)
    if table is None:
        raise _not_found(academic_year, quota_fingerprint)
    g, m = models.AdmissionQuotaGroup, models.AdmissionQuotaGroupMember
    oai, po, mp = models.OfferingAcademicInfo, models.ProgramOffering, models.MajorProgram
    groups = (
        await db.execute(select(g).where(g.academic_year == academic_year).order_by(g.code, g.id))
    ).scalars().all()
    member_rows = (
        await db.execute(
            select(
                m.group_id,
                m.offering_academic_info_id,
                oai.offering_id,
                oai.annual_admission_quota,
                mp.code.label("major_code"),
                mp.name.label("major_name"),
                po.offering_type,
            )
            .join(oai, oai.id == m.offering_academic_info_id)
            .outerjoin(po, po.id == oai.offering_id)
            .outerjoin(mp, mp.id == po.program_id)
            .where(m.academic_year == academic_year)
            .order_by(m.group_id, m.offering_academic_info_id)
        )
    ).all()
    by_group: Dict[int, List[Dict[str, Any]]] = {}
    for r in member_rows:
        by_group.setdefault(r.group_id, []).append(
            {
                "offering_academic_info_id": r.offering_academic_info_id,
                "offering_id": r.offering_id,
                "major_code": r.major_code,
                "major_name": r.major_name,
                "offering_type": r.offering_type,
                "annual_admission_quota": r.annual_admission_quota,
            }
        )
    out_groups = []
    for grp in groups:
        out_groups.append(
            {
                "id": grp.id,
                "code": grp.code,
                "name": grp.name,
                "ceiling": grp.ceiling,
                "usage": await qos.count_by_group(db, group_id=grp.id),
                "members": by_group.get(grp.id, []),
            }
        )
    return {
        "academic_year": table.academic_year,
        "status": table.status,
        "version": table.version,
        "locked_by_user_id": table.locked_by_user_id,
        "locked_at": table.locked_at,
        "available_actions": quota_table_actions(table.status),
        "quota_fingerprint": quota_fingerprint,
        "groups": out_groups,
    }


# ═══════════════════════════════ sửa ═══════════════════════════════════════════════════════
def _validate_payload_shape(groups) -> None:
    """Lỗi tự thân của thân request (không cần CSDL): mã nhóm trùng, một ngành ở hai chỗ. Báo ĐỦ danh sách một lần."""
    seen_codes, dup_codes = set(), set()
    seen_ai, dup_ai = set(), set()
    for grp in groups:
        if grp.code in seen_codes:
            dup_codes.add(grp.code)
        seen_codes.add(grp.code)
        for mem in grp.members:
            if mem.offering_academic_info_id in seen_ai:
                dup_ai.add(mem.offering_academic_info_id)
            seen_ai.add(mem.offering_academic_info_id)
    if dup_codes or dup_ai:
        raise ValidationError(
            detail="Bảng chỉ tiêu có mã nhóm trùng hoặc một ngành nằm ở hơn một chỗ.",
            public_payload={
                "reason_code": "quota_table_duplicate",
                "duplicate_group_codes": sorted(dup_codes),
                "duplicate_offering_academic_info_ids": sorted(dup_ai),
            },
        )


async def replace_quota_table(
    db: AsyncSession, academic_year: int, payload, *, actor_id: int
) -> Dict[str, Any]:
    """Thay TOÀN BỘ nội dung bảng chỉ tiêu ``draft`` của năm (tạo bảng nếu chưa có và ``payload.version == 0``).

    Nhóm giữ ``id`` theo mã (đổi tên / trần tại chỗ), nhóm không còn trong thân ⇒ xoá; thành viên thay hết; chỉ tiêu ngành
    của thành viên ghi vào ``offering_academic_info.annual_admission_quota`` (chỉ dòng có đổi)."""
    groups = list(payload.groups)
    _validate_payload_shape(groups)
    want: Dict[int, int] = {
        mem.offering_academic_info_id: mem.annual_admission_quota for grp in groups for mem in grp.members
    }

    # 1. Khoá năm → [GĐ2-F1] FOR SHARE học vụ của năm + thành viên (dấu chỉ tiêu) → học vụ thành viên FOR UPDATE (id tăng
    #    dần, chỉ nâng khoá) → dòng bảng.
    await lock_review_year(db, academic_year)
    current_fp = await read_quota_fingerprint(db, academic_year, lock=True, also_lock_ids=want.keys())
    await qos.lock_quota_cells(db, want.keys(), ())
    table = await _table_for_update(db, academic_year)
    _check_version(table, payload.version)
    _check_quota_fingerprint(
        payload.quota_fingerprint, current_fp, current_version=0 if table is None else int(table.version)
    )
    if table is not None and ACTION_EDIT not in quota_table_actions(table.status):
        raise QuotaTableConflict("quota_table_locked")

    # 2. Học vụ phải có thật, chưa xoá mềm, ĐÚNG năm của bảng (đọc lại dưới khoá).
    oai = models.OfferingAcademicInfo
    rows = {}
    if want:
        rows = {
            r.id: r
            for r in (
                await db.execute(
                    select(oai).where(oai.id.in_(sorted(want))).execution_options(populate_existing=True)
                )
            ).scalars()
        }
    bad = sorted(
        i for i in want if i not in rows or rows[i].is_deleted or rows[i].academic_year != academic_year
    )
    if bad:
        raise ValidationError(
            detail="Có ngành không thuộc năm %d (không tồn tại, đã xoá, hoặc khác năm)." % academic_year,
            public_payload={"reason_code": "quota_table_bad_member", "offering_academic_info_ids": bad},
        )

    now = datetime.now(timezone.utc)
    if table is None:
        table = models.AdmissionQuotaTable(academic_year=academic_year, status=QUOTA_TABLE_DRAFT, version=1)
        db.add(table)
        await db.flush()
        action = "created"
    else:
        table.version = int(table.version) + 1
        table.updated_at = now
        action = "updated"

    # 3. Nhóm (giữ id theo mã) + thành viên (thay hết).
    g, m = models.AdmissionQuotaGroup, models.AdmissionQuotaGroupMember
    await db.execute(delete(m).where(m.academic_year == academic_year))
    existing = {
        x.code: x
        for x in (
            await db.execute(select(g).where(g.academic_year == academic_year).execution_options(populate_existing=True))
        ).scalars()
    }
    keep = {grp.code for grp in groups}
    gone = [x.id for c, x in existing.items() if c not in keep]
    if gone:
        await db.execute(delete(g).where(g.id.in_(gone)))
    for grp in groups:
        row = existing.get(grp.code)
        if row is None:
            row = g(academic_year=academic_year, code=grp.code, name=grp.name, ceiling=grp.ceiling)
            db.add(row)
        else:
            row.name, row.ceiling = grp.name, grp.ceiling
        await db.flush()
        for mem in grp.members:
            db.add(m(group_id=row.id, offering_academic_info_id=mem.offering_academic_info_id, academic_year=academic_year))

    # 4. Chỉ tiêu ngành (cột có sẵn) — chỉ dòng có đổi.
    changed = 0
    for ai_id, quota in sorted(want.items()):
        r = rows[ai_id]
        if r.annual_admission_quota != quota:
            r.annual_admission_quota = quota
            r.updated_by_user_id = actor_id
            changed += 1
    await db.flush()

    figures = {"groups": len(groups), "members": len(want), "quota_changed": changed, "version": table.version}
    await _audit(db, academic_year, action, actor_id, changes={"figures": {"old": None, "new": figures}})
    log.info("admission_quota_table_saved", academic_year=academic_year, actor_id=actor_id, **figures)
    return await get_quota_table(db, academic_year)


# ═══════════════════════════════ khoá / mở khoá ════════════════════════════════════════════
async def lock_quota_table(
    db: AsyncSession, academic_year: int, *, expected_version: int, expected_quota_fingerprint: str, actor_id: int
) -> Dict[str, Any]:
    """``draft`` → ``locked``. Điều kiện kỹ thuật: mọi ngành thành viên có chỉ tiêu năm (thiếu ⇒ 409 nêu id) — ngành thiếu
    chỉ tiêu không xét được (đặc tả §5.4 bước 1), khoá bảng như vậy chỉ dời lỗi sang lúc xét.

    GĐ2-F1: khoá đóng băng ĐÚNG các chỉ tiêu người khoá đã xem ⇒ đòi dấu chỉ tiêu lúc mở (đọc lại ``FOR SHARE`` sau khoá năm,
    TRƯỚC dòng bảng — cùng chiều "học vụ trước bảng" với trigger)."""
    await lock_review_year(db, academic_year)
    current_fp = await read_quota_fingerprint(db, academic_year, lock=True)
    table = await _table_for_update(db, academic_year)
    if table is None:
        raise _not_found(academic_year)
    _check_version(table, expected_version)
    _check_quota_fingerprint(expected_quota_fingerprint, current_fp, current_version=int(table.version))
    if ACTION_LOCK not in quota_table_actions(table.status):
        raise QuotaTableConflict("quota_table_already_locked")
    m, oai = models.AdmissionQuotaGroupMember, models.OfferingAcademicInfo
    missing = sorted(
        (
            await db.execute(
                select(m.offering_academic_info_id)
                .join(oai, oai.id == m.offering_academic_info_id)
                .where(m.academic_year == academic_year, oai.annual_admission_quota.is_(None))
            )
        ).scalars()
    )
    if missing:
        raise QuotaTableConflict("quota_table_member_quota_missing", {"offering_academic_info_ids": missing})
    now = datetime.now(timezone.utc)
    table.status = QUOTA_TABLE_LOCKED
    table.locked_by_user_id = actor_id
    table.locked_at = now
    table.version = int(table.version) + 1
    table.updated_at = now
    await db.flush()
    await _audit(db, academic_year, "locked", actor_id, changes={"status": {"old": QUOTA_TABLE_DRAFT, "new": QUOTA_TABLE_LOCKED}})
    log.info("admission_quota_table_locked", academic_year=academic_year, actor_id=actor_id, version=table.version)
    return await get_quota_table(db, academic_year)


async def unlock_quota_table(
    db: AsyncSession, academic_year: int, *, expected_version: int, reason: str, actor_id: int
) -> Dict[str, Any]:
    """``locked`` → ``draft``, lý do BẮT BUỘC (ca biên D14), lưu vết. GĐ2-C sẽ thêm: không mở khoá khi năm có lần xét đã
    khoá (giữ chỗ)."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(detail="Lý do mở khoá là bắt buộc.")
    await lock_review_year(db, academic_year)
    table = await _table_for_update(db, academic_year)
    if table is None:
        raise _not_found(academic_year)
    _check_version(table, expected_version)
    if ACTION_UNLOCK not in quota_table_actions(table.status):
        raise QuotaTableConflict("quota_table_not_locked")
    now = datetime.now(timezone.utc)
    table.status = QUOTA_TABLE_DRAFT
    table.locked_by_user_id = None
    table.locked_at = None
    table.version = int(table.version) + 1
    table.updated_at = now
    await db.flush()
    await _audit(
        db, academic_year, "unlocked", actor_id,
        changes={"status": {"old": QUOTA_TABLE_LOCKED, "new": QUOTA_TABLE_DRAFT}}, reason=reason,
    )
    log.info("admission_quota_table_unlocked", academic_year=academic_year, actor_id=actor_id, version=table.version)
    return await get_quota_table(db, academic_year)
