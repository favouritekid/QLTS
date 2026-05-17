/**
 * SeedDefaultsButton — populate TT 05/2021 baseline rates for a year.
 *
 * Idempotent on the BE side: if any active row already exists for the
 * year, the call returns skipped_existing=true and inserts nothing.
 * We surface that distinction in the toast so admin knows whether to
 * delete-then-re-seed.
 */

"use client"

import { useState } from "react"
import { Sparkles } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
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

import { useSeedPriorityDefaults } from "@/lib/hooks/usePriorityConfig"

interface SeedDefaultsButtonProps {
  academicYear: number
}

export function SeedDefaultsButton({ academicYear }: SeedDefaultsButtonProps) {
  const seedMutation = useSeedPriorityDefaults()
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleConfirm = async () => {
    try {
      const result = await seedMutation.mutateAsync({ academic_year: academicYear })
      if (result.skipped_existing) {
        toast.info(`Năm ${academicYear} đã có cấu hình`, {
          description: "Bỏ qua seed vì đã tồn tại KV/UT đang hoạt động.",
        })
      } else {
        toast.success(`Đã khởi tạo TT 05/2021 cho năm ${academicYear}`, {
          description: `${result.inserted_areas} KV + ${result.inserted_objects} UT`,
        })
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Seed thất bại"
      toast.error(typeof msg === "string" ? msg : "Seed thất bại")
    } finally {
      setConfirmOpen(false)
    }
  }

  return (
    <>
      <Button
        variant="default"
        size="sm"
        onClick={() => setConfirmOpen(true)}
        disabled={seedMutation.isPending}
        data-testid="seed-defaults-btn"
      >
        <Sparkles className="mr-1 h-4 w-4" />
        Khởi tạo TT 05/2021
      </Button>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Khởi tạo cấu hình ưu tiên?</AlertDialogTitle>
            <AlertDialogDescription>
              Tạo bộ KV/UT mặc định theo TT 05/2021-BLĐTBXH cho năm{" "}
              {academicYear} (4 KV + 7 UT). Nếu năm đã có cấu hình, thao tác
              này sẽ tự động bỏ qua.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirm}>
              Khởi tạo
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
