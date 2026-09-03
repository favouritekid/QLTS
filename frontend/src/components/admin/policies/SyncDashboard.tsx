// src/components/admin/policies/SyncDashboard.tsx
"use client";

import { useState } from "react";

import { RefreshCw, AlertCircle, CheckCircle2, Database, ServerCrash } from "lucide-react";
import { usePolicySyncStatus, useSyncPolicies } from "@/hooks/policies/usePolicySync";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
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
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// `SyncStatus` / `MismatchedUser` được khai ở `@/lib/api/policies` và đi vào đây
// qua kiểu trả về của `usePolicySyncStatus()` — không cần import lại.

export function SyncDashboard() {
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);
  const [pendingSync, setPendingSync] = useState<{ type: "all" | "selected"; message: string } | null>(null);

  // Fetch sync status
  const {
    data: syncStatus,
    isLoading,
    isError,
    error: statusError,
    isFetching,
    refetch: refetchStatus,
  } = usePolicySyncStatus();

  // Sync mutation.
  //
  // `useSyncPolicies()` gọi `policiesApi.syncUsers(userIds)` → POST
  // `/api/admin/sync` (hằng `API_ENDPOINTS.ADMIN.SYNC.RUN`). KHÔNG có hậu tố
  // `/users`: `sync.py:53` khai `@router.post("")` trên prefix `/sync`, nên
  // đường đầy đủ dừng ở `/api/admin/sync`. `/api/admin/sync/users` là đường
  // CHẾT — đừng chép lại từ chú thích này ra hằng.
  // `null` = đồng bộ TẤT CẢ, mảng `user_id` = đồng bộ từng phần ⇒ partial sync
  // ĐÃ được hỗ trợ sẵn, hook không cần sửa gì.
  //
  // (Chú thích cũ ở chỗ này nói hook gọi `policiesApi.syncPolicies()` "no args"
  //  và partial sync "chưa hỗ trợ" — SAI cả hai. `syncPolicies` là hằng chết:
  //  không có endpoint backend tương ứng và 0 caller. Đừng dựng lại niềm tin
  //  vào nó từ chú thích này.)
  const syncMutation = useSyncPolicies();

  const handleSyncAll = () => {
    // Không có trạng thái đọc được thì không có gì để xác nhận — nút này chỉ
    // render sau cổng fail-closed bên dưới, nhánh này là chốt chặn thừa.
    if (!syncStatus) return;
    setPendingSync({
      type: "all",
      message: `Đồng bộ TẤT CẢ ${syncStatus.total_users} users từ Casbin về DB?`,
    });
  };

  const handleSyncSelected = () => {
    if (selectedUsers.length === 0) {
      toast.error("Chọn ít nhất 1 user để đồng bộ!");
      return;
    }
    setPendingSync({
      type: "selected",
      message: `Đồng bộ ${selectedUsers.length} user(s) đã chọn từ Casbin về DB?`,
    });
  };

  const confirmSync = () => {
    if (!pendingSync) return;
    if (pendingSync.type === "all") {
      syncMutation.mutate(null);
    } else {
      syncMutation.mutate(selectedUsers);
    }
    setPendingSync(null);
  };

  const toggleUserSelection = (userId: number) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const toggleSelectAll = () => {
    const mismatched = syncStatus?.mismatched_users ?? [];
    if (selectedUsers.length === mismatched.length) {
      setSelectedUsers([]);
    } else {
      setSelectedUsers(mismatched.map((u) => u.user_id));
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

  // ── CỔNG FAIL-CLOSED ────────────────────────────────────────────────────
  // Query hỏng ⇒ KHÔNG có số liệu nào cả, và tuyệt đối không suy ra số.
  //
  // Bản cũ để `syncStatus?.x || 0`: query lỗi ⇒ `undefined` ⇒ 0 ⇒ dashboard vẽ
  // "Tổng số Users 0 · Đã đồng bộ 0 · Chưa đồng bộ 0" rồi rơi vào nhánh
  // `outOfSyncCount > 0 ? … : <Alert>Hệ thống đã đồng bộ</Alert>` — tức là
  // KHẲNG ĐỊNH hệ thống sạch đúng lúc nó không đo được gì. Đó là báo cáo sai,
  // không phải báo lỗi.
  if (isError || !syncStatus) {
    return (
      <Alert variant="destructive" data-testid="sync-status-error">
        <ServerCrash className="h-4 w-4" />
        <AlertTitle>Không đọc được trạng thái đồng bộ DB ↔ Casbin</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            Không hiển thị số liệu nào vì không lấy được dữ liệu. Đây{" "}
            <strong>không</strong> có nghĩa là hệ thống đã đồng bộ — số user lệch
            hiện <strong>chưa xác định</strong>.
          </p>
          <p className="font-mono text-xs break-all">
            {statusError instanceof Error
              ? statusError.message
              : "Lỗi không xác định khi gọi API sync-status"}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetchStatus()}
            disabled={isFetching}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Thử lại
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  // Từ đây `syncStatus` chắc chắn có thật — đọc thẳng, không `|| 0`.
  const outOfSyncCount = syncStatus.out_of_sync_count;
  const syncedCount = syncStatus.synced_count;
  const totalUsers = syncStatus.total_users;
  const mismatchedUsers = syncStatus.mismatched_users ?? [];

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
                      checked={
                        mismatchedUsers.length > 0 &&
                        selectedUsers.length === mismatchedUsers.length
                      }
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
                {mismatchedUsers.map((user) => (
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

      {/* Sync Confirmation Dialog */}
      <AlertDialog open={!!pendingSync} onOpenChange={(open) => !open && setPendingSync(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Đồng bộ users?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingSync?.message}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={confirmSync}>
              Đồng bộ
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
