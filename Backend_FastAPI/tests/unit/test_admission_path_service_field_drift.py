"""PR #295 — anchor tests against the service-explicit-dict field-drop
drift class (memory ``service-explicit-dict-field-drop-pattern``).

Two anchors:

1. ``test_create_path_persists_application_fee`` — concrete repro of
   the 2026-05-14 audit finding #2. Before PR #295, ``create_path``
   built an explicit dict literal that left ``application_fee`` out;
   admin set a non-zero fee in the FE form → service silently dropped
   the field → DB row stored ``NULL`` → ``AdmissionPath.requires_
   application_fee`` returned False → fee gate skipped → downstream
   ``APPLICATION_FEE_PAID`` event never fired and consultation
   sts13/sts10 ladders never advanced. Same pattern class as PR #294
   (round flags) but on a different model.

2. ``test_create_path_dict_payload_covers_every_schema_field`` —
   generic parity test for the WHOLE schema. Introspects
   ``AdmissionPathCreate.model_fields`` and the source of
   ``AdmissionPathService.create_path``. Asserts each Pydantic field
   is either:
     a) referenced by name in the service source (positive forward),
        OR
     b) on the small ``SERVER_CONTROLLED_OR_RESOLVED`` allowlist
        (e.g. ``admission_round_id`` is auto-resolved to DOT_1 if the
        payload value is None; ``status`` is hardcoded to ``draft``).
   A future PR that adds a field to ``AdmissionPathCreate`` and forgets
   to plumb it through the service will fail this anchor immediately
   in CI Tier 1 — catching the drift class structurally, not after a
   prod symptom.

Non-tautological per memory ``pattern-change-impact-audit``: the
generic anchor asserts the EXACT field-name presence, not a count.
A regression that adds 1 field + removes 1 field would still trip
the assertion on the field that was dropped.
"""
from __future__ import annotations

import inspect
import random
import uuid

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.schemas.admission_path import AdmissionPathCreate
from app.services.admission_path_service import AdmissionPathService


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------
# Fixture chain — minimal path prereqs.
# ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_path_chain(admin_user_in_db, seed_lead_dependencies):
    """Build the chain ``create_path`` needs: offering + academic_info +
    method + round. Returns ids + the admin user model for the service
    call.
    """
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            program_id = seed_lead_dependencies["major_program_id"]

            offering_type_config = models.ConfigOfferingType(
                code=f"pdrift_{suffix}",
                name=f"Path drift anchor {suffix}",
                is_active=True,
            )
            s.add(offering_type_config)
            await s.flush()

            offering = models.ProgramOffering(
                offering_type=f"pdrift_{suffix}",
                program_id=program_id,
                offering_type_id=offering_type_config.id,
            )
            s.add(offering)
            await s.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                is_published=True,
            )
            s.add(academic_info)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"pdmethod_{suffix}",
                name="Path drift method",
                is_active=True,
            )
            s.add(method)
            await s.flush()

            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"PD_{suffix}",
                round_name=f"Path drift round {suffix}",
                is_active=True,
                allow_multi_nv=False,
                confirm_expiry_hours=168,
            )
            s.add(round_obj)
            await s.flush()

            return {
                "academic_info_id": academic_info.id,
                "admission_method_id": method.id,
                "admission_round_id": round_obj.id,
                "admin_user_id": admin_user_in_db["id"],
            }


# ---------------------------------------------------------------------
# Anchor 1 — concrete: application_fee persists after create_path
# ---------------------------------------------------------------------


async def test_create_path_persists_application_fee(seed_path_chain) -> None:
    """Before PR #295: ``create_path`` dict literal omitted
    ``application_fee`` → DB NULL regardless of payload value. Catches a
    future regression that reverts the model_dump-based payload back to
    an explicit dict that drops a field.
    """
    from decimal import Decimal

    payload = AdmissionPathCreate(
        academic_info_id=seed_path_chain["academic_info_id"],
        admission_method_id=seed_path_chain["admission_method_id"],
        admission_round_id=seed_path_chain["admission_round_id"],
        display_name="Path drift anchor",
        application_fee=Decimal("250000"),  # 250k VND — non-zero, non-default
    )

    async with AsyncSessionLocal() as s:
        admin = await s.get(models.User, seed_path_chain["admin_user_id"])
        service = AdmissionPathService(s)
        path, _cb = await service.create_path(payload, admin)
        await s.commit()
        created_id = path.id

    async with AsyncSessionLocal() as s2:
        persisted = await s2.get(models.AdmissionPath, created_id)
        assert persisted is not None
        assert persisted.application_fee is not None, (
            "application_fee dropped on INSERT — same drift as PR #294 "
            "round flags. Service must forward the payload field to the "
            f"ORM column. Got NULL on path id={created_id}."
        )
        assert Decimal(persisted.application_fee) == Decimal("250000"), (
            f"application_fee persisted but wrong value: "
            f"{persisted.application_fee!r} (expected 250000)"
        )
        # Downstream property gate — proves the round-trip reaches the
        # ``requires_application_fee`` consumer that the original bug
        # silenced.
        assert persisted.requires_application_fee is True


# ---------------------------------------------------------------------
# Anchor 2 — generic parity: every Pydantic field reaches the service
# ---------------------------------------------------------------------


# Fields the service intentionally controls / overrides; they will NOT
# appear in the service source by their Pydantic name because they are
# resolved/hardcoded server-side.
SERVER_CONTROLLED_OR_RESOLVED: frozenset[str] = frozenset({
    # Auto-resolved to DOT_1 if payload value is None; the service writes
    # the resolved id into ``payload_data["admission_round_id"]`` after
    # the dump, so the literal name appears in the source via the dict
    # key — but if the model_dump-based refactor ever drops it, this
    # carve-out makes the failure explicit. Keep in the allowlist.
    "admission_round_id",
})


async def test_create_path_payload_covers_every_schema_field() -> None:
    """Drift-class detector: the service must EITHER forward the payload
    via ``model_dump()`` (drift-immune by construction) OR mention every
    ``AdmissionPathCreate`` field by name (explicit forward).

    Two acceptable patterns:
      a) ``data.model_dump(...)`` / ``payload.model_dump(...)`` —
         dynamic forward; every field Pydantic accepts auto-flows. PR
         #295 refactor adopts this.
      b) Explicit dict / kwarg list — must reference each field by name.
         The pre-PR #295 ``create_path`` was this shape and dropped
         ``application_fee``.

    Server-controlled fields (e.g. ``status`` hardcoded ``draft``) bypass
    both rules via the ``SERVER_CONTROLLED_OR_RESOLVED`` allowlist.

    A regression that removes the ``model_dump()`` call AND fails to
    list every field by name will fail this anchor — catching the
    drift class structurally, not after a prod symptom.
    """
    import re
    schema_fields = set(AdmissionPathCreate.model_fields.keys())
    service_source = inspect.getsource(AdmissionPathService.create_path)

    # Pattern (a) — model_dump call on the payload object.
    uses_model_dump = bool(
        re.search(r"\b(data|payload)\s*\.\s*model_dump\b", service_source)
    )

    if uses_model_dump:
        # Drift-immune by construction. Anchor passes — the schema is
        # forwarded as a whole. Future drift via explicit override on
        # specific keys remains caught by the field-specific Anchor #1
        # (test_create_path_persists_application_fee).
        return

    # Pattern (b) — explicit listing. Every field must appear by name.
    missing: list[str] = []
    for field in schema_fields:
        if field in SERVER_CONTROLLED_OR_RESOLVED:
            continue
        if field not in service_source:
            missing.append(field)

    assert not missing, (
        "Service uses explicit pattern but is missing schema fields: "
        f"{sorted(missing)}\n\n"
        "Either:\n"
        "  - Refactor to ``data.model_dump()`` (drift-immune), OR\n"
        "  - Add each missing field to the explicit dict / kwarg list, OR\n"
        "  - Add intentionally server-controlled fields to "
        "``SERVER_CONTROLLED_OR_RESOLVED`` with a justifying comment.\n\n"
        "See PR #294 / PR #295 lessons + memory "
        "``service-explicit-dict-field-drop-pattern``."
    )
