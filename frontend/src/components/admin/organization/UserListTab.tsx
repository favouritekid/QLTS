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
} from "lucide-react";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { UserDialog } from "@/components/admin/UserDialog";
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

  // Fetch users with unit filter
  const {
    data: usersData,
    isLoading,
    error,
  } = useAdminUsersList({
    page: 1,
    page_size: 100,
    unit_id: unit.id, // Filter by current unit
    search: searchQuery || undefined,
  });

  const users = usersData?.users || [];
  const total = usersData?.total || 0;

  // Handle add user
  const handleAddUser = () => {
    setUserDialogOpen(true);
  };

  // Get user initials for avatar
  const getUserInitials = (fullName: string) => {
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
              {total} người dùng thuộc đơn vị này
            </p>
          </div>
          <Button onClick={handleAddUser}>
            <UserPlus className="h-4 w-4 mr-2" />
            Thêm người dùng
          </Button>
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
                : "Thêm người dùng vào đơn vị này"}
            </p>
            {!searchQuery && (
              <Button size="sm" onClick={handleAddUser}>
                <UserPlus className="h-4 w-4 mr-2" />
                Thêm người dùng
              </Button>
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
                      <Badge variant={getRoleBadgeVariant(user.role)}>
                        {user.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <Badge
                          variant={user.is_active ? "default" : "secondary"}
                          className="text-xs w-fit"
                        >
                          {user.is_active ? "Hoạt động" : "Không hoạt động"}
                        </Badge>
                        {user.is_email_verified && (
                          <Badge variant="outline" className="text-xs w-fit">
                            ✓ Email
                          </Badge>
                        )}
                      </div>
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
        preselectedUnitId={unit.id}
      />
    </div>
  );
}
