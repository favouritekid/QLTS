# app/services/pipeline_service.py
import asyncio  # ✅ Thêm import
import json  # ✅ Thêm import
from typing import List

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings  # ✅ Thêm import
# ✅ Thêm import
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# --- ✅ Định nghĩa Key, TTL, và Lock cho Cache ---
PIPELINE_STAGES_CACHE_KEY = "pipeline:all_stages"
PIPELINE_STATUSES_CACHE_KEY = "pipeline:all_statuses"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS  # Lấy từ config (ví dụ: 3600s)

_pipeline_cache_lock = asyncio.Lock()
_status_cache_lock = asyncio.Lock()
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

    log.debug("Cache miss for pipeline stages, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _pipeline_cache_lock:
        # 2a. Kiểm tra lại cache (phòng trường hợp request khác đã refresh)
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring lock) for pipeline stages")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Bỏ qua, chúng ta sẽ query lại

        log.debug("Cache miss (after acquiring lock), querying DB")

        # 3. Cache Miss: Query DB
        query = select(models.PipelineStage).order_by(models.PipelineStage.order)
        result = await db.execute(query)
        stages_models = result.scalars().all()

        # 4. Chuyển đổi models sang list[dict]
        stages_data = [
            {"id": s.id, "name": s.name, "order": s.order} for s in stages_models
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

    log.debug("Cache miss for consultation statuses, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _status_cache_lock:
        # 2a. Kiểm tra lại cache
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring lock) for statuses")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass

        log.debug("Cache miss (after acquiring lock), querying DB")

        # 3. Cache Miss: Query DB
        query = select(models.ConsultationStatus)
        result = await db.execute(query)
        statuses_models = result.scalars().all()

        # 4. Chuyển đổi models sang list[dict]
        statuses_data = [
            {
                "id": s.id,
                "name": s.name,
                "color_code": s.color_code,
                "stage_id": s.stage_id,
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
    db: AsyncSession, stage_in: schemas.PipelineStageCreate
) -> models.PipelineStage:
    try:
        # 1. Kiểm tra ID đã tồn tại
        existing_id = await db.get(models.PipelineStage, stage_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Pipeline Stage ID '{stage_in.id}' already exists."
            )

        # 2. Kiểm tra 'order' đã tồn tại
        existing_order = await db.scalar(
            select(models.PipelineStage).where(
                models.PipelineStage.order == stage_in.order
            )
        )
        if existing_order:
            raise DuplicateResourceError(
                f"Pipeline Stage order '{stage_in.order}' already exists."
            )

        # 3. Tạo
        db_stage = models.PipelineStage(**stage_in.model_dump())
        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

        # 4. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Created new pipeline stage, cache invalidated", stage_id=db_stage.id)

        return db_stage
    except Exception as e:
        await db.rollback()
        log.error("Failed to create pipeline stage", error=str(e), exc_info=True)
        raise e


async def get_pipeline_stage(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    """Lấy chi tiết 1 stage (không cache, vì chỉ dùng cho admin)."""
    return await _get_stage_by_id(db, stage_id)


async def update_pipeline_stage(
    db: AsyncSession, stage_id: str, stage_in: schemas.PipelineStageUpdate
) -> models.PipelineStage:
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        update_data = stage_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra 'order' (nếu thay đổi)
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

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_stage, key, value)

        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Updated pipeline stage, cache invalidated", stage_id=db_stage.id)

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


async def delete_pipeline_stage(db: AsyncSession, stage_id: str):
    try:
        db_stage = await _get_stage_by_id(db, stage_id)

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
    db: AsyncSession, status_in: schemas.ConsultationStatusCreate
) -> models.ConsultationStatus:
    try:
        # 1. Kiểm tra ID
        existing_id = await db.get(models.ConsultationStatus, status_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Consultation Status ID '{status_in.id}' already exists."
            )

        # 2. Kiểm tra Stage cha
        await _get_stage_by_id(
            db, status_in.stage_id
        )  # Sẽ ném 404 nếu stage_id không tồn tại

        # 3. Tạo
        db_status = models.ConsultationStatus(**status_in.model_dump())
        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)

        # 4. Hủy cache
        await invalidate_pipeline_cache()
        log.info(
            "Created new consultation status, cache invalidated", status_id=db_status.id
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
    db: AsyncSession, status_id: str, status_in: schemas.ConsultationStatusUpdate
) -> models.ConsultationStatus:
    try:
        db_status = await _get_status_by_id(db, status_id)
        update_data = status_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra Stage cha (nếu thay đổi)
        if "stage_id" in update_data and update_data["stage_id"] != db_status.stage_id:
            await _get_stage_by_id(
                db, update_data["stage_id"]
            )  # Ném 404 nếu không tìm thấy

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_status, key, value)

        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info(
            "Updated consultation status, cache invalidated", status_id=db_status.id
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


async def delete_consultation_status(db: AsyncSession, status_id: str):
    try:
        db_status = await _get_status_by_id(db, status_id)

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

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete consultation status",
            status_id=status_id,
            error=str(e),
            exc_info=True,
        )
        raise e
