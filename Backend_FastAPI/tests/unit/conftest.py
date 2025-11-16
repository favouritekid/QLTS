# tests/unit/conftest.py
"""
Fixtures for unit tests.

Unit tests should:
- Be fast (< 1 second each)
- Have no external dependencies (no DB, Redis, etc.)
- Use mocks for external services
- Test single units of code in isolation
"""

import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_db_session():
    """Mock database session for unit tests."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.begin = MagicMock()
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client for unit tests."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    redis.setex = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_request():
    """Mock FastAPI Request for unit tests."""
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get = MagicMock(return_value="Mozilla/5.0")
    return request
