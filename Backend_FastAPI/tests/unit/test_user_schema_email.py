"""
Regression tests for User schema email serialization fix.

Root cause: Pydantic EmailStr in response schema rejected placeholder emails
(e.g. @placeholder.local) during response serialization, causing 500 errors
on /api/admin/users and other endpoints returning User data.

Fix: User response schema overrides email field to `str`, while input schemas
(UserCreate, AdminUserCreate, UserUpdate) retain EmailStr validation.
"""

import pytest
from unittest.mock import MagicMock

from pydantic import ValidationError

from app.schemas.user import User, UserCreate, UserUpdate, AdminUserCreate, UsersPage


# ---------------------------------------------------------------------------
# Fix 1: Response schema accepts any email string from DB
# ---------------------------------------------------------------------------

class TestUserResponseSchemaEmail:
    """User response schema must serialize any email stored in DB."""

    def _make_user_obj(self, email: str) -> MagicMock:
        """Create a mock ORM user object with from_attributes support."""
        obj = MagicMock()
        obj.id = 1
        obj.username = "testuser"
        obj.email = email
        obj.full_name = "Test User"
        obj.role = "collaborator"
        obj.status = "active"
        obj.avatar_url = None
        obj.phone_number = None
        obj.unit_id = None
        obj.skills = None
        obj.availability_status = None
        obj.password_reset_required = False
        obj.mfa_enabled = False
        return obj

    def test_placeholder_local_email_serializes(self):
        """Regression: @placeholder.local must not cause 500."""
        obj = self._make_user_obj("ctv_CTV-2026-0012@placeholder.local")
        user = User.model_validate(obj, from_attributes=True)
        assert user.email == "ctv_CTV-2026-0012@placeholder.local"

    def test_noemail_domain_serializes(self):
        """New convention: @noemail.tnpc.edu.vn must serialize."""
        obj = self._make_user_obj("ctv.ctv-2026-0012@noemail.tnpc.edu.vn")
        user = User.model_validate(obj, from_attributes=True)
        assert user.email == "ctv.ctv-2026-0012@noemail.tnpc.edu.vn"

    def test_normal_email_serializes(self):
        """Normal emails still serialize correctly."""
        obj = self._make_user_obj("admin@qlts.tnpc.edu.vn")
        user = User.model_validate(obj, from_attributes=True)
        assert user.email == "admin@qlts.tnpc.edu.vn"

    def test_users_page_with_mixed_emails(self):
        """UsersPage must serialize a mix of normal and placeholder emails."""
        users_data = {
            "total_count": 2,
            "users": [
                {
                    "id": 1,
                    "username": "admin",
                    "email": "admin@example.com",
                    "full_name": "Admin",
                    "role": "admin",
                    "status": "active",
                },
                {
                    "id": 2,
                    "username": "0917106363",
                    "email": "ctv.ctv-2026-0012@noemail.tnpc.edu.vn",
                    "full_name": "CTV",
                    "role": "collaborator",
                    "status": "active",
                },
            ],
        }
        page = UsersPage.model_validate(users_data)
        assert page.total_count == 2
        assert page.users[1].email == "ctv.ctv-2026-0012@noemail.tnpc.edu.vn"


# ---------------------------------------------------------------------------
# Fix 1 guard: Input schemas still enforce EmailStr
# ---------------------------------------------------------------------------

class TestInputSchemasRetainEmailValidation:
    """Input schemas must continue rejecting invalid emails."""

    def test_user_create_rejects_placeholder_local(self):
        """UserCreate must reject @placeholder.local."""
        with pytest.raises(ValidationError, match="email"):
            UserCreate(
                username="testuser",
                email="ctv_CTV-2026-0012@placeholder.local",
                password="StrongP@ss1234",
                full_name="Test",
            )

    def test_user_create_accepts_valid_email(self):
        """UserCreate accepts properly formatted email."""
        user = UserCreate(
            username="testuser",
            email="user@example.com",
            password="StrongP@ss1234",
            full_name="Test",
        )
        assert "example.com" in user.email

    def test_admin_user_create_rejects_invalid_email(self):
        """AdminUserCreate inherits EmailStr validation."""
        with pytest.raises(ValidationError, match="email"):
            AdminUserCreate(
                username="testadmin",
                email="bad@placeholder.local",
                password="StrongP@ss1234",
                full_name="Admin",
                role="admin",
            )

    def test_user_update_rejects_invalid_email(self):
        """UserUpdate rejects invalid email when provided."""
        with pytest.raises(ValidationError, match="email"):
            UserUpdate(email="bad@placeholder.local")

    def test_user_update_accepts_none_email(self):
        """UserUpdate allows omitting email (Optional)."""
        update = UserUpdate(full_name="New Name")
        assert update.email is None
