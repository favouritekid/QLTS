"""Khung dựng hồ sơ multi-NV THẬT cho T6 (``publish_result`` / ``evaluate_cascade``) — MỘT nguồn.

Trước đây khung này nằm trong ``tests/api/test_b1_kv_override_preserve.py``; tách ra để test T6 dừng có nhãn
(``tests/api/test_t6_dung_co_nhan.py``) dùng chung, không chép.

Mọi giá trị là dữ liệu GIẢ (tên, số điện thoại, CCCD sinh từ dấu thời gian).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.priority_config import PriorityAreaConfig

#: Luật cộng điểm mặc định của path: bật KV, tắt UT.
BAT_KV = {"apply_area_bonus": True, "apply_object_bonus": False}


async def seed_area_rates(
    session,
    *,
    academic_year: int,
    rates: dict[str, Decimal],
    effective_from: date = date(2025, 1, 1),
    effective_to: Optional[date] = None,
) -> None:
    """Hàng ``priority_area_config`` cho ``academic_year``; mã đã có hàng thì bỏ qua (idempotent theo mã)."""
    co_san = (
        await session.execute(
            select(PriorityAreaConfig.area_code).where(PriorityAreaConfig.academic_year == academic_year)
        )
    ).scalars().all()
    for code, pts in rates.items():
        if code in co_san:
            continue
        session.add(
            PriorityAreaConfig(
                academic_year=academic_year,
                area_code=code,
                area_name=f"Khu vuc {code}",
                bonus_points=pts,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
    await session.flush()


async def seed_cascade_profile(
    seed_lead_dependencies: dict,
    *,
    status: str = "reviewing",
    academic_year: int = 2026,
    area_rates: Optional[dict[str, Decimal]] = None,
    choices: Optional[list[dict[str, Any]]] = None,
    history_fn: Optional[Callable[[dict], list]] = None,
    nhan: str = "T6",
) -> dict:
    """Hồ sơ ``uses_choice_engine`` + các NV thật.

    * ``area_rates``: hàng mức KV mở cho ``academic_year`` (mặc định KV1 = 0.75, KV3 = 0.00).
    * ``choices``: mỗi phần tử một NV theo ``display_order``; khoá tuỳ chọn ``round_year`` (mặc định
      ``academic_year``), ``bonus_rule`` (mặc định ``BAT_KV``), ``admit_quota`` (mặc định 10).
    * ``history_fn(seed) -> academic_history``: thay quá trình học mặc định (THPT 2020→2024, KV3).
    """
    from tests.fixtures.builders import (
        AdmissionRoundBuilder,
        ensure_submittable_ward,
        seed_submittable_offering_config,
        submittable_profile_fields,
    )

    if area_rates is None:
        area_rates = {"KV1": Decimal("0.75"), "KV3": Decimal("0.00")}
    if choices is None:
        choices = [{}]

    await ensure_submittable_ward()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            seed = await seed_submittable_offering_config(
                s, unit_id=seed_lead_dependencies["unit_id"], academic_year=academic_year,
            )
            await seed_area_rates(s, academic_year=academic_year, rates=area_rates)

            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            method = models.AdmissionMethod(
                code=f"{nhan}M_{ts}",
                name=f"{nhan} method {ts}",
                requires_subject_scores=False,
                requires_gpa=False,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            path_ids: list[int] = []
            config_ids: list[int] = []
            for i, nv in enumerate(choices):
                round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                    s, academic_year=nv.get("round_year", academic_year),
                )
                path = models.AdmissionPath(
                    academic_info_id=seed["academic_info_id"],
                    admission_method_id=method.id,
                    admission_round_id=round_id,
                    status="active",
                    admit_quota=nv.get("admit_quota", 10),
                    round_quota=10,
                    bonus_rule_override=nv.get("bonus_rule", BAT_KV),
                )
                s.add(path)
                await s.flush()
                sg = models.SubjectGroup(code=f"{nhan}G{ts}{i}"[:20], name=f"{nhan} grp {ts} {i}")
                s.add(sg)
                await s.flush()
                config = models.PathSubjectGroupConfig(
                    admission_path_id=path.id, subject_group_id=sg.id, min_score=Decimal("0.0"),
                )
                s.add(config)
                await s.flush()
                path_ids.append(path.id)
                config_ids.append(config.id)

            lead = models.Lead(
                full_name=f"{nhan} cascade lead {ts}",
                phone=f"08{ts:08d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            fields = submittable_profile_fields(seed)
            fields["uses_choice_engine"] = True
            if history_fn is not None:
                fields["academic_history"] = history_fn(seed)
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"9{ts:08d}0"[:12],
                status=status,
                academic_year=academic_year,
                applied_rules={},
                **fields,
            )
            s.add(profile)
            await s.flush()
            choice_ids: list[int] = []
            for i, (path_id, config_id) in enumerate(zip(path_ids, config_ids)):
                choice = models.AdmissionProfileChoice(
                    admission_profile_id=profile.id,
                    admission_path_id=path_id,
                    path_subject_group_config_id=config_id,
                    display_order=i + 1,
                    decision="pending",
                )
                s.add(choice)
                await s.flush()
                choice_ids.append(choice.id)
            return {
                "profile_id": profile.id,
                "choice_ids": choice_ids,
                "path_ids": path_ids,
                "seed": seed,
            }


async def load_profile_for_t6(session, profile_id: int) -> models.AdmissionProfile:
    """Nạp hồ sơ với ĐÚNG chuỗi eager-load router ``publish-result`` dùng."""
    from app.services.admission_choice_engine_service import t6_profile_load_options

    return (
        await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(*t6_profile_load_options())
        )
    ).scalar_one()


async def run_engine(profile_id: int, *, entry: str) -> None:
    """Gọi engine THẬT — ``entry`` chọn ``evaluate_cascade`` hay ``publish_result``; commit khi thành công."""
    from app.services import admission_choice_engine_service as engine_mod

    async with AsyncSessionLocal() as s:
        profile = await load_profile_for_t6(s, profile_id)
        if entry == "publish_result":
            await engine_mod.publish_result(s, profile)
        else:
            await engine_mod.evaluate_cascade(s, profile)
        await s.commit()


async def doc_lai_ho_so(profile_id: int) -> tuple[str, list[str]]:
    """``(status, [decision theo display_order])`` đọc trong session MỚI. Không ném khi hàng tồn tại."""
    async with AsyncSessionLocal() as s:
        status = (
            await s.execute(select(models.AdmissionProfile.status).where(models.AdmissionProfile.id == profile_id))
        ).scalar_one()
        quyet_dinh = (
            await s.execute(
                select(models.AdmissionProfileChoice.decision)
                .where(models.AdmissionProfileChoice.admission_profile_id == profile_id)
                .order_by(models.AdmissionProfileChoice.display_order)
            )
        ).scalars().all()
    return status, list(quyet_dinh)
