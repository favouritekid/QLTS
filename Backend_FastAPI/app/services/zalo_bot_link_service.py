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
from app.utils.exceptions import BusinessRuleViolation

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
) -> Tuple[bool, str]:
    """Consume a link code and bind ``chat_id`` to the resolved user."""
    from app.database import safe_redis_getdel

    user_id_str = await safe_redis_getdel(_code_key(code.upper()))
    if not user_id_str:
        return False, "Ma lien ket khong hop le hoac da het han."

    user_id = int(user_id_str)
    repo = StaffZaloBotLinkRepository(db)

    # Steal the chat_id from any other active user it was bound to.
    # Without this an attacker could keep one chat_id wired to a victim
    # by linking it first, then abandoning the binding.
    existing_chat = await repo.get_active_by_chat_id(chat_id)
    if existing_chat and existing_chat.user_id != user_id:
        existing_chat.is_active = False
        await db.flush()

    await repo.create_or_reactivate(user_id, chat_id, display_name)
    await _sync_preference(db, user_id, enabled=True)

    log.info(
        "Zalo Bot linked",
        user_id=user_id,
        chat_id_prefix=chat_id[:8] + "***" if chat_id else "",
    )
    return True, "Lien ket thanh cong! Ban se nhan thong bao tu QLTS qua Zalo."


async def unlink(db: AsyncSession, user_id: int) -> Tuple[bool, str]:
    """Mark the link inactive and flip per-channel preference off."""
    repo = StaffZaloBotLinkRepository(db)
    found = await repo.deactivate_by_user_id(user_id)
    if not found:
        return False, "Tai khoan chua duoc lien ket."
    await _sync_preference(db, user_id, enabled=False)
    return True, "Da huy lien ket."


async def unlink_by_chat_id(db: AsyncSession, chat_id: str) -> Tuple[bool, str]:
    repo = StaffZaloBotLinkRepository(db)
    link = await repo.get_active_by_chat_id(chat_id)
    if not link:
        return False, "Tai khoan chua duoc lien ket."
    return await unlink(db, link.user_id)


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


async def _sync_preference(
    db: AsyncSession, user_id: int, enabled: bool
) -> None:
    """Flip ``zalo_bot_enabled`` on the user's preference row.

    The column lands in v5 Step 11; once present, this MUST persist or
    the link operation is a lie (UI shows linked, dispatcher Gate A
    still blocks). DB errors here are surfaced — the router commits
    after this returns, so a flush failure rolls back the whole link.
    """
    from app.repositories.notification_preference_repository import (
        NotificationPreferenceRepository,
    )

    repo = NotificationPreferenceRepository(db)
    pref = await repo.get_or_create(user_id)
    pref.zalo_bot_enabled = enabled
    await db.flush()
