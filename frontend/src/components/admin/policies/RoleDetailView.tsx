// src/components/admin/policies/RoleDetailView.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FileCode, Layers, PlusCircle } from "lucide-react";
import { usePermissionExplain } from "@/hooks/usePermissionExplain";

interface RoleDetailViewProps {
  roleName: string;
}

export function RoleDetailView({ roleName }: RoleDetailViewProps) {
  const { data, isLoading } = usePermissionExplain(roleName);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!data) return null;

  const PolicyTable = ({ policies, title, icon: Icon, description }: {
    policies: typeof data.policies_from_template;
    title: string;
    icon: React.ElementType;
    description: string;
  }) => (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Icon className="h-5 w-5" />
          <CardTitle>{title}</CardTitle>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {policies.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Subject</TableHead>
                <TableHead>Object</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy, idx) => (
                <TableRow key={idx}>
                  <TableCell>
                    <Badge variant="outline">{policy.subject}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm">{policy.object}</TableCell>
                  <TableCell>
                    <code className="rounded bg-muted px-2 py-1 text-sm">{policy.action}</code>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-muted-foreground text-center py-8">No policies found</p>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Permission Breakdown for {data.role}</h2>
        <p className="text-muted-foreground">
          Understanding where this role's permissions come from
        </p>
      </div>

      <PolicyTable
        policies={data.policies_from_template}
        title={`From Template (${data.policies_from_template.length})`}
        icon={FileCode}
        description="Policies inherited from system role templates"
      />

      <PolicyTable
        policies={data.policies_from_features}
        title={`From Features (${data.policies_from_features.length})`}
        icon={Layers}
        description="Policies granted by enabled features"
      />

      <PolicyTable
        policies={data.policies_manual}
        title={`Manually Added (${data.policies_manual.length})`}
        icon={PlusCircle}
        description="Policies added individually by administrators"
      />
    </div>
  );
}
