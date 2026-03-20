// src/components/admin/organization/UserAssignmentDialog.tsx
"use client";

import { useState, useMemo, useEffect } from "react";
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
  UserMinus,
  Undo2,
} from "lucide-react";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { masterDataApi } from "@/lib/api/master-data";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { adminUsersKeys } from "@/hooks/useAdminUsers";
import { organizationKeys } from "@/hooks/useOrganization";
import { getAvatarUrl } from "@/lib/utils";
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
  const [debouncedSearch, setDebouncedSearch] = useState("");
  // Users selected to ADD to this unit (from available list)
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  // Users marked to REMOVE from this unit (from current list)
  const [removedUserIds, setRemovedUserIds] = useState<Set<number>>(new Set());
  const [isAssigning, setIsAssigning] = useState(false);

  const queryClient = useQueryClient();

  // Debounce search query (300ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Fetch all users (not filtered by unit)
  const {
    data: usersData,
    isLoading,
    error,
  } = useAdminUsersList({
    page: 1,
    page_size: 100,
    search: debouncedSearch || undefined,
    status: "active",
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

  // Reset state when dialog opens/closes
  const handleOpenChange = (newOpen: boolean) => {
    if (newOpen) {
      setSelectedUserIds(new Set());
      setRemovedUserIds(new Set());
    } else {
      setSelectedUserIds(new Set());
      setRemovedUserIds(new Set());
      setSearchQuery("");
    }
    onOpenChange(newOpen);
  };

  // Toggle selection for available users (to add)
  const handleToggleAvailable = (userId: number) => {
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

  // Toggle removal for current users
  const handleToggleRemove = (userId: number) => {
    setRemovedUserIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(userId)) {
        newSet.delete(userId);
      } else {
        newSet.add(userId);
      }
      return newSet;
    });
  };

  // Handle save - assign/unassign users
  const handleSave = async () => {
    const toAssign = Array.from(selectedUserIds);
    const toUnassign = Array.from(removedUserIds);

    if (toAssign.length === 0 && toUnassign.length === 0) {
      handleOpenChange(false);
      return;
    }

    setIsAssigning(true);

    try {
      const updatePromises: Promise<unknown>[] = [];

      toAssign.forEach((userId) => {
        updatePromises.push(masterDataApi.assignUserToUnit(userId, unit.id));
      });

      toUnassign.forEach((userId) => {
        updatePromises.push(masterDataApi.unassignUserFromUnit(userId, unit.id));
      });

      const results = await Promise.allSettled(updatePromises);

      const failures = results.filter((r) => r.status === "rejected").length;
      const successes = results.length - failures;

      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.all });

      if (failures === 0) {
        toast.success(`Đã cập nhật ${successes} người dùng`);
        handleOpenChange(false);
      } else if (successes > 0) {
        toast.warning(`Cập nhật ${successes}/${results.length} người dùng. ${failures} thất bại.`);
      } else {
        toast.error("Không thể cập nhật người dùng. Vui lòng thử lại.");
      }
    } catch {
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

  // Render current user row (read-only, with remove action)
  const renderCurrentUserRow = (user: User) => {
    const isMarkedForRemoval = removedUserIds.has(user.id);

    return (
      <div
        key={user.id}
        className={`flex items-center gap-3 p-3 rounded-lg ${isMarkedForRemoval ? "opacity-50 bg-destructive/5" : "hover:bg-accent/50"}`}
      >
        <Avatar className="h-8 w-8">
          <AvatarImage src={getAvatarUrl(user.avatar_url) || undefined} />
          <AvatarFallback className="text-xs">
            {getUserInitials(user.full_name)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className={`font-medium text-sm truncate ${isMarkedForRemoval ? "line-through" : ""}`}>
            {user.full_name || user.username}
          </div>
          <div className="text-xs text-muted-foreground truncate">
            {user.email}
          </div>
        </div>
        <Badge variant="secondary" className="text-xs shrink-0">
          {user.role}
        </Badge>
        <Button
          variant={isMarkedForRemoval ? "outline" : "ghost"}
          size="sm"
          className={`h-7 text-xs shrink-0 ${!isMarkedForRemoval ? "text-destructive hover:text-destructive hover:bg-destructive/10" : ""}`}
          onClick={() => handleToggleRemove(user.id)}
        >
          {isMarkedForRemoval ? (
            <><Undo2 className="h-3 w-3 mr-1" /> Hoàn tác</>
          ) : (
            <><UserMinus className="h-3 w-3 mr-1" /> Gỡ</>
          )}
        </Button>
      </div>
    );
  };

  // Render available user row (selectable checkbox)
  const renderAvailableUserRow = (user: User) => {
    const isSelected = selectedUserIds.has(user.id);

    return (
      <div
        key={user.id}
        className="flex items-center gap-3 p-3 rounded-lg hover:bg-accent/50 cursor-pointer"
        onClick={() => handleToggleAvailable(user.id)}
      >
        <Checkbox
          checked={isSelected}
          onCheckedChange={() => handleToggleAvailable(user.id)}
        />
        <Avatar className="h-8 w-8">
          <AvatarImage src={getAvatarUrl(user.avatar_url) || undefined} />
          <AvatarFallback className="text-xs">
            {getUserInitials(user.full_name)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{user.full_name || user.username}</div>
          <div className="text-xs text-muted-foreground truncate">
            {user.email}
          </div>
        </div>
        <Badge variant="secondary" className="text-xs shrink-0">
          {user.role}
        </Badge>
      </div>
    );
  };

  const hasChanges = selectedUserIds.size > 0 || removedUserIds.size > 0;

  return (
    <ResponsiveDialog open={open} onOpenChange={handleOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[600px] h-[80vh] flex flex-col">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle>Quản lý người dùng</ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Thêm hoặc gỡ người dùng khỏi đơn vị &quot;{unit.name}&quot;
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
              {/* Current Users Section (read-only with remove action) */}
              {currentUsers.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-3 text-muted-foreground">
                    Đang thuộc đơn vị này ({currentUsers.length})
                  </h4>
                  <div className="space-y-1">
                    {currentUsers.map((user) => renderCurrentUserRow(user))}
                  </div>
                </div>
              )}

              {/* Available Users Section (selectable) */}
              {availableUsers.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-3 text-muted-foreground">
                    Người dùng khác ({availableUsers.length})
                  </h4>
                  <div className="space-y-1">
                    {availableUsers.map((user) => renderAvailableUserRow(user))}
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* Footer */}
        <ResponsiveDialogFooter className="flex items-center justify-between sm:justify-between">
          <div className="text-sm text-muted-foreground">
            {selectedUserIds.size > 0 && (
              <span className="text-primary">{selectedUserIds.size} thêm</span>
            )}
            {selectedUserIds.size > 0 && removedUserIds.size > 0 && (
              <span> · </span>
            )}
            {removedUserIds.size > 0 && (
              <span className="text-destructive">{removedUserIds.size} gỡ</span>
            )}
            {!hasChanges && "Chưa có thay đổi"}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isAssigning}
            >
              Hủy
            </Button>
            <Button onClick={handleSave} disabled={isAssigning || !hasChanges}>
              {isAssigning && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Lưu thay đổi
            </Button>
          </div>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  );
}
