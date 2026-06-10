# -*- coding: utf-8 -*-
"""PR-3 anchors: /resolve-ward endpoint + update_profile canonicalization.

Two untested-before-this paths (review P1 #1):

1. ``GET /api/administrative/resolve-ward`` — resolve any ward code (current or
   legacy 3-tier) to its canonical CURRENT-era commune via
   ``successor_ward_code``. Current/survived → self; legacy merged → new code
   (cross-era); unmapped legacy / unknown → ``resolved=false`` (fail-closed).

2. ``PUT /api/admissions/{id}`` canonicalizes ``permanent_commune_code`` on save:
   a legacy merged code is stored as the CURRENT code; an unresolvable code is
   kept raw (so the submit gate fail-closes on it later, forcing a re-pick).

Seed nodes use raw SQL (mirrors test_administrative.py) to avoid ORM session
conflicts with the test client.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import LeadsURLs


ADMISSIONS = "/api/admissions"

# Distinct codes (94/95 era pair) so they can't collide with other admin-node
# test seeds running in the same module session.
CURRENT_CODE = "KVC01"
CURRENT_NAME = "Phường Hiện Hành KV"
CURRENT_PROVINCE_CODE = "95"
CURRENT_PROVINCE_NAME = "Tỉnh Hiện Hành KV"
LEGACY_MERGED_CODE = "KVL01"   # merged away → successor = CURRENT_CODE
LEGACY_UNMAPPED_CODE = "KVL02"  # legacy, no successor mapped yet → fail-closed


@pytest_asyncio.fixture(autouse=True)
async def _seed_kv_nodes(setup_test_database):
    """Seed a current ward + two legacy wards (one merged-away with a successor,
    one unmapped) into the truncated test DB before each test."""
    # Inline literals (trusted test constants) — mirrors test_administrative.py.
    # Bind params can't be reused across a string-concat (text) AND a varchar
    # column in one asyncpg prepared statement (AmbiguousParameterError).
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    f"""
                    INSERT INTO administrative_nodes
                        (code, name, level, path, province_code, district_code,
                         ward_code, valid_from, valid_to, is_active,
                         successor_ward_code)
                    VALUES
                        -- current province (2-level) the current ward belongs to
                        ('{CURRENT_PROVINCE_CODE}', '{CURRENT_PROVINCE_NAME}',
                         'PROVINCE', '{CURRENT_PROVINCE_CODE}',
                         '{CURRENT_PROVINCE_CODE}', NULL, NULL,
                         '2025-07-01', NULL, true, NULL),
                        -- current ward (2-level): identity successor = self
                        ('{CURRENT_CODE}', '{CURRENT_NAME}', 'WARD',
                         '{CURRENT_PROVINCE_CODE}/{CURRENT_CODE}',
                         '{CURRENT_PROVINCE_CODE}', NULL,
                         '{CURRENT_CODE}', '2025-07-01', NULL, true, '{CURRENT_CODE}'),
                        -- legacy ward merged into the current commune
                        ('{LEGACY_MERGED_CODE}', 'Xã Cũ Gộp', 'WARD',
                         '94/94_001/{LEGACY_MERGED_CODE}', '94', '94_001',
                         '{LEGACY_MERGED_CODE}', '2010-01-01', '2025-06-30', true,
                         '{CURRENT_CODE}'),
                        -- legacy ward with NO successor mapped yet (fail-closed)
                        ('{LEGACY_UNMAPPED_CODE}', 'Xã Cũ Chưa Map', 'WARD',
                         '94/94_001/{LEGACY_UNMAPPED_CODE}', '94', '94_001',
                         '{LEGACY_UNMAPPED_CODE}', '2010-01-01', '2025-06-30', true,
                         NULL)
                    """
                )
            )


# ===========================================================================
# 1. GET /resolve-ward
# ===========================================================================

@pytest.mark.asyncio
async def test_resolve_ward_current_returns_self(
    client: AsyncClient, regular_user_token_headers: dict
):
    """Current-era code → resolves to itself with its current name."""
    resp = await client.get(
        "/api/administrative/resolve-ward",
        params={"code": CURRENT_CODE},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "input_code": CURRENT_CODE,
        "current_code": CURRENT_CODE,
        "current_name": CURRENT_NAME,
        "current_province_name": CURRENT_PROVINCE_NAME,
        "resolved": True,
    }


@pytest.mark.asyncio
async def test_resolve_ward_legacy_merged_returns_current(
    client: AsyncClient, regular_user_token_headers: dict
):
    """Cross-era: a legacy merged-away code resolves to the CURRENT commune
    (different code, current name) — the core PR-3 behavior."""
    resp = await client.get(
        "/api/administrative/resolve-ward",
        params={"code": LEGACY_MERGED_CODE},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["input_code"] == LEGACY_MERGED_CODE
    assert body["current_code"] == CURRENT_CODE        # ← cross-era resolve
    assert body["current_name"] == CURRENT_NAME
    assert body["current_province_name"] == CURRENT_PROVINCE_NAME  # full 2-level addr
    assert body["resolved"] is True


@pytest.mark.asyncio
async def test_resolve_ward_unmapped_legacy_fails_closed(
    client: AsyncClient, regular_user_token_headers: dict
):
    """Legacy code with no successor mapped → resolved=false (fail-closed)."""
    resp = await client.get(
        "/api/administrative/resolve-ward",
        params={"code": LEGACY_UNMAPPED_CODE},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "input_code": LEGACY_UNMAPPED_CODE,
        "current_code": None,
        "current_name": None,
        "current_province_name": None,
        "resolved": False,
    }


@pytest.mark.asyncio
async def test_resolve_ward_unknown_code_fails_closed(
    client: AsyncClient, regular_user_token_headers: dict
):
    """Completely unknown code → resolved=false."""
    resp = await client.get(
        "/api/administrative/resolve-ward",
        params={"code": "NOPE_99999"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_code"] is None
    assert body["resolved"] is False


@pytest.mark.asyncio
async def test_resolve_ward_requires_auth(client: AsyncClient):
    """Endpoint is gated by get_current_active_user — unauthenticated → 401."""
    resp = await client.get(
        "/api/administrative/resolve-ward", params={"code": CURRENT_CODE}
    )
    assert resp.status_code == 401, resp.text


# ===========================================================================
# 2. PUT /admissions/{id} canonicalizes permanent_commune_code
# ===========================================================================

@pytest_asyncio.fixture
async def adm_config(seed_lead_dependencies: dict):
    """Seed offering chain + path (same shape as
    test_admissions_partial_update_invariants.adm_config)."""
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(code=f"kv_{ts}", name=f"KV_{ts}", display_order=1)
            s.add(ot); await s.flush()
            po = models.ProgramOffering(
                offering_type=f"KV_{ts}", program_id=mpid, offering_type_id=ot.id,
                is_active=True, duration_semesters=6,
            )
            s.add(po); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id, academic_year=2026,
                tuition_fee_per_year=5000000, annual_admission_quota=100, is_published=True,
            )
            s.add(ai); await s.flush()
            am = models.AdmissionMethod(
                code=f"kvm_{ts}", name=f"KVM_{ts}",
                requires_gpa=True, requires_subject_scores=False, is_active=True,
            )
            s.add(am); await s.flush()
            ac = models.AdmissionCriteria(
                method_id=am.id, code=f"KVTC_{ts}", name=f"KVTC_{ts}",
                min_gpa=6.0, scoring_method="average", subject_selection_mode="fixed",
                policy_version="2026.1", is_active=True,
            )
            s.add(ac); await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id,
                admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name="KV Test", display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "round_id": round_id,
    }


async def _create_draft_profile(
    client: AsyncClient, admin_token_headers: dict, adm_config: dict,
    officer_id: int, full_name: str,
) -> int:
    """Seed lead + consultation + draft admission profile under admin token."""
    lead_resp = await client.post(LeadsURLs.LEADS, json={
        "full_name": full_name,
        "phone": f"097{int(datetime.now().timestamp()) % 10_000_000:07d}",
        "source": "website",
        "unit_id": adm_config["unit_id"],
        "assigned_officer_id": officer_id,
        "offering_id": adm_config["offering_id"],
    }, headers=admin_token_headers)
    assert lead_resp.status_code in (200, 201), lead_resp.text
    lead_id = lead_resp.json()["id"]

    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    cons = await client.post(
        f"{LeadsURLs.LEADS}/{lead_id}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "pre-admission"},
        headers=admin_token_headers,
    )
    assert cons.status_code in (200, 201), cons.text

    prof = await client.post(ADMISSIONS, json={
        "lead_id": lead_id,
        "admission_method_id": adm_config["method_id"],
        "admission_round_id": adm_config["round_id"],
        "academic_year": 2026,
    }, headers=admin_token_headers)
    assert prof.status_code in (200, 201), prof.text
    return prof.json()["id"]


async def _read_commune_code(profile_id: int) -> str | None:
    async with AsyncSessionLocal() as s:
        prof = await s.get(models.AdmissionProfile, profile_id)
        return prof.permanent_commune_code


@pytest.mark.asyncio
async def test_update_canonicalizes_legacy_merged_to_current(
    client: AsyncClient, admin_token_headers: dict,
    officer_user_in_db: dict, adm_config: dict,
):
    """PUT with a legacy merged code stores the CURRENT code (canonicalized),
    never the legacy code."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "KV Canonicalize Cross-Era",
    )
    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={"version": 1, "permanent_commune_code": LEGACY_MERGED_CODE},
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text
    assert await _read_commune_code(pid) == CURRENT_CODE  # stored canonical, not legacy


@pytest.mark.asyncio
async def test_update_keeps_unresolvable_code_raw(
    client: AsyncClient, admin_token_headers: dict,
    officer_user_in_db: dict, adm_config: dict,
):
    """PUT with an unresolvable code keeps it raw (submit gate fail-closes
    later) — canonicalization must not blank out an unknown code."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "KV Canonicalize Fallback",
    )
    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={"version": 1, "permanent_commune_code": LEGACY_UNMAPPED_CODE},
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text
    assert await _read_commune_code(pid) == LEGACY_UNMAPPED_CODE  # kept raw
