// src/app/(dashboard)/admin/policies/page.tsx
"use client";

import { useState } from "react";
import { Activity, HardHat, ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { usePolicyStatistics } from "@/hooks/usePolicies";
import { RoleManagementWorkflowTab } from "@/components/admin/policies/RoleManagementWorkflowTab";
import { AdvancedToolsTab } from "@/components/admin/policies/AdvancedToolsTab";
import { AuditLogTab } from "@/components/admin/policies/AuditLogTab";

export default function PolicyManagementPage() {
  const [activeTab, setActiveTab] = useState("workflow");
  const { data: stats, isLoading: statsLoading } = usePolicyStatistics();

  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Policy Management</h1>
        <p className="text-muted-foreground">
          Quản lý tập trung quyền truy cập hệ thống theo vai trò và tính năng.
        </p>
      </header>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Policies</CardTitle>
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold">{stats?.total_policies || 0}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Roles</CardTitle>
            <HardHat className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold">{stats?.total_roles || 0}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">User Assignments</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold">{stats?.total_grouping_policies || 0}</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-3 gap-2">
          <TabsTrigger value="workflow">
            <ShieldCheck className="mr-2 h-4 w-4" />
            Quản lý Vai trò (Workflow)
          </TabsTrigger>
          <TabsTrigger value="tools">
            <HardHat className="mr-2 h-4 w-4" />
            Công cụ Nâng cao
          </TabsTrigger>
          <TabsTrigger value="audit">
            <Activity className="mr-2 h-4 w-4" />
            Nhật ký Hoạt động
          </TabsTrigger>
        </TabsList>

        <TabsContent value="workflow" className="space-y-4">
          <RoleManagementWorkflowTab />
        </TabsContent>

        <TabsContent value="tools" className="space-y-4">
          <AdvancedToolsTab />
        </TabsContent>

        <TabsContent value="audit" className="space-y-4">
          <AuditLogTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
