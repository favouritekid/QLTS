/**
 * CloneFromYearDialog — copy ACTIVE KV/UT rows year→year.
 *
 * BE is idempotent: rows that already exist active in `to_year` are
 * skipped silently, so admin can re-run after a partial seed without
 * harm. Toast surfaces the actual `cloned_areas` + `cloned_objects`
 * counts.
 */

"use client"

import { useState } from "react"
import { Copy } from "lucide-react"
import { toast } from "sonner"

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

import { useClonePriorityConfig } from "@/lib/hooks/usePriorityConfig"
import { priorityConfigCloneRequestSchema } from "@/lib/zod/priority-config"

interface CloneFromYearDialogProps {
  defaultToYear: number
}

export function CloneFromYearDialog({ defaultToYear }: CloneFromYearDialogProps) {
  const cloneMutation = useClonePriorityConfig()
  const [open, setOpen] = useState(false)
  const [fromYear, setFromYear] = useState<string>(String(defaultToYear - 1))
  const [toYear, setToYear] = useState<string>(String(defaultToYear))
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setError(null)
    const parsed = priorityConfigCloneRequestSchema.safeParse({
      from_year: Number(fromYear),
      to_year: Number(toYear),
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
      return
    }

    try {
      const result = await cloneMutation.mutateAsync(parsed.data)
      toast.success(
        `Đã sao chép từ ${parsed.data.from_year} sang ${parsed.data.to_year}`,
        {
          description: `${result.cloned_areas} KV + ${result.cloned_objects} UT`,
        },
      )
      setOpen(false)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Sao chép thất bại"
      setError(typeof msg === "string" ? msg : "Sao chép thất bại")
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setFromYear(String(defaultToYear - 1))
          setToYear(String(defaultToYear))
          setError(null)
          setOpen(true)
        }}
        data-testid="clone-from-year-btn"
      >
        <Copy className="mr-1 h-4 w-4" />
        Sao chép từ năm khác
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sao chép cấu hình ưu tiên</DialogTitle>
            <DialogDescription>
              Copy toàn bộ KV/UT đang hoạt động từ một năm sang năm khác. Mã
              nào đã tồn tại ở năm đích sẽ được giữ nguyên (không ghi đè).
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="clone-from">Từ năm</Label>
              <Input
                id="clone-from"
                type="number"
                min="2020"
                max="2100"
                value={fromYear}
                onChange={(e) => setFromYear(e.target.value)}
                data-testid="clone-from-input"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="clone-to">Sang năm</Label>
              <Input
                id="clone-to"
                type="number"
                min="2020"
                max="2100"
                value={toYear}
                onChange={(e) => setToYear(e.target.value)}
                data-testid="clone-to-input"
              />
            </div>
          </div>

          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={cloneMutation.isPending}
            >
              Hủy
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={cloneMutation.isPending}
              data-testid="clone-submit-btn"
            >
              Sao chép
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
