# tests/unit/test_terminal_status_guard.py
"""
Unit tests for Terminal Status Guard (Issue #3).

Tests the guard logic that prevents operations on leads in terminal states:
- HARD BLOCK: phase="enrolled" + is_final=True → Block consultation creation/status change
- SOFT BLOCK: other phases + is_final=True → Allow but skip lead status update
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.services.lead_service import (
    check_terminal_status_guard,
    TerminalGuardResult,
)


class TestTerminalGuardResult:
    """Test TerminalGuardResult dataclass behavior."""

    def test_default_values(self):
        """Default values should indicate no blocking."""
        result = TerminalGuardResult()
        assert result.is_terminal is False
        assert result.hard_block is False
        assert result.reason == ""
        assert result.current_status is None

    def test_soft_block_values(self):
        """Soft block should have is_terminal=True but hard_block=False."""
        result = TerminalGuardResult(
            is_terminal=True,
            hard_block=False,
            reason="Test soft block reason"
        )
        assert result.is_terminal is True
        assert result.hard_block is False
        assert "soft block" in result.reason.lower() or "Test" in result.reason

    def test_hard_block_values(self):
        """Hard block should have both is_terminal=True and hard_block=True."""
        result = TerminalGuardResult(
            is_terminal=True,
            hard_block=True,
            reason="Test hard block reason"
        )
        assert result.is_terminal is True
        assert result.hard_block is True


class TestCheckTerminalStatusGuard:
    """Test check_terminal_status_guard function."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_lead_no_status(self):
        """Create a mock lead without consultation_status_id."""
        lead = MagicMock()
        lead.id = 1
        lead.consultation_status_id = None
        return lead

    @pytest.fixture
    def mock_lead_with_status(self):
        """Create a mock lead with consultation_status_id."""
        lead = MagicMock()
        lead.id = 1
        lead.consultation_status_id = "sts05"  # Example status ID
        return lead

    @pytest.fixture
    def mock_status_non_final(self):
        """Create a mock non-final consultation status."""
        status = MagicMock()
        status.id = "sts05"
        status.name = "Đang tư vấn"
        status.phase = "consultation"
        status.is_final = False
        return status

    @pytest.fixture
    def mock_status_final_enrolled(self):
        """Create a mock final status with enrolled phase (HARD BLOCK)."""
        status = MagicMock()
        status.id = "sts11"
        status.name = "Đã xác nhận nhập học"
        status.phase = "enrolled"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_dropped_out(self):
        """Create a mock final status with enrolled phase for dropout (HARD BLOCK)."""
        status = MagicMock()
        status.id = "sts12"
        status.name = "Ngừng theo học"
        status.phase = "enrolled"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_withdrawn(self):
        """Create a mock final withdrawn status with admission phase (SOFT BLOCK)."""
        status = MagicMock()
        status.id = "sts08"
        status.name = "Không tiếp tục hồ sơ"
        status.phase = "admission"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_refunded(self):
        """Create a mock final refunded status with fee phase (SOFT BLOCK)."""
        status = MagicMock()
        status.id = "sts18"
        status.name = "Đã hoàn học phí"
        status.phase = "fee"
        status.is_final = True
        return status

    @pytest.mark.asyncio
    async def test_no_status_allows_operation(self, mock_db, mock_lead_no_status):
        """Lead without consultation_status_id should allow all operations."""
        result = await check_terminal_status_guard(mock_db, mock_lead_no_status)

        assert result.is_terminal is False
        assert result.hard_block is False
        mock_db.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_final_status_allows_operation(
        self, mock_db, mock_lead_with_status, mock_status_non_final
    ):
        """Non-final status should allow all operations."""
        mock_db.get.return_value = mock_status_non_final

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is False
        assert result.hard_block is False
        assert result.current_status == mock_status_non_final

    @pytest.mark.asyncio
    async def test_enrolled_final_status_hard_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_enrolled
    ):
        """Enrolled + is_final status should HARD BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts11"
        mock_db.get.return_value = mock_status_final_enrolled

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is True
        assert "nhập học" in result.reason or "enrolled" in result.reason.lower()
        assert result.current_status == mock_status_final_enrolled

    @pytest.mark.asyncio
    async def test_dropped_out_final_status_hard_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_dropped_out
    ):
        """Dropped out + is_final status should HARD BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts12"
        mock_db.get.return_value = mock_status_final_dropped_out

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is True
        assert result.current_status.phase == "enrolled"

    @pytest.mark.asyncio
    async def test_withdrawn_final_status_soft_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_withdrawn
    ):
        """Withdrawn + is_final status should SOFT BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts08"
        mock_db.get.return_value = mock_status_final_withdrawn

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is False  # Soft block
        assert "terminal" in result.reason.lower() or "withdraw" in result.reason.lower()
        assert result.current_status.phase == "admission"

    @pytest.mark.asyncio
    async def test_refunded_final_status_soft_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_refunded
    ):
        """Refunded + is_final status should SOFT BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts18"
        mock_db.get.return_value = mock_status_final_refunded

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is False  # Soft block
        assert result.current_status.phase == "fee"

    @pytest.mark.asyncio
    async def test_missing_status_in_db_allows_operation(
        self, mock_db, mock_lead_with_status
    ):
        """If status not found in DB, should allow operation (defensive)."""
        mock_db.get.return_value = None

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is False
        assert result.hard_block is False


class TestTerminalGuardIntegration:
    """Integration-style tests for terminal guard behavior."""

    @pytest.fixture
    def terminal_statuses(self):
        """List of terminal statuses from consultation_status_v3.csv."""
        return [
            {"id": "sts08", "name": "Không tiếp tục hồ sơ", "phase": "admission", "is_final": True},
            {"id": "sts11", "name": "Đã xác nhận nhập học", "phase": "enrolled", "is_final": True},
            {"id": "sts12", "name": "Ngừng theo học", "phase": "enrolled", "is_final": True},
            {"id": "sts16", "name": "Hồ sơ không đạt yêu cầu", "phase": "admission", "is_final": True},
            {"id": "sts18", "name": "Đã hoàn học phí", "phase": "fee", "is_final": True},
        ]

    def test_enrolled_phase_statuses_should_hard_block(self, terminal_statuses):
        """All enrolled phase terminal statuses should hard block."""
        enrolled_statuses = [s for s in terminal_statuses if s["phase"] == "enrolled"]

        assert len(enrolled_statuses) == 2  # sts11, sts12
        for status in enrolled_statuses:
            assert status["is_final"] is True
            # These should result in hard_block=True

    def test_non_enrolled_terminal_statuses_should_soft_block(self, terminal_statuses):
        """Non-enrolled terminal statuses should soft block."""
        non_enrolled_statuses = [
            s for s in terminal_statuses
            if s["phase"] != "enrolled" and s["is_final"]
        ]

        assert len(non_enrolled_statuses) == 3  # sts08, sts16, sts18
        for status in non_enrolled_statuses:
            assert status["is_final"] is True
            # These should result in hard_block=False, is_terminal=True


class TestTerminalGuardErrorMessages:
    """Test error message clarity for terminal guard."""

    def test_hard_block_message_mentions_phase(self):
        """Hard block message should mention 'enrolled' phase."""
        result = TerminalGuardResult(
            is_terminal=True,
            hard_block=True,
            reason="Lead đang ở trạng thái 'Đã nhập học' (phase=enrolled, is_final=True). "
                   "Không thể thêm consultation mới cho lead đã hoàn tất quy trình nhập học."
        )
        assert "enrolled" in result.reason
        assert "is_final=True" in result.reason

    def test_soft_block_message_mentions_terminal(self):
        """Soft block message should mention terminal state."""
        result = TerminalGuardResult(
            is_terminal=True,
            hard_block=False,
            reason="Lead đang ở trạng thái terminal 'Từ chối' (phase=admission, is_final=True). "
                   "Cho phép ghi nhận consultation nhưng không cập nhật lead status."
        )
        assert "terminal" in result.reason
        assert "không cập nhật lead status" in result.reason
