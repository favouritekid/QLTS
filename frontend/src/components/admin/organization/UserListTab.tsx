// src/components/admin/organization/UserListTab.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Users,
  Search,
  Mail,
  Phone,
  AlertCircle,
  UserPlus,
  Link as LinkIcon,
} from "lucide-react";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { UserDialog } from "@/components/admin/UserDialog";
import { UserAssignmentDialog } from "./UserAssignmentDialog";
import type { OrganizationUnit } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UserListTabProps {
  unit: OrganizationUnit;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UserListTab({ unit }: UserListTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);

  // Check if unit has children (for hierarchical filtering)
  const hasChildren = unit.children && unit.children.length > 0;

  // Fetch users with unit filter
  // ✅ Hierarchical Filter: If unit has children, include users from all descendant units
  const {
    data: usersData,
    isLoading,
    error,
  } = useAdminUsersList({
    page: 1,
    page_size: 100,
    unit_id: unit.id,
    include_children: hasChildren, // Enable hierarchical filter for parent units
    search: searchQuery || undefined,
  });

  const users = usersData?.users || [];
  const total = usersData?.total_count || 0;

  // Handle add user
  const handleAddUser = () => {
    setUserDialogOpen(true);
  };

  // Handle assign users
  const handleAssignUser = () => {
    setAssignDialogOpen(true);
  };

  // Get user initials for avatar
  const getUserInitials = (fullName: string | null | undefined) => {
    if (!fullName) return "??";
    const words = fullName.trim().split(/\s+/);
    if (words.length >= 2) {
      return (words[0][0] + words[words.length - 1][0]).toUpperCase();
    }
    return fullName.substring(0, 2).toUpperCase();
  };

  // Role badge variant
  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case "admin":
        return "destructive";
      case "manager":
        return "default";
      default:
        return "secondary";
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Người dùng</h3>
            <p className="text-sm text-muted-foreground">
              {total} người dùng {hasChildren
                ? "thuộc đơn vị này và các đơn vị con"
                : "thuộc đơn vị này"}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleAssignUser}>
              <LinkIcon className="h-4 w-4 mr-2" />
              Gán nhân sự
            </Button>
            <Button onClick={handleAddUser}>
              <UserPlus className="h-4 w-4 mr-2" />
              Tạo mới
            </Button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm kiếm theo tên, email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Users Table */}
      <ScrollArea className="flex-1">
        {/* Error State */}
        {error && (
          <div className="p-6">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Không thể tải danh sách người dùng. Vui lòng thử lại sau.
              </AlertDescription>
            </Alert>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !error && users.length === 0 && (
          <div className="p-12 text-center">
            <Users className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
            <h4 className="text-lg font-medium mb-2">
              {searchQuery
                ? "Không tìm thấy người dùng"
                : "Chưa có người dùng"}
            </h4>
            <p className="text-sm text-muted-foreground mb-4">
              {searchQuery
                ? "Thử tìm kiếm với từ khóa khác"
                : "Thêm hoặc gán người dùng vào đơn vị này"}
            </p>
            {!searchQuery && (
              <div className="flex justify-center gap-2">
                <Button variant="outline" size="sm" onClick={handleAssignUser}>
                  <LinkIcon className="h-4 w-4 mr-2" />
                  Gán nhân sự
                </Button>
                <Button size="sm" onClick={handleAddUser}>
                  <UserPlus className="h-4 w-4 mr-2" />
                  Tạo người dùng
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Data Table */}
        {!isLoading && !error && users.length > 0 && (
          <div className="px-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[250px]">Người dùng</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead className="w-[150px]">Số điện thoại</TableHead>
                  <TableHead className="w-[120px]">Vai trò</TableHead>
                  <TableHead className="w-[150px]">Trạng thái</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar className="h-8 w-8">
                          <AvatarImage src={user.avatar_url || undefined} />
                          <AvatarFallback className="text-xs">
                            {getUserInitials(user.full_name)}
                          </AvatarFallback>
                        </Avatar>
                        <div>
                          <div className="font-medium">{user.full_name}</div>
                          <div className="text-xs text-muted-foreground">
                            @{user.username}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-sm">
                        {user.email ? (
                          <>
                            <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                            <span>{user.email}</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-sm">
                        {user.phone_number ? (
                          <>
                            <Phone className="h-3.5 w-3.5 text-muted-foreground" />
                            <span>{user.phone_number}</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={getRoleBadgeVariant(user.role)}> {/* architecture-allow presentation */}
                        {user.role} {/* architecture-allow presentation */}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={user.status === "active" ? "default" : "secondary"}
                        className="text-xs w-fit"
                      >
                        {user.status === "active" ? "Hoạt động" : user.status === "banned" ? "Đã cấm" : "Chờ xử lý"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Loading State (inside table for consistency) */}
        {isLoading && (
          <div className="px-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[250px]">Người dùng</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead className="w-[150px]">Số điện thoại</TableHead>
                  <TableHead className="w-[120px]">Vai trò</TableHead>
                  <TableHead className="w-[150px]">Trạng thái</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[1, 2, 3, 4].map((i) => (
                  <TableRow key={i}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Skeleton className="h-8 w-8 rounded-full" />
                        <div className="space-y-2">
                          <Skeleton className="h-4 w-32" />
                          <Skeleton className="h-3 w-24" />
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-4 w-40" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-4 w-28" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-5 w-16" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-5 w-20" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </ScrollArea>

      {/* User Dialog */}
      <UserDialog
        open={userDialogOpen}
        onOpenChange={setUserDialogOpen}
        user={null}
        mode="create"
      />

      {/* User Assignment Dialog */}
      <UserAssignmentDialog
        open={assignDialogOpen}
        onOpenChange={setAssignDialogOpen}
        unit={unit}
      />
    </div>
  );
}
