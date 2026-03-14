# tests/services/test_lead_score.py
"""
Focused tests for calculate_lead_score — stale_penalty validation behavior.

Cases:
  - valid value within limit → used as-is
  - value > MAX_STALE_PENALTY → clamped to 50, warning logged
  - negative value → fallback to default (10), warning logged
  - invalid type (string, None, list) → fallback to default (10), warning logged
  - within threshold days → no penalty applied regardless of value
  - no config → default (10) used
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.lead_service import calculate_lead_score


class FakeScoringConfig:
    """Minimal mock for scoring_config returned by repository."""
    def __init__(self, params: dict):
        self.params = params


@pytest.fixture
def mock_db():
    return AsyncMock()


def _patch_repo(config):
    """Helper: patch LeadRepository to return given scoring config."""
    patcher = patch("app.repositories.LeadRepository")
    MockRepo = patcher.start()
    MockRepo.return_value.get_scoring_config_by_unit = AsyncMock(return_value=config)
    return patcher


class TestStalePenaltyValidation:
    """Verify stale_penalty is sanitized for all edge cases."""

    @pytest.mark.asyncio
    async def test_default_stale_penalty_applied(self, mock_db):
        """No config → default stale_penalty=10 subtracts normally."""
        patcher = _patch_repo(None)
        try:
            # education=bachelor(40) + source=website(20) = 60 base
            # stale 30 days → -10 penalty → 50
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=30,
            )
            assert score == 50
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_config_stale_penalty_within_limit(self, mock_db):
        """Config stale_penalty=30 (within 50 cap) applied as-is."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": 30}))
        try:
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=30,
            )
            # 60 base - 30 penalty = 30
            assert score == 30
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_config_stale_penalty_exceeds_cap_is_clamped(self, mock_db):
        """Config stale_penalty=200 gets clamped to MAX_STALE_PENALTY=50."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": 200}))
        try:
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=30,
            )
            # 60 base - 50 (clamped) = 10
            assert score == 10
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_config_stale_penalty_exceeds_cap_logs_warning(self, mock_db):
        """When stale_penalty > MAX, a warning is logged with raw_value and clamped_to."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": 999}))
        try:
            with patch("app.services.lead_service.log") as mock_log:
                await calculate_lead_score(
                    mock_db, unit_id=1, days_since_last_activity=30,
                )
                mock_log.warning.assert_called_once()
                kw = mock_log.warning.call_args[1]
                assert kw["raw_value"] == 999
                assert kw["clamped_to"] == 50
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_negative_stale_penalty_falls_back_to_default(self, mock_db):
        """Negative stale_penalty → fallback to default (10), warning logged."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": -20}))
        try:
            with patch("app.services.lead_service.log") as mock_log:
                score = await calculate_lead_score(
                    mock_db,
                    lead_education_level="bachelor",
                    lead_source="website",
                    unit_id=1,
                    days_since_last_activity=30,
                )
                # 60 base - 10 (default fallback) = 50
                assert score == 50
                mock_log.warning.assert_called_once()
                kw = mock_log.warning.call_args[1]
                assert kw["raw_value"] == -20
                assert kw["fallback"] == 10
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_string_stale_penalty_falls_back_to_default(self, mock_db):
        """Non-numeric string → fallback to default (10), warning logged."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": "abc"}))
        try:
            with patch("app.services.lead_service.log") as mock_log:
                score = await calculate_lead_score(
                    mock_db,
                    lead_education_level="bachelor",
                    lead_source="website",
                    unit_id=1,
                    days_since_last_activity=30,
                )
                # 60 base - 10 (default fallback) = 50
                assert score == 50
                mock_log.warning.assert_called_once()
                assert "invalid type" in mock_log.warning.call_args[0][0]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_none_stale_penalty_falls_back_to_default(self, mock_db):
        """None value → fallback to default (10), warning logged."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": None}))
        try:
            with patch("app.services.lead_service.log") as mock_log:
                score = await calculate_lead_score(
                    mock_db,
                    lead_education_level="bachelor",
                    lead_source="website",
                    unit_id=1,
                    days_since_last_activity=30,
                )
                assert score == 50
                mock_log.warning.assert_called_once()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_list_stale_penalty_falls_back_to_default(self, mock_db):
        """List value → fallback to default (10), warning logged."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": [10, 20]}))
        try:
            with patch("app.services.lead_service.log") as mock_log:
                score = await calculate_lead_score(
                    mock_db,
                    lead_education_level="bachelor",
                    lead_source="website",
                    unit_id=1,
                    days_since_last_activity=30,
                )
                assert score == 50
                mock_log.warning.assert_called_once()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_zero_stale_penalty_is_valid(self, mock_db):
        """stale_penalty=0 is valid — effectively disables the penalty."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": 0}))
        try:
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=30,
            )
            # 60 base - 0 penalty = 60
            assert score == 60
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_stale_penalty_not_applied_within_threshold(self, mock_db):
        """days_since_last_activity <= 7 → no penalty regardless of config."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": 200}))
        try:
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=5,
            )
            # 60 base, within threshold → no penalty → 60
            assert score == 60
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_numeric_string_stale_penalty_coerced(self, mock_db):
        """Numeric string like '25' is coerced to float successfully."""
        patcher = _patch_repo(FakeScoringConfig({"stale_penalty": "25"}))
        try:
            score = await calculate_lead_score(
                mock_db,
                lead_education_level="bachelor",
                lead_source="website",
                unit_id=1,
                days_since_last_activity=30,
            )
            # 60 base - 25 penalty = 35
            assert score == 35
        finally:
            patcher.stop()
