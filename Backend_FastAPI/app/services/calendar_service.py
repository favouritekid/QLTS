# app/services/calendar_service.py
"""
Calendar Service — Working days calculation (Phase A3)

Counts T2-T7 (Mon-Sat) working days per month, excluding holidays from holiday_calendar.
Used by KPI Planning Engine to compute WD_t for reverse-funnel formulas.
"""
import calendar
from datetime import date
from typing import Optional

import structlog
from sqlalchemy import select, extract, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import HolidayCalendar, KpiPlanMonth

log = structlog.get_logger(__name__)


async def count_working_days(db: AsyncSession, year: int, month: int) -> int:
    """
    Count working days (T2-T7 = Mon-Sat) in a given month, minus holidays.

    Holiday matching:
    - is_recurring=TRUE: match by month/day regardless of year (e.g. 1/1, 30/4)
    - is_recurring=FALSE: match by exact date (e.g. Tết Nguyên Đán 2026-01-28)
    - No double-counting when both match the same date.

    Args:
        db: Database session (read-only, no commit)
        year: Calendar year (e.g. 2026)
        month: Calendar month (1-12)

    Returns:
        Number of working days (≥ 0). Returns 0 if entire month is holidays.

    Raises:
        ValueError: If month not in 1..12
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month}")

    # Step 1: Count Mon-Sat days in the month (exclude Sunday = weekday 6)
    cal = calendar.Calendar()
    # itermonthdays2 returns (day, weekday) where weekday: Mon=0 .. Sun=6
    mon_sat_dates: set[date] = set()
    for day_num, weekday in cal.itermonthdays2(year, month):
        if day_num == 0:
            continue  # Day belongs to adjacent month
        if weekday != 6:  # Not Sunday
            mon_sat_dates.add(date(year, month, day_num))

    total_mon_sat = len(mon_sat_dates)

    # Step 2: Query holidays that fall in this month
    # - Recurring: match month AND day (any year)
    # - Non-recurring: match exact date in target year
    first_day = date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day = date(year, month, last_day_num)

    stmt = select(HolidayCalendar.date, HolidayCalendar.is_recurring).where(
        or_(
            # Non-recurring: exact date within month
            and_(
                HolidayCalendar.is_recurring == False,  # noqa: E712
                HolidayCalendar.date >= first_day,
                HolidayCalendar.date <= last_day,
            ),
            # Recurring: match month/day pattern (any year in DB)
            and_(
                HolidayCalendar.is_recurring == True,  # noqa: E712
                extract("month", HolidayCalendar.date) == month,
            ),
        )
    )
    result = await db.execute(stmt)
    holiday_rows = result.all()

    # Step 3: Collect unique holiday dates that fall on Mon-Sat
    holiday_dates: set[date] = set()
    for row_date, is_recurring in holiday_rows:
        if is_recurring:
            # Recurring: use the target year with the stored month/day
            try:
                actual_date = date(year, row_date.month, row_date.day)
            except ValueError:
                # Edge case: Feb 29 in non-leap year → skip
                continue
        else:
            actual_date = row_date

        # Only subtract if the holiday falls on a working day (Mon-Sat)
        if actual_date in mon_sat_dates:
            holiday_dates.add(actual_date)

    working_days = total_mon_sat - len(holiday_dates)

    log.debug(
        "Working days calculated",
        year=year, month=month,
        total_mon_sat=total_mon_sat,
        holidays_on_workdays=len(holiday_dates),
        working_days=working_days,
    )

    return working_days


async def get_working_days_override(
    db: AsyncSession, plan_month_id: int
) -> Optional[int]:
    """
    Check if admin has overridden working_days for a plan month.

    Override is detected by checking if "working_days" is in the
    overridden_fields JSONB. If so, return the overridden value.
    If not overridden, return None (caller should use count_working_days).

    Args:
        db: Database session (read-only, no commit)
        plan_month_id: ID of the KpiPlanMonth record

    Returns:
        Override value (int) if working_days was manually overridden.
        None if not overridden or record not found.
    """
    stmt = select(
        KpiPlanMonth.working_days,
        KpiPlanMonth.overridden_fields,
    ).where(KpiPlanMonth.id == plan_month_id)

    result = await db.execute(stmt)
    row = result.one_or_none()

    if row is None:
        return None

    working_days, overridden_fields = row
    overridden = overridden_fields or {}

    if "working_days" in overridden:
        return working_days

    return None


# =============================================================================
# HOLIDAY STATUS CHECK (Phase A9)
# =============================================================================

# Known lunar holidays that require manual seeding each year
LUNAR_HOLIDAY_KEYWORDS = ["Tết Nguyên Đán", "Giỗ Tổ Hùng Vương"]
HOLIDAY_COMPLETE_THRESHOLD = 8  # Minimum holidays expected for a complete year


async def get_holiday_status(db: AsyncSession, year: int) -> dict:
    """
    Check if holiday_calendar is sufficiently seeded for a given year.

    Returns dict with:
      - year, total_holidays, has_lunar_holidays, is_complete, warning
    Read-only — no commit.
    """
    from sqlalchemy import func

    # Count all holidays applicable to this year:
    # - Non-recurring: year column matches
    # - Recurring: always apply (match by is_recurring=TRUE)
    stmt = select(
        HolidayCalendar.name,
        HolidayCalendar.is_recurring,
        HolidayCalendar.year,
    ).where(
        or_(
            and_(HolidayCalendar.is_recurring == False, HolidayCalendar.year == year),  # noqa: E712
            HolidayCalendar.is_recurring == True,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    total = len(rows)

    # Check for lunar holidays by keyword match
    all_names = " ".join(r.name for r in rows)
    has_tet = any(kw in all_names for kw in ["Tết Nguyên Đán"])
    has_hung_vuong = any(kw in all_names for kw in ["Hùng Vương"])
    has_lunar = has_tet and has_hung_vuong

    is_complete = total >= HOLIDAY_COMPLETE_THRESHOLD and has_lunar

    # Build warning message
    warning = None
    if not is_complete:
        missing = []
        if not has_tet:
            missing.append("Tết Nguyên Đán")
        if not has_hung_vuong:
            missing.append("Giỗ Tổ Hùng Vương")
        if total < HOLIDAY_COMPLETE_THRESHOLD:
            missing.append(f"chỉ có {total}/{HOLIDAY_COMPLETE_THRESHOLD} ngày lễ")
        warning = f"Chưa cấu hình đầy đủ ngày lễ cho năm {year}: {', '.join(missing)}"

    return {
        "year": year,
        "total_holidays": total,
        "has_lunar_holidays": has_lunar,
        "is_complete": is_complete,
        "warning": warning,
    }
