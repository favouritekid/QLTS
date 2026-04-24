// src/app/(dashboard)/admissions/_components/dialogs/BulkAssignDialog.tsx
/**
 * BulkAssignDialog - Dialog for bulk assigning admission profiles to an officer
 */

"use client"

import { useState } from "react"
import { UserPlus, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Label } from "@/components/ui/label"

import { useAdminUsersList } from "@/hooks/useAdminUsers"

interface BulkAssignDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedCount: number
  onConfirm: (officerId: number) => void
  isLoading?: boolean
}

export function BulkAssignDialog({
  open,
  onOpenChange,
  selectedCount,
  onConfirm,
  isLoading = false,
}: BulkAssignDialogProps) {
  const [selectedOfficerId, setSelectedOfficerId] = useState<string>("")

  // Fetch active officers only. Backend /admissions/bulk/assign now
  // rejects non-officer and inactive targets, so surfacing admin/manager
  // in the dropdown would guarantee a 400 on submit.
  const { data: usersData, isLoading: usersLoading } = useAdminUsersList({
    page: 1,
    page_size: 100,
    status: "active",
    role: "officer",
  })

  // Defensive second pass in case the API returns an extra role through
  // pagination edge cases; keep only officer + active.
  const officers = usersData?.users?.filter(
    (user) => user.role === "officer" && user.status === "active"
  ) || []

  const handleSubmit = () => {
    if (!selectedOfficerId) return
    onConfirm(parseInt(selectedOfficerId, 10))
  }

  const handleClose = () => {
    setSelectedOfficerId("")
    onOpenChange(false)
  }

  return (
    <ResponsiveDialog open={open} onOpenChange={handleClose}>
      <ResponsiveDialogContent className="sm:max-w-[425px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-primary" />
            Phân công hàng loạt
          </ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Phân công <strong>{selectedCount}</strong> hồ sơ tuyển sinh cho cán bộ xử lý.
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="officer">
              Chọn cán bộ phụ trách <span className="text-error-500">*</span>
            </Label>
            <Select
              value={selectedOfficerId}
              onValueChange={setSelectedOfficerId}
              disabled={usersLoading}
            >
              <SelectTrigger>
                <SelectValue placeholder={usersLoading ? "Đang tải…" : "Chọn cán bộ"} />
              </SelectTrigger>
              <SelectContent>
                {officers.length === 0 ? (
                  <div className="p-2 text-sm text-muted-foreground">
                    Không có cán bộ nào
                  </div>
                ) : (
                  officers.map((officer) => (
                    <SelectItem key={officer.id} value={officer.id.toString()}>
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {officer.full_name || officer.username}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {officer.email}
                        </span>
                      </div>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Cán bộ được phân công sẽ phụ trách xử lý các hồ sơ đã chọn
            </p>
          </div>
        </div>

        <ResponsiveDialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isLoading}>
            Hủy
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading || !selectedOfficerId || officers.length === 0}
          >
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Phân công {selectedCount} hồ sơ
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  )
}
