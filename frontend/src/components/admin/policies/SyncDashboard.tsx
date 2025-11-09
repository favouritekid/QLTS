// src/components/admin/policies/SyncDashboard.tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, AlertCircle, CheckCircle2, Database } from "lucide-react";
import { api } from "@/lib/api/client";
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

interface MismatchedUser {
  user_id: number;
  username: string;
  db_role: string;
  casbin_role: string;
  all_casbin_roles: string[];
}

interface SyncStatus {
  total_users: number;
  synced_count: number;
  out_of_sync_count: number;
  mismatched_users: MismatchedUser[];
}

interface SyncResult {
  synced_count: number;
  failed_count: number;
  failed_users: Array<{
    user_id: number;
    username: string;
    error: string;
  }>;
}

export function SyncDashboard() {
  const queryClient = useQueryClient();
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);

  // Fetch sync status
  const {
    data: syncStatus,
    isLoading,
    refetch: refetchStatus,
  } = useQuery<SyncStatus>({
    queryKey: ["sync-status"],
    queryFn: async () => {
      const response = await api.get<SyncStatus>("/api/admin/sync/status");
      return response.data;
    },
  });

  // Sync mutation
  const syncMutation = useMutation({
    mutationFn: async (userIds: number[] | null) => {
      const response = await api.post<SyncResult>("/api/admin/sync/users", {
        user_ids: userIds,
      });
      return response.data;
    },
    onSuccess: (data) => {
      if (data.failed_count > 0) {
        toast.warning(
          `Synced ${data.synced_count} users, but ${data.failed_count} failed. Check the table for details.`
        );
      } else {
        toast.success(`Successfully synced ${data.synced_count} users!`);
      }
      setSelectedUsers([]);
      refetchStatus();
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: unknown) => {
      const errorMessage = error instanceof Error
        ? error.message
        : (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Unknown error";
      toast.error(`Sync failed: ${errorMessage}`);
    },
  });

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
                Kiểm tra và đồng bộ vai trò giữa Database (user.role) và Casbin (grouping policies)
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
              <div className="rounded-full bg-blue-100 p-3 dark:bg-blue-900">
                <Database className="h-6 w-6 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Tổng số Users</p>
                <p className="text-2xl font-bold">{totalUsers}</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="rounded-full bg-green-100 p-3 dark:bg-green-900">
                <CheckCircle2 className="h-6 w-6 text-green-600 dark:text-green-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Đã đồng bộ</p>
                <p className="text-2xl font-bold">{syncedCount}</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="rounded-full bg-red-100 p-3 dark:bg-red-900">
                <AlertCircle className="h-6 w-6 text-red-600 dark:text-red-400" />
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
