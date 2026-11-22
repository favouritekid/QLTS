# app/services/area_check_rules.py
"""F231 — kiểm khu vực ưu tiên của MỘT hồ sơ trên dữ kiện ĐÃ NẠP (hàm THUẦN — không đọc CSDL, không ghi gì).

Đề cương GĐ2-B đợt 2 §3 (K1 — owner 21-11: "nạp theo lô rồi dùng lại quy tắc tính"). Luật GIỐNG HỆT bản in GĐ1
(``council_candidate_service._resolve_area`` + ``_area_recompute_mismatch``), từng nhánh gọi ĐÚNG hàm thuần của
``priority_service`` mà đường từng hồ sơ gọi:

1. ảnh chụp KV chưa phân giải (``kv_snapshot_resolved``) ⇒ ``thieu_khu_vuc``;
2. hồ sơ ấn định thủ công (``area_resolution_basis`` hoặc ``rule_applied`` = ``manual_override``) ⇒ xác minh sổ
   (``decide_manual_override_provenance`` trên hàng sổ mới nhất ĐÃ NẠP) — không hiệu lực ⇒ ``khu_vuc_thu_cong_khong_hieu_luc``;
3. không thủ công ⇒ TÍNH LẠI KV bằng bộ quyết định của resolver (``decide_kv_for_profile`` trên bản đồ tra ĐÃ NẠP, cùng ngữ cảnh
   trình độ / loại hình ghi trong ảnh chụp): lỗi bất kỳ ⇒ ``khu_vuc_khong_tinh_lai_duoc``; khác KV của ảnh chụp ⇒
   ``khu_vuc_doi_sau_anh_chup``;
4. mức KV theo NĂM tuyển sinh của hồ sơ (``priority_academic_year``) qua ``pick_open_priority_rates`` trên các hàng ĐANG MỞ đã
   nạp: thiếu ⇒ ``chua_co_muc_khu_vuc``; hai hàng mở cùng mã ⇒ ``muc_khu_vuc_khong_nhat_quan``; có ⇒ ``(None, mức)``.

HAI BẢN của trình tự 1–4 đang cùng tồn tại (CLAUDE.md §7): bản in GĐ1 đang chạy production nên đổi đường đọc của nó sang hàm này
là PR RIÊNG (mặc định câu hỏi mở 1 của đề cương đợt 2 — owner có thể đổi). Cho tới lúc ấy hai bản bị KHOÁ BẰNG NHAU bởi
``tests/integration/test_gd2b_bt35_toan_luot_db.py`` (cùng dữ kiện ⇒ cùng kết quả trên đủ các nhánh F231).
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from app.services.priority_service import (
    RATE_TABLE_AREA,
    decide_kv_for_profile,
    decide_manual_override_provenance,
    kv_snapshot_resolved,
    pick_open_priority_rates,
    priority_academic_year,
)
from app.utils.exceptions import PriorityRateNotConfigured

AREA_MISSING = "thieu_khu_vuc"
AREA_MANUAL_INVALID = "khu_vuc_thu_cong_khong_hieu_luc"
AREA_CHANGED_AFTER_SNAPSHOT = "khu_vuc_doi_sau_anh_chup"
AREA_NOT_RECOMPUTABLE = "khu_vuc_khong_tinh_lai_duoc"
AREA_RATE_MISSING = "chua_co_muc_khu_vuc"
AREA_RATE_INCONSISTENT = "muc_khu_vuc_khong_nhat_quan"
#: Mọi mã chặn F231 (đặc tả GĐ2-B bản 4 §6.2 E6 — mức hồ sơ).
AREA_REASON_CODES: Tuple[str, ...] = (
    AREA_MISSING,
    AREA_MANUAL_INVALID,
    AREA_CHANGED_AFTER_SNAPSHOT,
    AREA_NOT_RECOMPUTABLE,
    AREA_RATE_MISSING,
    AREA_RATE_INCONSISTENT,
)
#: Nhãn "ấn định thủ công" — ở cột ``area_resolution_basis`` lẫn ``rule_applied`` của ảnh chụp (như ``_resolve_area``).
MANUAL_OVERRIDE = "manual_override"


def parse_kv_snapshot(raw: Any) -> Any:
    """``priority_resolution_snapshot`` đọc bằng SQL thô có thể là chuỗi JSON (như ``_resolve_area`` gặp) ⇒ giải mã; còn lại giữ."""
    return json.loads(raw) if isinstance(raw, str) else raw


def area_check(
    *,
    kv_snapshot: Any,
    area_resolution_basis: Optional[str],
    profile: Any,
    manual_audit_row: Any,
    commune_kv: Mapping[Tuple[Any, Any], Optional[str]],
    school_kv: Mapping[Tuple[Any, Any], Optional[str]],
    open_area_rate_rows: Iterable[Sequence[Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """``(mã chặn F231 | None, mức KV theo năm tuyển sinh dạng chuỗi | None)`` của MỘT hồ sơ — cùng hình giá trị với từng phần tử
    ``_resolve_area`` trả.

    * ``kv_snapshot`` / ``area_resolution_basis``: cột ``kv_snapshot`` / ``area_resolution_basis`` của ``SQL_CHECK_SOURCE`` (một
      nguồn với bản in);
    * ``profile``: đối tượng hồ sơ đã nạp (chỉ đọc CỘT — như ``session.get(..., raiseload("*"))`` của bản in);
    * ``manual_audit_row``: hàng ``kv_manual_override`` mới nhất của hồ sơ (``latest_manual_override_audit_rows``) hoặc ``None``;
    * ``commune_kv`` / ``school_kv``: bản đồ tra đã nạp cho MỌI khoá ``kv_lookup_keys`` của hồ sơ;
    * ``open_area_rate_rows``: các hàng ``(area_code, bonus_points)`` ĐANG MỞ của năm tuyển sinh hồ sơ.

    Lỗi của bước xác minh sổ nổi lên (như bản in); lỗi của bước tính lại ⇒ ``khu_vuc_khong_tinh_lai_duoc`` (như bản in)."""
    snap = parse_kv_snapshot(kv_snapshot)
    if not kv_snapshot_resolved(snap):
        return AREA_MISSING, None
    if area_resolution_basis == MANUAL_OVERRIDE or snap.get("rule_applied") == MANUAL_OVERRIDE:
        ok, _reason, _ = decide_manual_override_provenance(profile, manual_audit_row)
        if not ok:
            return AREA_MANUAL_INVALID, None
    else:
        try:
            new_area, _ = decide_kv_for_profile(
                profile,
                commune_kv=commune_kv,
                school_kv=school_kv,
                target_level=snap.get("target_level"),
                admission_type=snap.get("admission_type"),
            )
        # Không tính lại được ⇒ không chứng minh được KV sẽ in còn đúng ⇒ chặn (như ``_area_recompute_mismatch``).
        except Exception:  # noqa: BLE001
            return AREA_NOT_RECOMPUTABLE, None
        if new_area != snap.get("kv_resolved"):
            return AREA_CHANGED_AFTER_SNAPSHOT, None
    year = priority_academic_year(profile)
    area = snap["kv_resolved"]
    try:
        rates = pick_open_priority_rates(open_area_rate_rows, table=RATE_TABLE_AREA, academic_year=year, codes=[area])
    except PriorityRateNotConfigured:
        return AREA_RATE_MISSING, None
    except RuntimeError:  # hơn một hàng ĐANG MỞ cùng mã, cùng năm
        return AREA_RATE_INCONSISTENT, None
    return None, str(rates[area])
