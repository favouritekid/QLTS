# app/services/role_service.py
"""
Role Management Service

Handles role assignment, removal, and management operations.
Follows protocol-independent architecture - no HTTP dependencies.

Business Rules:
- Users must always have at least one role
- If last role removed, auto-assign "role:user"
- Database user.role field reflects highest priority role
- Role priority: admin > manager > officer > user
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from app.core.log_redaction import chu_loi_an_toan  # V6 vòng 5: lỗi CSDL ra ngoài log ⇒ tóm tắt
import logging

import casbin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.utils.exceptions import ConflictError, ResourceNotFoundError

log = logging.getLogger(__name__)

# Role priority for determining DB field value (highest to lowest)
#
# Diamond Inheritance Structure:
#                    ┌─────────┐
#                    │  Admin  │  (Level 5)
#                    └────┬────┘
#                      ▲   ▲
#          ┌───────────┘   └───────────┐
#          │                           │
#     ┌────┴─────┐               ┌─────┴────┐
#     │ Manager  │ (Level 4)     │Accountant│ (Level 3.5 for DB display)
#     └────┬─────┘               └─────┬────┘
#          │                           │
#          └───────────┐   ┌───────────┘
#                      ▼   ▼
#                    ┌─────────┐
#                    │ Officer │  (Level 2)
#                    └────┬────┘
#                         │
#                    ┌────┴────┐
#                    │  User   │  (Level 1)
#                    └─────────┘
#
# NOTE: Manager and Accountant are PARALLEL branches (same hierarchy level).
# They have slightly different priorities ONLY for determining which role
# to display in the user.role database field when a user has multiple roles.
# The actual permissions are handled by Casbin's diamond inheritance.
#
#: Số vòng tối đa của ``delete_role_atomic`` khi tập người mang vai mở rộng giữa lúc khoá và lúc kiểm lại. (PR-B lượt 4:
#: ``remove_role_from_users`` không còn vòng làm lại — quyết từ MỘT lần đọc ``casbin_rule`` dưới khoá.) ``failed_users``
#: của ``remove_role_from_users`` giữ trường cho thân phản hồi; lỗi CSDL nay ném ra (giao dịch không commit gì).
_MAX_LAN_ANH = 5


ROLE_PRIORITY = {
    "role:admin": 5,
    "role:manager": 4,        # User/Lead management branch
    "role:accountant": 3,     # Finance operations branch (parallel to manager)
    "role:officer": 2,        # Admission consultant (base for both branches)
    "role:user": 1,           # Basic user (base for all roles)
}


async def remove_role_from_users(
    db: AsyncSession,
    enforcer: casbin.AsyncEnforcer,
    user_ids: List[int],
    role_to_remove: str,
    actor_id: Optional[int] = None,  # PR-B Q4: Admin thao tác (``revoked_by_user_id`` khi tự thu hồi quyền duyệt chéo)
    request_meta: Optional[Any] = None,
) -> Tuple[Dict[str, Any], Callable]:
    """
    Remove a specific role from multiple users.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    SMART BEHAVIOR:
    - If user has ONLY this role → remove it and auto-assign "role:user"
    - If user has MULTIPLE roles → only remove this role, keep others
    - Updates database user.role to reflect remaining highest-priority role

    Args:
        db: Database session (injected via DI)
        enforcer: Casbin enforcer instance (injected via DI)
        user_ids: List of user IDs to remove role from
        role_to_remove: Role name to remove (e.g., "role:admin")

    Returns:
        Tuple of (result_dict, post_commit_callback)
        result_dict contains:
        - removed_count: Number of users role was removed from
        - reassigned_to_user_count: Number of users auto-assigned to "role:user"
        - failed_count: Number of failed operations
        - failed_users: List of failed operations with errors

    Raises:
        ResourceNotFoundError: If no user IDs provided

    Business Logic:
        1. For each user:
           a. Check if user has the role to remove
           b. Remove the role from Casbin
           c. Check remaining roles
           d. If no roles left, auto-assign "role:user"
           e. Update database user.role to highest priority role
        2. Flush changes to database
        3. Post-commit: Save Casbin policies
        4. Return operation summary

    Example:
        >>> result, callback = await remove_role_from_users(
        ...     db=session,
        ...     enforcer=app.state.enforcer,
        ...     user_ids=[1, 2, 3],
        ...     role_to_remove="role:manager"
        ... )
        >>> await db.commit()
        >>> await callback()
        >>> print(result["removed_count"])
        3
    """
    if not user_ids:
        raise ResourceNotFoundError(
            detail="No user IDs provided",
            context={"operation": "remove_role_from_users"}
        )

    removed_count = 0
    reassigned_count = 0
    failed_users = []

    from app.repositories import UserRepository
    from app.services.document_cross_review_service import revoke_grants_on_account_change

    user_repo = UserRepository(db)
    db_removed = role_to_remove.replace("role:", "")

    # id TĂNG (PR-B Q4: mỗi người khoá dòng user → dòng quyền chéo; hai lệnh chồng nhau khoá cùng chiều).
    #
    # PR-B lượt 4 (Codex lượt 3 điểm chặn 1, 2) — MỌI quyết định tính từ BẢNG ``casbin_rule``, nguồn CHUNG mọi worker
    # (enforcer trong bộ nhớ là bản RIÊNG từng worker Gunicorn, có thể cũ: worker thứ hai từng đọc lại vai đã bị gỡ ở
    # worker thứ nhất rồi ghi lại vai ấy vào CSDL). Cho MỖI người:
    # (0) khoá dòng ``user`` ``FOR NO KEY UPDATE`` — tuần tự theo tài khoản (mọi đường đổi vai CSDL lấy cùng khoá) — và
    #     làm mới đối tượng ``User`` dưới khoá (gán trùng giá trị cũ của đối tượng nạp trước khoá ⇒ ORM bỏ UPDATE);
    # (1) đọc vai của người ấy từ ``casbin_rule`` và KHOÁ các dòng ấy ``FOR UPDATE`` — MỘT lần đọc, SAU khoá (0); xoá về
    #     sau đi theo ID các dòng ĐÃ đọc (dòng cùng cặp chèn sau lần đọc không bị xoá — Codex lượt 4, C2);
    # (2) từ CHÍNH lần đọc ấy: xử lý / bỏ qua, vai CSDL = vai ưu tiên cao nhất còn lại (không còn ⇒ ``user``);
    # (3) RỒI mới ghi: tự thu hồi quyền chéo + nhật ký (Q4 — đúng MỘT lần, theo kết quả cuối), vai CSDL, xoá / chèn dòng
    #     ``casbin_rule`` — TẤT CẢ trong CÙNG giao dịch của router: lỗi ở bất kỳ người nào ⇒ không commit gì (kể cả
    #     Casbin) ⇒ thử lại bắt đầu từ trạng thái nguyên vẹn (owner câu 7). Không còn vòng làm lại (bản lượt 3: ghi thu
    #     hồi TRƯỚC khi xác nhận ảnh vai ⇒ tính lại mà vai cuối vẫn Cán bộ thì dấu thu hồi vòng trước vẫn commit).
    # Bộ nhớ enforcer của worker này nạp lại từ CSDL SAU commit (callback); worker khác giữ bản cũ tới lần nạp kế — không
    # đường đổi vai CSDL nào quyết từ bộ nhớ ấy nữa.
    # Người đã có vai trong CSDL là vai bị gỡ mà ``casbin_rule`` không còn vai ấy (CSDL lệch từ trước) ⇒ ĐỒNG BỘ LẠI vai
    # CSDL theo các vai còn lại + tự thu hồi, không bỏ qua.
    from app.repositories import document_bulk_repository as bulk_repo

    for user_id in sorted(user_ids):
        # (0)
        locked = await bulk_repo.lock_user_no_key_update(db, user_id)
        user = None
        if locked is not None:
            user = await user_repo.get_by_id(user_id)
            # PR-B lượt 5: làm mới cả ``unit_id`` — bản ghi phân công mới (bước 3) lấy đơn vị HIỆN HÀNH dưới khoá.
            await db.refresh(user, attribute_names=["role", "unit_id"])
        # (1)
        rows = await user_repo.lock_grouping_rows(user_id)
        roles = [r for _, r in rows]
        # (2)
        if role_to_remove in roles:
            pass
        elif locked is not None and locked.role == db_removed:
            log.warning("User %s: Casbin no longer has %s but DB role still does — reconciling", user_id, role_to_remove)
        else:
            log.warning(f"User {user_id} doesn't have role {role_to_remove}, skipping")
            continue
        remaining_roles = [r for r in roles if r != role_to_remove]
        highest_priority_role = max(
            remaining_roles or ["role:user"],
            key=lambda r: ROLE_PRIORITY.get(r, 0),
            default="role:user",
        )
        db_role_name = highest_priority_role.replace("role:", "")
        # (3)
        if user is not None:
            # GĐ1b PR-B Q4: vai CSDL rời Cán bộ ⇒ tự thu hồi quyền duyệt chéo CÙNG giao dịch. Ngoài mọi khối nuốt lỗi: lỗi ⇒
            # ném ra để router không commit gì (fail-closed).
            await revoke_grants_on_account_change(
                db,
                user_id=user.id,
                new_role=db_role_name,
                actor_id=actor_id,
                request_meta=request_meta,
            )
            if locked.role != db_role_name:
                # PR-B lượt 5 (Codex 22-11 B-P1): đổi vai CSDL qua ĐÚNG hàm PUT dùng (``_create_or_update_user_assignment``,
                # ``enforcer=None`` — ``casbin_rule`` ghi ở dưới): bản ghi phân công đang hiệu lực (``user_unit_assignment`` —
                # nguồn chuẩn của vai + đơn vị, ``user.role`` chỉ là bản sao) đóng lại, bản ghi MỚI mang vai mới, cùng giao
                # dịch, dưới khoá dòng người ở (0). Bản cũ chỉ ghi ``user.role`` ⇒ phân công còn mang vai vừa gỡ ⇒ bộ chọn
                # người nhận theo vai (``notification_resolvers``) vẫn chọn người đã bị gỡ vai Quản lý.
                from app.services.user_service import _create_or_update_user_assignment

                await _create_or_update_user_assignment(
                    db=db,
                    user=user,
                    new_role=db_role_name,
                    new_unit_id=user.unit_id,
                    assigned_by_user_id=actor_id,
                    enforcer=None,
                )
            db.add(user)
        if role_to_remove in roles:
            # Xoá ĐÚNG các dòng đã đọc + khoá ở (1) (theo id) — dòng cùng cặp chèn sau lần đọc là thao tác đến sau, phải còn.
            removed_count += 1 if await user_repo.delete_grouping_ids([i for i, r in rows if r == role_to_remove]) else 0
        if not remaining_roles:
            # SMART BEHAVIOR: If no roles left, auto-assign role:user
            await user_repo.add_grouping(user_id, "role:user")
            reassigned_count += 1
            log.info(f"User {user_id} had no roles left, auto-assigned role:user")

        # `log` ở module này là `logging.getLogger` CHUẨN, không phải
        # structlog — nó KHÔNG nhận kwarg tuỳ ý và ném
        # `TypeError: Logger._log() got an unexpected keyword argument`.
        # Trường có cấu trúc phải đi qua `extra={...}`.
        log.info(
            "User %s updated",
            user_id,
            extra={
                "removed_role": role_to_remove,
                "remaining_roles": remaining_roles,
                "db_role": db_role_name,
            },
        )

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction.

        KHÔNG gọi `save_policy()` (adapter async = `DELETE FROM casbin_rule` rồi ghi lại toàn bộ model — chạy SAU commit,
        ngoài mọi lock, một lượt reload chen giữa là đủ để ghi trạng thái CŨ đè lên trạng thái ĐÚNG).

        PR-B lượt 4: dòng ``casbin_rule`` đã ghi TRONG giao dịch vừa commit ⇒ nạp lại bộ nhớ enforcer CỦA WORKER NÀY từ
        CSDL (``load_policy`` dưới lock enforcer). Nạp hỏng chỉ để bộ nhớ worker này cũ (như mọi worker khác) — CSDL đã
        đúng, không đường đổi vai CSDL nào quyết từ bộ nhớ ⇒ chỉ ghi cảnh báo.
        """
        from app.services.casbin_service import dong_bo_tu_nguon_ben_vung

        loi = await dong_bo_tu_nguon_ben_vung(enforcer)
        if loi is not None:
            log.warning("remove_role_from_users: reload enforcer after commit failed", extra={"error": loi})

    result = {
        "detail": f"Removed {role_to_remove} from {removed_count} user(s), {reassigned_count} auto-assigned to role:user",
        "removed_count": removed_count,
        "reassigned_to_user_count": reassigned_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users,
    }

    return result, _post_commit


def _user_ids_with_grouping(grouping, role_name: str) -> set:
    """Id người có dòng grouping ``g, user:<id>, <role_name>`` (bỏ qua chủ thể không đúng dạng ``user:<số>``)."""
    ids = set()
    for group in grouping:
        # group format: ["user:123", "role:support"]
        if len(group) >= 2 and group[1] == role_name and group[0].startswith("user:"):
            try:
                ids.add(int(group[0].split(":")[1]))
            except (ValueError, IndexError):
                continue
    return ids


async def delete_role_atomic(
    db: AsyncSession,
    role_name: str,
    enforcer: casbin.AsyncEnforcer,
    actor_id: Optional[int] = None,  # PR-B lượt 3: người thao tác (Q4 — chỉ dùng nếu đổi vai kéo theo tự thu hồi)
    request_meta: Optional[Any] = None,
) -> Tuple[Dict[str, Any], Callable]:
    """
    Atomically delete a role with all its associations.
    Moved from Router to Service (Refactoring Pattern A).
    
    Args:
        db: Database session
        role_name: Role identifier (e.g., "role:support")
        enforcer: Casbin enforcer
        
    Returns:
        Tuple of (stats_dict, post_commit_callback)
    """
    from app.repositories import UserRepository
    from app.utils.exceptions import BadRequest, ResourceNotFoundError
    
    # STEP 1: Validate - System roles cannot be deleted
    SYSTEM_ROLES = {"role:admin", "role:manager", "role:accountant", "role:officer", "role:user"}
    if role_name in SYSTEM_ROLES:
        raise BadRequest(f"Cannot delete system role: {role_name}")

    # PR-B lượt 3 (Codex lượt 2 điểm chặn 5 / 4.1) — bước CSDL TRƯỚC lock enforcer.
    #
    # Bản cũ đọc người mang vai bằng một lần đọc thường rồi GHI ``user.role = "user"`` khi ĐANG giữ lock enforcer:
    # (a) dữ liệu cũ — người vừa được đổi sang Cán bộ (và cấp quyền duyệt chéo) bị ghi đè thành ``user`` mà không qua tự thu
    #     hồi (Q4); trả lại vai Cán bộ sau đó là dùng lại quyền cũ;
    # (b) lấy khoá dòng ``user`` khi đang giữ lock enforcer — NGƯỢC chiều mọi đường đổi vai khác (dòng ``user`` → lock
    #     enforcer, vd ``update_user``) ⇒ bế tắc giữa lock asyncio và khoá CSDL mà PostgreSQL không phát hiện được.
    # Nay:
    # (A) tìm người liên quan — đọc bảng ``casbin_rule`` + vai CSDL (PR-B lượt 4: không đọc bộ nhớ enforcer), không khoá;
    # (B) KHÔNG giữ lock enforcer: khoá từng dòng ``user`` (id tăng) ``FOR NO KEY UPDATE``, đọc lại vai DƯỚI khoá; chỉ người
    #     CÒN mang vai bị xoá mới bị đổi sang ``user``, qua ``revoke_grants_on_account_change`` (tầng chủ sở hữu Q4);
    # (C) lock enforcer: đồng bộ policy, kiểm role tồn tại, tìm lại người liên quan — có người MỚI chưa khoá (vừa được gán
    #     vai giữa (A) và (C)) ⇒ nhả lock, quay lại (B) cho người ấy, CHƯA đụng Casbin; đủ ⇒ xoá policy + hậu điều kiện
    #     (fail-closed như cũ) rồi gỡ grouping. Quá ``_MAX_LAN_ANH`` vòng ⇒ lỗi 500 (không commit gì).
    #     PR-B lượt 4 (Codex lượt 3 điểm chặn 5): (B) chạy trong MỘT savepoint; người mới có id NHỎ hơn người đã khoá ⇒
    #     rollback savepoint (nhả khoá) rồi khoá lại toàn tập theo id tăng — thứ tự khoá tăng trên TOÀN giao dịch.
    # Lỗi ở (C) ⇒ router rollback ⇒ các đổi vai ở (B) cũng mất (CSDL rollback được; Casbin chỉ bị đụng sau hậu điều kiện).
    from app.repositories import document_bulk_repository as bulk_repo
    from app.services.casbin_service import khoa_enforcer
    from app.services.document_cross_review_service import revoke_grants_on_account_change

    user_repo = UserRepository(db)
    db_role = role_name.replace("role:", "")
    locked_ids: List[int] = []  # thứ tự đã khoá trong savepoint hiện hành — luôn TĂNG
    reassigned_ids: set = set()
    sp = None

    # (A) — PR-B lượt 4 (Codex lượt 3 điểm chặn 1): đọc BẢNG ``casbin_rule`` (nguồn chung mọi worker), không đọc bộ nhớ
    # enforcer của worker này; cùng vai CSDL. Không khoá.
    candidate_ids = set(await user_repo.user_ids_with_grouping_role(role_name))
    candidate_ids |= {u.id for u in await user_repo.get_by_db_role(db_role)}

    for _vong in range(_MAX_LAN_ANH):
        moi = sorted(candidate_ids - set(locked_ids))
        if moi and locked_ids and moi[0] < locked_ids[-1]:
            # Codex lượt 3 điểm chặn 5: người MỚI có id NHỎ hơn người đã khoá ⇒ khoá tiếp là GIỮ id lớn CHỜ id nhỏ — ngược
            # chiều mọi đường khoá nhiều người theo id tăng (đồng bộ vai, gỡ vai hàng loạt, khoá tài khoản hàng loạt) ⇒ bế
            # tắc. Bảo toàn thứ tự khoá TOÀN giao dịch: rollback savepoint (khoá dòng lấy trong savepoint được NHẢ, đổi vai
            # trong đó cũng mất) rồi khoá lại TOÀN tập theo id tăng.
            await sp.rollback()
            sp, locked_ids, reassigned_ids = None, [], set()
            moi = sorted(candidate_ids)
        if sp is None:
            sp = await db.begin_nested()
        # (B) STEP 4 — đổi vai CSDL cho người CÒN mang vai bị xoá (vai đọc DƯỚI khoá dòng ``user``).
        for user_id in moi:
            locked_ids.append(user_id)
            locked = await bulk_repo.lock_user_no_key_update(db, user_id)
            if locked is None or locked.role != db_role:
                continue
            await revoke_grants_on_account_change(
                db, user_id=user_id, new_role="user", actor_id=actor_id, request_meta=request_meta
            )
            user = await user_repo.get_by_id(user_id)
            # đối tượng có thể nạp TRƯỚC khoá (Codex lượt 3 điểm chặn 3); PR-B lượt 5: làm mới cả ``unit_id`` (phân công mới).
            await db.refresh(user, attribute_names=["role", "unit_id"])
            # PR-B lượt 5 (Codex 22-11 B-P1): đổi vai CSDL qua ĐÚNG hàm PUT dùng — đóng bản ghi phân công đang hiệu lực, mở
            # bản ghi mới mang vai ``user``, cùng savepoint ``sp`` (khởi động lại vòng ⇒ lùi cả phân công).
            from app.services.user_service import _create_or_update_user_assignment

            await _create_or_update_user_assignment(
                db=db,
                user=user,
                new_role="user",
                new_unit_id=user.unit_id,
                assigned_by_user_id=actor_id,
                enforcer=None,
            )
            db.add(user)
            reassigned_ids.add(user_id)
        await db.flush()  # mọi câu ghi dòng ``user`` xong TRƯỚC khi vào lock enforcer

        # (C)
        # STEP 1b: ĐỒNG BỘ POLICY TỪ CSDL — TRƯỚC cả phép kiểm role tồn tại.
        #
        # Cả `role_has_policies` bên dưới lẫn `policies_to_remove` ở STEP 2b đều
        # dựng TỪ MODEL. Sau một lượt thu hồi hỏng, model đã quên rule mà hàng vẫn
        # nằm trong CSDL — khi ấy phép kiểm này ném `ResourceNotFoundError` (404)
        # cho một role vẫn còn quyền, còn retry thì chỉ nhìn thấy phần rule sót
        # trong model. Đồng bộ trước là điều kiện để hai bước đó nói về CSDL thật.
        # `all_policies` và `policies_to_remove` dựng TỪ MODEL ở trong vùng này,
        # nên lock phải bao cả lúc dựng — khoá riêng trong helper thì snapshot đã
        # kịp cũ. Lock TÁI VÀO ĐƯỢC nên helper vẫn tự khoá mà không tự chặn mình.
        async with khoa_enforcer(enforcer):
            from app.services.casbin_service import dong_bo_tu_nguon_ben_vung

            loi_dong_bo = await dong_bo_tu_nguon_ben_vung(enforcer)
            if loi_dong_bo is not None:
                raise ConflictError(
                    f"Không xoá được role {role_name}: không đồng bộ được policy từ "
                    f"CSDL nên chưa chạm vào gì — {loi_dong_bo}"
                )

            # STEP 2: Check if role exists (has any policies)
            all_policies = enforcer.get_policy()
            role_has_policies = any(p[0] == role_name for p in all_policies)
            if not role_has_policies:
                raise ResourceNotFoundError(f"Role not found: {role_name}")

            # STEP 3: tìm LẠI người liên quan (grouping trong model vừa đồng bộ + người CSDL còn mang vai — câu đọc thường,
            # không khoá dòng nào). Có người chưa qua (B) ⇒ nhả lock, quay lại (B); CHƯA đụng gì trong Casbin.
            all_grouping = enforcer.get_grouping_policy()
            candidate_ids = _user_ids_with_grouping(all_grouping, role_name) | {
                u.id for u in await user_repo.get_by_db_role(db_role)
            }
            if candidate_ids - set(locked_ids):
                continue

            # STEP 2b: XOÁ policy + KIỂM HẬU ĐIỀU KIỆN — TRƯỚC mọi mutation khác trên enforcer.
            #
            # Thứ tự này là phần fail-closed. Các bước sau đổi grouping policy trong
            # enforcer (STEP 5/6); DB (STEP 4 ở trên) thì router rollback được,
            # nhưng thay đổi trên enforcer thì KHÔNG hoàn tác đồng bộ. Nếu xoá policy
            # thất bại mà ta đã kịp gỡ grouping, hệ thống rơi vào trạng thái nửa
            # vời: user mất role, còn policy của role thì vẫn sống.
            #
            # Nên xoá policy trước, xác nhận sạch, rồi mới đụng thứ khác. Ném ở đây thì
            # router `except Exception -> rollback` và KHÔNG log "Role deleted
            # atomically".
            from app.services.casbin_service import (
                chuan_hoa_rule,
                policy_cua_role,
                xoa_nhom_rule_fail_closed,
                xoa_rule_chinh_xac,
            )

            policies_to_remove = [
                chuan_hoa_rule(p) for p in all_policies if p and p[0] == role_name
            ]
            removed_p_count = 0

            async def xu_ly(p):
                nonlocal removed_p_count
                if await xoa_rule_chinh_xac(enforcer, p):
                    removed_p_count += 1
                    return True
                return False

            # Thứ tự non-deny -> deny do helper chung giữ. Vòng `for` phẳng ở đây từng
            # xoá `deny` sau khi `allow` xoá hụt: role "xoá dở" mà quyền lại RỘNG HƠN
            # trước khi xoá.
            kq = await xoa_nhom_rule_fail_closed(
                enforcer, policies_to_remove, xu_ly, da_dong_bo=True
            )

            # `policy_cua_role` chỉ đọc MODEL BỘ NHỚ, nên nó KHÔNG thấy ca adapter hỏng
            # (model sạch mà hàng trong CSDL còn). `kq["con_song"]` mới là danh sách
            # rule chưa được XÁC NHẬN thu hồi — phải kiểm cả hai.
            policies_con_sot = policy_cua_role(enforcer, role_name)
            chua_xac_nhan = kq["con_song"]
            if policies_con_sot or chua_xac_nhan or not kq["an_toan"]:
                raise ConflictError(
                    f"Không xoá được role {role_name}: {len(policies_con_sot)} policy "
                    f"còn trong model, {len(chua_xac_nhan)} rule chưa xác nhận thu hồi"
                    + (
                        f" ({len(kq['deny_chua_cham'])} rule deny KHÔNG bị chạm tới vì "
                        f"non-deny xoá hụt — xoá deny lúc này là MỞ quyền)"
                        if not kq["an_toan"]
                        else ""
                    )
                    + f", quyền cũ VẪN CÒN hiệu lực. Chi tiết: {policies_con_sot}"
                )

            all_user_ids = candidate_ids | reassigned_ids

            # STEP 5: Remove grouping policies (user → role)
            removed_g_user_count = 0
            for user_id in sorted(all_user_ids):
                user_subject = f"user:{user_id}"
                removed = await enforcer.remove_grouping_policy(
                    user_subject, role_name
                )
                if removed:
                    removed_g_user_count += 1

                # STEP 6: Add grouping policy (user → role:user) if needed
                user_roles = await enforcer.get_roles_for_user(user_subject)
                if not user_roles or len(user_roles) == 0:
                    await enforcer.add_grouping_policy(user_subject, "role:user")

            # STEP 7: Remove all permission policies (p rules) for this role
            # (Policy đã được xoá và xác nhận sạch ở STEP 2b, TRƯỚC mọi mutation trên enforcer.)

            # STEP 8: Remove role inheritance grouping policies (g, role:X, role:user)
            removed_g_inherit_count = 0
            for group in all_grouping:
                # Check if this is a role inheriting from another role
                if len(group) >= 2 and group[0] == role_name:
                    removed = await enforcer.remove_grouping_policy(group[0], group[1])
                    if removed:
                        removed_g_inherit_count += 1
            break
    else:
        # Người mang vai đổi liên tục giữa lúc khoá và lúc kiểm lại ⇒ fail-closed (router không commit).
        raise RuntimeError(f"delete_role_atomic: danh sách người mang {role_name} đổi liên tục")
    await sp.commit()  # nhả savepoint (giữ thay đổi + khoá trong giao dịch của router)
    reassigned_count = len(reassigned_ids)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction.

        Không `save_policy()` — xem `remove_role_from_users`.
        """
        # Chỗ này từng làm CẢ ENDPOINT trả 500 SAU KHI transaction đã commit:
        # `_post_commit` chạy sau `db.commit()`, nên `TypeError` ở đây khiến
        # router bắt exception rồi trả "Failed to delete role" cho một việc ĐÃ
        # XẢY RA. Người vận hành thấy thất bại cho thứ đã thành công — và sẽ
        # thử xoá lại một role không còn tồn tại.
        log.info(
            "Atomic role deletion complete for %s",
            role_name,
            extra={
                "reassigned": reassigned_count,
                "policies_removed": removed_p_count,
            },
        )

    result = {
        # Tới được đây nghĩa là hậu điều kiện ở STEP 2b đã ĐẠT — role không
        # còn policy nào. Trường hợp còn sót đã ném ConflictError từ trước.
        "success": True,
        "detail": f"Role {role_name} deleted successfully",
        "role_name": role_name,
        "users_reassigned": reassigned_count,
        "permission_policies_removed": removed_p_count,
        "user_grouping_policies_removed": removed_g_user_count,
        "inheritance_grouping_policies_removed": removed_g_inherit_count,
        "total_affected_users": len(all_user_ids),
    }
    
    return result, _post_commit
