// src/app/(dashboard)/dashboard/page.tsx
"use client";

import React from "react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users, TrendingUp, DollarSign, Activity, ArrowUpRight } from "lucide-react";

export default function DashboardPage() {
  const { user, logout, isLoading } = useAuth();

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

  const stats = [
    {
      title: "Total Revenue",
      value: "$45,231.89",
      change: "+20.1%",
      icon: DollarSign,
      trend: "up",
    },
    {
      title: "Active Users",
      value: "2,350",
      change: "+180.1%",
      icon: Users,
      trend: "up",
    },
    {
      title: "Sales",
      value: "+12,234",
      change: "+19%",
      icon: TrendingUp,
      trend: "up",
    },
    {
      title: "Active Now",
      value: "573",
      change: "+201",
      icon: Activity,
      trend: "up",
    },
  ];

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
        {stats.map((stat, index) => (
          <Card key={index} className="transition-all hover:shadow-md">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className="text-muted-foreground h-4 w-4" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <div className="text-muted-foreground mt-1 flex items-center gap-1 text-xs">
                <Badge
                  variant={stat.trend === "up" ? "default" : "destructive"}
                  className="gap-1 px-1.5 py-0"
                >
                  <ArrowUpRight className="h-3 w-3" />
                  {stat.change}
                </Badge>
                <span>from last month</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Content Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent Activity */}
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

        {/* Quick Actions */}
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
