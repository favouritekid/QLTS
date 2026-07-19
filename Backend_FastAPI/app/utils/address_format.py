# app/utils/address_format.py
"""Format an AdmissionProfile's permanent address into one display string."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.models import AdmissionProfile


def format_permanent_address(profile: "AdmissionProfile") -> str:
    """Join the permanent-address parts into a single human-readable line.

    Order (coarse → fine is how VN addresses read on official documents):
    street/house → residential group (Tổ/Thôn/Buôn) → ward → district → province.
    Empty parts are skipped (district is often blank after the 2025 2-tier
    reform). Returns ``""`` if the profile has no address parts at all.

    Example: "Tổ dân phố 6, Phường Tự An, Thành phố Buôn Ma Thuột, Tỉnh Đắk Lắk"
    """
    parts = [
        getattr(profile, "permanent_street_address", None),
        getattr(profile, "permanent_residential_group", None),
        getattr(profile, "permanent_ward", None),
        getattr(profile, "permanent_district", None),
        getattr(profile, "permanent_province", None),
    ]
    return ", ".join(p.strip() for p in parts if p and p.strip())
