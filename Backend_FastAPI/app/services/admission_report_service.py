"""Weekly admission report service (orchestration only — no FastAPI imports).

Owns the week/round/scope contract; delegates all data access to
``AdmissionReportRepository``. Raises domain exceptions (never HTTPException).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.repositories.admission_report_repository import (
    AMBIGUOUS,
    UNASSIGNED,
    UNRESOLVED,
    AdmissionReportRepository,
    GroupKey,
    MajorInfo,
    WindowRange,
)
from app.schemas.admission_report import (
    AdmissionTrendResponse,
    AdmissionWeeklyReportResponse,
    AdmissionWowResponse,
    DataQuality,
    FunnelStage,
    MatrixMajor,
    MatrixOfficer,
    OfficerMajorCell,
    OfficerMajorMatrixResponse,
    PipelineFunnelResponse,
    ReportFilters,
    ReportRow,
    TrendPoint,
    WeekMeta,
    WowComparison,
    WowMovement,
    WowRow,
)
from app.utils.datetime_helpers import today_vn
from app.utils.exceptions import (
    BusinessRuleViolation,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_BUCKET_LABELS = {
    AMBIGUOUS: "Nhiều NV trúng (chưa xác định ngành)",
    UNRESOLVED: "Chưa phân loại ngành",
    UNASSIGNED: "Chưa gán cán bộ",
}


class AdmissionReportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionReportRepository(db)

    # ------------------------------------------------------------------- scope
    @staticmethod
    def _resolve_scope(
        current_user: models.User, requested_unit_id: Optional[int]
    ) -> Optional[int]:
        """Admin → toàn trường (or chosen unit); manager → ép unit của mình.

        Caller has already gated role to {admin, manager}. Manager without a unit
        fails closed; manager requesting another unit gets 404 (no existence leak).
        """
        if current_user.role == UserRole.ADMIN:
            return requested_unit_id  # None = all units
        if current_user.unit_id is None:
            raise PermissionDeniedError(
                detail="Tài khoản chưa được gán đơn vị, không thể xem báo cáo."
            )
        if requested_unit_id is not None and requested_unit_id != current_user.unit_id:
            raise ResourceNotFoundError(detail="Không tìm thấy đơn vị.")
        return current_user.unit_id

    # -------------------------------------------------------------------- week
    @staticmethod
    def _compute_week(week_start: Optional[date]) -> tuple[WeekMeta, WindowRange]:
        anchor = week_start or today_vn()
        iso_year, iso_week, iso_weekday = anchor.isocalendar()
        monday = anchor - timedelta(days=iso_weekday - 1)
        sunday = monday + timedelta(days=6)
        start_dt = datetime(monday.year, monday.month, monday.day, tzinfo=VN_TZ)
        end_excl = datetime(
            sunday.year, sunday.month, sunday.day, tzinfo=VN_TZ
        ) + timedelta(days=1)
        meta = WeekMeta(
            iso_year=iso_year, iso_week=iso_week, week_start=monday, week_end=sunday
        )
        return meta, WindowRange(start=start_dt, end_excl=end_excl)

    @staticmethod
    def _default_anchor(
        academic_year: int, week_start: Optional[date]
    ) -> Optional[date]:
        """Anchor a cumulative-to-now cutoff INSIDE ``academic_year``.

        Current year → today (None → ``_compute_week`` uses today). Past year →
        last ISO week (Dec 28, cumulative ≈ trọn năm). Future → first ISO week
        (Jan 4, cumulative ~0). Mirrors ``get_weekly_report``'s implicit-week rule
        so overview panels agree with the weekly cockpit.
        """
        if week_start is not None:
            return week_start
        if academic_year == today_vn().year:
            return None
        return (
            date(academic_year, 1, 4)
            if academic_year > today_vn().year
            else date(academic_year, 12, 28)
        )

    # ------------------------------------------------------------ cohort window
    async def _cohort_ranges(
        self,
        academic_year: int,
        round_code: Optional[str],
        *,
        skip_undated: bool = False,
    ) -> list[WindowRange]:
        """VN [start 00:00, end+1day 00:00) windows for the year's round(s).

        ``round_code`` not found → 404. A round missing start/end normally raises
        (fail-closed — the weekly cockpit). ``skip_undated=True`` (the overview
        funnel) SKIPS such rounds instead, so one misconfigured round can't 400 the
        whole "tất cả đợt" view.
        """
        stmt = select(
            models.OfferingAdmissionRound.round_code,
            models.OfferingAdmissionRound.start_date,
            models.OfferingAdmissionRound.end_date,
        ).where(models.OfferingAdmissionRound.academic_year == academic_year)
        if round_code is not None:
            stmt = stmt.where(models.OfferingAdmissionRound.round_code == round_code)
        rows = (await self.db.execute(stmt)).all()
        if round_code is not None and not rows:
            raise ResourceNotFoundError(
                detail=f"Không tìm thấy đợt {round_code} năm {academic_year}."
            )
        ranges: list[WindowRange] = []
        for rc, start, end in rows:
            if start is None or end is None:
                if skip_undated:
                    continue
                raise BusinessRuleViolation(
                    detail=(
                        f"Đợt {rc} thiếu ngày bắt đầu/kết thúc — "
                        "không xác định được cohort lead."
                    )
                )
            ranges.append(
                WindowRange(
                    start=datetime(start.year, start.month, start.day, tzinfo=VN_TZ),
                    end_excl=datetime(end.year, end.month, end.day, tzinfo=VN_TZ)
                    + timedelta(days=1),
                )
            )
        return ranges

    async def _assert_round_exists(
        self, academic_year: int, round_code: Optional[str]
    ) -> None:
        """404 if a specific ``round_code`` is given but not configured for the year.

        Trend/matrix scope profiles via ``resolve_profiles`` (which silently keeps
        round=None profiles), so without this a typo'd round returns 200 with a
        misleading subset — this makes them fail like the funnel/``_cohort_ranges``.
        """
        if round_code is None:
            return
        exists = (
            await self.db.execute(
                select(models.OfferingAdmissionRound.id)
                .where(
                    models.OfferingAdmissionRound.academic_year == academic_year,
                    models.OfferingAdmissionRound.round_code == round_code,
                )
                .limit(1)
            )
        ).first()
        if exists is None:
            raise ResourceNotFoundError(
                detail=f"Không tìm thấy đợt {round_code} năm {academic_year}."
            )

    # ----------------------------------------------------------------- filters
    async def get_filter_options(self, academic_year: Optional[int]) -> ReportFilters:
        """Years + rounds for the report filter controls.

        Catalog metadata (not unit-scoped data) → no IDOR scope here; the route
        gate (admin_or_manager) is the only check the filter list needs.
        """
        years = await self.repo.list_report_years()
        rounds = (
            await self.repo.list_report_rounds(academic_year)
            if academic_year is not None
            else []
        )
        return ReportFilters(academic_years=years, rounds=rounds)

    # ------------------------------------------------------------------ report
    async def get_weekly_report(
        self,
        *,
        current_user: models.User,
        academic_year: int,
        group_by: str,
        round_code: Optional[str] = None,
        week_start: Optional[date] = None,
        officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> AdmissionWeeklyReportResponse:
        scope_unit_id = self._resolve_scope(current_user, unit_id)
        # Anchor the implicit week INSIDE the academic year via the shared helper —
        # one source of truth with the overview panels (see ``_default_anchor``).
        anchor = self._default_anchor(academic_year, week_start)
        week_meta, week = self._compute_week(anchor)
        # An EXPLICIT week_start OUTSIDE the academic year is a stale/forward bookmark
        # → reject on the NORMALIZED ISO year (ISO week 1's Monday can fall in the
        # prior Dec; a week whose Thursday lands in the next Jan belongs to next year).
        # Symmetric guard: both a prior-year bookmark AND a next-year "Tuần sau" step
        # must fail so ``academic_year`` and ``week.iso_year`` never disagree.
        if week_start is not None and week_meta.iso_year != academic_year:
            raise ValidationError(
                detail="week_start ngoài năm tuyển sinh — hãy chọn tuần trong năm."
            )
        cohort_ranges = await self._cohort_ranges(academic_year, round_code)

        dims, major_labels = await self.repo.resolve_profiles(
            academic_year, scope_unit_id, officer_id, round_code
        )
        profile_ids = list(dims.keys())
        milestones = await self.repo.admission_milestones(
            profile_ids, week, week.end_excl
        )
        fin_rows = await self.repo.finance_rows(profile_ids, week.end_excl)
        profile_lead_ids = {d.lead_id for d in dims.values()}
        lead_map = await self.repo.lead_counts(
            academic_year,
            cohort_ranges,
            week,
            group_by,
            scope_unit_id,
            officer_id,
            profile_lead_ids,
        )

        acc: dict[GroupKey, ReportRow] = {}

        def _row(key: GroupKey) -> ReportRow:
            row = acc.get(key)
            if row is None:
                row = ReportRow(label="")
                acc[key] = row
            return row

        # ---- leads (intent offering→major | officer)
        for key, lc in lead_map.items():
            r = _row(key).lead
            r.new_in_week += lc.new_in_week
            r.active_current += lc.active_current
            r.consulting_positive_current += lc.consulting_positive_current

        # ---- admission milestones (first-transition, by resolved dim)
        for pid, dim in dims.items():
            key = dim.major_key if group_by == "major" else dim.officer_key
            ms = milestones.get(pid, {})
            a = _row(key).admission
            a.profiles_total += 1  # count every resolved profile (even if no history)
            for m in ("submitted", "admitted", "enrolled"):
                if ms.get(f"{m}_in_week"):
                    setattr(a, f"{m}_in_week", getattr(a, f"{m}_in_week") + 1)
                if ms.get(f"{m}_cumulative"):
                    setattr(a, f"{m}_cumulative", getattr(a, f"{m}_cumulative") + 1)

        # ---- finance ledger (cash: payment/refund; refund amount stored negative)
        paid_profiles: dict[GroupKey, set] = {}
        # Profiles with a cumulative APPLICATION-fee payment — used to surface the
        # "đã đóng lệ phí nhưng chưa nộp hồ sơ" (prepay-draft) cohort below.
        app_paid_profiles: dict[GroupKey, set] = {}
        for pid, fee_type, ttype, amount, created_at in fin_rows:
            dim = dims.get(pid)
            if dim is None:
                continue
            key = dim.major_key if group_by == "major" else dim.officer_key
            f = _row(key).finance
            amt = Decimal(amount)
            f.net_cumulative += amt
            if ttype == "payment":
                paid_profiles.setdefault(key, set()).add(pid)
                if fee_type == "application":
                    app_paid_profiles.setdefault(key, set()).add(pid)
            if week.start <= created_at < week.end_excl:
                f.net_in_week += amt
                if ttype == "payment":
                    f.gross_in_week += amt
                else:  # refund — amount is negative; report as a positive figure
                    f.refund_in_week += abs(amt)
                if fee_type == "application":
                    f.application_net_in_week += amt
                elif fee_type == "tuition":
                    f.tuition_net_in_week += amt
        for key, pids in paid_profiles.items():
            _row(key).finance.profiles_paid = len(pids)
        # Prepay-draft: đã đóng lệ phí xét tuyển nhưng CHƯA nộp hồ sơ (no submitted
        # milestone) — nhóm prepay fast-track cần nhắc hoàn tất nộp hồ sơ.
        for key, pids in app_paid_profiles.items():
            _row(key).admission.fee_paid_not_submitted = sum(
                1
                for pid in pids
                if not milestones.get(pid, {}).get("submitted_cumulative")
            )

        # ---- labels
        officer_names: dict[int, str] = {}
        if group_by == "officer":
            for dim in dims.values():
                if isinstance(dim.officer_key, int) and dim.officer_name:
                    officer_names[dim.officer_key] = dim.officer_name
            missing = [k for k in acc if isinstance(k, int) and k not in officer_names]
            officer_names.update(await self.repo.get_user_names(missing))

        # ---- chỉ tiêu: include EVERY quota-bearing major (even with 0 activity)
        # so behind-target ngành surface instead of vanishing.
        #  • Year-level only — skip when a single đợt is filtered (numerator round ≠
        #    denominator năm); FE hides the progress column.
        #  • Toàn-trường only (scope None) — quota is a per-offering institution
        #    target with NO per-unit split; activity scopes by Lead.unit_id while a
        #    shared offering's quota can't be attributed to one unit, so a manager
        #    gets the count cockpit instead of a misleading gap.
        quota_by_major: dict[int, int] = {}
        if group_by == "major" and round_code is None and scope_unit_id is None:
            for mid, (q, info) in (await self.repo.major_quotas(academic_year)).items():
                quota_by_major[mid] = q
                if mid not in acc:
                    _row(mid)  # materialise an empty row (0 counts)
                major_labels.setdefault(mid, info)

        rows: list[ReportRow] = []
        for key, row in acc.items():
            if isinstance(key, str):  # bucket sentinel
                row.is_bucket = True
                row.bucket_kind = key  # type: ignore[assignment]
                row.label = _BUCKET_LABELS.get(key, key)
            elif group_by == "major":
                info = major_labels.get(key)
                row.group_key = key
                row.code = info.code if info else None
                row.degree_level = info.degree_level if info else None
                if info and info.name:
                    row.label = f"{info.name} ({info.code})" if info.code else info.name
                else:
                    row.label = f"Ngành #{key}"
            else:  # officer
                row.group_key = key
                row.label = officer_names.get(key, f"Cán bộ #{key}")
            rows.append(row)

        # ---- attach chỉ tiêu + tỷ lệ chuyển đổi
        for row in rows:
            if not row.is_bucket and isinstance(row.group_key, int):
                row.admission.quota = quota_by_major.get(row.group_key)
            self._apply_conversion(row)

        rows.sort(key=self._sort_key)
        totals = self._totals(rows)

        dq = DataQuality(total_profiles=len(dims))
        for dim in dims.values():
            if dim.major_key == AMBIGUOUS:
                dq.ambiguous_profiles += 1
            elif dim.major_key == UNRESOLVED:
                dq.unresolved_profiles += 1
            if dim.officer_key == UNASSIGNED:
                dq.unassigned_profiles += 1

        return AdmissionWeeklyReportResponse(
            academic_year=academic_year,
            round_code=round_code,
            group_by=group_by,  # type: ignore[arg-type]
            week=week_meta,
            scope_unit_id=scope_unit_id,
            rows=rows,
            totals=totals,
            data_quality=dq,
        )

    # ------------------------------------------------- overview: pipeline funnel
    async def get_pipeline_funnel(
        self,
        *,
        current_user: models.User,
        academic_year: int,
        round_code: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> PipelineFunnelResponse:
        """Lead theo giai đoạn pipeline hiện tại (cohort = đợt/năm, scope IDOR).

        - Chỉ view "tất cả đợt" mới bỏ qua đợt thiếu ngày (``skip_undated``); chọn
          đích danh 1 đợt thiếu ngày → vẫn báo lỗi cấu hình (không giả rỗng).
        - Cohort gồm lead có hồ sơ (``profile_lead_ids``) → khớp weekly, admission
          không vượt lead.
        - Mô hình phễu (reached/conversion/leak theo OUTCOME) do BACKEND tính.
        """
        scope_unit_id = self._resolve_scope(current_user, unit_id)
        cohort_ranges = await self._cohort_ranges(
            academic_year, round_code, skip_undated=round_code is None
        )
        # walk-in parity: leads that already produced an in-scope profile
        dims, _ = await self.repo.resolve_profiles(
            academic_year, scope_unit_id, None, round_code
        )
        profile_lead_ids = {d.lead_id for d in dims.values()}
        stages_meta, on_path, leaked, total, leak_ids = (
            await self.repo.pipeline_funnel_counts(
                cohort_ranges, scope_unit_id, None, profile_lead_ids
            )
        )
        return PipelineFunnelResponse(
            academic_year=academic_year,
            round_code=round_code,
            scope_unit_id=scope_unit_id,
            total_leads=total,
            leaked=leaked,
            stages=self._build_funnel_stages(stages_meta, on_path, leak_ids),
        )

    # ------------------------------------------------------- overview: trend
    async def get_trend(
        self,
        *,
        current_user: models.User,
        academic_year: int,
        round_code: Optional[str] = None,
        unit_id: Optional[int] = None,
        weeks: int = 8,
    ) -> AdmissionTrendResponse:
        """N tuần tích luỹ (nộp/đủ ĐK/nhập học) — mỗi điểm là mốc first-transition
        < hết tuần đó. Resolve hồ sơ 1 lần rồi bucket, không query lại mỗi tuần."""
        scope_unit_id = self._resolve_scope(current_user, unit_id)
        await self._assert_round_exists(academic_year, round_code)
        end_meta, _ = self._compute_week(self._default_anchor(academic_year, None))
        dims, _ = await self.repo.resolve_profiles(
            academic_year, scope_unit_id, None, round_code
        )
        ts = await self.repo.milestone_timestamps(list(dims.keys()))
        # Điểm CUỐI = tuần mốc (``_default_anchor``) → trend khớp snapshot lũy kế
        # của KPI band + ma trận officer×ngành (cùng cutoff), KHÔNG lệch số. Walk
        # BACKWARD cho MỌI năm (điểm old→new). Năm tương lai: 8 tuần kết ở ISO tuần
        # 1 nên nhãn có thể chạm cuối năm trước — chấp nhận (năm tương lai ~0 dữ
        # liệu) để đổi lấy nhất quán, thay vì chiếu tới tuần chưa xảy ra.
        points: list[TrendPoint] = []
        for k in range(weeks):
            base = end_meta.week_start - timedelta(weeks=(weeks - 1 - k))
            wmeta, wrange = self._compute_week(base)
            cutoff = wrange.end_excl
            points.append(
                TrendPoint(
                    iso_year=wmeta.iso_year,
                    iso_week=wmeta.iso_week,
                    week_start=wmeta.week_start,
                    week_end=wmeta.week_end,
                    submitted_cumulative=sum(
                        1 for t in ts["submitted"].values() if t < cutoff
                    ),
                    admitted_cumulative=sum(
                        1 for t in ts["admitted"].values() if t < cutoff
                    ),
                    enrolled_cumulative=sum(
                        1 for t in ts["enrolled"].values() if t < cutoff
                    ),
                )
            )
        return AdmissionTrendResponse(
            academic_year=academic_year,
            round_code=round_code,
            scope_unit_id=scope_unit_id,
            weeks=weeks,
            points=points,
        )

    # ---------------------------------------- overview: week-over-week (WoW)
    @staticmethod
    def _finalize_movement(mv: WowMovement) -> None:
        """delta + delta_pct (%); mẫu số 0 → delta_pct=None (ưu tiên số tuyệt đối)."""
        mv.delta = mv.count_current - mv.count_previous
        mv.delta_pct = (
            round(mv.delta / mv.count_previous * 100, 1)
            if mv.count_previous > 0
            else None
        )

    async def get_week_over_week(
        self,
        *,
        current_user: models.User,
        academic_year: int,
        round_code: Optional[str] = None,
        unit_id: Optional[int] = None,
        group_by: str = "major",
    ) -> AdmissionWowResponse:
        """Biến động 2 tuần ISO ĐÃ HOÀN TẤT gần nhất (bỏ tuần đang chạy), 3 milestone.

        Tái dùng ``resolve_profiles`` (dim ỔN ĐỊNH theo major_id/officer_id — không
        join bằng nhãn) + ``milestone_timestamps`` (first-transition) + cùng
        scope/RBAC như trend. Năm KHÔNG phải năm hiện tại (``_default_anchor`` trả
        != None) → không có "tuần đang chạy" thật → ``insufficient_data`` (KHÔNG bịa
        2 tuần 0 giả). ``delta_pct=None`` khi tuần trước = 0. Tính theo major·officer
        ·totals; totals = Σ dimension (khớp tổng chung). FE chỉ render.
        """
        scope_unit_id = self._resolve_scope(current_user, unit_id)
        await self._assert_round_exists(academic_year, round_code)

        totals = WowRow(group_key=None, label="TỔNG")
        # WoW chỉ có nghĩa khi có "tuần đang chạy" thật = NĂM HIỆN TẠI. Năm khác
        # (_default_anchor != None: tương lai → Jan-4 nên 2 tuần rơi vào tháng 12 năm
        # trước = giả; quá khứ → Dec-28, mùa đã đóng) → báo insufficient_data.
        anchor = self._default_anchor(academic_year, None)
        if anchor is not None:
            return AdmissionWowResponse(
                academic_year=academic_year,
                round_code=round_code,
                scope_unit_id=scope_unit_id,
                group_by=group_by,  # type: ignore[arg-type]
                insufficient_data=True,
                comparison=None,
                rows=[],
                totals=totals,
            )

        end_meta, _ = self._compute_week(anchor)  # tuần ĐANG CHẠY (loại khỏi WoW)
        w1_meta, w1 = self._compute_week(end_meta.week_start - timedelta(weeks=1))
        w2_meta, w2 = self._compute_week(end_meta.week_start - timedelta(weeks=2))
        # Đầu tháng 1: 2 tuần đã-hoàn-tất gần nhất rơi vào tháng 12 NĂM TRƯỚC (ISO
        # year ≠ academic_year) → so nhịp sẽ lấy tuần của năm khác. Không đủ dữ liệu
        # TRONG NĂM để so → insufficient_data (nhất quán với chặn week_start ngoài năm).
        if w1_meta.iso_year != academic_year or w2_meta.iso_year != academic_year:
            return AdmissionWowResponse(
                academic_year=academic_year,
                round_code=round_code,
                scope_unit_id=scope_unit_id,
                group_by=group_by,  # type: ignore[arg-type]
                insufficient_data=True,
                comparison=None,
                rows=[],
                totals=totals,
            )

        dims, _major_by_id = await self.repo.resolve_profiles(
            academic_year, scope_unit_id, None, round_code
        )
        ts = await self.repo.milestone_timestamps(list(dims.keys()))

        acc: dict[GroupKey, WowRow] = {}

        def _row(key: GroupKey) -> WowRow:
            row = acc.get(key)
            if row is None:
                row = WowRow(label="")
                acc[key] = row
            return row

        # First-transition timestamp → 1 trong 2 tuần hoàn tất, theo dim của hồ sơ.
        # CHỈ materialize hàng khi có sự kiện TRONG 2 tuần (mốc ngoài cửa sổ đóng góp
        # 0 cho cả hai → bỏ, tránh hàng biến-động-0 thừa; totals không đổi).
        for milestone in ("submitted", "admitted", "enrolled"):
            for pid, t in ts[milestone].items():
                dim = dims.get(pid)
                if dim is None:
                    continue
                in_current = w1.start <= t < w1.end_excl
                in_previous = w2.start <= t < w2.end_excl
                if not (in_current or in_previous):
                    continue
                key = dim.major_key if group_by == "major" else dim.officer_key
                mv: WowMovement = getattr(_row(key), milestone)
                if in_current:
                    mv.count_current += 1
                else:
                    mv.count_previous += 1

        # Nhãn (mirror get_weekly_report): key int = ngành/cán bộ thật; key str =
        # bucket sentinel (ambiguous/unresolved/unassigned).
        officer_names: dict[int, str] = {}
        major_labels: dict[int, MajorInfo] = {}
        if group_by == "officer":
            for dim in dims.values():
                if isinstance(dim.officer_key, int) and dim.officer_name:
                    officer_names[dim.officer_key] = dim.officer_name
            missing = [k for k in acc if isinstance(k, int) and k not in officer_names]
            officer_names.update(await self.repo.get_user_names(missing))
        else:
            for dim in dims.values():
                if isinstance(dim.major_key, int) and dim.major:
                    major_labels[dim.major_key] = dim.major

        rows: list[WowRow] = []
        for key, row in acc.items():
            if isinstance(key, str):  # bucket sentinel
                row.is_bucket = True
                row.bucket_kind = key  # type: ignore[assignment]
                row.label = _BUCKET_LABELS.get(key, key)
            elif group_by == "major":
                info = major_labels.get(key)
                row.group_key = key
                row.code = info.code if info else None
                row.degree_level = info.degree_level if info else None
                if info and info.name:
                    row.label = f"{info.name} ({info.code})" if info.code else info.name
                else:
                    row.label = f"Ngành #{key}"
            else:  # officer
                row.group_key = key
                row.label = officer_names.get(key, f"Cán bộ #{key}")
            rows.append(row)

        # totals = Σ COUNT của dimension (trước khi tính delta), rồi finalise delta ở
        # MỌI hàng + totals → tổng dimension khớp tổng chung.
        for row in rows:
            for milestone in ("submitted", "admitted", "enrolled"):
                tm: WowMovement = getattr(totals, milestone)
                rm: WowMovement = getattr(row, milestone)
                tm.count_current += rm.count_current
                tm.count_previous += rm.count_previous
        for target in (*rows, totals):
            for milestone in ("submitted", "admitted", "enrolled"):
                self._finalize_movement(getattr(target, milestone))

        rows.sort(key=lambda r: (r.is_bucket, -r.submitted.count_current))

        return AdmissionWowResponse(
            academic_year=academic_year,
            round_code=round_code,
            scope_unit_id=scope_unit_id,
            group_by=group_by,  # type: ignore[arg-type]
            insufficient_data=False,
            comparison=WowComparison(
                latest_complete_week=w1_meta,
                previous_complete_week=w2_meta,
            ),
            rows=rows,
            totals=totals,
        )

    # -------------------------------------------- overview: officer × major heat
    async def get_officer_major_matrix(
        self,
        *,
        current_user: models.User,
        academic_year: int,
        round_code: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> OfficerMajorMatrixResponse:
        """Ma trận (ngành × cán bộ) — mỗi ô đếm 5 chỉ số hồ sơ cho 3 tab FE:
        Hồ sơ (đã nộp · nháp) · Học phí HK1 (một phần · đủ) · Nhập học.

        Tái dùng ``resolve_profiles`` (cặp officer_key × major_key mỗi hồ sơ) +
        ``admission_milestones`` (submitted/enrolled) + trạng thái hồ sơ (nháp) +
        đóng học phí HK1. Ambiguous ∪ unresolved gộp "Chưa phân loại ngành";
        unassigned → "Chưa gán cán bộ". Trả CẢ 5 chỉ số → FE đổi tab client-side
        không refetch.
        """
        scope_unit_id = self._resolve_scope(current_user, unit_id)
        await self._assert_round_exists(academic_year, round_code)
        _, week = self._compute_week(self._default_anchor(academic_year, None))
        dims, _major_by_id = await self.repo.resolve_profiles(
            academic_year, scope_unit_id, None, round_code
        )
        pids = list(dims.keys())
        milestones = await self.repo.admission_milestones(pids, week, week.end_excl)
        statuses = await self.repo.profile_statuses(pids)
        tuition = await self.repo.tuition_hk1_payment(pids)

        # (officer_id|None, major_id|None) -> [submitted, draft, fee_partial,
        # fee_full, enrolled]
        cells: dict[tuple, list] = {}
        officer_names: dict = {}
        majors: dict = {}  # major_id|None -> MajorInfo|None
        for pid, dim in dims.items():
            ms = milestones.get(pid, {})
            oid = dim.officer_key if isinstance(dim.officer_key, int) else None
            mid = dim.major_key if isinstance(dim.major_key, int) else None
            slot = cells.setdefault((oid, mid), [0, 0, 0, 0, 0])
            if ms.get("submitted_cumulative"):
                slot[0] += 1
            if statuses.get(pid) == "draft":
                slot[1] += 1
            fee = tuition.get(pid)
            if fee == "partial":
                slot[2] += 1
            elif fee == "full":
                slot[3] += 1
            if ms.get("enrolled_cumulative"):
                slot[4] += 1
            officer_names.setdefault(oid, dim.officer_name if oid is not None else None)
            majors.setdefault(mid, dim.major if mid is not None else None)

        missing = [
            o for o, nm in officer_names.items() if isinstance(o, int) and not nm
        ]
        if missing:
            resolved = await self.repo.get_user_names(missing)
            for oid in missing:
                officer_names[oid] = resolved.get(oid, f"Cán bộ #{oid}")

        # Sắp cán bộ + ngành theo tổng 'đã nộp' (chỉ số tab đầu) giảm dần → thứ tự
        # ỔN ĐỊNH xuyên tab; bucket (id=None) chốt cuối. FE re-sort hàng theo tab.
        o_sub: dict = {}
        m_sub: dict = {}
        for (o, m), v in cells.items():
            o_sub[o] = o_sub.get(o, 0) + v[0]
            m_sub[m] = m_sub.get(m, 0) + v[0]
        officer_ids = sorted(officer_names, key=lambda o: (o is None, -o_sub.get(o, 0)))
        major_ids = sorted(majors, key=lambda m: (m is None, -m_sub.get(m, 0)))

        officers_out = [
            MatrixOfficer(
                id=o,
                name=(officer_names.get(o) or "Cán bộ")
                if o is not None
                else "Chưa gán cán bộ",
            )
            for o in officer_ids
        ]
        majors_out = []
        for m in major_ids:
            if m is None:
                majors_out.append(MatrixMajor(id=None, name="Chưa phân loại ngành"))
                continue
            info = majors.get(m)
            majors_out.append(
                MatrixMajor(
                    id=m,
                    code=info.code if info else None,
                    name=(info.name if info and info.name else f"Ngành #{m}"),
                    degree_level=info.degree_level if info else None,
                )
            )
        cells_out = [
            OfficerMajorCell(
                officer_id=o,
                major_id=m,
                submitted=v[0],
                draft=v[1],
                fee_partial=v[2],
                fee_full=v[3],
                enrolled=v[4],
            )
            for (o, m), v in cells.items()
            if any(v)
        ]
        return OfficerMajorMatrixResponse(
            academic_year=academic_year,
            round_code=round_code,
            scope_unit_id=scope_unit_id,
            officers=officers_out,
            majors=majors_out,
            cells=cells_out,
        )

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _build_funnel_stages(
        stages_meta: list, on_path: dict, leak_stage_ids: set
    ) -> list[FunnelStage]:
        """Backend owns the funnel model (thin-client): from ordered stage meta
        ``(id, name, order, is_final, color)`` + ON-PATH counts (early exits already
        removed by the repo) + ``leak_stage_ids`` (negative-terminal stages derived
        from status outcomes), compute per-stage ``reached`` (cumulative on the path)
        and ``conversion_pct`` (vs the previous path stage).

        Leak stages are marked (``is_leak``) and kept OFF the path; the exited leads
        themselves are reported once as ``PipelineFunnelResponse.leaked``. reached[k]
        = Σ on_path at/below k. Pure + unit-testable; the FE renders it verbatim.
        """
        ordered = sorted(stages_meta, key=lambda s: s[2])  # by order
        path = [s for s in ordered if s[0] not in leak_stage_ids]
        reached: dict = {}
        running = 0
        for s in reversed(path):  # bottom-up cumulative on the path
            running += on_path.get(s[0], 0)
            reached[s[0]] = running
        out: list[FunnelStage] = []
        prev_reached: Optional[int] = None
        for sid, name, order, is_final, color in ordered:
            cur = on_path.get(sid, 0)
            if sid in leak_stage_ids:
                out.append(
                    FunnelStage(
                        stage_id=sid, name=name, order=order, is_final=is_final,
                        color_code=color, current=cur, reached=cur,
                        conversion_pct=None, is_leak=True,
                    )
                )
                continue
            r = reached.get(sid, 0)
            conv = round(r / prev_reached * 100, 1) if prev_reached else None
            out.append(
                FunnelStage(
                    stage_id=sid, name=name, order=order, is_final=is_final,
                    color_code=color, current=cur, reached=r,
                    conversion_pct=conv, is_leak=False,
                )
            )
            prev_reached = r
        return out

    @staticmethod
    def _sort_key(row: ReportRow):
        # buckets to the bottom; real rows by activity (hồ sơ nộp lũy kế, rồi lead).
        return (
            row.is_bucket,
            -(row.admission.submitted_cumulative + row.lead.new_in_week),
            row.label,
        )

    @staticmethod
    def _apply_conversion(row: ReportRow) -> None:
        """Cumulative funnel ratios; left None when the denominator is 0."""
        a = row.admission
        if a.submitted_cumulative:
            row.conversion.submit_to_admit = round(
                a.admitted_cumulative / a.submitted_cumulative, 4
            )
        if a.admitted_cumulative:
            row.conversion.admit_to_enroll = round(
                a.enrolled_cumulative / a.admitted_cumulative, 4
            )

    @staticmethod
    def _totals(rows: list[ReportRow]) -> ReportRow:
        t = ReportRow(label="TỔNG")
        for row in rows:
            t.lead.new_in_week += row.lead.new_in_week
            t.lead.active_current += row.lead.active_current
            t.lead.consulting_positive_current += row.lead.consulting_positive_current
            for m in (
                "profiles_total",
                "submitted_in_week",
                "admitted_in_week",
                "enrolled_in_week",
                "submitted_cumulative",
                "admitted_cumulative",
                "enrolled_cumulative",
                "fee_paid_not_submitted",
            ):
                setattr(
                    t.admission, m, getattr(t.admission, m) + getattr(row.admission, m)
                )
            for m in (
                "gross_in_week",
                "refund_in_week",
                "net_in_week",
                "application_net_in_week",
                "tuition_net_in_week",
                "net_cumulative",
                "profiles_paid",
            ):
                setattr(t.finance, m, getattr(t.finance, m) + getattr(row.finance, m))
            if row.admission.quota is not None:
                t.admission.quota = (t.admission.quota or 0) + row.admission.quota
        AdmissionReportService._apply_conversion(t)
        return t
