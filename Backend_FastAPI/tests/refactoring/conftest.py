# tests/refactoring/conftest.py
"""
Fixtures for refactoring verification tests.

These tests verify source code directly using AST parsing,
so they don't need database or Redis connections.
"""

import pytest


@pytest.fixture(scope="function", autouse=False)
async def setup_test_database():
    """No-op fixture - refactoring tests don't need database."""
    yield None


@pytest.fixture(scope="function", autouse=False)
async def setup_test_redis():
    """No-op fixture - refactoring tests don't need Redis."""
    yield None
