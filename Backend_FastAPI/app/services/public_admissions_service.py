"""
Read-only service layer for the public admissions website.

The public site must fail-closed: only active programs, active offerings,
published academic information, and public admission paths are exposed.
"""
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.public_admissions import (
    PublicAdmissionsAcademicInfoSummary,
    PublicAdmissionsAudience,
    PublicAdmissionsDegreeLevelGroup,
    PublicAdmissionsDocumentRequirement,
    PublicAdmissionsDocumentsMeta,
    PublicAdmissionsDocumentsResponse,
    PublicAdmissionsDiscountPolicySummary,
    PublicAdmissionsMethodTag,
    PublicAdmissionsMethodDocumentChecklist,
    PublicAdmissionsMethodsMeta,
    PublicAdmissionsMethodsResponse,
    PublicAdmissionsMethodUsage,
    PublicAdmissionsOfferingSummary,
    PublicAdmissionsOfferingTypeDocumentChecklist,
    PublicAdmissionsAudienceDocumentLayer,
    PublicAdmissionsProgramsMeta,
    PublicAdmissionsProgramsResponse,
    PublicAdmissionsProgramSummary,
    PublicAdmissionsSubjectGroupUsage,
    PublicAdmissionsTuitionBand,
    PublicAdmissionsTuitionMeta,
    PublicAdmissionsTuitionOffering,
    PublicAdmissionsTuitionResponse,
)
from app.services.document_resolution_service import AUDIENCE_LABELS
from app.utils.datetime_helpers import today_vn


# Tier source precedence for #17 Wave 6 (Phase 1 portion). Higher index =
# higher tier (path > method > shared). Used to pick the highest-tier
# attribution when aggregating across paths sharing an
# (offering_type_id, method_id) bucket — the storefront response shape
# carries a single source per scope, so the aggregator must collapse.
_TIER_RANK = {"shared": 0, "method_override": 1, "path_override": 2}

PUBLIC_PATH_STATUS = "active"
PUBLIC_PATH_VISIBILITY = "public"
DEGREE_LEVEL_SORT_ORDER = {
    "Tiến sĩ": 0,
    "Thạc sĩ": 1,
    "Đại học": 2,
    "Cao đẳng": 3,
    "Trung cấp": 4,
    "Sơ cấp": 5,
}
OFFERING_TYPE_SORT_ORDER = {
    "Chính quy": 0,
    "Liên thông": 1,
    "Từ xa": 2,
    "Kết hợp": 3,
    "Vừa làm vừa học": 4,
}


def _sort_degree_level(value: str) -> Tuple[int, str]:
    return DEGREE_LEVEL_SORT_ORDER.get(value, 99), value.lower()


def _sort_offering_type(value: str) -> Tuple[int, str]:
    return OFFERING_TYPE_SORT_ORDER.get(value, 99), value.lower()


def _latest_public_academic_info(
    offering: models.ProgramOffering,
) -> Optional[models.OfferingAcademicInfo]:
    for info in offering.academic_info_history:
        if info.is_published and not info.is_deleted:
            return info
    return None


def _money_range(values: Iterable[Optional[Decimal]]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None, None
    return min(valid_values), max(valid_values)


def _extract_semester_data(
    academic_info,
) -> Tuple[List["PublicSemesterTuitionItem"], Optional[Decimal]]:
    """Extract per-semester tuition items + HK1 amount from a loaded academic info.

    Returns (items_ordered_by_semester_no, hk1_amount_or_None).
    """
    from app.schemas.public_admissions import PublicSemesterTuitionItem

    items = []
    hk1_amount = None
    for st in getattr(academic_info, "semester_tuitions", None) or []:
        items.append(PublicSemesterTuitionItem(semester_no=st.semester_no, amount=st.amount))
        if st.semester_no == 1:
            hk1_amount = st.amount
    return items, hk1_amount


async def _load_public_program_snapshot(
    db: AsyncSession,
    eligible_offering_ids: Optional[Set[int]] = None,
) -> Tuple[
    List[models.MajorProgram],
    Dict[int, models.OfferingAcademicInfo],
    Set[int],
]:
    """Load public programs/offering academic_info snapshot.

    When ``eligible_offering_ids`` is provided, only offerings with at
    least one public-eligible admission path are kept. This lets
    path-scoped endpoints fail closed instead of exposing tuition/program
    data for offerings that have no active public path in the selected
    round/audience window.
    """
    repo = OrganizationRepository(db)
    programs = await repo.get_all_major_programs(is_active=True)

    public_programs: List[models.MajorProgram] = []
    latest_info_by_offering_id: Dict[int, models.OfferingAcademicInfo] = {}
    academic_info_ids: Set[int] = set()

    for program in programs:
        public_offerings = []
        for offering in program.offerings:
            if not offering.is_active:
                continue
            if eligible_offering_ids is not None and offering.id not in eligible_offering_ids:
                continue

            public_info = _latest_public_academic_info(offering)
            if public_info is None:
                continue

            latest_info_by_offering_id[offering.id] = public_info
            academic_info_ids.add(public_info.id)
            public_offerings.append(offering)

        if public_offerings:
            public_programs.append(program)

    public_programs.sort(key=lambda program: (_sort_degree_level(program.degree_level), program.name.lower(), program.id))
    return public_programs, latest_info_by_offering_id, academic_info_ids


def _eligible_offering_ids_from_paths(
    paths: List[models.AdmissionPath],
) -> Set[int]:
    """Return offering IDs represented by public-eligible paths."""
    return {
        path.academic_info.offering_id
        for path in paths
        if path.academic_info is not None
        and path.academic_info.offering_id is not None
    }


def _filter_snapshot_by_eligible_offerings(
    programs: List[models.MajorProgram],
    latest_info_by_offering_id: Dict[int, models.OfferingAcademicInfo],
    eligible_offering_ids: Set[int],
) -> Tuple[
    List[models.MajorProgram],
    Dict[int, models.OfferingAcademicInfo],
]:
    """In-memory filter of pre-loaded snapshot by eligible offering IDs.

    PR-3 review fix #1 (2026-05-28): replaces the original 2× DB query
    pattern in `get_public_programs_catalog` + `get_public_tuition_catalog`
    (load full snapshot → load paths → derive eligible set → RE-LOAD
    snapshot with filter) with a single in-memory pass.

    Saves 1 DB round-trip + 1 SQL scan per request. Storefront cached
    via CDN so prod impact is small, but cold-miss + crawler traffic
    sees direct DB pressure.

    Does NOT mutate input models — returns a filtered VIEW. Drops:
      - offerings whose offering.id not in eligible_offering_ids
      - programs with zero remaining eligible offerings

    The downstream caller iterates ``program.offerings`` and checks
    ``latest_info_by_offering_id.get(offering.id)``; offerings with
    ``None`` lookup result are skipped naturally. We therefore filter
    the dict (drop non-eligible offerings) but leave ``program.offerings``
    untouched (no relationship mutation risk) — non-eligible offerings
    on a kept program simply get `None` from the dict and are skipped.
    """
    filtered_info_by_offering_id = {
        offering_id: academic_info
        for offering_id, academic_info in latest_info_by_offering_id.items()
        if offering_id in eligible_offering_ids
    }

    # Keep a program if at least one of its offerings is in the eligible
    # set AND was originally accepted by the snapshot (i.e. still in
    # latest_info_by_offering_id — passed is_active + is_published).
    filtered_programs: List[models.MajorProgram] = [
        program
        for program in programs
        if any(
            offering.id in filtered_info_by_offering_id
            for offering in program.offerings
        )
    ]

    return filtered_programs, filtered_info_by_offering_id


async def _load_public_paths(
    db: AsyncSession,
    academic_info_ids: Set[int],
    audience: Optional[PublicAdmissionsAudience] = None,
    admission_round_id: Optional[int] = None,
) -> List[models.AdmissionPath]:
    if not academic_info_ids:
        return []

    today = today_vn()
    conditions = [
        models.AdmissionPath.academic_info_id.in_(sorted(academic_info_ids)),
        models.AdmissionPath.status == PUBLIC_PATH_STATUS,
        models.AdmissionPath.visibility == PUBLIC_PATH_VISIBILITY,
        # F43 — storefront only serves paths whose round is *public-eligible*.
        # We ALWAYS join + filter OfferingAdmissionRound, even when the
        # caller passes no admission_round_id. Public-eligible round =
        # active + not soft-archived + within its [start_date, end_date]
        # window (NULL bound = open-ended). This closes the leak where an
        # expired round (e.g. DOT_1 past its end_date) kept serving its
        # active+public paths alongside the open round under round=None.
        # admission_round_id is NOT NULL on AdmissionPath (PR-2C v2), so
        # the inner join never drops a legitimate path.
        models.OfferingAdmissionRound.is_active.is_(True),
        models.OfferingAdmissionRound.archived_at.is_(None),
        or_(
            models.OfferingAdmissionRound.start_date.is_(None),
            models.OfferingAdmissionRound.start_date <= today,
        ),
        or_(
            models.OfferingAdmissionRound.end_date.is_(None),
            models.OfferingAdmissionRound.end_date >= today,
        ),
    ]
    # When the caller pins a specific round we still apply the
    # public-eligible guard above — an explicit expired/archived/future
    # admission_round_id therefore returns zero paths (no stale data).
    if admission_round_id is not None:
        conditions.append(
            models.AdmissionPath.admission_round_id == admission_round_id
        )
    if audience is not None:
        # phase1_03 audience filter — JSONB ARRAY @> containment.
        # NULL applicable_to = legacy / applies to every audience
        # (Phase 1+2 query contract preserves NULL via OR branch
        # per AdmissionPath model line 161-167). MUST use contains()
        # not = ANY() so the ix_admission_path_applicable_to GIN
        # index is hit (model comment line 165-166).
        conditions.append(
            or_(
                models.AdmissionPath.applicable_to.is_(None),
                models.AdmissionPath.applicable_to.contains([audience.value]),
            )
        )

    query = (
        select(models.AdmissionPath)
        .join(
            models.OfferingAdmissionRound,
            models.AdmissionPath.admission_round_id
            == models.OfferingAdmissionRound.id,
        )
        .where(*conditions)
        .options(
            selectinload(models.AdmissionPath.academic_info)
            .selectinload(models.OfferingAcademicInfo.offering)
            .selectinload(models.ProgramOffering.program),
            selectinload(models.AdmissionPath.admission_method),
            selectinload(models.AdmissionPath.criteria)
            .selectinload(models.AdmissionCriteria.subject_group_mappings)
            .selectinload(models.CriteriaSubjectGroup.subject_group)
            .selectinload(models.SubjectGroup.subject_mappings)
            .selectinload(models.SubjectGroupSubject.subject),
        )
        .order_by(models.AdmissionPath.display_order, models.AdmissionPath.id)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


def _build_method_lookup(
    paths: List[models.AdmissionPath],
) -> Dict[int, List[PublicAdmissionsMethodTag]]:
    methods_by_academic_info: Dict[int, Dict[int, models.AdmissionMethod]] = defaultdict(dict)

    for path in paths:
        method = path.admission_method
        if method is None:
            continue
        methods_by_academic_info[path.academic_info_id][method.id] = method

    response: Dict[int, List[PublicAdmissionsMethodTag]] = {}
    for academic_info_id, methods in methods_by_academic_info.items():
        ordered_methods = sorted(
            methods.values(),
            key=lambda item: (item.display_order, item.name.lower(), item.id),
        )
        response[academic_info_id] = [
            PublicAdmissionsMethodTag(id=item.id, code=item.code, name=item.name)
            for item in ordered_methods
        ]
    return response


async def _load_path_document_tiers(
    db: AsyncSession,
    paths: List[models.AdmissionPath],
) -> Tuple[
    Dict[int, List[models.DocumentGroup]],
    Dict[Tuple[int, int], List[models.DocumentGroup]],
    Dict[int, List[models.DocumentGroup]],
    Dict[int, "models.ConfigOfferingType"],
    Dict[int, "models.AdmissionMethod"],
]:
    """Batch-load document groups for the 3-tier resolution rule
    (phase1_06 / #184 Wave 1 PR-1C') across the given paths.

    Three queries (one per tier) keyed by:
    * **Tier 1** ``path_groups_by_path[path_id]`` — admission_path_id
      matches; per-path-specific override.
    * **Tier 2** ``method_groups_by_scope[(offering_type_id, method_id)]``
      — admission_path_id IS NULL AND method matches; legacy
      method-specific bucket.
    * **Tier 3** ``shared_groups_by_offering_type[offering_type_id]`` —
      admission_path_id IS NULL AND admission_method_id IS NULL;
      offering-type-wide shared bucket.

    Also returns offering_type + admission_method model maps populated
    from eager-loaded relationships, so the caller can build the
    public response without extra round trips.

    The aggregator (``get_public_documents_catalog``) applies tier
    precedence per path (highest non-empty tier wins fully, mandatory-
    wins within the tier) and collapses to the storefront's
    (offering_type, method) bucketed schema.
    """
    if not paths:
        return {}, {}, {}, {}, {}

    path_ids: Set[int] = {p.id for p in paths}
    method_ids: Set[int] = {
        p.admission_method_id for p in paths if p.admission_method_id is not None
    }
    offering_type_ids: Set[int] = set()
    for p in paths:
        ot_id = (
            p.academic_info.offering.offering_type_id
            if p.academic_info and p.academic_info.offering
            else None
        )
        if ot_id is not None:
            offering_type_ids.add(ot_id)

    path_groups_by_path: Dict[int, List[models.DocumentGroup]] = defaultdict(list)
    method_groups_by_scope: Dict[
        Tuple[int, int], List[models.DocumentGroup]
    ] = defaultdict(list)
    shared_groups_by_offering_type: Dict[int, List[models.DocumentGroup]] = defaultdict(
        list
    )
    offering_type_models: Dict[int, "models.ConfigOfferingType"] = {}
    method_models: Dict[int, "models.AdmissionMethod"] = {}

    common_options = (
        selectinload(models.DocumentGroup.items).selectinload(
            models.DocumentGroupItem.document_type
        ),
        selectinload(models.DocumentGroup.offering_type),
        selectinload(models.DocumentGroup.admission_method),
    )

    if path_ids:
        path_query = (
            select(models.DocumentGroup)
            .where(
                models.DocumentGroup.admission_path_id.in_(sorted(path_ids)),
                models.DocumentGroup.is_active == True,  # noqa: E712
            )
            .options(*common_options)
        )
        result = await db.execute(path_query)
        for group in result.scalars().all():
            path_groups_by_path[group.admission_path_id].append(group)
            if group.offering_type is not None:
                offering_type_models[group.offering_type_id] = group.offering_type
            if group.admission_method is not None:
                method_models[group.admission_method_id] = group.admission_method

    if method_ids and offering_type_ids:
        method_query = (
            select(models.DocumentGroup)
            .where(
                models.DocumentGroup.offering_type_id.in_(sorted(offering_type_ids)),
                models.DocumentGroup.admission_method_id.in_(sorted(method_ids)),
                models.DocumentGroup.admission_path_id.is_(None),
                models.DocumentGroup.is_active == True,  # noqa: E712
            )
            .options(*common_options)
        )
        result = await db.execute(method_query)
        for group in result.scalars().all():
            method_groups_by_scope[
                (group.offering_type_id, group.admission_method_id)
            ].append(group)
            if group.offering_type is not None:
                offering_type_models[group.offering_type_id] = group.offering_type
            if group.admission_method is not None:
                method_models[group.admission_method_id] = group.admission_method

    if offering_type_ids:
        shared_query = (
            select(models.DocumentGroup)
            .where(
                models.DocumentGroup.offering_type_id.in_(sorted(offering_type_ids)),
                models.DocumentGroup.admission_method_id.is_(None),
                models.DocumentGroup.admission_path_id.is_(None),
                models.DocumentGroup.is_active == True,  # noqa: E712
            )
            .options(*common_options)
        )
        result = await db.execute(shared_query)
        for group in result.scalars().all():
            shared_groups_by_offering_type[group.offering_type_id].append(group)
            if group.offering_type is not None:
                offering_type_models[group.offering_type_id] = group.offering_type

    return (
        path_groups_by_path,
        method_groups_by_scope,
        shared_groups_by_offering_type,
        offering_type_models,
        method_models,
    )


def _merge_items_with_mandatory_wins(
    target: Dict[int, "models.DocumentGroupItem"],
    groups: Iterable[models.DocumentGroup],
) -> None:
    """Mandatory-wins merge mirror of
    AdmissionPathService.resolve_documents_for_path tier-internal
    aggregation. Mutates ``target`` in place.
    """
    for group in groups:
        for item in group.items:
            if item.document_type is None or not item.document_type.is_active:
                continue
            existing = target.get(item.document_type_id)
            if existing is None or (item.is_mandatory and not existing.is_mandatory):
                target[item.document_type_id] = item


def _items_to_public_documents(
    items: Iterable["models.DocumentGroupItem"],
    source: str,
) -> List[PublicAdmissionsDocumentRequirement]:
    docs = [
        PublicAdmissionsDocumentRequirement(
            document_type_id=item.document_type_id,
            document_type_code=item.document_type.code,
            document_type_name=item.document_type.name,
            document_type_description=item.document_type.description,
            is_mandatory=item.is_mandatory,
            requires_upload=item.requires_upload,
            submission_format=item.submission_format,
            display_order=item.display_order,
            source=source,
        )
        for item in items
    ]
    return sorted(
        docs,
        key=lambda doc: (
            doc.display_order,
            doc.document_type_name.lower(),
            doc.document_type_id,
        ),
    )


async def get_public_programs_catalog(
    db: AsyncSession,
    audience: Optional[PublicAdmissionsAudience] = None,
    admission_round_id: Optional[int] = None,
) -> PublicAdmissionsProgramsResponse:
    """Public programs catalog, fail-closed by public-eligible paths.

    ``admission_round_id=None`` means union of public-eligible active
    rounds only (not historical rounds). Explicit round IDs are still
    filtered through the same eligibility guard.
    """
    programs, latest_info_by_offering_id, academic_info_ids = await _load_public_program_snapshot(db)
    public_paths = await _load_public_paths(
        db, academic_info_ids,
        audience=audience,
        admission_round_id=admission_round_id,
    )
    eligible_offering_ids = _eligible_offering_ids_from_paths(public_paths)
    # PR-3 review fix #1 (2026-05-28): in-memory filter instead of
    # second _load_public_program_snapshot call — saves 1 DB round-trip
    # per request (storefront cold-miss + crawler traffic benefit).
    programs, latest_info_by_offering_id = _filter_snapshot_by_eligible_offerings(
        programs, latest_info_by_offering_id, eligible_offering_ids,
    )
    method_tags_by_info_id = _build_method_lookup(
        public_paths
    )

    degree_groups: Dict[str, List[PublicAdmissionsProgramSummary]] = defaultdict(list)
    offering_types: Set[str] = set()
    academic_years: Set[int] = set()

    for program in programs:
        program_offerings: List[PublicAdmissionsOfferingSummary] = []
        program_tuition_values: List[Optional[Decimal]] = []
        program_hk1_values: List[Optional[Decimal]] = []
        program_years: Set[int] = set()

        ordered_offerings = sorted(
            program.offerings,
            key=lambda item: (_sort_offering_type(item.offering_type), item.id),
        )
        for offering in ordered_offerings:
            academic_info = latest_info_by_offering_id.get(offering.id)
            if academic_info is None:
                continue

            offering_types.add(offering.offering_type)
            academic_years.add(academic_info.academic_year)
            program_years.add(academic_info.academic_year)
            program_tuition_values.append(academic_info.tuition_fee_per_year)

            sem_items, hk1_amount = _extract_semester_data(academic_info)
            program_hk1_values.append(hk1_amount)

            program_offerings.append(
                PublicAdmissionsOfferingSummary(
                    id=offering.id,
                    offering_type=offering.offering_type,
                    duration_semesters=offering.duration_semesters,
                    total_credits=offering.total_credits,
                    academic_info=PublicAdmissionsAcademicInfoSummary(
                        id=academic_info.id,
                        academic_year=academic_info.academic_year,
                        tuition_fee_per_year=academic_info.tuition_fee_per_year,
                        annual_admission_quota=academic_info.annual_admission_quota,
                        cutoff_score_previous_year=academic_info.cutoff_score_previous_year,
                        target_audience=academic_info.target_audience,
                        applied_discount_policy_ids=academic_info.applied_discount_policy_ids or [],
                        semester_tuitions=sem_items,
                        semester_1_tuition=hk1_amount,
                    ),
                    admission_methods=method_tags_by_info_id.get(academic_info.id, []),
                )
            )

        if not program_offerings:
            continue

        tuition_min, tuition_max = _money_range(program_tuition_values)
        hk1_min, hk1_max = _money_range(program_hk1_values)
        degree_groups[program.degree_level].append(
            PublicAdmissionsProgramSummary(
                id=program.id,
                code=program.code,
                name=program.name,
                degree_level=program.degree_level,
                is_heavy=program.is_heavy,
                offering_count=len(program_offerings),
                academic_years=sorted(program_years, reverse=True),
                tuition_min=tuition_min,
                tuition_max=tuition_max,
                semester_1_tuition_min=hk1_min,
                semester_1_tuition_max=hk1_max,
                offerings=program_offerings,
            )
        )

    degree_level_items: List[PublicAdmissionsDegreeLevelGroup] = []
    for degree_level in sorted(degree_groups.keys(), key=_sort_degree_level):
        programs_in_group = sorted(
            degree_groups[degree_level],
            key=lambda item: (item.name.lower(), item.id),
        )
        group_tuition_values = [
            offering.academic_info.tuition_fee_per_year
            for program in programs_in_group
            for offering in program.offerings
        ]
        group_hk1_values = [
            offering.academic_info.semester_1_tuition
            for program in programs_in_group
            for offering in program.offerings
        ]
        group_years = sorted(
            {year for program in programs_in_group for year in program.academic_years},
            reverse=True,
        )
        group_offering_types = sorted(
            {offering.offering_type for program in programs_in_group for offering in program.offerings},
            key=_sort_offering_type,
        )
        tuition_min, tuition_max = _money_range(group_tuition_values)
        hk1_min, hk1_max = _money_range(group_hk1_values)
        degree_level_items.append(
            PublicAdmissionsDegreeLevelGroup(
                degree_level=degree_level,
                program_count=len(programs_in_group),
                offering_count=sum(program.offering_count for program in programs_in_group),
                offering_types=group_offering_types,
                academic_years=group_years,
                tuition_min=tuition_min,
                tuition_max=tuition_max,
                semester_1_tuition_min=hk1_min,
                semester_1_tuition_max=hk1_max,
                programs=programs_in_group,
            )
        )

    summary = PublicAdmissionsProgramsMeta(
        degree_level_count=len(degree_level_items),
        program_count=sum(item.program_count for item in degree_level_items),
        offering_count=sum(item.offering_count for item in degree_level_items),
        latest_academic_year=max(academic_years) if academic_years else None,
        offering_types=sorted(offering_types, key=_sort_offering_type),
    )
    return PublicAdmissionsProgramsResponse(summary=summary, degree_levels=degree_level_items)


async def get_public_methods_catalog(
    db: AsyncSession,
    audience: Optional[PublicAdmissionsAudience] = None,
    admission_round_id: Optional[int] = None,
) -> PublicAdmissionsMethodsResponse:
    """Phase 2 v8.2 PR-2B v2 (Wave 6 #17 P2) — admission_round_id
    optional filter wired through _load_public_paths."""
    _, _, academic_info_ids = await _load_public_program_snapshot(db)
    paths = await _load_public_paths(
        db, academic_info_ids,
        audience=audience,
        admission_round_id=admission_round_id,
    )

    method_models: Dict[int, models.AdmissionMethod] = {}
    method_program_ids: Dict[int, Set[int]] = defaultdict(set)
    method_offering_ids: Dict[int, Set[int]] = defaultdict(set)
    method_path_ids: Dict[int, Set[int]] = defaultdict(set)
    method_years: Dict[int, Set[int]] = defaultdict(set)

    subject_group_models: Dict[int, models.SubjectGroup] = {}
    subject_group_method_codes: Dict[int, Set[str]] = defaultdict(set)
    subject_group_path_ids: Dict[int, Set[int]] = defaultdict(set)

    for path in paths:
        method = path.admission_method
        academic_info = path.academic_info
        offering = academic_info.offering if academic_info else None
        program = offering.program if offering else None

        if method is None or academic_info is None or offering is None or program is None:
            continue

        method_models[method.id] = method
        method_program_ids[method.id].add(program.id)
        method_offering_ids[method.id].add(offering.id)
        method_path_ids[method.id].add(path.id)
        method_years[method.id].add(academic_info.academic_year)

        criteria = path.criteria
        if criteria is None:
            continue

        for mapping in criteria.subject_group_mappings:
            subject_group = mapping.subject_group
            if subject_group is None:
                continue
            subject_group_models[subject_group.id] = subject_group
            subject_group_method_codes[subject_group.id].add(method.code)
            subject_group_path_ids[subject_group.id].add(path.id)

    methods = [
        PublicAdmissionsMethodUsage(
            id=method.id,
            code=method.code,
            name=method.name,
            description=method.description,
            requires_gpa=method.requires_gpa,
            requires_subject_scores=method.requires_subject_scores,
            public_program_count=len(method_program_ids[method.id]),
            public_offering_count=len(method_offering_ids[method.id]),
            public_path_count=len(method_path_ids[method.id]),
            academic_years=sorted(method_years[method.id], reverse=True),
        )
        for method in sorted(
            method_models.values(),
            key=lambda item: (item.display_order, item.name.lower(), item.id),
        )
    ]

    subject_groups = []
    for subject_group in sorted(subject_group_models.values(), key=lambda item: (item.display_order, item.code)):
        subjects = [
            mapping.subject.name_vi
            for mapping in subject_group.subject_mappings
            if mapping.subject is not None
        ]
        subject_groups.append(
            PublicAdmissionsSubjectGroupUsage(
                id=subject_group.id,
                code=subject_group.code,
                name=subject_group.name,
                subjects=subjects,
                method_codes=sorted(subject_group_method_codes[subject_group.id]),
                public_path_count=len(subject_group_path_ids[subject_group.id]),
            )
        )

    return PublicAdmissionsMethodsResponse(
        summary=PublicAdmissionsMethodsMeta(
            method_count=len(methods),
            subject_group_count=len(subject_groups),
            public_path_count=len(paths),
        ),
        methods=methods,
        subject_groups=subject_groups,
    )


async def get_public_documents_catalog(
    db: AsyncSession,
    audience: Optional[PublicAdmissionsAudience] = None,
    admission_round_id: Optional[int] = None,
) -> PublicAdmissionsDocumentsResponse:
    """Phase 2 v8.2 PR-2B v2 (Wave 6 #17 P2) — admission_round_id
    optional filter wired through _load_public_paths."""
    _, _, academic_info_ids = await _load_public_program_snapshot(db)
    paths = await _load_public_paths(
        db, academic_info_ids,
        audience=audience,
        admission_round_id=admission_round_id,
    )

    offering_type_ids: Set[int] = set()
    offering_type_programs: Dict[int, Set[str]] = defaultdict(set)
    offering_type_program_ids: Dict[int, Set[int]] = defaultdict(set)
    offering_type_offering_ids: Dict[int, Set[int]] = defaultdict(set)
    offering_type_method_ids: Dict[int, Set[int]] = defaultdict(set)
    offering_type_path_ids: Dict[int, Set[int]] = defaultdict(set)

    method_scope_program_ids: Dict[Tuple[int, int], Set[int]] = defaultdict(set)
    method_scope_offering_ids: Dict[Tuple[int, int], Set[int]] = defaultdict(set)
    method_scope_path_ids: Dict[Tuple[int, int], Set[int]] = defaultdict(set)
    method_scope_paths: Dict[
        Tuple[int, int], List[models.AdmissionPath]
    ] = defaultdict(list)

    for path in paths:
        academic_info = path.academic_info
        offering = academic_info.offering if academic_info else None
        program = offering.program if offering else None
        offering_type_id = offering.offering_type_id if offering else None
        method = path.admission_method

        if (
            academic_info is None
            or offering is None
            or program is None
            or offering_type_id is None
            or method is None
        ):
            continue

        offering_type_ids.add(offering_type_id)

        offering_type_programs[offering_type_id].add(program.name)
        offering_type_program_ids[offering_type_id].add(program.id)
        offering_type_offering_ids[offering_type_id].add(offering.id)
        offering_type_method_ids[offering_type_id].add(method.id)
        offering_type_path_ids[offering_type_id].add(path.id)

        scope_key = (offering_type_id, method.id)
        method_scope_program_ids[scope_key].add(program.id)
        method_scope_offering_ids[scope_key].add(offering.id)
        method_scope_path_ids[scope_key].add(path.id)
        method_scope_paths[scope_key].append(path)

    (
        path_groups_by_path,
        method_groups_by_scope,
        shared_groups_by_offering_type,
        offering_type_models,
        method_models,
    ) = await _load_path_document_tiers(db, paths)

    # Bridge: paths' admission_method instances aren't in method_models
    # if no DocumentGroup exists for that method (eager-load source).
    # Fill from the path objects so storefront still surfaces methods
    # whose docs resolve to the offering-type-level shared bucket.
    for path in paths:
        if (
            path.admission_method is not None
            and path.admission_method.id not in method_models
        ):
            method_models[path.admission_method.id] = path.admission_method

    offering_type_checklists: List[PublicAdmissionsOfferingTypeDocumentChecklist] = []
    resolved_document_type_ids: Set[int] = set()
    included_path_ids: Set[int] = set()
    included_method_ids: Set[int] = set()

    for offering_type_id in sorted(offering_type_ids):
        offering_type_model = offering_type_models.get(offering_type_id)
        if offering_type_model is None or not offering_type_model.is_active:
            continue

        # Tier 3 — offering-type-wide shared bucket. §9 (feat/document-group-
        # audience-merge): sau ĐỢT B, group shared tách NỀN (applicable_audience
        # NULL) + lớp audience. TÁCH hiển thị thay vì union (tránh trang công
        # khai liệt kê dư cả THPT lẫn THCS cho 1 chương trình).
        all_shared_groups = shared_groups_by_offering_type.get(offering_type_id, [])
        # getattr default None (consistent mandatory_wins_merge ĐỢT A): group
        # thiếu attr/applicable_audience NULL = lớp NỀN.
        nen_groups = [
            g for g in all_shared_groups
            if not getattr(g, "applicable_audience", None)
        ]
        audience_groups = [
            g for g in all_shared_groups
            if getattr(g, "applicable_audience", None)
        ]

        # shared_documents = lớp NỀN (luôn gộp cho mọi TS) — backward-compat FE cũ.
        shared_items: Dict[int, "models.DocumentGroupItem"] = {}
        _merge_items_with_mandatory_wins(shared_items, nen_groups)
        shared_documents = _items_to_public_documents(
            shared_items.values(), source="shared"
        )

        # audience_layers = 1 layer / audience (merge mandatory-wins trong lớp).
        layers_by_audience: Dict[str, List[models.DocumentGroup]] = defaultdict(list)
        for group in audience_groups:
            for aud in (getattr(group, "applicable_audience", None) or []):
                layers_by_audience[aud].append(group)
        audience_layers: List[PublicAdmissionsAudienceDocumentLayer] = []
        for aud in sorted(layers_by_audience):
            layer_items: Dict[int, "models.DocumentGroupItem"] = {}
            _merge_items_with_mandatory_wins(layer_items, layers_by_audience[aud])
            layer_docs = _items_to_public_documents(
                layer_items.values(), source="shared"
            )
            if layer_docs:
                audience_layers.append(
                    PublicAdmissionsAudienceDocumentLayer(
                        audience=aud,
                        audience_label=AUDIENCE_LABELS.get(aud, aud),
                        documents=layer_docs,
                    )
                )

        method_documents: List[PublicAdmissionsMethodDocumentChecklist] = []
        for method_id in sorted(offering_type_method_ids.get(offering_type_id, set())):
            scope_key = (offering_type_id, method_id)
            method_model = method_models.get(method_id)
            if method_model is None:
                continue

            scope_paths = method_scope_paths.get(scope_key, [])
            if not scope_paths:
                continue

            # Per-path 3-tier precedence (phase1_06 / Wave 1 PR-1C').
            # Highest non-empty tier wins fully per path; mandatory-
            # wins merge across paths sharing this scope. Source per
            # scope = highest tier observed across paths in scope.
            scope_items: Dict[int, "models.DocumentGroupItem"] = {}
            scope_source_rank = -1
            scope_source = "shared"

            for path in scope_paths:
                path_groups = path_groups_by_path.get(path.id, [])
                method_groups = method_groups_by_scope.get(scope_key, [])
                # §9: tier shared fallback chỉ lấy NỀN (lớp audience hiển thị
                # riêng ở audience_layers, KHÔNG union vào method docs).
                shared_groups = nen_groups

                if path_groups:
                    tier_groups, tier_source = path_groups, "path_override"
                elif method_groups:
                    tier_groups, tier_source = method_groups, "method_override"
                else:
                    tier_groups, tier_source = shared_groups, "shared"

                _merge_items_with_mandatory_wins(scope_items, tier_groups)
                tier_rank = _TIER_RANK[tier_source]
                if tier_rank > scope_source_rank:
                    scope_source_rank = tier_rank
                    scope_source = tier_source

            resolved_documents = _items_to_public_documents(
                scope_items.values(), source=scope_source
            )

            if not resolved_documents:
                continue

            included_method_ids.add(method_id)
            included_path_ids.update(method_scope_path_ids.get(scope_key, set()))
            resolved_document_type_ids.update(
                item.document_type_id for item in resolved_documents
            )
            method_documents.append(
                PublicAdmissionsMethodDocumentChecklist(
                    method_id=method_model.id,
                    method_code=method_model.code,
                    method_name=method_model.name,
                    source=scope_source,
                    public_program_count=len(
                        method_scope_program_ids.get(scope_key, set())
                    ),
                    public_offering_count=len(
                        method_scope_offering_ids.get(scope_key, set())
                    ),
                    public_path_count=len(method_scope_path_ids.get(scope_key, set())),
                    documents=resolved_documents,
                )
            )

        if not shared_documents and not audience_layers and not method_documents:
            continue

        resolved_document_type_ids.update(
            item.document_type_id for item in shared_documents
        )
        for layer in audience_layers:
            resolved_document_type_ids.update(
                doc.document_type_id for doc in layer.documents
            )
        sample_programs = sorted(offering_type_programs.get(offering_type_id, set()))[:4]
        offering_type_checklists.append(
            PublicAdmissionsOfferingTypeDocumentChecklist(
                offering_type_id=offering_type_id,
                offering_type_code=offering_type_model.code,
                offering_type_name=offering_type_model.name,
                public_program_count=len(
                    offering_type_program_ids.get(offering_type_id, set())
                ),
                public_offering_count=len(
                    offering_type_offering_ids.get(offering_type_id, set())
                ),
                public_method_count=len({item.method_id for item in method_documents}),
                sample_programs=sample_programs,
                shared_documents=shared_documents,
                audience_layers=audience_layers,
                method_documents=sorted(
                    method_documents,
                    key=lambda item: (item.method_name.lower(), item.method_id),
                ),
            )
        )

    offering_type_checklists.sort(
        key=lambda item: (
            _sort_offering_type(item.offering_type_name),
            item.offering_type_id,
        ),
    )

    return PublicAdmissionsDocumentsResponse(
        summary=PublicAdmissionsDocumentsMeta(
            offering_type_count=len(offering_type_checklists),
            method_count=len(included_method_ids),
            document_type_count=len(resolved_document_type_ids),
            public_path_count=len(included_path_ids),
        ),
        offering_types=offering_type_checklists,
    )


async def get_public_tuition_catalog(
    db: AsyncSession,
    audience: Optional[PublicAdmissionsAudience] = None,
    admission_round_id: Optional[int] = None,
) -> PublicAdmissionsTuitionResponse:
    # Tuition is offering-keyed, but public exposure is still path-gated:
    # only offerings with at least one public-eligible path for the selected
    # round/audience are allowed to surface tuition data.
    programs, latest_info_by_offering_id, academic_info_ids = await _load_public_program_snapshot(db)
    public_paths = await _load_public_paths(
        db,
        academic_info_ids,
        audience=audience,
        admission_round_id=admission_round_id,
    )
    eligible_offering_ids = _eligible_offering_ids_from_paths(public_paths)
    # PR-3 review fix #1 (2026-05-28): same in-memory filter as
    # get_public_programs_catalog — avoids 2× snapshot query per request.
    programs, latest_info_by_offering_id = _filter_snapshot_by_eligible_offerings(
        programs, latest_info_by_offering_id, eligible_offering_ids,
    )

    tuition_offerings: List[PublicAdmissionsTuitionOffering] = []
    degree_level_bands: Dict[str, List[PublicAdmissionsTuitionOffering]] = defaultdict(list)
    academic_years: Set[int] = set()
    policy_ids: Set[int] = set()

    for program in programs:
        for offering in sorted(program.offerings, key=lambda item: (_sort_offering_type(item.offering_type), item.id)):
            academic_info = latest_info_by_offering_id.get(offering.id)
            if academic_info is None:
                continue

            academic_years.add(academic_info.academic_year)
            for policy_id in academic_info.applied_discount_policy_ids or []:
                policy_ids.add(policy_id)

            sem_items, hk1_amount = _extract_semester_data(academic_info)
            item = PublicAdmissionsTuitionOffering(
                program_id=program.id,
                program_name=program.name,
                program_code=program.code,
                degree_level=program.degree_level,
                offering_id=offering.id,
                offering_type=offering.offering_type,
                academic_info_id=academic_info.id,
                academic_year=academic_info.academic_year,
                tuition_fee_per_year=academic_info.tuition_fee_per_year,
                annual_admission_quota=academic_info.annual_admission_quota,
                applied_discount_policy_ids=academic_info.applied_discount_policy_ids or [],
                semester_tuitions=sem_items,
                semester_1_tuition=hk1_amount,
            )
            tuition_offerings.append(item)
            degree_level_bands[program.degree_level].append(item)

    discount_policies: List[PublicAdmissionsDiscountPolicySummary] = []
    if policy_ids:
        policy_query = (
            select(models.TuitionDiscountPolicy)
            .where(
                models.TuitionDiscountPolicy.id.in_(sorted(policy_ids)),
                models.TuitionDiscountPolicy.is_active == True,
            )
            .order_by(
                models.TuitionDiscountPolicy.priority.desc(),
                models.TuitionDiscountPolicy.id,
            )
        )
        policy_result = await db.execute(policy_query)
        discount_policies = [
            PublicAdmissionsDiscountPolicySummary(
                id=policy.id,
                code=policy.code,
                name=policy.name,
                description=policy.description,
                discount_type=policy.discount_type.value if hasattr(policy.discount_type, "value") else str(policy.discount_type),
                discount_value=policy.discount_value,
                valid_from=policy.valid_from,
                valid_to=policy.valid_to,
                is_stackable=policy.is_stackable,
                priority=policy.priority,
            )
            for policy in policy_result.scalars().all()
        ]

    degree_levels = []
    for degree_level in sorted(degree_level_bands.keys(), key=_sort_degree_level):
        items = degree_level_bands[degree_level]
        tuition_min, tuition_max = _money_range(item.tuition_fee_per_year for item in items)
        hk1_min, hk1_max = _money_range(item.semester_1_tuition for item in items)
        degree_levels.append(
            PublicAdmissionsTuitionBand(
                degree_level=degree_level,
                published_offering_count=len(items),
                academic_years=sorted({item.academic_year for item in items}, reverse=True),
                tuition_min=tuition_min,
                tuition_max=tuition_max,
                semester_1_tuition_min=hk1_min,
                semester_1_tuition_max=hk1_max,
            )
        )

    return PublicAdmissionsTuitionResponse(
        summary=PublicAdmissionsTuitionMeta(
            program_count=len({item.program_id for item in tuition_offerings}),
            offering_count=len(tuition_offerings),
            policy_count=len(discount_policies),
            latest_academic_year=max(academic_years) if academic_years else None,
        ),
        degree_levels=degree_levels,
        offerings=tuition_offerings,
        discount_policies=discount_policies,
    )
