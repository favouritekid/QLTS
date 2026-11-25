"use client"

import { Badge } from "@/components/ui/badge"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { CONFIG_CHANGED_BADGE, NO_RUN_YET, runStatusLabel, tabCountEntries } from "@/lib/review-sessions/messages"
import type { ReviewRunSummary } from "@/lib/zod/review-sessions"

/**
 * Lượt kiểm gần nhất của một lần xét (`latest_run` của E2 / E3): trạng thái + lúc xong + số theo tab của MÁY CHỦ + nhãn "Cấu hình
 * đã đổi" khi máy chủ trả `config_changed_since_run` (cờ tính lúc GET — query E2 / E3 không giữ bản cũ, xem hook). Không tự
 * tính / cộng số nào.
 */
export function LatestRunSummary({ run, testId }: { run: ReviewRunSummary | null; testId: string }) {
  if (!run) {
    return (
      <span className="text-muted-foreground" data-testid={testId}>
        {NO_RUN_YET}
      </span>
    )
  }
  const counts = tabCountEntries(run.tab_counts)
  return (
    <div className="space-y-1 text-sm" data-testid={testId}>
      <div>
        {runStatusLabel(run.status)}
        {run.finished_at ? ` · ${formatDateTimeVN(run.finished_at)}` : null}
      </div>
      {counts.length ? (
        <div className="text-muted-foreground">{counts.map((c) => `${c.label} ${c.count}`).join(" · ")}</div>
      ) : null}
      {run.config_changed_since_run ? (
        <Badge variant="warning" data-testid={`${testId}-cau-hinh-doi`}>
          {CONFIG_CHANGED_BADGE}
        </Badge>
      ) : null}
    </div>
  )
}
