/**
 * CommuneKvTable — bảng vn_commune_area_map + dialog CRUD.
 *
 * 4 thao tác:
 * - Thêm xã (create)
 * - Sửa (PATCH metadata: tỉnh/xã — KHÔNG đổi KV ở đây)
 * - Đổi KV (replace-area): tạo bản ghi temporal MỚI, retire bản ghi cũ → giữ
 *   lịch sử KV theo thời gian
 * - Ngưng (retire): soft-close effective_to
 */

"use client"

import { useState } from "react"
import { History, Pencil, Plus, Trash2 } from "lucide-react"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import {
  useCreateCommune,
  useReplaceCommuneArea,
  useRetireCommune,
  useUpdateCommune,
} from "@/lib/hooks/useCommuneKvAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import {
  communeAreaCreateSchema,
  communeAreaUpdateSchema,
  communeReplaceAreaSchema,
  type CommuneAreaResponse,
} from "@/lib/zod/commune-kv"

const KV_OPTIONS = ["KV1", "KV2-NT", "KV2", "KV3"] as const

interface CommuneKvTableProps {
  rows: CommuneAreaResponse[]
  isLoading: boolean
}

interface CreateForm {
  commune_code: string
  province: string
  district: string
  ward: string
  area_code: string
}

const EMPTY_CREATE: CreateForm = {
  commune_code: "",
  province: "",
  district: "",
  ward: "",
  area_code: "KV3",
}

export function CommuneKvTable({ rows, isLoading }: CommuneKvTableProps) {
  const createMutation = useCreateCommune()
  const updateMutation = useUpdateCommune()
  const replaceMutation = useReplaceCommuneArea()
  const retireMutation = useRetireCommune()

  // Create
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<CreateForm>(EMPTY_CREATE)
  const [createError, setCreateError] = useState<string | null>(null)

  // Edit metadata
  const [editRow, setEditRow] = useState<CommuneAreaResponse | null>(null)
  const [editForm, setEditForm] = useState({ province: "", district: "", ward: "" })
  const [editError, setEditError] = useState<string | null>(null)

  // Replace area (đổi KV)
  const [replaceRow, setReplaceRow] = useState<CommuneAreaResponse | null>(null)
  const [replaceArea, setReplaceArea] = useState<string>("KV3")
  const [replaceError, setReplaceError] = useState<string | null>(null)

  // Retire
  const [retireRow, setRetireRow] = useState<CommuneAreaResponse | null>(null)

  const busy =
    createMutation.isPending ||
    updateMutation.isPending ||
    replaceMutation.isPending ||
    retireMutation.isPending

  const handleCreate = async () => {
    setCreateError(null)
    const parsed = communeAreaCreateSchema.safeParse({
      commune_code: createForm.commune_code.trim(),
      province: createForm.province.trim(),
      district: createForm.district.trim() || undefined,
      ward: createForm.ward.trim(),
      area_code: createForm.area_code,
    })
    if (!parsed.success) {
      setCreateError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
      return
    }
    try {
      await createMutation.mutateAsync(parsed.data)
      toast.success(`Đã thêm xã ${parsed.data.commune_code}`)
      setCreateOpen(false)
      setCreateForm(EMPTY_CREATE)
    } catch (e) {
      setCreateError(parseApiError(e, "Thêm xã thất bại"))
    }
  }

  const openEdit = (row: CommuneAreaResponse) => {
    setEditRow(row)
    setEditForm({ province: row.province, district: row.district, ward: row.ward })
    setEditError(null)
  }

  const handleEdit = async () => {
    if (!editRow) return
    setEditError(null)
    const parsed = communeAreaUpdateSchema.safeParse({
      province: editForm.province.trim(),
      // Empty → undefined để Pydantic exclude_unset bỏ qua (nhất quán với create
      // form), tránh PATCH district="" thừa khi không đổi.
      district: editForm.district.trim() || undefined,
      ward: editForm.ward.trim(),
    })
    if (!parsed.success) {
      setEditError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
      return
    }
    try {
      await updateMutation.mutateAsync({ id: editRow.id, data: parsed.data })
      toast.success(`Đã cập nhật ${editRow.ward}`)
      setEditRow(null)
    } catch (e) {
      setEditError(parseApiError(e, "Cập nhật thất bại"))
    }
  }

  const openReplace = (row: CommuneAreaResponse) => {
    setReplaceRow(row)
    setReplaceArea(row.area_code)
    setReplaceError(null)
  }

  const handleReplace = async () => {
    if (!replaceRow) return
    setReplaceError(null)
    const parsed = communeReplaceAreaSchema.safeParse({ area_code: replaceArea })
    if (!parsed.success) {
      setReplaceError(parsed.error.issues[0]?.message ?? "Mã KV không hợp lệ")
      return
    }
    if (replaceArea === replaceRow.area_code) {
      setReplaceError("KV mới trùng KV hiện tại")
      return
    }
    try {
      await replaceMutation.mutateAsync({
        id: replaceRow.id,
        data: parsed.data,
      })
      toast.success(`Đã đổi KV ${replaceRow.ward} → ${replaceArea}`)
      setReplaceRow(null)
    } catch (e) {
      setReplaceError(parseApiError(e, "Đổi KV thất bại"))
    }
  }

  const handleRetire = async () => {
    if (!retireRow) return
    try {
      await retireMutation.mutateAsync(retireRow.id)
      toast.success(`Đã ngưng ${retireRow.ward}`)
    } catch (e) {
      toast.error(parseApiError(e, "Ngưng thất bại"))
    } finally {
      setRetireRow(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          onClick={() => {
            setCreateForm(EMPTY_CREATE)
            setCreateError(null)
            setCreateOpen(true)
          }}
        >
          <Plus className="mr-1 h-4 w-4" />
          Thêm xã
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">Mã xã</TableHead>
              <TableHead>Tỉnh</TableHead>
              <TableHead>Xã / Phường</TableHead>
              <TableHead className="w-[100px]">KV</TableHead>
              <TableHead className="w-[170px]">Hiệu lực</TableHead>
              <TableHead className="w-[150px] text-right">Thao tác</TableHead>
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
                  Không có dòng nào khớp bộ lọc.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id} data-testid={`commune-row-${row.commune_code}`}>
                  <TableCell className="font-mono">{row.commune_code}</TableCell>
                  <TableCell>{row.province}</TableCell>
                  <TableCell>{row.ward}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="font-mono">
                      {row.area_code}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs tabular-nums">
                    {row.effective_from}
                    {row.effective_to ? ` → ${row.effective_to}` : " → nay"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(row)}
                        aria-label={`Sửa ${row.ward}`}
                        disabled={!!row.effective_to}
                        title="Sửa thông tin"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openReplace(row)}
                        aria-label={`Đổi KV ${row.ward}`}
                        disabled={!!row.effective_to}
                        title="Đổi KV (tạo bản ghi mới)"
                      >
                        <History className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setRetireRow(row)}
                        aria-label={`Ngưng ${row.ward}`}
                        disabled={!!row.effective_to}
                        title="Ngưng áp dụng"
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

      {/* Create */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Thêm xã</DialogTitle>
            <DialogDescription>
              Tạo bản ghi KV active mới. Mã xã phải chưa có dòng đang áp dụng.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-2">
              <Label htmlFor="c-code">Mã xã (BNV)</Label>
              <Input
                id="c-code"
                value={createForm.commune_code}
                onChange={(e) =>
                  setCreateForm((s) => ({ ...s, commune_code: e.target.value }))
                }
                placeholder="VD: 24717"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-province">Tỉnh</Label>
              <Input
                id="c-province"
                value={createForm.province}
                onChange={(e) =>
                  setCreateForm((s) => ({ ...s, province: e.target.value }))
                }
                placeholder="VD: Tỉnh Lâm Đồng"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-ward">Xã / Phường</Label>
              <Input
                id="c-ward"
                value={createForm.ward}
                onChange={(e) =>
                  setCreateForm((s) => ({ ...s, ward: e.target.value }))
                }
                placeholder="VD: Xã Đắk Mil"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-district">Huyện (cũ — để trống nếu 2 cấp)</Label>
              <Input
                id="c-district"
                value={createForm.district}
                onChange={(e) =>
                  setCreateForm((s) => ({ ...s, district: e.target.value }))
                }
                placeholder="Tuỳ chọn"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="c-kv">KV</Label>
              <Select
                value={createForm.area_code}
                onValueChange={(v) =>
                  setCreateForm((s) => ({ ...s, area_code: v }))
                }
              >
                <SelectTrigger id="c-kv">
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
            {createError && (
              <p className="text-destructive text-sm" role="alert">
                {createError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={busy}>
              Hủy
            </Button>
            <Button onClick={handleCreate} disabled={busy}>
              Tạo
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit metadata */}
      <Dialog open={!!editRow} onOpenChange={(o) => !o && setEditRow(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa thông tin xã</DialogTitle>
            <DialogDescription>
              Mã xã {editRow?.commune_code} · KV {editRow?.area_code}. Đổi KV
              dùng nút &quot;Đổi KV&quot; (tạo bản ghi mới, giữ lịch sử).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-2">
              <Label htmlFor="e-province">Tỉnh</Label>
              <Input
                id="e-province"
                value={editForm.province}
                onChange={(e) =>
                  setEditForm((s) => ({ ...s, province: e.target.value }))
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="e-ward">Xã / Phường</Label>
              <Input
                id="e-ward"
                value={editForm.ward}
                onChange={(e) =>
                  setEditForm((s) => ({ ...s, ward: e.target.value }))
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="e-district">Huyện (cũ)</Label>
              <Input
                id="e-district"
                value={editForm.district}
                onChange={(e) =>
                  setEditForm((s) => ({ ...s, district: e.target.value }))
                }
              />
            </div>
            {editError && (
              <p className="text-destructive text-sm" role="alert">
                {editError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditRow(null)} disabled={busy}>
              Hủy
            </Button>
            <Button onClick={handleEdit} disabled={busy}>
              Lưu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Replace area (đổi KV) */}
      <Dialog open={!!replaceRow} onOpenChange={(o) => !o && setReplaceRow(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Đổi KV — {replaceRow?.ward}</DialogTitle>
            <DialogDescription>
              KV hiện tại: <strong>{replaceRow?.area_code}</strong>. Hệ thống sẽ
              đóng bản ghi cũ (giữ lịch sử) và tạo bản ghi KV mới áp dụng từ hôm
              nay.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-2">
              <Label htmlFor="r-kv">KV mới</Label>
              <Select value={replaceArea} onValueChange={setReplaceArea}>
                <SelectTrigger id="r-kv">
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
            {replaceError && (
              <p className="text-destructive text-sm" role="alert">
                {replaceError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReplaceRow(null)} disabled={busy}>
              Hủy
            </Button>
            <Button
              onClick={handleReplace}
              disabled={busy || replaceArea === replaceRow?.area_code}
            >
              Đổi KV
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Retire */}
      <AlertDialog
        open={!!retireRow}
        onOpenChange={(o) => !o && setRetireRow(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Ngưng áp dụng KV</AlertDialogTitle>
            <AlertDialogDescription>
              Ngưng KV của {retireRow?.ward} ({retireRow?.commune_code})? Bản ghi
              sẽ đóng (effective_to = hôm nay), không xoá lịch sử.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleRetire}
            >
              Ngưng
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
