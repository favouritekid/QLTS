# tests/refactoring/phase1/test_task_1_6_role_service.py
"""
PHASE 1 - Task 1.6: Extract Role Management Verification Tests

Tests to verify that remove_role_from_users() has been properly extracted
to role_service.py and follows protocol-independent architecture.

Refactoring Completed:
- Business logic moved from router (admin.py) to service (role_service.py)
- Router now only handles HTTP concerns (request/response, DI)
- Service accepts dependencies via DI (db, enforcer)
- No HTTP-specific imports in service layer

Test Strategy:
1. Verify role_service.py exists and contains remove_role_from_users()
2. Verify service function has correct signature (db, enforcer params)
3. Verify service has no HTTP/FastAPI imports
4. Verify router imports and calls role_service
5. Verify ROLE_PRIORITY constant moved to service
6. Verify comprehensive documentation exists
"""

import ast
import inspect
from pathlib import Path

import pytest


class TestRoleServiceExists:
    """Test that role_service.py file exists and is structured correctly."""

    def test_role_service_file_exists(self):
        """Test that role_service.py file exists in services directory."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        assert service_path.exists(), (
            f"role_service.py not found at {service_path}. "
            "File should exist after Task 1.6 extraction."
        )

    def test_role_service_importable(self):
        """Test that role_service can be imported."""
        try:
            from app.services import role_service

            assert role_service is not None
        except ImportError as e:
            pytest.fail(f"Cannot import role_service: {e}")

    def test_role_service_exported_from_services_init(self):
        """Test that role_service is exported in services/__init__.py."""
        init_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "__init__.py"
        )

        with open(init_path, "r") as f:
            content = f.read()

        assert "role_service" in content, (
            "role_service not found in services/__init__.py. "
            "Service should be exported for use in routers."
        )


class TestRemoveRoleFromUsersInService:
    """Test that remove_role_from_users() function exists in role_service."""

    def test_remove_role_from_users_exists_in_service(self):
        """Test that remove_role_from_users() is defined in role_service.py."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find function definition
        function_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "remove_role_from_users":
                    function_found = True
                    break

        assert function_found, (
            "remove_role_from_users() not found in role_service.py. "
            "Function should be extracted from router to service."
        )

    def test_remove_role_from_users_signature(self):
        """
        Test that remove_role_from_users() has correct DI signature.

        Expected parameters:
        - db: AsyncSession (database dependency)
        - enforcer: casbin.AsyncEnforcer (Casbin dependency)
        - user_ids: List[int] (business data)
        - role_to_remove: str (business data)

        Should NOT have: request, current_admin (HTTP-specific)
        """
        from app.services import role_service

        func = role_service.remove_role_from_users
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Required DI parameters
        assert "db" in params, "Missing 'db' parameter (DI for database)"
        assert "enforcer" in params, "Missing 'enforcer' parameter (DI for Casbin)"

        # Business parameters
        assert "user_ids" in params, "Missing 'user_ids' parameter"
        assert "role_to_remove" in params, "Missing 'role_to_remove' parameter"

        # HTTP parameters should NOT exist in service
        assert "request" not in params, (
            "Service should NOT have 'request' parameter (protocol coupling)"
        )
        assert "current_admin" not in params, (
            "Service should NOT have 'current_admin' parameter "
            "(authentication is router concern)"
        )

    def test_remove_role_from_users_is_async(self):
        """Test that remove_role_from_users() is an async function."""
        from app.services import role_service

        func = role_service.remove_role_from_users

        assert inspect.iscoroutinefunction(func), (
            "remove_role_from_users() should be async (uses await for DB/Casbin)"
        )


class TestServiceProtocolIndependence:
    """Test that role_service.py is protocol-independent (no HTTP imports)."""

    def test_no_fastapi_imports(self):
        """
        Test that role_service.py has NO FastAPI imports.

        Forbidden imports:
        - from fastapi import Request, HTTPException, etc.
        - from fastapi.responses import ...

        Service layer should be protocol-agnostic.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Check all import statements
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""

                # Forbidden: FastAPI imports
                assert not module.startswith("fastapi"), (
                    f"PROTOCOL COUPLING: Found FastAPI import in role_service.py: "
                    f"'from {module} import ...'\n"
                    "Service layer should NOT import from FastAPI."
                )

    def test_no_http_exception_raises(self):
        """
        Test that role_service.py does NOT raise HTTPException.

        Services should raise custom domain exceptions instead.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Simple text search (not perfect, but catches obvious violations)
        assert "HTTPException" not in source, (
            "Service should NOT raise HTTPException. "
            "Use custom exceptions (ResourceNotFoundError, etc.) instead."
        )

    def test_uses_custom_exceptions(self):
        """Test that role_service.py uses custom exceptions from utils.exceptions."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Check for custom exception import
        assert "from app.utils.exceptions import" in source, (
            "Service should import custom exceptions from app.utils.exceptions"
        )

        # Check for usage
        assert "ResourceNotFoundError" in source, (
            "Service should use ResourceNotFoundError for missing resources"
        )


class TestRouterRefactored:
    """Test that router has been refactored to call service."""

    def test_router_imports_role_service(self):
        """Test that admin.py router imports role_service."""
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        assert "role_service" in source, (
            "Router should import role_service to call service functions"
        )

    def test_router_calls_role_service(self):
        """
        Test that router's remove_role_from_users() calls role_service.

        Router should delegate to service layer, not contain business logic.
        """
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find router function
        router_func_found = False
        calls_service = False

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "remove_role_from_users":
                    router_func_found = True

                    # Check if function body calls role_service
                    for child in ast.walk(node):
                        if isinstance(child, ast.Await):
                            # Check if await calls role_service.remove_role_from_users
                            call_node = child.value
                            if isinstance(call_node, ast.Call):
                                if isinstance(call_node.func, ast.Attribute):
                                    if (
                                        isinstance(call_node.func.value, ast.Name)
                                        and call_node.func.value.id == "role_service"
                                        and call_node.func.attr
                                        == "remove_role_from_users"
                                    ):
                                        calls_service = True
                                        break

        assert router_func_found, "Router function remove_role_from_users() not found"
        assert calls_service, (
            "Router function should call role_service.remove_role_from_users(). "
            "Business logic should be in service, not router."
        )

    def test_router_function_is_thin(self):
        """
        Test that router function is 'thin' (minimal logic).

        Router should only:
        1. Extract dependencies from HTTP context (request.app.state.enforcer)
        2. Call service with injected dependencies
        3. Return service result

        It should NOT contain business logic (role priority, DB updates, etc.)
        """
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find router function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "remove_role_from_users":
                    # Count lines in function body (excluding docstring)
                    body_lines = [
                        n
                        for n in node.body
                        if not isinstance(n, ast.Expr)
                        or not isinstance(n.value, ast.Constant)
                    ]

                    # Thin router should have ~2-5 lines (extract enforcer, call service, return)
                    assert len(body_lines) <= 5, (
                        f"Router function has {len(body_lines)} lines of logic. "
                        "Should be thin (~2-5 lines): extract dependencies, call service, return. "
                        "Business logic should be in service layer."
                    )


class TestRolePriorityInService:
    """Test that ROLE_PRIORITY constant is in service layer."""

    def test_role_priority_constant_in_service(self):
        """
        Test that ROLE_PRIORITY constant is defined in role_service.py.

        Business constants belong in service layer, not router.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        assert "ROLE_PRIORITY" in source, (
            "ROLE_PRIORITY constant should be defined in role_service.py. "
            "Business constants belong in service layer."
        )

        # Verify it's a dict with role priorities
        assert '"role:admin"' in source, "ROLE_PRIORITY should include admin role"
        assert '"role:user"' in source, "ROLE_PRIORITY should include user role"

    def test_role_priority_not_in_router(self):
        """
        Test that ROLE_PRIORITY constant is NOT in router function.

        After refactoring, business constants should be in service only.
        """
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        # Parse AST to find router function
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "remove_role_from_users":
                    # Get function source
                    func_source = ast.unparse(node)

                    # ROLE_PRIORITY should NOT be defined in router function
                    assert "ROLE_PRIORITY" not in func_source, (
                        "ROLE_PRIORITY constant found in router function. "
                        "Business constants should be in service layer only."
                    )


class TestDocumentation:
    """Test that proper documentation exists."""

    def test_service_has_module_docstring(self):
        """Test that role_service.py has comprehensive module docstring."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "role_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)
        module_docstring = ast.get_docstring(tree)

        assert module_docstring is not None, "role_service.py should have a docstring"
        assert len(module_docstring) > 50, (
            "Module docstring should be comprehensive (>50 characters)"
        )

    def test_remove_role_from_users_has_docstring(self):
        """Test that remove_role_from_users() has comprehensive docstring."""
        from app.services import role_service

        func = role_service.remove_role_from_users
        docstring = func.__doc__

        assert docstring is not None, "Function should have docstring"
        assert len(docstring) > 100, (
            "Function docstring should be comprehensive (>100 characters)"
        )

        # Should document parameters
        assert "Args:" in docstring or "Parameters:" in docstring, (
            "Docstring should document parameters"
        )

        # Should document return value
        assert "Returns:" in docstring, "Docstring should document return value"

    def test_router_function_updated_docstring(self):
        """Test that router function docstring mentions refactoring."""
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "remove_role_from_users":
                    docstring = ast.get_docstring(node)

                    assert docstring is not None
                    assert (
                        "REFACTORED" in docstring.upper()
                        or "role_service" in docstring
                    ), (
                        "Router docstring should mention refactoring "
                        "and point to role_service"
                    )


# === SUMMARY ===
"""
Test Results Expected:
- All tests should PASS after Task 1.6 refactoring
- If any test fails, it indicates incomplete extraction

Refactoring Goals Verified:
1. ✅ Business logic moved to service layer (role_service.py)
2. ✅ Router is thin (only HTTP concerns)
3. ✅ Protocol independence (no FastAPI imports in service)
4. ✅ Proper DI pattern (db, enforcer injected)
5. ✅ Custom exceptions used (not HTTPException)
6. ✅ Business constants in service (ROLE_PRIORITY)
7. ✅ Comprehensive documentation

Migration Impact:
- Service can now be reused in non-HTTP contexts (CLI, gRPC, etc.)
- Easier to test (can inject mock dependencies)
- Better separation of concerns
"""
