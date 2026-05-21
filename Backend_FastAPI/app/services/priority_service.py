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


def _has_thpt_history(academic_history: Optional[list]) -> bool:
    """True khi profile có ít nhất 1 academic_history entry mức THPT/GDTX hợp lệ.

    "Hợp lệ" = level ∈ {THPT, THCS_THPT, GDTX} + school_id + year_from/year_to
    không null. Dùng cho hybrid rule CĐ liên thông KHOI_LUONG_VH_THPT + TC
    (yêu cầu nghiệp vụ #6): có history → LICH_SU_THPT; không có → THUONG_TRU.
    """
    if not academic_history:
        return False
    return any(
        isinstance(e, dict)
        and e.get("level") in {"THPT", "THCS_THPT", "GDTX"}
        and e.get("school_id")
        and e.get("year_from") is not None
        and e.get("year_to") is not None
        for e in academic_history
    )


def _derive_kv_basis_level(
    cultural: Optional[str],
    vocational: str,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
    academic_history: Optional[list] = None,
    area_resolution_basis: Optional[str] = None,
) -> tuple[str, str]:
    """Map profile context → KV resolution basis + reason code.

    Phase E.4 (commit 5) refactor — signature mở rộng target_level +
    admission_type + academic_history để khớp matrix nghiệp vụ #6:

      - TC sau THCS (target=trung_cap chính quy, cultural=graduated_thcs) → THUONG_TRU
      - TC sau THPT/hoàn thành THPT → LICH_SU_THPT
      - CĐ chính quy sau THPT/hoàn thành THPT → LICH_SU_THPT
      - CĐ chính quy hoàn thành THPT + TC → LICH_SU_THPT (extended TT path)
      - TC liên thông từ SC/TC sau THCS → THUONG_TRU
      - TC liên thông có THPT/hoàn thành THPT → LICH_SU_THPT
      - CĐ liên thông từ TC/CĐ có TN_THPT → LICH_SU_THPT
      - CĐ liên thông KHOI_LUONG_VH_THPT + TC (completed_thpt + trung_cap/cao_dang):
          có history THPT/GDTX hợp lệ → LICH_SU_THPT
          không có history → THUONG_TRU
          thiếu cả history lẫn commune → INSUFFICIENT_DATA (resolve step xử lý)

    Returns ``(basis, basis_reason)``:
      basis ∈ {
        'LICH_SU_THPT'           — multi-school rule TT 05/2021 Mục 5.b
        'THUONG_TRU'             — vn_commune_area_map lookup
        'COMMUNE_SPECIAL'        — exception override (PT DTNT / ĐBKK 18+ tháng)
        'MANUAL'                 — admin/manager override KV trực tiếp
        'INSUFFICIENT_DATA'      — thiếu cultural/target/cấu hình quan trọng
        'MANUAL_REVIEW_REQUIRED' — multi-school tied graduation
        'NOT_RESOLVED'           — draft, cultural chưa khai
      }
      basis_reason — short snake_case key cho audit / FE display.

    Backward compat: target_level/admission_type/academic_history mặc định None;
    callers cũ chỉ truyền cultural + vocational + area_basis sẽ fall vào
    "LEGACY" path (replicate hành vi commit 4) — KHÔNG break test cũ NGAY,
    sẽ phase out khi resolve_kv_for_profile fully threaded.
    """
    # 1. Override paths — output bypass, áp trên mọi context.
    if area_resolution_basis == "permanent_address_special":
        return "COMMUNE_SPECIAL", "permanent_address_special_override"
    if area_resolution_basis == "manual_override":
        return "MANUAL", "admin_set_kv_directly"

    # 2. SC chính quy carve-out (yêu cầu nghiệp vụ #5+#6): SC không yêu cầu
    # văn hóa → cultural=None vẫn pass eligibility. KV resolve qua THUONG_TRU
    # (commune lookup). Phải check TRƯỚC "cultural is None" early-return để
    # không kẹt vào NOT_RESOLVED sai.
    if target_level == "so_cap" and cultural is None:
        return "THUONG_TRU", "sc_no_cultural_uses_commune"

    # 3. Draft state — cultural chưa khai (mọi target_level khác SC đều block).
    if cultural is None:
        return "NOT_RESOLVED", "cultural_not_set"

    voc = vocational or "none"

    # 3. Backward-compat legacy branch (target_level chưa truyền — caller cũ).
    #    Replicate matrix commit 4 để test legacy không break.
    if target_level is None:
        # Hồ sơ THPT-related → LICH_SU_THPT (trừ completed_thpt + so_cap/none → THUONG_TRU)
        if cultural in ("graduated_thpt", "graduated_gdtx", "completed_thpt"):
            if cultural == "completed_thpt" and voc in ("so_cap", "none"):
                return "THUONG_TRU", "legacy_completed_thpt_no_vocational"
            return "LICH_SU_THPT", "legacy_thpt_pathway"
        if cultural in ("graduated_thcs", "completed_thcs"):
            return "THUONG_TRU", "legacy_thcs_pathway_uses_commune"
        return "NOT_RESOLVED", "legacy_unknown_cultural"

    # 4. Phase E.4 matrix — target_level + admission_type drive basis.
    atype = admission_type or "chinh_quy"

    # 4a. Hybrid CĐ liên thông + completed_thpt + TC/CĐ (KHOI_LUONG_VH_THPT).
    # Per nghiệp vụ #6: có lịch sử THPT/GDTX hợp lệ → LICH_SU_THPT; không có
    # → THUONG_TRU; cả 2 thiếu → INSUFFICIENT_DATA (resolve step downgrade).
    if (
        target_level == "cao_dang"
        and atype == "lien_thong"
        and cultural == "completed_thpt"
        and voc in ("trung_cap", "cao_dang")
    ):
        if _has_thpt_history(academic_history):
            return "LICH_SU_THPT", "cd_lien_thong_khoi_luong_with_thpt_history"
        return "THUONG_TRU", "cd_lien_thong_khoi_luong_no_thpt_history_fallback"

    # 4b. CĐ (chính quy hoặc liên thông) với cultural graduated_thpt/gdtx/completed_thpt
    # → LICH_SU_THPT. Matrix nghiệp vụ #6:
    #   - CĐ chính quy sau THPT/hoàn thành THPT → LICH_SU_THPT
    #   - CĐ chính quy diện hoàn thành THPT + TC → LICH_SU_THPT
    #   - CĐ liên thông từ TC/CĐ có THPT → LICH_SU_THPT
    if target_level == "cao_dang":
        if cultural in ("graduated_thpt", "graduated_gdtx"):
            return "LICH_SU_THPT", f"cd_{atype}_post_thpt_uses_school_history"
        if cultural == "completed_thpt":
            # CĐ chính quy + hoàn thành THPT đủ kiến thức → LICH_SU_THPT (nghiệp vụ #5)
            return "LICH_SU_THPT", f"cd_{atype}_completed_thpt_uses_school_history"
        # Eligibility gate đã chặn graduated_thcs/completed_thcs cho CĐ chính quy.
        # Defensive: nếu reach here → cấu hình mismatch upstream.
        return "INSUFFICIENT_DATA", f"cd_{atype}_cultural_insufficient_for_kv_basis"

    # 4c. TC matrix.
    if target_level == "trung_cap":
        if atype == "lien_thong":
            # TC liên thông từ SC/TC sau THCS → THUONG_TRU
            if cultural == "graduated_thcs" and voc in ("so_cap", "trung_cap"):
                return "THUONG_TRU", "tc_lien_thong_post_thcs_with_voc_uses_commune"
            # TC liên thông có THPT/hoàn thành THPT → LICH_SU_THPT
            if cultural in ("completed_thpt", "graduated_thpt", "graduated_gdtx"):
                return "LICH_SU_THPT", "tc_lien_thong_post_thpt_uses_school_history"
            return "INSUFFICIENT_DATA", "tc_lien_thong_cultural_insufficient_for_kv_basis"
        # TC chính quy:
        # - TN_THCS → THUONG_TRU
        # - completed/graduated THPT/GDTX → LICH_SU_THPT
        if cultural == "graduated_thcs":
            return "THUONG_TRU", "tc_chinh_quy_post_thcs_uses_commune"
        if cultural in ("completed_thpt", "graduated_thpt", "graduated_gdtx"):
            return "LICH_SU_THPT", "tc_chinh_quy_post_thpt_uses_school_history"
        return "INSUFFICIENT_DATA", "tc_chinh_quy_cultural_insufficient_for_kv_basis"

    # 4d. SC chính quy — không yêu cầu cultural; default THUONG_TRU.
    # Engine sẽ check commune ở resolve step (ADDRESS_NOT_NORMALIZED nếu miss).
    if target_level == "so_cap":
        return "THUONG_TRU", "sc_uses_commune"

    # 5. Defensive: target_level ngoài CD/TC/SC scope (eligibility gate đã chặn).
    return "INSUFFICIENT_DATA", f"unsupported_target_level:{target_level}"


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
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> tuple[Optional[str], dict[str, Any]]:
    """Resolve KV cho profile per TT 05/2021 Phụ lục 01.

    Phase E.4 (commit 5) refactor — pipeline:
       Eligibility (upstream gate) → Exception → Auto basis → Resolve KV
       → Apply path bonus (caller) → Snapshot (freeze).

    Fail-closed: tuyệt đối KHÔNG silent 0đ. Khi catalog/data thiếu, trả
    rule_applied đặc tả lỗi:
      - "catalog_gap_school"      — vn_school_kv_assignment thiếu row
      - "catalog_gap_commune"     — vn_commune_area_map thiếu commune_code
      - "address_not_normalized"  — profile thiếu permanent_commune_code
      - "ambiguous_requires_manual" — tied graduation
      - "not_resolved"            — cultural NULL (draft)
      - "insufficient_data"       — combo input không match matrix nào

    Args:
      profile: AdmissionProfile với cultural_education_level + vocational_qualification
               + permanent_commune_code + academic_history + area_resolution_basis.
      db: AsyncSession.
      target_level: 'cao_dang' / 'trung_cap' / 'so_cap' từ path/config chain.
                    Optional cho backward-compat (callers cũ); None → legacy
                    matrix (cảnh báo: matrix giảm độ chính xác).
      admission_type: 'chinh_quy' / 'lien_thong' / ... từ config_offering_type.
                      Optional. Default 'chinh_quy' khi target_level đã set.

    Returns ``(kv_code, meta_dict)``:
       kv_code: 'KV1' / 'KV2' / 'KV2-NT' / 'KV3' hoặc None khi unresolved.
       meta_dict (matches priority_resolution_snapshot subset):
         {
             'rule_applied': str,
             'pathway': str,            # legacy alias cho FE display
             'basis': str,              # LICH_SU_THPT / THUONG_TRU / ...
             'basis_reason': str,       # short reason code
             'breakdown': {...} | None,
             'requires_manual_override': bool (optional),
             'reason': str (optional)
         }
    """
    cultural = getattr(profile, "cultural_education_level", None)
    vocational = getattr(profile, "vocational_qualification", "none") or "none"
    area_basis = getattr(profile, "area_resolution_basis", None)
    academic_history = getattr(profile, "academic_history", None) or []

    basis, basis_reason = _derive_kv_basis_level(
        cultural=cultural,
        vocational=vocational,
        target_level=target_level,
        admission_type=admission_type,
        academic_history=academic_history,
        area_resolution_basis=area_basis,
    )

    # Common meta scaffold — basis + basis_reason luôn included.
    def _meta_base(**extra) -> dict[str, Any]:
        base = {"basis": basis, "basis_reason": basis_reason}
        base.update(extra)
        return base

    # --- COMMUNE_SPECIAL: exception bypass (PT DTNT / ĐBKK 18+ tháng). ---
    # Hôm nay chỉ wire 2 case (yêu cầu nghiệp vụ #11), 4 case full defer Phase F.
    if basis == "COMMUNE_SPECIAL":
        commune_code = getattr(profile, "permanent_commune_code", None)
        if not commune_code:
            return None, _meta_base(
                rule_applied="address_not_normalized",
                pathway="commune_special",
                requires_manual_override=True,
                reason="special_case_no_commune_code",
            )
        kv = await _lookup_commune_kv(db, commune_code)
        if kv is None:
            return None, _meta_base(
                rule_applied="catalog_gap_commune",
                pathway="commune_special",
                requires_manual_override=True,
                reason="commune_code_not_in_catalog",
                breakdown={"commune_code_attempted": commune_code},
            )
        return kv, _meta_base(
            rule_applied="commune_lookup",
            pathway="commune_special",
            breakdown={"commune_code_used": commune_code},
        )

    # --- MANUAL: admin/manager override KV trực tiếp ---
    if basis == "MANUAL":
        # Caller phải đã set kv_resolved trong snapshot trước khi gọi engine;
        # engine trả None để báo "không tự resolve, dùng existing kv_resolved".
        return None, _meta_base(
            rule_applied="manual_override",
            pathway="manual",
            requires_manual_override=False,
            reason="admin_set_kv_directly",
        )

    # --- NOT_RESOLVED: cultural chưa khai (draft). ---
    if basis == "NOT_RESOLVED":
        return None, _meta_base(
            rule_applied="not_resolved",
            pathway="not_resolved",
            requires_manual_override=False,
            reason="cultural_not_set",
        )

    # --- INSUFFICIENT_DATA: combo không match matrix nào (eligibility gate đã chặn upstream). ---
    if basis == "INSUFFICIENT_DATA":
        return None, _meta_base(
            rule_applied="insufficient_data",
            pathway="insufficient_data",
            requires_manual_override=True,
            reason=basis_reason,
        )

    # --- THUONG_TRU: vn_commune_area_map lookup theo permanent_commune_code. ---
    if basis == "THUONG_TRU":
        commune_code = getattr(profile, "permanent_commune_code", None)
        if not commune_code:
            return None, _meta_base(
                rule_applied="address_not_normalized",
                pathway="thuong_tru",
                requires_manual_override=True,
                reason="profile_missing_permanent_commune_code",
            )
        kv = await _lookup_commune_kv(db, commune_code)
        if kv is None:
            return None, _meta_base(
                rule_applied="catalog_gap_commune",
                pathway="thuong_tru",
                requires_manual_override=True,
                reason="commune_code_not_in_catalog",
                breakdown={"commune_code_attempted": commune_code},
            )
        return kv, _meta_base(
            rule_applied="commune_lookup",
            pathway="thuong_tru",
            breakdown={"commune_code_used": commune_code},
        )

    # --- LICH_SU_THPT: multi-school rule TT 05/2021 Phụ lục 01 Mục 5.b. ---
    # Aggregate duration per KV qua academic_history, longest duration wins,
    # tie → graduation school (year_to + grade_to).
    accepted_levels = {"THPT", "THCS_THPT", "GDTX"}

    basis_entries = [
        e for e in academic_history
        if isinstance(e, dict)
        and e.get("level") in accepted_levels
        and e.get("school_id")
    ]

    pathway = "lich_su_thpt"

    if not basis_entries:
        return None, _meta_base(
            rule_applied="insufficient_data",
            pathway=pathway,
            requires_manual_override=True,
            reason="no_qualifying_thpt_history_entries",
            breakdown={"entries": []},
        )

    # Per-year KV duration map + breakdown per entry. Track lookup failures
    # explicit để fail-closed (catalog_gap_school).
    kv_years: dict[str, int] = {}
    breakdown_entries: list[dict[str, Any]] = []
    missing_lookups: list[dict[str, Any]] = []

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
            else:
                missing_lookups.append({"school_id": sid, "year": year})

        breakdown_entries.append({
            "school_id": sid,
            "school_name_at_time": entry.get("school_name"),
            "year_from": y_from,
            "year_to": y_to,
            "years_by_kv": entry_years_by_kv,
        })

    if not kv_years:
        # Tất cả lookup miss → vn_school_kv_assignment thiếu catalog cho 100%
        # entries. Fail-closed: trả catalog_gap_school + KV=None.
        return None, _meta_base(
            rule_applied="catalog_gap_school",
            pathway=pathway,
            requires_manual_override=True,
            reason="all_school_lookups_failed",
            breakdown={
                "entries": breakdown_entries,
                "kv_totals": {},
                "missing_lookups": missing_lookups,
            },
        )

    max_yrs = max(kv_years.values())
    winners = [kv for kv, y in kv_years.items() if y == max_yrs]

    breakdown_base = {
        "entries": breakdown_entries,
        "kv_totals": kv_years,
        "winner_years": max_yrs,
    }
    if missing_lookups:
        # Partial catalog gap — engine vẫn resolve theo entries có data,
        # nhưng audit ghi lại để admin biết catalog cần seed.
        breakdown_base["partial_catalog_missing"] = missing_lookups

    if len(winners) == 1:
        return winners[0], _meta_base(
            rule_applied="longest_duration",
            pathway=pathway,
            breakdown=breakdown_base,
        )

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
            return None, _meta_base(
                rule_applied="ambiguous_requires_manual",
                pathway=pathway,
                requires_manual_override=True,
                reason="tied_graduation_year_and_grade",
                breakdown={
                    **breakdown_base,
                    "tied_kv": winners,
                    "tied_entries": [
                        top_entry["school_id"],
                        second_entry["school_id"],
                    ],
                },
            )

    grad_entry = sorted_entries[0][1]
    grad_kv = await lookup_kv_for_school_year(
        db, grad_entry["school_id"], grad_entry["year_to"]
    )
    if grad_kv is None:
        # Graduation school year miss catalog → fail-closed.
        return None, _meta_base(
            rule_applied="catalog_gap_school",
            pathway=pathway,
            requires_manual_override=True,
            reason="graduation_school_lookup_failed",
            breakdown={
                **breakdown_base,
                "tied_kv": winners,
                "graduation_school_id": grad_entry["school_id"],
                "graduation_year": grad_entry["year_to"],
            },
        )
    return grad_kv, _meta_base(
        rule_applied="tiebreak_graduation_school",
        pathway=pathway,
        breakdown={
            **breakdown_base,
            "tied_kv": winners,
            "graduation_school_id": grad_entry["school_id"],
            "graduation_year": grad_entry["year_to"],
        },
    )


async def freeze_priority_snapshot(
    profile: "AdmissionProfile",
    db: "AsyncSession",
    frozen_at_status: str,
    resolved_by: str = "system",
    manual_override_reason: Optional[str] = None,
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
    eligibility: Optional[dict] = None,
    path_bonus_rule: Optional[dict] = None,
) -> dict[str, Any]:
    """Compute KV resolution + freeze into ``profile.priority_resolution_snapshot``.

    Called from:
      - submit_admission_profile (T1) → frozen_at_status='submitted_T1'
      - evaluate_cascade (T6) → frozen_at_status='engine_T6'

    Mutates ``profile.priority_resolution_snapshot`` directly. Caller is
    responsible for ``await db.flush()`` (no commit — service layer rule).

    ``frozen_at_status`` MUST be one of:
      'draft_preview' | 'submitted_T1' | 'engine_T6'

    Phase E.4 (commit 5) additive fields (optional — backward-compat):
      target_level, admission_type, eligibility, basis, basis_reason,
      rule_law_citation, path_bonus_rule.

    Returns the snapshot dict (also written to profile column).
    """
    kv_resolved, meta = await resolve_kv_for_profile(
        profile,
        db,
        target_level=target_level,
        admission_type=admission_type,
    )
    rule_applied = meta.get("rule_applied")
    snapshot: dict[str, Any] = {
        "kv_resolved": kv_resolved,
        "rule_applied": rule_applied,
        "pathway": meta.get("pathway"),
        "basis": meta.get("basis"),
        "basis_reason": meta.get("basis_reason"),
        "breakdown": meta.get("breakdown"),
        "rule_law_citation": resolve_law_citation(rule_applied),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_at_status": frozen_at_status,
        "resolved_by": resolved_by,
    }
    # Phase E.4 additive snapshot context — KHÔNG bắt buộc; callers chưa
    # eager-load path chain sẽ ship null, FE/audit log degrade gracefully.
    if target_level is not None:
        snapshot["target_level"] = target_level
    if admission_type is not None:
        snapshot["admission_type"] = admission_type
    if eligibility is not None:
        snapshot["eligibility"] = eligibility
    if path_bonus_rule is not None:
        snapshot["path_bonus_rule"] = path_bonus_rule
    if manual_override_reason:
        snapshot["manual_override_reason"] = manual_override_reason
    if meta.get("requires_manual_override"):
        snapshot["requires_manual_override"] = True
    if meta.get("reason"):
        snapshot["reason"] = meta["reason"]

    profile.priority_resolution_snapshot = snapshot
    return snapshot


def derive_target_level_and_type(path: "AdmissionPath") -> tuple[str, str]:
    """Derive (target_level, admission_type) từ AdmissionPath chain.

    Chain: AdmissionPath → OfferingAcademicInfo → ProgramOffering →
    MajorProgram.degree_level_id + ProgramOffering.offering_type_id (FK
    config_degree_level + config_offering_type).

    Returns:
        (target_level, admission_type) — cả 2 là `code` từ config table.
        target_level ∈ {"cao_dang", "trung_cap", "so_cap"} (Phase E.4
        scope GDNN; "dai_hoc"/"thac_si"/"tien_si" out-of-scope).
        admission_type ∈ {"chinh_quy", "lien_thong", "vua_lam_vua_hoc",
        "tu_xa", "lien_ket_quoc_te"}.

    Raises:
        BusinessRuleViolation("CONFIG_GAP_TARGET_LEVEL") khi không derive
        được do:
          - relation chain chưa eager-load (academic_info/offering/program/
            degree_level/offering_type)
          - degree_level_id/offering_type_id NULL trên major_program/
            program_offering
          - code không nằm trong GDNN scope (vd dai_hoc)
        Per yêu cầu nghiệp vụ #5: tuyệt đối KHÔNG fallback "so_cap" — fail-closed.

    Caller MUST eager-load chain trước khi gọi:
        selectinload(AdmissionPath.academic_info)
          .selectinload(OfferingAcademicInfo.offering)
          .selectinload(ProgramOffering.program)
          .selectinload(MajorProgram.degree_level_obj)  # FK config_degree_level
        selectinload(AdmissionPath.academic_info)
          .selectinload(OfferingAcademicInfo.offering)
          .selectinload(ProgramOffering.offering_type_obj)  # FK config_offering_type
    """
    from ..utils.exceptions import BusinessRuleViolation

    _GDNN_TARGET_LEVELS = frozenset({"cao_dang", "trung_cap", "so_cap"})

    academic_info = path.__dict__.get("academic_info")
    if academic_info is None:
        raise BusinessRuleViolation(
            "CONFIG_GAP_TARGET_LEVEL: AdmissionPath thiếu academic_info "
            "(relation chưa eager-load hoặc DB không nhất quán)."
        )
    offering = academic_info.__dict__.get("offering")
    if offering is None:
        raise BusinessRuleViolation(
            "CONFIG_GAP_TARGET_LEVEL: OfferingAcademicInfo thiếu offering."
        )
    program = offering.__dict__.get("program")
    if program is None:
        raise BusinessRuleViolation(
            "CONFIG_GAP_TARGET_LEVEL: ProgramOffering thiếu program (MajorProgram)."
        )

    # degree_level — model relationship `MajorProgram.degree_level_ref` →
    # ConfigDegreeLevel(.code). Eager-load via selectinload(program.degree_level_ref).
    degree_level_obj = program.__dict__.get("degree_level_ref")
    target_code: Optional[str] = (
        getattr(degree_level_obj, "code", None) if degree_level_obj else None
    )
    if target_code is None:
        raise BusinessRuleViolation(
            "CONFIG_GAP_TARGET_LEVEL: MajorProgram chưa gán degree_level_id "
            "(config_degree_level FK NULL). Vui lòng cấu hình bậc đào tạo "
            "trước khi cho hồ sơ submit."
        )
    if target_code not in _GDNN_TARGET_LEVELS:
        raise BusinessRuleViolation(
            f"CONFIG_GAP_TARGET_LEVEL: bậc đào tạo '{target_code}' nằm ngoài "
            f"phạm vi GDNN ({sorted(_GDNN_TARGET_LEVELS)}). Phase E.4 chỉ "
            f"hỗ trợ CĐ/TC/SC."
        )

    # offering_type — model relationship `ProgramOffering.offering_type_config`
    # → ConfigOfferingType(.code). Eager-load via
    # selectinload(offering.offering_type_config).
    offering_type_obj = offering.__dict__.get("offering_type_config")
    admission_type: Optional[str] = (
        getattr(offering_type_obj, "code", None) if offering_type_obj else None
    )
    if admission_type is None:
        raise BusinessRuleViolation(
            "CONFIG_GAP_TARGET_LEVEL: ProgramOffering chưa gán offering_type_id "
            "(config_offering_type FK NULL). Vui lòng cấu hình hệ đào tạo "
            "(chính quy / liên thông / VLVH...) trước khi cho hồ sơ submit."
        )

    return target_code, admission_type


def validate_eligibility(
    profile: "AdmissionProfile",
    target_level: str,
    admission_type: str = "chinh_quy",
) -> tuple[bool, Optional[str]]:
    """Validate candidate eligibility for target program level + type.

    Per TT 05/2021 Phụ lục 01 + Luật GDNN 2014/2025 (chốt 2026-05-21):
      - CĐ chính quy:     TN_THPT hoặc HOAN_THANH_THPT
      - CĐ liên thông:    TN_THPT hoặc HOAN_THANH_THPT + bằng TC/CĐ
      - TC chính quy:     TN_THCS trở lên
      - TC liên thông:    TN_THCS trở lên + bằng SC/TC
      - SC chính quy:     không yêu cầu văn hóa

    Args:
        profile: AdmissionProfile với cultural_education_level + vocational_qualification.
        target_level: config_degree_level.code — "cao_dang" / "trung_cap" / "so_cap".
        admission_type: config_offering_type.code — "chinh_quy" / "lien_thong" /
            "vua_lam_vua_hoc" / "tu_xa" / "lien_ket_quoc_te". Default "chinh_quy"
            cho backward-compat với callers cũ.

    Returns:
        (is_eligible, reason_code_if_not).
        reason_code dùng làm i18n key cho FE error display.

    Per yêu cầu nghiệp vụ #5: unknown target_level → block (fail-closed).
    """
    cultural = getattr(profile, "cultural_education_level", None)
    vocational = getattr(profile, "vocational_qualification", "none") or "none"

    _THPT_GRADUATED = ("graduated_thpt", "graduated_gdtx")
    _THPT_KNOWLEDGE = ("completed_thpt", "graduated_thpt", "graduated_gdtx")
    _THCS_OR_HIGHER = (
        "graduated_thcs",
        "completed_thpt",
        "graduated_thpt",
        "graduated_gdtx",
    )

    if target_level in ("cao_dang", "CD"):
        if admission_type == "lien_thong":
            # CĐ liên thông: kiến thức THPT (đã TN hoặc hoàn thành) + bằng TC/CĐ
            if cultural in _THPT_KNOWLEDGE and vocational in ("trung_cap", "cao_dang"):
                return True, None
            return False, "cd_lien_thong_requires_thpt_knowledge_plus_tc_or_cd"
        # CĐ chính quy + các hệ khác: TN_THPT hoặc HOAN_THANH_THPT (per spec mới
        # 2026-05-21 — yêu cầu nghiệp vụ #5).
        if cultural in _THPT_KNOWLEDGE:
            return True, None
        return False, "cd_chinh_quy_requires_thpt_or_completed_thpt"

    if target_level in ("trung_cap", "TC"):
        if admission_type == "lien_thong":
            # TC liên thông: TN_THCS trở lên + bằng SC/TC
            if cultural in _THCS_OR_HIGHER and vocational in ("so_cap", "trung_cap"):
                return True, None
            return False, "tc_lien_thong_requires_thcs_plus_sc_or_tc"
        # TC chính quy: TN_THCS trở lên
        if cultural in _THCS_OR_HIGHER:
            return True, None
        return False, "tc_requires_graduated_thcs_or_higher"

    if target_level in ("so_cap", "SC"):
        # SC chính quy không yêu cầu văn hóa. Liên thông SC chưa định nghĩa
        # nghiệp vụ — fail-closed.
        if admission_type == "chinh_quy":
            return True, None
        return False, "sc_only_supports_chinh_quy_in_phase_e4"

    # Yêu cầu nghiệp vụ #5: target_level ngoài CD/TC/SC scope → block.
    return False, f"unsupported_target_level:{target_level}"


# Legacy uppercase aliases for callers còn dùng "CD"/"TC"/"SC" tag.
_LEGACY_TARGET_LEVEL_ALIAS = {
    "CD": "cao_dang",
    "TC": "trung_cap",
    "SC": "so_cap",
}


def normalize_target_level(level: str) -> str:
    """Map legacy "CD"/"TC"/"SC" → config code "cao_dang"/"trung_cap"/"so_cap"."""
    return _LEGACY_TARGET_LEVEL_ALIAS.get(level, level)


# =============================================================================
# Q9 #07 Phase E.4 — Law citation resolver for FE EngineResultCard
# =============================================================================

# Map rule_applied (returned by resolve_kv_for_profile) → citation pháp lý.
# FE EngineResultCard hiển thị "Căn cứ: <citation>" để officer scan/trust.
#
# Keys MUST match the rule_applied values emitted by resolve_kv_for_profile
# (longest_duration, tiebreak_graduation_school, commune_lookup,
# manual_override, ambiguous_requires_manual). New rule_applied values
# added in tương lai PHẢI có entry tương ứng tại đây — nếu không,
# resolve_law_citation() returns None silently.
RULE_LAW_CITATION: dict[str, Optional[str]] = {
    # Rows 1, 2: THPT multi-school, một KV winner by duration (3+ năm)
    "longest_duration": "TT 05/2021 Phụ lục 01 Mục 5.b",
    # Rows 1, 2: THPT multi-school, tied by duration → resolve by graduation school
    "tiebreak_graduation_school": "TT 05/2021 Phụ lục 01 Mục 5.a",
    # Rows 3, 5, 6 (fallback) + Row 8 (PT DTNT / dự bị / quân nhân / xuất ngũ)
    "commune_lookup": "TT 05/2021 Phụ lục 01 Mục 4",
    # Row 9: admin/officer ấn định KV thủ công
    "manual_override": "TT 05/2021 Phụ lục 01 Mục 6 (admin override)",
    # Phase E.4 commit 5 — fail-closed codes mới. Citation = None (engine
    # không quyết định được; admin xử lý qua override hoặc catalog seed).
    "ambiguous_requires_manual": None,
    "address_not_normalized": None,
    "catalog_gap_commune": None,
    "catalog_gap_school": None,
    "insufficient_data": None,
    "not_resolved": None,
}


async def derive_profile_target_context(
    profile: "AdmissionProfile",
    db: "AsyncSession",
) -> dict[str, Any]:
    """Derive context cho freeze_priority_snapshot từ profile chain.

    Returns dict với keys:
      - target_level: str | None
      - admission_type: str | None
      - path_bonus_rule: dict | None
      - eligibility: {"passed": bool, "reason": str | None} | None
      - source: 'multi_nv_first_choice' | 'legacy_offering_admission_config' | 'unknown'

    Multi-NV: lookup choice với display_order=1; derive từ admission_path chain.
    Legacy: lookup offering_admission_config_id; derive từ chain.

    Fail-safe: nếu chain missing/incomplete, return None cho từng field;
    snapshot vẫn freeze nhưng context fields = None (engine T6 re-freeze sẽ
    cố retry khi caller eager-load đầy đủ).

    Eligibility chỉ compute khi target_level + admission_type cả 2 đều có.
    """
    from sqlalchemy import select as _sel
    from sqlalchemy.orm import selectinload as _sel_in

    ctx: dict[str, Any] = {
        "target_level": None,
        "admission_type": None,
        "path_bonus_rule": None,
        "eligibility": None,
        "source": "unknown",
    }

    try:
        # Lazy import to avoid model circular dep at module load
        from app import models

        path = None
        method = None

        if profile.uses_choice_engine:
            # Multi-NV: NV1 (display_order=1) làm primary cho snapshot context.
            stmt = (
                _sel(models.AdmissionProfileChoice)
                .where(
                    models.AdmissionProfileChoice.admission_profile_id == profile.id,
                    models.AdmissionProfileChoice.display_order == 1,
                )
                .options(
                    _sel_in(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.admission_method),
                    _sel_in(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.academic_info)
                    .selectinload(models.OfferingAcademicInfo.offering)
                    .selectinload(models.ProgramOffering.program)
                    .selectinload(models.MajorProgram.degree_level_ref),
                    _sel_in(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.academic_info)
                    .selectinload(models.OfferingAcademicInfo.offering)
                    .selectinload(models.ProgramOffering.offering_type_config),
                )
                .limit(1)
            )
            choice = (await db.execute(stmt)).scalar_one_or_none()
            if choice is not None and choice.admission_path is not None:
                path = choice.admission_path
                method = path.__dict__.get("admission_method")
                ctx["source"] = "multi_nv_first_choice"
        elif profile.offering_admission_config_id is not None:
            # Legacy single-path: derive từ offering_admission_config chain.
            # KHÔNG có bonus_rule_override (chỉ AdmissionPath có) — bonus_rule
            # context sẽ là None cho legacy; engine fallback admission_method default.
            stmt = (
                _sel(models.OfferingAdmissionConfig)
                .where(models.OfferingAdmissionConfig.id == profile.offering_admission_config_id)
                .options(
                    _sel_in(models.OfferingAdmissionConfig.academic_info)
                    .selectinload(models.OfferingAcademicInfo.offering)
                    .selectinload(models.ProgramOffering.program)
                    .selectinload(models.MajorProgram.degree_level_ref),
                    _sel_in(models.OfferingAdmissionConfig.academic_info)
                    .selectinload(models.OfferingAcademicInfo.offering)
                    .selectinload(models.ProgramOffering.offering_type_config),
                )
            )
            config = (await db.execute(stmt)).scalar_one_or_none()
            if config is not None:
                class _PathShim:
                    pass
                shim = _PathShim()
                shim.__dict__["academic_info"] = config.academic_info
                shim.__dict__["admission_method"] = None  # no path → no method
                path = shim  # type: ignore[assignment]
                ctx["source"] = "legacy_offering_admission_config"

        if path is not None:
            try:
                target_level, admission_type = derive_target_level_and_type(path)
                ctx["target_level"] = target_level
                ctx["admission_type"] = admission_type
            except Exception:  # noqa: BLE001 — defensive: missing chain
                pass

            # path_bonus_rule snapshot: chain override → method.default.
            # Lazy import để tránh circular.
            try:
                from .admission_choice_engine_service import resolve_effective_bonus_rule
                if hasattr(path, "bonus_rule_override") or method is not None:
                    rule = resolve_effective_bonus_rule(path)  # type: ignore[arg-type]
                    if rule is not None:
                        ctx["path_bonus_rule"] = dict(rule)
            except Exception:  # noqa: BLE001
                pass

        # Eligibility check audit — chỉ compute khi cả 2 field có.
        if ctx["target_level"] and ctx["admission_type"]:
            ok, reason = validate_eligibility(
                profile, ctx["target_level"], ctx["admission_type"]
            )
            ctx["eligibility"] = {"passed": ok, "reason": reason}

    except Exception:  # noqa: BLE001 — defensive: never block freeze on context
        pass

    return ctx


def resolve_law_citation(rule_applied: Optional[str]) -> Optional[str]:
    """Resolve citation pháp lý cho rule_applied value.

    Args:
        rule_applied: Engine return value từ resolve_kv_for_profile() meta.
                      Acceptable: longest_duration | tiebreak_graduation_school
                      | commune_lookup | manual_override | ambiguous_requires_manual.

    Returns:
        Citation string (vd "TT 05/2021 Phụ lục 01 Mục 5.b") nếu rule_applied
        match RULE_LAW_CITATION map.
        None nếu rule_applied=None, hoặc rule_applied không nằm trong map
        (defensive — không crash khi engine emit rule_applied mới chưa có entry).

    Called by:
        - PreviewPriorityKvResponse builder trong /preview-priority-kv endpoint
          (priority_kv_preview router) — set response.rule_law_citation.
        - _populate_response_fields for frozen priority_resolution_snapshot —
          resolve citation cho snapshot.rule_applied (optional, defer post-launch).
    """
    if not rule_applied:
        return None
    return RULE_LAW_CITATION.get(rule_applied)
