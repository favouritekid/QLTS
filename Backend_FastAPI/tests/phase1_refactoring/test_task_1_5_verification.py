# tests/phase1_refactoring/test_task_1_5_verification.py
"""
Test suite for PHASE 1 - Task 1.5: activity_service.py Request removal (Source Code Verification)

This test file verifies the source code directly using AST parsing and text analysis.

Verifies:
- No FastAPI Request imports in activity_service.py
- log_activity_from_request() function removed
- log_activity() accepts plain string parameters (ip_address, user_agent)
- Routers have helper functions that extract IP/UA from request
- Service layer is protocol-independent
"""

import pytest
import ast
from pathlib import Path


class TestTask15SourceCodeVerification:
    """Test Task 1.5 by analyzing source code directly."""

    @pytest.fixture
    def activity_service_source(self):
        """Load activity_service.py source code."""
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "activity_service.py"
        return service_path.read_text()

    @pytest.fixture
    def admin_router_source(self):
        """Load admin.py router source code."""
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "admin.py"
        return router_path.read_text()

    @pytest.fixture
    def profile_router_source(self):
        """Load profile.py router source code."""
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "profile.py"
        return router_path.read_text()

    def test_1_5_1_no_request_import(self, activity_service_source):
        """
        Task 1.5.1: Verify FastAPI Request is NOT imported in activity_service.py
        """
        tree = ast.parse(activity_service_source)

        request_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        if alias.name == "Request":
                            request_imported = True
                            break

        assert not request_imported, \
            "✗ Request should NOT be imported in activity_service.py (Task 1.5.1 failed)"

        print("✓ Task 1.5.1: Request import removed from activity_service.py")

    def test_1_5_1_verify_comment_about_removal(self, activity_service_source):
        """
        Task 1.5.1: Verify there's a comment documenting the Request removal
        """
        assert "PHASE 1: Removed FastAPI Request import" in activity_service_source or \
               "Removed Request import" in activity_service_source, \
            "✗ Should have comment documenting Request removal"

        print("✓ Task 1.5.1: Comment documenting Request removal exists")

    def test_1_5_2_log_activity_from_request_removed(self, activity_service_source):
        """
        Task 1.5.2: Verify log_activity_from_request() function is removed
        """
        # Check function definition is not present
        assert "def log_activity_from_request" not in activity_service_source, \
            "✗ log_activity_from_request() should be removed (Task 1.5.2 failed)"

        print("✓ Task 1.5.2: log_activity_from_request() function removed")

    def test_1_5_2_log_activity_exists_with_plain_params(self, activity_service_source):
        """
        Task 1.5.2: Verify log_activity() exists and accepts plain string parameters
        """
        # Check log_activity exists
        assert "async def log_activity(" in activity_service_source, \
            "✗ log_activity() function should exist"

        # Check for plain string parameters (not Request object)
        lines = activity_service_source.split('\n')
        found_function = False
        has_ip_param = False
        has_ua_param = False

        for i, line in enumerate(lines):
            if 'async def log_activity(' in line:
                found_function = True
                # Check next 20 lines for parameters
                function_def = '\n'.join(lines[i:i+20])
                if 'ip_address: Optional[str]' in function_def:
                    has_ip_param = True
                if 'user_agent: Optional[str]' in function_def:
                    has_ua_param = True
                break

        assert found_function, "✗ log_activity() function not found"
        assert has_ip_param, "✗ log_activity() should have 'ip_address: Optional[str]' parameter"
        assert has_ua_param, "✗ log_activity() should have 'user_agent: Optional[str]' parameter"

        print("✓ Task 1.5.2: log_activity() accepts plain string parameters (protocol-independent)")

    def test_1_5_3_admin_router_has_helper_function(self, admin_router_source):
        """
        Task 1.5.3: Verify admin.py has log_admin_activity() helper function
        """
        assert "async def log_admin_activity(" in admin_router_source, \
            "✗ admin.py should have log_admin_activity() helper function (Task 1.5.3 failed)"

        # Check it extracts IP address from request
        assert "request.client.host" in admin_router_source, \
            "✗ Helper should extract IP from request.client.host"

        # Check it extracts user agent from request
        assert 'request.headers.get("user-agent")' in admin_router_source or \
               "request.headers.get('user-agent')" in admin_router_source, \
            "✗ Helper should extract user-agent from request headers"

        # Check it calls activity_service.log_activity
        assert "await activity_service.log_activity(" in admin_router_source, \
            "✗ Helper should call activity_service.log_activity()"

        print("✓ Task 1.5.3: admin.py has log_admin_activity() helper with IP/UA extraction")

    def test_1_5_3_profile_router_has_helper_function(self, profile_router_source):
        """
        Task 1.5.3: Verify profile.py has log_profile_activity() helper function
        """
        assert "async def log_profile_activity(" in profile_router_source, \
            "✗ profile.py should have log_profile_activity() helper function (Task 1.5.3 failed)"

        # Check it extracts IP address from request
        assert "request.client.host" in profile_router_source, \
            "✗ Helper should extract IP from request.client.host"

        # Check it extracts user agent from request
        assert 'request.headers.get("user-agent")' in profile_router_source or \
               "request.headers.get('user-agent')" in profile_router_source, \
            "✗ Helper should extract user-agent from request headers"

        # Check it calls activity_service.log_activity
        assert "await activity_service.log_activity(" in profile_router_source, \
            "✗ Helper should call activity_service.log_activity()"

        print("✓ Task 1.5.3: profile.py has log_profile_activity() helper with IP/UA extraction")

    def test_1_5_4_no_calls_to_removed_function(self):
        """
        Task 1.5.4: Verify no routers are calling the removed log_activity_from_request()
        """
        import subprocess

        # Search all routers for calls to log_activity_from_request
        result = subprocess.run(
            ['grep', '-rn', 'await.*log_activity_from_request', 'app/routers/'],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent
        )

        # Should find no actual calls (only comments are OK)
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        actual_calls = [line for line in lines if not line.strip().startswith('#')]

        assert len(actual_calls) == 0, \
            f"✗ Found {len(actual_calls)} calls to removed function: {actual_calls}"

        print("✓ Task 1.5.4: No routers calling log_activity_from_request()")

    def test_1_5_helper_functions_pass_correct_params(self, admin_router_source, profile_router_source):
        """
        Task 1.5: Verify helper functions pass ip_address and user_agent to service
        """
        # Check admin helper - simplified check (just verify the parameters are passed somewhere)
        assert 'ip_address=ip_address' in admin_router_source, \
            "✗ admin helper should pass ip_address=ip_address to service"
        assert 'user_agent=user_agent' in admin_router_source, \
            "✗ admin helper should pass user_agent=user_agent to service"

        # Check profile helper
        assert 'ip_address=ip_address' in profile_router_source, \
            "✗ profile helper should pass ip_address=ip_address to service"
        assert 'user_agent=user_agent' in profile_router_source, \
            "✗ profile helper should pass user_agent=user_agent to service"

        print("✓ Task 1.5: Helper functions correctly pass ip_address and user_agent")

    def test_protocol_independence(self, activity_service_source):
        """
        Verify service layer is protocol-independent (no FastAPI-specific imports)
        """
        tree = ast.parse(activity_service_source)

        fastapi_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        fastapi_imports.append(alias.name)

        # activity_service should have NO FastAPI imports
        assert len(fastapi_imports) == 0, \
            f"✗ Service has FastAPI imports: {fastapi_imports}"

        print("✓ Protocol independence achieved (no FastAPI imports)")

    def test_service_uses_plain_types_only(self, activity_service_source):
        """
        Verify log_activity() uses only plain Python types (str, int, dict, etc.)
        No Request, HTTPException, or other framework-specific types.
        """
        # Check function signature
        lines = activity_service_source.split('\n')

        for i, line in enumerate(lines):
            if 'async def log_activity(' in line:
                # Get function signature (next 15 lines)
                signature = '\n'.join(lines[i:i+15])

                # Should NOT have Request parameter
                assert 'Request' not in signature, \
                    "✗ log_activity() should not have Request parameter"

                # Should have plain types
                assert 'Optional[str]' in signature, \
                    "✗ log_activity() should use Optional[str] for ip_address/user_agent"

                break

        print("✓ Service uses only plain Python types (protocol-independent)")


class TestTask15CompletionSummary:
    """Summary test for Task 1.5 completion."""

    @pytest.fixture
    def activity_service_source(self):
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "activity_service.py"
        return service_path.read_text()

    @pytest.fixture
    def admin_router_source(self):
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "admin.py"
        return router_path.read_text()

    @pytest.fixture
    def profile_router_source(self):
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "profile.py"
        return router_path.read_text()

    def test_task_1_5_all_subtasks_complete(
        self,
        activity_service_source,
        admin_router_source,
        profile_router_source
    ):
        """
        Verify ALL Task 1.5 subtasks are completed.

        Checklist:
        - [x] 1.5.1: Remove Request import
        - [x] 1.5.2: Refactor log_activity_from_request() (removed)
        - [x] 1.5.3: Update router to extract IP/UA (helpers created)
        - [x] 1.5.4: Update all callers (no calls to removed function)
        """
        checklist = {
            "1.5.1: No Request import": "from fastapi import Request" not in activity_service_source,
            "1.5.1: Removal documented": "PHASE 1" in activity_service_source or "Removed" in activity_service_source,
            "1.5.2: log_activity_from_request removed": "def log_activity_from_request" not in activity_service_source,
            "1.5.2: log_activity has plain params": "ip_address: Optional[str]" in activity_service_source,
            "1.5.3: admin.py has helper": "async def log_admin_activity(" in admin_router_source,
            "1.5.3: profile.py has helper": "async def log_profile_activity(" in profile_router_source,
            "1.5.3: Helpers extract IP": "request.client.host" in admin_router_source and "request.client.host" in profile_router_source,
            "1.5.3: Helpers extract UA": "user-agent" in admin_router_source.lower() and "user-agent" in profile_router_source.lower(),
            "Protocol independence": "from fastapi import Request" not in activity_service_source,
        }

        passed = sum(1 for v in checklist.values() if v)
        total = len(checklist)

        print(f"\n{'='*60}")
        print(f"TASK 1.5 COMPLETION STATUS: {passed}/{total} checks passed")
        print(f"{'='*60}")

        for task, status in checklist.items():
            symbol = "✓" if status else "✗"
            print(f"{symbol} {task}")

        print(f"{'='*60}")

        # Report failed tasks
        failed = [task for task, status in checklist.items() if not status]
        if failed:
            pytest.fail(f"Task 1.5 incomplete. Failed: {', '.join(failed)}")

        print("\n✅ TASK 1.5 FULLY COMPLETED - ALL CHECKS PASSED")
        print(f"{'='*60}\n")
