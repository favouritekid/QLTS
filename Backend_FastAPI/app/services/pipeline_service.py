# app/services/pipeline_service.py
"""
Pipeline Configuration Service - Manages pipeline stages and consultation statuses.

✅ REFACTORED: Now uses notification_dispatcher for all config change notifications.
This ensures notifications are persisted to database AND sent via Socket.IO.
"""
import json  # ✅ For JSON serialization
from typing import List, Optional

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

        # 3. Cache Miss: Query DB
        query = select(models.PipelineStage).order_by(models.PipelineStage.order)
        result = await db.execute(query)
        stages_models = result.scalars().all()

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

        # 3. Cache Miss: Query DB
        query = select(models.ConsultationStatus)
        result = await db.execute(query)
        statuses_models = result.scalars().all()

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
) -> models.PipelineStage:
    try:
        # 1. Kiểm tra ID đã tồn tại
        existing_id = await db.get(models.PipelineStage, stage_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Pipeline Stage ID '{stage_in.id}' already exists."
            )

        # 2. Kiểm tra 'name' đã tồn tại
        existing_name = await db.scalar(
            select(models.PipelineStage).where(
                models.PipelineStage.name == stage_in.name
            )
        )
        if existing_name:
            raise DuplicateResourceError(
                f"Pipeline Stage name '{stage_in.name}' already exists."
            )

        # 3. Kiểm tra 'order' đã tồn tại
        existing_order = await db.scalar(
            select(models.PipelineStage).where(
                models.PipelineStage.order == stage_in.order
            )
        )
        if existing_order:
            raise DuplicateResourceError(
                f"Pipeline Stage order '{stage_in.order}' already exists."
            )

        # 4. Tạo
        db_stage = models.PipelineStage(**stage_in.model_dump())
        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

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
                }
            )

        return db_stage
    except Exception as e:
        await db.rollback()
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
) -> models.PipelineStage:
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        update_data = stage_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra 'name' (nếu thay đổi)
        if "name" in update_data and update_data["name"] != db_stage.name:
            existing_name = await db.scalar(
                select(models.PipelineStage).where(
                    models.PipelineStage.name == update_data["name"]
                )
            )
            if existing_name:
                raise DuplicateResourceError(
                    f"Pipeline Stage name '{update_data['name']}' already in use."
                )

        # 2. Kiểm tra 'order' (nếu thay đổi)
        if "order" in update_data and update_data["order"] != db_stage.order:
            existing_order = await db.scalar(
                select(models.PipelineStage).where(
                    models.PipelineStage.order == update_data["order"]
                )
            )
            if existing_order:
                raise DuplicateResourceError(
                    f"Pipeline Stage order '{update_data['order']}' already in use."
                )

        # 3. Cập nhật
        for key, value in update_data.items():
            setattr(db_stage, key, value)

        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

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
                }
            )

        return db_stage
    except Exception as e:
        await db.rollback()
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
):
    try:
        db_stage = await _get_stage_by_id(db, stage_id)

        # Store data before deletion for socket event
        stage_data = {
            "id": db_stage.id,
            "name": db_stage.name,
            "order": db_stage.order,
        }

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        child_status_count = await db.scalar(
            select(func.count(models.ConsultationStatus.id)).where(
                models.ConsultationStatus.stage_id == stage_id
            )
        )
        if child_status_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete stage '{stage_id}'. It has {child_status_count} consultation statuses linked to it."
            )

        # 2. Xóa
        await db.delete(db_stage)
        await db.commit()

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
                }
            )

    except Exception as e:
        await db.rollback()
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
) -> models.ConsultationStatus:
    try:
        # 1. Kiểm tra ID
        existing_id = await db.get(models.ConsultationStatus, status_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Consultation Status ID '{status_in.id}' already exists."
            )

        # 2. Kiểm tra 'name' đã tồn tại
        existing_name = await db.scalar(
            select(models.ConsultationStatus).where(
                models.ConsultationStatus.name == status_in.name
            )
        )
        if existing_name:
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
        await db.commit()
        await db.refresh(db_status)

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
                }
            )

        return db_status
    except Exception as e:
        await db.rollback()
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
) -> models.ConsultationStatus:
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

        # 1. Kiểm tra 'name' (nếu thay đổi)
        if "name" in update_data and update_data["name"] != db_status.name:
            existing_name = await db.scalar(
                select(models.ConsultationStatus).where(
                    models.ConsultationStatus.name == update_data["name"]
                )
            )
            if existing_name:
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
        await db.commit()
        await db.refresh(db_status)

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
                }
            )

        return db_status
    except Exception as e:
        await db.rollback()
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
):
    try:
        db_status = await _get_status_by_id(db, status_id)

        # Store data before deletion for socket event
        status_data = {
            "id": db_status.id,
            "name": db_status.name,
            "color_code": db_status.color_code,
            "stage_id": db_status.stage_id,
        }

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        lead_count = await db.scalar(
            select(func.count(models.Lead.id)).where(
                models.Lead.consultation_status_id == status_id
            )
        )
        if lead_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is currently used by {lead_count} leads."
            )

        # (Tùy chọn) Kiểm tra xem có consultation nào đang dùng ID này không
        consultation_count = await db.scalar(
            select(func.count(models.Consultation.id)).where(
                models.Consultation.consultation_status_id == status_id
            )
        )
        if consultation_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is linked to {consultation_count} consultation history records."
            )

        # 2. Xóa
        await db.delete(db_status)
        await db.commit()

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
                }
            )

    except Exception as e:
        await db.rollback()
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
    """Lấy tất cả các allowed transitions với thông tin statuses."""
    query = (
        select(models.AllowedTransition)
        .options(
            # Eager load related statuses
            selectinload(models.AllowedTransition.from_status),
            selectinload(models.AllowedTransition.to_status),
        )
        .order_by(models.AllowedTransition.from_status_id)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_allowed_transition(
    db: AsyncSession,
    transition_in: schemas.AllowedTransitionCreate,
    current_user: Optional[models.User] = None
) -> models.AllowedTransition:
    """Tạo một allowed transition mới."""
    try:
        # 1. Kiểm tra from_status và to_status có tồn tại
        from_status = await _get_status_by_id(db, transition_in.from_status_id)
        to_status = await _get_status_by_id(db, transition_in.to_status_id)

        # 2. Kiểm tra không cho phép chuyển từ status sang chính nó
        if transition_in.from_status_id == transition_in.to_status_id:
            raise DuplicateResourceError(
                "Cannot create transition from a status to itself."
            )

        # 3. Kiểm tra transition đã tồn tại chưa
        existing = await db.scalar(
            select(models.AllowedTransition).where(
                models.AllowedTransition.from_status_id == transition_in.from_status_id,
                models.AllowedTransition.to_status_id == transition_in.to_status_id,
            )
        )
        if existing:
            raise DuplicateResourceError(
                f"Transition from '{transition_in.from_status_id}' to '{transition_in.to_status_id}' already exists."
            )

        # 4. Tạo transition
        db_transition = models.AllowedTransition(**transition_in.model_dump())
        db.add(db_transition)
        await db.commit()
        
        # ✅ FIX: Thay thế db.refresh bằng query có selectinload
        # Điều này nạp trước các quan hệ (from_status, to_status) để tránh lỗi MissingGreenlet
        query = (
            select(models.AllowedTransition)
            .options(
                selectinload(models.AllowedTransition.from_status),
                selectinload(models.AllowedTransition.to_status),
            )
            .where(models.AllowedTransition.id == db_transition.id)
        )
        result = await db.execute(query)
        db_transition = result.scalar_one()

        log.info(
            "Created allowed transition",
            from_status=transition_in.from_status_id,
            to_status=transition_in.to_status_id,
        )

        # === NOTIFICATION: Dispatch pipeline config updated event ===
        if current_user:
            from_name = db_transition.from_status.name if db_transition.from_status else "N/A"
            to_name = db_transition.to_status.name if db_transition.to_status else "N/A"
            await dispatch(
                db=db,
                event=SystemEvents.PIPELINE_CONFIG_UPDATED,
                payload={
                    "config_type": "allowed_transition",
                    "operation": "created",
                    "resource_id": str(db_transition.id),
                    "resource_name": f"{from_name} → {to_name}",
                    "actor_id": current_user.id,
                }
            )

        return db_transition

    except Exception as e:
        await db.rollback()
        log.error("Failed to create allowed transition", error=str(e), exc_info=True)
        raise e


async def delete_allowed_transition(
    db: AsyncSession,
    transition_id: int,
    current_user: Optional[models.User] = None
):
    """Xóa một allowed transition."""
    try:
        # Load with relationships for socket event
        query = (
            select(models.AllowedTransition)
            .options(
                selectinload(models.AllowedTransition.from_status),
                selectinload(models.AllowedTransition.to_status),
            )
            .where(models.AllowedTransition.id == transition_id)
        )
        result = await db.execute(query)
        db_transition = result.scalar_one_or_none()

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
        await db.commit()

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
                }
            )

    except Exception as e:
        await db.rollback()
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

    # TODO: Performance Opt - Có thể cache danh sách allowed_transitions vào Redis
    # Hiện tại query DB trực tiếp để đảm bảo tính đúng đắn (Consistency)
    query = select(models.AllowedTransition).where(
        and_(
            models.AllowedTransition.from_status_id == from_status_id,
            models.AllowedTransition.to_status_id == to_status_id
        )
    )
    result = await db.execute(query)
    transition = result.scalar_one_or_none()

    return transition is not None


async def get_allowed_next_statuses(
    db: AsyncSession,
    current_status_id: Optional[str]
) -> List[models.ConsultationStatus]:
    """
    Lấy danh sách các trạng thái được phép chuyển đến từ trạng thái hiện tại.

    Sử dụng bảng allowed_transitions để xác định workflow hợp lệ.
    ✅ LUÔN bao gồm universal statuses (is_universal=True) bất kể workflow.
    Nếu current_status_id là None (lead mới), trả về tất cả statuses.

    Args:
        db: AsyncSession
        current_status_id: ID của trạng thái hiện tại (có thể None)

    Returns:
        Danh sách ConsultationStatus được phép chuyển đến
    """
    # Nếu chưa có status (lead mới), trả về tất cả statuses
    if not current_status_id:
        query = (
            select(models.ConsultationStatus)
            .options(selectinload(models.ConsultationStatus.stage))
            .order_by(
                models.ConsultationStatus.is_universal.desc(),  # Universal first
                models.ConsultationStatus.stage_id,
                models.ConsultationStatus.name
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    # Query các transitions được phép từ status hiện tại
    query = (
        select(models.ConsultationStatus)
        .join(
            models.AllowedTransition,
            models.ConsultationStatus.id == models.AllowedTransition.to_status_id
        )
        .where(models.AllowedTransition.from_status_id == current_status_id)
        .options(selectinload(models.ConsultationStatus.stage))
        .order_by(models.ConsultationStatus.name)
    )

    result = await db.execute(query)
    allowed_statuses = list(result.scalars().all())

    # ✅ NEW: Luôn thêm universal statuses (có thể dùng ở mọi stage)
    universal_query = (
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.is_universal == True)
        .options(selectinload(models.ConsultationStatus.stage))
        .order_by(models.ConsultationStatus.name)
    )
    universal_result = await db.execute(universal_query)
    universal_statuses = list(universal_result.scalars().all())

    # Lấy current status để kiểm tra
    current_status = await _get_status_by_id(db, current_status_id)

    # ✅ IMPROVED: Merge với ordering rõ ràng
    # Thứ tự: Current (if not universal) → Universal → Allowed (sorted)
    final_statuses = []
    allowed_ids = {s.id for s in allowed_statuses}
    universal_ids = {s.id for s in universal_statuses}

    # 1. Current status first (nếu không phải universal và không trong allowed)
    if current_status and not current_status.is_universal and current_status.id not in allowed_ids:
        final_statuses.append(current_status)

    # 2. Universal statuses (already sorted by name)
    # Tránh duplicate với allowed list
    for universal_status in universal_statuses:
        if universal_status.id not in allowed_ids:
            final_statuses.append(universal_status)

    # 3. Allowed statuses (sorted by stage_id, then name for better UX)
    sorted_allowed = sorted(allowed_statuses, key=lambda s: (s.stage_id, s.name))
    final_statuses.extend(sorted_allowed)

    log.debug(
        "get_allowed_next_statuses",
        current_status=current_status_id,
        total_allowed=len(final_statuses),
        universal_count=len(universal_statuses),
        explicit_transitions=len(allowed_statuses),
    )

    return final_statuses