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
# Import shared fixtures from root conftest
# This allows integration tests to use database and Redis fixtures
