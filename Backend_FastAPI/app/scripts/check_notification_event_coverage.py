"""
Notification event coverage checker.

Verifies that every ``SystemEvents`` member that should fire a
user-facing notification has all four of its end-to-end mounting
points wired up:

  1. EVENT_CATALOG entry exists
  2. NOTIFICATION_SEED_DEFAULTS entry exists (only required for
     notification_class="user" + not retired)
  3. At least one source-file dispatch site (grep
     ``event=SystemEvents.<NAME>``)
  4. (Optional, --check-db) at least one ``notification_rule`` row
     with ≥1 ``notification_action`` row

Output is a per-event grid plus a summary. Exit code is 0 when no
required mount point is missing, 1 otherwise — suitable for CI.

The grep step is the one that ``ultrareview``-style diff readers
miss: a brand-new event in the catalog that no service ever
dispatches will pass type checks and unit tests, but produce zero
notifications in production. Run this before merging anything that
adds or renames a SystemEvents member.

Usage:
    python -m app.scripts.check_notification_event_coverage
    python -m app.scripts.check_notification_event_coverage --check-db
    python -m app.scripts.check_notification_event_coverage --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set

from app.core.event_catalog import EVENT_CATALOG
from app.core.events import SystemEvents
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS


REPO_ROOT = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
SCAN_DIRS = ("app/services", "app/tasks", "app/routers", "app/scripts")
DISPATCH_PATTERN = re.compile(r"event\s*=\s*SystemEvents\.([A-Z_][A-Z0-9_]*)")


@dataclass
class EventStatus:
    name: str
    in_catalog: bool = False
    notification_class: Optional[str] = None
    retired: bool = False
    in_seed_defaults: bool = False
    dispatch_sites: List[str] = field(default_factory=list)
    db_rule_present: Optional[bool] = None
    db_action_count: Optional[int] = None

    @property
    def requires_seed(self) -> bool:
        return (
            self.in_catalog
            and self.notification_class == "user"
            and not self.retired
        )

    @property
    def gaps(self) -> List[str]:
        out: List[str] = []
        if not self.in_catalog:
            out.append("missing-catalog-entry")
        if self.requires_seed and not self.in_seed_defaults:
            out.append("missing-seed-default")
        if self.requires_seed and not self.dispatch_sites:
            out.append("no-dispatch-site")
        if self.db_rule_present is False and self.requires_seed:
            out.append("no-db-rule")
        if (
            self.db_rule_present is True
            and (self.db_action_count or 0) == 0
        ):
            out.append("rule-has-zero-actions")
        return out


_SELF_PATH = Path(__file__).resolve()


def _scan_dispatch_sites() -> dict[str, List[str]]:
    """Grep dispatch sites: ``event=SystemEvents.<NAME>`` across the tree."""
    hits: dict[str, List[str]] = {}
    for sub in SCAN_DIRS:
        base = REPO_ROOT / sub
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            if py_file.resolve() == _SELF_PATH:
                continue  # don't match our own docstring examples
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                for match in DISPATCH_PATTERN.finditer(line):
                    name = match.group(1)
                    rel = py_file.relative_to(REPO_ROOT).as_posix()
                    hits.setdefault(name, []).append(f"{rel}:{lineno}")
    return hits


async def _scan_db() -> dict[str, tuple[bool, int]]:
    """Optional DB check — counts rule + action rows per event."""
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models import notification as nm

    out: dict[str, tuple[bool, int]] = {}
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                nm.NotificationRule.event,
                func.count(nm.NotificationAction.id),
            )
            .outerjoin(
                nm.NotificationAction,
                nm.NotificationAction.rule_id == nm.NotificationRule.id,
            )
            .group_by(nm.NotificationRule.event)
        )
        for event_name, action_count in result.all():
            out[event_name] = (True, int(action_count or 0))
    return out


def _build_statuses(
    db_data: Optional[dict[str, tuple[bool, int]]] = None,
) -> List[EventStatus]:
    dispatch_sites = _scan_dispatch_sites()
    catalog_by_name = {ev.value: defn for ev, defn in EVENT_CATALOG.items()}
    seed_keys: Set[str] = {ev.value for ev in NOTIFICATION_SEED_DEFAULTS}

    statuses: List[EventStatus] = []
    enum_names: Set[str] = set()

    for member in SystemEvents:
        enum_names.add(member.name)
        defn = catalog_by_name.get(member.value)
        st = EventStatus(name=member.name)
        if defn is not None:
            st.in_catalog = True
            st.notification_class = defn.notification_class
            st.retired = defn.retired
        st.in_seed_defaults = member.value in seed_keys
        st.dispatch_sites = dispatch_sites.get(member.name, [])
        if db_data is not None:
            present, count = db_data.get(member.value, (False, 0))
            st.db_rule_present = present
            st.db_action_count = count
        statuses.append(st)

    # Surface dispatch grep matches that point at names that no longer
    # exist on the enum (rename without grep, dead code, typos).
    for grepped_name in dispatch_sites:
        if grepped_name not in enum_names:
            ghost = EventStatus(name=f"{grepped_name} (UNKNOWN-ENUM)")
            ghost.dispatch_sites = dispatch_sites[grepped_name]
            statuses.append(ghost)

    return statuses


def _print_text(statuses: Iterable[EventStatus], check_db: bool) -> None:
    cols = ["Event", "Cat", "Class", "Seed", "Dispatch"]
    if check_db:
        cols += ["DB Rule", "Actions"]
    cols += ["Gaps"]

    print("\t".join(cols))
    for st in statuses:
        if not st.gaps and not st.requires_seed and st.in_catalog:
            # Quiet rows: in-catalog non-user / retired with no gaps
            continue
        row = [
            st.name,
            "Y" if st.in_catalog else "—",
            st.notification_class or "—",
            "Y" if st.in_seed_defaults else "—",
            str(len(st.dispatch_sites)),
        ]
        if check_db:
            row += [
                "—" if st.db_rule_present is None
                else ("Y" if st.db_rule_present else "—"),
                "—" if st.db_action_count is None else str(st.db_action_count),
            ]
        row += [",".join(st.gaps) or "ok"]
        print("\t".join(row))


def _print_json(statuses: Iterable[EventStatus]) -> None:
    payload = [
        {
            "name": st.name,
            "in_catalog": st.in_catalog,
            "notification_class": st.notification_class,
            "retired": st.retired,
            "requires_seed": st.requires_seed,
            "in_seed_defaults": st.in_seed_defaults,
            "dispatch_sites": st.dispatch_sites,
            "db_rule_present": st.db_rule_present,
            "db_action_count": st.db_action_count,
            "gaps": st.gaps,
        }
        for st in statuses
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _summarize(statuses: List[EventStatus]) -> int:
    failing = [st for st in statuses if st.gaps]
    if not failing:
        print("\nOK — every notification event is fully wired.", file=sys.stderr)
        return 0
    print(f"\n{len(failing)} event(s) with gaps:", file=sys.stderr)
    for st in failing:
        print(f"  - {st.name}: {', '.join(st.gaps)}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Also probe notification_rule + notification_action rows.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of TSV.",
    )
    args = parser.parse_args()

    db_data: Optional[dict[str, tuple[bool, int]]] = None
    if args.check_db:
        db_data = asyncio.run(_scan_db())

    statuses = _build_statuses(db_data)
    if args.json:
        _print_json(statuses)
    else:
        _print_text(statuses, check_db=args.check_db)
    return _summarize(statuses)


if __name__ == "__main__":
    sys.exit(main())
