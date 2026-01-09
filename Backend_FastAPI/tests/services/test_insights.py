# tests/services/test_insights_service.py
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import case, func, select  # Import cho test engagement score
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings

# Import necessary components
from app.services import insights_service

# Sample Data
mock_lead = models.Lead(
    id=1,
    full_name="Insight Lead",
    email="i@e.com",
    phone="123",
    source="website",
    unit_id=1,
    status="contacted",
    gpa=7.5,
    education_level="Tốt nghiệp THPT",
    location="Hà Nội",
    officer_rating=4,
    officer_summary="Good fit",
    pipeline_stage=models.PipelineStage(id="S2", name="Stage 2", order=2),  # Add stage
)

# Định nghĩa các đối tượng ConsultationStatus cần thiết cho Timeline
status_c1 = models.ConsultationStatus(
    id="C1", name="Consulted 1", color_code="#111", stage_id="S1"
)
status_c2 = models.ConsultationStatus(
    id="C2", name="Consulted 2", color_code="#222", stage_id="S2"
)
status_c3 = models.ConsultationStatus(
    id="C3", name="Consulted 3", color_code="#333", stage_id="S2"
)


# FIXED: Định nghĩa lại mock_consultations_data CHỈ với FK (consultation_status_id)
mock_consultations_data = [
    # Successful meeting (high score)
    {
        "id": 1,
        "lead_id": 1,
        "method": "meeting",
        # "outcome": "successful",  # Removed invalid field
        "duration_minutes": 35,
        "consultation_date": datetime.now(timezone.utc) - timedelta(days=2),
        "officer_id": 1,
        "consultation_status_id": status_c1.id,
    },
    # Follow-up call (medium score)
    {
        "id": 2,
        "lead_id": 1,
        "method": "call",
        # "outcome": "follow-up",  # Removed invalid field
        "duration_minutes": 12,
        "consultation_date": datetime.now(timezone.utc) - timedelta(days=10),
        "officer_id": 1,
        "consultation_status_id": status_c2.id,
    },
    # Failed email (low/negative score)
    {
        "id": 3,
        "lead_id": 1,
        "method": "email",
        # "outcome": "failed",  # Removed invalid field
        "duration_minutes": None,
        "consultation_date": datetime.now(timezone.utc) - timedelta(days=20),
        "officer_id": 1,
        "consultation_status_id": status_c3.id,
    },
]

# FIXED: Sử dụng dictionary cơ sở + truyền đối tượng quan hệ (consultation_status)
mock_timeline = [
    {
        "type": "consultation",
        "timestamp": mock_consultations_data[2]["consultation_date"],
        "data": models.Consultation(
            **mock_consultations_data[2], consultation_status=status_c3
        ),
    },
    {
        "type": "consultation",
        "timestamp": mock_consultations_data[1]["consultation_date"],
        "data": models.Consultation(
            **mock_consultations_data[1], consultation_status=status_c2
        ),
    },
    {
        "type": "consultation",
        "timestamp": mock_consultations_data[0]["consultation_date"],
        "data": models.Consultation(
            **mock_consultations_data[0], consultation_status=status_c1
        ),
    },
]


@pytest.fixture
def mock_db_session():
    """Creates a mock AsyncSession, mocks refresh for get_lead_insights."""
    session = AsyncMock(spec=AsyncSession)
    session.refresh = AsyncMock()
    session.execute = AsyncMock()

    # Mock for engagement score calculation
    mock_agg_result = MagicMock()
    # Manual calculation based on configs for expected base score
    cfg = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    expected_outcome_score = (
        cfg["outcome"]["successful"]
        + cfg["outcome"]["follow-up"]
        + cfg["outcome"]["failed"]
    )
    expected_method_score = (
        cfg["method"]["meeting"] + cfg["method"]["call"] + cfg["method"]["email"]
    )
    expected_duration_score = (35 // 10 * cfg["duration_bonus_per_10_min"]) + (
        12 // 10 * cfg["duration_bonus_per_10_min"]
    )

    mock_agg_result.one_or_none.return_value = MagicMock(
        total_count=len(mock_consultations_data),
        total_outcome_score=expected_outcome_score,
        total_method_score=expected_method_score,
        total_duration_score=expected_duration_score,
        last_consultation_date=mock_consultations_data[0][
            "consultation_date"
        ],  # Most recent
    )
    session.execute.return_value = mock_agg_result
    return session


@pytest.mark.asyncio
async def test_calculate_engagement_score(mock_db_session):
    """Test _calculate_engagement_score logic including inactivity penalty."""
    score = await insights_service._calculate_engagement_score(
        mock_db_session, mock_lead.id
    )

    # Calculate expected base score (without penalty) based on mock aggregation
    cfg = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    expected_base = (
        len(mock_consultations_data) * cfg["consultation_count_multiplier"]
        + (
            cfg["outcome"]["successful"]
            + cfg["outcome"]["follow-up"]
            + cfg["outcome"]["failed"]
        )
        + (cfg["method"]["meeting"] + cfg["method"]["call"] + cfg["method"]["email"])
        + (
            (35 // 10 * cfg["duration_bonus_per_10_min"])
            + (12 // 10 * cfg["duration_bonus_per_10_min"])
        )
    )
    expected_penalty = 0

    expected_score = int(
        max(0, min(expected_base - expected_penalty, cfg["max_score"]))
    )

    mock_db_session.execute.assert_awaited_once()  # Check DB query was made
    assert score == expected_score


def test_calculate_fit_score():
    """Test _calculate_fit_score logic (synchronous)."""
    score = insights_service._calculate_fit_score(mock_lead)
    cfg = settings.LEAD_SCORING_FIT_POINTS

    # Source: 'website' -> 5
    # GPA: 7.5 -> Threshold 7.0 (10 points)
    # Education: 'Tốt nghiệp THPT' -> 15
    # Location: 'Hà Nội' -> 10
    expected_base = (
        cfg["source"]["website"]
        + cfg["gpa_thresholds"][7.0]
        + cfg["education_level"]["Tốt nghiệp THPT"]
        + cfg["location"]["Hà Nội"]
    )
    expected_score = int(min(expected_base, cfg["max_score"]))

    assert score == expected_score


def test_calculate_urgency_score():
    """Test _calculate_urgency_score logic based on timeline."""
    score = insights_service._calculate_urgency_score(mock_lead, mock_timeline)
    cfg = settings.LEAD_SCORING_URGENCY_POINTS

    # Base Score: S2 (order 2) -> 2 * 15 = 30
    expected_base = mock_lead.pipeline_stage.order * cfg["stage_order_multiplier"]

    # We assume the timeline transition check is correct based on dates
    # (S2 @ Day 20 -> S1 @ Day 2) is a slow transition (18 days), resulting in a penalty of -10.

    # This requires running the actual calculation loop or mocking the internal logic.
    # For now, assert the base score + known factors.

    # Assuming slow transition penalty is applied (18 days > 14 days)
    # Penalty: 10
    expected_score = expected_base - 10

    # Simplification for Unit Test:
    assert score == expected_score


@pytest.mark.asyncio
async def test_get_lead_insights_overall_score_calculation(mock_db_session, mocker):
    """Test get_lead_insights combines all scores correctly with weights."""
    # Mock internal async functions
    mocker.patch(
        "app.services.insights_service._calculate_engagement_score",
        new_callable=AsyncMock,
        return_value=80,
    )
    mocker.patch("app.services.insights_service._calculate_fit_score", return_value=60)
    mocker.patch(
        "app.services.insights_service._calculate_urgency_score", return_value=50
    )

    # Note: mock_lead has officer_rating=4
    lead_insights = await insights_service.get_lead_insights(
        mock_db_session, mock_lead, mock_timeline
    )

    weights = settings.LEAD_SCORING_WEIGHTS
    expected_raw_score = (
        (80 * weights["engagement"])
        + (60 * weights["fit"])
        + (50 * weights["urgency"])
        + (
            mock_lead.officer_rating
            * weights["officer_rating_multiplier"]
            * weights["officer_rating_weight"]
        )
    )

    # Expected raw: (80*0.3) + (60*0.4) + (50*0.2) + (4*20*0.1) = 24 + 24 + 10 + 8 = 66
    expected_score = int(min(max(expected_raw_score, 0), 100))

    assert lead_insights.engagement_score == 80
    assert lead_insights.fit_score == 60
    assert lead_insights.urgency_score == 50
    assert lead_insights.overall_score == expected_score
    assert lead_insights.officer_rating == 4

    # Check refresh was called (minimal)
    mock_db_session.refresh.assert_awaited_once_with(
        mock_lead, ["assignment_logs", "pipeline_stage"]
    )
