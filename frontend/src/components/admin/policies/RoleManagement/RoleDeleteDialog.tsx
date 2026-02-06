// src/components/admin/policies/RoleManagement/RoleDeleteDialog.tsx
"use client";

import { AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import { RoleDeleteDialogProps } from "./types";

/**
 * RoleDeleteDialog - Confirmation dialog for role deletion
 *
 * Features:
 * - Shows affected users (if any)
 * - Displays policy count to be deleted
 * - Force delete checkbox for roles with assigned users
 * - Warning for single-role vs multi-role users
 */
export function RoleDeleteDialog({
  open,
  onOpenChange,
  selectedRole,
  selectedRoleDisplayName,
  usersWithRole,
  loadingUsers,
  forceDelete,
  onForceDeleteChange,
  onDeleteRole,
  isDeletingRole,
  policies,
}: RoleDeleteDialogProps) {
  const policyCount = policies?.filter(p => p.subject === selectedRole).length || 0;
  const userCount = usersWithRole.length;
  const multiRoleCount = usersWithRole.filter(
    (u) => u.casbin_roles && u.casbin_roles.length > 1
  ).length;
  const singleRoleCount = userCount - multiRoleCount;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            Xác Nhận Xóa Vai trò
          </DialogTitle>
          <DialogDescription>
            Bạn có chắc chắn muốn xóa vai trò <strong>&quot;{selectedRoleDisplayName}&quot;</strong>?
            Hành động này không thể hoàn tác.
          </DialogDescription>
        </DialogHeader>

        {loadingUsers ? (
          <div className="py-4">
            <Skeleton className="h-20 w-full" />
          </div>
        ) : (
          <>
            {/* User count warning */}
            {userCount > 0 && (
              <>
                <Alert variant="destructive" className="my-4">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>
                    <strong>⚠️ Cảnh báo:</strong> Có <strong>{userCount} user(s)</strong> đang được gán vai trò này.
                    <div className="mt-2 space-y-1">
                      {multiRoleCount > 0 && (
                        <div className="text-sm">
                          • <strong>{multiRoleCount} user(s)</strong> có nhiều vai trò → sẽ giữ lại các vai trò khác
                        </div>
                      )}
                      {singleRoleCount > 0 && (
                        <div className="text-sm">
                          • <strong>{singleRoleCount} user(s)</strong> chỉ có vai trò này → sẽ được chuyển về <code>user</code>
                        </div>
                      )}
                    </div>
                    {!forceDelete && (
                      <div className="mt-2 font-medium">
                        Bạn cần check &quot;Force delete&quot; bên dưới để xác nhận.
                      </div>
                    )}
                    {forceDelete && (
                      <div className="mt-2 text-orange-200 font-medium">
                        ✓ Đã xác nhận xóa vai trò khỏi tất cả users.
                      </div>
                    )}
                  </AlertDescription>
                </Alert>

                {/* List affected users */}
                <div className="my-4 p-3 border rounded-md bg-muted/50 max-h-40 overflow-y-auto">
                  <div className="text-sm font-medium mb-2">Affected Users:</div>
                  <div className="space-y-1.5">
                    {usersWithRole.map((user) => (
                      <div key={user.id} className="text-xs flex items-start gap-2">
                        <span className="font-mono bg-background px-1.5 py-0.5 rounded">{user.username}</span>
                        <span className="text-muted-foreground flex-1">
                          {user.full_name || user.email}
                        </span>
                        {user.casbin_roles && user.casbin_roles.length > 1 && (
                          <span className="text-xs text-orange-600 dark:text-orange-400">
                            (has {user.casbin_roles.length} roles)
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Policy count info */}
            <Alert className="my-4">
              <AlertDescription>
                <strong>📋 Policies:</strong> {policyCount} policies
                sẽ bị xóa vĩnh viễn.
              </AlertDescription>
            </Alert>

            {/* Force delete checkbox - only show if there are users */}
            {userCount > 0 && (
              <div className="flex items-start space-x-2 my-4 p-3 border rounded-md bg-muted">
                <Checkbox
                  id="force-delete"
                  checked={forceDelete}
                  onCheckedChange={(checked) => onForceDeleteChange(checked === true)}
                  className="mt-0.5"
                />
                <label
                  htmlFor="force-delete"
                  className="text-sm leading-relaxed peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1"
                >
                  <div className="font-medium mb-1">
                    Xác nhận xóa vai trò khỏi {userCount} user(s)
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Users có nhiều vai trò sẽ giữ lại các vai trò khác. Users chỉ có vai trò này sẽ được chuyển về <code className="bg-background px-1">user</code>.
                  </div>
                </label>
              </div>
            )}
          </>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onOpenChange(false);
              onForceDeleteChange(false);
            }}
            disabled={isDeletingRole}
          >
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={onDeleteRole}
            disabled={isDeletingRole || loadingUsers || (userCount > 0 && !forceDelete)}
          >
            {isDeletingRole ? "Đang xóa…" : "Xóa Vai trò"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
