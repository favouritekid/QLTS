"use client"

/**
 * GĐ1b K2 (§4.7) — lịch sử MỘT giấy theo `document_row_id` + tệp bằng chứng. Chỉ mở khi máy chủ trả `can_view_history`
 * (người gọi quyết); máy chủ vẫn là chốt: 404 ⇒ "không xem được". Giờ hiển thị cố định múi Việt Nam.
 * Tải tệp bằng chứng: 410 `EVIDENCE_FILE_MISSING` ⇒ báo "không còn", làm mới lịch sử (máy chủ đã đánh dấu).
 */
import { useState } from "react"
import axios from "axios"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useDocumentHistory, useDownloadEvidence } from "@/hooks/document-review/useDocumentReview"
import {
  documentStatusLabel,
  formatDateTimeVN,
  formatLabel,
  historyActionLabel,
  viaLabel,
} from "@/lib/document-review/messages"

interface Props {
  profileId: number
  documentRowId: number
  label: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DocumentHistoryDialog({ profileId, documentRowId, label, open, onOpenChange }: Props) {
  const history = useDocumentHistory(profileId, documentRowId, open)
  const evidence = useDownloadEvidence(profileId, documentRowId)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const downloading = evidence.isPending ? evidence.variables : null

  const download = (evidenceId: number) => {
    setDownloadError(null)
    evidence.mutate(evidenceId, {
      onError: (e) => {
        if (axios.isAxiosError(e) && e.response?.status === 410) {
          setDownloadError("Tệp bằng chứng không còn trên máy chủ — đã ghi nhận tệp mất.")
        } else if (axios.isAxiosError(e) && e.response?.status === 404) {
          setDownloadError("Không tải được tệp bằng chứng này (không có hoặc ngoài phạm vi của bạn).")
        } else {
          setDownloadError("Không tải được tệp bằng chứng — thử lại sau.")
        }
      },
    })
  }

  const notFound = axios.isAxiosError(history.error) && history.error.response?.status === 404

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Lịch sử giấy</DialogTitle>
          <DialogDescription>«{label}»</DialogDescription>
        </DialogHeader>

        {history.isLoading && <p className="text-sm text-muted-foreground">Đang tải lịch sử…</p>}
        {history.isError && (
          <p role="alert" className="text-sm text-destructive">
            {notFound ? "Không xem được lịch sử giấy này." : "Không tải được lịch sử — thử lại sau."}
          </p>
        )}

        {history.data && (
          <div className="space-y-4">
            <p className="text-sm">
              Trạng thái hiện tại: <strong>{documentStatusLabel(history.data.status)}</strong>
            </p>

            {history.data.entries.length === 0 ? (
              <p className="text-sm text-muted-foreground">Chưa có thao tác nào được ghi.</p>
            ) : (
              <ol className="space-y-2" data-testid="lich-su-giay">
                {history.data.entries.map((en) => (
                  <li key={en.id} className="rounded-md border p-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{historyActionLabel(en.action)}</span>
                      {en.via && <Badge variant="outline">{viaLabel(en.via)}</Badge>}
                      {en.unknown_submitter_ack && <Badge variant="warning">Có cam kết không rõ người nhận</Badge>}
                      <span className="text-muted-foreground">{formatDateTimeVN(en.at)}</span>
                    </div>
                    <div className="text-muted-foreground">
                      {en.actor_name ?? (en.actor_user_id != null ? `Người dùng #${en.actor_user_id}` : "Không rõ người thao tác")}
                      {en.old_status || en.new_status
                        ? ` · ${documentStatusLabel(en.old_status)} → ${documentStatusLabel(en.new_status)}`
                        : ""}
                    </div>
                    {(en.declared_format || en.verified_format) && (
                      <div>
                        Hình thức lúc nhận: {formatLabel(en.declared_format)}
                        {en.verified_format ? ` · đã xác nhận: ${formatLabel(en.verified_format)}` : ""}
                      </div>
                    )}
                    {en.reason && <div>Lý do: {en.reason}</div>}
                    {en.batch_id && <div className="text-xs text-muted-foreground">Mã lô: {en.batch_id}</div>}
                    {en.grant_id != null && <div className="text-xs text-muted-foreground">Quyền duyệt chéo #{en.grant_id}</div>}
                  </li>
                ))}
              </ol>
            )}

            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Tệp bằng chứng</h3>
              {history.data.evidence_files.length === 0 ? (
                <p className="text-sm text-muted-foreground">Không có tệp bằng chứng.</p>
              ) : (
                <ul className="space-y-1" data-testid="tep-bang-chung">
                  {history.data.evidence_files.map((ev) => (
                    <li key={ev.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span>Duyệt lúc {formatDateTimeVN(ev.verified_at)}</span>
                      {ev.sha256 && <code className="text-xs">{ev.sha256.slice(0, 12)}…</code>}
                      {ev.file_missing ? (
                        <Badge variant="error">Tệp không còn</Badge>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => download(ev.id)}
                          disabled={evidence.isPending}
                        >
                          {downloading === ev.id ? "Đang tải…" : "Tải tệp"}
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {downloadError && (
                <p role="alert" className="text-sm text-destructive">
                  {downloadError}
                </p>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
