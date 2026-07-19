// src/app/(dashboard)/admissions/[id]/_components/EnrollmentLetterButton.tsx
"use client"

import { useState } from "react"
import { Download, FileText, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { usePermissions } from "@/hooks/usePermissions"
import {
  useDownloadEnrollmentLetter,
  useEnrollmentLetters,
  useIssueEnrollmentLetter,
} from "@/hooks/admissions/useEnrollmentLetter"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface Props {
  profile: AdmissionProfileResponse
}

/** "19/07/2026 14:30" — hiển thị mốc phát hành theo giờ địa phương. */
function formatIssuedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/**
 * Officer/manager/admin action: issue the official "Giấy báo nhập học" PDF.
 * Self-gating on the backend permission flag `issue_enrollment_letter` (thin
 * client — no role/status checks here). Opens a dialog to enter the two
 * enrollment-window dates, then downloads the returned PDF. The backend is
 * authoritative on eligibility + the date range; the client-side end>=start
 * check is only to fail fast before the request.
 *
 * Dialog cũng liệt kê các bản ĐÃ PHÁT kèm nút tải lại. Không có lối tải lại
 * thì officer làm mất file (đóng nhầm tab, máy in kẹt) chỉ còn cách bấm "Xuất
 * PDF" lần nữa — mà mỗi lần bấm sinh thêm một bản CHÍNH THỨC mới, không khử
 * trùng lặp. Tải lại biến sự cố vặt thành thao tác đọc thay vì phát hành mới.
 */
export function EnrollmentLetterButton({ profile }: Props) {
  const { can } = usePermissions(profile)
  const [open, setOpen] = useState(false)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const mutation = useIssueEnrollmentLetter(profile.id)
  // Chỉ nạp khi dialog mở — danh sách này không cần cho lần render đầu của trang.
  const letters = useEnrollmentLetters(profile.id, open)
  const download = useDownloadEnrollmentLetter(profile.id)

  if (!can("issue_enrollment_letter")) return null

  const rangeInvalid = Boolean(startDate && endDate && endDate < startDate)
  const canSubmit =
    Boolean(startDate) && Boolean(endDate) && !rangeInvalid && !mutation.isPending
  const issued = letters.data ?? []

  // Đóng dialog GIỮ NGUYÊN 2 ngày đã nhập: officer thường mở ra xem lại danh
  // sách rồi đóng, gõ lại ngày mỗi lần là phiền vô ích. Chỉ xoá sau khi phát
  // hành thành công (lần sau là một đợt khác).
  const handleOpenChange = (next: boolean) => setOpen(next)

  const handleSubmit = () => {
    if (!canSubmit) return
    mutation.mutate(
      { enrollmentStartDate: startDate, enrollmentEndDate: endDate },
      {
        onSuccess: () => {
          setStartDate("")
          setEndDate("")
          setOpen(false)
        },
      },
    )
  }

  return (
    <>
      <Button variant="outline" className="gap-2" onClick={() => setOpen(true)}>
        <FileText className="h-4 w-4" aria-hidden="true" />
        Xuất giấy báo nhập học
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Xuất giấy báo nhập học</DialogTitle>
            <DialogDescription>
              Nhập khoảng thời gian thí sinh lên trường làm thủ tục. Giấy báo sẽ
              được tạo dưới dạng PDF để tải về.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label htmlFor="el-start-date">Từ ngày</Label>
              <Input
                id="el-start-date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="el-end-date">Đến ngày</Label>
              <Input
                id="el-end-date"
                type="date"
                value={endDate}
                min={startDate || undefined}
                onChange={(e) => setEndDate(e.target.value)}
                aria-invalid={rangeInvalid}
              />
            </div>
            {rangeInvalid && (
              <p className="text-destructive text-sm" role="alert">
                Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu.
              </p>
            )}

            {issued.length > 0 && (
              <div className="border-t pt-3">
                <p className="text-muted-foreground mb-2 text-sm font-medium">
                  Đã phát {issued.length} bản — tải lại thay vì xuất bản mới:
                </p>
                <ul className="max-h-40 space-y-1 overflow-y-auto">
                  {issued.map((letter) => (
                    <li
                      key={letter.id}
                      className="flex items-center justify-between gap-2 text-sm"
                    >
                      <span className="text-muted-foreground truncate">
                        {formatIssuedAt(letter.generated_at)}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 shrink-0 gap-1.5"
                        disabled={download.isPending}
                        onClick={() => download.mutate(letter.id)}
                      >
                        <Download className="h-3.5 w-3.5" aria-hidden="true" />
                        Tải lại
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => handleOpenChange(false)}
            >
              Đóng
            </Button>
            <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
              {mutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              )}
              Xuất PDF
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
