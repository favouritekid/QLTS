// src/app/(dashboard)/admissions/_components/dialogs/BulkAssignDialog.tsx
/**
 * BulkAssignDialog - Dialog for bulk assigning admission profiles to an officer
 */

"use client"

import { useState } from "react"
import { UserPlus, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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

  // Fetch officers
  const { data: usersData, isLoading: usersLoading } = useAdminUsersList({
    page: 1,
    page_size: 100,
    status: "active",
  })

  // Filter for officers and admins
  const officers = usersData?.users?.filter(
    (user) => user.role === "officer" || user.role === "admin" || user.role === "manager" // architecture-allow legacy
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
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-primary" />
            Phân công hàng loạt
          </DialogTitle>
          <DialogDescription>
            Phân công <strong>{selectedCount}</strong> hồ sơ tuyển sinh cho cán bộ xử lý.
          </DialogDescription>
        </DialogHeader>

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
                <SelectValue placeholder={usersLoading ? "Đang tải..." : "Chọn cán bộ"} />
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

        <DialogFooter>
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
