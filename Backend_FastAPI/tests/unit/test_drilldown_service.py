from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import models
from app.database import AsyncSessionLocal
from app.services.drilldown_service import (
    get_consultations_drilldown,
    get_transitions_drilldown,
)


def _ctx(officer_id: int):
    return SimpleNamespace(
        effective_officer_ids=[officer_id],
        scope_kind="personal",
        label="Cá nhân",
        forced_by_role=False,
        includes_descendants=False,
    )


async def _seed_drilldown_pipeline(session):
    session.add_all([
        models.PipelineStage(id="dd_stage_progress", name="Đang xử lý", order=9001),
        models.PipelineStage(id="dd_stage_win", name="Thắng", order=9002, is_final_stage=True),
        models.PipelineStage(id="dd_stage_loss", name="Thua", order=9003, is_final_stage=True),
        models.ConsultationStatus(
            id="dd_status_progress",
            name="Đang xử lý",
            color_code="#999999",
            stage_id="dd_stage_progress",
            outcome_type="neutral",
            is_final=False,
            counts_for_funnel=True,
        ),
        models.ConsultationStatus(
            id="dd_status_win",
            name="Thắng",
            color_code="#00AA00",
            stage_id="dd_stage_win",
            outcome_type="positive",
            is_final=True,
            counts_for_funnel=True,
        ),
        models.ConsultationStatus(
            id="dd_status_loss",
            name="Thua",
            color_code="#CC0000",
            stage_id="dd_stage_loss",
            outcome_type="negative",
            is_final=True,
            counts_for_funnel=True,
        ),
    ])


def _lead(
    *,
    name: str,
    phone: str,
    officer_id: int,
    unit_id: int,
    status: str,
    consultation_status_id: str,
    pipeline_stage_id: str,
    created_at: datetime,
    updated_at: datetime | None = None,
    assigned_at: datetime | None = None,
):
    return models.Lead(
        full_name=name,
        phone=phone,
        source="website",
        status=status,
        unit_id=unit_id,
        assigned_officer_id=officer_id,
        consultation_status_id=consultation_status_id,
        pipeline_stage_id=pipeline_stage_id,
        created_at=created_at,
        updated_at=updated_at or created_at,
        assigned_at=assigned_at or created_at,
    )


def _history(
    *,
    lead_id: int,
    changed_at: datetime,
    old_status: str,
    new_status: str,
    old_stage_id: str,
    new_stage_id: str,
    old_consultation_status_id: str,
    new_consultation_status_id: str,
    loss_reason_code: str | None = None,
):
    return models.LeadStatusHistory(
        lead_id=lead_id,
        changed_at=changed_at,
        old_status=old_status,
        new_status=new_status,
        old_pipeline_stage_id=old_stage_id,
        new_pipeline_stage_id=new_stage_id,
        old_consultation_status_id=old_consultation_status_id,
        new_consultation_status_id=new_consultation_status_id,
        loss_reason_code=loss_reason_code,
    )


@pytest.mark.asyncio
async def test_win_rate_drilldown_uses_latest_transition_per_lead(
    setup_test_database,
    seed_lead_dependencies,
    officer_user_in_db,
):
    unit_id = seed_lead_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await _seed_drilldown_pipeline(session)

            lead_won = _lead(
                name="Lead Won",
                phone="0900000001",
                officer_id=officer_id,
                unit_id=unit_id,
                status="converted",
                consultation_status_id="dd_status_win",
                pipeline_stage_id="dd_stage_win",
                created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            )
            lead_lost = _lead(
                name="Lead Lost",
                phone="0900000002",
                officer_id=officer_id,
                unit_id=unit_id,
                status="rejected",
                consultation_status_id="dd_status_loss",
                pipeline_stage_id="dd_stage_loss",
                created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 9, tzinfo=timezone.utc),
            )
            lead_reopened = _lead(
                name="Lead Reopened",
                phone="0900000003",
                officer_id=officer_id,
                unit_id=unit_id,
                status="assigned",
                consultation_status_id="dd_status_progress",
                pipeline_stage_id="dd_stage_progress",
                created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
            )
            session.add_all([lead_won, lead_lost, lead_reopened])
            await session.flush()

            session.add_all([
                _history(
                    lead_id=lead_won.id,
                    changed_at=datetime(2026, 3, 5, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="rejected",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_loss",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_loss",
                    loss_reason_code="PRICE_HIGH",
                ),
                _history(
                    lead_id=lead_won.id,
                    changed_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
                    old_status="rejected",
                    new_status="converted",
                    old_stage_id="dd_stage_loss",
                    new_stage_id="dd_stage_win",
                    old_consultation_status_id="dd_status_loss",
                    new_consultation_status_id="dd_status_win",
                ),
                _history(
                    lead_id=lead_lost.id,
                    changed_at=datetime(2026, 3, 9, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="rejected",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_loss",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_loss",
                    loss_reason_code="NO_CONTACT",
                ),
                _history(
                    lead_id=lead_reopened.id,
                    changed_at=datetime(2026, 3, 4, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="converted",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_win",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_win",
                ),
                _history(
                    lead_id=lead_reopened.id,
                    changed_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
                    old_status="converted",
                    new_status="assigned",
                    old_stage_id="dd_stage_win",
                    new_stage_id="dd_stage_progress",
                    old_consultation_status_id="dd_status_win",
                    new_consultation_status_id="dd_status_progress",
                ),
            ])

        result = await get_transitions_drilldown(
            db=session,
            ctx=_ctx(officer_id),
            metric_key="win_rate",
            start_date="2026-03-01",
            end_date="2026-03-31",
        )

    assert result["metadata"]["total_count"] == 2
    assert {row["lead_name"] for row in result["rows"]} == {"Lead Won", "Lead Lost"}
    assert {row["outcome"] for row in result["rows"]} == {"positive", "negative"}


@pytest.mark.asyncio
async def test_consultation_effectiveness_drilldown_requires_consulted_leads(
    setup_test_database,
    seed_lead_dependencies,
    officer_user_in_db,
):
    unit_id = seed_lead_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await _seed_drilldown_pipeline(session)

            consulted_won = _lead(
                name="Consulted Won",
                phone="0900000011",
                officer_id=officer_id,
                unit_id=unit_id,
                status="converted",
                consultation_status_id="dd_status_win",
                pipeline_stage_id="dd_stage_win",
                created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
            )
            unconsulted_lost = _lead(
                name="Unconsulted Lost",
                phone="0900000012",
                officer_id=officer_id,
                unit_id=unit_id,
                status="rejected",
                consultation_status_id="dd_status_loss",
                pipeline_stage_id="dd_stage_loss",
                created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
            )
            consulted_lost = _lead(
                name="Consulted Lost",
                phone="0900000013",
                officer_id=officer_id,
                unit_id=unit_id,
                status="rejected",
                consultation_status_id="dd_status_loss",
                pipeline_stage_id="dd_stage_loss",
                created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 14, tzinfo=timezone.utc),
            )
            session.add_all([consulted_won, unconsulted_lost, consulted_lost])
            await session.flush()

            session.add_all([
                models.Consultation(
                    lead_id=consulted_won.id,
                    officer_id=officer_id,
                    method="phone",
                    notes="human consultation",
                    consultation_date=datetime(2026, 3, 10, tzinfo=timezone.utc),
                ),
                models.Consultation(
                    lead_id=consulted_lost.id,
                    officer_id=officer_id,
                    method="phone",
                    notes="human consultation",
                    consultation_date=datetime(2026, 3, 11, tzinfo=timezone.utc),
                ),
                _history(
                    lead_id=consulted_won.id,
                    changed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="converted",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_win",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_win",
                ),
                _history(
                    lead_id=unconsulted_lost.id,
                    changed_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="rejected",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_loss",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_loss",
                    loss_reason_code="PRICE_HIGH",
                ),
                _history(
                    lead_id=consulted_lost.id,
                    changed_at=datetime(2026, 3, 14, tzinfo=timezone.utc),
                    old_status="assigned",
                    new_status="rejected",
                    old_stage_id="dd_stage_progress",
                    new_stage_id="dd_stage_loss",
                    old_consultation_status_id="dd_status_progress",
                    new_consultation_status_id="dd_status_loss",
                    loss_reason_code="NO_CONTACT",
                ),
            ])

        result = await get_transitions_drilldown(
            db=session,
            ctx=_ctx(officer_id),
            metric_key="consultation_effectiveness",
            start_date="2026-03-01",
            end_date="2026-03-31",
        )

    assert result["metadata"]["total_count"] == 2
    assert {row["lead_name"] for row in result["rows"]} == {"Consulted Won", "Consulted Lost"}


@pytest.mark.asyncio
async def test_loss_reason_drilldown_honors_human_consultation_filter(
    setup_test_database,
    seed_lead_dependencies,
    officer_user_in_db,
):
    unit_id = seed_lead_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await _seed_drilldown_pipeline(session)

            lead_human = _lead(
                name="Human Consultation",
                phone="0900000021",
                officer_id=officer_id,
                unit_id=unit_id,
                status="assigned",
                consultation_status_id="dd_status_progress",
                pipeline_stage_id="dd_stage_progress",
                created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
            lead_system = _lead(
                name="System Consultation",
                phone="0900000022",
                officer_id=officer_id,
                unit_id=unit_id,
                status="assigned",
                consultation_status_id="dd_status_progress",
                pipeline_stage_id="dd_stage_progress",
                created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
            session.add_all([lead_human, lead_system])
            await session.flush()

            session.add_all([
                models.Consultation(
                    lead_id=lead_human.id,
                    officer_id=officer_id,
                    method="phone",
                    notes="manual",
                    consultation_date=datetime(2026, 3, 7, tzinfo=timezone.utc),
                    loss_reason_code="PRICE_HIGH",
                ),
                models.Consultation(
                    lead_id=lead_system.id,
                    officer_id=officer_id,
                    method="system",
                    notes="auto",
                    consultation_date=datetime(2026, 3, 8, tzinfo=timezone.utc),
                    loss_reason_code="PRICE_HIGH",
                ),
            ])

        result = await get_consultations_drilldown(
            db=session,
            ctx=_ctx(officer_id),
            metric_key="loss_reason",
            start_date="2026-03-01",
            end_date="2026-03-31",
            loss_reason_code="PRICE_HIGH",
            consultation_kind="human",
        )

    assert result["metadata"]["total_count"] == 1
    assert [row["lead_name"] for row in result["rows"]] == ["Human Consultation"]
