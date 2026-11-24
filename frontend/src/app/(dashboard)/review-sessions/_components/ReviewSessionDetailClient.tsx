"use client"

import Link from "next/link"
import { useState } from "react"
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { useReviewSession } from "@/lib/hooks/use-review-sessions"
import {
  ACTION_NOT_YET,
  CANCELLED_FLOORS_NOTE,
  CONFIG_CHANGED_BANNER,
  NO_DONE_RUN,
  RELOADING,
  REVIEW_DRAFT_NOTE,
  SESSION_ACTION_LABEL,
  describeReviewSessionError,
  knownSessionActions,
  quotaTableDraftBanner,
  quotaTableHref,
  quotaTableLinkLabel,
  quotaTableStatusLabel,
  sessionStatusLabel,
  userRef,
} from "@/lib/review-sessions/messages"
import { REVIEW_SESSIONS_ROUTE } from "@/lib/review-sessions/url"

import { CancelReviewSessionDialog } from "./CancelReviewSessionDialog"
import { LatestRunSummary } from "./LatestRunSummary"
import { ReviewErrorAlert } from "./ReviewErrorAlert"

function Banner({ testId, children }: { testId: string; children: string }) {
  return (
    <Alert data-testid={testId}>
      <AlertTriangle className="h-4 w-4" />
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  )
}

/**
 * M2 — chi tiết lần xét (E3, `no-store`; query `staleTime` / `gcTime` 0 — đính chính 2 §1). Lấy lại khi vào trang, sau MỌI thao
 * tác ghi (hook lo, bất kể kết quả) và khi bấm "Tải lại". Tải lỗi (kể cả 429) ⇒ hiện LỖI, không vẽ dữ liệu cũ.
 *
 * Thanh nút CHỈ theo `available_actions` của máy chủ (`[]` ⇒ không nút; giá trị lạ bỏ qua) — không theo `status`, không theo vai.
 * Trong lúc E3 đang tải lại, nút ghi bị khoá để thao tác kế luôn dùng `version` mới nhất. F1 làm "Huỷ lần xét" (M7); "Sửa điểm
 * sàn" (F2) và "Kiểm hồ sơ" (F3) hiện theo cờ nhưng chưa bấm được ở bản này. Băng cảnh báo hiện NGUYÊN cờ máy chủ, không suy.
 */
export function ReviewSessionDetailClient({ sessionId }: { sessionId: number }) {
  const q = useReviewSession(sessionId)
  const [cancelOpen, setCancelOpen] = useState(false)

  if (q.isError) {
    return (
      <div className="space-y-3">
        <ReviewErrorAlert testId="lan-xet-loi" message={describeReviewSessionError(q.error, "read").message} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="lan-xet-tai-lai">
            <RefreshCw className="mr-1 h-4 w-4" />
            Tải lại
          </Button>
          <Button asChild variant="ghost">
            <Link href={REVIEW_SESSIONS_ROUTE} data-testid="ve-danh-sach">
              Về danh sách lần xét
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  if (!q.data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="lan-xet-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải lần xét…
      </p>
    )
  }

  const s = q.data
  const actions = knownSessionActions(s.available_actions)
  const busy = q.isFetching
  const notYet = actions.some((a) => a !== "cancel")

  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold" data-testid="lan-xet-tieu-de">
            Lần xét số {s.seq_no} — năm {s.academic_year} — {s.admission_round.round_name}
          </h1>
          <Badge variant="outline" data-testid="lan-xet-trang-thai">
            {sessionStatusLabel(s.status)}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
          <span data-testid="lan-xet-bang-chi-tieu">
            Bảng chỉ tiêu năm: {quotaTableStatusLabel(s.quota_table.status)} (phiên bản {s.quota_table.version}) ·{" "}
            <Link href={quotaTableHref(s.academic_year)} className="underline" data-testid="lan-xet-lien-ket-bang-chi-tieu">
              {quotaTableLinkLabel(s.academic_year)}
            </Link>
          </span>
          <span data-testid="lan-xet-tao">
            Tạo bởi {userRef(s.created_by_user_id)} lúc {formatDateTimeVN(s.created_at)}
          </span>
        </div>
        {s.cancelled_at !== null ? (
          <p className="text-sm" data-testid="lan-xet-huy">
            Huỷ bởi {userRef(s.cancelled_by_user_id)} lúc {formatDateTimeVN(s.cancelled_at)}
            {s.cancel_reason !== null ? ` — Lý do: ${s.cancel_reason}` : null}
          </p>
        ) : null}
        <p className="text-sm text-muted-foreground">{REVIEW_DRAFT_NOTE}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {actions.length ? (
          <div className="flex flex-wrap gap-2" data-testid="thanh-nut">
            {actions.map((a) =>
              a === "cancel" ? (
                <Button key={a} variant="destructive" disabled={busy} onClick={() => setCancelOpen(true)} data-testid="nut-cancel">
                  {SESSION_ACTION_LABEL[a]}
                </Button>
              ) : (
                <Button key={a} variant="outline" disabled title={ACTION_NOT_YET} data-testid={`nut-${a}`}>
                  {SESSION_ACTION_LABEL[a]}
                </Button>
              ),
            )}
          </div>
        ) : null}
        <Button variant="ghost" onClick={() => void q.refetch()} disabled={busy} data-testid="lan-xet-tai-lai">
          <RefreshCw className="mr-1 h-4 w-4" />
          Tải lại
        </Button>
        {busy ? (
          <span className="text-sm text-muted-foreground" data-testid="lan-xet-dang-tai-lai">
            {RELOADING}
          </span>
        ) : null}
      </div>
      {notYet ? <p className="text-xs text-muted-foreground">{ACTION_NOT_YET}</p> : null}

      {s.latest_run?.config_changed_since_run ? <Banner testId="bang-cau-hinh-doi">{CONFIG_CHANGED_BANNER}</Banner> : null}
      {s.quota_table.status === "draft" ? (
        <Banner testId="bang-chi-tieu-nhap">{quotaTableDraftBanner(s.academic_year)}</Banner>
      ) : null}
      {s.status === "cancelled" ? <Banner testId="bang-da-huy">{CANCELLED_FLOORS_NOTE}</Banner> : null}

      <section className="space-y-2 rounded-md border p-4 text-sm" data-testid="lan-xet-tom-tat">
        <div>
          Số điểm sàn: <span data-testid="lan-xet-so-san">{s.floors.length}</span>
        </div>
        <div className="space-y-1">
          <div className="font-medium">Lượt kiểm gần nhất</div>
          <LatestRunSummary run={s.latest_run} testId="lan-xet-luot" />
        </div>
        {s.latest_done_run_id === null ? (
          <p className="text-muted-foreground" data-testid="lan-xet-chua-luot-xong">
            {NO_DONE_RUN}
          </p>
        ) : null}
      </section>

      <CancelReviewSessionDialog
        open={cancelOpen && actions.includes("cancel")}
        onOpenChange={setCancelOpen}
        sessionId={s.id}
        version={s.version}
        seqNo={s.seq_no}
        academicYear={s.academic_year}
        busy={busy}
      />
    </div>
  )
}
