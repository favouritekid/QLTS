"""Unit tests cho bank_name_from_bin — nguồn tên ngân hàng kèm VietQR."""

from app.utils.bank_names import bank_name_from_bin


def test_known_bin_returns_full_name():
    assert bank_name_from_bin("970436") == (
        "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)"
    )
    assert "BIDV" in bank_name_from_bin("970418")
    assert "Techcombank" in bank_name_from_bin("970407")


def test_unknown_bin_falls_back_to_labelled_bin():
    assert bank_name_from_bin("999999") == "Ngân hàng (BIN 999999)"


def test_empty_bin_falls_back_without_crash():
    assert bank_name_from_bin("") == "Ngân hàng (BIN )"
