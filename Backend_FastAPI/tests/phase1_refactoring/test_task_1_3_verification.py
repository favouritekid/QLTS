# tests/phase1_refactoring/test_task_1_3_verification.py
"""
Test suite for PHASE 1 - Task 1.3: user_service.py refactoring (Source Code Verification)

This test file does NOT import app modules (to avoid dependency issues).
Instead, it verifies the source code directly using AST parsing and text analysis.

Verifies:
- No HTTPException imports in user_service.py
- Service raises custom exceptions (CacheServiceError, UserServiceError)
- Custom exceptions have proper context
- Router exception handling works correctly
"""

import pytest
import ast
from pathlib import Path


class TestTask13SourceCodeVerification:
    """Test Task 1.3 by analyzing source code directly."""

    @pytest.fixture
    def user_service_source(self):
        """Load user_service.py source code."""
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        return service_path.read_text()

    @pytest.fixture
    def auth_router_source(self):
        """Load auth.py router source code."""
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        return router_path.read_text()

    def test_1_3_2_no_httpexception_import(self, user_service_source):
        """
        Task 1.3.2: Verify HTTPException is NOT imported in user_service.py
        """
        tree = ast.parse(user_service_source)

        http_exception_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        if alias.name == "HTTPException":
                            http_exception_imported = True
                            break

        assert not http_exception_imported, \
            "✗ HTTPException should NOT be imported in user_service.py (Task 1.3.2 failed)"

        print("✓ Task 1.3.2: HTTPException removed from imports")

    def test_1_3_2_custom_exceptions_imported(self, user_service_source):
        """
        Task 1.3.2: Verify custom exceptions ARE imported
        """
        required_imports = [
            "CacheServiceError",
            "UserServiceError",
            "BaseAppException",
        ]

        for exc_name in required_imports:
            assert exc_name in user_service_source, \
                f"✗ {exc_name} should be imported (Task 1.3.2 failed)"

        print(f"✓ Task 1.3.2: All custom exceptions imported: {required_imports}")

    def test_1_3_3_cache_service_error_raised(self, user_service_source):
        """
        Task 1.3.3: Verify CacheServiceError is raised (Line 989)
        """
        # Check for CacheServiceError raise statement
        assert "raise CacheServiceError(" in user_service_source, \
            "✗ CacheServiceError should be raised (Task 1.3.3 failed)"

        # Check for proper context
        assert '"operation":' in user_service_source, \
            "✗ CacheServiceError should include 'operation' in context"
        assert '"error":' in user_service_source, \
            "✗ CacheServiceError should include 'error' in context"

        # Check for specific error message
        assert "Failed to invalidate sessions in cache" in user_service_source, \
            "✗ CacheServiceError should have proper detail message"

        print("✓ Task 1.3.3: CacheServiceError raised with proper context")

    def test_1_3_4_baseappexception_type_check(self, user_service_source):
        """
        Task 1.3.4: Verify BaseAppException is used for type checking (Line 1037)
        """
        assert "isinstance(e, BaseAppException)" in user_service_source, \
            "✗ Should use BaseAppException for type checking (Task 1.3.4 failed)"

        # Ensure old pattern is removed
        assert "isinstance(e, HTTPException)" not in user_service_source, \
            "✗ Should not check isinstance(e, HTTPException) anymore"

        print("✓ Task 1.3.4: Type check updated to BaseAppException")

    def test_1_3_5_user_service_error_raised(self, user_service_source):
        """
        Task 1.3.5: Verify UserServiceError is raised (Line 1044)
        """
        assert "raise UserServiceError(" in user_service_source, \
            "✗ UserServiceError should be raised (Task 1.3.5 failed)"

        # Check for proper error message
        assert "Could not invalidate sessions" in user_service_source, \
            "✗ UserServiceError should have proper detail message"

        print("✓ Task 1.3.5: UserServiceError raised with proper context")

    def test_1_3_6_router_imports_custom_exceptions(self, auth_router_source):
        """
        Task 1.3.6: Verify auth.py imports custom exceptions
        """
        assert "from ..utils.exceptions import" in auth_router_source, \
            "✗ auth.py should import from utils.exceptions"

        required_imports = ["CacheServiceError", "UserServiceError"]
        for exc_name in required_imports:
            assert exc_name in auth_router_source, \
                f"✗ auth.py should import {exc_name} (Task 1.3.6 failed)"

        print(f"✓ Task 1.3.6: Router imports custom exceptions: {required_imports}")

    def test_1_3_6_router_catches_custom_exceptions(self, auth_router_source):
        """
        Task 1.3.6: Verify router catches custom exceptions
        """
        # Check for proper exception catching
        assert "except (CacheServiceError, UserServiceError)" in auth_router_source, \
            "✗ Router should catch (CacheServiceError, UserServiceError)"

        # Count occurrences (should be 2: password reset + password change)
        occurrences = auth_router_source.count("except (CacheServiceError, UserServiceError)")
        assert occurrences >= 2, \
            f"✗ Expected at least 2 exception handlers, found {occurrences}"

        print(f"✓ Task 1.3.6: Router catches custom exceptions ({occurrences} handlers)")

    def test_1_3_6_router_logs_error_context(self, auth_router_source):
        """
        Task 1.3.6: Verify router logs error context from exceptions
        """
        # Router should access exception attributes
        assert "e.detail" in auth_router_source, \
            "✗ Router should log exception detail"
        assert "e.context" in auth_router_source, \
            "✗ Router should log exception context"

        print("✓ Task 1.3.6: Router logs error detail and context")

    def test_1_3_6_router_converts_to_httpexception(self, auth_router_source):
        """
        Task 1.3.6: Verify router converts custom exceptions to HTTPException
        """
        # After catching custom exceptions, should raise HTTPException
        lines = auth_router_source.split('\n')

        found_pattern = False
        for i, line in enumerate(lines):
            if 'except (CacheServiceError, UserServiceError)' in line:
                # Check next 10 lines for HTTPException raise
                context = '\n'.join(lines[i:i+10])
                if 'raise HTTPException' in context:
                    found_pattern = True
                    break

        assert found_pattern, \
            "✗ Router should raise HTTPException after catching custom exceptions"

        print("✓ Task 1.3.6: Router converts custom exceptions to HTTPException")

    def test_no_raise_httpexception_in_service(self, user_service_source):
        """
        Verify service never raises HTTPException (should use custom exceptions)
        """
        assert "raise HTTPException" not in user_service_source, \
            "✗ Service should NOT raise HTTPException (use custom exceptions instead)"

        print("✓ Service layer never raises HTTPException")

    def test_protocol_independence(self, user_service_source):
        """
        Verify service layer is protocol-independent (no FastAPI HTTP-specific imports)
        """
        tree = ast.parse(user_service_source)

        fastapi_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        fastapi_imports.append(alias.name)

        # Only UploadFile is allowed (for file handling)
        allowed = {"UploadFile"}
        forbidden = set(fastapi_imports) - allowed

        assert not forbidden, \
            f"✗ Service has forbidden FastAPI imports: {forbidden}"

        print(f"✓ Protocol independence achieved (only allowed: {allowed})")


class TestTask13CompletionSummary:
    """Summary test for Task 1.3 completion."""

    @pytest.fixture
    def user_service_source(self):
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        return service_path.read_text()

    @pytest.fixture
    def auth_router_source(self):
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        return router_path.read_text()

    def test_task_1_3_all_subtasks_complete(self, user_service_source, auth_router_source):
        """
        Verify ALL Task 1.3 subtasks are completed.

        Checklist:
        - [x] 1.3.2: Replace HTTPException imports
        - [x] 1.3.3: Refactor Line 984 (CacheServiceError)
        - [x] 1.3.4: Refactor Line 1027 (type check)
        - [x] 1.3.5: Refactor Line 1034 (UserServiceError)
        - [x] 1.3.6: Update router handlers
        - [ ] 1.3.7: Integration tests (manual verification)
        """
        checklist = {
            "1.3.2: No HTTPException import": "HTTPException" not in user_service_source.split("from fastapi import")[1].split("\n")[0] if "from fastapi import" in user_service_source else True,
            "1.3.2: Custom exceptions imported": all(exc in user_service_source for exc in ["CacheServiceError", "UserServiceError", "BaseAppException"]),
            "1.3.3: CacheServiceError raised": "raise CacheServiceError(" in user_service_source,
            "1.3.4: BaseAppException type check": "isinstance(e, BaseAppException)" in user_service_source,
            "1.3.5: UserServiceError raised": "raise UserServiceError(" in user_service_source,
            "1.3.6: Router imports exceptions": all(exc in auth_router_source for exc in ["CacheServiceError", "UserServiceError"]),
            "1.3.6: Router catches exceptions": "except (CacheServiceError, UserServiceError)" in auth_router_source,
            "1.3.6: Router converts to HTTP": "raise HTTPException" in auth_router_source,
        }

        passed = sum(1 for v in checklist.values() if v)
        total = len(checklist)

        print(f"\n{'='*60}")
        print(f"TASK 1.3 COMPLETION STATUS: {passed}/{total} checks passed")
        print(f"{'='*60}")

        for task, status in checklist.items():
            symbol = "✓" if status else "✗"
            print(f"{symbol} {task}")

        print(f"{'='*60}")

        # Report failed tasks
        failed = [task for task, status in checklist.items() if not status]
        if failed:
            pytest.fail(f"Task 1.3 incomplete. Failed: {', '.join(failed)}")

        print("\n✅ TASK 1.3 FULLY COMPLETED - ALL CHECKS PASSED")
        print(f"{'='*60}\n")
