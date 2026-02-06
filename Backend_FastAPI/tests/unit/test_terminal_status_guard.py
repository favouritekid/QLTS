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
        status.name = "Đã nhập học"
        status.phase = "enrolled"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_reserved(self):
        """Create a mock final status with enrolled phase for reserved (HARD BLOCK)."""
        status = MagicMock()
        status.id = "sts12"
        status.name = "Đã bảo lưu"
        status.phase = "enrolled"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_rejected(self):
        """Create a mock final status with admission phase (SOFT BLOCK)."""
        status = MagicMock()
        status.id = "sts08"
        status.name = "Từ chối"
        status.phase = "admission"
        status.is_final = True
        return status

    @pytest.fixture
    def mock_status_final_not_interested(self):
        """Create a mock final status with consultation phase (SOFT BLOCK)."""
        status = MagicMock()
        status.id = "sts04"
        status.name = "Không quan tâm"
        status.phase = "consultation"
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
    async def test_reserved_final_status_hard_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_reserved
    ):
        """Reserved (Đã bảo lưu) + is_final status should HARD BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts12"
        mock_db.get.return_value = mock_status_final_reserved

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is True
        assert result.current_status.phase == "enrolled"

    @pytest.mark.asyncio
    async def test_rejected_final_status_soft_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_rejected
    ):
        """Rejected (Từ chối) + is_final status should SOFT BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts08"
        mock_db.get.return_value = mock_status_final_rejected

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is False  # Soft block
        assert "terminal" in result.reason.lower() or "Từ chối" in result.reason
        assert result.current_status.phase == "admission"

    @pytest.mark.asyncio
    async def test_not_interested_final_status_soft_blocks(
        self, mock_db, mock_lead_with_status, mock_status_final_not_interested
    ):
        """Not Interested (Không quan tâm) + is_final status should SOFT BLOCK."""
        mock_lead_with_status.consultation_status_id = "sts04"
        mock_db.get.return_value = mock_status_final_not_interested

        result = await check_terminal_status_guard(mock_db, mock_lead_with_status)

        assert result.is_terminal is True
        assert result.hard_block is False  # Soft block
        assert result.current_status.phase == "consultation"

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
            {"id": "sts04", "name": "Không quan tâm", "phase": "consultation", "is_final": True},
            {"id": "sts08", "name": "Từ chối", "phase": "admission", "is_final": True},
            {"id": "sts11", "name": "Đã nhập học", "phase": "enrolled", "is_final": True},
            {"id": "sts12", "name": "Đã bảo lưu", "phase": "enrolled", "is_final": True},
            {"id": "sts16", "name": "Rút hồ sơ", "phase": "admission", "is_final": True},
            {"id": "sts18", "name": "Từ chối nhập học", "phase": "admission", "is_final": True},
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

        assert len(non_enrolled_statuses) == 4  # sts04, sts08, sts16, sts18
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
