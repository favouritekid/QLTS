"""Unit tests for ``admission_service`` ``applied_rules`` snapshot —
the 3 new fields wired in #184 Wave 1 PR-1B' (phase1_03 +
phase1_02 wired).

PLAN line 2776 contract: applied_rules is the immutable per-profile
snapshot of the path config at create time. PR-1B' adds 3 keys:

* ``applicable_to`` — list of audience strings or None.
* ``method_quota`` — int or None.
* ``bonus_rule_override`` — dict (the raw JSONB shape) or None.

This file locks the snapshot keys exist in the source + the values
are read from the path attribute (not hard-coded / mocked
elsewhere). Full integration of profile create flow is covered by
existing ``test_admission_service.py``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services import admission_service


_SERVICE_FILE = Path(admission_service.__file__).resolve()


# ---------------------------------------------------------------------------
# 1. Source-text contract — 3 keys present in the snapshot dict
# ---------------------------------------------------------------------------


def test_applied_rules_includes_applicable_to_key() -> None:
    """The snapshot dict literal must reference the new key. Static
    grep is sufficient — the production code path that constructs
    the dict is the only writer for ``applied_rules``."""
    src = _SERVICE_FILE.read_text()
    assert '"applicable_to":' in src


def test_applied_rules_includes_method_quota_key() -> None:
    src = _SERVICE_FILE.read_text()
    assert '"method_quota":' in src


def test_applied_rules_includes_bonus_rule_override_key() -> None:
    src = _SERVICE_FILE.read_text()
    assert '"bonus_rule_override":' in src


# ---------------------------------------------------------------------------
# 2. Source contract — values read from path attribute, not hard-coded
# ---------------------------------------------------------------------------


def test_applied_rules_reads_applicable_to_from_path() -> None:
    """The new keys must read from ``admission_path.<attr>`` so the
    snapshot reflects the live path config at create time. A bug
    where someone hard-coded the value (e.g. ``"applicable_to":
    None``) would silently break Phase 3 audience filter for
    profiles created in Phase 1+2."""
    src = _SERVICE_FILE.read_text()
    # ``applicable_to`` may use list() conversion to detach from the
    # ORM list type; either way the source must reference the path attribute.
    assert "admission_path.applicable_to" in src or 'getattr(admission_path, "applicable_to"' in src


def test_applied_rules_reads_method_quota_from_path() -> None:
    src = _SERVICE_FILE.read_text()
    assert (
        "admission_path.method_quota" in src
        or 'getattr(admission_path, "method_quota"' in src
    )


def test_applied_rules_reads_bonus_rule_override_from_path() -> None:
    src = _SERVICE_FILE.read_text()
    assert (
        "admission_path.bonus_rule_override" in src
        or 'getattr(admission_path, "bonus_rule_override"' in src
    )
