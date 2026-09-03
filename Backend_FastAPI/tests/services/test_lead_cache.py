# tests/services/test_lead_cache.py
"""
Unit tests for lead_cache_service.calculate_urgency_score.

Pins the expected urgency score values for new leads to prevent
regressions where cached_urgency_score defaults to 50 (stale).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import lead_service
from app.services.lead_cache_service import calculate_urgency_score


class TestCalculateUrgencyScore:
    """Pure-function tests for calculate_urgency_score."""

    def test_new_lead_low_score(self):
        """New lead (0 consultations, just created) with score < 70 → 55."""
        result = calculate_urgency_score(
            days_since_contact=0,
            lead_score=50,
            consultation_count=0,
            overdue_days=0,
            is_final_stage=False,
        )
        # base(30) + never_contacted(25) = 55
        assert result == 55

    def test_new_lead_hot(self):
        """New hot lead (score >= 70, 0 consultations) → 70."""
        result = calculate_urgency_score(
            days_since_contact=0,
            lead_score=85,
            consultation_count=0,
            overdue_days=0,
            is_final_stage=False,
        )
        # base(30) + hot(15) + never_contacted(25) = 70
        assert result == 70

    def test_contacted_lead_no_urgency(self):
        """Lead contacted today, no overdue, low score → 30 (base only)."""
        result = calculate_urgency_score(
            days_since_contact=0,
            lead_score=30,
            consultation_count=1,
            overdue_days=0,
            is_final_stage=False,
        )
        assert result == 30

    def test_inactivity_penalty_caps_at_45(self):
        """Inactivity penalty maxes at 45 (15+ days)."""
        result = calculate_urgency_score(
            days_since_contact=20,
            lead_score=30,
            consultation_count=1,
            overdue_days=0,
            is_final_stage=False,
        )
        # base(30) + inactivity(min(20*3, 45)=45) = 75
        assert result == 75

    def test_overdue_penalty_caps_at_30(self):
        """Overdue penalty maxes at 30 (6+ days)."""
        result = calculate_urgency_score(
            days_since_contact=0,
            lead_score=30,
            consultation_count=1,
            overdue_days=10,
            is_final_stage=False,
        )
        # base(30) + overdue(min(10*5, 30)=30) = 60
        assert result == 60

    def test_final_stage_reduction(self):
        """Final stage subtracts 50, clamped to 0."""
        result = calculate_urgency_score(
            days_since_contact=0,
            lead_score=30,
            consultation_count=1,
            overdue_days=0,
            is_final_stage=True,
        )
        # base(30) - final(50) = -20 → clamped to 0
        assert result == 0

    def test_score_clamped_to_100(self):
        """Score never exceeds 100 even with all bonuses."""
        result = calculate_urgency_score(
            days_since_contact=30,
            lead_score=90,
            consultation_count=0,
            overdue_days=15,
            is_final_stage=False,
        )
        # base(30) + inactivity(45) + hot(15) + never_contacted(25) + overdue(30) = 145 → 100
        assert result == 100

    def test_default_50_is_not_valid_for_new_lead(self):
        """The model default of 50 should NEVER be the correct value for a new lead."""
        low_score = calculate_urgency_score(
            days_since_contact=0, lead_score=0,
            consultation_count=0, overdue_days=0, is_final_stage=False,
        )
        hot_score = calculate_urgency_score(
            days_since_contact=0, lead_score=70,
            consultation_count=0, overdue_days=0, is_final_stage=False,
        )
        assert low_score != 50, "Model default 50 must not match real urgency for new leads"
        assert hot_score != 50


class TestImportUrgencyInitialization:
    """Import flow should populate cached_urgency_score before bulk insert."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("score", "expected_urgency", "expected_hot"),
        [
            (50, 55, False),
            (85, 70, True),
        ],
    )
    async def test_import_populates_cached_urgency_score_before_insert(
        self,
        score: int,
        expected_urgency: int,
        expected_hot: bool,
    ):
        repo = AsyncMock()
        repo.check_batch_email_conflict = AsyncMock(return_value=set())
        repo.check_batch_phone_conflict = AsyncMock(return_value=set())
        repo.register_phone_identities = AsyncMock()

        captured = {}

        async def _bulk_insert_leads(batch):
            captured["batch"] = batch
            # Hợp đồng: mỗi hàng TỰ MÔ TẢ ``(id, phone, phone2)`` — đó là
            # thứ khiến chỗ gọi không phải ghép id với SĐT theo vị trí.
            # Mock phải giữ đúng hình dạng ấy, nếu không nó khoá một hợp
            # đồng đã chết và bản vá thật sẽ vỡ ở đây thay vì ở sản phẩm.
            return [
                (101 + i, d.get("phone"), d.get("phone2"))
                for i, d in enumerate(batch)
            ]

        repo.bulk_insert_leads.side_effect = _bulk_insert_leads

        db = AsyncMock()
        nested_tx = AsyncMock()
        nested_tx.__aenter__.return_value = None
        nested_tx.__aexit__.return_value = None
        db.begin_nested = MagicMock(return_value=nested_tx)
        db.flush = AsyncMock()

        initial_status = SimpleNamespace(
            id="sts01",
            stage_id="stg01",
            legacy_status="new",
        )
        phone = "0909.667.001" if not expected_hot else "0909.667.002"

        csv_content = (
            "full_name,email,phone,source,unit_id\n"
            f"Import Urgency {score},import_urgency_{score}@example.com,"
            f"{phone},website,1001\n"
        )

        with patch(
            "app.services.lead_service.StatusHelper.get_initial_status",
            new=AsyncMock(return_value=initial_status),
        ), patch(
            "app.services.lead_service.LeadRepository",
            return_value=repo,
        ), patch(
            "app.services.lead_service.calculate_lead_score",
            new=AsyncMock(return_value=score),
        ):
            result, callback = await lead_service.import_leads_from_file_content(
                file_content=csv_content.encode("utf-8"),
                filename="urgency_import.csv",
                db=db,
                default_unit_id=1001,
            )

        assert result.successful_imports == 1
        assert result.failed_imports == 0
        assert result.created_lead_ids == [101]
        assert callback is not None

        inserted = captured["batch"][0]
        assert inserted["lead_score"] == score
        assert inserted["is_hot_lead"] is expected_hot
        assert inserted["cached_urgency_score"] == expected_urgency
        assert inserted["cached_urgency_score"] != 50
