"""Unit tests cho document_resolution_service (feat/document-group-audience-merge).

Pure logic, KHÔNG DB. Validate: derive_audience_set (cultural mapping + CONFIG_GAP
nuốt nội bộ — round-3 BLOCKER), filter_shared_by_audience, mandatory_wins_merge
(mandatory-wins + exclude_inactive G3), compute_completed_doc_codes (§6).
"""
import pytest
from types import SimpleNamespace

from app.services.document_resolution_service import (
    AUDIENCE_LABELS,
    compute_completed_doc_codes,
    derive_audience_set,
    filter_shared_by_audience,
    mandatory_wins_merge,
)

pytestmark = pytest.mark.unit


def _dt(code, *, is_active=True, name=None):
    return SimpleNamespace(code=code, is_active=is_active, name=name or code)


def _item(code, *, mandatory=True, active=True, order=1):
    return SimpleNamespace(
        document_type_id=hash(code) % 100000,
        document_type=_dt(code, is_active=active),
        is_mandatory=mandatory,
        requires_upload=True,
        submission_format="photo",
        display_order=order,
    )


def _group(items, *, audience=None):
    return SimpleNamespace(items=items, applicable_audience=audience)


# =============================================================================
# derive_audience_set — chiều văn hóa TRỰC TIẾP từ cultural
# =============================================================================
@pytest.mark.parametrize(
    "cultural,expected",
    [
        ("graduated_thpt", {"POST_THPT"}),
        ("completed_thpt", {"POST_THPT"}),
        ("graduated_gdtx", {"POST_THPT"}),
        ("graduated_thcs", {"POST_THCS"}),
        ("completed_thcs", {"POST_THCS"}),
        (None, set()),
        ("garbage", set()),
    ],
)
def test_derive_audience_cultural_dimension(cultural, expected):
    profile = SimpleNamespace(cultural_education_level=cultural)
    # path=None → chỉ chiều văn hóa.
    assert derive_audience_set(profile, None) == expected


def test_derive_audience_config_gap_swallowed_keeps_cultural():
    """round-3 BLOCKER: derive_target_level_and_type raise CONFIG_GAP (path
    chain chưa load) → KHÔNG raise ra ngoài, VẪN trả tập văn hóa."""
    profile = SimpleNamespace(cultural_education_level="graduated_thpt")
    # path không có chain eager-load → derive_target_level_and_type CONFIG_GAP.
    bad_path = SimpleNamespace(__dict__={})  # academic_info=None → CONFIG_GAP
    result = derive_audience_set(profile, bad_path)
    assert result == {"POST_THPT"}  # cultural dimension survives


def test_derive_audience_never_raises():
    profile = SimpleNamespace(cultural_education_level=None)
    bad_path = SimpleNamespace(__dict__={})
    assert derive_audience_set(profile, bad_path) == set()  # không raise


# =============================================================================
# filter_shared_by_audience — NỀN luôn merge + overlap
# =============================================================================
def test_filter_shared_none_audience_only_base():
    base = _group([_item("cccd")], audience=None)
    thpt = _group([_item("hoc_ba_thpt")], audience=["POST_THPT"])
    # audience_set=None (legacy/create) → CHỈ NỀN.
    result = filter_shared_by_audience([base, thpt], None)
    assert result == [base]


def test_filter_shared_base_plus_overlap():
    base = _group([_item("cccd")], audience=None)
    thpt = _group([_item("hoc_ba_thpt")], audience=["POST_THPT"])
    thcs = _group([_item("hoc_ba_thcs")], audience=["POST_THCS"])
    result = filter_shared_by_audience([base, thpt, thcs], {"POST_THPT"})
    assert base in result and thpt in result and thcs not in result


def test_filter_shared_empty_audience_set_only_base():
    base = _group([_item("cccd")], audience=None)
    thpt = _group([_item("hoc_ba_thpt")], audience=["POST_THPT"])
    # empty set && [POST_THPT] = false → chỉ NỀN.
    assert filter_shared_by_audience([base, thpt], set()) == [base]


# =============================================================================
# mandatory_wins_merge — mandatory thắng + exclude_inactive (G3)
# =============================================================================
def test_merge_mandatory_wins():
    optional_item = _item("x", mandatory=False)
    mandatory_item = _item("x", mandatory=True)
    # cùng document_type_id (code 'x') → mandatory override optional.
    optional_item.document_type_id = mandatory_item.document_type_id = 42
    doc_map = {}
    mandatory_wins_merge(doc_map, [_group([optional_item])], "shared")
    mandatory_wins_merge(doc_map, [_group([mandatory_item])], "shared")
    assert doc_map[42][0].is_mandatory is True


def test_merge_exclude_inactive_true_drops():
    inactive = _item("old", active=False)
    doc_map = {}
    mandatory_wins_merge(doc_map, [_group([inactive])], "shared", exclude_inactive=True)
    assert doc_map == {}


def test_merge_exclude_inactive_false_keeps():
    inactive = _item("old", active=False)
    doc_map = {}
    mandatory_wins_merge(doc_map, [_group([inactive])], "shared", exclude_inactive=False)
    assert len(doc_map) == 1  # path/create giữ doc inactive


def test_merge_stores_group_audience():
    it = _item("hoc_ba_thpt")
    doc_map = {}
    mandatory_wins_merge(doc_map, [_group([it], audience=["POST_THPT"])], "shared")
    _item_stored, source, grp_aud = doc_map[it.document_type_id]
    assert source == "shared" and grp_aud == ["POST_THPT"]


# =============================================================================
# compute_completed_doc_codes — completed_* loại bằng TN (§6)
# =============================================================================
@pytest.mark.parametrize(
    "cultural,expected",
    [
        ("completed_thpt", {"bang_tot_nghiep_thpt"}),
        ("completed_thcs", {"bang_tot_nghiep_thcs"}),
        ("graduated_thpt", set()),
        ("graduated_thcs", set()),
        (None, set()),
    ],
)
def test_compute_completed_doc_codes(cultural, expected):
    profile = SimpleNamespace(cultural_education_level=cultural)
    assert compute_completed_doc_codes(profile) == expected


def test_audience_labels_cover_all_five():
    assert set(AUDIENCE_LABELS) == {
        "POST_THCS", "POST_THPT", "LIEN_THONG_TC", "LIEN_THONG_CD", "VLVH",
    }
