#!/usr/bin/env python3
"""
Smoke fixture seed for local DEV environment.

Complement layer trên seed_from_xlsx + seed_sample_data: giả định core
data (programs, offerings, academic_info, methods, subjects, users,
casbin) đã loaded. Script này thêm edge-state matrix mà Chrome MCP
pre-push smoke cần để cover 18 scenarios PR-1+PR-2+PR-3+PR-4.

5 fixture groups:
  1. ROUND matrix    — 6 rounds across window/visibility/multi_nv axes
  2. PATH matrix     — 9+ paths với quota/audience/visibility variants
  3. ANNUAL QUOTA   — Tier 1 anchor (offering cap=2, 2 admitted profiles)
  4. PROFILE state   — 7 profile fixtures via state_service.transition()
  5. MAGIC-LINK      — 6 token fixtures (active/expired/consumed/locked)

Idempotency:
  - All seeded rows marked với `round_code` LIKE 'SMOKE_DEV_%' (rounds)
    hoặc `applied_rules->>'smoke_marker' = 'true'` (profiles).
  - Reuse existing programs/methods/users/casbin — no duplicate.
  - Rerun-safe: skip-if-exists per row.

Usage:
  python -m scripts.seed_smoke_dev                # seed all groups
  python -m scripts.seed_smoke_dev --group 1      # only Round matrix
  python -m scripts.seed_smoke_dev --group 1 2    # multiple groups
  python -m scripts.seed_smoke_dev --verify       # row count report
  python -m scripts.seed_smoke_dev --reset        # cascade delete markers

Production guard:
  Refuses to run when APP_ENV='production' OR DB name matches 'qlts_prod*'.

Author: PR #348 review follow-up (2026-05-28 smoke session).
Reference: SMOKE_SEED_GUIDE.md cho fixture matrix + scenario mapping.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("APP_ENV", "development")

from app.database import AsyncSessionLocal  # noqa: E402
from app import models  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — fixture markers
# ═══════════════════════════════════════════════════════════════════════════════

# Round codes prefix (UNIQUE per academic_year). Idempotent identity key.
# Short prefix vì round_code VARCHAR(20) — `SMOKE_DEV_ACTIVE_MULTI` (21) overflows.
ROUND_PREFIX = "SMK_"
ACADEMIC_YEAR = 2026

# Profile marker in applied_rules JSONB (no native column for fixture tag).
PROFILE_MARKER_KEY = "smoke_marker"
PROFILE_MARKER_VALUE = "SMOKE_DEV"

# Citizen ID prefix — deterministic for re-seed idempotency.
CITIZEN_ID_PREFIX = "SMOKEDEV"  # appended với 4-digit index → SMOKEDEV0001


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTION GUARD
# ═══════════════════════════════════════════════════════════════════════════════

def assert_safe_environment() -> None:
    """Refuse to run on production environment OR production DB.

    Two-tier guard:
      1. APP_ENV != 'production'
      2. Database URL does not contain 'qlts_prod' substring

    Either tier failure aborts immediately. Belt+suspenders since
    accidental prod run = catastrophic (creates SMOKE_DEV_* rounds visible
    in storefront, seeds fake profiles into real candidate pipeline).
    """
    app_env = os.environ.get("APP_ENV", "development").lower()
    if app_env == "production":
        sys.exit("❌ ABORT: APP_ENV=production. This script seeds test data — refuse to run.")

    from app.config import settings as app_settings
    db_url = str(getattr(app_settings, "DATABASE_URL", ""))
    if "qlts_prod" in db_url.lower():
        sys.exit(f"❌ ABORT: DATABASE_URL contains 'qlts_prod'. Refuse to seed.\n   {db_url}")

    print(f"✅ Environment guard OK — APP_ENV={app_env}, DB target appears safe.")


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — ROUND MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

async def seed_group_1_rounds(session: AsyncSession) -> dict[str, int]:
    """Seed 6 rounds covering window × multi_nv × visibility axes.

    Returns dict mapping round_code → round.id for downstream groups.

    Matrix:
      ACTIVE_MULTI    end=today+30, multi_nv=true  → S3 explicit active
      ACTIVE_SINGLE   end=today+30, multi_nv=false → single-NV path
      EXPIRED         end=today-1                  → S7 cutoff create
      ARCHIVED        archived_at=NOW()            → S4 archived empty
      FUTURE          start=today+30               → F43 future filter
      OPEN_ENDED      start=NULL, end=NULL         → F43 NULL window edge
    """
    today = date.today()
    print(f"\n📅 Group 1 — Round matrix (today={today})")

    rounds_spec = [
        # code suffix,     start_date,        end_date,          multi_nv, archived
        ("ACTIVE_MULTI",   today - timedelta(days=10),  today + timedelta(days=30), True,  None),
        ("ACTIVE_SINGLE",  today - timedelta(days=10),  today + timedelta(days=30), False, None),
        ("EXPIRED",        today - timedelta(days=30),  today - timedelta(days=1),  False, None),
        ("ARCHIVED",       today - timedelta(days=60),  today - timedelta(days=10), False, datetime.now(timezone.utc)),
        ("FUTURE",         today + timedelta(days=30),  today + timedelta(days=60), False, None),
        ("OPEN_ENDED",     None,                        None,                       False, None),
    ]

    round_ids: dict[str, int] = {}

    for suffix, start, end, multi_nv, archived_at in rounds_spec:
        code = f"{ROUND_PREFIX}{suffix}"

        existing = (await session.execute(
            select(models.OfferingAdmissionRound).where(
                models.OfferingAdmissionRound.academic_year == ACADEMIC_YEAR,
                models.OfferingAdmissionRound.round_code == code,
            )
        )).scalar_one_or_none()

        if existing:
            round_ids[suffix] = existing.id
            print(f"  ⏭  {code} exists (id={existing.id}), skip")
            continue

        new_round = models.OfferingAdmissionRound(
            academic_year=ACADEMIC_YEAR,
            round_code=code,
            round_name=f"Smoke fixture {suffix} {ACADEMIC_YEAR}",
            start_date=start,
            end_date=end,
            is_active=True,
            archived_at=archived_at,
            allow_multi_nv=multi_nv,
        )
        session.add(new_round)
        await session.flush()
        round_ids[suffix] = new_round.id
        print(f"  ✅  {code} created (id={new_round.id}, multi_nv={multi_nv}, "
              f"window=[{start}..{end}], archived={archived_at is not None})")

    await session.commit()
    return round_ids


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — PATH × ROUND + AUDIENCE MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

async def seed_group_2_paths(
    session: AsyncSession, round_ids: dict[str, int]
) -> dict[str, int]:
    """Seed 9 paths covering quota × audience × visibility × round axes.

    Reuses existing programs/methods/academic_info — picks first available
    matching constraint via SQL. Returns dict path_label → path.id.

    Constraint: UNIQUE (admission_round_id, academic_info_id, admission_method_id).
    Matrix uses different (round, method) pairs to avoid conflict.

    Paths seeded:
      full_quota_1      → ACTIVE_MULTI, admit_quota=1, public, no audience
      free_quota_5      → ACTIVE_MULTI, admit_quota=5, public, no audience
      unbounded_null    → ACTIVE_MULTI, admit_quota=NULL, public
      audience_thpt     → ACTIVE_MULTI, applicable_to=[POST_THPT]
      audience_vlvh     → ACTIVE_MULTI, applicable_to=[VLVH]
      audience_null     → ACTIVE_MULTI, applicable_to=NULL (legacy all)
      internal_hidden   → ACTIVE_MULTI, visibility='internal' (NOT public)
      archived_path     → ACTIVE_MULTI, status='archived'
      on_expired_round  → EXPIRED round
    """
    print(f"\n🛤  Group 2 — Path matrix")

    # Pick first academic_info under any program (just need a valid FK).
    ai_stmt = (
        select(models.OfferingAcademicInfo)
        .where(models.OfferingAcademicInfo.is_published.is_(True))
        .limit(1)
    )
    target_ai = (await session.execute(ai_stmt)).scalar_one_or_none()
    if not target_ai:
        sys.exit("❌ No published academic_info found. Run seed_from_xlsx first.")

    # Pick 3 distinct admission methods (Q-P3-02 multi-NV chain needs ≥2).
    methods_stmt = select(models.AdmissionMethod).where(
        models.AdmissionMethod.is_active.is_(True)
    ).order_by(models.AdmissionMethod.id).limit(5)
    methods = (await session.execute(methods_stmt)).scalars().all()
    if len(methods) < 3:
        sys.exit("❌ Need ≥3 active admission_methods. Run seed_admission_config first.")

    # Path spec: label, round_key, method_idx, admit_quota, applicable_to,
    #            visibility, status. UNIQUE (round, ai, method) enforced by DB.
    paths_spec = [
        # Quota variants (all on ACTIVE_MULTI, different methods)
        ("full_quota_1",     "ACTIVE_MULTI", 0, 1,    None,                  "public",   "active"),
        ("free_quota_5",     "ACTIVE_MULTI", 1, 5,    None,                  "public",   "active"),
        ("unbounded_null",   "ACTIVE_MULTI", 2, None, None,                  "public",   "active"),
        # Audience variants (need different rounds since methods reused)
        ("audience_thpt",    "ACTIVE_SINGLE", 0, 10,  ["POST_THPT"],         "public",   "active"),
        ("audience_vlvh",    "ACTIVE_SINGLE", 1, 10,  ["VLVH"],              "public",   "active"),
        ("audience_null",    "ACTIVE_SINGLE", 2, 10,  None,                  "public",   "active"),
        # Visibility + status edge
        ("internal_hidden",  "OPEN_ENDED",   0, 5,    None,                  "internal", "active"),
        ("archived_path",    "OPEN_ENDED",   1, 5,    None,                  "public",   "archived"),
        ("on_expired_round", "EXPIRED",      0, 5,    None,                  "public",   "active"),
    ]

    path_ids: dict[str, int] = {}

    for label, round_key, method_idx, admit_quota, applicable_to, visibility, status in paths_spec:
        round_id = round_ids.get(round_key)
        if not round_id:
            print(f"  ⚠️  Skip {label}: round {round_key} not seeded")
            continue
        method = methods[method_idx]

        existing = (await session.execute(
            select(models.AdmissionPath).where(
                models.AdmissionPath.admission_round_id == round_id,
                models.AdmissionPath.academic_info_id == target_ai.id,
                models.AdmissionPath.admission_method_id == method.id,
            )
        )).scalar_one_or_none()

        if existing:
            path_ids[label] = existing.id
            print(f"  ⏭  {label} exists (id={existing.id}), skip")
            continue

        new_path = models.AdmissionPath(
            academic_info_id=target_ai.id,
            admission_method_id=method.id,
            admission_round_id=round_id,
            admit_quota=admit_quota,
            round_quota=admit_quota * 2 if admit_quota else None,
            applicable_to=applicable_to,
            visibility=visibility,
            status=status,
        )
        session.add(new_path)
        await session.flush()
        path_ids[label] = new_path.id
        print(f"  ✅  {label} created (id={new_path.id}, quota={admit_quota}, "
              f"audience={applicable_to}, vis={visibility}, status={status})")

    await session.commit()
    return path_ids


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — ANNUAL QUOTA TIER 1 SCENARIO  (sketch — implement when needed)
# ═══════════════════════════════════════════════════════════════════════════════

# Group 3 marker — dedicated ProgramOffering offering_type so --reset
# can cascade delete it without touching real data.
G3_OFFERING_TYPE = "smk_g3"


async def seed_group_3_annual_quota(
    session: AsyncSession, round_ids: dict[str, int]
) -> dict[str, int]:
    """Annual academic_info cap anchor for PR-1 Tier 1.

    POST-REVIEW B2 fix (2026-05-28): create DEDICATED ProgramOffering
    (offering_type='smk_g3') + OfferingAcademicInfo with annual_quota=2
    + 2 paths. KHÔNG mutate any existing academic_info row.

    Pre-fix mutated an existing offering's annual_quota → side effect
    persisted past --reset → contaminated unrelated catalog queries.
    Now --reset cascade deletes ProgramOffering → ai → paths fully.

    Strategy:
      1. Get/create ProgramOffering (program=first, offering_type='smk_g3')
      2. Get/create OfferingAcademicInfo (annual_quota=2, is_published)
      3. Create 2 paths on ACTIVE_MULTI round, different methods

    Returns dict labels → ids for downstream Group 4 reference.
    """
    print(f"\n📊 Group 3 — Annual quota Tier 1 anchor (dedicated offering)")

    round_id = round_ids.get("ACTIVE_MULTI")
    if not round_id:
        print(f"   ⚠️  Skip — SMK_ACTIVE_MULTI round missing.")
        return {}

    # Pick first program for FK
    program = (await session.execute(
        select(models.MajorProgram).order_by(models.MajorProgram.id).limit(1)
    )).scalar_one_or_none()
    if not program:
        sys.exit("   ❌ Need ≥1 program. Run seed_sample_data first.")

    # Dedicated G3 offering (UNIQUE program_id + offering_type)
    offering = (await session.execute(
        select(models.ProgramOffering).where(
            models.ProgramOffering.program_id == program.id,
            models.ProgramOffering.offering_type == G3_OFFERING_TYPE,
        )
    )).scalar_one_or_none()
    if not offering:
        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type=G3_OFFERING_TYPE,
            duration_semesters=8,
            is_active=True,
        )
        session.add(offering)
        await session.flush()
        print(f"   ✅  ProgramOffering created (id={offering.id}, type={G3_OFFERING_TYPE})")
    else:
        print(f"   ⏭  ProgramOffering reused (id={offering.id})")

    # Dedicated academic_info with annual_quota=2
    ai = (await session.execute(
        select(models.OfferingAcademicInfo).where(
            models.OfferingAcademicInfo.offering_id == offering.id,
            models.OfferingAcademicInfo.academic_year == ACADEMIC_YEAR,
        )
    )).scalar_one_or_none()
    if not ai:
        ai = models.OfferingAcademicInfo(
            offering_id=offering.id,
            academic_year=ACADEMIC_YEAR,
            annual_admission_quota=2,
            tuition_fee_per_year=Decimal("10000000"),
            is_published=True,
        )
        session.add(ai)
        await session.flush()
        print(f"   ✅  AcademicInfo created (id={ai.id}, annual_quota=2)")
    else:
        print(f"   ⏭  AcademicInfo reused (id={ai.id})")

    # 2 distinct methods → 2 paths under same ai (UNIQUE round+ai+method enforced)
    methods = (await session.execute(
        select(models.AdmissionMethod).where(
            models.AdmissionMethod.is_active.is_(True)
        ).order_by(models.AdmissionMethod.id).limit(2)
    )).scalars().all()
    if len(methods) < 2:
        sys.exit("   ❌ Need ≥2 active admission_methods")

    path_ids: dict[str, int] = {}
    for idx, method in enumerate(methods):
        label = f"capped_path_{idx}"
        existing = (await session.execute(
            select(models.AdmissionPath).where(
                models.AdmissionPath.admission_round_id == round_id,
                models.AdmissionPath.academic_info_id == ai.id,
                models.AdmissionPath.admission_method_id == method.id,
            )
        )).scalar_one_or_none()
        if existing:
            path_ids[label] = existing.id
            print(f"   ⏭  {label} exists (id={existing.id})")
            continue

        path = models.AdmissionPath(
            academic_info_id=ai.id,
            admission_method_id=method.id,
            admission_round_id=round_id,
            admit_quota=10,  # plenty path cap so Tier 1 (annual) is the gate
            round_quota=20,
            visibility="public",
            status="active",
        )
        session.add(path)
        await session.flush()
        path_ids[label] = path.id
        print(f"   ✅  {label} created (id={path.id}, method={method.code})")

    await session.commit()
    return path_ids


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — PROFILE STATE MATRIX  (sketch — uses state_service.transition)
# ═══════════════════════════════════════════════════════════════════════════════

async def seed_group_4_profiles(
    session: AsyncSession,
    round_ids: dict[str, int],
    path_ids: dict[str, int],
) -> dict[str, int]:
    """Profile state matrix via state_service.transition().

    Strategy:
      1. Seed 1 SMOKE_DEV_LEAD (citizen_id unique by index, smoke_marker
         qua applied_rules).
      2. Tạo PathSubjectGroupConfig cho 2 paths trong Group 2 (full_quota_1,
         free_quota_5) — needed for AdmissionProfileChoice FK.
      3. Tạo 5 profiles initial status=draft (INSERT direct + applied_rules
         marker — initial state KHÔNG cần transition).
      4. Transition các profile cần trạng thái khác qua state_service với
         skip_dispatch=True (tránh notification side effect ngoài ý muốn).

    Fixtures (7 total):
      DRAFT_active           — Round ACTIVE_MULTI, choice on free_quota_5
      DRAFT_expired          — Round EXPIRED (cho S8/S9 cutoff CRUD)
      SUBMITTED_pending      — draft → submitted
      ADMITTED_consumer      — full chain → status=admitted + choice
                               .decision=admitted on full_quota_1 (consume seat)
      WAITLISTED_promotable  — chain → waitlisted, choice on full path
      REJECTED               — chain → rejected
      ENROLLED               — chain → enrolled (KPI smoke)
    """
    print(f"\n👤 Group 4 — Profile state matrix")

    from app.services import admission_state_service

    # Pick officer + manager for actor refs
    officer_stmt = select(models.User).where(
        models.User.role == "officer", models.User.status == "active"
    ).limit(1)
    officer = (await session.execute(officer_stmt)).scalar_one_or_none()
    manager_stmt = select(models.User).where(
        models.User.role == "manager", models.User.status == "active"
    ).limit(1)
    manager = (await session.execute(manager_stmt)).scalar_one_or_none()
    if not (officer and manager):
        sys.exit("   ❌ Need ≥1 active officer + 1 active manager user")

    # Pipeline stage — use first available
    pipeline_stmt = select(models.PipelineStage).order_by(models.PipelineStage.id).limit(1)
    pipeline_stage = (await session.execute(pipeline_stmt)).scalar_one_or_none()
    if not pipeline_stage:
        sys.exit("   ❌ Need ≥1 pipeline_stage row. Run seed_categories first.")

    # Seed N leads — 1 per profile (UNIQUE(lead_id, academic_year) constraint).
    # Idempotent by deterministic phone "0900000xxx".
    async def get_or_create_lead(idx: int) -> models.Lead:
        phone = f"09000{idx:05d}"
        existing = (await session.execute(
            select(models.Lead).where(models.Lead.phone == phone)
        )).scalar_one_or_none()
        if existing:
            return existing
        new_lead = models.Lead(
            full_name=f"SMOKE DEV Candidate {idx}",
            phone=phone,
            unit_id=officer.unit_id,
            pipeline_stage_id=pipeline_stage.id,
            source="walkin",
            assigned_officer_id=officer.id,
        )
        session.add(new_lead)
        await session.flush()
        return new_lead

    # PathSubjectGroupConfig for paths that will host choices
    sg_stmt = select(models.SubjectGroup).order_by(models.SubjectGroup.id).limit(1)
    sg = (await session.execute(sg_stmt)).scalar_one()
    config_ids: dict[str, int] = {}
    for label in ("full_quota_1", "free_quota_5"):
        path_id = path_ids.get(label)
        if not path_id:
            continue
        existing = (await session.execute(
            select(models.PathSubjectGroupConfig).where(
                models.PathSubjectGroupConfig.admission_path_id == path_id,
                models.PathSubjectGroupConfig.subject_group_id == sg.id,
            )
        )).scalar_one_or_none()
        if existing:
            config_ids[label] = existing.id
            continue
        cfg = models.PathSubjectGroupConfig(
            admission_path_id=path_id,
            subject_group_id=sg.id,
            min_score=Decimal("0.00"),
        )
        session.add(cfg)
        await session.flush()
        config_ids[label] = cfg.id

    await session.commit()
    print(f"   ✅  PathSubjectGroupConfig seeded for {list(config_ids.keys())}")

    # Profile spec — label, target_status, round_key, path_label, choice_decision
    profiles_spec = [
        ("DRAFT_active",          "draft",      "ACTIVE_MULTI", "free_quota_5", None),
        ("DRAFT_expired",         "draft",      "EXPIRED",      "on_expired_round", None),
        ("SUBMITTED_pending",     "submitted",  "ACTIVE_MULTI", "free_quota_5", None),
        ("ADMITTED_consumer",     "admitted",   "ACTIVE_MULTI", "full_quota_1", "admitted"),
        ("WAITLISTED_promotable", "waitlisted", "ACTIVE_MULTI", "full_quota_1", "waitlisted"),
        ("REJECTED",              "rejected",   "ACTIVE_MULTI", "free_quota_5", "rejected"),
        ("ENROLLED",              "enrolled",   "ACTIVE_MULTI", "free_quota_5", None),
    ]

    # Transition chains per target. Each entry là sequence từ 'draft' tới target.
    # Note: state machine ALLOWED_TRANSITIONS dictates each hop.
    chains = {
        "draft":      ["draft"],
        "submitted":  ["draft", "submitted"],
        "admitted":   ["draft", "submitted", "reviewing", "result_published", "admitted"],
        "waitlisted": ["draft", "submitted", "reviewing", "result_published", "waitlisted"],
        "rejected":   ["draft", "submitted", "reviewing", "result_published", "rejected"],
        "enrolled":   ["draft", "submitted", "reviewing", "result_published",
                       "admitted", "confirmed", "enrolled"],
    }

    profile_ids: dict[str, int] = {}

    for label, target, round_key, path_label, choice_decision in profiles_spec:
        round_id = round_ids.get(round_key)
        path_id = path_ids.get(path_label)
        if not (round_id and path_id):
            print(f"   ⚠️  Skip {label}: missing round/path FK")
            continue

        # Deterministic citizen_id by profile index
        idx = len(profile_ids) + 1
        citizen = f"{CITIZEN_ID_PREFIX}{idx:04d}"

        existing = (await session.execute(
            select(models.AdmissionProfile).where(
                models.AdmissionProfile.citizen_id == citizen
            )
        )).scalar_one_or_none()
        if existing:
            profile_ids[label] = existing.id
            print(f"   ⏭  {label} exists (id={existing.id}, citizen={citizen})")
            continue

        # Get/create dedicated lead for this profile (UNIQUE constraint)
        lead_for_profile = await get_or_create_lead(idx)

        # INSERT initial draft directly (no transition needed for start state)
        profile = models.AdmissionProfile(
            lead_id=lead_for_profile.id,
            citizen_id=citizen,
            academic_year=ACADEMIC_YEAR,
            status="draft",
            applied_rules={
                PROFILE_MARKER_KEY: PROFILE_MARKER_VALUE,
                "admission_path_id": path_id,
            },
            uses_choice_engine=(round_key == "ACTIVE_MULTI"),
        )
        session.add(profile)
        await session.flush()

        # Choice (cho profiles in multi-NV round)
        config_id = config_ids.get(path_label)
        if config_id and choice_decision is not None:
            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path_id,
                path_subject_group_config_id=config_id,
                display_order=1,
                decision=choice_decision,
            )
            session.add(choice)
            await session.flush()
        elif config_id and target != "draft":
            # Need choice in pending state for multi-NV profile that will
            # transit beyond draft
            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path_id,
                path_subject_group_config_id=config_id,
                display_order=1,
                decision="pending",
            )
            session.add(choice)
            await session.flush()

        await session.commit()

        # Transition chain (skip if target=='draft' — already there)
        if target != "draft":
            chain = chains.get(target, ["draft"])
            for new_status in chain[1:]:  # skip first since profile starts at draft
                try:
                    await admission_state_service.transition(
                        session, profile, new_status,
                        actor=manager,  # use manager for both reviewing + final ops
                        reason=f"smoke seed → {new_status}",
                        source="seed_smoke_dev",
                        skip_dispatch=True,  # don't fire notifications during seed
                    )
                    await session.commit()
                except Exception as e:
                    print(f"   ⚠️  {label} transition → {new_status} failed: {e}")
                    await session.rollback()
                    break

        profile_ids[label] = profile.id
        final_status = profile.status if profile.status else target
        print(f"   ✅  {label} (id={profile.id}, citizen={citizen}, status={final_status})")

    return profile_ids


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — MAGIC-LINK TOKEN FIXTURE  (sketch)
# ═══════════════════════════════════════════════════════════════════════════════

async def seed_group_5_tokens(
    session: AsyncSession, profile_ids: dict[str, int]
) -> dict[str, int]:
    """AdmissionConfirmationToken matrix — 6 token fixtures.

    Reuse Group 4 profiles. Token determinism via fixed string per fixture
    (avoids regen on re-seed). Each token represents a magic-link state:

      SUBMIT_active        — DRAFT_active, action=submit, fresh expiry
      CONFIRM_active       — ADMITTED_consumer, action=confirm
      RESUBMIT_active      — REJECTED, action=resubmit
      EXPIRED              — DRAFT_active, action=submit, expires_at < now
      CONSUMED             — SUBMITTED_pending, confirmed_at = now
      HARD_LOCKED          — DRAFT_active, attempt_count=10 + lock_until future
    """
    import secrets
    print(f"\n🔗 Group 5 — Magic-link tokens")

    if not profile_ids:
        print(f"   ⚠️  Skip — Group 4 profile_ids empty.")
        return {}

    now = datetime.now(timezone.utc)
    in_7d = now + timedelta(days=7)
    past_1d = now - timedelta(days=1)
    in_24h = now + timedelta(hours=24)

    # spec: label, profile_key, action_type, expires_at, confirmed_at,
    #       attempt_count, lock_until, lock_count.
    # UNIQUE(profile_id, action_type) enforced — spread across profiles.
    tokens_spec = [
        ("SUBMIT_active",   "DRAFT_active",          "submit",   in_7d,   None, 0, None,    0),
        ("CONFIRM_active",  "ADMITTED_consumer",     "confirm",  in_7d,   None, 0, None,    0),
        ("RESUBMIT_active", "REJECTED",              "resubmit", in_7d,   None, 0, None,    0),
        ("EXPIRED",         "DRAFT_expired",         "submit",   past_1d, None, 0, None,    0),
        ("CONSUMED",        "SUBMITTED_pending",     "confirm",  in_7d,   now,  1, None,    0),
        ("HARD_LOCKED",     "WAITLISTED_promotable", "submit",   in_7d,   None,10, in_24h,  4),
    ]

    token_ids: dict[str, int] = {}
    for label, profile_key, action, expires_at, confirmed_at, attempts, lock_until, lock_count in tokens_spec:
        profile_id = profile_ids.get(profile_key)
        if not profile_id:
            print(f"   ⚠️  Skip {label}: profile {profile_key} not seeded")
            continue

        # Deterministic token by label (idempotent re-seed)
        token_str = f"smk_dev_{label.lower()}_{profile_id:06d}"[:64]

        existing = (await session.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == token_str
            )
        )).scalar_one_or_none()
        if existing:
            token_ids[label] = existing.id
            print(f"   ⏭  {label} exists (id={existing.id})")
            continue

        token = models.AdmissionConfirmationToken(
            profile_id=profile_id,
            token=token_str,
            action_type=action,
            expires_at=expires_at,
            confirmed_at=confirmed_at,
            attempt_count=attempts,
            lock_until=lock_until,
            lock_count=lock_count,
            locked_at=now if attempts >= 5 else None,
        )
        session.add(token)
        await session.flush()
        token_ids[label] = token.id
        print(f"   ✅  {label} (id={token.id}, action={action}, attempts={attempts})")

    await session.commit()
    return token_ids


# ═══════════════════════════════════════════════════════════════════════════════
# RESET — cascade delete SMOKE_DEV_* markers
# ═══════════════════════════════════════════════════════════════════════════════

async def reset(session: AsyncSession) -> None:
    """Cascade delete all SMOKE_DEV_* fixtures.

    Order matters due to FK constraints:
      1. AdmissionConfirmationToken (depends on profile)
      2. AdmissionProfileChoice (depends on profile + path)
      3. AdmissionProfile (smoke_marker)
      4. AdmissionPath (depends on round)
      5. OfferingAdmissionRound (top-level marker)
    """
    print(f"\n🗑  RESET — cascade delete SMOKE_DEV_* fixtures")

    # Profiles by marker
    profile_count = await session.execute(text(
        "DELETE FROM admission_confirmation_token "
        "WHERE profile_id IN (SELECT id FROM admission_profile "
        f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}') "
        "RETURNING profile_id"
    ))
    print(f"  Tokens deleted: {profile_count.rowcount}")

    choices = await session.execute(text(
        "DELETE FROM admission_profile_choice "
        "WHERE admission_profile_id IN (SELECT id FROM admission_profile "
        f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}') "
        "RETURNING id"
    ))
    print(f"  Choices deleted: {choices.rowcount}")

    profiles = await session.execute(text(
        f"DELETE FROM admission_profile "
        f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}' RETURNING id"
    ))
    print(f"  Profiles deleted: {profiles.rowcount}")

    # Paths under SMOKE_DEV_* rounds
    paths = await session.execute(text(
        "DELETE FROM admission_path "
        "WHERE admission_round_id IN (SELECT id FROM offering_admission_round "
        f"WHERE round_code LIKE '{ROUND_PREFIX}%%') RETURNING id"
    ))
    print(f"  Paths deleted: {paths.rowcount}")

    # Rounds themselves
    rounds = await session.execute(text(
        f"DELETE FROM offering_admission_round "
        f"WHERE round_code LIKE '{ROUND_PREFIX}%%' RETURNING id"
    ))
    print(f"  Rounds deleted: {rounds.rowcount}")

    # Group 3 dedicated offering — cascade deletes ai + any orphan paths.
    # Order AFTER round delete vì Group 2 paths on smoke rounds đã sạch.
    g3_offering = await session.execute(text(
        f"DELETE FROM program_offering "
        f"WHERE offering_type = '{G3_OFFERING_TYPE}' RETURNING id"
    ))
    print(f"  G3 ProgramOffering deleted: {g3_offering.rowcount}")

    await session.commit()
    print(f"✅ Reset complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# VERIFY — row count report
# ═══════════════════════════════════════════════════════════════════════════════

async def verify(session: AsyncSession) -> None:
    """Print row count per fixture marker + key state distributions."""
    print(f"\n📋 VERIFY — Smoke fixture row counts")

    queries = [
        ("SMOKE_DEV rounds",
         f"SELECT COUNT(*) FROM offering_admission_round WHERE round_code LIKE '{ROUND_PREFIX}%%'"),
        ("SMOKE_DEV paths",
         f"SELECT COUNT(*) FROM admission_path WHERE admission_round_id IN "
         f"(SELECT id FROM offering_admission_round WHERE round_code LIKE '{ROUND_PREFIX}%%')"),
        ("SMOKE_DEV profiles",
         f"SELECT COUNT(*) FROM admission_profile "
         f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}'"),
        ("SMOKE_DEV choices",
         f"SELECT COUNT(*) FROM admission_profile_choice "
         f"WHERE admission_profile_id IN (SELECT id FROM admission_profile "
         f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}')"),
        ("SMOKE_DEV tokens",
         f"SELECT COUNT(*) FROM admission_confirmation_token "
         f"WHERE profile_id IN (SELECT id FROM admission_profile "
         f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}')"),
        ("G3 dedicated offering",
         f"SELECT COUNT(*) FROM program_offering WHERE offering_type = '{G3_OFFERING_TYPE}'"),
        ("G3 dedicated academic_info",
         f"SELECT COUNT(*) FROM offering_academic_info ai "
         f"JOIN program_offering po ON po.id = ai.offering_id "
         f"WHERE po.offering_type = '{G3_OFFERING_TYPE}'"),
    ]

    for label, sql in queries:
        result = await session.execute(text(sql))
        count = result.scalar_one()
        print(f"  {label:30s} {count:>5}")

    # Round detail
    print(f"\n  Round detail:")
    rounds_detail = await session.execute(text(
        f"SELECT id, round_code, start_date, end_date, allow_multi_nv, "
        f"archived_at IS NOT NULL AS archived "
        f"FROM offering_admission_round WHERE round_code LIKE '{ROUND_PREFIX}%%' ORDER BY id"
    ))
    for row in rounds_detail:
        print(f"    id={row.id} {row.round_code:30s} window=[{row.start_date}..{row.end_date}] "
              f"multi_nv={row.allow_multi_nv} archived={row.archived}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group", nargs="*", type=int, choices=[1, 2, 3, 4, 5],
        help="Seed specific group(s). Default: all groups."
    )
    parser.add_argument("--reset", action="store_true",
                        help="Cascade delete SMOKE_DEV_* fixtures. Mutually exclusive với seed.")
    parser.add_argument("--verify", action="store_true",
                        help="Print row count report. Read-only.")
    args = parser.parse_args()

    assert_safe_environment()

    async with AsyncSessionLocal() as session:
        if args.reset:
            await reset(session)
            return
        if args.verify:
            await verify(session)
            return

        groups_to_seed = args.group or [1, 2, 3, 4, 5]
        round_ids: dict[str, int] = {}
        path_ids: dict[str, int] = {}
        profile_ids: dict[str, int] = {}

        # Ensure dependencies exist when running later groups standalone.
        if any(g in groups_to_seed for g in [2, 3, 4]):
            if not round_ids:
                round_ids = await _lookup_existing_rounds(session)
        if any(g in groups_to_seed for g in [4, 5]):
            if not path_ids:
                path_ids = await _lookup_existing_paths(session, round_ids)

        if 1 in groups_to_seed:
            round_ids = await seed_group_1_rounds(session)
        if 2 in groups_to_seed:
            path_ids = await seed_group_2_paths(session, round_ids)
        if 3 in groups_to_seed:
            await seed_group_3_annual_quota(session, round_ids)
        if 4 in groups_to_seed:
            profile_ids = await seed_group_4_profiles(session, round_ids, path_ids)
        if 5 in groups_to_seed:
            if not profile_ids:
                profile_ids = await _lookup_existing_profiles(session)
            await seed_group_5_tokens(session, profile_ids)

        print(f"\n✅ Seed complete. Run `--verify` để xem row counts.")


async def _lookup_existing_rounds(session: AsyncSession) -> dict[str, int]:
    """Lookup existing SMK_* rounds when later group needs round_ids
    but Group 1 was skipped (rerun pattern)."""
    result = await session.execute(
        select(models.OfferingAdmissionRound.id, models.OfferingAdmissionRound.round_code)
        .where(models.OfferingAdmissionRound.round_code.like(f"{ROUND_PREFIX}%"))
    )
    return {
        row.round_code.replace(ROUND_PREFIX, ""): row.id
        for row in result
    }


async def _lookup_existing_paths(
    session: AsyncSession, round_ids: dict[str, int]
) -> dict[str, int]:
    """Reverse-map paths to Group 2 labels by (round_id, method_idx).

    Inferred labels from path spec table — fragile, but adequate for
    standalone rerun. If schema spec changes, this lookup needs update.
    """
    if not round_ids:
        return {}

    # Same spec ordering as Group 2 seed
    paths_label_spec = [
        ("full_quota_1",     "ACTIVE_MULTI",  0),
        ("free_quota_5",     "ACTIVE_MULTI",  1),
        ("unbounded_null",   "ACTIVE_MULTI",  2),
        ("audience_thpt",    "ACTIVE_SINGLE", 0),
        ("audience_vlvh",    "ACTIVE_SINGLE", 1),
        ("audience_null",    "ACTIVE_SINGLE", 2),
        ("internal_hidden",  "OPEN_ENDED",    0),
        ("archived_path",    "OPEN_ENDED",    1),
        ("on_expired_round", "EXPIRED",       0),
    ]
    methods = (await session.execute(
        select(models.AdmissionMethod).where(models.AdmissionMethod.is_active.is_(True))
        .order_by(models.AdmissionMethod.id).limit(5)
    )).scalars().all()

    path_ids: dict[str, int] = {}
    for label, round_key, method_idx in paths_label_spec:
        round_id = round_ids.get(round_key)
        if not (round_id and method_idx < len(methods)):
            continue
        method = methods[method_idx]
        result = await session.execute(
            select(models.AdmissionPath.id).where(
                models.AdmissionPath.admission_round_id == round_id,
                models.AdmissionPath.admission_method_id == method.id,
            ).order_by(models.AdmissionPath.id).limit(1)
        )
        pid = result.scalar_one_or_none()
        if pid:
            path_ids[label] = pid
    return path_ids


async def _lookup_existing_profiles(session: AsyncSession) -> dict[str, int]:
    """Lookup profiles by smoke marker for Group 5 standalone rerun."""
    result = await session.execute(text(
        f"SELECT id, citizen_id FROM admission_profile "
        f"WHERE applied_rules->>'{PROFILE_MARKER_KEY}' = '{PROFILE_MARKER_VALUE}' "
        f"ORDER BY id"
    ))
    # Map by citizen_id suffix order (matches Group 4 enumeration)
    labels_by_index = [
        "DRAFT_active", "DRAFT_expired", "SUBMITTED_pending",
        "ADMITTED_consumer", "WAITLISTED_promotable", "REJECTED", "ENROLLED",
    ]
    profile_ids: dict[str, int] = {}
    rows = list(result)
    for idx, row in enumerate(rows):
        if idx < len(labels_by_index):
            profile_ids[labels_by_index[idx]] = row.id
    return profile_ids


if __name__ == "__main__":
    asyncio.run(main())
