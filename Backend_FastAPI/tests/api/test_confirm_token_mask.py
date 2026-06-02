"""PR1 Commit 7 anchor: the PUBLIC confirm-info endpoint masks the lead name
before CCCD verification and sets Referrer-Policy: no-referrer (A01 / A09).

The token sits in the URL, so GET /api/admissions/confirm/{token} is reachable
by anyone with the link; it must not echo the full name (PII) nor leak the
token via the Referer header.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.schemas.admission import ConfirmTokenInfoResponse, _mask_display_name


def test_mask_display_name_cases():
    masked = _mask_display_name("Nguyễn Văn An")
    assert masked != "Nguyễn Văn An"
    assert "Nguyễn" not in masked and "Văn" not in masked
    assert masked.count("•••") == 3  # one mask per word, length not leaked
    assert _mask_display_name("A") == "A"  # single char unchanged
    assert _mask_display_name("") == ""


def test_schema_masks_profile_name():
    r = ConfirmTokenInfoResponse(
        valid=True,
        expired=False,
        locked=False,
        already_used=False,
        attempts_remaining=3,
        profile_name="Trần Thị Bích",
    )
    assert r.profile_name != "Trần Thị Bích"
    assert "Trần" not in r.profile_name
    assert "•••" in r.profile_name


@pytest.mark.asyncio
async def test_confirm_get_masks_and_sets_referrer_policy(
    client: AsyncClient, monkeypatch
):
    async def _fake_get_token_info(db, token):
        return {
            "valid": True,
            "expired": False,
            "locked": False,
            "already_used": False,
            "attempts_remaining": 3,
            "profile_name": "Nguyễn Văn An",
            "expires_at": None,
        }

    monkeypatch.setattr(
        "app.routers.admissions.admission_service.get_token_info",
        _fake_get_token_info,
    )
    resp = await client.get("/api/admissions/confirm/sometoken")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("referrer-policy") == "no-referrer"
    body = resp.json()
    assert body["profile_name"] != "Nguyễn Văn An"
    assert "Nguyễn" not in body["profile_name"]
    assert "•••" in body["profile_name"]
