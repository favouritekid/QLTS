"""3-tier resolution rule tests for
``AdmissionPathService.resolve_documents_for_path`` (#184 Wave 1
PR-1C' / phase1_06).

PLAN line 619-623 + line 2683 contract — when resolving the
document checklist for an admission path:

1. **Tier 1**: any DocumentGroup with ``admission_path_id =
   path.id`` wins fully (ignore tier 2 + 3).
2. **Tier 2**: else any DocumentGroup with
   ``admission_path_id IS NULL`` AND ``admission_method_id =
   path.method`` wins fully (ignore tier 3).
3. **Tier 3**: else fall back to shared
   (``admission_path_id IS NULL`` AND ``admission_method_id IS
   NULL``).

Within a tier, mandatory-wins on duplicate document_type. Source
indicators on the response surface which tier provided each
document so admin can debug drift via FE.

What does NOT live here:
* Migration / schema shape — see
  ``test_phase1_05_06_revision_chain.py``.
* DocumentGroup invariant on path FK — see
  ``test_document_group_service_phase1_06_invariant.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.admission_path_service import AdmissionPathService


pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _doc_type(code: str, name: str = "doc"):
    return SimpleNamespace(code=code, name=name)


def _item(doc_type_code: str, *, is_mandatory=True, display_order=0):
    return SimpleNamespace(
        document_type_id=hash(doc_type_code) % 10_000,
        document_type=_doc_type(doc_type_code),
        is_mandatory=is_mandatory,
        requires_upload=True,
        submission_format=None,
        display_order=display_order,
    )


def _group(*items):
    return SimpleNamespace(items=list(items))


def _path(*, path_id=42, admission_method_id=10):
    return SimpleNamespace(id=path_id, admission_method_id=admission_method_id)


def _make_service(*, path_groups, method_groups, shared_groups):
    """Service stub whose repo returns the (path, method, shared)
    triple per the new repository contract."""
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = MagicMock()
    service.repo = MagicMock()
    service.repo.get_document_groups_for_path = AsyncMock(
        return_value=(path_groups, method_groups, shared_groups)
    )
    return service


# =============================================================================
# Tier precedence
# =============================================================================


class TestThreeTierPrecedence:
    @pytest.mark.asyncio
    async def test_tier1_path_wins_fully_over_tier2_and_tier3(self):
        """Path-level group present → tier 1 wins fully; tier 2 +
        tier 3 are ignored even if they would contribute different
        documents."""
        service = _make_service(
            path_groups=[_group(_item("CCCD", display_order=1))],
            method_groups=[_group(_item("HOC_BA", display_order=2))],
            shared_groups=[_group(_item("ANH3X4", display_order=3))],
        )
        resolved, _ = await service.resolve_documents_for_path(
            _path(), offering_type_id=5
        )
        codes = [doc.document_type_code for doc in resolved]
        assert codes == ["CCCD"]
        assert all(doc.source == "path_override" for doc in resolved)

    @pytest.mark.asyncio
    async def test_tier2_method_wins_when_no_path_groups(self):
        """No path-level groups → fall through to tier 2 (method)
        and ignore tier 3."""
        service = _make_service(
            path_groups=[],
            method_groups=[_group(_item("HOC_BA", display_order=2))],
            shared_groups=[_group(_item("ANH3X4", display_order=3))],
        )
        resolved, _ = await service.resolve_documents_for_path(
            _path(), offering_type_id=5
        )
        codes = [doc.document_type_code for doc in resolved]
        assert codes == ["HOC_BA"]
        assert all(doc.source == "method_override" for doc in resolved)

    @pytest.mark.asyncio
    async def test_tier3_shared_wins_when_no_path_no_method(self):
        """No path-level + no method-specific → fall through to
        shared tier."""
        service = _make_service(
            path_groups=[],
            method_groups=[],
            shared_groups=[_group(_item("ANH3X4", display_order=3))],
        )
        resolved, _ = await service.resolve_documents_for_path(
            _path(), offering_type_id=5
        )
        codes = [doc.document_type_code for doc in resolved]
        assert codes == ["ANH3X4"]
        assert all(doc.source == "shared" for doc in resolved)

    @pytest.mark.asyncio
    async def test_no_groups_at_any_tier_returns_empty_list(self):
        service = _make_service(
            path_groups=[], method_groups=[], shared_groups=[]
        )
        resolved, _ = await service.resolve_documents_for_path(
            _path(), offering_type_id=5
        )
        assert resolved == []


# =============================================================================
# Within-tier precedence — mandatory wins
# =============================================================================


class TestWithinTierMandatoryWins:
    @pytest.mark.asyncio
    async def test_path_tier_mandatory_overrides_optional(self):
        """Two path-level groups touch the same document_type — the
        mandatory item wins, mirroring legacy tier-2/tier-3 logic."""
        # Same document_type_code → same hash bucket.
        optional_first = _item("HOC_BA", is_mandatory=False, display_order=1)
        mandatory_second = _item("HOC_BA", is_mandatory=True, display_order=2)
        service = _make_service(
            path_groups=[_group(optional_first), _group(mandatory_second)],
            method_groups=[],
            shared_groups=[],
        )
        resolved, _ = await service.resolve_documents_for_path(
            _path(), offering_type_id=5
        )
        # One item only (same document_type), mandatory.
        assert len(resolved) == 1
        assert resolved[0].is_mandatory is True
        assert resolved[0].source == "path_override"


# =============================================================================
# Repository contract — caller passes path id only when path tier exists
# =============================================================================


class TestRepoContract:
    @pytest.mark.asyncio
    async def test_repo_receives_path_id_argument(self):
        """The service MUST pass ``path.id`` to the repo so tier-1
        query runs. A regression that drops the kwarg silently
        degrades the new feature back to 2-tier resolution."""
        service = _make_service(
            path_groups=[], method_groups=[], shared_groups=[]
        )
        await service.resolve_documents_for_path(
            _path(path_id=99), offering_type_id=5
        )
        kwargs = service.repo.get_document_groups_for_path.call_args.kwargs
        assert kwargs.get("admission_path_id") == 99
