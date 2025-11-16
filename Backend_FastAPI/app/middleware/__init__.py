# app/middleware/__init__.py
"""Middleware package for the application."""

from .exception_handlers import register_exception_handlers

__all__ = ["register_exception_handlers"]
