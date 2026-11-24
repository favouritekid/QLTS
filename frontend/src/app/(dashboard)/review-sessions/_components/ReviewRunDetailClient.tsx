"use client"

import Link from "next/link"
import { useState } from "react"
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { useReviewRun, useReviewSession } from "@/lib/hooks/use-review-sessions"
import {
  OLD_RUN_NOTE,
  RELOADING,
  RUN_CONFIG_CHANGED_BANNER,
  RUN_NOT_DONE_NOTE,
  RUN_NO_SUMMARY,
  RUN_RESULTS_NEXT_PHASE,
  RUN_VIEW_TABS,
  describeReviewSessionError,
  durationLabel,
  feeGateModeLabel,
  runFailedMessage,
  runStatusLabel,
  runWarningLabel,
  tabCountEntries,
  userRef,
  type RunViewTab,
} from "@/lib/review-sessions/messages"
import { classifyRunStatus } from "@/lib/review-sessions/run-tracking"
import { reviewSessionHref } from "@/lib/review-sessions/url"

import { ReviewErrorAlert } from "./ReviewErrorAlert"
import { RunFloorsUsed, RunQuotaView } from "./ReviewRunReference"

/**
 * M5 — một lượt kiểm (thiết kế §3.6; đợt F3 làm ĐẦU TRANG + hai thẻ "Chỉ tiêu tham khảo", "Điểm sàn đã dùng"; thẻ "Kết quả" bốn tab
 * thuộc F4). Đọc E8 (lượt) + E3 (lần xét: số thứ tự, `latest_done_run_id`) — cả hai theo khuôn DC-1 (`staleTime` / `gcTime` 0, không
 * `placeholderData`): `config_changed_since_run` máy chủ tính LÚC GET ⇒ không giữ bản cũ. Tải lỗi (kể cả 429) ⇒ hiện LỖI, KHÔNG vẽ đầu
 * trang / bảng cũ (đọc `isError` TRƯỚC `data`).
 *
 * Băng cảnh báo hiện NGUYÊN cờ máy chủ: "lượt cũ" = lượt đã `done` mà `id` khác `latest_done_run_id` của E3 (so hai id máy chủ
 * trả; lượt chưa xong / hỏng có băng trạng thái riêng); `config_changed_since_run`; `summary.warnings` (nhãn Phụ lục A, lạ ⇒ câu
 * chung có mã; `quota_closed_present` nhấn mạnh — cổng N4). Số ở các thẻ là NGUYÊN số máy chủ — không tự tính / cộng.
 */
export function ReviewRunDetailClient({ sessionId, runId }: { sessionId: number; runId: number }) {
  const sq = useReviewSession(sessionId)
  const rq = useReviewRun(sessionId, runId)
  const [view, setView] = useState<RunViewTab>("ket-qua")
  const busy = sq.isFetching || rq.isFetching
  const reload = () => {
    void sq.refetch()
    void rq.refetch()
  }

  if (rq.isError || sq.isError) {
    const error = rq.isError ? rq.error : sq.error
    return (
      <div className="space-y-3">
        <ReviewErrorAlert testId="luot-loi" message={describeReviewSessionError(error, "read").message} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={reload} disabled={busy} data-testid="luot-tai-lai">
            <RefreshCw className="mr-1 h-4 w-4" />
            Tải lại
          </Button>
          <Button asChild variant="ghost">
            <Link href={reviewSessionHref(sessionId)} data-testid="ve-lan-xet">
              Về lần xét
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  if (!rq.data || !sq.data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="luot-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải lượt kiểm…
      </p>
    )
  }

  const run = rq.data
  const s = sq.data
  const progress = classifyRunStatus(run.status)
  const warnings = run.summary?.warnings ?? []
  const counts = tabCountEntries(run.summary?.tab_counts)

  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold" data-testid="luot-tieu-de">
            Lượt kiểm #{run.id} — lần xét số {s.seq_no} năm {s.academic_year}
          </h1>
          <Badge variant="outline" data-testid="luot-trang-thai">
            {runStatusLabel(run.status)}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
          {run.finished_at !== null ? <span data-testid="luot-xong">Xong lúc {formatDateTimeVN(run.finished_at)}</span> : null}
          <span data-testid="luot-thoi-luong">Thời lượng {durationLabel(run.duration_ms)}</span>
          <span data-testid="luot-nguoi-chay">Chạy bởi {userRef(run.requested_by_user_id)}</span>
          <span data-testid="luot-bo-luat">Bộ luật {run.rule_version}</span>
          <span data-testid="luot-cong-hoc-phi">Cổng học phí lúc chạy: {feeGateModeLabel(run.inputs.fee_gate_mode)}</span>
          <span data-testid="luot-anh-chup">Ảnh chụp lúc {formatDateTimeVN(run.inputs.snapshot_at)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={reload} disabled={busy} data-testid="luot-tai-lai">
            <RefreshCw className="mr-1 h-4 w-4" />
            Tải lại
          </Button>
          <Button asChild variant="ghost">
            <Link href={reviewSessionHref(sessionId)} data-testid="ve-lan-xet">
              Về lần xét
            </Link>
          </Button>
          {busy ? <span className="text-sm text-muted-foreground">{RELOADING}</span> : null}
        </div>
      </header>

      {progress === "done" && s.latest_done_run_id !== run.id ? (
        <Alert data-testid="bang-luot-cu">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{OLD_RUN_NOTE}</AlertDescription>
        </Alert>
      ) : null}
      {progress === "pending" ? (
        <Alert data-testid="bang-luot-chua-xong">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{RUN_NOT_DONE_NOTE}</AlertDescription>
        </Alert>
      ) : null}
      {progress === "failed" ? <ReviewErrorAlert testId="bang-luot-hong" message={runFailedMessage(run.error_code)} /> : null}
      {run.config_changed_since_run ? (
        <Alert data-testid="bang-luot-cau-hinh-doi">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{RUN_CONFIG_CHANGED_BANNER}</AlertDescription>
        </Alert>
      ) : null}
      {warnings.map((w) => (
        <Alert key={w} variant={w === "quota_closed_present" ? "destructive" : "default"} data-testid={`canh-bao-${w}`}>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{runWarningLabel(w)}</AlertDescription>
        </Alert>
      ))}

      <div className="flex flex-wrap gap-2" role="tablist" data-testid="luot-the">
        {RUN_VIEW_TABS.map((t) => (
          <Button
            key={t.key}
            role="tab"
            aria-selected={view === t.key}
            variant={view === t.key ? "default" : "outline"}
            size="sm"
            onClick={() => setView(t.key)}
            data-testid={`the-${t.key}`}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {view === "ket-qua" ? (
        <section className="space-y-2 text-sm" data-testid="the-noi-dung-ket-qua">
          {counts.length ? (
            <p data-testid="luot-so-nhom">{counts.map((c) => `${c.label} ${c.count}`).join(" · ")}</p>
          ) : (
            <p className="text-muted-foreground">{RUN_NO_SUMMARY}</p>
          )}
          <p className="text-muted-foreground">{RUN_RESULTS_NEXT_PHASE}</p>
        </section>
      ) : null}
      {view === "chi-tieu" ? <RunQuotaView view={run.quota_view} /> : null}
      {view === "diem-san" ? <RunFloorsUsed floors={run.inputs.floors} majors={run.quota_view?.majors ?? []} /> : null}
    </div>
  )
}
