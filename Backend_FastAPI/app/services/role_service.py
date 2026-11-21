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
#: Số lần tối đa làm lại đọc ảnh vai Casbin → ghi CSDL → đối chiếu ảnh khi ghi Casbin (``remove_role_from_users``).
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
    from app.services.casbin_service import khoa_enforcer
    from app.services.document_cross_review_service import revoke_grants_on_account_change

    user_repo = UserRepository(db)
    db_removed = role_to_remove.replace("role:", "")

    # id TĂNG (PR-B Q4: mỗi người khoá dòng user → dòng quyền chéo; hai lệnh chồng nhau khoá cùng chiều).
    #
    # Thứ tự cho MỖI người:
    # (0) PR-B lượt 3 (Codex lượt 2 điểm chặn 3) — TUẦN TỰ HOÁ THEO TÀI KHOẢN: khoá dòng ``user`` ``FOR NO KEY UPDATE``
    #     (= khoá mà mọi đường đổi vai CSDL lấy qua ``revoke_grants_on_account_change``) TRƯỚC khi đọc vai Casbin. Hai lệnh
    #     gỡ hai vai khác nhau của cùng một người xếp hàng tại đây: lệnh sau đọc Casbin SAU khi lệnh trước đã gỡ + commit.
    #     Quyết "người này có cần xử lý không" bằng vai CSDL đọc DƯỚI khoá này.
    # (1) đọc vai Casbin (ảnh S), KHÔNG đổi;
    # (2) tự thu hồi quyền chéo + nhật ký và ghi vai CSDL = vai cao nhất của S trừ vai bị gỡ (cùng giao dịch, lỗi ⇒ ném ra,
    #     router không commit) — PR-B lượt 2, owner câu 7: CSDL TRƯỚC Casbin (adapter ghi bằng phiên RIÊNG, không rollback);
    # (3) RỒI mới gỡ vai trong Casbin, trong lock enforcer, và CHỈ KHI ảnh Casbin lúc ấy VẪN là S — vai CSDL luôn tính từ
    #     CÙNG tập vai mà lệnh dùng để ghi Casbin (Codex lượt 2 điểm chặn 3: ``check_permission`` lấy vai từ ``user.role``).
    #     Ảnh đã đổi (một thao tác CHỈ sửa Casbin chen giữa (1) và (3) — các đường ấy không khoá dòng người) ⇒ làm lại
    #     (1)–(3) với ảnh mới; quá ``_MAX_LAN_ANH`` lần ⇒ ném lỗi (500, không commit gì; thử lại).
    # Người đã qua bước (3) mà giao dịch vẫn rollback (lỗi ở người SAU trong cùng lệnh, hay commit lỗi): lần thử lại thấy
    # Casbin không còn vai NHƯNG vai CSDL vẫn là vai bị gỡ ⇒ ĐỒNG BỘ LẠI (vai CSDL theo vai Casbin còn lại + tự thu hồi),
    # không bỏ qua ⇒ Casbin, vai CSDL, dấu thu hồi về nhất quán.
    from app.repositories import document_bulk_repository as bulk_repo

    for user_id in sorted(user_ids):
        user_subject = f"user:{user_id}"

        # (0) Khoá dòng người TRƯỚC mọi lần đọc Casbin của người này.
        locked = await bulk_repo.lock_user_no_key_update(db, user_id)
        user = await user_repo.get_by_id(user_id) if locked is not None else None

        remaining_roles: List[str] = []
        db_role_name = None
        xu_ly = None  # None = chưa quyết; False = bỏ qua người này
        xong = False
        for _lan in range(_MAX_LAN_ANH):
            try:
                # (1) Lock bao TRỌN lần đọc ảnh (không đổi gì ở bước này).
                async with khoa_enforcer(enforcer):
                    snapshot = list(await enforcer.get_roles_for_user(user_subject))
            except Exception as e:
                failed_users.append({"user_id": user_id, "error": chu_loi_an_toan(e)})
                log.error("Failed to read roles of user %s", user_id, extra={"error": str(e)})
                break

            if xu_ly is None:
                if role_to_remove in snapshot:
                    xu_ly = True
                elif locked is not None and locked.role == db_removed:
                    # Lần trước đã gỡ trong Casbin nhưng CSDL rollback ⇒ đồng bộ lại vai CSDL theo Casbin hiện có.
                    xu_ly = True
                    log.warning(
                        "User %s: Casbin no longer has %s but DB role still does — reconciling", user_id, role_to_remove
                    )
                else:
                    xu_ly = False
                    log.warning(f"User {user_id} doesn't have role {role_to_remove}, skipping")
                    break

            # (2) Vai CSDL = vai ưu tiên cao nhất của ẢNH S trừ vai bị gỡ (không còn vai nào ⇒ role:user).
            remaining_roles = [r for r in snapshot if r != role_to_remove]
            highest_priority_role = max(
                remaining_roles or ["role:user"],
                key=lambda r: ROLE_PRIORITY.get(r, 0),
                default="role:user",
            )
            db_role_name = highest_priority_role.replace("role:", "")
            if user is not None:
                # GĐ1b PR-B Q4: vai CSDL rời Cán bộ ⇒ tự thu hồi quyền duyệt chéo CÙNG giao dịch, TRƯỚC khi ghi vai và
                # TRƯỚC khi đụng Casbin. Ngoài mọi khối nuốt lỗi: lỗi ⇒ ném ra để router không commit gì (fail-closed).
                await revoke_grants_on_account_change(
                    db,
                    user_id=user.id,
                    new_role=db_role_name,
                    actor_id=actor_id,
                    request_meta=request_meta,
                )
                user.role = db_role_name
                db.add(user)

            try:
                # (3) Lock bao TRỌN đối chiếu ảnh -> gỡ role -> gán lại role dự phòng (giữa lúc gỡ và lúc gán lại người dùng
                # KHÔNG có role nào).
                async with khoa_enforcer(enforcer):
                    current_roles = list(await enforcer.get_roles_for_user(user_subject))
                    if sorted(current_roles) == sorted(snapshot):
                        if role_to_remove in current_roles:
                            await enforcer.remove_grouping_policy(user_subject, role_to_remove)
                            removed_count += 1
                        if not remaining_roles:
                            # SMART BEHAVIOR: If no roles left, auto-assign role:user
                            await enforcer.add_grouping_policy(user_subject, "role:user")
                            reassigned_count += 1
                            log.info(f"User {user_id} had no roles left, auto-assigned role:user")
                        xong = True
            except Exception as e:
                # Vai CSDL + dấu thu hồi đã ghi (vai CSDL là thứ Casbin dùng làm chủ thể ``role:{user.role}``); Casbin sẽ
                # được gỡ ở lần thử lại (vai còn trong Casbin ⇒ nhánh thường; thu hồi khi ấy là no-op vì vai CSDL đã đổi).
                failed_users.append({"user_id": user_id, "error": chu_loi_an_toan(e)})
                log.error("Failed to remove role from user %s", user_id, extra={"error": str(e)})
                break
            if xong:
                break
            log.warning("User %s: Casbin roles changed between read and write — recomputing", user_id)
        else:
            # Ảnh Casbin đổi liên tục giữa đọc và ghi: không kết luận được vai CSDL ⇒ fail-closed (router không commit).
            raise RuntimeError(f"remove_role_from_users: ảnh vai Casbin của user {user_id} đổi liên tục")

        if not xong:
            continue

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

        KHÔNG gọi `save_policy()`. `auto_save` bật nên mọi
        `add/remove_grouping_policy` ở trên ĐÃ ghi xuống `casbin_rule`. Còn
        `save_policy()` của adapter async là `DELETE FROM casbin_rule` rồi ghi
        lại toàn bộ model — chạy SAU `db.commit()`, tức ngoài mọi lock đã giữ
        lúc mutation, nên một lượt reload chen giữa hai thời điểm là đủ để nó
        ghi trạng thái CŨ đè lên trạng thái ĐÚNG.
        """

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
    # (A) tìm người liên quan — lock enforcer CHỈ để đọc grouping, nhả ngay;
    # (B) KHÔNG giữ lock enforcer: khoá từng dòng ``user`` (id tăng) ``FOR NO KEY UPDATE``, đọc lại vai DƯỚI khoá; chỉ người
    #     CÒN mang vai bị xoá mới bị đổi sang ``user``, qua ``revoke_grants_on_account_change`` (tầng chủ sở hữu Q4);
    # (C) lock enforcer: đồng bộ policy, kiểm role tồn tại, tìm lại người liên quan — có người MỚI chưa khoá (vừa được gán
    #     vai giữa (A) và (C)) ⇒ nhả lock, quay lại (B) cho người ấy, CHƯA đụng Casbin; đủ ⇒ xoá policy + hậu điều kiện
    #     (fail-closed như cũ) rồi gỡ grouping. Quá ``_MAX_LAN_ANH`` vòng ⇒ lỗi 500 (không commit gì).
    # Lỗi ở (C) ⇒ router rollback ⇒ các đổi vai ở (B) cũng mất (CSDL rollback được; Casbin chỉ bị đụng sau hậu điều kiện).
    from app.repositories import document_bulk_repository as bulk_repo
    from app.services.casbin_service import khoa_enforcer
    from app.services.document_cross_review_service import revoke_grants_on_account_change

    user_repo = UserRepository(db)
    db_role = role_name.replace("role:", "")
    locked_ids: set = set()
    reassigned_ids: set = set()

    # (A)
    async with khoa_enforcer(enforcer):
        candidate_ids = _user_ids_with_grouping(enforcer.get_grouping_policy(), role_name)
    candidate_ids |= {u.id for u in await user_repo.get_by_db_role(db_role)}

    for _vong in range(_MAX_LAN_ANH):
        # (B) STEP 4 — đổi vai CSDL cho người CÒN mang vai bị xoá (vai đọc DƯỚI khoá dòng ``user``).
        for user_id in sorted(candidate_ids - locked_ids):
            locked_ids.add(user_id)
            locked = await bulk_repo.lock_user_no_key_update(db, user_id)
            if locked is None or locked.role != db_role:
                continue
            await revoke_grants_on_account_change(
                db, user_id=user_id, new_role="user", actor_id=actor_id, request_meta=request_meta
            )
            user = await user_repo.get_by_id(user_id)
            user.role = "user"
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
            if candidate_ids - locked_ids:
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
