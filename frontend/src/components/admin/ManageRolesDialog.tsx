"use client";

import { useState, useEffect, useMemo } from "react";
import { Check, X, Plus, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAdminAssignRole, useAdminRemoveRole, useAdminUserRoles } from "@/hooks/useAdminUsers";
import { useRoles } from "@/hooks/usePolicies";
import type { User } from "@/types/api.types";

interface ManageRolesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: User;
}

/**
 * Capitalize first letter for display (e.g., "admin" -> "Admin")
 */
function capitalizeRole(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function ManageRolesDialog({ open, onOpenChange, user }: ManageRolesDialogProps) {
  const [selectedRole, setSelectedRole] = useState<string>("");
  const [roleToRemove, setRoleToRemove] = useState<string | null>(null);

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setSelectedRole("");
    }
    onOpenChange(newOpen);
  };

  const assignRoleMutation = useAdminAssignRole();
  const removeRoleMutation = useAdminRemoveRole();

  // Fetch available roles from Casbin
  const { data: rolesData, isLoading: isLoadingAvailableRoles } = useRoles();

  // Fetch user roles from API
  const { data: userRoles, isLoading: isLoadingRoles, error: rolesError, refetch } = useAdminUserRoles(user.id);

  // Build available roles from Casbin API
  const AVAILABLE_ROLES = useMemo(() => {
    if (!rolesData?.roles) return [];
    return rolesData.roles.map(role => ({
      value: role.name, // Already has "role:" prefix
      label: capitalizeRole(role.name.replace(/^role:/, '')), // Strip prefix for display
    }));
  }, [rolesData]);

  // Refetch roles when dialog opens
  useEffect(() => {
    if (open) {
      refetch();
    }
  }, [open, refetch]);

  const isPending = assignRoleMutation.isPending || removeRoleMutation.isPending;
  const isLoading = isLoadingRoles || isLoadingAvailableRoles;

  // Primary role from user object — defensive: handle both "admin" and "role:admin"
  const primaryRole = user.role.startsWith("role:") ? user.role : `role:${user.role}`;

  // Additional roles are all roles except the primary role
  const additionalRoles = userRoles?.filter(role => role !== primaryRole) || [];

  async function handleAssignRole() {
    if (!selectedRole) return;

    try {
      await assignRoleMutation.mutateAsync({
        user_id: user.id,
        role: selectedRole,
      });
      setSelectedRole("");
    } catch {
      // Error handling is done in the mutation hook
    }
  }

  async function handleRemoveRole(role: string) {
    try {
      await removeRoleMutation.mutateAsync({
        user_id: user.id,
        role: role,
      });
    } catch {
      // Error handling is done in the mutation hook
    }
  }

  // Get roles that can be assigned (not already assigned)
  const assignableRoles = AVAILABLE_ROLES.filter(
    (r) => r.value !== primaryRole && !additionalRoles.includes(r.value)
  );

  return (
    <>
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>Quản lý vai trò</DialogTitle>
          <DialogDescription>
            Quản lý vai trò bổ sung cho <span className="font-semibold">{user.username}</span>. Vai trò chính được đặt trong hồ sơ người dùng.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Primary Role (Read-only) */}
          <div>
            <h4 className="text-sm font-medium mb-3">Vai trò chính</h4>
            <div className="flex items-center gap-2">
              <Badge variant="default" className="text-sm">
                {user.role.toUpperCase()} {/* architecture-allow presentation */}
              </Badge>
              <span className="text-xs text-muted-foreground">(Được đặt trong hồ sơ người dùng)</span>
            </div>
          </div>

          {/* Additional Roles */}
          <div>
            <h4 className="text-sm font-medium mb-3">Vai trò bổ sung</h4>

            {rolesError ? (
              <div className="text-sm text-destructive mb-4 p-3 rounded-lg border border-destructive/50 bg-destructive/10">
                Không thể tải vai trò người dùng. Vui lòng thử lại.
              </div>
            ) : isLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : additionalRoles.length > 0 ? (
              <div className="space-y-2 mb-4">
                {additionalRoles.map((role) => {
                  const roleLabel = AVAILABLE_ROLES.find((r) => r.value === role)?.label || role;
                  return (
                    <div
                      key={role}
                      className="flex items-center justify-between p-3 rounded-lg border bg-muted/50"
                    >
                      <div className="flex items-center gap-2">
                        <Check className="h-4 w-4 text-success-600" />
                        <span className="text-sm font-medium">{roleLabel}</span>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setRoleToRemove(role)}
                        disabled={isPending}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground mb-4">
                Chưa có vai trò bổ sung. Thêm vai trò bên dưới.
              </p>
            )}

            {/* Assign New Role */}
            {assignableRoles.length > 0 && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <Select value={selectedRole} onValueChange={setSelectedRole}>
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Chọn vai trò để gán" />
                    </SelectTrigger>
                    <SelectContent>
                      {assignableRoles.map((role) => (
                        <SelectItem key={role.value} value={role.value}>
                          {role.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="icon"
                    onClick={handleAssignRole}
                    disabled={!selectedRole || isPending}
                    aria-label="Thêm vai trò"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* Info Box */}
          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="text-xs text-muted-foreground">
              <strong>Lưu ý:</strong> Vai trò bổ sung cung cấp thêm quyền ngoài vai trò chính. Thay đổi có hiệu lực ngay.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={isPending}
          >
            Đóng
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

      {/* Confirm role removal */}
      <AlertDialog open={!!roleToRemove} onOpenChange={(open) => !open && setRoleToRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa vai trò</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa vai trò{" "}
              <span className="font-semibold">
                {roleToRemove ? capitalizeRole(roleToRemove.replace(/^role:/, "")) : ""}
              </span>{" "}
              khỏi người dùng <span className="font-semibold">{user.username}</span>?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (roleToRemove) {
                  handleRemoveRole(roleToRemove);
                  setRoleToRemove(null);
                }
              }}
            >
              Xóa vai trò
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
