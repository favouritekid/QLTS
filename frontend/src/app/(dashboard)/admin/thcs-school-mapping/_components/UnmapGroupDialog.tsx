/**
 * UnmapGroupDialog — huỷ ghép một nhóm. KHÔNG gỡ trường đã áp vào hồ sơ.
 */

"use client"

import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

import { useUnmapThcsGroup } from "@/lib/hooks/useThcsSchoolMapping"
import { parseApiError } from "@/lib/utils/api-errors"
import type { ThcsNameGroup } from "@/lib/zod/thcs-school-mapping"

interface Props {
  group: ThcsNameGroup | null
  onOpenChange: (open: boolean) => void
}

export function UnmapGroupDialog({ group, onOpenChange }: Props) {
  const mutation = useUnmapThcsGroup()

  const handleUnmap = async () => {
    if (!group) return
    try {
      await mutation.mutateAsync(group.normalized_name)
      toast.success(`Đã huỷ ghép “${group.normalized_name}”`)
    } catch (e) {
      toast.error(parseApiError(e, "Huỷ ghép thất bại"))
    } finally {
      onOpenChange(false)
    }
  }

  return (
    <AlertDialog open={group != null} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Huỷ ghép “{group?.normalized_name}”</AlertDialogTitle>
          <AlertDialogDescription>
            Bỏ liên kết nhóm tên này với {group?.mapping?.school_name}. Hồ sơ ĐÃ được
            áp ghép trước đó vẫn giữ trường đã gắn — muốn đổi thì sửa từng hồ sơ.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Không</AlertDialogCancel>
          <AlertDialogAction onClick={handleUnmap} disabled={mutation.isPending}>
            Huỷ ghép
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
