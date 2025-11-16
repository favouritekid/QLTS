# tests/phase1_refactoring/test_task_1_3_user_service.py
"""
Test suite for PHASE 1 - Task 1.3: user_service.py refactoring

Verifies:
- No HTTPException imports in user_service.py
- Service raises custom exceptions (CacheServiceError, UserServiceError)
- Custom exceptions have proper attributes (detail, context)
- Exception types are correct
- Router exception handling works correctly
"""

import pytest
import ast
import inspect
from pathlib import Path

from app.services import user_service
from app.utils.exceptions import (
    BaseAppException,
    CacheServiceError,
    UserServiceError,
)


class TestTask13ServiceLayerRefactoring:
    """Test Task 1.3: Verify user_service.py refactoring."""

    def test_1_3_2_no_httpexception_import(self):
        """
        Task 1.3.2: Verify HTTPException is NOT imported in user_service.py

        Service layer should be protocol-independent.
        HTTPException is a FastAPI/HTTP-specific concern.
        """
        # Read the source file
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        source_code = service_path.read_text()

        # Parse AST
        tree = ast.parse(source_code)

        # Check imports
        http_exception_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        if alias.name == "HTTPException":
                            http_exception_imported = True
                            break
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "HTTPException" in alias.name:
                        http_exception_imported = True
                        break

        assert not http_exception_imported, \
            "HTTPException should NOT be imported in user_service.py (protocol independence)"

    def test_1_3_2_custom_exceptions_imported(self):
        """
        Task 1.3.2: Verify custom exceptions ARE imported in user_service.py
        """
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        source_code = service_path.read_text()

        # Check for custom exception imports
        assert "CacheServiceError" in source_code, \
            "CacheServiceError should be imported"
        assert "UserServiceError" in source_code, \
            "UserServiceError should be imported"
        assert "BaseAppException" in source_code, \
            "BaseAppException should be imported for type checking"

    def test_1_3_3_cache_service_error_attributes(self):
        """
        Task 1.3.3: Verify CacheServiceError has correct attributes

        Line 989 in user_service.py should raise CacheServiceError with:
        - detail: human-readable message
        - context: dict with operation, user_id, error
        """
        # Create instance as it would be raised in service
        exc = CacheServiceError(
            detail="Failed to invalidate sessions in cache",
            context={
                "operation": "redis_blacklist",
                "user_id": 123,
                "error": "Connection timeout",
            }
        )

        # Verify attributes
        assert exc.detail == "Failed to invalidate sessions in cache"
        assert exc.context["operation"] == "redis_blacklist"
        assert exc.context["user_id"] == 123
        assert exc.context["error"] == "Connection timeout"

        # Verify it's a service error
        assert isinstance(exc, BaseAppException)
        assert exc.status_code == 500
        assert exc.error_code == "CACHE_ERROR"

    def test_1_3_4_baseappexception_type_check(self):
        """
        Task 1.3.4: Verify BaseAppException is used for type checking

        Line 1037 should check isinstance(e, BaseAppException)
        """
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        source_code = service_path.read_text()

        # Verify the type check is updated
        assert "isinstance(e, BaseAppException)" in source_code, \
            "Should use BaseAppException for type checking (not HTTPException)"

        # Ensure HTTPException type check is removed
        assert "isinstance(e, HTTPException)" not in source_code, \
            "Should not check for HTTPException anymore"

    def test_1_3_5_user_service_error_attributes(self):
        """
        Task 1.3.5: Verify UserServiceError has correct attributes

        Line 1044 should raise UserServiceError with detail and context
        """
        exc = UserServiceError(
            detail="Could not invalidate sessions",
            context={"user_id": 456, "error": "Database error"}
        )

        assert exc.detail == "Could not invalidate sessions"
        assert exc.context["user_id"] == 456
        assert exc.context["error"] == "Database error"
        assert isinstance(exc, BaseAppException)
        assert exc.status_code == 500
        assert exc.error_code == "USER_SERVICE_ERROR"

    def test_1_3_source_code_verification(self):
        """
        Comprehensive source code verification for all Task 1.3 changes.
        """
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        source_code = service_path.read_text()

        # Verify specific refactored lines exist
        verifications = {
            "Line 989 - CacheServiceError": 'raise CacheServiceError(',
            "Line 1044 - UserServiceError": 'raise UserServiceError(',
            "Context in CacheServiceError": '"operation":',
            "Context in UserServiceError": '"user_id":',
            "BaseAppException import": 'BaseAppException',
        }

        for check_name, expected_text in verifications.items():
            assert expected_text in source_code, \
                f"{check_name} not found in user_service.py"

    def test_exception_hierarchy(self):
        """
        Verify exception hierarchy is correct.
        """
        # Test CacheServiceError
        cache_exc = CacheServiceError("Test")
        assert isinstance(cache_exc, BaseAppException)
        assert isinstance(cache_exc, Exception)

        # Test UserServiceError
        user_exc = UserServiceError("Test")
        assert isinstance(user_exc, BaseAppException)
        assert isinstance(user_exc, Exception)


class TestTask13RouterExceptionHandling:
    """Test Task 1.3.6: Verify router exception handling."""

    def test_1_3_6_auth_router_imports_custom_exceptions(self):
        """
        Task 1.3.6: Verify auth.py imports custom exceptions
        """
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        source_code = router_path.read_text()

        assert "from ..utils.exceptions import" in source_code, \
            "auth.py should import custom exceptions"
        assert "CacheServiceError" in source_code, \
            "auth.py should import CacheServiceError"
        assert "UserServiceError" in source_code, \
            "auth.py should import UserServiceError"

    def test_1_3_6_auth_router_catches_custom_exceptions(self):
        """
        Task 1.3.6: Verify auth.py catches custom exceptions

        Both password reset and password change handlers should catch:
        - CacheServiceError
        - UserServiceError
        """
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        source_code = router_path.read_text()

        # Check for exception catching
        assert "except (CacheServiceError, UserServiceError)" in source_code, \
            "auth.py should catch custom exceptions from user_service"

        # Should have 2 occurrences (password reset + password change)
        occurrences = source_code.count("except (CacheServiceError, UserServiceError)")
        assert occurrences >= 2, \
            f"Expected at least 2 exception handlers, found {occurrences}"

    def test_1_3_6_auth_router_converts_to_http_exception(self):
        """
        Task 1.3.6: Verify router converts custom exceptions to HTTPException
        """
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        source_code = router_path.read_text()

        # After catching custom exception, should raise HTTPException
        assert "raise HTTPException(" in source_code, \
            "Router should convert custom exceptions to HTTPException for API response"

        # Should log error context
        assert "error=e.detail" in source_code or "e.detail" in source_code, \
            "Router should access exception detail for logging"

    def test_1_3_6_no_old_httpexception_catch(self):
        """
        Task 1.3.6: Verify old HTTPException catch patterns are removed

        Old pattern was:
            except HTTPException:
                raise

        This should be replaced with custom exception handling.
        """
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"
        source_code = router_path.read_text()

        # Check that we're not just catching and re-raising HTTPException
        # from service layer (which no longer raises it)
        lines = source_code.split('\n')

        # Find exception handling blocks
        for i, line in enumerate(lines):
            if 'invalidate_all_sessions' in line:
                # Look at the next 20 lines for exception handling
                context = '\n'.join(lines[i:i+20])

                # Should NOT have the old pattern of catching HTTPException
                # immediately after service call
                if 'except HTTPException:' in context and 'raise' in context:
                    # Check if it's the old pattern (catch and re-raise)
                    # vs new pattern (convert custom exception to HTTPException)
                    following_lines = context.split('\n')
                    for j, following_line in enumerate(following_lines):
                        if 'except HTTPException:' in following_line:
                            # Check next few lines
                            next_lines = following_lines[j+1:j+5]
                            next_code = '\n'.join(next_lines)
                            if 'raise\n' in next_code or next_code.strip() == 'raise':
                                pytest.fail(
                                    "Found old pattern: 'except HTTPException: raise' "
                                    "This should be replaced with custom exception handling"
                                )


class TestTask13Summary:
    """Summary tests for Task 1.3 completion."""

    def test_task_1_3_completion_checklist(self):
        """
        Verify all Task 1.3 subtasks are completed.
        """
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        router_path = Path(__file__).parent.parent.parent / "app" / "routers" / "auth.py"

        service_code = service_path.read_text()
        router_code = router_path.read_text()

        checklist = {
            "1.3.2: No HTTPException import": "HTTPException" not in service_code or "from fastapi import UploadFile" in service_code,
            "1.3.2: Custom exceptions imported": "CacheServiceError" in service_code,
            "1.3.3: CacheServiceError raised": "raise CacheServiceError" in service_code,
            "1.3.4: BaseAppException type check": "isinstance(e, BaseAppException)" in service_code,
            "1.3.5: UserServiceError raised": "raise UserServiceError" in service_code,
            "1.3.6: Router imports custom exceptions": "CacheServiceError" in router_code,
            "1.3.6: Router catches custom exceptions": "except (CacheServiceError, UserServiceError)" in router_code,
        }

        failed_checks = []
        for check_name, passed in checklist.items():
            if not passed:
                failed_checks.append(check_name)

        assert not failed_checks, \
            f"Task 1.3 incomplete. Failed checks: {', '.join(failed_checks)}"

    def test_protocol_independence_achieved(self):
        """
        Verify service layer is protocol-independent.

        Service should not import or use FastAPI-specific classes except:
        - UploadFile (for file handling, acceptable)
        """
        service_path = Path(__file__).parent.parent.parent / "app" / "services" / "user_service.py"
        source_code = service_path.read_text()

        # Parse imports
        tree = ast.parse(source_code)

        fastapi_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "fastapi":
                    for alias in node.names:
                        fastapi_imports.append(alias.name)

        # Allowed FastAPI imports for user_service
        allowed = {"UploadFile"}  # File handling is OK

        forbidden = set(fastapi_imports) - allowed

        assert not forbidden, \
            f"Service has forbidden FastAPI imports: {forbidden}. " \
            f"Only {allowed} are allowed for protocol independence."
