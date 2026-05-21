"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { History, Activity } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AuditReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Cockpit card cho § audit gần đây. Hiển thị 3 entry gần nhất từ
 * priority_audit_log (BE-canonical) để manager scan các thao tác gần
 * trên hồ sơ trước khi quyết định.
 */
export function AuditReviewCard({ profile }: AuditReviewCardProps) {
  const log = profile.priority_audit_log ?? []
  const recent = log.slice(-3).reverse()

  return (
    <Card data-testid="audit-review-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Audit gần đây</CardTitle>
          </div>
          <History className="w-6 h-6 text-muted-foreground" />
        </div>
      </CardHeader>

      <CardContent className="space-y-2 text-sm">
        {recent.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">Chưa có thao tác audit.</p>
        ) : (
          <ul className="space-y-1.5">
            {recent.map((entry) => (
              <li key={entry.id} className="flex items-baseline justify-between text-xs gap-2">
                <span className="font-medium truncate flex-1">{entry.action_type}</span>
                <span className="text-muted-foreground truncate">
                  {entry.actor_name ?? (entry.actor_id != null ? `#${entry.actor_id}` : "—")}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {new Date(entry.created_at).toLocaleDateString("vi-VN")}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">
          Xem đầy đủ ở {log.length} thao tác trong panel ưu tiên.
        </p>
      </CardContent>
    </Card>
  )
}
