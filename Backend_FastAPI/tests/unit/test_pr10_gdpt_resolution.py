"""PR #10 — unit tests cho SWAP Giấy CN hoàn thành GDPT (completed_thpt).

Pure resolution logic (no DB): the ``completed_*`` swap drops the diploma
(``compute_completed_doc_codes``) AND adds the GDPT certificate
(``compute_completed_add_doc_codes`` + ``build_completed_add_items`` +
``build_resolved_response(add_items=...)``).
"""
from types import SimpleNamespace

from app.services.document_resolution_service import (
    build_completed_add_items,
    build_resolved_response,
    compute_completed_add_doc_codes,
    compute_completed_doc_codes,
)


GDPT = "giay_cn_hoan_thanh_gdpt"
DIPLOMA = "bang_tot_nghiep_thpt"


def _profile(cultural):
    return SimpleNamespace(cultural_education_level=cultural)


def _doc_type(dt_id, code, name="X", order=1):
    return SimpleNamespace(id=dt_id, code=code, name=name, display_order=order)


def _map_item(dt_id, code, name="X", mandatory=True, upload=True, fmt="photo", order=1):
    dt = SimpleNamespace(code=code, name=name)
    item = SimpleNamespace(
        document_type_id=dt_id,
        document_type=dt,
        is_mandatory=mandatory,
        requires_upload=upload,
        submission_format=fmt,
        display_order=order,
    )
    return {dt_id: (item, "shared", None)}


# ---------------------------------------------------------------------------
# compute_completed_add_doc_codes — symmetric with the remove map
# ---------------------------------------------------------------------------


def test_completed_thpt_adds_gdpt():
    assert compute_completed_add_doc_codes(_profile("completed_thpt")) == {GDPT}


def test_completed_thpt_also_drops_diploma():
    # The swap is two-sided: drop the diploma AND add the GDPT cert.
    assert compute_completed_doc_codes(_profile("completed_thpt")) == {DIPLOMA}
    assert compute_completed_add_doc_codes(_profile("completed_thpt")) == {GDPT}


def test_graduated_thpt_adds_nothing_and_keeps_diploma():
    assert compute_completed_add_doc_codes(_profile("graduated_thpt")) == set()
    assert compute_completed_doc_codes(_profile("graduated_thpt")) == set()


def test_completed_thcs_adds_nothing_known_limitation():
    # completed_thcs has no source certificate yet → empty (GĐ1 limitation).
    assert compute_completed_add_doc_codes(_profile("completed_thcs")) == set()


def test_none_cultural_adds_nothing():
    assert compute_completed_add_doc_codes(_profile(None)) == set()


# ---------------------------------------------------------------------------
# build_completed_add_items — synthetic paper-only shape (finding #3)
# ---------------------------------------------------------------------------


def test_build_add_items_paper_only_shape():
    items = build_completed_add_items([_doc_type(9, GDPT, "Giấy CN GDPT", 45)])
    assert len(items) == 1
    it = items[0]
    assert it.document_type_id == 9
    assert it.document_type_code == GDPT
    assert it.document_type_name == "Giấy CN GDPT"
    assert it.is_mandatory is True
    assert it.requires_upload is False  # paper-only
    assert it.submission_format is None
    assert it.display_order == 45
    assert it.source == "shared"
    assert it.applicable_audience is None
    assert it.layer_kind == "shared_base"


def test_build_add_items_empty_for_no_doc_types():
    assert build_completed_add_items([]) == []


# ---------------------------------------------------------------------------
# build_resolved_response(add_items=...) — append + dedup + sort
# ---------------------------------------------------------------------------


def test_resolved_appends_add_item_when_absent():
    doc_map = _map_item(1, "hoc_ba", order=1)
    add = build_completed_add_items([_doc_type(9, GDPT, order=5)])
    resolved = build_resolved_response(doc_map, completed_codes=None, add_items=add)
    codes = [r.document_type_code for r in resolved]
    assert "hoc_ba" in codes
    assert GDPT in codes
    assert len(resolved) == 2


def test_resolved_dedups_add_item_when_code_already_present():
    # If a DocumentGroup already configured the GDPT cert, keep the config
    # row (requires_upload from config) and DO NOT append the synthetic one.
    doc_map = _map_item(9, GDPT, upload=True, order=5)
    add = build_completed_add_items([_doc_type(9, GDPT, order=5)])
    resolved = build_resolved_response(doc_map, completed_codes=None, add_items=add)
    gdpt_rows = [r for r in resolved if r.document_type_code == GDPT]
    assert len(gdpt_rows) == 1, "must not duplicate the GDPT cert"
    # The surviving row is the config one (requires_upload=True), not synthetic.
    assert gdpt_rows[0].requires_upload is True


def test_resolved_sorts_by_display_order_after_append():
    # add-item with a small display_order must sort before a larger config doc.
    doc_map = _map_item(1, "hoc_ba", order=10)
    add = build_completed_add_items([_doc_type(9, GDPT, order=3)])
    resolved = build_resolved_response(doc_map, completed_codes=None, add_items=add)
    assert [r.document_type_code for r in resolved] == [GDPT, "hoc_ba"]


def test_resolved_drops_diploma_and_adds_gdpt_together():
    # Full swap shape: a doc_map containing the diploma + completed_codes
    # dropping it + add_items injecting the GDPT cert.
    doc_map = {
        **_map_item(1, "hoc_ba", order=1),
        **_map_item(2, DIPLOMA, order=2),
    }
    add = build_completed_add_items([_doc_type(9, GDPT, order=2)])
    resolved = build_resolved_response(
        doc_map, completed_codes={DIPLOMA}, add_items=add
    )
    codes = {r.document_type_code for r in resolved}
    assert DIPLOMA not in codes, "diploma must be dropped for completed_thpt"
    assert GDPT in codes, "GDPT cert must be added"
    assert "hoc_ba" in codes
