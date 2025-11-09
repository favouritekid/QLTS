# 🚀 Hướng Dẫn Implementation - Phần 2

**Tiếp theo từ Phase 3...**

---

## Phase 4: Admin Page (⏱️ 3-4 giờ)

### Bước 4.1: Tạo Admin Organization Page

**File:** `frontend/src/app/(dashboard)/admin/organization/page.tsx` (TẠO MỚI)

```typescript
// app/(dashboard)/admin/organization/page.tsx
"use client";

import { useState, useMemo } from "react";
import {
  Building2,
  Plus,
  Edit,
  Trash2,
  GraduationCap,
  Download,
  Upload,
  Search,
  Filter,
  MoreHorizontal,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import {
  useOrganizationUnits,
  useDeleteUnit,
  useMajors,
  useDeleteMajor,
  flattenOrganizationTree,
} from "@/hooks/useOrganization";
import type { OrganizationUnit, Major } from "@/types/organization.types";
import { UnitDialog } from "@/components/admin/organization/UnitDialog";
import { MajorDialog } from "@/components/admin/organization/MajorDialog";
import { useAuth } from "@/hooks/useAuth";

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export default function OrganizationManagementPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("units");
  
  // Dialog states
  const [isUnitDialogOpen, setIsUnitDialogOpen] = useState(false);
  const [selectedUnit, setSelectedUnit] = useState<OrganizationUnit | null>(null);
  const [isMajorDialogOpen, setIsMajorDialogOpen] = useState(false);
  const [selectedMajor, setSelectedMajor] = useState<Major | null>(null);
  
  // Delete confirmation states
  const [deleteUnitId, setDeleteUnitId] = useState<number | null>(null);
  const [deleteMajorId, setDeleteMajorId] = useState<number | null>(null);
  
  // Filter states
  const [searchTerm, setSearchTerm] = useState("");
  const [filterType, setFilterType] = useState<string>("all");
  const [selectedUnitForMajors, setSelectedUnitForMajors] = useState<number>(0);
  
  // Queries
  const { data: units, isLoading: isLoadingUnits, error: unitsError } = useOrganizationUnits();
  const { data: majors, isLoading: isLoadingMajors } = useMajors(
    selectedUnitForMajors || undefined
  );
  
  // Mutations
  const deleteUnitMutation = useDeleteUnit();
  const deleteMajorMutation = useDeleteMajor();
  
  // Check permissions
  const canManageOrganization = user?.role === "admin" || user?.role === "super_admin";

  // ===================================================================
  // HANDLERS
  // ===================================================================

  const handleOpenUnitDialog = (unit: OrganizationUnit | null = null) => {
    setSelectedUnit(unit);
    setIsUnitDialogOpen(true);
  };

  const handleOpenMajorDialog = (major: Major | null = null) => {
    setSelectedMajor(major);
    setIsMajorDialogOpen(true);
  };

  const handleDeleteUnit = async () => {
    if (deleteUnitId) {
      await deleteUnitMutation.mutateAsync(deleteUnitId);
      setDeleteUnitId(null);
    }
  };

  const handleDeleteMajor = async () => {
    if (deleteMajorId) {
      await deleteMajorMutation.mutateAsync(deleteMajorId);
      setDeleteMajorId(null);
    }
  };

  // ===================================================================
  // COMPUTED VALUES
  // ===================================================================

  // Filtered and flattened units
  const filteredUnits = useMemo(() => {
    if (!units) return [];
    
    // Flatten the tree
    const flattened = flattenOrganizationTree(units);
    
    // Apply filters
    return flattened.filter(({ unit }) => {
      const matchesSearch = unit.name
        .toLowerCase()
        .includes(searchTerm.toLowerCase());
      const matchesType = filterType === "all" || unit.type === filterType;
      return matchesSearch && matchesType;
    });
  }, [units, searchTerm, filterType]);

  // Get unique unit types for filter
  const unitTypes = useMemo(() => {
    if (!units) return [];
    const types = new Set<string>();
    const collectTypes = (units: OrganizationUnit[]) => {
      units.forEach(unit => {
        types.add(unit.type);
        if (unit.children) collectTypes(unit.children);
      });
    };
    collectTypes(units);
    return Array.from(types).sort();
  }, [units]);

  // ===================================================================
  // PERMISSION CHECK
  // ===================================================================

  if (!canManageOrganization) {
    return (
      <div className="space-y-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Không có quyền truy cập</AlertTitle>
          <AlertDescription>
            Bạn không có quyền quản lý cấu trúc tổ chức. Vui lòng liên hệ quản trị viên.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  // ===================================================================
  // RENDER
  // ===================================================================

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Quản lý Tổ chức</h1>
        <p className="text-muted-foreground">
          Quản lý cấu trúc tổ chức: Đơn vị và Ngành học
        </p>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-2 max-w-[400px]">
          <TabsTrigger value="units">
            <Building2 className="mr-2 h-4 w-4" />
            Đơn vị
          </TabsTrigger>
          <TabsTrigger value="majors">
            <GraduationCap className="mr-2 h-4 w-4" />
            Ngành học
          </TabsTrigger>
        </TabsList>

        {/* ============================================================= */}
        {/* TAB 1: UNITS MANAGEMENT */}
        {/* ============================================================= */}
        <TabsContent value="units" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <CardTitle>Danh sách Đơn vị</CardTitle>
                  <CardDescription>
                    Quản lý các đơn vị trong cấu trúc tổ chức
                  </CardDescription>
                </div>
                <Button onClick={() => handleOpenUnitDialog(null)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Thêm Đơn vị
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Filters */}
              <div className="flex flex-col sm:flex-row gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Tìm kiếm đơn vị..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="pl-8"
                  />
                </div>
                <Select value={filterType} onValueChange={setFilterType}>
                  <SelectTrigger className="w-full sm:w-[180px]">
                    <Filter className="mr-2 h-4 w-4" />
                    <SelectValue placeholder="Lọc theo loại" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả</SelectItem>
                    {unitTypes.map(type => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Error State */}
              {unitsError && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Lỗi</AlertTitle>
                  <AlertDescription>
                    Không thể tải danh sách đơn vị. Vui lòng thử lại sau.
                  </AlertDescription>
                </Alert>
              )}

              {/* Table */}
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tên Đơn vị</TableHead>
                      <TableHead>Loại</TableHead>
                      <TableHead>Đơn vị cha</TableHead>
                      <TableHead className="text-right">Hành động</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {isLoadingUnits ? (
                      // Loading state
                      Array.from({ length: 5 }).map((_, i) => (
                        <TableRow key={i}>
                          <TableCell colSpan={4}>
                            <Skeleton className="h-8 w-full" />
                          </TableCell>
                        </TableRow>
                      ))
                    ) : filteredUnits.length > 0 ? (
                      // Data rows
                      filteredUnits.map(({ unit, level, hasChildren }) => {
                        const indent = "  ".repeat(level);
                        const prefix = level > 0 ? "└─ " : "";
                        
                        return (
                          <TableRow key={unit.id}>
                            <TableCell className="font-medium">
                              <div className="flex items-center gap-2">
                                <span style={{ marginLeft: `${level * 20}px` }}>
                                  {prefix}
                                  {unit.name}
                                </span>
                                {hasChildren && (
                                  <Badge variant="secondary" className="text-xs">
                                    {unit.children.length} con
                                  </Badge>
                                )}
                                {unit.majors.length > 0 && (
                                  <Badge variant="outline" className="text-xs">
                                    {unit.majors.length} ngành
                                  </Badge>
                                )}
                              </div>
                            </TableCell>
                            <TableCell>
                              <Badge variant="outline">{unit.type}</Badge>
                            </TableCell>
                            <TableCell>
                              {unit.parent_id
                                ? units?.find(u => u.id === unit.parent_id)?.name || "—"
                                : "—"}
                            </TableCell>
                            <TableCell className="text-right">
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="icon">
                                    <MoreHorizontal className="h-4 w-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuLabel>Hành động</DropdownMenuLabel>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onClick={() => handleOpenUnitDialog(unit)}
                                  >
                                    <Edit className="mr-2 h-4 w-4" />
                                    Chỉnh sửa
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onClick={() => setDeleteUnitId(unit.id)}
                                    className="text-destructive"
                                    disabled={hasChildren || unit.majors.length > 0}
                                  >
                                    <Trash2 className="mr-2 h-4 w-4" />
                                    Xóa
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </TableCell>
                          </TableRow>
                        );
                      })
                    ) : (
                      // Empty state
                      <TableRow>
                        <TableCell colSpan={4} className="h-32 text-center">
                          <div className="flex flex-col items-center gap-2 text-muted-foreground">
                            <Building2 className="h-8 w-8" />
                            <p>Chưa có đơn vị nào</p>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleOpenUnitDialog(null)}
                            >
                              <Plus className="mr-2 h-4 w-4" />
                              Tạo đơn vị đầu tiên
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============================================================= */}
        {/* TAB 2: MAJORS MANAGEMENT */}
        {/* ============================================================= */}
        <TabsContent value="majors" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <CardTitle>Danh sách Ngành học</CardTitle>
                  <CardDescription>
                    Quản lý các ngành học trong hệ thống
                  </CardDescription>
                </div>
                <Button onClick={() => handleOpenMajorDialog(null)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Thêm Ngành học
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Unit Filter */}
              <div className="flex flex-col sm:flex-row gap-2">
                <Select
                  value={selectedUnitForMajors ? String(selectedUnitForMajors) : "0"}
                  onValueChange={(value) => setSelectedUnitForMajors(parseInt(value))}
                >
                  <SelectTrigger className="w-full sm:w-[300px]">
                    <SelectValue placeholder="Chọn đơn vị để xem ngành học..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">Tất cả đơn vị</SelectItem>
                    {units && flattenOrganizationTree(units).map(({ unit, level }) => {
                      const indent = "  ".repeat(level);
                      const prefix = level > 0 ? "└─ " : "";
                      return (
                        <SelectItem key={unit.id} value={String(unit.id)}>
                          {indent}{prefix}{unit.name}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>

              {/* Info Alert */}
              {!selectedUnitForMajors && (
                <Alert>
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Chọn đơn vị</AlertTitle>
                  <AlertDescription>
                    Vui lòng chọn một đơn vị để xem danh sách ngành học
                  </AlertDescription>
                </Alert>
              )}

              {/* Table */}
              {selectedUnitForMajors > 0 && (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Tên Ngành học</TableHead>
                        <TableHead>Mã Ngành</TableHead>
                        <TableHead>Đơn vị Quản lý</TableHead>
                        <TableHead className="text-right">Hành động</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {isLoadingMajors ? (
                        // Loading state
                        Array.from({ length: 3 }).map((_, i) => (
                          <TableRow key={i}>
                            <TableCell colSpan={4}>
                              <Skeleton className="h-8 w-full" />
                            </TableCell>
                          </TableRow>
                        ))
                      ) : majors && majors.length > 0 ? (
                        // Data rows
                        majors.map(major => (
                          <TableRow key={major.id}>
                            <TableCell className="font-medium">
                              {major.name}
                            </TableCell>
                            <TableCell>
                              <Badge variant="outline">{major.code}</Badge>
                            </TableCell>
                            <TableCell>
                              {units?.find(u => u.id === major.unit_id)?.name || "—"}
                            </TableCell>
                            <TableCell className="text-right">
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="icon">
                                    <MoreHorizontal className="h-4 w-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuLabel>Hành động</DropdownMenuLabel>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onClick={() => handleOpenMajorDialog(major)}
                                  >
                                    <Edit className="mr-2 h-4 w-4" />
                                    Chỉnh sửa
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onClick={() => setDeleteMajorId(major.id)}
                                    className="text-destructive"
                                  >
                                    <Trash2 className="mr-2 h-4 w-4" />
                                    Xóa
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        // Empty state
                        <TableRow>
                          <TableCell colSpan={4} className="h-32 text-center">
                            <div className="flex flex-col items-center gap-2 text-muted-foreground">
                              <GraduationCap className="h-8 w-8" />
                              <p>Chưa có ngành học nào</p>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleOpenMajorDialog(null)}
                              >
                                <Plus className="mr-2 h-4 w-4" />
                                Tạo ngành học đầu tiên
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ============================================================= */}
      {/* DIALOGS */}
      {/* ============================================================= */}
      
      {/* Unit Dialog */}
      <UnitDialog
        open={isUnitDialogOpen}
        onOpenChange={setIsUnitDialogOpen}
        unit={selectedUnit}
        allUnits={units || []}
      />

      {/* Major Dialog */}
      <MajorDialog
        open={isMajorDialogOpen}
        onOpenChange={setIsMajorDialogOpen}
        major={selectedMajor}
        allUnits={units || []}
      />

      {/* Delete Unit Confirmation */}
      <AlertDialog
        open={!!deleteUnitId}
        onOpenChange={(open) => !open && setDeleteUnitId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa đơn vị</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa đơn vị này? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteUnit}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Major Confirmation */}
      <AlertDialog
        open={!!deleteMajorId}
        onOpenChange={(open) => !open && setDeleteMajorId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa ngành học</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa ngành học này? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteMajor}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
```

### Bước 4.2: Thêm Route vào Sidebar

**File:** `frontend/src/components/layouts/dashboard/AppSidebar.tsx` (SỬA - nếu có)

Tìm phần admin menu items và thêm:

```typescript
// components/layouts/dashboard/AppSidebar.tsx

// ... existing imports ...
import { Building2 } from "lucide-react"; // Thêm icon

// ... trong phần admin menu items ...
{
  title: "Quản lý Tổ chức",
  url: "/admin/organization",
  icon: Building2,
},
```

### ✅ Checkpoint Phase 4

- [ ] Admin page render đúng
- [ ] Tabs chuyển đổi mượt mà
- [ ] Search và filter hoạt động
- [ ] CRUD operations test thành công
- [ ] Dialogs open/close đúng
- [ ] Delete confirmations hoạt động
- [ ] UI responsive trên mobile

---

## Phase 5: Integration & Testing (⏱️ 2-3 giờ)

### Bước 5.1: End-to-End Testing Flow

```bash
# 1. Khởi động cả Backend và Frontend
# Terminal 1: Backend
cd Backend_FastAPI
python -m uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Redis (nếu chưa chạy)
redis-server
```

### Bước 5.2: Test Checklist

**🔍 Backend Tests:**

```bash
# Mở http://localhost:8000/docs

1. Login với admin account
2. Test CREATE Unit:
   POST /api/admin/organization-units
   {
     "name": "Khoa Công nghệ Thông tin",
     "type": "Khoa",
     "description": "Test description",
     "parent_id": null
   }
   ✅ Status: 201
   ✅ Response chứa ID

3. Test UPDATE Unit:
   PUT /api/admin/organization-units/{id}
   {
     "name": "Khoa CNTT (Updated)"
   }
   ✅ Status: 200
   ✅ Socket emission visible in browser console

4. Test CREATE Major:
   POST /api/admin/majors
   {
     "name": "Công nghệ Thông tin",
     "code": "IT-2024",
     "unit_id": {id_from_step_2}
   }
   ✅ Status: 201

5. Test DELETE Major:
   DELETE /api/admin/majors/{id}
   ✅ Status: 204

6. Test DELETE Unit (should fail if has children):
   DELETE /api/admin/organization-units/{id_with_children}
   ✅ Status: 400 or 409
   ✅ Error message about children

7. Test DELETE Unit (success):
   DELETE /api/admin/organization-units/{id_without_children}
   ✅ Status: 204
```

**🎨 Frontend Tests:**

```markdown
1. Navigate to /admin/organization
   ✅ Page loads without errors
   ✅ Sidebar link works

2. Test Units Tab:
   ✅ Table shows all units
   ✅ Hierarchy displayed correctly with indentation
   ✅ Search works
   ✅ Type filter works
   ✅ "Thêm Đơn vị" button opens dialog

3. Test Unit Creation:
   ✅ Dialog opens
   ✅ All fields present
   ✅ Parent selector shows hierarchy
   ✅ Form validation works
   ✅ Submit creates unit
   ✅ Toast notification shown
   ✅ Table auto-updates

4. Test Unit Update:
   ✅ Click edit on a unit
   ✅ Dialog pre-filled with data
   ✅ Change name
   ✅ Save works
   ✅ Table auto-updates

5. Test Unit Delete:
   ✅ Click delete on unit without children
   ✅ Confirmation dialog shown
   ✅ Delete works
   ✅ Table auto-updates
   ✅ Delete disabled for units with children

6. Test Majors Tab:
   ✅ Switch to Majors tab
   ✅ Unit selector shows all units
   ✅ Select a unit
   ✅ Majors table loads
   ✅ Create major works
   ✅ Edit major works
   ✅ Delete major works

7. Test Real-time Sync:
   ✅ Open two browser windows
   ✅ Login as admin in both
   ✅ Go to /admin/organization in both
   ✅ Create unit in window 1
   ✅ Window 2 shows toast and updates automatically
   ✅ Same for update and delete

8. Test Error Handling:
   ✅ Turn off backend
   ✅ Try to create unit
   ✅ Error toast shown
   ✅ Turn on backend
   ✅ Retry works

9. Test Mobile Responsive:
   ✅ Open DevTools
   ✅ Toggle device toolbar (Ctrl+Shift+M)
   ✅ Test on iPhone SE (375px)
   ✅ Test on iPad (768px)
   ✅ All buttons accessible
   ✅ Dialogs fit screen
   ✅ Table scrolls horizontally
```

### Bước 5.3: Performance Testing

```javascript
// Chạy trong browser console

// 1. Test with many units (tạo 50 units)
async function createManyUnits() {
  for (let i = 0; i < 50; i++) {
    await fetch('http://localhost:8000/api/admin/organization-units', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer YOUR_TOKEN'
      },
      body: JSON.stringify({
        name: `Test Unit ${i}`,
        type: 'Khoa',
        parent_id: null
      })
    });
  }
}

// 2. Measure render time
console.time('table-render');
// Navigate to page
console.timeEnd('table-render');
// Should be < 500ms

// 3. Test search performance
console.time('search');
// Type in search box
console.timeEnd('search');
// Should be < 100ms with debouncing
```

### Bước 5.4: Common Issues & Solutions

**Issue 1: Socket.IO not connecting**
```bash
# Check browser console
WebSocket connection failed

# Solution:
1. Check if backend is running
2. Check CORS settings in backend
3. Verify Socket.IO endpoint in frontend config
```

**Issue 2: Cache not invalidating**
```bash
# Symptom: Changes not reflected in UI

# Solution:
1. Check SocketHandler is mounted
2. Check browser console for "data_updated" events
3. Check Redis is running: redis-cli ping
4. Clear browser cache: Ctrl+Shift+R
```

**Issue 3: Circular dependency not prevented**
```bash
# Symptom: Can make unit its own parent

# Solution:
1. Check wouldCreateCircularDependency function
2. Add validation in both frontend and backend
3. Test with nested units
```

**Issue 4: Form not resetting after submit**
```bash
# Symptom: Old data shows when creating new unit

# Solution:
1. Check useEffect dependencies in dialog
2. Ensure form.reset() is called
3. Verify dialog onOpenChange handler
```

### ✅ Checkpoint Phase 5

- [ ] All backend endpoints tested
- [ ] All frontend features tested
- [ ] Real-time sync working
- [ ] Error handling working
- [ ] Mobile responsive confirmed
- [ ] Performance acceptable
- [ ] Common issues documented

---

## Phase 6: Polish & Deploy (⏱️ 1-2 giờ)

### Bước 6.1: Code Cleanup

```bash
# 1. Xóa console.log statements không cần thiết
# Search trong VS Code: Ctrl+Shift+F
# Pattern: console\.log

# 2. Format code
cd frontend
npm run format  # hoặc prettier --write "src/**/*.{ts,tsx}"

cd ../Backend_FastAPI
black .  # Format Python code

# 3. Run linters
cd frontend
npm run lint

cd ../Backend_FastAPI
flake8 app/
```

### Bước 6.2: Update Documentation

**File:** `docs/organization-management.md` (TẠO MỚI)

```markdown
# Organization Management Module

## Overview
Quản lý cấu trúc tổ chức bao gồm Đơn vị (Organization Units) và Ngành học (Majors).

## Features
- ✅ CRUD operations cho Units và Majors
- ✅ Hierarchical structure với parent-child relationships
- ✅ Real-time sync via Socket.IO
- ✅ Permission-based access (Admin only)
- ✅ Search và filter
- ✅ Validation chống circular dependencies

## Architecture

### Backend
- **Models:** `OrganizationUnit`, `Major` (SQLAlchemy)
- **Service:** `organization_service.py` (Business logic + Redis cache)
- **Router:** `routers/admin.py` (API endpoints)
- **Real-time:** Socket.IO emissions on all CUD operations

### Frontend
- **Page:** `/admin/organization`
- **Hooks:** `useOrganization.ts` (React Query)
- **Components:** `UnitDialog`, `MajorDialog`
- **Real-time:** `SocketHandler` (Auto invalidation)

## API Endpoints

### Public (Authenticated users)
```
GET /api/organization-units        # List all units (tree)
GET /api/organization-units/{id}   # Get unit details
GET /api/majors?unitId={id}        # List majors by unit
GET /api/majors/{id}               # Get major details
```

### Admin Only
```
POST   /api/admin/organization-units       # Create unit
PUT    /api/admin/organization-units/{id}  # Update unit
DELETE /api/admin/organization-units/{id}  # Delete unit

POST   /api/admin/majors                   # Create major
PUT    /api/admin/majors/{id}              # Update major
DELETE /api/admin/majors/{id}              # Delete major
```

## Usage Examples

### Frontend
```typescript
import { useOrganizationUnits, useCreateUnit } from "@/hooks/useOrganization";

function MyComponent() {
  const { data: units, isLoading } = useOrganizationUnits();
  const createUnit = useCreateUnit();
  
  const handleCreate = async () => {
    await createUnit.mutateAsync({
      name: "New Unit",
      type: "Khoa",
      parent_id: null
    });
  };
  
  // ...
}
```

### Backend
```python
from app.services import organization_service

# In your endpoint
unit = await organization_service.create_organization_unit(
    db, 
    OrganizationUnitCreate(name="Test", type="Khoa")
)
```

## Database Schema

```sql
CREATE TABLE organization_unit (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES organization_unit(id)
);

CREATE TABLE major (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    unit_id INTEGER NOT NULL REFERENCES organization_unit(id)
);
```

## Permissions Required

- **Read:** Any authenticated user
- **Create/Update/Delete:** Admin role only

## Known Limitations

1. Maximum hierarchy depth: Unlimited (but recommend max 5 levels)
2. Cannot delete units with children or majors
3. Major code cannot be changed after creation
4. Redis required for caching

## Troubleshooting

### Problem: Changes not showing in UI
**Solution:** Check Socket.IO connection in browser console

### Problem: Cannot delete unit
**Solution:** Unit has children or majors - delete them first

### Problem: Circular dependency error
**Solution:** Check parent selection logic

## Future Enhancements

- [ ] Bulk import from Excel
- [ ] Export to Excel
- [ ] Drag-and-drop reordering
- [ ] Tree view visualization
- [ ] Audit log for changes
- [ ] Unit permissions (who can manage which units)
```

### Bước 6.3: Git Commit & Push

```bash
# 1. Stage changes
git add .

# 2. Commit
git commit -m "feat: implement organization management module

- Add Organization Unit and Major CRUD endpoints
- Implement real-time sync via Socket.IO
- Create admin UI with dialogs and validation
- Add hierarchical unit structure support
- Implement Redis caching for performance
- Add comprehensive error handling
- Mobile responsive design

Closes #XXX"

# 3. Push to remote
git push origin feature/organization-management

# 4. Create Pull Request on GitHub/GitLab
```

### Bước 6.4: Deployment Checklist

```markdown
## Pre-Deployment Checklist

### Backend
- [ ] All tests passing
- [ ] Database migrations ready
- [ ] Redis configured in production
- [ ] Socket.IO CORS configured
- [ ] Environment variables set
- [ ] API documentation updated

### Frontend
- [ ] Build succeeds: `npm run build`
- [ ] No console errors in production build
- [ ] Environment variables set
- [ ] Socket.IO endpoint configured for production

### Database
- [ ] Run migrations: `alembic upgrade head`
- [ ] Verify organization_unit and major tables exist
- [ ] Check indexes created

### Testing
- [ ] Smoke test on staging
- [ ] Real-time sync tested on staging
- [ ] Mobile tested on actual devices
- [ ] Permission checks verified

### Monitoring
- [ ] Add logging for organization operations
- [ ] Set up alerts for failed operations
- [ ] Monitor Socket.IO connection health
- [ ] Track API response times
```

### Bước 6.5: Post-Deployment Verification

```bash
# 1. Health check
curl https://your-api.com/health

# 2. Test endpoint
curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://your-api.com/api/organization-units

# 3. Check logs
# Backend logs
tail -f /var/log/your-app/backend.log

# Frontend logs (browser console)
# Open https://your-app.com/admin/organization
# Check console for errors

# 4. Monitor Redis
redis-cli -h your-redis-host
> INFO stats
> KEYS org:*

# 5. Check Socket.IO
# Browser console:
socket.connected  # Should be true
```

### ✅ Final Checklist

- [ ] Code cleaned and formatted
- [ ] Documentation complete
- [ ] Git committed and pushed
- [ ] Pull request created
- [ ] Deployment checklist completed
- [ ] Post-deployment verification passed
- [ ] Team notified of new feature
- [ ] User training materials prepared (if needed)

---

## 🎉 Congratulations!

Bạn đã hoàn thành implement module Quản lý Tổ chức (Organization Management)!

### 📊 Summary

**Đã implement:**
- ✅ Backend CRUD API với Socket.IO
- ✅ Redis caching với lock mechanism
- ✅ Frontend React Query hooks
- ✅ Admin UI với dialogs
- ✅ Real-time synchronization
- ✅ Form validation
- ✅ Error handling
- ✅ Mobile responsive
- ✅ Permission checks
- ✅ Documentation

**Thời gian thực tế:** 15-21 giờ
**LOC (Lines of Code):** ~2,500 lines
**Files created/modified:** 15+ files

### 🚀 Next Steps

1. **User Training:** Tạo video tutorial cho users
2. **Monitoring:** Theo dõi usage và performance
3. **Feedback:** Thu thập feedback từ users
4. **Iterate:** Cải tiến dựa trên feedback

### 📚 Related Modules

Sau khi module này ổn định, bạn có thể tiếp tục với:
- **Asset Management:** Quản lý tài sản (sẽ reference đến Units)
- **User Management Enhancement:** Gán users vào units
- **Reporting:** Báo cáo theo units và majors

---

**Happy Coding! 🎊**
