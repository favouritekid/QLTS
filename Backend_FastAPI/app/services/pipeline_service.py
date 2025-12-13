# app/services/pipeline_service.py
"""
Pipeline Configuration Service - Manages pipeline stages and consultation statuses.

✅ REFACTORED: Now uses notification_dispatcher for all config change notifications.
This ensures notifications are persisted to database AND sent via Socket.IO.
"""
import json  # ✅ For JSON serialization
from typing import Callable, List, Optional, Tuple  # ✅ ADD Callable, Tuple for transaction pattern

import structlog
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..config import settings  # ✅ For cache TTL
from ..core.events import SystemEvents
from .notification_dispatcher import dispatch
# ✅ Import Redis utilities including distributed lock
from ..database import (
    safe_redis_delete,
    safe_redis_get,
    safe_redis_set,
    redis_distributed_lock,  # ✅ TASK 5.4: Replace asyncio.Lock with Redis distributed lock
)
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# --- ✅ Cache Key and TTL Configuration ---
PIPELINE_STAGES_CACHE_KEY = "pipeline:all_stages"
PIPELINE_STATUSES_CACHE_KEY = "pipeline:all_statuses"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS  # e.g., 3600s

# ✅ TASK 5.4: Removed asyncio.Lock - Now using Redis distributed locks
# This enables proper cache synchronization across multiple workers/pods
# Old: _pipeline_cache_lock = asyncio.Lock()
# Old: _status_cache_lock = asyncio.Lock()
# ----------------------------------------------


# ===============================================================
# CHỨC NĂNG CACHE
# ===============================================================


async def get_all_pipeline_stages(db: AsyncSession) -> List[dict]:
    """Lấy tất cả Pipeline Stages (Hỗ trợ Cache + Chống Cache Stampede)."""
    log.debug("Fetching all pipeline stages", cache_key=PIPELINE_STAGES_CACHE_KEY)

    # 1. Thử cache trước
    try:
        cached_data = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for pipeline stages")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error(
            "Failed to get pipeline stages from cache",
            cache_key=PIPELINE_STAGES_CACHE_KEY,
            error=str(e_redis_get),
        )

    log.debug("Cache miss for pipeline stages, acquiring distributed lock...")

    # 2. Cache Miss -> Acquire Redis Distributed Lock
    # ✅ TASK 5.4: Using Redis distributed lock (works across workers/pods)
    async with redis_distributed_lock("pipeline_stages_cache", timeout=10):
        # 2a. Double-check cache (another worker may have refreshed it)
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring distributed lock) for pipeline stages")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Ignore, we'll query DB

        log.debug("Cache miss (after acquiring distributed lock), querying DB")

        # ✅ SPRINT 4 REFACTORED: Use PipelineRepository for data access
        from app.repositories import PipelineRepository
        
        repo = PipelineRepository(db)
        stages_models = await repo.get_all_stages_ordered()

        # 4. Chuyển đổi models sang list[dict] (include CRM fields)
        stages_data = [
            {
                "id": s.id,
                "name": s.name,
                "order": s.order,
                "is_final_stage": s.is_final_stage,
            }
            for s in stages_models
        ]

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                PIPELINE_STAGES_CACHE_KEY, json.dumps(stages_data), ex=CACHE_TTL
            )
            log.debug("Stored pipeline stages in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set pipeline stages in cache",
                cache_key=PIPELINE_STAGES_CACHE_KEY,
                error=str(e_redis_set),
            )

        # 6. Trả về (lock được tự động giải phóng)
        return stages_data


async def get_all_consultation_statuses(
    db: AsyncSession,
) -> List[dict]:
    """Lấy tất cả Consultation Statuses (Hỗ trợ Cache + Chống Cache Stampede)."""
    log.debug(
        "Fetching all consultation statuses", cache_key=PIPELINE_STATUSES_CACHE_KEY
    )

    # 1. Thử cache
    try:
        cached_data = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for consultation statuses")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error(
            "Failed to get consultation statuses from cache",
            cache_key=PIPELINE_STATUSES_CACHE_KEY,
            error=str(e_redis_get),
        )

    log.debug("Cache miss for consultation statuses, acquiring distributed lock...")

    # 2. Cache Miss -> Acquire Redis Distributed Lock
    # ✅ TASK 5.4: Using Redis distributed lock (works across workers/pods)
    async with redis_distributed_lock("pipeline_statuses_cache", timeout=10):
        # 2a. Double-check cache (another worker may have refreshed it)
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring distributed lock) for statuses")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Ignore, we'll query DB

        log.debug("Cache miss (after acquiring distributed lock), querying DB")

        # ✅ SPRINT 4 REFACTORED: Use PipelineRepository for data access
        from app.repositories import PipelineRepository
        
        repo = PipelineRepository(db)
        statuses_models = await repo.get_all_statuses()

        # 4. Chuyển đổi models sang list[dict] (include CRM fields)
        statuses_data = [
            {
                "id": s.id,
                "name": s.name,
                "color_code": s.color_code,
                "stage_id": s.stage_id,
                "outcome_type": s.outcome_type.value,  # Convert enum to string
                "is_final_status": s.is_final_status,
                "legacy_status": s.legacy_status,  # Backward compatibility
                "is_universal": s.is_universal,  # ✅ Universal status support
                "updates_pipeline": s.updates_pipeline,  # ✅ Pipeline update control
            }
            for s in statuses_models
        ]

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                PIPELINE_STATUSES_CACHE_KEY, json.dumps(statuses_data), ex=CACHE_TTL
            )
            log.debug("Stored consultation statuses in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set consultation statuses in cache",
                cache_key=PIPELINE_STATUSES_CACHE_KEY,
                error=str(e_redis_set),
            )

        # 6. Trả về (lock được tự động giải phóng)
        return statuses_data


async def invalidate_pipeline_cache():
    """Xóa cache của pipeline (stages và statuses)."""
    try:
        await safe_redis_delete(PIPELINE_STAGES_CACHE_KEY)
        await safe_redis_delete(PIPELINE_STATUSES_CACHE_KEY)
        log.info(
            "Pipeline cache invalidated successfully.",
            keys=[PIPELINE_STAGES_CACHE_KEY, PIPELINE_STATUSES_CACHE_KEY],
        )
    except Exception as e:
        log.error("Failed to invalidate pipeline cache", error=str(e))


# ===============================================================
# HELPER (NỘI BỘ)
# ===============================================================


async def _get_stage_by_id(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    stage = await db.get(models.PipelineStage, stage_id)
    if not stage:
        raise ResourceNotFoundError(detail=f"Pipeline Stage '{stage_id}' not found.")
    return stage


async def _get_status_by_id(
    db: AsyncSession, status_id: str
) -> models.ConsultationStatus:
    status = await db.get(models.ConsultationStatus, status_id)
    if not status:
        raise ResourceNotFoundError(
            detail=f"Consultation Status '{status_id}' not found."
        )
    return status


# ===============================================================
# CRUD CHO PIPELINE STAGE
# ===============================================================


async def create_pipeline_stage(
    db: AsyncSession,
    stage_in: schemas.PipelineStageCreate,
    current_user: Optional[models.User] = None
) -> Tuple[models.PipelineStage, Callable]:
    """
    Create a new pipeline stage.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (pipeline_stage, post_commit_callback)
    """
    try:
        # 1. Kiểm tra ID đã tồn tại
        existing_id = await db.get(models.PipelineStage, stage_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Pipeline Stage ID '{stage_in.id}' already exists."
            )

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 2. Kiểm tra 'name' đã tồn tại
        if await repo.check_stage_name_exists(stage_in.name):
            raise DuplicateResourceError(
                f"Pipeline Stage name '{stage_in.name}' already exists."
            )

        # 3. Kiểm tra 'order' đã tồn tại
        if await repo.check_stage_order_exists(stage_in.order):
            raise DuplicateResourceError(
                f"Pipeline Stage order '{stage_in.order}' already exists."
            )

        # 4. Tạo
        db_stage = models.PipelineStage(**stage_in.model_dump())
        db.add(db_stage)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_stage)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 5. Hủy cache
            await invalidate_pipeline_cache()
            log.info("Created new pipeline stage, cache invalidated", stage_id=db_stage.id)

            # 6. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "pipeline_stage",
                        "operation": "created",
                        "resource_id": db_stage.id,
                        "resource_name": db_stage.name,
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return db_stage, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create pipeline stage", error=str(e), exc_info=True)
        raise e


async def get_pipeline_stage(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    """Lấy chi tiết 1 stage (không cache, vì chỉ dùng cho admin)."""
    return await _get_stage_by_id(db, stage_id)


async def update_pipeline_stage(
    db: AsyncSession,
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    current_user: Optional[models.User] = None
) -> Tuple[models.PipelineStage, Callable]:
    """
    Update a pipeline stage.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (pipeline_stage, post_commit_callback)
    """
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        update_data = stage_in.model_dump(exclude_unset=True)

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 1. Kiểm tra 'name' (nếu thay đổi)
        if "name" in update_data and update_data["name"] != db_stage.name:
            if await repo.check_stage_name_exists(update_data["name"], exclude_id=stage_id):
                raise DuplicateResourceError(
                    f"Pipeline Stage name '{update_data['name']}' already in use."
                )

        # 2. Kiểm tra 'order' (nếu thay đổi)
        if "order" in update_data and update_data["order"] != db_stage.order:
            if await repo.check_stage_order_exists(update_data["order"], exclude_id=stage_id):
                raise DuplicateResourceError(
                    f"Pipeline Stage order '{update_data['order']}' already in use."
                )

        # 3. Cập nhật
        for key, value in update_data.items():
            setattr(db_stage, key, value)

        db.add(db_stage)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_stage)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 4. Hủy cache
            await invalidate_pipeline_cache()
            log.info("Updated pipeline stage, cache invalidated", stage_id=db_stage.id)

            # 5. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "pipeline_stage",
                        "operation": "updated",
                        "resource_id": db_stage.id,
                        "resource_name": db_stage.name,
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return db_stage, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to update pipeline stage",
            stage_id=stage_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_pipeline_stage(
    db: AsyncSession,
    stage_id: str,
    current_user: Optional[models.User] = None
) -> Tuple[None, Callable]:
    """
    Delete a pipeline stage.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        db_stage = await _get_stage_by_id(db, stage_id)

        # Store data before deletion for socket event
        stage_data = {
            "id": db_stage.id,
            "name": db_stage.name,
            "order": db_stage.order,
        }

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        child_status_count = await repo.count_statuses_by_stage(stage_id)
        if child_status_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete stage '{stage_id}'. It has {child_status_count} consultation statuses linked to it."
            )

        # 2. Xóa
        await db.delete(db_stage)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 3. Hủy cache
            await invalidate_pipeline_cache()
            log.info("Deleted pipeline stage, cache invalidated", stage_id=stage_id)

            # 4. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "pipeline_stage",
                        "operation": "deleted",
                        "resource_id": stage_id,
                        "resource_name": stage_data["name"],
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to delete pipeline stage",
            stage_id=stage_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# ===============================================================
# CRUD CHO CONSULTATION STATUS
# ===============================================================


async def create_consultation_status(
    db: AsyncSession,
    status_in: schemas.ConsultationStatusCreate,
    current_user: Optional[models.User] = None
) -> Tuple[models.ConsultationStatus, Callable]:
    """
    Create a new consultation status.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (consultation_status, post_commit_callback)
    """
    try:
        # 1. Kiểm tra ID
        existing_id = await db.get(models.ConsultationStatus, status_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Consultation Status ID '{status_in.id}' already exists."
            )

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 2. Kiểm tra 'name' đã tồn tại
        if await repo.check_status_name_exists(status_in.name):
            raise DuplicateResourceError(
                f"Consultation Status name '{status_in.name}' already exists."
            )

        # 3. Kiểm tra Stage cha
        await _get_stage_by_id(
            db, status_in.stage_id
        )  # Sẽ ném 404 nếu stage_id không tồn tại

        # ✅ NEW: Validate universal status constraints
        if status_in.is_universal and status_in.legacy_status:
            log.warning(
                "Creating universal status with legacy_status override",
                status_id=status_in.id,
                status_name=status_in.name,
                legacy_status=status_in.legacy_status,
                recommendation="Universal statuses should not have legacy_status. "
                              "The legacy status derivation is bypassed when updates_pipeline=false.",
            )
            # Note: Không raise error, chỉ warning vì có thể có use case hợp lệ

        # ✅ CRITICAL FIX: Convert Pydantic model to dict with proper enum handling
        create_data = status_in.model_dump(mode='python')

        # ✅ FORCE outcome_type to lowercase (handle ALL possible formats)
        if "outcome_type" in create_data:
            val = create_data["outcome_type"]

            # Log for debugging
            log.debug(
                "Converting outcome_type",
                original_value=val,
                original_type=type(val).__name__
            )

            # Force to lowercase string regardless of input type
            if isinstance(val, models.OutcomeTypeEnum):
                # Enum object -> get .value
                create_data["outcome_type"] = val.value.lower()
            elif isinstance(val, str):
                # String -> force lowercase
                create_data["outcome_type"] = val.lower()
            elif hasattr(val, 'value'):
                # Any object with .value attribute
                create_data["outcome_type"] = str(val.value).lower()
            else:
                # Last resort: stringify and lowercase
                create_data["outcome_type"] = str(val).lower()

            log.debug(
                "Converted outcome_type",
                converted_value=create_data["outcome_type"]
            )

        # 4. Tạo model với dữ liệu đã làm sạch
        db_status = models.ConsultationStatus(**create_data)

        db.add(db_status)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_status)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 5. Hủy cache
            await invalidate_pipeline_cache()
            log.info(
                "Created new consultation status, cache invalidated", status_id=db_status.id
            )

            # 6. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "consultation_status",
                        "operation": "created",
                        "resource_id": db_status.id,
                        "resource_name": db_status.name,
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return db_status, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create consultation status", error=str(e), exc_info=True)
        raise e


async def get_consultation_status(
    db: AsyncSession, status_id: str
) -> models.ConsultationStatus:
    """Lấy chi tiết 1 status (không cache, vì chỉ dùng cho admin)."""
    return await _get_status_by_id(db, status_id)


async def update_consultation_status(
    db: AsyncSession,
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    current_user: Optional[models.User] = None
) -> Tuple[models.ConsultationStatus, Callable]:
    """
    Update a consultation status.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (consultation_status, post_commit_callback)
    """
    try:
        db_status = await _get_status_by_id(db, status_id)
        update_data = status_in.model_dump(exclude_unset=True, mode='python')

        # ✅ FORCE outcome_type to lowercase if present
        if "outcome_type" in update_data:
            val = update_data["outcome_type"]

            log.debug(
                "Converting outcome_type for update",
                original_value=val,
                original_type=type(val).__name__
            )

            # Force to lowercase string regardless of input type
            if isinstance(val, models.OutcomeTypeEnum):
                update_data["outcome_type"] = val.value.lower()
            elif isinstance(val, str):
                update_data["outcome_type"] = val.lower()
            elif hasattr(val, 'value'):
                update_data["outcome_type"] = str(val.value).lower()
            else:
                update_data["outcome_type"] = str(val).lower()

            log.debug(
                "Converted outcome_type for update",
                converted_value=update_data["outcome_type"]
            )

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 1. Kiểm tra 'name' (nếu thay đổi)
        if "name" in update_data and update_data["name"] != db_status.name:
            if await repo.check_status_name_exists(update_data["name"], exclude_id=status_id):
                raise DuplicateResourceError(
                    f"Consultation Status name '{update_data['name']}' already in use."
                )

        # 2. Kiểm tra Stage cha (nếu thay đổi)
        if "stage_id" in update_data and update_data["stage_id"] != db_status.stage_id:
            await _get_stage_by_id(
                db, update_data["stage_id"]
            )  # Ném 404 nếu không tìm thấy

        # ✅ NEW: Validate universal status constraints
        # Check nếu status đang được update thành universal + có legacy_status
        will_be_universal = update_data.get("is_universal", db_status.is_universal)
        will_have_legacy = update_data.get("legacy_status", db_status.legacy_status)

        if will_be_universal and will_have_legacy:
            log.warning(
                "Updating status to universal with legacy_status override",
                status_id=status_id,
                status_name=db_status.name,
                legacy_status=will_have_legacy,
                recommendation="Universal statuses should not have legacy_status. "
                              "The legacy status derivation is bypassed when updates_pipeline=false.",
            )
            # Note: Không raise error, chỉ warning vì có thể có use case hợp lệ

        # 3. Cập nhật
        for key, value in update_data.items():
            setattr(db_status, key, value)

        db.add(db_status)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_status)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 4. Hủy cache
            await invalidate_pipeline_cache()
            log.info(
                "Updated consultation status, cache invalidated", status_id=db_status.id
            )

            # 5. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "consultation_status",
                        "operation": "updated",
                        "resource_id": db_status.id,
                        "resource_name": db_status.name,
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return db_status, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to update consultation status",
            status_id=status_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_consultation_status(
    db: AsyncSession,
    status_id: str,
    current_user: Optional[models.User] = None
) -> Tuple[None, Callable]:
    """
    Delete a consultation status.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        db_status = await _get_status_by_id(db, status_id)

        # Store data before deletion for socket event
        status_data = {
            "id": db_status.id,
            "name": db_status.name,
            "color_code": db_status.color_code,
            "stage_id": db_status.stage_id,
        }

        # ✅ SPRINT 5: Use Repository for validation
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        lead_count = await repo.count_leads_by_status(status_id)
        if lead_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is currently used by {lead_count} leads."
            )

        # (Tùy chọn) Kiểm tra xem có consultation nào đang dùng ID này không
        consultation_count = await repo.count_consultations_by_status(status_id)
        if consultation_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is linked to {consultation_count} consultation history records."
            )

        # 2. Xóa
        await db.delete(db_status)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # 3. Hủy cache
            await invalidate_pipeline_cache()
            log.info("Deleted consultation status, cache invalidated", status_id=status_id)

            # 4. === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "consultation_status",
                        "operation": "deleted",
                        "resource_id": status_id,
                        "resource_name": status_data["name"],
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to delete consultation status",
            status_id=status_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# ===============================================================
# ALLOWED TRANSITIONS CRUD
# ===============================================================


async def get_all_allowed_transitions(db: AsyncSession) -> List[models.AllowedTransition]:
    """
    Lấy tất cả các allowed transitions với thông tin statuses.
    
    ✅ SPRINT 4 REFACTORED: Now uses PipelineRepository for data access.
    """
    from app.repositories import PipelineRepository
    
    repo = PipelineRepository(db)
    return await repo.get_all_transitions_with_statuses()


async def create_allowed_transition(
    db: AsyncSession,
    transition_in: schemas.AllowedTransitionCreate,
    current_user: Optional[models.User] = None
) -> Tuple[models.AllowedTransition, Callable]:
    """
    Create a new allowed transition.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (allowed_transition, post_commit_callback)
    """
    try:
        # 1. Kiểm tra from_status và to_status có tồn tại
        from_status = await _get_status_by_id(db, transition_in.from_status_id)
        to_status = await _get_status_by_id(db, transition_in.to_status_id)

        # 2. Kiểm tra không cho phép chuyển từ status sang chính nó
        if transition_in.from_status_id == transition_in.to_status_id:
            raise DuplicateResourceError(
                "Cannot create transition from a status to itself."
            )

        # ✅ SPRINT 5: Use Repository for validation (already imported above)
        from app.repositories import PipelineRepository
        repo = PipelineRepository(db)

        # 3. Kiểm tra transition đã tồn tại chưa
        if await repo.check_transition_exists(transition_in.from_status_id, transition_in.to_status_id):
            raise DuplicateResourceError(
                f"Transition from '{transition_in.from_status_id}' to '{transition_in.to_status_id}' already exists."
            )

        # 4. Tạo transition
        db_transition = models.AllowedTransition(**transition_in.model_dump())
        db.add(db_transition)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ SPRINT 4 REFACTORED: Use Repository for reload with relationships
        from app.repositories import PipelineRepository
        
        repo = PipelineRepository(db)
        db_transition = await repo.get_transition_by_id_with_statuses(db_transition.id)

        # Store names for callback
        from_name = db_transition.from_status.name if db_transition.from_status else "N/A"
        to_name = db_transition.to_status.name if db_transition.to_status else "N/A"

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Created allowed transition",
                from_status=transition_in.from_status_id,
                to_status=transition_in.to_status_id,
            )

            # === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "allowed_transition",
                        "operation": "created",
                        "resource_id": str(db_transition.id),
                        "resource_name": f"{from_name} → {to_name}",
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return db_transition, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create allowed transition", error=str(e), exc_info=True)
        raise e


async def delete_allowed_transition(
    db: AsyncSession,
    transition_id: int,
    current_user: Optional[models.User] = None
) -> Tuple[None, Callable]:
    """
    Delete an allowed transition.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        # ✅ SPRINT 4 REFACTORED: Use Repository for loading with relationships
        from app.repositories import PipelineRepository
        
        repo = PipelineRepository(db)
        db_transition = await repo.get_transition_by_id_with_statuses(transition_id)

        if not db_transition:
            raise ResourceNotFoundError(
                f"Allowed transition with ID {transition_id} not found."
            )

        # Store data before deletion for socket event
        transition_data = {
            "id": db_transition.id,
            "from_status_id": db_transition.from_status_id,
            "to_status_id": db_transition.to_status_id,
            "from_status_name": db_transition.from_status.name if db_transition.from_status else "N/A",
            "to_status_name": db_transition.to_status.name if db_transition.to_status else "N/A",
        }

        await db.delete(db_transition)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Deleted allowed transition", transition_id=transition_id)

            # === NOTIFICATION: Dispatch pipeline config updated event ===
            if current_user:
                await dispatch(
                    db=db,
                    event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                    payload={
                        "config_type": "allowed_transition",
                        "operation": "deleted",
                        "resource_id": str(transition_id),
                        "resource_name": f"{transition_data['from_status_name']} → {transition_data['to_status_name']}",
                        "actor_id": current_user.id,
                    },
                    auto_commit=True  # ✅ Auto-commit for service callback
                )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to delete allowed transition",
            transition_id=transition_id,
            error=str(e),
            exc_info=True,
        )
        raise e

async def validate_status_transition(
    db: AsyncSession,
    from_status_id: str,
    to_status_id: str
) -> bool:
    """
    Kiểm tra xem việc chuyển từ trạng thái A sang B có hợp lệ không.

    Logic:
    1. Nếu from == to: Luôn đúng (cập nhật thông tin khác của lead).
    2. Nếu from là None (Lead mới): Luôn đúng (hoặc check rule init tùy logic).
    3. ✅ NEW: Nếu to_status là universal: Luôn đúng (có thể dùng ở mọi stage).
    4. Query bảng allowed_transitions.
    """
    if from_status_id == to_status_id:
        return True

    if not from_status_id:
        # Trường hợp Lead chưa có status (hiếm), cho phép gán status đầu tiên
        return True

    # ✅ FIX: Kiểm tra universal status trước khi query transitions
    # Universal statuses có thể dùng ở mọi pipeline stage mà không cần explicit rule
    try:
        to_status = await db.get(models.ConsultationStatus, to_status_id)
        if to_status and to_status.is_universal:
            log.debug(
                "Universal status transition - always allowed",
                from_status=from_status_id,
                to_status=to_status_id,
                status_name=to_status.name,
            )
            return True
    except Exception as e:
        log.warning(
            "Failed to check universal status",
            to_status_id=to_status_id,
            error=str(e)
        )
        # Continue to check allowed_transitions as fallback

    # ✅ SPRINT 4 REFACTORED: Use Repository for transition check
    from app.repositories import PipelineRepository
    
    repo = PipelineRepository(db)
    return await repo.check_transition_exists(from_status_id, to_status_id)


async def get_allowed_next_statuses(
    db: AsyncSession,
    current_status_id: Optional[str]
) -> List[models.ConsultationStatus]:
    """
    Lấy danh sách các trạng thái được phép chuyển đến từ trạng thái hiện tại.

    Logic mới (User Request):
    1.  **Current Status**: Luôn bao gồm trạng thái hiện tại.
    2.  **Siblings**: Tự động bao gồm TẤT CẢ trạng thái trong cùng Stage hiện tại.
    3.  **Allowed Transitions**: Các trạng thái Next Stage được cấu hình rõ ràng.
    4.  **Universal**: Các trạng thái toàn cục (luôn có sẵn).

    Args:
        db: AsyncSession
        current_status_id: ID của trạng thái hiện tại (có thể None)

    Returns:
        Danh sách ConsultationStatus hợp lệ
    """
    # ✅ SPRINT 4 REFACTORED: Use Repository for all status queries
    from app.repositories import PipelineRepository

    repo = PipelineRepository(db)

    # Nếu chưa có status (lead mới), trả về tất cả statuses
    if not current_status_id:
        return await repo.get_all_statuses_with_stage()

    # 1. Lấy thông tin Current Status để biết Stage hiện tại
    current_status = await _get_status_by_id(db, current_status_id)
    current_stage_id = current_status.stage_id if current_status else None

    # 2. Lấy danh sách Allowed Transitions (Cấu hình)
    allowed_transition_statuses = await repo.get_allowed_next_statuses_from(current_status_id)

    # 3. Lấy danh sách Universal
    universal_statuses = await repo.get_universal_statuses_with_stage()

    # 4. ✅ NEW: Lấy danh sách Siblings (Cùng Stage)
    sibling_statuses = []
    if current_stage_id:
        sibling_statuses = await repo.get_statuses_for_stage(current_stage_id)

    # 5. Merge và Deduplicate
    # Sử dụng dict để loại bỏ trùng lặp (key = id)
    final_statuses_map = {}

    # a. Thêm Current Status trước (để đảm bảo có mặt)
    if current_status:
        final_statuses_map[current_status.id] = current_status

    # b. Thêm Siblings (Ưu tiên hiển thị cùng nhóm hiện tại)
    for s in sibling_statuses:
        # Nếu sibling là universal, nó sẽ được xử lý ở bước d (để gom nhóm Universal riêng nếu cần)
        # Nhưng ở đây ta cứ thêm vào, frontend sẽ lọc display.
        # Lưu ý: Sibling đè Current nếu trùng (không sao, cùng object)
        final_statuses_map[s.id] = s

    # c. Thêm Allowed Transitions (Next Stage)
    for s in allowed_transition_statuses:
        final_statuses_map[s.id] = s

    # d. Thêm Universal
    for s in universal_statuses:
        final_statuses_map[s.id] = s

    # 6. Convert về List và Sắp xếp
    final_list = list(final_statuses_map.values())

    # Helper để sort:
    # Order:
    # 1. Current Stage (Siblings) include Current Status
    # 2. Next Stages (Allowed Transitions)
    # 3. Others (Universal outside of above logic?) - Universal thường display riêng dòng 1 Frontend.

    # Tuy nhiên, hàm này trả về 1 list phẳng. Frontend sẽ group.
    # Ta sort sơ bộ để debug dễ hơn: Stage Order -> Status Name
    def sort_key(s):
        stage_order = s.stage.order if s.stage else 999
        return (stage_order, s.name)

    # Cần load relationship stage cho các status (dùng repo đã load hoặc lazy load)
    # Các hàm repo get_statuses_for_stage chưa chắc đã load stage?
    # Kiểm tra lại repo: get_statuses_for_stage dùng select đơn giản.
    # Để an toàn cho sort, ta nên tin tưởng frontend sort hoặc đảm bảo stage loaded.
    # Ở đây ta trả về list, Frontend sẽ dùng field stage_id hoặc stage object để group.

    return final_list