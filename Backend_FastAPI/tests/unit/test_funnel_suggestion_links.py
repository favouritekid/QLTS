"""Regression tests for funnel suggestion action URLs.

These suggestions are rendered as deep-links into the leads page, so they must
only use query params the leads filter actually supports.
"""

from app.services.officer_service import generate_funnel_suggestions


def test_stage_based_suggestions_only_use_supported_filters():
    suggestions = generate_funnel_suggestions(
        funnel_stages=[
            {
                "stage_id": 12,
                "stage_name": "Tư vấn",
                "is_final_stage": False,
                "conversion_rate": 35.0,
                "velocity": {"avg_days": 8.0},
                "estimated_lost_revenue": {
                    "total_lost_revenue": 250_000_000,
                    "lost_leads_count": 4,
                },
            }
        ],
        config={
            "bottleneck_threshold": 50,
            "slow_stage_threshold_days": 5,
            "high_loss_threshold_vnd": 100_000_000,
            "max_suggestions": 10,
        },
    )

    stage_urls = {
        suggestion["type"]: suggestion["action_url"]
        for suggestion in suggestions
        if suggestion["type"] in {"bottleneck", "slow_stage", "high_loss"}
    }

    assert stage_urls == {
        "bottleneck": "/leads?stage=12",
        "slow_stage": "/leads?stage=12",
        "high_loss": "/leads?stage=12&status=rejected,unqualified",
    }
    assert all("outcome=" not in url for url in stage_urls.values())
    assert all("loss_reason=" not in url for url in stage_urls.values())

    stage_drilldowns = {
        suggestion["type"]: suggestion["drill_down"]
        for suggestion in suggestions
        if suggestion["type"] in {"bottleneck", "slow_stage", "high_loss"}
    }
    assert stage_drilldowns == {
        "bottleneck": {
            "target": "transitions",
            "exactness": "exact",
            "metric_key": "bottleneck",
            "filters": {"stage_id": "12"},
        },
        "slow_stage": {
            "target": "transitions",
            "exactness": "exact",
            "metric_key": "slow_stage",
            "filters": {"stage_id": "12"},
        },
        "high_loss": {
            "target": "transitions",
            "exactness": "exact",
            "metric_key": "high_loss",
            "filters": {
                "stage_id": "12",
                "outcome": "negative",
                "final_only": True,
            },
        },
    }


def test_loss_reason_suggestion_uses_supported_status_filter():
    suggestions = generate_funnel_suggestions(
        funnel_stages=[],
        aggregated_loss_breakdown=[
            {
                "reason_code": "OTHER",
                "count": 6,
                "percentage": 42.9,
            }
        ],
        config={
            "loss_reason_threshold_pct": 20,
            "max_suggestions": 10,
        },
    )

    loss_reason_suggestion = next(
        suggestion
        for suggestion in suggestions
        if suggestion["type"] == "loss_reason"
    )

    assert loss_reason_suggestion["action_url"] == "/leads?status=rejected,unqualified"
    assert "outcome=" not in loss_reason_suggestion["action_url"]
    assert "loss_reason=" not in loss_reason_suggestion["action_url"]
    assert loss_reason_suggestion["drill_down"] == {
        "target": "consultations",
        "exactness": "exact",
        "metric_key": "loss_reason",
        "filters": {
            "loss_reason_code": "OTHER",
            "consultation_kind": "human",
        },
    }
