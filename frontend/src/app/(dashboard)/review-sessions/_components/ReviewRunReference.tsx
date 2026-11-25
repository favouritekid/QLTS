"use client"

import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { floorScoreDisplay } from "@/lib/review-sessions/floor-draft"
import {
  MAJOR_INACTIVE_LABEL,
  OFFERING_INACTIVE_LABEL,
  RUN_FLOORS_USED_EMPTY,
  RUN_NO_SUMMARY,
  WOULD_EXCEED_LABEL,
  academicInfoRef,
  annualQuotaLabel,
  majorLabel,
  quotaStateLabel,
  usedBreakdown,
} from "@/lib/review-sessions/messages"
import type { ReviewRun } from "@/lib/zod/review-sessions"

type QuotaView = NonNullable<ReviewRun["quota_view"]>
type QuotaMajor = QuotaView["majors"][number]

/** `null` ⇒ "—" (không đổi thành 0 — `frontend/CLAUDE.md` "Default business values"); số ⇒ NGUYÊN số máy chủ. */
function numberOrDash(n: number | null): string {
  return n === null ? "—" : String(n)
}

/**
 * Thẻ "Chỉ tiêu tham khảo" (thiết kế §3.6) — `quota_view` của lượt kiểm, NGUYÊN số máy chủ trả: chỉ tiêu năm (`null` ⇒ "Chưa cấu
 * hình", `0` ⇒ "0 — đóng tuyệt đối"), đã dùng (kèm "theo công bố …, theo “Phê duyệt” cũ …"), còn lại `remaining`, sàn lúc chạy,
 * trạng thái `state`, ứng viên / máy đề xuất / cần quyết, cờ đang ngừng. Nhóm: trần, đã dùng, máy đề xuất lượt này, còn sau đề xuất
 * (`remaining_after_auto`, có thể ÂM), "Sẽ vượt trần" khi `would_exceed` — CHỈ cảnh báo (QĐB:25), không chặn gì.
 * KHÔNG tự tính "còn lại" hay cộng số nào.
 */
export function RunQuotaView({ view }: { view: QuotaView | null }) {
  if (view === null) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="cttk-chua-co">
        {RUN_NO_SUMMARY}
      </p>
    )
  }
  return (
    <div className="space-y-4" data-testid="cttk">
      <Table data-testid="cttk-nganh">
        <TableHeader>
          <TableRow>
            <TableHead>Ngành</TableHead>
            <TableHead>Loại hình</TableHead>
            <TableHead>Nhóm</TableHead>
            <TableHead>Chỉ tiêu năm</TableHead>
            <TableHead>Đã dùng</TableHead>
            <TableHead>Còn lại</TableHead>
            <TableHead>Sàn lúc chạy</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead>Ứng viên</TableHead>
            <TableHead>Máy đề xuất</TableHead>
            <TableHead>Cần quyết</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {view.majors.map((m) => {
            const id = m.offering_academic_info_id
            return (
              <TableRow key={id} data-testid={`cttk-${id}`}>
                <TableCell>
                  {majorLabel(m.major_code, m.major_name)}
                  {m.major_inactive ? (
                    <Badge variant="outline" className="ml-2" data-testid={`cttk-${id}-nganh-ngung`}>
                      {MAJOR_INACTIVE_LABEL}
                    </Badge>
                  ) : null}
                  {m.offering_inactive ? (
                    <Badge variant="outline" className="ml-2" data-testid={`cttk-${id}-loai-hinh-ngung`}>
                      {OFFERING_INACTIVE_LABEL}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell>{m.offering_type ?? "—"}</TableCell>
                <TableCell>{m.group_code ?? "—"}</TableCell>
                <TableCell data-testid={`cttk-${id}-chi-tieu`}>{annualQuotaLabel(m.annual_admission_quota)}</TableCell>
                <TableCell data-testid={`cttk-${id}-da-dung`}>
                  {m.used}
                  <span className="block text-xs text-muted-foreground">{usedBreakdown(m.used_publish, m.used_approved)}</span>
                </TableCell>
                <TableCell data-testid={`cttk-${id}-con-lai`}>{numberOrDash(m.remaining)}</TableCell>
                <TableCell data-testid={`cttk-${id}-san`}>{m.floor_score === null ? "—" : floorScoreDisplay(m.floor_score)}</TableCell>
                <TableCell data-testid={`cttk-${id}-trang-thai`}>{quotaStateLabel(m.state)}</TableCell>
                <TableCell>{m.candidates}</TableCell>
                <TableCell>{m.auto}</TableCell>
                <TableCell>{m.needs_decision}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <Table data-testid="cttk-nhom">
        <TableHeader>
          <TableRow>
            <TableHead>Nhóm</TableHead>
            <TableHead>Trần</TableHead>
            <TableHead>Đã dùng</TableHead>
            <TableHead>Máy đề xuất lượt này</TableHead>
            <TableHead>Còn sau đề xuất</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {view.groups.map((g) => (
            <TableRow key={g.group_id} data-testid={`cttk-nhom-${g.group_id}`}>
              <TableCell>
                {g.code} — {g.name}
              </TableCell>
              <TableCell>{g.ceiling}</TableCell>
              <TableCell>
                {g.used}
                <span className="block text-xs text-muted-foreground">{usedBreakdown(g.used_publish, g.used_approved)}</span>
              </TableCell>
              <TableCell>{g.auto_in_run}</TableCell>
              <TableCell data-testid={`cttk-nhom-${g.group_id}-con-sau`}>
                {g.remaining_after_auto}
                {g.would_exceed ? (
                  <Badge variant="warning" className="ml-2" data-testid={`cttk-nhom-${g.group_id}-vuot-tran`}>
                    {WOULD_EXCEED_LABEL}
                  </Badge>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/**
 * Thẻ "Điểm sàn đã dùng" (thiết kế §3.6) — `inputs.floors` (ảnh chụp GIÁ TRỊ lúc chạy, bất biến — P4): id học vụ + mức; nhãn ngành
 * ghép theo id với `quota_view.majors` của CÙNG lượt (trình bày); không có ⇒ "Học vụ #id".
 */
export function RunFloorsUsed({
  floors,
  majors,
}: {
  floors: ReviewRun["inputs"]["floors"]
  majors: readonly QuotaMajor[]
}) {
  if (floors.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="san-da-dung-rong">
        {RUN_FLOORS_USED_EMPTY}
      </p>
    )
  }
  const byId = new Map(majors.map((m) => [m.offering_academic_info_id, m] as const))
  return (
    <Table data-testid="san-da-dung">
      <TableHeader>
        <TableRow>
          <TableHead>Ngành</TableHead>
          <TableHead>Loại hình</TableHead>
          <TableHead>Điểm sàn</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {floors.map((f) => {
          const m = byId.get(f.offering_academic_info_id)
          return (
            <TableRow key={f.offering_academic_info_id} data-testid={`san-da-dung-${f.offering_academic_info_id}`}>
              <TableCell>{m ? majorLabel(m.major_code, m.major_name) : academicInfoRef(f.offering_academic_info_id)}</TableCell>
              <TableCell>{m?.offering_type ?? "—"}</TableCell>
              <TableCell>{floorScoreDisplay(f.floor_score)}</TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
