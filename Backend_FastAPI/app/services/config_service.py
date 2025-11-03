# app/services/config_service.py
import json  # 👈 *** ADD IMPORT ***
from typing import Any, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas

# 👈 *** ADD REDIS IMPORTS ***
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import ResourceNotFoundError

log = structlog.get_logger(__name__)

# === ⭐️ CONFIGURATION CACHE SETTINGS ⭐️ ===
CONFIG_CACHE_TTL_SECONDS = 3600  # Cache config for 1 hour


async def get_assignment_config(db: AsyncSession, unit_id: int) -> dict:
    """
    Lấy cấu hình phân chia của một đơn vị.
    ✅ FIXED: Uses Redis Cache-Aside pattern.
    """
    cache_key = f"config:assignment:{unit_id}"
    await log.debug("Fetching assignment config", unit_id=unit_id, cache_key=cache_key) # THÊM await

    # 1. Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            await log.debug("Cache hit for assignment config", unit_id=unit_id) # THÊM await
            return json.loads(cached_data)
    except Exception as e_redis_get:
        # Log error but proceed to DB query (fail-open)
        await log.error( # THÊM await
            "Failed to get assignment config from cache",
            unit_id=unit_id,
            error=str(e_redis_get),
        )

    await log.debug("Cache miss for assignment config, querying DB", unit_id=unit_id) # THÊM await
    # 2. Cache Miss: Query DB
    config = await db.scalar(
        select(models.OfficerAssignmentConfig).where(
            models.OfficerAssignmentConfig.unit_id == unit_id
        )
    )
    
    # === TÁCH KIỂM TRA ===
    if not config:
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found."
        )
    
    # Kiểm tra params (cột JSON có thể cần truy cập)
    config_params = config.params
    
    if not config_params: # Nếu params là None hoặc {}
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found or has no params."
        )
    # === KẾT THÚC TÁCH ===

    # 3. Store in cache
    try:
        await safe_redis_set(
            cache_key, json.dumps(config_params), ex=CONFIG_CACHE_TTL_SECONDS
        )
        await log.debug( # THÊM await
            "Stored assignment config in cache",
            unit_id=unit_id,
            ttl=CONFIG_CACHE_TTL_SECONDS,
        )
    except Exception as e_redis_set:
        await log.error( # THÊM await
            "Failed to set assignment config in cache",
            unit_id=unit_id,
            error=str(e_redis_set),
        )

    return config_params


async def update_assignment_config(
    db: AsyncSession, unit_id: int, params: Any
) -> models.OfficerAssignmentConfig:
    """
    Cập nhật cấu hình phân chia của một đơn vị.
    Sử dụng commit/rollback tường minh.
    """
    cache_key = f"config:assignment:{unit_id}"
    try:
        # Logic tìm hoặc tạo config
        config = await db.scalar(
            select(models.OfficerAssignmentConfig)
            .where(models.OfficerAssignmentConfig.unit_id == unit_id)
            .with_for_update()  # Lock the row
        )
        
        if not config:
            unit = await db.get(models.OrganizationUnit, unit_id)
            if not unit:
                raise ResourceNotFoundError(
                    detail=f"Organization Unit with id {unit_id} not found."
                )
            config = models.OfficerAssignmentConfig(unit_id=unit_id, params=params)
            await log.info("Creating new assignment config", unit_id=unit_id)
        else:
            config.params = params
            await log.info("Updating existing assignment config", unit_id=unit_id)

        db.add(config)
        
        # === THAY ĐỔI CHÍNH ===
        # 1. Commit thay đổi vào DB
        await db.commit()
        # 2. Refresh để load lại cột 'params' sau khi commit
        # (Chỉ định rõ 'params' để đảm bảo nó được load)
        await db.refresh(config, attribute_names=['params'])
        
        config_to_return = config
        # === KẾT THÚC THAY ĐỔI ===

        # --- Invalidate Cache SAU KHI DB commit thành công ---
        try:
            deleted_count = await safe_redis_delete(cache_key)
            if deleted_count > 0:
                await log.info("Invalidated assignment config cache", unit_id=unit_id)
            else:
                await log.debug("No assignment config cache to invalidate", unit_id=unit_id)
        except Exception as e_redis_del:
            await log.error(
                "Failed to invalidate assignment config cache after update",
                unit_id=unit_id,
                error=str(e_redis_del),
            )

        return config_to_return

    except Exception as e:
        await db.rollback() # Rollback nếu có lỗi TRƯỚC KHI commit
        await log.error(
            "Failed to update assignment config",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e # Ném lại lỗi (ví dụ: ResourceNotFoundError)


# --- Skill Rules (Consider caching if needed) ---


async def get_all_skill_rules(db: AsyncSession) -> List[models.SkillRequirementRule]:
    # NOTE: Caching this might be complex due to potential updates.
    # If this list is large and frequently accessed, consider Redis caching
    # with appropriate invalidation when rules are created/deleted.
    # For now, let's keep it simple.
    result = await db.execute(select(models.SkillRequirementRule))
    return result.scalars().all()


async def create_skill_rule(
    db: AsyncSession, rule_in: schemas.SkillRuleCreate
) -> models.SkillRequirementRule:
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = models.SkillRequirementRule(**rule_in.model_dump())
        db.add(db_rule)
        await db.commit()
        await db.refresh(db_rule)
        # Invalidate cache for get_all_skill_rules if implemented
        # await safe_redis_delete("config:all_skill_rules")
        return db_rule
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create skill rule",
            rule=rule_in.model_dump_json(),
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_skill_rule(db: AsyncSession, rule_id: int):
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = await db.get(models.SkillRequirementRule, rule_id)
        if not db_rule:
            raise ResourceNotFoundError(
                detail=f"Skill rule with id {rule_id} not found."
            )
        await db.delete(db_rule)
        await db.commit()
        # Invalidate cache for get_all_skill_rules if implemented
        # await safe_redis_delete("config:all_skill_rules")
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete skill rule", rule_id=rule_id, error=str(e), exc_info=True
        )
        raise e
