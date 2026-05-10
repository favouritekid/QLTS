# app/services/quota_matrix_service.py
"""Quota matrix overview service (Phase 2 v8.2 PR-2D.1 v2).

Aggregation logic cho GET /api/v2/admin/years/{year}/quota-matrix endpoint.
Returns matrix với rows = academic_info × academic_year, cols = rounds,
cells = aggregated quota.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    OfferingAcademicInfo,
    OfferingAdmissionRound,
    ProgramOffering,
)
from app.models.admission_config import AdmissionPath
from app.models.major_program import MajorProgram
from app.models.admission_config.method import AdmissionMethod
from app.schemas.quota_matrix import (
    PathMatrixCell,
    PathMatrixMethodRow,
    PathMatrixResponse,
    QuotaMatrixCell,
    QuotaMatrixResponse,
    QuotaMatrixRound,
    QuotaMatrixRow,
)


class QuotaMatrixService:
    """Aggregation service cho quota matrix admin view."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_matrix(self, academic_year: int) -> QuotaMatrixResponse:
        """Build matrix: rows = academic_info, cols = rounds, cells = sum quota.

        Filter:
        - academic_info.academic_year = year
        - academic_info.is_deleted = false
        - round.academic_year = year
        - path.status != 'archived'
        """
        # 1. Rounds for the year (sorted by round_code asc cho stable column order)
        rounds_stmt = (
            select(OfferingAdmissionRound)
            .where(OfferingAdmissionRound.academic_year == academic_year)
            .order_by(OfferingAdmissionRound.round_code)
        )
        rounds = list((await self.db.execute(rounds_stmt)).scalars().all())

        # 2. Academic infos for the year với eager-load offering → program
        ai_stmt = (
            select(OfferingAcademicInfo)
            .where(
                OfferingAcademicInfo.academic_year == academic_year,
                OfferingAcademicInfo.is_deleted.is_(False),
            )
            .options(
                selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program)
            )
            .order_by(OfferingAcademicInfo.id)
        )
        academic_infos = list((await self.db.execute(ai_stmt)).scalars().all())

        # 3. All paths for these academic_infos (excluding archived)
        ai_ids = [ai.id for ai in academic_infos]
        paths: List[AdmissionPath] = []
        if ai_ids:
            paths_stmt = select(AdmissionPath).where(
                AdmissionPath.academic_info_id.in_(ai_ids),
                AdmissionPath.status != "archived",
            )
            paths = list((await self.db.execute(paths_stmt)).scalars().all())

        # 4. Aggregate paths into cells map: (ai_id, round_id) → cell
        cell_map: dict[tuple[int, int], QuotaMatrixCell] = {}
        for path in paths:
            if path.admission_round_id is None:
                continue  # defensive; PR-2C v2 swap NOT NULL nhưng safe
            key = (path.academic_info_id, path.admission_round_id)
            cell = cell_map.get(key)
            if cell is None:
                round_obj = next(
                    (r for r in rounds if r.id == path.admission_round_id), None
                )
                if round_obj is None:
                    # Path's round is from different year; skip
                    continue
                cell = QuotaMatrixCell(
                    admission_round_id=path.admission_round_id,
                    round_code=round_obj.round_code,
                )
                cell_map[key] = cell
            cell.total_admit_quota += int(path.admit_quota or 0)
            cell.total_round_quota += int(path.round_quota or 0)
            cell.total_submission_count += int(path.submission_count or 0)
            cell.path_count += 1

        # 5. Build rows
        rows: List[QuotaMatrixRow] = []
        for ai in academic_infos:
            offering = ai.offering
            program = offering.program if offering else None
            cells_by_round_id: dict[int, QuotaMatrixCell] = {}
            for r in rounds:
                cell = cell_map.get((ai.id, r.id))
                if cell is not None:
                    cells_by_round_id[r.id] = cell
            sum_allocated = sum(c.total_admit_quota for c in cells_by_round_id.values())
            remaining: int | None = None
            if ai.annual_admission_quota is not None:
                remaining = ai.annual_admission_quota - sum_allocated

            rows.append(
                QuotaMatrixRow(
                    academic_info_id=ai.id,
                    academic_year=ai.academic_year,
                    program_name=program.name if program else "(không tên)",
                    program_code=program.code if program else None,
                    degree_level=program.degree_level if program else None,
                    annual_admission_quota=ai.annual_admission_quota,
                    cells_by_round_id=cells_by_round_id,
                    sum_admit_allocated=sum_allocated,
                    sum_remaining=remaining,
                )
            )

        return QuotaMatrixResponse(
            academic_year=academic_year,
            rounds=[
                QuotaMatrixRound(
                    id=r.id,
                    round_code=r.round_code,
                    round_name=r.round_name,
                    is_active=r.is_active,
                )
                for r in rounds
            ],
            rows=rows,
            total_rows=len(rows),
        )

    async def get_path_matrix_by_major(
        self, academic_info_id: int
    ) -> PathMatrixResponse:
        """Per-major view: rows = methods, cols = rounds, cells = exact path.

        Filter:
        - academic_info.id = id (single ngành × năm × hệ ĐT)
        - rounds.academic_year = academic_info.academic_year
        - paths.academic_info_id = id, status != 'archived'
        - methods: ALL active methods (so admin có cells trống render '+ Tạo path')
        """
        ai_stmt = (
            select(OfferingAcademicInfo)
            .where(OfferingAcademicInfo.id == academic_info_id)
            .options(
                selectinload(OfferingAcademicInfo.offering)
                .selectinload(ProgramOffering.program)
            )
        )
        ai = (await self.db.execute(ai_stmt)).scalar_one_or_none()
        if ai is None:
            from app.utils.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(
                f"OfferingAcademicInfo {academic_info_id} not found"
            )

        # Rounds for the year
        rounds_stmt = (
            select(OfferingAdmissionRound)
            .where(OfferingAdmissionRound.academic_year == ai.academic_year)
            .order_by(OfferingAdmissionRound.round_code)
        )
        rounds = list((await self.db.execute(rounds_stmt)).scalars().all())

        # All active methods
        methods_stmt = (
            select(AdmissionMethod)
            .where(AdmissionMethod.is_active.is_(True))
            .order_by(AdmissionMethod.display_order, AdmissionMethod.id)
        )
        methods = list((await self.db.execute(methods_stmt)).scalars().all())

        # Paths for this academic_info (excluding archived)
        paths_stmt = (
            select(AdmissionPath)
            .where(
                AdmissionPath.academic_info_id == academic_info_id,
                AdmissionPath.status != "archived",
            )
            .options(selectinload(AdmissionPath.criteria))
        )
        paths = list((await self.db.execute(paths_stmt)).scalars().all())

        # Build cells map: (method_id, round_id) → path
        path_map: dict[tuple[int, int], AdmissionPath] = {}
        for p in paths:
            if p.admission_round_id is None:
                continue
            path_map[(p.admission_method_id, p.admission_round_id)] = p

        # Build method rows
        method_rows: List[PathMatrixMethodRow] = []
        for m in methods:
            cells: dict[int, PathMatrixCell | None] = {}
            sum_admit = 0
            for r in rounds:
                p = path_map.get((m.id, r.id))
                if p is None:
                    cells[r.id] = None
                else:
                    cells[r.id] = PathMatrixCell(
                        path_id=p.id,
                        admission_round_id=p.admission_round_id,
                        admission_method_id=p.admission_method_id,
                        round_quota=p.round_quota,
                        admit_quota=p.admit_quota,
                        submission_count=int(p.submission_count or 0),
                        status=p.status,
                        criteria_code=p.criteria.code if p.criteria else None,
                    )
                    sum_admit += int(p.admit_quota or 0)
            method_rows.append(
                PathMatrixMethodRow(
                    admission_method_id=m.id,
                    method_code=m.code,
                    method_name=m.name,
                    cells_by_round_id=cells,
                    sum_admit_quota=sum_admit,
                )
            )

        # Aggregate header
        offering = ai.offering
        program = offering.program if offering else None
        sum_allocated = sum(mr.sum_admit_quota for mr in method_rows)
        remaining: int | None = None
        if ai.annual_admission_quota is not None:
            remaining = ai.annual_admission_quota - sum_allocated

        return PathMatrixResponse(
            academic_info_id=ai.id,
            academic_year=ai.academic_year,
            program_name=program.name if program else "(không tên)",
            program_code=program.code if program else None,
            degree_level=program.degree_level if program else None,
            annual_admission_quota=ai.annual_admission_quota,
            sum_admit_allocated=sum_allocated,
            sum_remaining=remaining,
            rounds=[
                QuotaMatrixRound(
                    id=r.id, round_code=r.round_code,
                    round_name=r.round_name, is_active=r.is_active,
                )
                for r in rounds
            ],
            methods=method_rows,
        )
