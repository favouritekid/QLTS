"""Unit tests for #184 Wave 5-D migration ``phase1_16_create_archived_admission_profile_table``.

Pure-text + AST contract tests — locks the revision chain, table name, the
column-mirror invariant against the live ``AdmissionProfile`` model, the
archive metadata column, the ``(lead_id, academic_year)`` index per PLAN line
931-934, the no-constraint shape (FK/UQ/CHECK), the ENUM reuse pattern, and the
idempotent guard surface.

Live alembic roundtrip is DEFERRED to staging clone D12-D14 because the dev DB
is in a stamped-without-upgrade drift state for Wave 2 (``phase1_09a`` ENUM +
columns, ``phase1_10`` status_history). Production deploy will have the proper
chain so the ``conduct conduct_grade`` reference resolves.

What lives here:
1. Revision row + chain (``phase1_16`` → ``phase1_19c``).
2. Underscore-prefixed table name ``_archived_admission_profile``.
3. Mirror parity — every ``AdmissionProfile`` column name appears in the
   migration source (re-derived, NOT hardcoded).
4. Archive metadata column ``archived_at`` shape.
5. ``ix_archived_profile_lead_year`` composite index per PLAN line 933-934.
6. NO FK / UQ / CHECK constraints (archive must accept historical violators).
7. ``conduct conduct_grade`` ENUM uses ``create_type=False`` reuse pattern.
8. Idempotent guards (``table_exists`` + ``index_exists``) on both upgrade and
   downgrade paths.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_16 = (
    _VERSIONS_DIR / "phase1_16_create_archived_admission_profile_table.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_16.stem, _PHASE1_16)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration_by_revision(revision_id: str):
    """Nạp module migration theo revision id, không theo TÊN TỆP.

    Tên tệp không phải khoá: một revision có thể được đổi tên tệp mà id vẫn
    nguyên. Quét `revision: str = "<id>"` trong từng tệp rồi mới nạp.
    """
    for f in sorted(_VERSIONS_DIR.glob("*.py")):
        noi_dung = f.read_text(encoding="utf-8")
        if re.search(rf'^revision(?::\s*str)?\s*=\s*"{re.escape(revision_id)}"',
                     noi_dung, re.M):
            spec = importlib.util.spec_from_file_location(f.stem, f)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise AssertionError(f"khong tim thay migration co revision {revision_id!r}")


@pytest.fixture
def phase1_16():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_16.read_text(encoding="utf-8")


_TABLE = "_archived_admission_profile"


def _cot_khai_o_moi_migration() -> set:
    """Bộ cột của bảng archive, GỘP từ MỌI migration chạm tới nó.

    Bất biến thật không phải "phase1_16 liệt kê đủ cột" mà là "BẢNG archive soi
    gương ``AdmissionProfile``" — và một bảng hoàn toàn có thể được bồi thêm cột
    bằng ``op.add_column`` ở migration sau. Neo vào một tệp duy nhất làm phép
    kiểm sai theo cả hai chiều: đỏ oan khi cột được thêm ở nơi khác, và (nguy
    hơn) xanh oan nếu ai đó dựng lại bảng ở migration khác.

    Khoanh vùng bằng AST theo ĐÚNG lời gọi nhắm bảng này, không phải "tệp có
    nhắc tên bảng": ``phase1_17`` và ``phase2_01_v2`` đều nhắc tên bảng trong
    docstring/comment nhưng khai cột của BẢNG KHÁC (outbox, round). Lọc theo
    tên tệp sẽ nuốt trọn 28 cột lạ và làm phép đếm vô nghĩa.
    """
    cot = set()
    for f in sorted(_VERSIONS_DIR.glob("*.py")):
        noi_dung = f.read_text(encoding="utf-8")
        if _TABLE not in noi_dung:
            continue
        cay = ast.parse(noi_dung)

        # Hằng module trỏ đúng bảng này — migration dùng ``op.create_table(TABLE, …)``
        ten_hang = {
            t.id
            for n in ast.walk(cay)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
            and n.value.value == _TABLE
            for t in n.targets
            if isinstance(t, ast.Name)
        }

        def tro_dung_bang(nut) -> bool:
            if isinstance(nut, ast.Constant):
                return nut.value == _TABLE
            return isinstance(nut, ast.Name) and nut.id in ten_hang

        for n in ast.walk(cay):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr not in ("create_table", "add_column"):
                continue
            if not n.args or not tro_dung_bang(n.args[0]):
                continue
            for con in ast.walk(n):
                if (
                    isinstance(con, ast.Call)
                    and isinstance(con.func, ast.Attribute)
                    and con.func.attr == "Column"
                    and con.args
                    and isinstance(con.args[0], ast.Constant)
                ):
                    cot.add(con.args[0].value)
    return cot


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_16_revision_id(phase1_16) -> None:
    assert phase1_16.revision == "phase1_16"


def test_phase1_16_chains_off_phase1_19c(phase1_16) -> None:
    """Wave 5 ship-order chốt 2026-05-05 Codex round 19: alembic chain
    string-based, NOT numeric monotonic. ``phase1_16`` follows
    ``phase1_19c`` (Wave 5-A) so the archive table can be created before
    ``phase1_17`` (5-E) and ``phase1_19d`` (5-B) which depend on it."""
    # `a9312d02` CHÈN `phase1_19c5` vào giữa `phase1_19c` và mắt xích này
    # (chuyển seed HOA sang thường trước pre-flight của `phase3_01`). Đổi chain
    # là CỐ Ý, nên khẳng định cha trực tiếp theo trạng thái thật...
    assert phase1_16.down_revision == "phase1_19c5"

    # ...nhưng vẫn khoá ý định GỐC: chuỗi phải còn đi QUA `phase1_19c`. Nếu chỉ
    # sửa hằng số ở trên thành cha mới thì lần chèn kế tiếp lại âm thầm cắt
    # `phase1_19c` khỏi chuỗi mà không ca nào đỏ.
    ke = _load_migration_by_revision("phase1_19c5")
    assert ke.down_revision == "phase1_19c", (
        f"phase1_19c5 phải nối tiếp phase1_19c, đang là {ke.down_revision!r}"
    )


# ---------------------------------------------------------------------------
# 2. Table name + archive contract
# ---------------------------------------------------------------------------


def test_phase1_16_uses_underscore_prefixed_table_name(phase1_16) -> None:
    """PLAN line 124, 195, 562, 914, 931, 934 ALL use the leading-underscore
    convention to mark this as an internal/archive table, not a domain
    entity."""
    assert phase1_16.TABLE == "_archived_admission_profile"


def test_phase1_16_index_constant_matches_plan_line_933(phase1_16) -> None:
    assert phase1_16.INDEX_LEAD_YEAR == "ix_archived_profile_lead_year"


# ---------------------------------------------------------------------------
# 3. Column mirror parity — re-derived from AdmissionProfile model
# ---------------------------------------------------------------------------


def test_phase1_16_mirrors_every_admission_profile_column(src) -> None:
    """Re-derive the column list from the live ``AdmissionProfile`` model
    instead of hardcoding it. Memory ``verify-schema-before-proposing``: a
    later schema rename to source must not silently drift from the archive
    mirror — this check catches it."""
    from app.models.admission import AdmissionProfile

    source_columns = {c.name for c in AdmissionProfile.__table__.columns}
    missing = sorted(source_columns - _cot_khai_o_moi_migration())
    assert not missing, (
        f"bảng archive thiếu cột của AdmissionProfile: {missing}"
    )


def test_phase1_16_column_count_matches_source_plus_one(src) -> None:
    """Archive table = source columns + exactly 1 archive-metadata column
    (``archived_at``). No extra audit/discriminator columns until a
    multi-trigger archive lands."""
    from app.models.admission import AdmissionProfile

    source_count = len(AdmissionProfile.__table__.columns)
    unique = _cot_khai_o_moi_migration()
    assert len(unique) == source_count + 1, (
        f"Expected {source_count + 1} columns "
        f"({source_count} source + 1 archived_at), got {len(unique)}: {unique}"
    )


# ---------------------------------------------------------------------------
# 4. Archive metadata column
# ---------------------------------------------------------------------------


def test_phase1_16_archived_at_is_not_null_with_now_default(src) -> None:
    """``archived_at`` is the cron's INSERT marker — must not be nullable so
    every row carries a timestamp, and must default to ``now()`` so the cron
    INSERT statement does not need to set it explicitly."""
    # Match the multi-line column declaration via a single regex.
    pattern = re.compile(
        r'sa\.Column\(\s*"archived_at"[^)]*?'
        r'sa\.DateTime\(timezone=True\)[^)]*?'
        r'nullable=False[^)]*?'
        r'server_default=sa\.text\("now\(\)"\)',
        re.DOTALL,
    )
    assert pattern.search(src), "archived_at column shape mismatch"


# ---------------------------------------------------------------------------
# 5. Index per PLAN line 933-934
# ---------------------------------------------------------------------------


def test_phase1_16_creates_lead_year_composite_index(src) -> None:
    """PLAN line 931-934 mandates ``ix_archived_profile_lead_year`` on
    ``(lead_id, academic_year)`` — keeps ``Lead.current_admission_profile``
    UNION query (P1 fix #6 v2.12, PLAN line 911-928) fast against archive."""
    assert "ix_archived_profile_lead_year" in src
    # Regex tolerant to whitespace inside the column list.
    assert re.search(
        r'\[\s*"lead_id"\s*,\s*"academic_year"\s*\]', src
    ), "Index columns must be (lead_id, academic_year) in that order"


# ---------------------------------------------------------------------------
# 6. No FK / UQ / CHECK constraints
# ---------------------------------------------------------------------------


def test_phase1_16_declares_no_foreign_keys(src) -> None:
    """Archive must outlive source row deletes — no FK dependency on
    ``admission_profile.id`` / ``lead.id`` / ``user.id``."""
    assert "ForeignKey(" not in src


def test_phase1_16_declares_no_unique_constraints(src) -> None:
    """Wave 4 will swap the ``(lead_id)`` UNIQUE on ``admission_profile`` to
    composite ``(lead_id, academic_year)``. An archive row from BEFORE that
    swap must not be retroactively rejected — so the archive table mirrors
    NO unique surface."""
    assert "UniqueConstraint" not in src
    assert "unique=True" not in src


def test_phase1_16_declares_no_check_constraints(src) -> None:
    """Wave 3 ``phase1_11`` extends the status CHECK from 10 to 14 values.
    An archive row inserted before that extend must round-trip when the
    archive is re-queried — no CHECK on the archive table preserves it."""
    assert "CheckConstraint" not in src


# ---------------------------------------------------------------------------
# 7. ENUM reuse pattern
# ---------------------------------------------------------------------------


def test_phase1_16_reuses_conduct_grade_enum_without_creating(src) -> None:
    """``conduct_grade`` is owned by ``phase1_09a``. Archive table column
    must reference it with ``create_type=False`` so the migration does NOT
    try to ``CREATE TYPE`` again on a DB that already has it."""
    pattern = re.compile(
        r'postgresql\.ENUM\([^)]*?'
        r'name="conduct_grade"[^)]*?'
        r'create_type=False',
        re.DOTALL,
    )
    assert pattern.search(src), "conduct_grade ENUM must use create_type=False"


# ---------------------------------------------------------------------------
# 8. Idempotent guards
# ---------------------------------------------------------------------------


def test_phase1_16_upgrade_guards_table_create(src) -> None:
    """Idempotent re-run: a half-applied upgrade re-running must skip the
    ``CREATE TABLE`` if the table already exists."""
    assert "if not table_exists(TABLE):" in src


def test_phase1_16_upgrade_guards_index_create(src) -> None:
    assert "if not index_exists(TABLE, INDEX_LEAD_YEAR):" in src


def test_phase1_16_downgrade_short_circuits_when_table_missing(src) -> None:
    """Per ``phase1_19a`` template — drop_index against a missing parent
    table raises; downgrade returns early when the table is already gone."""
    pattern = re.compile(
        r"def downgrade\(\) -> None:\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"if not table_exists\(TABLE\):\s*\n\s*return",
        re.MULTILINE,
    )
    assert pattern.search(src), (
        "downgrade() must short-circuit when the table is already gone"
    )


def test_phase1_16_downgrade_drops_index_before_table(src) -> None:
    """Even though ``DROP TABLE`` cascades indexes, the explicit
    ``drop_index`` call lets a half-applied downgrade resume safely."""
    # Find the relative ordering of drop_index and drop_table in downgrade.
    downgrade_block = src[src.index("def downgrade("):]
    drop_index_pos = downgrade_block.index("op.drop_index(")
    drop_table_pos = downgrade_block.index("op.drop_table(")
    assert drop_index_pos < drop_table_pos


# ---------------------------------------------------------------------------
# 9. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_16_defines_upgrade_and_downgrade(phase1_16) -> None:
    assert callable(getattr(phase1_16, "upgrade", None))
    assert callable(getattr(phase1_16, "downgrade", None))
