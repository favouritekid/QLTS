# app/routers/sms_campaigns.py
"""
SMS Marketing — campaigns + build + preflight + attestations (admin only).
PR-3. Router "dumb": dịch HTTP ↔ service, commit, không business logic.
Hard gate `require_admin`. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.schemas import sms as sms_schemas
from app.services.sms_campaign_service import SmsCampaignService

router = APIRouter(prefix="/api/sms", tags=["SMS Campaigns"])

# Giới hạn ID khớp cột Integer (int4) — chặn int32 overflow → 500 (#1 R4).
_MAX_ID = 2147483647


# =====================================================================
# Campaign CRUD
# =====================================================================
@router.post(
    "/campaigns",
    response_model=sms_schemas.SmsCampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    payload: sms_schemas.SmsCampaignCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    campaign = await SmsCampaignService(db).create_campaign(
        payload, current_user
    )
    await db.commit()
    return campaign


@router.get("/campaigns", response_model=sms_schemas.SmsCampaignList)
async def list_campaigns(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
):
    total, items = await SmsCampaignService(db).list_campaigns(
        skip=skip, limit=limit, status=status_filter, search=search
    )
    return {"total": total, "items": items}


@router.get(
    "/campaigns/{campaign_id}", response_model=sms_schemas.SmsCampaignOut
)
async def get_campaign(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    return await SmsCampaignService(db).get_campaign(campaign_id)


@router.patch(
    "/campaigns/{campaign_id}", response_model=sms_schemas.SmsCampaignOut
)
async def update_campaign(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsCampaignUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    campaign = await SmsCampaignService(db).update_campaign(
        campaign_id, payload
    )
    await db.commit()
    return campaign


# =====================================================================
# Campaign ↔ group
# =====================================================================
@router.post(
    "/campaigns/{campaign_id}/groups",
    response_model=sms_schemas.SmsCampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_group(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsCampaignGroupAttach,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    campaign = await SmsCampaignService(db).attach_group(
        campaign_id, payload.group_id
    )
    await db.commit()
    return campaign


@router.delete(
    "/campaigns/{campaign_id}/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_group(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    await SmsCampaignService(db).detach_group(campaign_id, group_id)
    await db.commit()
    return None


# =====================================================================
# Build + preflight + attestations
# =====================================================================
@router.post(
    "/campaigns/{campaign_id}/build",
    response_model=sms_schemas.SmsPreflightReport,
)
async def build_campaign(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    report = await SmsCampaignService(db).build(campaign_id, current_user)
    await db.commit()
    return report


@router.get(
    "/campaigns/{campaign_id}/preflight",
    response_model=sms_schemas.SmsPreflightReport,
)
async def get_preflight(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    return await SmsCampaignService(db).preflight(campaign_id)


@router.post(
    "/campaigns/{campaign_id}/attestations",
    response_model=sms_schemas.SmsCampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_attestation(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsAttestationCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    campaign = await SmsCampaignService(db).add_attestation(
        campaign_id, payload, current_user
    )
    await db.commit()
    return campaign
