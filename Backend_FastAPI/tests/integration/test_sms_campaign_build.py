# tests/integration/test_sms_campaign_build.py
"""
Integration test PR-3 (SMS Campaign Build BE).

Phủ: campaign CRUD + validation (biến lạ, external+{link}, allowlist host,
update-non-draft), group attach/detach, BUILD (dedupe snapshot + fail-closed
consent/opt-out filter + token triplet khi {link} + [QC]/optout trong
skeleton + over_limit gate + rebuild invalidate revision cũ), preflight,
attestation khớp build_revision.

Build nội bộ (token/skeleton/excluded_reason) verify trực tiếp qua SQL
(chưa expose recipient API tới PR-4). Chạy one-off container (CLAUDE.md).
"""
import re

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal

API = "/api/sms"
_GRANT = {
    "event_type": "granted",
    "occurred_at": "2026-05-01T00:00:00+07:00",
    "basis": "signed_form",
    "disclosure_version": "v1",
    "proof_reference": "ho-so/ref",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
async def _mk_group(client, h, name):
    res = await client.post(
        f"{API}/contact-groups",
        json={"name": name, "group_type": "custom"},
        headers=h,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _mk_contact(client, h, name, phone, granted=True):
    res = await client.post(
        f"{API}/contacts",
        json={"full_name": name, "phone": phone},
        headers=h,
    )
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    if granted:
        r = await client.post(
            f"{API}/contacts/{cid}/consent-events", json=_GRANT, headers=h
        )
        assert r.status_code == 201, r.text
    return cid


async def _add_to_group(client, h, cid, gid):
    res = await client.post(
        f"{API}/contacts/{cid}/groups", json={"group_id": gid}, headers=h
    )
    assert res.status_code == 201, res.text


async def _mk_campaign(client, h, template, **kw):
    body = {"name": kw.pop("name", "Chien dich QA"), "sms_template": template}
    body.update(kw)
    return await client.post(f"{API}/campaigns", json=body, headers=h)


async def _recipients(campaign_id):
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            text(
                "SELECT phone_normalized_snapshot AS phone, excluded_reason, "
                "token_hash, token_ciphertext, rendered_message_skeleton AS sk, "
                "group_ids_snapshot AS gids, build_revision AS rev, "
                "invalidated_at, is_over_limit, encoding "
                "FROM sms_campaign_recipient WHERE campaign_id=:c "
                "ORDER BY phone_normalized_snapshot, build_revision"
            ),
            {"c": campaign_id},
        )
        return [dict(r) for r in res.mappings().all()]


# ---------------------------------------------------------------------
# Campaign CRUD + validation
# ---------------------------------------------------------------------
async def test_campaign_crud_and_validation(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    # create + auto-slug
    res = await _mk_campaign(client, h, "Chao {name}, xem {link}",
                             name="Tuyen Sinh 2026")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == "tuyen-sinh-2026"
    assert body["has_link"] is True
    assert body["status"] == "draft"
    cid = body["id"]

    # get + list
    assert (await client.get(f"{API}/campaigns/{cid}", headers=h)).status_code == 200
    assert (await client.get(f"{API}/campaigns", headers=h)).json()["total"] >= 1

    # update draft OK
    res = await client.patch(
        f"{API}/campaigns/{cid}",
        json={"sms_template": "Xin chao {full_name}"},
        headers=h,
    )
    assert res.status_code == 200
    assert res.json()["has_link"] is False  # bỏ {link}

    # biến template lạ → 400
    res = await _mk_campaign(client, h, "Hi {foo}", name="X1")
    assert res.status_code == 400

    # external + thiếu {link} → 400
    res = await _mk_campaign(
        client, h, "Khong co link", name="X2",
        landing_type="external",
        landing_url="https://qlts.tnpc.edu.vn/landing",
    )
    assert res.status_code == 400

    # external host ngoài allowlist → 400
    res = await _mk_campaign(
        client, h, "Bam {link}", name="X3",
        landing_type="external", landing_url="https://evil.com/x",
    )
    assert res.status_code == 400

    # external hợp lệ (host allowlist + {link}) → 201
    res = await _mk_campaign(
        client, h, "Bam {link}", name="X4",
        landing_type="external",
        landing_url="https://qlts.tnpc.edu.vn/landing",
    )
    assert res.status_code == 201, res.text


# ---------------------------------------------------------------------
# Group attach/detach
# ---------------------------------------------------------------------
async def test_campaign_group_attach_detach(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    gid = await _mk_group(client, h, "Nhom QA G")
    cid = (await _mk_campaign(client, h, "Hi {name}", name="CG")).json()["id"]

    res = await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": gid}, headers=h
    )
    assert res.status_code == 201
    assert res.json()["group_count"] == 1

    # trùng → 409
    res = await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": gid}, headers=h
    )
    assert res.status_code == 409

    # detach
    res = await client.delete(
        f"{API}/campaigns/{cid}/groups/{gid}", headers=h
    )
    assert res.status_code == 204
    # detach lại → 404
    res = await client.delete(
        f"{API}/campaigns/{cid}/groups/{gid}", headers=h
    )
    assert res.status_code == 404


async def test_campaign_list_groups(
    client: AsyncClient, admin_token_headers: dict
):
    """GET /campaigns/{id}/groups liệt kê nhóm đã gắn + member_count (PR-6d)."""
    h = admin_token_headers
    g1 = await _mk_group(client, h, "LG Nhom 1")
    g2 = await _mk_group(client, h, "LG Nhom 2")
    c1 = await _mk_contact(client, h, "LG A", "0987000201")
    await _add_to_group(client, h, c1, g1)  # g1 có 1 thành viên
    cid = (await _mk_campaign(client, h, "Hi {name}", name="CLG")).json()["id"]

    # chưa gắn → rỗng
    res = await client.get(f"{API}/campaigns/{cid}/groups", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0

    for g in (g1, g2):
        await client.post(
            f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
        )

    res = await client.get(f"{API}/campaigns/{cid}/groups", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    by_id = {g["id"]: g for g in body["items"]}
    assert set(by_id) == {g1, g2}
    assert by_id[g1]["member_count"] == 1
    assert by_id[g2]["member_count"] == 0

    # detach g2 → còn 1
    await client.delete(f"{API}/campaigns/{cid}/groups/{g2}", headers=h)
    res = await client.get(f"{API}/campaigns/{cid}/groups", headers=h)
    assert res.json()["total"] == 1

    # campaign không tồn tại → 404
    res = await client.get(f"{API}/campaigns/999999999/groups", headers=h)
    assert res.status_code == 404


# ---------------------------------------------------------------------
# BUILD — dedupe + snapshot + fail-closed + token + skeleton
# ---------------------------------------------------------------------
async def test_build_dedupe_failclosed_token(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g1 = await _mk_group(client, h, "Nhom 1")
    g2 = await _mk_group(client, h, "Nhom 2")

    # granted, chỉ G1
    c1 = await _mk_contact(client, h, "Nguyen A", "0901000001", granted=True)
    await _add_to_group(client, h, c1, g1)
    # unknown (chưa consent), G1 → bị loại no_consent
    c2 = await _mk_contact(client, h, "Tran B", "0901000002", granted=False)
    await _add_to_group(client, h, c2, g1)
    # granted, ở CẢ G1 + G2 → dedupe 1 recipient, group_ids gồm cả 2
    c3 = await _mk_contact(client, h, "Le C", "0901000003", granted=True)
    await _add_to_group(client, h, c3, g1)
    await _add_to_group(client, h, c3, g2)
    # granted nhưng opt-out toàn cục → bị loại opted_out
    c4 = await _mk_contact(client, h, "Pham D", "0901000004", granted=True)
    await _add_to_group(client, h, c4, g1)
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO sms_opt_out (phone_normalized, source, observed_at) "
            "VALUES ('0901000004','manual', now())"))
        await s.commit()

    cid = (
        await _mk_campaign(client, h, "Chao {name}, xem {link}", name="Build1")
    ).json()["id"]
    for g in (g1, g2):
        await client.post(
            f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
        )

    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.status_code == 200, res.text
    rep = res.json()
    assert rep["build_revision"] == 1
    assert rep["status"] == "ready"
    assert rep["has_link"] is True
    assert rep["total"] == 4          # 4 phone unique (dedupe c3)
    assert rep["exportable"] == 2     # c1, c3
    assert rep["excluded_by_reason"].get("no_consent") == 1
    assert rep["excluded_by_reason"].get("opted_out") == 1

    rows = {r["phone"]: r for r in await _recipients(cid)}
    # c1 granted → exportable + token hex 64 + skeleton có [QC] + optout
    r1 = rows["0901000001"]
    assert r1["excluded_reason"] is None
    assert re.fullmatch(r"[0-9a-f]{64}", r1["token_hash"])
    assert r1["token_ciphertext"]
    assert r1["sk"].startswith("[QC]")
    assert "huy" in r1["sk"].lower() or "tu choi" in r1["sk"].lower()
    assert "__SMS_LINK__" in r1["sk"]   # sentinel, KHÔNG raw code
    # c2 unknown → no_consent + KHÔNG token
    r2 = rows["0901000002"]
    assert r2["excluded_reason"] == "no_consent"
    assert r2["token_hash"] is None
    # c3 dedupe: group_ids gồm cả g1,g2
    r3 = rows["0901000003"]
    assert r3["excluded_reason"] is None
    assert set(r3["gids"]) == {g1, g2}
    # c4 opt-out
    assert rows["0901000004"]["excluded_reason"] == "opted_out"


# ---------------------------------------------------------------------
# BUILD — over_limit gate + no-{link}
# ---------------------------------------------------------------------
async def test_build_over_limit_and_no_link(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom OL")
    c = await _mk_contact(client, h, "Nguyen Dai", "0902000001", granted=True)
    await _add_to_group(client, h, c, g)

    # template dài (ASCII 200) → tin cuối > 160 GSM7 → over_limit
    long_tpl = "X" * 200
    cid = (await _mk_campaign(client, h, long_tpl, name="OverLimit")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.status_code == 200, res.text
    rep = res.json()
    assert rep["has_link"] is False
    assert rep["exportable"] == 0
    assert rep["excluded_by_reason"].get("over_limit") == 1
    assert len(rep["over_limit"]) == 1
    assert rep["over_limit"][0]["segments"] >= 2
    assert any("EXPORT" in w for w in rep["warnings"])
    assert any("{link}" in w for w in rep["warnings"])

    rows = await _recipients(cid)
    assert rows[0]["is_over_limit"] is True
    assert rows[0]["token_hash"] is None  # no {link} → no token


# ---------------------------------------------------------------------
# Rebuild invalidate revision cũ + attestation khớp revision
# ---------------------------------------------------------------------
async def test_rebuild_invalidate_and_attestation(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom RB")
    c = await _mk_contact(client, h, "Nguyen E", "0903000001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="Rebuild")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )

    # build 1
    r1 = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert r1.json()["build_revision"] == 1
    # attestation khớp rev 1
    res = await client.post(
        f"{API}/campaigns/{cid}/attestations",
        json={"kind": "consent", "reference": "bao-cao-kiem-consent"},
        headers=h,
    )
    assert res.status_code == 201
    assert res.json()["consent_checked_build_revision"] == 1

    # build 2 (rebuild) → revision 2; recipient rev 1 bị invalidate
    r2 = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert r2.json()["build_revision"] == 2

    rows = await _recipients(cid)
    by_rev = {r["rev"]: r for r in rows}
    assert by_rev[1]["invalidated_at"] is not None   # rev cũ vô hiệu
    assert by_rev[2]["invalidated_at"] is None        # rev mới hợp lệ

    # attestation rev 1 giờ KHÔNG khớp build_revision=2 (gate export PR-4)
    detail = (await client.get(f"{API}/campaigns/{cid}", headers=h)).json()
    assert detail["build_revision"] == 2
    assert detail["consent_checked_build_revision"] == 1  # stale → gate sẽ chặn

    # update campaign khi status=ready → 400 (chỉ draft)
    res = await client.patch(
        f"{API}/campaigns/{cid}", json={"name": "doi ten"}, headers=h
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R1 #1 — compliance fail-closed: optout rỗng → build 400
# ---------------------------------------------------------------------
async def test_build_requires_optout(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "SMS_OPTOUT_INSTRUCTION", "   ")  # rỗng sau strip
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Optout")
    c = await _mk_contact(client, h, "A", "0908100001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="OptoutReq")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R1 #2 — template/render fail-closed
# ---------------------------------------------------------------------
async def test_template_strict_validation(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    for i, tpl in enumerate(
        ["Hi {foo-1}", "Hi {{name}}", "Hi {name!r}", "Hi {}", "Hi {name"]
    ):
        res = await _mk_campaign(client, h, tpl, name=f"BadTpl{i}")
        assert res.status_code == 400, f"{tpl!r} → {res.status_code}"


async def test_name_equals_link_no_sentinel(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Inject")
    # tên contact = "{link}" nhưng template KHÔNG có {link}
    c = await _mk_contact(client, h, "{link}", "0908300001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Xin chao {name}", name="Inject")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.json()["has_link"] is False
    sk = (await _recipients(cid))[0]["sk"]
    assert "__SMS_LINK__" not in sk   # tên '{link}' KHÔNG thành sentinel
    assert "{link}" in sk             # giữ literal trong tên
    assert (await _recipients(cid))[0]["token_hash"] is None


# ---------------------------------------------------------------------
# Codex R1 #3 — đổi nhóm sau build → reset draft
# ---------------------------------------------------------------------
async def test_group_change_resets_to_draft(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g1 = await _mk_group(client, h, "GC G1")
    g2 = await _mk_group(client, h, "GC G2")
    c = await _mk_contact(client, h, "A", "0908200001", granted=True)
    await _add_to_group(client, h, c, g1)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="GChange")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g1}, headers=h
    )
    r = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert r.json()["status"] == "ready"
    # attach nhóm khác → status reset draft
    res = await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g2}, headers=h
    )
    assert res.json()["status"] == "draft"
    # build lại → ready; detach → draft
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).json()["status"] == "ready"
    assert (await client.delete(
        f"{API}/campaigns/{cid}/groups/{g2}", headers=h)).status_code == 204
    assert (await client.get(
        f"{API}/campaigns/{cid}", headers=h)).json()["status"] == "draft"


# ---------------------------------------------------------------------
# Codex R1 #6 — UCS-2 đo theo UTF-16 code units (non-BMP = 2)
# ---------------------------------------------------------------------
def test_measure_ucs2_emoji():
    from app.utils.sms_render import measure
    enc, n, seg, over = measure("\U0001F600" * 36)  # 36 emoji non-BMP
    assert enc == "UCS2"
    assert n == 72        # 36 × 2 UTF-16 code units (KHÔNG phải 36)
    assert seg >= 2       # > 70 → multi-segment
    assert over is True


# ---------------------------------------------------------------------
# Codex R2 #2 — sentinel injection fail-closed
# ---------------------------------------------------------------------
async def test_template_rejects_sentinel(
    client: AsyncClient, admin_token_headers: dict
):
    res = await _mk_campaign(
        client, admin_token_headers, "Xem __SMS_LINK__ ngay", name="SentTpl"
    )
    assert res.status_code == 400  # template chứa chuỗi nội bộ → từ chối


async def test_name_sentinel_sanitized(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Sent")
    # tên contact = literal sentinel; template KHÔNG có {link}
    c = await _mk_contact(client, h, "__SMS_LINK__", "0908400001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="NameSent")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.json()["has_link"] is False
    row = (await _recipients(cid))[0]
    assert "__SMS_LINK__" not in row["sk"]  # tên bị sanitize → không sentinel
    assert row["token_hash"] is None


# ---------------------------------------------------------------------
# Codex R2 #4 — template toàn khoảng trắng → 422
# ---------------------------------------------------------------------
async def test_template_whitespace_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    res = await _mk_campaign(client, admin_token_headers, "    ", name="WsTpl")
    assert res.status_code == 422


# ---------------------------------------------------------------------
# Codex R3 #1 — update_campaign serialize với build qua campaign row lock
# ---------------------------------------------------------------------
async def test_update_serializes_with_build_lock(
    client: AsyncClient, admin_token_headers: dict
):
    from app.schemas import sms as sms_schemas
    from app.services.sms_campaign_service import SmsCampaignService

    h = admin_token_headers
    cid = (await _mk_campaign(client, h, "Hi {name}", name="LockRace")).json()["id"]
    # Session A giữ lock FOR UPDATE trên campaign (mô phỏng build đang chạy).
    async with AsyncSessionLocal() as sa:
        await sa.execute(
            text("SELECT id FROM sms_campaign WHERE id=:c FOR UPDATE"),
            {"c": cid},
        )
        # Session B: lock_timeout ngắn → update_campaign (FOR UPDATE) phải lỗi
        # → chứng tỏ update serialize với build (không đọc không khóa).
        async with AsyncSessionLocal() as sb:
            await sb.execute(text("SET lock_timeout = '400ms'"))
            svc = SmsCampaignService(sb)
            with pytest.raises(Exception):
                await svc.update_campaign(
                    cid, sms_schemas.SmsCampaignUpdate(name="doi ten")
                )
        await sa.rollback()


# ---------------------------------------------------------------------
# Codex R3 #2 — name fallback + drop-broken-row (missing_data)
# ---------------------------------------------------------------------
async def test_name_fallback_when_empty(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "SMS_OPTOUT_INSTRUCTION", "STOP")  # footer ngắn
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom FB")
    # tên = literal sentinel → sanitize rỗng → fallback quy định (§D6)
    c = await _mk_contact(client, h, "__SMS_LINK__", "0908500001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="Fallback")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.json()["exportable"] == 1     # fallback → vẫn gửi được
    sk = (await _recipients(cid))[0]["sk"]
    assert "Quý phụ huynh/học sinh" in sk
    assert "__SMS_LINK__" not in sk


async def test_name_render_token_dropped_missing_data(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom MD")
    # tên contact = literal "{name}" → tin cuối còn placeholder → missing_data
    c = await _mk_contact(client, h, "{name}", "0908600001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="MissData")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.json()["exportable"] == 0
    assert res.json()["excluded_by_reason"].get("missing_data") == 1


# ---------------------------------------------------------------------
# Codex R3 #4 — gate từ chối Fernet key sai định dạng (prod)
# ---------------------------------------------------------------------
def test_fernet_malformed_key_rejected(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    monkeypatch.setattr(
        cfg, "SMS_TOKEN_ENCRYPTION_KEYS", '{"v1": "not-a-fernet-key"}'
    )
    monkeypatch.setattr(cfg, "SMS_TOKEN_ACTIVE_KEY_VERSION", "v1")
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()


# ---------------------------------------------------------------------
# Codex R4 #1 — ID cực lớn → 422 (chống int32 overflow 500)
# ---------------------------------------------------------------------
async def test_extreme_id_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    big = "1" * 101
    assert (await client.get(
        f"{API}/campaigns/{big}", headers=h)).status_code == 422
    assert (await client.post(
        f"{API}/campaigns/{big}/build", headers=h)).status_code == 422
    # group_id trong body cũng bị chặn
    cid = (await _mk_campaign(client, h, "Hi {name}", name="ExtremeId")).json()["id"]
    res = await client.post(
        f"{API}/campaigns/{cid}/groups",
        json={"group_id": int("9" * 30)}, headers=h,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------
# Codex R4 #2 — footer chứa {foo} → drop missing_data (no placeholder sót)
# ---------------------------------------------------------------------
async def test_footer_placeholder_dropped(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "SMS_OPTOUT_INSTRUCTION", "Tu choi {foo}")
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom FootPH")
    c = await _mk_contact(client, h, "Nguyen A", "0908700001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="FootPH")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.json()["exportable"] == 0
    assert res.json()["excluded_by_reason"].get("missing_data") == 1


# ---------------------------------------------------------------------
# Codex R4 #4 — keyring value không phải chuỗi → RuntimeError (không AttributeError)
# ---------------------------------------------------------------------
def test_keyring_nonstring_key_rejected(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    monkeypatch.setattr(cfg, "SMS_TOKEN_ENCRYPTION_KEYS", '{"v1": 123}')
    monkeypatch.setattr(cfg, "SMS_TOKEN_ACTIVE_KEY_VERSION", "v1")
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()


# ---------------------------------------------------------------------
# Codex R5 #1 — skip cực lớn → 422 (chống offset int64 overflow 500)
# ---------------------------------------------------------------------
async def test_skip_extreme_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    res = await client.get(
        f"{API}/campaigns?skip={'1' * 101}", headers=admin_token_headers
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------
# Codex R5 #2 — skeleton_is_broken bắt ngoặc LẺ (không cân bằng)
# ---------------------------------------------------------------------
def test_skeleton_lone_brace_broken():
    from app.utils.sms_render import skeleton_is_broken

    # ngoặc LẺ '{foo' / 'foo}' (không cân bằng) cũng phải bị coi là hỏng
    assert skeleton_is_broken("[QC] Hi {foo STOP", has_link=False) is True
    assert skeleton_is_broken("[QC] Hi foo} STOP", has_link=False) is True
    # bình thường (không ngoặc) → OK; sentinel mà không link → hỏng
    assert skeleton_is_broken("[QC] Hi An STOP", has_link=False) is False
    assert skeleton_is_broken("[QC] x __SMS_LINK__", has_link=False) is True


# ---------------------------------------------------------------------
# Codex R5 #3 — token_key_version > 32 ký tự → RuntimeError (cột VARCHAR(32))
# ---------------------------------------------------------------------
def test_key_version_too_long_rejected(monkeypatch):
    import json

    from cryptography.fernet import Fernet

    from app.config import settings as cfg
    from app.utils import sms_token

    long_ver = "v" * 33
    key = Fernet.generate_key().decode()  # key HỢP LỆ → chỉ version sai
    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    monkeypatch.setattr(
        cfg, "SMS_TOKEN_ENCRYPTION_KEYS", json.dumps({long_ver: key})
    )
    monkeypatch.setattr(cfg, "SMS_TOKEN_ACTIVE_KEY_VERSION", long_ver)
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()


# ---------------------------------------------------------------------
# Codex R5 #4 — frequency cap âm bị từ chối (campaign + global config)
# ---------------------------------------------------------------------
async def test_freq_cap_negative_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    res = await _mk_campaign(
        client, admin_token_headers, "Hi {name}",
        name="NegFreq", frequency_cap_days=-1,
    )
    assert res.status_code == 422


def test_global_freq_cap_rejects_negative():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError) as ei:
        Settings(SMS_FREQUENCY_CAP_DAYS=-5)
    assert "SMS_FREQUENCY_CAP_DAYS" in str(ei.value)


# ---------------------------------------------------------------------
# Codex R5 #5 — preflight có preview ≤5 dòng (sentinel → URL mẫu), §D6
# ---------------------------------------------------------------------
async def test_preflight_includes_preview(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom PV")
    c = await _mk_contact(client, h, "Nguyen Preview", "0908800001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (
        await _mk_campaign(client, h, "Chao {name}, xem {link}", name="Preview")
    ).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    rep = (await client.post(f"{API}/campaigns/{cid}/build", headers=h)).json()
    assert rep["exportable"] == 1
    assert 1 <= len(rep["preview"]) <= 5
    line = rep["preview"][0]
    assert "__SMS_LINK__" not in line   # sentinel đã thay bằng URL mẫu
    assert "/r/" in line                # link mẫu có path /r/
    assert line.startswith("[QC]")
    assert "Nguyen Preview" in line     # tên đã render vào preview


# ---------------------------------------------------------------------
# Codex R6 #1 — chặn rebuild sau khi đã bàn giao ≥1 batch (§232)
# ---------------------------------------------------------------------
async def test_rebuild_blocked_after_handoff(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom HO")
    c = await _mk_contact(client, h, "Nguyen HO", "0909000001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="Handoff")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).status_code == 200
    # mô phỏng đã bàn giao batch: set handed_off_at cho recipient
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE sms_campaign_recipient SET handed_off_at = now() "
            "WHERE campaign_id = :c"), {"c": cid})
        await s.commit()
    # rebuild → 400 (đã handoff → không build lại, tạo campaign mới)
    res = await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R6 #2 — attestation chỉ ở 'ready'; sau export bị đóng băng
# ---------------------------------------------------------------------
async def test_attestation_blocked_after_export(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom AE")
    c = await _mk_contact(client, h, "Nguyen AE", "0909000002", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="AttestExp")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    # attest ở 'ready' → OK
    r = await client.post(
        f"{API}/campaigns/{cid}/attestations",
        json={"kind": "consent", "reference": "rep-ready"}, headers=h,
    )
    assert r.status_code == 201
    # chuyển 'exported' (mô phỏng đã sinh file) → attest bị chặn 400
    async with AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE sms_campaign SET status='exported' WHERE id=:c"),
            {"c": cid},
        )
        await s.commit()
    res = await client.post(
        f"{API}/campaigns/{cid}/attestations",
        json={"kind": "consent", "reference": "rep-after"}, headers=h,
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R6 #3 — over_limit nhất quán: row no_consent+dài KHÔNG vào over_limit
# ---------------------------------------------------------------------
async def test_over_limit_excludes_higher_priority_row(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom OLC")
    # chưa consent + template dài → no_consent thắng (ưu tiên cao hơn)
    c = await _mk_contact(client, h, "Nguyen OLC", "0909000003", granted=False)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "X" * 200, name="OLConsist")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    rep = (await client.post(f"{API}/campaigns/{cid}/build", headers=h)).json()
    assert rep["excluded_by_reason"].get("no_consent") == 1
    assert rep["excluded_by_reason"].get("over_limit") is None  # KHÔNG đếm over
    assert rep["over_limit"] == []                              # list rỗng (nhất quán)
    assert not any("EXPORT" in w for w in rep["warnings"])      # không cảnh báo over


# ---------------------------------------------------------------------
# Codex R6 #4 — external_suppression → dnc_suppressed (KHÔNG phải opted_out)
# ---------------------------------------------------------------------
async def test_external_suppression_is_dnc(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom DNC")
    c = await _mk_contact(client, h, "Nguyen DNC", "0909000004", granted=True)
    await _add_to_group(client, h, c, g)
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO sms_opt_out (phone_normalized, source, observed_at) "
            "VALUES ('0909000004','external_suppression', now())"))
        await s.commit()
    cid = (await _mk_campaign(client, h, "Hi {name}", name="DncSup")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    rep = (await client.post(f"{API}/campaigns/{cid}/build", headers=h)).json()
    assert rep["excluded_by_reason"].get("dnc_suppressed") == 1
    assert rep["excluded_by_reason"].get("opted_out") is None
    assert (await _recipients(cid))[0]["excluded_reason"] == "dnc_suppressed"


# ---------------------------------------------------------------------
# Codex R6 #5 — API trả actor (*_checked_by_id) của attestation
# ---------------------------------------------------------------------
async def test_attestation_exposes_actor(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Actor")
    c = await _mk_contact(client, h, "Nguyen Actor", "0909000005", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="Actor")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    r = await client.post(
        f"{API}/campaigns/{cid}/attestations",
        json={"kind": "consent", "reference": "rep-actor"}, headers=h,
    )
    assert r.status_code == 201
    actor = r.json()["consent_checked_by_id"]
    assert actor is not None                       # actor lộ ra ở response mutation
    detail = (await client.get(f"{API}/campaigns/{cid}", headers=h)).json()
    assert detail["consent_checked_by_id"] == actor  # GET cũng trả actor


# ---------------------------------------------------------------------
# Codex R7 P1-1 — đã handoff thì chặn attach + update (không lách qua draft)
# ---------------------------------------------------------------------
async def test_handoff_blocks_attach_and_update(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom HOA")
    g2 = await _mk_group(client, h, "Nhom HOA2")
    c = await _mk_contact(client, h, "Nguyen HOA", "0909100001", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="HandoffMut")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    await client.post(f"{API}/campaigns/{cid}/build", headers=h)
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE sms_campaign_recipient SET handed_off_at=now() "
            "WHERE campaign_id=:c"), {"c": cid})
        await s.commit()
    # attach nhóm khác → 400 (không reset về draft sau handoff)
    assert (await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g2}, headers=h
    )).status_code == 400
    # ép draft (giả lập) + đã handoff → update cũng bị chặn 400
    async with AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE sms_campaign SET status='draft' WHERE id=:c"),
            {"c": cid},
        )
        await s.commit()
    assert (await client.patch(
        f"{API}/campaigns/{cid}", json={"name": "doi"}, headers=h
    )).status_code == 400


# ---------------------------------------------------------------------
# Codex R7 P1-2 — prod fail-closed: footer placeholder xxxx + base_url + ip
# ---------------------------------------------------------------------
async def test_prod_footer_placeholder_xxxx_rejected(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom PFX")
    c = await _mk_contact(client, h, "Nguyen PFX", "0909100002", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="ProdFx")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_OPTOUT_INSTRUCTION", "Tu choi: goi 1900 XXXX")
    # footer còn 'XXXX' placeholder → build 400 (no-link nên không cần keyring)
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).status_code == 400


def test_prod_base_url_must_be_https_allowlisted(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    monkeypatch.setattr(cfg, "SMS_IP_HASH_SECRET", "y" * 40)
    monkeypatch.setattr(cfg, "SMS_PUBLIC_BASE_URL", "http://evil.example")
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()


def test_prod_ip_hash_secret_must_be_strong(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    # ip secret còn default công khai → RuntimeError
    monkeypatch.setattr(
        cfg, "SMS_IP_HASH_SECRET", "dev-sms-ip-hash-secret-change-in-prod"
    )
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()


# ---------------------------------------------------------------------
# Codex R7 P2-1 — preflight stale: draft sau build → preview rỗng + warning
# ---------------------------------------------------------------------
async def test_preflight_stale_clears_preview(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom STL")
    g2 = await _mk_group(client, h, "Nhom STL2")
    c = await _mk_contact(client, h, "Nguyen STL", "0909100003", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (
        await _mk_campaign(client, h, "Chao {name} {link}", name="Stale")
    ).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    rep = (await client.post(f"{API}/campaigns/{cid}/build", headers=h)).json()
    assert rep["preview"]                       # ready → có preview
    # đổi audience → draft (stale)
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g2}, headers=h
    )
    rep2 = (await client.get(f"{API}/campaigns/{cid}/preflight", headers=h)).json()
    assert rep2["status"] == "draft"
    assert rep2["build_revision"] == 1          # số liệu thuộc rev cũ
    assert rep2["preview"] == []                # preview cũ KHÔNG hiển thị
    assert any("CŨ" in w for w in rep2["warnings"])


# ---------------------------------------------------------------------
# Codex R7 P2-2 — footer > 160 → build 400 (snapshot không cắt ngầm)
# ---------------------------------------------------------------------
async def test_footer_too_long_rejected(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "SMS_OPTOUT_INSTRUCTION", "A" * 161)
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom FL")
    c = await _mk_contact(client, h, "Nguyen FL", "0909100004", granted=True)
    await _add_to_group(client, h, c, g)
    cid = (await _mk_campaign(client, h, "Hi {name}", name="FootLong")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).status_code == 400


# ---------------------------------------------------------------------
# Codex R7 P2-3 — link_expires_at: quá khứ/naive → 422; tương lai tz → 201
# ---------------------------------------------------------------------
async def test_link_expires_validation(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    # quá khứ → 422
    assert (await _mk_campaign(
        client, h, "Hi {name}", name="ExpPast",
        link_expires_at="2020-01-01T00:00:00+07:00")).status_code == 422
    # naive (không timezone) → 422
    assert (await _mk_campaign(
        client, h, "Hi {name}", name="ExpNaive",
        link_expires_at="2099-01-01T00:00:00")).status_code == 422
    # tương lai + tz → 201
    assert (await _mk_campaign(
        client, h, "Hi {name}", name="ExpOk",
        link_expires_at="2099-01-01T00:00:00+07:00")).status_code == 201


# ---------------------------------------------------------------------
# Codex R7 P2-4 — decrypt_code key không phải chuỗi → None (không 500)
# ---------------------------------------------------------------------
def test_decrypt_nonstring_key_returns_none(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "SMS_TOKEN_ENCRYPTION_KEYS", '{"v1": 123}')
    monkeypatch.setattr(cfg, "SMS_TOKEN_ACTIVE_KEY_VERSION", "v1")
    assert sms_token.decrypt_code("anything", "v1") is None


# ---------------------------------------------------------------------
# Codex R7 P3-1 — nhóm is_active=false → attach 400
# ---------------------------------------------------------------------
async def test_inactive_group_attach_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Inact")
    async with AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE sms_contact_group SET is_active=false WHERE id=:g"),
            {"g": g},
        )
        await s.commit()
    cid = (await _mk_campaign(client, h, "Hi {name}", name="InactG")).json()["id"]
    assert (await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )).status_code == 400


# ---------------------------------------------------------------------
# Codex R7 P3-2 — nhóm rỗng (0 member) → build 400
# ---------------------------------------------------------------------
async def test_empty_group_build_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom Empty")  # KHÔNG add member
    cid = (await _mk_campaign(client, h, "Hi {name}", name="EmptyG")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).status_code == 400


# ---------------------------------------------------------------------
# Codex R7 P3-3 — list campaign trả group_count thực (không null)
# ---------------------------------------------------------------------
async def test_list_group_count_populated(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom GC")
    cid = (await _mk_campaign(client, h, "Hi {name}", name="ListGCx")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    res = await client.get(f"{API}/campaigns?search=ListGCx", headers=h)
    item = next(i for i in res.json()["items"] if i["id"] == cid)
    assert item["group_count"] == 1


# ---------------------------------------------------------------------
# Codex R7 P3-4 — CTA chỉ có label (thiếu URL) → 400
# ---------------------------------------------------------------------
async def test_cta_requires_both_label_and_url(
    client: AsyncClient, admin_token_headers: dict
):
    res = await _mk_campaign(
        client, admin_token_headers, "Hi {name}", name="CtaHalf",
        landing_cta_label="Bam day",
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R7 P3-5 — global frequency cap có trần (le=3650)
# ---------------------------------------------------------------------
def test_global_freq_cap_ceiling():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(SMS_FREQUENCY_CAP_DAYS=999999999)


# ---------------------------------------------------------------------
# Codex R7 P3-7 — URL lưu sau khi strip whitespace
# ---------------------------------------------------------------------
async def test_landing_url_stored_stripped(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    res = await _mk_campaign(
        client, h, "Bam {link}", name="UrlStrip", landing_type="external",
        landing_url="  https://qlts.tnpc.edu.vn/x  ",
    )
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    detail = (await client.get(f"{API}/campaigns/{cid}", headers=h)).json()
    assert detail["landing_url"] == "https://qlts.tnpc.edu.vn/x"


# ---------------------------------------------------------------------
# Codex R8 P2 — build re-check expiry: future lúc create, expired trước build
# ---------------------------------------------------------------------
async def test_build_rejects_expired_link(
    client: AsyncClient, admin_token_headers: dict
):
    h = admin_token_headers
    g = await _mk_group(client, h, "Nhom EXP")
    c = await _mk_contact(client, h, "Nguyen EXP", "0909200001", granted=True)
    await _add_to_group(client, h, c, g)
    # tạo với expiry TƯƠNG LAI (qua schema), template có {link}
    cid = (await _mk_campaign(
        client, h, "Chao {name} {link}", name="ExpBuild",
        link_expires_at="2099-01-01T00:00:00+07:00")).json()["id"]
    await client.post(
        f"{API}/campaigns/{cid}/groups", json={"group_id": g}, headers=h
    )
    # giả lập thời gian trôi: expiry đã quá khứ
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE sms_campaign SET link_expires_at='2020-01-01T00:00:00+07' "
            "WHERE id=:c"), {"c": cid})
        await s.commit()
    # build → 400 (link đã hết hạn, không build link chết)
    assert (await client.post(
        f"{API}/campaigns/{cid}/build", headers=h)).status_code == 400


# ---------------------------------------------------------------------
# Codex R8 P3 — prod SMS_PUBLIC_BASE_URL từ chối userinfo/query/fragment
# ---------------------------------------------------------------------
def test_prod_base_url_rejects_userinfo_query(monkeypatch):
    from app.config import settings as cfg
    from app.utils import sms_token

    monkeypatch.setattr(cfg, "APP_ENV", "production")
    monkeypatch.setattr(cfg, "SMS_TOKEN_HASH_SECRET", "x" * 40)
    monkeypatch.setattr(cfg, "SMS_IP_HASH_SECRET", "y" * 40)
    # host đúng allowlist NHƯNG có userinfo + query → URL link sẽ sai
    monkeypatch.setattr(
        cfg, "SMS_PUBLIC_BASE_URL", "https://user@qlts.tnpc.edu.vn?x=1"
    )
    with pytest.raises(RuntimeError):
        sms_token.ensure_token_secrets_configured()
