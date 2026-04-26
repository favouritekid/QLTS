"""Zalo Bot Platform notification channel.

Worker-only sender that pushes notifications to the staff member's
linked Zalo Bot chat. Resolves the chat_id via the
``staff_zalo_bot_link`` row, calls ``zalo_bot_gateway.send_message``,
and maps gateway results onto the standard ``ChannelResult`` shape.

External recipients are not supported: this channel is gated to
``recipient_kind == "internal"`` upstream by the rule CRUD validator
(Step 16) and at metadata exposure time (``internal_only=True``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

import structlog

from .base import BaseChannel, ChannelResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.notification_delivery import NotificationDelivery

log = structlog.get_logger(__name__)


# Plain-text cap matching the gateway. We truncate rather than reject so
# a slightly-too-long template still delivers; truncation is logged so
# the operator can shorten the template upstream.
_MAX_TEXT_LENGTH = 2000
_TRUNCATION_MARKER = "…"


def _format_text(snapshot: Dict[str, Any]) -> str:
    """Build the plain-text body sent to the bot.

    Prefers an explicit ``message`` field — falls back to ``title``.
    Combined ``title + message`` is the user-visible payload, mirroring
    the in-app browser format.
    """
    title = (snapshot.get("title") or "").strip()
    message = (snapshot.get("message") or "").strip()
    if title and message:
        body = f"{title}\n\n{message}"
    else:
        body = message or title

    if len(body) > _MAX_TEXT_LENGTH:
        truncated_at = _MAX_TEXT_LENGTH - len(_TRUNCATION_MARKER)
        body = body[:truncated_at] + _TRUNCATION_MARKER
    return body


class ZaloBotChannel(BaseChannel):
    """Worker-only single-delivery channel for Zalo Bot Platform."""

    channel_name = "zalo_bot"

    async def execute_delivery(
        self,
        delivery: "NotificationDelivery",
        db: "AsyncSession",
    ) -> ChannelResult:
        from app.gateways.zalo_bot import zalo_bot_gateway
        from app.repositories.staff_zalo_bot_link_repository import (
            StaffZaloBotLinkRepository,
        )

        if not delivery.user_id:
            # zalo_bot does not target external recipients; the rule
            # validator should have rejected this upstream. Treat as
            # permanent so we don't retry forever.
            log.warning(
                "zalo_bot delivery without user_id",
                delivery_id=delivery.id,
            )
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[],
                error_message="no_zalo_bot_link",  # routes to PERMANENT_ERRORS
                delivery_id=delivery.id,
            )

        repo = StaffZaloBotLinkRepository(db)
        link = await repo.get_active_by_user_id(delivery.user_id)
        if not link:
            # No active link OR link was deactivated — staff is opted
            # out. Permanent until they re-link.
            log.info(
                "zalo_bot delivery skipped — no active link",
                delivery_id=delivery.id,
                user_id=delivery.user_id,
            )
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id],
                error_message="no_zalo_bot_link",
                delivery_id=delivery.id,
            )

        snapshot = delivery.payload_snapshot or {}
        text = _format_text(snapshot)
        if not text:
            log.warning(
                "zalo_bot delivery skipped — empty text body",
                delivery_id=delivery.id,
            )
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id],
                error_message="empty_text",
                delivery_id=delivery.id,
            )

        result = await zalo_bot_gateway.send_message(link.chat_id, text)

        # Logging: never echo the message body — it may carry PII via
        # template substitution. Mask the chat_id like the link service
        # does so log scraping doesn't leak the binding.
        chat_prefix = (link.chat_id[:8] + "***") if link.chat_id else ""

        if result.success:
            log.info(
                "zalo_bot delivery sent",
                delivery_id=delivery.id,
                user_id=delivery.user_id,
                chat_id_prefix=chat_prefix,
                msg_id=result.message_id,
                text_len=len(text),
            )
            return ChannelResult(
                success=True,
                sent_count=1,
                failed_ids=[],
                delivery_id=delivery.id,
                provider_message_id=result.message_id,
            )

        log.warning(
            "zalo_bot delivery failed",
            delivery_id=delivery.id,
            user_id=delivery.user_id,
            chat_id_prefix=chat_prefix,
            error_code=result.error_code,
            # Gateway already sanitised error_message — no token leak.
            error_message=result.error_message,
        )
        return ChannelResult(
            success=False,
            sent_count=0,
            failed_ids=[delivery.user_id],
            # Tag with channel prefix so PERMANENT_ERRORS can match
            # specific Zalo Bot codes if/when classification is added.
            error_message=f"Zalo Bot error {result.error_code}: {result.error_message}",
            delivery_id=delivery.id,
        )

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any],
    ) -> ChannelResult:
        """zalo_bot is worker-only — batch ``send`` always errors."""
        return ChannelResult(
            success=False,
            sent_count=0,
            failed_ids=recipient_ids,
            error_message=(
                "zalo_bot channel uses execute_delivery() via worker, "
                "not batch send()"
            ),
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """zalo_bot needs no per-action config — the link record carries
        the routing target. Empty/missing config is valid; presence of
        ``external_resolver`` is rejected upstream by the rule
        validator (Step 16) since this channel is internal-only.
        """
        return True
