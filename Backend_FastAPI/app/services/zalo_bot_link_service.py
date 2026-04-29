"""Zalo Bot link service.

Three flows:
- ``generate_link_code(user_id)`` — produce a 6-char one-shot code stored
  in Redis with TTL 600s. Idempotent per user: regenerating supersedes
  any previous unconsumed code.
- ``verify_and_link(code, chat_id, display_name)`` — atomically consume
  the code and bind the chat_id to the user.
- ``unlink(user_id)`` / ``unlink_by_chat_id(chat_id)`` — mark the link
  inactive and flip the user's per-channel preference.

Atomicity guarantees:
- Code creation uses ``SET NX`` so colliding codes are rejected by Redis,
  not by the application.
- Code consumption uses ``GETDEL`` so two webhook deliveries racing on
  the same code can't both succeed.
- Both operations return early on Redis failure (``safe_redis_*`` helpers
  shield via the circuit breaker).
"""
from __future__ import annotations

import secrets
import string
from typing import Callable, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.staff_zalo_bot_link_repository import (
    StaffZaloBotLinkRepository,
)
from app.services import notification_consent_service
from app.utils.exceptions import BusinessRuleViolation
from app.utils.masking import mask_chat_id

log = structlog.get_logger(__name__)

# v5/E8: 10 minutes — staff hand off code through Zalo app, search bot,
# add bot, and finally type ``/lienkiet <CODE>``. 5 min was too tight.
LINK_CODE_TTL = 600
LINK_CODE_PREFIX = "zalo_bot:link:"

# Code alphabet excludes lowercase + ambiguous chars implicitly because
# Zalo chat clients display fixed-width fonts inconsistently. 36^6 ≈
# 2.1B combinations — collision probability per generation is negligible
# but the SET NX retry below covers the pathological case.
_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 6
_GEN_RETRIES = 5


def _user_pointer_key(user_id: int) -> str:
    """Per-user reverse pointer so regenerate can revoke the old code.

    Stored alongside the code itself; both expire on TTL even if the
    pointer revoke step is skipped (e.g. process crash mid-flow).
    """
    return f"{LINK_CODE_PREFIX}user:{user_id}"


def _code_key(code: str) -> str:
    return f"{LINK_CODE_PREFIX}{code}"


async def generate_link_code(
    db: AsyncSession, user_id: int
) -> Tuple[str, Optional[Callable]]:
    """Generate a fresh link code for ``user_id``.

    Side effects:
    - Deletes any previous unconsumed code for the same user.
    - Inserts the new code with ``SET NX EX``; retries up to 5 times on
      collision before raising.

    Returns ``(code, post_commit_callback)``. The callback is a no-op
    that just emits a structured log line — the router pattern still
    calls it after ``db.commit()`` for symmetry with other services.
    """
    from app.database import (
        safe_redis_delete,
        safe_redis_get,
        safe_redis_set,
    )

    pointer_key = _user_pointer_key(user_id)
    prev_code = await safe_redis_get(pointer_key)
    if prev_code:
        # v5/E1 — kill the previous code so a stale screenshot can't be
        # used to hijack the new binding window.
        await safe_redis_delete(_code_key(prev_code))

    for _ in range(_GEN_RETRIES):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        created = await safe_redis_set(
            _code_key(code), str(user_id), ex=LINK_CODE_TTL, nx=True
        )
        if created:
            await safe_redis_set(pointer_key, code, ex=LINK_CODE_TTL)

            async def _post_commit() -> None:
                log.info("Zalo Bot link code generated", user_id=user_id)

            return code, _post_commit

    # 5 collisions in a row on a 36^6 keyspace — effectively impossible
    # unless Redis is corrupted or under attack.
    log.error("Zalo Bot link code generation exhausted retries", user_id=user_id)
    raise BusinessRuleViolation("Không tạo được mã liên kết. Vui lòng thử lại.")


async def verify_and_link(
    db: AsyncSession,
    code: str,
    chat_id: str,
    display_name: Optional[str] = None,
    *,
    source: str = "zalo_bot_webhook",
) -> Tuple[bool, str, Optional[Callable]]:
    """Consume a link code and bind ``chat_id`` to the resolved user.

    Returns ``(ok, reply_text, post_commit)``. ``post_commit`` is non-None
    only when an existing chat_id binding was displaced — caller (webhook
    router) MUST await it after ``db.commit()`` so the displaced user
    receives a ``ZALO_BOT_LINK_DISPLACED`` notification. Audit rows are
    written inline (same txn as the link write) — caller does not need
    to await anything for audit.
    """
    from app.database import safe_redis_getdel
    from app.services import audit_service

    user_id_str = await safe_redis_getdel(_code_key(code.upper()))
    if not user_id_str:
        return False, "Mã liên kết không hợp lệ hoặc đã hết hạn.", None

    user_id = int(user_id_str)
    repo = StaffZaloBotLinkRepository(db)

    # Steal the chat_id from any other active user it was bound to.
    # Without this an attacker could keep one chat_id wired to a victim
    # by linking it first, then abandoning the binding.
    existing_chat = await repo.get_active_by_chat_id(chat_id)
    displaced_user_id: Optional[int] = None
    displaced_link_id: Optional[int] = None
    if existing_chat and existing_chat.user_id != user_id:
        displaced_user_id = existing_chat.user_id
        displaced_link_id = existing_chat.id
        existing_chat.is_active = False
        await db.flush()
        # Flip displaced user's master toggle off so downstream dispatch
        # doesn't treat them as bot-eligible (active link gone, but pref
        # column would otherwise stay True → confusing orphan state).
        await _sync_preference(
            db, displaced_user_id, enabled=False, actor_user_id=user_id
        )
        # Audit: the displaced row stops being the active binding.
        await audit_service.log_audit(
            db,
            entity_type="StaffZaloBotLink",
            entity_id=displaced_link_id,
            action="chat_id_reassigned",
            actor_user_id=user_id,
            old_value={"is_active": True, "user_id": displaced_user_id},
            new_value={"is_active": False},
            reason=f"chat_id reassigned to user_id={user_id}",
            source=source,
        )
        # Consent history parity: the displaced staff member loses delivery
        # eligibility for the zalo_bot channel. Record a revoke row so the
        # consent timeline shows the event alongside grant/unlink.
        # SAVEPOINT + try/except: upsert_consent flushes; an IntegrityError
        # would poison the session, but the SAVEPOINT __aexit__ rolls back
        # cleanly when an exception bubbles, then the outer except logs +
        # continues without blocking the link write.
        try:
            async with db.begin_nested():
                await notification_consent_service.record_zalo_bot_consent(
                    db,
                    user_id=displaced_user_id,
                    granted=False,
                    source="displaced",
                    actor_id=user_id,
                )
        except Exception:
            log.warning(
                "record_zalo_bot_consent (displaced) failed, link unblocked",
                displaced_user_id=displaced_user_id,
                exc_info=True,
            )

    link = await repo.create_or_reactivate(user_id, chat_id, display_name)
    await _sync_preference(db, user_id, enabled=True, actor_user_id=user_id)

    # Audit the link create/reactivate. ``action`` is "created" whether
    # this is a brand-new row or a reactivation of an inactive row — the
    # audit log captures intent ("user is now linked") not row physics.
    await audit_service.log_created(
        db,
        entity_type="StaffZaloBotLink",
        entity_id=link.id,
        actor_user_id=user_id,
        new_values={
            "user_id": user_id,
            "chat_id_prefix": mask_chat_id(chat_id),
            "display_name": display_name,
            "is_active": True,
        },
        source=source,
    )

    # Consent history parity: a successful link grants zalo_bot consent
    # for the new user. SAVEPOINT + try/except (see helper docstring) so
    # an upsert IntegrityError can't poison the link transaction.
    try:
        async with db.begin_nested():
            await notification_consent_service.record_zalo_bot_consent(
                db,
                user_id=user_id,
                granted=True,
                source="link",
                actor_id=user_id,
            )
    except Exception:
        log.warning(
            "record_zalo_bot_consent (link) failed, link unblocked",
            user_id=user_id,
            exc_info=True,
        )

    log.info(
        "Zalo Bot linked",
        user_id=user_id,
        chat_id_prefix=mask_chat_id(chat_id),
        displaced_user_id=displaced_user_id,
    )

    post_commit: Optional[Callable] = None
    if displaced_user_id is not None:
        # Build a closure that dispatches the displacement notification
        # AFTER the router commits — safe_dispatch must NEVER fire while
        # the link write is still in-flight (see MASTER_ARCHITECTURE Part 7).
        from app.core.events import SystemEvents
        from app.services.notification_dispatcher import safe_dispatch

        _displaced_user_id = displaced_user_id
        _new_user_id = user_id
        _chat_prefix = mask_chat_id(chat_id)

        async def _post_commit() -> None:
            await safe_dispatch(
                db=db,
                event=SystemEvents.ZALO_BOT_LINK_DISPLACED,
                payload={
                    "user_id": _displaced_user_id,
                    "displaced_by_user_id": _new_user_id,
                    "chat_id_prefix": _chat_prefix,
                    "actor_id": _new_user_id,
                },
            )

        post_commit = _post_commit

    return (
        True,
        "Liên kết thành công! Bạn sẽ nhận thông báo từ QLTS qua Zalo.",
        post_commit,
    )


async def unlink(
    db: AsyncSession,
    user_id: int,
    *,
    source: str = "api",
) -> Tuple[bool, str, Optional[Callable]]:
    """Mark the link inactive and flip per-channel preference off.

    Returns ``(ok, reply_text, post_commit)``. ``post_commit`` is always
    None for unlink (no fan-out); kept for signature parity with
    ``verify_and_link``.
    """
    from app.services import audit_service

    repo = StaffZaloBotLinkRepository(db)
    link = await repo.get_by_user_id(user_id)
    if not link or not link.is_active:
        return False, "Tài khoản chưa được liên kết.", None

    link_id = link.id
    found = await repo.deactivate_by_user_id(user_id)
    if not found:
        return False, "Tài khoản chưa được liên kết.", None

    await _sync_preference(db, user_id, enabled=False, actor_user_id=user_id)

    await audit_service.log_deleted(
        db,
        entity_type="StaffZaloBotLink",
        entity_id=link_id,
        actor_user_id=user_id,
        old_values={"user_id": user_id, "is_active": True},
        reason="user-initiated unlink",
        source=source,
    )

    # Consent history parity: revoke row mirrors the unlink. ``source``
    # propagates so audit trail can distinguish API unlink from webhook
    # /huylienket unlink ("api" vs "zalo_bot_webhook"). SAVEPOINT +
    # try/except (see helper docstring) so a flush failure can't poison
    # the unlink transaction.
    try:
        async with db.begin_nested():
            await notification_consent_service.record_zalo_bot_consent(
                db,
                user_id=user_id,
                granted=False,
                source=f"unlink:{source}",
                actor_id=user_id,
            )
    except Exception:
        log.warning(
            "record_zalo_bot_consent (unlink) failed, unlink unblocked",
            user_id=user_id,
            exc_info=True,
        )

    return True, "Đã huỷ liên kết.", None


async def unlink_by_chat_id(
    db: AsyncSession, chat_id: str
) -> Tuple[bool, str, Optional[Callable]]:
    """Unlink whoever owns ``chat_id`` (called from webhook ``/huylienket``)."""
    repo = StaffZaloBotLinkRepository(db)
    link = await repo.get_active_by_chat_id(chat_id)
    if not link:
        return False, "Tài khoản chưa được liên kết.", None
    return await unlink(db, link.user_id, source="zalo_bot_webhook")


async def get_link_status(db: AsyncSession, user_id: int) -> Optional[dict]:
    repo = StaffZaloBotLinkRepository(db)
    link = await repo.get_by_user_id(user_id)
    if not link:
        return None
    return {
        "is_linked": link.is_active,
        "display_name": link.display_name,
        "linked_at": link.linked_at.isoformat() if link.linked_at else None,
    }


async def _get_or_create_pref_safe(db: AsyncSession, user_id: int):
    """Concurrency-safe wrapper around ``NotificationPreferenceRepository.get_or_create``.

    The base ``get_or_create`` is read-then-insert with no upsert, so two
    concurrent requests for the same user that both observe "no row"
    will both INSERT and the second hits the unique-on-user_id constraint
    with ``IntegrityError``. Realistic trigger paths for zalo bot:
    user opens 2 browser tabs and clicks "Tạo mã" twice, or sends
    ``/lienket`` from two chat_ids in quick succession.

    We wrap the call in a SAVEPOINT so a constraint violation rolls back
    only the failed INSERT (not the link write that called us). On
    rollback we re-fetch — the winning concurrent INSERT must have
    committed by then. If re-fetch still returns None, the failure was
    not a race and the original ``IntegrityError`` is re-raised so the
    router can rollback + return 5xx. Pre-existing repo behavior is
    unchanged for non-racing callers.
    """
    from sqlalchemy.exc import IntegrityError

    from app.repositories.notification_preference_repository import (
        NotificationPreferenceRepository,
    )

    repo = NotificationPreferenceRepository(db)
    try:
        async with db.begin_nested():
            return await repo.get_or_create(user_id)
    except IntegrityError:
        # Race: another transaction inserted the row between our SELECT
        # and INSERT. Re-fetch — the winning row is now visible.
        existing = await repo.get_by_user_id(user_id)
        if existing is None:
            raise
        return existing


async def _sync_preference(
    db: AsyncSession,
    user_id: int,
    enabled: bool,
    *,
    actor_user_id: Optional[int] = None,
) -> None:
    """Flip ``zalo_bot_enabled`` on the user's preference row + audit.

    The column lands in v5 Step 11; once present, this MUST persist or
    the link operation is a lie (UI shows linked, dispatcher Gate A
    still blocks). DB errors here are surfaced — the router commits
    after this returns, so a flush failure rolls back the whole link.

    Audit row is written only when the value actually changes; toggling
    the column to its current value is a no-op for both DB and audit.
    """
    from app.services import audit_service

    pref = await _get_or_create_pref_safe(db, user_id)
    old_value = bool(pref.zalo_bot_enabled)
    if old_value == enabled:
        return  # No-op — nothing to flip, nothing to audit.
    pref.zalo_bot_enabled = enabled
    await db.flush()

    await audit_service.log_field_change(
        db,
        entity_type="NotificationPreference",
        entity_id=pref.id,
        field_name="zalo_bot_enabled",
        old_value=old_value,
        new_value=enabled,
        actor_user_id=actor_user_id if actor_user_id is not None else user_id,
        reason=(
            "synced from staff_zalo_bot_link link/unlink/displacement "
            "(zalo_bot_link_service._sync_preference)"
        ),
        source="zalo_bot_link_service",
    )
