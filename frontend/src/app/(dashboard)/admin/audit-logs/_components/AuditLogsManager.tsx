// src/app/(dashboard)/admin/audit-logs/_components/AuditLogsManager.tsx
"use client";

import { useState } from "react";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Search,
  Filter,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Plus,
  Pencil,
  Trash2,
  RotateCcw,
  ArrowRight,
  User,
  Clock,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TableEmptyState } from "@/components/common/EmptyState";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useAuditLogs, useAuditLogSummary, auditLogKeys } from "@/hooks/useAuditLogs";
import type { AuditLogEntry } from "@/lib/api/audit-logs";
import { cn } from "@/lib/utils";

// ============================================================================
// CONSTANTS
// ============================================================================

const ENTITY_TYPES = [
  { value: "Lead", label: "Lead" },
  { value: "Consultation", label: "Tư vấn" },
  { value: "AdmissionProfile", label: "Hồ sơ xét tuyển" },
];

const ACTION_TYPES = [
  { value: "created", label: "Tạo mới" },
  { value: "updated", label: "Cập nhật" },
  { value: "deleted", label: "Xóa" },
  { value: "restored", label: "Khôi phục" },
  { value: "status_changed", label: "Đổi trạng thái" },
];

const ACTION_CONFIG: Record<
  string,
  { icon: typeof Plus; label: string; color: string }
> = {
  created: {
    icon: Plus,
    label: "Tạo mới",
    color: "bg-success-100 text-success-700",
  },
  updated: {
    icon: Pencil,
    label: "Cập nhật",
    color: "bg-info-100 text-info-700",
  },
  deleted: {
    icon: Trash2,
    label: "Xóa",
    color: "bg-error-100 text-error-700",
  },
  restored: {
    icon: RotateCcw,
    label: "Khôi phục",
    color: "bg-purple-100 text-purple-700",
  },
  status_changed: {
    icon: ArrowRight,
    label: "Đổi trạng thái",
    color: "bg-orange-100 text-orange-700",
  },
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function getActionConfig(action: string) {
  return (
    ACTION_CONFIG[action] || {
      icon: Clock,
      label: action,
      color: "bg-muted text-muted-foreground",
    }
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "(trống)";
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

function SummaryCards() {
  const { data: summary, isLoading } = useAuditLogSummary();

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-20" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Tổng số thay đổi</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{summary.total.toLocaleString()}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Lead</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {(summary.by_entity_type.Lead || 0).toLocaleString()}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Tư vấn</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {(summary.by_entity_type.Consultation || 0).toLocaleString()}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Hồ sơ xét tuyển</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {(summary.by_entity_type.AdmissionProfile || 0).toLocaleString()}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function AuditLogRow({ entry }: { entry: AuditLogEntry }) {
  const config = getActionConfig(entry.action);
  const Icon = config.icon;

  return (
    <TableRow>
      <TableCell>
        <Badge variant="outline" className={cn("gap-1", config.color)}>
          <Icon className="h-3 w-3" />
          {config.label}
        </Badge>
      </TableCell>
      <TableCell>
        <Badge variant="secondary">{entry.entity_type}</Badge>
        <span className="ml-2 text-muted-foreground">#{entry.entity_id}</span>
      </TableCell>
      <TableCell>
        {entry.actor ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex items-center gap-1">
                  <User className="h-3 w-3 text-muted-foreground" />
                  {entry.actor.full_name || entry.actor.username}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>Username: {entry.actor.username}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <span className="text-muted-foreground">System</span>
        )}
      </TableCell>
      <TableCell className="max-w-xs">
        {entry.changes ? (
          <div className="text-xs space-y-0.5">
            {Object.entries(entry.changes).slice(0, 2).map(([field, change]) => (
              <div key={field} className="truncate">
                <span className="font-medium">{field}:</span>{" "}
                <span className="text-error-600 line-through">
                  {formatValue(change.old)}
                </span>{" "}
                <ArrowRight className="h-2 w-2 inline text-muted-foreground" />{" "}
                <span className="text-success-600">{formatValue(change.new)}</span>
              </div>
            ))}
            {Object.keys(entry.changes).length > 2 && (
              <span className="text-muted-foreground">
                +{Object.keys(entry.changes).length - 2} thay đổi khác
              </span>
            )}
          </div>
        ) : entry.field_name ? (
          <div className="text-xs">
            <span className="font-medium">{entry.field_name}:</span>{" "}
            <span className="text-error-600 line-through">
              {formatValue(entry.old_value)}
            </span>{" "}
            <ArrowRight className="h-2 w-2 inline text-muted-foreground" />{" "}
            <span className="text-success-600">{formatValue(entry.new_value)}</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">{entry.reason || "-"}</span>
        )}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {format(new Date(entry.created_at), "dd/MM/yyyy HH:mm:ss", {
          locale: vi,
        })}
      </TableCell>
    </TableRow>
  );
}

function LoadingRows() {
  return (
    <>
      {[1, 2, 3, 4, 5].map((i) => (
        <TableRow key={i}>
          <TableCell>
            <Skeleton className="h-6 w-20" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-6 w-24" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-6 w-32" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-6 w-48" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-6 w-28" />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function AuditLogsManager() {
  const queryClient = useQueryClient();

  // Filter state
  const [entityType, setEntityType] = useState<string | undefined>(undefined);
  const [action, setAction] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // Query
  const { data, isLoading, isFetching, refetch } = useAuditLogs({
    entity_type: entityType,
    action: action,
    page,
    page_size: pageSize,
  });

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: auditLogKeys.all });
    refetch();
  };

  const handleClearFilters = () => {
    setEntityType(undefined);
    setAction(undefined);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <SummaryCards />

      {/* Filters */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Lịch sử thay đổi</CardTitle>
              <CardDescription>
                Xem chi tiết các thay đổi dữ liệu trong hệ thống
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isFetching}
            >
              <RefreshCw
                className={cn("h-4 w-4 mr-2", isFetching && "animate-spin")}
              />
              Làm mới
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Lọc:</span>
            </div>

            <Select
              value={entityType || "all"}
              onValueChange={(v) => {
                setEntityType(v === "all" ? undefined : v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Loại entity" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả loại</SelectItem>
                {ENTITY_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={action || "all"}
              onValueChange={(v) => {
                setAction(v === "all" ? undefined : v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Hành động" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả hành động</SelectItem>
                {ACTION_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {(entityType || action) && (
              <Button variant="ghost" size="sm" onClick={handleClearFilters}>
                Xóa bộ lọc
              </Button>
            )}
          </div>

          {/* Table */}
          <div className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-28">Hành động</TableHead>
                  <TableHead className="w-36">Entity</TableHead>
                  <TableHead className="w-40">Người thực hiện</TableHead>
                  <TableHead>Chi tiết thay đổi</TableHead>
                  <TableHead className="w-36">Thời gian</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <LoadingRows />
                ) : !data?.items || data.items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="h-32">
                      <TableEmptyState
                        title="Không có dữ liệu audit log"
                        description="Các hoạt động trong hệ thống sẽ được ghi lại ở đây"
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  data.items.map((entry) => (
                    <AuditLogRow key={entry.id} entry={entry} />
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {data && data.total > pageSize && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
                Hiển thị {(page - 1) * pageSize + 1} -{" "}
                {Math.min(page * pageSize, data.total)} / {data.total} bản ghi
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Trước
                </Button>
                <span className="text-sm">
                  Trang {page} / {Math.ceil(data.total / pageSize)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!data.has_more}
                >
                  Sau
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
