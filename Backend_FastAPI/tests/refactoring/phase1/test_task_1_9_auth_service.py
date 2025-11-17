# tests/refactoring/phase1/test_task_1_9_auth_service.py
"""
PHASE 1 - Task 1.9: Extract Token Management Verification Tests

Tests to verify that token management functions have been properly extracted
to auth_service.py and follow protocol-independent architecture.

Refactoring Completed:
- Token functions moved from security.py to services/auth_service.py
- security.py re-exports functions for backward compatibility
- Password utilities remain in security.py (utility functions)
- No HTTP/FastAPI dependencies in token management

Test Strategy:
1. Verify auth_service.py exists and has all token functions
2. Verify function signatures are correct
3. Verify protocol independence (no HTTP imports)
4. Verify backward compatibility (security.py re-exports)
5. Verify comprehensive documentation
"""

import ast
import inspect
from pathlib import Path

import pytest


class TestAuthServiceExists:
    """Test that auth_service.py exists with all token functions."""

    def test_auth_service_file_exists(self):
        """Test that auth_service.py file exists."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "auth_service.py"
        )

        assert service_path.exists(), (
            "auth_service.py not found in app/services/. "
            "Token management should be extracted to service layer."
        )

    def test_auth_service_importable(self):
        """Test that auth_service can be imported."""
        try:
            from app.services import auth_service
        except ImportError as e:
            pytest.fail(f"Failed to import auth_service: {e}")

    def test_auth_service_exported_from_services_init(self):
        """Test that auth_service is exported from services/__init__.py."""
        init_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "__init__.py"
        )

        with open(init_path, "r") as f:
            content = f.read()

        assert "from . import auth_service" in content or "import auth_service" in content, (
            "auth_service should be exported from services/__init__.py"
        )


class TestTokenFunctionsInService:
    """Test that all token functions exist in auth_service with correct signatures."""

    EXPECTED_FUNCTIONS = [
        "create_access_token",
        "create_refresh_token",
        "create_password_reset_token",
        "verify_password_reset_token",
        "decode_token",
        "decode_token_for_invalidation",
    ]

    def test_all_token_functions_exist(self):
        """Test that all token management functions exist in auth_service."""
        from app.services import auth_service

        for func_name in self.EXPECTED_FUNCTIONS:
            assert hasattr(auth_service, func_name), (
                f"{func_name}() not found in auth_service. "
                f"Function should be extracted from security.py to auth_service.py"
            )

    def test_create_access_token_signature(self):
        """Test create_access_token has correct signature (DI pattern)."""
        from app.services import auth_service

        func = auth_service.create_access_token
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Required parameters
        assert "data" in params, "Missing 'data' parameter"
        assert "refresh_jti" in params, "Missing 'refresh_jti' parameter"

        # Optional parameters
        assert "expires_delta" in params, "Missing 'expires_delta' parameter"

        # Should NOT have HTTP-specific parameters
        assert "request" not in params, "Should NOT have 'request' parameter"

    def test_create_refresh_token_signature(self):
        """Test create_refresh_token has correct signature."""
        from app.services import auth_service

        func = auth_service.create_refresh_token
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        assert "data" in params, "Missing 'data' parameter"
        assert "expires_delta" in params, "Missing 'expires_delta' parameter"

    def test_decode_token_signature(self):
        """Test decode_token has correct signature."""
        from app.services import auth_service

        func = auth_service.decode_token
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        assert "token" in params, "Missing 'token' parameter"
        assert len(params) == 1, "Should only have 'token' parameter"


class TestProtocolIndependence:
    """Test that auth_service is protocol-independent."""

    def test_no_fastapi_imports(self):
        """Test that auth_service does NOT import FastAPI/HTTP modules."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "auth_service.py"
        )

        with open(service_path, "r") as f:
            content = f.read()

        # Should NOT import FastAPI
        assert "from fastapi" not in content, (
            "auth_service should NOT import fastapi (protocol coupling)"
        )
        assert "import fastapi" not in content, (
            "auth_service should NOT import fastapi (protocol coupling)"
        )

        # Should NOT import Request
        assert "from starlette.requests import Request" not in content, (
            "auth_service should NOT import Request (HTTP coupling)"
        )

    def test_uses_standard_types_only(self):
        """Test that auth_service uses only standard Python types."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "auth_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        # Find all function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name in [
                    "create_access_token",
                    "create_refresh_token",
                    "decode_token",
                ]:
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should use dict, str, not HTTP types
                    assert "Response" not in func_source, (
                        f"{node.name} should return standard types (str), not Response"
                    )
                    assert "HTTPException" not in func_source, (
                        f"{node.name} should not raise HTTPException"
                    )

    def test_raises_domain_exceptions(self):
        """Test that auth_service raises domain exceptions (InvalidToken), not HTTP."""
        from app.services import auth_service

        # decode_token should raise InvalidToken (domain exception)
        func_source = inspect.getsource(auth_service.decode_token)

        assert "InvalidToken" in func_source, (
            "decode_token should raise InvalidToken (domain exception)"
        )
        assert "HTTPException" not in func_source, (
            "decode_token should NOT raise HTTPException (HTTP exception)"
        )


class TestBackwardCompatibility:
    """Test that security.py maintains backward compatibility."""

    def test_security_reexports_token_functions(self):
        """Test that security.py re-exports token functions from auth_service."""
        security_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "security.py"
        )

        with open(security_path, "r") as f:
            content = f.read()

        # Should import from auth_service
        assert "from .services.auth_service import" in content, (
            "security.py should import token functions from auth_service"
        )

        # Should import these specific functions
        expected_imports = [
            "create_access_token",
            "create_refresh_token",
            "decode_token",
        ]

        for func_name in expected_imports:
            assert func_name in content, (
                f"security.py should re-export {func_name} for backward compatibility"
            )

    def test_security_still_has_password_functions(self):
        """Test that password utility functions remain in security.py."""
        from app import security

        # Password functions should still be in security.py
        assert hasattr(security, "verify_password"), (
            "verify_password should remain in security.py (utility function)"
        )
        assert hasattr(security, "get_password_hash"), (
            "get_password_hash should remain in security.py (utility function)"
        )

    def test_can_import_from_security(self):
        """Test that token functions can still be imported from security.py."""
        try:
            from app.security import (
                create_access_token,
                create_refresh_token,
                decode_token,
            )
        except ImportError as e:
            pytest.fail(
                f"Failed to import token functions from security.py: {e}. "
                f"Backward compatibility broken!"
            )

    def test_can_import_from_auth_service(self):
        """Test that token functions can be imported from auth_service directly."""
        try:
            from app.services.auth_service import (
                create_access_token,
                create_refresh_token,
                decode_token,
            )
        except ImportError as e:
            pytest.fail(
                f"Failed to import token functions from auth_service: {e}"
            )


class TestDocumentation:
    """Test that proper documentation exists."""

    def test_auth_service_has_module_docstring(self):
        """Test that auth_service.py has comprehensive module docstring."""
        from app.services import auth_service

        assert auth_service.__doc__ is not None, (
            "auth_service.py should have module docstring"
        )
        assert len(auth_service.__doc__) > 200, (
            "auth_service.py module docstring should be comprehensive"
        )

        # Should mention Task 1.9
        assert "Task 1.9" in auth_service.__doc__ or "1.9" in auth_service.__doc__, (
            "Module docstring should mention Task 1.9"
        )

    def test_token_functions_have_docstrings(self):
        """Test that all token functions have comprehensive docstrings."""
        from app.services import auth_service

        functions_to_check = [
            "create_access_token",
            "create_refresh_token",
            "decode_token",
        ]

        for func_name in functions_to_check:
            func = getattr(auth_service, func_name)
            docstring = func.__doc__

            assert docstring is not None, f"{func_name} should have docstring"
            assert len(docstring) > 100, (
                f"{func_name} docstring should be comprehensive (>100 chars)"
            )

            # Should document parameters
            assert "Args:" in docstring or "Parameters:" in docstring, (
                f"{func_name} docstring should document parameters"
            )

            # Should document return value
            assert "Returns:" in docstring, (
                f"{func_name} docstring should document return value"
            )

    def test_security_module_updated_docstring(self):
        """Test that security.py docstring mentions refactoring."""
        from app import security

        docstring = security.__doc__

        assert docstring is not None, "security.py should have module docstring"

        # Should mention refactoring or Task 1.9
        assert (
            "REFACTORED" in docstring.upper()
            or "Task 1.9" in docstring
            or "auth_service" in docstring
        ), (
            "security.py docstring should mention refactoring and point to auth_service"
        )


# === SUMMARY ===
"""
Test Results Expected:
- All tests should PASS after Task 1.9 refactoring
- If any test fails, it indicates incomplete extraction

Refactoring Goals Verified:
1. ✅ Token functions moved to service layer (auth_service.py)
2. ✅ Protocol independence (no HTTP imports)
3. ✅ Proper exception handling (InvalidToken, not HTTPException)
4. ✅ Backward compatibility (security.py re-exports)
5. ✅ Password utilities remain in security.py
6. ✅ Comprehensive documentation

Migration Impact:
- Token functions now reusable in non-HTTP contexts (CLI, Celery, etc.)
- Easier to test (no HTTP infrastructure needed)
- Better separation of concerns
- Backward compatible (existing imports still work)
"""
