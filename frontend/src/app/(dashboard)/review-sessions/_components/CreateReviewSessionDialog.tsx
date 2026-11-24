"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { useCreateReviewSession, useReviewRounds } from "@/lib/hooks/use-review-sessions"
import {
  CREATE_NOTE,
  CREATE_UNCERTAIN,
  describeReviewSessionError,
  quotaTableHref,
  quotaTableLinkLabel,
  roundStateLabel,
} from "@/lib/review-sessions/messages"
import { reviewSessionHref } from "@/lib/review-sessions/url"
import type { ReviewRoundOption } from "@/lib/zod/review-sessions"

import { ReviewErrorAlert } from "./ReviewErrorAlert"
import { yearOptions } from "./years"

const SELECT_CLASS = "h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultYear: number
}

/**
 * M1 — hộp "Tạo lần xét" (E1). Chọn năm ⇒ tải đợt của năm ⇒ chọn đợt ⇒ Tạo. Đợt nào được chọn do MÁY CHỦ quyết (owner G1:
 * được đợt "Ngừng", không được đợt đã lưu trữ — chặn ở máy chủ); giao diện chỉ hiện nhãn tình trạng đợt, không ẩn / khoá đợt nào.
 * Nội dung chỉ dựng khi hộp mở ⇒ mở lại là bắt đầu sạch.
 */
export function CreateReviewSessionDialog({ open, onOpenChange, defaultYear }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="hop-tao-lan-xet">
        <DialogHeader>
          <DialogTitle>Tạo lần xét nháp</DialogTitle>
          <DialogDescription>{CREATE_NOTE}</DialogDescription>
        </DialogHeader>
        {open ? <CreateReviewSessionForm defaultYear={defaultYear} onClose={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  )
}

interface CreateErrorView {
  message: string
  /** năm lấy từ `academic_year` trong THÂN 409 `REVIEW_QUOTA_TABLE_MISSING` (đính chính 2 §3) */
  quotaYear: number | null
}

/**
 * Lỗi E1 (thiết kế §3.2): 409 thiếu bảng ⇒ câu máy chủ + liên kết bảng chỉ tiêu năm ấy; mất kết nối / 5xx (trừ đóng băng) ⇒ "chưa
 * rõ đã tạo hay chưa"; còn lại theo bảng chung §5. Rẽ nhánh theo MÃ.
 */
function createErrorView(error: unknown): CreateErrorView {
  const v = describeReviewSessionError(error, "write")
  if (v.errorCode === "REVIEW_QUOTA_TABLE_MISSING") {
    const y = v.data?.academic_year
    return { message: v.message, quotaYear: typeof y === "number" && Number.isInteger(y) ? y : null }
  }
  if (v.kind === "uncertain" || (v.kind !== "frozen" && v.status !== undefined && v.status >= 500)) {
    return { message: CREATE_UNCERTAIN, quotaYear: null }
  }
  return { message: v.message, quotaYear: null }
}

function CreateReviewSessionForm({ defaultYear, onClose }: { defaultYear: number; onClose: () => void }) {
  const router = useRouter()
  const [year, setYear] = useState(defaultYear)
  const [roundId, setRoundId] = useState("")
  const rounds = useReviewRounds(year)
  const create = useCreateReviewSession()

  const roundItems: ReviewRoundOption[] = rounds.isError ? [] : (rounds.data?.items ?? [])
  // Đợt đã chọn phải còn trong danh sách MỚI NHẤT (sau 400 `review_round_invalid` danh sách được tải lại).
  const roundSelected = roundItems.some((r) => String(r.id) === roundId)
  const canSubmit = roundSelected && !create.isPending && !rounds.isFetching
  const err = create.error ? createErrorView(create.error) : null

  const submit = () => {
    create.mutate(
      { academic_year: year, admission_round_id: Number(roundId) },
      {
        onSuccess: (session) => {
          onClose()
          router.push(reviewSessionHref(session.id))
        },
      },
    )
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <Label htmlFor="tao-nam">Năm tuyển sinh</Label>
        <select
          id="tao-nam"
          data-testid="tao-nam"
          className={SELECT_CLASS}
          value={year}
          disabled={create.isPending}
          onChange={(e) => {
            setYear(Number(e.target.value))
            setRoundId("")
            create.reset()
          }}
        >
          {yearOptions(year).map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <Label htmlFor="tao-dot">Đợt</Label>
        {rounds.isError ? (
          <ReviewErrorAlert testId="tao-dot-loi" message={describeReviewSessionError(rounds.error, "read").message} />
        ) : !rounds.data ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="tao-dot-dang-tai">
            <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách đợt…
          </p>
        ) : roundItems.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="tao-dot-rong">
            Năm {year} chưa có đợt tuyển sinh nào.
          </p>
        ) : (
          <select
            id="tao-dot"
            data-testid="tao-dot"
            className={SELECT_CLASS}
            value={roundSelected ? roundId : ""}
            disabled={create.isPending}
            onChange={(e) => {
              setRoundId(e.target.value)
              create.reset()
            }}
          >
            <option value="">— Chọn đợt —</option>
            {roundItems.map((r) => (
              <option key={r.id} value={String(r.id)}>
                {`${r.round_name} (${r.round_code}) — ${roundStateLabel(r)}`}
              </option>
            ))}
          </select>
        )}
      </div>

      {err ? (
        <ReviewErrorAlert testId="tao-loi" message={err.message}>
          {err.quotaYear !== null ? (
            <Link href={quotaTableHref(err.quotaYear)} className="font-medium underline" data-testid="tao-lien-ket-bang-chi-tieu">
              {quotaTableLinkLabel(err.quotaYear)}
            </Link>
          ) : null}
        </ReviewErrorAlert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={create.isPending}>
          Bỏ
        </Button>
        <Button type="button" onClick={submit} disabled={!canSubmit} data-testid="tao-xac-nhan">
          {create.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Tạo
        </Button>
      </DialogFooter>
    </div>
  )
}
