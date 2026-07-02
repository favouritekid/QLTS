# tests/integration/test_sms_engagement.py
"""
Integration test PR-7 P2-2 (SMS Phase 2 — deep engagement / đo quan tâm ngành).

Phủ:
- Landing GET +danh mục ngành (no session).
- Flow session → program-view → heartbeat: ghi dwell + cập nhật aggregate
  interest (§18.F), rồi hồ sơ sở thích contact (admin) + report ngành nóng.
- Clamp dwell thổi phồng theo wall-clock.
- Bot session bị loại khỏi interest + report.
- Ranking nhiều ngành theo tổng dwell desc.
- 404 generic: code sai, session token sai, ngành không tồn tại.
- Admin endpoint yêu cầu auth.

Lấy raw code qua decrypt token_ciphertext (dev Fernet). Handoff mô phỏng bằng
SQL. Chạy one-off container (CLAUDE.md — suite fan-out fixture nặng).
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
_UA_HUMAN = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 "
    "Safari/604.1"
)
_UA_BOT = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
_H = {"User-Agent": _UA_HUMAN}


async def _mk_group(client, h, name="Eng Nhom"):
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


async def _setup(client, h, phone="0981234567"):
    """group + 1 contact granted + campaign {link} + build + handoff (past).
    Trả (campaign_id, raw_code, contact_id)."""
    gid = await _mk_group(client, h)
    contact_id = await _mk_contact(client, h, "Phu huynh A", phone)
    await client.post(
        f"{API}/contacts/{contact_id}/groups", json={"group_id": gid}, headers=h
    )
    r = await client.post(
        f"{API}/campaigns",
        json={
            "name": "Eng QA",
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
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT token_ciphertext, token_key_version FROM "
                    "sms_campaign_recipient WHERE campaign_id=:c LIMIT 1"
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
    code = decrypt_code(row[0], row[1])
    assert code, "decrypt token thất bại"
    return cid, code, contact_id


async def _seed_second_major(new_id=9002):
    """Ngành #2 active (dùng chung unit với ngành #1 seed_lead_dependencies).
    id tường minh vì test DB dùng create_all() → sequence major_program chưa
    sync (auto-id sẽ đụng id=1 seeded). Trả id ngành mới."""
    async with AsyncSessionLocal() as s:
        unit_id = (
            await s.execute(
                text("SELECT unit_id FROM major_program WHERE id=1")
            )
        ).scalar()
        await s.execute(
            text(
                "INSERT INTO major_program "
                "(id, name, code, degree_level, is_active, unit_id) VALUES "
                "(:i, 'Test Major 2', 'TM2', 'Cao đẳng', true, :u)"
            ),
            {"i": new_id, "u": unit_id},
        )
        await s.commit()
    return new_id


# ---------------------------------------------------------------------
# Landing +danh mục ngành
# ---------------------------------------------------------------------
async def test_landing_includes_active_programs(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    _cid, code, _contact = await _setup(client, h)
    lr = await client.get(f"{PUB}/landing/{code}")
    assert lr.status_code == 200, lr.text
    body = lr.json()
    assert body["headline"] == "Tuyển sinh 2026"
    progs = body["programs"]
    assert isinstance(progs, list) and len(progs) >= 1
    assert any(p["id"] == 1 and p["code"] == "TM1" for p in progs)


# ---------------------------------------------------------------------
# Flow đầy đủ: session → program-view → heartbeat → interest
# ---------------------------------------------------------------------
async def test_session_view_heartbeat_updates_interest(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    _cid, code, contact_id = await _setup(client, h)

    # 1) tạo session (UA người thật)
    rs = await client.post(f"{PUB}/landing/{code}/session", headers=_H)
    assert rs.status_code == 200, rs.text
    token = rs.json()["session_token"]
    assert token and len(token) >= 16
    assert rs.headers.get("cache-control") == "no-store"

    # 2) mở trang ngành #1
    rv = await client.post(
        f"{PUB}/landing/{code}/program-view",
        json={"session_token": token, "major_program_id": 1},
        headers=_H,
    )
    assert rv.status_code == 200, rv.text
    view_id = rv.json()["program_view_id"]
    assert rv.json()["sequence_no"] == 1

    # 3) heartbeat cộng dwell (100s < cap 180) — view mới nên wall-clock cho phép
    #    tối đa vài giây + grace(30) → 100 sẽ bị clamp về ~30. Test clamp riêng;
    #    ở đây kiểm dwell > 0 + interest được tạo.
    hb = await client.post(
        f"{PUB}/landing/{code}/heartbeat",
        json={"session_token": token, "program_view_id": view_id,
              "dwell_seconds": 25},
        headers=_H,
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["dwell_seconds"] == 25  # ≤ grace 30 → không clamp
    assert hb.json()["active_seconds"] == 25

    # DB: program_view + aggregate interest
    async with AsyncSessionLocal() as s:
        pv = (
            await s.execute(
                text(
                    "SELECT dwell_seconds, major_program_id, contact_id FROM "
                    "sms_program_view WHERE id=:i"
                ),
                {"i": view_id},
            )
        ).first()
        interest = (
            await s.execute(
                text(
                    "SELECT view_count, total_dwell_seconds, interest_score "
                    "FROM sms_contact_program_interest WHERE contact_id=:c "
                    "AND major_program_id=1"
                ),
                {"c": contact_id},
            )
        ).first()
    assert pv[0] == 25 and pv[1] == 1 and pv[2] == contact_id
    assert interest is not None
    assert interest[0] == 1 and interest[1] == 25
    assert interest[2] > 0.0  # score dương

    # 4) hồ sơ sở thích contact (admin)
    ci = await client.get(f"{API}/contacts/{contact_id}/interests", headers=h)
    assert ci.status_code == 200, ci.text
    items = ci.json()["items"]
    assert len(items) == 1
    assert items[0]["major_program_id"] == 1
    assert items[0]["total_dwell_seconds"] == 25
    assert items[0]["interest_score"] > 0.0


# ---------------------------------------------------------------------
# Clamp dwell thổi phồng theo wall-clock
# ---------------------------------------------------------------------
async def test_heartbeat_clamps_inflated_dwell(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    _cid, code, _contact = await _setup(client, h)
    token = (
        await client.post(f"{PUB}/landing/{code}/session", headers=_H)
    ).json()["session_token"]
    view_id = (
        await client.post(
            f"{PUB}/landing/{code}/program-view",
            json={"session_token": token, "major_program_id": 1},
            headers=_H,
        )
    ).json()["program_view_id"]
    # client báo dwell khổng lồ (dưới trần schema 86400) ngay sau khi mở view
    # → clamp về ~grace(30)s theo wall-clock
    hb = await client.post(
        f"{PUB}/landing/{code}/heartbeat",
        json={"session_token": token, "program_view_id": view_id,
              "dwell_seconds": 80000},
        headers=_H,
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["dwell_seconds"] <= 60  # wall-clock(≈0) + grace(30) + lag


# ---------------------------------------------------------------------
# Bot session KHÔNG cập nhật interest
# ---------------------------------------------------------------------
async def test_bot_session_excluded_from_interest(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    _cid, code, contact_id = await _setup(client, h)
    bot_ua = {"User-Agent": _UA_BOT}
    token = (
        await client.post(f"{PUB}/landing/{code}/session", headers=bot_ua)
    ).json()["session_token"]
    view_id = (
        await client.post(
            f"{PUB}/landing/{code}/program-view",
            json={"session_token": token, "major_program_id": 1},
            headers=bot_ua,
        )
    ).json()["program_view_id"]
    hb = await client.post(
        f"{PUB}/landing/{code}/heartbeat",
        json={"session_token": token, "program_view_id": view_id,
              "dwell_seconds": 20},
        headers=bot_ua,
    )
    assert hb.status_code == 200
    # dwell bot VẪN ghi (audit) nhưng interest KHÔNG được tạo cho bot
    async with AsyncSessionLocal() as s:
        is_bot = (
            await s.execute(
                text("SELECT is_suspected_bot FROM sms_landing_session LIMIT 1")
            )
        ).scalar()
        interest = (
            await s.execute(
                text(
                    "SELECT count(*) FROM sms_contact_program_interest "
                    "WHERE contact_id=:c"
                ),
                {"c": contact_id},
            )
        ).scalar()
    assert is_bot is True
    assert interest == 0
    # report ngành nóng cũng loại bot → rỗng
    rep = await client.get(f"{API}/reports/program-interest", headers=h)
    assert rep.status_code == 200
    assert rep.json()["view_count_total"] == 0

    # ⭐ CHỐNG NHIỄM BOT (finding /review #1): giờ 1 phiên NGƯỜI THẬT của CÙNG
    # contact xem CÙNG ngành 1 → recompute interest KHÔNG được cộng dwell bot.
    htoken = (
        await client.post(f"{PUB}/landing/{code}/session", headers=_H)
    ).json()["session_token"]
    hview = (
        await client.post(
            f"{PUB}/landing/{code}/program-view",
            json={"session_token": htoken, "major_program_id": 1},
            headers=_H,
        )
    ).json()["program_view_id"]
    assert (
        await client.post(
            f"{PUB}/landing/{code}/heartbeat",
            json={"session_token": htoken, "program_view_id": hview,
                  "dwell_seconds": 15},
            headers=_H,
        )
    ).status_code == 200
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT view_count, total_dwell_seconds FROM "
                    "sms_contact_program_interest WHERE contact_id=:c "
                    "AND major_program_id=1"
                ),
                {"c": contact_id},
            )
        ).first()
    # CHỈ view người thật (15s) — KHÔNG có 20s của bot (nếu nhiễm sẽ =2 view/35s)
    assert row is not None
    assert row[0] == 1 and row[1] == 15


# ---------------------------------------------------------------------
# Report ngành nóng — ranking theo tổng dwell desc
# ---------------------------------------------------------------------
async def test_program_interest_report_ranking(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    cid, code, _contact = await _setup(client, h)
    major2 = await _seed_second_major()
    token = (
        await client.post(f"{PUB}/landing/{code}/session", headers=_H)
    ).json()["session_token"]

    async def _view_and_beat(major_id, dwell):
        vid = (
            await client.post(
                f"{PUB}/landing/{code}/program-view",
                json={"session_token": token, "major_program_id": major_id},
                headers=_H,
            )
        ).json()["program_view_id"]
        # nới wall-clock: đẩy viewed_at về quá khứ để dwell không bị clamp
        async with AsyncSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE sms_program_view SET viewed_at = now() - "
                    "interval '1 hour' WHERE id=:i"
                ),
                {"i": vid},
            )
            await s.commit()
        await client.post(
            f"{PUB}/landing/{code}/heartbeat",
            json={"session_token": token, "program_view_id": vid,
                  "dwell_seconds": dwell},
            headers=_H,
        )
        return vid

    await _view_and_beat(1, 30)        # ngành 1: 30s
    await _view_and_beat(major2, 120)  # ngành 2: 120s (nóng hơn)

    rep = await client.get(f"{API}/reports/program-interest", headers=h)
    assert rep.status_code == 200, rep.text
    body = rep.json()
    assert body["view_count_total"] == 2
    assert body["distinct_contacts_total"] == 1
    assert body["total_dwell_seconds"] == 150
    items = body["items"]
    assert len(items) == 2
    # rank tổng dwell desc → ngành 2 đứng đầu
    assert items[0]["major_program_id"] == major2
    assert items[0]["total_dwell_seconds"] == 120
    assert items[1]["major_program_id"] == 1
    # filter theo major_program_id
    rep1 = await client.get(
        f"{API}/reports/program-interest?major_program_id=1", headers=h
    )
    assert rep1.json()["view_count_total"] == 1
    assert len(rep1.json()["items"]) == 1


# ---------------------------------------------------------------------
# 404 / auth
# ---------------------------------------------------------------------
async def test_session_invalid_code_404(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    # code sai format
    assert (
        await client.post(f"{PUB}/landing/xx/session", headers=_H)
    ).status_code == 404
    # đúng format base62×9 nhưng không khớp recipient
    assert (
        await client.post(f"{PUB}/landing/ABCdef123/session", headers=_H)
    ).status_code == 404


async def test_program_view_invalid_token_and_program_404(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    h = admin_token_headers
    _cid, code, _contact = await _setup(client, h)
    token = (
        await client.post(f"{PUB}/landing/{code}/session", headers=_H)
    ).json()["session_token"]
    # session token sai → 404
    bad = await client.post(
        f"{PUB}/landing/{code}/program-view",
        json={"session_token": "wrong-token-xxxxxxxx", "major_program_id": 1},
        headers=_H,
    )
    assert bad.status_code == 404
    # ngành không tồn tại → 404
    nope = await client.post(
        f"{PUB}/landing/{code}/program-view",
        json={"session_token": token, "major_program_id": 999999},
        headers=_H,
    )
    assert nope.status_code == 404


async def test_engagement_admin_endpoints_require_auth(client: AsyncClient):
    assert (
        await client.get(f"{API}/reports/program-interest")
    ).status_code == 401
    assert (
        await client.get(f"{API}/contacts/1/interests")
    ).status_code == 401
