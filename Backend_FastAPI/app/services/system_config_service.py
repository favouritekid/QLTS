# app/services/system_config_service.py
"""System Config Service (#184 Wave 1 PR-1D / phase1_13).

Admin-only mutation layer over the ``system_config`` key/value
store. Closes B4 P0 blocker.

Governance per Q10 — admin-only on PATCH; manager / officer /
accountant / user can only READ via the GET endpoints. The
service raises ``BusinessRuleViolation`` (not ``HTTPException``)
on guard fail per MASTER_ARCHITECTURE service-isolation rule;
the router layer translates to HTTP via the deps.

Read path (``get_value`` / ``list_all``) is intentionally permissive
— any caller with a valid session can read the runtime config
because the typical use-case (FE storefront reading
``current_intake_year``) needs it during anonymous flows.
Sensitive keys should NOT be stored in ``system_config``; use
encrypted secrets / env vars for those.
"""
from datetime import datetime, timezone
from typing import Any, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.models import User
from app.models.system_config import SystemConfig
from app.schemas.system_config import SystemConfigUpdate
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
)


# Type alias for the no-op post-commit callback the service
# returns. Mirrors the convention from admission_path_service.
async def _noop_callback() -> None:
    pass


class SystemConfigService:
    """Read + admin-mutate runtime config rows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------
    # READ PATH — any authenticated caller
    # ------------------------------------------------------------

    async def list_all(self) -> list[SystemConfig]:
        """List all config rows ordered by key."""
        query = select(SystemConfig).order_by(SystemConfig.key)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_key(self, key: str) -> SystemConfig:
        """Fetch a single config row by key.

        Raises:
            ResourceNotFoundError: key doesn't exist (404 to caller).
        """
        query = select(SystemConfig).where(SystemConfig.key == key)
        result = await self.db.execute(query)
        row = result.scalars().first()
        if row is None:
            raise ResourceNotFoundError(
                f"system_config key '{key}' không tồn tại"
            )
        return row

    async def get_value(self, key: str, default: Any = None) -> Any:
        """Convenience accessor — returns ``value`` or ``default``
        when key is absent. Used by service callers that want a
        fallback instead of a 404.
        """
        try:
            row = await self.get_by_key(key)
        except ResourceNotFoundError:
            return default
        return row.value

    # ------------------------------------------------------------
    # MUTATE PATH — admin only
    # ------------------------------------------------------------

    async def update(
        self,
        key: str,
        data: SystemConfigUpdate,
        user: User,
    ) -> Tuple[SystemConfig, Any]:
        """PATCH a single config row.

        Q10 governance — only admin can mutate. Manager / officer /
        accountant / user submitting this call get
        ``BusinessRuleViolation`` translated to 403 by the router
        layer.

        Returns ``(row, post_commit_callback)`` per service contract.
        Caller (router) commits the txn + awaits the callback.
        """
        if user.role != UserRole.ADMIN:
            raise BusinessRuleViolation(
                f"Chỉ admin được sửa system_config (key='{key}'). "
                "Manager / officer / accountant / user phải liên hệ admin."
            )

        row = await self.get_by_key(key)

        # exclude_unset semantic — only the explicitly-set keys
        # flow through. ``value`` is REQUIRED in the schema so it's
        # always present; ``description`` may be omitted to leave
        # unchanged.
        update_data = data.model_dump(exclude_unset=True)

        if "value" in update_data:
            row.value = update_data["value"]
        if "description" in update_data:
            row.description = update_data["description"]

        # Audit trail — onupdate=now() handles ``updated_at``
        # automatically; service writes the actor explicitly.
        row.updated_by_user_id = user.id
        # Belt-and-suspenders: SQLA onupdate fires on flush, but
        # explicit timestamp ensures the value is set even when
        # the caller's session config skips onupdate hooks.
        row.updated_at = datetime.now(timezone.utc)

        await self.db.flush()
        return row, _noop_callback
