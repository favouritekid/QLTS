# app/core/constants.py
"""
Centralized constants for the QLTS application.

This module provides type-safe enums and constants to replace hardcoded strings
throughout the codebase, improving maintainability and reducing errors.
"""
from enum import StrEnum


class UserRole(StrEnum):
    """
    User role enum for type-safe role comparisons.

    Usage:
        from app.core.constants import UserRole

        if current_user.role == UserRole.ADMIN:
            ...

        # Works with SQLAlchemy queries too:
        .where(models.User.role == UserRole.OFFICER)

    Note:
        StrEnum ensures the value is stored as string in database
        and is compatible with existing string-based role column.

    Role hierarchy: a TREE, not a line — see ``ROLE_INHERITANCE`` below (the ONE source; Casbin is seeded from it and
    ``role_outranks`` derives management rank from it). ADMIN > MANAGER > OFFICER > USER and ACCOUNTANT > OFFICER;
    MANAGER and ACCOUNTANT are NOT comparable (separation of duties); COLLABORATOR inherits nothing.

    Separation of Duties:
        - OFFICER: Admission consultants (tư vấn viên tuyển sinh)
        - ACCOUNTANT: Finance staff (kế toán viên) - handles payments, invoices
    """
    ADMIN = "admin"
    MANAGER = "manager"
    ACCOUNTANT = "accountant"  # Finance staff - record/verify payments, issue invoices
    OFFICER = "officer"  # Admission consultant - manage leads, create payment intents
    COLLABORATOR = "collaborator"  # External collaborator (CTV) - submit leads, view own stats
    USER = "user"  # Basic user role with minimal permissions


# Cạnh KẾ THỪA vai ``(vai con, vai cha)``: vai con có mọi quyền của vai cha (Casbin ``g, role:<con>, role:<cha>``).
# MỘT nguồn cho HAI việc: (a) ``app/main.py`` seed các dòng ``g`` này vào ``casbin_rule`` lúc khởi động; (b) ``role_outranks``
# dưới đây suy cấp vai từ CHÍNH các cạnh ấy — bảng cấp không thể trôi khỏi thứ Casbin thật sự cấp.
# Cây (tách nhiệm vụ): Quản lý KHÔNG kế thừa Kế toán; Quản trị KHÔNG kế thừa Kế toán (bỏ cạnh kim cương 15-05);
# Cộng tác viên không kế thừa ai và không ai kế thừa nó.
ROLE_INHERITANCE = (
    (UserRole.OFFICER, UserRole.USER),
    (UserRole.ACCOUNTANT, UserRole.OFFICER),
    (UserRole.MANAGER, UserRole.OFFICER),
    (UserRole.ADMIN, UserRole.MANAGER),
)


def _inherited_roles(role: str) -> frozenset:
    """Mọi vai mà ``role`` kế thừa (bắc cầu, KHÔNG gồm chính nó), theo ``ROLE_INHERITANCE``."""
    found: set = set()
    frontier = [role]
    while frontier:
        current = frontier.pop()
        for child, parent in ROLE_INHERITANCE:
            if child == current and parent not in found:
                found.add(parent)
                frontier.append(parent)
    return frozenset(found)


def role_outranks(actor_role: str, target_role: str) -> bool:
    """F154 / Q-A13 — người vai ``actor_role`` có ĐƯỢC tác động (đặt mật khẩu, sửa, xoá, gán vai) lên vai ``target_role``?

    MỘT nguồn cấp vai cho cổng ``deps.verify_user_management_permission`` (``require_outrank``) và cho cổng gán vai mới
    ``deps.require_assignable_role``:

    - Quản trị: được với MỌI vai (owner 25-11 Q-A12: kể cả Quản trị khác). Việc "trừ chính mình" là phép so DANH TÍNH,
      do cổng ở ``deps`` xét — không nằm ở đây.
    - Vai khác: chỉ khi ``actor_role`` KẾ THỪA (bắc cầu) ``target_role`` — tức người thao tác đã có MỌI quyền của vai đích.
      Đặt được mật khẩu = đăng nhập được dưới tên người đích; nếu vai đích có quyền mà mình không có thì đó là leo quyền.
      Hệ quả: vai ngang (chính vai mình) và vai không so được (Quản lý ↔ Kế toán, ai ↔ Cộng tác viên) đều bị TỪ CHỐI.
    - Vai lạ (không có trong ``ROLE_INHERITANCE``): không kế thừa gì ⇒ không tác động được ai, và chỉ Quản trị tác động
      được nó (fail-closed).

    Owner chốt 25-11 (Q-A13): đi theo CÂY — Quản lý KHÔNG tạo / đặt mật khẩu / sửa / xoá được Kế toán (tách nhiệm vụ);
    không vai nào ngoài Quản trị thao tác được Cộng tác viên; CÙNG hàm này cho cả route TẠO tài khoản (bỏ bảng tuyến tính
    viết tay ở đó). ``role_service.ROLE_PRIORITY`` / ``user_service.highest_priority_role`` vẫn tuyến tính nhưng chỉ để
    CHỌN vai CSDL từ nhiều vai Casbin của MỘT người — không dùng để quyết ai được thao tác trên ai.
    """
    if actor_role == UserRole.ADMIN:
        return True
    return target_role in _inherited_roles(actor_role)


# Vai được phép GẮN vào một hồ sơ CTV qua ``user_id``. create_collaborator ĐỔI User.role của người đó thành 'collaborator',
# mà Casbin lấy subject = role:{User.role} ⇒ gắn một tài khoản nhân sự là tước quyền của họ. MỘT nguồn cho cổng
# ``deps.validate_collaborator_create`` VÀ bước khoá + đọc lại ngay trước khi ghi vai ở ``collaborator_service``
# (``collaborator_link_target_allowed``).
COLLABORATOR_LINKABLE_ROLES = frozenset({UserRole.USER, UserRole.COLLABORATOR})


# Sentinel method dành riêng cho consultation do HỆ THỐNG tạo (SLA auto-close,
# reopen). Cuộc 'system' là BẤT BIẾN (F1: không ai kể cả admin sửa/xóa/khôi phục)
# và bị LOẠI khỏi metrics (B7/B8: count/last_consultation_at/ranking/effectiveness).
# 🔴 SECURITY: client TUYỆT ĐỐI không được tạo/đổi method thành giá trị này qua
# API create/update — nếu spoof được sẽ tạo row bất biến, ẩn khỏi KPI, kẹt cả
# admin. CHỈ internal service (reopen/auto-close) tạo bằng ``models.Consultation``
# trực tiếp (không đi qua add_consultation/update_consultation service). Guard ở
# schema (422) + service (400). Nguồn constant DUY NHẤT cho cả 2 tầng.
SYSTEM_CONSULTATION_METHOD = "system"
