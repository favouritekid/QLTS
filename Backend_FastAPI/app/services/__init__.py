# app/services/__init__.py
"""
Services package.

IMPORTANT: This __init__.py is intentionally kept minimal to avoid circular imports.
Import services directly from their modules instead of via this package.

Example:
    # ❌ Old way (causes circular imports):
    from .. import services
    services.user_service.some_function()

    # ✅ New way (no circular imports):
    from ..services import user_service
    user_service.some_function()
"""
# flake8: noqa: F401