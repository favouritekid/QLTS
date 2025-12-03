from app.core.rate_limits import limiter, RateLimits
# app/routers/monitoring.py
"""
System Monitoring Router
Provides comprehensive health monitoring endpoints for:
- Celery workers and tasks
- Redis cache statistics
- Socket.IO connections
- System overview
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.celery_utils import celery_app
from app.core import deps
from app.database import redis_client, safe_redis_ping, safe_redis_lrange
from app.services.notification_service import INBOX_CACHE_KEY_PREFIX
from app.socket_manager import sio

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/monitoring", tags=["System Monitoring"])

# Permission dependency - Admin only
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# CELERY MONITORING
# ============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/celery/workers")
async def get_celery_workers(
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get information about active Celery workers.

    Returns:
        - Worker names
        - Status (online/offline)
        - Active tasks count
        - Processed tasks stats
    """
    try:
        inspect = celery_app.control.inspect(timeout=2.0)

        # Get worker stats
        stats = await run_in_threadpool(inspect.stats)
        active_tasks = await run_in_threadpool(inspect.active)
        registered_tasks = await run_in_threadpool(inspect.registered)

        if not stats:
            return {
                "status": "no_workers",
                "message": "No active Celery workers found",
                "workers": []
            }

        workers = []
        for worker_name, worker_stats in stats.items():
            workers.append({
                "name": worker_name,
                "status": "online",
                "active_tasks": len(active_tasks.get(worker_name, [])) if active_tasks else 0,
                "total_tasks": worker_stats.get("total", {}),
                "pool_info": {
                    "max_concurrency": worker_stats.get("pool", {}).get("max-concurrency"),
                    "processes": worker_stats.get("pool", {}).get("processes"),
                },
                "registered_tasks": len(registered_tasks.get(worker_name, [])) if registered_tasks else 0,
            })

        return {
            "status": "ok",
            "worker_count": len(workers),
            "workers": workers
        }

    except Exception as e:
        log.error("Failed to get Celery workers info", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to Celery: {str(e)}"
        )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/celery/tasks")
async def get_celery_tasks(
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get information about Celery tasks.

    Returns:
        - Active tasks
        - Scheduled tasks
        - Reserved tasks
        - Registered task names
    """
    try:
        inspect = celery_app.control.inspect(timeout=2.0)

        active = await run_in_threadpool(inspect.active) or {}
        scheduled = await run_in_threadpool(inspect.scheduled) or {}
        reserved = await run_in_threadpool(inspect.reserved) or {}
        registered = await run_in_threadpool(inspect.registered) or {}

        # Flatten tasks from all workers
        active_tasks = []
        for worker_tasks in active.values():
            active_tasks.extend(worker_tasks)

        scheduled_tasks = []
        for worker_tasks in scheduled.values():
            scheduled_tasks.extend(worker_tasks)

        reserved_tasks = []
        for worker_tasks in reserved.values():
            reserved_tasks.extend(worker_tasks)

        # Get unique registered task names
        registered_task_names = set()
        for worker_tasks in registered.values():
            registered_task_names.update(worker_tasks)

        return {
            "active": {
                "count": len(active_tasks),
                "tasks": active_tasks
            },
            "scheduled": {
                "count": len(scheduled_tasks),
                "tasks": scheduled_tasks
            },
            "reserved": {
                "count": len(reserved_tasks),
                "tasks": reserved_tasks
            },
            "registered": {
                "count": len(registered_task_names),
                "task_names": sorted(list(registered_task_names))
            }
        }

    except Exception as e:
        log.error("Failed to get Celery tasks info", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to Celery: {str(e)}"
        )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/celery/stats")
async def get_celery_stats(
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get Celery statistics and configuration.

    Returns:
        - Broker URL (sanitized)
        - Result backend URL (sanitized)
        - Worker configuration
    """
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        stats = await run_in_threadpool(inspect.stats) or {}

        # Sanitize sensitive info
        broker_url = str(celery_app.conf.broker_url)
        if "@" in broker_url:
            # Hide credentials: redis://user:pass@host -> redis://***@host
            parts = broker_url.split("@")
            broker_url = f"{parts[0].split('//')[0]}//***@{parts[-1]}"

        result_backend = str(celery_app.conf.result_backend)
        if "@" in result_backend:
            parts = result_backend.split("@")
            result_backend = f"{parts[0].split('//')[0]}//***@{parts[-1]}"

        return {
            "broker": {
                "url": broker_url,
                "connected": len(stats) > 0
            },
            "result_backend": {
                "url": result_backend
            },
            "configuration": {
                "task_serializer": celery_app.conf.task_serializer,
                "result_serializer": celery_app.conf.result_serializer,
                "worker_prefetch_multiplier": celery_app.conf.worker_prefetch_multiplier,
                "worker_max_tasks_per_child": celery_app.conf.worker_max_tasks_per_child,
            },
            "workers": stats
        }

    except Exception as e:
        log.error("Failed to get Celery stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to get Celery stats: {str(e)}"
        )


# ============================================================================
# REDIS MONITORING
# ============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/redis/info")
async def get_redis_info(
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get Redis server information and statistics.

    Returns:
        - Server version
        - Connected clients
        - Memory usage
        - Keyspace statistics
    """
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis client not configured"
        )

    try:
        # Ping Redis
        await safe_redis_ping()

        # Get Redis INFO
        info = await redis_client.info()

        # Get keyspace info
        keyspace = {}
        for db_key, db_info in info.get("keyspace", {}).items():
            keyspace[db_key] = db_info

        # Get memory info
        memory_used = info.get("used_memory_human", "unknown")
        memory_peak = info.get("used_memory_peak_human", "unknown")

        return {
            "status": "connected",
            "server": {
                "version": info.get("redis_version", "unknown"),
                "mode": info.get("redis_mode", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "uptime_days": info.get("uptime_in_days", 0),
            },
            "clients": {
                "connected": info.get("connected_clients", 0),
                "blocked": info.get("blocked_clients", 0),
            },
            "memory": {
                "used": memory_used,
                "peak": memory_peak,
                "used_bytes": info.get("used_memory", 0),
                "peak_bytes": info.get("used_memory_peak", 0),
            },
            "stats": {
                "total_connections_received": info.get("total_connections_received", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            },
            "keyspace": keyspace,
        }

    except Exception as e:
        log.error("Failed to get Redis info", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to Redis: {str(e)}"
        )


# ============================================================================
# SOCKET.IO MONITORING
# ============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/socket/connections")
async def get_socket_connections(
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get active Socket.IO connections.

    Returns:
        - Total active connections
        - List of connected users with session info
    """
    try:
        # Get all active session IDs from Socket.IO server
        all_sids = list(sio.eio.sockets.keys()) if sio.eio.sockets else []

        connections = []
        for sid in all_sids:
            try:
                session = await sio.get_session(sid)
                if session:
                    connections.append({
                        "sid": sid,
                        "user_id": session.get("user_id"),
                        "username": session.get("username"),
                    })
            except Exception as e:
                log.warning(f"Failed to get session for SID {sid}", error=str(e))
                continue

        return {
            "status": "ok",
            "total_connections": len(all_sids),
            "authenticated_connections": len(connections),
            "connections": connections
        }

    except Exception as e:
        log.error("Failed to get Socket.IO connections", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Socket.IO connections: {str(e)}"
        )


# ============================================================================
# NOTIFICATION METRICS (✅ PHASE 1.3.1)
# ============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/notifications/metrics")
async def get_notification_metrics(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    ✅ PHASE 1.3.1: Get comprehensive notification system metrics.

    (Admin only) Provides visibility into:
    - Total notifications created
    - Notifications by type breakdown
    - Notifications by status (read/unread)
    - Cache performance metrics
    - Recent activity (24h, 7d, 30d)
    - Top recipients

    Returns:
        Metrics object with detailed statistics for monitoring and optimization
    """
    metrics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "totals": {},
        "by_type": {},
        "by_status": {},
        "cache": {},
        "activity": {},
        "top_recipients": [],
    }

    try:
        # 1. Total notifications count
        result = await db.execute(
            text("SELECT COUNT(*) as total FROM notification")
        )
        metrics["totals"]["all_time"] = result.scalar() or 0

        # 2. Notifications by type breakdown
        result = await db.execute(
            text("""
                SELECT type, COUNT(*) as count
                FROM notification
                GROUP BY type
                ORDER BY count DESC
            """)
        )
        metrics["by_type"] = {row[0]: row[1] for row in result.fetchall()}

        # 3. Notifications by read status
        result = await db.execute(
            text("""
                SELECT
                    SUM(CASE WHEN is_read = true THEN 1 ELSE 0 END) as read_count,
                    SUM(CASE WHEN is_read = false THEN 1 ELSE 0 END) as unread_count
                FROM notification
            """)
        )
        row = result.first()
        metrics["by_status"] = {
            "read": row[0] or 0,
            "unread": row[1] or 0,
        }

        # 4. Cache performance metrics (Redis)
        try:
            if redis_client:
                # Get Redis INFO for keyspace stats
                info = await redis_client.info()
                keyspace_hits = info.get("keyspace_hits", 0)
                keyspace_misses = info.get("keyspace_misses", 0)

                total_ops = keyspace_hits + keyspace_misses
                hit_rate = (keyspace_hits / total_ops * 100) if total_ops > 0 else 0

                metrics["cache"]["redis_hits"] = keyspace_hits
                metrics["cache"]["redis_misses"] = keyspace_misses
                metrics["cache"]["hit_rate_percent"] = round(hit_rate, 2)

                # Count inbox cache keys
                # Pattern: user_inbox:*
                keys = await redis_client.keys(f"{INBOX_CACHE_KEY_PREFIX}:*")
                metrics["cache"]["inbox_keys_count"] = len(keys) if keys else 0

                # Sample cache size (check first 5 inbox caches)
                if keys:
                    sample_keys = keys[:5]
                    total_items = 0
                    for key in sample_keys:
                        items = await safe_redis_lrange(key, 0, -1)
                        total_items += len(items)
                    avg_items = total_items / len(sample_keys) if sample_keys else 0
                    metrics["cache"]["avg_items_per_inbox"] = round(avg_items, 1)
        except Exception as e:
            log.warning("Failed to get cache metrics", error=str(e))
            metrics["cache"]["error"] = str(e)

        # 5. Recent activity (24h, 7d, 30d)
        result = await db.execute(
            text("""
                SELECT
                    COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                    COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as last_7d,
                    COUNT(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN 1 END) as last_30d
                FROM notification
            """)
        )
        row = result.first()
        metrics["activity"] = {
            "last_24h": row[0] or 0,
            "last_7d": row[1] or 0,
            "last_30d": row[2] or 0,
        }

        # 6. Top recipients (users with most notifications)
        result = await db.execute(
            text("""
                SELECT
                    n.user_id,
                    u.username,
                    COUNT(*) as notification_count,
                    SUM(CASE WHEN n.is_read = false THEN 1 ELSE 0 END) as unread_count
                FROM notification n
                LEFT JOIN "user" u ON n.user_id = u.id
                GROUP BY n.user_id, u.username
                ORDER BY notification_count DESC
                LIMIT 10
            """)
        )
        metrics["top_recipients"] = [
            {
                "user_id": row[0],
                "username": row[1],
                "total_notifications": row[2],
                "unread_notifications": row[3],
            }
            for row in result.fetchall()
        ]

        # 7. Performance insights
        metrics["insights"] = []

        # Alert if unread ratio is too high (> 50%)
        unread_ratio = (
            metrics["by_status"]["unread"] / metrics["totals"]["all_time"] * 100
            if metrics["totals"]["all_time"] > 0 else 0
        )
        if unread_ratio > 50:
            metrics["insights"].append({
                "level": "warning",
                "message": f"High unread notification ratio: {unread_ratio:.1f}%"
            })

        # Alert if cache hit rate is low (< 70%)
        if "hit_rate_percent" in metrics["cache"]:
            if metrics["cache"]["hit_rate_percent"] < 70:
                metrics["insights"].append({
                    "level": "warning",
                    "message": f"Low cache hit rate: {metrics['cache']['hit_rate_percent']}%"
                })

        # Positive feedback if cache hit rate is good (> 80%)
        if "hit_rate_percent" in metrics["cache"]:
            if metrics["cache"]["hit_rate_percent"] > 80:
                metrics["insights"].append({
                    "level": "info",
                    "message": f"Good cache hit rate: {metrics['cache']['hit_rate_percent']}%"
                })

        return metrics

    except Exception as e:
        log.error("Failed to get notification metrics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notification metrics: {str(e)}"
        )


# ============================================================================
# SYSTEM OVERVIEW
# ============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/system/overview")
async def get_system_overview(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get comprehensive system health overview.

    Returns:
        - API status
        - Database status
        - Redis status
        - Celery status
        - Socket.IO status
        - System statistics
    """
    overview = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api": {"status": "ok"},
        "database": {"status": "unknown"},
        "redis": {"status": "unknown"},
        "celery": {"status": "unknown"},
        "socket_io": {"status": "unknown"},
        "statistics": {}
    }

    # 1. Database check
    try:
        await db.execute(text("SELECT 1"))
        overview["database"]["status"] = "ok"

        # Get database statistics
        result = await db.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM "user") as total_users,
                (SELECT COUNT(*) FROM lead) as total_leads,
                (SELECT COUNT(*) FROM user_session WHERE revoked_at IS NULL) as active_sessions
        """))
        row = result.first()
        if row:
            overview["statistics"]["total_users"] = row[0]
            overview["statistics"]["total_leads"] = row[1]
            overview["statistics"]["active_sessions"] = row[2]

    except Exception as e:
        overview["database"]["status"] = "error"
        overview["database"]["error"] = str(e)
        log.error("Database check failed in overview", error=str(e))

    # 2. Redis check
    try:
        await safe_redis_ping()
        overview["redis"]["status"] = "ok"

        if redis_client:
            info = await redis_client.info()
            overview["redis"]["connected_clients"] = info.get("connected_clients", 0)
            overview["redis"]["used_memory"] = info.get("used_memory_human", "unknown")

    except Exception as e:
        overview["redis"]["status"] = "error"
        overview["redis"]["error"] = str(e)
        log.error("Redis check failed in overview", error=str(e))

    # 3. Celery check
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        stats = await run_in_threadpool(inspect.stats)
        active_tasks = await run_in_threadpool(inspect.active)

        if stats:
            overview["celery"]["status"] = "ok"
            overview["celery"]["workers"] = len(stats)

            # Count active tasks across all workers
            total_active = 0
            if active_tasks:
                for worker_tasks in active_tasks.values():
                    total_active += len(worker_tasks)
            overview["celery"]["active_tasks"] = total_active
        else:
            overview["celery"]["status"] = "no_workers"
            overview["celery"]["workers"] = 0

    except Exception as e:
        overview["celery"]["status"] = "error"
        overview["celery"]["error"] = str(e)
        log.error("Celery check failed in overview", error=str(e))

    # 4. Socket.IO check
    try:
        all_sids = list(sio.eio.sockets.keys()) if sio.eio.sockets else []
        overview["socket_io"]["status"] = "ok"
        overview["socket_io"]["active_connections"] = len(all_sids)

    except Exception as e:
        overview["socket_io"]["status"] = "error"
        overview["socket_io"]["error"] = str(e)
        log.error("Socket.IO check failed in overview", error=str(e))

    # Determine overall health
    all_ok = all([
        overview["database"]["status"] == "ok",
        overview["redis"]["status"] == "ok",
        overview["celery"]["status"] in ["ok", "no_workers"],  # no_workers is acceptable
        overview["socket_io"]["status"] == "ok",
    ])

    overview["overall_status"] = "healthy" if all_ok else "degraded"

    return overview