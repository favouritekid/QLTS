from decimal import Decimal

from app.utils.vietqr import build_vietqr_payload, render_qr_png


def test_build_vietqr_payload_includes_crc_field():
    payload = build_vietqr_payload(
        bank_bin="970436",
        account_number="123456789",
        account_name="QLTS",
        amount=Decimal("1500000"),
        add_info="Nguyen Van A HS 000001 thanh toan hoc phi",
    )

    assert payload.startswith("000201")
    # Point of Initiation must be "12" (dynamic) so the fixed amount is locked.
    assert "010212" in payload
    assert "5303704" in payload
    assert "54071500000" in payload
    assert payload[-8:-4] == "6304"
    assert len(payload[-4:]) == 4
    int(payload[-4:], 16)


def test_render_qr_png_returns_png_bytes():
    image = render_qr_png("00020101021153037045405100006304ABCD")

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
