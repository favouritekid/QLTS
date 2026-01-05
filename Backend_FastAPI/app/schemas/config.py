# app/schemas/config.py
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class AssignmentConfig(BaseModel):
    params: Optional[Dict[str, Any]] = None  # Có thể là None hoặc dict


class ScoringConfig(BaseModel):
    params: Any


class SkillRuleBase(BaseModel):
    lead_attribute: str
    attribute_value: str
    required_skill: str


class SkillRuleCreate(SkillRuleBase):
    pass


class SkillRule(SkillRuleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SYSTEM CATEGORY SCHEMAS (Dynamic Config)
# ============================================================================

class SystemCategoryBase(BaseModel):
    type: str
    code: str
    name: str
    description: Optional[str] = None
    display_order: int = 0
    is_active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True)


class SystemCategoryCreate(SystemCategoryBase):
    pass


class SystemCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class SystemCategory(SystemCategoryBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

