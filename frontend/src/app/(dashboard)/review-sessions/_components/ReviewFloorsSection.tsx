"use client"

import type { Dispatch, SetStateAction } from "react"

import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { floorScoreDisplay, lastFloorSave, type FloorDraft } from "@/lib/review-sessions/floor-draft"
import {
  DELETED_LABEL,
  FLOORS_EMPTY,
  FLOORS_SECTION_TITLE,
  annualQuotaLabel,
  floorsLastSaved,
  majorLabel,
  userRef,
} from "@/lib/review-sessions/messages"
import type { ReviewFloor } from "@/lib/zod/review-sessions"

import { ReviewFloorsEditor } from "./ReviewFloorsEditor"

/**
 * Chế độ XEM (thiết kế §3.4): bảng `floors` của E3 — Ngành · Loại hình · Nhóm · Chỉ tiêu năm (`null` ⇒ "Chưa cấu hình", `0` ⇒
 * "0 — đóng tuyệt đối") · Điểm sàn (chuỗi máy chủ, dấu phẩy) · nhãn "Đã xoá". Owner G2: MỘT dòng chung "lưu lần cuối bởi … lúc …",
 * KHÔNG cột "người sửa" cho từng dòng.
 */
function FloorsView({ floors }: { floors: readonly ReviewFloor[] }) {
  const last = lastFloorSave(floors)
  if (last === null) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="san-rong">
        {FLOORS_EMPTY}
      </p>
    )
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground" data-testid="san-luu-lan-cuoi">
        {floorsLastSaved(userRef(last.userId), formatDateTimeVN(last.at))}
      </p>
      <Table data-testid="san-bang-xem">
        <TableHeader>
          <TableRow>
            <TableHead>Ngành</TableHead>
            <TableHead>Loại hình</TableHead>
            <TableHead>Nhóm</TableHead>
            <TableHead>Chỉ tiêu năm</TableHead>
            <TableHead>Điểm sàn</TableHead><TableHead>Người sửa</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {floors.map((f) => (
            <TableRow key={f.offering_academic_info_id} data-testid={`san-xem-${f.offering_academic_info_id}`}>
              <TableCell>
                {majorLabel(f.major_code, f.major_name)}
                {f.is_deleted ? (
                  <Badge variant="destructive" className="ml-2">
                    {DELETED_LABEL}
                  </Badge>
                ) : null}
              </TableCell>
              <TableCell>{f.offering_type ?? "—"}</TableCell>
              <TableCell>{f.group_code ?? "—"}</TableCell>
              <TableCell data-testid={`san-xem-chi-tieu-${f.offering_academic_info_id}`}>
                {annualQuotaLabel(f.annual_admission_quota)}
              </TableCell>
              <TableCell data-testid={`san-xem-diem-${f.offering_academic_info_id}`}>{floorScoreDisplay(f.floor_score)}</TableCell><TableCell>{userRef(f.updated_by_user_id)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

interface Props {
  sessionId: number
  /** `floors` của E3 đang xem (chế độ xem) */
  floors: readonly ReviewFloor[]
  /** đang soạn VÀ E3 còn trả `edit_floors` — màn cha quyết (theo `available_actions`) */
  editing: boolean
  busy: boolean
  draft: FloorDraft
  onDraftChange: Dispatch<SetStateAction<FloorDraft>>
  onCloseEditor: () => void
}

/** M3 — thẻ "Điểm sàn": xem (E3) hoặc soạn (E10 + E4). Bản soạn do màn cha giữ (khuôn F01-4). */
export function ReviewFloorsSection({ sessionId, floors, editing, busy, draft, onDraftChange, onCloseEditor }: Props) {
  return (
    <section className="space-y-3 rounded-md border p-4" data-testid="san">
      <h2 className="text-lg font-semibold">{FLOORS_SECTION_TITLE}</h2>
      {editing ? (
        <ReviewFloorsEditor
          sessionId={sessionId}
          busy={busy}
          draft={draft}
          onDraftChange={onDraftChange}
          onClose={onCloseEditor}
        />
      ) : (
        <FloorsView floors={floors} />
      )}
    </section>
  )
}
