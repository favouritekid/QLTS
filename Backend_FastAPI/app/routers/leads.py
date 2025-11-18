import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import insights_service, lead_service

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
    """Lấy danh sách Leads (có phân trang, filter, search, sort)."""
    skip = (page - 1) * page_size
    total, leads = await lead_service.get_leads(
        db,
        skip=skip,
        limit=page_size,
        # === ⭐️ TRUYỀN THAM SỐ VÀO SERVICE ===
        status=status,
        assigned_officer_id=assigned_officer_id,
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
    return await lead_service.update_lead(db, lead.id, lead_in, updated_by=current_user)


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
    return await lead_service.add_consultation(
        db, lead.id, current_user.id, consultation_in
    )


@router.post("/{lead_id}/assign", response_model=schemas.Lead)
async def assign_lead_manually(
    assign_data: schemas.AssignLead,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin/Manager only) Gán thủ công một Lead (Đã xác thực 2 lớp)."""
    return await lead_service.assign_lead_manually(
        db, lead.id, assign_data.officer_id, current_user
    )


@router.post("/{lead_id}/action", response_model=schemas.Lead)
async def perform_lead_action(
    action_data: schemas.LeadAction,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Xử lý hành động (reject/reassign) của Officer (Đã xác thực 2 lớp)."""
    return await lead_service.process_officer_action(
        db, lead.id, current_user, action_data.action, action_data.reason
    )


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


@router.delete(
    "/{lead_id}/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_a_consultation(
    consultation_id: int,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin only) Xóa một ghi chú tư vấn (Đã xác thực 2 lớp)."""
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
