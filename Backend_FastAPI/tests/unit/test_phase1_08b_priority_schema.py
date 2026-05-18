"""Unit tests for ``phase1_08b_priority_demographics_gdnn`` migration.

Q9 #07 PR1 — locks the schema contract for 4 new tables + 7 new columns
on admission_profile + 3 new snapshot columns on admission_profile_choice.

Pure-text contract tests. End-to-end alembic upgrade smoke runs in the
dev container as part of the verification step.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_08B = _VERSIONS_DIR / "phase1_08b_priority_demographics_gdnn.py"


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_08b():
    return _load_migration(_PHASE1_08B)


@pytest.fixture
def src() -> str:
    return _PHASE1_08B.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_revision_id_is_phase1_08b(phase1_08b) -> None:
    assert phase1_08b.revision == "phase1_08b"


def test_chains_off_phase1_08a(phase1_08b) -> None:
    assert phase1_08b.down_revision == "phase1_08a"


# ---------------------------------------------------------------------------
# 2. Four new tables ship
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "priority_area_config",
        "priority_object_config",
        "vn_commune_area_map",
        "vn_high_school",
    ],
)
def test_creates_table(src: str, table: str) -> None:
    assert f'create_table(\n        "{table}"' in src or f'"{table}"' in src
    # Ensure drop_table in downgrade
    assert f'drop_table("{table}")' in src


# ---------------------------------------------------------------------------
# 3. Partial UNIQUE indexes (B1 + M1 fix) — allow temporal history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "index_name",
    [
        "uq_priority_area_config_year_code_active",
        "uq_priority_object_config_year_sub_active",
        "uq_vn_commune_area_map_code_active",
    ],
)
def test_partial_unique_index(src: str, index_name: str) -> None:
    """Each "active row" UNIQUE is partial (WHERE effective_to IS NULL)
    so history rows can coexist — required for mid-year regulation
    changes and commune-merge events."""
    assert index_name in src


def test_partial_unique_uses_effective_to_null_predicate(src: str) -> None:
    # Pattern repeated for 3 partial UNIQUEs above
    assert src.count('postgresql_where=sa.text("effective_to IS NULL")') >= 3


# ---------------------------------------------------------------------------
# 4. CHECK regex (M2 fix) — catch typos at DB layer
# ---------------------------------------------------------------------------


def test_area_code_check_regex_uses_hyphen_canonical(src: str) -> None:
    """Canonical KV2-NT (hyphen) per TT 05/2021 Phụ lục 01 text —
    NOT KV2_NT (underscore). Regex must enforce hyphen form."""
    assert "'^KV[1-9](-NT)?$'" in src
    assert "ck_priority_area_config_area_code_format" in src
    assert "ck_vn_commune_area_map_area_code_format" in src
    assert "ck_vn_high_school_kv_code_format" in src


def test_group_code_and_sub_code_regex(src: str) -> None:
    assert "'^UT[1-9]$'" in src
    assert "ck_priority_object_config_group_code_format" in src
    assert "'^[0-9]{2}$'" in src
    assert "ck_priority_object_config_sub_code_format" in src


# ---------------------------------------------------------------------------
# 5. Soft-delete pattern (M3 fix) on vn_high_school
# ---------------------------------------------------------------------------


def test_vn_high_school_has_is_active_default_true(src: str) -> None:
    assert '"is_active"' in src
    assert 'server_default=sa.text("true")' in src


def test_high_school_id_fk_uses_restrict(src: str) -> None:
    """RESTRICT prevents hard DELETE while a profile references the row
    — admin must use is_active=false soft-delete instead. Preserves
    audit trail for "trường nào cho KV1?" questions years later."""
    assert 'ondelete="RESTRICT"' in src


# ---------------------------------------------------------------------------
# 6. effective_from default = CURRENT_DATE (M5 fix, not arbitrary epoch)
# ---------------------------------------------------------------------------


def test_effective_from_defaults_to_current_date(src: str) -> None:
    """4 tables each have effective_from with CURRENT_DATE default."""
    assert src.count('server_default=sa.text("CURRENT_DATE")') == 4


# ---------------------------------------------------------------------------
# 7. admission_profile — 7 new columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "high_school_id",
        "high_school_kv_resolved",
        "permanent_commune_code",
        "area_resolution_basis",
        "area_resolution_reason",
        "priority_object_codes",
        "priority_object_evidence",
    ],
)
def test_admission_profile_adds_column(src: str, column: str) -> None:
    assert f'"{column}"' in src
    # Downgrade drops each
    assert f'drop_column("admission_profile", "{column}")' in src


def test_priority_object_codes_and_evidence_are_not_null_with_default(
    src: str,
) -> None:
    """m2 fix lock: these 2 cols are NOT NULL with empty JSONB default
    so engine never receives NULL JSONB."""
    assert "'[]'::jsonb" in src
    assert "'{}'::jsonb" in src


# ---------------------------------------------------------------------------
# 8. admission_profile_choice — 3 snapshot columns (Q-P3-11 pattern)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "priority_area_bonus_snapshot",
        "priority_object_bonus_snapshot",
        "priority_config_snapshot",
    ],
)
def test_admission_profile_choice_adds_snapshot_column(
    src: str, column: str
) -> None:
    assert f'"{column}"' in src
    assert f'drop_column("admission_profile_choice", "{column}")' in src
