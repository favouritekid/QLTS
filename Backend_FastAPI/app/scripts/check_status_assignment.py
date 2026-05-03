"""Block direct ``profile.status`` writes outside ``state_service.transition()``.

Cold Cutover #16 + CI tooling extension — every legal mutation of
``AdmissionProfile.status`` MUST flow through
``app.services.admission_state_service.transition()``. This script
walks the ``app/services/``, ``app/routers/``, ``app/tasks/`` AST and
fails CI if any module assigns ``<x>.status = <literal-or-expr>``
against an admission-profile-typed local without going through the
centralized writer.

Detection patterns (CI-status spec ``PR_DRAFTS_2026-05-01.md`` §103-107):

  **AST Assign — leftmost name in ``ADMISSION_PROFILE_VAR_NAMES``**

  1. ``profile.status = "..."``           — Pattern 1.1 direct literal write
  2. ``locked_profile.status = "..."``    — alias: identity-lock branches
  3. ``admission_profile.status = "..."`` — alias: router-level fanout
  4. ``current_profile.status = "..."``   — alias: resolver helpers
  5. ``profile_row.status = "..."``       — alias: result-set iteration
  6. ``prof.status = "..."``              — alias: short loop var

  **AST Call**

  7. ``setattr(<alias>, "status", ...)``      — Pattern 1.2 builtin
  8. ``<alias>.__setattr__("status", ...)``   — Pattern 1.3 dunder bypass

  **Regex grep fallback (Pattern 1.4)**

  9. ``(?:setattr|__setattr__)\\s*\\([^,]+,\\s*["']status["']`` — backup
     for AST gaps (e.g. minified / formatted oddly / dataclass replace
     style). Flags any ``setattr`` / ``__setattr__`` call whose literal
     second arg is ``"status"`` regardless of leftmost-name resolution
     — over-broad on purpose because the intent of literally writing
     ``"status"`` outside the centralized writer is suspicious by
     itself.

Allow-list (loaded from ``Backend_FastAPI/.contract-allowlist.yaml``;
the YAML is the canonical source per spec line 109. The hardcoded
fallback below kicks in only when the YAML file is missing or
malformed — useful for the smoke run inside the test container before
the YAML lands):

  * ``app/services/admission_state_service.py`` — THE centralized
    writer; this is the ONE module where ``profile.status = ...``
    is the canonical pattern.
  * ``alembic/versions/**/*.py``                — data migrations
    legitimately rewrite status columns; lint covers code paths,
    not migration scripts.
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
    repository / DAL lint.

The detector errs on the side of fewer false positives (parameterized
attribute names like ``setattr(obj, name_var, value)`` are skipped at
the AST layer; Pattern 1.4 regex fallback recaptures them when the
literal ``"status"`` argument is still visible in the source line).

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
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
SCAN_DIRS: Tuple[str, ...] = ("app/services", "app/routers", "app/tasks")

# YAML-loaded allow-list config — spec source line 109. The script
# loads ``Backend_FastAPI/.contract-allowlist.yaml`` at startup; if
# the file is missing or malformed it falls back to the hardcoded
# defaults below so the smoke run inside the test container still
# exits 0 on clean code.
_ALLOWLIST_CONFIG_PATH = REPO_ROOT / ".contract-allowlist.yaml"

# Hardcoded fallback (used iff the YAML config can't be loaded).
# Glob patterns matched against POSIX-style relative paths via Python's
# fnmatch, which does NOT special-case ``**`` — patterns must spell
# each depth level explicitly. Keep in sync with
# ``.contract-allowlist.yaml`` so the fallback matches the canonical
# YAML when it lands.
_ALLOWLIST_FALLBACK: Tuple[str, ...] = (
    "app/services/admission_state_service.py",
    "alembic/versions/*.py",
    "tests/*.py",
    "tests/*/*.py",
    "tests/*/*/*.py",
)
_PROFILE_VAR_NAMES_FALLBACK: Tuple[str, ...] = (
    "profile",
    "locked_profile",
    "admission_profile",
    "current_profile",
    "profile_row",
    "prof",
)


def _load_config() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Load allow-list + profile-var-names from
    ``.contract-allowlist.yaml``. Falls back to the hardcoded defaults
    if the file is missing, unreadable, or has a malformed shape —
    callers get a working detector even before the YAML lands.

    Logged via stderr so a misconfigured YAML never silently
    downgrades the lint to fallback mode without operator visibility.
    """
    try:
        with _ALLOWLIST_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(
            f"[check_status_assignment] WARN: could not load "
            f"{_ALLOWLIST_CONFIG_PATH.name} ({exc!r}); "
            "using hardcoded fallback.",
            file=sys.stderr,
        )
        return _ALLOWLIST_FALLBACK, _PROFILE_VAR_NAMES_FALLBACK

    if not isinstance(data, dict):
        print(
            f"[check_status_assignment] WARN: {_ALLOWLIST_CONFIG_PATH.name} "
            "is not a YAML mapping; using hardcoded fallback.",
            file=sys.stderr,
        )
        return _ALLOWLIST_FALLBACK, _PROFILE_VAR_NAMES_FALLBACK

    raw_allowlist = data.get("allowlist") or []
    raw_var_names = data.get("profile_var_names") or []
    allowlist = tuple(str(item) for item in raw_allowlist) or _ALLOWLIST_FALLBACK
    profile_var_names = (
        tuple(str(item) for item in raw_var_names) or _PROFILE_VAR_NAMES_FALLBACK
    )
    return allowlist, profile_var_names


# Public constants — exposed for the lock tests in
# ``test_check_status_assignment.py`` so the YAML drift surfaces as a
# test failure rather than silent fallback.
ALLOWLIST, ADMISSION_PROFILE_VAR_NAMES = _load_config()
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


def _is_setattr_status_call(node: ast.Call) -> Optional[Tuple[str, str]]:
    """Return ``(pattern, source_repr)`` if ``node`` is one of:

    * Pattern 1.2 — ``setattr(<profile-var>, "status", <value>)``
    * Pattern 1.3 — ``<profile-var>.__setattr__("status", <value>)``

    Else ``None``.

    Object must be a ``Name`` in ``ADMISSION_PROFILE_VAR_NAMES`` so
    ``setattr(fee, "status", ...)`` etc. on non-admission entities
    fall through. Skips parameterized name forms (``setattr(obj,
    attr_var, value)``) — they cannot be statically resolved to
    ``"status"`` and the detector errs on the side of fewer false
    positives at the AST layer; Pattern 1.4 regex fallback recaptures
    the dynamic-attr case when the literal ``"status"`` argument is
    still visible in the source line.
    """
    func = node.func

    # Pattern 1.2 — ``setattr(profile, "status", value)``: bare
    # ``Name`` callable + 3 args.
    if isinstance(func, ast.Name) and func.id == "setattr":
        if len(node.args) < 3:
            return None
        name_arg = node.args[1]
        if not isinstance(name_arg, ast.Constant) or name_arg.value != "status":
            return None
        obj_arg = node.args[0]
        if not (
            isinstance(obj_arg, ast.Name)
            and obj_arg.id in ADMISSION_PROFILE_VAR_NAMES
        ):
            return None
        return "setattr", f'setattr({obj_arg.id}, "status", ...)'

    # Pattern 1.3 — ``profile.__setattr__("status", value)``: the
    # callable is an ``Attribute`` whose ``attr`` is ``__setattr__``
    # AND whose ``value`` is a ``Name`` in the admission alias set.
    # 2 positional args (``"status"``, value).
    if isinstance(func, ast.Attribute) and func.attr == "__setattr__":
        if not (
            isinstance(func.value, ast.Name)
            and func.value.id in ADMISSION_PROFILE_VAR_NAMES
        ):
            return None
        if len(node.args) < 2:
            return None
        name_arg = node.args[0]
        if not isinstance(name_arg, ast.Constant) or name_arg.value != "status":
            return None
        return "dunder_setattr", f'{func.value.id}.__setattr__("status", ...)'

    return None


# Pattern 1.4 — regex grep fallback. Two flavors because
# ``setattr(obj, name, value)`` (3 args) and ``obj.__setattr__(name,
# value)`` (2 args bound) place the ``"status"`` literal at different
# arg positions:
#
#   * ``setattr`` form  — ``"status"`` is the 2nd positional arg, so
#     match: ``setattr ( <1st-arg> , "status"``.
#   * ``__setattr__`` form — bound on the receiver, so ``"status"``
#     is the FIRST positional arg: ``__setattr__ ( "status"``.
#
# Both patterns allow nested parens in the 1st arg (e.g.
# ``setattr(get_profile(), "status", x)``) by NOT excluding parens
# from the 1st-arg character class. The trade-off is occasional
# false positives on exotic shapes (e.g. a comma inside a nested
# string literal); the de-dupe via ``ast_caught_lines`` + ``ast
# _rejected_lines`` covers the common cases.
_DYNAMIC_STATUS_PATTERN_SETATTR = re.compile(
    r"""\bsetattr\s*\(
        \s*[^,]+?\s*,\s*           # 1st arg + comma (any chars; nested parens OK)
        ["']status["']             # 2nd arg literal "status"
    """,
    re.VERBOSE,
)
_DYNAMIC_STATUS_PATTERN_DUNDER = re.compile(
    r"""\b__setattr__\s*\(
        \s*["']status["']          # 1st arg literal "status"
    """,
    re.VERBOSE,
)


def _scan_dynamic_status_writes(rel: str, source: str) -> List["Violation"]:
    """Pattern 1.4 — line-by-line regex grep for setattr/__setattr__
    calls whose literal ``"status"`` arg is in the position the
    function's signature expects.

    Skips comment lines (``#``-prefixed); de-dupe against AST hits
    happens in ``_scan_file`` via the ``suppressed`` set. The regex
    is more permissive than the AST checks above because its job is
    to catch AST gaps (e.g. ``setattr(get_profile(), "status", x)``
    where the first arg is a Call, not a Name) — the trade-off is
    occasional false positives on exotic shapes.
    """
    found: List["Violation"] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        match = _DYNAMIC_STATUS_PATTERN_SETATTR.search(line)
        if match is not None:
            found.append(Violation(
                file=rel,
                line=lineno,
                pattern="regex_fallback",
                target_repr='setattr(..., "status", ...) [regex fallback]',
            ))
            continue  # one regex_fallback hit per line is enough
        match = _DYNAMIC_STATUS_PATTERN_DUNDER.search(line)
        if match is not None:
            found.append(Violation(
                file=rel,
                line=lineno,
                pattern="regex_fallback",
                target_repr='<obj>.__setattr__("status", ...) [regex fallback]',
            ))
    return found


def _is_setattr_status_inspected_and_rejected(node: ast.Call) -> bool:
    """Return True if ``node`` is a ``setattr(<known-non-admission-name>,
    "status", value)`` or ``<known-non-admission-name>.__setattr__(
    "status", value)`` call — i.e. the AST detector inspected the
    line, saw a literal ``"status"`` second arg, but rejected because
    the leftmost was a ``Name`` NOT in ``ADMISSION_PROFILE_VAR_NAMES``.

    These are intentional non-admission entity writes (Fee, User,
    ZaloDelivery, etc.) — Pattern 1.4 regex MUST skip them, otherwise
    the regex over-broad catch would re-flag every Fee/User/Delivery
    ``.status = ...`` write across the codebase as a false positive.

    Returns False for cases AST genuinely can't resolve (first arg is
    ``Call``, ``Subscript``, etc.) — those are the AST-gap cases
    Pattern 1.4 is designed to catch.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id == "setattr":
        if len(node.args) < 2:
            return False
        name_arg = node.args[1]
        if not isinstance(name_arg, ast.Constant) or name_arg.value != "status":
            return False
        obj_arg = node.args[0]
        # Inspected + rejected = first arg is a Name we recognize
        # (decided to skip), NOT an unparseable expression (AST gap).
        return (
            isinstance(obj_arg, ast.Name)
            and obj_arg.id not in ADMISSION_PROFILE_VAR_NAMES
        )
    if isinstance(func, ast.Attribute) and func.attr == "__setattr__":
        if len(node.args) < 1:
            return False
        name_arg = node.args[0]
        if not isinstance(name_arg, ast.Constant) or name_arg.value != "status":
            return False
        return (
            isinstance(func.value, ast.Name)
            and func.value.id not in ADMISSION_PROFILE_VAR_NAMES
        )
    return False


def _scan_file(py_file: Path, rel: str) -> List[Violation]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    found: List[Violation] = []
    ast_caught_lines: set[int] = set()  # de-dupe regex against AST hits
    ast_rejected_lines: set[int] = set()  # AST inspected + skipped (non-admission entity)

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
                    ast_caught_lines.add(node.lineno)
        elif isinstance(node, ast.AugAssign):
            rendered = _is_status_attribute_target(node.target)
            if rendered:
                found.append(Violation(
                    file=rel,
                    line=node.lineno,
                    pattern="direct_assign",
                    target_repr=f"{rendered} {ast.unparse(node.op)}= ...",
                ))
                ast_caught_lines.add(node.lineno)
        elif isinstance(node, ast.Call):
            ast_hit = _is_setattr_status_call(node)
            if ast_hit:
                pattern, repr_str = ast_hit
                found.append(Violation(
                    file=rel,
                    line=node.lineno,
                    pattern=pattern,
                    target_repr=repr_str,
                ))
                ast_caught_lines.add(node.lineno)
            elif _is_setattr_status_inspected_and_rejected(node):
                # AST inspected the literal "status" call, leftmost
                # name is recognized non-admission — Pattern 1.4
                # regex MUST also skip to avoid false positives on
                # Fee/User/ZaloDelivery ``.status = ...`` writes.
                ast_rejected_lines.add(node.lineno)

    # Pattern 1.4 — regex grep fallback. Append only lines where AST
    # neither flagged nor consciously rejected. This keeps the regex
    # firing on AST-gap cases (e.g. ``setattr(get_profile(), "status",
    # x)`` with a Call as first arg) while suppressing the over-broad
    # catch on intentional non-admission ``.status`` writes.
    suppressed = ast_caught_lines | ast_rejected_lines
    for v in _scan_dynamic_status_writes(rel, source):
        if v.line not in suppressed:
            found.append(v)

    return found


def _is_path_allowlisted(rel: str, allowlist: Tuple[str, ...]) -> bool:
    """Return True when ``rel`` matches any glob pattern in ``allowlist``.

    Uses ``fnmatch`` semantics — ``alembic/versions/**/*.py`` matches
    any ``alembic/versions/<anything>/...py`` path. Exact-path entries
    (``app/services/admission_state_service.py``) match themselves
    only. Mirrors the spec line 109 glob format.
    """
    for pattern in allowlist:
        if fnmatch.fnmatch(rel, pattern):
            return True
    return False


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
            if _is_path_allowlisted(rel, ALLOWLIST):
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
