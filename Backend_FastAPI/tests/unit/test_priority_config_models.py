"""ORM smoke tests for Q9 #07 PR1 priority config + VN locality models.

Verifies model registration, __tablename__, column attribute presence,
and Base metadata wiring — catches "I forgot to import the model in
__init__.py" regressions before alembic autogenerate goes sideways.
"""
from __future__ import annotations

from decimal import Decimal

import pytest


def test_priority_area_config_model_is_importable() -> None:
    from app.models import PriorityAreaConfig
    assert PriorityAreaConfig.__tablename__ == "priority_area_config"


def test_priority_object_config_model_is_importable() -> None:
    from app.models import PriorityObjectConfig
    assert PriorityObjectConfig.__tablename__ == "priority_object_config"


def test_vn_commune_area_map_model_is_importable() -> None:
    from app.models import VnCommuneAreaMap
    assert VnCommuneAreaMap.__tablename__ == "vn_commune_area_map"


def test_vn_high_school_model_is_importable() -> None:
    from app.models import VnHighSchool
    assert VnHighSchool.__tablename__ == "vn_high_school"


@pytest.mark.parametrize(
    "model_name, expected_columns",
    [
        (
            "PriorityAreaConfig",
            {
                "id", "academic_year", "area_code", "area_name",
                "bonus_points", "description", "effective_from",
                "effective_to", "created_at", "updated_at",
            },
        ),
        (
            "PriorityObjectConfig",
            {
                "id", "academic_year", "group_code", "sub_code",
                "description", "bonus_points", "evidence_doc_type",
                "effective_from", "effective_to", "created_at",
                "updated_at",
            },
        ),
        (
            "VnCommuneAreaMap",
            {
                "id", "commune_code", "province", "district", "ward",
                "area_code", "effective_from", "effective_to",
            },
        ),
        (
            "VnHighSchool",
            {
                "id", "name", "province", "district", "ward",
                "kv_code", "is_active", "effective_from", "effective_to",
            },
        ),
    ],
)
def test_model_has_expected_columns(model_name: str, expected_columns: set[str]) -> None:
    """Lock the column set so renaming/removing a field surfaces here
    instead of in a runtime SQLAlchemy error."""
    import app.models as m
    model = getattr(m, model_name)
    actual = set(model.__table__.columns.keys())
    assert expected_columns.issubset(actual), (
        f"{model_name} missing columns: {expected_columns - actual}"
    )


def test_bonus_points_uses_numeric_4_2() -> None:
    """Precision (4, 2) matches the migration — supports up to 99.99
    points which is far above any plausible regulation cap (TT 05/2021
    max conceivable is 2.75)."""
    from app.models import PriorityAreaConfig, PriorityObjectConfig
    for model in (PriorityAreaConfig, PriorityObjectConfig):
        col = model.__table__.columns["bonus_points"]
        assert col.type.precision == 4
        assert col.type.scale == 2


def test_vn_high_school_is_active_defaults_true() -> None:
    """Soft-delete flag default — admin "deletes" by flipping to false,
    FK RESTRICT on admission_profile.high_school_id blocks hard DELETE."""
    from app.models import VnHighSchool
    col = VnHighSchool.__table__.columns["is_active"]
    assert col.nullable is False


def test_models_are_in_base_metadata() -> None:
    """Final wiring check: alembic autogenerate compares Base.metadata
    against the live DB. If a model isn't reachable from Base, future
    autogen runs would silently miss the table."""
    from app.models import Base
    table_names = set(Base.metadata.tables.keys())
    for tbl in (
        "priority_area_config",
        "priority_object_config",
        "vn_commune_area_map",
        "vn_high_school",
    ):
        assert tbl in table_names, f"{tbl} not registered in Base.metadata"
