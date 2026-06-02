# tests/fixtures/builders.py
"""
Track T: Seed data builders for test fixtures.

Replaces hard-coded seed_lead_dependencies / seeded_dependencies fixtures
across 4 conftest files. Uses dynamic ID allocation via counter.
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Dynamic ID counter to avoid hard-coded IDs and cross-test collisions
_id_counter = 10000


def _next_id() -> int:
    """Generate a unique ID for test data."""
    global _id_counter
    _id_counter += 1
    return _id_counter


def reset_id_counter(start: int = 10000):
    """Reset ID counter (call between test sessions if needed)."""
    global _id_counter
    _id_counter = start


# ---------------------------------------------------------------------------
# Gap #3 submit gate (KV PR) — permanent address + current-era ward.
# ``submit_and_evaluate`` now requires full_name + phone + permanent_province +
# permanent_ward AND ``permanent_commune_code`` to be a CURRENT-era WARD
# (administrative_nodes valid_to IS NULL). Any test that submits a profile for
# SUCCESS must (1) seed this ward via ``ensure_submittable_ward()`` and (2) fill
# ``**SUBMITTABLE_PERMANENT_ADDRESS`` in the profile update payload.
# ---------------------------------------------------------------------------
SUBMITTABLE_WARD_CODE = "99TESTKV"
SUBMITTABLE_PERMANENT_ADDRESS = {
    "permanent_province": "Tỉnh Test KV",
    "permanent_ward": "Phường Test KV",
    "permanent_commune_code": SUBMITTABLE_WARD_CODE,
}


async def ensure_submittable_ward() -> str:
    """Idempotently seed one CURRENT-era WARD node so the Gap #3 submit gate
    (`_is_current_era_ward`) accepts ``SUBMITTABLE_PERMANENT_ADDRESS``.

    Returns the ward code. Safe to call repeatedly (per-test) — re-running on an
    already-seeded DB is a no-op.
    """
    from datetime import date

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.administrative_node import (
        AdministrativeLevel,
        AdministrativeNode,
    )

    async with AsyncSessionLocal() as s:
        exists = (
            await s.execute(
                select(AdministrativeNode.id)
                .where(
                    AdministrativeNode.code == SUBMITTABLE_WARD_CODE,
                    AdministrativeNode.level == AdministrativeLevel.WARD,
                    AdministrativeNode.valid_to.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            s.add(
                AdministrativeNode(
                    code=SUBMITTABLE_WARD_CODE,
                    name="Phường Test KV",
                    level=AdministrativeLevel.WARD,
                    path=f"99/{SUBMITTABLE_WARD_CODE}",
                    province_code="99",
                    ward_code=SUBMITTABLE_WARD_CODE,
                    valid_from=date(2025, 7, 1),
                    valid_to=None,
                    is_active=True,
                )
            )
            await s.commit()
    return SUBMITTABLE_WARD_CODE


async def seed_submittable_offering_config(
    session, unit_id: int, academic_year: int = 2026
) -> dict:
    """Seed the full legacy single-NV submit chain (#337) and return its ids.

    ``unit_id`` is the owning OrganizationUnit for the MajorProgram (NOT NULL
    FK) — pass the lead's unit so the chain stays scope-consistent.
    ``academic_year`` flows into ``OfferingAcademicInfo`` and is echoed back in
    the result so the caller's profile honors the SAME year — avoids a silent
    mismatch against the UNIQUE(lead_id/citizen_id, academic_year) constraints.

    ``submit_and_evaluate``'s legacy path (``uses_choice_engine=False``)
    derives the target level from ``offering_admission_config_id`` →
    academic_info → offering → ``MajorProgram.degree_level_id`` +
    ``ProgramOffering.offering_type_id``, then resolves the applicant's KV
    from the academic_history THPT entry → ``VnSchool`` →
    ``VnSchoolKvAssignment``. Without both, submit fail-closes with
    ``CONFIG_GAP_TARGET_LEVEL`` / ``KV_UNRESOLVED`` (the #337 test-debt).

    Mirrors ``tests/api/test_magic_link_3_actions_wire.py::_seed`` — the
    proven recipe shipped with the 2026-05-29 magic-link #337 fix.
    ``ConfigOfferingType``/``ConfigDegreeLevel`` are get-or-created (shared
    UNIQUE codes); everything else uses a per-call suffix to avoid
    cross-test collisions. The caller owns the session/transaction; this
    helper flushes but does not commit.

    Returns ``{offering_admission_config_id, school_id, academic_year,
    major_program_id}``. Pair with ``ensure_submittable_ward()`` +
    ``SUBMITTABLE_PERMANENT_ADDRESS`` + a ``graduated_thpt`` cultural level
    on the profile for a fully submittable hồ sơ.
    """
    from sqlalchemy import select

    from app import models

    suffix = _next_id()

    offering_type = (
        await session.execute(
            select(models.ConfigOfferingType).where(
                models.ConfigOfferingType.code == "chinh_quy"
            )
        )
    ).scalar_one_or_none()
    if offering_type is None:
        offering_type = models.ConfigOfferingType(
            code="chinh_quy", name="Chính quy", is_active=True,
        )
        session.add(offering_type)
        await session.flush()

    degree_level = (
        await session.execute(
            select(models.ConfigDegreeLevel).where(
                models.ConfigDegreeLevel.code == "cao_dang"
            )
        )
    ).scalar_one_or_none()
    if degree_level is None:
        degree_level = models.ConfigDegreeLevel(
            code="cao_dang", name="Cao đẳng", display_order=2, is_active=True,
        )
        session.add(degree_level)
        await session.flush()

    # MajorProgram.degree_level_id (FK) is what derive_target_level_and_type
    # reads; the legacy ``degree_level`` text column is still NOT NULL so it
    # must be populated in parallel.
    # Explicit id via the shared _next_id() counter — SeedDependenciesBuilder
    # also inserts MajorProgram with explicit ids, leaving the SERIAL
    # sequence behind, so an auto-id insert here would collide on the pkey.
    major = models.MajorProgram(
        id=suffix,
        name=f"Submittable Major {suffix}",
        code=f"SM{suffix}",
        degree_level="Cao đẳng",
        degree_level_id=degree_level.id,
        unit_id=unit_id,
    )
    session.add(major)
    await session.flush()

    offering = models.ProgramOffering(
        offering_type=f"sm_{suffix}",
        program_id=major.id,
        offering_type_id=offering_type.id,
    )
    session.add(offering)
    await session.flush()

    academic_info = models.OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=academic_year,
        is_published=True,
    )
    session.add(academic_info)
    await session.flush()

    method = models.AdmissionMethod(
        code=f"sm_method_{suffix}", name="Submittable method", is_active=True,
    )
    session.add(method)
    await session.flush()

    criteria = models.AdmissionCriteria(
        method_id=method.id,
        code=f"sm_crit_{suffix}",
        name="Submittable criteria",
        min_gpa=0,
        is_active=True,
    )
    session.add(criteria)
    await session.flush()

    config = models.OfferingAdmissionConfig(
        academic_info_id=academic_info.id,
        criteria_id=criteria.id,
        is_active=True,
    )
    session.add(config)
    await session.flush()

    # KV layer: a THPT school + KV3 assignment covering graduation years
    # 2020-2024 so the academic_history THPT entry resolves to a KV.
    school = models.VnSchool(
        moet_school_code=f"S{suffix}",
        moet_province_code="001",
        name=f"THPT Submittable {suffix}",
        province="Hà Nội",
        district="Ba Đình",
        level="THPT",
    )
    session.add(school)
    await session.flush()
    session.add(
        models.VnSchoolKvAssignment(
            school_id=school.id,
            kv_code="KV3",
            effective_from_year=2020,
            effective_to_year=2024,
            source="manual_admin",
        )
    )
    await session.flush()

    return {
        "offering_admission_config_id": config.id,
        "school_id": school.id,
        "academic_year": academic_year,
        "major_program_id": major.id,
    }


def submittable_profile_fields(seed: dict) -> dict:
    """Profile column kwargs that clear every ``submit_and_evaluate`` gate,
    given a seed from ``seed_submittable_offering_config()``.

    Covers (#337): the legacy target-level config, a KV-resolvable THPT
    ``academic_history`` entry, ``graduated_thpt`` cultural eligibility, and
    the Gap #3 permanent address. The caller must ALSO
    ``await ensure_submittable_ward()`` once before creating the profile.
    """
    return {
        "offering_admission_config_id": seed["offering_admission_config_id"],
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
        "uses_choice_engine": False,
        "full_name": "Submittable Candidate",
        "phone": "0901234567",
        **SUBMITTABLE_PERMANENT_ADDRESS,
        "academic_history": [
            {
                "school_name": "THPT Submittable",
                "year_from": 2020,
                "year_to": 2024,
                "gpa": 8.0,
                "graduation_type": "THPT",
                "level": "THPT",
                "grade_to": 12,
                "school_id": seed["school_id"],
            }
        ],
    }


class SeedDependenciesBuilder:
    """
    Builder for seeding unit/stage/status dependencies.

    Usage:
        builder = SeedDependenciesBuilder()
        result = await builder.build(session, models, settings)
        # result = {"unit_id": ..., "major_program_id": ..., ...}
    """

    def __init__(
        self,
        unit_id: Optional[int] = None,
        unit_name: str = "Test Unit",
        include_admission_pipeline: bool = True,
    ):
        self.unit_id = unit_id or _next_id()
        self.unit_name = unit_name
        self.include_admission_pipeline = include_admission_pipeline

    async def build(self, session, models, settings=None) -> dict:
        """
        Seed dependencies and return result dict.

        Args:
            session: active async session (inside begin() context)
            models: app.models module
            settings: kept for backwards-compatible signature, unused —
                Wave 5 replaced the `settings.DEFAULT_*_LEAD_STATUS*`
                reads with literal shadow constants in
                `tests/_lead_status_test_ids`.

        Returns:
            dict with unit_id, major_program_id, initial_status_id, etc.
        """
        from tests._lead_status_test_ids import (
            INITIAL_LEAD_STATUS_ID,
            LOST_LEAD_STATUS_ID,
        )
        major_id = _next_id()
        stage_a_id = f"STG_{self.unit_id}_A"
        stage_lost_id = f"STG_{self.unit_id}_LOST"
        initial_status_id = INITIAL_LEAD_STATUS_ID
        lost_status_id = LOST_LEAD_STATUS_ID
        status_a1_id = f"STS_{self.unit_id}_A1"

        # Core entities
        unit = models.OrganizationUnit(
            id=self.unit_id, name=self.unit_name, code=f"U{self.unit_id}",
        )
        major = models.MajorProgram(id=major_id, name="Test Major", code=f"M{major_id}")
        stage_a = models.PipelineStage(id=stage_a_id, name="Initial Stage", order=10)
        stage_lost = models.PipelineStage(id=stage_lost_id, name="Lost Stage", order=999)

        initial_status = models.ConsultationStatus(
            id=initial_status_id, name="New Lead", color_code="#0000FF", stage_id=stage_a_id,
        )
        status_a1 = models.ConsultationStatus(
            id=status_a1_id, name="Status A1", color_code="#00FF00", stage_id=stage_a_id,
        )
        lost_status = models.ConsultationStatus(
            id=lost_status_id, name="Lost", color_code="#FF0000", stage_id=stage_lost_id,
        )

        session.add_all([unit, major, stage_a, stage_lost, initial_status, status_a1, lost_status])
        await session.flush()

        # Admission pipeline (optional)
        if self.include_admission_pipeline:
            admission_stages = [
                models.PipelineStage(id=f"stg0{i}", name=name, order=1000 + i, is_final_stage=(i >= 6))
                for i, name in enumerate([
                    "Chua tu van", "Dang tu van", "Da nop ho so",
                    "Ket qua ho so", "Xu ly hoc phi", "Da nhap hoc", "Khong di hoc",
                ], start=1)
            ]
            session.add_all(admission_stages)
            await session.flush()

            admission_statuses_data = [
                ("sts00", "Chua lien he", "#999999", "stg01"),
                ("sts05", "Hen lien he lai", "#FFA500", "stg02"),
                ("sts06", "Dong y tu van", "#00FF00", "stg02"),
                ("sts07", "Da nop ho so", "#0088FF", "stg03"),
                ("sts09", "Du dieu kien", "#00CC00", "stg04"),
                ("sts10", "Hoan tat hoc phi", "#008800", "stg05"),
                ("sts11", "Da nhap hoc", "#006600", "stg06"),
                ("sts12", "Khong di hoc", "#CC0000", "stg07"),
                ("sts13", "Dang xu ly", "#FFCC00", "stg03"),
                ("sts14", "Xac nhan nhap hoc", "#009900", "stg05"),
                ("sts16", "Ho so khong dat", "#FF0000", "stg04"),
                ("sts17", "Yeu cau bo sung", "#FF8800", "stg03"),
                ("sts18", "Da hoan hoc phi", "#008888", "stg05"),
            ]
            admission_statuses = [
                models.ConsultationStatus(id=sid, name=name, color_code=color, stage_id=stage)
                for sid, name, color, stage in admission_statuses_data
            ]
            session.add_all(admission_statuses)

        log.info(f"Seeded dependencies: unit_id={self.unit_id}, major_id={major_id}")

        return {
            "unit_id": self.unit_id,
            "major_program_id": major_id,
            "initial_status_id": initial_status_id,
            "status_a1_id": status_a1_id,
            "stage_id": stage_a_id,
        }


# =============================================================================
# Phase 2 v8.2 PR-2A v2 — AdmissionRoundBuilder year-level (Q1 Option A)
# =============================================================================


class AdmissionRoundBuilder:
    """Builder for OfferingAdmissionRound test fixtures (year-level).

    Q1 v8.2: round = 1 row globally per (academic_year, round_code), NOT
    per academic_info (v6 archived).

    Defaults: round_code='DOT_1', academic_year=2026, dates NULL,
    is_active=True. No quota fields (moved to admission_path PR-2B v2).

    Usage::

        round_payload = AdmissionRoundBuilder.make(academic_year=2026)
        round_obj = models.OfferingAdmissionRound(**round_payload)
        session.add(round_obj)
    """

    @staticmethod
    async def get_or_create_default_round(
        session,
        academic_year: int = 2026,
        round_code: str = "DOT_1",
    ) -> int:
        """Idempotent helper for test fixtures (Phase 2 v8.2 PR-2C v2 prep).

        Returns OfferingAdmissionRound.id for given (academic_year,
        round_code). Creates row if not exists. Centralizes round seeding
        so test fixtures don't duplicate boilerplate per file.

        Usage::

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=ai.academic_year
            )
            ap = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,  # required post PR-2C v2
                ...
            )
        """
        from app import models  # noqa: F401 — avoid circular at module import
        from sqlalchemy import select

        result = await session.execute(
            select(models.OfferingAdmissionRound).where(
                models.OfferingAdmissionRound.academic_year == academic_year,
                models.OfferingAdmissionRound.round_code == round_code,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            payload = AdmissionRoundBuilder.make(
                academic_year=academic_year, round_code=round_code
            )
            obj = models.OfferingAdmissionRound(**payload)
            session.add(obj)
            await session.flush()
        return obj.id

    @staticmethod
    def make(
        academic_year: int = 2026,
        round_code: str = "DOT_1",
        **overrides,
    ) -> dict:
        # Extract round number from code for display name (DOT_1 → "Đợt 1")
        suffix = (
            round_code.replace("DOT_", "")
            if round_code.startswith("DOT_")
            else round_code
        )
        defaults = {
            "academic_year": academic_year,
            "round_code": round_code,
            "round_name": f"Đợt {suffix} - {academic_year}",
            "start_date": None,
            "end_date": None,
            "is_active": True,
            "archived_at": None,
            "extended_at": None,
            "extended_by_user_id": None,
            "extension_reason": None,
        }
        defaults.update(overrides)
        return defaults
