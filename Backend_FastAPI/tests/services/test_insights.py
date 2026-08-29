# tests/services/test_insights_service.py
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
    """AsyncSession giả; chỉ ``refresh`` được ``get_lead_insights`` dùng tới.

    Bản trước còn giả lập ``session.execute`` để nuôi phần tính engagement.
    Đường đó đã biến mất: ``_calculate_engagement_score`` nay đọc qua
    ``InsightsRepository.get_engagement_score_data`` (refactor
    "add InsightsRepository and KpiRepository"), nên session không còn được
    truy vấn trực tiếp. Giữ lại mock cũ chỉ tạo ảo giác về một lời gọi không
    tồn tại.
    """
    session = AsyncMock(spec=AsyncSession)
    session.refresh = AsyncMock()
    return session


def _du_lieu_engagement():
    """Bản ghi tổng hợp đúng hình dạng ``InsightsRepository`` trả về.

    ``_calculate_engagement_score`` đọc năm thuộc tính: ``total_count``,
    ``total_status_score``, ``total_method_score``, ``total_duration_score``,
    ``last_consultation_date``.

    ⚠️ Là ``total_status_score``, KHÔNG phải ``total_outcome_score``. Cột
    ``outcome`` đã bị gỡ khỏi ``Consultation`` (dữ liệu mẫu trong tệp này cũng
    đã chú thích "Removed invalid field") và điểm nay tính theo
    ``consultation_status``. Mock cấp sai tên khiến thuộc tính trở thành một
    ``MagicMock`` mới, ``score`` cộng dồn thành ``MagicMock``, và lỗi chỉ nổ ở
    tận ``min(score, max_score)`` dưới dạng ``TypeError: '<' not supported``.
    """
    cfg = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    diem_trang_thai = (
        cfg["outcome"]["successful"]
        + cfg["outcome"]["follow-up"]
        + cfg["outcome"]["failed"]
    )
    diem_phuong_thuc = (
        cfg["method"]["meeting"] + cfg["method"]["call"] + cfg["method"]["email"]
    )
    diem_thoi_luong = (35 // 10 * cfg["duration_bonus_per_10_min"]) + (
        12 // 10 * cfg["duration_bonus_per_10_min"]
    )
    return SimpleNamespace(
        total_count=len(mock_consultations_data),
        total_status_score=diem_trang_thai,
        total_method_score=diem_phuong_thuc,
        total_duration_score=diem_thoi_luong,
        last_consultation_date=mock_consultations_data[0]["consultation_date"],
    )


@pytest.mark.asyncio
async def test_calculate_engagement_score(mock_db_session):
    """Test _calculate_engagement_score logic including inactivity penalty."""
    du_lieu = _du_lieu_engagement()
    with patch.object(
        insights_service.InsightsRepository,
        "get_engagement_score_data",
        new=AsyncMock(return_value=du_lieu),
    ) as doc_du_lieu:
        score = await insights_service._calculate_engagement_score(
            mock_db_session, mock_lead.id
        )
    doc_du_lieu.assert_awaited_once_with(mock_lead.id)

    # Calculate expected base score (without penalty) based on mock aggregation
    cfg = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    expected_base = (
        du_lieu.total_count * cfg["consultation_count_multiplier"]
        + du_lieu.total_status_score
        + du_lieu.total_method_score
        + du_lieu.total_duration_score
    )
    # Lần tư vấn gần nhất cách 2 ngày; hình phạt chỉ áp khi > 3 ngày.
    expected_penalty = 0

    expected_score = int(
        max(0, min(expected_base - expected_penalty, cfg["max_score"]))
    )

    assert score == expected_score


def test_calculate_fit_score():
    """``fit = min(lead_score + officer_rating × 4, 100)``.

    Bản trước cộng bốn khoản từ ``LEAD_SCORING_FIT_POINTS`` (source / gpa /
    education_level / location). Lượt "Lead Insights Upgrade with Officer
    Rating" đã chuyển phần chấm điểm ấy sang ``lead_score`` — một giá trị được
    tính sẵn và lưu trên Lead — rồi cộng thêm thưởng theo đánh giá của officer.
    Docstring của hàm khai đúng công thức này kèm ví dụ.

    Các khoá cấu hình cũ vẫn tồn tại vì nơi TÍNH ``lead_score`` còn dùng chúng;
    sự tồn tại của khoá không chứng minh hàm này còn đọc chúng — và đó là lý do
    ca cũ đỏ bằng ``assert 16 == 40`` chứ không phải ``KeyError``.
    """
    score = insights_service._calculate_fit_score(mock_lead)

    diem_nen = mock_lead.lead_score or 0
    thuong = int(mock_lead.officer_rating) * 4
    assert score == min(diem_nen + thuong, 100)

    # Trần 100 được docstring khai tường minh: lead_score=90, rating=3 -> 100.
    lead_sat_tran = models.Lead(
        id=2, full_name="Cap", email="c@e.com", phone="1", unit_id=1,
        lead_score=90, officer_rating=3,
    )
    assert insights_service._calculate_fit_score(lead_sat_tran) == 100

    # Không có officer_rating thì chỉ còn lead_score.
    lead_khong_rating = models.Lead(
        id=3, full_name="NoRating", email="n@e.com", phone="1", unit_id=1,
        lead_score=60, officer_rating=None,
    )
    assert insights_service._calculate_fit_score(lead_khong_rating) == 60


def test_get_urgency_score_doc_gia_tri_da_tinh_san():
    """``urgency`` nay ĐỌC ``lead.cached_urgency_score``, không tự tính.

    Hàm cũ ``_calculate_urgency_score(lead, timeline)`` đã bị thay bằng
    ``_get_urgency_score(lead)``. Công thức (task quá hạn, hoạt động trong 24h,
    thứ tự giai đoạn, số ngày im lặng) chuyển sang ``lead_cache_service`` để
    điểm hiển thị cho officer luôn khớp giá trị lưu trên Lead — docstring của
    hàm nêu rõ mục đích ấy.

    Vì thế ca này KHÔNG dựng lại timeline: dựng timeline để suy ra một con số
    mà hàm không còn đọc là kiểm một phép tính đã chuyển đi nơi khác.
    """
    lead_co_diem = models.Lead(
        id=4, full_name="Cached", email="ca@e.com", phone="1", unit_id=1,
        cached_urgency_score=42,
    )
    assert insights_service._get_urgency_score(lead_co_diem) == 42

    # Chưa có giá trị cache thì trả 0, không nổ.
    lead_chua_cache = models.Lead(
        id=5, full_name="NoCache", email="nc@e.com", phone="1", unit_id=1,
        cached_urgency_score=None,
    )
    assert insights_service._get_urgency_score(lead_chua_cache) == 0

    # Tên cũ phải KHÔNG còn tồn tại — nếu nó quay lại, hai nguồn tính urgency
    # sẽ cùng sống và trôi khỏi nhau.
    assert not hasattr(insights_service, "_calculate_urgency_score")


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
    # Hàm urgency đã đổi tên: `_calculate_urgency_score` -> `_get_urgency_score`.
    # Patch tên cũ chỉ tạo ra một thuộc tính mới trên module rồi bị mocker gỡ
    # lúc teardown — sản phẩm không hề gọi tới nó.
    mocker.patch(
        "app.services.insights_service._get_urgency_score", return_value=50
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
