"""Regression suite — withdraw must survive a SHALLOW-loaded ``choices``
relation (fix/admission-choices-eager-graph, 2026-07-20).

Background — production bug found while rehearsing a bulk withdrawal:

    Withdrawing a profile that still has an UNPAID HK1 tuition fee returned
    HTTP 500. ``withdraw_profile`` STEP 2 cancels every unpaid fee;
    ``cancel_fee`` reverts the HK1-tuition lead projection and for that calls
    ``fee_calculation_service._get_profile``, which eager-loads only
    ``selectinload(AdmissionProfile.choices)`` — SHALLOW. The profile lands in
    the identity map with ``choices`` marked loaded but the nested graph still
    lazy. ``_populate_response_fields`` then asked only
    ``"choices" in inspect(profile).unloaded`` → False → skipped its defensive
    reload → ``_resolve_allowed_subjects`` touched ``group.subject_mappings``
    from sync code → ``MissingGreenlet`` → 500 and the whole withdrawal rolled
    back. Several live profiles were left unwithdrawable through the UI.

The fix is ONE layer, deliberately: ``_choices_eager_graph_incomplete``
validates the whole ``_choice_eager_paths()`` contract at the response
chokepoint and reloads when any hop is unloaded.

    A second "belt" layer — making ``_resolve_allowed_subjects`` degrade to
    ``[]`` on an unloaded graph — was written, reviewed, and REMOVED. ``[]``
    is fail-closed only from the submit gate's point of view; the T6 publish
    cascade reads the same helper and treats an empty allowed-set as "cannot
    score", skipping straight to a persisted ``decision='rejected'`` with an
    EMPTY reason list. It turned a loud, rolled-back 500 into a silent,
    permanent, unexplainable rejection of a qualified candidate. Do not
    reintroduce it: a graph that is not loaded must stop the caller, never
    produce a decision.

Non-tautological: every test asserts concrete DB state / status codes /
message text that a regression cannot satisfy by accident.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# FIXTURES / HELPERS
# ==============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_sts08(seed_lead_dependencies: dict):
    """``lead_admission_sync`` moves a withdrawn profile's lead to sts08."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = await session.get(models.ConsultationStatus, "sts08")
            if existing is None:
                session.add(
                    models.ConsultationStatus(
                        id="sts08",
                        name="Khong tiep tuc ho so",
                        color_code="#FF0000",
                        # stg07 = "Khong di hoc" (is_final_stage). stage_id MUST
                        # match
                        # test_tuition_prepay_flow::_ensure_consultation_status
                        # — both are get-or-create against a shared qlts_test, so a
                        # mismatch makes the winner collection-order dependent.
                        stage_id="stg07",
                    )
                )
    return seed_lead_dependencies


async def _seed_multi_nv_profile(
    seed_lead_dependencies: dict,
    *,
    status: str = "submitted",
) -> dict:
    """Seed a multi-NV profile whose single choice carries the full
    subject-group graph (path → config → group → mapping → subject).

    Mirrors the anchor seeding in
    ``tests/api/test_admission_response_choices_serialization.py`` so both
    suites exercise the same shape.
    """
    suffix = uuid.uuid4().hex[:8]
    unit_id = seed_lead_dependencies["unit_id"]
    program_id = seed_lead_dependencies["major_program_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering_type = models.ConfigOfferingType(
                code=f"eg_ot_{suffix}", name=f"EG OT {suffix}", is_active=True,
            )
            s.add(offering_type)
            await s.flush()

            offering = models.ProgramOffering(
                offering_type=f"eg_ot_{suffix}",
                program_id=program_id,
                offering_type_id=offering_type.id,
            )
            s.add(offering)
            await s.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id, academic_year=2026, is_published=True,
            )
            s.add(academic_info)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"eg_m_{suffix}", name="EG method", is_active=True,
            )
            s.add(method)
            await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"eg_c_{suffix}",
                name="EG criteria",
                min_gpa=0,
                is_active=True,
            )
            s.add(criteria)
            await s.flush()

            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"EG_R_{suffix}",
                round_name=f"EG round {suffix}",
                is_active=True,
                allow_multi_nv=True,
            )
            s.add(round_obj)
            await s.flush()

            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_obj.id,
                criteria_id=criteria.id,
                status="active",
            )
            s.add(path)
            await s.flush()

            # SubjectGroup.code is VARCHAR(10).
            subject_group = models.SubjectGroup(
                code=f"eg{suffix[:6]}", name=f"Tổ hợp {suffix}", is_active=True,
            )
            s.add(subject_group)
            await s.flush()

            subject = models.Subject(
                code=f"S{suffix[:4]}",
                name_vi=f"Môn {suffix}",
                is_active=True,
            )
            s.add(subject)
            await s.flush()

            s.add(
                models.SubjectGroupSubject(
                    subject_group_id=subject_group.id,
                    subject_id=subject.id,
                    position=1,
                )
            )
            await s.flush()

            sg_config = models.PathSubjectGroupConfig(
                admission_path_id=path.id, subject_group_id=subject_group.id,
            )
            s.add(sg_config)
            await s.flush()

            lead = models.Lead(
                full_name=f"Eager graph {suffix}",
                phone=f"097{random.randint(1000000, 9999999)}",
                email=f"eager_{suffix}@test.com",
                source="walkin",
                unit_id=unit_id,
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                consultation_status_id="sts06",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=uuid.uuid4().hex[:12],
                status=status,
                applied_rules={},
                academic_year=2026,
                version=1,
                uses_choice_engine=True,
            )
            s.add(profile)
            await s.flush()

            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path.id,
                path_subject_group_config_id=sg_config.id,
                display_order=1,
                decision="pending",
            )
            s.add(choice)
            await s.flush()

            # One score row so the ("scores", "subject") leg is actually
            # walked. With zero scores the collection is empty and BOTH
            # directions of the parity assertion pass vacuously — the leg
            # could be dropped from the repository and nothing would fail.
            s.add(
                models.ProfileChoiceScore(
                    admission_profile_choice_id=choice.id,
                    subject_id=subject.id,
                    score=Decimal("8.0"),
                    max_score_snapshot=Decimal("10.0"),
                    weight_snapshot=Decimal("1.0"),
                )
            )
            await s.flush()

            return {
                "profile_id": profile.id,
                "lead_id": lead.id,
                "subject_code": subject.code,
                "suffix": suffix,
            }


async def _add_fee(
    session,
    profile_id: int,
    *,
    fee_type: str,
    semester_no: int | None,
    final_amount: Decimal,
    paid_amount: Decimal,
    status: str,
    with_invoice: bool = False,
) -> models.Fee:
    fee = models.Fee(
        admission_profile_id=profile_id,
        fee_type=fee_type,
        semester_no=semester_no,
        academic_year=2026,
        base_amount=final_amount,
        total_discount=Decimal("0"),
        final_amount=final_amount,
        paid_amount=paid_amount,
        waived_amount=Decimal("0"),
        status=status,
        calculated_at=datetime.now(timezone.utc),
        version=1,
    )
    session.add(fee)
    await session.flush()

    if with_invoice:
        session.add(
            models.Invoice(
                fee_id=fee.id,
                invoice_number=f"INV-T-{uuid.uuid4().hex[:10]}",
                installment_no=1,
                amount=final_amount,
                paid_amount=Decimal("0"),
                penalty_amount=Decimal("0"),
                status="issued",
                due_date=date.today() + timedelta(days=30),
            )
        )
        await session.flush()
    return fee


# ==============================================================================
# T1 — the identity-map repro, at the guard level
# ==============================================================================


class TestChoicesEagerGraphGuard:
    async def test_shallow_loaded_choices_is_reported_incomplete(
        self, seed_lead_dependencies: dict,
    ) -> None:
        """A profile loaded with a bare ``selectinload(choices)`` — exactly
        what ``fee_calculation_service._get_profile`` does — must be reported
        INCOMPLETE, otherwise the chokepoint skips its reload and the sync
        response code lazy-loads (MissingGreenlet).

        The pre-fix guard (``"choices" in inspect(profile).unloaded``) returns
        False here, so this test fails on a revert.
        """
        from app.services.admission_service import (
            _choices_eager_graph_incomplete,
        )

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)

        async with AsyncSessionLocal() as s:
            profile = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(
                        models.AdmissionProfile.id == seeded["profile_id"]
                    )
                    .options(selectinload(models.AdmissionProfile.choices))
                )
            ).scalar_one()

            # Top-level relation IS loaded — the old guard was satisfied here.
            assert "choices" not in sa.inspect(profile).unloaded, (
                "precondition: shallow selectinload must mark choices loaded"
            )
            assert _choices_eager_graph_incomplete(profile) is True, (
                "shallow-loaded choices must be reported incomplete — the "
                "nested subject-group graph is still lazy"
            )

    async def test_repository_eager_load_is_reported_complete(
        self, seed_lead_dependencies: dict,
    ) -> None:
        """The list the chokepoint injects must satisfy its own guard —
        otherwise the reload would loop or fire on every mutation."""
        from sqlalchemy.orm.attributes import set_committed_value

        from app.repositories.admission_profile_choice_repository import (
            AdmissionProfileChoiceRepository,
        )
        from app.services.admission_service import (
            _choices_eager_graph_incomplete,
        )

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)

        async with AsyncSessionLocal() as s:
            profile = await s.get(
                models.AdmissionProfile, seeded["profile_id"]
            )
            fresh = await AdmissionProfileChoiceRepository(s).list_by_profile(
                profile.id
            )
            set_committed_value(profile, "choices", fresh)

            assert _choices_eager_graph_incomplete(profile) is False, (
                "list_by_profile(eager=True) output must satisfy the guard; "
                "if this fails the guard checks a relation the repository "
                "does not load — they must stay in sync"
            )

    async def test_guard_pinpoints_the_deep_subject_mappings_hop(
        self, seed_lead_dependencies: dict,
    ) -> None:
        """Pin WHICH hop is actually lazy, so a future model change that flips
        ``lazy=`` is caught here rather than in production.

        ``AdmissionProfileChoice.admission_path`` /
        ``path_subject_group_config`` / ``scores`` are declared
        ``lazy="selectin"`` (admission_profile_choice.py:193-205), so a bare
        ``selectinload(AdmissionProfile.choices)`` already drags those in —
        which is exactly why the old top-level guard looked satisfied. The
        genuinely unloaded hop is ``SubjectGroup.subject_mappings``, the one
        that raised MissingGreenlet in production.
        """
        from app.services.admission_service import (
            _choices_eager_graph_incomplete,
        )

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)

        async with AsyncSessionLocal() as s:
            profile = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(
                        models.AdmissionProfile.id == seeded["profile_id"]
                    )
                    .options(selectinload(models.AdmissionProfile.choices))
                )
            ).scalar_one()

            choice = profile.__dict__["choices"][0]
            config = choice.__dict__.get("path_subject_group_config")
            assert config is not None, (
                "lazy='selectin' should have auto-loaded the config"
            )
            group = config.__dict__.get("subject_group")
            assert group is not None, (
                "lazy='selectin' should have auto-loaded the subject_group"
            )
            assert "subject_mappings" in sa.inspect(group).unloaded, (
                "subject_mappings is THE lazy hop that crashed production; if "
                "this fails the model changed and the guard needs revisiting"
            )

            # Assert the SUBJECT-GROUP leg ALONE is reported incomplete.
            # Asserting the whole guard here would pass through an unrelated
            # leg: AdmissionPath.admission_method/criteria/academic_info/
            # admission_round are all default-lazy too, so the guard trips on
            # the FIRST of them and never reaches the hop this test names.
            # NOTE this pins the WALKER's descent, not the contents of
            # the guard's leg set (the leg is passed as a literal). Removing
            # that leg from the table is caught by
            # test_guard_matches_repository_eager_contract, not here.
            from app.services.admission_service import (
                _relation_path_incomplete,
            )
            sg_leg = ("path_subject_group_config", "subject_group",
                      "subject_mappings", "subject")
            assert _relation_path_incomplete(choice, sg_leg) is True, (
                "the subject-group leg must be reported incomplete on its own"
            )
            assert _choices_eager_graph_incomplete(profile) is True

    async def test_guard_matches_repository_eager_contract(
        self, seed_lead_dependencies: dict,
    ) -> None:
        """PARITY, in the direction that actually breaks: every relationship
        the repository eager-loads must be covered by the guard's leg set
        (``_choice_eager_paths()``, now derived from
        ``_choices_eager_load_options()`` — this test is what pins that that
        loader stays a subset of what ``list_by_profile`` actually loads).

        The dangerous drift is the repository growing a leg the guard does not
        know about — the guard then reports "complete", the reload is skipped,
        and the MissingGreenlet 500 returns with the fix still in place. A test
        that merely asserts ``incomplete is False`` on a fully-loaded profile
        cannot catch that: a guard checking NOTHING satisfies it too.

        So: load via the repository, walk the graph it actually populated, and
        require each loaded relationship path to be a prefix of a declared leg.
        """
        from app.repositories.admission_profile_choice_repository import (
            AdmissionProfileChoiceRepository,
        )
        from app.services.admission_service import (
            _choice_eager_paths,
            _relation_path_incomplete,
        )

        declared = set(_choice_eager_paths())

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)

        max_depth = max(len(leg) for leg in declared)

        def _loaded_paths(obj: Any, prefix: tuple = ()) -> set:
            """Relationship paths actually populated on ``obj``.

            Depth cap is derived from the declared legs (+1) so a repository
            chain DEEPER than anything declared is still observed — a fixed
            cap equal to the longest leg would make such drift invisible.
            """
            found: set = set()
            if obj is None or len(prefix) > max_depth:
                return found
            if isinstance(obj, (list, tuple)):
                for item in obj:
                    found |= _loaded_paths(item, prefix)
                return found
            state = sa.inspect(obj, raiseerr=False)
            if state is None or not hasattr(state, "mapper"):
                return found
            for rel in state.mapper.relationships.keys():
                if rel not in obj.__dict__:
                    continue  # not loaded — nothing to cover
                path = prefix + (rel,)
                found.add(path)
                found |= _loaded_paths(obj.__dict__[rel], path)
            return found

        async with AsyncSessionLocal() as s:
            choices = await AdmissionProfileChoiceRepository(
                s
            ).list_by_profile(seeded["profile_id"])
            assert choices, (
                "seed must produce at least one choice — an empty list makes "
                "every assertion below vacuously true"
            )
            loaded = set()
            for choice in choices:
                loaded |= _loaded_paths(choice)
        assert loaded, "walk found no loaded relationships — test is vacuous"

        def _covered(path: tuple) -> bool:
            # A loaded path is covered when it is a prefix of a declared leg
            # (the guard walks the full leg, so it inspects every prefix).
            return any(leg[:len(path)] == path for leg in declared)

        # Exclude the ``profile`` back-reference: list_by_profile never loads
        # AdmissionProfile, so it does not appear in ``loaded`` today — this is
        # a defensive filter against a future explicit backref eager-load,
        # narrow on purpose (``p[0]``, not a blanket set) so it cannot mask a
        # genuine uncovered leg.
        uncovered = {
            p for p in loaded if not _covered(p) and p[0] != "profile"
        }
        assert not uncovered, (
            f"the repository eager-loads relationship path(s) the guard does "
            f"not check: {sorted(uncovered)}. Add them to "
            f"the loader/guard contract in admission_service.py, or the "
            f"reload will "
            f"be skipped on a graph that is actually incomplete."
        )

        # And the reverse: nothing declared may be missing from a repository
        # load, else the guard would demand a reload on every single request.
        for leg in declared:
            for choice in choices:
                assert not _relation_path_incomplete(choice, leg), (
                    f"guard declares leg {leg} that list_by_profile does not "
                    f"load — every mutation would fire a redundant reload"
                )


# ==============================================================================
# T2/T3 — the live withdraw scenarios
# ==============================================================================


class TestWithdrawWithUnpaidHK1Tuition:
    async def test_unpaid_hk1_tuition_withdraws_and_cancels_fee(
        self,
        seed_lead_dependencies: dict,
        seed_sts08: dict,
        admin_user_in_db: dict,
    ) -> None:
        """THE production repro shape.

        submitted + application fee paid + HK1 tuition ``invoiced``/unpaid.
        STEP 2 cancels the tuition fee → ``cancel_fee`` shallow-loads choices
        → pre-fix this raised MissingGreenlet and rolled the whole withdrawal
        back. Must now settle to ``withdrawn`` with the tuition fee AND its
        invoice cancelled, while the non-refundable application fee is kept.
        """
        from app.services import admission_service

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)
        profile_id = seeded["profile_id"]

        async with AsyncSessionLocal() as s:
            async with s.begin():
                await _add_fee(
                    s, profile_id,
                    fee_type="application", semester_no=None,
                    final_amount=Decimal("70000"),
                    paid_amount=Decimal("70000"),
                    status="paid",
                )
                await _add_fee(
                    s, profile_id,
                    fee_type="tuition", semester_no=1,
                    final_amount=Decimal("9200000"),
                    paid_amount=Decimal("0"),
                    status="invoiced",
                    with_invoice=True,
                )

        async with AsyncSessionLocal() as s:
            actor = await s.get(models.User, admin_user_in_db["id"])
            assert actor is not None, "admin_user_in_db fixture must seed one"

            profile = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile_id)
                    .options(selectinload(models.AdmissionProfile.lead))
                )
            ).scalar_one()

            result, callback = await admission_service.withdraw_profile(
                db=s,
                profile_id=profile_id,
                actor=actor,
                data={
                    "reason": "Rút hồ sơ — repro HK1 chưa thu",
                    "version": profile.version,
                },
            )
            await s.commit()
            if callback:
                await callback()

            assert result.status == "withdrawn", (
                f"no refundable money collected → must settle straight to "
                f"withdrawn; got {result.status!r}"
            )

        async with AsyncSessionLocal() as s:
            fees = (
                await s.execute(
                    select(models.Fee).where(
                        models.Fee.admission_profile_id == profile_id
                    )
                )
            ).scalars().all()
            by_type = {f.fee_type: f for f in fees}

            assert by_type["tuition"].status == "cancelled", (
                "unpaid HK1 tuition must be cancelled by STEP 2 — this is "
                "what closes the 'still collectable after withdrawal' hole"
            )
            assert by_type["application"].status == "paid", (
                "lệ phí xét tuyển is non-refundable and must be left intact"
            )

            invoice_statuses = (
                await s.execute(
                    select(models.Invoice.status)
                    .join(models.Fee, models.Fee.id == models.Invoice.fee_id)
                    .where(models.Fee.admission_profile_id == profile_id)
                )
            ).scalars().all()
            assert invoice_statuses == ["cancelled"], (
                f"cancel_fee must cascade to the one tuition invoice; got "
                f"{invoice_statuses} (a bare all() would pass on an empty list)"
            )

            lead_status = (
                await s.execute(
                    select(models.Lead.consultation_status_id).where(
                        models.Lead.id == seeded["lead_id"]
                    )
                )
            ).scalar_one()
            assert lead_status == "sts08", (
                f"withdrawn profile must push lead to sts08; got {lead_status}"
            )

    async def test_unpaid_hk1_plus_collected_fee_goes_withdrawal_pending(
        self,
        seed_lead_dependencies: dict,
        seed_sts08: dict,
        admin_user_in_db: dict,
    ) -> None:
        """The rarer branch the reviewer asked to cover: an unpaid HK1 tuition
        (→ triggers the shallow load) PLUS refundable money already collected
        (→ routes to ``withdrawal_pending`` instead of ``_finalize_withdrawn``).

        Both branches call ``_populate_response_fields``, so this pins the
        second entry point against the same crash.

        ``paid_amount`` is set on the fee directly: STEP 3 computes the
        refundable balance in-memory from the fee rows, so this reaches the
        withdrawal_pending branch without seeding payment-method scaffolding.
        """
        from app.services import admission_service

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)
        profile_id = seeded["profile_id"]

        async with AsyncSessionLocal() as s:
            async with s.begin():
                await _add_fee(
                    s, profile_id,
                    fee_type="tuition", semester_no=1,
                    final_amount=Decimal("9200000"),
                    paid_amount=Decimal("0"),
                    status="invoiced",
                    with_invoice=True,
                )
                await _add_fee(
                    s, profile_id,
                    fee_type="tuition", semester_no=2,
                    final_amount=Decimal("5000000"),
                    paid_amount=Decimal("2570000"),
                    status="partial",
                )

        async with AsyncSessionLocal() as s:
            actor = await s.get(models.User, admin_user_in_db["id"])
            profile = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile_id)
                    .options(selectinload(models.AdmissionProfile.lead))
                )
            ).scalar_one()

            result, callback = await admission_service.withdraw_profile(
                db=s,
                profile_id=profile_id,
                actor=actor,
                data={
                    "reason": "Rút hồ sơ — còn tiền phải hoàn",
                    "version": profile.version,
                },
            )
            await s.commit()
            if callback:
                await callback()

            assert result.status == "withdrawal_pending", (
                f"refundable money still held → must wait in "
                f"withdrawal_pending; got {result.status!r}"
            )

        async with AsyncSessionLocal() as s:
            lead_status = (
                await s.execute(
                    select(models.Lead.consultation_status_id).where(
                        models.Lead.id == seeded["lead_id"]
                    )
                )
            ).scalar_one()
            assert lead_status == "sts06", (
                f"lead must be HELD at its pre-withdraw status until the "
                f"refund completes (a '!= sts08' assertion would also accept "
                f"a wrong terminal status); got {lead_status}"
            )


# ==============================================================================
# T4 — response serialization must not lazy-load either
# ==============================================================================


class TestResponseSerializationAfterShallowLoad:
    async def test_admission_response_serializes_after_shallow_choices_load(
        self, seed_lead_dependencies: dict, admin_user_in_db: dict,
    ) -> None:
        """``AdmissionProfileChoiceResponse`` getattr-walks admission_path,
        academic_info/offering/program, method/round, subject-group config and
        scores.subject (schemas/admission_profile_choice.py:156). So a shallow
        graph 500s at SERIALIZATION even when no validation code runs.

        After ``_populate_response_fields`` repairs the graph, model_validate
        must succeed AND the display fields must be populated — proving the
        reload injected real data rather than an empty placeholder.
        """
        from app.schemas.admission import AdmissionProfileResponse
        from app.services.admission_service import _populate_response_fields

        seeded = await _seed_multi_nv_profile(seed_lead_dependencies)

        async with AsyncSessionLocal() as s:
            actor = await s.get(models.User, admin_user_in_db["id"])

            profile = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(
                        models.AdmissionProfile.id == seeded["profile_id"]
                    )
                    .options(
                        selectinload(models.AdmissionProfile.lead),
                        # SHALLOW — mirrors fee_calculation_service._get_profile
                        selectinload(models.AdmissionProfile.choices),
                    )
                )
            ).scalar_one()

            await _populate_response_fields(s, profile, actor)

            payload = AdmissionProfileResponse.model_validate(profile)

        assert len(payload.choices) == 1, (
            f"seeded choice must serialize; got {len(payload.choices)}"
        )
        assert payload.choices[0].display_subject_group_name, (
            "display_subject_group_name comes from the nested subject_group; "
            "empty means the repaired graph did not reach it"
        )
