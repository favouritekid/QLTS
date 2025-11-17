# Test Suite Documentation

This document describes the organization and structure of the Backend_FastAPI test suite.

## 📁 Directory Structure

```
tests/
├── unit/                    # Unit tests (fast, isolated, no external dependencies)
│   ├── core/               # Core functionality tests (security, dependencies)
│   ├── services/           # Service layer unit tests
│   └── conftest.py         # Mock fixtures for unit tests
│
├── integration/            # Integration tests (require external services)
│   ├── api/               # API endpoint integration tests
│   └── conftest.py        # Real database/Redis fixtures
│
├── security/              # Security-focused tests
│   └── test_*.py          # Authentication, authorization, encryption tests
│
├── refactoring/           # Refactoring verification tests
│   └── phase1/            # Phase 1: Service layer protocol independence
│
├── regression/            # Regression tests (prevent bugs from reappearing)
│
├── performance/           # Performance and load tests
│
├── e2e/                   # End-to-end tests (full user workflows)
│
├── fixtures/              # Shared test data and constants
│   ├── constants.py       # Test user credentials, test data
│   └── mock_data.py       # Mock objects and sample data
│
├── utils/                 # Test utilities and helpers
│
└── conftest.py            # Root fixtures (database, Redis, shared setup)
```

## 🏷️ Test Markers

Tests are categorized using pytest markers. Run specific categories with `-m <marker>`:

| Marker | Description | Example |
|--------|-------------|---------|
| `unit` | Fast, isolated tests with no external dependencies | `pytest -m unit` |
| `integration` | Tests requiring database, Redis, or Celery | `pytest -m integration` |
| `security` | Security-focused tests (auth, encryption, etc.) | `pytest -m security` |
| `performance` | Performance and stress tests | `pytest -m performance` |
| `e2e` | End-to-end user workflow tests | `pytest -m e2e` |
| `regression` | Tests preventing known bugs from returning | `pytest -m regression` |
| `refactoring` | Source code verification tests | `pytest -m refactoring` |
| `slow` | Long-running tests | `pytest -m "not slow"` |

## 🚀 Running Tests

### Run all tests
```bash
pytest
```

### Run specific category
```bash
# Unit tests only (fastest)
pytest -m unit

# Integration tests only
pytest -m integration

# Security tests
pytest -m security

# Refactoring verification
pytest -m refactoring
```

### Run specific directory
```bash
# All unit tests
pytest tests/unit/

# All integration tests
pytest tests/integration/

# Phase 1 refactoring tests
pytest tests/refactoring/phase1/
```

### Run specific file
```bash
pytest tests/unit/services/test_user_service_management.py
```

### Run specific test
```bash
pytest tests/unit/services/test_user_service_management.py::TestUserManagement::test_create_user
```

### Run with verbose output
```bash
pytest -v
pytest -vv  # Extra verbose
```

### Run and show print statements
```bash
pytest -s
```

### Run with coverage
```bash
pytest --cov=app --cov-report=html
```

### Common combinations
```bash
# Fast tests only (exclude slow and integration)
pytest -m "unit and not slow"

# All tests except integration (for CI without external services)
pytest -m "not integration"

# Verbose output for failed tests
pytest -v --tb=short
```

## 📝 Test Categories Explained

### Unit Tests (`tests/unit/`)
- **Purpose**: Test individual functions/methods in isolation
- **Speed**: Very fast (< 1 second each)
- **Dependencies**: None (uses mocks)
- **Example**: Test user_service.create_user() with mocked database

**Fixtures**: `mock_db_session`, `mock_redis_client`, `mock_user`

### Integration Tests (`tests/integration/`)
- **Purpose**: Test multiple components working together
- **Speed**: Slower (1-5 seconds each)
- **Dependencies**: PostgreSQL, Redis, Celery
- **Example**: Test full API endpoint with real database queries

**Fixtures**: `test_db`, `async_session`, `redis_client`, `test_client`

### Security Tests (`tests/security/`)
- **Purpose**: Verify authentication, authorization, encryption
- **Speed**: Fast to medium
- **Example**: Test JWT token validation, password hashing, role-based access

### Refactoring Tests (`tests/refactoring/`)
- **Purpose**: Verify refactoring work using AST parsing and source code analysis
- **Speed**: Very fast (no imports, just file reading)
- **Example**: Verify HTTPException removed from service layer

**Phase 1 Tests**:
- Task 1.3: user_service.py HTTPException removal
- Task 1.4: session_service.py DI pattern fix
- Task 1.5: activity_service.py Request removal

### Performance Tests (`tests/performance/`)
- **Purpose**: Measure response times, throughput, resource usage
- **Speed**: Very slow (minutes)
- **Example**: Load test API with 1000 concurrent requests

### E2E Tests (`tests/e2e/`)
- **Purpose**: Test complete user workflows from start to finish
- **Speed**: Slow (10-30 seconds each)
- **Example**: User registration → login → create lead → assign → complete

### Regression Tests (`tests/regression/`)
- **Purpose**: Prevent specific bugs from reappearing
- **Speed**: Varies
- **Example**: Test for bug #123 that was fixed in PR #456

## 🔧 Configuration

### pytest.ini
Configuration file at project root defines:
- Test discovery patterns
- Custom markers
- Default options
- Warning filters

### conftest.py Hierarchy
1. **tests/conftest.py**: Root fixtures (database, Redis, shared)
2. **tests/unit/conftest.py**: Mock fixtures for unit tests
3. **tests/integration/conftest.py**: Real service fixtures
4. **tests/refactoring/conftest.py**: No-op fixtures (source code tests don't need DB)

## 📊 Test Statistics

After reorganization:
- **Total tests**: 215+
- **Unit tests**: ~80
- **Integration tests**: ~100
- **Security tests**: ~20
- **Refactoring tests**: 48 (Phase 1)
- **Other**: ~17

## 🎯 Best Practices

### Writing New Tests

1. **Choose the right category**:
   - Does it need a database? → `integration/`
   - Pure logic test? → `unit/`
   - Security concern? → `security/`

2. **Use appropriate fixtures**:
   - Unit tests: Use mocks from `tests/unit/conftest.py`
   - Integration tests: Use real fixtures from `tests/integration/conftest.py`

3. **Mark your tests**:
```python
import pytest

@pytest.mark.unit
def test_calculate_total():
    assert calculate_total([1, 2, 3]) == 6

@pytest.mark.integration
async def test_create_user_endpoint(test_client, async_session):
    response = await test_client.post("/users", json={...})
    assert response.status_code == 201
```

4. **Use descriptive names**:
```python
# Good
def test_user_creation_fails_with_duplicate_email()

# Bad
def test_user()
```

5. **Follow AAA pattern**:
```python
def test_example():
    # Arrange
    user = User(email="test@example.com")

    # Act
    result = validate_user(user)

    # Assert
    assert result is True
```

### Running Tests in Development

```bash
# Quick feedback loop (unit tests only)
pytest -m unit

# Before committing (all tests except slow)
pytest -m "not slow"

# Before pushing (all tests)
pytest
```

### CI/CD Integration

```bash
# CI without external services
pytest -m "not integration and not e2e"

# Full test suite (with Docker services)
docker-compose up -d postgres redis
pytest
```

## 📈 Test Coverage

Generate coverage report:
```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

Target coverage: 80%+ for service layer, 60%+ overall

## 🐛 Debugging Tests

### Failed test with detailed output
```bash
pytest -vv --tb=long tests/path/to/test.py::test_name
```

### Run with debugger
```bash
pytest --pdb  # Drop into debugger on failure
```

### Show all logs
```bash
pytest -s --log-cli-level=DEBUG
```

## 📚 Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Pytest Markers](https://docs.pytest.org/en/stable/mark.html)
- [Testing FastAPI](https://fastapi.tiangolo.com/tutorial/testing/)

## 🔄 Migration History

**2024 Test Reorganization** (Commits: 5f3a18e, 0ec3ea3, be5003f, cf416d1, c5a1a09, 6023e35)

**Before**: 47 test files in 9 directories (messy, hard to navigate)
**After**: 47 test files in 7 organized categories (professional structure)

**Benefits**:
- ✅ Faster test discovery and execution
- ✅ Clear separation of concerns
- ✅ Easy to run specific test categories
- ✅ Better CI/CD integration
- ✅ Improved developer experience

**Key Changes**:
- Moved `tests/services/` → `tests/unit/services/`
- Moved `tests/core/` → `tests/unit/core/`
- Moved `tests/routers/` → `tests/integration/api/`
- Moved `tests/phase1_refactoring/` → `tests/refactoring/phase1/`
- Added 7 pytest markers
- Created category-specific conftest files
- Fixed import paths and path calculations

---

**Last Updated**: 2024-11-16
**Maintained By**: QLTS Development Team
