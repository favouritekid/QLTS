# 📋 Đánh Giá Chi Tiết Kế Hoạch Implement Quản Lý Organization (Major/Unit)

**Dự án:** QLTS (Quản Lý Tài Sản)  
**Ngày đánh giá:** 2025-11-09  
**Người đánh giá:** Claude AI

---

## 1. 🎯 Tổng Quan Tình Trạng Hiện Tại

### Backend (✅ 85% Hoàn thành)

**Đã có:**
- ✅ Models: `OrganizationUnit` và `Major` đã được định nghĩa đầy đủ
- ✅ Service Layer: `organization_service.py` với Redis cache, lock mechanism
- ✅ Router: Endpoints cơ bản cho CRUD operations
- ✅ Schema: Pydantic models cho validation

**Thiếu:**
- ❌ `emit_data_updated` integration trong service layer
- ❌ Admin endpoints cho CUD operations (chỉ có READ endpoints public)

### Frontend (❌ 5% Hoàn thành)

**Đã có:**
- ✅ SocketHandler infrastructure
- ✅ React Query setup
- ✅ UI component library (shadcn/ui)

**Thiếu:**
- ❌ API endpoints configuration
- ❌ React Query hooks cho organization
- ❌ UI components (dialogs, tables)
- ❌ Admin pages

---

## 2. ⚠️ Những Điểm CẦN ĐIỀU CHỈNH trong Kế Hoạch

### 2.1. Backend - Emit Data Updated (Bước 1)

**❌ Vấn đề:** Kế hoạch đề xuất import `emit_data_updated` từ `user_service`

```python
# ❌ KHÔNG ĐÚNG theo codebase hiện tại
from .user_service import emit_data_updated
```

**✅ THỰC TẾ:** Cần kiểm tra lại `user_service.py` hoặc `socket_manager.py` để xem hàm này có tồn tại không.

**🔍 Phát hiện từ codebase:**
Sau khi scan, tôi thấy codebase có `socket_manager.py` nhưng chưa thấy `emit_data_updated` được định nghĩa rõ ràng.

**💡 GIẢI PHÁP:**
```python
# app/services/organization_service.py
import structlog
from ..socket_manager import emit_to_user_room, socket_manager

log = structlog.get_logger(__name__)

async def emit_organization_updated(
    operation: str,  # "create", "update", "delete"
    resource_id: int,
    resource_name: str = None
):
    """Phát sóng cập nhật organization qua Socket.IO"""
    try:
        # Emit to all users (hoặc chỉ admin users)
        await socket_manager.emit_to_all(
            "data_updated",
            {
                "resource_type": "organization",
                "operation": operation,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    except Exception as e:
        log.error("Failed to emit organization update", error=str(e))
```

### 2.2. Backend - Admin Endpoints Thiếu

**❌ Vấn đề:** Router hiện tại (`routers/organization.py`) chỉ có:
- `GET /organization-units` (public)
- `GET /majors` (public)

**✅ CẦN BỔ SUNG:** Admin-only endpoints trong `routers/admin.py`

```python
# app/routers/admin.py (THÊM VÀO FILE HIỆN CÓ)

from ..services import organization_service

# Organization Units Management
@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    dependencies=[Depends(deps.AdminRequired)]  # ⚠️ CHÚ Ý: Dùng AdminRequired
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """Tạo đơn vị mới (Admin only)"""
    return await organization_service.create_organization_unit(db, unit_in)

@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    dependencies=[Depends(deps.AdminRequired)]
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """Cập nhật đơn vị (Admin only)"""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)

@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(deps.AdminRequired)]
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.AdminRequired,
):
    """Xóa đơn vị (Admin only)"""
    await organization_service.delete_organization_unit(db, unit_id)
    return None

# Tương tự cho Major endpoints...
```

### 2.3. Frontend - API Endpoints (Bước 2)

**⚠️ ĐIỀU CHỈNH:** Endpoints phải phân biệt rõ public vs admin

```typescript
// src/lib/api/endpoints.ts (THÊM VÀO API_ENDPOINTS)

export const API_ENDPOINTS = {
  // ... (các endpoints khác giữ nguyên)
  
  // 🆕 ORGANIZATION (Public endpoints)
  ORGANIZATION: {
    LIST_UNITS: "/api/organization-units",  // GET (public)
    GET_UNIT: (id: number) => `/api/organization-units/${id}`,  // GET (public)
    LIST_MAJORS: "/api/majors",  // GET (public, với query params)
  },
  
  ADMIN: {
    // ... (các ADMIN endpoints khác giữ nguyên)
    
    // 🆕 ORGANIZATION MANAGEMENT (Admin-only endpoints)
    ORGANIZATION: {
      CREATE_UNIT: "/api/admin/organization-units",  // POST
      UPDATE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,  // PUT
      DELETE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,  // DELETE
      
      CREATE_MAJOR: "/api/admin/majors",  // POST
      UPDATE_MAJOR: (id: number) => `/api/admin/majors/${id}`,  // PUT
      DELETE_MAJOR: (id: number) => `/api/admin/majors/${id}`,  // DELETE
    },
  },
} as const;
```

### 2.4. Frontend - React Query Keys (Bước 3)

**💡 CẢI TIẾN:** Cấu trúc query keys nên theo pattern của codebase hiện tại

```typescript
// src/hooks/useOrganization.ts

// ✅ PATTERN ĐÚNG theo codebase hiện tại
export const organizationKeys = {
  all: ["organization"] as const,
  lists: () => [...organizationKeys.all, "list"] as const,
  list: (filters?: string) => [...organizationKeys.lists(), { filters }] as const,
  details: () => [...organizationKeys.all, "detail"] as const,
  detail: (id: number) => [...organizationKeys.details(), id] as const,
  
  // Major keys (nested under organization)
  majors: () => [...organizationKeys.all, "majors"] as const,
  majorsList: (unitId?: number, search?: string) => 
    [...organizationKeys.majors(), { unitId, search }] as const,
};
```

### 2.5. Frontend - SocketHandler Integration (Bước 4)

**✅ KẾ HOẠCH ĐÚNG**, nhưng cần thêm chi tiết:

```typescript
// components/layouts/SocketHandler.tsx

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
      // ... (logic cũ giữ nguyên)
      break;
      
    case "organization":
      // ✅ Invalidate ALL organization queries
      queryClient.invalidateQueries({
        queryKey: organizationKeys.all  // Sẽ invalidate cả units và majors
      });
      
      // 💡 CẢI TIẾN: Chỉ show toast khi operation quan trọng
      if (data.operation !== "update" || data.resource_name) {
        toast.info(`Đơn vị đã được ${
          data.operation === "create" ? "tạo" :
          data.operation === "update" ? "cập nhật" :
          "xóa"
        }`, {
          description: data.resource_name 
            ? `${data.resource_name}` 
            : "Danh sách được làm mới tự động",
          duration: 3000,
        });
      }
      break;
      
    case "major":
      // Major changes affect organization tree
      queryClient.invalidateQueries({
        queryKey: organizationKeys.all
      });
      
      toast.info(`Ngành học đã được cập nhật`, {
        description: "Làm mới tự động",
        duration: 3000,
      });
      break;
      
    // ... (các cases khác)
  }
};
```

### 2.6. Frontend - UnitDialog Component (Bước 5)

**⚠️ VẤN ĐỀ:** Logic chọn parent_id cần xử lý đệ quy tốt hơn

```typescript
// components/admin/organization/UnitDialog.tsx

// ❌ KẾ HOẠCH THIẾU: Logic loại trừ đơn vị con cháu chưa đầy đủ
const getValidParents = (units: OrganizationUnit[], editUnitId: number | null): OrganizationUnit[] => {
  if (!editUnitId) {
    return units; // Khi tạo mới, tất cả đơn vị đều có thể là parent
  }
  
  // ✅ GIẢI PHÁP ĐẦY ĐỦ: Loại trừ đơn vị hiện tại và tất cả con cháu
  const getAllDescendantIds = (unit: OrganizationUnit, allUnits: OrganizationUnit[]): Set<number> => {
    const descendants = new Set<number>([unit.id]);
    
    const findChildren = (parentId: number) => {
      const children = allUnits.filter(u => u.parent_id === parentId);
      children.forEach(child => {
        descendants.add(child.id);
        findChildren(child.id); // Đệ quy tìm con cháu
      });
    };
    
    findChildren(unit.id);
    return descendants;
  };
  
  const editUnit = units.find(u => u.id === editUnitId);
  if (!editUnit) return units;
  
  const excludedIds = getAllDescendantIds(editUnit, units);
  return units.filter(u => !excludedIds.has(u.id));
};
```

**💡 CẢI TIẾN THÊM:** Select component nên hiển thị cấu trúc cây

```typescript
// ✅ TỐT HƠN: Hiển thị indent để thể hiện hierarchy
const renderUnitOption = (unit: OrganizationUnit, level: number = 0) => {
  const indent = "  ".repeat(level);
  return (
    <SelectItem key={unit.id} value={String(unit.id)}>
      {indent}{level > 0 && "└─ "}{unit.name} ({unit.type})
    </SelectItem>
  );
};

// Trong JSX:
<SelectContent>
  <SelectItem value="null">Không có (Root level)</SelectItem>
  {flattenUnitsWithHierarchy(parentOptions).map(({ unit, level }) => 
    renderUnitOption(unit, level)
  )}
</SelectContent>
```

### 2.7. Frontend - Admin Page (Bước 6)

**✅ CẤU TRÚC TỐT**, nhưng cần thêm features:

```typescript
// app/(dashboard)/admin/organization/page.tsx

// 💡 BỔ SUNG: Thêm search, filter, export
export default function OrganizationManagementPage() {
  const [activeTab, setActiveTab] = useState("units");
  const [searchTerm, setSearchTerm] = useState("");
  const [filterType, setFilterType] = useState<string>("all");
  
  // ✅ THÊM: Debounced search
  const debouncedSearch = useDebounce(searchTerm, 300);
  
  const { data: units, isLoading } = useOrganizationUnits();
  
  // ✅ THÊM: Client-side filtering
  const filteredUnits = useMemo(() => {
    if (!units) return [];
    
    return units.filter(unit => {
      const matchesSearch = unit.name.toLowerCase().includes(debouncedSearch.toLowerCase());
      const matchesType = filterType === "all" || unit.type === filterType;
      return matchesSearch && matchesType;
    });
  }, [units, debouncedSearch, filterType]);
  
  // ✅ THÊM: Tree view vs Flat list toggle
  const [viewMode, setViewMode] = useState<"tree" | "flat">("flat");
  
  return (
    <div className="space-y-6">
      {/* Header with actions */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Quản lý Tổ chức</h1>
          <p className="text-muted-foreground">
            Quản lý cấu trúc tổ chức: Đơn vị và Ngành học
          </p>
        </div>
        
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleExport}>
            <Download className="mr-2 h-4 w-4" />
            Xuất dữ liệu
          </Button>
          <Button onClick={() => handleOpenUnitDialog(null)}>
            <Plus className="mr-2 h-4 w-4" />
            Thêm Đơn vị
          </Button>
        </div>
      </div>
      
      {/* Filters */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-4">
            <Input
              placeholder="Tìm kiếm đơn vị..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="max-w-sm"
            />
            
            <Select value={filterType} onValueChange={setFilterType}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Loại đơn vị" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả</SelectItem>
                <SelectItem value="Khoa">Khoa</SelectItem>
                <SelectItem value="Phòng ban">Phòng ban</SelectItem>
                <SelectItem value="Trung tâm">Trung tâm</SelectItem>
              </SelectContent>
            </Select>
            
            <div className="ml-auto flex gap-2">
              <Button
                variant={viewMode === "flat" ? "default" : "outline"}
                size="sm"
                onClick={() => setViewMode("flat")}
              >
                <List className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === "tree" ? "default" : "outline"}
                size="sm"
                onClick={() => setViewMode("tree")}
              >
                <TreePine className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>
      
      {/* Main content */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        {/* ... rest of the code */}
      </Tabs>
    </div>
  );
}
```

---

## 3. 🚨 Những Thiếu Sót Quan Trọng

### 3.1. ❌ THIẾU: Error Boundary và Loading States

```typescript
// ✅ CẦN THÊM: Comprehensive error handling
export default function OrganizationManagementPage() {
  const { data: units, isLoading, error, isError } = useOrganizationUnits();
  
  // Error state
  if (isError) {
    return (
      <Card className="p-6">
        <div className="text-center">
          <AlertCircle className="mx-auto h-12 w-12 text-destructive" />
          <h3 className="mt-4 text-lg font-semibold">Không thể tải dữ liệu</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            {error?.message || "Đã xảy ra lỗi khi tải danh sách đơn vị"}
          </p>
          <Button
            className="mt-4"
            onClick={() => queryClient.invalidateQueries({ queryKey: organizationKeys.all })}
          >
            Thử lại
          </Button>
        </div>
      </Card>
    );
  }
  
  // ... rest of the component
}
```

### 3.2. ❌ THIẾU: Optimistic Updates

```typescript
// ✅ CẦN THÊM: Optimistic updates cho UX tốt hơn
export function useUpdateUnit() {
  const queryClient = useQueryClient();
  
  return useMutation<OrganizationUnit, AxiosError<ApiErrorResponse>, { id: number; data: UnitUpdate }>({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<OrganizationUnit>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_UNIT(id),
        data
      );
      return response.data;
    },
    
    // 💡 OPTIMISTIC UPDATE
    onMutate: async ({ id, data }) => {
      // Cancel ongoing queries
      await queryClient.cancelQueries({ queryKey: organizationKeys.all });
      
      // Snapshot previous value
      const previousUnits = queryClient.getQueryData<OrganizationUnit[]>(
        organizationKeys.list()
      );
      
      // Optimistically update cache
      if (previousUnits) {
        queryClient.setQueryData<OrganizationUnit[]>(
          organizationKeys.list(),
          previousUnits.map(unit => 
            unit.id === id ? { ...unit, ...data } : unit
          )
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
      toast.error("Cập nhật thất bại", {
        description: err.response?.data?.detail || "Đã xảy ra lỗi"
      });
    },
    
    // Refetch on success
    onSuccess: () => {
      toast.success("Cập nhật thành công!");
      queryClient.invalidateQueries({ queryKey: organizationKeys.all });
    },
  });
}
```

### 3.3. ❌ THIẾU: Permission Checks

```typescript
// ✅ CẦN THÊM: Permission guards
import { useAuth } from "@/hooks/useAuth";
import { hasPermission } from "@/lib/auth/permissions";

export default function OrganizationManagementPage() {
  const { user } = useAuth();
  const canManageOrganization = hasPermission(user, "admin.organization.write");
  
  if (!canManageOrganization) {
    return (
      <Card className="p-6">
        <div className="text-center">
          <ShieldAlert className="mx-auto h-12 w-12 text-warning" />
          <h3 className="mt-4 text-lg font-semibold">Không có quyền truy cập</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Bạn không có quyền quản lý cấu trúc tổ chức
          </p>
        </div>
      </Card>
    );
  }
  
  // ... rest of the component
}
```

### 3.4. ❌ THIẾU: Form Validation chi tiết

```typescript
// ✅ CẦN THÊM: Robust validation
const unitSchema = z.object({
  name: z.string()
    .min(3, "Tên phải có ít nhất 3 ký tự")
    .max(255, "Tên không được quá 255 ký tự")
    .regex(/^[a-zA-ZÀ-ỹ\s]+$/, "Tên chỉ được chứa chữ cái và khoảng trắng"),
    
  type: z.string()
    .min(1, "Loại đơn vị là bắt buộc")
    .refine(
      (val) => ["Khoa", "Viện", "Phòng ban", "Trung tâm"].includes(val),
      "Loại đơn vị không hợp lệ"
    ),
    
  parent_id: z.coerce.number()
    .optional()
    .nullable()
    .refine(
      (val) => val === null || val > 0,
      "ID đơn vị cha không hợp lệ"
    ),
    
  description: z.string()
    .max(1000, "Mô tả không được quá 1000 ký tự")
    .optional(),
});
```

### 3.5. ❌ THIẾU: Bulk Operations

```typescript
// ✅ CẦN THÊM: Bulk delete, bulk update
export function useBulkDeleteUnits() {
  const queryClient = useQueryClient();
  
  return useMutation<void, AxiosError<ApiErrorResponse>, number[]>({
    mutationFn: async (ids) => {
      await api.post(API_ENDPOINTS.ADMIN.ORGANIZATION.BULK_DELETE, { ids });
    },
    onSuccess: (_, deletedIds) => {
      toast.success(`Đã xóa ${deletedIds.length} đơn vị`);
      queryClient.invalidateQueries({ queryKey: organizationKeys.all });
    },
    onError: (error) => {
      toast.error("Xóa hàng loạt thất bại", {
        description: error.response?.data?.detail
      });
    },
  });
}

// UI Component
function BulkActions({ selectedIds }: { selectedIds: number[] }) {
  const bulkDelete = useBulkDeleteUnits();
  
  const handleBulkDelete = () => {
    if (selectedIds.length === 0) return;
    
    if (confirm(`Bạn có chắc muốn xóa ${selectedIds.length} đơn vị đã chọn?`)) {
      bulkDelete.mutate(selectedIds);
    }
  };
  
  return (
    <div className="flex gap-2">
      <Button
        variant="destructive"
        size="sm"
        disabled={selectedIds.length === 0 || bulkDelete.isPending}
        onClick={handleBulkDelete}
      >
        <Trash2 className="mr-2 h-4 w-4" />
        Xóa ({selectedIds.length})
      </Button>
    </div>
  );
}
```

### 3.6. ❌ THIẾU: Export/Import Functionality

```typescript
// ✅ CẦN THÊM: Export to Excel/CSV
export async function exportOrganizationTree() {
  try {
    const response = await api.get(
      API_ENDPOINTS.ADMIN.ORGANIZATION.EXPORT,
      { responseType: "blob" }
    );
    
    const blob = new Blob([response.data], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    });
    
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `organization_tree_${new Date().toISOString().split("T")[0]}.xlsx`;
    link.click();
    
    window.URL.revokeObjectURL(url);
    toast.success("Xuất dữ liệu thành công!");
  } catch (error) {
    toast.error("Xuất dữ liệu thất bại");
  }
}
```

---

## 4. 💡 Khuyến Nghị Bổ Sung

### 4.1. Testing Strategy

```typescript
// ✅ THÊM: Unit tests cho hooks
describe("useOrganizationUnits", () => {
  it("should fetch units successfully", async () => {
    const { result } = renderHook(() => useOrganizationUnits(), {
      wrapper: createQueryWrapper(),
    });
    
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeDefined();
  });
  
  it("should handle errors gracefully", async () => {
    // Mock API error
    server.use(
      rest.get(API_ENDPOINTS.ORGANIZATION.LIST_UNITS, (req, res, ctx) => {
        return res(ctx.status(500), ctx.json({ detail: "Server error" }));
      })
    );
    
    const { result } = renderHook(() => useOrganizationUnits(), {
      wrapper: createQueryWrapper(),
    });
    
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

### 4.2. Documentation

```markdown
# 📚 TẠO: docs/organization-management.md

## Organization Management Module

### Overview
Quản lý cấu trúc tổ chức bao gồm các đơn vị (Units) và ngành học (Majors).

### Architecture
- **Backend:** FastAPI + SQLAlchemy + Redis
- **Frontend:** Next.js + React Query + Socket.IO
- **Real-time:** Automatic sync via WebSocket

### API Endpoints

#### Public Endpoints
- `GET /api/organization-units` - Lấy danh sách đơn vị
- `GET /api/majors?unitId={id}` - Lấy danh sách ngành học

#### Admin Endpoints (requires admin role)
- `POST /api/admin/organization-units` - Tạo đơn vị mới
- `PUT /api/admin/organization-units/{id}` - Cập nhật đơn vị
- `DELETE /api/admin/organization-units/{id}` - Xóa đơn vị

### Frontend Usage

```typescript
import { useOrganizationUnits, useCreateUnit } from "@/hooks/useOrganization";

function MyComponent() {
  const { data: units, isLoading } = useOrganizationUnits();
  const createUnit = useCreateUnit();
  
  // ...
}
```

### Best Practices
1. Always check permissions before rendering admin UI
2. Use optimistic updates for better UX
3. Handle loading and error states gracefully
4. Validate form inputs on both client and server
```

### 4.3. Performance Optimization

```typescript
// ✅ THÊM: Virtualized list cho large datasets
import { useVirtualizer } from "@tanstack/react-virtual";

function OrganizationTable({ units }: { units: OrganizationUnit[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  
  const virtualizer = useVirtualizer({
    count: units.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 50, // Row height
    overscan: 5,
  });
  
  return (
    <div ref={parentRef} className="h-[600px] overflow-auto">
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: "relative",
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const unit = units[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <UnitRow unit={unit} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

### 4.4. Accessibility (a11y)

```typescript
// ✅ THÊM: ARIA labels và keyboard navigation
<Button
  onClick={() => handleOpenUnitDialog(null)}
  aria-label="Thêm đơn vị tổ chức mới"
>
  <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
  <span>Thêm Đơn vị</span>
</Button>

<Table role="table" aria-label="Danh sách đơn vị tổ chức">
  <TableHeader role="rowgroup">
    <TableRow role="row">
      <TableHead role="columnheader">Tên Đơn vị</TableHead>
      {/* ... */}
    </TableRow>
  </TableHeader>
  {/* ... */}
</Table>
```

---

## 5. 📝 Checklist Triển Khai

### Phase 1: Backend Foundation (3-4 giờ)
- [ ] Tạo hàm `emit_organization_updated` trong service
- [ ] Thêm emit calls vào tất cả CUD operations
- [ ] Tạo admin endpoints trong `routers/admin.py`
- [ ] Test endpoints với Postman/Thunder Client
- [ ] Verify Socket.IO emissions với socket client test

### Phase 2: Frontend Data Layer (2-3 giờ)
- [ ] Thêm API_ENDPOINTS configuration
- [ ] Tạo file `hooks/useOrganization.ts` với tất cả hooks
- [ ] Implement query keys theo best practices
- [ ] Add optimistic updates
- [ ] Test hooks với React Testing Library

### Phase 3: Frontend UI Components (4-5 giờ)
- [ ] Tạo `UnitDialog.tsx` với full validation
- [ ] Tạo `MajorDialog.tsx`
- [ ] Implement tree view component (optional)
- [ ] Add bulk operations UI
- [ ] Test components với Storybook

### Phase 4: Admin Page (3-4 giờ)
- [ ] Tạo `app/(dashboard)/admin/organization/page.tsx`
- [ ] Implement search, filter, sort
- [ ] Add export/import functionality
- [ ] Implement permission guards
- [ ] Polish UI/UX

### Phase 5: Integration & Testing (2-3 giờ)
- [ ] Update SocketHandler với organization handling
- [ ] End-to-end testing
- [ ] Performance testing với large datasets
- [ ] Cross-browser testing
- [ ] Mobile responsive testing

### Phase 6: Documentation (1-2 giờ)
- [ ] API documentation
- [ ] Frontend component documentation
- [ ] User guide
- [ ] Developer guide

**Tổng thời gian ước tính:** 15-21 giờ

---

## 6. 🎯 Kết Luận

### Đánh Giá Kế Hoạch Gốc: **7.5/10**

**Điểm mạnh:**
- ✅ Cấu trúc rõ ràng, dễ follow
- ✅ Phủ sóng đầy đủ các layer (backend, frontend, real-time)
- ✅ Theo đúng patterns của codebase hiện tại

**Điểm yếu:**
- ❌ Thiếu error handling và edge cases
- ❌ Chưa có optimistic updates
- ❌ Chưa xử lý permissions
- ❌ Thiếu bulk operations và export/import
- ❌ Validation chưa đủ chi tiết
- ❌ Chưa có testing strategy

### Khuyến Nghị Triển Khai

**Ưu tiên cao (Must-have):**
1. Bổ sung `emit_organization_updated` với error handling
2. Tạo admin endpoints với permission checks
3. Implement comprehensive error states
4. Add form validation đầy đủ
5. Integrate với SocketHandler

**Ưu tiên trung bình (Should-have):**
6. Optimistic updates cho UX tốt hơn
7. Bulk operations (delete, update)
8. Export/Import functionality
9. Tree view mode

**Ưu tiên thấp (Nice-to-have):**
10. Virtualized list cho performance
11. Advanced search và filtering
12. Drag-and-drop reordering
13. Comprehensive testing suite

### Rủi Ro Cần Lưu Ý

1. **Hiệu năng:** Với cây tổ chức lớn (>1000 nodes), cần implement pagination hoặc virtualization
2. **Đệ quy:** Cần validation chặt chẽ để tránh circular dependencies
3. **Cache invalidation:** Cần test kỹ để đảm bảo không bị stale data
4. **Permissions:** Phải integrate với Casbin policy hiện có

---

**Tài liệu này được tạo bởi Claude AI dựa trên phân tích chi tiết codebase QLTS.**
