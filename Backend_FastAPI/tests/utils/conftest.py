# tests/utils/conftest.py
"""
Local conftest for utils tests that don't require database/Redis fixtures.

This file overrides the parent conftest.py to prevent automatic database
setup for simple unit tests like test_exceptions.py.
"""

import pytest


# Override the setup_test_database fixture to do nothing
# Exception tests don't need database
@pytest.fixture(scope="function", autouse=False)
async def setup_test_database():
    """
    No-op fixture for utils tests.

    Utils tests (like exception tests) don't need database setup.
    This override prevents the parent conftest from setting up database.
    """
    yield None


# Override redis_client fixture to do nothing
@pytest.fixture(scope="function", autouse=False)
async def redis_client():
    """
    No-op fixture for utils tests.

    Utils tests don't need Redis.
    """
    yield None


# Override db fixture to do nothing
@pytest.fixture(scope="function", autouse=False)
async def db():
    """
    No-op fixture for utils tests.

    Utils tests don't need database sessions.
    """
    yield None
