"use client"

import { useState, type Dispatch, type SetStateAction } from "react"
import { Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { usePutReviewFloors, useReviewFloorCandidates } from "@/lib/hooks/use-review-sessions"
import {
  EMPTY_FLOOR_DRAFT,
  buildFloorsPlan,
  floorDraftConflicts,
  floorDraftText,
  floorIdsFromValidation,
  floorScoreDisplay,
  groupFloorCandidates,
  idListFrom,
  normalizeFloorInput,
  type FloorDraft,
} from "@/lib/review-sessions/floor-draft"
import {
  DELETED_LABEL,
  FLOOR_EMPTY_VALUE,
  FLOOR_GROUP_TITLE,
  FLOOR_INPUT_INVALID,
  FLOOR_NOT_APPLICABLE_NOTE,
  FLOORS_BAD_MEMBER_HINT,
  FLOORS_COL_MINE,
  FLOORS_COL_SAVED,
  FLOORS_CONFIRM_EMPTY,
  FLOORS_CONFIRM_EMPTY_NO,
  FLOORS_CONFIRM_EMPTY_NOTE,
  FLOORS_CONFIRM_EMPTY_YES,
  FLOORS_DISCARD,
  FLOORS_INVALID_422,
  FLOORS_LOADING,
  FLOORS_NOT_EDITABLE,
  FLOORS_SAVE_MINE,
  FLOORS_SAVED,
  FLOORS_STALE_NO_DIFF,
  FLOORS_STALE_NOTE,
  FLOORS_STALE_TITLE,
  FLOORS_USE_NEW,
  INACTIVE_LABEL,
  NOT_REVIEWABLE_HINT,
  RELOADING,
  annualQuotaLabel,
  describeReviewSessionError,
  floorCandidatesEmpty,
  floorDroppedNote,
  floorsSaveLabel,
  floorsTooMany,
  majorLabel,
  quotaStateLabel,
} from "@/lib/review-sessions/messages"
import { FLOORS_MAX_ITEMS, type ReviewFloorCandidate, type ReviewFloorIn } from "@/lib/zod/review-sessions"

import { ReviewErrorAlert } from "./ReviewErrorAlert"

interface Props {
  sessionId: number
  /** E3 đang tải lại ⇒ khoá nút ghi (khuôn F1) */
  busy: boolean
  /** Bản soạn — do màn cha GIỮ (ngoài nhánh dữ liệu / lỗi của E3 và E10), khuôn F01-4. Thành phần này không giữ bản sao. */
  draft: FloorDraft
  onDraftChange: Dispatch<SetStateAction<FloorDraft>>
  /** rời chế độ soạn (màn cha) */
  onClose: () => void
}

/** Câu lỗi E4 (thiết kế §3.4 bảng lỗi): mã đã biết ⇒ câu máy chủ (STALE, NOT_DRAFT, `bad_member`, …); 422 ⇒ câu riêng; còn lại §5. */
function saveErrorText(error: unknown): string {
  const v = describeReviewSessionError(error, "write")
  if (v.kind === "invalid") return FLOORS_INVALID_422
  if (v.reasonCode === "review_floor_bad_member") return `${v.message}\n${FLOORS_BAD_MEMBER_HINT}`
  return v.message
}

const HEADERS = ["Ngành", "Loại hình", "Nhóm", "Chỉ tiêu", "Điểm sàn", "Trạng thái"] as const

function FloorRow(props: {
  item: ReviewFloorCandidate
  text: string
  flagged: boolean
  inputDisabled: boolean
  onText: (id: number, text: string) => void
}) {
  const { item, text, flagged, inputDisabled, onText } = props
  const id = item.offering_academic_info_id
  const invalid = item.floor_accepted && normalizeFloorInput(text).kind === "invalid"
  const label = majorLabel(item.major_code, item.major_name)
  return (
    <TableRow
      data-testid={`san-dong-${id}`}
      data-flagged={flagged ? "true" : undefined}
      className={flagged ? "bg-destructive/10" : undefined}
    >
      <TableCell>
        {label}
        {item.major_inactive || item.offering_inactive ? (
          <Badge variant="outline" className="ml-2">
            {INACTIVE_LABEL}
          </Badge>
        ) : null}
        {item.is_deleted ? (
          <Badge variant="destructive" className="ml-2">
            {DELETED_LABEL}
          </Badge>
        ) : null}
      </TableCell>
      <TableCell>{item.offering_type ?? "—"}</TableCell>
      <TableCell>{item.group_code ?? "—"}</TableCell>
      <TableCell data-testid={`san-chi-tieu-${id}`}>{annualQuotaLabel(item.annual_admission_quota)}</TableCell>
      <TableCell>
        {item.floor_accepted ? (
          <div className="space-y-1">
            <Input
              data-testid={`san-o-${id}`}
              aria-label={`Điểm sàn ${label}`}
              aria-invalid={invalid || flagged}
              inputMode="decimal"
              className="w-28"
              value={text}
              disabled={inputDisabled}
              onChange={(e) => onText(id, e.target.value)}
            />
            {invalid ? (
              <p className="text-xs text-destructive" data-testid={`san-o-loi-${id}`}>
                {FLOOR_INPUT_INVALID}
              </p>
            ) : null}
            {item.floor_applicable ? null : <p className="text-xs text-muted-foreground">{FLOOR_NOT_APPLICABLE_NOTE}</p>}
          </div>
        ) : item.floor_score !== null ? (
          <span className="text-sm text-destructive" data-testid={`san-bo-khi-luu-${id}`}>
            {floorDroppedNote(floorScoreDisplay(item.floor_score))}
          </span>
        ) : (
          "—"
        )}
      </TableCell>
      <TableCell data-testid={`san-trang-thai-${id}`}>{quotaStateLabel(item.state)}</TableCell>
    </TableRow>
  )
}

/**
 * M3 — soạn điểm sàn (E10 đọc, E4 ghi). Thin client:
 *  - danh sách + nhóm + ô nhập theo CỜ máy chủ của E10 (`floor_applicable`, `floor_accepted`, `state`) — xem `floor-draft.ts`;
 *  - "Lưu" gửi TOÀN BỘ danh sách (thay toàn bộ) + `session_version` của CHÍNH ảnh chụp E10 đang soạn (phụ lục E10 §1.1); cho phép
 *    soạn khi E10 trả `edit_floors` (cùng hàm với E3 / cổng ghi); danh sách rỗng ⇒ hỏi lại; quá 500 dòng ⇒ khoá "Lưu";
 *  - E10 tải lỗi (kể cả 429) ⇒ hiện LỖI, không vẽ bảng cũ (DC-1); bản soạn KHÔNG mất (nằm ở màn cha);
 *  - lỗi E4: 409 STALE ⇒ GIỮ bản soạn + bảng so + "Dùng bản mới" / "Lưu bản của tôi đè lên" (gửi `version` mới); 409 NOT_DRAFT ⇒ rời
 *    chế độ soạn + câu máy chủ; 400 `bad_member` / `duplicate` ⇒ câu máy chủ + tô đúng id; 422 ⇒ tô theo `loc`; đóng băng / mất kết
 *    nối ⇒ §5, giữ bản soạn. Làm mới E2 / E3 / E7 / E8 / E10 khi E4 kết thúc do hook lo (bất kể kết quả).
 */
export function ReviewFloorsEditor(props: Props) {
  const { sessionId, busy, onClose } = props
  const [draft, onDraftChange] = useState<FloorDraft>(props.draft)
  const q = useReviewFloorCandidates(sessionId)
  const put = usePutReviewFloors(sessionId)
  const [confirmEmpty, setConfirmEmpty] = useState(false)

  const discard = () => {
    put.reset()
    onDraftChange(EMPTY_FLOOR_DRAFT)
    onClose()
  }

  if (q.isError) {
    return (
      <div className="space-y-2">
        <ReviewErrorAlert testId="san-tai-loi" message={describeReviewSessionError(q.error, "read").message} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="san-tai-lai">
            <RefreshCw className="mr-1 h-4 w-4" />
            Tải lại
          </Button>
          <Button variant="ghost" onClick={discard} data-testid="san-bo">
            {FLOORS_DISCARD}
          </Button>
        </div>
      </div>
    )
  }

  if (!q.data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="san-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> {FLOORS_LOADING}
      </p>
    )
  }

  const c = q.data
  const canEdit = c.available_actions.includes("edit_floors")
  const plan = buildFloorsPlan(c.items, draft.overrides)
  const groups = groupFloorCandidates(c.items)
  const conflicts = draft.staleConflict ? floorDraftConflicts(c.items, draft.overrides) : []
  const tooMany = plan.floors.length > FLOORS_MAX_ITEMS
  const flagged = new Set(draft.flaggedIds)
  const locked = busy || q.isFetching || put.isPending
  const canSave = canEdit && !locked && plan.invalidIds.length === 0 && !tooMany

  const setText = (id: number, text: string) =>
    onDraftChange((d) => ({ ...d, overrides: { ...d.overrides, [id]: text } }))

  const send = (floors: ReviewFloorIn[]) => {
    const sentIds = floors.map((f) => f.offering_academic_info_id)
    put.mutate(
      { version: c.session_version, floors },
      {
        onSuccess: () => {
          onDraftChange(EMPTY_FLOOR_DRAFT)
          onClose()
          toast.success(FLOORS_SAVED)
        },
        onError: (error) => {
          const v = describeReviewSessionError(error, "write")
          if (v.errorCode === "REVIEW_SESSION_STALE") {
            onDraftChange((d) => ({ ...d, staleConflict: true, flaggedIds: [] }))
            return
          }
          if (v.errorCode === "REVIEW_SESSION_NOT_DRAFT") {
            onClose()
            toast.error(v.message)
            return
          }
          const ids =
            v.reasonCode === "review_floor_bad_member"
              ? idListFrom(v.data?.offering_academic_info_ids)
              : v.reasonCode === "review_floor_duplicate"
                ? idListFrom(v.data?.duplicate_offering_academic_info_ids)
                : v.kind === "invalid"
                  ? floorIdsFromValidation(v.data, sentIds)
                  : []
          onDraftChange((d) => ({ ...d, flaggedIds: ids }))
        },
      },
    )
  }

  const save = () => {
    if (!canSave) return
    if (plan.floors.length === 0) {
      setConfirmEmpty(true)
      return
    }
    send(plan.floors)
  }

  const takeSavedVersion = () => {
    put.reset()
    onDraftChange(EMPTY_FLOOR_DRAFT)
  }

  return (
    <div className="space-y-4" data-testid="san-soan">
      {canEdit ? null : (
        <p className="text-sm text-muted-foreground" data-testid="san-khong-sua-duoc">
          {FLOORS_NOT_EDITABLE}
        </p>
      )}
      {c.items.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="san-khong-hoc-vu">
          {floorCandidatesEmpty(c.academic_year)}
        </p>
      ) : null}

      {groups.map((g) =>
        g.items.length ? (
          <div key={g.key} className="space-y-1" data-testid={`san-nhom-${g.key}`}>
            <h3 className="text-sm font-semibold" data-testid={`san-nhom-${g.key}-tieu-de`}>
              {FLOOR_GROUP_TITLE[g.key]} ({g.items.length})
              {g.key === "not_reviewable" ? ` ${NOT_REVIEWABLE_HINT}` : ""}
            </h3>
            <Table>
              <TableHeader>
                <TableRow>
                  {HEADERS.map((h) => (
                    <TableHead key={h}>{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {g.items.map((item) => (
                  <FloorRow
                    key={item.offering_academic_info_id}
                    item={item}
                    text={floorDraftText(item, draft.overrides)}
                    flagged={flagged.has(item.offering_academic_info_id)}
                    inputDisabled={!canEdit || put.isPending}
                    onText={setText}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null,
      )}

      {tooMany ? (
        <p className="text-sm text-destructive" data-testid="san-qua-nhieu">
          {floorsTooMany(plan.floors.length, FLOORS_MAX_ITEMS)}
        </p>
      ) : null}

      {put.error ? <ReviewErrorAlert testId="san-loi" message={saveErrorText(put.error)} /> : null}

      {draft.staleConflict ? (
        <div className="space-y-2 rounded-md border border-warning-500 p-3" data-testid="san-xung-dot">
          <p className="font-medium">{FLOORS_STALE_TITLE}</p>
          {q.isFetching ? (
            // E10 đang tải lại sau 409 ⇒ chưa có "mức vừa lưu" — không so với ảnh chụp cũ.
            <p className="text-sm text-muted-foreground" data-testid="san-so-dang-tai">
              {RELOADING}
            </p>
          ) : conflicts.length ? (
            <>
              <p className="text-sm text-muted-foreground">{FLOORS_STALE_NOTE}</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ngành</TableHead>
                    <TableHead>{FLOORS_COL_MINE}</TableHead>
                    <TableHead>{FLOORS_COL_SAVED}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {conflicts.map((x) => {
                    const mine = normalizeFloorInput(x.mine)
                    return (
                      <TableRow key={x.item.offering_academic_info_id} data-testid={`san-so-${x.item.offering_academic_info_id}`}>
                        <TableCell>{majorLabel(x.item.major_code, x.item.major_name)}</TableCell>
                        <TableCell data-testid={`san-so-cua-toi-${x.item.offering_academic_info_id}`}>
                          {mine.kind === "ok" ? floorScoreDisplay(mine.value) : mine.kind === "empty" ? FLOOR_EMPTY_VALUE : x.mine}
                        </TableCell>
                        <TableCell data-testid={`san-so-vua-luu-${x.item.offering_academic_info_id}`}>
                          {x.saved === null ? FLOOR_EMPTY_VALUE : floorScoreDisplay(x.saved)}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </>
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="san-so-khong-khac">
              {FLOORS_STALE_NO_DIFF}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={takeSavedVersion} disabled={q.isFetching || put.isPending} data-testid="san-dung-ban-moi">
              {FLOORS_USE_NEW}
            </Button>
            <Button onClick={save} disabled={!canSave} data-testid="san-luu-de">
              {FLOORS_SAVE_MINE}
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" onClick={discard} disabled={put.isPending} data-testid="san-bo">
          {FLOORS_DISCARD}
        </Button>
        {draft.staleConflict ? null : (
          <Button onClick={save} disabled={!canSave} data-testid="san-luu">
            {put.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {floorsSaveLabel(plan.floors.length)}
          </Button>
        )}
      </div>

      <AlertDialog open={confirmEmpty} onOpenChange={setConfirmEmpty}>
        <AlertDialogContent data-testid="san-xac-nhan-xoa-het">
          <AlertDialogHeader>
            <AlertDialogTitle>{FLOORS_CONFIRM_EMPTY}</AlertDialogTitle>
            <AlertDialogDescription>{FLOORS_CONFIRM_EMPTY_NOTE}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{FLOORS_CONFIRM_EMPTY_NO}</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={!canSave}
              onClick={() => {
                setConfirmEmpty(false)
                send([])
              }}
              data-testid="san-xoa-het-dong-y"
            >
              {FLOORS_CONFIRM_EMPTY_YES}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
