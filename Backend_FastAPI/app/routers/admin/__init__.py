# app/routers/admin/__init__.py
"""
Admin router module - Split from monolithic admin.py

This module aggregates specialized admin routers for better organization
and maintainability.

PHASE 2A: users.py + roles.py ✅
PHASE 2B: organization.py + config.py (pending)
PHASE 2C: pipeline.py (pending)
"""

from fastapi import APIRouter

# PHASE 2A routers
from . import users, roles

# Create main admin router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Include PHASE 2A routers
router.include_router(users.router)    # /api/admin/users/*
router.include_router(roles.router)    # /api/admin/roles/*

# PHASE 2B: Will add organization and config routers
# PHASE 2C: Will add pipeline router
