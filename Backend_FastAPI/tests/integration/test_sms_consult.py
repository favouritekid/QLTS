# tests/integration/test_sms_consult.py
"""
Integration test PR-7 P2-3 (SMS consult officer §16.5/§16.7).

Phủ: tạo consult link cho lead (match/tạo contact từ phone) → resolve /r/{code}
(nhánh consult) 302 + click → landing consult (programs, no campaign headline) →
session source_type='consult' → program-view+heartbeat → interest → lead
interests (qua contact match). IDOR officer (lead người khác → 404). Auth.

Chạy one-off container (CLAUDE.md — fixture chain officer/lead).
"""
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from tests.fixtures.constants import TestOrgData

API = "/api/sms"
PUB = "/api/public/sms"
_UA_HUMAN = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/16.0 Mobile Safari/604.1"
)


async def _mk_lead(phone: str, officer_id=None) -> int:
    """Tạo 1 lead trực tiếp (assigned officer nếu có). Trả lead_id."""
    async with AsyncSessionLocal() as s:
        lead = models.Lead(
            full_name="QA Consult Lead",
            phone=phone,
            source="test",
            unit_id=TestOrgData.UNIT_1["id"],
            status=INITIAL_LEAD_STATUS_ID,
            consultation_status_id=INITIAL_LEAD_STATUS_ID,
            pipeline_stage_id="STAGE_A",
            assigned_officer_id=officer_id,
            assigned_at=datetime.now(timezone.utc) if officer_id else None,
        )
        s.add(lead)
        await s.flush()
        lid = lead.id
        await s.commit()
    return lid


# ---------------------------------------------------------------------
# Flow đầy đủ: consult link → /r → landing → session → interest → lead interests
# ---------------------------------------------------------------------
async def test_consult_full_flow(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    lead_id = await _mk_lead("0987755111")

    # 1) admin tạo consult link
    r = await client.post(f"{API}/leads/{lead_id}/consult-link", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    code = body["code"]
    assert body["url"].endswith(f"/r/{code}")
    contact_id = body["contact_id"]
    assert body["consult_link_id"] > 0

    # DB: consult link + contact tạo (consent unknown, source lead_consult)
    async with AsyncSessionLocal() as s:
        cl = (
            await s.execute(
                text(
                    "SELECT lead_id, contact_id, landing_type FROM "
                    "sms_consult_link WHERE id=:i"
                ),
                {"i": body["consult_link_id"]},
            )
        ).first()
        ct = (
            await s.execute(
                text(
                    "SELECT source_label, marketing_consent_status FROM "
                    "sms_contact WHERE id=:c"
                ),
                {"c": contact_id},
            )
        ).first()
    assert cl[0] == lead_id and cl[1] == contact_id and cl[2] == "qlts_hosted"
    assert ct[0] == "lead_consult" and ct[1] == "unknown"

    # 2) /r/{code} → 302 /lp + consult click ghi (nhánh consult của resolve)
    res = await client.get(
        f"/r/{code}", headers={"User-Agent": _UA_HUMAN}, follow_redirects=False
    )
    assert res.status_code == 302
    assert res.headers["location"] == f"/lp/{code}"
    async with AsyncSessionLocal() as s:
        cc = (
            await s.execute(
                text(
                    "SELECT raw_click_count, human_click_count FROM "
                    "sms_consult_link WHERE id=:i"
                ),
                {"i": body["consult_link_id"]},
            )
        ).first()
    assert cc[0] == 1 and cc[1] == 1

    # 3) landing consult: programs có, headline null (no campaign)
    lr = await client.get(f"{PUB}/landing/{code}")
    assert lr.status_code == 200, lr.text
    lb = lr.json()
    assert lb["headline"] is None
    assert isinstance(lb["programs"], list) and len(lb["programs"]) >= 1

    # 4) session (source consult) → program-view → heartbeat
    token = (
        await client.post(
            f"{PUB}/landing/{code}/session",
            headers={"User-Agent": _UA_HUMAN},
        )
    ).json()["session_token"]
    async with AsyncSessionLocal() as s:
        srow = (
            await s.execute(
                text(
                    "SELECT source_type, consult_link_id, contact_id FROM "
                    "sms_landing_session WHERE contact_id=:c"
                ),
                {"c": contact_id},
            )
        ).first()
    assert srow[0] == "consult" and srow[1] == body["consult_link_id"]
    assert srow[2] == contact_id

    vid = (
        await client.post(
            f"{PUB}/landing/{code}/program-view",
            json={"session_token": token, "major_program_id": 1},
            headers={"User-Agent": _UA_HUMAN},
        )
    ).json()["program_view_id"]
    hb = await client.post(
        f"{PUB}/landing/{code}/heartbeat",
        json={"session_token": token, "program_view_id": vid, "dwell_seconds": 20},
        headers={"User-Agent": _UA_HUMAN},
    )
    assert hb.status_code == 200

    # 5) lead interests (qua contact match phone) — thấy ngành 1
    li = await client.get(f"{API}/leads/{lead_id}/interests", headers=h)
    assert li.status_code == 200, li.text
    lij = li.json()
    assert lij["lead_id"] == lead_id and lij["contact_id"] == contact_id
    assert len(lij["items"]) == 1 and lij["items"][0]["major_program_id"] == 1


async def test_consult_reuses_existing_contact(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    """Contact đã tồn tại theo phone → consult link DÙNG LẠI (không tạo trùng)."""
    h = admin_token_headers
    # tạo contact trước qua API
    rc = await client.post(
        f"{API}/contacts",
        json={"full_name": "Existing", "phone": "0987755222"},
        headers=h,
    )
    assert rc.status_code == 201, rc.text
    existing_cid = rc.json()["id"]
    lead_id = await _mk_lead("0987755222")
    r = await client.post(f"{API}/leads/{lead_id}/consult-link", headers=h)
    assert r.status_code == 200
    assert r.json()["contact_id"] == existing_cid  # dùng lại, không tạo mới


async def test_lead_interests_empty_no_contact(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    lead_id = await _mk_lead("0987755333")
    li = await client.get(f"{API}/leads/{lead_id}/interests", headers=h)
    assert li.status_code == 200
    assert li.json()["contact_id"] is None and li.json()["items"] == []


async def test_consult_missing_lead_404(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    assert (
        await client.post(f"{API}/leads/999999/consult-link", headers=h)
    ).status_code == 404
    assert (
        await client.get(f"{API}/leads/999999/interests", headers=h)
    ).status_code == 404


async def test_consult_officer_idor(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies,
):
    """Officer: lead CỦA MÌNH → 200; lead officer KHÁC (assigned=None) → 404."""
    oh = officer_token_headers
    own = await _mk_lead("0987755444", officer_id=officer_user_in_db["id"])
    other = await _mk_lead("0987755555", officer_id=None)  # không giao officer

    ok = await client.post(f"{API}/leads/{own}/consult-link", headers=oh)
    assert ok.status_code == 200, ok.text  # Casbin officer policy + IDOR pass

    idor = await client.post(f"{API}/leads/{other}/consult-link", headers=oh)
    assert idor.status_code == 404  # ngoài phạm vi officer → 404 (không lộ)


async def test_consult_requires_auth(client: AsyncClient):
    assert (
        await client.post(f"{API}/leads/1/consult-link")
    ).status_code == 401
    assert (
        await client.get(f"{API}/leads/1/interests")
    ).status_code == 401
