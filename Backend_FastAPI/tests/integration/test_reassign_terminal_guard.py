"""Integration tests (R1) — chặn assign/reassign trên lead consultation-terminal.

Lead đã đóng (sts20: ``is_final`` + ``phase=='consultation'``) KHÔNG được giao/đổi
officer bằng đường thủ công hay officer-reassign — phải reopen trước. Guard mềm
``check_terminal_status_guard`` chỉ hard-block ``enrolled`` nên R1 chặn CỨNG riêng
ở đường assign. Xem plan ``spicy-rolling-whistle.md`` §R1.

Đường hợp lệ (reopen→assign) + non-terminal vẫn giao được đã có test hiện hữu
phủ (``test_assignment.py`` + assign flow), nên file này chỉ khoá 2 lỗ mới.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service
from app.utils.exceptions import BusinessRuleViolation

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def terminal_status(
    db: AsyncSession, seeded_dependencies: dict
) -> models.ConsultationStatus:
    """Consultation status CUỐI phase tư vấn (giống sts20 prod)."""
    cs = models.ConsultationStatus(
        id="STS20_TEST",
        name="Ngừng tư vấn (test)",
        color_code="#CC0000",
        stage_id=seeded_dependencies["stage_id"],
        is_final=True,
        phase="consultation",
    )
    db.add(cs)
    await db.flush()
    return cs


@pytest_asyncio.fixture
async def terminal_lead(
    db: AsyncSession,
    seeded_dependencies: dict,
    terminal_status: models.ConsultationStatus,
    officer_user: models.User,
) -> models.Lead:
    """Lead đã đóng (terminal), đang gán cho officer_user."""
    lead = models.Lead(
        full_name="Terminal Lead",
        phone="0900111222",
        email="terminal_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_user.id,
        consultation_status_id=terminal_status.id,
        consultation_count=0,
        status="rejected",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def test_assign_lead_manually_blocks_terminal(
    db: AsyncSession,
    terminal_lead: models.Lead,
    officer_user: models.User,
    manager_user: models.User,
):
    """Manager giao lead đã đóng cho officer khác → BusinessRuleViolation."""
    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.assign_lead_manually(
            db, terminal_lead.id, officer_user.id, manager_user
        )
    assert "mở lại" in str(exc.value.detail).lower()


async def test_officer_reassign_blocks_terminal(
    db: AsyncSession,
    terminal_lead: models.Lead,
    officer_user: models.User,
):
    """Officer tự xin đổi người (reassign) trên lead đã đóng → chặn CỨNG
    (né ping-pong bỏ qua reopen)."""
    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.process_officer_action(
            db, terminal_lead.id, officer_user, "reassign", "muốn đổi người"
        )
    assert "mở lại" in str(exc.value.detail).lower()
