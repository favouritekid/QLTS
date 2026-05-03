"""Block direct ``profile.status`` writes outside ``state_service.transition()``.

Cold Cutover Task #16 — every legal mutation of
``AdmissionProfile.status`` MUST flow through
``app.services.admission_state_service.transition()``. This script
walks the ``app/services/`` AST and fails CI if any module assigns
``<x>.status = <literal-or-expr>`` against an admission-profile-typed
local without going through the centralized writer.

Detection patterns (all map to ``ast.Assign`` with an ``Attribute``
target whose ``attr == "status"`` and leftmost name in
``ADMISSION_PROFILE_VAR_NAMES``):

  1. ``profile.status = "..."``           — direct literal write
  2. ``locked_profile.status = "..."``    — alias used in identity-lock branches
  3. ``admission_profile.status = "..."`` — alias used in router-level fanout
  4. ``current_profile.status = "..."``   — alias used in resolver helpers
  5. ``profile_row.status = "..."``       — alias used in result-set iteration
  6. ``prof.status = "..."``              — short alias used in tight loops
  7. ``setattr(<any of the above>, "status", ...)`` — dynamic write

Allow-list (callers where direct writes are intentional):

  * ``app/services/admission_state_service.py`` — THE centralized
    writer; this is the ONE module where ``profile.status = ...``
    is the canonical pattern.
  * ``alembic/versions/*.py``                   — data migrations
    legitimately rewrite status columns; covered by separate review
    (the migration ordering gates Phase 1 schema changes).
  * ``tests/**/*.py``                           — fixture setup +
    test scaffolds; lint enforcement applies to runtime code.

Out of scope (not flagged):

  * Comparison expressions (``if profile.status == "..."``) — those
    are READ checks; #15 already covered the helper bridge for
    admitted-equivalence reads.
  * Calls into the centralized writer (``state_service.transition(...,
    "approved", ...)``) — the AST detector matches assignment
    targets, not function arguments.
  * SQL ``UPDATE`` statements outside Alembic — flagged by separate
    repository / DAL lint, not part of #16.

The detector errs on the side of fewer false positives (parameterized
attribute names like ``setattr(obj, name_var, value)`` are skipped),
which mirrors ``check_notification_event_coverage._scan_raw_dispatch
_calls`` — the same script style + walks the same AST surface.

Usage::

    python -m app.scripts.check_status_assignment
    python -m app.scripts.check_status_assignment --json

Exit code is 0 when no violation is found, 1 otherwise. Suitable for
CI gating + the future ``admission-contract-check.yml`` workflow
(tracked separately per TRACKER row #183 ``CI-workflow``).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
SCAN_DIRS: Tuple[str, ...] = ("app/services", "app/routers", "app/tasks")
# Files where direct ``<x>.status = ...`` writes are intentional.
# Stored as POSIX-style relative paths (matches the existing
# ``RAW_DISPATCH_ALLOWLIST`` style from
# ``check_notification_event_coverage.py``).
ALLOWLIST: Tuple[str, ...] = (
    "app/services/admission_state_service.py",
)

# Admission-profile variable names — the lint only flags writes whose
# leftmost identifier is one of these. Without static type info we
# cannot prove ``foo.status = ...`` writes an ``AdmissionProfile``;
# instead, the lint covers the common alias set seen across the
# admission codebase plus a few defensive entries so a future caller
# that picks a different name still gets blocked at CI time.
#
# Audit done on 2026-05-03 (#16) — all 11 legacy direct-write sites
# used the canonical name ``profile``; the broader alias list below
# is forward-prevention. If a future caller introduces yet another
# alias (e.g. ``draft_profile``, ``the_profile``), add it here AND
# audit the call site to make sure it routes through
# ``state_service.transition()``. The corresponding lock test
# ``test_admission_profile_var_names_locked`` keeps this tuple
# explicit so additions are an intentional decision.
ADMISSION_PROFILE_VAR_NAMES: Tuple[str, ...] = (
    "profile",
    "locked_profile",
    "admission_profile",
    "current_profile",
    "profile_row",
    "prof",
)
_SELF_PATH = Path(__file__).resolve()


@dataclass
class Violation:
    file: str
    line: int
    pattern: str  # "direct_assign" | "setattr"
    target_repr: str  # the source-level snippet (e.g. ``profile.status``)


@dataclass
class ScanResult:
    files_scanned: int = 0
    violations: List[Violation] = field(default_factory=list)


def _attribute_chain_repr(node: ast.Attribute) -> str:
    """Render ``a.b.c`` chain back to source-like text for the report.

    Falls back to ``ast.unparse`` for nested expressions (subscripts,
    calls, etc.) so the violation message points at the exact target
    a reviewer would see in the diff.
    """
    parts: List[str] = [node.attr]
    cur: ast.AST = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    try:
        return ast.unparse(node)  # py3.9+
    except Exception:
        return ".".join(reversed(parts))


def _leftmost_name(node: ast.AST) -> Optional[str]:
    """Return the leftmost ``Name`` identifier in an attribute chain.

    Walks ``Attribute(value=Attribute(value=Name(...), ...), ...)``
    down to the bottom; returns ``None`` if the chain bottoms out on
    something other than a plain ``Name`` (e.g. ``Subscript``,
    ``Call``).
    """
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id
    return None


def _is_status_attribute_target(target: ast.AST) -> Optional[str]:
    """Return the source-level repr if ``target`` is an
    ``Attribute(attr='status')`` whose leftmost name is in
    ``ADMISSION_PROFILE_VAR_NAMES``, else ``None``.

    Catches the canonical form ``profile.status`` plus chains rooted
    at ``profile`` (e.g. ``self.profile.status`` only matches when
    leftmost is ``profile``; ``self.profile.status`` would have
    leftmost ``self`` and is intentionally NOT flagged — the lint
    targets the direct write surface, not arbitrary attribute
    chains). Other ``.status`` writes on different entities (Fee,
    User, ZaloDelivery) fall through unflagged.
    """
    if not (isinstance(target, ast.Attribute) and target.attr == "status"):
        return None
    leftmost = _leftmost_name(target)
    if leftmost not in ADMISSION_PROFILE_VAR_NAMES:
        return None
    return _attribute_chain_repr(target)


def _is_setattr_status_call(node: ast.Call) -> Optional[str]:
    """Return the source-level repr if ``node`` is
    ``setattr(<profile-var>, "status", <value>)``, else ``None``.

    Object must be a ``Name`` in ``ADMISSION_PROFILE_VAR_NAMES`` so
    ``setattr(fee, "status", ...)`` etc. on non-admission entities
    fall through. Skips parameterized name forms (``setattr(obj,
    attr_var, value)``) — they cannot be statically resolved to
    ``"status"`` and the detector errs on the side of fewer false
    positives, matching ``_scan_raw_dispatch_calls`` from the coverage
    script.
    """
    func = node.func
    func_name: Optional[str] = None
    if isinstance(func, ast.Name):
        func_name = func.id
    elif isinstance(func, ast.Attribute):
        func_name = func.attr
    if func_name != "setattr":
        return None
    if len(node.args) < 3:
        return None
    name_arg = node.args[1]
    if not isinstance(name_arg, ast.Constant) or name_arg.value != "status":
        return None
    obj_arg = node.args[0]
    if not (isinstance(obj_arg, ast.Name) and obj_arg.id in ADMISSION_PROFILE_VAR_NAMES):
        return None
    return f'setattr({obj_arg.id}, "status", ...)'


def _scan_file(py_file: Path, rel: str) -> List[Violation]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    found: List[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                rendered = _is_status_attribute_target(target)
                if rendered:
                    found.append(Violation(
                        file=rel,
                        line=node.lineno,
                        pattern="direct_assign",
                        target_repr=f"{rendered} = ...",
                    ))
        elif isinstance(node, ast.AugAssign):
            rendered = _is_status_attribute_target(node.target)
            if rendered:
                found.append(Violation(
                    file=rel,
                    line=node.lineno,
                    pattern="direct_assign",
                    target_repr=f"{rendered} {ast.unparse(node.op)}= ...",
                ))
        elif isinstance(node, ast.Call):
            rendered_setattr = _is_setattr_status_call(node)
            if rendered_setattr:
                found.append(Violation(
                    file=rel,
                    line=node.lineno,
                    pattern="setattr",
                    target_repr=rendered_setattr,
                ))
    return found


def scan() -> ScanResult:
    result = ScanResult()
    for sub in SCAN_DIRS:
        base = REPO_ROOT / sub
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            if py_file.resolve() == _SELF_PATH:
                continue
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel in ALLOWLIST:
                continue
            result.files_scanned += 1
            result.violations.extend(_scan_file(py_file, rel))
    return result


def _print_text(result: ScanResult) -> None:
    if not result.violations:
        print(
            f"OK — scanned {result.files_scanned} file(s); "
            "no direct profile.status writes outside the allow-list.",
            file=sys.stderr,
        )
        return
    print(
        f"\n{len(result.violations)} direct profile.status write(s) outside "
        "the allow-list — every status mutation MUST flow through "
        "app.services.admission_state_service.transition() (Cold Cutover #16):",
        file=sys.stderr,
    )
    for v in result.violations:
        print(f"  {v.file}:{v.line}\t[{v.pattern}]\t{v.target_repr}", file=sys.stderr)


def _print_json(result: ScanResult) -> None:
    payload = {
        "files_scanned": result.files_scanned,
        "violations": [
            {"file": v.file, "line": v.line, "pattern": v.pattern, "target_repr": v.target_repr}
            for v in result.violations
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of TSV.",
    )
    args = parser.parse_args()
    result = scan()
    if args.json:
        _print_json(result)
    else:
        _print_text(result)
    return 0 if not result.violations else 1


if __name__ == "__main__":
    sys.exit(main())
