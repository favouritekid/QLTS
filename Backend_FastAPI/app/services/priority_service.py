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

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Generator, Iterable, Mapping, NamedTuple, Optional, Sequence

import structlog
from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.admission import AdmissionProfile


log = structlog.get_logger(__name__)
_ZERO = Decimal("0.00")


def area_bonus_enabled(rule: Optional[dict[str, Any]]) -> bool:
    """Luật cộng điểm (kết quả ``resolve_effective_bonus_rule``) có cộng điểm KHU VỰC không —
    MỘT nguồn cho T6 (:func:`calculate_priority_bonus`) và văn bản Hội đồng (câu 22, owner
    06-11: "theo cấu hình đường xét"). ``None`` (đường xét không override, phương thức không có
    mặc định) ⇒ không cộng — đúng nhánh "bonus disabled" của T6."""
    if rule is None:
        return False
    return bool(rule.get("apply_area_bonus"))


def object_bonus_enabled(rule: Optional[dict[str, Any]]) -> bool:
    """Luật cộng điểm (kết quả ``resolve_effective_bonus_rule``) có cộng điểm ĐỐI TƯỢNG không —
    MỘT nguồn cho T6 (:func:`calculate_priority_bonus`) và văn bản Hội đồng (owner 06-11: công tắc
    của đường xét; cách suy đối tượng + trần của văn bản giữ luật v1). ``None`` ⇒ không cộng — đúng
    nhánh "bonus disabled" của T6."""
    if rule is None:
        return False
    return bool(rule.get("apply_object_bonus"))


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

    apply_area = area_bonus_enabled(rule)
    apply_object = object_bonus_enabled(rule)
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


# =============================================================================
# Một nguồn: năm tuyển sinh, hàng mức đang mở, vị từ "KV đã phân giải"
# =============================================================================
#
# Owner Q10(a): mức điểm chọn theo NĂM TUYỂN SINH của hồ sơ, hàng ĐANG MỞ (``effective_to IS NULL``), KHÔNG lọc
# ngày nào (cả ngày nộp lẫn ngày chạy). Thiếu hàng ⇒ dừng có nhãn, không 0 điểm. Mọi nơi tra mức (T6, xem trước,
# nhóm UT đã xác minh, danh mục) đi qua ``select_open_priority_rates``; không nơi nào tự so ``effective_from``.

#: Tên bảng trong ``PriorityRateNotConfigured.table`` — cũng là tên bảng thật.
RATE_TABLE_AREA = "priority_area_config"
RATE_TABLE_OBJECT = "priority_object_config"

#: ``rule_applied`` mà resolver phát ra khi phân giải KV THÀNH CÔNG. Whitelist: mã ngoài tập (kể cả mã tương lai,
#: ``manual_override_unverified``, ``catalog_gap_*``) là CHƯA phân giải. Cổng nộp (T1) và T6 dùng chung qua
#: ``kv_snapshot_resolved``.
KV_SUCCESS_RULE_APPLIED = frozenset({
    "longest_duration",
    "tiebreak_graduation_school",
    "commune_lookup",
    "manual_override",
})


def kv_snapshot_resolved(snapshot: Optional[dict]) -> bool:
    """KV đã phân giải ⇔ ``rule_applied`` thuộc whitelist VÀ ``kv_resolved`` có giá trị."""
    s = snapshot if isinstance(snapshot, dict) else {}
    return s.get("rule_applied") in KV_SUCCESS_RULE_APPLIED and s.get("kv_resolved") is not None


#: L3 (owner 22-11, ``logs-P5/cong-bo-ket-qua/gd2/l3/QUYET-DINH-OWNER-L3-5-CAU-2026-11-22.md`` +
#: ``…/QUYET-DINH-OWNER-L3-TRUONG-THCS-VAO-DANH-MUC-2026-11-22.md``): "KV chờ xác minh" — thí sinh trung cấp xét sau THCS chưa
#: tính được KV từ trường THCS trong danh mục, thí sinh sơ cấp, và nhánh cũ không truyền trình độ. NGOÀI whitelist ⇒ CHƯA phân
#: giải (T6 dừng có nhãn, không 0 điểm; bản in GĐ1 / máy xét GĐ2-B chặn ``khu_vuc_cho_xac_minh``); RIÊNG cổng nộp cho qua.
KV_PENDING_VERIFICATION_RULE = "kv_pending_verification"


def kv_snapshot_pending_verification(snapshot: Optional[dict]) -> bool:
    """Ảnh chụp mang "KV chờ xác minh" (L3) — MỘT vị từ cho cổng nộp, T6, bản in GĐ1 và máy xét GĐ2-B."""
    s = snapshot if isinstance(snapshot, dict) else {}
    return s.get("rule_applied") == KV_PENDING_VERIFICATION_RULE


def kv_pending_verification_kind(snapshot: Optional[dict]) -> Optional[str]:
    """Loại "KV chờ xác minh" cho câu dừng T6: ``"thcs_history"`` — trung cấp sau THCS, tính được khi trường THCS có trong danh mục;
    ``"manual"`` — chỉ xác minh tay (sơ cấp, nhánh cũ, trường PT DTNT); ``None`` — không phải chờ xác minh."""
    if not kv_snapshot_pending_verification(snapshot):
        return None
    if snapshot.get("pathway") == KV_PATHWAY_THCS_HISTORY and snapshot.get("reason") != KV_PENDING_REASON_THCS_DTNT:
        return "thcs_history"
    return "manual"


def kv_snapshot_blocks_submit(snapshot: Optional[dict]) -> bool:
    """Cổng nộp (T1): chặn khi KV chưa phân giải, TRỪ "KV chờ xác minh" (owner L3: "vẫn tiếp nhận bình thường"). Mọi mã khác
    ngoài whitelist vẫn chặn như cũ — vị từ riêng, không nới ``kv_snapshot_resolved`` (T6 / bản in vẫn coi là chưa phân giải)."""
    return not kv_snapshot_resolved(snapshot) and not kv_snapshot_pending_verification(snapshot)


def priority_academic_year(profile: Any) -> int:
    """Năm tuyển sinh của hồ sơ — nguồn năm DUY NHẤT để tra mức (owner Q10(a)).

    ``admission_profile.academic_year`` là NOT NULL (gán lúc tạo từ ``academic_info``), nên ``None`` chỉ xảy ra với
    stub test. Không rơi về năm của máy hay một năm cứng.
    """
    nam = getattr(profile, "academic_year", None)
    if nam is None:
        raise ValueError(
            f"admission_profile {getattr(profile, 'id', None)} không có academic_year — "
            "không có năm để tra mức điểm ưu tiên (không rơi về năm khác)."
        )
    return int(nam)


async def select_open_priority_rates(
    db: "AsyncSession",
    *,
    table: str,
    academic_year: int,
    codes: list[str],
) -> dict[str, Decimal]:
    """Hàng mức ĐANG MỞ của ``academic_year`` cho từng mã trong ``codes``: ``{mã: điểm}``.

    * "Đang mở" = ``effective_to IS NULL`` (khớp partial UNIQUE ``uq_priority_*_active`` của production). Hàng có
      ``effective_to`` — kể cả ở tương lai — là đã đóng; hàng mở có ``effective_from`` ở tương lai áp ngay.
    * Mã nào thiếu hàng ⇒ ``PriorityRateNotConfigured`` liệt kê MỌI mã thiếu.
    * Hai hàng mở cùng mã (test DB dựng bằng ``create_all`` không có partial UNIQUE) ⇒ ``RuntimeError``: không chọn
      bừa một hàng.
    """
    from app.models.priority_config import PriorityAreaConfig, PriorityObjectConfig

    if table == RATE_TABLE_AREA:
        model, cot_ma = PriorityAreaConfig, PriorityAreaConfig.area_code
    elif table == RATE_TABLE_OBJECT:
        model, cot_ma = PriorityObjectConfig, PriorityObjectConfig.sub_code
    else:
        raise ValueError(f"Bảng mức không hỗ trợ: {table!r}")

    can = list(dict.fromkeys(codes))
    if not can:
        return {}
    stmt = select(cot_ma, model.bonus_points).where(
        model.academic_year == academic_year,
        cot_ma.in_(can),
        model.effective_to.is_(None),
    )
    rows = (await db.execute(stmt)).all()
    return pick_open_priority_rates(rows, table=table, academic_year=academic_year, codes=can)


def pick_open_priority_rates(
    rows: Iterable[Sequence[Any]],
    *,
    table: str,
    academic_year: int,
    codes: list[str],
) -> dict[str, Decimal]:
    """Phần QUYẾT ĐỊNH của :func:`select_open_priority_rates` — hàm THUẦN trên các hàng ``(mã, điểm)`` ĐANG MỞ của
    ``academic_year`` đã đọc (GĐ2-B đợt 2: máy xét đọc MỌI hàng mở của năm bằng MỘT câu rồi gọi chính hàm này cho từng mã —
    một nguồn luật với T6 / bản in). Hàng của mã KHÔNG thuộc ``codes`` bị bỏ qua (câu đọc theo năm có thể trả thêm mã khác).
    Hai hàng mở cùng mã ⇒ ``RuntimeError``; mã thiếu ⇒ ``PriorityRateNotConfigured`` liệt kê MỌI mã thiếu."""
    from app.utils.exceptions import PriorityRateNotConfigured

    can = list(dict.fromkeys(codes))
    muc: dict[str, Decimal] = {}
    for ma, diem in rows:
        if ma not in can:
            continue
        if ma in muc:
            raise RuntimeError(
                f"{table}: hơn một hàng ĐANG MỞ cho mã {ma!r} năm {academic_year} — dữ liệu mức không nhất quán."
            )
        muc[ma] = Decimal(diem)
    thieu = [m for m in can if m not in muc]
    if thieu:
        raise PriorityRateNotConfigured(table=table, academic_year=academic_year, missing_codes=thieu)
    return muc


def best_code_by_rate(muc: dict[str, Decimal], ordered_codes: list[str]) -> str:
    """Mã có mức cao nhất trong ``muc`` (TT: chỉ hưởng MỘT diện cao nhất); hoà ⇒ mã đứng trước trong
    ``ordered_codes``. Một nguồn cho T6, xem trước và nhóm UT đã xác minh."""
    return max(muc, key=lambda c: (muc[c], -ordered_codes.index(c)))


async def _resolve_area_bonus(
    db: "AsyncSession",
    profile: "AdmissionProfile",
    academic_year: int,
) -> tuple[Decimal, dict[str, Any]]:
    """Điểm KV của hồ sơ — chỉ gọi khi luật cộng điểm bật ``apply_area_bonus``.

    KV đọc từ ``priority_resolution_snapshot`` (đóng băng ở T1, đóng băng lại ở T6). KV chưa phân giải
    (``kv_snapshot_resolved`` sai) ⇒ ``PriorityKvUnresolved`` — owner Q17(a): dừng có nhãn, KHÔNG 0 điểm. Thiếu hàng
    mức ⇒ ``PriorityRateNotConfigured`` (owner Q10-kèm).

    Returns ``(bonus_points, meta_dict)`` where meta is merged into the config_snapshot for audit.
    """
    from app.utils.exceptions import PriorityKvUnresolved

    snapshot = getattr(profile, "priority_resolution_snapshot", None)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    if not kv_snapshot_resolved(snapshot):
        raise PriorityKvUnresolved(
            rule_applied=snapshot.get("rule_applied"),
            reason=snapshot.get("reason"),
            context={"profile_id": getattr(profile, "id", None)},
            # L3: nhãn riêng "KV chờ xác minh" (cùng ``error_code`` — tập mã dừng T6 của FE không đổi).
            pending_verification=kv_pending_verification_kind(snapshot),
        )
    area_code = snapshot["kv_resolved"]
    muc = await select_open_priority_rates(
        db, table=RATE_TABLE_AREA, academic_year=academic_year, codes=[area_code]
    )
    rate = muc[area_code]
    return rate, {"area_code": area_code, "area_rate": str(rate)}


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

    Thiếu hàng mức ĐANG MỞ cho BẤT KỲ mã đã xác minh nào ⇒ ``PriorityRateNotConfigured`` (owner Q10-kèm): không lấy
    max trên các mã còn lại.

    Returns ``(bonus_points, meta_dict)``.
    """
    verified_codes = verified_object_codes(profile)
    meta: dict[str, Any] = {
        "verified_codes": verified_codes,
        "object_max_code": None,
        "object_rate": None,
    }
    if not verified_codes:
        return _ZERO, meta

    muc = await select_open_priority_rates(
        db, table=RATE_TABLE_OBJECT, academic_year=academic_year, codes=verified_codes
    )
    # Pick max bonus + record which sub_code won (audit "candidate had
    # UT1+UT2 verified, engine applied UT1 because higher rate").
    best_code = best_code_by_rate(muc, verified_codes)
    best_rate = muc[best_code]
    meta["object_max_code"] = best_code
    meta["object_rate"] = str(best_rate)
    return best_rate, meta


def verified_object_codes(profile: Any) -> list[str]:
    """Mã đối tượng ưu tiên có minh chứng ``verified`` (``priority_object_evidence[mã]["status"]``), theo thứ tự khai trong
    ``priority_object_codes`` — vị từ của :func:`_resolve_object_bonus` (T6), tách thành hàm thuần để máy xét GĐ2-B (đặc tả
    bản 4 §6.4 "các diện khác") dùng CHUNG, không chép. Chỉ đọc cột của hồ sơ."""
    codes = getattr(profile, "priority_object_codes", None) or []
    evidence = getattr(profile, "priority_object_evidence", None) or {}
    return [
        c
        for c in codes
        if isinstance(evidence.get(c), dict) and evidence[c].get("status") == "verified"
    ]


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


#: G5 — MỘT quy ước năm cho luật học nhiều trường (owner 22-11, ``logs-P5/cong-bo-ket-qua/gd2/
#: QUYET-DINH-OWNER-KV-NAM-THUC-HOC-VA-L3-2026-11-22.md`` mục 1–2; thay phần "năm kết thúc" của Q12 ngày 11-10):
#:
#: * khoá năm học = NĂM BẮT ĐẦU (năm học 2024–2025 ⇒ 2024). Một mục ``year_from → year_to`` (năm vào học → năm học xong /
#:   tốt nghiệp — ``AcademicRecordSchema``: "Start year (e.g., 2020)", "End year (e.g., 2023)") gồm ĐÚNG ``year_to − year_from`` năm
#:   học, khoá ``year_from .. year_to − 1`` (Q15(b) ngày 11-10, theo quy ước năm bắt đầu). Vd THPT 2022 → tốt nghiệp 2025 ⇒ 2022, 2023,
#:   2024 — KHÔNG tra 2025 (năm học 2025–2026, sau khi em đã tốt nghiệp). Trường tốt nghiệp (bước hoà) tra ở năm học CUỐI
#:   ``year_to − 1``;
#: * mục 0 năm học (``year_to == year_from``) ⇒ DỪNG có nhãn (Q15(b));
#: * mục LIÊN CẤP (``THCS_THPT``) chỉ đóng góp lớp 10..``grade_to`` (T5c "Chỉ tính THPT", Q8 "Suy 3 năm cuối (từ năm kết thúc + lớp
#:   kết thúc)"): ``grade_to − 9`` năm học cuối của mục; ``grade_to`` ≤ 9 ⇒ chỉ năm THCS ⇒ bỏ qua cả mục; THIẾU / sai ``grade_to`` ⇒
#:   DỪNG có nhãn, không tự xác định KV (owner 22-11, như THPT thiếu lớp — Q16(a)).
KV_LIEN_CAP_LEVEL = "THCS_THPT"
#: Lớp đầu của cấp THCS — lớp cuối phần THCS hợp lệ là 6..9 (:func:`kv_entry_thcs_last_grade`, owner 24-11).
_THCS_FIRST_GRADE = 6
_THPT_FIRST_GRADE = 10
_THPT_LAST_GRADE = 12
#: Mã ca DỪNG của một mục (``breakdown.entries[].case``) — hồ sơ ra ``insufficient_data`` / ``history_entries_inconsistent``.
KV_ENTRY_ZERO_LENGTH = "zero_length_entry"
KV_ENTRY_LIEN_CAP_MISSING_GRADE = "lien_cap_missing_grade_to"
KV_HISTORY_INCONSISTENT_REASON = "history_entries_inconsistent"


def _history_grade(value: Any) -> Optional[int]:
    """``grade_to`` hợp lệ (số nguyên 1..12 — khớp ``AcademicRecordSchema``) hoặc ``None`` (thiếu / lạ)."""
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _THPT_LAST_GRADE:
        return value
    return None


def _history_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def kv_lien_cap_without_thpt(entry: Any) -> bool:
    """Mục liên cấp có lớp kết thúc hợp lệ ≤ 9 ⇒ chỉ có năm THCS ⇒ KHÔNG được đếm (owner T5c), không là ứng viên trường tốt nghiệp."""
    if not isinstance(entry, dict) or entry.get("level") != KV_LIEN_CAP_LEVEL:
        return False
    grade = _history_grade(entry.get("grade_to"))
    return grade is not None and grade < _THPT_FIRST_GRADE


#: Bậc học của ``academic_history`` mà luật học nhiều trường xét (THPT, GDTX, liên cấp) — MỘT nguồn cho phép đếm và
#: :func:`_has_thpt_history`.
_KV_HISTORY_LEVELS = frozenset({"THPT", "THCS_THPT", "GDTX"})


def kv_history_basis_entry(entry: Any) -> bool:
    """MỘT vị từ "mục lịch sử THPT được tính" (owner 22-11 — chung cho phép đếm KV và cho :func:`_has_thpt_history`): object, cấp
    THPT / GDTX / liên cấp, KHÔNG phải liên cấp chỉ tới lớp ≤ 9 (:func:`kv_lien_cap_without_thpt`), và có ``school_id``.

    Liên cấp THIẾU / sai lớp kết thúc được tính BẤT KỂ ``school_id`` (Codex G5 rà tĩnh ``d4b7a69f`` P4): không loại được phần THPT ⇒
    phải vào tập để phép đếm DỪNG có nhãn (:func:`kv_entry_problem`). Nếu kiểm ``school_id`` trước, mục ấy bị loại lặng lẽ: là mục
    duy nhất thì CĐ liên thông rơi về thường trú; còn mục THPT khác thì KV chỉ tính từ mục đó — owner đòi dừng ở cả hai ca."""
    if not isinstance(entry, dict) or entry.get("level") not in _KV_HISTORY_LEVELS:
        return False
    if entry.get("level") == KV_LIEN_CAP_LEVEL and _history_grade(entry.get("grade_to")) is None:
        return True
    return bool(entry.get("school_id")) and not kv_lien_cap_without_thpt(entry)


def kv_entry_problem(entry: dict) -> Optional[str]:
    """Mã ca DỪNG của một mục đã vào tập đếm (:func:`kv_history_basis_entry`), ``None`` = đếm được.

    * liên cấp thiếu / sai ``grade_to`` ⇒ :data:`KV_ENTRY_LIEN_CAP_MISSING_GRADE` (không biết đâu là năm THPT);
    * ``year_from`` / ``year_to`` là số nguyên và BẰNG nhau ⇒ :data:`KV_ENTRY_ZERO_LENGTH` (0 năm học — Q15(b)).
    Mục thiếu năm / năm ngược vẫn bị BỎ QUA như trước (schema cấm; không đổi ở G5)."""
    if entry.get("level") == KV_LIEN_CAP_LEVEL and _history_grade(entry.get("grade_to")) is None:
        return KV_ENTRY_LIEN_CAP_MISSING_GRADE
    y_from, y_to = entry.get("year_from"), entry.get("year_to")
    if _history_int(y_from) and _history_int(y_to) and y_to == y_from:
        return KV_ENTRY_ZERO_LENGTH
    return None


def kv_lien_cap_split_year(entry: dict) -> int:
    """MỘT chỗ CẮT mục liên cấp (``THCS_THPT``) thành phần THCS và phần THPT — khoá năm bắt đầu của năm học lớp 10 đầu tiên trong mục:
    lớp kết thúc ``g`` hợp lệ ⇒ ``min(year_to, max(year_from, year_to − (g − 9)))`` (``g`` ≤ 9 ⇒ ``year_to``: cả mục là THCS). Phần THPT
    = ``split .. year_to − 1`` (:func:`kv_entry_school_years`, G5); phần THCS = ``year_from .. split − 1``
    (:func:`kv_entry_thcs_school_years`, L3 — owner 22-11 ``QUYET-DINH-OWNER-L3A-5-CAU`` câu 3: "cắt như G5 cắt phần THPT"). Chỉ gọi
    khi năm là số nguyên và lớp kết thúc hợp lệ."""
    y_from, y_to = entry["year_from"], entry["year_to"]
    grade = _history_grade(entry.get("grade_to"))
    return min(y_to, max(y_from, y_to - (grade - (_THPT_FIRST_GRADE - 1))))


def kv_entry_school_years(entry: dict) -> range:
    """Khoá năm học (NĂM BẮT ĐẦU) được tra của một mục đếm được ở nhánh THPT: ``range(năm học đầu, year_to)``.

    * THPT / GDTX: ``year_from .. year_to − 1``.
    * liên cấp lớp kết thúc ``g`` ∈ 10..12: ``g − 9`` năm học cuối — ``kv_lien_cap_split_year .. year_to − 1`` (mục ngắn thì không
      sớm hơn năm vào học). Vd lớp 6 → hết lớp 10 ``2017→2022`` ⇒ chỉ 2021; lớp 6–12 ``2016→2023`` ⇒ 2020, 2021, 2022 — ĐÚNG như mục
      THPT ``2020→2023``.
    Chỉ gọi sau :func:`kv_entry_problem` = ``None`` và đã loại :func:`kv_lien_cap_without_thpt`. Nhánh THCS dùng
    :func:`kv_entry_thcs_school_years` (CÙNG chỗ cắt)."""
    y_from, y_to = entry["year_from"], entry["year_to"]
    first = y_from
    if entry.get("level") == KV_LIEN_CAP_LEVEL:
        first = kv_lien_cap_split_year(entry)
    return range(first, y_to)


def kv_entry_thcs_end_year(entry: dict) -> int:
    """L3: năm KẾT THÚC phần THCS của một dòng THCS đếm được (như ``year_to`` của dòng THCS thường) — liên cấp ⇒ chỗ cắt
    :func:`kv_lien_cap_split_year`; dòng khác ⇒ ``year_to``."""
    if entry.get("level") == KV_LIEN_CAP_LEVEL:
        return kv_lien_cap_split_year(entry)
    return entry["year_to"]


def kv_entry_thcs_school_years(entry: dict) -> range:
    """L3: khoá năm học (năm bắt đầu) của phần THCS — ``year_from .. kv_entry_thcs_end_year − 1``. CÙNG quy ước khoá với G5 (owner L3
    câu 4: "đếm năm học như G5"); liên cấp lớp 6 → 10 ``2017→2022`` ⇒ 2017, 2018, 2019, 2020 (năm 2021 là lớp 10, thuộc phần THPT)."""
    return range(entry["year_from"], kv_entry_thcs_end_year(entry))


def kv_entry_thcs_last_school_year(entry: dict) -> int:
    """L3: khoá năm học CUỐI của phần THCS (năm học lớp 9 / năm cuối ở trường) — khoá tra trường tốt nghiệp THCS ở bước hoà."""
    return kv_entry_thcs_end_year(entry) - 1


def kv_entry_thcs_last_grade(entry: dict) -> Optional[int]:
    """L3: lớp cuối của PHẦN THCS — khoá thứ hai của bước hoà nhánh THCS (:func:`kv_graduation_pick`, CÙNG luật với THPT). Liên cấp
    lớp kết thúc ≥ 10 ⇒ 9 (phần THCS dừng ở lớp 9; lớp kết thúc hợp lệ đã được :func:`kv_thcs_entry_case` bảo đảm); dòng khác ⇒
    ``grade_to``. Lớp cuối phần THCS KHÔNG phải số nguyên 6..9 ⇒ ``None`` (dữ liệu lớp không hợp lệ). So được hay không do
    :func:`_history_int` ở bước hoà quyết (MỘT chỗ, chung THPT) — ``None`` ⇒ như ô lớp trống:
    * owner 23-11 ``QUYET-DINH-OWNER-O-LOP-TRONG-CAN-XET-TAY`` (a): lớp trống / null / sai kiểu ở nhóm tốt nghiệp ⇒ cần xét tay, KHÔNG
      coi là 0 (khoá cũ ``_history_grade(...) or 0`` — luật (b) — đã bỏ);
    * owner 24-11 ``QUYET-DINH-OWNER-L3-DONG-THCS-LOP-NGOAI-6-9``: dòng THCS ghi lớp ngoài 6–9 (schema cho 1..12) là dữ liệu lớp không
      hợp lệ ⇒ cùng đường ấy — trước đây "lớp 12" so như số nên thắng liên cấp đã cắt về 9 lặng lẽ (rà đoàn 3 D'2 NỢ-1). Phần mở
      rộng kỹ thuật (điều phối 24-11, một định nghĩa): liên cấp kết thúc ở lớp 1–5 (lớp cuối phần THCS < 6) cũng không hợp lệ."""
    grade = entry.get("grade_to")
    if entry.get("level") == KV_LIEN_CAP_LEVEL and _history_int(grade):
        grade = min(grade, _THPT_FIRST_GRADE - 1)
    if _history_int(grade) and _THCS_FIRST_GRADE <= grade <= _THPT_FIRST_GRADE - 1:
        return grade
    return None


def kv_last_school_year(entry: dict) -> Any:
    """Khoá năm học CUỐI của mục (``year_to − 1``) — khoá tra trường tốt nghiệp ở bước hoà. ``year_to`` không phải số ⇒ trả nguyên giá
    trị (hành vi cũ: phép tra không ra hàng)."""
    y_to = entry.get("year_to")
    return y_to - 1 if _history_int(y_to) else y_to


# ── Bước hoà (trường tốt nghiệp) — MỘT luật cho nhánh THPT và nhánh THCS (L3) ──
# Owner 23-11 ``QUYET-DINH-OWNER-O-LOP-TRONG-CAN-XET-TAY`` (a) + rà hợp nhất 23-11 J1c / Codex lượt 2 B'3: luật hoà phải MỘT, sống
# trong bộ quyết định chung :func:`_kv_resolution_steps` (đường lẻ và đường lô cùng tiêu thụ). Hai nhánh chỉ khác HAI bộ truy cập
# (năm kết thúc, lớp cuối) — THPT: ``year_to`` / ``grade_to``; THCS: năm kết thúc / lớp cuối của PHẦN THCS (cắt liên cấp một chỗ,
# :func:`kv_lien_cap_split_year`). "So được" = :func:`_history_int` cho cả hai (MỘT helper — CLAUDE.md §7).


def kv_entry_end_year(entry: dict) -> Any:
    """Nhánh THPT: năm kết thúc của mục ở bước hoà — ``year_to`` NGUYÊN giá trị (thiếu khoá ⇒ ``None``)."""
    return entry.get("year_to")


def kv_entry_last_grade(entry: dict) -> Any:
    """Nhánh THPT: lớp cuối của mục ở bước hoà — ``grade_to`` NGUYÊN giá trị (thiếu khoá ⇒ ``None``: owner 23-11 — "thiếu hẳn khoá"
    và "null" xử lý NHƯ NHAU)."""
    return entry.get("grade_to")


def kv_graduation_year_group(
    entries: list, year_of: Callable[[dict], Any] = kv_entry_end_year
) -> list[tuple[int, dict]]:
    """Nhóm ứng viên trường tốt nghiệp ở bước hoà: ``(chỉ số trong entries, mục)`` của các mục có năm kết thúc (``year_of``) LỚN NHẤT.

    Trường tốt nghiệp luôn thuộc nhóm này vì khoá xếp đầu tiên của bước hoà là năm kết thúc. Bước hoà chỉ xếp TRONG nhóm (rà hợp nhất
    23-11 mục B-H1): xếp cả các nhóm thấp hơn không đổi kết quả, nhưng bắt hai mục cùng năm ở nhóm thấp so lớp với nhau ⇒
    ``TypeError`` khi một mục có lớp ``null`` / chuỗi. Chỉ số là chỉ số GỐC (``enumerate`` TRƯỚC khi lọc — khoá ổn định ``-index``).
    Chỉ gọi khi MỌI năm kết thúc là số nguyên (:func:`_history_int`) — vế đầu của :func:`kv_graduation_candidates_unclear`."""
    latest = max(year_of(e) for e in entries)
    return [(i, e) for i, e in enumerate(entries) if year_of(e) == latest]


def kv_graduation_candidates_unclear(
    entries: list,
    year_of: Callable[[dict], Any] = kv_entry_end_year,
    grade_of: Callable[[dict], Any] = kv_entry_last_grade,
) -> Optional[list]:
    """Chốt thiếu dữ liệu của bước hoà (M1): các mục CÓ THỂ là trường tốt nghiệp mà KHÔNG so được ⇒ trả danh sách mục ấy (hoà không
    phân định ⇒ cần xét tay); ``None`` = so được, đi tiếp phép xếp trong nhóm :func:`kv_graduation_year_group`.

    * Một mục bất kỳ thiếu / sai kiểu năm kết thúc ⇒ không biết mục nào học sau cùng ⇒ MỌI mục.
    * Năm đều hợp lệ: nhóm có năm kết thúc lớn nhất có từ 2 mục trở lên mà một mục thiếu / sai kiểu lớp ⇒ nhóm ấy.
    * Nhóm năm lớn nhất chỉ có MỘT mục ⇒ so được (lớp không cần) — như cũ. Lớp lạ ở nhóm THẤP hơn không cản: nhóm ấy không được xếp.

    "Hợp lệ" = :func:`_history_int` (số nguyên thật: không ``bool``, chuỗi, số thực, ``None``; thiếu khoá = ``None``). Vì sao: khoá
    sắp xếp cũ ``(.get("year_to", 0), .get("grade_to", 0), -index)`` chỉ thay khi THIẾU khoá; JSON ``null`` (hay chuỗi) ⇒ so ``None``
    với ``int`` ⇒ ``TypeError`` (owner GO 22-11 "sửa ngay, PR nhỏ riêng"). Owner 23-11 (a): áp CHUNG THPT và THCS."""
    if any(not _history_int(year_of(e)) for e in entries):
        return list(entries)
    candidates = [e for _, e in kv_graduation_year_group(entries, year_of)]
    if len(candidates) >= 2 and any(not _history_int(grade_of(e)) for e in candidates):
        return candidates
    return None


def kv_graduation_pick(
    entries: list,
    year_of: Callable[[dict], Any] = kv_entry_end_year,
    grade_of: Callable[[dict], Any] = kv_entry_last_grade,
) -> tuple[Optional[dict], list]:
    """MỘT luật bước hoà của luật học nhiều trường (như ghi ở quyết định owner 23-11 ``QUYET-DINH-OWNER-O-LOP-TRONG-CAN-XET-TAY``: hoà
    thời gian mà KV khác nhau ⇒ trường tốt nghiệp = năm kết thúc lớn nhất, năm trùng ⇒ lớp cuối lớn nhất) — gọi từ nhánh THPT VÀ
    nhánh THCS của :func:`_kv_resolution_steps`.

    Trả ``(mục tốt nghiệp, [])`` hoặc ``(None, các mục không phân định)``:
    * chốt thiếu dữ liệu :func:`kv_graduation_candidates_unclear` ⇒ ``(None, mục không so được)``;
    * xếp NHÓM năm lớn nhất theo ``(năm, lớp, -chỉ số gốc)`` (:func:`kv_graduation_year_group`); hai mục đầu bằng nhau cả năm lẫn
      lớp ⇒ ``(None, [mục 1, mục 2])`` (M1).
    Nhánh THPT đổi ``(None, …)`` thành ``ambiguous_requires_manual``; nhánh THCS thành "KV chờ xác minh"
    (``thcs_tied_graduation_school``). Dữ liệu đúng kiểu: kết quả như phép xếp toàn bộ cũ (bàn giao hoà THPT G5 §2)."""
    if not entries:
        return None, []
    unclear = kv_graduation_candidates_unclear(entries, year_of, grade_of)
    if unclear is not None:
        return None, unclear
    ranked = sorted(
        kv_graduation_year_group(entries, year_of),
        key=lambda pair: (year_of(pair[1]), grade_of(pair[1]), -pair[0]),  # -index: ổn định, ưu tiên mục khai trước
        reverse=True,
    )
    top = ranked[0][1]
    if len(ranked) >= 2:
        second = ranked[1][1]
        if (year_of(top), grade_of(top)) == (year_of(second), grade_of(second)):
            return None, [top, second]
    return top, []


def _has_thpt_history(academic_history: Optional[list]) -> bool:
    """True khi profile có ít nhất 1 academic_history entry mức THPT/GDTX hợp lệ.

    "Hợp lệ" = :func:`kv_history_basis_entry` (MỘT vị từ với phép đếm KV — owner 22-11: liên cấp chỉ tới lớp ≤ 9 KHÔNG còn là "có
    THPT") + year_from/year_to không null. Dùng cho hybrid rule CĐ liên thông KHOI_LUONG_VH_THPT + TC (yêu cầu nghiệp vụ #6): có
    history → LICH_SU_THPT; không có → THUONG_TRU. Liên cấp THIẾU lớp kết thúc vẫn là "có" ⇒ đi LICH_SU_THPT ⇒ phép đếm DỪNG có nhãn
    (không lặng lẽ rơi về thường trú).
    """
    if not academic_history:
        return False
    return any(
        kv_history_basis_entry(e)
        and e.get("year_from") is not None
        and e.get("year_to") is not None
        for e in academic_history
    )


# ── L3: dòng lịch sử học THCS (nhánh trung cấp sau THCS) ──
KV_THCS_LEVEL = "THCS"
#: ``graduation_type`` ("Trình độ" trên form) của dòng THCS. Đo production 22-11 (``gd2/l3/do-prod-2026-11-22``): dòng THCS thật
#: hầu hết có ``level`` TRỐNG (giao diện chỉ gán ``level`` khi chọn trường từ danh mục), ``graduation_type = 'THCS'``, không ``school_id``.
KV_THCS_GRADUATION_TYPE = "THCS"
#: Mã ca DỪNG của một dòng THCS (``breakdown.entries[].case``) ⇒ hồ sơ "KV chờ xác minh".
KV_THCS_ENTRY_WITHOUT_SCHOOL = "thcs_entry_without_school"
KV_THCS_ENTRY_BAD_SCHOOL_ID = "thcs_entry_school_id_invalid"
KV_THCS_ENTRY_LEVEL_MISMATCH = "school_level_mismatch"
KV_THCS_ENTRY_LEVEL_UNKNOWN = "entry_level_unknown"
KV_THCS_ENTRY_YEARS_INVALID = "entry_years_invalid"


def _blank(value: Any) -> Optional[Any]:
    """Chuỗi rỗng / chỉ khoảng trắng ⇒ ``None`` (ô "trống" của JSONB); giá trị khác giữ nguyên."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def kv_thcs_entry_case(entry: Any) -> tuple[bool, Optional[str]]:
    """``(là dòng THCS, mã ca dừng | None)`` của một mục ``academic_history`` cho nhánh trung cấp sau THCS (L3).

    * cấp ``THCS`` (chọn trường THCS từ danh mục): dòng THCS; ``graduation_type`` khác THCS (và không trống) ⇒ lệch cấp ⇒ dừng;
    * ``level`` trống: ``graduation_type = 'THCS'`` ⇒ dòng THCS (dòng gõ tay — dạng phổ biến nhất ở production); trống cả hai ⇒
      KHÔNG biết dòng thuộc cấp nào ⇒ dừng (không lặng lẽ bỏ — có thể là trường THCS gõ tay); trình độ khác ⇒ không phải dòng THCS;
    * liên cấp (``THCS_THPT``): lớp kết thúc ≤ 9 ⇒ dòng THCS (cả mục); THIẾU / sai lớp kết thúc ⇒ dừng (như G5); lớp kết thúc ≥ 10 mà
      mục CÒN năm học THCS (trước chỗ cắt :func:`kv_lien_cap_split_year`) ⇒ dòng THCS, chỉ đếm phần lớp 6–9 (owner 22-11
      ``QUYET-DINH-OWNER-L3A-5-CAU`` câu 3); mục chỉ có năm THPT ⇒ không phải dòng THCS;
    * cấp khác (THPT, trung học nghề, khác…): ``graduation_type = 'THCS'`` ⇒ lệch cấp ⇒ dừng (điều phối 22-11: 8 dòng production
      chọn trường cấp THPT mà ghi trình độ THCS — KHÔNG tự tính); còn lại không phải dòng THCS.

    Dòng THCS còn phải có năm hợp lệ và ``school_id`` (số nguyên), xét theo thứ tự: năm thiếu / ngược ⇒
    :data:`KV_THCS_ENTRY_YEARS_INVALID`; 0 năm học (``y→y``) ⇒ :data:`KV_ENTRY_ZERO_LENGTH` (Q15(b), như G5); thiếu trường ⇒
    :data:`KV_THCS_ENTRY_WITHOUT_SCHOOL` ("trường chưa có trong danh mục"). Cờ DTNT của trường tra ở bộ quyết định (cần CSDL)."""
    if not isinstance(entry, dict):
        return False, None
    level = _blank(entry.get("level"))
    gtype = _blank(entry.get("graduation_type"))
    if level == KV_LIEN_CAP_LEVEL:
        grade = _history_grade(entry.get("grade_to"))
        if grade is None:
            return True, KV_ENTRY_LIEN_CAP_MISSING_GRADE
        if grade >= _THPT_FIRST_GRADE:
            y_from, y_to = entry.get("year_from"), entry.get("year_to")
            if not (_history_int(y_from) and _history_int(y_to) and y_to >= y_from):
                return True, KV_THCS_ENTRY_YEARS_INVALID
            if kv_lien_cap_split_year(entry) <= y_from:
                return False, None  # chỉ có năm THPT
    elif level == KV_THCS_LEVEL:
        if gtype is not None and gtype != KV_THCS_GRADUATION_TYPE:
            return True, KV_THCS_ENTRY_LEVEL_MISMATCH
    elif level is None:
        if gtype is None:
            return True, KV_THCS_ENTRY_LEVEL_UNKNOWN
        if gtype != KV_THCS_GRADUATION_TYPE:
            return False, None
    else:
        if gtype == KV_THCS_GRADUATION_TYPE:
            return True, KV_THCS_ENTRY_LEVEL_MISMATCH
        return False, None
    # Năm trước trường (điều phối 22-11 mục 4: dòng THCS ``y→y`` theo luật G5 — 0 năm học, dừng có nhãn — kể cả dòng gõ tay).
    y_from, y_to = entry.get("year_from"), entry.get("year_to")
    if not (_history_int(y_from) and _history_int(y_to) and y_to >= y_from):
        return True, KV_THCS_ENTRY_YEARS_INVALID
    if y_to == y_from:
        return True, KV_ENTRY_ZERO_LENGTH
    sid = entry.get("school_id")
    if sid is None or sid == "":
        return True, KV_THCS_ENTRY_WITHOUT_SCHOOL
    if not _history_int(sid):
        return True, KV_THCS_ENTRY_BAD_SCHOOL_ID
    return True, None


def kv_thcs_history_plan(academic_history: Any) -> tuple[list[dict], list[dict]]:
    """``(dòng THCS đếm được, dòng dừng)`` — MỘT nguồn cho bộ quyết định (nhánh ``LICH_SU_THCS``) và :func:`kv_lookup_keys`. Dòng
    dừng mang ``index`` theo ``academic_history`` + ``case`` (:func:`kv_thcs_entry_case`); không mang tên trường."""
    countable: list[dict] = []
    problems: list[dict] = []
    for i, entry in enumerate(academic_history if isinstance(academic_history, list) else []):
        is_thcs, problem = kv_thcs_entry_case(entry)
        if not is_thcs:
            continue
        if problem is None:
            countable.append(entry)
            continue
        problems.append(
            {
                "index": i,
                "level": entry.get("level"),
                "graduation_type": entry.get("graduation_type"),
                "school_id": entry.get("school_id"),
                "grade_to": entry.get("grade_to"),
                "year_from": entry.get("year_from"),
                "year_to": entry.get("year_to"),
                "case": problem,
            }
        )
    return countable, problems


# =============================================================================
# L3 (owner 22-11) — KV của thí sinh trung cấp xét sau THCS theo NƠI HỌC THCS; sơ cấp + nhánh cũ "chờ xác minh"
# =============================================================================
#
# Căn cứ: ``logs-P5/cong-bo-ket-qua/gd2/l3/QUYET-DINH-OWNER-L3-5-CAU-2026-11-22.md`` (câu 1, 2, 4, 5) +
# ``…/QUYET-DINH-OWNER-L3-TRUONG-THCS-VAO-DANH-MUC-2026-11-22.md`` (đổi câu 3: Admin thêm trường THCS vào danh mục, KV trường = KV xã
# hiện tại) + ``…/DIEU-TRA-BO-KV-TRUNG-CAP-BO-SUNG-TT05-2026-11-22.md`` (TT 05 PL01 5.a / 5.c: KV theo nơi học và tốt nghiệp THCS).
#
# * Trung cấp sau THCS (chính quy; liên thông từ sơ cấp / trung cấp) ⇒ căn cứ ``LICH_SU_THCS``: tính từ các dòng lịch sử học THCS có
#   trường trong danh mục — CÙNG cách đếm năm học (:func:`kv_entry_school_years`), CÙNG phép tra theo năm, CÙNG luật "khu vực học
#   lâu nhất, hoà ⇒ trường tốt nghiệp" như THPT (owner câu 4 "giống cách tính THPT"; bước hoà là MỘT hàm :func:`kv_graduation_pick`
#   — lớp trống ở nhóm tốt nghiệp ⇒ cần xét tay, owner 23-11 (a)). Không tính được ⇒ "KV chờ xác minh".
# * Sơ cấp và nhánh cũ không truyền trình độ (THCS) ⇒ "KV chờ xác minh" (câu 5).
# * Nhãn ``permanent_address_special`` KHÔNG là căn cứ cho ba nhóm này (câu 2); ấn định tay có nguồn gốc vẫn thắng.
# * Câu 1 "đo trước rồi quyết": hồ sơ CŨ (ảnh chụp KV do luật cũ ra) giữ luật cũ cho tới khi bật cờ
#   ``KV_L3_APPLY_TO_EXISTING_ENABLED`` (mặc định TẮT; env đọc lúc TẠO container ⇒ đổi bằng ``up -d``, không ``restart``).
#
# Nhánh ``legacy_completed_thpt_no_vocational`` (hoàn thành THPT, không chuyên môn / sơ cấp, nơi gọi không truyền trình độ): owner
# 22-11 ``QUYET-DINH-OWNER-L3A-5-CAU`` câu 5 ⇒ tính theo trường THPT (``LICH_SU_THPT``), cùng cơ chế hồ sơ cũ. Nhánh còn lại cho em
# đã xong THPT mà lấy hộ khẩu: ``cd_lien_thong_khoi_luong_no_thpt_history_fallback`` (CĐ liên thông, không có lịch sử THPT) — GIỮ,
# chưa có quyết định (bàn giao L3-a lượt 2).

KV_BASIS_THCS_HISTORY = "LICH_SU_THCS"
KV_BASIS_PENDING_VERIFICATION = "PENDING_VERIFICATION"

#: Lý do căn cứ của luật CŨ (``THUONG_TRU``) ở ba nhóm L3 ⇒ căn cứ MỚI.
_L3_NEW_BASIS: dict[str, tuple[str, str]] = {
    "tc_chinh_quy_post_thcs_uses_commune": (KV_BASIS_THCS_HISTORY, "tc_chinh_quy_post_thcs_uses_thcs_school_history"),
    "tc_lien_thong_post_thcs_with_voc_uses_commune": (
        KV_BASIS_THCS_HISTORY,
        "tc_lien_thong_post_thcs_with_voc_uses_thcs_school_history",
    ),
    "sc_no_cultural_uses_commune": (KV_BASIS_PENDING_VERIFICATION, "sc_no_cultural_kv_needs_verification"),
    "sc_uses_commune": (KV_BASIS_PENDING_VERIFICATION, "sc_kv_needs_verification"),
    "legacy_thcs_pathway_uses_commune": (KV_BASIS_PENDING_VERIFICATION, "legacy_thcs_pathway_kv_needs_verification"),
}

#: Owner 22-11 ``QUYET-DINH-OWNER-L3A-5-CAU`` câu 5: nhánh cũ "hoàn thành THPT, không chuyên môn / sơ cấp, nơi gọi không truyền
#: trình độ" ⇒ cách tính của NHÓM THPT (lý do có sẵn ``legacy_thpt_pathway``), bỏ hộ khẩu. Là nhóm THPT nên nhãn hộ khẩu đặc biệt
#: VẪN thắng (câu 2 chỉ áp cho ba nhóm trên) — xét SAU nhãn. Hồ sơ cũ theo cùng cờ (câu 1; production 0 hồ sơ ở 22-11).
_L3_THPT_BASIS: dict[str, tuple[str, str]] = {
    "legacy_completed_thpt_no_vocational": ("LICH_SU_THPT", "legacy_thpt_pathway"),
}

#: ``(basis, basis_reason)`` mà luật CŨ ghi vào ảnh chụp KV của hồ sơ thuộc các nhánh L3 đổi — "hồ sơ cũ" (điều phối 22-11 chấp nhận).
#: Gồm cả nhãn hộ khẩu đặc biệt (luật cũ cho nhãn ấy thắng mọi nhóm). Luật cũ tái tạo ĐÚNG cặp ấy ở lần chụp sau ⇒ ổn định.
KV_L3_LEGACY_SNAPSHOT_PAIRS = frozenset(
    {("THUONG_TRU", reason) for reason in (*_L3_NEW_BASIS, *_L3_THPT_BASIS)}
    | {("COMMUNE_SPECIAL", "permanent_address_special_override")}
)


def kv_l3_keeps_legacy_rule(previous_snapshot: Any) -> bool:
    """Hồ sơ CŨ giữ luật cũ ⇔ cờ ``KV_L3_APPLY_TO_EXISTING_ENABLED`` TẮT (mặc định; thiếu biến = tắt) VÀ ảnh chụp KV đang có do luật
    cũ ra (:data:`KV_L3_LEGACY_SNAPSHOT_PAIRS`). Hồ sơ chưa từng chụp ⇒ luật mới. Cờ là cờ CHO PHÉP: chỉ ``true`` mới áp luật mới cho
    hồ sơ cũ."""
    from app.config import settings

    if settings.KV_L3_APPLY_TO_EXISTING_ENABLED is True:
        return False
    s = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    return (s.get("basis"), s.get("basis_reason")) in KV_L3_LEGACY_SNAPSHOT_PAIRS


def _derive_kv_basis_level(
    cultural: Optional[str],
    vocational: str,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
    academic_history: Optional[list] = None,
    area_resolution_basis: Optional[str] = None,
    previous_snapshot: Optional[dict] = None,
) -> tuple[str, str]:
    """``(basis, basis_reason)`` của hồ sơ — ma trận :func:`_derive_kv_matrix_basis` + hai đường vượt + luật L3.

    Thứ tự: ấn định tay (``MANUAL``) → ma trận → ba nhóm L3 (không giữ luật cũ) ⇒ căn cứ mới → nhãn hộ khẩu đặc biệt
    (``COMMUNE_SPECIAL``) → nhánh cũ hoàn thành THPT (không giữ luật cũ) ⇒ ``LICH_SU_THPT`` → kết quả ma trận. ``previous_snapshot`` = ảnh chụp KV hiện có của hồ sơ (:func:`kv_l3_keeps_legacy_rule`);
    ``None`` ⇒ hồ sơ chưa chụp ⇒ luật mới."""
    if area_resolution_basis == "manual_override":
        return "MANUAL", "admin_set_kv_directly"
    basis, basis_reason = _derive_kv_matrix_basis(
        cultural=cultural,
        vocational=vocational,
        target_level=target_level,
        admission_type=admission_type,
        academic_history=academic_history,
    )
    l3_basis = _L3_NEW_BASIS.get(basis_reason) if basis == "THUONG_TRU" else None
    thpt_basis = _L3_THPT_BASIS.get(basis_reason) if basis == "THUONG_TRU" else None
    if (l3_basis is not None or thpt_basis is not None) and kv_l3_keeps_legacy_rule(previous_snapshot):
        l3_basis = thpt_basis = None  # hồ sơ cũ, cờ tắt ⇒ luật cũ
    if l3_basis is not None:
        return l3_basis
    if area_resolution_basis == "permanent_address_special":
        return "COMMUNE_SPECIAL", "permanent_address_special_override"
    if thpt_basis is not None:
        return thpt_basis
    return basis, basis_reason


def _derive_kv_matrix_basis(
    cultural: Optional[str],
    vocational: str,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
    academic_history: Optional[list] = None,
) -> tuple[str, str]:
    """Map profile context → KV resolution basis + reason code (MA TRẬN gốc; hai đường vượt ``permanent_address_special`` /
    ``manual_override`` và luật L3 nằm ở :func:`_derive_kv_basis_level`).

    Phase E.4 (commit 5) refactor — signature mở rộng target_level +
    admission_type + academic_history để khớp matrix nghiệp vụ #6:

      - TC sau THCS (target=trung_cap chính quy, cultural=completed_thcs/graduated_thcs) → THUONG_TRU
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
        'LICH_SU_THPT'           — multi-school rule TT 05/2021 Phụ lục 01 Mục 5.a
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
    # 1. Override paths (``permanent_address_special`` / ``manual_override``) — ở :func:`_derive_kv_basis_level` (L3).

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

    # 4. Backward-compat legacy branch (target_level chưa truyền — caller cũ).
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

    # 5. Phase E.4 matrix — target_level + admission_type drive basis.
    atype = admission_type or "chinh_quy"

    # 5a. Hybrid CĐ liên thông + completed_thpt + TC/CĐ (KHOI_LUONG_VH_THPT).
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

    # 5b. CĐ (chính quy hoặc liên thông) với cultural graduated_thpt/gdtx/completed_thpt
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
        # Eligibility gate đã chặn completed_thcs/graduated_thcs cho CĐ chính quy.
        # Defensive: nếu reach here → cấu hình mismatch upstream.
        return "INSUFFICIENT_DATA", f"cd_{atype}_cultural_insufficient_for_kv_basis"

    # 5c. TC matrix.
    if target_level == "trung_cap":
        if atype == "lien_thong":
            # TC liên thông từ SC/TC sau THCS → THUONG_TRU
            if cultural in ("completed_thcs", "graduated_thcs") and voc in (
                "so_cap",
                "trung_cap",
            ):
                return "THUONG_TRU", "tc_lien_thong_post_thcs_with_voc_uses_commune"
            # TC liên thông có THPT/hoàn thành THPT → LICH_SU_THPT
            if cultural in ("completed_thpt", "graduated_thpt", "graduated_gdtx"):
                return "LICH_SU_THPT", "tc_lien_thong_post_thpt_uses_school_history"
            return (
                "INSUFFICIENT_DATA",
                "tc_lien_thong_cultural_insufficient_for_kv_basis",
            )
        # TC chính quy:
        # - Hoàn thành/TN_THCS → THUONG_TRU
        # - completed/graduated THPT/GDTX → LICH_SU_THPT
        if cultural in ("completed_thcs", "graduated_thcs"):
            return "THUONG_TRU", "tc_chinh_quy_post_thcs_uses_commune"
        if cultural in ("completed_thpt", "graduated_thpt", "graduated_gdtx"):
            return "LICH_SU_THPT", "tc_chinh_quy_post_thpt_uses_school_history"
        return "INSUFFICIENT_DATA", "tc_chinh_quy_cultural_insufficient_for_kv_basis"

    # 5d. SC chính quy — không yêu cầu cultural; default THUONG_TRU.
    # Engine sẽ check commune ở resolve step (ADDRESS_NOT_NORMALIZED nếu miss).
    if target_level == "so_cap":
        return "THUONG_TRU", "sc_uses_commune"

    # 6. Defensive: target_level ngoài CD/TC/SC scope (eligibility gate đã chặn).
    return "INSUFFICIENT_DATA", f"unsupported_target_level:{target_level}"


async def _lookup_commune_kv(
    db: "AsyncSession", commune_code: str, year: int
) -> Optional[str]:
    """Lookup KV for a commune_code from vn_commune_area_map, AS-OF the given
    academic year (temporal — mirrors ``lookup_kv_for_school_year`` semantics).

    A KV row is effective for ``year`` when it is the active policy at the end
    of that academic year (half-open interval): ``effective_from <= Dec-31-year``
    AND ``effective_to`` is NULL or strictly after Dec-31-year. So a mid-year KV
    reclassification (xã hết khó khăn → KV đổi), recorded as expire-old +
    insert-new, resolves to the correct row per year instead of always taking
    the "now" row — which would silently mis-score historical/future cycles.
    Returns None if commune not in table (graceful — coverage may be partial).
    """
    from app.models.vn_locality import VnCommuneAreaMap, commune_kv_pick_order_sql

    as_of = date(year, 12, 31)
    stmt = (
        select(VnCommuneAreaMap.area_code)
        .where(
            VnCommuneAreaMap.commune_code == commune_code,
            VnCommuneAreaMap.effective_from <= as_of,
            (VnCommuneAreaMap.effective_to.is_(None))
            | (VnCommuneAreaMap.effective_to > as_of),
        )
        # MỘT thứ tự với đường lô (``commune_kv_pick_order_sql``): mới nhất theo ``effective_from``, hoà ⇒ ``id`` lớn nhất.
        .order_by(text(commune_kv_pick_order_sql(VnCommuneAreaMap.__tablename__)))
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
    from app.models.vn_school import VnSchoolKvAssignment, school_kv_pick_order_sql

    stmt = (
        select(VnSchoolKvAssignment.kv_code)
        .where(
            VnSchoolKvAssignment.school_id == school_id,
            VnSchoolKvAssignment.effective_from_year <= year,
            (VnSchoolKvAssignment.effective_to_year.is_(None))
            | (VnSchoolKvAssignment.effective_to_year >= year),
        )
        # Codex 22-11 lượt 2 B-P1: nhiều dòng chồng khoảng cùng khớp ⇒ thứ tự TẤT ĐỊNH, MỘT nguồn với đường lô.
        .order_by(text(school_kv_pick_order_sql(VnSchoolKvAssignment.__tablename__)))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def lookup_school_is_dtnt(db: "AsyncSession", school_id: int) -> Optional[bool]:
    """L3: cờ trường PT dân tộc nội trú (``vn_school.is_dtnt``) của một trường — ``None`` khi không có trường. Bản lô:
    ``admission_review_load_repository.read_school_dtnt``."""
    from app.models.vn_school import VnSchool

    result = await db.execute(select(VnSchool.is_dtnt).where(VnSchool.id == school_id))
    return result.scalar_one_or_none()


# Bậc học của ``academic_history`` mà luật nhiều trường tính: MỘT định nghĩa ``_KV_HISTORY_LEVELS`` (khối G5, cạnh
# ``kv_history_basis_entry``) — bộ quyết định và :func:`kv_lookup_keys` cùng đi qua ``kv_history_basis_entry`` (Codex GĐ2-B lượt 2 P4).
#: Loại phép tra mà bộ quyết định KV yêu cầu.
KV_LOOKUP_COMMUNE = "commune"
KV_LOOKUP_SCHOOL = "school"
#: L3 (điều phối 22-11, Phần C mục 2): cờ trường PT dân tộc nội trú (``vn_school.is_dtnt``) — khoá = id trường, năm = ``None``.
KV_LOOKUP_SCHOOL_DTNT = "school_dtnt"


class KvLookup(NamedTuple):
    """Một phép tra danh mục KV mà bộ quyết định cần: ``(loại, khoá, năm)`` — ``commune``: khoá = mã xã (``_lookup_commune_kv``);
    ``school``: khoá = id trường (``lookup_kv_for_school_year``); ``school_dtnt``: khoá = id trường, năm ``None``
    (``lookup_school_is_dtnt``)."""

    kind: str
    key: Any
    year: Any


class KvLookupNotLoaded(RuntimeError):
    """Đường lô: bộ quyết định cần một phép tra mà lượt nạp KHÔNG có trong bản đồ — fail-closed (nơi gọi coi như "không tính lại
    được"), KHÔNG đoán ``None``. Chỉ id / năm trong thông điệp."""


async def resolve_kv_for_profile(
    profile: "AdmissionProfile",
    db: "AsyncSession",
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> tuple[Optional[str], dict[str, Any]]:
    """Resolve KV cho profile per TT 05/2021 Phụ lục 01 — BỘ ĐỌC TỪNG HỒ SƠ quanh bộ quyết định :func:`_kv_resolution_steps`.

    GĐ2-B đợt 2 (K1 — đề cương đợt 2 §3): luật nằm TRỌN trong bộ quyết định (generator thuần, không đọc CSDL); hàm này chỉ trả
    lời từng phép tra nó yêu cầu bằng ĐÚNG hai hàm đọc cũ (``_lookup_commune_kv`` / ``lookup_kv_for_school_year``, gọi qua tên
    module — test bọc được), đúng thứ tự và đúng số lần như trước. Đường lô (:func:`decide_kv_for_profile`) trả lời cùng bộ
    quyết định từ bản đồ đã nạp bằng MỘT câu ⇒ một nguồn luật cho T1 / T6 / bản in GĐ1 / máy xét GĐ2-B. Tham số, giá trị trả,
    nhánh lỗi: xem :func:`_kv_resolution_steps`."""
    steps = _kv_resolution_steps(profile, target_level=target_level, admission_type=admission_type)
    try:
        request = next(steps)
        while True:
            if request.kind == KV_LOOKUP_COMMUNE:
                answer = await _lookup_commune_kv(db, request.key, request.year)
            elif request.kind == KV_LOOKUP_SCHOOL_DTNT:
                answer = await lookup_school_is_dtnt(db, request.key)
            else:
                answer = await lookup_kv_for_school_year(db, request.key, request.year)
            request = steps.send(answer)
    except StopIteration as done:
        return done.value


def decide_kv_for_profile(
    profile: "AdmissionProfile",
    *,
    commune_kv: Mapping[tuple[Any, Any], Optional[str]],
    school_kv: Mapping[tuple[Any, Any], Optional[str]],
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
    school_dtnt: Optional[Mapping[Any, Optional[bool]]] = None,
) -> tuple[Optional[str], dict[str, Any]]:
    """Đường LÔ của :func:`resolve_kv_for_profile`: CÙNG bộ quyết định, mỗi phép tra trả lời từ bản đồ đã nạp —
    ``commune_kv[(mã xã, năm)]`` / ``school_kv[(id trường, năm)]`` (giá trị ``None`` = danh mục không có hàng, như hai hàm đọc);
    ``school_dtnt[id trường]`` (L3 — cờ DTNT, ``None`` = không có trường; khoá từ :func:`kv_school_dtnt_keys`).
    Khoá vắng trong bản đồ ⇒ :class:`KvLookupNotLoaded` (không đoán; ``school_dtnt`` không truyền = bản đồ rỗng). Không đọc CSDL."""
    steps = _kv_resolution_steps(profile, target_level=target_level, admission_type=admission_type)
    try:
        request = next(steps)
        while True:
            if request.kind == KV_LOOKUP_SCHOOL_DTNT:
                table, key = (school_dtnt or {}), request.key
            else:
                table = commune_kv if request.kind == KV_LOOKUP_COMMUNE else school_kv
                key = (request.key, request.year)
            if key not in table:
                steps.close()
                raise KvLookupNotLoaded(
                    "Thiếu phép tra KV %s cho hồ sơ %s (năm %r)."
                    % (request.kind, getattr(profile, "id", None), request.year)
                )
            request = steps.send(table[key])
    except StopIteration as done:
        return done.value


def kv_lookup_keys(
    profile: "AdmissionProfile",
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> tuple[frozenset, frozenset]:
    """Tập KHOÁ TRA (bao trùm) mà bộ quyết định có thể cần cho ``profile`` — ``(xã: {(mã xã, năm)}, trường: {(id trường, năm)})``
    — để đường lô nạp TRƯỚC bằng hai câu cho mọi hồ sơ. Chỉ khoá đúng kiểu (mã xã chuỗi; id trường / năm số nguyên); dữ liệu
    lạ không sinh khoá ⇒ bộ quyết định gặp khoá vắng ⇒ :class:`KvLookupNotLoaded` (fail-closed).

    Dựng bằng CHÍNH các helper G5 của bộ quyết định (Codex GĐ2-B lượt 2 P4 / P5 — không giữ luật năm riêng): mục =
    ``kv_history_basis_entry`` không có mã dừng ``kv_entry_problem`` (mục dừng ⇒ bộ quyết định dừng trước mọi phép tra); năm đếm =
    ``kv_entry_school_years``; ứng viên trường tốt nghiệp = ``kv_last_school_year`` của MỌI mục ấy, kể cả mục thiếu / ngược
    ``year_from`` (bị bỏ khỏi phép đếm nhưng vẫn được xếp ở bước hoà)."""
    communes, schools, _dtnt = _kv_lookup_plan(profile, target_level=target_level, admission_type=admission_type)
    return communes, schools


def kv_school_dtnt_keys(
    profile: "AdmissionProfile",
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> frozenset:
    """L3: id trường cần tra cờ DTNT (``school_dtnt`` của :func:`decide_kv_for_profile`) — CÙNG kế hoạch với :func:`kv_lookup_keys`."""
    return _kv_lookup_plan(profile, target_level=target_level, admission_type=admission_type)[2]


def _kv_lookup_plan(
    profile: "AdmissionProfile",
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> tuple[frozenset, frozenset, frozenset]:
    """``(khoá xã, khoá trường theo năm, id trường cần cờ DTNT)`` — MỘT nơi dựng mọi khoá tra cho đường lô."""
    try:
        kv_year = priority_academic_year(profile)
    except ValueError:
        return frozenset(), frozenset(), frozenset()
    history = getattr(profile, "academic_history", None) or []
    basis, _ = _derive_kv_basis_level(
        cultural=getattr(profile, "cultural_education_level", None),
        vocational=getattr(profile, "vocational_qualification", "none") or "none",
        target_level=target_level,
        admission_type=admission_type,
        academic_history=history,
        area_resolution_basis=getattr(profile, "area_resolution_basis", None),
        previous_snapshot=getattr(profile, "priority_resolution_snapshot", None),
    )
    communes: set = set()
    schools: set = set()
    dtnt: set = set()
    if basis in ("COMMUNE_SPECIAL", "THUONG_TRU"):
        commune_code = getattr(profile, "permanent_commune_code", None)
        if isinstance(commune_code, str) and commune_code:
            communes.add((commune_code, kv_year))
    elif basis == "LICH_SU_THPT":
        for entry in history:
            if not kv_history_basis_entry(entry) or kv_entry_problem(entry) is not None:
                continue
            sid = entry.get("school_id")
            if not _history_int(sid):  # MỘT helper "số nguyên thật" với bộ quyết định (bỏ bản trùng ``_plain_int`` — Codex B'3)
                continue
            y_from, y_to = entry.get("year_from"), entry.get("year_to")
            last_year = kv_last_school_year(entry)
            if _history_int(last_year):
                schools.add((sid, last_year))
            if _history_int(y_from) and _history_int(y_to) and y_to >= y_from:
                for year in kv_entry_school_years(entry):
                    schools.add((sid, year))
    elif basis == KV_BASIS_THCS_HISTORY:
        # L3: CÙNG kế hoạch dòng THCS với bộ quyết định (:func:`kv_thcs_history_plan`) — có dòng dừng ⇒ bộ quyết định dừng trước
        # mọi phép tra ⇒ không cần khoá. Dòng đếm được đã có ``school_id`` / năm là số nguyên.
        entries, problems = kv_thcs_history_plan(history)
        if not problems:
            for entry in entries:
                sid = entry["school_id"]
                dtnt.add(sid)
                schools.add((sid, kv_entry_thcs_last_school_year(entry)))
                for year in kv_entry_thcs_school_years(entry):
                    schools.add((sid, year))
    return frozenset(communes), frozenset(schools), frozenset(dtnt)


def _kv_count_school_years(
    entries: list,
    years_of: Callable[[dict], range] = kv_entry_school_years,
) -> Generator[KvLookup, Optional[str], tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]]:
    """Vòng ĐẾM NĂM HỌC theo KV của luật học nhiều trường — MỘT nguồn cho nhánh THPT (``LICH_SU_THPT``) và nhánh THCS (L3,
    ``LICH_SU_THCS``): mỗi năm học (khoá năm bắt đầu — ``years_of``: :func:`kv_entry_school_years` cho THPT,
    :func:`kv_entry_thcs_school_years` cho THCS, cùng chỗ cắt liên cấp) một phép tra KV trường theo năm. Trả
    ``(số năm theo KV, breakdown từng mục, các phép tra không ra hàng)``. Mục thiếu / ngược năm bị bỏ qua (hành vi THPT cũ; nhánh
    THCS đã loại các mục ấy ở :func:`kv_thcs_entry_case`)."""
    kv_years: dict[str, int] = {}
    breakdown_entries: list[dict[str, Any]] = []
    missing_lookups: list[dict[str, Any]] = []

    for entry in entries:
        sid = entry["school_id"]
        y_from = entry.get("year_from")
        y_to = entry.get("year_to")
        if y_from is None or y_to is None or y_to < y_from:
            continue

        entry_years_by_kv: list[dict[str, Any]] = []
        # G5: khoá NĂM BẮT ĐẦU của từng năm học thực học (``year_from .. year_to − 1``); liên cấp chỉ phần của nhánh (THPT: lớp
        # 10..``grade_to``; THCS: lớp 6–9).
        school_years = years_of(entry)
        for year in school_years:
            kv = yield KvLookup(KV_LOOKUP_SCHOOL, sid, year)
            if kv:
                kv_years[kv] = kv_years.get(kv, 0) + 1
                entry_years_by_kv.append({"year": year, "kv": kv})
            else:
                missing_lookups.append({"school_id": sid, "year": year})

        breakdown_entries.append(
            {
                "school_id": sid,
                "school_name_at_time": entry.get("school_name"),
                "year_from": y_from,
                "year_to": y_to,
                "counted_school_years": list(school_years),
                "years_by_kv": entry_years_by_kv,
            }
        )
    return kv_years, breakdown_entries, missing_lookups


#: ``pathway`` của hai nhánh L3.
KV_PATHWAY_THCS_HISTORY = "lich_su_thcs"
KV_PATHWAY_PENDING_VERIFICATION = "cho_xac_minh"
#: ``reason`` của "KV chờ xác minh" (snapshot ``reason``) — câu hiển thị ở ``kv-labels.ts`` (FE).
KV_PENDING_REASON_NEEDS_VERIFICATION = "kv_basis_needs_manual_verification"
KV_PENDING_REASON_THCS_MISSING = "thcs_history_missing"
KV_PENDING_REASON_THCS_NOT_IN_CATALOG = "thcs_school_not_in_catalog"
KV_PENDING_REASON_THCS_INCONSISTENT = "thcs_history_inconsistent"
KV_PENDING_REASON_THCS_KV_MISSING = "thcs_school_kv_missing"
KV_PENDING_REASON_THCS_TIED = "thcs_tied_graduation_school"
KV_PENDING_REASON_THCS_DTNT = "thcs_school_dtnt"


def _kv_thcs_history_steps(
    academic_history: list,
    meta_base: Callable[..., dict[str, Any]],
) -> Generator[KvLookup, Optional[str], tuple[Optional[str], dict[str, Any]]]:
    """Nhánh ``LICH_SU_THCS`` (L3): KV theo các dòng THCS có trường trong danh mục — khu vực học lâu nhất (cùng vòng đếm với THPT),
    hoà ⇒ KV trường tốt nghiệp lớp 9 (MỘT luật hoà với THPT — :func:`kv_graduation_pick`) tra ở năm học lớp 9
    (:func:`kv_entry_thcs_last_school_year`). MỌI ca không tính được ⇒ "KV chờ xác minh" (:data:`KV_PENDING_VERIFICATION_RULE`,
    ``requires_manual_override``), ``reason`` nói đúng việc cán bộ cần làm — kể cả lớp trống / sai kiểu (owner 23-11 (a)) hoặc lớp cuối
    phần THCS ngoài 6–9 (owner 24-11) ở nhóm tốt nghiệp khi hoà."""
    pathway = KV_PATHWAY_THCS_HISTORY

    def _pending(reason: str, breakdown: dict[str, Any]) -> tuple[None, dict[str, Any]]:
        return None, meta_base(
            rule_applied=KV_PENDING_VERIFICATION_RULE,
            pathway=pathway,
            requires_manual_override=True,
            reason=reason,
            breakdown=breakdown,
        )

    entries, problems = kv_thcs_history_plan(academic_history)
    if problems:
        only_not_in_catalog = all(p["case"] == KV_THCS_ENTRY_WITHOUT_SCHOOL for p in problems)
        return _pending(
            KV_PENDING_REASON_THCS_NOT_IN_CATALOG if only_not_in_catalog else KV_PENDING_REASON_THCS_INCONSISTENT,
            {"entries": problems},
        )
    if not entries:
        return _pending(KV_PENDING_REASON_THCS_MISSING, {"entries": []})

    # Điều phối 22-11 (Phần C mục 2): trường PT DTNT ⇒ diện hộ khẩu (TT 05 PL01 5.b) ⇒ "chờ xác minh", xác minh bằng ấn định tay; không
    # tự tính theo KV trường. Mỗi trường một lần tra, theo thứ tự xuất hiện. Không có trường (id lạ) ⇒ "chưa có trong danh mục".
    dtnt_ids: list = []
    unknown_ids: list = []
    for sid in dict.fromkeys(e["school_id"] for e in entries):
        flag = yield KvLookup(KV_LOOKUP_SCHOOL_DTNT, sid, None)
        if flag is None:
            unknown_ids.append(sid)
        elif flag:
            dtnt_ids.append(sid)
    if unknown_ids:
        return _pending(KV_PENDING_REASON_THCS_NOT_IN_CATALOG, {"entries": [], "unknown_school_ids": unknown_ids})
    if dtnt_ids:
        return _pending(KV_PENDING_REASON_THCS_DTNT, {"entries": [], "dtnt_school_ids": dtnt_ids})

    kv_years, breakdown_entries, missing_lookups = yield from _kv_count_school_years(entries, kv_entry_thcs_school_years)
    if missing_lookups or not kv_years:
        # Trường THCS chưa có KV cho một / mọi năm học (Q19(d)(ii): không tính từ phần còn lại).
        return _pending(
            KV_PENDING_REASON_THCS_KV_MISSING,
            {"entries": breakdown_entries, "kv_totals": kv_years, "missing_lookups": missing_lookups},
        )

    max_yrs = max(kv_years.values())
    winners = [kv for kv, y in kv_years.items() if y == max_yrs]
    breakdown_base = {"entries": breakdown_entries, "kv_totals": kv_years, "winner_years": max_yrs}
    if len(winners) == 1:
        return winners[0], meta_base(rule_applied="longest_duration", pathway=pathway, breakdown=breakdown_base)

    # Bước hoà: MỘT luật với nhánh THPT (:func:`kv_graduation_pick`) trên phần THCS — năm kết thúc phần THCS, lớp cuối phần THCS
    # (liên cấp ⇒ 9). Owner 23-11 (a): lớp trống / null / sai kiểu — và owner 24-11: lớp cuối phần THCS ngoài 6–9
    # (:func:`kv_entry_thcs_last_grade` ⇒ ``None``) — ở nhóm tốt nghiệp ⇒ KHÔNG coi là 0 / so như số mà "KV chờ xác minh" — cùng
    # đường với hai dòng ngang nhau cả năm lẫn lớp (``thcs_tied_graduation_school``; cổng nộp cho qua, T6 dừng có nhãn, F231
    # ``khu_vuc_cho_xac_minh``), như THPT dùng chung đường M1 cho hai ca ấy.
    grad_entry, undecided = kv_graduation_pick(entries, kv_entry_thcs_end_year, kv_entry_thcs_last_grade)
    if grad_entry is None:
        return _pending(
            KV_PENDING_REASON_THCS_TIED,
            {**breakdown_base, "tied_kv": winners, "tied_entries": [e["school_id"] for e in undecided]},
        )
    grad_lookup_year = kv_entry_thcs_last_school_year(grad_entry)
    grad_kv = yield KvLookup(KV_LOOKUP_SCHOOL, grad_entry["school_id"], grad_lookup_year)
    graduation = {
        "tied_kv": winners,
        "graduation_school_id": grad_entry["school_id"],
        "graduation_year": kv_entry_thcs_end_year(grad_entry),
        "graduation_lookup_year": grad_lookup_year,
    }
    if grad_kv is None:
        return _pending(KV_PENDING_REASON_THCS_KV_MISSING, {**breakdown_base, **graduation})
    return grad_kv, meta_base(
        rule_applied="tiebreak_graduation_school", pathway=pathway, breakdown={**breakdown_base, **graduation}
    )


def _kv_resolution_steps(
    profile: "AdmissionProfile",
    *,
    target_level: Optional[str] = None,
    admission_type: Optional[str] = None,
) -> Generator[KvLookup, Optional[str], tuple[Optional[str], dict[str, Any]]]:
    """BỘ QUYẾT ĐỊNH KV (thuần, không đọc CSDL): mỗi phép tra danh mục là một ``yield KvLookup(...)``; nơi gọi gửi lại kết quả
    (``None`` = không có hàng). Trả ``(kv_code, meta)`` qua ``StopIteration.value``. Hai nơi gọi: :func:`resolve_kv_for_profile`
    (từng hồ sơ, đọc CSDL) và :func:`decide_kv_for_profile` (lô). Phần dưới là docstring luật gốc (``db`` = nơi gọi tra).

    Resolve KV cho profile per TT 05/2021 Phụ lục 01.

    Phase E.4 (commit 5) refactor — pipeline:
       Eligibility (upstream gate) → Exception → Auto basis → Resolve KV
       → Apply path bonus (caller) → Snapshot (freeze).

    Fail-closed: tuyệt đối KHÔNG silent 0đ. Khi catalog/data thiếu, trả
    rule_applied đặc tả lỗi:
      - "catalog_gap_school"      — vn_school_kv_assignment thiếu row (mọi năm, hoặc MỘT PHẦN năm — Q19(d))
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
    # Temporal KV: resolve commune KV as-of the profile's admission year so a
    # mid-year KV reclassification doesn't silently mis-score. Mirrors the
    # academic_year semantics of lookup_kv_for_school_year. Năm tuyển sinh của
    # hồ sơ luôn có (NOT NULL) — không rơi về năm của máy (owner Q10(a)).
    kv_year = priority_academic_year(profile)

    basis, basis_reason = _derive_kv_basis_level(
        cultural=cultural,
        vocational=vocational,
        target_level=target_level,
        admission_type=admission_type,
        academic_history=academic_history,
        area_resolution_basis=area_basis,
        previous_snapshot=getattr(profile, "priority_resolution_snapshot", None),
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
        kv = yield KvLookup(KV_LOOKUP_COMMUNE, commune_code, kv_year)
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
        kv = yield KvLookup(KV_LOOKUP_COMMUNE, commune_code, kv_year)
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

    # --- L3: sơ cấp / nhánh cũ không truyền trình độ — "KV chờ xác minh" (không tra danh mục nào). ---
    if basis == KV_BASIS_PENDING_VERIFICATION:
        return None, _meta_base(
            rule_applied=KV_PENDING_VERIFICATION_RULE,
            pathway=KV_PATHWAY_PENDING_VERIFICATION,
            requires_manual_override=True,
            reason=KV_PENDING_REASON_NEEDS_VERIFICATION,
        )

    # --- L3: trung cấp sau THCS — KV theo nơi học THCS (trường trong danh mục). ---
    if basis == KV_BASIS_THCS_HISTORY:
        return (yield from _kv_thcs_history_steps(academic_history, _meta_base))

    # --- LICH_SU_THPT: multi-school rule TT 05/2021 Phụ lục 01 Mục 5.a. ---
    # Aggregate duration per KV qua academic_history, longest duration wins,
    # tie → graduation school (year_to + grade_to).
    # G5 (owner 22-11): tập mục = MỘT vị từ ``kv_history_basis_entry`` (chung với ``_has_thpt_history`` và :func:`kv_lookup_keys`) —
    # mục liên cấp chỉ có năm THCS (lớp kết thúc ≤ 9) KHÔNG đóng góp năm nào và KHÔNG là ứng viên trường tốt nghiệp (như mục THCS).
    basis_entries = [e for e in academic_history if kv_history_basis_entry(e)]

    pathway = "lich_su_thpt"

    if not basis_entries:
        return None, _meta_base(
            rule_applied="insufficient_data",
            pathway=pathway,
            requires_manual_override=True,
            reason="no_qualifying_thpt_history_entries",
            breakdown={"entries": []},
        )

    # G5: mục lệch (liên cấp thiếu lớp kết thúc; mục 0 năm học) ⇒ DỪNG có nhãn, liệt kê MỌI mục lệch (cán bộ sửa một lần), không
    # tra danh mục, không tự xác định KV. ``insufficient_data`` nằm ngoài whitelist ⇒ cổng nộp chặn; T6 dừng ``PRIORITY_KV_UNRESOLVED``.
    inconsistent = [
        {
            "index": i,
            "level": e.get("level"),
            "grade_to": e.get("grade_to"),
            "year_from": e.get("year_from"),
            "year_to": e.get("year_to"),
            "case": problem,
        }
        for i, e in enumerate(academic_history)
        if kv_history_basis_entry(e)
        for problem in (kv_entry_problem(e),)
        if problem is not None
    ]
    if inconsistent:
        return None, _meta_base(
            rule_applied="insufficient_data",
            pathway=pathway,
            requires_manual_override=True,
            reason=KV_HISTORY_INCONSISTENT_REASON,
            breakdown={"entries": inconsistent},
        )

    # Per-year KV duration map + breakdown per entry. Track lookup failures
    # explicit để fail-closed (catalog_gap_school). MỘT vòng đếm cho THPT và THCS (L3): :func:`_kv_count_school_years`.
    kv_years, breakdown_entries, missing_lookups = yield from _kv_count_school_years(basis_entries)

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

    if missing_lookups:
        # Owner Q19(d)(ii): MỘT PHẦN năm/trường thiếu danh mục KV ⇒ DỪNG có nhãn, không tính KV từ phần còn lại.
        # Trước đây bỏ các năm thiếu rồi vẫn chọn KV thắng (``partial_catalog_missing``) — KV thắng có thể chỉ do
        # năm của trường thiếu danh mục bị loại khỏi phép đếm. Chặn Ở ĐÂY (nhánh resolver), không ở tầng gọi:
        # nhìn từ ngoài, ca này ra một KV hợp lệ nên guard "không xác định được KV" không thấy.
        return None, _meta_base(
            rule_applied="catalog_gap_school",
            pathway=pathway,
            requires_manual_override=True,
            reason="some_school_lookups_failed",
            breakdown={
                "entries": breakdown_entries,
                "kv_totals": kv_years,
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

    if len(winners) == 1:
        return winners[0], _meta_base(
            rule_applied="longest_duration",
            pathway=pathway,
            breakdown=breakdown_base,
        )

    # Tiebreak: graduation school (highest year_to + grade_to, stable index) — MỘT luật hoà với nhánh THCS: :func:`kv_graduation_pick`
    # (bộ truy cập mặc định ``year_to`` / ``grade_to``). Hai ca ra ``(None, …)`` cùng đường M1 (hoà không phân định ⇒ cần xét tay,
    # cùng mã lý do):
    # * owner GO 22-11 + owner 23-11 (a): mục có thể là trường tốt nghiệp mà thiếu / sai kiểu year_to / grade_to ⇒ KHÔNG so (tránh
    #   TypeError của khoá sắp xếp) — ``tied_entries`` = các mục ấy;
    # * M1: hai mục đầu NHÓM year_to lớn nhất cùng year_to + grade_to — ``tied_entries`` = hai mục ấy.
    # Chỉ xếp NHÓM year_to lớn nhất (rà hợp nhất 23-11 B-H1): nhóm thấp có thể có hai mục cùng năm, một lớp null / chuỗi, một lớp số ⇒
    # xếp chung buộc so hai lớp ấy ⇒ TypeError. Dữ liệu đúng kiểu: kết quả như xếp toàn bộ cũ.
    grad_entry, undecided = kv_graduation_pick(basis_entries)
    if grad_entry is None:
        return None, _meta_base(
            rule_applied="ambiguous_requires_manual",
            pathway=pathway,
            requires_manual_override=True,
            reason="tied_graduation_year_and_grade",
            breakdown={
                **breakdown_base,
                "tied_kv": winners,
                "tied_entries": [e["school_id"] for e in undecided],
            },
        )

    # G5 (owner 22-11): tra trường tốt nghiệp ở NĂM HỌC CUỐI (khoá năm bắt đầu ``year_to − 1``), không phải năm sau tốt nghiệp.
    # ``graduation_lookup_year`` ghi ĐÚNG khoá đã đem tra (Codex G5 P1) — ``graduation_year`` vẫn là ``year_to`` như cũ.
    grad_lookup_year = kv_last_school_year(grad_entry)
    grad_kv = yield KvLookup(KV_LOOKUP_SCHOOL, grad_entry["school_id"], grad_lookup_year)
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
                "graduation_lookup_year": grad_lookup_year,
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
            "graduation_lookup_year": grad_lookup_year,
        },
    )


# =============================================================================
# B1 (2026-09-13) — Bảo toàn override KV hợp lệ QUA freeze, kèm dấu vết phê duyệt
# =============================================================================
#
# Vì sao khối này tồn tại
# -----------------------
# ``resolve_kv_for_profile`` trả ``(None, {"rule_applied": "manual_override"})``
# cho nhánh ``basis == "MANUAL"``: engine cố ý KHÔNG tự resolve và giao cho
# caller giữ lại ``kv_resolved`` đang có. ``freeze_priority_snapshot`` thì lại
# dựng snapshot MỚI từ số 0 ⇒ ``kv_resolved`` về ``None`` và mất trọn
# ``manual_override_by/_at/_reason``. Hậu quả đo được:
#   * submit: ``_kv_unresolved_error_message`` chặn (ồn ào, nhưng thấy được);
#   * T6 (``admission_choice_engine_service`` freeze rồi
#     ``calculate_priority_bonus``): ``_resolve_area_bonus`` đọc
#     ``snapshot["kv_resolved"]`` → ``None`` → ``return _ZERO`` — 0 điểm khu
#     vực, không lỗi, không log. Cột fallback ``high_school_kv_resolved`` đã
#     DROP ở phase1_09 nên không cứu được.
#
# Vì sao KHÔNG được "cứ giữ lại kv_resolved cũ"
# ---------------------------------------------
# ``area_resolution_basis`` nhận giá trị ``'manual_override'`` qua ``PUT
# /api/admissions/{id}`` thường (schema cho phép, service ghi thẳng). Nếu freeze
# tin cái nhãn ấy thì bất kỳ ai sửa được hồ sơ draft cũng "đóng dấu thủ công"
# lên một KV do engine tính ra — kể cả KV tính từ dữ liệu đã bị sửa lại sau đó.
# Nhãn ``MANUAL`` và "kv_resolved khác null" LÀ THỨ CẦN CHỨNG MINH, không phải
# bằng chứng.
#
# Căn cứ độc lập
# --------------
# Đường override được phép DUY NHẤT (``priority_override_service.override_kv``,
# gọi từ ``POST /api/v2/admissions/{id}/override-priority-kv``) INSERT một hàng
# ``priority_audit_log`` với ``action_type='kv_manual_override'`` trong CÙNG
# transaction với việc ghi snapshot. Đường ``PUT`` thường KHÔNG sinh hàng nào.
# Hàng audit ấy — chứ không phải nhãn trong snapshot — là căn cứ.
#
# Năm điều kiện HẾT HIỆU LỰC (fail-closed, dẫn từ mã):
#   1. Không có hàng audit nào  -> ``no_audit_row``
#      (đúng ca ``PUT`` thường + ca snapshot bị vá tay).
#   2. ``audit.actor_id`` khác ``snapshot.manual_override_by`` hoặc
#      ``audit.new_value.kv_resolved`` khác ``snapshot.kv_resolved`` ->
#      ``audit_row_mismatch_*``. Khoá snapshot vào ĐÚNG quyết định đã ghi sổ.
#   3. ``audit.metadata.actor_role`` ngoài {admin, manager} ->
#      ``actor_role_not_allowed``. Đây là ca thật, không phải giả định: trước
#      "Phase E.4 commit 7" (``priority_override_service`` ~dòng 283) officer
#      ĐƯỢC override submitted/reviewing/revision_requested; các hàng ấy nay
#      không còn hợp lệ.
#   4. ``|audit.created_at - snapshot.manual_override_at|`` > 300s ->
#      ``timestamp_out_of_band``. Chặn ca snapshot mang dấu override MỚI HƠN
#      mọi hàng đã ghi sổ.
#   5. Vân tay đầu vào KV lúc override khác vân tay tính lại lúc freeze ->
#      ``stale_inputs``. Người duyệt đã quyết trên MỘT bộ dữ liệu; dữ liệu đổi
#      thì quyết định ấy hết hiệu lực, phải duyệt lại.
#      Hàng audit CŨ (ghi trước bản vá này) không có vân tay ->
#      ``provenance_incomplete_no_fingerprint`` — cũng fail-closed: không
#      chứng minh được thì không công nhận.
#
# Vân tay CHỈ gồm đầu vào mà ``resolve_kv_for_profile`` thật sự đọc để ra KV
# (văn hoá, chuyên môn, mã xã thường trú, năm tuyển sinh, lịch sử học tập).
# KHÔNG gồm ngành / NV1 / phương thức: khi ``basis == MANUAL`` engine bỏ qua
# chúng, và "đổi ngành thì override còn hiệu lực không" là câu hỏi NGHIỆP VỤ
# chưa có quyết định ở đâu trong mã. Đưa chúng vào đây là tự đặt chính sách.
#
# Guard ``_KV_SUCCESS_RULE_APPLIED`` / ``_kv_unresolved_error_message`` trong
# ``admission_service`` KHÔNG bị đụng tới: ca không chứng minh được xuất xứ đi
# ra với ``rule_applied='manual_override_unverified'`` — một giá trị NGOÀI
# whitelist ấy — nên cổng submit chặn y như cũ mà không phải nới một chữ nào.

_MANUAL_OVERRIDE_KV_CODES = frozenset({"KV1", "KV2-NT", "KV2", "KV3"})
_MANUAL_OVERRIDE_ALLOWED_ACTOR_ROLES = frozenset({"admin", "manager"})
# Khớp ``priority_override_service._MIN_REASON_LEN`` (20). Không import chéo:
# module ấy import ngược lại priority_service ở tầng hàm.
_MANUAL_OVERRIDE_MIN_REASON_LEN = 20
# Hàng audit lấy ``created_at`` từ DB (server default), snapshot lấy giờ Python
# của cùng transaction => lệch mili-giây là bình thường; 300s là biên rộng rãi
# mà vẫn chặn được ca "đóng dấu lại sau này".
_MANUAL_OVERRIDE_MAX_CLOCK_SKEW_SECONDS = 300
_MANUAL_OVERRIDE_UNVERIFIED_RULE = "manual_override_unverified"
# Khoá audit_metadata mang vân tay đầu vào KV tại thời điểm override.
KV_INPUTS_FINGERPRINT_KEY = "kv_inputs_fingerprint"


def kv_inputs_fingerprint(profile: "AdmissionProfile") -> str:
    """sha256 của ĐÚNG những đầu vào quyết định KV mà engine đọc.

    Đọc thẳng từ ``resolve_kv_for_profile`` + ``_derive_kv_basis_level``:
    ``cultural_education_level``, ``vocational_qualification``,
    ``permanent_commune_code``, ``academic_year`` (biến ``kv_year``) và
    ``academic_history``. Từ ``academic_history`` chỉ lấy các khoá mà luật
    multi-school TT 05/2021 Phụ lục 01 Mục 5.a dùng (``school_id``/``level``/
    ``year_from``/``year_to``/``grade_to``/``graduation_type``) — thêm GPA hay
    đổi thứ tự phần tử KHÔNG được làm hết hiệu lực một quyết định đúng.

    CỐ Ý KHÔNG có ``area_resolution_basis``: chính nó là công tắc bật nhánh
    MANUAL, đưa vào thì vân tay tự mâu thuẫn. Cũng CỐ Ý không có
    ``target_level``/``admission_type``: nhánh MANUAL bỏ qua chúng.
    """
    import hashlib
    import json

    history = getattr(profile, "academic_history", None) or []
    normalised: list[dict[str, Any]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        normalised.append(
            {
                "school_id": entry.get("school_id"),
                "level": entry.get("level"),
                "year_from": entry.get("year_from"),
                "year_to": entry.get("year_to"),
                "grade_to": entry.get("grade_to"),
                "graduation_type": entry.get("graduation_type"),
            }
        )
    # Sắp xếp tất định: thứ tự phần tử trong JSONB không mang nghĩa nghiệp vụ.
    normalised.sort(key=lambda e: json.dumps(e, sort_keys=True, default=str))

    payload = {
        "cultural_education_level": getattr(
            profile, "cultural_education_level", None
        ),
        "vocational_qualification": getattr(profile, "vocational_qualification", None)
        or "none",
        "permanent_commune_code": getattr(profile, "permanent_commune_code", None),
        "academic_year": getattr(profile, "academic_year", None),
        "academic_history": normalised,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_iso_utc(raw: Any) -> Optional[datetime]:
    """ISO-8601 str (hoặc datetime) -> aware UTC datetime; None khi không đọc được."""
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def verify_manual_override_provenance(
    db: "AsyncSession",
    profile: "AdmissionProfile",
) -> tuple[bool, Optional[str], dict[str, Any]]:
    """Override KV đang khai trong snapshot có ĐƯỢC PHÉP không?

    Returns ``(ok, refuse_reason, evidence)``:
      * ``ok=True``  -> ``evidence`` mang các khoá dấu vết để chép vào snapshot
        mới (``manual_override_*``, ``kv_resolved``, ``manual_override_audit_id``).
      * ``ok=False`` -> ``refuse_reason`` là mã snake_case để ghi vào
        ``snapshot["reason"]`` + log.

    Fail-closed ở MỌI nhánh. Xem khối chú thích phía trên cho 5 điều kiện.

    GĐ2-B đợt 2 (đề cương §3): luật nằm ở hai hàm thuần :func:`manual_override_claim_refusal` (ảnh chụp) và
    :func:`decide_manual_override_provenance` (đối chiếu sổ); hàm này chỉ ĐỌC hàng sổ mới nhất của MỘT hồ sơ (đúng câu cũ, chỉ
    đọc khi ảnh chụp qua kiểm). Đường lô đọc hàng sổ của MỌI hồ sơ bằng :func:`latest_manual_override_audit_rows` rồi gọi cùng
    hàm thuần.
    """
    from app.models.priority_audit import PriorityAuditLog

    refusal = manual_override_claim_refusal(profile)
    if refusal is not None:
        return False, refusal, {}

    stmt = (
        select(PriorityAuditLog)
        .where(
            PriorityAuditLog.profile_id == profile.id,
            PriorityAuditLog.action_type == _MANUAL_OVERRIDE_AUDIT_ACTION,
        )
        .order_by(PriorityAuditLog.created_at.desc(), PriorityAuditLog.id.desc())
        .limit(1)
    )
    audit_row = (await db.execute(stmt)).scalars().first()
    return decide_manual_override_provenance(profile, audit_row)


#: ``priority_audit_log.action_type`` của đường override KV DUY NHẤT (``priority_override_service.override_kv``).
_MANUAL_OVERRIDE_AUDIT_ACTION = "kv_manual_override"


async def latest_manual_override_audit_rows(db: Any, profile_ids: Sequence[int]) -> dict[int, Any]:
    """Đường LÔ của phần đọc sổ trong :func:`verify_manual_override_provenance`: hàng ``kv_manual_override`` MỚI NHẤT của từng hồ
    sơ (cùng thứ tự ``created_at`` giảm rồi ``id`` giảm — ``DISTINCT ON``) bằng MỘT câu (kể cả danh sách rỗng). Hồ sơ không có
    hàng ⇒ vắng khoá.
    ``db``: phiên ORM (kể cả phiên trên kết nối ảnh chụp chỉ đọc)."""
    from sqlalchemy import Integer, any_, bindparam
    from sqlalchemy.dialects.postgresql import ARRAY

    from app.models.priority_audit import PriorityAuditLog

    ids = sorted({int(p) for p in profile_ids})
    stmt = (
        select(PriorityAuditLog)
        .where(
            # Tham số MẢNG (một tham số, không chia khúc) và chạy cả khi rỗng — số câu không theo số hồ sơ (owner Q3 22-11).
            PriorityAuditLog.profile_id == any_(bindparam("ids", ids, type_=ARRAY(Integer))),
            PriorityAuditLog.action_type == _MANUAL_OVERRIDE_AUDIT_ACTION,
        )
        .distinct(PriorityAuditLog.profile_id)
        .order_by(
            PriorityAuditLog.profile_id,
            PriorityAuditLog.created_at.desc(),
            PriorityAuditLog.id.desc(),
        )
    )
    return {int(r.profile_id): r for r in (await db.execute(stmt)).scalars()}


def manual_override_claim_refusal(profile: Any) -> Optional[str]:
    """Bước 1 (thuần) của :func:`verify_manual_override_provenance`: ảnh chụp có khai override ĐỦ dạng không — ``None`` = đủ;
    không thì mã từ chối (``no_prior_snapshot`` / ``snapshot_kv_invalid`` / ``snapshot_missing_actor`` /
    ``snapshot_missing_timestamp`` / ``snapshot_reason_too_short``)."""
    snapshot = getattr(profile, "priority_resolution_snapshot", None)
    if not isinstance(snapshot, dict) or not snapshot:
        return "no_prior_snapshot"

    claimed_kv = snapshot.get("kv_resolved")
    claimed_by = snapshot.get("manual_override_by")
    claimed_at = _parse_iso_utc(snapshot.get("manual_override_at"))
    claimed_reason = (snapshot.get("manual_override_reason") or "").strip()

    if claimed_kv not in _MANUAL_OVERRIDE_KV_CODES:
        return "snapshot_kv_invalid"
    if not isinstance(claimed_by, int) or isinstance(claimed_by, bool):
        return "snapshot_missing_actor"
    if claimed_at is None:
        return "snapshot_missing_timestamp"
    if len(claimed_reason) < _MANUAL_OVERRIDE_MIN_REASON_LEN:
        return "snapshot_reason_too_short"
    return None


def decide_manual_override_provenance(
    profile: Any, audit_row: Any
) -> tuple[bool, Optional[str], dict[str, Any]]:
    """Phần QUYẾT ĐỊNH (thuần) của :func:`verify_manual_override_provenance` trên hàng sổ mới nhất ĐÃ ĐỌC (``None`` = không có) —
    cùng 5 điều kiện, cùng mã, cùng ``evidence``. Gọi lại :func:`manual_override_claim_refusal` trước (đường lô không đọc sổ
    riêng cho từng hồ sơ nên không có bước chặn sớm)."""
    refusal = manual_override_claim_refusal(profile)
    if refusal is not None:
        return False, refusal, {}
    snapshot = profile.priority_resolution_snapshot
    claimed_kv = snapshot.get("kv_resolved")
    claimed_by = snapshot.get("manual_override_by")
    claimed_at = _parse_iso_utc(snapshot.get("manual_override_at"))
    claimed_reason = (snapshot.get("manual_override_reason") or "").strip()

    if audit_row is None:
        return False, "no_audit_row", {}

    new_value = audit_row.new_value if isinstance(audit_row.new_value, dict) else {}
    metadata = (
        audit_row.audit_metadata if isinstance(audit_row.audit_metadata, dict) else {}
    )

    if audit_row.actor_id != claimed_by:
        return False, "audit_row_mismatch_actor", {}
    if new_value.get("kv_resolved") != claimed_kv:
        return False, "audit_row_mismatch_kv", {}
    if metadata.get("actor_role") not in _MANUAL_OVERRIDE_ALLOWED_ACTOR_ROLES:
        return False, "actor_role_not_allowed", {}

    audited_at = _parse_iso_utc(audit_row.created_at)
    if audited_at is None:
        return False, "audit_row_missing_timestamp", {}
    if (
        abs((audited_at - claimed_at).total_seconds())
        > _MANUAL_OVERRIDE_MAX_CLOCK_SKEW_SECONDS
    ):
        return False, "timestamp_out_of_band", {}

    audited_fingerprint = metadata.get(KV_INPUTS_FINGERPRINT_KEY)
    if not audited_fingerprint:
        # Hàng audit ghi trước bản vá này: không có gì chứng minh dữ liệu KV
        # còn nguyên như lúc duyệt => không công nhận. Lối ra vận hành là
        # override LẠI qua endpoint (sinh hàng audit mới có vân tay), KHÔNG
        # phải sửa dữ liệu cũ.
        return False, "provenance_incomplete_no_fingerprint", {}
    if audited_fingerprint != kv_inputs_fingerprint(profile):
        return False, "stale_inputs", {}

    evidence = {
        "kv_resolved": claimed_kv,
        "manual_override_by": claimed_by,
        "manual_override_by_name": snapshot.get("manual_override_by_name"),
        "manual_override_at": snapshot.get("manual_override_at"),
        "manual_override_reason": claimed_reason,
        "evidence_file_id": snapshot.get("evidence_file_id"),
        "manual_override_audit_id": audit_row.id,
        "manual_override_actor_role": metadata.get("actor_role"),
        KV_INPUTS_FINGERPRINT_KEY: audited_fingerprint,
    }
    return True, None, evidence


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
      - evaluate_cascade (T6)         → frozen_at_status='engine_T6'

    Mutates ``profile.priority_resolution_snapshot`` directly. Caller is
    responsible for ``await db.flush()`` (no commit — service layer rule).

    ``frozen_at_status`` values this helper writes:
      'submitted_T1' | 'engine_T6'

    Snapshot column ALSO sees ``'manual_override'`` — written directly by
    ``priority_override_service.override_kv`` (NOT via this helper).

    Phase E.4 semantics — ``frozen_at_status='submitted_T1'`` indicates the
    snapshot was frozen DURING a submit attempt; it does NOT imply the
    submit succeeded. Since commit ``dd108eb2`` (Phase E.4), submit
    aggregates KV unresolved/resolution_failed into ``validation_errors``
    instead of raising, so the snapshot persists (router still commits)
    while ``profile.status`` stays ``'draft'``. This is required to
    expose the engine signal (``requires_manual_override``) to the manager
    /admin override-draft gate. To disambiguate ``submitted_T1`` snapshots,
    callers MUST check ``profile.status``:
      - ``status='draft'`` + ``submitted_T1``  → submit FAILED, snapshot
        captures resolution attempt for override gate
      - ``status='submitted'`` + ``submitted_T1`` → submit SUCCEEDED

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

    # --- B1: nhánh MANUAL — engine CỐ Ý trả None, caller phải giữ lại KV đã
    # được duyệt. Chỉ giữ khi CHỨNG MINH được xuất xứ bằng hàng
    # ``priority_audit_log`` (xem khối chú thích trên
    # ``verify_manual_override_provenance``). Không chứng minh được thì đi ra
    # bằng ``manual_override_unverified`` — NGOÀI ``_KV_SUCCESS_RULE_APPLIED``
    # nên cổng submit chặn mà không phải nới guard.
    override_evidence: dict[str, Any] = {}
    override_refused_reason: Optional[str] = None
    if rule_applied == "manual_override":
        ok, refuse_reason, override_evidence = (
            await verify_manual_override_provenance(db, profile)
        )
        if ok:
            kv_resolved = override_evidence["kv_resolved"]
            log.info(
                "kv_manual_override_preserved_through_freeze",
                profile_id=getattr(profile, "id", None),
                kv_resolved=kv_resolved,
                frozen_at_status=frozen_at_status,
                audit_id=override_evidence.get("manual_override_audit_id"),
                override_by=override_evidence.get("manual_override_by"),
            )
        else:
            override_refused_reason = refuse_reason
            override_evidence = {}
            rule_applied = _MANUAL_OVERRIDE_UNVERIFIED_RULE
            kv_resolved = None
            log.warning(
                "kv_manual_override_refused_unverified_provenance",
                profile_id=getattr(profile, "id", None),
                frozen_at_status=frozen_at_status,
                refuse_reason=refuse_reason,
                claimed_kv=(
                    (getattr(profile, "priority_resolution_snapshot", None) or {}).get(
                        "kv_resolved"
                    )
                    if isinstance(
                        getattr(profile, "priority_resolution_snapshot", None), dict
                    )
                    else None
                ),
            )

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

    # --- B1: chép dấu vết phê duyệt SANG snapshot mới. Trước bản vá này freeze
    # dựng dict từ số 0 nên ai/khi nào/lý do/chứng cứ biến mất cùng kv_resolved,
    # và không còn cách nào đọc ra hồ sơ này từng được duyệt KV thủ công.
    if override_evidence:
        snapshot.update(
            {
                "manual_override_by": override_evidence["manual_override_by"],
                "manual_override_by_name": override_evidence[
                    "manual_override_by_name"
                ],
                "manual_override_at": override_evidence["manual_override_at"],
                "manual_override_reason": override_evidence[
                    "manual_override_reason"
                ],
                "evidence_file_id": override_evidence["evidence_file_id"],
                "manual_override_audit_id": override_evidence[
                    "manual_override_audit_id"
                ],
                "manual_override_actor_role": override_evidence[
                    "manual_override_actor_role"
                ],
                KV_INPUTS_FINGERPRINT_KEY: override_evidence[
                    KV_INPUTS_FINGERPRINT_KEY
                ],
                "manual_override_verified_at": snapshot["frozen_at"],
            }
        )
        snapshot.pop("requires_manual_override", None)
        snapshot.pop("reason", None)
    elif override_refused_reason is not None:
        # Fail-closed: nêu ĐÚNG lý do từ chối để manager biết phải làm gì
        # (duyệt lại qua endpoint override), và bật lại cờ engine-signal cho
        # cổng override-draft của ``priority_override_service``.
        snapshot["reason"] = f"manual_override_unverified:{override_refused_reason}"
        snapshot["requires_manual_override"] = True

    # --- B1: ``ut_verified_bucket`` do priority_override_service (verify /
    # reject / untick / re-upload) ghi bằng deep-merge vào CÙNG cột JSONB này.
    # Freeze dựng dict mới nên nó cũng rơi mất. Giữ lại: nó là kết quả xác minh
    # chứng cứ UT, không phải trạng thái engine KV tính ra được.
    _prev_snapshot = getattr(profile, "priority_resolution_snapshot", None)
    if isinstance(_prev_snapshot, dict) and "ut_verified_bucket" in _prev_snapshot:
        snapshot.setdefault("ut_verified_bucket", _prev_snapshot["ut_verified_bucket"])

    profile.priority_resolution_snapshot = snapshot
    return snapshot


def _make_path_shim_from_academic_info(academic_info: Any) -> Any:
    """Build pseudo-AdmissionPath stub bọc academic_info đã eager-load.

    ``derive_target_level_and_type`` đọc qua ``path.__dict__['academic_info']``
    để mimic eager-load semantics; legacy callers (single-path / config
    chain) không có thực thể AdmissionPath nên cần shim. Helper này centralize
    pattern (trước đây duplicated 2 chỗ: admission_service._validate_*
    + priority_service.derive_profile_target_context).

    Trả về object với ``__dict__['academic_info']`` set + ``admission_method``
    placeholder=None (legacy không có method chain — bonus_rule context fall
    về admission_method default).
    """

    class _PathShim:
        pass

    shim = _PathShim()
    shim.__dict__["academic_info"] = academic_info
    shim.__dict__["admission_method"] = None
    return shim


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
    from ..utils.exceptions import TargetLevelConfigGap

    _GDNN_TARGET_LEVELS = frozenset({"cao_dang", "trung_cap", "so_cap"})

    # Khoá VẮNG trong ``__dict__`` = quan hệ CHƯA NẠP (lỗi mã của nơi gọi); khoá CÓ mà giá trị None = FK NULL
    # (cấu hình thiếu). Hai ca khác bản chất ⇒ ``gap_kind`` khác nhau (review C8 R2).
    academic_info = path.__dict__.get("academic_info")
    if academic_info is None:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: AdmissionPath thiếu academic_info "
            "(relation chưa eager-load hoặc DB không nhất quán).",
            gap_kind="relation_not_loaded",
        )
    offering = academic_info.__dict__.get("offering")
    if offering is None:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: OfferingAcademicInfo thiếu offering.",
            gap_kind="relation_not_loaded",
        )
    program = offering.__dict__.get("program")
    if program is None:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: ProgramOffering thiếu program (MajorProgram).",
            gap_kind="relation_not_loaded",
        )

    # degree_level — model relationship `MajorProgram.degree_level_ref` →
    # ConfigDegreeLevel(.code). Eager-load via selectinload(program.degree_level_ref).
    if "degree_level_ref" not in program.__dict__:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: MajorProgram.degree_level_ref chưa eager-load.",
            gap_kind="relation_not_loaded",
        )
    degree_level_obj = program.__dict__.get("degree_level_ref")
    target_code: Optional[str] = (
        getattr(degree_level_obj, "code", None) if degree_level_obj else None
    )
    if target_code is None:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: MajorProgram chưa gán degree_level_id "
            "(config_degree_level FK NULL). Vui lòng cấu hình bậc đào tạo "
            "trước khi cho hồ sơ submit.",
            gap_kind="degree_level_missing",
        )
    if target_code not in _GDNN_TARGET_LEVELS:
        raise TargetLevelConfigGap(
            f"CONFIG_GAP_TARGET_LEVEL: bậc đào tạo '{target_code}' nằm ngoài "
            f"phạm vi GDNN ({sorted(_GDNN_TARGET_LEVELS)}). Phase E.4 chỉ "
            f"hỗ trợ CĐ/TC/SC.",
            gap_kind="level_out_of_scope",
            level_code=target_code,
        )

    # offering_type — model relationship `ProgramOffering.offering_type_config`
    # → ConfigOfferingType(.code). Eager-load via
    # selectinload(offering.offering_type_config).
    if "offering_type_config" not in offering.__dict__:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: ProgramOffering.offering_type_config chưa eager-load.",
            gap_kind="relation_not_loaded",
        )
    offering_type_obj = offering.__dict__.get("offering_type_config")
    admission_type: Optional[str] = (
        getattr(offering_type_obj, "code", None) if offering_type_obj else None
    )
    if admission_type is None:
        raise TargetLevelConfigGap(
            "CONFIG_GAP_TARGET_LEVEL: ProgramOffering chưa gán offering_type_id "
            "(config_offering_type FK NULL). Vui lòng cấu hình hệ đào tạo "
            "(chính quy / liên thông / VLVH...) trước khi cho hồ sơ submit.",
            gap_kind="offering_type_missing",
        )

    return target_code, admission_type


def derive_major_code(path: "AdmissionPath") -> Optional[str]:
    """Lấy ``MajorProgram.code`` (mã ngành GDNN cấp IV) từ AdmissionPath chain.

    Chain: AdmissionPath → academic_info → offering → program.code. Trả None
    nếu chain chưa eager-load / thiếu (caller eager-load cùng lúc với
    ``derive_target_level_and_type`` nên thực tế hai giá trị đi cùng nhau).
    """
    academic_info = path.__dict__.get("academic_info")
    offering = academic_info.__dict__.get("offering") if academic_info else None
    program = offering.__dict__.get("program") if offering else None
    return getattr(program, "code", None) if program else None


def _is_health_sector_code(major_code: Optional[str]) -> bool:
    """Mã ngành GDNN cấp IV (TT 04/2017/TT-BLĐTBXH): chữ số 2-3 = '72' →
    lĩnh vực Sức khỏe (vd 5720101 Y sỹ TC, 6720201 Dược CĐ)."""
    return bool(major_code) and len(major_code) >= 3 and major_code[1:3] == "72"


def validate_eligibility(
    profile: "AdmissionProfile",
    target_level: str,
    admission_type: str = "chinh_quy",
    major_code: Optional[str] = None,
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

    # === Compliance guard — Luật GDNN 2025 Điều 45 Khoản 2 ===
    # TC lĩnh vực sức khỏe CHẤM DỨT tuyển sinh diện đầu-vào-THCS từ 01/01/2026.
    # Chặn CẢ completed_thcs (thuật ngữ TT22) lẫn graduated_thcs (nhãn legacy
    # cùng tầng đầu vào THCS) để không tạo bypass bằng nhãn cũ. Đầu vào THPT
    # (completed/graduated_thpt, graduated_gdtx) + ngành khác KHÔNG bị chặn.
    academic_year = getattr(profile, "academic_year", None)
    if (
        target_level in ("trung_cap", "TC")
        and _is_health_sector_code(major_code)
        and (academic_year or 0) >= 2026
        and cultural in ("completed_thcs", "graduated_thcs")
    ):
        return False, "tc_health_thcs_entry_closed_2026"

    _THPT_GRADUATED = ("graduated_thpt", "graduated_gdtx")
    _THPT_KNOWLEDGE = ("completed_thpt", "graduated_thpt", "graduated_gdtx")
    _THCS_OR_HIGHER = (
        "completed_thcs",
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
# Bảng và hàm phân giải nằm ở ``app.constants.priority_law_citation`` (MỘT nguồn,
# dùng chung với schema response cho snapshot đã đóng băng). Re-export tên cũ để
# các nơi đang ``from app.services.priority_service import resolve_law_citation``
# không đổi. Sửa câu căn cứ thì sửa Ở ĐÓ, không khai lại bảng ở đây.
from app.constants.priority_law_citation import (  # noqa: E402
    RULE_LAW_CITATION,
    resolve_law_citation,
)


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
                    _sel_in(models.AdmissionProfileChoice.admission_path).selectinload(
                        models.AdmissionPath.admission_method
                    ),
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
                .where(
                    models.OfferingAdmissionConfig.id
                    == profile.offering_admission_config_id
                )
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
                path = _make_path_shim_from_academic_info(config.academic_info)
                ctx["source"] = "legacy_offering_admission_config"

        if path is not None:
            try:
                target_level, admission_type = derive_target_level_and_type(path)
                ctx["target_level"] = target_level
                ctx["admission_type"] = admission_type
            except Exception as exc:  # noqa: BLE001 — defensive: missing chain
                # Phase E.4 reviewer P5: log debug để trace context-derive
                # failures (vd chain chưa eager-load đầy đủ). Vẫn không block
                # freeze; snapshot ship null cho 2 field này, FE/audit degrade.
                log.debug(
                    "derive_target_level_context_failed",
                    profile_id=getattr(profile, "id", None),
                    source=ctx["source"],
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

            # path_bonus_rule snapshot: chain override → method.default.
            # Lazy import để tránh circular.
            try:
                from .admission_choice_engine_service import (
                    resolve_effective_bonus_rule,
                )

                if hasattr(path, "bonus_rule_override") or method is not None:
                    rule = resolve_effective_bonus_rule(path)  # type: ignore[arg-type]
                    if rule is not None:
                        ctx["path_bonus_rule"] = dict(rule)
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "derive_path_bonus_rule_context_failed",
                    profile_id=getattr(profile, "id", None),
                    source=ctx["source"],
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        # Eligibility check audit — chỉ compute khi cả 2 field có.
        if ctx["target_level"] and ctx["admission_type"]:
            ok, reason = validate_eligibility(
                profile,
                ctx["target_level"],
                ctx["admission_type"],
                derive_major_code(path),
            )
            ctx["eligibility"] = {"passed": ok, "reason": reason}

    except Exception as exc:  # noqa: BLE001 — defensive: never block freeze on context
        log.debug(
            "derive_profile_target_context_failed",
            profile_id=getattr(profile, "id", None),
            error=str(exc),
            error_type=type(exc).__name__,
        )

    return ctx
