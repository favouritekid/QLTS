# tests/refactoring/phase1/test_task_1_7_user_sync_service.py
"""
PHASE 1 - Task 1.7: Extract User Sync Verification Tests

Tests to verify that sync_users_to_casbin() has been properly extracted
to user_service.py and follows protocol-independent architecture.

Refactoring Completed:
- Business logic moved from router (admin.py) to service (user_service.py)
- Router now only handles HTTP concerns (request/response, DI, admin logging)
- Service accepts dependencies via DI (db, enforcer)
- No HTTP-specific imports in service layer

Test Strategy:
1. Verify sync_users_to_casbin() exists in user_service.py
2. Verify service function has correct signature (db, enforcer, user_ids params)
3. Verify service function is async
4. Verify router imports and calls user_service
5. Verify router is thin (minimal logic)
6. Verify comprehensive documentation exists
"""

import ast
import inspect
from pathlib import Path

import pytest


class TestUserSyncServiceExists:
    """Test that sync_users_to_casbin() function exists in user_service.py."""

    def test_sync_users_to_casbin_exists_in_service(self):
        """Test that sync_users_to_casbin() is defined in user_service.py."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "user_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find function definition
        function_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "sync_users_to_casbin":
                    function_found = True
                    break

        assert function_found, (
            "sync_users_to_casbin() not found in user_service.py. "
            "Function should be extracted from router to service."
        )

    def test_sync_users_to_casbin_signature(self):
        """
        Test that sync_users_to_casbin() has correct DI signature.

        Expected parameters:
        - db: AsyncSession (database dependency)
        - enforcer: casbin.AsyncEnforcer (Casbin dependency)
        - user_ids: Optional[List[int]] (optional filter for specific users)

        Should NOT have: request, current_admin, sync_request (HTTP-specific)
        """
        from app.services import user_service

        func = user_service.sync_users_to_casbin
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Required DI parameters
        assert "db" in params, "Missing 'db' parameter (DI for database)"
        assert "enforcer" in params, "Missing 'enforcer' parameter (DI for Casbin)"

        # Business parameters
        assert "user_ids" in params, "Missing 'user_ids' parameter"

        # Verify user_ids is optional (has default value)
        user_ids_param = sig.parameters["user_ids"]
        assert user_ids_param.default is not inspect.Parameter.empty, (
            "'user_ids' should be optional (default=None) to support syncing all users"
        )

        # HTTP parameters should NOT exist in service
        assert "request" not in params, (
            "Service should NOT have 'request' parameter (protocol coupling)"
        )
        assert "current_admin" not in params, (
            "Service should NOT have 'current_admin' parameter "
            "(authentication is router concern)"
        )
        assert "sync_request" not in params, (
            "Service should NOT have 'sync_request' parameter (HTTP schema)"
        )

    def test_sync_users_to_casbin_is_async(self):
        """Test that sync_users_to_casbin() is an async function."""
        from app.services import user_service

        func = user_service.sync_users_to_casbin

        assert inspect.iscoroutinefunction(func), (
            "sync_users_to_casbin() should be async (uses await for DB/Casbin)"
        )


class TestUserSyncServiceProtocolIndependence:
    """Test that sync_users_to_casbin() is protocol-independent."""

    def test_service_has_no_request_dependency(self):
        """
        Test that sync_users_to_casbin() does NOT depend on HTTP Request.

        Service should receive all dependencies via parameters (DI pattern),
        not extract them from request object.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "user_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find sync_users_to_casbin function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "sync_users_to_casbin":
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should NOT access request.app.state
                    assert "request.app.state" not in func_source, (
                        "Service should NOT access request.app.state. "
                        "Dependencies should be injected via parameters."
                    )

                    # Should NOT access request at all
                    assert "request." not in func_source, (
                        "Service should NOT access HTTP request object. "
                        "Use dependency injection instead."
                    )

    def test_service_returns_dict_not_http_response(self):
        """
        Test that sync_users_to_casbin() returns plain dict, not HTTP response.

        Service layer should return domain objects/dicts.
        Router layer is responsible for HTTP response formatting.
        """
        from app.services import user_service

        func = user_service.sync_users_to_casbin
        sig = inspect.signature(func)

        # Check return annotation
        return_annotation = sig.return_annotation

        # Should be Dict or dict (not Response, JSONResponse, etc.)
        assert "Dict" in str(return_annotation) or "dict" in str(return_annotation), (
            "Service should return Dict/dict, not HTTP response object"
        )


class TestRouterRefactored:
    """Test that router has been refactored to call service."""

    def test_router_calls_user_service_sync(self):
        """
        Test that router's sync_users() calls user_service.sync_users_to_casbin().

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
                if node.name == "sync_users":
                    router_func_found = True

                    # Check if function body calls user_service.sync_users_to_casbin
                    for child in ast.walk(node):
                        if isinstance(child, ast.Await):
                            # Check if await calls user_service.sync_users_to_casbin
                            call_node = child.value
                            if isinstance(call_node, ast.Call):
                                if isinstance(call_node.func, ast.Attribute):
                                    # Check for services.user_service.sync_users_to_casbin
                                    if (
                                        call_node.func.attr == "sync_users_to_casbin"
                                        and isinstance(call_node.func.value, ast.Attribute)
                                        and call_node.func.value.attr == "user_service"
                                    ):
                                        calls_service = True
                                        break

        assert router_func_found, "Router function sync_users() not found"
        assert calls_service, (
            "Router function should call services.user_service.sync_users_to_casbin(). "
            "Business logic should be in service, not router."
        )

    def test_router_function_is_thin(self):
        """
        Test that router function is 'thin' (minimal logic).

        Router should only:
        1. Extract dependencies from HTTP context (request.app.state.enforcer)
        2. Call service with injected dependencies
        3. Commit transaction
        4. Log admin activity (HTTP/audit concern)
        5. Return service result

        It should NOT contain business logic (role sync, DB updates, etc.)
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
                if node.name == "sync_users":
                    # Count lines in function body (excluding docstring)
                    body_lines = [
                        n
                        for n in node.body
                        if not isinstance(n, ast.Expr)
                        or not isinstance(n.value, ast.Constant)
                    ]

                    # Thin router should have ~5-10 lines:
                    # 1. Extract enforcer
                    # 2. Extract user_ids
                    # 3. Call service
                    # 4. Commit
                    # 5. Log activity
                    # 6. Log info
                    # 7. Return result
                    assert len(body_lines) <= 10, (
                        f"Router function has {len(body_lines)} lines of logic. "
                        "Should be thin (~5-10 lines): "
                        "extract dependencies, call service, commit, log, return. "
                        "Business logic should be in service layer."
                    )

    def test_router_has_refactored_docstring(self):
        """Test that router function docstring mentions refactoring."""
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "sync_users":
                    docstring = ast.get_docstring(node)

                    assert docstring is not None
                    assert (
                        "REFACTORED" in docstring.upper()
                        or "user_service" in docstring
                    ), (
                        "Router docstring should mention refactoring "
                        "and point to user_service"
                    )


class TestDocumentation:
    """Test that proper documentation exists."""

    def test_sync_users_to_casbin_has_docstring(self):
        """Test that sync_users_to_casbin() has comprehensive docstring."""
        from app.services import user_service

        func = user_service.sync_users_to_casbin
        docstring = func.__doc__

        assert docstring is not None, "Function should have docstring"
        assert len(docstring) > 200, (
            "Function docstring should be comprehensive (>200 characters)"
        )

        # Should document parameters
        assert "Args:" in docstring or "Parameters:" in docstring, (
            "Docstring should document parameters"
        )

        # Should document return value
        assert "Returns:" in docstring, "Docstring should document return value"

        # Should document business rules
        assert "Business Rules:" in docstring or "Rules:" in docstring, (
            "Docstring should document business rules"
        )

    def test_docstring_mentions_di_pattern(self):
        """Test that docstring explains DI pattern and protocol independence."""
        from app.services import user_service

        func = user_service.sync_users_to_casbin
        docstring = func.__doc__

        # Should mention dependency injection
        assert "DI" in docstring or "injected" in docstring.lower(), (
            "Docstring should mention dependency injection pattern"
        )

        # Should mention protocol independence
        assert "protocol" in docstring.lower() or "HTTP" in docstring, (
            "Docstring should mention protocol independence"
        )

    def test_docstring_has_usage_examples(self):
        """Test that docstring includes usage examples."""
        from app.services import user_service

        func = user_service.sync_users_to_casbin
        docstring = func.__doc__

        assert "Example:" in docstring, (
            "Docstring should include usage examples"
        )


# === SUMMARY ===
"""
Test Results Expected:
- All tests should PASS after Task 1.7 refactoring
- If any test fails, it indicates incomplete extraction

Refactoring Goals Verified:
1. ✅ Business logic moved to service layer (user_service.py)
2. ✅ Router is thin (only HTTP concerns)
3. ✅ Protocol independence (no HTTP request in service)
4. ✅ Proper DI pattern (db, enforcer injected)
5. ✅ Service returns domain objects (dict), not HTTP responses
6. ✅ Comprehensive documentation

Migration Impact:
- Service can now be reused in non-HTTP contexts (CLI, Celery, etc.)
- Easier to test (can inject mock dependencies)
- Better separation of concerns
- Router complexity reduced significantly
"""
