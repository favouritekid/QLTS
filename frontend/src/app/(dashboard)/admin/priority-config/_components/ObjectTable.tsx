/**
 * ObjectTable — UT (đối tượng) bonus rates per academic_year.
 *
 * Q9 #07 PR3 admin FE — TT 05/2021 priority object config CRUD.
 *
 * UT row identifier is the composite (group_code, sub_code) — e.g.
 * UT1/04, UT2/06. The BE enforces uniqueness per (year, sub_code) so
 * we keep group_code as a small input that defaults to UT1.
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
  useCreatePriorityObject,
  usePriorityObjects,
  useRetirePriorityObject,
  useUpdatePriorityObject,
} from "@/lib/hooks/usePriorityConfig"
import {
  priorityObjectConfigCreateSchema,
  priorityObjectConfigUpdateSchema,
  type PriorityObjectConfigResponse,
} from "@/lib/zod/priority-config"

interface ObjectTableProps {
  academicYear: number
}

interface ObjectFormState {
  group_code: string
  sub_code: string
  description: string
  bonus_points: string
  evidence_doc_type: string
}

const EMPTY_FORM: ObjectFormState = {
  group_code: "UT1",
  sub_code: "",
  description: "",
  bonus_points: "0",
  evidence_doc_type: "",
}

export function ObjectTable({ academicYear }: ObjectTableProps) {
  const { data: rows, isLoading } = usePriorityObjects(academicYear)
  const createMutation = useCreatePriorityObject(academicYear)
  const updateMutation = useUpdatePriorityObject()
  const retireMutation = useRetirePriorityObject()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<ObjectFormState>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [retireTarget, setRetireTarget] = useState<PriorityObjectConfigResponse | null>(
    null,
  )

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setDialogOpen(true)
  }

  const openEdit = (row: PriorityObjectConfigResponse) => {
    setEditingId(row.id)
    setForm({
      group_code: row.group_code,
      sub_code: row.sub_code,
      description: row.description,
      bonus_points: String(row.bonus_points),
      evidence_doc_type: row.evidence_doc_type ?? "",
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
        const parsed = priorityObjectConfigCreateSchema.safeParse({
          academic_year: academicYear,
          group_code: form.group_code.trim(),
          sub_code: form.sub_code.trim(),
          description: form.description.trim(),
          bonus_points: bonus,
          evidence_doc_type: form.evidence_doc_type.trim() || null,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await createMutation.mutateAsync(parsed.data)
        toast.success(`Đã tạo ${parsed.data.group_code}/${parsed.data.sub_code}`)
      } else {
        const parsed = priorityObjectConfigUpdateSchema.safeParse({
          description: form.description.trim(),
          bonus_points: bonus,
          evidence_doc_type: form.evidence_doc_type.trim() || null,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await updateMutation.mutateAsync({
          objectId: editingId,
          data: parsed.data,
        })
        toast.success(`Đã cập nhật UT #${editingId}`)
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
      toast.success(`Đã ngưng ${retireTarget.group_code}/${retireTarget.sub_code}`)
    } catch (error) {
      const msg =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Ngưng UT thất bại"
      toast.error(typeof msg === "string" ? msg : "Ngưng UT thất bại")
    } finally {
      setRetireTarget(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Đối tượng (UT)</h3>
          <p className="text-muted-foreground text-sm">
            Cộng điểm theo đối tượng ưu tiên (TT 05/2021 Phụ lục 01)
          </p>
        </div>
        <Button size="sm" onClick={openCreate} data-testid="object-add-btn">
          <Plus className="mr-1 h-4 w-4" />
          Thêm UT
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : !rows || rows.length === 0 ? (
        <div className="text-muted-foreground rounded-md border py-8 text-center text-sm">
          Chưa có đối tượng nào cho năm {academicYear}. Bấm &quot;Seed
          Defaults&quot; để khởi tạo TT 05/2021.
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">Nhóm</TableHead>
                <TableHead className="w-[80px]">Mã</TableHead>
                <TableHead>Mô tả</TableHead>
                <TableHead className="w-[120px] text-right">Điểm cộng</TableHead>
                <TableHead className="w-[100px] text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-testid={`object-row-${row.group_code}-${row.sub_code}`}
                >
                  <TableCell>
                    <Badge variant="secondary" className="font-mono">
                      {row.group_code}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono">{row.sub_code}</TableCell>
                  <TableCell className="max-w-[400px] truncate">
                    {row.description}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {Number(row.bonus_points).toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(row)}
                        aria-label={`Sửa ${row.group_code}/${row.sub_code}`}
                        data-testid={`object-edit-${row.group_code}-${row.sub_code}`}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setRetireTarget(row)}
                        aria-label={`Ngưng ${row.group_code}/${row.sub_code}`}
                        data-testid={`object-retire-${row.group_code}-${row.sub_code}`}
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

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingId == null ? "Thêm đối tượng" : `Sửa UT #${editingId}`}
            </DialogTitle>
            <DialogDescription>
              Năm học {academicYear}. group_code: UT1/UT2; sub_code: 2 chữ số
              (VD: 01, 04, 07).
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="object-group">Nhóm</Label>
                <Input
                  id="object-group"
                  value={form.group_code}
                  disabled={editingId != null}
                  onChange={(e) =>
                    setForm((s) => ({ ...s, group_code: e.target.value }))
                  }
                  placeholder="UT1"
                  data-testid="object-form-group"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="object-sub">Mã (2 chữ số)</Label>
                <Input
                  id="object-sub"
                  value={form.sub_code}
                  disabled={editingId != null}
                  onChange={(e) =>
                    setForm((s) => ({ ...s, sub_code: e.target.value }))
                  }
                  placeholder="04"
                  maxLength={2}
                  data-testid="object-form-sub"
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="object-desc">Mô tả</Label>
              <Textarea
                id="object-desc"
                value={form.description}
                onChange={(e) =>
                  setForm((s) => ({ ...s, description: e.target.value }))
                }
                placeholder="Anh hùng LLVTND, anh hùng lao động..."
                rows={2}
                data-testid="object-form-desc"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="object-bonus">Điểm cộng</Label>
              <Input
                id="object-bonus"
                type="number"
                step="0.25"
                min="0"
                max="99.99"
                value={form.bonus_points}
                onChange={(e) =>
                  setForm((s) => ({ ...s, bonus_points: e.target.value }))
                }
                data-testid="object-form-bonus"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="object-evidence">Loại chứng từ (tùy chọn)</Label>
              <Input
                id="object-evidence"
                value={form.evidence_doc_type}
                onChange={(e) =>
                  setForm((s) => ({ ...s, evidence_doc_type: e.target.value }))
                }
                placeholder="VD: anh_hung_certificate"
                maxLength={100}
                data-testid="object-form-evidence"
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
              data-testid="object-form-submit"
            >
              {editingId == null ? "Tạo" : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={!!retireTarget}
        onOpenChange={(open) => !open && setRetireTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận ngưng UT</AlertDialogTitle>
            <AlertDialogDescription>
              Ngưng {retireTarget?.group_code}/{retireTarget?.sub_code}? Hồ sơ
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
