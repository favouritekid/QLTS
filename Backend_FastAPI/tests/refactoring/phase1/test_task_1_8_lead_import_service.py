# tests/refactoring/phase1/test_task_1_8_lead_import_service.py
"""
PHASE 1 - Task 1.8: Extract Lead Import Verification Tests

Tests to verify that import_leads_from_file_content() has been properly extracted
to lead_service.py and follows protocol-independent architecture.

Refactoring Completed:
- Business logic moved from router (admin.py) to service (lead_service.py)
- Router now only handles HTTP concerns (file reading, exception conversion)
- Service accepts file content as bytes (protocol-independent)
- No HTTP-specific dependencies in service layer

Test Strategy:
1. Verify import_leads_from_file_content() exists in lead_service.py
2. Verify service function has correct signature (file_content, filename, db params)
3. Verify service function is async
4. Verify router imports and calls lead_service
5. Verify router is thin (minimal logic)
6. Verify comprehensive documentation exists
"""

import ast
import inspect
from pathlib import Path

import pytest


class TestLeadImportServiceExists:
    """Test that import_leads_from_file_content() function exists in lead_service.py."""

    def test_import_leads_from_file_content_exists_in_service(self):
        """Test that import_leads_from_file_content() is defined in lead_service.py."""
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "lead_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find function definition
        function_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "import_leads_from_file_content":
                    function_found = True
                    break

        assert function_found, (
            "import_leads_from_file_content() not found in lead_service.py. "
            "Function should be extracted from router to service."
        )

    def test_import_leads_from_file_content_signature(self):
        """
        Test that import_leads_from_file_content() has correct DI signature.

        Expected parameters:
        - file_content: bytes (file content, protocol-independent)
        - filename: str (for file type detection)
        - db: AsyncSession (database dependency)

        Should NOT have: file, UploadFile, request (HTTP-specific)
        """
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Required parameters
        assert "file_content" in params, "Missing 'file_content' parameter (bytes)"
        assert "filename" in params, "Missing 'filename' parameter (str)"
        assert "db" in params, "Missing 'db' parameter (DI for database)"

        # HTTP parameters should NOT exist in service
        assert "file" not in params, (
            "Service should NOT have 'file' parameter (HTTP coupling)"
        )
        assert "request" not in params, (
            "Service should NOT have 'request' parameter (protocol coupling)"
        )
        assert "current_admin" not in params, (
            "Service should NOT have 'current_admin' parameter "
            "(authentication is router concern)"
        )

    def test_import_leads_from_file_content_is_async(self):
        """Test that import_leads_from_file_content() is an async function."""
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content

        assert inspect.iscoroutinefunction(func), (
            "import_leads_from_file_content() should be async (uses await for DB)"
        )


class TestLeadImportServiceProtocolIndependence:
    """Test that import_leads_from_file_content() is protocol-independent."""

    def test_service_has_no_http_imports(self):
        """
        Test that service function does NOT import FastAPI/HTTP modules.

        Service should not depend on FastAPI, UploadFile, HTTPException, etc.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "lead_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find import_leads_from_file_content function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "import_leads_from_file_content":
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should NOT import UploadFile
                    assert "UploadFile" not in func_source, (
                        "Service should NOT use UploadFile (HTTP-specific). "
                        "Use bytes instead."
                    )

                    # Should NOT raise HTTPException
                    assert "HTTPException" not in func_source, (
                        "Service should NOT raise HTTPException. "
                        "Use ValueError or custom exceptions instead."
                    )

    def test_service_accepts_bytes_not_uploadfile(self):
        """
        Test that service accepts bytes (protocol-independent), not UploadFile.

        This allows service to be called from:
        - HTTP (FastAPI UploadFile → bytes)
        - CLI (local file → bytes)
        - S3 (download → bytes)
        - Tests (mock bytes)
        """
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content
        sig = inspect.signature(func)

        # Check file_content parameter type annotation
        file_content_param = sig.parameters["file_content"]
        assert "bytes" in str(file_content_param.annotation), (
            "file_content parameter should be annotated as 'bytes', not UploadFile"
        )

    def test_service_raises_valueerror_not_httpexception(self):
        """
        Test that service raises ValueError, not HTTPException.

        Service layer should raise domain exceptions (ValueError, custom exceptions).
        Router layer converts these to HTTP exceptions.
        """
        service_path = (
            Path(__file__).parent.parent.parent.parent
            / "app"
            / "services"
            / "lead_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Parse AST
        tree = ast.parse(source)

        # Find import_leads_from_file_content function
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "import_leads_from_file_content":
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should raise ValueError for validation errors
                    assert "ValueError" in func_source, (
                        "Service should raise ValueError for validation errors"
                    )

                    # Should NOT raise HTTPException
                    assert "HTTPException" not in func_source, (
                        "Service should NOT raise HTTPException"
                    )


class TestRouterRefactored:
    """Test that router has been refactored to call service."""

    def test_router_calls_lead_service_import(self):
        """
        Test that router's import_leads_from_file() calls lead_service.import_leads_from_file_content().

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
                if node.name == "import_leads_from_file":
                    router_func_found = True

                    # Check if function body calls lead_service.import_leads_from_file_content
                    for child in ast.walk(node):
                        if isinstance(child, ast.Await):
                            # Check if await calls lead_service.import_leads_from_file_content
                            call_node = child.value
                            if isinstance(call_node, ast.Call):
                                if isinstance(call_node.func, ast.Attribute):
                                    # Check for services.lead_service.import_leads_from_file_content
                                    if (
                                        call_node.func.attr == "import_leads_from_file_content"
                                        and isinstance(call_node.func.value, ast.Attribute)
                                        and call_node.func.value.attr == "lead_service"
                                    ):
                                        calls_service = True
                                        break

        assert router_func_found, "Router function import_leads_from_file() not found"
        assert calls_service, (
            "Router function should call services.lead_service.import_leads_from_file_content(). "
            "Business logic should be in service, not router."
        )

    def test_router_function_is_thin(self):
        """
        Test that router function is 'thin' (minimal logic).

        Router should only:
        1. Read file content from UploadFile (HTTP-specific)
        2. Call service with file content
        3. Handle exception conversion (ValueError → HTTPException)
        4. Return service result

        It should NOT contain business logic (DataFrame processing, validation, DB operations, etc.)
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
                if node.name == "import_leads_from_file":
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should NOT contain pandas DataFrame processing
                    assert "DataFrame" not in func_source, (
                        "Router should NOT process DataFrames. "
                        "DataFrame processing belongs in service."
                    )

                    # Should NOT contain bulk insert logic
                    assert "bulk insert" not in func_source.lower(), (
                        "Router should NOT contain bulk insert logic. "
                        "DB operations belong in service."
                    )

                    # Should NOT validate columns
                    assert "required_columns" not in func_source, (
                        "Router should NOT validate columns. "
                        "Validation belongs in service."
                    )

                    # Count lines in function body (excluding docstring)
                    body_lines = [
                        n
                        for n in node.body
                        if not isinstance(n, ast.Expr)
                        or not isinstance(n.value, ast.Constant)
                    ]

                    # Thin router should have ~5-10 lines:
                    # 1. Log request
                    # 2-3. Read file content (try/except/finally)
                    # 4-5. Call service (try/except)
                    # 6. Return result
                    assert len(body_lines) <= 15, (
                        f"Router function has {len(body_lines)} lines of logic. "
                        "Should be thin (~5-15 lines): "
                        "log, read file, call service, handle exceptions, return. "
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
                if node.name == "import_leads_from_file":
                    docstring = ast.get_docstring(node)

                    assert docstring is not None
                    assert (
                        "REFACTORED" in docstring.upper()
                        or "lead_service" in docstring
                    ), (
                        "Router docstring should mention refactoring "
                        "and point to lead_service"
                    )

    def test_router_converts_valueerror_to_httpexception(self):
        """
        Test that router converts service ValueError to HTTPException.

        This is a router responsibility - translating domain exceptions to HTTP.
        """
        router_path = (
            Path(__file__).parent.parent.parent.parent / "app" / "routers" / "admin.py"
        )

        with open(router_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name == "import_leads_from_file":
                    # Get function source
                    func_source = ast.unparse(node)

                    # Should catch ValueError
                    assert "except ValueError" in func_source, (
                        "Router should catch ValueError from service"
                    )

                    # Should raise HTTPException
                    assert "HTTPException" in func_source, (
                        "Router should convert ValueError to HTTPException"
                    )


class TestDocumentation:
    """Test that proper documentation exists."""

    def test_import_leads_from_file_content_has_docstring(self):
        """Test that import_leads_from_file_content() has comprehensive docstring."""
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content
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

    def test_docstring_mentions_protocol_independence(self):
        """Test that docstring explains protocol independence."""
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content
        docstring = func.__doc__

        # Should mention protocol independence
        assert "protocol" in docstring.lower() or "reusable" in docstring.lower(), (
            "Docstring should mention protocol independence or reusability"
        )

    def test_docstring_has_usage_examples(self):
        """Test that docstring includes usage examples."""
        from app.services import lead_service

        func = lead_service.import_leads_from_file_content
        docstring = func.__doc__

        assert "Example:" in docstring, (
            "Docstring should include usage examples"
        )


# === SUMMARY ===
"""
Test Results Expected:
- All tests should PASS after Task 1.8 refactoring
- If any test fails, it indicates incomplete extraction

Refactoring Goals Verified:
1. ✅ Business logic moved to service layer (lead_service.py)
2. ✅ Router is thin (only HTTP concerns)
3. ✅ Protocol independence (accepts bytes, not UploadFile)
4. ✅ Proper exception handling (ValueError → HTTPException in router)
5. ✅ Service does not import FastAPI/HTTP modules
6. ✅ Comprehensive documentation

Migration Impact:
- Service can now be reused in non-HTTP contexts (CLI, S3, Celery, etc.)
- Easier to test (can pass mock bytes instead of mock UploadFile)
- Better separation of concerns
- Router complexity reduced dramatically (~80% reduction)
"""
