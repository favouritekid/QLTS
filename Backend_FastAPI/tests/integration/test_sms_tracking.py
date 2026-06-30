# tests/integration/test_sms_tracking.py
"""
Integration test PR-5 (SMS Tracking / Landing / Reports / Opt-out).

Phủ: /r/{code} resolve + ghi click (qlts_hosted→/lp; bot vs human; invalid/
unknown→404), landing read-only (no PII + already_opted_out), opt-out công khai
idempotent, report click + CTR, dashboard, opt-out admin (manual + list + dup).

Lấy raw code bằng decrypt token_ciphertext (dev Fernet key). Handoff mô phỏng
bằng SQL vì PR-4 không có ở nhánh này. Chạy one-off container (CLAUDE.md).
"""
from httpx import AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.utils.sms_token import decrypt_code

API = "/api/sms"
PUB = "/api/public/sms"
_GRANT = {
    "event_type": "granted",
    "occurred_at": "2026-05-01T00:00:00+07:00",
    "basis": "signed_form",
    "disclosure_version": "v1",
    "proof_reference": "ho-so/ref",
}
# UA người thật (không chứa token scanner) vs UA bot.
_UA_HUMAN = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 "
    "Safari/604.1"
)
_UA_BOT = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"


async def _mk_group(client, h, name="Track Nhom"):
    r = await client.post(
        f"{API}/contact-groups", json={"name": name, "group_type": "custom"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _mk_contact(client, h, name, phone):
    r = await client.post(
        f"{API}/contacts", json={"full_name": name, "phone": phone}, headers=h
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    rc = await client.post(
        f"{API}/contacts/{cid}/consent-events", json=_GRANT, headers=h
    )
    assert rc.status_code == 201, rc.text
    return cid


async def _built_campaign(client, h, phone="0981234567"):
    """group + 1 contact granted + campaign có {link} + build + mô phỏng handoff.
    Trả (campaign_id, raw_code, phone_normalized)."""
    gid = await _mk_group(client, h)
    await _mk_contact(client, h, "Phu huynh A", phone)
    await client.post(
        f"{API}/contacts/1/groups", json={"group_id": gid}, headers=h
    )
    r = await client.post(
        f"{API}/campaigns",
        json={
            "name": "Track QA",
            "sms_template": "Chao {full_name}, xem {link}",
            "landing_headline": "Tuyển sinh 2026",
            "landing_body": "Thông tin tuyển sinh chi tiết.",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": gid}, headers=h
    )
    rb = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert rb.status_code == 200, rb.text
    # Lấy raw code + mô phỏng handoff (past để không bị 'instant_after_send').
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT id, token_ciphertext, token_key_version, "
                    "phone_normalized_snapshot FROM sms_campaign_recipient "
                    "WHERE campaign_id=:c LIMIT 1"
                ),
                {"c": cid},
            )
        ).first()
        await s.execute(
            text(
                "UPDATE sms_campaign_recipient SET handed_off_at = now() - "
                "interval '1 hour' WHERE campaign_id=:c"
            ),
            {"c": cid},
        )
        await s.commit()
    code = decrypt_code(row[1], row[2])
    assert code, "decrypt token thất bại"
    return cid, code, row[3]


# ---------------------------------------------------------------------
# /r/{code} resolve + click
# ---------------------------------------------------------------------
async def test_resolve_human_click_and_redirect(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    cid, code, _phone = await _built_campaign(client, h)
    res = await client.get(
        f"/r/{code}", headers={"User-Agent": _UA_HUMAN}, follow_redirects=False
    )
    assert res.status_code == 302, res.text
    assert res.headers["location"] == f"/lp/{code}"
    assert res.headers.get("cache-control") == "no-store"
    async with AsyncSessionLocal() as s:
        rec = (
            await s.execute(
                text(
                    "SELECT raw_click_count, human_click_count, "
                    "first_human_clicked_at FROM sms_campaign_recipient "
                    "WHERE campaign_id=:c"
                ),
                {"c": cid},
            )
        ).first()
        bot = (
            await s.execute(
                text(
                    "SELECT is_suspected_bot FROM sms_click_event ORDER BY id "
                    "DESC LIMIT 1"
                )
            )
        ).scalar()
    assert rec[0] == 1 and rec[1] == 1 and rec[2] is not None
    assert bot is False


async def test_resolve_bot_not_counted_human(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    cid, code, _ = await _built_campaign(client, h)
    res = await client.get(
        f"/r/{code}", headers={"User-Agent": _UA_BOT}, follow_redirects=False
    )
    assert res.status_code == 302
    async with AsyncSessionLocal() as s:
        rec = (
            await s.execute(
                text(
                    "SELECT raw_click_count, human_click_count FROM "
                    "sms_campaign_recipient WHERE campaign_id=:c"
                ),
                {"c": cid},
            )
        ).first()
        reason = (
            await s.execute(
                text(
                    "SELECT bot_reason FROM sms_click_event ORDER BY id DESC "
                    "LIMIT 1"
                )
            )
        ).scalar()
    assert rec[0] == 1 and rec[1] == 0  # raw tăng, human KHÔNG
    assert reason == "known_scanner_ua"


async def test_resolve_invalid_and_unknown_404(
    client: AsyncClient, admin_token_headers: dict
):
    # sai charset/length
    assert (
        await client.get("/r/xx", follow_redirects=False)
    ).status_code == 404
    # đúng format base62×9 nhưng không khớp recipient
    assert (
        await client.get("/r/ABCdef123", follow_redirects=False)
    ).status_code == 404


# ---------------------------------------------------------------------
# Landing + opt-out công khai
# ---------------------------------------------------------------------
async def test_landing_and_public_optout_idempotent(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    cid, code, phone = await _built_campaign(client, h)
    # landing read-only, KHÔNG lộ PII
    lr = await client.get(f"{PUB}/landing/{code}")
    assert lr.status_code == 200, lr.text
    body = lr.json()
    assert body["headline"] == "Tuyển sinh 2026"
    assert body["already_opted_out"] is False
    assert phone not in lr.text  # KHÔNG lộ số điện thoại recipient
    assert lr.headers.get("cache-control") == "no-store"

    # opt-out lần 1
    o1 = await client.post(f"{PUB}/opt-out", json={"code": code})
    assert o1.status_code == 200 and o1.json()["already_opted_out"] is False
    # opt-out lần 2 → idempotent
    o2 = await client.post(f"{PUB}/opt-out", json={"code": code})
    assert o2.json()["already_opted_out"] is True
    # landing lại → đã opt-out
    lr2 = await client.get(f"{PUB}/landing/{code}")
    assert lr2.json()["already_opted_out"] is True
    # DB có opt-out source landing_optout
    async with AsyncSessionLocal() as s:
        src = (
            await s.execute(
                text(
                    "SELECT source FROM sms_opt_out WHERE phone_normalized=:p"
                ),
                {"p": phone},
            )
        ).scalar()
    assert src == "landing_optout"


# ---------------------------------------------------------------------
# Reports + dashboard
# ---------------------------------------------------------------------
async def test_report_clicks_and_dashboard(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    cid, code, _ = await _built_campaign(client, h)
    await client.get(
        f"/r/{code}", headers={"User-Agent": _UA_HUMAN}, follow_redirects=False
    )
    # report clicks
    rep = await client.get(
        f"{API}/reports/clicks?granularity=day&campaign_id={cid}", headers=h
    )
    assert rep.status_code == 200, rep.text
    rb = rep.json()
    assert rb["total_clicks"] == 1 and rb["human_clicks"] == 1
    assert rb["distinct_contacts_clicked"] == 1
    assert rb["recipients_handed_off"] == 1
    assert rb["ctr_percent"] == 100.0
    assert len(rb["buckets"]) == 1

    # dashboard
    dash = await client.get(f"{API}/campaigns/{cid}/dashboard", headers=h)
    assert dash.status_code == 200, dash.text
    db = dash.json()
    assert db["ctr_percent"] == 100.0
    assert db["recipients_handed_off"] == 1
    assert db["has_link"] is True
    assert len(db["clickers"]) == 1
    assert db["clickers"][0]["human_click_count"] == 1


# ---------------------------------------------------------------------
# Opt-out admin
# ---------------------------------------------------------------------
async def test_admin_manual_optout_and_list(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    r = await client.post(
        f"{API}/opt-out/manual",
        json={"phone": "0987654321", "source": "phone_call", "reason": "goi dien"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["phone_normalized"] == "0987654321"
    # trùng → 409
    r2 = await client.post(
        f"{API}/opt-out/manual", json={"phone": "0987654321"}, headers=h
    )
    assert r2.status_code == 409
    # số ≥8 ký tự (qua schema) nhưng KHÔNG phải di động VN → service 400
    r3 = await client.post(
        f"{API}/opt-out/manual", json={"phone": "0123456789"}, headers=h
    )
    assert r3.status_code == 400
    # list
    lst = await client.get(f"{API}/opt-out", headers=h)
    assert lst.status_code == 200
    assert any(
        it["phone_normalized"] == "0987654321" for it in lst.json()["items"]
    )
