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
