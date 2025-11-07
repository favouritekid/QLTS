// src/app/(dashboard)/dashboard/page.tsx
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
import { Users, TrendingUp, DollarSign, Activity, UserCheck, UserX, UserPlus, Shield } from "lucide-react";

export default function DashboardPage() {
  const { user, logout, isLoading } = useAuth();
  const { data: stats, isLoading: isLoadingStats } = useUserStatistics();

  const isAdmin = user?.role === "admin" || user?.role === "manager";

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="space-y-4 text-center">
          <div className="border-primary mx-auto h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" />
          <p className="text-muted-foreground text-sm">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  // User statistics for admin/manager
  const userStats = stats ? [
    {
      title: "Total Users",
      value: stats.total_users.toString(),
      change: `+${stats.new_users_last_7_days} this week`,
      icon: Users,
      trend: "up" as const,
    },
    {
      title: "Active Users",
      value: stats.active_users.toString(),
      change: `${((stats.active_users / stats.total_users) * 100).toFixed(1)}%`,
      icon: UserCheck,
      trend: "up" as const,
    },
    {
      title: "Pending Users",
      value: stats.pending_users.toString(),
      icon: UserPlus,
      trend: "neutral" as const,
    },
    {
      title: "Banned Users",
      value: stats.banned_users.toString(),
      icon: UserX,
      trend: "down" as const,
    },
  ] : [];

  // Default placeholder stats for non-admin users
  const defaultStats = [
    {
      title: "Total Revenue",
      value: "$45,231.89",
      change: "+20.1%",
      icon: DollarSign,
      trend: "up" as const,
    },
    {
      title: "Active Users",
      value: "2,350",
      change: "+180.1%",
      icon: Users,
      trend: "up" as const,
    },
    {
      title: "Sales",
      value: "+12,234",
      change: "+19%",
      icon: TrendingUp,
      trend: "up" as const,
    },
    {
      title: "Active Now",
      value: "573",
      change: "+201",
      icon: Activity,
      trend: "up" as const,
    },
  ];

  const displayStats = isAdmin && stats ? userStats : defaultStats;

  return (
    <div className="animate-fade-in space-y-4">
      {/* Page Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Dashboard</h1>
          <p className="text-muted-foreground text-sm">
            Welcome back,{" "}
            <span className="text-foreground font-medium">{user?.username || "Guest"}</span>!
          </p>
        </div>

        {/* Buttons */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            Download Report
          </Button>
          <Button onClick={() => logout()} variant="destructive" size="sm">
            Logout
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoadingStats && isAdmin ? (
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
          displayStats.map((stat, index) => (
            <Card key={index} className="transition-all hover:shadow-md">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
                <stat.icon className="text-muted-foreground h-4 w-4" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stat.value}</div>
                {stat.change && (
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
        {/* Recent Activity - Show for admin/manager */}
        {isAdmin && (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Recent User Activities</CardTitle>
              <CardDescription>Latest user management actions</CardDescription>
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
                          by {activity.actor_username || "System"} •{" "}
                          {format(new Date(activity.created_at), "MMM d, HH:mm")}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-center text-sm py-8">
                  No recent activities
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Recent Activity - Default for non-admin */}
        {!isAdmin && (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Recent Activity</CardTitle>
              <CardDescription>Your latest updates and actions</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {[1, 2, 3, 4].map((item) => (
                  <div
                    key={item}
                    className="hover:bg-muted/50 flex items-center gap-3 rounded-lg p-2"
                  >
                    <div className="bg-primary/10 flex h-9 w-9 items-center justify-center rounded-full">
                      <Activity className="text-primary h-4 w-4" />
                    </div>
                    <div className="flex-1 space-y-0.5">
                      <p className="text-sm leading-none font-medium">Activity {item}</p>
                      <p className="text-muted-foreground text-xs">2 hours ago</p>
                    </div>
                    <Button variant="ghost" size="sm">
                      View
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Quick Actions - Admin */}
        {isAdmin && (
          <Card>
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
              <CardDescription>User management shortcuts</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Link href="/admin/users">
                <Button className="w-full justify-start" variant="outline" size="sm">
                  <Users className="mr-2 h-4 w-4" />
                  Manage Users
                </Button>
              </Link>
              <Link href="/admin/policies">
                <Button className="w-full justify-start" variant="outline" size="sm">
                  <Shield className="mr-2 h-4 w-4" />
                  Manage Policies
                </Button>
              </Link>
              <Button className="w-full justify-start" variant="outline" size="sm" disabled>
                <TrendingUp className="mr-2 h-4 w-4" />
                View Reports
              </Button>
              <Button className="w-full justify-start" variant="outline" size="sm" disabled>
                <Activity className="mr-2 h-4 w-4" />
                Activity Logs
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Quick Actions - Default */}
        {!isAdmin && (
          <Card>
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
              <CardDescription>Common tasks and shortcuts</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Users className="mr-2 h-4 w-4" />
                Add New User
              </Button>
              <Button className="w-full justify-start" variant="outline" size="sm">
                <TrendingUp className="mr-2 h-4 w-4" />
                Create Report
              </Button>
              <Button className="w-full justify-start" variant="outline" size="sm">
                <DollarSign className="mr-2 h-4 w-4" />
                View Revenue
              </Button>
              <Button className="w-full justify-start" variant="outline" size="sm">
                <Activity className="mr-2 h-4 w-4" />
                Monitor Activity
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Additional Content */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>User Information</CardTitle>
            <CardDescription>Your account details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Username:</span>
              <span className="text-muted-foreground">{user?.username}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Email:</span>
              <span className="text-muted-foreground">{user?.email}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Role:</span>
              <Badge variant="outline">{user?.role}</Badge>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Status:</span>
              <Badge variant={user?.status === "active" ? "default" : "secondary"}>
                {user?.status}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Status</CardTitle>
            <CardDescription>All systems operational</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {["API Server", "Database", "Cache", "Storage"].map((service) => (
              <div key={service} className="flex items-center justify-between text-sm">
                <span className="font-medium">{service}</span>
                <Badge className="bg-green-500 hover:bg-green-600">Operational</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
