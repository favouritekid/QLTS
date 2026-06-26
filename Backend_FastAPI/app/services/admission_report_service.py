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
    WindowRange,
)
from app.schemas.admission_report import (
    AdmissionWeeklyReportResponse,
    DataQuality,
    ReportFilters,
    ReportRow,
    WeekMeta,
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

    # ------------------------------------------------------------ cohort window
    async def _cohort_ranges(
        self, academic_year: int, round_code: Optional[str]
    ) -> list[WindowRange]:
        """VN [start 00:00, end+1day 00:00) windows for the year's round(s).

        Fail-closed: a selected round missing start/end raises (don't silently span
        everything). ``round_code`` not found → 404.
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
        # Implicit week for a NON-current academic_year: anchor INSIDE that year so
        # the week + cumulative cutoffs stay in-year (today's week would compute
        # cutoffs outside it). Future → ISO week 1 (Jan 4; cumulative ~0, chưa bắt
        # đầu); past → last ISO week (Dec 28; cumulative ≈ trọn năm). Both dates are
        # always inside the year's own ISO weeks.
        anchor = week_start
        if anchor is None and academic_year != today_vn().year:
            anchor = (
                date(academic_year, 1, 4)
                if academic_year > today_vn().year
                else date(academic_year, 12, 28)
            )
        week_meta, week = self._compute_week(anchor)
        # An EXPLICIT week_start before the academic year is a stale bookmark → reject
        # on the NORMALIZED ISO year (ISO week 1's Monday can fall in the prior Dec).
        if week_start is not None and week_meta.iso_year < academic_year:
            raise ValidationError(
                detail="week_start trước năm tuyển sinh — hãy chọn tuần trong năm."
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

    # --------------------------------------------------------------- helpers
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
