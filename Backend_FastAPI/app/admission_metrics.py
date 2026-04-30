# app/admission_metrics.py
"""Prometheus metrics for admission workflows.

Mirrors the per-domain pattern established in ``socket_metrics.py``.
Exposed on ``GET /metrics`` (see ``app/main.py``).
"""
from prometheus_client import Counter

# Quota enforcement skip counter — fires when ``_check_quota_for_offering``
# bails out before counting seats. Read these labels alongside ADM-026
# audit logs to spot data drift (e.g. a wave of profiles whose lead has
# no offering_id, which would silently bypass the cap).
#
# Reasons currently emitted:
#   * missing_offering_id  — profile.lead.offering_id IS NULL
admission_quota_skip_total = Counter(
    "admission_quota_skip_total",
    "Admission quota enforcement skipped (count by reason)",
    ["reason"],
)
