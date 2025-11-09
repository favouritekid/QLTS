# 🚀 Hướng Dẫn Implementation Hoàn Chỉnh: Quản Lý Organization (Major/Unit)

**Dự án:** QLTS (Quản Lý Tài Sản)  
**Module:** Organization Management (Đơn vị & Ngành học)  
**Thời gian ước tính:** 15-21 giờ  
**Ngày tạo:** 2025-11-09

---

## 📋 Mục Lục

- [Phase 0: Chuẩn Bị](#phase-0-chuẩn-bị)
- [Phase 1: Backend Foundation](#phase-1-backend-foundation)
- [Phase 2: Frontend Data Layer](#phase-2-frontend-data-layer)
- [Phase 3: UI Components](#phase-3-ui-components)
- [Phase 4: Admin Page](#phase-4-admin-page)
- [Phase 5: Integration & Testing](#phase-5-integration--testing)
- [Phase 6: Polish & Deploy](#phase-6-polish--deploy)

---

## Phase 0: Chuẩn Bị

### ✅ Prerequisites Checklist

```bash
# 1. Kiểm tra Backend đang chạy
curl http://localhost:8000/docs

# 2. Kiểm tra Frontend đang chạy
curl http://localhost:3000

# 3. Kiểm tra Redis đang chạy
redis-cli ping  # Phải trả về PONG

# 4. Kiểm tra Database migrations
cd Backend_FastAPI
alembic current  # Xem migration hiện tại

# 5. Tạo branch mới
git checkout -b feature/organization-management
```

### 📦 Dependencies Cần Thiết

Backend (đã có sẵn):
- ✅ FastAPI
- ✅ SQLAlchemy
- ✅ Redis
- ✅ Socket.IO

Frontend (đã có sẵn):
- ✅ Next.js 14
- ✅ React Query (TanStack Query)
- ✅ shadcn/ui
- ✅ Socket.IO client

### 🗂️ Cấu Trúc Files Sẽ Tạo/Sửa

```
Backend_FastAPI/
├── app/
│   ├── routers/
│   │   └── admin.py                    # ✏️ SỬA - Thêm organization endpoints
│   ├── services/
│   │   └── organization_service.py     # ✏️ SỬA - Thêm emit functions
│   └── socket_manager.py               # ✏️ SỬA - Thêm emit_to_all nếu chưa có

frontend/
├── src/
│   ├── app/(dashboard)/admin/
│   │   └── organization/
│   │       └── page.tsx                # 🆕 TẠO - Admin page
│   ├── components/admin/organization/
│   │   ├── UnitDialog.tsx              # 🆕 TẠO - Dialog tạo/sửa unit
│   │   ├── MajorDialog.tsx             # 🆕 TẠO - Dialog tạo/sửa major
│   │   ├── OrganizationTree.tsx        # 🆕 TẠO - Tree view component
│   │   └── BulkActions.tsx             # 🆕 TẠO - Bulk operations
│   ├── components/layouts/
│   │   └── SocketHandler.tsx           # ✏️ SỬA - Thêm organization handler
│   ├── hooks/
│   │   └── useOrganization.ts          # 🆕 TẠO - React Query hooks
│   ├── lib/api/
│   │   └── endpoints.ts                # ✏️ SỬA - Thêm endpoints
│   └── types/
│       └── organization.types.ts       # 🆕 TẠO - TypeScript types
```

---

## Phase 1: Backend Foundation (⏱️ 3-4 giờ)

### Bước 1.1: Tạo Emit Function cho Socket.IO

**File:** `Backend_FastAPI/app/socket_manager.py`

```python
# app/socket_manager.py

# Tìm class SocketManager và thêm method này (nếu chưa có)

class SocketManager:
    # ... existing code ...
    
    async def emit_to_all(
        self,
        event: str,
        data: dict,
        namespace: str = "/"
    ):
        """
        Phát sóng một sự kiện đến TẤT CẢ clients đã kết nối.
        
        Args:
            event: Tên sự kiện (ví dụ: "data_updated")
            data: Dữ liệu cần gửi
            namespace: Socket.IO namespace (mặc định "/")
        """
        try:
            await self.sio.emit(event, data, namespace=namespace)
            log.info(
                "Emitted event to all clients",
                event=event,
                namespace=namespace,
                data_keys=list(data.keys())
            )
        except Exception as e:
            log.error(
                "Failed to emit event to all clients",
                event=event,
                error=str(e),
                exc_info=True
            )

# Export singleton instance
socket_manager = SocketManager()
```

### Bước 1.2: Thêm Emit Functions vào Organization Service

**File:** `Backend_FastAPI/app/services/organization_service.py`

```python
# app/services/organization_service.py

# 1️⃣ THÊM IMPORTS ở đầu file
from datetime import datetime
from ..socket_manager import socket_manager

# ... existing imports ...

# 2️⃣ THÊM HELPER FUNCTION sau phần imports
async def emit_organization_updated(
    operation: str,
    resource_type: str,  # "organization" hoặc "major"
    resource_id: int,
    resource_name: str = None
):
    """
    Phát sóng sự kiện cập nhật organization qua Socket.IO.
    
    Args:
        operation: "create", "update", hoặc "delete"
        resource_type: "organization" hoặc "major"
        resource_id: ID của resource
        resource_name: Tên của resource (optional)
    """
    try:
        await socket_manager.emit_to_all(
            "data_updated",
            {
                "resource_type": resource_type,
                "operation": operation,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        log.info(
            "Emitted organization update",
            resource_type=resource_type,
            operation=operation,
            resource_id=resource_id
        )
    except Exception as e:
        log.error(
            "Failed to emit organization update",
            resource_type=resource_type,
            operation=operation,
            resource_id=resource_id,
            error=str(e)
        )

# 3️⃣ CẬP NHẬT CÁC FUNCTIONS HIỆN CÓ

# Tìm function create_organization_unit và thêm emit call
async def create_organization_unit(
    db: AsyncSession, unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    try:
        if unit_in.parent_id:
            parent_unit = await db.get(models.OrganizationUnit, unit_in.parent_id)
            if not parent_unit:
                raise ResourceNotFoundError(
                    detail=f"Parent unit with id {unit_in.parent_id} not found."
                )

        db_unit = models.OrganizationUnit(**unit_in.model_dump())
        db.add(db_unit)
        await db.commit()
        await db.refresh(db_unit)

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="create",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        return await get_organization_unit_by_id(db, db_unit.id)
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create organization unit",
            unit_name=unit_in.name,
            error=str(e),
            exc_info=True,
        )
        raise e


# Tìm function update_organization_unit và thêm emit call
async def update_organization_unit(
    db: AsyncSession, unit_id: int, unit_in: schemas.OrganizationUnitUpdate
) -> models.OrganizationUnit:
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        update_data = unit_in.model_dump(exclude_unset=True)

        if "parent_id" in update_data:
            new_parent_id = update_data["parent_id"]
            if new_parent_id is None:
                db_unit.parent_id = None
            else:
                if new_parent_id == unit_id:
                    raise DuplicateResourceError(
                        detail="A unit cannot be its own parent."
                    )
                parent_unit = await db.get(models.OrganizationUnit, new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )
                db_unit.parent_id = new_parent_id

        for key, value in update_data.items():
            if key != "parent_id":
                setattr(db_unit, key, value)

        db.add(db_unit)
        await db.commit()

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="update",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        return await get_organization_unit_by_id(db, unit_id)
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# Tìm function delete_organization_unit và thêm emit call
async def delete_organization_unit(db: AsyncSession, unit_id: int):
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        unit_name = db_unit.name  # Lưu tên trước khi xóa
        
        if db_unit.children or db_unit.majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains child units or majors."
            )
        await db.delete(db_unit)
        await db.commit()

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="delete",
            resource_type="organization",
            resource_id=unit_id,
            resource_name=unit_name
        )

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# 4️⃣ LÀM TƯƠNG TỰ CHO MAJOR FUNCTIONS

# Tìm function create_major và thêm emit call
async def create_major(db: AsyncSession, major_in: schemas.MajorCreate) -> models.Major:
    try:
        existing_major_query = select(models.Major).where(
            models.Major.code == major_in.code
        )
        existing_major = await db.execute(existing_major_query)
        if existing_major.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Major with code '{major_in.code}' already exists."
            )

        db_major = models.Major(**major_in.model_dump())
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="create",
            resource_type="major",
            resource_id=db_major.id,
            resource_name=db_major.name
        )

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create major",
            major_code=major_in.code,
            error=str(e),
            exc_info=True,
        )
        raise e


# Tìm function update_major và thêm emit call
async def update_major(
    db: AsyncSession, major_id: int, major_in: schemas.MajorUpdate
) -> models.Major:
    try:
        db_major = await get_major_by_id(db, major_id)
        update_data = major_in.model_dump(exclude_unset=True)

        if "code" in update_data and update_data["code"] != db_major.code:
            existing_major_query = select(models.Major).where(
                models.Major.code == update_data["code"]
            )
            if (await db.execute(existing_major_query)).scalar_one_or_none():
                raise DuplicateResourceError(
                    detail=f"Major with code '{update_data['code']}' already exists."
                )

        for key, value in update_data.items():
            setattr(db_major, key, value)
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="update",
            resource_type="major",
            resource_id=db_major.id,
            resource_name=db_major.name
        )

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


# Tìm function delete_major và thêm emit call
async def delete_major(db: AsyncSession, major_id: int):
    try:
        db_major = await get_major_by_id(db, major_id)
        major_name = db_major.name  # Lưu tên trước khi xóa
        
        await db.delete(db_major)
        await db.commit()

        await invalidate_org_cache()  # Existing
        
        # 🆕 THÊM DÒNG NÀY
        await emit_organization_updated(
            operation="delete",
            resource_type="major",
            resource_id=major_id,
            resource_name=major_name
        )

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e
```

### Bước 1.3: Thêm Admin Endpoints

**File:** `Backend_FastAPI/app/routers/admin.py`

Tìm cuối file và thêm đoạn code này:

```python
# app/routers/admin.py

# ... existing imports ...
from ..services import organization_service  # 🆕 THÊM IMPORT NÀY

# ... existing code ...

# 🆕 THÊM TẤT CẢ CODE BÊN DƯỚI vào cuối file, trước dòng cuối cùng


# =====================================================================
# ORGANIZATION MANAGEMENT ENDPOINTS (Admin Only)
# =====================================================================

# -------------------- Organization Units --------------------

@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
    summary="Create Organization Unit",
    description="Create a new organization unit (Admin only)",
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Tạo đơn vị tổ chức mới.
    
    **Requires:** Admin role
    
    **Returns:** Created organization unit with full details
    """
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    summary="Get Organization Unit Details",
    description="Get detailed information about a specific organization unit",
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    """
    Lấy thông tin chi tiết của một đơn vị.
    
    **Requires:** Authenticated user
    """
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    summary="Update Organization Unit",
    description="Update an existing organization unit (Admin only)",
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Cập nhật thông tin đơn vị tổ chức.
    
    **Requires:** Admin role
    
    **Note:** Cannot create circular dependencies (unit cannot be its own parent)
    """
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Organization Unit",
    description="Delete an organization unit (Admin only)",
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Xóa đơn vị tổ chức.
    
    **Requires:** Admin role
    
    **Note:** Cannot delete units that have children or majors
    """
    await organization_service.delete_organization_unit(db, unit_id)
    return None


# -------------------- Majors --------------------

@router.post(
    "/majors",
    response_model=schemas.Major,
    status_code=status.HTTP_201_CREATED,
    summary="Create Major",
    description="Create a new major/program (Admin only)",
)
async def create_new_major(
    major_in: schemas.MajorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Tạo ngành học mới.
    
    **Requires:** Admin role
    
    **Note:** Major code must be unique
    """
    return await organization_service.create_major(db, major_in)


@router.get(
    "/majors/{major_id}",
    response_model=schemas.Major,
    summary="Get Major Details",
    description="Get detailed information about a specific major",
)
async def get_major_details(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    """
    Lấy thông tin chi tiết của một ngành học.
    
    **Requires:** Authenticated user
    """
    return await organization_service.get_major_by_id(db, major_id)


@router.put(
    "/majors/{major_id}",
    response_model=schemas.Major,
    summary="Update Major",
    description="Update an existing major (Admin only)",
)
async def update_existing_major(
    major_id: int,
    major_in: schemas.MajorUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Cập nhật thông tin ngành học.
    
    **Requires:** Admin role
    """
    return await organization_service.update_major(db, major_id, major_in)


@router.delete(
    "/majors/{major_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Major",
    description="Delete a major (Admin only)",
)
async def delete_existing_major(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """
    Xóa ngành học.
    
    **Requires:** Admin role
    """
    await organization_service.delete_major(db, major_id)
    return None
```

### Bước 1.4: Test Backend

```bash
# 1. Restart backend server
cd Backend_FastAPI
# Ctrl+C để dừng server
python -m uvicorn app.main:app --reload

# 2. Mở browser, truy cập Swagger docs
# http://localhost:8000/docs

# 3. Test các endpoints mới (cần login với admin account trước):
# - POST /api/admin/organization-units
# - PUT /api/admin/organization-units/{id}
# - DELETE /api/admin/organization-units/{id}
# - POST /api/admin/majors
# - PUT /api/admin/majors/{id}
# - DELETE /api/admin/majors/{id}

# 4. Kiểm tra Socket.IO emissions
# Mở browser console, kết nối socket và lắng nghe:
```

JavaScript test (chạy trong browser console):
```javascript
const socket = io('http://localhost:8000');
socket.on('data_updated', (data) => {
    console.log('Received data_updated:', data);
});
```

### ✅ Checkpoint Phase 1

- [ ] Socket emit function đã hoạt động
- [ ] Tất cả CRUD endpoints đã test thành công
- [ ] Socket.IO emissions được nhận ở client
- [ ] No errors trong backend logs

---

## Phase 2: Frontend Data Layer (⏱️ 2-3 giờ)

### Bước 2.1: Tạo TypeScript Types

**File:** `frontend/src/types/organization.types.ts` (TẠO MỚI)

```typescript
// src/types/organization.types.ts

/**
 * Organization Unit (Đơn vị tổ chức)
 */
export interface OrganizationUnit {
  id: number;
  name: string;
  type: string;
  description?: string | null;
  parent_id: number | null;
  children: OrganizationUnit[];
  majors: Major[];
  // Relationship fields (computed)
  parent?: OrganizationUnit | null;
}

/**
 * Major (Ngành học)
 */
export interface Major {
  id: number;
  name: string;
  code: string;
  description?: string | null;
  unit_id: number;
  unit?: OrganizationUnit;
}

/**
 * Form data for creating organization unit
 */
export interface OrganizationUnitCreate {
  name: string;
  type: string;
  description?: string | null;
  parent_id?: number | null;
}

/**
 * Form data for updating organization unit
 */
export interface OrganizationUnitUpdate {
  name?: string;
  type?: string;
  description?: string | null;
  parent_id?: number | null;
}

/**
 * Form data for creating major
 */
export interface MajorCreate {
  name: string;
  code: string;
  description?: string | null;
  unit_id: number;
}

/**
 * Form data for updating major
 */
export interface MajorUpdate {
  name?: string;
  code?: string;
  description?: string | null;
  unit_id?: number;
}

/**
 * API Response for organization list
 */
export interface OrganizationListResponse {
  units: OrganizationUnit[];
  total: number;
}

/**
 * Flattened unit for easier rendering (with hierarchy info)
 */
export interface FlattenedUnit {
  unit: OrganizationUnit;
  level: number;
  hasChildren: boolean;
}
```

### Bước 2.2: Cập Nhật API Endpoints

**File:** `frontend/src/lib/api/endpoints.ts` (SỬA)

```typescript
// src/lib/api/endpoints.ts

export const API_ENDPOINTS = {
  AUTH: {
    // ... existing code ...
  },
  SESSIONS: {
    // ... existing code ...
  },
  USERS: {
    // ... existing code ...
  },
  PROFILE: {
    // ... existing code ...
  },
  
  // 🆕 THÊM BLOCK MỚI - Organization (Public)
  ORGANIZATION: {
    LIST_UNITS: "/api/organization-units",
    GET_UNIT: (id: number) => `/api/organization-units/${id}`,
    LIST_MAJORS: "/api/majors",
    GET_MAJOR: (id: number) => `/api/majors/${id}`,
  },
  
  ADMIN: {
    USERS: {
      // ... existing code ...
    },
    PERMISSIONS: {
      // ... existing code ...
    },
    
    // 🆕 THÊM BLOCK MỚI - Organization Management (Admin Only)
    ORGANIZATION: {
      // Units
      CREATE_UNIT: "/api/admin/organization-units",
      UPDATE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,
      DELETE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,
      
      // Majors
      CREATE_MAJOR: "/api/admin/majors",
      UPDATE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
      DELETE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
    },
    
    ACTIVITY_LOGS: "/api/admin/activity-logs",
    STATISTICS: "/api/admin/statistics",
  },
  NOTIFICATIONS: {
    // ... existing code ...
  },
} as const;
```

### Bước 2.3: Tạo React Query Hooks

**File:** `frontend/src/hooks/useOrganization.ts` (TẠO MỚI)

```typescript
// src/hooks/useOrganization.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { ApiErrorResponse } from "@/types/api.types";
import type {
  OrganizationUnit,
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
  Major,
  MajorCreate,
  MajorUpdate,
} from "@/types/organization.types";

// =====================================================================
// QUERY KEYS
// =====================================================================

export const organizationKeys = {
  all: ["organization"] as const,
  lists: () => [...organizationKeys.all, "list"] as const,
  list: (filters?: string) => [...organizationKeys.lists(), { filters }] as const,
  details: () => [...organizationKeys.all, "detail"] as const,
  detail: (id: number) => [...organizationKeys.details(), id] as const,
  
  // Major-specific keys
  majors: () => [...organizationKeys.all, "majors"] as const,
  majorsList: (unitId?: number, search?: string) => 
    [...organizationKeys.majors(), { unitId, search }] as const,
  majorDetail: (id: number) => [...organizationKeys.majors(), "detail", id] as const,
};

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get all organization units (tree structure)
 * Uses: Public endpoint, automatic cache invalidation via Socket.IO
 */
export function useOrganizationUnits() {
  return useQuery<OrganizationUnit[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.list(),
    queryFn: async () => {
      const response = await api.get<OrganizationUnit[]>(
        API_ENDPOINTS.ORGANIZATION.LIST_UNITS
      );
      return response.data;
    },
    staleTime: Infinity, // Cache forever, invalidate via Socket.IO
    gcTime: 1000 * 60 * 30, // 30 minutes in cache
  });
}

/**
 * Get a single organization unit by ID
 */
export function useOrganizationUnit(id: number) {
  return useQuery<OrganizationUnit, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.detail(id),
    queryFn: async () => {
      const response = await api.get<OrganizationUnit>(
        API_ENDPOINTS.ORGANIZATION.GET_UNIT(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: Infinity,
  });
}

/**
 * Get majors by unit ID (with optional search)
 */
export function useMajors(unitId?: number, search?: string) {
  return useQuery<Major[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorsList(unitId, search),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (unitId) params.append("unitId", String(unitId));
      if (search) params.append("search", search);
      
      const response = await api.get<Major[]>(
        `${API_ENDPOINTS.ORGANIZATION.LIST_MAJORS}?${params.toString()}`
      );
      return response.data;
    },
    enabled: !!unitId,
    staleTime: Infinity,
  });
}

/**
 * Get a single major by ID
 */
export function useMajor(id: number) {
  return useQuery<Major, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorDetail(id),
    queryFn: async () => {
      const response = await api.get<Major>(
        API_ENDPOINTS.ORGANIZATION.GET_MAJOR(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: Infinity,
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Organization Units
// =====================================================================

/**
 * Create a new organization unit
 * Includes optimistic updates for better UX
 */
export function useCreateUnit() {
  const queryClient = useQueryClient();
  
  return useMutation<
    OrganizationUnit,
    AxiosError<ApiErrorResponse>,
    OrganizationUnitCreate
  >({
    mutationFn: async (data) => {
      const response = await api.post<OrganizationUnit>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_UNIT,
        data
      );
      return response.data;
    },
    onSuccess: (newUnit) => {
      toast.success("Đơn vị mới đã được tạo!", {
        description: newUnit.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Tạo đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing organization unit
 * Includes optimistic updates
 */
export function useUpdateUnit() {
  const queryClient = useQueryClient();
  
  return useMutation<
    OrganizationUnit,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OrganizationUnitUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<OrganizationUnit>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_UNIT(id),
        data
      );
      return response.data;
    },
    
    // Optimistic update
    onMutate: async ({ id, data }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: organizationKeys.list() });
      
      // Snapshot the previous value
      const previousUnits = queryClient.getQueryData<OrganizationUnit[]>(
        organizationKeys.list()
      );
      
      // Optimistically update the cache
      if (previousUnits) {
        const updateUnitInTree = (units: OrganizationUnit[]): OrganizationUnit[] => {
          return units.map(unit => {
            if (unit.id === id) {
              return { ...unit, ...data };
            }
            if (unit.children && unit.children.length > 0) {
              return {
                ...unit,
                children: updateUnitInTree(unit.children)
              };
            }
            return unit;
          });
        };
        
        queryClient.setQueryData<OrganizationUnit[]>(
          organizationKeys.list(),
          updateUnitInTree(previousUnits)
        );
      }
      
      return { previousUnits };
    },
    
    // Rollback on error
    onError: (err, variables, context) => {
      if (context?.previousUnits) {
        queryClient.setQueryData(
          organizationKeys.list(),
          context.previousUnits
        );
      }
      
      const message = err.response?.data?.detail || "Cập nhật đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },
    
    onSuccess: (updatedUnit) => {
      toast.success("Đơn vị đã được cập nhật!", {
        description: updatedUnit.name,
      });
      // Socket.IO will handle final cache invalidation
    },
  });
}

/**
 * Delete an organization unit
 */
export function useDeleteUnit() {
  const queryClient = useQueryClient();
  
  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_UNIT(id));
    },
    
    onSuccess: (_, deletedId) => {
      toast.success("Đơn vị đã được xóa!");
      // Socket.IO will handle cache invalidation
    },
    
    onError: (error) => {
      const message = error.response?.data?.detail || "Xóa đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Majors
// =====================================================================

/**
 * Create a new major
 */
export function useCreateMajor() {
  const queryClient = useQueryClient();
  
  return useMutation<Major, AxiosError<ApiErrorResponse>, MajorCreate>({
    mutationFn: async (data) => {
      const response = await api.post<Major>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_MAJOR,
        data
      );
      return response.data;
    },
    onSuccess: (newMajor) => {
      toast.success("Ngành học mới đã được tạo!", {
        description: newMajor.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Tạo ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing major
 */
export function useUpdateMajor() {
  const queryClient = useQueryClient();
  
  return useMutation<
    Major,
    AxiosError<ApiErrorResponse>,
    { id: number; data: MajorUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<Major>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_MAJOR(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedMajor) => {
      toast.success("Ngành học đã được cập nhật!", {
        description: updatedMajor.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Cập nhật ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete a major
 */
export function useDeleteMajor() {
  const queryClient = useQueryClient();
  
  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_MAJOR(id));
    },
    onSuccess: () => {
      toast.success("Ngành học đã được xóa!");
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Xóa ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

/**
 * Flatten organization tree for easier rendering
 * Preserves hierarchy information
 */
export function flattenOrganizationTree(
  units: OrganizationUnit[],
  level: number = 0
): Array<{ unit: OrganizationUnit; level: number; hasChildren: boolean }> {
  const result: Array<{ unit: OrganizationUnit; level: number; hasChildren: boolean }> = [];
  
  for (const unit of units) {
    result.push({
      unit,
      level,
      hasChildren: unit.children && unit.children.length > 0,
    });
    
    if (unit.children && unit.children.length > 0) {
      result.push(...flattenOrganizationTree(unit.children, level + 1));
    }
  }
  
  return result;
}

/**
 * Get all descendant IDs of a unit (for preventing circular dependencies)
 */
export function getAllDescendantIds(
  unit: OrganizationUnit,
  allUnits: OrganizationUnit[]
): Set<number> {
  const descendants = new Set<number>([unit.id]);
  
  const findChildren = (parentId: number) => {
    const children = allUnits.filter(u => u.parent_id === parentId);
    children.forEach(child => {
      descendants.add(child.id);
      findChildren(child.id); // Recursive
    });
  };
  
  findChildren(unit.id);
  return descendants;
}

/**
 * Check if making unitId a parent of childId would create a circular dependency
 */
export function wouldCreateCircularDependency(
  parentId: number,
  childId: number,
  allUnits: OrganizationUnit[]
): boolean {
  const childUnit = allUnits.find(u => u.id === childId);
  if (!childUnit) return false;
  
  const descendants = getAllDescendantIds(childUnit, allUnits);
  return descendants.has(parentId);
}
```

### Bước 2.4: Cập Nhật SocketHandler

**File:** `frontend/src/components/layouts/SocketHandler.tsx` (SỬA)

```typescript
// components/layouts/SocketHandler.tsx

// ... existing imports ...
import { organizationKeys } from "@/hooks/useOrganization"; // 🆕 THÊM IMPORT NÀY

export function SocketHandler() {
  // ... existing code ...

  useEffect(() => {
    const socket = socketService.getSocket();
    if (!socket) return;

    // ... existing handlers ...

    // ✅ Tìm function handleDataUpdated và THÊM cases mới
    const handleDataUpdated = (data: {
      resource_type: string;
      operation: "create" | "update" | "delete";
      resource_id: number;
      resource_name?: string;
      timestamp: string;
    }) => {
      console.log("[SocketHandler] Received data_updated event:", data);

      switch (data.resource_type) {
        case "user":
          // ... existing code ...
          break;
          
        case "lead":
          // ... existing code ...
          break;
          
        // 🆕 THÊM CASE MỚI CHO ORGANIZATION
        case "organization":
          // Invalidate all organization-related queries
          queryClient.invalidateQueries({
            queryKey: organizationKeys.all
          });
          
          // Show toast notification
          const operationText =
            data.operation === "create" ? "tạo mới" :
            data.operation === "update" ? "cập nhật" :
            "xóa";
          
          toast.info(`Đơn vị đã được ${operationText}`, {
            description: data.resource_name 
              ? `${data.resource_name} - Dữ liệu được làm mới tự động`
              : "Danh sách đơn vị được làm mới tự động",
            duration: 3000,
          });
          break;
          
        // 🆕 THÊM CASE MỚI CHO MAJOR
        case "major":
          // Major changes affect the entire organization tree
          queryClient.invalidateQueries({
            queryKey: organizationKeys.all
          });
          
          toast.info("Ngành học đã được cập nhật", {
            description: data.resource_name 
              ? `${data.resource_name}`
              : "Dữ liệu được làm mới tự động",
            duration: 3000,
          });
          break;
          
        case "policy":
          // ... existing code ...
          break;

        default:
          console.warn("[SocketHandler] Unknown resource_type:", data.resource_type);
      }
    };

    // ... rest of the code (listeners registration) ...
    socket.on("data_updated", handleDataUpdated);
    // ... other listeners ...

    return () => {
      socket.off("data_updated", handleDataUpdated);
      // ... other cleanup ...
    };
  }, [isAuthenticated, addNotification, preferences, queryClient]);

  return null;
}
```

### ✅ Checkpoint Phase 2

- [ ] Types đã được tạo đầy đủ
- [ ] API endpoints đã được thêm vào config
- [ ] React Query hooks đã test với dummy data
- [ ] SocketHandler đã được cập nhật
- [ ] No TypeScript errors

---

## Phase 3: UI Components (⏱️ 4-5 giờ)

### Bước 3.1: Tạo Unit Dialog Component

**File:** `frontend/src/components/admin/organization/UnitDialog.tsx` (TẠO MỚI)

```typescript
// components/admin/organization/UnitDialog.tsx
"use client";

import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, Plus, Building2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  useCreateUnit,
  useUpdateUnit,
  getAllDescendantIds,
  wouldCreateCircularDependency,
} from "@/hooks/useOrganization";
import type {
  OrganizationUnit,
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
} from "@/types/organization.types";

// =====================================================================
// VALIDATION SCHEMA
// =====================================================================

const unitSchema = z.object({
  name: z
    .string()
    .min(3, "Tên phải có ít nhất 3 ký tự")
    .max(255, "Tên không được quá 255 ký tự")
    .regex(
      /^[a-zA-ZÀ-ỹ0-9\s\-&().]+$/,
      "Tên chỉ được chứa chữ cái, số và các ký tự đặc biệt: - & ( ) ."
    ),
  type: z
    .string()
    .min(1, "Loại đơn vị là bắt buộc")
    .max(50, "Loại đơn vị không được quá 50 ký tự"),
  description: z
    .string()
    .max(1000, "Mô tả không được quá 1000 ký tự")
    .optional()
    .nullable(),
  parent_id: z.coerce
    .number()
    .int("ID phải là số nguyên")
    .positive("ID phải là số dương")
    .optional()
    .nullable(),
});

type UnitFormValues = z.infer<typeof unitSchema>;

// =====================================================================
// COMPONENT
// =====================================================================

interface UnitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  unit?: OrganizationUnit | null;
  allUnits: OrganizationUnit[];
}

export function UnitDialog({
  open,
  onOpenChange,
  unit,
  allUnits,
}: UnitDialogProps) {
  const isEditMode = !!unit;
  
  const createMutation = useCreateUnit();
  const updateMutation = useUpdateUnit();
  const isPending = createMutation.isPending || updateMutation.isPending;

  const form = useForm<UnitFormValues>({
    resolver: zodResolver(unitSchema),
    defaultValues: {
      name: "",
      type: "Khoa",
      description: "",
      parent_id: null,
    },
  });

  // Reset form when dialog opens/closes or unit changes
  useEffect(() => {
    if (open) {
      if (isEditMode && unit) {
        form.reset({
          name: unit.name,
          type: unit.type,
          description: unit.description || "",
          parent_id: unit.parent_id,
        });
      } else {
        form.reset({
          name: "",
          type: "Khoa",
          description: "",
          parent_id: null,
        });
      }
    }
  }, [unit, isEditMode, form, open]);

  // Get valid parent options (exclude self and descendants)
  const validParentOptions = useMemo(() => {
    if (!isEditMode || !unit) {
      return allUnits;
    }
    
    const excludedIds = getAllDescendantIds(unit, allUnits);
    return allUnits.filter(u => !excludedIds.has(u.id));
  }, [allUnits, unit, isEditMode]);

  // Flatten units with hierarchy for display
  const flattenedParentOptions = useMemo(() => {
    const flatten = (
      units: OrganizationUnit[],
      level: number = 0
    ): Array<{ unit: OrganizationUnit; level: number }> => {
      const result: Array<{ unit: OrganizationUnit; level: number }> = [];
      
      for (const u of units) {
        result.push({ unit: u, level });
        
        if (u.children && u.children.length > 0) {
          result.push(...flatten(u.children, level + 1));
        }
      }
      
      return result;
    };
    
    return flatten(validParentOptions);
  }, [validParentOptions]);

  // Submit handler
  async function onSubmit(values: UnitFormValues) {
    try {
      // Check for circular dependency before submitting
      if (values.parent_id && isEditMode && unit) {
        if (wouldCreateCircularDependency(values.parent_id, unit.id, allUnits)) {
          form.setError("parent_id", {
            message: "Không thể chọn đơn vị này làm cha vì sẽ tạo vòng lặp",
          });
          return;
        }
      }

      if (isEditMode && unit) {
        // Update
        await updateMutation.mutateAsync({
          id: unit.id,
          data: values as OrganizationUnitUpdate,
        });
      } else {
        // Create
        await createMutation.mutateAsync(values as OrganizationUnitCreate);
      }
      
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error already handled by mutation hooks
      console.error("Submit error:", error);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            {isEditMode ? "Chỉnh sửa Đơn vị" : "Tạo Đơn vị Mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? `Cập nhật thông tin cho "${unit?.name}"`
              : "Thêm một đơn vị mới vào cấu trúc tổ chức"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên Đơn vị <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Ví dụ: Khoa Công nghệ Thông tin"
                      {...field}
                      disabled={isPending}
                    />
                  </FormControl>
                  <FormDescription>
                    Tên đầy đủ của đơn vị tổ chức
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Type Field */}
            <FormField
              control={form.control}
              name="type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Loại Đơn vị <span className="text-destructive">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn loại đơn vị" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="Khoa">Khoa</SelectItem>
                      <SelectItem value="Viện">Viện</SelectItem>
                      <SelectItem value="Phòng ban">Phòng ban</SelectItem>
                      <SelectItem value="Trung tâm">Trung tâm</SelectItem>
                      <SelectItem value="Bộ môn">Bộ môn</SelectItem>
                      <SelectItem value="Khác">Khác</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Phân loại đơn vị (Khoa, Viện, Phòng ban, v.v.)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Parent Unit Field */}
            <FormField
              control={form.control}
              name="parent_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đơn vị Cha (Tùy chọn)</FormLabel>
                  <Select
                    onValueChange={(value) =>
                      field.onChange(value === "null" ? null : parseInt(value))
                    }
                    value={field.value ? String(field.value) : "null"}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn đơn vị cha..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="null">
                        <span className="text-muted-foreground">
                          Không có (Root level)
                        </span>
                      </SelectItem>
                      {flattenedParentOptions.map(({ unit: u, level }) => {
                        const indent = "  ".repeat(level);
                        const prefix = level > 0 ? "└─ " : "";
                        return (
                          <SelectItem key={u.id} value={String(u.id)}>
                            {indent}
                            {prefix}
                            {u.name} ({u.type})
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Chọn đơn vị cấp trên (nếu có). Để trống nếu đây là đơn vị cấp cao nhất.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Description Field */}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mô tả (Tùy chọn)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả chi tiết về đơn vị..."
                      className="resize-none"
                      rows={3}
                      {...field}
                      value={field.value || ""}
                      disabled={isPending}
                    />
                  </FormControl>
                  <FormDescription>
                    Thông tin bổ sung về đơn vị (tối đa 1000 ký tự)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Warning for editing */}
            {isEditMode && unit && (unit.children.length > 0 || unit.majors.length > 0) && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Đơn vị này có {unit.children.length} đơn vị con và{" "}
                  {unit.majors.length} ngành học. Thay đổi có thể ảnh hưởng đến cấu trúc tổ chức.
                </AlertDescription>
              </Alert>
            )}

            {/* Footer Buttons */}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditMode ? "Lưu thay đổi" : "Tạo Đơn vị"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

### Bước 3.2: Tạo Major Dialog Component

**File:** `frontend/src/components/admin/organization/MajorDialog.tsx` (TẠO MỚI)

```typescript
// components/admin/organization/MajorDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, GraduationCap } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCreateMajor,
  useUpdateMajor,
  flattenOrganizationTree,
} from "@/hooks/useOrganization";
import type {
  Major,
  MajorCreate,
  MajorUpdate,
  OrganizationUnit,
} from "@/types/organization.types";

// =====================================================================
// VALIDATION SCHEMA
// =====================================================================

const majorSchema = z.object({
  name: z
    .string()
    .min(3, "Tên phải có ít nhất 3 ký tự")
    .max(255, "Tên không được quá 255 ký tự"),
  code: z
    .string()
    .min(2, "Mã ngành phải có ít nhất 2 ký tự")
    .max(50, "Mã ngành không được quá 50 ký tự")
    .regex(
      /^[A-Z0-9_-]+$/,
      "Mã ngành chỉ được chứa chữ IN HOA, số, gạch dưới và gạch ngang"
    ),
  description: z
    .string()
    .max(1000, "Mô tả không được quá 1000 ký tự")
    .optional()
    .nullable(),
  unit_id: z.coerce
    .number({ required_error: "Phải chọn đơn vị" })
    .int("ID phải là số nguyên")
    .positive("Phải chọn đơn vị"),
});

type MajorFormValues = z.infer<typeof majorSchema>;

// =====================================================================
// COMPONENT
// =====================================================================

interface MajorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  major?: Major | null;
  allUnits: OrganizationUnit[];
}

export function MajorDialog({
  open,
  onOpenChange,
  major,
  allUnits,
}: MajorDialogProps) {
  const isEditMode = !!major;
  
  const createMutation = useCreateMajor();
  const updateMutation = useUpdateMajor();
  const isPending = createMutation.isPending || updateMutation.isPending;

  const form = useForm<MajorFormValues>({
    resolver: zodResolver(majorSchema),
    defaultValues: {
      name: "",
      code: "",
      description: "",
      unit_id: 0,
    },
  });

  // Reset form when dialog opens/closes or major changes
  useEffect(() => {
    if (open) {
      if (isEditMode && major) {
        form.reset({
          name: major.name,
          code: major.code,
          description: major.description || "",
          unit_id: major.unit_id,
        });
      } else {
        form.reset({
          name: "",
          code: "",
          description: "",
          unit_id: 0,
        });
      }
    }
  }, [major, isEditMode, form, open]);

  // Flatten units for display
  const flattenedUnits = flattenOrganizationTree(allUnits);

  // Submit handler
  async function onSubmit(values: MajorFormValues) {
    try {
      if (isEditMode && major) {
        // Update
        await updateMutation.mutateAsync({
          id: major.id,
          data: values as MajorUpdate,
        });
      } else {
        // Create
        await createMutation.mutateAsync(values as MajorCreate);
      }
      
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error already handled by mutation hooks
      console.error("Submit error:", error);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GraduationCap className="h-5 w-5" />
            {isEditMode ? "Chỉnh sửa Ngành học" : "Tạo Ngành học Mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? `Cập nhật thông tin cho "${major?.name}"`
              : "Thêm một ngành học mới vào hệ thống"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên Ngành học <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Ví dụ: Công nghệ Thông tin"
                      {...field}
                      disabled={isPending}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Code Field */}
            <FormField
              control={form.control}
              name="code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Mã Ngành <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Ví dụ: IT-2024"
                      {...field}
                      disabled={isPending || isEditMode} // Code không thể sửa
                      className="uppercase"
                      onChange={(e) =>
                        field.onChange(e.target.value.toUpperCase())
                      }
                    />
                  </FormControl>
                  <FormDescription>
                    Mã ngành duy nhất (chỉ chữ IN HOA, số, gạch dưới và gạch ngang)
                    {isEditMode && " - Không thể thay đổi"}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit Field */}
            <FormField
              control={form.control}
              name="unit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Đơn vị Quản lý <span className="text-destructive">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={(value) => field.onChange(parseInt(value))}
                    value={field.value ? String(field.value) : undefined}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn đơn vị quản lý..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {flattenedUnits.map(({ unit, level }) => {
                        const indent = "  ".repeat(level);
                        const prefix = level > 0 ? "└─ " : "";
                        return (
                          <SelectItem key={unit.id} value={String(unit.id)}>
                            {indent}
                            {prefix}
                            {unit.name} ({unit.type})
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Chọn đơn vị chịu trách nhiệm quản lý ngành học này
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Description Field */}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mô tả (Tùy chọn)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả chi tiết về ngành học..."
                      className="resize-none"
                      rows={3}
                      {...field}
                      value={field.value || ""}
                      disabled={isPending}
                    />
                  </FormControl>
                  <FormDescription>
                    Thông tin bổ sung về ngành học (tối đa 1000 ký tự)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Footer Buttons */}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditMode ? "Lưu thay đổi" : "Tạo Ngành học"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

### ✅ Checkpoint Phase 3

- [ ] UnitDialog component đã test với mock data
- [ ] MajorDialog component đã test với mock data
- [ ] Form validation hoạt động đúng
- [ ] Parent selection không tạo circular dependency
- [ ] UI responsive trên mobile

---

**(Phần tiếp theo sẽ có Phase 4, 5, 6 - bạn có muốn tôi tiếp tục không? File này đã khá dài rồi.)**
