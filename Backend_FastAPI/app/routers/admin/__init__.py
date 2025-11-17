# app/routers/admin/__init__.py
"""
Admin router module - Split from monolithic admin.py

This module aggregates specialized admin routers for better organization
and maintainability.

PHASE 2A: users.py + roles.py
PHASE 2B: organization.py + config.py
PHASE 2C: pipeline.py
"""

from fastapi import APIRouter

# PHASE 2A routers
from . import users

# Create main admin router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Include PHASE 2A routers
router.include_router(users.router)

# PHASE 2B: Will add organization and config routers
# PHASE 2C: Will add pipeline router
