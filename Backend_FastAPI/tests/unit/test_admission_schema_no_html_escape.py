"""Regression test cho bug "amp" (double HTML-escape).

``AcademicRecordSchema`` và ``FamilyMemberSchema`` dùng CHUNG cho cả
request lẫn response. Trước đây cả hai html.escape() text fields ở tầng
schema; vì ``html.escape`` không idempotent (``&`` → ``&amp;``), mỗi vòng
đọc→sửa→lưu cộng thêm một lớp ``&amp;`` → tên trường "THPT Ea H'leo" biến
thành "THPT Ea H&amp;amp;...amp;#x27;leo".

Fix: schema chỉ trim, KHÔNG escape (escape là việc của tầng render —
React/JSX, Jinja autoescape). Test này khóa hành vi: giá trị đi qua schema
phải giữ NGUYÊN VĂN ký tự ``&``, ``'``, ``<``, ``>`` (không thành entity).
"""
import pytest

from app.schemas.admission import AcademicRecordSchema, FamilyMemberSchema


# Tên trường thật trong vn_school có cả & (THCS&THPT) lẫn ' (Ea H'leo).
RAW_SCHOOL_NAMES = [
    "THPT Ea H'leo (Từ 04/6/2021)",
    "THCS & THPT Nguyễn Du - Đà Lạt",
    "Trường <Test> \"Quote\" & Co",
]

HTML_ENTITY_FRAGMENTS = ["&amp;", "&#x27;", "&#39;", "&lt;", "&gt;", "&quot;"]


def _assert_no_html_entity(value: str) -> None:
    for frag in HTML_ENTITY_FRAGMENTS:
        assert frag not in value, f"giá trị bị escape thành entity ({frag}): {value!r}"


@pytest.mark.parametrize("raw", RAW_SCHOOL_NAMES)
def test_academic_school_name_not_escaped(raw):
    rec = AcademicRecordSchema(school_name=raw, year_from=2020, year_to=2023)
    assert rec.school_name == raw
    _assert_no_html_entity(rec.school_name)


@pytest.mark.parametrize("raw", RAW_SCHOOL_NAMES)
def test_family_text_fields_not_escaped(raw):
    member = FamilyMemberSchema(
        relationship="Bố & Mẹ",
        full_name=raw,
        occupation="Kỹ sư R&D",
        phone="0901234567",
    )
    assert member.full_name == raw
    assert member.relationship == "Bố & Mẹ"
    assert member.occupation == "Kỹ sư R&D"
    _assert_no_html_entity(member.full_name)
    _assert_no_html_entity(member.relationship)
    _assert_no_html_entity(member.occupation)


def test_school_name_still_trimmed():
    """Vẫn trim khoảng trắng (giữ hành vi cũ, chỉ bỏ escape)."""
    rec = AcademicRecordSchema(
        school_name="  THPT Ea H'leo  ", year_from=2020, year_to=2023
    )
    assert rec.school_name == "THPT Ea H'leo"


def test_already_escaped_value_passes_through_unchanged():
    """Giá trị đã chứa '&amp;' KHÔNG bị escape thêm lớp nữa (idempotent).

    (Backfill migration mới là nơi 'gỡ' giá trị lịch sử đã hỏng — schema
    chỉ cần ngừng tạo thêm lớp.)
    """
    already = "THPT Ea H&amp;#x27;leo"
    rec = AcademicRecordSchema(school_name=already, year_from=2020, year_to=2023)
    assert rec.school_name == already  # không thành &amp;amp;#x27;
