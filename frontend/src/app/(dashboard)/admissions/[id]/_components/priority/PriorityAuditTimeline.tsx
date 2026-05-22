"use client"

/**
 * PriorityAuditTimeline — Q9 #07 Phase E.4 workbench audit display.
 *
 * Renders priority_audit_log entries (KV overrides + UT verify/reject)
 * as a vertical timeline at workbench bottom. Hidden when empty.
 *
 * Data source: profile.priority_audit_log (BE response field added in E.4).
 */
import { History, ShieldCheck, ThumbsUp, ThumbsDown } from "lucide-react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { PriorityAuditEntry } from "@/lib/zod/admissions"

interface PriorityAuditTimelineProps {
  entries?: PriorityAuditEntry[] | null
}

function actionMeta(actionType: string) {
  switch (actionType) {
    case "kv_manual_override":
      return {
        icon: ShieldCheck,
        label: "Ấn định KV",
        color: "text-amber-700",
        bg: "bg-amber-50",
      }
    case "ut_evidence_verified":
      return {
        icon: ThumbsUp,
        label: "Duyệt UT",
        color: "text-emerald-700",
        bg: "bg-emerald-50",
      }
    case "ut_evidence_rejected":
      return {
        icon: ThumbsDown,
        label: "Từ chối UT",
        color: "text-red-700",
        bg: "bg-red-50",
      }
    default:
      return {
        icon: History,
        label: actionType,
        color: "text-muted-foreground",
        bg: "bg-muted",
      }
  }
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

function summarize(entry: PriorityAuditEntry): string {
  if (entry.action_type === "kv_manual_override") {
    const oldKv = (entry.old_value as { kv_resolved?: string } | null)?.kv_resolved
    const newKv = (entry.new_value as { kv_resolved?: string } | null)?.kv_resolved
    const reason = (entry.new_value as { reason?: string } | null)?.reason
    return `${oldKv ?? "—"} → ${newKv ?? "—"}${reason ? ` · ${reason}` : ""}`
  }
  if (entry.action_type === "ut_evidence_verified") {
    const subCode =
      (entry.audit_metadata as { sub_code?: string } | null)?.sub_code ??
      (entry.new_value as { sub_code?: string } | null)?.sub_code
    return subCode ? `UT${subCode}` : ""
  }
  if (entry.action_type === "ut_evidence_rejected") {
    const subCode =
      (entry.audit_metadata as { sub_code?: string } | null)?.sub_code ??
      (entry.new_value as { sub_code?: string } | null)?.sub_code
    const reason = (entry.audit_metadata as { reject_reason?: string } | null)
      ?.reject_reason
    return `${subCode ? `UT${subCode}` : ""}${reason ? ` · ${reason}` : ""}`
  }
  return ""
}

export function PriorityAuditTimeline({ entries }: PriorityAuditTimelineProps) {
  if (!entries || entries.length === 0) return null

  return (
    <Card data-testid="priority-audit-timeline">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" />
          Lịch sử quyết định ưu tiên
        </CardTitle>
        <CardDescription className="text-xs">
          {entries.length} thao tác gần nhất trên KV và UT
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map((entry) => {
          const meta = actionMeta(entry.action_type)
          const Icon = meta.icon
          const detail = summarize(entry)
          return (
            <div
              key={entry.id}
              className={`flex items-start gap-3 rounded-md border p-2 ${meta.bg}`}
              data-testid={`audit-entry-${entry.id}`}
            >
              <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${meta.color}`} />
              <div className="flex-1 min-w-0 text-sm">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className={`font-medium ${meta.color}`}>{meta.label}</span>
                  {entry.actor_name && (
                    <span className="text-muted-foreground">
                      bởi {entry.actor_name}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">
                    {formatTime(entry.created_at)}
                  </span>
                </div>
                {detail && (
                  <p className="text-xs text-foreground/80 mt-0.5 break-words">
                    {detail}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
