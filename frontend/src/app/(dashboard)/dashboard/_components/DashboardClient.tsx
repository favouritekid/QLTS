// src/app/(dashboard)/dashboard/_components/DashboardClient.tsx
/**
 * Admin Dashboard Client Component
 *
 * ✅ This dashboard is for Admin/Manager roles only.
 * Officers are redirected to /dashboard/officer at the page level.
 *
 * Shows:
 * - User statistics (total, active, pending, banned)
 * - Recent user management activities
 * - Quick admin actions
 * - Real-time system health status
 */
"use client";

import React from "react";
import Link from "next/link";
import { format } from "date-fns";
import { useAuth } from "@/hooks/useAuth";
import { useUserStatistics } from "@/hooks/useActivityLogs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Users, Activity, UserCheck, UserX, UserPlus, Shield, LayoutDashboard } from "lucide-react";
import { SystemStatusCard } from "./SystemStatusCard";
import type { User, UserStatistics } from "@/types/api.types";

interface DashboardClientProps {
  initialUser?: User;
  initialStats?: UserStatistics;
}

export function DashboardClient({ initialUser, initialStats }: DashboardClientProps) {
  const { user, logout } = useAuth({ initialData: initialUser });

  // ✅ Admin dashboard - statistics are always fetched (non-admins are redirected at page level)
  const { data: stats, isLoading: isLoadingStats } = useUserStatistics({
    enabled: true,
    initialData: initialStats,
  });

  // User statistics cards
  const userStats = stats ? [
    {
      title: "Tổng Người Dùng",
      value: stats.total_users.toString(),
      change: `+${stats.new_users_last_7_days} tuần này`,
      icon: Users,
    },
    {
      title: "Người Dùng Hoạt Động",
      value: stats.active_users.toString(),
      change: stats.total_users > 0
        ? `${((stats.active_users / stats.total_users) * 100).toFixed(1)}% tổng số`
        : "0%",
      icon: UserCheck,
    },
    {
      title: "Chờ Duyệt",
      value: stats.pending_users.toString(),
      change: stats.pending_users > 0 ? "Cần xử lý" : "Không có",
      icon: UserPlus,
      highlight: stats.pending_users > 0,
    },
    {
      title: "Bị Cấm",
      value: stats.banned_users.toString(),
      icon: UserX,
    },
  ] : [];

  return (
    <PageContainer className="animate-fade-in">
      {/* Page Header */}
      <PageHeader
        title="Bảng Điều Khiển Quản Trị"
        description={
          <>
            Chào mừng trở lại,{" "}
            <span className="text-foreground font-medium">{user?.full_name || user?.username || "Admin"}</span>!
          </>
        }
        actions={
          <>
            <Link href="/dashboard/officer">
              <Button variant="outline" size="sm">
                <LayoutDashboard className="mr-2 h-4 w-4" />
                Officer Dashboard
              </Button>
            </Link>
            <Button onClick={() => logout()} variant="destructive" size="sm">
              Đăng Xuất
            </Button>
          </>
        }
      />

      {/* Stats Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoadingStats ? (
          <>
            {[1, 2, 3, 4].map((i) => (
              <Card key={i}>
                <CardHeader className="space-y-0 pb-2">
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-16" />
                </CardContent>
              </Card>
            ))}
          </>
        ) : (
          userStats.map((stat, index) => (
            <Card
              key={index}
              className={`transition-shadow hover:shadow-md ${
                "highlight" in stat && stat.highlight ? "border-warning-500 bg-warning-50/30 dark:bg-warning-950/20" : ""
              }`}
            >
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
                <stat.icon className="text-muted-foreground h-4 w-4" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tabular-nums">{stat.value}</div>
                {"change" in stat && stat.change && (
                  <p className="text-muted-foreground mt-1 text-xs">
                    {stat.change}
                  </p>
                )}
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Content Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent Activity */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Hoạt Động Người Dùng Gần Đây</CardTitle>
            <CardDescription>Các thao tác quản lý người dùng mới nhất</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoadingStats || !stats?.recent_activities ? (
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : stats.recent_activities.length > 0 ? (
              <div className="space-y-3">
                {stats.recent_activities.map((activity) => (
                  <div
                    key={activity.id}
                    className="hover:bg-muted/50 flex items-center gap-3 rounded-lg p-2"
                  >
                    <div className="bg-primary/10 flex h-9 w-9 items-center justify-center rounded-full">
                      <Activity className="text-primary h-4 w-4" />
                    </div>
                    <div className="flex-1 space-y-0.5">
                      <p className="text-sm leading-none font-medium">
                        {activity.description || activity.action}
                      </p>
                      <p className="text-muted-foreground text-xs">
                        bởi {activity.actor_username || "System"} •{" "}
                        {format(new Date(activity.created_at), "dd/MM, HH:mm")}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-center text-sm py-8">
                Chưa có hoạt động gần đây
              </p>
            )}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader>
            <CardTitle>Thao Tác Nhanh</CardTitle>
            <CardDescription>Phím tắt quản lý hệ thống</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Link href="/admin/users">
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Users className="mr-2 h-4 w-4" />
                Quản Lý Người Dùng
              </Button>
            </Link>
            <Link href="/admin/policies">
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Shield className="mr-2 h-4 w-4" />
                Quản Lý Chính Sách
              </Button>
            </Link>
            <Link href="/admin/audit-logs">
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Activity className="mr-2 h-4 w-4" />
                Nhật Ký Hoạt Động
              </Button>
            </Link>
            <Link href="/admin/monitoring">
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Activity className="mr-2 h-4 w-4" />
                Giám Sát Hệ Thống
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* Additional Content */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* User Info Card */}
        <Card>
          <CardHeader>
            <CardTitle>Thông Tin Người Dùng</CardTitle>
            <CardDescription>Chi tiết tài khoản của bạn</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Tên đăng nhập:</span>
              <span className="text-muted-foreground">{user?.username}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Email:</span>
              <span className="text-muted-foreground">{user?.email}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Vai trò:</span>
              <Badge variant="outline" className="capitalize">{user?.role}</Badge>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Trạng thái:</span>
              <Badge variant={user?.status === "active" ? "default" : "secondary"}>
                {user?.status === "active" ? "Hoạt động" : user?.status}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* ✅ FIX: Real-time System Status Card (replaces static badges) */}
        <SystemStatusCard />
      </div>
    </PageContainer>
  );
}
