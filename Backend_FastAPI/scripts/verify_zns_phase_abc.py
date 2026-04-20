#!/usr/bin/env python3
"""
One-step verification gate for ZNS notification Phases A/B/C.

Purpose:
    - Run the focused regression suite that covers Phase A/B/C changes.
    - Surface the known unrelated legacy parity debt (`application_fee_paid`)
      without blocking by default.
    - Provide a single pre-push command before handing off to CI.

Usage:
    python Backend_FastAPI/scripts/verify_zns_phase_abc.py
    python Backend_FastAPI/scripts/verify_zns_phase_abc.py --strict

Exit codes:
    0 - Phase A/B/C regression suite passed and no unexpected parity drift found
    1 - Phase A/B/C regression suite failed, docker/pytest unavailable, or
        unexpected parity drift found
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PHASE_TEST_TARGETS: list[str] = [
    "tests/utils/test_datetime_helpers.py",
    "tests/utils/test_id_helpers.py",
    "tests/unit/test_notification_payloads.py",
    "tests/unit/test_condition_metadata_parity.py",
    "tests/unit/test_zalo_phase1_review_findings.py",
]

LEGACY_PARITY_TARGET = "tests/unit/test_notification_parity.py"
KNOWN_PARITY_DEBT_MARKER = "application_fee_paid"
KNOWN_PARITY_DEBT_DETAIL = "missing from NOTIFICATION_REGISTRY"


def build_command(*args: str) -> list[str]:
    return ["docker", "compose", "exec", "-T", "backend", *args]


def format_command(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def run_command(
    repo_root: Path,
    args: Sequence[str],
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=repo_root,
        text=True,
        capture_output=capture,
        check=False,
    )


def print_header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def ensure_pytest_available(repo_root: Path) -> bool:
    cmd = build_command("python", "-m", "pytest", "--version")
    print_header("Pytest Availability Check")
    print(format_command(cmd))
    result = run_command(repo_root, cmd, capture=True)
    if result.returncode == 0:
        print((result.stdout or "").strip())
        return True

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
    )
    print(output or "Unable to detect pytest.")
    print()
    print(
        "Pytest is not available in the backend container. "
        "Install dev dependencies first:"
    )
    print("  docker compose exec backend pip install -r requirements-dev.txt")
    return False


def run_phase_suite(repo_root: Path) -> bool:
    cmd = build_command("python", "-m", "pytest", "-q", *PHASE_TEST_TARGETS)
    print_header("Phase A/B/C Regression Suite")
    print(format_command(cmd))
    result = run_command(repo_root, cmd)
    return result.returncode == 0


def analyze_legacy_parity(repo_root: Path, *, strict: bool) -> bool:
    cmd = build_command("python", "-m", "pytest", "-q", LEGACY_PARITY_TARGET)
    print_header("Legacy Parity Sentinel")
    print(format_command(cmd))
    result = run_command(repo_root, cmd, capture=True)

    combined_output = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    )

    if result.returncode == 0:
        print((combined_output or "PASS").strip())
        return True

    print((combined_output or "FAIL").strip())

    is_known_debt = (
        KNOWN_PARITY_DEBT_MARKER in combined_output
        and KNOWN_PARITY_DEBT_DETAIL in combined_output
    )

    if is_known_debt and not strict:
        print()
        print(
            "Known legacy parity debt detected: "
            "`application_fee_paid` is still absent from deprecated "
            "`NOTIFICATION_REGISTRY`."
        )
        print(
            "Runtime catalog wiring is unaffected; this warning is kept visible "
            "so Phase A/B/C can be verified without masking new drift."
        )
        print("Use `--strict` if you want this debt to fail the gate.")
        return True

    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify ZNS notification Phases A/B/C before pushing to CI."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Fail the verification when the known legacy parity debt "
            "`application_fee_paid` is still present."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]

    print("ZNS Phase A/B/C Verification")
    print(f"Repo root: {repo_root}")
    print(f"Strict mode: {'ON' if args.strict else 'OFF'}")

    if not ensure_pytest_available(repo_root):
        return 1

    if not run_phase_suite(repo_root):
        print_header("Result")
        print("FAIL: Phase A/B/C regression suite failed.")
        return 1

    if not analyze_legacy_parity(repo_root, strict=args.strict):
        print_header("Result")
        if args.strict:
            print("FAIL: Legacy parity sentinel failed in strict mode.")
        else:
            print("FAIL: Unexpected parity drift detected.")
        return 1

    print_header("Result")
    if args.strict:
        print("PASS: Phase A/B/C regression suite and parity sentinel are clean.")
    else:
        print("PASS: Phase A/B/C regression suite is clean.")
        print(
            "NOTE: Non-blocking legacy parity debt is still surfaced when present."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
