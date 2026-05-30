"""Wave 6 PR #17 Phase 1 portion (#184 cutover prep) — tests for
public_admissions_service Phase 1 storefront refactor.

PLAN line 3565 #17 scope:
1. ``applicable_to`` audience filter (Wave 1 PR-1B' phase1_03 primitive).
2. 3-tier doc resolution delegation (Wave 1 PR-1C' phase1_06 primitive).

The Phase 2 portion — ``admission_round_id`` filter — is deferred to
the Phase 2 storefront PR paired with phase2_01 + phase2_02 (the
``OfferingAdmissionRound`` table + nullable FK on AdmissionPath are
not yet created).

What does NOT live here:
* JSONB GIN index plan tests — see DBA review on phase1_03 migration.
* AdmissionPathService.resolve_documents_for_path internals — see
  ``test_admission_path_resolution_3tier.py``.
* DocumentGroup invariant on path FK — see
  ``test_document_group_service_phase1_06_invariant.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.public_admissions import (
    PublicAdmissionsAudience,
    PublicAdmissionsDocumentsResponse,
)
from app.services import public_admissions_service


pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures — keep the surface small: enough for the public schema to
# validate, no more.
# =============================================================================


def _doc_type(code: str, name: str = "doc", description: str | None = None):
    return SimpleNamespace(
        code=code,
        name=name,
        description=description,
        is_active=True,
        display_order=0,
    )


def _doc_item(
    doc_type_code: str,
    *,
    is_mandatory: bool = True,
    display_order: int = 0,
):
    return SimpleNamespace(
        document_type_id=hash(doc_type_code) % 10_000,
        document_type=_doc_type(doc_type_code),
        is_mandatory=is_mandatory,
        requires_upload=True,
        submission_format=None,
        display_order=display_order,
    )


def _doc_group(
    *items,
    offering_type_id=5,
    admission_method_id=10,
    admission_path_id=None,
    applicable_audience=None,
):
    return SimpleNamespace(
        items=list(items),
        offering_type_id=offering_type_id,
        admission_method_id=admission_method_id,
        admission_path_id=admission_path_id,
        applicable_audience=applicable_audience,
        offering_type=SimpleNamespace(
            id=offering_type_id,
            code="OT",
            name="Chính quy",
            is_active=True,
        ),
        admission_method=SimpleNamespace(
            id=admission_method_id,
            code="HB",
            name="Học bạ",
            display_order=1,
        ),
    )


def _admission_path(*, path_id=42, method_id=10, offering_type_id=5):
    method = SimpleNamespace(
        id=method_id,
        code="HB",
        name="Học bạ",
        display_order=1,
    )
    offering_type = SimpleNamespace(
        id=offering_type_id,
        code="OT",
        name="Chính quy",
        is_active=True,
    )
    program = SimpleNamespace(id=100, name="CNTT", code="CNTT")
    offering = SimpleNamespace(
        id=200,
        offering_type_id=offering_type_id,
        offering_type=offering_type,
        program=program,
    )
    academic_info = SimpleNamespace(id=300, offering=offering)
    return SimpleNamespace(
        id=path_id,
        academic_info_id=academic_info.id,
        academic_info=academic_info,
        admission_method_id=method_id,
        admission_method=method,
    )


# =============================================================================
# Audience filter propagation
# =============================================================================


class TestAudienceFilterPropagation:
    @pytest.mark.asyncio
    async def test_audience_passed_to_load_paths_in_methods_catalog(
        self, monkeypatch
    ):
        """get_public_methods_catalog forwards the audience kwarg to
        ``_load_public_paths`` so the JSONB containment filter actually
        narrows the path set the catalog derives from.
        """
        captured = {}

        async def fake_snapshot(db):
            return [], {}, set()

        async def fake_load_paths(db, ids, audience=None, admission_round_id=None):
            captured["audience"] = audience
            return []

        monkeypatch.setattr(
            public_admissions_service,
            "_load_public_program_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            public_admissions_service, "_load_public_paths", fake_load_paths
        )

        await public_admissions_service.get_public_methods_catalog(
            db=MagicMock(), audience=PublicAdmissionsAudience.POST_THPT
        )

        assert captured["audience"] is PublicAdmissionsAudience.POST_THPT

    @pytest.mark.asyncio
    async def test_audience_none_propagates_unchanged(self, monkeypatch):
        """audience=None must reach _load_public_paths as None — the
        helper short-circuits the JSONB containment branch when None,
        preserving backward-compat behavior.
        """
        captured = {}

        async def fake_snapshot(db):
            return [], {}, set()

        async def fake_load_paths(db, ids, audience=None, admission_round_id=None):
            captured["audience"] = audience
            return []

        monkeypatch.setattr(
            public_admissions_service,
            "_load_public_program_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            public_admissions_service, "_load_public_paths", fake_load_paths
        )

        await public_admissions_service.get_public_methods_catalog(
            db=MagicMock(), audience=None
        )

        assert captured["audience"] is None

    @pytest.mark.asyncio
    async def test_audience_propagates_to_documents_catalog(self, monkeypatch):
        """get_public_documents_catalog forwards audience to
        ``_load_public_paths`` so that downstream 3-tier resolution
        runs against the narrowed path set.
        """
        captured = {}

        async def fake_snapshot(db):
            return [], {}, set()

        async def fake_load_paths(db, ids, audience=None, admission_round_id=None):
            captured["audience"] = audience
            return []

        async def fake_load_tiers(db, paths):
            return {}, {}, {}, {}, {}

        monkeypatch.setattr(
            public_admissions_service,
            "_load_public_program_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            public_admissions_service, "_load_public_paths", fake_load_paths
        )
        monkeypatch.setattr(
            public_admissions_service, "_load_path_document_tiers", fake_load_tiers
        )

        await public_admissions_service.get_public_documents_catalog(
            db=MagicMock(), audience=PublicAdmissionsAudience.LIEN_THONG_CD
        )

        assert captured["audience"] is PublicAdmissionsAudience.LIEN_THONG_CD

    @pytest.mark.asyncio
    async def test_tuition_catalog_accepts_audience_no_op(self, monkeypatch):
        """Tuition is offering-keyed (not path-keyed) so audience is a
        no-op for now. Phase 2 will narrow offerings via
        round+audience joins. Asserting the param is accepted without
        TypeError is the contract.
        """

        async def fake_snapshot(db):
            return [], {}, set()

        monkeypatch.setattr(
            public_admissions_service,
            "_load_public_program_snapshot",
            fake_snapshot,
        )

        # No assertion on internals — call returns the empty-state shape
        # which validates the response model, proving the param wired
        # cleanly through the public API.
        await public_admissions_service.get_public_tuition_catalog(
            db=MagicMock(), audience=PublicAdmissionsAudience.VLVH
        )


# =============================================================================
# 3-tier doc resolution aggregation in get_public_documents_catalog
# =============================================================================


class TestDocumentsCatalogTierAggregation:
    """Wave 6 #17 collapses per-path 3-tier resolution into the
    storefront's (offering_type_id, method_id) bucketed schema.

    Source per scope = highest tier observed across paths in scope.
    Mandatory-wins on duplicate document_type, both within tier and
    across paths sharing scope.

    All tests mock at the loader boundary so the aggregation logic is
    isolated from DB / SQLAlchemy.
    """

    @pytest.fixture(autouse=True)
    def _stub_program_snapshot(self, monkeypatch):
        """All documents-catalog tests share the same program snapshot
        stub — what varies is the path set + tier loader output.
        """

        async def fake_snapshot(db):
            return [], {}, {300}

        monkeypatch.setattr(
            public_admissions_service,
            "_load_public_program_snapshot",
            fake_snapshot,
        )

    async def _run(
        self,
        monkeypatch,
        *,
        paths,
        path_groups_by_path,
        method_groups_by_scope,
        shared_groups_by_offering_type,
        offering_type_models,
        method_models,
    ) -> PublicAdmissionsDocumentsResponse:
        async def fake_load_paths(db, ids, audience=None, admission_round_id=None):
            return paths

        async def fake_load_tiers(db, _paths):
            return (
                path_groups_by_path,
                method_groups_by_scope,
                shared_groups_by_offering_type,
                offering_type_models,
                method_models,
            )

        monkeypatch.setattr(
            public_admissions_service, "_load_public_paths", fake_load_paths
        )
        monkeypatch.setattr(
            public_admissions_service, "_load_path_document_tiers", fake_load_tiers
        )

        return await public_admissions_service.get_public_documents_catalog(
            db=MagicMock()
        )

    @pytest.mark.asyncio
    async def test_tier3_shared_only_attributes_source_shared(self, monkeypatch):
        """No path-specific or method-specific groups → response source
        = "shared" (Tier 3) for the (offering_type, method) bucket.
        """
        path = _admission_path()
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [_doc_group(_doc_item("CCCD"), admission_method_id=None)]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        assert len(result.offering_types) == 1
        ot = result.offering_types[0]
        assert len(ot.method_documents) == 1
        method_doc = ot.method_documents[0]
        assert method_doc.source == "shared"
        assert {d.document_type_code for d in method_doc.documents} == {"CCCD"}

    @pytest.mark.asyncio
    async def test_tier2_method_wins_over_tier3(self, monkeypatch):
        """Method-specific group present → response source =
        "method_override" (Tier 2). Tier 3 is ignored for the bucket.
        """
        path = _admission_path()
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={
                (5, 10): [_doc_group(_doc_item("HOC_BA"), admission_method_id=10)]
            },
            shared_groups_by_offering_type={
                5: [_doc_group(_doc_item("CCCD"), admission_method_id=None)]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        ot = result.offering_types[0]
        method_doc = ot.method_documents[0]
        assert method_doc.source == "method_override"
        assert {d.document_type_code for d in method_doc.documents} == {"HOC_BA"}

    @pytest.mark.asyncio
    async def test_tier1_path_wins_over_tier2_and_tier3(self, monkeypatch):
        """Path-specific group present → response source =
        "path_override" (Tier 1). Tier 2 + 3 ignored for the bucket.
        """
        path = _admission_path(path_id=42)
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={
                42: [
                    _doc_group(
                        _doc_item("PATH_DOC"),
                        admission_method_id=10,
                        admission_path_id=42,
                    )
                ]
            },
            method_groups_by_scope={
                (5, 10): [_doc_group(_doc_item("HOC_BA"), admission_method_id=10)]
            },
            shared_groups_by_offering_type={
                5: [_doc_group(_doc_item("CCCD"), admission_method_id=None)]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        ot = result.offering_types[0]
        method_doc = ot.method_documents[0]
        assert method_doc.source == "path_override"
        assert {d.document_type_code for d in method_doc.documents} == {"PATH_DOC"}

    @pytest.mark.asyncio
    async def test_scope_source_is_highest_tier_across_paths_in_scope(
        self, monkeypatch
    ):
        """When two paths share the same (offering_type, method)
        scope but resolve to different tiers (one path_override, one
        falls through to method/shared), the bucket source attribution
        = highest tier observed. Storefront returns one source per
        scope so the highest-tier ranking is the contract.
        """
        path_a = _admission_path(path_id=42)
        path_b = _admission_path(path_id=43)
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path_a, path_b],
            path_groups_by_path={
                42: [
                    _doc_group(
                        _doc_item("PATH_DOC"),
                        admission_method_id=10,
                        admission_path_id=42,
                    )
                ],
                # path 43 has no path-specific group → falls to method
            },
            method_groups_by_scope={
                (5, 10): [_doc_group(_doc_item("HOC_BA"), admission_method_id=10)]
            },
            shared_groups_by_offering_type={},
            offering_type_models={5: ot_model},
            method_models={10: path_a.admission_method},
        )

        ot = result.offering_types[0]
        method_doc = ot.method_documents[0]
        # path_override (rank 2) > method_override (rank 1) → bucket
        # source = path_override.
        assert method_doc.source == "path_override"
        # Mandatory-wins UNION of both paths' resolved docs.
        assert {d.document_type_code for d in method_doc.documents} == {
            "PATH_DOC",
            "HOC_BA",
        }

    @pytest.mark.asyncio
    async def test_mandatory_wins_within_tier(self, monkeypatch):
        """When the same document_type appears multiple times within
        the winning tier (e.g. two groups list it with different
        is_mandatory flags), the mandatory variant survives. Storefront
        consumers must not silently lose required-doc requirements
        because of group ordering.
        """
        path = _admission_path()
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={
                (5, 10): [
                    _doc_group(
                        _doc_item("CCCD", is_mandatory=False, display_order=1),
                        admission_method_id=10,
                    ),
                    _doc_group(
                        _doc_item("CCCD", is_mandatory=True, display_order=1),
                        admission_method_id=10,
                    ),
                ]
            },
            shared_groups_by_offering_type={},
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        ot = result.offering_types[0]
        method_doc = ot.method_documents[0]
        assert len(method_doc.documents) == 1
        assert method_doc.documents[0].is_mandatory is True

    @pytest.mark.asyncio
    async def test_offering_type_inactive_drops_from_response(self, monkeypatch):
        """Inactive offering_type model → entire bucket suppressed
        (storefront fail-closed contract).
        """
        path = _admission_path()
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=False
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={
                (5, 10): [_doc_group(_doc_item("HOC_BA"), admission_method_id=10)]
            },
            shared_groups_by_offering_type={},
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        assert result.offering_types == []
        assert result.summary.offering_type_count == 0

    @pytest.mark.asyncio
    async def test_shared_documents_at_offering_type_level(self, monkeypatch):
        """``shared_documents`` on the offering_type checklist surfaces
        the offering-type-wide tier-3 bucket distinct from per-method
        resolution. This used to be implicit in the previous 2-tier
        flow — Wave 6 #17 keeps the field populated even when a
        path-level override wins for some methods.
        """
        path = _admission_path()
        ot_model = SimpleNamespace(
            id=5, code="OT", name="Chính quy", is_active=True
        )
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [_doc_group(_doc_item("ANH3X4"), admission_method_id=None)]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )

        ot = result.offering_types[0]
        assert {d.document_type_code for d in ot.shared_documents} == {"ANH3X4"}
        assert all(d.source == "shared" for d in ot.shared_documents)

    # -------------------------------------------------------------------------
    # §9 (feat/document-group-audience-merge): tách NỀN vs audience_layers
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_shared_splits_nen_vs_audience_layers(self, monkeypatch):
        """Sau ĐỢT B: shared groups = NỀN + lớp audience. Catalog public TÁCH:
        shared_documents=NỀN; audience_layers=từng lớp (KHÔNG union dư)."""
        path = _admission_path()
        ot_model = SimpleNamespace(id=5, code="OT", name="Chính quy", is_active=True)
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [
                    _doc_group(_doc_item("CCCD"), admission_method_id=None),
                    _doc_group(
                        _doc_item("HB_THPT"),
                        admission_method_id=None,
                        applicable_audience=["POST_THPT"],
                    ),
                    _doc_group(
                        _doc_item("HB_THCS"),
                        admission_method_id=None,
                        applicable_audience=["POST_THCS"],
                    ),
                ]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )
        ot = result.offering_types[0]
        # NỀN: chỉ base, KHÔNG academic.
        assert {d.document_type_code for d in ot.shared_documents} == {"CCCD"}
        # audience_layers: 2 lớp, mỗi lớp đúng giấy của nó.
        layers = {l.audience: {d.document_type_code for d in l.documents} for l in ot.audience_layers}
        assert layers == {"POST_THPT": {"HB_THPT"}, "POST_THCS": {"HB_THCS"}}
        assert all(l.audience_label for l in ot.audience_layers)  # có nhãn

    @pytest.mark.asyncio
    async def test_method_fallback_uses_nen_not_audience_union(self, monkeypatch):
        """Method fallback tier shared chỉ lấy NỀN — KHÔNG union lớp audience
        (academic hiển thị riêng ở audience_layers)."""
        path = _admission_path()
        ot_model = SimpleNamespace(id=5, code="OT", name="Chính quy", is_active=True)
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [
                    _doc_group(_doc_item("CCCD"), admission_method_id=None),
                    _doc_group(
                        _doc_item("HB_THPT"),
                        admission_method_id=None,
                        applicable_audience=["POST_THPT"],
                    ),
                ]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )
        ot = result.offering_types[0]
        method_doc = ot.method_documents[0]
        # method shared-fallback = NỀN only (KHÔNG có HB_THPT).
        assert {d.document_type_code for d in method_doc.documents} == {"CCCD"}

    @pytest.mark.asyncio
    async def test_offering_type_with_only_audience_layers_included(self, monkeypatch):
        """Offering type chỉ có lớp audience (không NỀN) VẪN xuất hiện (skip
        condition tính cả audience_layers)."""
        path = _admission_path()
        ot_model = SimpleNamespace(id=5, code="OT", name="Chính quy", is_active=True)
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [
                    _doc_group(
                        _doc_item("HB_THCS"),
                        admission_method_id=None,
                        applicable_audience=["POST_THCS"],
                    )
                ]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )
        assert len(result.offering_types) == 1
        ot = result.offering_types[0]
        assert ot.shared_documents == []
        assert len(ot.audience_layers) == 1
        assert ot.audience_layers[0].audience == "POST_THCS"

    @pytest.mark.asyncio
    async def test_multi_audience_group_appears_in_both_layers(self, monkeypatch):
        """Group applicable_audience nhiều giá trị → xuất hiện ở MỌI layer khớp
        (review nit: loop trên array audience)."""
        path = _admission_path()
        ot_model = SimpleNamespace(id=5, code="OT", name="Chính quy", is_active=True)
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [
                    _doc_group(
                        _doc_item("SHARED_BOTH"),
                        admission_method_id=None,
                        applicable_audience=["POST_THPT", "POST_THCS"],
                    )
                ]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )
        ot = result.offering_types[0]
        layers = {
            l.audience: {d.document_type_code for d in l.documents}
            for l in ot.audience_layers
        }
        assert layers == {"POST_THPT": {"SHARED_BOTH"}, "POST_THCS": {"SHARED_BOTH"}}

    @pytest.mark.asyncio
    async def test_layer_merge_mandatory_wins(self, monkeypatch):
        """2 group cùng audience trùng doc-type (1 optional, 1 mandatory) → layer
        chọn mandatory (mandatory-wins TRONG lớp — review nit)."""
        path = _admission_path()
        ot_model = SimpleNamespace(id=5, code="OT", name="Chính quy", is_active=True)
        result = await self._run(
            monkeypatch,
            paths=[path],
            path_groups_by_path={},
            method_groups_by_scope={},
            shared_groups_by_offering_type={
                5: [
                    _doc_group(
                        _doc_item("HB", is_mandatory=False),
                        admission_method_id=None,
                        applicable_audience=["POST_THPT"],
                    ),
                    _doc_group(
                        _doc_item("HB", is_mandatory=True),
                        admission_method_id=None,
                        applicable_audience=["POST_THPT"],
                    ),
                ]
            },
            offering_type_models={5: ot_model},
            method_models={10: path.admission_method},
        )
        layer = result.offering_types[0].audience_layers[0]
        docs = {d.document_type_code: d.is_mandatory for d in layer.documents}
        assert docs == {"HB": True}  # mandatory wins


# =============================================================================
# Audience enum surface
# =============================================================================


class TestAudienceEnum:
    def test_enum_values_match_admission_path_applicable_to(self):
        """The PublicAdmissionsAudience enum mirrors the
        ``admission_audience`` PostgreSQL ENUM created by phase1_03.
        Drift on either side silently breaks the JSONB containment
        filter (string comparison fails) — anchor the pair here.
        """
        assert {a.value for a in PublicAdmissionsAudience} == {
            "POST_THCS",
            "POST_THPT",
            "LIEN_THONG_TC",
            "LIEN_THONG_CD",
            "VLVH",
        }
