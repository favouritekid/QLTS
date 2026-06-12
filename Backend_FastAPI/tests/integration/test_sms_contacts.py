# tests/integration/test_sms_contacts.py
"""
Integration test PR-2 (SMS Marketing — Contact Management BE).

Phủ: group CRUD + auto-slug, contact CRUD, dedupe global (giữ bản đầu),
mobile-only, membership add/remove + idempotent, consent-event ledger
fail-closed + projection latest-state, và ANCHOR import counts invariant
(§4.4): row=valid+invalid+dup; skipped=invalid+dup; added+existing=valid;
inserted<=valid.

Chạy one-off container (CLAUDE.md):
  docker compose run --rm --no-deps backend \
    python -m pytest tests/integration/test_sms_contacts.py -q
"""
from httpx import AsyncClient

API = "/api/sms"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
async def _create_group(client, headers, name="Nhóm Phụ huynh 2026"):
    res = await client.post(
        f"{API}/contact-groups",
        json={"name": name, "group_type": "parent"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_contact(client, headers, full_name, phone, note=None):
    res = await client.post(
        f"{API}/contacts",
        json={"full_name": full_name, "phone": phone, "note": note},
        headers=headers,
    )
    return res


def _upload_files(csv_text: str):
    return {"file": ("contacts.csv", csv_text.encode("utf-8"), "text/csv")}


# ---------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------
async def test_group_crud_and_autoslug(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers, "Phụ Huynh K10")
    # auto-slug bỏ dấu
    assert group["code"] == "phu-huynh-k10"
    assert group["member_count"] == 0
    gid = group["id"]

    # GET detail
    res = await client.get(
        f"{API}/contact-groups/{gid}", headers=admin_token_headers
    )
    assert res.status_code == 200

    # LIST
    res = await client.get(
        f"{API}/contact-groups", headers=admin_token_headers
    )
    assert res.status_code == 200
    assert res.json()["total"] >= 1

    # PATCH
    res = await client.patch(
        f"{API}/contact-groups/{gid}",
        json={"description": "mô tả mới", "is_active": False},
        headers=admin_token_headers,
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    # duplicate slug → 409
    res = await client.post(
        f"{API}/contact-groups",
        json={"name": "Phụ Huynh K10", "group_type": "parent"},
        headers=admin_token_headers,
    )
    assert res.status_code == 409


async def test_group_not_found(
    client: AsyncClient, admin_token_headers: dict
):
    res = await client.get(
        f"{API}/contact-groups/999999", headers=admin_token_headers
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------
# Contact CRUD + dedupe + mobile-only
# ---------------------------------------------------------------------
async def test_contact_create_dedupe_and_mobile_only(
    client: AsyncClient, admin_token_headers: dict
):
    # tạo hợp lệ — normalize + international
    res = await _create_contact(
        client, admin_token_headers, "Nguyễn A", "0901234567"
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["phone_normalized"] == "0901234567"
    assert body["phone_international"] == "84901234567"
    assert body["marketing_consent_status"] == "unknown"

    # PATCH identity (phủ nhánh refresh updated_at onupdate)
    res = await client.patch(
        f"{API}/contacts/{body['id']}",
        json={"full_name": "Nguyễn A (sửa)", "note": "vip"},
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "Nguyễn A (sửa)"

    # trùng phone toàn cục → 409
    res = await _create_contact(
        client, admin_token_headers, "Người khác", "0901234567"
    )
    assert res.status_code == 409

    # landline 02x → 400 (mobile-only)
    res = await _create_contact(
        client, admin_token_headers, "Cố định", "02839991234"
    )
    assert res.status_code == 400

    # +84 normalize hợp lệ
    res = await _create_contact(
        client, admin_token_headers, "Quốc tế", "+84 912 345 678"
    )
    assert res.status_code == 201
    assert res.json()["phone_normalized"] == "0912345678"


# ---------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------
async def test_membership_add_remove_idempotent(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers)
    gid = group["id"]
    contact = (
        await _create_contact(
            client, admin_token_headers, "Trần B", "0987000111"
        )
    ).json()
    cid = contact["id"]

    # add
    res = await client.post(
        f"{API}/contacts/{cid}/groups",
        json={"group_id": gid, "note": "ghi chú nhóm"},
        headers=admin_token_headers,
    )
    assert res.status_code == 201

    # add lần 2 → 409
    res = await client.post(
        f"{API}/contacts/{cid}/groups",
        json={"group_id": gid},
        headers=admin_token_headers,
    )
    assert res.status_code == 409

    # group hiện 1 member
    res = await client.get(
        f"{API}/contact-groups/{gid}/contacts", headers=admin_token_headers
    )
    assert res.json()["total"] == 1

    # remove
    res = await client.delete(
        f"{API}/contacts/{cid}/groups/{gid}", headers=admin_token_headers
    )
    assert res.status_code == 204

    # remove lần 2 → 404
    res = await client.delete(
        f"{API}/contacts/{cid}/groups/{gid}", headers=admin_token_headers
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------
# Consent-event ledger + projection
# ---------------------------------------------------------------------
async def test_consent_event_ledger_and_projection(
    client: AsyncClient, admin_token_headers: dict
):
    cid = (
        await _create_contact(
            client, admin_token_headers, "Lê C", "0903000222"
        )
    ).json()["id"]

    # GRANT đủ proof → 201 + projection granted
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2026-06-01T08:00:00+07:00",
            "basis": "signed_form",
            "disclosure_version": "v1",
            "proof_reference": "ho-so/2026/PH-001",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201, res.text

    res = await client.get(
        f"{API}/contacts", params={"search": "0903000222"},
        headers=admin_token_headers,
    )
    contact = res.json()["items"][0]
    assert contact["marketing_consent_status"] == "granted"
    assert contact["marketing_consent_basis"] == "signed_form"

    # GRANT thiếu proof → 422 (schema fail-closed)
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2026-06-02T08:00:00+07:00",
            "basis": "signed_form",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 422

    # REVOKE → 201 + projection revoked
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "revoked",
            "occurred_at": "2026-06-03T08:00:00+07:00",
            "revoke_source": "manual",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201, res.text

    # REVOKE kèm grant-data → 422
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "revoked",
            "occurred_at": "2026-06-03T09:00:00+07:00",
            "revoke_source": "manual",
            "proof_reference": "x",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 422

    # ledger có 2 sự kiện (granted + revoked)
    res = await client.get(
        f"{API}/contacts/{cid}/consent-events", headers=admin_token_headers
    )
    assert res.json()["total"] == 2


# ---------------------------------------------------------------------
# Import — ANCHOR counts invariant + dedupe global
# ---------------------------------------------------------------------
async def test_import_counts_invariant_and_dedupe(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers)
    gid = group["id"]

    # contact tồn tại trước (toàn cục), CHƯA ở nhóm
    await _create_contact(
        client, admin_token_headers, "Contact X", "0901111111"
    )

    csv_text = (
        "full_name,phone,note\n"
        "Nguyen A,0901234567,note1\n"          # valid mới
        "Tran B,0912345678,\n"                  # valid mới
        ",0987654321,khong-ten\n"               # invalid: thiếu tên
        "Le C,02839999999,landline\n"           # invalid: không di động
        "Pham D,0901234567,trung-file\n"        # duplicate trong file
        "Existing X,0901111111,tai-dung\n"      # valid: contact đã có
    )
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files(csv_text),
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    r = res.json()

    assert r["row_count"] == 6
    assert r["invalid_count"] == 2
    assert r["duplicate_contact_count"] == 1
    assert r["valid_count"] == 3
    assert r["inserted_contact_count"] == 2   # row6 tái dùng X
    assert r["added_member_count"] == 3
    assert r["existing_member_count"] == 0
    assert r["skipped_count"] == 3
    assert r["consent_applied"] is False
    # bất biến
    assert r["row_count"] == (
        r["valid_count"] + r["invalid_count"] + r["duplicate_contact_count"]
    )
    assert r["skipped_count"] == r["invalid_count"] + r["duplicate_contact_count"]
    assert r["added_member_count"] + r["existing_member_count"] == r["valid_count"]
    assert r["inserted_contact_count"] <= r["valid_count"]
    assert len(r["errors"]) == 3

    # contact X giữ identity gốc (B3 — không ghi đè tên)
    res = await client.get(
        f"{API}/contacts", params={"search": "0901111111"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["full_name"] == "Contact X"

    # import LẦN 2 cùng file → tất cả đã là member (idempotent)
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files(csv_text),
        headers=admin_token_headers,
    )
    r2 = res.json()
    assert r2["inserted_contact_count"] == 0      # phone đã tồn tại toàn cục
    assert r2["added_member_count"] == 0
    assert r2["existing_member_count"] == 3
    assert r2["added_member_count"] + r2["existing_member_count"] == r2["valid_count"]


# ---------------------------------------------------------------------
# Import — consent áp cho contact MỚI + partial reject
# ---------------------------------------------------------------------
async def test_import_consent_applied_and_partial_reject(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers)
    gid = group["id"]

    # consent một phần (chỉ basis) → 400
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files("full_name,phone\nA,0905000111\n"),
        data={"consent_basis": "signed_form"},
        headers=admin_token_headers,
    )
    assert res.status_code == 400, res.text

    # consent đủ 4 → contact mới granted + có consent event
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files("full_name,phone\nNguyen A,0905000222\n"),
        data={
            "consent_basis": "signed_form",
            "consent_disclosure_version": "v1",
            "consent_proof_ref": "ho-so/lo-2026",
            "consent_obtained_at": "2026-05-20T00:00:00+07:00",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["consent_applied"] is True
    assert res.json()["inserted_contact_count"] == 1

    res = await client.get(
        f"{API}/contacts", params={"search": "0905000222"},
        headers=admin_token_headers,
    )
    contact = res.json()["items"][0]
    assert contact["marketing_consent_status"] == "granted"

    res = await client.get(
        f"{API}/contacts/{contact['id']}/consent-events",
        headers=admin_token_headers,
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["import_batch_id"] is not None


# ---------------------------------------------------------------------
# Codex R1 #1 — import consent áp cho contact ĐÃ tồn tại (không chỉ mới)
# ---------------------------------------------------------------------
async def test_import_consent_applies_to_existing_contact(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers)
    gid = group["id"]
    cid = (
        await _create_contact(
            client, admin_token_headers, "Cũ", "0906000111"
        )
    ).json()["id"]

    res = await client.get(
        f"{API}/contacts", params={"search": "0906000111"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["marketing_consent_status"] == "unknown"

    # import lô CÓ bằng chứng, chứa đúng số contact cũ
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files("full_name,phone\nCũ,0906000111\n"),
        data={
            "consent_basis": "signed_form",
            "consent_disclosure_version": "v1",
            "consent_proof_ref": "ho-so/lo-X",
            "consent_obtained_at": "2026-05-20T00:00:00+07:00",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["inserted_contact_count"] == 0  # tái dùng

    # contact CŨ giờ granted + có ledger event
    res = await client.get(
        f"{API}/contacts", params={"search": "0906000111"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["marketing_consent_status"] == "granted"
    res = await client.get(
        f"{API}/contacts/{cid}/consent-events", headers=admin_token_headers
    )
    assert res.json()["total"] == 1


# ---------------------------------------------------------------------
# Codex R1 #2 — projection theo occurred_at (grant cũ KHÔNG phục hồi revoke)
# ---------------------------------------------------------------------
async def test_consent_projection_respects_occurred_at(
    client: AsyncClient, admin_token_headers: dict
):
    cid = (
        await _create_contact(
            client, admin_token_headers, "X", "0907000222"
        )
    ).json()["id"]

    # revoke MỚI (06-10)
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "revoked",
            "occurred_at": "2026-06-10T00:00:00+07:00",
            "revoke_source": "manual",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201

    # grant CŨ hơn (06-01) — KHÔNG được override → vẫn revoked
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2026-06-01T00:00:00+07:00",
            "basis": "signed_form",
            "disclosure_version": "v1",
            "proof_reference": "ref",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201
    res = await client.get(
        f"{API}/contacts", params={"search": "0907000222"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["marketing_consent_status"] == "revoked"

    # grant MỚI hơn (06-11, vẫn ≤ hôm nay) → granted
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2026-06-11T00:00:00+07:00",
            "basis": "signed_form",
            "disclosure_version": "v1",
            "proof_reference": "ref2",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201
    res = await client.get(
        f"{API}/contacts", params={"search": "0907000222"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["marketing_consent_status"] == "granted"


# ---------------------------------------------------------------------
# Codex R1 #3 — note trong file được giữ (không mất im lặng)
# ---------------------------------------------------------------------
async def test_import_preserves_note(
    client: AsyncClient, admin_token_headers: dict
):
    group = await _create_group(client, admin_token_headers)
    gid = group["id"]
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files(
            "full_name,phone,note\nNguyen A,0908000333,ghi-chu-quan-trong\n"
        ),
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    res = await client.get(
        f"{API}/contacts", params={"search": "0908000333"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["note"] == "ghi-chu-quan-trong"


# ---------------------------------------------------------------------
# Codex R1 #4 — PATCH chặn null (400) / toàn khoảng trắng (422)
# ---------------------------------------------------------------------
async def test_patch_rejects_null_and_blank(
    client: AsyncClient, admin_token_headers: dict
):
    gid = (await _create_group(client, admin_token_headers))["id"]

    # explicit null cho cột NOT NULL → 400 (không phải 500)
    for body in ({"name": None}, {"group_type": None}, {"is_active": None}):
        res = await client.patch(
            f"{API}/contact-groups/{gid}", json=body,
            headers=admin_token_headers,
        )
        assert res.status_code == 400, f"{body} → {res.status_code}"

    # toàn khoảng trắng → 422 (schema validator)
    res = await client.patch(
        f"{API}/contact-groups/{gid}", json={"name": "   "},
        headers=admin_token_headers,
    )
    assert res.status_code == 422

    cid = (
        await _create_contact(
            client, admin_token_headers, "Nguyễn A", "0909000444"
        )
    ).json()["id"]
    res = await client.patch(
        f"{API}/contacts/{cid}", json={"full_name": None},
        headers=admin_token_headers,
    )
    assert res.status_code == 400
    res = await client.patch(
        f"{API}/contacts/{cid}", json={"full_name": "   "},
        headers=admin_token_headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------
# Codex R2 #1 — chặn consent ở tương lai (API 422 / import 400)
# ---------------------------------------------------------------------
async def test_future_consent_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    cid = (
        await _create_contact(
            client, admin_token_headers, "F", "0906000888"
        )
    ).json()["id"]
    # API consent-events occurred_at tương lai → 422
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2099-01-01T00:00:00+07:00",
            "basis": "signed_form",
            "disclosure_version": "v1",
            "proof_reference": "ref",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 422

    # import consent_obtained_at tương lai → 400
    gid = (await _create_group(client, admin_token_headers))["id"]
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files("full_name,phone\nA,0906000777\n"),
        data={
            "consent_basis": "signed_form",
            "consent_disclosure_version": "v1",
            "consent_proof_ref": "ref",
            "consent_obtained_at": "2099-01-01T00:00:00+07:00",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R2 #2 — cùng occurred_at: REVOKE thắng (fail-closed)
# ---------------------------------------------------------------------
async def test_equal_time_revoke_wins(
    client: AsyncClient, admin_token_headers: dict
):
    cid = (
        await _create_contact(
            client, admin_token_headers, "Z", "0907000999"
        )
    ).json()["id"]
    same = "2026-06-05T00:00:00+07:00"
    # revoke trước
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "revoked", "occurred_at": same,
            "revoke_source": "manual",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201
    # grant CÙNG occurred_at, ghi SAU → revoke vẫn thắng (không fail-open)
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted", "occurred_at": same,
            "basis": "signed_form", "disclosure_version": "v1",
            "proof_reference": "ref",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 201
    res = await client.get(
        f"{API}/contacts", params={"search": "0907000999"},
        headers=admin_token_headers,
    )
    assert res.json()["items"][0]["marketing_consent_status"] == "revoked"


# ---------------------------------------------------------------------
# Codex R2 #3 — họ tên >255 ký tự = row invalid (KHÔNG 500)
# ---------------------------------------------------------------------
async def test_import_oversized_name_is_row_invalid(
    client: AsyncClient, admin_token_headers: dict
):
    gid = (await _create_group(client, admin_token_headers))["id"]
    long_name = "A" * 256
    csv_text = (
        "full_name,phone\n"
        f"{long_name},0905001111\n"
        "Ngan,0905002222\n"
    )
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files(csv_text),
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    r = res.json()
    assert r["row_count"] == 2
    assert r["invalid_count"] == 1
    assert r["valid_count"] == 1
    assert r["inserted_contact_count"] == 1
    assert any("quá dài" in e["reason"] for e in r["errors"])


# ---------------------------------------------------------------------
# Codex R3 #1 — datetime KHÔNG timezone bị từ chối (422)
# ---------------------------------------------------------------------
async def test_naive_occurred_at_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    cid = (
        await _create_contact(
            client, admin_token_headers, "N", "0903009999"
        )
    ).json()["id"]
    res = await client.post(
        f"{API}/contacts/{cid}/consent-events",
        json={
            "event_type": "granted",
            "occurred_at": "2026-06-01T00:00:00",  # KHÔNG có timezone
            "basis": "signed_form",
            "disclosure_version": "v1",
            "proof_reference": "ref",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------
# Codex R3 #2 — consent field quá dài khi import → 400 (KHÔNG 500)
# ---------------------------------------------------------------------
async def test_import_oversized_consent_field_rejected(
    client: AsyncClient, admin_token_headers: dict
):
    gid = (await _create_group(client, admin_token_headers))["id"]
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files("full_name,phone\nA,0905003333\n"),
        data={
            "consent_basis": "signed_form",
            "consent_disclosure_version": "v1",
            "consent_proof_ref": "x" * 513,  # cột String(512)
            "consent_obtained_at": "2026-05-20T00:00:00+07:00",
        },
        headers=admin_token_headers,
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------
# Codex R3 #3 — race tạo trùng phone → 409 (không 500)
# ---------------------------------------------------------------------
async def test_concurrent_duplicate_phone_returns_409(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    # Giả lập race TOCTOU: pre-check LUÔN miss (None) → INSERT thứ 2 đụng
    # UNIQUE constraint → service phải đổi IntegrityError thành 409.
    from app.repositories.sms_contact_repository import (
        SmsContactRepository,
    )

    async def _always_none(self, phone):
        return None

    monkeypatch.setattr(
        SmsContactRepository, "get_contact_by_phone", _always_none
    )
    r1 = await _create_contact(
        client, admin_token_headers, "A", "0904111222"
    )
    assert r1.status_code == 201
    r2 = await _create_contact(
        client, admin_token_headers, "B", "0904111222"
    )
    assert r2.status_code == 409


# ---------------------------------------------------------------------
# Codex R4 — chặn Unicode digit (full-width/Arabic) bypass dedupe
# ---------------------------------------------------------------------
# Full-width "７６５４３２１０" + Arabic-Indic "١٢٣٤٥٦٧٨"
_FULLWIDTH = "05" + "７６５４３２１０"
_ARABIC = "09" + "١٢٣٤٥٦٧٨"


async def test_create_contact_rejects_unicode_digits(
    client: AsyncClient, admin_token_headers: dict
):
    # full-width digits → 400 (không được coi là di động hợp lệ)
    res = await _create_contact(
        client, admin_token_headers, "FW", _FULLWIDTH
    )
    assert res.status_code == 400, res.text
    # Arabic-Indic digits → 400
    res = await _create_contact(
        client, admin_token_headers, "AR", _ARABIC
    )
    assert res.status_code == 400, res.text


async def test_import_rejects_unicode_digit_phone(
    client: AsyncClient, admin_token_headers: dict
):
    gid = (await _create_group(client, admin_token_headers))["id"]
    # contact ASCII thật cùng "số" với bản full-width
    await _create_contact(
        client, admin_token_headers, "Real", "0576543210"
    )
    csv_text = (
        "full_name,phone\n"
        "Real,0576543210\n"
        f"Fake,{_FULLWIDTH}\n"
    )
    res = await client.post(
        f"{API}/contact-groups/{gid}/contacts/upload",
        files=_upload_files(csv_text),
        headers=admin_token_headers,
    )
    assert res.status_code == 200, res.text
    r = res.json()
    # dòng full-width = invalid (KHÔNG tạo contact trùng lách dedupe)
    assert r["invalid_count"] == 1
    assert r["valid_count"] == 1
    assert r["inserted_contact_count"] == 0  # ASCII row tái dùng contact cũ
    # toàn hệ thống vẫn chỉ 1 contact cho số này
    res = await client.get(
        f"{API}/contacts", params={"search": "576543210"},
        headers=admin_token_headers,
    )
    assert res.json()["total"] == 1


# ---------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------
async def test_requires_auth(client: AsyncClient):
    res = await client.get(f"{API}/contact-groups")
    assert res.status_code == 401
