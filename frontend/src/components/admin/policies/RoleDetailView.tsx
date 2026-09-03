// src/components/admin/policies/RoleDetailView.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FileCode, Layers, PlusCircle, Link2, RefreshCw, ServerCrash } from "lucide-react";
import { usePermissionExplain } from "@/hooks/usePermissionExplain";

interface RoleDetailViewProps {
  roleName: string;
}

interface PolicyRule {
  subject: string;
  object: string;
  action: string;
}

interface PolicyTableProps {
  policies: PolicyRule[];
  title: string;
  icon: React.ElementType;
  description: string;
}

// Move PolicyTable outside of RoleDetailView to avoid creating component during render
function PolicyTable({ policies, title, icon: Icon, description }: PolicyTableProps) {
  return (
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
}

export function RoleDetailView({ roleName }: RoleDetailViewProps) {
  const { data, isLoading, isError, error, isFetching, refetch } =
    usePermissionExplain(roleName);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  // Bản cũ: `if (!data) return null;` — query explain hỏng ⇒ component biến mất
  // KHÔNG một tín hiệu nào. Bảng "quyền đến từ đâu" rỗng ở MỌI role trông y hệt
  // "role này chưa có quyền nào", nên một endpoint chết sống sót rất lâu mà
  // không ai thấy. Không có dữ liệu thì phải NÓI RA là không có dữ liệu.
  if (isError || !data) {
    return (
      <Alert variant="destructive" data-testid="role-explain-error">
        <ServerCrash className="h-4 w-4" />
        <AlertTitle>
          Không tải được phân rã quyền của vai trò {roleName}
        </AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            Bảng nguồn gốc quyền của vai trò này <strong>không</strong> hiển thị
            được. Đây <strong>không</strong> có nghĩa là vai trò không có quyền
            nào — quyền thực tế của nó hiện <strong>chưa xác định</strong>, đừng
            dựa vào màn hình này để kết luận.
          </p>
          <p className="font-mono text-xs break-all">
            {error instanceof Error
              ? error.message
              : "Lỗi không xác định khi gọi API explain"}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Thử lại
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold font-display">Permission Breakdown for {data.role}</h2>
        <p className="text-muted-foreground">
          Understanding where this role&apos;s permissions come from
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
        policies={data.policies_inherited || []}
        title={`Inherited Policies (${data.policies_inherited?.length || 0})`}
        icon={Link2}
        description="Policies inherited from other roles via grouping policies (e.g., role:user)"
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
