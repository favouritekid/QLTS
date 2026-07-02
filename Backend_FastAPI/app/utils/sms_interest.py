# app/utils/sms_interest.py
"""
Công thức `interest_score` Phase 2 (§16.10-P2-Q2 / §18.F, ĐÃ CHỐT):

    interest_score = normalize( Σ_view  dwell_factor(v) × recency_weight(v) )
      dwell_factor(s)   = min(s / DWELL_CAP, 1.0)     # cap → phiên dài không vô hạn
      recency_weight(t) = exp(-Δdays / HALF_LIFE)     # ưu tiên gần đây
      normalize(x)      = x / (x + K)                  # squash 0–1

Pure Python (KHÔNG import fastapi/sqlalchemy) — nhận list view + tham số config,
trả float ∈ [0,1). Tần suất (frequency) tự gấp vào vì cộng dồn theo từng view;
dwell = cường độ (capped chống gian lận); recency = độ mới.

Nguồn: Dynamic Yield affinity + Dotdigital weighting curve. KHÔNG ML.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §18.F.
"""
import math
from datetime import datetime, timezone
from typing import Iterable, Tuple


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def dwell_factor(dwell_seconds: int, cap: int) -> float:
    """min(s / cap, 1.0). cap ≥ 1 (config ge=1); guard chia 0 phòng lỗi cấu hình."""
    if cap <= 0:
        return 1.0 if dwell_seconds > 0 else 0.0
    return min(max(dwell_seconds, 0) / cap, 1.0)


def recency_weight(viewed_at: datetime, now: datetime, half_life_days: int) -> float:
    """exp(-Δdays / half_life). Δdays clamp ≥ 0 (view 'tương lai' do lệch đồng
    hồ → weight 1.0, không >1). half_life ≥ 1 (config)."""
    delta_days = (_aware(now) - _aware(viewed_at)).total_seconds() / 86400.0
    if delta_days <= 0:
        return 1.0
    hl = half_life_days if half_life_days > 0 else 1
    return math.exp(-delta_days / hl)


def normalize(x: float, k: float) -> float:
    """x / (x + K); K > 0 (config gt=0). x ≥ 0 → kết quả ∈ [0,1)."""
    denom = x + k
    if denom <= 0:
        return 0.0
    return x / denom


def compute_interest_score(
    views: Iterable[Tuple[int, datetime]],
    now: datetime,
    *,
    dwell_cap: int,
    half_life_days: int,
    k: float,
) -> float:
    """Tính interest_score từ MỌI view (dwell_seconds, viewed_at) của 1 cặp
    (contact, ngành). now = mốc tính recency (thường thời điểm cập nhật)."""
    raw = 0.0
    for dwell_seconds, viewed_at in views:
        raw += dwell_factor(dwell_seconds, dwell_cap) * recency_weight(
            viewed_at, now, half_life_days
        )
    return normalize(raw, k)
