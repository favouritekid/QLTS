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
