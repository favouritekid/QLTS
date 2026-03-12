// src/components/audit/AuditLogTimeline.tsx
/**
 * AuditLogTimeline Component
 *
 * Displays the audit log history for an entity in a timeline format.
 * Can be embedded in entity detail pages (Lead, Consultation, etc.)
 */

"use client";

import React, { useState } from "react";
import { format, parseISO } from "date-fns";
import type { AxiosError } from "axios";
import { vi } from "date-fns/locale";
import {
  Clock,
  Plus,
  Pencil,
  Trash2,
  RotateCcw,
  ArrowRight,
  User,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useEntityAuditHistory } from "@/hooks/useAuditLogs";
import type { AuditLogEntry } from "@/lib/api/audit-logs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ============================================================================
// TYPES
// ============================================================================

interface AuditLogTimelineProps {
  entityType: string;
  entityId: number;
  className?: string;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const ACTION_CONFIG: Record<
  string,
  { icon: typeof Plus; label: string; color: string }
> = {
  created: {
    icon: Plus,
    label: "Tạo mới",
    color: "text-success-600 bg-success-100",
  },
  updated: {
    icon: Pencil,
    label: "Cập nhật",
    color: "text-info-600 bg-info-100",
  },
  deleted: {
    icon: Trash2,
    label: "Xóa",
    color: "text-error-600 bg-error-100",
  },
  restored: {
    icon: RotateCcw,
    label: "Khôi phục",
    color: "text-purple-600 bg-purple-100",
  },
  status_changed: {
    icon: ArrowRight,
    label: "Đổi trạng thái",
    color: "text-warning-600 bg-warning-100",
  },
};

const FIELD_LABELS: Record<string, string> = {
  full_name: "Họ tên",
  phone: "Số điện thoại",
  email: "Email",
  status: "Trạng thái",
  consultation_status_id: "Trạng thái tư vấn",
  pipeline_stage_id: "Giai đoạn",
  unit_id: "Đơn vị",
  offering_id: "Ngành học",
  source: "Nguồn",
  education_level: "Trình độ",
  gpa: "GPA",
  notes: "Ghi chú",
  method: "Phương thức",
  consultation_date: "Ngày tư vấn",
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function getActionConfig(action: string) {
  return (
    ACTION_CONFIG[action] || {
      icon: Clock,
      label: action,
      color: "text-muted-foreground bg-muted",
    }
  );
}

function formatFieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "(trống)";
  }
  if (typeof value === "boolean") {
    return value ? "Có" : "Không";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

function ChangeDetail({
  field,
  oldValue,
  newValue,
}: {
  field: string;
  oldValue: unknown;
  newValue: unknown;
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="font-medium text-muted-foreground">
        {formatFieldLabel(field)}:
      </span>
      <span className="text-error-600 line-through">{formatValue(oldValue)}</span>
      <ArrowRight className="h-3 w-3 text-muted-foreground" />
      <span className="text-success-600">{formatValue(newValue)}</span>
    </div>
  );
}

function renderChanges(entry: AuditLogEntry): React.ReactNode {
  if (!entry.changes || Object.keys(entry.changes).length === 0) {
    return null;
  }

  return (
    <div className="mt-2 space-y-1 rounded-md bg-muted/50 p-2">
      {Object.entries(entry.changes).map(([field, changeObj]) => (
        <ChangeDetail
          key={field}
          field={field}
          oldValue={(changeObj as { old: unknown; new: unknown }).old}
          newValue={(changeObj as { old: unknown; new: unknown }).new}
        />
      ))}
    </div>
  );
}

function renderSingleFieldChange(entry: AuditLogEntry): React.ReactNode {
  if (!entry.field_name || entry.changes) {
    return null;
  }

  return (
    <div className="mt-2 rounded-md bg-muted/50 p-2">
      <ChangeDetail
        field={entry.field_name}
        oldValue={entry.old_value}
        newValue={entry.new_value}
      />
    </div>
  );
}

function AuditLogItem({ entry }: { entry: AuditLogEntry }) {
  const config = getActionConfig(entry.action);
  const Icon = config.icon;

  return (
    <div className="relative flex gap-4 pb-6 last:pb-0">
      {/* Timeline line */}
      <div className="absolute left-4 top-8 bottom-0 w-px bg-border last:hidden" />

      {/* Icon */}
      <div
        className={cn(
          "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          config.color
        )}
      >
        <Icon className="h-4 w-4" />
      </div>

      {/* Content */}
      <div className="flex-1 space-y-1">
        {/* Header */}
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="text-xs">
            {config.label}
          </Badge>

          {entry.actor && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="flex items-center gap-1 text-sm text-muted-foreground">
                    <User className="h-3 w-3" />
                    {entry.actor.full_name || entry.actor.username}
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Username: {entry.actor.username}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}

          <span className="text-xs text-muted-foreground">
            {format(parseISO(entry.created_at), "dd/MM/yyyy HH:mm:ss", {
              locale: vi,
            })}
          </span>
        </div>

        {/* Reason */}
        {entry.reason ? (
          <p className="text-sm text-muted-foreground">{entry.reason}</p>
        ) : null}

        {/* Changes */}
        {renderChanges(entry)}

        {/* Single field change */}
        {renderSingleFieldChange(entry)}

        {/* New values for created action */}
        {entry.action === "created" && entry.new_value !== null && entry.new_value !== undefined ? (
          <div className="mt-2 rounded-md bg-muted/50 p-2">
            <p className="text-sm font-medium text-muted-foreground mb-1">
              Giá trị ban đầu:
            </p>
            <pre className="text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
              {String(JSON.stringify(entry.new_value, null, 2))}
            </pre>
          </div>
        ) : null}

        {/* Old values for deleted/restored action */}
        {(entry.action === "deleted" || entry.action === "restored") &&
          (entry.old_value !== null || entry.new_value !== null) ? (
            <div className="mt-2 rounded-md bg-muted/50 p-2">
              <pre className="text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                {String(JSON.stringify(entry.old_value ?? entry.new_value, null, 2))}
              </pre>
            </div>
          ) : null}

        {/* Source badge */}
        {entry.source && (
          <Badge variant="secondary" className="text-xs mt-1">
            {entry.source}
          </Badge>
        )}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex gap-4">
          <Skeleton className="h-8 w-8 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
      <Clock className="h-12 w-12 mb-2 opacity-50" />
      <p className="text-sm">Chưa có lịch sử thay đổi</p>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-destructive">
      <AlertCircle className="h-12 w-12 mb-2 opacity-50" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const PAGE_SIZE = 50;

export function AuditLogTimeline({
  entityType,
  entityId,
  className,
}: AuditLogTimelineProps) {
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
  } = useEntityAuditHistory(entityType, entityId, { page_size: pageSize });

  if (isLoading) {
    return <LoadingSkeleton />;
  }

  if (isError) {
    const msg = (error as AxiosError<{ detail?: string }>)?.response?.data?.detail
      || "Không thể tải lịch sử thay đổi";
    return <ErrorState message={msg} />;
  }

  if (!data?.items || data.items.length === 0) {
    return <EmptyState />;
  }

  const remaining = data.total - data.items.length;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="text-sm text-muted-foreground mb-4">
        Tổng cộng {data.total} thay đổi
      </div>
      {data.items.map((entry) => (
        <AuditLogItem key={entry.id} entry={entry} />
      ))}
      {data.has_more && (
        <div className="text-center py-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={isFetching}
            onClick={() => setPageSize((prev) => prev + PAGE_SIZE)}
          >
            {isFetching ? "Đang tải…" : `Tải thêm (còn ${remaining})`}
          </Button>
        </div>
      )}
    </div>
  );
}
