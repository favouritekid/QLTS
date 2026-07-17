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

    Role hierarchy (highest to lowest):
        ADMIN > MANAGER > ACCOUNTANT > OFFICER > USER

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


# Sentinel method dành riêng cho consultation do HỆ THỐNG tạo (SLA auto-close,
# reopen). Cuộc 'system' là BẤT BIẾN (F1: không ai kể cả admin sửa/xóa/khôi phục)
# và bị LOẠI khỏi metrics (B7/B8: count/last_consultation_at/ranking/effectiveness).
# 🔴 SECURITY: client TUYỆT ĐỐI không được tạo/đổi method thành giá trị này qua
# API create/update — nếu spoof được sẽ tạo row bất biến, ẩn khỏi KPI, kẹt cả
# admin. CHỈ internal service (reopen/auto-close) tạo bằng ``models.Consultation``
# trực tiếp (không đi qua add_consultation/update_consultation service). Guard ở
# schema (422) + service (400). Nguồn constant DUY NHẤT cho cả 2 tầng.
SYSTEM_CONSULTATION_METHOD = "system"
