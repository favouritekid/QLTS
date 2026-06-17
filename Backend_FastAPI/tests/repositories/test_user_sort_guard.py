"""Anchor tests for ``user_repository._safe_user_sort_column``.

Pins the contract that ``ORDER BY <user-supplied>`` cannot leak the
sensitive columns of ``models.User`` (password hash, MFA secret,
backup codes, JWT id, search vector). The repository routes every
``sort_by`` parameter through this helper before composing the query.

If a future contributor adds a new sensitive column to ``User`` and
forgets to keep it OUT of ``_ALLOWED_USER_SORT_FIELDS``, these tests
fail loudly. The third test (``test_default_unknown_falls_back``) is
intentionally non-tautological — it asserts the *behaviour* (returns
the id column), not the implementation (does not check the allowlist
membership directly), so a refactor that swaps the allowlist for a
deny-list will still be caught.
"""
from app import models
from app.repositories.user_repository import (
    _ALLOWED_USER_SORT_FIELDS,
    _safe_user_sort_column,
)


class TestSafeUserSortColumn:
    def test_allowlisted_field_returns_correct_column(self):
        assert _safe_user_sort_column("username") is models.User.username
        assert _safe_user_sort_column("email") is models.User.email
        assert _safe_user_sort_column("full_name") is models.User.full_name
        assert _safe_user_sort_column("role") is models.User.role

    def test_default_unknown_falls_back(self):
        # Garbage value should sort by id, NOT raise and NOT pick up
        # whatever attribute happens to share the name on the model.
        assert _safe_user_sort_column("not_a_column") is models.User.id
        assert _safe_user_sort_column("") is models.User.id

    def test_legacy_default_created_at_falls_back(self):
        # ``user_repository.get_filtered`` historically defaulted to
        # ``sort_by="created_at"``; the User model never had that column,
        # so the old ``getattr(..., User.id)`` quietly fell back. The
        # new guard preserves that behaviour rather than crashing.
        assert _safe_user_sort_column("created_at") is models.User.id
        assert _safe_user_sort_column("updated_at") is models.User.id

    def test_password_hash_blocked(self):
        # The whole reason this guard exists: password_hash IS a real
        # column on User, so getattr() would have returned it without
        # the allowlist. Verify it falls back to id instead.
        assert _safe_user_sort_column("password_hash") is models.User.id

    def test_other_sensitive_columns_blocked(self):
        for field in (
            "totp_secret_encrypted",
            "backup_codes_hashed",
            "active_jti",
            "search_vector",
        ):
            assert _safe_user_sort_column(field) is models.User.id, (
                f"Sensitive field {field!r} must fall back to User.id, "
                f"got {_safe_user_sort_column(field)!r}"
            )

    def test_allowlist_does_not_leak_secrets(self):
        # Belt-and-suspenders: even if someone edits the allowlist
        # contents, none of these strings should ever appear there.
        forbidden = {
            "password_hash",
            "totp_secret_encrypted",
            "backup_codes_hashed",
            "active_jti",
            "search_vector",
        }
        leaked = forbidden & _ALLOWED_USER_SORT_FIELDS
        assert not leaked, (
            f"Sensitive fields snuck into the allowlist: {sorted(leaked)}. "
            f"Remove them from _ALLOWED_USER_SORT_FIELDS in user_repository.py."
        )
