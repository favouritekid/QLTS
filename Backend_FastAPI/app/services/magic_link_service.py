"""PR-CO-2-BE / PR-3E (Phase 3 close-out plan v2 LOCKED 2026-05-14)
+ FU PR-CO-2-BE-2 (magic-link 3-actions wire, 2026-05-15):
multi-action magic-link consume service.

Sits in front of the existing single-action confirm path
(``admission_service.verify_and_confirm``) and the
submit/resubmit/withdraw handlers. Responsibilities:

  1. Per-token rate limit (5/60s, Redis ``mlt:{token}``, fail-closed)
  2. Action enum match between URL path and DB ``action_type``
  3. CCCD constant-time compare (``hmac.compare_digest``)
  4. Dispatch to the action-specific handler

Wave A acceptance gate "Magic-link consume atomic" is satisfied by the
existing ADM-013 3-step profile-first lock in
``AdmissionRepository.get_token_for_confirm`` — the row lock + the
``confirmed_at IS NULL`` predicate at consume time make concurrent
consumes serialise to a single winner.

All four actions (confirm/submit/resubmit/withdraw) are wired. The
3 non-confirm actions delegate to the existing service functions with
``current_user=None`` / ``actor=None`` (CCCD acts as proof of identity;
``_check_idor_access`` early-returns for ``None`` per its V3 contract).
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..config import settings
from ..utils.token_logging import token_fingerprint
from ..utils.exceptions import (
    BadRequest,
    ResourceNotFoundError,
)
from . import admission_service
from .magic_link_rate_limit import (
    ATTEMPTS_CAP_PER_WINDOW,
    consume_attempt,
)
from ..repositories import AdmissionRepository

log = structlog.get_logger(__name__)


PostCommitCallback = Optional[Callable[[], Awaitable[None]]]


async def consume_token(
    db: AsyncSession,
    token_value: str,
    cccd_last4: str,
    action: str,
) -> Tuple[models.AdmissionProfile, PostCommitCallback]:
    """Consume a magic-link token for the specified action.

    Args:
        db: Async DB session.
        token_value: URL-safe token string from URL path.
        cccd_last4: Last 4 digits of citizen ID from request body.
        action: One of ``submit | resubmit | confirm | withdraw``.

    Returns:
        Tuple of (profile, post_commit_callback). Caller (router)
        commits the transaction and awaits the callback for the
        notification fanout.

    Raises:
        ResourceNotFoundError: Token missing OR action_type mismatch
            (both return 404 to avoid leaking token existence).
        BadRequest: Rate limit hit, expired/used/locked, CCCD wrong, or
            (for ``submit``) profile validation failed.
        ConflictError / domain exceptions from the underlying service:
            propagated as-is so the router's existing handler maps to
            the right status.
    """
    # Step 1 — Per-token rate limit. Fail-closed when Redis breaker open.
    #
    # STATUS-CODE CONTRACT (PR-5 2026-05-28): the two fail-closed branches
    # below raise ``BadRequest`` → HTTP 400. This is INTENTIONALLY different
    # from the legacy router endpoint ``POST /api/admissions/confirm/{token}``
    # (``routers/admissions.py::confirm_admission_by_token``) which returns
    # 503 (Redis breaker) / 429 (cap exceeded). The router can raise
    # ``HTTPException`` directly with the semantically-correct status; this
    # service-layer path cannot (services must never raise ``HTTPException``)
    # and there is no domain exception mapping to 429/503 yet.
    #
    # 400 is the PRESERVED PROD CONTRACT for this already-deployed endpoint,
    # NOT a claim that 400 is the correct HTTP semantics — it is not (the
    # client request is fine; the server is rate-limiting / temporarily
    # unavailable). Normalising magic-link to 429/503 needs new 429/503
    # domain exceptions + a wire test and is deferred to a dedicated
    # domain-exception PR so this hardening PR does not change a deployed
    # contract. See the matching note in confirm_admission_by_token.
    count = await consume_attempt(token_value)
    if count is None:
        # Redis down; treat as rate-limited rather than open the door.
        # Same defensive stance as resend cap (memory `zalo-bot-audit-gap`).
        log.warning(
            "Magic-link consume blocked: rate-limit service unavailable",
            token_fp=token_fingerprint(token_value),
            action=action,
        )
        raise BadRequest(
            "Tạm thời không thể xử lý yêu cầu. Vui lòng thử lại sau ít phút."
        )
    if count > ATTEMPTS_CAP_PER_WINDOW:
        log.warning(
            "Magic-link consume blocked: per-token rate limit exceeded",
            token_fp=token_fingerprint(token_value),
            action=action,
            count=count,
            cap=ATTEMPTS_CAP_PER_WINDOW,
        )
        raise BadRequest(
            f"Đã thử quá {ATTEMPTS_CAP_PER_WINDOW} lần trong 60 giây. "
            "Vui lòng đợi và thử lại."
        )

    # Step 2 — Fetch token with the same ADM-013 3-step profile-first
    # lock used by the existing /confirm/{token} flow. Locks the
    # profile FIRST then the token, eliminating the race that the
    # legacy single-statement lock left open.
    repo = AdmissionRepository(db)
    token_obj = await repo.get_token_for_confirm(token_value)
    if token_obj is None:
        # Generic not-found — do NOT distinguish "wrong token" from
        # "wrong action" in the response (avoids enumeration).
        raise ResourceNotFoundError("Invalid or expired confirmation link")

    # Step 3 — Action enum match. URL action MUST match DB action_type.
    # If a candidate edits the URL from /confirm/<t> to /submit/<t>
    # we treat it as if the token does not exist for that action.
    # Not constant-time critical: action_type values are public.
    if token_obj.action_type != action:
        log.warning(
            "Magic-link action mismatch",
            token_fp=token_fingerprint(token_value),
            url_action=action,
            token_action=token_obj.action_type,
        )
        raise ResourceNotFoundError("Invalid or expired confirmation link")

    # Step 4 — Token freshness gates. Mirrors the existing confirm path
    # so behaviour is identical regardless of which endpoint surface
    # the candidate clicks through.
    now = datetime.now(timezone.utc)

    if token_obj.confirmed_at is not None:
        raise BadRequest("This confirmation link has already been used")

    if token_obj.locked_at is not None:
        raise BadRequest(
            "This confirmation link has been locked due to too many failed attempts. "
            "Please contact support for assistance."
        )

    if token_obj.expires_at < now:
        raise BadRequest(
            "This confirmation link has expired. Please request a new link."
        )

    # Sliding cooldown (ADM-023). Distinct from ``locked_at`` — the
    # cooldown clears itself by passage of time; ``locked_at`` only by
    # an admin reset.
    if token_obj.lock_until is not None and token_obj.lock_until > now:
        retry_in_seconds = int((token_obj.lock_until - now).total_seconds())
        raise BadRequest(
            f"Quá nhiều lần nhập sai. Vui lòng thử lại sau {retry_in_seconds} giây."
        )

    # Step 5 — Profile / CCCD prerequisite.
    profile = token_obj.profile
    if not profile or not profile.citizen_id:
        raise BadRequest("Profile data is incomplete. Please contact support.")

    expected_digits = profile.citizen_id[-settings.ADMISSION_CONFIRM_CCCD_DIGITS:]

    # Constant-time compare via ``hmac.compare_digest`` per plan v2
    # RC2 mitigation (no timing leak). The decision to compare the
    # last-4 digits — not the full CCCD — matches the existing
    # /confirm/{token} contract and the candidate-facing 4-key UX.
    if not hmac.compare_digest(cccd_last4, expected_digits):
        # Delegate brute-force counter bookkeeping to the existing
        # CCCD ladder logic in ``verify_and_confirm`` rather than
        # duplicate ~70 lines of cooldown/hard-lock/dispatch. We
        # invoke the legacy path with the same digits so the existing
        # audit + dispatch + lock_count bookkeeping fires under the
        # exact same row lock we are still holding.
        #
        # H3 review FU (2026-05-14): pass the pre-fetched ``token_obj``
        # so verify_and_confirm skips the second ``get_token_for_confirm``
        # round-trip. Identity-map semantics within the same session
        # make this safe; legacy ``/confirm/{token}`` consumers that
        # don't pre-fetch fall through to the legacy fetch path.
        # The legacy function raises ``BadRequest`` (or attaches a
        # post-commit callback for the hard-lock case) — we propagate.
        await admission_service.verify_and_confirm(
            db=db,
            token_value=token_value,
            last_digits=cccd_last4,
            token_obj=token_obj,
        )
        # Unreachable: the legacy path raises BadRequest on CCCD
        # mismatch. Defensive raise so the type checker can prove
        # the function returns a tuple on every branch below.
        raise BadRequest("CCCD verification failed")

    # Step 6 — Dispatch the action handler. Each handler is responsible
    # for the state mutation + dispatch + returning a post_commit
    # callback that the router awaits after ``db.commit()``.
    if action == "confirm":
        # Delegate wholesale to the proven confirm flow. We re-enter
        # ``verify_and_confirm`` with the correct CCCD — it will
        # short-circuit the freshness gates (still satisfied), pass
        # the CCCD check, atomic-update confirmed_at, dispatch the
        # APPLICATION_CONFIRMED event, and hand back the callback.
        #
        # H3 review FU (2026-05-14): the ``token_obj=token_obj`` kwarg
        # makes verify_and_confirm skip its own ``get_token_for_confirm``
        # round-trip — zero extra DB query on the happy path. The
        # legacy ``/confirm/{token}`` consumer omits the kwarg and
        # still fetches as before. Identity-map within the same
        # AsyncSession guarantees the locked row is reused.
        result_profile, callback = await admission_service.verify_and_confirm(
            db=db,
            token_value=token_value,
            last_digits=cccd_last4,
            token_obj=token_obj,
        )
        return result_profile, callback

    # FU PR-CO-2-BE-2 — wired handlers for submit / resubmit / withdraw.
    # Each handler:
    #   1. Stamps token.confirmed_at = NOW() inside the same row lock so
    #      concurrent consumes serialise (mirrors the confirm path's
    #      atomicity guarantee).
    #   2. Delegates to the existing officer-side service function with
    #      ``current_user=None`` / ``actor=None``. The service layer's
    #      ``_check_idor_access`` early-returns for ``None`` (CCCD has
    #      already proven identity at step 5 above).
    #   3. Returns ``(profile, post_commit_callback)`` — router commits
    #      then awaits the callback.
    if action == "submit":
        return await _handle_submit(db, token_obj, profile)
    if action == "resubmit":
        return await _handle_resubmit(db, token_obj, profile)
    if action == "withdraw":
        return await _handle_withdraw(db, token_obj, profile)

    # Unknown action — should be unreachable because the router enum
    # match (step 3) already filtered. Defensive 404 mirroring the
    # earlier "invalid token / action" branches.
    raise ResourceNotFoundError("Invalid or expired confirmation link")


# =========================================================================
# Action handlers (FU PR-CO-2-BE-2)
# =========================================================================


async def _handle_submit(
    db: AsyncSession,
    token_obj: "models.AdmissionConfirmationToken",
    profile: "models.AdmissionProfile",
) -> Tuple["models.AdmissionProfile", PostCommitCallback]:
    """Candidate magic-link submit (draft → submitted).

    Delegates to ``admission_service.submit_and_evaluate(current_user=None)``.
    The Item A submit guard (count(choices) >= 1 for multi-NV profiles)
    applies automatically — a candidate cannot submit an empty multi-NV
    profile via magic-link any more than via dashboard.
    """
    token_obj.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    result_dict, post_commit = await admission_service.submit_and_evaluate(
        db=db,
        profile_id=profile.id,
        current_user=None,
    )

    if result_dict.get("status") != "submitted":
        # Validation errors — the service rolled the profile back to
        # ``draft`` and returned the error list. Surface as 400 so the
        # FE landing page can render the validation issues.
        errors = result_dict.get("validation_errors") or []
        joined = "; ".join(errors) if errors else "Hồ sơ chưa hợp lệ để nộp."
        raise BadRequest(joined)

    return profile, post_commit


async def _handle_resubmit(
    db: AsyncSession,
    token_obj: "models.AdmissionConfirmationToken",
    profile: "models.AdmissionProfile",
) -> Tuple["models.AdmissionProfile", PostCommitCallback]:
    """Candidate magic-link resubmit (revision_requested → resubmitted).

    State edge ``revision_requested → resubmitted`` already exists in
    ``ALLOWED_TRANSITIONS`` (admission_state_machine.py), so the standard
    ``resubmit_profile`` handles the candidate path with no edge add.
    """
    token_obj.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    result_profile, callback = await admission_service.resubmit_profile(
        db=db,
        profile_id=profile.id,
        officer=None,
        data={
            "notes": "Ứng viên tự nộp lại qua magic-link",
            # version omitted intentionally — candidate flow doesn't
            # surface optimistic-locking version to the public FE.
        },
    )
    return result_profile, callback


async def _handle_withdraw(
    db: AsyncSession,
    token_obj: "models.AdmissionConfirmationToken",
    profile: "models.AdmissionProfile",
) -> Tuple["models.AdmissionProfile", PostCommitCallback]:
    """Candidate magic-link withdraw — withdraw_profile already accepts
    ``actor=None`` after FU PR-CO-2-BE-2 hardening.

    The current ``profile.version`` is read inside the service after the
    row lock — passing it here from the pre-lock snapshot would be racy.
    The service treats a version match against its own re-read as the
    optimistic-locking gate.
    """
    token_obj.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    result_profile, callback = await admission_service.withdraw_profile(
        db=db,
        profile_id=profile.id,
        actor=None,
        data={
            "reason": "Ứng viên tự rút hồ sơ qua magic-link",
            "version": profile.version,
        },
    )
    return result_profile, callback
