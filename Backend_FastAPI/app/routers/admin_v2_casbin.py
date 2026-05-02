# app/routers/admin_v2_casbin.py
"""T0-5 — admin-only Casbin reload endpoint.

Cutover safety: during the maintenance window the deploy seeds new deny rules
directly via DB INSERT (bypassing the policy/role admin endpoints which are
themselves frozen). The running ``casbin.AsyncEnforcer`` was loaded at
``app.lifespan`` and does not see those new rows until something calls
``load_policy()``. This endpoint exposes that single primitive over an
admin-only HTTP surface so the runbook can cleanly trigger a reload at
``T+3:30`` without restarting the worker.

Strict scope (B1 boundary):

* read-only with respect to ``auth_model.conf`` — does NOT touch the model
  file, the deny block, or the policy template registry. That is owned by
  the B1 RBAC refactor wave on the cutover plan.
* re-uses the existing ``request.app.state.enforcer`` set in
  ``app/main.py`` lifespan; does NOT instantiate a new enforcer.
* the response shape is intentionally minimal — ``success``,
  ``reloaded_at``, ``policy_count`` (when reachable), ``actor_id`` — so
  monitoring written against the staging dry-run keeps reading on the
  real cutover tick.

Path: ``POST /api/v2/admin/casbin/reload`` (the ``/api/v2`` prefix
separates this cutover-only surface from the v1 admin tree mounted at
``/api/admin/...``). See ``Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md``
§3.5 T0-5.
"""
from datetime import datetime, timezone

import casbin
import structlog
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.services import activity_service

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin/casbin",
    tags=["Admin v2 - Casbin"],
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/reload", status_code=status.HTTP_200_OK)
async def reload_casbin_policy(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Reload the in-process Casbin policy from the database.

    Returns 200 with ``{"success": true, "reloaded_at", "policy_count",
    "actor_id"}`` on success.

    On reload failure (DB unreachable, adapter raises, etc.) returns 500
    with ``{"success": false, "reloaded_at", "error", "actor_id"}``. The
    enforcer is left in its previous in-memory state — no partial flush —
    so the worker / API stays serviceable.
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    started_at = _utcnow_iso()
    try:
        await enforcer.load_policy()
    except Exception as exc:
        log.error(
            "casbin_reload_failed",
            actor_id=current_admin.id,
            error=str(exc),
            exc_info=True,
        )
        # Audit the failure too — best-effort, must not mask the original
        # error if the audit write also fails.
        try:
            await activity_service.log_activity(
                db=db,
                action="casbin_reload_failed",
                resource_type="casbin_policy",
                actor_id=current_admin.id,
                description=f"Casbin reload failed: {exc!s}",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            await db.commit()
        except Exception:  # noqa: BLE001 — audit best-effort
            log.warning("casbin_reload_failure_audit_skipped", exc_info=True)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "reloaded_at": started_at,
                "error": str(exc),
                "actor_id": current_admin.id,
            },
        )

    # `get_policy()` is sync (per `app/routers/admin/roles.py`); guard the
    # count read so a defensive accessor failure does not turn a successful
    # reload into a 500.
    try:
        policy_count: int | None = len(enforcer.get_policy())
    except Exception:  # noqa: BLE001 — count is informational, not load-bearing
        policy_count = None

    completed_at = _utcnow_iso()
    log.info(
        "casbin_reload_succeeded",
        actor_id=current_admin.id,
        policy_count=policy_count,
        reloaded_at=completed_at,
    )

    await activity_service.log_activity(
        db=db,
        action="casbin_reload",
        resource_type="casbin_policy",
        actor_id=current_admin.id,
        description=(
            f"Casbin policy reloaded from DB"
            + (f" ({policy_count} policies)" if policy_count is not None else "")
        ),
        changes={"policy_count": policy_count},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    return {
        "success": True,
        "reloaded_at": completed_at,
        "policy_count": policy_count,
        "actor_id": current_admin.id,
    }
