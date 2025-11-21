import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..core import deps
from ..services import insights_service, lead_service

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Leads"])

PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Tạo một Lead mới."""
    return await lead_service.create_lead(db, lead_in)


@router.get("", response_model=schemas.LeadsPage)
async def get_all_leads(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    # === ⭐️ THÊM CÁC THAM SỐ QUERY ===
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    assigned_officer_id: Optional[int] = Query(
        None, description="Filter by assigned officer ID"
    ),
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    offering_id: Optional[int] = Query(None, description="Filter by program offering ID"),
    source: Optional[str] = Query(
        None, description="Filter by source (comma-separated)"
    ),
    search: Optional[str] = Query(
        None, description="Search term for name, email, phone"
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
    # === KẾT THÚC THÊM THAM SỐ ===
):
    """
    Lấy danh sách Leads (có phân trang, filter, search, sort).

    **Role-based filtering:**
    - Admin/Manager: Xem tất cả leads
    - Officer: Chỉ xem leads được gán cho mình
    """
    skip = (page - 1) * page_size

    # === ROLE-BASED FILTERING ===
    # Officers can only see their assigned leads
    effective_officer_id = assigned_officer_id
    if current_user.role == "officer":
        # Force filter by current officer, ignore any passed assigned_officer_id
        effective_officer_id = current_user.id

    total, leads = await lead_service.get_leads(
        db,
        skip=skip,
        limit=page_size,
        # === ⭐️ TRUYỀN THAM SỐ VÀO SERVICE ===
        status=status,
        assigned_officer_id=effective_officer_id,
        unit_id=unit_id,
        offering_id=offering_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
        # === KẾT THÚC TRUYỀN THAM SỐ ===
    )
    return {"total_count": total, "leads": leads}


@router.get("/{lead_id}", response_model=schemas.Lead)
async def get_lead_details(
    lead: models.Lead = LeadAccessDep,
):
    """Lấy thông tin chi tiết của một Lead."""
    return lead


@router.put("/{lead_id}", response_model=schemas.Lead)
async def update_existing_lead(
    lead_in: schemas.LeadUpdate,
    lead: models.Lead = LeadAccessDep,
    # Lấy current_user từ Casbin check hoặc get_current_user
    current_user: models.User = PermissionDep,  # <<< LẤY USER TỪ DEPENDENCY
    db: AsyncSession = Depends(database.get_db),
):
    """Cập nhật một Lead (chỉ Admin/Manager)."""
    # <<< SỬA Ở ĐÂY: Truyền current_user vào service >>>

    # Track which fields are being updated
    update_data = lead_in.model_dump(exclude_unset=True)
    updated_fields = list(update_data.keys())
    status_changed = "consultation_status_id" in updated_fields or "pipeline_stage_id" in updated_fields

    result = await lead_service.update_lead(db, lead.id, lead_in, updated_by=current_user)
    await db.commit()

    # Emit Socket.IO event for real-time updates
    from ..socket_manager import emit_lead_updated
    await emit_lead_updated(
        lead_id=lead.id,
        officer_id=result.assigned_officer_id,
        updated_fields=updated_fields,
        updated_by_username=current_user.username,
        status_changed=status_changed,
    )

    return result


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    (Admin only) Soft delete a Lead.

    Sets deleted_at timestamp instead of physically deleting the lead.
    Preserves all historical data (consultations, applications, logs).
    Deleted leads are filtered out from normal queries.

    **Permission:** Admin only (enforced by Casbin)

    **Status Code:** 204 No Content on success

    **Raises:**
    - 404 Not Found: If lead doesn't exist or already deleted
    - 403 Forbidden: If user doesn't have admin permission
    """
    await lead_service.delete_lead(db, lead_id, deleted_by=current_user)
    await db.commit()
    return None


@router.post(
    "/{lead_id}/consultations",
    response_model=schemas.Consultation,
    status_code=status.HTTP_201_CREATED,
)
async def add_new_consultation(
    consultation_in: schemas.ConsultationCreate,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Thêm một ghi chú tư vấn mới cho Lead (Đã xác thực 2 lớp)."""
    # Service 'add_consultation' có logic check quyền sở hữu
    # nhưng check ở đây vẫn an toàn hơn
    result = await lead_service.add_consultation(
        db, lead.id, current_user.id, consultation_in
    )
    await db.commit()

    # Emit Socket.IO event for real-time updates
    from ..socket_manager import emit_consultation_created
    await emit_consultation_created(
        lead_id=lead.id,
        consultation_id=result.id,
        officer_id=lead.assigned_officer_id,
        consultation_status_id=result.consultation_status_id or "",
        created_by_username=current_user.username,
    )

    return result


@router.post("/{lead_id}/assign", response_model=schemas.Lead)
async def assign_lead_manually(
    assign_data: schemas.AssignLead,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin/Manager only) Gán thủ công một Lead (Đã xác thực 2 lớp)."""
    result = await lead_service.assign_lead_manually(
        db, lead.id, assign_data.officer_id, current_user
    )
    await db.commit()
    return result


@router.post("/{lead_id}/action", response_model=schemas.Lead)
async def perform_lead_action(
    action_data: schemas.LeadAction,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Xử lý hành động (reject/reassign) của Officer (Đã xác thực 2 lớp)."""
    result = await lead_service.process_officer_action(
        db, lead.id, current_user, action_data.action, action_data.reason
    )
    await db.commit()
    return result


@router.get("/{lead_id}/timeline", response_model=List[schemas.TimelineItem])
async def get_lead_timeline(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy lịch sử tổng hợp (timeline) của một Lead (Đã xác thực quyền)."""
    return await lead_service.get_lead_timeline(db, lead.id)


@router.get("/{lead_id}/insights", response_model=schemas.LeadInsights)
async def get_lead_insights(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy các chỉ số insight 360 độ của một Lead (Đã xác thực quyền)."""
    timeline = await lead_service.get_lead_timeline(db, lead.id)
    return await insights_service.get_lead_insights(db, lead, timeline)


@router.put(
    "/{lead_id}/consultations/{consultation_id}", response_model=schemas.Consultation
)
async def update_a_consultation(
    consultation_id: int,
    consultation_in: schemas.ConsultationUpdate,
    lead: models.Lead = LeadAccessDep,  # <-- IDOR Check
    current_user: models.User = PermissionDep,  # <-- Casbin Check
    db: AsyncSession = Depends(database.get_db),
):
    """
    Cập nhật một ghi chú tư vấn (Admin: any consultation, Officer: most recent only).

    Permission Rules:
    - Admin: Can update any consultation
    - Officer: Can only update the most recent consultation to maintain consultation chain integrity
    - Other roles: Cannot update consultations

    Business Logic:
    - If status_id is changed and this is the most recent consultation, lead status will be updated
    - Changes are logged in LeadStatusHistory
    - Real-time Socket.IO event is emitted to all connected clients

    This prevents Officers from breaking the consultation chain by editing historical consultations.
    """
    result = await lead_service.update_consultation(
        db, lead.id, consultation_id, consultation_in, current_user
    )
    return result


@router.delete(
    "/{lead_id}/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_a_consultation(
    consultation_id: int,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """
    Xóa một ghi chú tư vấn (Admin: any consultation, Officer: most recent only).

    Permission Rules:
    - Admin: Can delete any consultation
    - Officer: Can only delete the most recent consultation to maintain consultation chain integrity
    - Other roles: Cannot delete consultations

    This prevents Officers from breaking the consultation chain by deleting historical consultations.
    """
    await lead_service.delete_consultation(db, lead.id, consultation_id, current_user)
    return None


@router.get("/export")
async def export_leads(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    format: str = Query("csv", description="Export format (csv or xlsx)"),
    # Apply same filters as get_all_leads
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    assigned_officer_id: Optional[int] = Query(
        None, description="Filter by assigned officer ID"
    ),
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    offering_id: Optional[int] = Query(None, description="Filter by program offering ID"),
    source: Optional[str] = Query(
        None, description="Filter by source (comma-separated)"
    ),
    search: Optional[str] = Query(
        None, description="Search term for name, email, phone"
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
):
    """
    Export leads to CSV or Excel file.

    Apply same filters as the list endpoint to allow exporting filtered results.
    Maximum 10,000 leads per export to prevent performance issues.
    """
    # Get filtered leads (no pagination, but limit to 10,000)
    total, leads = await lead_service.get_leads(
        db,
        skip=0,
        limit=10000,  # Export limit
        status=status,
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        offering_id=offering_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
    )

    if format.lower() == "csv":
        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            "id",
            "full_name",
            "email",
            "phone",
            "status",
            "lead_score",
            "source",
            "education_level",
            "gpa",
            "location",
            "assigned_officer_id",
            "pipeline_stage_id",
            "consultation_status_id",
            "created_at",
            "updated_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for lead in leads:
            writer.writerow({
                "id": lead.id,
                "full_name": lead.full_name,
                "email": lead.email,
                "phone": lead.phone,
                "status": lead.status,
                "lead_score": lead.lead_score,
                "source": lead.source,
                "education_level": lead.education_level or "",
                "gpa": lead.gpa or "",
                "location": lead.location or "",
                "assigned_officer_id": lead.assigned_officer_id or "",
                "pipeline_stage_id": lead.pipeline_stage_id or "",
                "consultation_status_id": lead.consultation_status_id or "",
                "created_at": lead.created_at.isoformat() if lead.created_at else "",
                "updated_at": lead.updated_at.isoformat() if lead.updated_at else "",
            })

        output.seek(0)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leads_export_{timestamp}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    elif format.lower() in ["xlsx", "excel"]:
        # Generate Excel using openpyxl
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Leads Export"

        # Header row with styling
        headers = [
            "ID", "Full Name", "Email", "Phone", "Status", "Lead Score",
            "Source", "Education Level", "GPA", "Location",
            "Assigned Officer ID", "Pipeline Stage ID", "Consultation Status ID",
            "Created At", "Updated At"
        ]
        ws.append(headers)

        # Style header row
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        # Data rows
        for lead in leads:
            ws.append([
                lead.id,
                lead.full_name,
                lead.email,
                lead.phone,
                lead.status,
                lead.lead_score,
                lead.source,
                lead.education_level or "",
                lead.gpa or "",
                lead.location or "",
                lead.assigned_officer_id or "",
                lead.pipeline_stage_id or "",
                lead.consultation_status_id or "",
                lead.created_at.isoformat() if lead.created_at else "",
                lead.updated_at.isoformat() if lead.updated_at else "",
            ])

        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)  # Cap at 50
            ws.column_dimensions[column_letter].width = adjusted_width

        # Save to BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leads_export_{timestamp}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    else:
        return {
            "error": f"Unsupported format '{format}'. Supported formats: csv, xlsx"
        }


@router.get("/import/template")
async def download_import_template(
    format: str = Query("csv", description="Template format (csv or xlsx)"),
    current_user: models.User = PermissionDep,
):
    """
    Download CSV/Excel template for lead import.

    Returns a pre-formatted template file with:
    - Correct column headers (required + optional)
    - Example data row with Vietnamese sample
    - Column descriptions as comments (Excel only)

    **Query Parameters:**
    - `format`: "csv" or "xlsx" (default: csv)

    **Template Columns:**
    - Required: full_name, email, phone, source, unit_id
    - Optional: offering_id, education_level, gpa, location

    **Usage:**
    1. Download template
    2. Fill in lead data
    3. Upload via POST /api/admin/users/leads/import
    """
    # Define template data
    headers = ["full_name", "email", "phone", "source", "unit_id", "offering_id", "education_level", "gpa", "location"]
    example_row = [
        "Nguyễn Văn An",
        "nguyenvanan@gmail.com",
        "0901234567",
        "website",
        "1",  # unit_id - Replace with your actual unit ID
        "",   # offering_id - Optional
        "bachelor",  # high_school, bachelor, master, phd
        "3.5",  # 0.0-4.0
        "Hà Nội"
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "csv":
        # Generate CSV template
        output = io.StringIO()
        writer = csv.writer(output)

        # Add header comment
        output.write("# Lead Import Template\n")
        output.write("# Required columns: full_name, email, phone, source, unit_id\n")
        output.write("# Optional columns: offering_id, education_level, gpa, location\n")
        output.write("# Education levels: high_school, bachelor, master, phd\n")
        output.write("# Sources: website, referral, social_media, walk_in, email, phone, event, other\n")
        output.write("#\n")

        # Write headers and example
        writer.writerow(headers)
        writer.writerow(example_row)

        output.seek(0)
        filename = f"lead_import_template_{timestamp}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    elif format.lower() in ["xlsx", "excel"]:
        # Generate Excel template with styling
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.comments import Comment

        wb = Workbook()
        ws = wb.active
        ws.title = "Lead Import Template"

        # Header row with styling
        ws.append(headers)
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)

        column_descriptions = [
            "Full name (required)",
            "Email address (required, unique per unit)",
            "Phone number (required)",
            "Lead source (required): website, referral, social_media, walk_in, email, phone, event, other",
            "Organization Unit ID (required): Get from /api/organization-units",
            "Program Offering ID (optional): Get from /api/offerings",
            "Education level (optional): high_school, bachelor, master, phd",
            "GPA (optional): 0.0-4.0 scale",
            "Location (optional): City/Province"
        ]

        for idx, cell in enumerate(ws[1], start=0):
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
            # Add comment with description
            cell.comment = Comment(column_descriptions[idx], "System")

        # Example row
        ws.append(example_row)

        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = max(max_length + 2, 15)  # Min 15 chars
            ws.column_dimensions[column_letter].width = adjusted_width

        # Save to BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"lead_import_template_{timestamp}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    else:
        return {"error": f"Unsupported format '{format}'. Supported: csv, xlsx"}


@router.post("/bulk-assign", status_code=status.HTTP_200_OK)
async def bulk_assign_leads(
    bulk_assign_data: schemas.BulkAssignLeadsSchema,
    officer_id: int = Query(..., description="Officer ID to assign leads to"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    (Admin/Manager only) Bulk assign multiple leads to a single officer.

    Assigns multiple leads to one officer in a single operation.
    Continues on errors (doesn't fail fast) and returns detailed results.

    **Request Body:**
    ```json
    {
        "lead_ids": [1, 2, 3, 4, 5]
    }
    ```

    **Query Parameters:**
    - `officer_id`: Target officer ID to assign all leads to

    **Response:**
    ```json
    {
        "total": 5,
        "successful": 4,
        "failed": 1,
        "assigned_lead_ids": [1, 2, 3, 4],
        "errors": [
            {"lead_id": 5, "error": "Lead with id 5 not found"}
        ]
    }
    ```

    **Permission:** Admin or Manager only (enforced by Casbin)

    **Business Rules:**
    - Officer must exist, be active, and have role="officer"
    - Creates AssignmentLog for each successful assignment
    - Logs state change in LeadStatusHistory
    - Updates lead status to "assigned"
    - Updates officer's last_assigned_at timestamp
    """
    result = await lead_service.bulk_assign_leads(
        db,
        lead_ids=bulk_assign_data.lead_ids,
        officer_id=officer_id,
        assigner=current_user
    )
    await db.commit()
    return result


@router.post("/import", response_model=schemas.LeadImportResult)
async def officer_import_leads(
    file: UploadFile = File(
        ..., description="CSV or Excel file containing lead data (.csv, .xlsx)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Import leads từ file CSV hoặc Excel (cho Officer/Admin/Manager).

    **Khác với Admin import:**
    - Leads được tự động gán cho officer đang import
    - Officer chỉ có thể import vào unit của mình

    **Required columns:** full_name, email, phone, source
    **Optional columns:** phone2, offering_id, education_level, gpa, location

    **Note:** unit_id sẽ được tự động set thành unit của officer.
    """
    log.info(
        "Received officer lead import request",
        user_id=current_user.id,
        role=current_user.role,
        filename=file.filename,
    )

    # Validate officer has a unit
    if not current_user.unit_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must be assigned to a unit before importing leads."
        )

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        log.error(
            "Failed to read uploaded file",
            filename=file.filename,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}"
        )

    # Call service with auto-assign parameters
    try:
        result = await lead_service.import_leads_from_file_content(
            file_content=content,
            filename=file.filename or "unknown",
            db=db,
            default_unit_id=current_user.unit_id,  # Force unit to officer's unit
            auto_assign_officer_id=current_user.id,  # Auto-assign to officer
        )
        return result

    except ValueError as e:
        log.warning(
            "Lead import validation failed",
            user_id=current_user.id,
            filename=file.filename,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
