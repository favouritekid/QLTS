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


# =============================================================================
# Phase C — KV Resolution (Q9 #07 PR5 v1.3)
# =============================================================================
#
# Implements TT 05/2021/TT-BLĐTBXH Phụ lục 01 multi-school KV resolution:
#   - "Nếu chuyển trường, thời gian học ở khu vực nào lâu hơn được hưởng
#      ưu tiên theo khu vực đó."
#   - "Khi mỗi năm học một trường thuộc các khu vực có mức ưu tiên khác
#      nhau hoặc nửa thời gian học ở trường này, nửa thời gian học ở
#      trường kia thì tốt nghiệp ở khu vực nào, hưởng ưu tiên theo khu
#      vực đó."
#
# Branched by 2-field parallel (cultural_education_level, vocational_qualification)
# per v1.3 redesign. See Documents/Q9_07_PR5_REDESIGN.md cho 6-row matrix
# + 3 bypass cases (area_resolution_basis = permanent_address_special / manual_override
# / NOT_RESOLVED).
# =============================================================================


def _derive_kv_basis_level(
    cultural: Optional[str],
    vocational: str,
    area_resolution_basis: Optional[str] = None,
) -> str:
    """Map (cultural, vocational, area_basis) → KV resolution basis.

    Returns one of:
      'THPT'              — apply 3-year THPT multi-school rule (rows 1, 2)
      'TC'                — apply TC time multi-school rule (rows 2-fallthrough, 4)
      'COMMUNE_FALLBACK'  — THCS only / so_cap / completed_thpt+none (rows 3, 5, 6)
      'COMMUNE_SPECIAL'   — 4 special cases bypass (row 8)
      'MANUAL'            — admin override (row 9)
      'NOT_RESOLVED'      — cultural chưa khai (row 7, draft)

    See `Documents/Q9_07_PR5_REDESIGN.md` v1.3 Section "KV resolution basis
    derivation matrix" cho 9 rows complete spec.
    """
    # Row 8/9: area_resolution_basis overrides matrix
    if area_resolution_basis == "permanent_address_special":
        return "COMMUNE_SPECIAL"
    if area_resolution_basis == "manual_override":
        return "MANUAL"

    # Row 7: cultural not set (draft state)
    if cultural is None:
        return "NOT_RESOLVED"

    # Rows 1, 2 (partial), 3: THPT-related cultural levels
    if cultural in ("graduated_thpt", "graduated_gdtx", "completed_thpt"):
        # Row 3 (completed_thpt + so_cap/none) → COMMUNE_FALLBACK
        if cultural == "completed_thpt" and vocational in ("so_cap", "none"):
            return "COMMUNE_FALLBACK"
        return "THPT"  # Rows 1 + 2

    # Rows 4, 5: graduated_thcs + vocational branching
    if cultural == "graduated_thcs":
        if vocational in ("trung_cap", "cao_dang"):
            return "TC"  # Row 4
        return "COMMUNE_FALLBACK"  # Row 5

    # Row 6: completed_thcs (any vocational) → fallback
    if cultural == "completed_thcs":
        return "COMMUNE_FALLBACK"

    # Defensive: unknown cultural (shouldn't happen due to CHECK enum)
    return "NOT_RESOLVED"


async def _lookup_commune_kv(
    db: "AsyncSession", commune_code: str
) -> Optional[str]:
    """Lookup active KV for a commune_code from vn_commune_area_map.

    Active row = effective_to IS NULL. Returns None if commune not in table
    (graceful — Phase B.2 may not have full coverage yet).
    """
    from app.models.vn_locality import VnCommuneAreaMap

    stmt = (
        select(VnCommuneAreaMap.area_code)
        .where(
            VnCommuneAreaMap.commune_code == commune_code,
            VnCommuneAreaMap.effective_to.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def lookup_kv_for_school_year(
    db: "AsyncSession", school_id: int, year: int
) -> Optional[str]:
    """Lookup KV for a school at a given academic year (temporal).

    Query pattern (per VnSchoolKvAssignment docstring):
        SELECT kv_code FROM vn_school_kv_assignment
        WHERE school_id = :sid
          AND :year BETWEEN effective_from_year
                       AND COALESCE(effective_to_year, 9999);
    """
    from app.models.vn_school import VnSchoolKvAssignment

    stmt = (
        select(VnSchoolKvAssignment.kv_code)
        .where(
            VnSchoolKvAssignment.school_id == school_id,
            VnSchoolKvAssignment.effective_from_year <= year,
            (VnSchoolKvAssignment.effective_to_year.is_(None))
            | (VnSchoolKvAssignment.effective_to_year >= year),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def resolve_kv_for_profile(
    profile: "AdmissionProfile",
    db: "AsyncSession",
) -> tuple[Optional[str], dict[str, Any]]:
    """Resolve KV for a profile per TT 05/2021 Phụ lục 01 multi-school rule.

    Returns ``(kv_code, meta_dict)`` where ``meta_dict`` matches the shape
    of ``priority_resolution_snapshot`` (without freeze metadata):

        {
            'rule_applied': str,   # longest_duration | tiebreak_graduation_school
                                   # | commune_lookup | manual_override
                                   # | ambiguous_requires_manual
            'pathway': str,        # thpt_multi_school | tc_multi_school
                                   # | commune_fallback | commune_special
                                   # | manual | not_resolved
            'breakdown': {...} | None,
            'requires_manual_override': bool (optional),
            'reason': str (optional)
        }

    NULL kv_code → engine ignores (legacy fallback 0đ).

    See `Documents/Q9_07_PR5_REDESIGN.md` v1.3 Section "Resolution algorithm".
    """
    cultural = getattr(profile, "cultural_education_level", None)
    vocational = getattr(profile, "vocational_qualification", "none") or "none"
    area_basis = getattr(profile, "area_resolution_basis", None)

    basis = _derive_kv_basis_level(cultural, vocational, area_basis)

    # --- Row 8: 4 special cases bypass (PT DTNT / dự bị / quân nhân / xuất ngũ) ---
    if basis == "COMMUNE_SPECIAL":
        commune_code = getattr(profile, "permanent_commune_code", None)
        if commune_code:
            kv = await _lookup_commune_kv(db, commune_code)
            return kv, {
                "rule_applied": "commune_lookup",
                "pathway": "commune_special",
                "breakdown": {"commune_code_used": commune_code},
            }
        return None, {
            "rule_applied": "ambiguous_requires_manual",
            "pathway": "commune_special",
            "requires_manual_override": True,
            "reason": "special_case_no_commune",
        }

    # --- Row 9: admin/officer manual override ---
    if basis == "MANUAL":
        # Caller should have set kv_resolved in snapshot before calling;
        # treat as no-op here (returns NULL → snapshot keeps existing).
        return None, {
            "rule_applied": "manual_override",
            "pathway": "manual",
            "requires_manual_override": False,
            "reason": "admin_set_kv_directly",
        }

    # --- Row 7: cultural not set (draft) ---
    if basis == "NOT_RESOLVED":
        return None, {
            "rule_applied": "ambiguous_requires_manual",
            "pathway": "not_resolved",
            "requires_manual_override": False,
            "reason": "cultural_not_set",
        }

    # --- Rows 3, 5, 6: commune fallback (THCS only / so_cap / completed_thpt+none) ---
    if basis == "COMMUNE_FALLBACK":
        commune_code = getattr(profile, "permanent_commune_code", None)
        if commune_code:
            kv = await _lookup_commune_kv(db, commune_code)
            return kv, {
                "rule_applied": "commune_lookup",
                "pathway": "commune_fallback",
                "breakdown": {"commune_code_used": commune_code},
            }
        return None, {
            "rule_applied": "ambiguous_requires_manual",
            "pathway": "commune_fallback",
            "requires_manual_override": True,
            "reason": "fallback_no_commune",
        }

    # --- Rows 1, 2, 4: multi-school rule (THPT or TC) ---
    history = getattr(profile, "academic_history", None) or []
    basis_entries = [
        e for e in history
        if isinstance(e, dict)
        and e.get("level") == basis
        and e.get("school_id")
    ]

    pathway = "thpt_multi_school" if basis == "THPT" else "tc_multi_school"

    if not basis_entries:
        return None, {
            "rule_applied": "ambiguous_requires_manual",
            "pathway": pathway,
            "requires_manual_override": True,
            "reason": "no_qualifying_entries",
            "breakdown": {"target_level": basis, "entries": []},
        }

    # Per-year KV duration map + breakdown per entry
    kv_years: dict[str, int] = {}
    breakdown_entries: list[dict[str, Any]] = []

    for entry in basis_entries:
        sid = entry["school_id"]
        y_from = entry.get("year_from")
        y_to = entry.get("year_to")
        if y_from is None or y_to is None or y_to < y_from:
            continue

        entry_years_by_kv: list[dict[str, Any]] = []
        for year in range(y_from, y_to + 1):
            kv = await lookup_kv_for_school_year(db, sid, year)
            if kv:
                kv_years[kv] = kv_years.get(kv, 0) + 1
                entry_years_by_kv.append({"year": year, "kv": kv})

        breakdown_entries.append({
            "school_id": sid,
            "school_name_at_time": entry.get("school_name"),
            "year_from": y_from,
            "year_to": y_to,
            "years_by_kv": entry_years_by_kv,
        })

    if not kv_years:
        return None, {
            "rule_applied": "ambiguous_requires_manual",
            "pathway": pathway,
            "requires_manual_override": True,
            "reason": "no_kv_lookup_succeeded",
            "breakdown": {
                "target_level": basis,
                "entries": breakdown_entries,
                "kv_totals": {},
            },
        }

    max_yrs = max(kv_years.values())
    winners = [kv for kv, y in kv_years.items() if y == max_yrs]

    breakdown_base = {
        "target_level": basis,
        "entries": breakdown_entries,
        "kv_totals": kv_years,
        "winner_years": max_yrs,
    }

    if len(winners) == 1:
        return winners[0], {
            "rule_applied": "longest_duration",
            "pathway": pathway,
            "breakdown": breakdown_base,
        }

    # Tiebreak: graduation school (highest year_to + grade_to, stable index).
    # M1: detect ambiguous (2+ entries cùng year_to + grade_to) → require manual.
    sorted_entries = sorted(
        enumerate(basis_entries),
        key=lambda pair: (
            pair[1].get("year_to", 0),
            pair[1].get("grade_to", 0),
            -pair[0],  # stable: prefer earlier index when ties
        ),
        reverse=True,
    )
    if len(sorted_entries) >= 2:
        top_entry = sorted_entries[0][1]
        second_entry = sorted_entries[1][1]
        if (
            top_entry.get("year_to") == second_entry.get("year_to")
            and top_entry.get("grade_to") == second_entry.get("grade_to")
        ):
            return None, {
                "rule_applied": "ambiguous_requires_manual",
                "pathway": pathway,
                "requires_manual_override": True,
                "reason": "tied_graduation_year_and_grade",
                "breakdown": {
                    **breakdown_base,
                    "tied_kv": winners,
                    "tied_entries": [
                        top_entry["school_id"],
                        second_entry["school_id"],
                    ],
                },
            }

    grad_entry = sorted_entries[0][1]
    grad_kv = await lookup_kv_for_school_year(
        db, grad_entry["school_id"], grad_entry["year_to"]
    )
    return grad_kv, {
        "rule_applied": "tiebreak_graduation_school",
        "pathway": pathway,
        "breakdown": {
            **breakdown_base,
            "tied_kv": winners,
            "graduation_school_id": grad_entry["school_id"],
            "graduation_year": grad_entry["year_to"],
        },
    }


async def freeze_priority_snapshot(
    profile: "AdmissionProfile",
    db: "AsyncSession",
    frozen_at_status: str,
    resolved_by: str = "system",
    manual_override_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Compute KV resolution + freeze into ``profile.priority_resolution_snapshot``.

    Called from:
      - submit_admission_profile (T1) → frozen_at_status='submitted_T1'
      - evaluate_cascade (T6) → frozen_at_status='engine_T6'

    Mutates ``profile.priority_resolution_snapshot`` directly. Caller is
    responsible for ``await db.flush()`` (no commit — service layer rule).

    ``frozen_at_status`` MUST be one of:
      'draft_preview' | 'submitted_T1' | 'engine_T6'

    Returns the snapshot dict (also written to profile column).
    """
    kv_resolved, meta = await resolve_kv_for_profile(profile, db)
    snapshot: dict[str, Any] = {
        "kv_resolved": kv_resolved,
        "rule_applied": meta.get("rule_applied"),
        "pathway": meta.get("pathway"),
        "breakdown": meta.get("breakdown"),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_at_status": frozen_at_status,
        "resolved_by": resolved_by,
    }
    if manual_override_reason:
        snapshot["manual_override_reason"] = manual_override_reason
    if meta.get("requires_manual_override"):
        snapshot["requires_manual_override"] = True
    if meta.get("reason"):
        snapshot["reason"] = meta["reason"]

    profile.priority_resolution_snapshot = snapshot
    return snapshot


def validate_eligibility(
    profile: "AdmissionProfile",
    target_level: str,
) -> tuple[bool, Optional[str]]:
    """Validate candidate eligibility for target program level.

    Per TT 05/2021 Phụ lục 01 + Luật GDNN 2014/2025:
      - target_level='CD' (Cao đẳng): requires graduated_thpt OR graduated_gdtx
        OR (completed_thpt + trung_cap) — path 2 cho liên thông
      - target_level='TC' (Trung cấp): requires graduated_thcs trở lên
      - target_level='SC' (Sơ cấp): no academic requirement

    Returns ``(is_eligible, reason_if_not)``.
    """
    cultural = getattr(profile, "cultural_education_level", None)
    vocational = getattr(profile, "vocational_qualification", "none") or "none"

    if target_level in ("CD", "cao_dang"):
        # Path 1: tốt nghiệp THPT/GDTX direct
        if cultural in ("graduated_thpt", "graduated_gdtx"):
            return True, None
        # Path 2: liên thông — đủ kiến thức THPT + bằng TC nghề
        if cultural == "completed_thpt" and vocational == "trung_cap":
            return True, None
        # Path 2 extended: graduated_thcs + cao_dang already done → re-enroll OK
        if cultural == "graduated_thcs" and vocational == "cao_dang":
            return True, None
        return False, "cd_requires_thpt_or_thpt_kien_thuc_plus_trung_cap"

    if target_level in ("TC", "trung_cap"):
        # Per Luật GDNN: TC yêu cầu tốt nghiệp THCS trở lên
        if cultural in (
            "graduated_thcs",
            "completed_thpt",
            "graduated_thpt",
            "graduated_gdtx",
        ):
            return True, None
        return False, "tc_requires_graduated_thcs_or_higher"

    if target_level in ("SC", "so_cap"):
        return True, None  # SC không yêu cầu trình độ văn hóa

    # Unknown target_level — defensive pass-through (caller validates)
    return True, None
