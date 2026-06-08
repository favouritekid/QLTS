"""VietQR EMVCo payload and PNG rendering helpers."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import qrcode


VIETQR_GUID = "A000000727"
VIETQR_SERVICE_CODE = "QRIBFTTA"
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF


def _tlv(tag: str, value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    encoded = value.strip()
    if len(encoded) > 99:
        raise ValueError(f"EMVCo TLV value for tag {tag} exceeds 99 characters")
    return f"{tag}{len(encoded):02d}{encoded}"


def _crc16_ccitt(data: str) -> str:
    crc = CRC_INIT
    for byte in data.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def build_vietqr_payload(
    bank_bin: str,
    account_number: str,
    amount: Decimal,
    add_info: str,
    account_name: str | None = None,
) -> str:
    """Build a static merchant VietQR transfer payload.

    The caller owns content normalization for ``add_info``. This helper only
    emits EMVCo TLV and the final CRC field.
    """
    if amount <= 0:
        raise ValueError("VietQR amount must be positive")

    merchant_account = _tlv(
        "00",
        VIETQR_GUID,
    ) + _tlv(
        "01",
        _tlv("00", bank_bin) + _tlv("01", account_number),
    ) + _tlv(
        "02",
        VIETQR_SERVICE_CODE,
    )

    amount_text = str(int(amount))
    payload_without_crc = (
        _tlv("00", "01")
        # Point of Initiation "12" = dynamic (one-time, amount locked). The
        # invoice amount is fixed per-transfer, so "11" (static, payer-editable
        # amount) would let the payer change the amount and break reconciliation.
        + _tlv("01", "12")
        + _tlv("38", merchant_account)
        + _tlv("53", "704")
        + _tlv("54", amount_text)
        + _tlv("58", "VN")
    )

    if account_name:
        payload_without_crc += _tlv("59", account_name[:25])

    payload_without_crc += _tlv("62", _tlv("08", add_info))

    crc_input = payload_without_crc + "6304"
    return crc_input + _crc16_ccitt(crc_input)


def render_qr_png(payload: str) -> bytes:
    """Render a QR code PNG for the provided payload."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
