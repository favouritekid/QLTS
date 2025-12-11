# app/repositories/__init__.py
"""
✅ PHASE 2 - WEEK 1: Repository Layer

Repository pattern implementation for clean data access layer.

Export all repositories for easy import:
    from app.repositories import LeadRepository, UserRepository
"""

from app.repositories.base import BaseRepository
from app.repositories.application_repository import ApplicationRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "ApplicationRepository",
    "LeadRepository",
    "OrganizationRepository",
    "UserRepository",
]

