# app/routers/sms_contacts.py
"""
SMS Marketing — contact groups & contacts (admin only). PR-2.

Router "dumb": chỉ dịch HTTP ↔ service, commit transaction, không chứa
business logic. Hard gate `require_admin` (Phase 1 admin-only, §2.1 #9).
Service raise domain exception → middleware map sang HTTP. KHÔNG sửa
main.py (đã wire ở PR-1).
"""
import hashlib
from datetime import datetime
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Path,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.schemas import sms as sms_schemas
from app.services.sms_contact_service import SmsContactService

router = APIRouter(prefix="/api/sms", tags=["SMS Contacts"])

# PostgreSQL Integer is int4. Reject oversized path/query values before asyncpg
# receives them and turns an invalid API input into a 500 response.
_MAX_ID = 2147483647


# =====================================================================
# Contact groups
# =====================================================================
@router.post(
    "/contact-groups",
    response_model=sms_schemas.SmsContactGroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact_group(
    payload: sms_schemas.SmsContactGroupCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    group = await SmsContactService(db).create_group(payload, current_user)
    await db.commit()
    return group


@router.get(
    "/contact-groups", response_model=sms_schemas.SmsContactGroupList
)
async def list_contact_groups(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
    group_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
):
    total, items = await SmsContactService(db).list_groups(
        skip=skip,
        limit=limit,
        group_type=group_type,
        is_active=is_active,
        search=search,
    )
    return {"total": total, "items": items}


@router.get(
    "/contact-groups/{group_id}",
    response_model=sms_schemas.SmsContactGroupOut,
)
async def get_contact_group(
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    return await SmsContactService(db).get_group(group_id)


@router.patch(
    "/contact-groups/{group_id}",
    response_model=sms_schemas.SmsContactGroupOut,
)
async def update_contact_group(
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsContactGroupUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    group = await SmsContactService(db).update_group(group_id, payload)
    await db.commit()
    return group


@router.post(
    "/contact-groups/{group_id}/contacts/upload",
    response_model=sms_schemas.SmsImportResult,
)
async def upload_contacts_to_group(
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    file: UploadFile = File(..., description="File .csv hoặc .xlsx"),
    source_label: Optional[str] = Form(None),
    consent_basis: Optional[str] = Form(None),
    consent_disclosure_version: Optional[str] = Form(None),
    consent_proof_ref: Optional[str] = Form(None),
    consent_obtained_at: Optional[datetime] = Form(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    content = await file.read()
    file_sha256 = hashlib.sha256(content).hexdigest() if content else None
    result = await SmsContactService(db).import_contacts(
        group_id=group_id,
        file_content=content,
        filename=file.filename or "",
        user=current_user,
        source_label=source_label,
        consent_basis=consent_basis,
        consent_disclosure_version=consent_disclosure_version,
        consent_proof_ref=consent_proof_ref,
        consent_obtained_at=consent_obtained_at,
        file_sha256=file_sha256,
    )
    await db.commit()
    return result


@router.get(
    "/contact-groups/{group_id}/contacts",
    response_model=sms_schemas.SmsContactList,
)
async def list_group_contacts(
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    consent_status: Optional[str] = Query(None),
):
    # 404 nếu nhóm không tồn tại
    await SmsContactService(db).get_group(group_id)
    total, items = await SmsContactService(db).list_contacts(
        skip=skip,
        limit=limit,
        search=search,
        consent_status=consent_status,
        group_id=group_id,
    )
    return {"total": total, "items": items}


# =====================================================================
# Contacts
# =====================================================================
@router.get("/contacts", response_model=sms_schemas.SmsContactList)
async def list_contacts(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    consent_status: Optional[str] = Query(None),
):
    total, items = await SmsContactService(db).list_contacts(
        skip=skip,
        limit=limit,
        search=search,
        consent_status=consent_status,
    )
    return {"total": total, "items": items}


@router.post(
    "/contacts",
    response_model=sms_schemas.SmsContactOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    payload: sms_schemas.SmsContactCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    contact = await SmsContactService(db).create_contact(
        payload, current_user
    )
    await db.commit()
    return contact


@router.patch(
    "/contacts/{contact_id}", response_model=sms_schemas.SmsContactOut
)
async def update_contact(
    contact_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsContactUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    contact = await SmsContactService(db).update_contact(
        contact_id, payload
    )
    await db.commit()
    return contact


@router.post(
    "/contacts/{contact_id}/consent-events",
    response_model=sms_schemas.SmsConsentEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def append_consent_event(
    contact_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsConsentEventCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    event = await SmsContactService(db).append_consent_event(
        contact_id, payload, current_user
    )
    await db.commit()
    return event


@router.get(
    "/contacts/{contact_id}/consent-events",
    response_model=sms_schemas.SmsConsentEventList,
)
async def list_consent_events(
    contact_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
):
    total, items = await SmsContactService(db).list_consent_events(
        contact_id, skip=skip, limit=limit
    )
    return {"total": total, "items": items}


@router.post(
    "/contacts/{contact_id}/groups",
    response_model=sms_schemas.SmsContactOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_contact_to_group(
    contact_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    payload: sms_schemas.SmsGroupMembershipAdd,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    service = SmsContactService(db)
    await service.add_contact_to_group(
        contact_id, payload.group_id, payload.note, current_user
    )
    await db.commit()
    # Trả contact (kèm trạng thái mới nhất) cho client tiện refresh
    return await service.get_contact(contact_id)


@router.delete(
    "/contacts/{contact_id}/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_contact_from_group(
    contact_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    group_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    await SmsContactService(db).remove_contact_from_group(
        contact_id, group_id
    )
    await db.commit()
    return None
