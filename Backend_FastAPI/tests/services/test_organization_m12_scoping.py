# tests/services/test_organization_m12_scoping.py
"""
M12 FIX TESTS: Manager/Officer unit scoping on organization READ endpoints.

Verifies:
- Admin sees ALL data (no filtering)
- Manager sees ONLY managed units + descendants
- Officer sees ONLY their own unit + descendants
- Unknown role sees all data (Casbin handles endpoint access)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.core.constants import UserRole
from app.services import organization_service


# === Fixtures ===

@pytest.fixture
def mock_db_session():
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def admin_user():
    return models.User(id=1, username="admin", role=UserRole.ADMIN)


@pytest.fixture
def manager_user():
    return models.User(id=2, username="manager", role=UserRole.MANAGER, unit_id=10)


@pytest.fixture
def officer_user():
    return models.User(id=3, username="officer", role=UserRole.OFFICER, unit_id=20)


# === Sample tree data for testing ===

def _make_tree():
    """
    Create sample organization tree:
    Unit 1 (root)
      ├── Unit 10 (managed by manager)
      │     └── Unit 11 (child of 10)
      └── Unit 20 (officer's unit)
    Unit 2 (root, unrelated)
      └── Unit 21
    """
    return [
        {
            "id": 1, "name": "Root 1", "children": [
                {"id": 10, "name": "Managed", "children": [
                    {"id": 11, "name": "Child of Managed", "children": []},
                ]},
                {"id": 20, "name": "Officer Unit", "children": []},
            ]
        },
        {
            "id": 2, "name": "Root 2", "children": [
                {"id": 21, "name": "Unrelated Child", "children": []},
            ]
        },
    ]


# =============================================================================
# TESTS: _filter_tree_by_managed_units (pure function, no DB)
# =============================================================================


def test_filter_tree_managed_unit_at_root():
    """Manager manages root unit 1 → sees unit 1 and all its children."""
    tree = _make_tree()
    result = organization_service._filter_tree_by_managed_units(tree, {1})
    assert len(result) == 1
    assert result[0]["id"] == 1
    # Children should be preserved intact
    assert len(result[0]["children"]) == 2


def test_filter_tree_managed_unit_nested():
    """Manager manages unit 10 → sees unit 10 + its children, not siblings."""
    tree = _make_tree()
    result = organization_service._filter_tree_by_managed_units(tree, {10})
    assert len(result) == 1
    assert result[0]["id"] == 10
    assert len(result[0]["children"]) == 1
    assert result[0]["children"][0]["id"] == 11


def test_filter_tree_multiple_managed_units():
    """Manager manages units 10 and 2 → sees both subtrees."""
    tree = _make_tree()
    result = organization_service._filter_tree_by_managed_units(tree, {10, 2})
    ids = {n["id"] for n in result}
    assert ids == {10, 2}


def test_filter_tree_no_managed_units():
    """No managed units → empty result."""
    tree = _make_tree()
    result = organization_service._filter_tree_by_managed_units(tree, set())
    assert result == []


def test_filter_tree_nonexistent_ids():
    """Managed IDs not in tree → empty result."""
    tree = _make_tree()
    result = organization_service._filter_tree_by_managed_units(tree, {999, 888})
    assert result == []


# =============================================================================
# TESTS: _apply_unit_scoping (async, needs mock DB for Manager)
# =============================================================================


@pytest.mark.asyncio
async def test_apply_unit_scoping_no_user(mock_db_session):
    """No current_user → return full tree (no filtering)."""
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, None)
    assert len(result) == 2  # Both roots


@pytest.mark.asyncio
async def test_apply_unit_scoping_admin(mock_db_session, admin_user):
    """Admin → return full tree."""
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, admin_user)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_apply_unit_scoping_manager(mock_db_session, manager_user, mocker):
    """Manager with managed units → filtered tree."""
    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[10],
    )
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, manager_user)
    assert len(result) == 1
    assert result[0]["id"] == 10


@pytest.mark.asyncio
async def test_apply_unit_scoping_manager_no_managed_units(mock_db_session, manager_user, mocker):
    """Manager with no managed units → empty list."""
    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[],
    )
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, manager_user)
    assert result == []


@pytest.mark.asyncio
async def test_apply_unit_scoping_officer(mock_db_session, officer_user):
    """Officer with unit_id=20 → only sees unit 20 subtree."""
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, officer_user)
    assert len(result) == 1
    assert result[0]["id"] == 20


@pytest.mark.asyncio
async def test_apply_unit_scoping_officer_no_unit(mock_db_session):
    """Officer without unit_id → empty list."""
    officer_no_unit = models.User(id=5, username="nounit", role=UserRole.OFFICER, unit_id=None)
    tree = _make_tree()
    result = await organization_service._apply_unit_scoping(mock_db_session, tree, officer_no_unit)
    assert result == []


# =============================================================================
# TESTS: _get_allowed_unit_ids_for_user
# =============================================================================


@pytest.mark.asyncio
async def test_allowed_unit_ids_admin(mock_db_session, admin_user):
    """Admin → None (full access, no filtering)."""
    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, admin_user)
    assert result is None


@pytest.mark.asyncio
async def test_allowed_unit_ids_no_user(mock_db_session):
    """No user → None (full access)."""
    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, None)
    assert result is None


@pytest.mark.asyncio
async def test_allowed_unit_ids_manager(mock_db_session, manager_user, mocker):
    """Manager → set of managed unit IDs + descendants."""
    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[10],
    )
    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository",
        autospec=True,
    )
    mock_repo.return_value.get_descendant_unit_ids = AsyncMock(return_value=[10, 11, 12])

    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, manager_user)
    assert result == {10, 11, 12}


@pytest.mark.asyncio
async def test_allowed_unit_ids_manager_no_managed(mock_db_session, manager_user, mocker):
    """Manager with no managed units → empty set."""
    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[],
    )
    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, manager_user)
    assert result == set()


@pytest.mark.asyncio
async def test_allowed_unit_ids_officer(mock_db_session, officer_user, mocker):
    """Officer → set of own unit ID + descendants."""
    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository",
        autospec=True,
    )
    mock_repo.return_value.get_descendant_unit_ids = AsyncMock(return_value=[20, 22])

    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, officer_user)
    assert result == {20, 22}


@pytest.mark.asyncio
async def test_allowed_unit_ids_officer_no_unit(mock_db_session):
    """Officer without unit_id → empty set."""
    officer = models.User(id=5, username="nounit", role=UserRole.OFFICER, unit_id=None)
    result = await organization_service._get_allowed_unit_ids_for_user(mock_db_session, officer)
    assert result == set()


# =============================================================================
# TESTS: _filter_agg_tree_by_managed_units (Pydantic model tree)
# =============================================================================


def _make_agg_node(id, children=None):
    """Helper to create minimal OrganizationTreeNodeWithAggregation."""
    return schemas.OrganizationTreeNodeWithAggregation(
        id=id,
        name=f"Unit {id}",
        type="Khoa",
        description=None,
        parent_id=None,
        is_active=True,
        majors=[],
        stats=schemas.UnitAggregatedStats(
            total_majors=0, direct_majors=0,
            total_admission_quota=None,
            avg_tuition_fee=None, min_tuition_fee=None, max_tuition_fee=None,
        ),
        children=children or [],
    )


def test_filter_agg_tree_managed_at_root():
    """Managed unit at root → include it."""
    tree = [
        _make_agg_node(1, children=[_make_agg_node(10), _make_agg_node(20)]),
        _make_agg_node(2),
    ]
    result = organization_service._filter_agg_tree_by_managed_units(tree, {1})
    assert len(result) == 1
    assert result[0].id == 1


def test_filter_agg_tree_managed_nested():
    """Managed unit nested → extract subtree."""
    tree = [
        _make_agg_node(1, children=[_make_agg_node(10, children=[_make_agg_node(11)])]),
    ]
    result = organization_service._filter_agg_tree_by_managed_units(tree, {10})
    assert len(result) == 1
    assert result[0].id == 10
    assert len(result[0].children) == 1


def test_filter_agg_tree_empty_managed():
    """Empty managed set → empty result."""
    tree = [_make_agg_node(1)]
    result = organization_service._filter_agg_tree_by_managed_units(tree, set())
    assert result == []


# =============================================================================
# TESTS: get_all_program_offerings with scoping
# =============================================================================


@pytest.mark.asyncio
async def test_get_all_offerings_admin_no_filter(mock_db_session, admin_user, mocker):
    """Admin → all offerings returned unfiltered."""
    prog_a = MagicMock(unit_id=10)
    prog_b = MagicMock(unit_id=20)
    offering_a = MagicMock(program=prog_a)
    offering_b = MagicMock(program=prog_b)

    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository", autospec=True
    )
    mock_repo.return_value.get_all_offerings = AsyncMock(return_value=[offering_a, offering_b])

    result = await organization_service.get_all_program_offerings(
        mock_db_session, current_user=admin_user
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_all_offerings_manager_filtered(mock_db_session, manager_user, mocker):
    """Manager → only offerings from managed units."""
    prog_managed = MagicMock(unit_id=10)
    prog_other = MagicMock(unit_id=99)
    offering_managed = MagicMock(program=prog_managed)
    offering_other = MagicMock(program=prog_other)

    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository", autospec=True
    )
    mock_repo.return_value.get_all_offerings = AsyncMock(
        return_value=[offering_managed, offering_other]
    )
    mock_repo.return_value.get_descendant_unit_ids = AsyncMock(return_value=[10, 11])

    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[10],
    )

    result = await organization_service.get_all_program_offerings(
        mock_db_session, current_user=manager_user
    )
    assert len(result) == 1
    assert result[0].program.unit_id == 10


# =============================================================================
# TESTS: get_all_academic_infos with scoping
# =============================================================================


@pytest.mark.asyncio
async def test_get_all_academic_infos_admin_no_filter(mock_db_session, admin_user, mocker):
    """Admin → all academic infos returned unfiltered."""
    info_a = MagicMock(offering_id=100)
    info_b = MagicMock(offering_id=200)

    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository", autospec=True
    )
    mock_repo.return_value.get_all_academic_infos = AsyncMock(
        return_value=[(info_a, 0), (info_b, 1)]
    )

    # Mock the pydantic model_validate
    mocker.patch.object(
        schemas.OfferingAcademicInfo, "model_validate",
        side_effect=lambda obj: MagicMock(
            path_count=0, annual_admission_quota=0,
            admission_status=None,
        )
    )

    result = await organization_service.get_all_academic_infos(
        mock_db_session, current_user=admin_user
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_all_academic_infos_manager_filtered(mock_db_session, manager_user, mocker):
    """Manager → only academic infos from managed unit offerings."""
    info_managed = MagicMock(offering_id=100)  # offering 100 belongs to managed unit
    info_other = MagicMock(offering_id=200)    # offering 200 belongs to unmanaged unit

    mock_repo = mocker.patch(
        "app.services.organization_service.OrganizationRepository", autospec=True
    )
    mock_repo.return_value.get_all_academic_infos = AsyncMock(
        return_value=[(info_managed, 1), (info_other, 0)]
    )
    mock_repo.return_value.get_descendant_unit_ids = AsyncMock(return_value=[10, 11])

    mocker.patch(
        "app.services.organization_service._get_managed_unit_ids",
        new_callable=AsyncMock,
        return_value=[10],
    )

    # Mock the DB execute for allowed offering IDs query
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [100]  # Only offering 100 is in managed units
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock the pydantic model_validate
    mocker.patch.object(
        schemas.OfferingAcademicInfo, "model_validate",
        side_effect=lambda obj: MagicMock(
            path_count=0, annual_admission_quota=0,
            admission_status=None,
        )
    )

    result = await organization_service.get_all_academic_infos(
        mock_db_session, current_user=manager_user
    )
    # Only info_managed should remain (offering_id=100 is in allowed set)
    assert len(result) == 1
