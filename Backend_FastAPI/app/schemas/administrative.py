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
    """Province response schema."""
    pass


class DistrictResponse(AdministrativeNodeBase):
    """District response schema with province reference."""
    province_code: str


class WardResponse(AdministrativeNodeBase):
    """Ward response schema."""
    province_code: str
    district_code: Optional[str] = None  # NULL for 2-level structure


class WardDetailResponse(WardResponse):
    """Ward with full hierarchy info for lookup."""
    path: str
    valid_from: date
    valid_to: Optional[date] = None
    # For 3-level lookup
    old_district_name: Optional[str] = None
