# tests/refactoring/phase1/test_task_1_10_schema_security.py
"""
PHASE 1 - Task 1.10: Schema Security Verification Tests

Tests to verify that sensitive fields (password_hash) are NOT exposed
in API response schemas.

Security Issue Fixed:
- UserInDB schema had password_hash field without exclusion
- Risk: Could accidentally be used in response_model
- Fix: Added Field(exclude=True) to password_hash

Test Strategy:
1. Verify password_hash is excluded from JSON serialization
2. Verify password_hash is excluded from dict() output
3. Verify password_hash is NOT in model_dump()
4. Verify User schema (safe) doesn't have password_hash
5. Verify UserInDB has deprecation warning in docstring
"""

import pytest
from pydantic import ValidationError

from app.schemas.user import User, UserInDB


class TestUserInDBSecurityFix:
    """Tests for UserInDB schema security fix."""

    def test_password_hash_excluded_from_model_dump(self):
        """
        Test that password_hash is excluded from model_dump().

        SECURITY: This prevents password hash from appearing in JSON responses
        even if developer accidentally uses UserInDB as response_model.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
            "password_hash": "hashed_password_should_not_appear",
        }

        user_in_db = UserInDB(**user_data)

        # Get dict representation (what FastAPI serializes to JSON)
        dumped = user_in_db.model_dump()

        # 🔒 SECURITY CHECK: password_hash must NOT be in output
        assert "password_hash" not in dumped, (
            "SECURITY FAILURE: password_hash found in model_dump()! "
            "This would expose password hashes in API responses."
        )

        # Verify other fields are present
        assert dumped["id"] == 1
        assert dumped["username"] == "testuser"
        assert dumped["email"] == "test@example.com"

    def test_password_hash_excluded_from_json(self):
        """
        Test that password_hash is excluded from JSON serialization.

        SECURITY: Ensures password hash never appears in HTTP responses.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
            "password_hash": "hashed_password_should_not_appear",
        }

        user_in_db = UserInDB(**user_data)

        # Get JSON string (what FastAPI returns to client)
        json_str = user_in_db.model_dump_json()

        # 🔒 SECURITY CHECK: password_hash must NOT be in JSON
        assert "password_hash" not in json_str, (
            "SECURITY FAILURE: password_hash found in JSON output! "
            "This would expose password hashes to clients."
        )
        assert "hashed_password_should_not_appear" not in json_str, (
            "SECURITY FAILURE: password hash value found in JSON!"
        )

        # Verify other fields are present
        assert "testuser" in json_str
        assert "test@example.com" in json_str

    def test_password_hash_excluded_from_dict(self):
        """
        Test that password_hash is excluded from dict() method.

        SECURITY: Double-check all serialization methods.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
            "password_hash": "hashed_password_should_not_appear",
        }

        user_in_db = UserInDB(**user_data)

        # Use dict() method (should also exclude password_hash)
        dict_output = dict(user_in_db)

        # 🔒 SECURITY CHECK
        assert "password_hash" not in dict_output, (
            "SECURITY FAILURE: password_hash found in dict() output!"
        )

    def test_password_hash_field_exists_internally(self):
        """
        Test that password_hash field exists internally for database operations.

        This ensures the field can still be used for DB operations,
        just not exposed in API responses.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
            "password_hash": "hashed_password_value",
        }

        user_in_db = UserInDB(**user_data)

        # Field should exist internally (for DB operations)
        assert hasattr(user_in_db, "password_hash")
        assert user_in_db.password_hash == "hashed_password_value"

        # But NOT in serialized output
        assert "password_hash" not in user_in_db.model_dump()

    def test_user_in_db_has_deprecation_warning(self):
        """
        Test that UserInDB has deprecation warning in docstring.

        This warns developers not to use this schema in API responses.
        """
        docstring = UserInDB.__doc__

        assert docstring is not None, "UserInDB should have a docstring"
        assert "DEPRECATED" in docstring, "Should have DEPRECATED warning"
        assert "DO NOT USE" in docstring, "Should have DO NOT USE warning"
        assert "API RESPONSES" in docstring, "Should mention API responses"
        assert "password_hash" in docstring, "Should mention password_hash risk"


class TestUserSchemaSafety:
    """Tests for User schema (safe response schema)."""

    def test_user_schema_has_no_password_hash(self):
        """
        Test that User schema does NOT have password_hash field.

        SECURITY: User schema is safe for API responses.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
        }

        user = User(**user_data)

        # Verify password_hash field doesn't exist
        assert not hasattr(user, "password_hash"), (
            "User schema should NOT have password_hash field"
        )

        # Verify safe fields are present
        assert user.id == 1
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    def test_user_schema_serialization_safe(self):
        """
        Test that User schema serialization is safe (no sensitive data).

        This is the recommended schema for API responses.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "user",
            "status": "active",
            "avatar_url": "https://example.com/avatar.jpg",
            "phone_number": "+1234567890",
        }

        user = User(**user_data)

        # Get JSON output
        json_str = user.model_dump_json()

        # Should contain safe fields
        assert "testuser" in json_str
        assert "test@example.com" in json_str

        # Should NOT contain any password-related data
        assert "password" not in json_str.lower()
        assert "hash" not in json_str.lower()


class TestSchemaSecurityRegression:
    """Regression tests to prevent future security issues."""

    def test_no_new_sensitive_fields_in_user(self):
        """
        Prevent regression: Ensure User schema doesn't gain sensitive fields.

        This test will fail if someone adds password/hash fields to User schema.
        """
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "role": "user",
            "status": "active",
        }

        user = User(**user_data)
        fields = user.model_dump().keys()

        # List of forbidden field names (case-insensitive)
        forbidden_fields = [
            "password",
            "password_hash",
            "hashed_password",
            "pwd",
            "secret",
            "private_key",
            "api_key",
            "token",  # Note: Token schema is separate and intentional
        ]

        for field in fields:
            field_lower = field.lower()
            for forbidden in forbidden_fields:
                assert forbidden not in field_lower, (
                    f"SECURITY REGRESSION: Forbidden field '{forbidden}' "
                    f"found in User schema field '{field}'"
                )

    def test_user_in_db_serialization_always_excludes_password(self):
        """
        Regression test: Ensure UserInDB always excludes password_hash.

        This test ensures the Field(exclude=True) is not accidentally removed.
        """
        user_data = {
            "id": 999,
            "username": "sensitive_test",
            "email": "sensitive@test.com",
            "role": "admin",
            "status": "active",
            "full_name": "Sensitive Test",
            "password_hash": "THIS_SHOULD_NEVER_APPEAR_IN_OUTPUT",
        }

        user_in_db = UserInDB(**user_data)

        # Try all serialization methods
        model_dump_output = user_in_db.model_dump()
        model_dump_json = user_in_db.model_dump_json()
        dict_output = dict(user_in_db)

        # All should exclude password_hash
        assert "password_hash" not in model_dump_output
        assert "THIS_SHOULD_NEVER_APPEAR" not in model_dump_json
        assert "password_hash" not in dict_output


# === DOCUMENTATION ===
"""
Test Results Expected:
- All tests should PASS after security fix
- If any test fails, it indicates a security vulnerability

Security Impact:
- HIGH: Prevents password hash exposure in API responses
- Protects against OWASP A02:2021 - Cryptographic Failures
- Prevents offline password cracking attacks

Migration Guide:
- Use `User` schema for all API responses
- Never use `UserInDB` as response_model in routers
- UserInDB is only for internal database operations
"""
