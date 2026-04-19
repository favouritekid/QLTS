"""Tests for app.utils.text_helpers."""
from app.utils.text_helpers import to_bank_transfer_note


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
