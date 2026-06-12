# app/services/document_resolution_service.py
"""
Document Resolution Service — module chung resolve bộ hồ sơ đa chiều.

feat/document-group-audience-merge. Tách helper merge + audience khỏi
``admission_path_service`` + ``public_admissions_service`` để 1 NGUỒN merge
duy nhất (tránh drift — round-6 G3).

Bộ hồ sơ của 1 thí sinh = hợp các lớp giấy tờ khớp 3 chiều:
- **Loại hình** (offering_type) — tier shared/method/path (đã có).
- **Đối tượng/trình độ văn hóa** — ``DocumentGroup.applicable_audience`` (THÊM).
- **Phương thức** (admission_method) — tier method (đã có).

Precedence tier (path > method > shared) GIỮ NGUYÊN. Audience CHỈ merge trong
tier shared (path/method override = fork, không đụng audience).

Pure: chỉ import models + lazy ``priority_service`` (no FastAPI, no import cycle).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

import structlog

from app.schemas.admission_path import ResolvedDocumentResponse

log = structlog.get_logger(__name__)


# Nhãn tiếng Việt cho từng audience (FE render từ BE — thin-client).
AUDIENCE_LABELS: Dict[str, str] = {
    "POST_THCS": "Tốt nghiệp THCS",
    "POST_THPT": "Tốt nghiệp THPT",
    "LIEN_THONG_TC": "Liên thông Trung cấp",
    "LIEN_THONG_CD": "Liên thông Cao đẳng",
    "VLVH": "Vừa làm vừa học",
}

# cultural_education_level → audience VĂN HÓA (suy TRỰC TIẾP, KHÔNG qua derive).
# Giá trị cultural: schemas/admission.py:732.
_CULTURAL_TO_AUDIENCE: Dict[str, str] = {
    "completed_thcs": "POST_THCS",
    "graduated_thcs": "POST_THCS",
    "completed_thpt": "POST_THPT",
    "graduated_thpt": "POST_THPT",
    "graduated_gdtx": "POST_THPT",
}


def cultural_to_audience(cultural: Optional[str]) -> Optional[str]:
    """Map ``cultural_education_level`` → ``admission_audience`` chiều VĂN HÓA.

    Public wrapper quanh ``_CULTURAL_TO_AUDIENCE`` (nguồn sự thật DUY NHẤT,
    dùng chung document-resolution + filter phương thức ở AddChoiceDialog) →
    caller KHÔNG import symbol private xuyên module. Trả ``None`` nếu cultural
    là None / rỗng / không nằm trong map → caller KHÔNG lọc theo audience.
    """
    if not cultural:
        return None
    return _CULTURAL_TO_AUDIENCE.get(cultural)


# cultural "completed_*" = hoàn thành chương trình nhưng CHƯA có bằng → mã bằng
# TN cần LOẠI khỏi bộ hồ sơ (§6 GĐ1; doc type bằng TN tồn tại prod 2026-05-29).
_COMPLETED_DIPLOMA_TO_REMOVE: Dict[str, str] = {
    "completed_thpt": "bang_tot_nghiep_thpt",
    "completed_thcs": "bang_tot_nghiep_thcs",
}

# PR #10 — ĐỐI XỨNG with ..._TO_REMOVE: "completed_*" nộp Giấy CN hoàn thành
# chương trình THAY cho bằng TN bị loại. Vì ``_CULTURAL_TO_AUDIENCE`` map cả
# completed_thpt + graduated_thpt → CÙNG POST_THPT, audience layer KHÔNG phân
# biệt được → SWAP phải làm ở tầng code (caller dựng synthetic resolved item).
# completed_thcs CHƯA có giấy nguồn → để trống (known-limitation GĐ1).
_COMPLETED_DIPLOMA_TO_ADD: Dict[str, str] = {
    "completed_thpt": "giay_cn_hoan_thanh_gdpt",
}


def mandatory_wins_merge(
    doc_map: Dict[int, tuple],
    groups: Iterable,
    source: str,
    *,
    exclude_inactive: bool = False,
) -> None:
    """Merge items từ ``groups`` vào ``doc_map`` (mutate in-place), mandatory-wins.

    ``doc_map``: ``{document_type_id: (DocumentGroupItem, source, group_audience)}``
    — ``group_audience`` = ``group.applicable_audience`` của group thắng (None cho
    NỀN/override) để response gắn ``applicable_audience`` + ``layer_kind``.
    Item bắt buộc override item không bắt buộc CÙNG document_type.

    ``exclude_inactive`` (round-6 G3 — 2 caller KHÁC hành vi):
      - ``False`` (path/create snapshot): GIỮ item kể cả doc_type inactive
        (hành vi ``admission_path_service.resolve_documents_for_path`` cũ).
      - ``True`` (public/storefront): BỎ item có doc_type inactive
        (giữ hardening #348 ``public_admissions_service``).
    """
    for group in groups:
        grp_aud = getattr(group, "applicable_audience", None)
        for item in group.items:
            if exclude_inactive and (
                item.document_type is None or not item.document_type.is_active
            ):
                continue
            existing = doc_map.get(item.document_type_id)
            if existing is None or (
                item.is_mandatory and not existing[0].is_mandatory
            ):
                doc_map[item.document_type_id] = (item, source, grp_aud)


def filter_shared_by_audience(
    shared_groups: Iterable,
    audience_set: Optional[Set[str]],
) -> List:
    """Lọc shared groups theo ``audience_set`` của thí sinh.

    Trả: group NỀN (``applicable_audience`` NULL/rỗng — LUÔN merge cho mọi TS)
         + group có ``applicable_audience && audience_set`` (overlap).

    ``audience_set=None`` → CHỈ NỀN (backward-compat: legacy / admin no-audience /
    create chưa biết audience). Public xử lý ALL layers riêng (§9).
    """
    result: List = []
    for group in shared_groups:
        aud = getattr(group, "applicable_audience", None)
        if not aud:  # NULL hoặc [] → lớp NỀN
            result.append(group)
        elif audience_set is not None and (set(aud) & audience_set):
            result.append(group)
    return result


def derive_audience_set(profile, path) -> Set[str]:
    """Suy ``audience_set`` của hồ sơ từ 2 chiều.

    - **Văn hóa**: TRỰC TIẾP từ ``profile.cultural_education_level`` (KHÔNG qua
      derive → KHÔNG bao giờ rớt vì CONFIG_GAP).
    - **Loại hình**: qua ``derive_target_level_and_type(path)`` — bọc try/except
      QUANH RIÊNG call này → CONFIG_GAP/chain chưa load chỉ rớt chiều loại hình.

    INVARIANT (round-3 BLOCKER): hàm NÀY **không bao giờ raise** và **luôn trả
    ≥ tập văn hóa** → re-resolve luôn apply (chống P0-A tái sinh ở nhánh CONFIG_GAP).
    """
    audience: Set[str] = set()

    cultural = getattr(profile, "cultural_education_level", None)
    if cultural in _CULTURAL_TO_AUDIENCE:
        audience.add(_CULTURAL_TO_AUDIENCE[cultural])

    if path is not None:
        try:
            from .priority_service import derive_target_level_and_type

            target_level, admission_type = derive_target_level_and_type(path)
            if admission_type == "lien_thong":
                if target_level == "trung_cap":
                    audience.add("LIEN_THONG_TC")
                elif target_level == "cao_dang":
                    audience.add("LIEN_THONG_CD")
            elif admission_type == "vua_lam_vua_hoc":
                audience.add("VLVH")
        except Exception as exc:  # noqa: BLE001 — fail-safe: chỉ rớt chiều loại hình
            # log.warning (KHÔNG info) để bug code thật trong derive (vd
            # AttributeError do typo) lộ ra thay vì âm thầm rớt chiều loại hình.
            # CONFIG_GAP (chain chưa load) là ca hợp lệ duy nhất kỳ vọng ở đây.
            log.warning(
                "derive_audience_set_offering_type_dim_skipped",
                reason=str(exc),
                error_type=type(exc).__name__,
                cultural_audience=sorted(audience),
            )

    return audience


def compute_preview_audience_set(
    cultural: Optional[str],
    offering_type_code: Optional[str],
) -> Set[str]:
    """Audience set cho PREVIEW config-level (§5b/G5 "Xem trước theo TS").

    KHÔNG cần path/profile (admin chỉ nhập raw cultural/vocational/offering_type
    → BE derive, thin-client). Chỉ suy:
    - **Văn hóa**: ``cultural`` trực tiếp → POST_THCS/POST_THPT (nhu cầu gốc).
    - **VLVH**: offering_type ``vua_lam_vua_hoc``.

    LIEN_THONG_TC/CD cần degree level (program cụ thể) → KHÔNG suy được ở
    tầng offering_type; defer known-limitation GĐ1 (lớp LIEN_THONG chưa tồn tại).
    """
    audience: Set[str] = set()
    if cultural in _CULTURAL_TO_AUDIENCE:
        audience.add(_CULTURAL_TO_AUDIENCE[cultural])
    if offering_type_code == "vua_lam_vua_hoc":
        audience.add("VLVH")
    return audience


def compute_completed_doc_codes(profile) -> Set[str]:
    """Mã bằng TN cần LOẠI khỏi bộ hồ sơ khi ``cultural='completed_*'``.

    "completed" = hoàn thành chương trình nhưng CHƯA có bằng (§6 GĐ1) → không
    yêu cầu nộp bằng TN tương ứng. "graduated_*" giữ bằng (đã có).
    """
    cultural = getattr(profile, "cultural_education_level", None)
    code = _COMPLETED_DIPLOMA_TO_REMOVE.get(cultural)
    return {code} if code else set()


def compute_completed_add_doc_codes(profile) -> Set[str]:
    """PR #10 — mã giấy cần THÊM khi ``cultural='completed_*'`` (đối xứng
    ``compute_completed_doc_codes``).

    "completed_thpt" (trượt tốt nghiệp) nộp Giấy CN hoàn thành chương trình
    GDPT thay cho bằng TN bị loại. "graduated_*" giữ bằng, KHÔNG thêm.
    Trả set rỗng cho cultural khác (kể cả completed_thcs — chưa có giấy nguồn).
    """
    cultural = getattr(profile, "cultural_education_level", None)
    code = _COMPLETED_DIPLOMA_TO_ADD.get(cultural)
    return {code} if code else set()


def build_resolved_response(
    doc_map: Dict[int, tuple],
    completed_codes: Optional[Set[str]] = None,
    add_items: Optional[List[ResolvedDocumentResponse]] = None,
) -> List[ResolvedDocumentResponse]:
    """``doc_map`` ``(item, source, group_audience)`` → list ResolvedDocumentResponse.

    Builder canonical cho resolve (path/create) + preview config — cùng module
    với ``mandatory_wins_merge`` (đúng layering, tránh caller reach vào private
    của service khác). Loại item code ∈ ``completed_codes`` (cultural=completed_*
    → bỏ bằng TN §6). ``layer_kind``: path_override / method_override /
    shared_audience / shared_base. ``applicable_audience``: audience group thắng
    (None cho NỀN/override).

    PR #10 — ``add_items``: synthetic ResolvedDocumentResponse do CALLER dựng
    từ DB (vd Giấy CN hoàn thành GDPT cho ``completed_thpt``). Builder GIỮ PURE:
    chỉ APPEND item có ``document_type_code`` CHƯA xuất hiện trong kết quả
    (dedup — nếu DocumentGroup đã cấu hình giấy đó thì giữ bản config, không
    nhân đôi), rồi sort lại theo ``display_order``.
    """
    completed = completed_codes or set()
    resolved: List[ResolvedDocumentResponse] = []
    for _doc_type_id, (item, source, grp_aud) in doc_map.items():
        code = item.document_type.code if item.document_type else ""
        if code in completed:
            continue
        if source == "path_override":
            layer_kind = "path_override"
        elif source == "method_override":
            layer_kind = "method_override"
        elif grp_aud:
            layer_kind = "shared_audience"
        else:
            layer_kind = "shared_base"
        resolved.append(
            ResolvedDocumentResponse(
                document_type_id=item.document_type_id,
                document_type_code=code,
                document_type_name=(
                    item.document_type.name if item.document_type else ""
                ),
                is_mandatory=item.is_mandatory,
                requires_upload=item.requires_upload,
                submission_format=item.submission_format,
                display_order=item.display_order,
                source=source,
                applicable_audience=list(grp_aud) if grp_aud else None,
                layer_kind=layer_kind,
            )
        )

    if add_items:
        existing_codes = {r.document_type_code for r in resolved}
        for extra in add_items:
            if extra.document_type_code not in existing_codes:
                resolved.append(extra)
                existing_codes.add(extra.document_type_code)

    resolved.sort(key=lambda x: x.display_order)
    return resolved


def build_completed_add_items(doc_types) -> List[ResolvedDocumentResponse]:
    """PR #10 — dựng synthetic add-items (paper-only) từ list ConfigDocumentType.

    Pure builder dùng CHUNG cho cả ``resolve_documents_for_profile`` (resolve
    thật) lẫn preview config → 1 nguồn shape, KHÔNG drift (finding #3). Caller
    lookup doc type từ DB rồi truyền vào (chỉ ``id``/``code``/``name``/
    ``display_order`` được đọc). Phần paper-only dựng CỨNG: vì #10 KHÔNG tạo
    ``DocumentGroupItem`` cho giấy GDPT, các field config (``requires_upload``,
    ``submission_format``, ``is_mandatory``) — vốn nằm ở ``DocumentGroupItem`` —
    phải set tường minh ở đây.

    ``layer_kind='shared_base'`` + ``applicable_audience=None``: item chỉ xuất
    hiện trong context resolve của hồ sơ completed_*, KHÔNG gắn badge audience
    (tránh hiểu nhầm "đã tốt nghiệp" cho người trượt TN).
    """
    items: List[ResolvedDocumentResponse] = []
    for dt in doc_types:
        items.append(
            ResolvedDocumentResponse(
                document_type_id=dt.id,
                document_type_code=dt.code,
                document_type_name=dt.name,
                is_mandatory=True,
                requires_upload=False,  # paper-only — officer ghi nhận tại quầy
                submission_format=None,
                display_order=dt.display_order,
                source="shared",
                applicable_audience=None,
                layer_kind="shared_base",
            )
        )
    return items
