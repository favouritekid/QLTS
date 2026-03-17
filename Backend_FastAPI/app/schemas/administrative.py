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
