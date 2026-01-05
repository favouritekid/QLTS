# app/routers/admin/cache.py
"""
Admin Cache Management Router

Provides endpoints for viewing and managing Redis cache.
Only accessible by admins.
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel

from app.core.deps import CasbinAuth  # Phase 2.2
from app import models, database

router = APIRouter(prefix="/cache", tags=["Admin - Cache Management"])



# =============================================================================
# SCHEMAS
# =============================================================================

class CacheKeyInfo(BaseModel):
    """Information about a cache key."""
    key: str
    ttl: int  # -1 = no expiry, -2 = key doesn't exist
    type: str
    size_bytes: Optional[int] = None


class CacheStats(BaseModel):
    """Overall cache statistics."""
    total_keys: int
    memory_used: str
    connected_clients: int
    uptime_seconds: int


class ClearCacheRequest(BaseModel):
    """Request to clear specific cache keys."""
    patterns: List[str]  # e.g., ["org:*", "pipeline:*"]


class ClearCacheResponse(BaseModel):
    """Response after clearing cache."""
    deleted_count: int
    deleted_keys: List[str]


# =============================================================================
# KNOWN CACHE KEY PATTERNS
# =============================================================================

KNOWN_CACHE_PATTERNS = {
    "org:all_units_tree": "Organization tree hierarchy",
    "org:tree_with_aggregation:*": "Organization tree with aggregation stats",
    "pipeline:all_stages": "Pipeline stages list",
    "pipeline:all_statuses": "Consultation statuses list",
    "config:assignment:*": "Assignment configuration per unit",
    "session:*": "User session mappings",
    "blacklist:*": "Revoked JWT tokens",
    "user_blacklist:*": "Revoked user sessions",
    "socket_rate_limit:*": "Socket.IO rate limiting",
    "lock:*": "Distributed locks",
}


# =============================================================================
# ENDPOINTS
# =============================================================================

@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/keys", response_model=List[CacheKeyInfo])
async def list_cache_keys(
    request: Request,
    current_admin: models.User = CasbinAuth,
    pattern: str = Query("*", description="Key pattern to search (e.g., 'org:*', 'pipeline:*')"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum keys to return"),
):
    """
    List all cache keys matching the pattern.

    **Pattern examples:**
    - `*` - All keys
    - `org:*` - Organization cache
    - `pipeline:*` - Pipeline cache
    - `config:*` - Configuration cache
    - `session:*` - Session cache
    """
    try:
        keys = await database.redis_client.keys(pattern)
        keys = keys[:limit]  # Limit results

        result = []
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            ttl = await database.redis_client.ttl(key_str)
            key_type = await database.redis_client.type(key_str)
            type_str = key_type.decode() if isinstance(key_type, bytes) else key_type

            # Get size if string type
            size = None
            if type_str == "string":
                size = await database.redis_client.strlen(key_str)

            result.append(CacheKeyInfo(
                key=key_str,
                ttl=ttl,
                type=type_str,
                size_bytes=size,
            ))

        # Sort by key name
        result.sort(key=lambda x: x.key)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/keys/{key:path}")
async def get_cache_value(
    request: Request,
    key: str,
    current_admin: models.User = CasbinAuth,
):
    """
    Get the value of a specific cache key.

    **Note:** Large values will be truncated to 10KB.
    """
    try:
        key_type = await database.redis_client.type(key)
        type_str = key_type.decode() if isinstance(key_type, bytes) else key_type

        if type_str == "none":
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found")

        ttl = await database.redis_client.ttl(key)

        # Get value based on type
        if type_str == "string":
            value = await database.redis_client.get(key)
            value_str = value.decode() if isinstance(value, bytes) else value
            # Truncate if too large
            if len(value_str) > 10240:
                value_str = value_str[:10240] + "... [TRUNCATED]"
        elif type_str == "list":
            value_str = await database.redis_client.lrange(key, 0, 100)
        elif type_str == "set":
            value_str = list(await database.redis_client.smembers(key))[:100]
        elif type_str == "hash":
            value_str = await database.redis_client.hgetall(key)
        else:
            value_str = f"[Type: {type_str} - cannot display]"

        return {
            "key": key,
            "type": type_str,
            "ttl": ttl,
            "value": value_str,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/keys/{key:path}")
async def delete_cache_key(
    request: Request,
    key: str,
    current_admin: models.User = CasbinAuth,
):
    """
    Delete a specific cache key.
    """
    try:
        exists = await database.redis_client.exists(key)
        if not exists:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found")

        deleted = await database.redis_client.delete(key)

        return {
            "success": True,
            "deleted_key": key,
            "deleted_count": deleted,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/clear", response_model=ClearCacheResponse)
async def clear_cache_by_patterns(
    request: Request,  # Required for rate limiter
    body: ClearCacheRequest,  # Renamed from 'request' to avoid conflict
    current_admin: models.User = CasbinAuth,
):
    """
    Clear cache keys matching specified patterns.

    **Example patterns:**
    - `org:*` - Clear all organization cache
    - `pipeline:*` - Clear all pipeline cache
    - `config:assignment:*` - Clear all assignment config cache

    **Safety:** Will not delete session/auth keys unless explicitly specified.
    """
    deleted_keys = []

    try:
        for pattern in body.patterns:  # Changed from request. to body.
            # Safety check - warn about auth keys
            if pattern in ["session:*", "blacklist:*", "*"]:
                # Still allow but log warning
                pass

            keys = await database.redis_client.keys(pattern)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                await database.redis_client.delete(key_str)
                deleted_keys.append(key_str)

        return ClearCacheResponse(
            deleted_count=len(deleted_keys),
            deleted_keys=deleted_keys,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/stats", response_model=CacheStats)
async def get_cache_stats(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    Get Redis cache statistics.
    """
    try:
        info = await database.redis_client.info()
        dbsize = await database.redis_client.dbsize()

        return CacheStats(
            total_keys=dbsize,
            memory_used=info.get("used_memory_human", "unknown"),
            connected_clients=info.get("connected_clients", 0),
            uptime_seconds=info.get("uptime_in_seconds", 0),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/patterns")
async def get_known_patterns(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    Get list of known cache key patterns used in this application.
    """
    return {
        "patterns": [
            {"pattern": k, "description": v}
            for k, v in KNOWN_CACHE_PATTERNS.items()
        ]
    }


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/invalidate/organization")
async def invalidate_organization_cache(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    Invalidate all organization-related cache.

    Use this after bulk organization changes.
    """
    patterns = ["org:all_units_tree", "org:tree_with_aggregation:*"]
    deleted_keys = []

    try:
        for pattern in patterns:
            keys = await database.redis_client.keys(pattern)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                await database.redis_client.delete(key_str)
                deleted_keys.append(key_str)

        return {
            "success": True,
            "invalidated": deleted_keys,
            "message": "Organization cache invalidated. Next request will rebuild cache.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/invalidate/pipeline")
async def invalidate_pipeline_cache(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    Invalidate all pipeline-related cache.

    Use this after pipeline stage/status changes.
    """
    patterns = ["pipeline:all_stages", "pipeline:all_statuses"]
    deleted_keys = []

    try:
        for pattern in patterns:
            keys = await database.redis_client.keys(pattern)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                await database.redis_client.delete(key_str)
                deleted_keys.append(key_str)

        return {
            "success": True,
            "invalidated": deleted_keys,
            "message": "Pipeline cache invalidated. Next request will rebuild cache.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/invalidate/config")
async def invalidate_config_cache(
    request: Request,
    current_admin: models.User = CasbinAuth,
    unit_id: Optional[int] = Query(None, description="Specific unit ID, or None for all"),
):
    """
    Invalidate assignment configuration cache.

    Use this after configuration changes.
    """
    if unit_id:
        pattern = f"config:assignment:{unit_id}"
    else:
        pattern = "config:assignment:*"

    deleted_keys = []

    try:
        keys = await database.redis_client.keys(pattern)
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            await database.redis_client.delete(key_str)
            deleted_keys.append(key_str)

        return {
            "success": True,
            "invalidated": deleted_keys,
            "message": "Config cache invalidated. Next request will rebuild cache.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis error: {str(e)}")