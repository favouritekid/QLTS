# app/schemas/administrative.py
"""Pydantic schemas for administrative nodes API."""

from pydantic import BaseModel
from typing import Optional
from datetime import date


class AdministrativeNodeBase(BaseModel):
    """Base schema for administrative node."""
    code: str
    name: str

    class Config:
        from_attributes = True


class ProvinceResponse(AdministrativeNodeBase):
    """Province response — mode determines which era is returned."""
    pass


class DistrictResponse(AdministrativeNodeBase):
    """District response (legacy 3-level only)."""
    province_code: str


class WardResponse(AdministrativeNodeBase):
    """Ward response."""
    province_code: str
    district_code: Optional[str] = None  # NULL for current 2-level


class WardDetailResponse(WardResponse):
    """Ward with full hierarchy info for lookup."""
    path: str
    valid_from: date
    valid_to: Optional[date] = None
    old_district_name: Optional[str] = None


class ResolveWardResponse(BaseModel):
    """PR-3: resolve any ward code (current or legacy) → canonical current commune.

    ``resolved=False`` (current_code=None) means the input couldn't be mapped to a
    current-era commune → FE keeps the officer on a current-mode pick (submit gate
    also fail-closes)."""
    input_code: str
    current_code: Optional[str] = None
    current_name: Optional[str] = None
    resolved: bool
