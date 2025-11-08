// src/components/admin/policies/AuditLogTab.tsx
"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, Clock, User as UserIcon } from "lucide-react";
import { useActivityLogs } from "@/hooks/useActivityLogs";

export function AuditLogTab() {
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // Fetch activity logs filtered for casbin_policy resource type
  const { data, isLoading, error } = useActivityLogs({
    resource_type: "casbin_policy",
    page,
    page_size: pageSize,
  });

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat("vi-VN", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const getActionBadgeVariant = (action: string): "default" | "secondary" | "destructive" => {
    if (action.includes("add") || action.includes("create")) return "default";
    if (action.includes("remove") || action.includes("delete")) return "destructive";
    return "secondary";
  };

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Policy Audit Log</CardTitle>
          <CardDescription>Track all policy changes and modifications</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center gap-2 p-8 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <p>Failed to load audit logs: {error.message}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy Audit Log</CardTitle>
        <CardDescription>
          Real-time tracking of all policy changes, additions, and deletions
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : !data || data.logs.length === 0 ? (
          <div className="text-muted-foreground p-8 text-center">
            <p>No policy changes recorded yet.</p>
          </div>
        ) : (
          <>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <UserIcon className="text-muted-foreground h-4 w-4" />
                          <span className="font-medium">
                            {log.actor?.full_name || log.actor?.username || `User #${log.actor_id}`}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={getActionBadgeVariant(log.action)}>
                          {log.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-md">
                        <p className="line-clamp-2 text-sm">{log.description}</p>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1 text-sm text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          {formatDate(log.created_at)}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Pagination */}
            {data && data.total_count > pageSize && (
              <div className="mt-4 flex items-center justify-between">
                <div className="text-muted-foreground text-sm">
                  Showing {(page - 1) * pageSize + 1} to{" "}
                  {Math.min(page * pageSize, data.total_count)} of {data.total_count} entries
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= Math.ceil(data.total_count / pageSize)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
