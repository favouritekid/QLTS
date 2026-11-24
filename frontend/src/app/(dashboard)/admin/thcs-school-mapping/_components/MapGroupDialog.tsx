/**
 * MapGroupDialog — ghép một nhóm tên THCS gõ tay với trường có sẵn trong danh mục.
 * BE chỉ nhận trường THCS / liên cấp THCS-THPT đang hoạt động (lỗi hiện nguyên văn).
 */

"use client"

import { useState } from "react"
import { toast } from "sonner"

import {
  VnSchoolPicker,
  type VnSchoolPickerValue,
} from "@/components/admissions/VnSchoolPicker"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import { useMapThcsGroup } from "@/lib/hooks/useThcsSchoolMapping"
import { parseApiError } from "@/lib/utils/api-errors"
import type { ThcsNameGroup } from "@/lib/zod/thcs-school-mapping"

const EMPTY: VnSchoolPickerValue = {
  school_id: null,
  school_name: "",
  level: null,
  current_kv: null,
}

interface Props {
  group: ThcsNameGroup | null
  onOpenChange: (open: boolean) => void
}

export function MapGroupDialog({ group, onOpenChange }: Props) {
  const [picked, setPicked] = useState<VnSchoolPickerValue>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const mutation = useMapThcsGroup()

  const handleSubmit = async () => {
    if (!group || picked.school_id == null) {
      setError("Chọn một trường trong danh mục")
      return
    }
    setError(null)
    try {
      await mutation.mutateAsync({
        normalized_name: group.normalized_name,
        school_id: picked.school_id,
      })
      toast.success(`Đã ghép “${group.normalized_name}” với ${picked.school_name}`)
      onOpenChange(false)
    } catch (e) {
      setError(parseApiError(e, "Ghép thất bại"))
    }
  }

  return (
    <Dialog open={group != null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ghép nhóm “{group?.normalized_name}”</DialogTitle>
          <DialogDescription>
            Chọn trường THCS (hoặc liên cấp THCS-THPT) trong danh mục. Mọi dòng THCS
            gõ tay có cùng tên chuẩn hoá sẽ được coi là trường này khi áp ghép.
            Hai trường trùng tên ở hai xã: đừng ghép — sửa tay từng hồ sơ.
          </DialogDescription>
        </DialogHeader>
        <VnSchoolPicker
          value={picked}
          onChange={setPicked}
          placeholder="Tìm trường THCS trong danh mục…"
        />
        {error && (
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Hủy
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={mutation.isPending || picked.school_id == null}
          >
            Ghép
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
