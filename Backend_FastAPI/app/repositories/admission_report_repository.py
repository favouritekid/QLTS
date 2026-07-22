"""Data access for the weekly admission report.

Design (locked with product owner):
- **Attribution = recomputed-current**: ngành/officer resolve theo trạng thái HIỆN
  TẠI (admitted choice → NV1 → applied_rules → lead.offering). Số tuần đã qua có
  thể đổi khi publish/đổi NV.
- **Event-based weeks**: lead ``created_at`` (new) / ``LeadStatusHistory.changed_at``;
  admission milestones = FIRST transition into a status (status_history MIN
  ``occurred_at``); finance = ledger ``PaymentTransaction.created_at``.
- Resolution + bucketing done in Python (catalog is small) so ``ambiguous`` (>1
  admitted choice) and ``unresolved`` (no choice/offering) are explicit, never
  silently folded into a real ngành.
- Soft-deleted leads (``Lead.deleted_at``) are excluded everywhere (parity with the
  admission stats fix).

The service layer owns the week/round contract and passes pre-computed VN-aware
ranges in; this repo only aggregates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Union

from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.utils.admission_status import ADMITTED_LIKE_STATUSES

# Milestone status sets (event-based, first-transition).
SUBMITTED_STATUSES = frozenset({"submitted", "resubmitted"})
ENROLLED_STATUS = "enrolled"

# Bucket sentinels (group keys that are not a real major_id / officer_id).
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"
UNASSIGNED = "unassigned"

# Cash-affecting ledger types only (waive/adjustment/penalty/reversal are not cash).
_CASH_TYPES = ("payment", "refund")

GroupKey = Union[int, str]  # major_id / officer_id, or a bucket sentinel


@dataclass
class MajorInfo:
    major_id: int
    code: Optional[str]
    name: Optional[str]
    degree_level: Optional[str]


@dataclass
class ProfileDim:
    """Resolved reporting dimensions for one profile."""

    profile_id: int
    lead_id: int
    # major group key: int major_id, or AMBIGUOUS / UNRESOLVED
    major_key: GroupKey
    major: Optional[MajorInfo]
    # officer group key: int officer_id, or UNASSIGNED
    officer_key: GroupKey
    officer_name: Optional[str]
    round_code: Optional[str]


@dataclass
class WindowRange:
    start: datetime  # VN-aware
    end_excl: datetime  # VN-aware, half-open


@dataclass
class _Counts:
    submitted_in_week: int = 0
    admitted_in_week: int = 0
    enrolled_in_week: int = 0
    submitted_cumulative: int = 0
    admitted_cumulative: int = 0
    enrolled_cumulative: int = 0


@dataclass
class _Money:
    gross_in_week: Decimal = field(default_factory=lambda: Decimal("0"))
    refund_in_week: Decimal = field(default_factory=lambda: Decimal("0"))
    net_in_week: Decimal = field(default_factory=lambda: Decimal("0"))
    application_net_in_week: Decimal = field(default_factory=lambda: Decimal("0"))
    tuition_net_in_week: Decimal = field(default_factory=lambda: Decimal("0"))
    net_cumulative: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class _Leads:
    new_in_week: int = 0
    active_current: int = 0
    consulting_positive_current: int = 0


class AdmissionReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ filters
    async def list_report_years(self) -> list[int]:
        """Years selectable in the report (config ∪ live report data), newest first.

        Union of: ``OfferingAcademicInfo`` (excl. soft-deleted) ∪
        ``OfferingAdmissionRound`` (config) ∪ academic years of LIVE (non-deleted
        lead) profiles (data). So a year configured with offerings but no rounds
        appears, AND a year whose config was removed but still has live profiles
        (the endpoint serves it) stays selectable — while a year that exists ONLY
        via soft-deleted leads cannot leak in.
        """
        info_years = select(models.OfferingAcademicInfo.academic_year).where(
            models.OfferingAcademicInfo.is_deleted.is_(False)
        )
        round_years = select(models.OfferingAdmissionRound.academic_year)
        profile_years = (
            select(models.AdmissionProfile.academic_year)
            .join(models.Lead, models.AdmissionProfile.lead_id == models.Lead.id)
            .where(
                models.AdmissionProfile.academic_year.isnot(None),
                models.Lead.deleted_at.is_(None),
            )
        )
        rows = (
            (await self.db.execute(info_years.union(round_years, profile_years)))
            .scalars()
            .all()
        )
        return sorted({y for y in rows if y is not None}, reverse=True)

    async def list_report_rounds(self, academic_year: int) -> list[str]:
        """Distinct round_codes configured for the year, ordered by code."""
        stmt = (
            select(models.OfferingAdmissionRound.round_code)
            .where(models.OfferingAdmissionRound.academic_year == academic_year)
            .distinct()
            .order_by(models.OfferingAdmissionRound.round_code)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def major_quotas(
        self, academic_year: int
    ) -> dict[int, tuple[int, MajorInfo]]:
        """major_id -> (Σ annual_admission_quota, MajorInfo) for the year, toàn trường.

        Returns EVERY ACTIVE major with a (non-soft-deleted) quota row — even with
        zero activity — so the cockpit can rank 0%-progress ngành. Whole-school
        only: ``annual_admission_quota`` is a per-offering institution target with
        no per-unit split, so the service shows it for admin scope only.
        """
        stmt = (
            select(
                models.MajorProgram.id,
                models.MajorProgram.code,
                models.MajorProgram.name,
                models.MajorProgram.degree_level,
                func.sum(models.OfferingAcademicInfo.annual_admission_quota),
            )
            .join(
                models.ProgramOffering,
                models.ProgramOffering.program_id == models.MajorProgram.id,
            )
            .join(
                models.OfferingAcademicInfo,
                models.OfferingAcademicInfo.offering_id == models.ProgramOffering.id,
            )
            .where(
                models.OfferingAcademicInfo.academic_year == academic_year,
                models.OfferingAcademicInfo.annual_admission_quota.isnot(None),
                models.OfferingAcademicInfo.is_deleted.is_(False),
                models.MajorProgram.is_active.is_(True),
                models.ProgramOffering.is_active.is_(True),
            )
            .group_by(
                models.MajorProgram.id,
                models.MajorProgram.code,
                models.MajorProgram.name,
                models.MajorProgram.degree_level,
            )
        )
        rows = (await self.db.execute(stmt)).all()
        return {
            mid: (
                int(total),
                MajorInfo(major_id=mid, code=code, name=name, degree_level=degree),
            )
            for mid, code, name, degree, total in rows
            if total is not None
        }

    # ------------------------------------------------------------------ catalog
    async def _build_catalog(
        self,
    ) -> tuple[
        dict[int, tuple[MajorInfo, Optional[str]]],
        dict[int, MajorInfo],
        dict[int, MajorInfo],
    ]:
        """Return (path_id -> (MajorInfo, round_code), offering_id -> MajorInfo).

        One pass over the (small) catalog. ``degree_level`` uses the plain text
        column to avoid the ``degree_level_ref`` ``lazy="raise"`` relationship.
        """
        # offering_id -> MajorInfo
        off_rows = await self.db.execute(
            select(
                models.OfferingAcademicInfo.id,
                models.ProgramOffering.program_id,
                models.MajorProgram.code,
                models.MajorProgram.name,
                models.MajorProgram.degree_level,
                models.OfferingAcademicInfo.offering_id,
            )
            .join(
                models.ProgramOffering,
                models.OfferingAcademicInfo.offering_id == models.ProgramOffering.id,
            )
            .join(
                models.MajorProgram,
                models.ProgramOffering.program_id == models.MajorProgram.id,
            )
        )
        academic_info_to_major: dict[int, MajorInfo] = {}
        offering_to_major: dict[int, MajorInfo] = {}
        major_by_id: dict[int, MajorInfo] = {}
        for ai_id, major_id, code, name, degree, offering_id in off_rows:
            info = MajorInfo(
                major_id=major_id, code=code, name=name, degree_level=degree
            )
            academic_info_to_major[ai_id] = info
            offering_to_major[offering_id] = info
            major_by_id[major_id] = info

        # path_id -> (academic_info_id, round_code)
        path_rows = await self.db.execute(
            select(
                models.AdmissionPath.id,
                models.AdmissionPath.academic_info_id,
                models.OfferingAdmissionRound.round_code,
            ).join(
                models.OfferingAdmissionRound,
                models.AdmissionPath.admission_round_id
                == models.OfferingAdmissionRound.id,
            )
        )
        path_to_major: dict[int, tuple[MajorInfo, Optional[str]]] = {}
        for path_id, ai_id, round_code in path_rows:
            info = academic_info_to_major.get(ai_id)
            if info is not None:
                path_to_major[path_id] = (info, round_code)
        return path_to_major, offering_to_major, major_by_id

    async def get_user_names(self, user_ids: list[int]) -> dict[int, str]:
        """user_id -> display name (full_name → username → #id)."""
        if not user_ids:
            return {}
        rows = await self.db.execute(
            select(models.User.id, models.User.full_name, models.User.username).where(
                models.User.id.in_(user_ids)
            )
        )
        return {uid: (full or username or f"#{uid}") for uid, full, username in rows}

    # --------------------------------------------------------------- resolution
    async def resolve_profiles(
        self,
        academic_year: int,
        scope_unit_id: Optional[int],
        officer_id: Optional[int],
        round_code: Optional[str],
    ) -> tuple[dict[int, ProfileDim], dict[int, MajorInfo]]:
        """Resolve every in-scope profile to its (major, officer, round) dims.

        Scope: ``profile.academic_year == academic_year``, ``lead.deleted_at IS
        NULL``, optional ``lead.unit_id``/``lead.assigned_officer_id``. When
        ``round_code`` is given, profiles whose resolved round differs are dropped.
        """
        path_to_major, offering_to_major, major_by_id = await self._build_catalog()

        conds = [
            models.AdmissionProfile.academic_year == academic_year,
            models.Lead.deleted_at.is_(None),
        ]
        if scope_unit_id is not None:
            conds.append(models.Lead.unit_id == scope_unit_id)
        if officer_id is not None:
            conds.append(models.Lead.assigned_officer_id == officer_id)

        rows = await self.db.execute(
            select(
                models.AdmissionProfile.id,
                models.AdmissionProfile.lead_id,
                models.AdmissionProfile.applied_rules,
                models.Lead.assigned_officer_id,
                models.Lead.offering_id,
                models.User.full_name,
                models.User.username,
            )
            .join(models.Lead, models.AdmissionProfile.lead_id == models.Lead.id)
            .join(
                models.User,
                models.Lead.assigned_officer_id == models.User.id,
                isouter=True,
            )
            .where(and_(*conds))
        )
        profiles = rows.all()
        profile_ids = [r[0] for r in profiles]
        choices_by_profile = await self._load_choices(profile_ids)

        out: dict[int, ProfileDim] = {}
        for (
            pid,
            lead_id,
            applied_rules,
            officer,
            offering_id,
            full_name,
            username,
        ) in profiles:
            major_key, major_info, resolved_round = self._resolve_one(
                pid,
                applied_rules,
                offering_id,
                choices_by_profile,
                path_to_major,
                offering_to_major,
            )
            if (
                round_code is not None
                and resolved_round is not None
                and resolved_round != round_code
            ):
                continue  # different round (None-round profiles are always shown)
            officer_key: GroupKey = officer if officer is not None else UNASSIGNED
            out[pid] = ProfileDim(
                profile_id=pid,
                lead_id=lead_id,
                major_key=major_key,
                major=major_info,
                officer_key=officer_key,
                officer_name=(full_name or username) if officer is not None else None,
                round_code=resolved_round,
            )
        return out, major_by_id

    async def _load_choices(self, profile_ids: list[int]) -> dict[int, list]:
        if not profile_ids:
            return {}
        rows = await self.db.execute(
            select(
                models.AdmissionProfileChoice.admission_profile_id,
                models.AdmissionProfileChoice.admission_path_id,
                models.AdmissionProfileChoice.decision,
                models.AdmissionProfileChoice.display_order,
            ).where(models.AdmissionProfileChoice.admission_profile_id.in_(profile_ids))
        )
        by_profile: dict[int, list] = defaultdict(list)
        for pid, path_id, decision, order in rows:
            by_profile[pid].append((path_id, decision, order))
        return by_profile

    @staticmethod
    def _resolve_one(
        pid: int,
        applied_rules: Optional[dict],
        offering_id: Optional[int],
        choices_by_profile: dict[int, list],
        path_to_major: dict[int, tuple[MajorInfo, Optional[str]]],
        offering_to_major: dict[int, MajorInfo],
    ) -> tuple[GroupKey, Optional[MajorInfo], Optional[str]]:
        """5-tier resolver: admitted → NV1 → applied_rules → offering → unresolved.
        >1 admitted → ambiguous (never auto-pick).
        """
        chs = choices_by_profile.get(pid, [])
        admitted = [c for c in chs if c[1] == "admitted"]
        if len(admitted) > 1:
            return AMBIGUOUS, None, None

        # Ordered path candidates; use the FIRST that actually resolves so a
        # broken/archived path does NOT short-circuit into UNRESOLVED — it falls
        # through to the next tier (legacy applied_rules, then lead.offering).
        candidate_paths: list[int] = []
        if len(admitted) == 1:
            candidate_paths.append(admitted[0][0])
        nv1 = next((c for c in chs if c[2] == 1), None)  # NV1 = display_order == 1
        if nv1 is not None:
            candidate_paths.append(nv1[0])
        if isinstance(applied_rules, dict):  # guard non-dict JSONB (list/str → no .get)
            legacy_path = applied_rules.get("admission_path_id")
            if legacy_path is not None:
                try:
                    candidate_paths.append(int(legacy_path))
                except (TypeError, ValueError):
                    pass
        for path_id in candidate_paths:
            res = AdmissionReportRepository._from_path(path_id, path_to_major)
            if res[0] != UNRESOLVED:
                return res

        # final fallback: lead intent offering
        if offering_id is not None and offering_id in offering_to_major:
            info = offering_to_major[offering_id]
            return info.major_id, info, None
        return UNRESOLVED, None, None

    @staticmethod
    def _from_path(
        path_id: int, path_to_major: dict[int, tuple[MajorInfo, Optional[str]]]
    ) -> tuple[GroupKey, Optional[MajorInfo], Optional[str]]:
        hit = path_to_major.get(path_id)
        if hit is None:
            return UNRESOLVED, None, None
        info, round_code = hit
        return info.major_id, info, round_code

    # ------------------------------------------------------------- admission ev
    async def admission_milestones(
        self,
        profile_ids: list[int],
        week: WindowRange,
        cumulative_end: datetime,
    ) -> dict[int, dict[str, bool]]:
        """For each profile → which milestone events land in-week / cumulative.

        Milestone = FIRST transition into the status set (MIN occurred_at). Counting
        the first occurrence keeps a resubmitted profile from being counted twice
        across weeks.
        """
        if not profile_ids:
            return {}
        hist = models.AdmissionProfileStatusHistory
        result: dict[int, dict[str, bool]] = {}

        async def _first_into(status_pred):
            rows = await self.db.execute(
                select(hist.profile_id, func.min(hist.occurred_at))
                .where(
                    hist.profile_id.in_(profile_ids),
                    # Exclude the phase1_10 synthetic "initial state" backfill row
                    # (from_status NULL → current @ profile.created_at) — it would
                    # mis-date legacy milestones to the creation week. Scalar-derived
                    # backfills + real transitions keep a non-NULL from_status.
                    hist.from_status.isnot(None),
                    status_pred,
                )
                .group_by(hist.profile_id)
            )
            return {pid: ts for pid, ts in rows}

        # Monotone funnel: a profile that reached a later milestone is counted at
        # every earlier one too (override/bulk-import can skip the 'submitted' row),
        # so submitted ⊇ admitted ⊇ enrolled → MIN(submitted) ≤ MIN(admitted) ≤ ...
        admitted_set = set(ADMITTED_LIKE_STATUSES) | {ENROLLED_STATUS}
        submitted_set = set(SUBMITTED_STATUSES) | admitted_set
        firsts = {
            "submitted": await _first_into(hist.to_status.in_(submitted_set)),
            "admitted": await _first_into(hist.to_status.in_(admitted_set)),
            "enrolled": await _first_into(hist.to_status == ENROLLED_STATUS),
        }
        for milestone, by_pid in firsts.items():
            for pid, ts in by_pid.items():
                slot = result.setdefault(pid, {})
                if ts is not None and ts < cumulative_end:
                    slot[f"{milestone}_cumulative"] = True
                    if week.start <= ts < week.end_excl:
                        slot[f"{milestone}_in_week"] = True
        return result

    # ----------------------------------------------------------------- finance
    async def finance_rows(
        self,
        profile_ids: list[int],
        cumulative_end: datetime,
    ) -> list[tuple[int, str, str, Decimal, datetime]]:
        """Raw cash ledger rows for in-scope profiles up to ``cumulative_end``.

        Returns (profile_id, fee_type, transaction_type, amount, created_at).
        ``amount`` keeps its stored sign (refund negative). Bucketing into
        week/cumulative + by dimension is done by the caller.
        """
        if not profile_ids:
            return []
        rows = await self.db.execute(
            select(
                models.Fee.admission_profile_id,
                models.Fee.fee_type,
                models.PaymentTransaction.transaction_type,
                models.PaymentTransaction.amount,
                models.PaymentTransaction.created_at,
            )
            .join(models.Fee, models.PaymentTransaction.fee_id == models.Fee.id)
            .where(
                models.Fee.admission_profile_id.in_(profile_ids),
                # Admission-relevant fees only, so gross/net reconciles with the
                # application+tuition split (excludes dormitory/insurance/...).
                models.Fee.fee_type.in_(("application", "tuition")),
                models.PaymentTransaction.transaction_type.in_(_CASH_TYPES),
                models.PaymentTransaction.created_at < cumulative_end,
            )
        )
        return [tuple(r) for r in rows.all()]

    # -------------------------------------------------------------------- leads
    async def lead_counts(
        self,
        academic_year: int,
        cohort_ranges: list[WindowRange],
        week: WindowRange,
        group_by: str,
        scope_unit_id: Optional[int],
        officer_id: Optional[int],
        profile_lead_ids: Optional[set] = None,
    ) -> dict[GroupKey, _Leads]:
        """Lead funnel grouped by intent-offering→major (major mode) or officer.

        Cohort = ``lead.created_at`` within any round window of the year. Leads
        without an offering go to UNRESOLVED (major mode); without an officer to
        UNASSIGNED (officer mode). Stocks (``active_current``/``consulting_positive``)
        are NOW among cohort leads (cohort-restricted, not all leads ever).
        """
        window_preds = [
            and_(
                models.Lead.created_at >= r.start,
                models.Lead.created_at < r.end_excl,
            )
            for r in cohort_ranges
        ]
        # Cohort = leads created in a round window OR leads that already produced an
        # in-scope profile (walk-ins between rounds) — keeps the lead funnel aligned
        # with the admission/finance population so admission never exceeds lead.
        if profile_lead_ids:
            window_preds.append(models.Lead.id.in_(profile_lead_ids))
        if not window_preds:
            return {}
        cohort_pred = or_(*window_preds)
        conds = [models.Lead.deleted_at.is_(None), cohort_pred]
        if scope_unit_id is not None:
            conds.append(models.Lead.unit_id == scope_unit_id)
        if officer_id is not None:
            conds.append(models.Lead.assigned_officer_id == officer_id)

        new_in_week = and_(
            models.Lead.created_at >= week.start, models.Lead.created_at < week.end_excl
        )
        # active = consultation status not final (NULL status → treat as active)
        active = models.ConsultationStatus.is_final.isnot(True)
        # "Tư vấn+" stock: currently at a positive consultation-phase status.
        consulting = and_(
            models.ConsultationStatus.phase == "consultation",
            models.ConsultationStatus.outcome_type == "positive",
        )

        if group_by == "officer":
            group_col = models.Lead.assigned_officer_id
        else:
            group_col = models.ProgramOffering.program_id

        stmt = (
            select(
                group_col,
                func.count(distinct(models.Lead.id)).filter(new_in_week),
                func.count(distinct(models.Lead.id)).filter(active),
                func.count(distinct(models.Lead.id)).filter(consulting),
            )
            .select_from(models.Lead)
            .join(
                models.ConsultationStatus,
                models.Lead.consultation_status_id == models.ConsultationStatus.id,
                isouter=True,
            )
            .where(and_(*conds))
            .group_by(group_col)
        )
        if group_by != "officer":
            stmt = stmt.join(
                models.ProgramOffering,
                models.Lead.offering_id == models.ProgramOffering.id,
                isouter=True,
            )

        rows = await self.db.execute(stmt)
        out: dict[GroupKey, _Leads] = {}
        for key_val, new_cnt, active_cnt, consult_cnt in rows:
            if key_val is None:
                key: GroupKey = UNASSIGNED if group_by == "officer" else UNRESOLVED
            else:
                key = key_val
            bucket = out.setdefault(key, _Leads())
            bucket.new_in_week += int(new_cnt or 0)
            bucket.active_current += int(active_cnt or 0)
            bucket.consulting_positive_current += int(consult_cnt or 0)
        return out

    # ----------------------------------------------------- milestone timestamps
    async def milestone_timestamps(
        self, profile_ids: list[int]
    ) -> dict[str, dict[int, datetime]]:
        """profile_id → FIRST-transition timestamp per milestone (for the trend).

        Same event definition as ``admission_milestones`` (MIN occurred_at, skipping
        the synthetic ``from_status IS NULL`` backfill row), but returns the raw
        timestamps so the service can bucket them into any number of week cutoffs
        without re-querying per week. Monotone funnel: submitted ⊇ admitted ⊇
        enrolled.
        """
        empty = {"submitted": {}, "admitted": {}, "enrolled": {}}
        if not profile_ids:
            return empty
        hist = models.AdmissionProfileStatusHistory

        async def _first_into(status_pred) -> dict[int, datetime]:
            rows = await self.db.execute(
                select(hist.profile_id, func.min(hist.occurred_at))
                .where(
                    hist.profile_id.in_(profile_ids),
                    hist.from_status.isnot(None),
                    status_pred,
                )
                .group_by(hist.profile_id)
            )
            return {pid: ts for pid, ts in rows if ts is not None}

        admitted_set = set(ADMITTED_LIKE_STATUSES) | {ENROLLED_STATUS}
        submitted_set = set(SUBMITTED_STATUSES) | admitted_set
        return {
            "submitted": await _first_into(hist.to_status.in_(submitted_set)),
            "admitted": await _first_into(hist.to_status.in_(admitted_set)),
            "enrolled": await _first_into(hist.to_status == ENROLLED_STATUS),
        }

    # -------------------------------------------------------- pipeline funnel
    async def pipeline_funnel_counts(
        self,
        cohort_ranges: list[WindowRange],
        scope_unit_id: Optional[int],
        officer_id: Optional[int],
    ) -> tuple[list[tuple[str, str, int, bool, str]], dict[str, int], int]:
        """(stages_meta, counts_by_stage, total_leads) for the cohort.

        Stages = every ``PipelineStage`` ordered by ``order``. Counts = distinct
        leads currently at each stage (``Lead.pipeline_stage_id``) among the cohort
        (``created_at`` in a round window of the year, non-deleted, unit/officer
        scoped). A lead with NULL stage folds into the lowest-order stage (chưa bắt
        đầu) so ``Σ current == total_leads``.
        """
        stage_rows = (
            await self.db.execute(
                select(
                    models.PipelineStage.id,
                    models.PipelineStage.name,
                    models.PipelineStage.order,
                    models.PipelineStage.is_final_stage,
                    models.PipelineStage.color_code,
                ).order_by(models.PipelineStage.order)
            )
        ).all()
        stages = [
            (sid, name, order, bool(fin), color)
            for sid, name, order, fin, color in stage_rows
        ]
        if not cohort_ranges:
            return stages, {}, 0

        window_preds = [
            and_(models.Lead.created_at >= r.start, models.Lead.created_at < r.end_excl)
            for r in cohort_ranges
        ]
        conds = [models.Lead.deleted_at.is_(None), or_(*window_preds)]
        if scope_unit_id is not None:
            conds.append(models.Lead.unit_id == scope_unit_id)
        if officer_id is not None:
            conds.append(models.Lead.assigned_officer_id == officer_id)

        rows = await self.db.execute(
            select(
                models.Lead.pipeline_stage_id,
                func.count(distinct(models.Lead.id)),
            )
            .where(and_(*conds))
            .group_by(models.Lead.pipeline_stage_id)
        )
        lowest = stages[0][0] if stages else None  # order-sorted → first = lowest
        counts: dict[str, int] = {}
        total = 0
        for stage_id, cnt in rows:
            c = int(cnt or 0)
            total += c
            key = stage_id if stage_id is not None else lowest
            if key is not None:
                counts[key] = counts.get(key, 0) + c
        return stages, counts, total
