"""Regression lock — `BUG_RESUBMIT_NOTES_NONE` (admission_service.py:6267).

Pre-existing P3 bug surfaced via V3 runtime test Rehearsal #6 (2026-05-07):
when a client POSTs `/api/admissions/{id}/resubmit` without a ``notes`` field
(or with ``notes: null``), Pydantic's ``Optional[str] = None`` default makes
``data['notes']`` resolve to ``None``. The previous expression

    data.get('notes', 'No notes')[:50]

returned ``None`` (not the default — ``.get`` returns the actual stored
value if the key exists, regardless of value) and ``None[:50]`` raised
``TypeError: 'NoneType' object is not subscriptable``, propagating as a
500 to the client.

Atomicity stayed intact (the outer transaction rolled back fully — no
profile mutation, no status_history row), but the user-visible 500 was
the bug.

The fix is the truthy-coalesce form

    (data.get('notes') or 'No notes')[:50]

which handles four input shapes correctly:

* missing key  ``{}`` → 'No notes'
* explicit ``None`` ``{'notes': None}`` → 'No notes'
* empty string ``{'notes': ''}`` → 'No notes'
* real string  ``{'notes': 'foo'}`` → 'foo'

The test below reads the *live* expression from
``admission_service.resubmit_profile``'s source via ``inspect`` and
exercises it, so a regression to the buggy ``.get(key, default)`` form
will fail loudly here before reaching production again.
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.services import admission_service


def _extract_reason_template() -> str:
    """Pull the ``reason=f"Profile resubmitted: ..."`` line from the live
    ``resubmit_profile`` function source."""
    src = inspect.getsource(admission_service.resubmit_profile)
    match = re.search(
        r'reason=f"Profile resubmitted:\s*(\{.*?\})"',
        src,
    )
    assert match, (
        "Expected reason f-string in resubmit_profile not found — has the "
        "function been refactored? Update this regression lock to match the "
        "new shape."
    )
    return match.group(1)


def _evaluate(expression: str, data: dict) -> str:
    """Evaluate ``f"Profile resubmitted: {<expression>}"`` against ``data``
    and return the resulting reason string."""
    return eval(  # noqa: S307 — controlled local eval, expression sourced from project file
        f'f"Profile resubmitted: {expression}"',
        {"data": data},
    )


@pytest.mark.parametrize(
    "data,expected",
    [
        ({}, "Profile resubmitted: No notes"),
        ({"notes": None}, "Profile resubmitted: No notes"),
        ({"notes": ""}, "Profile resubmitted: No notes"),
        ({"notes": "Real notes value"}, "Profile resubmitted: Real notes value"),
        ({"notes": "x" * 80}, "Profile resubmitted: " + "x" * 50),
    ],
    ids=[
        "missing_key",
        "explicit_None_BUG_REGRESSION_GUARD",
        "empty_string",
        "real_value",
        "truncated_to_50",
    ],
)
def test_resubmit_reason_handles_all_notes_shapes(data, expected):
    """Live-source expression must produce expected reason for all 5 shapes."""
    expression = _extract_reason_template()
    assert _evaluate(expression, data) == expected


def test_resubmit_reason_template_does_not_use_dotget_default_anti_pattern():
    """Anchor — fail if someone reverts to ``.get('notes', 'No notes')`` form
    that triggers ``None[:50]`` ``TypeError`` on ``notes=None`` payload."""
    expression = _extract_reason_template()
    # Anti-pattern: .get('notes', 'No notes') returns None when key=None,
    # then [:50] raises TypeError. Truthy-coalesce form (... or 'No notes')
    # avoids this.
    assert "or 'No notes'" in expression or 'or "No notes"' in expression, (
        f"Resubmit reason template appears to use .get(default) anti-pattern: "
        f"{expression!r}. Use ``(data.get('notes') or 'No notes')[:50]`` to "
        f"handle ``notes=None`` payload — see V3 R6 BUG_RESUBMIT_NOTES_NONE."
    )
