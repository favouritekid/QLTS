# tests/phase1_refactoring/test_task_1_4_verification.py
"""
Test suite for PHASE 1 - Task 1.4: session_service.py DI pattern refactoring (Source Code Verification)

This test file verifies the source code directly using AST parsing and text analysis.

Verifies:
- No HTTPException imports in session_service.py
- No AsyncSessionLocal() usage in functions (DI pattern violation)
- Service functions accept db parameter
- Custom exceptions properly used (SessionRevocationError, SessionServiceError)
- Router passes db parameter to service calls
"""

import pytest
import ast
from pathlib import Path


class TestTask14SourceCodeVerification:
    """Test Task 1.4 by analyzing source code directly."""

    @pytest.fixture
    def session_service_source(self):
        """Load session_service.py source code."""
        service_path = Path(__file__).parent.parent.parent.parent / "app" / "services" / "session_service.py"
        return service_path.read_text()

    @pytest.fixture
    def sessions_router_source(self):
        """Load sessions.py router source code."""
        router_path = Path(__file__).parent.parent.parent.parent / "app" / "routers" / "sessions.py"
        return router_path.read_text()

    def test_1_4_1_no_httpexception_import(self, session_service_source):
        """
        Task 1.4.1: Verify HTTPException is NOT imported in session_service.py
        """
        tree = ast.parse(session_service_source)

        http_exception_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        if alias.name == "HTTPException":
                            http_exception_imported = True
                            break

        assert not http_exception_imported, \
            "✗ HTTPException should NOT be imported in session_service.py (Task 1.4.1 failed)"

        print("✓ Task 1.4.1: HTTPException removed from imports")

    def test_1_4_1_custom_exceptions_imported(self, session_service_source):
        """
        Task 1.4.1: Verify custom exceptions ARE imported
        """
        required_imports = [
            "SessionRevocationError",
            "SessionServiceError",
        ]

        for exc_name in required_imports:
            assert exc_name in session_service_source, \
                f"✗ {exc_name} should be imported (Task 1.4.1 failed)"

        print(f"✓ Task 1.4.1: Custom exceptions imported: {required_imports}")

    def test_1_4_2_session_revocation_error_used(self, session_service_source):
        """
        Task 1.4.2: Verify SessionRevocationError is raised
        """
        assert "raise SessionRevocationError(" in session_service_source, \
            "✗ SessionRevocationError should be raised (Task 1.4.2 failed)"

        # Check for proper context
        assert '"session_id":' in session_service_source, \
            "✗ SessionRevocationError should include 'session_id' in context"
        assert '"error":' in session_service_source, \
            "✗ SessionRevocationError should include 'error' in context"

        print("✓ Task 1.4.2: SessionRevocationError raised with proper context")

    def test_1_4_3_no_asyncsessionlocal_creation(self, session_service_source):
        """
        Task 1.4.3: Verify AsyncSessionLocal() is NOT created in functions (DI violation)

        CRITICAL: Services should accept db parameter, not create their own sessions.
        """
        # Check for anti-pattern: async with AsyncSessionLocal() as db:
        lines = session_service_source.split('\n')

        violations = []
        for i, line in enumerate(lines, 1):
            # Look for actual usage (not comments)
            if "AsyncSessionLocal()" in line and not line.strip().startswith("#"):
                violations.append(f"Line {i}: {line.strip()}")

        assert not violations, \
            f"✗ Found AsyncSessionLocal() creation (DI anti-pattern):\n" + "\n".join(violations)

        print("✓ Task 1.4.3: No AsyncSessionLocal() creation (DI pattern correct)")

    def test_1_4_3_revoke_session_has_db_parameter(self, session_service_source):
        """
        Task 1.4.3: Verify revoke_session() accepts db parameter
        """
        # Find function definition
        lines = session_service_source.split('\n')

        found_function = False
        has_db_param = False

        for i, line in enumerate(lines):
            if 'async def revoke_session(' in line:
                found_function = True
                # Check next 5 lines for db parameter
                function_def = '\n'.join(lines[i:i+6])
                if 'db: AsyncSession' in function_def:
                    has_db_param = True
                break

        assert found_function, "✗ revoke_session() function not found"
        assert has_db_param, "✗ revoke_session() should have 'db: AsyncSession' parameter"

        print("✓ Task 1.4.3: revoke_session() accepts db parameter (DI pattern)")

    def test_1_4_3_revoke_all_other_sessions_has_db_parameter(self, session_service_source):
        """
        Task 1.4.3: Verify revoke_all_other_sessions() accepts db parameter
        """
        lines = session_service_source.split('\n')

        found_function = False
        has_db_param = False

        for i, line in enumerate(lines):
            if 'async def revoke_all_other_sessions(' in line:
                found_function = True
                # Check next 5 lines for db parameter
                function_def = '\n'.join(lines[i:i+6])
                if 'db: AsyncSession' in function_def:
                    has_db_param = True
                break

        assert found_function, "✗ revoke_all_other_sessions() function not found"
        assert has_db_param, "✗ revoke_all_other_sessions() should have 'db: AsyncSession' parameter"

        print("✓ Task 1.4.3: revoke_all_other_sessions() accepts db parameter (DI pattern)")

    def test_1_4_4_router_injects_db(self, sessions_router_source):
        """
        Task 1.4.4: Verify router injects db dependency
        """
        # Check for Depends(database.get_db)
        assert "db: AsyncSession = Depends(database.get_db)" in sessions_router_source, \
            "✗ Router should inject db dependency (Task 1.4.4 failed)"

        # Should appear at least 2 times (revoke_session + revoke_all_other_sessions)
        count = sessions_router_source.count("db: AsyncSession = Depends(database.get_db)")
        assert count >= 2, \
            f"✗ Expected at least 2 db injections, found {count}"

        print(f"✓ Task 1.4.4: Router injects db dependency ({count} endpoints)")

    def test_1_4_4_router_passes_db_to_revoke_session(self, sessions_router_source):
        """
        Task 1.4.4: Verify router passes db to revoke_session()
        """
        lines = sessions_router_source.split('\n')

        found_call = False
        passes_db = False

        for i, line in enumerate(lines):
            if 'session_service.revoke_session(' in line:
                found_call = True
                # Check next 5 lines for db=db
                call_context = '\n'.join(lines[i:i+6])
                if 'db=db' in call_context:
                    passes_db = True
                break

        assert found_call, "✗ revoke_session() call not found in router"
        assert passes_db, "✗ Router should pass db=db to revoke_session()"

        print("✓ Task 1.4.4: Router passes db to revoke_session()")

    def test_1_4_4_router_passes_db_to_revoke_all_other_sessions(self, sessions_router_source):
        """
        Task 1.4.4: Verify router passes db to revoke_all_other_sessions()
        """
        lines = sessions_router_source.split('\n')

        found_call = False
        passes_db = False

        for i, line in enumerate(lines):
            if 'session_service.revoke_all_other_sessions(' in line:
                found_call = True
                # Check next 5 lines for db=db
                call_context = '\n'.join(lines[i:i+6])
                if 'db=db' in call_context:
                    passes_db = True
                break

        assert found_call, "✗ revoke_all_other_sessions() call not found in router"
        assert passes_db, "✗ Router should pass db=db to revoke_all_other_sessions()"

        print("✓ Task 1.4.4: Router passes db to revoke_all_other_sessions()")

    def test_no_raise_httpexception_in_service(self, session_service_source):
        """
        Verify service never raises HTTPException (should use custom exceptions)
        """
        assert "raise HTTPException" not in session_service_source, \
            "✗ Service should NOT raise HTTPException (use custom exceptions instead)"

        print("✓ Service layer never raises HTTPException")

    def test_protocol_independence(self, session_service_source):
        """
        Verify service layer is protocol-independent (no FastAPI HTTP-specific imports)
        """
        tree = ast.parse(session_service_source)

        fastapi_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        fastapi_imports.append(alias.name)

        # Only status is allowed (for status codes, but we should minimize this)
        allowed = {"status"}
        forbidden = set(fastapi_imports) - allowed

        assert not forbidden, \
            f"✗ Service has forbidden FastAPI imports: {forbidden}"

        print(f"✓ Protocol independence achieved (allowed: {allowed})")


class TestTask14CompletionSummary:
    """Summary test for Task 1.4 completion."""

    @pytest.fixture
    def session_service_source(self):
        service_path = Path(__file__).parent.parent.parent.parent / "app" / "services" / "session_service.py"
        return service_path.read_text()

    @pytest.fixture
    def sessions_router_source(self):
        router_path = Path(__file__).parent.parent.parent.parent / "app" / "routers" / "sessions.py"
        return router_path.read_text()

    def test_task_1_4_all_subtasks_complete(self, session_service_source, sessions_router_source):
        """
        Verify ALL Task 1.4 subtasks are completed.

        Checklist:
        - [x] 1.4.1: Replace HTTPException imports
        - [x] 1.4.2: Implement SessionRevocationError
        - [x] 1.4.3: Fix DI pattern - add db parameter, remove AsyncSessionLocal
        - [x] 1.4.4: Update router to pass db parameter
        - [x] 1.4.5: Verify tests pass (this test)
        """
        checklist = {
            "1.4.1: No HTTPException import": "HTTPException" not in session_service_source or "from fastapi import status" in session_service_source,
            "1.4.1: Custom exceptions imported": all(exc in session_service_source for exc in ["SessionRevocationError", "SessionServiceError"]),
            "1.4.2: SessionRevocationError raised": "raise SessionRevocationError(" in session_service_source,
            "1.4.3: No AsyncSessionLocal() creation": "AsyncSessionLocal()" not in session_service_source.replace("#", ""),
            "1.4.3: revoke_session has db param": "async def revoke_session(\n    db: AsyncSession" in session_service_source,
            "1.4.3: revoke_all_other_sessions has db param": "async def revoke_all_other_sessions(\n    db: AsyncSession" in session_service_source,
            "1.4.4: Router injects db": "db: AsyncSession = Depends(database.get_db)" in sessions_router_source,
            "1.4.4: Router passes db to revoke_session": "session_service.revoke_session(\n            db=db" in sessions_router_source,
            "1.4.4: Router passes db to revoke_all_other_sessions": "session_service.revoke_all_other_sessions(\n            db=db" in sessions_router_source,
        }

        passed = sum(1 for v in checklist.values() if v)
        total = len(checklist)

        print(f"\n{'='*60}")
        print(f"TASK 1.4 COMPLETION STATUS: {passed}/{total} checks passed")
        print(f"{'='*60}")

        for task, status in checklist.items():
            symbol = "✓" if status else "✗"
            print(f"{symbol} {task}")

        print(f"{'='*60}")

        # Report failed tasks
        failed = [task for task, status in checklist.items() if not status]
        if failed:
            pytest.fail(f"Task 1.4 incomplete. Failed: {', '.join(failed)}")

        print("\n✅ TASK 1.4 FULLY COMPLETED - ALL CHECKS PASSED")
        print(f"{'='*60}\n")
