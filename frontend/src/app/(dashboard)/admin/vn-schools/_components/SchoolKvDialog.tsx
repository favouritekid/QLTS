/**
 * SchoolKvDialog — quản lý phân loại KV theo năm của 1 trường (2 cấp).
 *
 * List assignment + form thêm/sửa (kv_code, năm từ-đến, source) + xoá. Overlap
 * năm do BE chặn (400). Tránh nested Radix dialog: form inline trong dialog.
 */

"use client"

import { useState } from "react"
import { Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import {
  useAddKvAssignment,
  useDeleteKvAssignment,
  useKvAssignments,
  useUpdateKvAssignment,
} from "@/lib/hooks/useVnSchoolAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import {
  kvAssignmentCreateSchema,
  kvAssignmentUpdateSchema,
  type KvAssignmentResponse,
  type SchoolResponse,
} from "@/lib/zod/vn-school-admin"

const KV_OPTIONS = ["KV1", "KV2-NT", "KV2", "KV3"] as const

interface Props {
  school: SchoolResponse | null
  onOpenChange: (open: boolean) => void
}

interface KvForm {
  kv_code: string
  from_year: string
  to_year: string
  source: string
}

const EMPTY: KvForm = {
  kv_code: "KV1",
  from_year: "",
  to_year: "",
  source: "manual_admin",
}

export function SchoolKvDialog({ school, onOpenChange }: Props) {
  const schoolId = school?.id ?? null
  const { data: rows, isLoading } = useKvAssignments(schoolId)
  const addMutation = useAddKvAssignment()
  const updateMutation = useUpdateKvAssignment()
  const deleteMutation = useDeleteKvAssignment()

  // State khởi tạo mới mỗi lần component remount (SchoolTable truyền key=school.id
  // → đổi trường = remount = form sạch). Tránh setState đồng bộ trong useEffect
  // (react-hooks: cascading renders).
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<KvForm>(EMPTY)
  const [error, setError] = useState<string | null>(null)

  const busy =
    addMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending

  const startEdit = (a: KvAssignmentResponse) => {
    setEditId(a.id)
    setForm({
      kv_code: a.kv_code,
      from_year: String(a.effective_from_year),
      to_year: a.effective_to_year != null ? String(a.effective_to_year) : "",
      source: a.source,
    })
    setError(null)
  }

  const resetForm = () => {
    setEditId(null)
    setForm(EMPTY)
    setError(null)
  }

  const handleSubmit = async () => {
    if (schoolId == null) return
    setError(null)
    const fromYear = Number(form.from_year)
    if (!form.from_year || Number.isNaN(fromYear)) {
      setError("Năm bắt đầu phải là số")
      return
    }
    const toYear = form.to_year.trim() ? Number(form.to_year) : null
    if (toYear != null && Number.isNaN(toYear)) {
      setError("Năm kết thúc phải là số hoặc để trống")
      return
    }
    try {
      if (editId == null) {
        const parsed = kvAssignmentCreateSchema.safeParse({
          kv_code: form.kv_code,
          effective_from_year: fromYear,
          effective_to_year: toYear,
          source: form.source.trim() || "manual_admin",
        })
        if (!parsed.success) {
          setError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await addMutation.mutateAsync({ schoolId, data: parsed.data })
        toast.success("Đã thêm phân loại KV")
      } else {
        const parsed = kvAssignmentUpdateSchema.safeParse({
          kv_code: form.kv_code,
          effective_from_year: fromYear,
          effective_to_year: toYear,
          source: form.source.trim() || "manual_admin",
        })
        if (!parsed.success) {
          setError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await updateMutation.mutateAsync({ id: editId, data: parsed.data })
        toast.success("Đã cập nhật phân loại KV")
      }
      resetForm()
    } catch (e) {
      setError(parseApiError(e, "Thao tác thất bại"))
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteMutation.mutateAsync(id)
      toast.success("Đã xoá phân loại KV")
      if (editId === id) resetForm()
    } catch (e) {
      toast.error(parseApiError(e, "Xoá thất bại"))
    }
  }

  return (
    <Dialog open={school != null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Phân loại KV theo năm</DialogTitle>
          <DialogDescription>
            {school?.name} — mỗi khoảng năm 1 KV, không chồng lấn. Để trống &quot;Năm
            kết thúc&quot; = đang áp dụng.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[90px]">KV</TableHead>
                <TableHead className="w-[140px]">Năm</TableHead>
                <TableHead>Nguồn</TableHead>
                <TableHead className="w-[90px] text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-4 text-center text-sm">
                    Đang tải…
                  </TableCell>
                </TableRow>
              ) : !rows || rows.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground py-4 text-center text-sm"
                  >
                    Chưa có phân loại KV nào.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-mono">{a.kv_code}</TableCell>
                    <TableCell className="tabular-nums">
                      {a.effective_from_year}–{a.effective_to_year ?? "nay"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {a.source}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => startEdit(a)}
                          disabled={busy}
                          aria-label="Sửa phân loại KV"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(a.id)}
                          disabled={busy}
                          aria-label="Xoá phân loại KV"
                        >
                          <Trash2 className="text-destructive h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Add / Edit form */}
        <div className="space-y-3 rounded-md border bg-muted/30 p-3">
          <p className="text-sm font-medium">
            {editId == null ? "Thêm phân loại KV" : `Sửa phân loại #${editId}`}
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="grid gap-1.5">
              <Label htmlFor="kv-code">KV</Label>
              <Select
                value={form.kv_code}
                onValueChange={(v) => setForm((s) => ({ ...s, kv_code: v }))}
              >
                <SelectTrigger id="kv-code">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KV_OPTIONS.map((kv) => (
                    <SelectItem key={kv} value={kv}>
                      {kv}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="kv-from">Năm bắt đầu</Label>
              <Input
                id="kv-from"
                type="number"
                value={form.from_year}
                onChange={(e) =>
                  setForm((s) => ({ ...s, from_year: e.target.value }))
                }
                placeholder="2025"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="kv-to">Năm kết thúc</Label>
              <Input
                id="kv-to"
                type="number"
                value={form.to_year}
                onChange={(e) =>
                  setForm((s) => ({ ...s, to_year: e.target.value }))
                }
                placeholder="trống = nay"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="kv-source">Nguồn</Label>
              <Input
                id="kv-source"
                value={form.source}
                onChange={(e) =>
                  setForm((s) => ({ ...s, source: e.target.value }))
                }
                placeholder="manual_admin"
              />
            </div>
          </div>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            {editId != null && (
              <Button variant="outline" size="sm" onClick={resetForm} disabled={busy}>
                Huỷ sửa
              </Button>
            )}
            <Button size="sm" onClick={handleSubmit} disabled={busy}>
              {editId == null ? "Thêm" : "Lưu"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
