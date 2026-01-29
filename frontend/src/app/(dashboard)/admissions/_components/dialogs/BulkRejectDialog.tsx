// src/app/(dashboard)/admissions/_components/dialogs/BulkRejectDialog.tsx
/**
 * BulkRejectDialog - Dialog for bulk rejecting admission profiles
 */

"use client"

import { useState } from "react"
import { AlertTriangle } from "lucide-react"

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
import { Textarea } from "@/components/ui/textarea"

interface BulkRejectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedCount: number
  onConfirm: (reason: string) => void
  isLoading?: boolean
}

export function BulkRejectDialog({
  open,
  onOpenChange,
  selectedCount,
  onConfirm,
  isLoading = false,
}: BulkRejectDialogProps) {
  const [reason, setReason] = useState("")
  const [error, setError] = useState("")

  const handleSubmit = () => {
    if (reason.trim().length < 10) {
      setError("Lý do từ chối phải có ít nhất 10 ký tự")
      return
    }
    setError("")
    onConfirm(reason.trim())
  }

  const handleClose = () => {
    setReason("")
    setError("")
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-error-500" />
            Từ chối hàng loạt
          </DialogTitle>
          <DialogDescription>
            Bạn sắp từ chối <strong>{selectedCount}</strong> hồ sơ tuyển sinh.
            Vui lòng nhập lý do từ chối.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="reason">
              Lý do từ chối <span className="text-error-500">*</span>
            </Label>
            <Textarea
              id="reason"
              placeholder="Nhập lý do từ chối (ít nhất 10 ký tự)..."
              value={reason}
              onChange={(e) => {
                setReason(e.target.value)
                if (error) setError("")
              }}
              rows={4}
              className={error ? "border-error-500" : ""}
            />
            {error && (
              <p className="text-sm text-error-500">{error}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {reason.length}/1000 ký tự
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={handleClose}
            disabled={isLoading}
          >
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={handleSubmit}
            disabled={isLoading || reason.trim().length < 10}
          >
            {isLoading ? "Đang xử lý..." : `Từ chối ${selectedCount} hồ sơ`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
