from app.utils.fee_receipt import canonical_receipt_key


def test_canonical_receipt_key_vectors_are_stable():
    vectors = {
        " ABC-123 ": (
            "appfee:rcpt:"
            "5942d94f524882e0f29bf0a1e5a6dcc952eea1c0c21dd3588a3fc7db9716db0c"
        ),
        "ＡＢＣ": (
            "appfee:rcpt:"
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        ),
        "İ": (
            "appfee:rcpt:"
            "fbbdb347060082cf4e72cdc5f02679dd809ebf4e6c601933e858d954a65f5e73"
        ),
        "ı": (
            "appfee:rcpt:"
            "544bc1a8b6aad8d7553a578c8602fb5ea913a8a118c13900fa2a36c80880899a"
        ),
    }

    for raw, expected in vectors.items():
        key = canonical_receipt_key(raw)
        assert key == expected
        assert len(key) == 76


def test_canonical_receipt_key_length_does_not_follow_receipt_length():
    key = canonical_receipt_key(" R" * 100)

    assert key.startswith("appfee:rcpt:")
    assert len(key) == 76
