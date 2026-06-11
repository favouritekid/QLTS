/**
 * SchoolTable — bảng vn_school + dialog Thêm / Sửa / Ngừng + nút Quản lý KV.
 *
 * Ngừng (DELETE) = deactivate (is_active=false) — KHÔNG hard-delete (giữ KV
 * assignment). KV quản lý qua SchoolKvDialog (2 cấp: list + add/edit/delete).
 */

"use client"

import { useState } from "react"
import { Layers, Pencil, Plus, Power } from "lucide-react"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import {
  useCreateSchool,
  useDeactivateSchool,
  useUpdateSchool,
} from "@/lib/hooks/useVnSchoolAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import {
  schoolCreateSchema,
  schoolUpdateSchema,
  VN_SCHOOL_LEVELS,
  VN_SCHOOL_LEVEL_LABELS,
  type SchoolResponse,
  type VnSchoolLevel,
} from "@/lib/zod/vn-school-admin"

import { SchoolKvDialog } from "./SchoolKvDialog"

interface SchoolTableProps {
  rows: SchoolResponse[]
  isLoading: boolean
}

interface FormState {
  moet_school_code: string
  moet_province_code: string
  name: string
  province: string
  district: string
  ward: string
  level: VnSchoolLevel
  is_dtnt: boolean
}

const EMPTY: FormState = {
  moet_school_code: "",
  moet_province_code: "",
  name: "",
  province: "",
  district: "",
  ward: "",
  level: "THPT",
  is_dtnt: false,
}

export function SchoolTable({ rows, isLoading }: SchoolTableProps) {
  const createMutation = useCreateSchool()
  const updateMutation = useUpdateSchool()
  const deactivateMutation = useDeactivateSchool()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [formError, setFormError] = useState<string | null>(null)

  const [deactivateRow, setDeactivateRow] = useState<SchoolResponse | null>(null)
  const [kvSchool, setKvSchool] = useState<SchoolResponse | null>(null)

  const busy =
    createMutation.isPending ||
    updateMutation.isPending ||
    deactivateMutation.isPending

  const openCreate = () => {
    setEditId(null)
    setForm(EMPTY)
    setFormError(null)
    setDialogOpen(true)
  }

  const openEdit = (row: SchoolResponse) => {
    setEditId(row.id)
    setForm({
      moet_school_code: row.moet_school_code,
      moet_province_code: row.moet_province_code,
      name: row.name,
      province: row.province,
      district: row.district ?? "",
      ward: row.ward ?? "",
      level: row.level as VnSchoolLevel,
      is_dtnt: row.is_dtnt,
    })
    setFormError(null)
    setDialogOpen(true)
  }

  const handleSubmit = async () => {
    setFormError(null)
    try {
      if (editId == null) {
        const parsed = schoolCreateSchema.safeParse({
          moet_school_code: form.moet_school_code.trim(),
          moet_province_code: form.moet_province_code.trim(),
          name: form.name.trim(),
          province: form.province.trim(),
          district: form.district.trim() || undefined,
          ward: form.ward.trim() || undefined,
          level: form.level,
          is_dtnt: form.is_dtnt,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await createMutation.mutateAsync(parsed.data)
        toast.success(`Đã thêm trường ${parsed.data.moet_school_code}`)
      } else {
        const parsed = schoolUpdateSchema.safeParse({
          name: form.name.trim(),
          province: form.province.trim(),
          district: form.district.trim() || undefined,
          ward: form.ward.trim() || undefined,
          level: form.level,
          is_dtnt: form.is_dtnt,
        })
        if (!parsed.success) {
          setFormError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
          return
        }
        await updateMutation.mutateAsync({ id: editId, data: parsed.data })
        toast.success(`Đã cập nhật trường #${editId}`)
      }
      setDialogOpen(false)
    } catch (e) {
      setFormError(parseApiError(e, "Thao tác thất bại"))
    }
  }

  const handleDeactivate = async () => {
    if (!deactivateRow) return
    try {
      await deactivateMutation.mutateAsync(deactivateRow.id)
      toast.success(`Đã ngừng ${deactivateRow.name}`)
    } catch (e) {
      toast.error(parseApiError(e, "Ngừng trường thất bại"))
    } finally {
      setDeactivateRow(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          Thêm trường
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[130px]">Mã MOET</TableHead>
              <TableHead>Tên trường</TableHead>
              <TableHead>Tỉnh</TableHead>
              <TableHead className="w-[110px]">Cấp</TableHead>
              <TableHead className="w-[90px]">KV</TableHead>
              <TableHead className="w-[180px] text-right">Thao tác</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [1, 2, 3, 4, 5].map((i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-muted-foreground py-8 text-center text-sm"
                >
                  Không có trường nào khớp bộ lọc.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id} data-testid={`school-row-${row.id}`}>
                  <TableCell className="font-mono text-xs">
                    {row.moet_school_code}/{row.moet_province_code}
                  </TableCell>
                  <TableCell>
                    {row.name}
                    {!row.is_active && (
                      <Badge variant="outline" className="ml-2">
                        Đã ngừng
                      </Badge>
                    )}
                    {row.is_dtnt && (
                      <Badge variant="secondary" className="ml-2">
                        DTNT
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{row.province}</TableCell>
                  <TableCell className="text-xs">
                    {VN_SCHOOL_LEVEL_LABELS[row.level as VnSchoolLevel] ??
                      row.level}
                  </TableCell>
                  <TableCell>
                    {row.current_kv ? (
                      <Badge variant="secondary" className="font-mono">
                        {row.current_kv}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setKvSchool(row)}
                        aria-label={`Quản lý KV ${row.name}`}
                        title="Quản lý KV theo năm"
                      >
                        <Layers className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(row)}
                        aria-label={`Sửa ${row.name}`}
                        disabled={!row.is_active}
                        title="Sửa thông tin"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeactivateRow(row)}
                        aria-label={`Ngừng ${row.name}`}
                        disabled={!row.is_active}
                        title="Ngừng (ẩn) trường"
                      >
                        <Power className="text-destructive h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Create / Edit */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editId == null ? "Thêm trường" : `Sửa trường #${editId}`}
            </DialogTitle>
            <DialogDescription>
              {editId == null
                ? "Mã MOET (trường + tỉnh) phải chưa tồn tại."
                : "Mã MOET không đổi được. Ngừng trường dùng nút Ngừng."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="s-code">Mã trường MOET</Label>
                <Input
                  id="s-code"
                  value={form.moet_school_code}
                  disabled={editId != null}
                  onChange={(e) =>
                    setForm((s) => ({ ...s, moet_school_code: e.target.value }))
                  }
                  placeholder="VD: 040123"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="s-prov-code">Mã tỉnh MOET</Label>
                <Input
                  id="s-prov-code"
                  value={form.moet_province_code}
                  disabled={editId != null}
                  onChange={(e) =>
                    setForm((s) => ({
                      ...s,
                      moet_province_code: e.target.value,
                    }))
                  }
                  placeholder="VD: 040"
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="s-name">Tên trường</Label>
              <Input
                id="s-name"
                value={form.name}
                onChange={(e) =>
                  setForm((s) => ({ ...s, name: e.target.value }))
                }
                placeholder="VD: THPT Đắk Mil"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="s-prov">Tỉnh</Label>
                <Input
                  id="s-prov"
                  value={form.province}
                  onChange={(e) =>
                    setForm((s) => ({ ...s, province: e.target.value }))
                  }
                  placeholder="VD: Đắk Lắk"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="s-district">Huyện/Quận</Label>
                <Input
                  id="s-district"
                  value={form.district}
                  onChange={(e) =>
                    setForm((s) => ({ ...s, district: e.target.value }))
                  }
                  placeholder="Tuỳ chọn"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="s-level">Cấp</Label>
                <Select
                  value={form.level}
                  onValueChange={(v) =>
                    setForm((s) => ({ ...s, level: v as VnSchoolLevel }))
                  }
                >
                  <SelectTrigger id="s-level">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VN_SCHOOL_LEVELS.map((lv) => (
                      <SelectItem key={lv} value={lv}>
                        {VN_SCHOOL_LEVEL_LABELS[lv]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2 pt-7">
                <Switch
                  id="s-dtnt"
                  checked={form.is_dtnt}
                  onCheckedChange={(v) =>
                    setForm((s) => ({ ...s, is_dtnt: v }))
                  }
                />
                <Label htmlFor="s-dtnt">Trường DTNT</Label>
              </div>
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
              disabled={busy}
            >
              Hủy
            </Button>
            <Button onClick={handleSubmit} disabled={busy}>
              {editId == null ? "Tạo" : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deactivate */}
      <AlertDialog
        open={!!deactivateRow}
        onOpenChange={(o) => !o && setDeactivateRow(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Ngừng trường</AlertDialogTitle>
            <AlertDialogDescription>
              Ngừng (ẩn) {deactivateRow?.name}? Trường sẽ không hiện trong dropdown
              tuyển sinh nhưng GIỮ lịch sử KV (không xoá). Có thể tạo lại nếu cần.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDeactivate}
            >
              Ngừng
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* KV management */}
      <SchoolKvDialog
        school={kvSchool}
        onOpenChange={(o) => !o && setKvSchool(null)}
      />
    </div>
  )
}
