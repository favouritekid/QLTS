# tests/integration/conftest.py
"""
Fixtures for integration tests.

Integration tests:
- Test components working together
- Use real database (test DB)
- Use real Redis (test Redis)
- Test API endpoints with real requests
- May be slower than unit tests
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

# Import shared fixtures from root conftest
# This allows integration tests to use database and Redis fixtures


@pytest_asyncio.fixture
async def db(setup_test_database) -> AsyncSession:
    """
    Provide a database session for integration tests.

    This fixture:
    1. Depends on setup_test_database to ensure schema is ready
    2. Creates a new AsyncSession for the test
    3. Yields the session for test use
    4. Closes the session after test completes

    Usage:
        async def test_something(db: AsyncSession):
            user = models.User(...)
            db.add(user)
            await db.commit()
    """
    async with AsyncSessionLocal() as session:
        yield session
