# app/services/priority_service.py
"""Priority Bonus calculation service (Q9 #07 PR2).

Pure Python (no FastAPI imports) — takes a profile + bonus rule snapshot
+ academic_year, returns ``(area_bonus, object_bonus, config_snapshot)``.

Plug point: ``admission_choice_engine_service.evaluate_cascade()`` calls
this for each choice at T6 publish time, right after capturing
``bonus_rule_snapshot``. The 3 return values are written verbatim to
``admission_profile_choice.priority_area_bonus_snapshot`` /
``priority_object_bonus_snapshot`` / ``priority_config_snapshot``.

Compliance source (TT 05/2021/TT-BLĐTBXH Phụ lục 01)
----------------------------------------------------

* KV (khu vực): max 4 codes per ``priority_area_config`` table; each
  ``academic_year`` has its own row set so a mid-year regulation change
  creates a new row instead of mutating the old one.

* UT (đối tượng): N sub_codes per ``priority_object_config``; multi-UT
  per profile applies the MAX (TT 05/2021 Phụ lục 01: "chỉ được hưởng
  một diện ưu tiên cao nhất").

* Evidence gate: UT bonus only counts for sub_codes whose
  ``priority_object_evidence[sub_code].status == 'verified'``. Unverified
  / rejected / missing → 0 contribution, regardless of admin / officer
  later flipping it (snapshot freezes T6 state).

* Cap: optional ``rule.max_total_bonus``; NULL = no cap (TT 05/2021
  default; admin may set per quy chế trường).

* Toggle: ``rule.apply_area_bonus`` / ``apply_object_bonus`` gate each
  side independently. Both false → snapshot all zeros (engine still
  records the config_snapshot for audit).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.admission import AdmissionProfile


_ZERO = Decimal("0.00")


async def calculate_priority_bonus(
    db: "AsyncSession",
    profile: "AdmissionProfile",
    rule: Optional[dict[str, Any]],
    academic_year: int,
) -> tuple[Decimal, Decimal, dict[str, Any]]:
    """Compute KV + UT bonus for a profile at T6 publish.

    Args:
        db: active AsyncSession (engine already opens a savepoint).
        profile: AdmissionProfile (eager-loaded; reads
            ``high_school_kv_resolved`` + ``priority_object_codes`` +
            ``priority_object_evidence`` + ``area_resolution_basis``).
        rule: BonusRuleOverride snapshot dict from
            ``resolve_effective_bonus_rule(path)``. NULL = bonus disabled
            (legacy paths without explicit override or method default).
        academic_year: year-level grouping (vd 2026) — looked up via
            ``path.admission_round.academic_year``.

    Returns:
        ``(area_bonus, object_bonus, config_snapshot)``

        * area_bonus: Decimal(4, 2) after toggle + cap
        * object_bonus: Decimal(4, 2) after toggle + cap (max of verified)
        * config_snapshot: JSONB-shaped dict for audit replay; always
          populated (even when bonus disabled) so engine has a record
          of "we considered priority for this choice but the rule said 0"
    """
    # Build config_snapshot upfront so every code path returns one.
    snapshot: dict[str, Any] = {
        "academic_year": academic_year,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "rule": dict(rule) if rule else None,
        "area_resolution_basis": getattr(profile, "area_resolution_basis", None),
        "area_code": None,
        "area_rate": None,
        "object_max_code": None,
        "object_rate": None,
        "verified_codes": [],
    }

    if rule is None:
        # Legacy path with no method default + no path override = bonus disabled.
        return _ZERO, _ZERO, snapshot

    apply_area = bool(rule.get("apply_area_bonus"))
    apply_object = bool(rule.get("apply_object_bonus"))
    max_total = rule.get("max_total_bonus")
    max_total_dec = Decimal(str(max_total)) if max_total is not None else None

    area_bonus = _ZERO
    object_bonus = _ZERO

    if apply_area:
        area_bonus, area_meta = await _resolve_area_bonus(
            db=db,
            profile=profile,
            academic_year=academic_year,
        )
        snapshot.update(area_meta)

    if apply_object:
        object_bonus, object_meta = await _resolve_object_bonus(
            db=db,
            profile=profile,
            academic_year=academic_year,
        )
        snapshot.update(object_meta)

    # Combined cap (TT 05/2021 không enforce; admin tùy chọn).
    if max_total_dec is not None:
        total = area_bonus + object_bonus
        if total > max_total_dec:
            # Proportional clip — keeps area/object ratio so the audit
            # snapshot still reflects "this profile would have qualified
            # for X but cap reduced to Y" without misattributing the cut.
            if total > _ZERO:
                ratio = max_total_dec / total
                area_bonus = (area_bonus * ratio).quantize(Decimal("0.01"))
                object_bonus = (object_bonus * ratio).quantize(Decimal("0.01"))
            snapshot["cap_applied"] = str(max_total_dec)

    return area_bonus, object_bonus, snapshot


async def _resolve_area_bonus(
    db: "AsyncSession",
    profile: "AdmissionProfile",
    academic_year: int,
) -> tuple[Decimal, dict[str, Any]]:
    """Lookup the KV rate for the profile's resolved area_code.

    v1.3 phase1_09: KV resolved code lives in
    ``profile.priority_resolution_snapshot.kv_resolved`` (frozen at T1
    submit + re-frozen at T6 engine, per Q-P3-11 snapshot pattern).
    Falls back to legacy ``profile.high_school_kv_resolved`` getattr
    for backward-compat during cutover transition (column DROPPED in
    phase1_09 so getattr returns None on real ORM, but kept for test
    SimpleNamespace stubs).

    NULL → 0đ (graceful — candidate chưa fill diploma info).

    Returns ``(bonus_points, meta_dict)`` where meta is merged into the
    config_snapshot for audit.
    """
    from app.models.priority_config import PriorityAreaConfig

    # v1.3: read from snapshot.kv_resolved (canonical post-phase1_09)
    snapshot = getattr(profile, "priority_resolution_snapshot", None) or {}
    area_code = snapshot.get("kv_resolved") if isinstance(snapshot, dict) else None
    # Backward-compat fallback for test stubs + legacy code paths
    if not area_code:
        area_code = getattr(profile, "high_school_kv_resolved", None)
    meta: dict[str, Any] = {"area_code": area_code, "area_rate": None}
    if not area_code:
        return _ZERO, meta

    stmt = (
        select(PriorityAreaConfig.bonus_points)
        .where(
            PriorityAreaConfig.academic_year == academic_year,
            PriorityAreaConfig.area_code == area_code,
            PriorityAreaConfig.effective_from <= _today(),
        )
        .where(
            (PriorityAreaConfig.effective_to.is_(None))
            | (PriorityAreaConfig.effective_to > _today())
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    rate = result.scalar_one_or_none()
    if rate is None:
        # Admin chưa seed rate cho năm này → engine ghi 0đ (graceful);
        # snapshot vẫn lưu area_code để audit thấy "candidate khai KV1
        # nhưng rate chưa có config".
        return _ZERO, meta

    meta["area_rate"] = str(rate)
    return Decimal(rate), meta


async def _resolve_object_bonus(
    db: "AsyncSession",
    profile: "AdmissionProfile",
    academic_year: int,
) -> tuple[Decimal, dict[str, Any]]:
    """Lookup MAX UT rate over verified evidence.

    Per TT 05/2021 Phụ lục 01: "chỉ được hưởng một diện ưu tiên cao
    nhất" — multi-UT đối tượng applies the highest bonus, not the sum.

    Evidence gate: a sub_code only counts if
    ``profile.priority_object_evidence[code].status == 'verified'``.
    Missing key / 'pending' / 'rejected' → 0 contribution.

    Returns ``(bonus_points, meta_dict)``.
    """
    from app.models.priority_config import PriorityObjectConfig

    codes = getattr(profile, "priority_object_codes", None) or []
    evidence = getattr(profile, "priority_object_evidence", None) or {}

    verified_codes = [
        c
        for c in codes
        if isinstance(evidence.get(c), dict)
        and evidence[c].get("status") == "verified"
    ]
    meta: dict[str, Any] = {
        "verified_codes": verified_codes,
        "object_max_code": None,
        "object_rate": None,
    }
    if not verified_codes:
        return _ZERO, meta

    stmt = (
        select(
            PriorityObjectConfig.sub_code,
            PriorityObjectConfig.bonus_points,
        )
        .where(
            PriorityObjectConfig.academic_year == academic_year,
            PriorityObjectConfig.sub_code.in_(verified_codes),
            PriorityObjectConfig.effective_from <= _today(),
        )
        .where(
            (PriorityObjectConfig.effective_to.is_(None))
            | (PriorityObjectConfig.effective_to > _today())
        )
    )
    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return _ZERO, meta

    # Pick max bonus + record which sub_code won (audit "candidate had
    # UT1+UT2 verified, engine applied UT1 because higher rate").
    best_code, best_rate = max(rows, key=lambda r: r[1])
    meta["object_max_code"] = best_code
    meta["object_rate"] = str(best_rate)
    return Decimal(best_rate), meta


def _today():
    """date.today() — extracted so tests can monkeypatch a fixed value
    without freezing the whole datetime module."""
    from datetime import date

    return date.today()
