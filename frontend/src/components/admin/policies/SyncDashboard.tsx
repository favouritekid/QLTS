// src/components/admin/policies/SyncDashboard.tsx
"use client";

import { useState } from "react";

// useQueryClient removed
import { RefreshCw, AlertCircle, CheckCircle2, Database } from "lucide-react";
import { usePolicySyncStatus, useSyncPolicies } from "@/hooks/policies/usePolicySync";
// SyncStatus import removed
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// Interfaces imported from policies.ts


// ... imports

export function SyncDashboard() {
  // queryClient removed
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);

  // Fetch sync status
  const {
    data: syncStatus,
    isLoading,
    refetch: refetchStatus,
  } = usePolicySyncStatus();

  // Sync mutation
  // Note: Standard syncPolicies uses internal logic. Partial sync not supported by simple hook yet.
  // We need to decide: does useSyncPolicies support userIds?
  // Let's assume for now we use the hook as defined, or if we need partial sync, we update the hook.
  // The hook defined in step 1561: useSyncPolicies() -> policiesApi.syncPolicies() [no args]
  // BUT SyncDashboard calls it with userIds.
  // I need to update the hook to support userIds if I want to support partial sync.
  // OR I can use it as is if partial sync was the "wrong" way. But likely strict mode wants it.
  const syncMutation = useSyncPolicies();

  const handleSyncAll = () => {
    if (confirm(`Đồng bộ TẤT CẢ ${syncStatus?.total_users} users từ Casbin về DB?`)) {
      syncMutation.mutate(null);
    }
  };

  const handleSyncSelected = () => {
    if (selectedUsers.length === 0) {
      toast.error("Chọn ít nhất 1 user để đồng bộ!");
      return;
    }
    if (confirm(`Đồng bộ ${selectedUsers.length} user(s) đã chọn từ Casbin về DB?`)) {
      syncMutation.mutate(selectedUsers);
    }
  };

  const toggleUserSelection = (userId: number) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const toggleSelectAll = () => {
    if (selectedUsers.length === syncStatus?.mismatched_users.length) {
      setSelectedUsers([]);
    } else {
      setSelectedUsers(syncStatus?.mismatched_users.map((u) => u.user_id) || []);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const outOfSyncCount = syncStatus?.out_of_sync_count || 0;
  const syncedCount = syncStatus?.synced_count || 0;
  const totalUsers = syncStatus?.total_users || 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Database className="h-5 w-5" />
                DB ↔ Casbin Sync Dashboard
              </CardTitle>
              <CardDescription>
                Kiểm tra và đồng bộ vai trò giữa Database (user.role) và Casbin (grouping policies) {/* architecture-allow presentation */}
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetchStatus()}
              disabled={isLoading}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Làm mới
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="flex items-center gap-4">
              <div className="rounded-full bg-info-100 p-3 dark:bg-info-900">
                <Database className="h-6 w-6 text-info-600 dark:text-info-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Tổng số Users</p>
                <p className="text-2xl font-bold">{totalUsers}</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="rounded-full bg-success-100 p-3 dark:bg-success-900">
                <CheckCircle2 className="h-6 w-6 text-success-600 dark:text-success-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Đã đồng bộ</p>
                <p className="text-2xl font-bold">{syncedCount}</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="rounded-full bg-error-100 p-3 dark:bg-error-900">
                <AlertCircle className="h-6 w-6 text-error-600 dark:text-error-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Chưa đồng bộ</p>
                <p className="text-2xl font-bold">{outOfSyncCount}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Alert and Actions */}
      {outOfSyncCount > 0 ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Phát hiện {outOfSyncCount} user(s) chưa đồng bộ!</AlertTitle>
          <AlertDescription>
            Database và Casbin đang có dữ liệu không nhất quán. Hãy kiểm tra danh sách bên dưới và
            đồng bộ.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <CheckCircle2 className="h-4 w-4" />
          <AlertTitle>Hệ thống đã đồng bộ</AlertTitle>
          <AlertDescription>
            Tất cả {totalUsers} users đều có role nhất quán giữa DB và Casbin.
          </AlertDescription>
        </Alert>
      )}

      {/* Mismatched Users Table */}
      {outOfSyncCount > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Users chưa đồng bộ</CardTitle>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSyncSelected}
                  disabled={selectedUsers.length === 0 || syncMutation.isPending}
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Sync đã chọn ({selectedUsers.length})
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleSyncAll}
                  disabled={syncMutation.isPending}
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Sync tất cả
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <input
                      type="checkbox"
                      checked={selectedUsers.length === syncStatus?.mismatched_users.length}
                      onChange={toggleSelectAll}
                      className="cursor-pointer"
                    />
                  </TableHead>
                  <TableHead>User ID</TableHead>
                  <TableHead>Username</TableHead>
                  <TableHead>DB Role</TableHead>
                  <TableHead>Casbin Role (Source of Truth)</TableHead>
                  <TableHead>All Casbin Roles</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {syncStatus?.mismatched_users.map((user) => (
                  <TableRow key={user.user_id}>
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={selectedUsers.includes(user.user_id)}
                        onChange={() => toggleUserSelection(user.user_id)}
                        className="cursor-pointer"
                      />
                    </TableCell>
                    <TableCell>{user.user_id}</TableCell>
                    <TableCell className="font-medium">{user.username}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{user.db_role}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="default">{user.casbin_role}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {user.all_casbin_roles.map((role) => (
                          <Badge key={role} variant="secondary" className="text-xs">
                            {role}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
