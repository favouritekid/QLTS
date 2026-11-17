"use client"

/**
 * Hộp chứa luồng lô (`BulkVerifyFlow`). Gắn hộp chỉ khi mở (`open` ⇒ dựng mới) để mỗi lần mở là một luồng sạch.
 * ⚠️ Nút mở hộp này ở `/admissions` ("Duyệt giấy theo bộ lọc hiện tại") và `DocumentChecklist` ("Xác nhận kiểm tra")
 * CHỜ biên bản đo nền V4.
 */
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { BulkEndpoint, BulkSelection } from "@/hooks/document-review/useBulkVerify"

import { BulkVerifyFlow } from "./BulkVerifyFlow"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  endpoint: BulkEndpoint
  selection: BulkSelection
  title: string
  scopeLabel: string
  allowOptional?: boolean
}

export function BulkVerifyDialog({ open, onOpenChange, endpoint, selection, title, scopeLabel, allowOptional }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Kết quả được ghi theo từng hồ sơ. Đóng hộp không huỷ lô — tra lại ở mục &quot;Lô duyệt giấy của tôi&quot;.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <BulkVerifyFlow
            endpoint={endpoint}
            selection={selection}
            scopeLabel={scopeLabel}
            allowOptional={allowOptional}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
