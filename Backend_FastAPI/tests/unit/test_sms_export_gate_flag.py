# tests/unit/test_sms_export_gate_flag.py
"""
Unit test cờ `can_export` (gate trạng thái khu Export/bàn giao).

Bối cảnh: FE trước đây tự suy diễn từ `campaign.status` với
CLOSED_STATUSES={handed_off, closed}. Bàn giao batch ĐẦU đẩy campaign sang
'handed_off' → FE ẩn luôn nút bàn giao của các nhà mạng còn lại, operator
tưởng đã xong. Sự cố thật chiến dịch #6 (13-07): 338/380 người nhận kẹt ở
'generated', báo cáo giấu 46 lượt click người thật.

Thuần logic, không chạm DB/HTTP.
"""
from types import SimpleNamespace

import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,build_revision,expected",
    [
        ("draft", 0, False),      # chưa build
        ("draft", 2, False),      # đổi nhóm sau build → phải build lại
        ("ready", 1, True),       # build xong, chưa export
        ("exported", 1, True),    # re-export
        # Bàn giao batch ĐẦU đẩy campaign sang 'handed_off' nhưng vẫn phải
        # export/bàn giao được cho các nhà mạng còn lại — ca gây sự cố #6.
        ("handed_off", 3, True),
        ("closed", 3, False),     # đã bàn giao hết → khoá
    ],
)
def test_can_export_flag(status, build_revision, expected):
    from app.services.sms_campaign_service import SmsCampaignService

    service = SmsCampaignService(db=None)
    campaign = SimpleNamespace(
        status=status,
        build_revision=build_revision,
        sms_template="[QC] Test {link}",
    )
    service._with_computed(campaign, group_count=1)
    assert campaign.can_export is expected


@pytest.mark.unit
def test_can_export_uses_single_source_of_truth():
    """Cờ hiển thị phải đọc CÙNG hằng với gate thật của export service —
    tránh drift kiểu 'FE nghĩ export được, BE trả 400' (và ngược lại)."""
    from app.services.sms_export_service import EXPORTABLE_CAMPAIGN_STATUS

    assert EXPORTABLE_CAMPAIGN_STATUS == {"ready", "exported", "handed_off"}
