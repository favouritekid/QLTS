"""ADM-012 regression: bulk admission actions must not leak raw exception
text into the per-item error map.

Domain exceptions carry safe user-facing copy and should pass through; any
other exception (DB, validation library, downstream HTTP errors, etc.) is
hidden behind ``Unexpected error (ref: <correlation>)`` and the full
detail is logged server-side with a correlation id.
"""

import pytest

from app.services.admission_service import _safe_bulk_error_message
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "exc",
    [
        ResourceNotFoundError("Profile 42 not found"),
        BadRequest("Officer must be active"),
        BusinessRuleViolation("Cannot approve a draft profile"),
        PermissionDeniedError("Only managers can assign"),
        ConflictError("Stale version"),
        ValidationError("Citizen ID is required"),
    ],
)
def test_domain_exception_message_passes_through(exc):
    """Domain exceptions are user-facing — keep their copy."""
    msg = _safe_bulk_error_message(
        exc,
        bulk_label="admission_bulk_approve",
        profile_id=1,
        actor_id=99,
    )
    assert msg == str(exc)


def test_generic_exception_is_hidden_behind_correlation_id():
    """Unknown exceptions must NOT leak ``str(e)`` into the response."""
    # Mimic something the DB layer might raise — message contains a SQL
    # snippet that we never want to surface to the API client.
    leaky = RuntimeError(
        "psycopg2.errors.UniqueViolation: duplicate key value violates unique "
        'constraint "ix_admission_profiles_citizen_id"'
    )

    msg = _safe_bulk_error_message(
        leaky,
        bulk_label="admission_bulk_approve",
        profile_id=42,
        actor_id=99,
    )

    assert msg.startswith("Unexpected error"), msg
    assert "ref:" in msg, msg
    # SQL/library detail must not appear in the user-facing copy.
    assert "psycopg2" not in msg
    assert "UniqueViolation" not in msg
    assert "ix_admission_profiles_citizen_id" not in msg


def test_correlation_id_is_per_call_unique():
    """Two unknown failures get distinct correlation ids so ops can pivot."""
    msg1 = _safe_bulk_error_message(
        RuntimeError("boom 1"),
        bulk_label="admission_bulk_assign",
        profile_id=1,
    )
    msg2 = _safe_bulk_error_message(
        RuntimeError("boom 2"),
        bulk_label="admission_bulk_assign",
        profile_id=2,
    )
    assert msg1 != msg2


def test_handles_missing_actor_id():
    """``actor_id`` is optional — helper must not crash when it's None."""
    msg = _safe_bulk_error_message(
        BusinessRuleViolation("test"),
        bulk_label="admission_bulk_reject",
        profile_id=7,
        actor_id=None,
    )
    assert msg == "test"
