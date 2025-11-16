# tests/phase1_refactoring/conftest.py
"""
Local conftest for PHASE 1 refactoring tests.

These tests verify protocol independence and proper exception handling,
but don't need full database setup.
"""

import pytest


# Override fixtures to skip database setup for simple verification tests
@pytest.fixture(scope="function", autouse=False)
async def setup_test_database():
    """No-op fixture - these tests don't need database."""
    yield None


@pytest.fixture(scope="function", autouse=False)
async def redis_client():
    """No-op fixture - these tests don't need Redis."""
    yield None


@pytest.fixture(scope="function", autouse=False)
async def db():
    """No-op fixture - these tests don't need database sessions."""
    yield None
