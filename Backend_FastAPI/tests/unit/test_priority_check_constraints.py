"""ORM CHECK constraint mirror tests (Q9 #07 PR1 review fix M-CR-2).

Test DB uses ``Base.metadata.create_all()`` (memory test-db-schema-source)
and therefore picks up CHECK constraints declared in
``__table_args__`` — NOT those declared only in alembic migrations.
This file locks the parity so a future drift between migration CHECK
and ORM CHECK surfaces here instead of leaking to prod.

Each test inspects the model's __table__.constraints list and asserts
the named CheckConstraint is present with the expected SQL text. Pure
metadata inspection — no DB session required, so the test is cheap
and deterministic.
"""
from __future__ import annotations

from typing import Iterable

import pytest
from sqlalchemy import CheckConstraint


def _check_constraint_sql(table, name: str) -> str:
    """Return the SQL text of a named CheckConstraint, or raise."""
    matches = [
        c for c in table.constraints
        if isinstance(c, CheckConstraint) and c.name == name
    ]
    assert matches, f"CheckConstraint {name!r} not found on {table.name}"
    return str(matches[0].sqltext)


@pytest.mark.parametrize(
    "model_name, constraint_name, expected_sql_fragment",
    [
        (
            "PriorityAreaConfig",
            "ck_priority_area_config_area_code_format",
            "KV[1-9](-NT)?",
        ),
        (
            "PriorityObjectConfig",
            "ck_priority_object_config_group_code_format",
            "UT[1-9]",
        ),
        (
            "PriorityObjectConfig",
            "ck_priority_object_config_sub_code_format",
            "[0-9]{2}",
        ),
        (
            "VnCommuneAreaMap",
            "ck_vn_commune_area_map_area_code_format",
            "KV[1-9](-NT)?",
        ),
        (
            "VnHighSchool",
            "ck_vn_high_school_kv_code_format",
            "KV[1-9](-NT)?",
        ),
    ],
)
def test_orm_mirrors_migration_check(
    model_name: str, constraint_name: str, expected_sql_fragment: str
) -> None:
    """The 5 CHECK regex defined in phase1_08b migration must be
    mirrored in the ORM __table_args__ so test DB picks them up via
    Base.metadata.create_all()."""
    import app.models as m
    model = getattr(m, model_name)
    sql = _check_constraint_sql(model.__table__, constraint_name)
    assert expected_sql_fragment in sql, (
        f"{model_name}.{constraint_name} SQL missing fragment "
        f"{expected_sql_fragment!r} — got: {sql!r}"
    )


def test_admission_profile_has_area_resolution_basis_check() -> None:
    """m-CR-3 fix: enum-like CHECK on area_resolution_basis catches
    typos at DB layer (vd: 'highschool' vs 'high_school')."""
    from app.models import AdmissionProfile
    sql = _check_constraint_sql(
        AdmissionProfile.__table__,
        "ck_admission_profile_area_resolution_basis",
    )
    # Verify all 3 enum values are listed
    for value in ("high_school", "permanent_address_special", "manual_override"):
        assert value in sql, f"enum value {value!r} missing from CHECK SQL"


def test_kv_check_excludes_underscore_form() -> None:
    """Canonical is KV2-NT (hyphen); underscore form 'KV2_NT' must be
    rejected by the regex. Locks m6 canonical-form decision."""
    from app.models import PriorityAreaConfig
    import re
    sql = _check_constraint_sql(
        PriorityAreaConfig.__table__,
        "ck_priority_area_config_area_code_format",
    )
    # Strip the SQL operator + quotes to extract just the regex pattern
    # vd: "area_code ~ '^KV[1-9](-NT)?$'"
    match = re.search(r"'(\^KV.+\$)'", sql)
    assert match, f"Couldn't extract regex from SQL: {sql!r}"
    pattern = match.group(1)
    # Compile the PG regex (use Python re — slight dialect diff but
    # core character class + anchor semantics match)
    py_re = re.compile(pattern)
    assert py_re.match("KV2-NT"), "Canonical KV2-NT must match"
    assert not py_re.match("KV2_NT"), "Underscore KV2_NT must be rejected"
    assert not py_re.match("kv1"), "Lowercase must be rejected"
    assert not py_re.match("KV1 "), "Trailing space must be rejected"
