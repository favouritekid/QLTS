/**
 * AreaTable — KV (Khu vực) bonus rates per academic_year.
 *
 * Q9 #07 PR3 admin FE — TT 05/2021 priority area config CRUD.
 *
 * Renders the active KV rows for the selected year. Each row supports
 * inline edit (bonus_points + area_name + description), retire
 * (effective_to = today), and a "Thêm mới" dialog for new codes.
 *
 * The component trusts BE to return only currently-active rows when
 * `activeOnly=true` (default) — no client-side filter.
 */

"use client"

import { useState } from "react"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
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
import { Skeleton } from "@/components/ui/skeleton"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

import {
  useCreatePriorityArea,
  usePriorityAreas,
  useRetirePriorityArea,
  useUpdatePriorityArea,
} from "@/lib/hooks/usePriorityConfig"
import {
  priorityAreaConfigCreateSchema,
  priorityAreaConfigUpdateSchema,
  type PriorityAreaConfigResponse,
} from "@/lib/zod/priority-config"

interface AreaTableProps {
  academicYear: number
}

interface AreaFormState {
  area_code: string
  area_name: string
  bonus_points: string
  description: string
}

const EMPTY_FORM: AreaFormState = {
  area_code: "",
  area_name: "",
  bonus_points: "0",
  description: "",
}

export function AreaTable({ academicYear }: AreaTableProps) {
  const { data: rows, isLoading } = usePriorityAreas(academicYear)
  const createMutation = useCreatePriorityArea(academicYear)
  const updateMutation = useUpdatePriorityArea()
  const retireMutation = useRetirePriorityArea()

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<AreaFormState>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)

  // Retire confirm
  const [retireTarget, setRetireTarget] = useState<PriorityAreaConfigResponse | null>(
    null,
  )

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setDialogOpen(true)
  }

  const openEdit = (row: PriorityAreaConfigResponse) => {
    setEditingId(row.id)
    setForm({
      area_code: row.area_code,
      area_name: row.area_name,
      bonus_points: String(row.bonus_points),
      description: row.description ?? "",
    })
    setFormError(null)
    setDialogOpen(true)
  }

  const handleSubmit = async () => {
    setFormError(null)
    const bonus = Number(form.bonus_points)
    if (Number.isNaN(bonus)) {
      setFormError("Điểm cộng phải là số")
      return
    }

    try {
      if (editingId == null) {
        const parsed = priorityAreaConfigCreateSchema.safeParse({
          academic_year: academicYear,
          area_code: form.area_code.trim(),
          area_name: form.area_name.trim(),
          bonus_points: bonus,
          description: form.description.trim() || null,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await createMutation.mutateAsync(parsed.data)
        toast.success(`Đã tạo ${parsed.data.area_code}`)
      } else {
        const parsed = priorityAreaConfigUpdateSchema.safeParse({
          area_name: form.area_name.trim(),
          bonus_points: bonus,
          description: form.description.trim() || null,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await updateMutation.mutateAsync({ areaId: editingId, data: parsed.data })
        toast.success(`Đã cập nhật KV #${editingId}`)
      }
      setDialogOpen(false)
    } catch (error) {
      const msg =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Thao tác thất bại"
      setFormError(typeof msg === "string" ? msg : "Thao tác thất bại")
    }
  }

  const handleRetireConfirm = async () => {
    if (!retireTarget) return
    try {
      await retireMutation.mutateAsync(retireTarget.id)
      toast.success(`Đã ngưng ${retireTarget.area_code}`)
    } catch (error) {
      const msg =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Ngưng KV thất bại"
      toast.error(typeof msg === "string" ? msg : "Ngưng KV thất bại")
    } finally {
      setRetireTarget(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Khu vực (KV)</h3>
          <p className="text-muted-foreground text-sm">
            Cộng điểm theo khu vực trường THPT (TT 05/2021 Phụ lục 01)
          </p>
        </div>
        <Button size="sm" onClick={openCreate} data-testid="area-add-btn">
          <Plus className="mr-1 h-4 w-4" />
          Thêm KV
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : !rows || rows.length === 0 ? (
        <div className="text-muted-foreground rounded-md border py-8 text-center text-sm">
          Chưa có khu vực nào cho năm {academicYear}. Bấm &quot;Seed
          Defaults&quot; để khởi tạo TT 05/2021.
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[110px]">Mã KV</TableHead>
                <TableHead>Tên</TableHead>
                <TableHead className="w-[120px] text-right">Điểm cộng</TableHead>
                <TableHead>Mô tả</TableHead>
                <TableHead className="w-[100px] text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} data-testid={`area-row-${row.area_code}`}>
                  <TableCell>
                    <Badge variant="secondary" className="font-mono">
                      {row.area_code}
                    </Badge>
                  </TableCell>
                  <TableCell>{row.area_name}</TableCell>
                  <TableCell className="text-right font-mono">
                    {Number(row.bonus_points).toFixed(2)}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-[300px] truncate">
                    {row.description ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(row)}
                        aria-label={`Sửa ${row.area_code}`}
                        data-testid={`area-edit-${row.area_code}`}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setRetireTarget(row)}
                        aria-label={`Ngưng ${row.area_code}`}
                        data-testid={`area-retire-${row.area_code}`}
                      >
                        <Trash2 className="text-destructive h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingId == null ? "Thêm khu vực" : `Sửa KV #${editingId}`}
            </DialogTitle>
            <DialogDescription>
              Năm học {academicYear}. Mã KV theo TT 05/2021: KV1, KV2-NT, KV2, KV3.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid gap-2">
              <Label htmlFor="area-code">Mã KV</Label>
              <Input
                id="area-code"
                value={form.area_code}
                disabled={editingId != null}
                onChange={(e) =>
                  setForm((s) => ({ ...s, area_code: e.target.value }))
                }
                placeholder="KV1 / KV2-NT / KV2 / KV3"
                data-testid="area-form-code"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="area-name">Tên</Label>
              <Input
                id="area-name"
                value={form.area_name}
                onChange={(e) =>
                  setForm((s) => ({ ...s, area_name: e.target.value }))
                }
                placeholder="Khu vực 1"
                data-testid="area-form-name"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="area-bonus">Điểm cộng</Label>
              <Input
                id="area-bonus"
                type="number"
                step="0.25"
                min="0"
                max="99.99"
                value={form.bonus_points}
                onChange={(e) =>
                  setForm((s) => ({ ...s, bonus_points: e.target.value }))
                }
                data-testid="area-form-bonus"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="area-desc">Mô tả</Label>
              <Textarea
                id="area-desc"
                value={form.description}
                onChange={(e) =>
                  setForm((s) => ({ ...s, description: e.target.value }))
                }
                placeholder="Tuỳ chọn"
                rows={2}
                data-testid="area-form-desc"
              />
            </div>

            {formError && (
              <p className="text-destructive text-sm" role="alert">
                {formError}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={createMutation.isPending || updateMutation.isPending}
            >
              Hủy
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={createMutation.isPending || updateMutation.isPending}
              data-testid="area-form-submit"
            >
              {editingId == null ? "Tạo" : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Retire confirm */}
      <AlertDialog
        open={!!retireTarget}
        onOpenChange={(open) => !open && setRetireTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận ngưng KV</AlertDialogTitle>
            <AlertDialogDescription>
              Ngưng {retireTarget?.area_code} ({retireTarget?.area_name})? Hồ sơ
              đã snapshot sẽ không bị ảnh hưởng — chỉ ngừng áp dụng cho hồ sơ
              mới.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleRetireConfirm}
            >
              Ngưng
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
