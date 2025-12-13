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
    """
    ADMIN = "admin"
    MANAGER = "manager"
    OFFICER = "officer"
