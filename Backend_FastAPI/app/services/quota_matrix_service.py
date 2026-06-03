# app/services/quota_matrix_service.py
"""Quota matrix overview service (Phase 2 v8.2 PR-2D.1 v2).

Aggregation logic cho GET /api/v2/admin/years/{year}/quota-matrix endpoint.
Returns matrix với rows = academic_info × academic_year, cols = rounds,
cells = aggregated quota.
"""

from typing import List

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AdmissionProfile,
    AdmissionProfileChoice,
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
# Reuse canonical seat-occupying status tuple (single source of truth). Import
# verified non-circular: admission_service does NOT import quota_matrix_service.
from app.services.admission_service import QUOTA_OCCUPYING_STATUSES


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

        funnel_counts = await self._compute_funnel_counts([p.id for p in paths])

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
            if path.admit_quota is None:
                cell.total_admit_quota = None
            elif cell.total_admit_quota is not None:
                cell.total_admit_quota += int(path.admit_quota)
            if path.round_quota is None:
                cell.total_round_quota = None
            elif cell.total_round_quota is not None:
                cell.total_round_quota += int(path.round_quota)
            cell.total_submission_count += int(path.submission_count or 0)
            fc = funnel_counts[path.id]
            cell.total_submitted_count += fc["submitted"]
            cell.total_approved_count += fc["approved"]
            cell.total_enrolled_count += fc["enrolled"]
            cell.total_dropped_count += fc["dropped"]
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
            sum_allocated = sum(
                c.total_admit_quota or 0 for c in cells_by_round_id.values()
            )
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

    async def _compute_funnel_counts(
        self, path_ids: List[int]
    ) -> dict[int, dict[str, int]]:
        """Aggregate actual funnel counts per path (multi-NV + legacy).

        Returns map ``path_id → {submitted, approved, enrolled, dropped}``,
        default 0. **Read-only SELECT** — tách hẳn đường enforcement
        (``check_choice_admit_capacity`` tự đếm có lock riêng). Hiển thị
        sai chỉ ảnh hưởng UI cho admin, KHÔNG sai dữ liệu.

        Tái dùng cấu trúc query canonical (``admission_choice_engine_service.
        check_choice_admit_capacity``), cộng 2 nguồn:
          M1 — multi-NV qua ``AdmissionProfileChoice``. Đếm
               ``COUNT(DISTINCT profile_id)`` chống đếm trùng khi 1 profile
               chọn CÙNG path với 2 tổ hợp môn (choice UNIQUE 3-cột, không
               có UNIQUE trên ``(profile, path)``).
          M2 — legacy single-NV qua ``applied_rules->>'admission_path_id'``,
               lọc ``uses_choice_engine=FALSE`` để KHÔNG double-count với M1.

        ⚠️ M2 so sánh **DẠNG TEXT** (``IN :path_ids_as_text``) — KHÔNG cast
        cột JSON → int. ``.astext.cast(Integer)`` raise ``invalid input
        syntax for integer`` nếu text là rác phi-số (NOT NULL không bảo vệ),
        và né seq-scan cast toàn bảng.
        """
        counts: dict[int, dict[str, int]] = {
            pid: {"submitted": 0, "approved": 0, "enrolled": 0, "dropped": 0}
            for pid in path_ids
        }
        if not path_ids:
            return counts

        # M1 — multi-NV via choice rows. COUNT(DISTINCT profile_id) chống N2.
        m1_stmt = (
            select(
                AdmissionProfileChoice.admission_path_id.label("path_id"),
                func.count(distinct(AdmissionProfileChoice.admission_profile_id))
                .filter(AdmissionProfile.status.not_in(("draft", "withdrawn")))
                .label("submitted_cnt"),
                func.count(distinct(AdmissionProfileChoice.admission_profile_id))
                .filter(
                    AdmissionProfileChoice.decision == "admitted",
                    AdmissionProfile.status.in_(QUOTA_OCCUPYING_STATUSES),
                )
                .label("approved_cnt"),
                func.count(distinct(AdmissionProfileChoice.admission_profile_id))
                .filter(
                    AdmissionProfileChoice.decision == "admitted",
                    AdmissionProfile.status == "enrolled",
                )
                .label("enrolled_cnt"),
                func.count(distinct(AdmissionProfileChoice.admission_profile_id))
                .filter(
                    AdmissionProfileChoice.decision == "admitted",
                    AdmissionProfile.status == "enrolled",
                    AdmissionProfile.is_dropped.is_(True),
                )
                .label("dropped_cnt"),
            )
            .join(
                AdmissionProfile,
                AdmissionProfile.id
                == AdmissionProfileChoice.admission_profile_id,
            )
            .where(AdmissionProfileChoice.admission_path_id.in_(path_ids))
            .group_by(AdmissionProfileChoice.admission_path_id)
        )
        for row in (await self.db.execute(m1_stmt)).all():
            d = counts.get(row.path_id)
            if d is None:
                continue
            d["submitted"] += int(row.submitted_cnt or 0)
            d["approved"] += int(row.approved_cnt or 0)
            d["enrolled"] += int(row.enrolled_cnt or 0)
            d["dropped"] += int(row.dropped_cnt or 0)

        # M2 — legacy single-NV via applied_rules JSON. So sánh DẠNG TEXT.
        path_id_text = AdmissionProfile.applied_rules["admission_path_id"].astext
        path_ids_as_text = [str(pid) for pid in path_ids]
        m2_stmt = (
            select(
                path_id_text.label("path_id_text"),
                func.count(AdmissionProfile.id)
                .filter(AdmissionProfile.status.not_in(("draft", "withdrawn")))
                .label("submitted_cnt"),
                func.count(AdmissionProfile.id)
                .filter(AdmissionProfile.status.in_(QUOTA_OCCUPYING_STATUSES))
                .label("approved_cnt"),
                func.count(AdmissionProfile.id)
                .filter(AdmissionProfile.status == "enrolled")
                .label("enrolled_cnt"),
                func.count(AdmissionProfile.id)
                .filter(
                    AdmissionProfile.status == "enrolled",
                    AdmissionProfile.is_dropped.is_(True),
                )
                .label("dropped_cnt"),
            )
            .where(
                AdmissionProfile.uses_choice_engine.is_(False),
                path_id_text.in_(path_ids_as_text),
            )
            .group_by(path_id_text)
        )
        for row in (await self.db.execute(m2_stmt)).all():
            try:
                pid = int(row.path_id_text)
            except (TypeError, ValueError):
                continue  # defensive; WHERE đã lọc nhưng giữ an toàn
            d = counts.get(pid)
            if d is None:
                continue
            d["submitted"] += int(row.submitted_cnt or 0)
            d["approved"] += int(row.approved_cnt or 0)
            d["enrolled"] += int(row.enrolled_cnt or 0)
            d["dropped"] += int(row.dropped_cnt or 0)

        return counts

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

        # Funnel counts gom 1 lần cho TẤT CẢ path (tránh N+1).
        funnel_counts = await self._compute_funnel_counts([p.id for p in paths])

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
                    fc = funnel_counts[p.id]
                    cells[r.id] = PathMatrixCell(
                        path_id=p.id,
                        admission_round_id=p.admission_round_id,
                        admission_method_id=p.admission_method_id,
                        round_quota=p.round_quota,
                        admit_quota=p.admit_quota,
                        submission_count=int(p.submission_count or 0),
                        status=p.status,
                        criteria_code=p.criteria.code if p.criteria else None,
                        submitted_count=fc["submitted"],
                        approved_count=fc["approved"],
                        enrolled_count=fc["enrolled"],
                        dropped_count=fc["dropped"],
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
