"use client"

import type { ReactNode } from "react"
import Link from "next/link"

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { academicInfoRef, majorLabel, tabLabel } from "@/lib/review-sessions/messages"
import {
  PRIOR_YEAR_TITLE,
  PROFILE_GONE,
  documentGapsText,
  ethnicPriorityLabel,
  flagLabel,
  hintLabel,
  labelList,
  numberLabel,
  perChoiceStatusLabel,
  priorYearLine,
  profileStatusLabel,
  reasonLabel,
  scoreLabel,
  unitRef,
  withinSeatsLabel,
} from "@/lib/review-sessions/row-labels"
import type { ReviewRow, ReviewRun } from "@/lib/zod/review-sessions"

type QuotaMajor = NonNullable<ReviewRun["quota_view"]>["majors"][number]

/** [ĐX] */
export const ROW_DRAWER_NO_PRIOR = "(không có)"
/** [ĐX] */
export const ROW_DRAWER_OPEN_PROFILE = "Mở hồ sơ"

function Field({ label, testId, children }: { label: string; testId: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span data-testid={testId}>{children}</span>
    </div>
  )
}

/**
 * M6 — ngăn chi tiết MỘT em (thiết kế §3.7). Dữ liệu = ĐÚNG dòng E9 đã có (KHÔNG gọi thêm). Mọi trường hiện NGUYÊN giá trị máy chủ:
 * điểm là chuỗi (chỉ đổi dấu thập phân), `null` ⇒ "—" (không thành 0), mã lạ ⇒ câu chung có mã; từng nguyện vọng theo ĐÚNG thứ tự
 * máy chủ trả (không sắp lại), nhãn ngành ghép theo `offering_academic_info_id` với `quota_view.majors` CÙNG lượt (trình bày).
 * Giao diện KHÔNG cộng điểm thành phần. Ô chọn của Ban thư ký (C2) gắn ở F5.
 */
export function ReviewRowDrawer({
  row,
  majors,
  onClose,
}: {
  row: ReviewRow | null
  majors: readonly QuotaMajor[]
  onClose: () => void
}) {
  const byId = new Map(majors.map((m) => [m.offering_academic_info_id, m] as const))
  const majorOf = (id: number | null) => {
    if (id === null) return "—"
    const m = byId.get(id)
    return m ? majorLabel(m.major_code, m.major_name) : academicInfoRef(id)
  }
  return (
    <Sheet open={row !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid="ngan-chi-tiet">
        {row !== null ? (
          <>
            <SheetHeader>
              <SheetTitle data-testid="ngan-ten">{row.full_name ?? PROFILE_GONE}</SheetTitle>
              <SheetDescription data-testid="ngan-dau">
                Trạng thái hồ sơ lúc chạy: {profileStatusLabel(row.profile_status)} · Đơn vị: {unitRef(row.unit_id)} · Nhóm:{" "}
                {tabLabel(row.tab)}
              </SheetDescription>
            </SheetHeader>
            <div className="mt-4 space-y-4">
              {row.full_name !== null ? (
                <Link
                  href={`/admissions/${row.profile_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm underline"
                  data-testid="ngan-mo-ho-so"
                >
                  {ROW_DRAWER_OPEN_PROFILE}
                </Link>
              ) : null}

              <section className="space-y-1">
                <Field label="Lý do" testId="ngan-ly-do">
                  {labelList(row.reason_codes, reasonLabel)}
                </Field>
                <Field label="Cờ" testId="ngan-co">
                  {labelList(row.flags, flagLabel)}
                </Field>
                <Field label="Gợi ý" testId="ngan-goi-y">
                  {labelList(row.decision_hints, hintLabel)}
                </Field>
              </section>

              <section className="space-y-1">
                <Field label="Tổng điểm xét" testId="ngan-tong">
                  {scoreLabel(row.review_total)}
                </Field>
                <Field label="Tổng môn" testId="ngan-tong-mon">
                  {scoreLabel(row.score_parts?.subject_total ?? null)}
                </Field>
                <Field label="Ưu tiên khu vực" testId="ngan-kv">
                  {scoreLabel(row.score_parts?.area ?? null)}
                </Field>
                <Field label="Ưu tiên đối tượng" testId="ngan-doi-tuong">
                  {scoreLabel(row.score_parts?.object ?? null)}
                </Field>
                <Field label="Ưu tiên (sau trần)" testId="ngan-uu-tien">
                  {scoreLabel(row.score_parts?.priority_total ?? null)}
                </Field>
                <Field label="Điểm sàn" testId="ngan-san">
                  {scoreLabel(row.floor_score)}
                </Field>
                <Field label="Hạng trong ngành" testId="ngan-hang">
                  {numberLabel(row.rank_in_major)}
                </Field>
                <Field label="Số chỗ" testId="ngan-so-cho">
                  {withinSeatsLabel(row.within_seats)}
                </Field>
                <Field label="Ưu tiên dân tộc" testId="ngan-dan-toc">
                  {ethnicPriorityLabel(row.ethnic_priority_state)}
                </Field>
                <Field label="Giấy thiếu / chưa duyệt" testId="ngan-giay">
                  {documentGapsText(row)}
                </Field>
              </section>

              <section className="space-y-1">
                <div className="text-sm font-medium">Từng nguyện vọng</div>
                {row.per_choice.length === 0 ? (
                  <p className="text-sm text-muted-foreground">—</p>
                ) : (
                  <Table data-testid="ngan-nv">
                    <TableHeader>
                      <TableRow>
                        <TableHead>NV</TableHead>
                        <TableHead>Ngành</TableHead>
                        <TableHead>Trạng thái</TableHead>
                        <TableHead>Lý do</TableHead>
                        <TableHead>Tổng điểm</TableHead>
                        <TableHead>Sàn lúc chạy</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {row.per_choice.map((c) => (
                        <TableRow key={c.choice_id} data-testid={`ngan-nv-${c.choice_id}`}>
                          <TableCell>NV{c.display_order}</TableCell>
                          <TableCell>{majorOf(c.offering_academic_info_id)}</TableCell>
                          <TableCell>{perChoiceStatusLabel(c.status)}</TableCell>
                          <TableCell>{labelList(c.reason_codes, reasonLabel)}</TableCell>
                          <TableCell>{scoreLabel(c.review_total)}</TableCell>
                          <TableCell>{scoreLabel(c.floor_score)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </section>

              <section className="space-y-1" data-testid="ngan-nam-truoc">
                <div className="text-sm font-medium">{PRIOR_YEAR_TITLE}</div>
                {row.prior_year_findings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{ROW_DRAWER_NO_PRIOR}</p>
                ) : (
                  <ul className="list-disc pl-5 text-sm">
                    {row.prior_year_findings.map((f, i) => (
                      <li key={`${f.year}-${f.basis}-${i}`}>{priorYearLine(f)}</li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
