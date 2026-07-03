// src/app/(dashboard)/admin/users/[id]/_components/UserDetailClient.tsx
"use client";

import type { User } from "@/types/api.types";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Edit, Key, Shield, Activity, User as UserIcon } from "lucide-react";
import { format } from "date-fns";
import { vi } from "date-fns/locale";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { useAdminUserDetail } from "@/hooks/useAdminUsers";
import { useActivityLogs } from "@/hooks/useActivityLogs";
import { getAvatarUrl } from "@/lib/utils";
import { UserDialog } from "@/components/admin/UserDialog";
import { SetPasswordDialog } from "@/components/admin/SetPasswordDialog";
import { ManageRolesDialog } from "@/components/admin/ManageRolesDialog";

interface UserDetailClientProps {
  userId: number;
  initialData?: User;
}

export function UserDetailClient({ userId, initialData }: UserDetailClientProps) {
  const router = useRouter();

  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [setPasswordDialogOpen, setSetPasswordDialogOpen] = useState(false);
  const [manageRolesDialogOpen, setManageRolesDialogOpen] = useState(false);

  // Fetch user details
  const { data: user, isLoading: isLoadingUser, error: userError } = useAdminUserDetail(userId, { initialData });

  // Fetch activity logs for this user
  const { data: activityData, isLoading: isLoadingActivity } = useActivityLogs({
    target_user_id: userId,
    page: 1,
    page_size: 20,
  });

  if (userError) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()} aria-label="Quay lại">
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <h1 className="text-3xl font-bold font-display">Không tìm thấy người dùng</h1>
        </div>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi khi tải thông tin người dùng. Người dùng có thể đã bị xoá.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isLoadingUser || !user) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="grid gap-6 md:grid-cols-3">
          <Skeleton className="h-64" />
          <Skeleton className="h-64 md:col-span-2" />
        </div>
      </div>
    );
  }

  const statusColors: Record<string, string> = {
    active: "bg-success-500/10 text-success-500 border-success-500/20",
    pending: "bg-warning-500/10 text-warning-500 border-warning-500/20",
    banned: "bg-error-500/10 text-error-500 border-error-500/20",
  };

  const roleColors: Record<string, string> = {
    admin: "bg-purple-500/10 text-purple-500 border-purple-500/20",
    manager: "bg-info-500/10 text-info-500 border-info-500/20",
    officer: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
    user: "bg-muted text-muted-foreground border-border",
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()} aria-label="Quay lại">
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold font-display">{user.full_name || user.username}</h1>
            <p className="text-muted-foreground">@{user.username}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setUserDialogOpen(true)}>
            <Edit className="mr-2 h-4 w-4" />
            Sửa
          </Button>
          <Button variant="outline" onClick={() => setSetPasswordDialogOpen(true)}>
            <Key className="mr-2 h-4 w-4" />
            Đặt mật khẩu
          </Button>
          <Button variant="outline" onClick={() => setManageRolesDialogOpen(true)}>
            <Shield className="mr-2 h-4 w-4" />
            Quản lý vai trò
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* User Info Card */}
        <Card>
          <CardHeader>
            <CardTitle>Thông tin người dùng</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-col items-center gap-4">
              <Avatar className="h-24 w-24">
                <AvatarImage src={getAvatarUrl(user.avatar_url)} alt={user.username} />
                <AvatarFallback className="text-2xl">
                  {user.username.substring(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="text-center">
                <p className="font-semibold">{user.full_name || "Chưa có tên"}</p>
                <p className="text-sm text-muted-foreground">{user.email}</p>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <p className="text-sm font-medium text-muted-foreground">User ID</p>
                <p className="text-sm">{user.id}</p>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Vai trò</p>
                <Badge variant="outline" className={roleColors[user.role] || roleColors.user}> {/* architecture-allow presentation */}
                  {user.role.toUpperCase()} {/* architecture-allow presentation */}
                </Badge>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Trạng thái</p>
                <Badge variant="outline" className={statusColors[user.status] || statusColors.active}>
                  {user.status.toUpperCase()}
                </Badge>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Số điện thoại</p>
                <p className="text-sm">{user.phone_number || "Chưa cung cấp"}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Tabs Section */}
        <div className="md:col-span-2">
          <Tabs defaultValue="activity" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="activity">
                <Activity className="mr-2 h-4 w-4" />
                Nhật ký hoạt động
              </TabsTrigger>
              <TabsTrigger value="details">
                <UserIcon className="mr-2 h-4 w-4" />
                Thông tin chi tiết
              </TabsTrigger>
            </TabsList>

            {/* Activity Logs Tab */}
            <TabsContent value="activity">
              <Card>
                <CardHeader>
                  <CardTitle>Hoạt động gần đây</CardTitle>
                  <CardDescription>
                    Các hành động trên tài khoản này
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {isLoadingActivity ? (
                    <div className="space-y-2">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                      ))}
                    </div>
                  ) : activityData?.logs && activityData.logs.length > 0 ? (
                    <div className="rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Hành động</TableHead>
                            <TableHead>Người thực hiện</TableHead>
                            <TableHead>Mô tả</TableHead>
                            <TableHead>Ngày</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {activityData.logs.map((log) => (
                            <TableRow key={log.id}>
                              <TableCell className="font-medium">
                                <Badge variant="outline">{log.action}</Badge>
                              </TableCell>
                              <TableCell>
                                {log.actor_username || "Hệ thống"}
                              </TableCell>
                              <TableCell className="max-w-md truncate">
                                {log.description || "Không có mô tả"}
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground">
                                {format(new Date(log.created_at), "dd/MM/yyyy HH:mm", { locale: vi })}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : (
                    <p className="text-center text-muted-foreground py-8">
                      Chưa có nhật ký hoạt động cho người dùng này.
                    </p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Additional Details Tab */}
            <TabsContent value="details">
              <Card>
                <CardHeader>
                  <CardTitle>Thông tin bổ sung</CardTitle>
                  <CardDescription>
                    Hồ sơ mở rộng và dữ liệu hệ thống
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Tên đăng nhập</p>
                      <p className="text-sm">{user.username}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Email</p>
                      <p className="text-sm">{user.email}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Họ và tên</p>
                      <p className="text-sm">{user.full_name || "Chưa cung cấp"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Số điện thoại</p>
                      <p className="text-sm">{user.phone_number || "Chưa cung cấp"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Đơn vị tổ chức</p>
                      <p className="text-sm">{user.unit_id ? `Đơn vị #${user.unit_id}` : "Chưa phân công"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Trạng thái sẵn sàng</p>
                      <p className="text-sm">{user.availability_status || "Không có"}</p>
                    </div>
                    {/* Thuộc tính riêng của officer (chỉ đọc); role-gate hiển thị là
                        deviation có chủ đích với "no role checks" cho tab thông tin. */}
                    {user.role === "officer" && (
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">Trọng số phân công lead</p>
                        {/* "—" khi thiếu (KHÔNG bịa giá trị nghiệp vụ "1") */}
                        <p className="text-sm">{user.assignment_weight ?? "—"}</p>
                      </div>
                    )}
                  </div>
                  {user.skills && user.skills.length > 0 && (
                    <div>
                      <p className="text-sm font-medium text-muted-foreground mb-2">Kỹ năng</p>
                      <div className="flex flex-wrap gap-2">
                        {user.skills.map((skill, index) => (
                          <Badge key={index} variant="secondary">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>

      {/* Dialogs */}
      <UserDialog
        open={userDialogOpen}
        onOpenChange={setUserDialogOpen}
        mode="edit"
        user={user}
      />
      <SetPasswordDialog
        open={setPasswordDialogOpen}
        onOpenChange={setSetPasswordDialogOpen}
        user={user}
      />
      <ManageRolesDialog
        open={manageRolesDialogOpen}
        onOpenChange={setManageRolesDialogOpen}
        user={user}
      />
    </div>
  );
}
