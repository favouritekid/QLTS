// src/app/(dashboard)/admin/policies/page.tsx
"use client";

import { useState } from "react";
import { Shield, FileText, Grid3x3, Activity } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { usePolicyStatistics } from "@/hooks/usePolicies";
import { PoliciesTab } from "@/components/admin/policies/PoliciesTab";
import { RolesTab } from "@/components/admin/policies/RolesTab";
import { TemplatesTab } from "@/components/admin/policies/TemplatesTab";
import { AuditLogTab } from "@/components/admin/policies/AuditLogTab";

export default function PolicyManagementPage() {
  const [activeTab, setActiveTab] = useState("policies");
  const { data: stats, isLoading: statsLoading } = usePolicyStatistics();

  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Policy Management</h1>
        <p className="text-muted-foreground">
          Manage Casbin policies, roles, and permissions with templates
        </p>
      </header>

      {/* Statistics Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Policies</CardTitle>
            <Shield className="h-4 w-4 text-muted-foreground" />
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
            <Grid3x3 className="h-4 w-4 text-muted-foreground" />
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
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="policies">
            <FileText className="mr-2 h-4 w-4" />
            Policies
          </TabsTrigger>
          <TabsTrigger value="roles">
            <Grid3x3 className="mr-2 h-4 w-4" />
            Roles
          </TabsTrigger>
          <TabsTrigger value="templates">
            <Shield className="mr-2 h-4 w-4" />
            Templates
          </TabsTrigger>
          <TabsTrigger value="audit">
            <Activity className="mr-2 h-4 w-4" />
            Audit Log
          </TabsTrigger>
        </TabsList>

        <TabsContent value="policies" className="space-y-4">
          <PoliciesTab />
        </TabsContent>

        <TabsContent value="roles" className="space-y-4">
          <RolesTab />
        </TabsContent>

        <TabsContent value="templates" className="space-y-4">
          <TemplatesTab />
        </TabsContent>

        <TabsContent value="audit" className="space-y-4">
          <AuditLogTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
