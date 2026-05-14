/**
 * RoundsManagementTab — admin top-level UI cho OfferingAdmissionRound
 * year-level (Phase 2 v8.2 PR-2A v2 — Q1 Option A workflow inversion fix).
 *
 * Per user Pass 4 review: chuyển từ bottom-up (vào từng ngành tạo đợt) sang
 * top-down (admin tạo đợt 1 lần cho cả trường). Round là entity year-level
 * (1 đợt = 1 row globally), KHÔNG nest dưới academic_info nữa.
 *
 * Capabilities:
 * - Year selector dropdown (default: hiện tại)
 * - List rounds per year (table với mã đợt, dates, trạng thái, hành động)
 * - Tạo đợt mới (single)
 * - Tạo nhanh 4 đợt (DOT_1/DOT_2/DOT_3/BO_SUNG atomic)
 * - Sửa đợt (time-window/lifecycle only — Q3 v8.2)
 * - Gia hạn end_date với lý do ≥10 ký tự (SPEC §2.1.a Rule 2)
 * - Lưu trữ (soft-archive — Concern γ v6 admin discretion)
 *
 * Tiếng Việt nhất quán per user feedback.
 */

"use client"

import {
  Archive,
  ArchiveRestore,
  CalendarPlus,
  Edit,
  Layers,
  Plus,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
  useAdmissionRounds,
  useBulkCreateRounds,
  useCreateRound,
  useExtendRound,
  useRestoreRound,
  useSoftArchiveRound,
  useUpdateRound,
} from "@/hooks/admissions/useAdmissionRounds"
import type { AdmissionRoundResponse } from "@/lib/zod/admission-rounds"

interface FormState {
  round_code: string
  round_name: string
  start_date: string
  end_date: string
  is_active: boolean
  // Phase 3 Q-P3-02 / Q-P3-06 surfaced via phase3_01 migration + this PR.
  // Defaults mirror Pydantic AdmissionRoundBase to keep create + update + API
  // contract aligned.
  allow_multi_nv: boolean
  confirm_expiry_hours: number
}

const EMPTY_FORM: FormState = {
  round_code: "",
  round_name: "",
  start_date: "",
  end_date: "",
  is_active: true,
  allow_multi_nv: false,
  confirm_expiry_hours: 168,
}

const DEFAULT_4_ROUNDS = [
  { round_code: "DOT_1", round_name: "Đợt 1" },
  { round_code: "DOT_2", round_name: "Đợt 2" },
  { round_code: "DOT_3", round_name: "Đợt 3" },
  { round_code: "BO_SUNG", round_name: "Đợt bổ sung" },
]

function formStateToCreatePayload(f: FormState) {
  return {
    round_code: f.round_code,
    round_name: f.round_name,
    start_date: f.start_date || null,
    end_date: f.end_date || null,
    is_active: f.is_active,
    allow_multi_nv: f.allow_multi_nv,
    confirm_expiry_hours: f.confirm_expiry_hours,
  }
}

function formStateToUpdatePayload(f: FormState) {
  return {
    round_name: f.round_name,
    start_date: f.start_date || null,
    end_date: f.end_date || null,
    is_active: f.is_active,
    allow_multi_nv: f.allow_multi_nv,
    confirm_expiry_hours: f.confirm_expiry_hours,
  }
}

function roundToFormState(r: AdmissionRoundResponse): FormState {
  return {
    round_code: r.round_code,
    round_name: r.round_name,
    start_date: r.start_date ?? "",
    end_date: r.end_date ?? "",
    is_active: r.is_active,
    allow_multi_nv: r.allow_multi_nv,
    confirm_expiry_hours: r.confirm_expiry_hours,
  }
}

function statusLabel(r: AdmissionRoundResponse): {
  label: string
  variant: "default" | "secondary" | "outline"
} {
  if (r.archived_at) return { label: "Đã lưu trữ", variant: "outline" }
  if (r.is_active) return { label: "Đang hoạt động", variant: "default" }
  return { label: "Tạm dừng", variant: "secondary" }
}

export function RoundsManagementTab() {
  const currentYear = new Date().getFullYear()
  const [academicYear, setAcademicYear] = useState<number>(currentYear)

  const { data, isLoading } = useAdmissionRounds(academicYear)
  const createMutation = useCreateRound(academicYear)
  const bulkCreateMutation = useBulkCreateRounds(academicYear)
  const updateMutation = useUpdateRound(academicYear)
  const archiveMutation = useSoftArchiveRound(academicYear)
  const restoreMutation = useRestoreRound(academicYear)
  const extendMutation = useExtendRound(academicYear)

  const [createOpen, setCreateOpen] = useState(false)
  const [bulkCreateOpen, setBulkCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<AdmissionRoundResponse | null>(null)
  const [extendTarget, setExtendTarget] = useState<AdmissionRoundResponse | null>(null)
  const [archiveTarget, setArchiveTarget] = useState<AdmissionRoundResponse | null>(null)
  const [restoreTarget, setRestoreTarget] = useState<AdmissionRoundResponse | null>(null)

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [extendForm, setExtendForm] = useState({ end_date: "", extension_reason: "" })

  const rounds = data?.items ?? []

  // Year selector range — current ± 2 năm
  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 1 + i)

  const handleCreate = async () => {
    await createMutation.mutateAsync(formStateToCreatePayload(form))
    setCreateOpen(false)
    setForm(EMPTY_FORM)
  }

  const handleBulkCreate = async () => {
    await bulkCreateMutation.mutateAsync({
      rounds: DEFAULT_4_ROUNDS.map((r) => ({
        round_code: r.round_code,
        round_name: `${r.round_name} - ${academicYear}`,
        is_active: true,
      })),
    })
    setBulkCreateOpen(false)
  }

  const handleUpdate = async () => {
    if (!editTarget) return
    await updateMutation.mutateAsync({
      id: editTarget.id,
      data: formStateToUpdatePayload(form),
    })
    setEditTarget(null)
  }

  const handleArchive = async () => {
    if (!archiveTarget) return
    await archiveMutation.mutateAsync(archiveTarget.id)
    setArchiveTarget(null)
  }

  const handleRestore = async () => {
    if (!restoreTarget) return
    await restoreMutation.mutateAsync(restoreTarget.id)
    setRestoreTarget(null)
  }

  const handleExtend = async () => {
    if (!extendTarget) return
    await extendMutation.mutateAsync({
      id: extendTarget.id,
      data: extendForm,
    })
    setExtendTarget(null)
    setExtendForm({ end_date: "", extension_reason: "" })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Đợt tuyển sinh</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Quản lý đợt tuyển sinh theo năm học (DOT_1 / DOT_2 / DOT_3 / Bổ sung)
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Label htmlFor="year-select" className="text-sm whitespace-nowrap">
              Năm học:
            </Label>
            <Select
              value={academicYear.toString()}
              onValueChange={(v) => setAcademicYear(parseInt(v, 10))}
            >
              <SelectTrigger id="year-select" className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {yearOptions.map((y) => (
                  <SelectItem key={y} value={y.toString()}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="outline"
            onClick={() => setBulkCreateOpen(true)}
            disabled={rounds.length >= 4}
          >
            <Layers className="h-4 w-4 mr-2" />
            Tạo nhanh 4 đợt
          </Button>
          <Button
            onClick={() => {
              setForm(EMPTY_FORM)
              setCreateOpen(true)
            }}
          >
            <Plus className="h-4 w-4 mr-2" />
            Thêm đợt
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground p-4">Đang tải...</div>
      ) : rounds.length === 0 ? (
        <div className="border rounded-lg p-8 text-center space-y-3">
          <p className="text-muted-foreground">
            Chưa có đợt tuyển sinh nào năm {academicYear}.
          </p>
          <Button variant="outline" onClick={() => setBulkCreateOpen(true)}>
            <Layers className="h-4 w-4 mr-2" />
            Tạo nhanh 4 đợt mặc định
          </Button>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Mã đợt</TableHead>
              <TableHead>Tên hiển thị</TableHead>
              <TableHead>Bắt đầu</TableHead>
              <TableHead>Kết thúc</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead className="text-right">Hành động</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rounds.map((r) => {
              const status = statusLabel(r)
              return (
                <TableRow key={r.id}>
                  <TableCell className="font-mono">{r.round_code}</TableCell>
                  <TableCell>{r.round_name}</TableCell>
                  <TableCell>{r.start_date ?? "—"}</TableCell>
                  <TableCell>
                    {r.end_date ?? "—"}
                    {r.extended_at && (
                      <Badge variant="secondary" className="ml-2 text-xs">
                        Đã gia hạn
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={status.variant}>{status.label}</Badge>
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setForm(roundToFormState(r))
                        setEditTarget(r)
                      }}
                      disabled={r.archived_at !== null}
                      aria-label="Sửa đợt"
                    >
                      <Edit className="h-3 w-3" />
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setExtendForm({
                          end_date: r.end_date ?? "",
                          extension_reason: "",
                        })
                        setExtendTarget(r)
                      }}
                      disabled={r.archived_at !== null}
                      aria-label="Gia hạn đợt"
                    >
                      <CalendarPlus className="h-3 w-3" />
                    </Button>
                    {r.archived_at === null ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setArchiveTarget(r)}
                        aria-label="Lưu trữ đợt"
                      >
                        <Archive className="h-3 w-3" aria-hidden="true" />
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRestoreTarget(r)}
                        aria-label="Khôi phục đợt"
                      >
                        <ArchiveRestore className="h-3 w-3" aria-hidden="true" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tạo đợt tuyển sinh mới — Năm {academicYear}</DialogTitle>
            <DialogDescription>
              Mã đợt phải duy nhất trong năm học (vd: DOT_1, DOT_2, BO_SUNG).
            </DialogDescription>
          </DialogHeader>
          <RoundForm form={form} setForm={setForm} mode="create" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Huỷ
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!form.round_code || !form.round_name}
            >
              Tạo
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk-create Dialog */}
      <Dialog open={bulkCreateOpen} onOpenChange={setBulkCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tạo nhanh 4 đợt — Năm {academicYear}</DialogTitle>
            <DialogDescription>
              Hệ thống sẽ tạo đồng thời 4 đợt mặc định: Đợt 1, Đợt 2, Đợt 3, Đợt
              bổ sung. Đợt nào đã tồn tại sẽ được bỏ qua. Admin có thể sửa thời
              gian từng đợt sau khi tạo.
            </DialogDescription>
          </DialogHeader>
          <ul className="text-sm space-y-1 list-disc list-inside py-2">
            {DEFAULT_4_ROUNDS.map((r) => (
              <li key={r.round_code}>
                <span className="font-mono">{r.round_code}</span> —{" "}
                {r.round_name} - {academicYear}
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkCreateOpen(false)}>
              Huỷ
            </Button>
            <Button onClick={handleBulkCreate}>
              <Layers className="h-4 w-4 mr-2" />
              Tạo 4 đợt
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={editTarget !== null} onOpenChange={(o) => !o && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa đợt {editTarget?.round_code}</DialogTitle>
            <DialogDescription>
              Cập nhật tên hiển thị, ngày bắt đầu/kết thúc, trạng thái hoạt động.
              Mã đợt không thể thay đổi sau khi tạo.
            </DialogDescription>
          </DialogHeader>
          <RoundForm form={form} setForm={setForm} mode="edit" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTarget(null)}>
              Huỷ
            </Button>
            <Button onClick={handleUpdate}>Lưu</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Extend Dialog */}
      <Dialog
        open={extendTarget !== null}
        onOpenChange={(o) => !o && setExtendTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Gia hạn đợt {extendTarget?.round_code}</DialogTitle>
            <DialogDescription>
              Lý do gia hạn bắt buộc tối thiểu 10 ký tự (lưu vào nhật ký kiểm tra).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="extend_end_date">Ngày kết thúc mới</Label>
              <Input
                id="extend_end_date"
                type="date"
                value={extendForm.end_date}
                onChange={(e) =>
                  setExtendForm({ ...extendForm, end_date: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="extend_reason">Lý do (≥10 ký tự)</Label>
              <Textarea
                id="extend_reason"
                value={extendForm.extension_reason}
                onChange={(e) =>
                  setExtendForm({
                    ...extendForm,
                    extension_reason: e.target.value,
                  })
                }
                placeholder="VD: Kéo dài đợt do bão lũ miền Trung"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExtendTarget(null)}>
              Huỷ
            </Button>
            <Button
              onClick={handleExtend}
              disabled={
                !extendForm.end_date ||
                extendForm.extension_reason.trim().length < 10
              }
            >
              Gia hạn
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Archive Confirm Dialog */}
      <Dialog
        open={archiveTarget !== null}
        onOpenChange={(o) => !o && setArchiveTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Lưu trữ đợt {archiveTarget?.round_code}?</DialogTitle>
            <DialogDescription>
              Đợt sẽ ẩn khỏi danh sách công khai và không hiển thị trong cấu hình
              đường tuyển sinh. Hồ sơ thí sinh đã đăng ký vẫn giữ liên kết với đợt
              này (không bị xóa).
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveTarget(null)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={handleArchive}
              disabled={archiveMutation.isPending}
              aria-busy={archiveMutation.isPending}
            >
              <Trash2 className="h-4 w-4 mr-2" aria-hidden="true" />
              Lưu trữ
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Restore Confirm Dialog */}
      <Dialog
        open={restoreTarget !== null}
        onOpenChange={(o) => !o && setRestoreTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Khôi phục đợt {restoreTarget?.round_code}?</DialogTitle>
            <DialogDescription>
              Đợt sẽ hiện lại trên storefront và xuất hiện trong danh sách cấu
              hình đường tuyển sinh. Trạng thái Đang hoạt động sẽ được bật lại.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestoreTarget(null)}>
              Huỷ
            </Button>
            <Button
              onClick={handleRestore}
              disabled={restoreMutation.isPending}
              aria-busy={restoreMutation.isPending}
            >
              <ArchiveRestore className="h-4 w-4 mr-2" aria-hidden="true" />
              Khôi phục
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// =============================================================================
// Form sub-component (shared create/edit)
// =============================================================================


function RoundForm({
  form,
  setForm,
  mode,
}: {
  form: FormState
  setForm: (f: FormState) => void
  mode: "create" | "edit"
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="round_code">Mã đợt</Label>
          <Input
            id="round_code"
            value={form.round_code}
            onChange={(e) => setForm({ ...form, round_code: e.target.value })}
            placeholder="DOT_1"
            disabled={mode === "edit"}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="round_name">Tên hiển thị</Label>
          <Input
            id="round_name"
            value={form.round_name}
            onChange={(e) => setForm({ ...form, round_name: e.target.value })}
            placeholder="Đợt 1 - 2026"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="start_date">Ngày bắt đầu</Label>
          <Input
            id="start_date"
            type="date"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="end_date">Ngày kết thúc</Label>
          <Input
            id="end_date"
            type="date"
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
        </div>
      </div>

      <div className="flex items-center space-x-2">
        <Checkbox
          id="is_active"
          checked={form.is_active}
          onCheckedChange={(c) => setForm({ ...form, is_active: Boolean(c) })}
        />
        <Label htmlFor="is_active">Đang hoạt động</Label>
      </div>

      {/* Phase 3 Q-P3-02 — per-round multi-NV gate. Off by default; admin
          flips on per round when the round should accept multi-choice
          submissions. Engine + storefront read this same value. */}
      <div className="flex items-start space-x-2">
        <Checkbox
          id="allow_multi_nv"
          className="mt-1"
          checked={form.allow_multi_nv}
          onCheckedChange={(c) => setForm({ ...form, allow_multi_nv: Boolean(c) })}
        />
        <div className="space-y-1">
          <Label htmlFor="allow_multi_nv">Cho phép nhiều nguyện vọng</Label>
          <p className="text-xs text-muted-foreground">
            Bật để thí sinh đăng ký nhiều ngành xếp thứ tự ưu tiên trong đợt
            này. Tắt = mỗi hồ sơ chỉ 1 nguyện vọng (chế độ cũ).
          </p>
        </div>
      </div>

      {/* Phase 3 Q-P3-06 — per-round magic-link confirm expiry. Default
          168h (7 ngày). Admin có thể rút ngắn (vd: 24h cho đợt gấp) hoặc
          nới (vd: 336h=14d cho đợt dài). */}
      <div className="space-y-2">
        <Label htmlFor="confirm_expiry_hours">
          Thời hạn xác nhận nhập học (giờ)
        </Label>
        <Input
          id="confirm_expiry_hours"
          type="number"
          min={1}
          max={8760}
          value={form.confirm_expiry_hours}
          onChange={(e) =>
            setForm({
              ...form,
              confirm_expiry_hours: Number(e.target.value) || 0,
            })
          }
        />
        <p className="text-xs text-muted-foreground">
          Sau khi trúng tuyển, thí sinh có {form.confirm_expiry_hours} giờ
          (~{Math.round((form.confirm_expiry_hours / 24) * 10) / 10} ngày) để
          xác nhận nhập học qua magic-link. Mặc định 168 giờ (7 ngày).
        </p>
      </div>
    </div>
  )
}
