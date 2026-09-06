#!/usr/bin/env python3
"""Fail-closed classifier for production deployment changes.

The workflow itself always starts on ``push: main``.  This program decides
whether the environment-protected deploy job should be created.  Only paths
that are explicitly known to be CI/test/documentation-only may return
``SAFE_NO_DEPLOY``; runtime, control-plane, mixed, and unknown changes all
return ``DEPLOY``.

The classifier reads Git's NUL-delimited diff directly.  It does not use the
GitHub changed-files API or event-level path filters, and therefore does not
inherit their file-list truncation when deciding whether production is stale.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


DEPLOY = "DEPLOY"
SAFE_NO_DEPLOY = "SAFE_NO_DEPLOY"
BLOCK = "BLOCK"

SCHEMA_VERSION = 1
ZERO_SHA = "0" * 40
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
STATUS_RE = re.compile(r"[A-Z][0-9]{0,3}\Z")

# These files control whether or how production is changed.  They must be
# checked before the broad .github/ safe prefix below.
CONTROL_PLANE_EXACT = {
    ".github/workflows/deploy.yml",
    ".github/scripts/deploy_change_classifier.py",
}
CONTROL_PLANE_PREFIXES = (
    ".github/actions/",
    ".github/scripts/deploy_",
)

# frontend/** is intentionally indivisible.  Its Docker source stage hashes
# the effective context into .qlts-source-manifest.json, including colocated
# *.test.ts(x) files that frontend/.dockerignore does not exclude.
RUNTIME_PREFIXES = (
    "Backend_FastAPI/app/",
    "Backend_FastAPI/alembic/",
    "Backend_FastAPI/scripts/",
    "frontend/",
    "nginx/",
    "scripts/",
)

RUNTIME_EXACT = {
    "Backend_FastAPI/.dockerignore",
    "Backend_FastAPI/Dockerfile",
    "Backend_FastAPI/alembic.ini",
    "Backend_FastAPI/auth_model.conf",
    "Backend_FastAPI/docker-entrypoint.sh",
    "Backend_FastAPI/gunicorn.conf.py",
    "docker-compose.yml",
}

RUNTIME_RE = (
    re.compile(r"^Backend_FastAPI/Dockerfile(?:\.[^/]+)?\Z"),
    re.compile(r"^Backend_FastAPI/requirements[^/]*\.txt\Z"),
    re.compile(r"^Backend_FastAPI/docker-entrypoint[^/]*\Z"),
    re.compile(r"^docker-compose[^/]*\.ya?ml\Z"),
)

# This is the only route to SAFE_NO_DEPLOY.  Anything outside these explicit
# surfaces is UNKNOWN and therefore deploys.  .github/actions/** is evaluated
# as control-plane first, so a future local action cannot silently become safe.
SAFE_PREFIXES = (
    "Backend_FastAPI/tests/",
    "Documents/",
    "tests-e2e/",
    ".github/",
    ".agent/",
    ".smoke-evidence/",
    ".claude/",
)

SAFE_EXACT = {
    ".dockerignore",  # no production image uses the repository root as context
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
}

SAFE_RE = (
    re.compile(r"^[^/]+\.md\Z"),
    re.compile(r"^LICENSE(?:\.[^/]+)?\Z"),
)

SKIP_BRACKET_RE = re.compile(
    r"\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]", re.IGNORECASE
)
SKIP_TRAILER_RE = re.compile(
    r"^skip-checks\s*:\s*true\s*$", re.IGNORECASE | re.MULTILINE
)


class ClassificationError(Exception):
    """Input or repository state is not trustworthy enough to classify."""


@dataclass(frozen=True)
class ChangeRecord:
    status: str
    old_path: str | None
    new_path: str | None

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(p for p in (self.old_path, self.new_path) if p is not None)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "old_path": self.old_path,
            "new_path": self.new_path,
        }


def _validate_sha(value: str, label: str) -> str:
    value = value.strip().lower()
    if not SHA_RE.fullmatch(value):
        raise ClassificationError(f"{label} must be exactly 40 lowercase hex characters")
    return value


def _normalise_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ClassificationError("diff contains an empty or non-string path")
    if "\x00" in value or "\\" in value or value.startswith("/"):
        raise ClassificationError(f"diff contains an unsafe path: {value!r}")
    path = value[2:] if value.startswith("./") else value
    parts = PurePosixPath(path).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ClassificationError(f"diff contains an unsafe path: {value!r}")
    return path


def parse_name_status_z(raw: bytes) -> list[ChangeRecord]:
    """Parse ``git diff --name-status -z`` without splitting path whitespace."""
    if not isinstance(raw, bytes):
        raise ClassificationError("git diff output must be bytes")
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise ClassificationError("truncated NUL-delimited git diff")

    try:
        tokens = [part.decode("utf-8", errors="strict") for part in raw[:-1].split(b"\0")]
    except UnicodeDecodeError as exc:
        raise ClassificationError(f"git diff is not UTF-8: {exc}") from exc

    records: list[ChangeRecord] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not STATUS_RE.fullmatch(status):
            raise ClassificationError(f"invalid git status token: {status!r}")
        kind = status[0]
        needed = 2 if kind in {"R", "C"} else 1
        if index + needed > len(tokens):
            raise ClassificationError(f"truncated record for git status {status!r}")
        paths = [_normalise_path(p) for p in tokens[index:index + needed]]
        index += needed
        if kind in {"R", "C"}:
            records.append(ChangeRecord(status, paths[0], paths[1]))
        elif kind == "D":
            records.append(ChangeRecord(status, paths[0], None))
        else:
            records.append(ChangeRecord(status, None, paths[0]))
    return records


def classify_path(path: str) -> str:
    path = _normalise_path(path)
    if path in CONTROL_PLANE_EXACT or path.startswith(CONTROL_PLANE_PREFIXES):
        return "runtime"
    if path in RUNTIME_EXACT or path.startswith(RUNTIME_PREFIXES):
        return "runtime"
    if any(pattern.fullmatch(path) for pattern in RUNTIME_RE):
        return "runtime"
    if path in SAFE_EXACT or path.startswith(SAFE_PREFIXES):
        return "safe"
    if any(pattern.fullmatch(path) for pattern in SAFE_RE):
        return "safe"
    return "unknown"


def classify_records(records: Sequence[ChangeRecord]) -> dict[str, object]:
    if not records:
        raise ClassificationError("push diff contains zero change records")

    seen_paths: set[str] = set()
    runtime: set[str] = set()
    unknown: set[str] = set()
    safe: set[str] = set()
    for record in records:
        if not record.paths:
            raise ClassificationError(f"record has no paths: {record!r}")
        for path in record.paths:
            if path in seen_paths:
                # A path may legitimately be the destination of one record and
                # source of another in an unusual diff; classify it once.
                continue
            seen_paths.add(path)
            kind = classify_path(path)
            {"runtime": runtime, "unknown": unknown, "safe": safe}[kind].add(path)

    deploy = bool(runtime or unknown)
    reasons = [f"runtime:{path}" for path in sorted(runtime)]
    reasons.extend(f"unknown:{path}" for path in sorted(unknown))
    if not deploy:
        reasons.append("only_explicit_safe_paths")
    return {
        "classification": DEPLOY if deploy else SAFE_NO_DEPLOY,
        "deploy": deploy,
        "reasons": reasons,
        "runtime_paths": sorted(runtime),
        "unknown_paths": sorted(unknown),
        "safe_paths": sorted(safe),
        "unique_path_count": len(seen_paths),
    }


def _git(*args: str, text: bool = False) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", *args],
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"") or getattr(exc, "stdout", b"") or b""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ClassificationError(f"git command failed: {str(detail).strip() or exc}") from exc
    return result.stdout


def read_diff(before: str, after: str) -> list[ChangeRecord]:
    raw = _git(
        "-c", "diff.renames=true", "diff", "--name-status", "-z", "-M",
        before, after, "--",
    )
    assert isinstance(raw, bytes)
    return parse_name_status_z(raw)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_github_output(deploy: bool, classification: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"deploy={'true' if deploy else 'false'}\n")
        handle.write(f"classification={classification}\n")


def make_plan(event: str, before: str, after: str) -> dict[str, object]:
    after = _validate_sha(after, "after")
    head = str(_git("rev-parse", "HEAD", text=True)).strip().lower()
    if head != after:
        raise ClassificationError(f"checkout HEAD {head!r} differs from after {after!r}")

    if event == "workflow_dispatch":
        decision: dict[str, object] = {
            "classification": DEPLOY,
            "deploy": True,
            "reasons": ["manual_workflow_dispatch"],
            "runtime_paths": [],
            "unknown_paths": [],
            "safe_paths": [],
            "unique_path_count": 0,
        }
        records: list[ChangeRecord] = []
        before_value: str | None = None
    elif event == "push":
        before_value = _validate_sha(before, "before")
        if before_value == ZERO_SHA:
            decision = {
                "classification": DEPLOY,
                "deploy": True,
                "reasons": ["zero_before_sha"],
                "runtime_paths": [],
                "unknown_paths": [],
                "safe_paths": [],
                "unique_path_count": 0,
            }
            records = []
        else:
            records = read_diff(before_value, after)
            decision = classify_records(records)
    else:
        raise ClassificationError(f"unsupported event: {event!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "enforcing",
        "event": event,
        "before_sha": before_value,
        "after_sha": after,
        "change_record_count": len(records),
        "records": [record.as_dict() for record in records],
        **decision,
    }


def find_skip_directives(parts: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for source, text in parts:
        text = text or ""
        for match in SKIP_BRACKET_RE.finditer(text):
            found.append({"source": source, "directive": match.group(0)})
        for match in SKIP_TRAILER_RE.finditer(text):
            found.append({"source": source, "directive": match.group(0)})
    return found


def _commit_messages(base: str, head: str) -> list[str]:
    base = _validate_sha(base, "base")
    head = _validate_sha(head, "head")
    raw = _git("log", "--format=%B%x00", f"{base}..{head}")
    assert isinstance(raw, bytes)
    try:
        return [part.decode("utf-8", errors="strict") for part in raw.split(b"\0") if part]
    except UnicodeDecodeError as exc:
        raise ClassificationError(f"commit message is not UTF-8: {exc}") from exc


def check_skip_directives(base: str, head: str, title: str, body: str) -> list[dict[str, str]]:
    parts: list[tuple[str, str]] = [("pull_request.title", title), ("pull_request.body", body)]
    parts.extend((f"commit[{index}]", message)
                 for index, message in enumerate(_commit_messages(base, head), start=1))
    return find_skip_directives(parts)


def _classify_command(args: argparse.Namespace) -> int:
    artifact = Path(args.artifact)
    try:
        plan = make_plan(args.event, args.before, args.after)
        _write_json(artifact, plan)
        deploy = bool(plan["deploy"])
        classification = str(plan["classification"])
        _write_github_output(deploy, classification)
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:  # fail closed and retain a diagnostic artifact
        plan = {
            "schema_version": SCHEMA_VERSION,
            "mode": "enforcing",
            "event": args.event,
            "before_sha": args.before or None,
            "after_sha": args.after or None,
            "classification": BLOCK,
            "deploy": False,
            "reasons": [f"exception:{type(exc).__name__}"],
            "block_reason": str(exc),
            "traceback": traceback.format_exc(),
            "change_record_count": 0,
            "records": [],
        }
        try:
            _write_json(artifact, plan)
        finally:
            _write_github_output(False, BLOCK)
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


def _check_skip_command(args: argparse.Namespace) -> int:
    try:
        found = check_skip_directives(
            args.base,
            args.head,
            os.environ.get("PR_TITLE", ""),
            os.environ.get("PR_BODY", ""),
        )
    except Exception as exc:
        print(f"BLOCK: cannot inspect merge-message inputs: {exc}", file=sys.stderr)
        return 1
    if found:
        for item in found:
            print(f"::error::Forbidden Actions skip directive in {item['source']}: {item['directive']}")
        return 1
    print("No Actions skip directive in PR title, body, or commit messages.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify", help="classify a push or manual dispatch")
    classify.add_argument("--event", required=True, choices=("push", "workflow_dispatch"))
    classify.add_argument("--before", default="")
    classify.add_argument("--after", required=True)
    classify.add_argument("--artifact", required=True)
    classify.set_defaults(handler=_classify_command)

    check_skip = sub.add_parser(
        "check-skip-directives",
        help="reject messages that can suppress push/pull_request workflows",
    )
    check_skip.add_argument("--base", required=True)
    check_skip.add_argument("--head", required=True)
    check_skip.set_defaults(handler=_check_skip_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
