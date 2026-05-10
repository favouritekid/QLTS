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
from app.schemas.quota_matrix import (
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
