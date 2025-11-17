# app/routers/admin/__init__.py
"""
Admin router module - Split from monolithic admin.py

This module aggregates specialized admin routers for better organization
and maintainability.

PHASE 2A: users.py + roles.py ✅
PHASE 2B: organization.py + config.py ✅
PHASE 2C: pipeline.py (pending)
"""

from fastapi import APIRouter

# PHASE 2A routers
from . import users, roles

# PHASE 2B routers
from . import organization, config

# Create main admin router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Include PHASE 2A routers
router.include_router(users.router)    # /api/admin/users/*
router.include_router(roles.router)    # /api/admin/roles/*

# Include PHASE 2B routers
router.include_router(organization.router)  # /api/admin/organization-units/*, /api/admin/programs/*, /api/admin/offerings/*
router.include_router(config.router)        # /api/admin/assignment-config/*, /api/admin/skill-rules/*

# PHASE 2C: Will add pipeline router
