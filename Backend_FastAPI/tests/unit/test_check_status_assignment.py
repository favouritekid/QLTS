"""Unit tests for ``app/scripts/check_status_assignment.py`` (#16 lint).

Verifies the AST detector:

  1. Catches direct ``profile.status = ...`` writes (the canonical
     pattern from the 11 legacy sites #16 just refactored).
  2. Catches ``setattr(profile, "status", ...)`` dynamic writes.
  3. Skips comparisons (``if profile.status == "..."``) — those are
     READ checks, not writes.
  4. Skips writes on non-admission entities (``fee.status``,
     ``user.status``, ``delivery.status``) — leftmost-name allowlist
     restricts the lint to ``ADMISSION_PROFILE_VAR_NAMES``.
  5. Allow-list (``app/services/admission_state_service.py``) escapes
     the scan — that file IS the centralized writer.
  6. Allowlist content + scan dirs + variable-name allowlist are
     locked so future changes are an explicit decision.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Make the script importable as a module without going through
# ``python -m`` so the helpers can be unit-tested directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "scripts"))
import check_status_assignment as lint  # noqa: E402  (path setup must run first)


# ---------------------------------------------------------------------------
# Helpers — write a temp .py file + scan it
# ---------------------------------------------------------------------------


def _scan_source(tmp_path: Path, source: str, *, rel: str = "tmp_target.py"):
    """Drop ``source`` to a tmp file and call ``_scan_file`` directly.

    Returns the list of ``Violation`` objects so tests assert on the
    exact pattern + target_repr the AST detector emits.
    """
    py_file = tmp_path / rel
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text(textwrap.dedent(source), encoding="utf-8")
    return lint._scan_file(py_file, rel)


# ---------------------------------------------------------------------------
# 1. Direct assignment detection
# ---------------------------------------------------------------------------


def test_detects_direct_profile_status_assignment(tmp_path: Path) -> None:
    src = '''
        async def some_handler(profile):
            profile.status = "approved"
            return profile
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 1
    v = violations[0]
    assert v.pattern == "direct_assign"
    assert v.target_repr == "profile.status = ..."


@pytest.mark.parametrize(
    "alias",
    ["locked_profile", "admission_profile", "current_profile", "profile_row", "prof"],
)
def test_detects_admission_profile_alias_writes(tmp_path: Path, alias: str) -> None:
    """Forward-prevention: future callers that pick a different alias
    for an AdmissionProfile (instead of the canonical ``profile``)
    still get blocked. The lint covers the common alias set audited
    in the codebase as of 2026-05-03 + a few defensive entries."""
    src = f'''
        async def some_handler({alias}):
            {alias}.status = "approved"
            return {alias}
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 1
    v = violations[0]
    assert v.pattern == "direct_assign"
    assert v.target_repr == f"{alias}.status = ..."


def test_detects_setattr_on_admission_profile_alias(tmp_path: Path) -> None:
    """``setattr(locked_profile, "status", ...)`` must be flagged the
    same way ``setattr(profile, ...)`` is."""
    src = '''
        def dynamic_write(locked_profile):
            setattr(locked_profile, "status", "approved")
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 1
    v = violations[0]
    assert v.pattern == "setattr"
    assert v.target_repr == 'setattr(locked_profile, "status", ...)'


def test_detects_admission_profile_alias_in_router_pattern(tmp_path: Path) -> None:
    """End-to-end: the router-level pattern that walks a result set
    and rewrites each row's status MUST be caught — this is the
    pattern that leaked into bulk-route surfaces before #16
    centralised the writer."""
    src = '''
        async def fan_out(rows, admission_profile):
            admission_profile.status = "rejected"
            for profile_row in rows:
                profile_row.status = "withdrawn"
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 2
    targets = sorted(v.target_repr for v in violations)
    assert targets == [
        "admission_profile.status = ...",
        "profile_row.status = ...",
    ]


def test_detects_aug_assign_on_status(tmp_path: Path) -> None:
    """Augmented assignment (``profile.status += "x"``) is rare but
    syntactically possible; the lint catches it for completeness."""
    src = '''
        def weird(profile):
            profile.status += "_suffix"
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 1
    assert violations[0].pattern == "direct_assign"


# ---------------------------------------------------------------------------
# 2. setattr() detection
# ---------------------------------------------------------------------------


def test_detects_setattr_on_status(tmp_path: Path) -> None:
    src = '''
        def dynamic_write(profile):
            setattr(profile, "status", "rejected")
    '''
    violations = _scan_source(tmp_path, src)
    assert len(violations) == 1
    v = violations[0]
    assert v.pattern == "setattr"
    assert v.target_repr == 'setattr(profile, "status", ...)'


def test_skips_setattr_with_dynamic_attr_name(tmp_path: Path) -> None:
    """Parameterized name (``setattr(obj, attr_var, value)``) cannot be
    statically resolved to ``"status"``; the detector errs on the side
    of fewer false positives, matching the ``check_notification_event_
    coverage._scan_raw_dispatch_calls`` style."""
    src = '''
        def dynamic_attr(profile, attr_name):
            setattr(profile, attr_name, "anything")
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


def test_skips_setattr_with_non_status_attr(tmp_path: Path) -> None:
    src = '''
        def write_something_else(profile):
            setattr(profile, "version", 2)
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


# ---------------------------------------------------------------------------
# 3. Comparisons (READ) are not flagged
# ---------------------------------------------------------------------------


def test_skips_status_comparison_read(tmp_path: Path) -> None:
    """``if profile.status == "approved"`` is a READ check — #15
    centralized those through ``is_admitted_like()``. The lint blocks
    only WRITES."""
    src = '''
        def read_check(profile):
            if profile.status == "approved":
                return True
            elif profile.status in ("draft", "submitted"):
                return False
            return profile.status != "withdrawn"
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


def test_skips_function_call_with_status_kwarg(tmp_path: Path) -> None:
    """``some_func(status="approved")`` is a function arg, not an
    assignment to ``profile.status``. Don't flag."""
    src = '''
        def call_helper(profile):
            do_stuff(status="approved", profile_id=profile.id)
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


# ---------------------------------------------------------------------------
# 4. Non-admission entities (leftmost-name allowlist)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "var_name",
    ["fee", "user", "delivery", "payment", "invoice", "lead", "consultation"],
)
def test_skips_status_writes_on_non_admission_entities(
    tmp_path: Path, var_name: str
) -> None:
    """Other entities have ``.status`` columns too (Fee, User, ZaloDelivery,
    LeadClaim, ConsultationStatus). The lint targets ONLY admission
    profile writes; the leftmost-name allowlist restricts to
    ``ADMISSION_PROFILE_VAR_NAMES``. Without the restriction the
    initial run-through reported 5+ false positives across the
    services tree."""
    src = f'''
        def update_{var_name}({var_name}):
            {var_name}.status = "anything"
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


def test_skips_setattr_on_non_admission_entity(tmp_path: Path) -> None:
    src = '''
        def update_fee(fee):
            setattr(fee, "status", "paid")
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


def test_does_not_flag_chain_rooted_at_self(tmp_path: Path) -> None:
    """``self.profile.status = ...`` has leftmost ``self`` (not
    ``profile``); the lint targets the direct-write surface only.
    A future caller with this pattern would surface in code review,
    not the lint — keep the heuristic tight."""
    src = '''
        class Owner:
            def write(self):
                self.profile.status = "x"
    '''
    violations = _scan_source(tmp_path, src)
    assert violations == []


# ---------------------------------------------------------------------------
# 5. Allow-list module path escape
# ---------------------------------------------------------------------------


def test_state_service_module_in_allowlist() -> None:
    """The centralized writer is the ONE module where direct writes
    are intentional. If this slips out of the allowlist the lint
    will fail for the very file that wrote the contract."""
    assert "app/services/admission_state_service.py" in lint.ALLOWLIST


def test_allowlist_skipped_during_scan(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: write a violation in an allow-listed path + a
    violation outside; the scan reports only the outside one. Uses
    monkey-patched ``REPO_ROOT`` + ``ALLOWLIST`` to keep the test
    hermetic."""
    # Build a fake repo layout
    (tmp_path / "app" / "services").mkdir(parents=True)
    (tmp_path / "app" / "routers").mkdir(parents=True)

    allow_path = tmp_path / "app" / "services" / "admission_state_service.py"
    allow_path.write_text(
        textwrap.dedent('''
            async def transition(db, profile, new_status):
                profile.status = new_status  # legitimate, allow-listed
        ''')
    )
    block_path = tmp_path / "app" / "routers" / "admissions.py"
    block_path.write_text(
        textwrap.dedent('''
            async def some_route(profile):
                profile.status = "approved"  # SHOULD be flagged
        ''')
    )

    monkeypatch.setattr(lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        lint, "ALLOWLIST", ("app/services/admission_state_service.py",),
    )
    result = lint.scan()

    assert result.files_scanned >= 1
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.file == "app/routers/admissions.py"
    assert v.line == 3
    assert v.pattern == "direct_assign"


# ---------------------------------------------------------------------------
# 6. Constants locked
# ---------------------------------------------------------------------------


def test_admission_profile_var_names_locked() -> None:
    """Adding or removing an alias should be a deliberate decision —
    bumping this assertion forces the author to audit the affected
    call sites for centralized-writer compliance.

    Audit done on 2026-05-03 (#16) — all 11 legacy direct-write sites
    used the canonical ``profile`` name; the broader alias list is
    forward-prevention so future callers that pick a different name
    still get blocked at CI time. No existing alias write sites
    found in the codebase as of #16 ship.
    """
    assert lint.ADMISSION_PROFILE_VAR_NAMES == (
        "profile",
        "locked_profile",
        "admission_profile",
        "current_profile",
        "profile_row",
        "prof",
    )


def test_scan_dirs_locked() -> None:
    assert lint.SCAN_DIRS == ("app/services", "app/routers", "app/tasks")


def test_allowlist_locked() -> None:
    assert lint.ALLOWLIST == (
        "app/services/admission_state_service.py",
    )
