"""K4 — sổ phân loại MỌI khoá ngoại tới ``user.id`` + hàm chung kiểm "xoá được tài khoản không" (GĐ1b).

Đặc tả GĐ1b bản 3.6 §4.3 (K4-A, K4b = C, K4c, K4d), §4.5 mục 4, §9. Đo mốc nền V5 (17-11, mã ``221a757d``): xoá cán bộ có
``assignment_log`` / tư vấn ⇒ **500** (NOT NULL khi ORM tự gán NULL); có lead đang giao ⇒ lead bị **gỡ âm thầm**.

MỘT nguồn: :data:`USER_REFERENCES`. ``tests/api/test_gd1b_xoa_tai_khoan.py`` đọc ``pg_constraint`` của lược đồ THẬT và
khẳng định tập (bảng, cột) trùng khớp — thêm khoá ngoại tới ``user`` mà quên phân loại ⇒ đỏ. Mỗi cột đúng MỘT nhóm:

* ``BLOCK_ACTOR`` — người dùng đã từng THỰC HIỆN thao tác nghiệp vụ ⇒ 409, khuyên khoá tài khoản.
* ``BLOCK_ASSIGNMENT_HISTORY`` — người dùng đã từng ĐƯỢC GIAO việc ⇒ 409.
* ``CURRENT_STATE`` — người dùng ĐANG phụ trách việc (K4b = C) ⇒ 409 nêu số lượng; KHÔNG gỡ âm thầm.
* ``OWNED_CASCADE`` — dòng chính người dùng sở hữu, không phải lịch sử nghiệp vụ ⇒ xoá cùng người dùng (CSDL CASCADE,
  hoặc hàm chung xoá TƯỜNG MINH sau khi qua kiểm).
* ``IGNORE`` — cột nullable ``SET NULL`` không phải lịch sử nghiệp vụ ⇒ để CSDL xử lý. Cột NO ACTION / RESTRICT /
  NOT NULL KHÔNG được ở nhóm này (test khoá).

Tầng chủ sở hữu bất biến "không xoá tài khoản đã từng thao tác" = :func:`assert_user_deletable` (dịch vụ). ``RESTRICT``
trên các bảng GĐ1b là lớp phòng thủ thêm.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.exceptions import BusinessRuleViolation, ConflictError


class UserRefGroup(str, Enum):
    BLOCK_ACTOR = "BLOCK_ACTOR"
    BLOCK_ASSIGNMENT_HISTORY = "BLOCK_ASSIGNMENT_HISTORY"
    CURRENT_STATE = "CURRENT_STATE"
    OWNED_CASCADE = "OWNED_CASCADE"
    IGNORE = "IGNORE"


@dataclass(frozen=True)
class UserRef:
    table: str
    column: str
    group: UserRefGroup
    #: Vị từ SQL thêm cho phép kiểm chặn (vd lô: chỉ lô ĐÃ chạy mới là thao tác).
    block_where: Optional[str] = None
    #: Dòng hàm chung xoá TƯỜNG MINH sau khi qua kiểm (``"TRUE"`` = mọi dòng của người dùng). ``None`` ⇒ không xoá tay.
    delete_where: Optional[str] = None
    #: Nhãn đếm cho câu báo ``CURRENT_STATE``.
    current_label: Optional[str] = None


A = UserRefGroup.BLOCK_ACTOR
H = UserRefGroup.BLOCK_ASSIGNMENT_HISTORY
C = UserRefGroup.CURRENT_STATE
O = UserRefGroup.OWNED_CASCADE
I = UserRefGroup.IGNORE

#: MỘT nguồn — xếp theo (bảng, cột). Đo 17-11: 94 cột cũ + 8 cột GĐ1b = 102; GĐ2-A thêm 1 = 103.
USER_REFERENCES: Tuple[UserRef, ...] = (
    UserRef("_admission_backfill_exceptions", "resolved_by_user_id", A),
    UserRef("accounting_period", "closed_by_id", A),
    UserRef("admission_path", "activated_by", A),
    UserRef("admission_profile", "applicable_circular_set_by_id", A),
    UserRef("admission_profile", "approved_by_id", A),
    UserRef("admission_profile", "assigned_reviewer_id", C, current_label="đang nhận xét {n} hồ sơ"),
    UserRef("admission_profile", "confirmed_by_id", A),
    UserRef("admission_profile", "dropped_by_id", A),
    UserRef("admission_profile", "overridden_by_id", A),
    UserRef("admission_profile", "rejected_by_id", A),
    UserRef("admission_profile", "resubmitted_by_id", A),
    UserRef("admission_profile", "revision_requested_by_id", A),
    UserRef("admission_profile_status_history", "transitioned_by_user_id", A),
    # GĐ2-A: người khoá bảng chỉ tiêu năm (RESTRICT). Mở khoá xoá cột này — vết còn ở ``entity_audit_log``.
    UserRef("admission_quota_table", "locked_by_user_id", A),
    UserRef("assignment_decision_log", "assigned_officer_id", H),
    UserRef("assignment_log", "officer_id", H),
    UserRef("collaborator", "approved_by_id", A),
    UserRef("collaborator", "managed_by_officer_id", C, current_label="đang quản lý {n} cộng tác viên"),
    UserRef("collaborator", "user_id", C, current_label="đang là tài khoản của {n} hồ sơ cộng tác viên"),
    UserRef("commission_policy", "created_by_id", A),
    UserRef("commission_record", "approved_by_id", A),
    UserRef("commission_record", "cancelled_by_id", A),
    UserRef("commission_record", "paid_by_id", A),
    UserRef("commission_record", "rejected_by_id", A),
    UserRef("consultation", "officer_id", A),
    UserRef("council_decision_submission", "nguoi_tao_id", A),
    UserRef("council_document_set", "nguoi_tao_id", A),
    UserRef("council_document_template", "nguoi_tai_id", A),
    UserRef("document_audit_log", "actor_user_id", A),
    # Lô ĐÃ chạy = thao tác (chặn); bản xem trước chưa chạy = của riêng người dùng (xoá tường minh) — §4.3, §5.8.
    UserRef(
        "document_bulk_batch", "actor_user_id", A,
        block_where="status <> 'previewed'", delete_where="status = 'previewed'",
    ),
    UserRef("document_bulk_batch", "finalized_by_user_id", A),
    UserRef("document_cross_review_grant", "granted_by_user_id", A),
    UserRef("document_cross_review_grant", "grantee_user_id", A),
    UserRef("document_cross_review_grant", "revoked_by_user_id", A),
    UserRef("document_download_log", "actor_user_id", A),
    UserRef("document_evidence_file", "verified_by_user_id", A),
    UserRef("enrollment_letter", "generated_by_id", A),
    UserRef("entity_audit_log", "actor_user_id", A),
    UserRef("fee", "calculated_by_id", A),
    UserRef("holiday_calendar", "created_by", A),
    UserRef("invoice", "cancelled_by_id", A),
    UserRef("invoice", "issued_by_id", A),
    UserRef("kpi_config", "officer_id", O),
    UserRef("kpi_plan", "created_by", A),
    UserRef("kpi_plan", "officer_id", O),
    UserRef("kpi_plan_month", "overridden_by", A),
    UserRef("kpi_target", "officer_id", O),
    UserRef("lead", "assigned_officer_id", C, current_label="đang phụ trách {n} lead"),
    UserRef("lead_claim", "reviewed_by_id", A),
    UserRef("lead_reopen_request", "requested_by_id", A),
    UserRef("lead_reopen_request", "reviewed_by_id", A),
    UserRef("lead_status_history", "changed_by_user_id", A),
    UserRef("lead_status_history", "new_assigned_officer_id", H),
    UserRef("lead_status_history", "old_assigned_officer_id", H),
    UserRef("login_history", "user_id", O),
    UserRef("notification", "user_id", O, delete_where="TRUE"),
    UserRef("notification_consent", "granted_by", A),
    UserRef("notification_consent_history", "performed_by", A),
    UserRef("notification_delivery", "user_id", I),
    UserRef("notification_preference", "user_id", O, delete_where="TRUE"),
    UserRef("notification_template", "created_by", A),
    UserRef("offering_academic_info", "created_by_user_id", A),
    UserRef("offering_academic_info", "updated_by_user_id", A),
    UserRef("offering_admission_round", "extended_by_user_id", A),
    UserRef("offering_semester_tuition", "created_by_user_id", A),
    UserRef("offering_semester_tuition", "updated_by_user_id", A),
    UserRef("overpayment_record", "resolved_by_id", A),
    UserRef("payment", "created_by_id", A),
    UserRef("payment", "rejected_by_id", A),
    UserRef("payment", "verified_by_id", A),
    UserRef("payment_import_batch", "created_by_id", A),
    UserRef("payment_transaction", "performed_by_id", A),
    UserRef("priority_audit_log", "actor_id", A),
    UserRef("profile_document", "paper_submitted_by", A),
    UserRef("profile_document", "rejected_by", A),
    UserRef("profile_document", "uploaded_by", A),
    UserRef("profile_document", "verified_by", A),
    UserRef("refund_request", "approved_by_id", A),
    UserRef("refund_request", "rejected_by_id", A),
    UserRef("refund_request", "requested_by_id", A),
    UserRef("sms_campaign", "consent_checked_by_id", A),
    UserRef("sms_campaign", "created_by_id", A),
    UserRef("sms_campaign", "dnc_checked_by_id", A),
    UserRef("sms_campaign", "optout_channel_checked_by_id", A),
    UserRef("sms_campaign_export_batch", "generated_by_id", A),
    UserRef("sms_consult_link", "created_by_id", A),
    UserRef("sms_contact", "created_by_id", A),
    UserRef("sms_contact_group", "created_by_id", A),
    UserRef("sms_contact_group_member", "added_by_id", A),
    UserRef("sms_contact_import_batch", "uploaded_by_id", A),
    UserRef("sms_marketing_consent_event", "recorded_by_id", A),
    UserRef("sms_opt_out", "revoked_by_id", A),
    UserRef("staff_zalo_bot_link", "user_id", O),
    UserRef("system_config", "updated_by_user_id", A),
    UserRef("trusted_device", "user_id", O),
    UserRef("tuition_discount_policy", "created_by_user_id", A),
    UserRef("tuition_discount_policy", "updated_by_user_id", A),
    UserRef("user_activity_log", "actor_id", A),
    # Tài khoản BỊ thao tác (tạo / sửa / xoá — chính lệnh xoá ghi dòng này TRƯỚC khi xoá): không phải "đã từng thao tác".
    # Khoá ngoại đổi sang SET NULL ở migration gd1b20261117 (trước đây ORM tự gán NULL qua ``User.activities_received``).
    UserRef("user_activity_log", "target_user_id", I),
    UserRef("user_session", "user_id", O),
    UserRef("user_unit_assignment", "assigned_by_user_id", A),
    UserRef("user_unit_assignment", "user_id", O),
    UserRef("vn_school_kv_assignment", "created_by", A),
)

MESSAGE_BLOCK_ACTOR = "Tài khoản đã từng thao tác trên hồ sơ / giấy tờ — hãy khoá tài khoản thay vì xoá"
MESSAGE_BLOCK_ASSIGNMENT_HISTORY = "Tài khoản đã từng được giao việc — hãy khoá tài khoản"
MESSAGE_CURRENT_STATE_SUFFIX = "chuyển giao trước"

ERROR_CODE_CURRENT_STATE = "USER_HAS_CURRENT_WORK"
ERROR_CODE_BLOCK_ACTOR = "USER_HAS_ACTIVITY"
ERROR_CODE_BLOCK_ASSIGNMENT_HISTORY = "USER_HAS_ASSIGNMENT_HISTORY"


class UserNotDeletable(ConflictError):
    """409 — ít nhất một tài khoản trong lệnh không xoá được; KHÔNG một câu ghi nào đã chạy (§4.3 bước 4)."""


def _q(identifier: str) -> str:
    """Định danh SQL lấy từ :data:`USER_REFERENCES` (hằng trong mã) — bọc ngoặc kép."""
    return '"%s"' % identifier.replace('"', '""')


def _check_sql(refs: Sequence[UserRef]) -> str:
    parts = []
    for i, r in enumerate(refs):
        cond = "%s = ANY(:ids)" % _q(r.column)
        if r.block_where:
            cond += " AND (%s)" % r.block_where
        parts.append(
            "SELECT %d AS ref_index, %s AS user_id, count(*) AS n FROM %s WHERE %s GROUP BY %s"
            % (i, _q(r.column), _q(r.table), cond, _q(r.column))
        )
    return "\nUNION ALL\n".join(parts)


_CHECKED_REFS: Tuple[UserRef, ...] = tuple(
    r for r in USER_REFERENCES if r.group in (A, H, C)
)
_CHECK_SQL = _check_sql(_CHECKED_REFS)
_EXPLICIT_DELETES: Tuple[UserRef, ...] = tuple(r for r in USER_REFERENCES if r.delete_where)


def _build_conflict(found: Dict[int, List[Tuple[UserRef, int]]]) -> UserNotDeletable:
    lines = []
    payload = []
    codes = set()
    for uid in sorted(found):
        items = found[uid]
        current = [(r, n) for r, n in items if r.group is C]
        reasons = []
        if current:
            reasons.append(
                "Đang " + " / ".join(r.current_label.format(n=n).removeprefix("đang ") for r, n in current)
                + " — " + MESSAGE_CURRENT_STATE_SUFFIX
            )
            codes.add(ERROR_CODE_CURRENT_STATE)
        if any(r.group is A for r, _ in items):
            reasons.append(MESSAGE_BLOCK_ACTOR)
            codes.add(ERROR_CODE_BLOCK_ACTOR)
        if any(r.group is H for r, _ in items):
            reasons.append(MESSAGE_BLOCK_ASSIGNMENT_HISTORY)
            codes.add(ERROR_CODE_BLOCK_ASSIGNMENT_HISTORY)
        lines.append("Tài khoản #%d: %s" % (uid, "; ".join(reasons)))
        payload.append(
            {
                "user_id": uid,
                "reasons": sorted({r.group.value for r, _ in items}),
                "current_work": {"%s.%s" % (r.table, r.column): n for r, n in current},
            }
        )
    exc = UserNotDeletable(
        detail="Không xoá được tài khoản. " + " | ".join(lines),
        public_payload={"blocked_users": payload},
    )
    for code in (ERROR_CODE_CURRENT_STATE, ERROR_CODE_BLOCK_ACTOR, ERROR_CODE_BLOCK_ASSIGNMENT_HISTORY):
        if code in codes:
            exc.error_code = code
            break
    return exc


async def assert_user_deletable(db: AsyncSession, user_ids: Iterable[int], actor_id: Optional[int]) -> List[int]:
    """Hàm chung cho ``delete_user`` VÀ ``perform_bulk_action`` (§4.3).

    1. Bỏ trùng, xếp id, bỏ chính người bấm.
    2. Khoá (người bị xoá ∪ admin đang hoạt động, nếu có người bị xoá là admin đang hoạt động) ``FOR UPDATE`` — hai lệnh xoá
       admin chéo không bế tắc. PR-B lượt 5 (owner 22-11, K4 ↔ K4): người bấm (khoá ngoại ``user_activity_log.actor_id``
       của nhật ký router ghi SAU bước này) vào CÙNG thứ tự id tăng, ``FOR KEY SHARE`` — qua :func:`lock_users_in_id_order`
       (MỘT nơi giữ thứ tự khoá): (a) ĐỌC không khoá tập cần ``FOR UPDATE`` bằng đúng vị từ cũ, (b) khoá tập ấy ∪ người bấm
       theo id tăng. Người bấm đã nằm trong tập (admin, khi xoá admin) ⇒ chỉ ``FOR UPDATE``, không khoá lại yếu hơn. Tập admin
       đổi giữa (a) và (b) ⇒ phép kiểm "admin hiện tại ⊆ đã khoá" ở bước 3 trả ``ConflictError`` như trước.
    3. Guard "admin cuối" cho CẢ lệnh.
    4. Kiểm mọi cột ``BLOCK_*`` + ``CURRENT_STATE`` — CHỈ ĐỌC. Một người không đạt ⇒ 409 cả lệnh, không câu ghi nào.
    5. Xoá tường minh các dòng ``OWNED_CASCADE`` cần xoá tay. Người gọi ``db.delete`` rồi ``flush``.

    Trả danh sách id sẽ xoá (đã khoá, tồn tại). Id không tồn tại bị bỏ qua (người gọi quyết 404 hay bỏ qua).
    """
    ids = sorted({int(u) for u in user_ids} - ({int(actor_id)} if actor_id is not None else set()))
    if not ids:
        return []

    # (2a) ĐỌC (không khoá) tập cần ``FOR UPDATE`` — đúng vị từ của câu khoá cũ.
    can_khoa = (
        await db.execute(
            text(
                'SELECT id FROM "user" '
                "WHERE id = ANY(:ids) "
                "   OR (role = 'admin' AND status = 'active' AND EXISTS ("
                '       SELECT 1 FROM "user" t WHERE t.id = ANY(:ids) AND t.role = \'admin\' AND t.status = \'active\'))'
            ),
            {"ids": ids},
        )
    ).scalars().all()
    # (2b) khoá theo id TĂNG: tập trên ``FOR UPDATE`` + người bấm ``FOR KEY SHARE`` (nếu ngoài tập). Vai / trạng thái đọc
    # DƯỚI khoá (hàng trả về).
    by_id = await lock_users_in_id_order(db, target_ids=can_khoa, referenced_ids=[actor_id], delete_targets=True)
    targets = [u for u in ids if u in by_id]
    if not targets:
        return []

    target_admins = [u for u in targets if by_id[u].role == "admin" and by_id[u].status == "active"]
    if target_admins:
        # Đọc lại dưới khoá: tập admin đang hoạt động hiện tại phải nằm trọn trong tập đã khoá.
        active_admins = set(
            (
                await db.execute(text("SELECT id FROM \"user\" WHERE role = 'admin' AND status = 'active'"))
            ).scalars()
        )
        if not active_admins.issubset(by_id):
            raise ConflictError(detail="Danh sách quản trị viên vừa thay đổi — hãy thử lại.")
        if len(active_admins - set(target_admins)) < 1:
            raise BusinessRuleViolation(detail="Cannot delete the last active admin user.")

    rows = (await db.execute(text(_CHECK_SQL), {"ids": targets})).all()
    found: Dict[int, List[Tuple[UserRef, int]]] = {}
    for ref_index, uid, n in rows:
        if n:
            found.setdefault(uid, []).append((_CHECKED_REFS[ref_index], int(n)))
    if found:
        raise _build_conflict(found)

    for r in _EXPLICIT_DELETES:
        await db.execute(
            text("DELETE FROM %s WHERE %s = ANY(:ids) AND (%s)" % (_q(r.table), _q(r.column), r.delete_where)),
            {"ids": targets},
        )
    return targets


#: Cột của ``user`` có chỉ mục DUY NHẤT thường (không một phần, không biểu thức) — PostgreSQL coi ``UPDATE`` đổi giá trị cột
#: như thế là "key update" ⇒ dòng phải khoá ``FOR UPDATE`` (không phải ``FOR NO KEY UPDATE``), xung đột cả ``FOR KEY SHARE``
#: của khoá ngoại. ``id`` không bao giờ bị sửa nên không ghi. ``tests/api/test_gd1b_cheo_phan_cong_vai.py`` đọc
#: ``pg_index`` của lược đồ THẬT và khoá tập này (+ ``id``) — thêm cột duy nhất mới mà quên ghi ở đây ⇒ ĐỎ.
USER_KEY_COLUMNS = ("username", "email")


def changes_user_key_columns(user: object, update_data: Dict[str, object]) -> bool:
    """``True`` khi ``update_data`` sẽ ĐỔI THẬT giá trị một cột khoá (``USER_KEY_COLUMNS``) của ``user`` — so giá trị sắp
    ghi (đã chuẩn hoá ở tầng kiểm dữ liệu) với giá trị hiện có của đối tượng; ``None`` = không ghi cột ấy."""
    return any(
        update_data.get(c) is not None and update_data.get(c) != getattr(user, c, None) for c in USER_KEY_COLUMNS
    )


async def lock_users_in_id_order(
    db: AsyncSession,
    *,
    target_ids: Iterable[int],
    referenced_ids: Iterable[Optional[int]] = (),
    delete_targets: bool = False,
    key_update_ids: Iterable[int] = (),
) -> Dict[int, object]:
    """THỨ TỰ KHOÁ DÒNG ``user`` cho mọi đường GHI tài khoản (PR-B lượt 5, Codex 22-11 P2) — cùng chiều K4.

    Đường đổi vai / đơn vị / trạng thái khoá người ĐÍCH rồi GHI dòng có khoá ngoại tới NGƯỜI KHÁC (người thao tác:
    ``user_unit_assignment.assigned_by_user_id``, ``document_cross_review_grant.revoked_by_user_id``, nhật ký; người quản
    lý CTV…). Khoá ngoại tự lấy ``FOR KEY SHARE`` trên dòng người ấy LÚC GHI — tức SAU khi đã giữ người đích, và trong
    vòng lặp nhiều người thì SAU người đích ĐẦU TIÊN được ghi. :func:`assert_user_deletable` khoá ``FOR UPDATE ORDER BY
    id``; người được tham chiếu A có id NHỎ hơn một người đích U ⇒ đường ghi giữ U chờ A, K4 giữ A chờ U ⇒ vòng chờ.

    Luật: khoá TRƯỚC mọi câu ghi, theo id TĂNG trên hợp (người đích ∪ người được tham chiếu) — người đích ``FOR NO KEY
    UPDATE`` (đúng khoá của ``UPDATE "user"`` KHÔNG đổi cột khoá), người được tham chiếu ``FOR KEY SHARE`` (đúng khoá của
    khoá ngoại; chỉ xung đột ``FOR UPDATE``). Sau đó mọi khoá ngoại tới ``user`` của giao dịch trỏ vào dòng ĐÃ giữ, và
    không câu ``UPDATE`` nào phải NÂNG mức khoá ⇒ không chờ thêm dòng ``user`` nào. Người gọi khoá lại từng người trong vòng
    (đọc dưới khoá) là no-op.

    Người đích khoá ``FOR UPDATE`` ngay từ đầu khi (a) ``delete_targets`` hoặc (b) id nằm trong ``key_update_ids`` —
    ``UPDATE`` sắp ĐỔI cột khoá (``USER_KEY_COLUMNS``, vd PUT đổi email; xem :func:`changes_user_key_columns`). PR-B lượt 6
    (Codex 22-11 H1): khoá ``FOR NO KEY UPDATE`` rồi tới lúc ``flush`` PostgreSQL mới NÂNG lên ``FOR UPDATE`` ⇒ phải chờ
    mọi ``FOR KEY SHARE`` đang giữ dòng ấy GIỮA chừng, sau khi đã giữ dòng khác ⇒ vòng chờ (A sửa email U ‖ U sửa email A;
    U xoá A ‖ A sửa email U).

    ``delete_targets=True`` (CHỈ K4 — :func:`assert_user_deletable`, owner 22-11 "K4 ↔ K4"): người đích sắp bị XOÁ ⇒ khoá
    ``FOR UPDATE`` (đúng khoá của ``DELETE``) thay vì ``FOR NO KEY UPDATE``; cùng MỘT vòng id tăng với người được tham
    chiếu (người bấm — khoá ngoại nhật ký) — thứ tự khoá dòng ``user`` chỉ nằm ở hàm này.

    Trả ``{id: (id, role, status)}`` các người đích còn tồn tại (người đích không còn ⇒ bỏ qua, người gọi quyết 404).
    Người được tham chiếu không còn ⇒ bỏ qua, KHÔNG báo lỗi ở đây: phép kiểm sẵn có của người gọi (vd cán bộ quản lý CTV
    không tồn tại ⇒ 404) hoặc chính khoá ngoại lúc ghi quyết như trước — hàm này chỉ đổi THỨ TỰ khoá, không đổi kết quả.
    Không tự xả thay đổi đang chờ (``no_autoflush``): không câu ghi nào chen trước khoá."""
    from app.repositories import document_bulk_repository as bulk_repo

    targets = {int(u) for u in target_ids}
    referenced = {int(u) for u in referenced_ids if u is not None} - targets
    key_update = {int(u) for u in key_update_ids}
    rows: Dict[int, object] = {}
    with db.no_autoflush:
        for uid in sorted(targets | referenced):
            if uid in targets:
                if delete_targets or uid in key_update:
                    row = await bulk_repo.lock_user_for_update(db, uid)
                else:
                    row = await bulk_repo.lock_user_no_key_update(db, uid)
                if row is not None:
                    rows[uid] = row
            else:
                await bulk_repo.lock_user_key_share(db, uid)
    return rows
