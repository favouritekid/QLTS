"""Tests for app.utils.text_helpers."""
from app.utils.text_helpers import (
    LIKE_ESCAPE_CHAR,
    escape_like_pattern,
    to_bank_transfer_note,
)


class TestToBankTransferNote:
    def test_none_returns_empty(self):
        assert to_bank_transfer_note(None) == ""

    def test_empty_string(self):
        assert to_bank_transfer_note("") == ""

    def test_pure_ascii_passthrough(self):
        assert to_bank_transfer_note("Hello World 42") == "Hello World 42"

    def test_vietnamese_diacritics_stripped(self):
        # All accents removed, base letters kept.
        assert to_bank_transfer_note("Phạm Thái Hà") == "Pham Thai Ha"

    def test_dong_letter_stripped(self):
        # đ / Đ don't decompose via NFD; explicit replace.
        assert to_bank_transfer_note("Điều dưỡng") == "Dieu duong"

    def test_dashes_replaced_with_space(self):
        assert to_bank_transfer_note("HS-000042") == "HS 000042"

    def test_special_chars_replaced(self):
        assert to_bank_transfer_note("ND: abc@def#ghi") == "ND abc def ghi"

    def test_spaces_collapsed(self):
        assert to_bank_transfer_note("a    b\tc\nd") == "a b c d"

    def test_truncated_to_max_len(self):
        raw = "a" * 120
        assert len(to_bank_transfer_note(raw, max_len=90)) == 90

    def test_zalo_compliant_output_pattern(self):
        import re
        composed = to_bank_transfer_note(
            "Phạm Thái Hà-HS-000042 thanh toán học phí Điều dưỡng"
        )
        assert re.match(r"^[a-zA-Z0-9 ]+$", composed), f"not Zalo-compliant: {composed!r}"

    def test_compose_example_matches_zalo_sample_shape(self):
        # Zalo sample: "Pham Thai Ha HS000042 thanh toan hoc phi Dieu duong"
        # Our composer uses ho_va_ten + lead_code + ten_nganh.
        composed = to_bank_transfer_note(
            "Phạm Thái Hà HS000042 thanh toán học phí Điều dưỡng"
        )
        assert composed == "Pham Thai Ha HS000042 thanh toan hoc phi Dieu duong"


class TestEscapeLikePattern:
    """Anchor for the LIKE-injection fix shipped alongside the
    repository search hardening. Each test pins a behaviour the
    repository code now relies on; if any assertion breaks, callers
    of ``.ilike(escape=LIKE_ESCAPE_CHAR)`` need re-auditing.
    """

    def test_empty_string_passes_through(self):
        assert escape_like_pattern("") == ""

    def test_plain_text_unchanged(self):
        assert escape_like_pattern("hello") == "hello"

    def test_percent_escaped(self):
        # ``%`` becomes ``\%`` so it matches literally inside ilike.
        assert escape_like_pattern("a%b") == "a\\%b"

    def test_underscore_escaped(self):
        # ``_`` would otherwise match any single character.
        assert escape_like_pattern("a_b") == "a\\_b"

    def test_backslash_escaped_first(self):
        # Backslash must double up BEFORE we add escape chars; otherwise
        # ``a\b`` becomes ``a\b`` and a smuggled ``\%`` would slip
        # through as a wildcard.
        assert escape_like_pattern("a\\b") == "a\\\\b"

    def test_smuggled_escape_sequence_neutralised(self):
        # Worst case: input is literally ``\%``. The backslash gets
        # doubled, so the ``%`` ends up as ``\\\%`` — ``%`` is escaped,
        # backslash is a literal pair. The user-provided backslash
        # cannot disarm our own escape.
        result = escape_like_pattern("\\%")
        assert result == "\\\\\\%"

    def test_combined_wildcards_all_escaped(self):
        assert escape_like_pattern("100% off_now") == "100\\% off\\_now"

    def test_escape_char_constant_is_single_backslash(self):
        # Sanity: callers pass this verbatim to ilike(escape=...).
        # If this changes the helper output must match.
        assert LIKE_ESCAPE_CHAR == "\\"
