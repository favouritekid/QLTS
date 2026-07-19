// src/app/(dashboard)/admissions/[id]/_components/EnrollmentLetterButton.tsx
"use client"

import { useState } from "react"
import { FileText, Loader2 } from "lucide-react"

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
import { useIssueEnrollmentLetter } from "@/hooks/admissions/useEnrollmentLetter"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface Props {
  profile: AdmissionProfileResponse
}

/**
 * Officer/manager/admin action: issue the official "Giấy báo nhập học" PDF.
 * Self-gating on the backend permission flag `issue_enrollment_letter` (thin
 * client — no role/status checks here). Opens a dialog to enter the two
 * enrollment-window dates, then downloads the returned PDF. The backend is
 * authoritative on eligibility + the date range; the client-side end>=start
 * check is only to fail fast before the request.
 */
export function EnrollmentLetterButton({ profile }: Props) {
  const { can } = usePermissions(profile)
  const [open, setOpen] = useState(false)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const mutation = useIssueEnrollmentLetter(profile.id)

  if (!can("issue_enrollment_letter")) return null

  const rangeInvalid = Boolean(startDate && endDate && endDate < startDate)
  const canSubmit =
    Boolean(startDate) && Boolean(endDate) && !rangeInvalid && !mutation.isPending

  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    if (!next) {
      setStartDate("")
      setEndDate("")
    }
  }

  const handleSubmit = () => {
    if (!canSubmit) return
    mutation.mutate(
      { enrollmentStartDate: startDate, enrollmentEndDate: endDate },
      { onSuccess: () => handleOpenChange(false) },
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
