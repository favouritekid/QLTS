# app/services/priority_config_service.py
"""Service layer for admin priority_area_config + priority_object_config CRUD.

Domain logic (V3.0 contract):
* Pure Python (no FastAPI imports — raises DomainExceptions).
* Returns ``(result, post_commit_callback)`` tuples.
* Clone-from-year + seed-defaults helpers for admin bootstrapping.

Seed defaults follow TT 05/2021/TT-BLĐTBXH Phụ lục 01:
  KV1 = 0.75, KV2-NT = 0.50, KV2 = 0.25, KV3 = 0.00
  UT1 group: 01..04 = 2.00; UT2 group: 05..07 = 1.00
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.priority_config import PriorityAreaConfig, PriorityObjectConfig
from app.repositories.priority_config_repository import PriorityConfigRepository
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)


PostCommitCallback = Optional[Callable[[], Awaitable[None]]]


async def _noop_callback() -> None:
    return None


# Default seed rates from TT 05/2021/TT-BLĐTBXH Phụ lục 01.
# Keys are stable across years — admin may override per quy chế trường
# via subsequent PATCH or new TT.
TT_05_2021_AREA_DEFAULTS: list[dict[str, Any]] = [
    {"area_code": "KV1", "area_name": "Khu vực 1", "bonus_points": Decimal("0.75")},
    {"area_code": "KV2-NT", "area_name": "Khu vực 2 nông thôn", "bonus_points": Decimal("0.50")},
    {"area_code": "KV2", "area_name": "Khu vực 2", "bonus_points": Decimal("0.25")},
    {"area_code": "KV3", "area_name": "Khu vực 3", "bonus_points": Decimal("0.00")},
]

TT_05_2021_OBJECT_DEFAULTS: list[dict[str, Any]] = [
    # UT1 group (2.00đ) — đối tượng 01..04 per Phụ lục 01
    {
        "group_code": "UT1", "sub_code": "01",
        "description": "Công dân Việt Nam dân tộc thiểu số có hộ khẩu KV1",
        "bonus_points": Decimal("2.00"),
        "evidence_doc_type": "Giấy chứng nhận dân tộc + sổ hộ khẩu KV1",
    },
    {
        "group_code": "UT1", "sub_code": "02",
        "description": "Người lao động làm việc liên tục ≥5 năm, có ≥2 năm là chiến sĩ thi đua cấp tỉnh+",
        "bonus_points": Decimal("2.00"),
        "evidence_doc_type": "Quyết định khen thưởng + xác nhận đơn vị",
    },
    {
        "group_code": "UT1", "sub_code": "03",
        "description": "Thương binh, bệnh binh, quân nhân/công an phục vụ ≥12 tháng ở KV1 hoặc ≥18 tháng",
        "bonus_points": Decimal("2.00"),
        "evidence_doc_type": "Quyết định phục vụ + giấy xác nhận thương/bệnh binh",
    },
    {
        "group_code": "UT1", "sub_code": "04",
        "description": "Con liệt sĩ, con thương binh/bệnh binh suy giảm ≥81%, con Anh hùng",
        "bonus_points": Decimal("2.00"),
        "evidence_doc_type": "Giấy chứng nhận từ cơ quan BXH",
    },
    # UT2 group (1.00đ) — đối tượng 05..07
    {
        "group_code": "UT2", "sub_code": "05",
        "description": "Thanh niên xung phong; quân nhân/công an phục vụ <18 tháng không KV1",
        "bonus_points": Decimal("1.00"),
        "evidence_doc_type": "Quyết định xuất ngũ / xác nhận đơn vị",
    },
    {
        "group_code": "UT2", "sub_code": "06",
        "description": "Dân tộc thiểu số ngoài KV1; con thương binh suy giảm <81%; con người hoạt động kháng chiến",
        "bonus_points": Decimal("1.00"),
        "evidence_doc_type": "Giấy chứng nhận dân tộc / giấy xác nhận BXH",
    },
    {
        "group_code": "UT2", "sub_code": "07",
        "description": "Người khuyết tật nặng; người lao động ưu tú là thợ giỏi/nghệ nhân; Y tá/dược tá/hộ lý ≥3 năm",
        "bonus_points": Decimal("1.00"),
        "evidence_doc_type": "Giấy xác nhận khuyết tật / quyết định công nhận",
    },
]


class PriorityConfigService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PriorityConfigRepository(db)

    # =========================================================================
    # Area CRUD
    # =========================================================================

    async def list_areas(
        self, academic_year: int, active_only: bool = False
    ) -> list[PriorityAreaConfig]:
        return await self.repo.list_areas(academic_year, active_only=active_only)

    async def create_area(
        self, data: dict[str, Any]
    ) -> Tuple[PriorityAreaConfig, PostCommitCallback]:
        # Active-row guard mirrors the partial UNIQUE (year, code, NULL effective_to).
        existing = await self.repo.get_active_area(
            data["academic_year"], data["area_code"]
        )
        if existing is not None:
            raise DuplicateResourceError(
                f"Active KV rate for {data['area_code']!r} year "
                f"{data['academic_year']} already exists — retire it first "
                f"or PATCH the existing row."
            )
        # Drop nones so SQL gets server defaults (effective_from = CURRENT_DATE)
        clean = {k: v for k, v in data.items() if v is not None}
        row = await self.repo.create_area(clean)
        return row, _noop_callback

    async def update_area(
        self, area_id: int, data: dict[str, Any]
    ) -> Tuple[PriorityAreaConfig, PostCommitCallback]:
        row = await self.repo.get_area(area_id)
        if row is None:
            raise ResourceNotFoundError(
                f"PriorityAreaConfig {area_id} not found"
            )
        clean = {k: v for k, v in data.items() if v is not None or k == "effective_to"}
        # Allow explicit effective_to=None passthrough (re-activate)
        await self.repo.update_area(row, clean)
        return row, _noop_callback

    async def retire_area(
        self, area_id: int, effective_to: Optional[date] = None
    ) -> Tuple[PriorityAreaConfig, PostCommitCallback]:
        row = await self.repo.get_area(area_id)
        if row is None:
            raise ResourceNotFoundError(
                f"PriorityAreaConfig {area_id} not found"
            )
        if row.effective_to is not None:
            raise BusinessRuleViolation(
                f"PriorityAreaConfig {area_id} đã retire trước đó "
                f"(effective_to={row.effective_to})"
            )
        target = effective_to or date.today()
        await self.repo.retire_area(row, target)
        return row, _noop_callback

    # =========================================================================
    # Object CRUD
    # =========================================================================

    async def list_objects(
        self, academic_year: int, active_only: bool = False
    ) -> list[PriorityObjectConfig]:
        return await self.repo.list_objects(academic_year, active_only=active_only)

    async def create_object(
        self, data: dict[str, Any]
    ) -> Tuple[PriorityObjectConfig, PostCommitCallback]:
        existing = await self.repo.get_active_object(
            data["academic_year"], data["sub_code"]
        )
        if existing is not None:
            raise DuplicateResourceError(
                f"Active UT rate for sub_code {data['sub_code']!r} year "
                f"{data['academic_year']} already exists — retire it first "
                f"or PATCH the existing row."
            )
        clean = {k: v for k, v in data.items() if v is not None}
        row = await self.repo.create_object(clean)
        return row, _noop_callback

    async def update_object(
        self, obj_id: int, data: dict[str, Any]
    ) -> Tuple[PriorityObjectConfig, PostCommitCallback]:
        row = await self.repo.get_object(obj_id)
        if row is None:
            raise ResourceNotFoundError(
                f"PriorityObjectConfig {obj_id} not found"
            )
        clean = {k: v for k, v in data.items() if v is not None or k == "effective_to"}
        await self.repo.update_object(row, clean)
        return row, _noop_callback

    async def retire_object(
        self, obj_id: int, effective_to: Optional[date] = None
    ) -> Tuple[PriorityObjectConfig, PostCommitCallback]:
        row = await self.repo.get_object(obj_id)
        if row is None:
            raise ResourceNotFoundError(
                f"PriorityObjectConfig {obj_id} not found"
            )
        if row.effective_to is not None:
            raise BusinessRuleViolation(
                f"PriorityObjectConfig {obj_id} đã retire trước đó "
                f"(effective_to={row.effective_to})"
            )
        target = effective_to or date.today()
        await self.repo.retire_object(row, target)
        return row, _noop_callback

    # =========================================================================
    # Clone-from-year + Seed-defaults helpers
    # =========================================================================

    async def clone_from_year(
        self, from_year: int, to_year: int
    ) -> Tuple[dict[str, int], PostCommitCallback]:
        """Copy all ACTIVE rows from from_year to to_year. Skips any
        (year, code) already present in to_year — admin can run twice
        safely. Validation: from_year != to_year."""
        if from_year == to_year:
            raise BusinessRuleViolation(
                "from_year và to_year phải khác nhau"
            )

        source_areas = await self.repo.list_areas(from_year, active_only=True)
        source_objects = await self.repo.list_objects(from_year, active_only=True)

        cloned_areas = 0
        for src in source_areas:
            existing = await self.repo.get_active_area(to_year, src.area_code)
            if existing is not None:
                continue
            await self.repo.create_area(
                {
                    "academic_year": to_year,
                    "area_code": src.area_code,
                    "area_name": src.area_name,
                    "bonus_points": src.bonus_points,
                    "description": src.description,
                }
            )
            cloned_areas += 1

        cloned_objects = 0
        for src in source_objects:
            existing = await self.repo.get_active_object(to_year, src.sub_code)
            if existing is not None:
                continue
            await self.repo.create_object(
                {
                    "academic_year": to_year,
                    "group_code": src.group_code,
                    "sub_code": src.sub_code,
                    "description": src.description,
                    "bonus_points": src.bonus_points,
                    "evidence_doc_type": src.evidence_doc_type,
                }
            )
            cloned_objects += 1

        return (
            {"cloned_areas": cloned_areas, "cloned_objects": cloned_objects},
            _noop_callback,
        )

    async def seed_tt_05_2021_defaults(
        self, academic_year: int
    ) -> Tuple[dict[str, Any], PostCommitCallback]:
        """Idempotent seeder for TT 05/2021 baseline rates.

        Skips entirely if ANY active row already exists for the year —
        avoids partial-state where some rates seed and others don't.
        Admin must explicitly retire existing rows + re-seed to refresh.
        """
        # Check for any existing active row (area or object) before seeding
        existing_areas = await self.repo.list_areas(academic_year, active_only=True)
        existing_objects = await self.repo.list_objects(academic_year, active_only=True)
        if existing_areas or existing_objects:
            return (
                {
                    "inserted_areas": 0,
                    "inserted_objects": 0,
                    "skipped_existing": True,
                },
                _noop_callback,
            )

        for area in TT_05_2021_AREA_DEFAULTS:
            await self.repo.create_area({"academic_year": academic_year, **area})
        for obj in TT_05_2021_OBJECT_DEFAULTS:
            await self.repo.create_object({"academic_year": academic_year, **obj})

        return (
            {
                "inserted_areas": len(TT_05_2021_AREA_DEFAULTS),
                "inserted_objects": len(TT_05_2021_OBJECT_DEFAULTS),
                "skipped_existing": False,
            },
            _noop_callback,
        )
