"""Contract tests for ``docgrp_audience_bf_20260530`` backfill migration (ĐỢT B).

feat/document-group-audience-merge ĐỢT B — split bộ hồ sơ NỀN thành lớp
``applicable_audience`` (POST_THPT / POST_THCS). Verify migration:
1. Khoá revision chain (down_revision = ĐỢT A ``docgrp_audience_20260529``).
2. Phân loại doc code đúng (bang_diem_thpt ∈ POST_THPT — H2; POST_THCS = 2 mã;
   gate chinh_quy — §8.0).
3. Upgrade: MOVE item THPT (UPDATE group_id), tạo group lớp với cast
   ``::admission_audience[]``, INSERT item THCS gated chinh_quy, KHÔNG tạo
   group rỗng.
4. Idempotency: reuse group theo code + SELECT-trước-INSERT item THCS.
5. Downgrade HOÀN NGUYÊN split THẬT (H3): move THPT VỀ NỀN + xóa group POST_*;
   non-destructive (KHÔNG DROP TYPE, KHÔNG xóa config_document_type).
6. Guard code ≤ 50 (P2 — UNIQUE VARCHAR(50)).

Pattern theo ``test_migration_cleanup_uppercase.py`` — importlib-load module,
contract-assert revision + constants + SQL body. Run thật ở dev-DB roundtrip
pre-PR + CI integration sweep post-merge.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATION_FILE = "docgrp_audience_bf_20260530_backfill_split_layers.py"


@pytest.fixture
def migration():
    path = _VERSIONS_DIR / _MIGRATION_FILE
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, f"Cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module_src(migration):
    return inspect.getsource(migration)


# ---------------------------------------------------------------------------
# 1. Revision chain lock
# ---------------------------------------------------------------------------


def test_revision_id(migration):
    assert migration.revision == "docgrp_audience_bf_20260530"


def test_down_revision_chains_off_dot_a(migration):
    """Backfill (ĐỢT B) PHẢI revise off schema migration (ĐỢT A). Nếu migration
    khác land giữa commit này và merge → migration đó bump down_revision sang
    ``docgrp_audience_bf_20260530`` HOẶC rebase revision này lên head mới."""
    assert migration.down_revision == "docgrp_audience_20260529"


# ---------------------------------------------------------------------------
# 2. Phân loại doc code → lớp audience
# ---------------------------------------------------------------------------


def test_post_thpt_codes_include_bang_diem_thpt(migration):
    """H2: bang_diem_thpt PHẢI vào POST_THPT (KHÔNG để NỀN) — tránh ép
    TC-liên-thông-từ-THCS nộp bảng điểm THPT họ không có."""
    assert set(migration.POST_THPT_DOC_CODES) == {
        "hoc_ba_thpt",
        "bang_tot_nghiep_thpt",
        "bang_diem_thpt",
    }


def test_post_thcs_codes_are_the_two_existing_doc_types(migration):
    """§8.0: lớp POST_THCS dùng 2 doc type ĐÃ TỒN TẠI prod (§8.1 round-8)."""
    assert tuple(migration.POST_THCS_DOC_CODES) == (
        "hoc_ba_thcs",
        "bang_tot_nghiep_thcs",
    )


def test_post_thcs_gated_to_chinh_quy(migration):
    """§8.0: lớp POST_THCS CHỈ wire cho offering type chinh_quy (TC từ THCS).
    lien_thong/vlvh/... = known-limitation, admin upsert qua panel."""
    assert migration.CHINH_QUY_OT_CODE == "chinh_quy"
    src = inspect.getsource(migration.upgrade)
    assert "CHINH_QUY_OT_CODE" in src, (
        "Upgrade phải gate INSERT POST_THCS sau ot_code == CHINH_QUY_OT_CODE"
    )


# ---------------------------------------------------------------------------
# 3. Upgrade body — MOVE THPT + tạo group lớp + INSERT THCS, không group rỗng
# ---------------------------------------------------------------------------


def test_upgrade_moves_thpt_items_via_update_group_id(migration):
    """§8.2 SPLIT = MOVE: item THPT UPDATE sang group anh em (KHÔNG copy → tránh
    luôn bắt buộc; KHÔNG đụng uq_document_group_item vì target group khác)."""
    src = inspect.getsource(migration.upgrade)
    assert "UPDATE document_group_item SET group_id" in src, (
        "Split POST_THPT phải MOVE item qua UPDATE group_id."
    )


def test_upgrade_does_not_create_empty_thpt_group(migration):
    """§8.2: KHÔNG tạo group POST_THPT rỗng — chỉ tạo khi có item THPT để move."""
    src = inspect.getsource(migration.upgrade)
    assert "if thpt_items:" in src, (
        "Tạo group POST_THPT phải gated 'if thpt_items' (không tạo group rỗng)."
    )


def test_audience_group_insert_casts_enum_array(module_src):
    """Cột applicable_audience = ARRAY(admission_audience); INSERT PHẢI cast
    ``::admission_audience[]`` (N4) kẻo 'operator does not exist' / sai type."""
    assert "::admission_audience[]" in module_src, (
        "INSERT group lớp phải cast ARRAY[:aud]::admission_audience[]."
    )


def test_thcs_item_insert_present(module_src):
    """§8.0: INSERT item vào document_group_item cho lớp POST_THCS."""
    assert "INSERT INTO document_group_item" in module_src


# ---------------------------------------------------------------------------
# 4. Idempotency (N4) — reuse theo code + SELECT-trước-INSERT
# ---------------------------------------------------------------------------


def test_audience_group_reused_by_code(migration):
    """Rerun: group lớp đã tồn tại → reuse theo code (KHÔNG INSERT trùng →
    UNIQUE violation)."""
    src = inspect.getsource(migration._ensure_audience_group)
    assert "SELECT id FROM document_group WHERE code" in src
    assert "if existing is not None" in src, (
        "_ensure_audience_group phải reuse khi code đã tồn tại."
    )


def test_thcs_item_insert_guarded(migration):
    """Rerun: item THCS đã có (group, doc_type) → bỏ qua (idempotent)."""
    src = inspect.getsource(migration.upgrade)
    assert "FROM document_group_item" in src and "if exists:" in src, (
        "INSERT item THCS phải SELECT-trước (idempotent guard)."
    )


# ---------------------------------------------------------------------------
# 5. Downgrade — hoàn nguyên split THẬT (H3) + non-destructive
# ---------------------------------------------------------------------------


def test_downgrade_moves_thpt_back_to_nen(migration):
    """H3: downgrade PHẢI move item POST_THPT VỀ NỀN (UPDATE group_id = NỀN),
    KHÔNG chỉ drop cột — nếu để group tách đứng yên, code resolve cũ
    post-rollback merge TẤT CẢ shared group → hồ sơ mới over-require."""
    src = inspect.getsource(migration.downgrade)
    assert "UPDATE document_group_item SET group_id = :nen" in src, (
        "Downgrade phải move item POST_THPT về group NỀN."
    )
    assert "_POST_THPT" in src and "_POST_THCS" in src, (
        "Downgrade match group lớp theo code deterministic {nen}_POST_*."
    )


def test_downgrade_deletes_audience_groups(migration):
    src = inspect.getsource(migration.downgrade)
    assert "DELETE FROM document_group WHERE id" in src


def test_downgrade_is_non_destructive_to_doc_types(migration):
    """Non-destructive: downgrade KHÔNG drop enum admission_audience (ĐỢT A
    quản) cũng KHÔNG xóa config_document_type THCS (chỉ thêm, giữ lại)."""
    src = inspect.getsource(migration.downgrade)
    for forbidden in ("DROP TYPE", "config_document_type", "DROP COLUMN"):
        assert forbidden not in src, (
            f"Downgrade ĐỢT B phải non-destructive — token cấm {forbidden!r}."
        )


# ---------------------------------------------------------------------------
# 6. Code length guard (P2)
# ---------------------------------------------------------------------------


def test_audience_group_code_asserts_max_50(migration):
    """code group UNIQUE VARCHAR(50) → guard fail-loud khi vượt."""
    src = inspect.getsource(migration._audience_group_code)
    assert "<= 50" in src or "len(code)" in src, (
        "_audience_group_code phải assert độ dài ≤ 50."
    )
    # Smoke: code seed thực ngắn (≤ ~23) — không raise.
    assert migration._audience_group_code("HS_CHINH_QUY", "POST_THPT") == (
        "HS_CHINH_QUY_POST_THPT"
    )
    assert migration._audience_group_code("HS_LIEN_THONG", "POST_THCS") == (
        "HS_LIEN_THONG_POST_THCS"
    )


def test_audience_group_code_raises_when_too_long(migration):
    """Guard thực sự raise khi nen_code dài → code > 50."""
    long_code = "X" * 45  # 45 + len('_POST_THPT')=10 = 55 > 50
    with pytest.raises(AssertionError):
        migration._audience_group_code(long_code, "POST_THPT")
