"use client"

/**
 * GĐ2-C C2 — ô chọn của Ban thư ký cho MỘT dòng kết quả lần xét. Thành phần ĐỘC LẬP: màn kết quả lần xét (route dòng của GĐ2-B —
 * lát L4, chưa có) sẽ gắn nó vào từng dòng và đưa vào `row` đúng bản xem dòng của máy chủ.
 *
 * Thin client: danh sách loại hiện ra = `row.applicable_kinds` do MÁY CHỦ tính (không tự suy từ tab / cờ); cờ "đang ngừng" chỉ
 * hiện câu nhắc. Gửi `based_on_row_hash` = mã băm của dòng ĐANG HIỆN và `supersedes_id` = lựa chọn hiệu lực ĐANG HIỆN — máy chủ
 * từ chối khi dữ liệu đã đổi (409 `SELECTION_STALE`) hoặc người khác vừa chọn (409 `SELECTION_CHANGED`). Lý do: ô bắt buộc với
 * "Loại khỏi lần này" / "Chờ bổ sung" (owner C6) — nút khoá khi trống, máy chủ vẫn là chốt.
 */
import { useId, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { usePutReviewSelection } from "@/lib/hooks/use-review-selections"
import {
  describeReviewSelectionError,
  INACTIVE_FLAG_WARNING,
  NOTE_REQUIRED_HINT,
  SELECTION_KIND_LABEL,
  STALE_BADGE,
} from "@/lib/review-selections/messages"
import {
  INACTIVE_FLAGS,
  NOTE_MAX_LENGTH,
  SELECTION_KINDS_REASON_REQUIRED,
  type Selection,
  type SelectionKind,
  type SelectionRowInput,
} from "@/lib/zod/review-selections"

export interface ReviewSelectionPickerProps {
  sessionId: number
  row: SelectionRowInput
  /** Lựa chọn HIỆU LỰC hiện tại của hồ sơ (từ `GET …/selections`), `null` = chưa có. */
  current: Selection | null
  onSaved?: (selection: Selection) => void
}

export function hasInactiveFlag(flags: readonly string[]): boolean {
  return flags.some((f) => (INACTIVE_FLAGS as readonly string[]).includes(f))
}

export function ReviewSelectionPicker({ sessionId, row, current, onSaved }: ReviewSelectionPickerProps) {
  const groupId = useId()
  const noteId = useId()
  const [kind, setKind] = useState<SelectionKind | "">("")
  const [note, setNote] = useState("")
  const put = usePutReviewSelection(sessionId)

  const needsNote = kind !== "" && SELECTION_KINDS_REASON_REQUIRED.includes(kind)
  const canSubmit = kind !== "" && (!needsNote || note.trim().length > 0) && !put.isPending

  function submit() {
    if (kind === "") return
    const trimmed = note.trim()
    put.mutate(
      {
        profileId: row.profile_id,
        body: {
          kind,
          based_on_row_hash: row.row_hash,
          supersedes_id: current ? current.id : null,
          note: trimmed.length > 0 ? trimmed : null,
        },
      },
      {
        onSuccess: (saved) => {
          setKind("")
          setNote("")
          onSaved?.(saved)
        },
      },
    )
  }

  return (
    <div className="space-y-3" data-testid="o-chon-thu-ky">
      {hasInactiveFlag(row.flags) && (
        <p role="alert" className="text-sm text-warning-700 dark:text-warning-400" data-testid="canh-bao-dang-ngung">
          {INACTIVE_FLAG_WARNING}
        </p>
      )}

      {current && (
        <div className="space-y-1 text-sm" data-testid="lua-chon-hien-tai">
          <p>
            Đang chọn: <span className="font-medium">{SELECTION_KIND_LABEL[current.kind]}</span>
            {current.is_stale && (
              <Badge variant="warning" className="ml-2">
                {STALE_BADGE}
              </Badge>
            )}
          </p>
          {current.note && <p className="text-muted-foreground">Lý do: {current.note}</p>}
          <p className="text-xs text-muted-foreground">
            {current.decided_by_full_name ?? current.decided_by_username ?? `#${current.decided_by_user_id}`} ·{" "}
            {formatDateTimeVN(current.decided_at)}
          </p>
        </div>
      )}

      {row.applicable_kinds.length === 0 ? (
        <p className="text-sm text-muted-foreground">Hồ sơ này không có lựa chọn nào của Ban thư ký.</p>
      ) : (
        <RadioGroup
          aria-labelledby={groupId}
          value={kind}
          onValueChange={(v) => setKind(v as SelectionKind)}
        >
          <p id={groupId} className="text-sm font-medium">
            Lựa chọn của Ban thư ký
          </p>
          {row.applicable_kinds.map((k) => {
            const itemId = `${groupId}-${k}`
            return (
              <div key={k} className="flex items-center gap-2">
                <RadioGroupItem value={k} id={itemId} />
                <Label htmlFor={itemId}>{SELECTION_KIND_LABEL[k]}</Label>
              </div>
            )
          })}
        </RadioGroup>
      )}

      <div className="space-y-1">
        <Label htmlFor={noteId}>{needsNote ? "Lý do (bắt buộc)" : "Lý do"}</Label>
        <Textarea
          id={noteId}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={NOTE_MAX_LENGTH}
          rows={2}
        />
        <p className="text-xs text-muted-foreground">{NOTE_REQUIRED_HINT}</p>
      </div>

      {put.isError && (
        <p role="alert" className="text-sm text-destructive" data-testid="loi-lua-chon">
          {describeReviewSelectionError(put.error)}
        </p>
      )}

      <Button type="button" onClick={submit} disabled={!canSubmit}>
        {current ? "Đổi lựa chọn" : "Ghi lựa chọn"}
      </Button>
    </div>
  )
}
