# app/repositories/__init__.py
"""
✅ PHASE 2 - WEEK 1: Repository Layer

Repository pattern implementation for clean data access layer.

Export all repositories for easy import:
    from app.repositories import LeadRepository, UserRepository
"""

from app.repositories.base import BaseRepository
from app.repositories.lead_repository import LeadRepository

__all__ = [
    "BaseRepository",
    "LeadRepository",
]
