// src/components/admin/policies/RolesTab.tsx
"use client";

import { Shield, Lock } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

import { useRoles } from "@/hooks/usePolicies";

export function RolesTab() {
  const { data, isLoading } = useRoles();

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {data?.roles.map((role) => (
        <Card key={role.name} className={role.is_system_role ? "border-primary" : ""}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                {role.display_name}
              </CardTitle>
              {role.is_system_role && (
                <Badge variant="default">
                  <Lock className="mr-1 h-3 w-3" />
                  System
                </Badge>
              )}
            </div>
            <CardDescription>{role.description}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">Policies</div>
              <div className="text-2xl font-bold">{role.policy_count}</div>
            </div>
            <div className="mt-2 text-xs text-muted-foreground">
              Role ID: <code className="rounded bg-muted px-1">{role.name}</code>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
