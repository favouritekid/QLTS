"""NGUỒN DUY NHẤT cho câu "Căn cứ: …" hiển thị cạnh kết quả phân giải khu vực ưu tiên.

Ba nơi từng tự giữ bản riêng và cả ba cùng ghi SAI số mục so với chính TT 05/2021/TT-BLĐTBXH
Phụ lục 01 ("CÁC CHÍNH SÁCH ƯU TIÊN"), đối chiếu nguyên văn ngày 11-10-2026:

* mục 4 thuộc nhóm tuyển thẳng / ưu tiên xét tuyển — KHÔNG nói gì về khu vực;
* mục 5 "Chính sách ưu tiên theo khu vực": 5.a luật học nhiều trường (học liên tục và tốt nghiệp ở
  khu vực nào hưởng khu vực đó; chuyển trường ⇒ khu vực học lâu hơn; mỗi năm một trường hoặc nửa/nửa
  ⇒ khu vực nơi tốt nghiệp), 5.b các trường hợp hưởng theo hộ khẩu thường trú, 5.c danh sách khu vực;
* mục 6 "Khung điểm ưu tiên" — mức chênh lệch điểm, KHÔNG phải căn cứ cho việc ấn định tay.

Bản cũ ghi ``longest_duration`` → "Mục 5.b", ``commune_lookup`` → "Mục 4", ``manual_override`` →
"Mục 6 (admin override)". Ấn định khu vực thủ công là thao tác XÁC NHẬN NỘI BỘ của nhà trường, không
có mục thông tư nào quy định ⇒ câu hiển thị nói đúng như vậy, không gán sang một mục.

``commune_lookup`` dùng chung cho các ca hộ khẩu của mục 5.b VÀ các ca trường tự quyết dùng nơi thường
trú (vd trung cấp sau THCS — quyết định nghiệp vụ #6, không có trong TT 05) ⇒ chỉ trích tới "Mục 5",
không trích "5.b" để khỏi nói quá văn bản.

Snapshot đã ĐÓNG BĂNG trong ``admission_profile.priority_resolution_snapshot`` vẫn mang câu cũ (ghi lúc
phân giải; snapshot ấn định tay còn giữ câu của lần phân giải TRƯỚC qua ``**prev_snapshot``). Không
sửa dữ liệu: ``with_current_law_citation`` trả BẢN SAO với câu tính lại từ ``rule_applied``, dùng ở tầng
schema response. Frontend còn một bảng dự phòng (``engineDisplay.ts``) — test
``test_phase_e4_pr4_compliance.py`` khoá nó bằng đúng bảng này.
"""

from typing import Any, Mapping, Optional

TT05_PHU_LUC_01 = "TT 05/2021 Phụ lục 01"
#: V3: TT 76/2026/TT-BGDĐT thay TT 05 từ 03-11-2026. Số MỤC trong Phụ lục I CHƯA đối chiếu nguyên văn (bản ký là
#: ảnh) — bản vá này phát hiện bảng TT 05 cũ sai cả 3/3 chỗ, nên câu TT 76 chỉ trích tới cấp PHỤ LỤC, không nói
#: quá văn bản. Đối chiếu xong thì thêm số mục ở đây.
TT76_PHU_LUC_I = "TT 76/2026/TT-BGDĐT Phụ lục I"
_AN_DINH_THU_CONG = "Ấn định thủ công — xác nhận nội bộ của nhà trường, không thuộc mục nào của thông tư"

# Keys PHẢI khớp các giá trị ``rule_applied`` mà ``resolve_kv_for_profile`` / ấn định tay phát ra.
# Thêm ``rule_applied`` mới mà quên khai ở đây ⇒ ``resolve_law_citation`` trả None lặng lẽ.
RULE_LAW_CITATION: dict[str, Optional[str]] = {
    # Học nhiều trường THPT: khu vực học lâu hơn.
    "longest_duration": f"{TT05_PHU_LUC_01} Mục 5.a",
    # Học nhiều trường, thời gian bằng nhau / mỗi năm một trường ⇒ khu vực nơi tốt nghiệp.
    "tiebreak_graduation_school": f"{TT05_PHU_LUC_01} Mục 5.a",
    # Tra khu vực theo xã/phường (hộ khẩu thường trú hoặc ca đặc biệt) — xem docstring.
    "commune_lookup": f"{TT05_PHU_LUC_01} Mục 5",
    # Không phải căn cứ thông tư.
    "manual_override": _AN_DINH_THU_CONG,
    # Engine không quyết được ⇒ không có căn cứ để hiện.
    "ambiguous_requires_manual": None,
    "address_not_normalized": None,
    "catalog_gap_commune": None,
    "catalog_gap_school": None,
    "insufficient_data": None,
    "not_resolved": None,
    # Ấn định tay KHÔNG chứng minh được xuất xứ (``priority_service._MANUAL_OVERRIDE_UNVERIFIED_RULE``) ⇒ không căn cứ.
    "manual_override_unverified": None,
}


#: Cùng tập khoá với bảng TT 05 — test khoá hai bảng có đúng một tập ``rule_applied``.
RULE_LAW_CITATION_TT76: dict[str, Optional[str]] = {
    "longest_duration": TT76_PHU_LUC_I,
    "tiebreak_graduation_school": TT76_PHU_LUC_I,
    "commune_lookup": TT76_PHU_LUC_I,
    "manual_override": _AN_DINH_THU_CONG,
    "ambiguous_requires_manual": None,
    "address_not_normalized": None,
    "catalog_gap_commune": None,
    "catalog_gap_school": None,
    "insufficient_data": None,
    "not_resolved": None,
    # Ấn định tay KHÔNG chứng minh được xuất xứ (``priority_service._MANUAL_OVERRIDE_UNVERIFIED_RULE``) ⇒ không căn cứ.
    "manual_override_unverified": None,
}

#: Bảng căn cứ theo THÔNG TƯ ÁP DỤNG của hồ sơ (``app/constants/admission_circular.py``).
RULE_LAW_CITATION_BY_CIRCULAR: dict[str, dict[str, Optional[str]]] = {
    "TT05_2021": RULE_LAW_CITATION,
    "TT76_2026": RULE_LAW_CITATION_TT76,
}


def _bang_cho(circular: Optional[str]) -> dict[str, Optional[str]]:
    """``None`` ⇒ bảng TT 05 (giữ hành vi cũ cho lời gọi không biết thông tư); mã lạ ⇒ ValueError (không đoán)."""
    if circular is None:
        return RULE_LAW_CITATION
    try:
        return RULE_LAW_CITATION_BY_CIRCULAR[circular]
    except KeyError:
        raise ValueError("Thông tư không có bảng căn cứ: %r" % (circular,)) from None


def resolve_law_citation(rule_applied: Optional[str], circular: Optional[str] = None) -> Optional[str]:
    """Câu căn cứ cho một ``rule_applied`` theo ``circular``; None khi rỗng hoặc không có trong bảng."""
    if not rule_applied:
        return None
    return _bang_cho(circular).get(rule_applied)


def with_current_law_citation(
    snapshot: Optional[Mapping[str, Any]], circular: Optional[str] = None
) -> dict[str, Any]:
    """BẢN SAO của snapshot với ``rule_law_citation`` tính lại từ ``rule_applied`` THEO ``circular``.

    KHÔNG BAO GIỜ sửa đối tượng truyền vào: snapshot có thể chính là thuộc tính JSONB của ORM, sửa tại
    chỗ thì phiên SQLAlchemy có thể flush xuống CSDL — đúng thứ bản vá này không được làm.
    ``rule_applied`` không có trong bảng ⇒ giữ nguyên câu đã lưu (không đoán).
    """
    bang = _bang_cho(circular)
    out: dict[str, Any] = dict(snapshot or {})
    rule_applied = out.get("rule_applied")
    if isinstance(rule_applied, str) and rule_applied in bang:
        out["rule_law_citation"] = bang[rule_applied]
    return out
