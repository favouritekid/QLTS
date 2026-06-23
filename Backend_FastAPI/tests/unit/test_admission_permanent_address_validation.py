from types import SimpleNamespace

from app.services.admission_service import (
    _validate_permanent_address,
    _validate_personal_info,
)


def _profile(**overrides):
    values = {
        "full_name": "Nguyen Van A",
        "dob": "2001-01-01",
        "gender": "Nam",
        "citizen_id": "001234567890",
        "nationality": "VN",
        "ethnicity": "Kinh",
        "phone": "0901234567",
        "place_of_birth": "Ha Noi",
        "permanent_province": "Dak Lak",
        "permanent_ward": "Xa Ea Kao",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_permanent_address_validator_returns_specific_required_errors():
    missing, errors = _validate_permanent_address(
        _profile(permanent_province=None, permanent_ward=""),
    )

    assert missing == ["Tỉnh/Thành phố thường trú", "Phường/Xã thường trú"]
    assert errors == [
        "Thiếu địa chỉ thường trú: Tỉnh/Thành phố",
        "Thiếu địa chỉ thường trú: Phường/Xã",
    ]


def test_personal_info_readiness_includes_permanent_address_errors():
    missing, errors = _validate_personal_info(
        _profile(permanent_province=None, permanent_ward=None),
    )

    assert "Tỉnh/Thành phố thường trú" in missing
    assert "Phường/Xã thường trú" in missing
    assert "Thiếu địa chỉ thường trú: Tỉnh/Thành phố" in errors
    assert "Thiếu địa chỉ thường trú: Phường/Xã" in errors


def test_permanent_address_validator_accepts_two_tier_address_without_district():
    missing, errors = _validate_permanent_address(_profile())

    assert missing == []
    assert errors == []
