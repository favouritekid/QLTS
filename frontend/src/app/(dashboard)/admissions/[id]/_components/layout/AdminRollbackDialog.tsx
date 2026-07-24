"use client"

/**
 * C2 — Admin rollback về nháp + entry-point ĐỔI NGÀNH.
 *
 * Tách RIÊNG khỏi ProfileActionMenu để hook react-query ``useAdminRollback``
 * CHỈ chạy khi admin thực sự có quyền (parent render component này CÓ ĐIỀU KIỆN
 * ``can("admin_rollback")``). Nếu để hook ngay trong ProfileActionMenu thì mọi
 * test render ProfileActionMenu / AdmissionHeader (transitive) bị ép phải bọc
 * QueryClientProvider → "No QueryClient set".
 */

import {
  AuditReasonDialog,
  pushRecentReason,
} from "@/components/admissions/AuditReasonDialog"
import { useAdminRollback } from "@/hooks/admissions"

interface AdminRollbackDialogProps {
  profileId: number
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AdminRollbackDialog({
  profileId,
  open,
  onOpenChange,
}: AdminRollbackDialogProps) {
  const mutation = useAdminRollback(profileId)

  const handleConfirm = (reason: string, allowMajorChange: boolean) => {
    mutation.mutate(
      { reason, allow_major_change: allowMajorChange },
      {
        onSuccess: () => {
          pushRecentReason("admin_rollback", reason)
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <AuditReasonDialog
      action="admin_rollback"
      open={open}
      onOpenChange={onOpenChange}
      onConfirm={handleConfirm}
      isSubmitting={mutation.isPending}
      showMajorChangeToggle
    />
  )
}
