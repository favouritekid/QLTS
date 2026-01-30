// src/components/admin/organization/UserAssignmentDialog.tsx
"use client";

import { useState, useMemo } from "react";
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Search,
  Loader2,
  AlertCircle,
  Users as UsersIcon,
  CheckCircle2,
} from "lucide-react";
import { useAdminUsersList, useAssignUserToUnit, useUnassignUserFromUnit } from "@/hooks/useAdminUsers";
// API_ENDPOINTS removed as it is internal to masterDataApi now
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { adminUsersKeys } from "@/hooks/useAdminUsers";
import type { User } from "@/types/api.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

// Minimal unit interface for user assignment - compatible with both
// OrganizationUnit and OrganizationTreeNodeWithAggregation
interface MinimalOrganizationUnit {
  id: number;
  name: string;
  type: string;
  parent_id: number | null;
  is_active: boolean;
}

interface UserAssignmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  unit: MinimalOrganizationUnit;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UserAssignmentDialog({
  open,
  onOpenChange,
  unit,
}: UserAssignmentDialogProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [isAssigning, setIsAssigning] = useState(false);

  const queryClient = useQueryClient();

  // Fetch all users (not filtered by unit)
  const {
    data: usersData,
    isLoading,
    error,
  } = useAdminUsersList({
    page: 1,
    page_size: 100, // Max allowed by backend
    search: searchQuery || undefined,
    status: "active", // Only active users
  });

  const users = useMemo(() => usersData?.users || [], [usersData?.users]);

  // Filter users by search and categorize them
  const { currentUsers, availableUsers } = useMemo(() => {
    const current: User[] = [];
    const available: User[] = [];

    users.forEach((user) => {
      if (user.unit_id === unit.id) {
        current.push(user);
      } else {
        available.push(user);
      }
    });

    return { currentUsers: current, availableUsers: available };
  }, [users, unit.id]);

  // Initialize selected users when opening dialog
  const handleOpenChange = (newOpen: boolean) => {
    if (newOpen) {
      // Pre-select users already in this unit
      setSelectedUserIds(new Set(currentUsers.map((u) => u.id)));
    } else {
      // Clear selections when closing
      setSelectedUserIds(new Set());
      setSearchQuery("");
    }
    onOpenChange(newOpen);
  };

  // Toggle user selection
  const handleToggleUser = (userId: number) => {
    setSelectedUserIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(userId)) {
        newSet.delete(userId);
      } else {
        newSet.add(userId);
      }
      return newSet;
    });
  };

  const { mutateAsync: assignUser } = useAssignUserToUnit();
  const { mutateAsync: unassignUser } = useUnassignUserFromUnit();

  // Handle save - assign/unassign users
  const handleSave = async () => {
    setIsAssigning(true);

    try {
      // Determine which users to assign and which to unassign
      const currentUserIds = new Set(currentUsers.map((u) => u.id));
      const toAssign: number[] = [];
      const toUnassign: number[] = [];

      // Check all users
      users.forEach((user) => {
        const isCurrentlyInUnit = currentUserIds.has(user.id);
        const isSelected = selectedUserIds.has(user.id);

        if (isSelected && !isCurrentlyInUnit) {
          // User is selected but not in unit → assign
          toAssign.push(user.id);
        } else if (!isSelected && isCurrentlyInUnit) {
          // User is in unit but not selected → unassign
          toUnassign.push(user.id);
        }
      });

      // Perform updates using hooks
      const updatePromises: Promise<unknown>[] = [];

      // Assign users to this unit
      toAssign.forEach((userId) => {
        updatePromises.push(assignUser({ userId, unitId: unit.id }));
      });

      // Unassign users from this unit
      toUnassign.forEach((userId) => {
        updatePromises.push(unassignUser({ userId, unitId: unit.id }));
      });

      await Promise.all(updatePromises);

      // Invalidate user queries to refresh data
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });

      // Show success message
      toast.success(`Đã cập nhật ${toAssign.length + toUnassign.length} người dùng`);

      // Close dialog on success
      onOpenChange(false);
    } catch (error) {
      console.error("Failed to update user assignments:", error);
      toast.error("Không thể cập nhật người dùng. Vui lòng thử lại.");
    } finally {
      setIsAssigning(false);
    }
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

  // Render user row
  const renderUserRow = (user: User, isCurrentlyInUnit: boolean) => {
    const isSelected = selectedUserIds.has(user.id);

    return (
      <div
        key={user.id}
        className="flex items-center gap-3 p-3 rounded-lg hover:bg-accent/50 cursor-pointer"
        onClick={() => handleToggleUser(user.id)}
      >
        <Checkbox
          checked={isSelected}
          onCheckedChange={() => handleToggleUser(user.id)}
        />
        <Avatar className="h-8 w-8">
          <AvatarImage src={user.avatar_url || undefined} />
          <AvatarFallback className="text-xs">
            {getUserInitials(user.full_name)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{user.full_name}</div>
          <div className="text-xs text-muted-foreground truncate">
            {user.email}
          </div>
        </div>
        {isCurrentlyInUnit && (
          <Badge variant="default" className="text-xs">
            <CheckCircle2 className="h-3 w-3 mr-1" />
            Đã thuộc đơn vị
          </Badge>
        )}
        <Badge variant="secondary" className="text-xs">
          {user.role} {/* architecture-allow presentation */}
        </Badge>
      </div>
    );
  };

  return (
    <ResponsiveDialog open={open} onOpenChange={handleOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[600px] h-[80vh] flex flex-col">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle>Quản lý người dùng</ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Chọn người dùng để thêm vào đơn vị &quot;{unit.name}&quot;
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

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

        {/* User List */}
        <ScrollArea className="flex-1 -mx-6 px-6">
          {/* Error State */}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Không thể tải danh sách người dùng. Vui lòng thử lại sau.
              </AlertDescription>
            </Alert>
          )}

          {/* Loading State */}
          {isLoading && (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex items-center gap-3 p-3">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-8 w-8 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-48" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Empty State */}
          {!isLoading && !error && users.length === 0 && (
            <div className="py-12 text-center">
              <UsersIcon className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
              <h4 className="text-sm font-medium mb-2">
                {searchQuery
                  ? "Không tìm thấy người dùng"
                  : "Không có người dùng"}
              </h4>
              <p className="text-xs text-muted-foreground">
                {searchQuery
                  ? "Thử tìm kiếm với từ khóa khác"
                  : "Chưa có người dùng trong hệ thống"}
              </p>
            </div>
          )}

          {/* User List */}
          {!isLoading && !error && users.length > 0 && (
            <div className="space-y-6">
              {/* Current Users Section */}
              {currentUsers.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-3 text-muted-foreground">
                    Đang thuộc đơn vị này ({currentUsers.length})
                  </h4>
                  <div className="space-y-1">
                    {currentUsers.map((user) => renderUserRow(user, true))}
                  </div>
                </div>
              )}

              {/* Available Users Section */}
              {availableUsers.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-3 text-muted-foreground">
                    Người dùng khác ({availableUsers.length})
                  </h4>
                  <div className="space-y-1">
                    {availableUsers.map((user) => renderUserRow(user, false))}
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* Footer */}
        <ResponsiveDialogFooter className="flex items-center justify-between sm:justify-between">
          <div className="text-sm text-muted-foreground">
            {selectedUserIds.size} người dùng đã chọn
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isAssigning}
            >
              Hủy
            </Button>
            <Button onClick={handleSave} disabled={isAssigning}>
              {isAssigning && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Lưu thay đổi
            </Button>
          </div>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  );
}
