/**
 * RoundManagementPanel — admin CRUD UI cho OfferingAdmissionRound
 * (Phase 2 PR-2A, Q5 v6 bundled với PR-2A).
 *
 * Sibling pattern follow `AdmissionMethodPanel.tsx` cùng dir.
 *
 * Capabilities:
 * - List rounds dưới academic_info (selected ngoài qua prop)
 * - Add round (POST /api/v2/admin/academic-info/{id}/rounds)
 * - Edit round (PATCH /api/v2/admin/rounds/{id})
 * - Soft-archive (DELETE /api/v2/admin/rounds/{id}) — Concern γ v6: Phase 2
 *   allow regardless of submission_count, admin discretion
 * - Extend end_date (POST /rounds/{id}/extend) — SPEC §2.1.a Rule 2,
 *   reason ≥10 chars mandatory (Concern A v4)
 * - v2.12 P1 fix #4: round_quota decrease với override flag UI
 */

"use client"

import { CalendarPlus, Edit, Archive, Plus, Trash2 } from "lucide-react"
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
  useCreateRound,
  useExtendRound,
  useSoftArchiveRound,
  useUpdateRound,
} from "@/hooks/admissions/useAdmissionRounds"
import type { AdmissionRoundResponse } from "@/lib/zod/admission-rounds"

interface Props {
  academicInfoId: number | null
}

interface FormState {
  round_code: string
  round_name: string
  start_date: string
  end_date: string
  round_quota: string // string for input field; convert to number on submit
  admit_quota: string
  is_active: boolean
}

const EMPTY_FORM: FormState = {
  round_code: "",
  round_name: "",
  start_date: "",
  end_date: "",
  round_quota: "",
  admit_quota: "",
  is_active: true,
}

function formStateToCreatePayload(f: FormState) {
  return {
    round_code: f.round_code,
    round_name: f.round_name,
    start_date: f.start_date || null,
    end_date: f.end_date || null,
    round_quota: f.round_quota ? Number(f.round_quota) : null,
    admit_quota: f.admit_quota ? Number(f.admit_quota) : null,
    is_active: f.is_active,
  }
}

function formStateToUpdatePayload(f: FormState, override: boolean) {
  return {
    round_name: f.round_name,
    start_date: f.start_date || null,
    end_date: f.end_date || null,
    round_quota: f.round_quota ? Number(f.round_quota) : null,
    admit_quota: f.admit_quota ? Number(f.admit_quota) : null,
    is_active: f.is_active,
    override,
  }
}

function roundToFormState(r: AdmissionRoundResponse): FormState {
  return {
    round_code: r.round_code,
    round_name: r.round_name,
    start_date: r.start_date ?? "",
    end_date: r.end_date ?? "",
    round_quota: r.round_quota?.toString() ?? "",
    admit_quota: r.admit_quota?.toString() ?? "",
    is_active: r.is_active,
  }
}

export function RoundManagementPanel({ academicInfoId }: Props) {
  const { data, isLoading } = useAdmissionRounds(academicInfoId)
  const createMutation = useCreateRound(academicInfoId ?? 0)
  const updateMutation = useUpdateRound(academicInfoId ?? 0)
  const archiveMutation = useSoftArchiveRound(academicInfoId ?? 0)
  const extendMutation = useExtendRound(academicInfoId ?? 0)

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<AdmissionRoundResponse | null>(
    null
  )
  const [extendTarget, setExtendTarget] = useState<AdmissionRoundResponse | null>(
    null
  )
  const [archiveTarget, setArchiveTarget] = useState<AdmissionRoundResponse | null>(
    null
  )
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [extendForm, setExtendForm] = useState({
    end_date: "",
    extension_reason: "",
  })
  const [overrideQuota, setOverrideQuota] = useState(false)

  if (academicInfoId === null) {
    return (
      <div className="text-sm text-muted-foreground p-4">
        Chọn một năm học để quản lý các đợt tuyển sinh.
      </div>
    )
  }

  const rounds = data?.items ?? []

  const handleCreate = async () => {
    await createMutation.mutateAsync(formStateToCreatePayload(form))
    setCreateOpen(false)
    setForm(EMPTY_FORM)
  }

  const handleUpdate = async () => {
    if (!editTarget) return
    await updateMutation.mutateAsync({
      id: editTarget.id,
      data: formStateToUpdatePayload(form, overrideQuota),
    })
    setEditTarget(null)
    setOverrideQuota(false)
  }

  const handleArchive = async () => {
    if (!archiveTarget) return
    await archiveMutation.mutateAsync(archiveTarget.id)
    setArchiveTarget(null)
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
        <h3 className="text-lg font-semibold">Đợt tuyển sinh</h3>
        <Button
          onClick={() => {
            setForm(EMPTY_FORM)
            setCreateOpen(true)
          }}
        >
          <Plus className="h-4 w-4 mr-2" /> Thêm đợt
        </Button>
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Đang tải...</div>
      ) : rounds.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          Chưa có đợt nào. Tạo DOT_1 để bắt đầu.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Mã đợt</TableHead>
              <TableHead>Tên hiển thị</TableHead>
              <TableHead>Bắt đầu</TableHead>
              <TableHead>Kết thúc</TableHead>
              <TableHead>Quota / Đã nộp</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead className="text-right">Hành động</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rounds.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono">{r.round_code}</TableCell>
                <TableCell>{r.round_name}</TableCell>
                <TableCell>{r.start_date ?? "—"}</TableCell>
                <TableCell>
                  {r.end_date ?? "—"}
                  {r.extended_at && (
                    <Badge variant="secondary" className="ml-2 text-xs">
                      Extended
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  {r.round_quota ?? "∞"} / {r.submission_count}
                </TableCell>
                <TableCell>
                  {r.archived_at ? (
                    <Badge variant="outline">Archived</Badge>
                  ) : r.is_active ? (
                    <Badge variant="default">Active</Badge>
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
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
                    aria-label="Sửa"
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
                    aria-label="Kéo dài"
                  >
                    <CalendarPlus className="h-3 w-3" />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setArchiveTarget(r)}
                    disabled={r.archived_at !== null}
                    aria-label="Lưu trữ"
                  >
                    <Archive className="h-3 w-3" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* Create Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tạo đợt tuyển sinh mới</DialogTitle>
            <DialogDescription>
              Mã đợt phải UNIQUE per năm học (vd: DOT_1, DOT_2, BO_SUNG).
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

      {/* Edit Dialog */}
      <Dialog open={editTarget !== null} onOpenChange={(o) => !o && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa đợt {editTarget?.round_code}</DialogTitle>
            <DialogDescription>
              Quota mới &lt; submission_count cần check ô &quot;Override&quot;
              (v2.12 P1 fix #4).
            </DialogDescription>
          </DialogHeader>
          <RoundForm form={form} setForm={setForm} mode="edit" />
          <div className="flex items-center space-x-2">
            <Checkbox
              id="override"
              checked={overrideQuota}
              onCheckedChange={(c) => setOverrideQuota(Boolean(c))}
            />
            <Label htmlFor="override" className="text-sm">
              Override (cho phép quota giảm dưới submission_count)
            </Label>
          </div>
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
            <DialogTitle>Kéo dài đợt {extendTarget?.round_code}</DialogTitle>
            <DialogDescription>
              Lý do bắt buộc ≥10 ký tự (audit log).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="extend_end_date">end_date mới</Label>
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
              Kéo dài
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
              Đợt sẽ ẩn khỏi storefront + path config dropdown
              (is_active=false). Profile đã link round_id giữ nguyên qua
              applied_rules. Phase 2 cho phép lưu trữ kể cả khi đã có hồ sơ.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveTarget(null)}>
              Huỷ
            </Button>
            <Button variant="destructive" onClick={handleArchive}>
              <Trash2 className="h-4 w-4 mr-2" /> Lưu trữ
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
          <Label htmlFor="start_date">Bắt đầu</Label>
          <Input
            id="start_date"
            type="date"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="end_date">Kết thúc</Label>
          <Input
            id="end_date"
            type="date"
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="round_quota">Quota đăng ký</Label>
          <Input
            id="round_quota"
            type="number"
            min="0"
            value={form.round_quota}
            onChange={(e) => setForm({ ...form, round_quota: e.target.value })}
            placeholder="∞ (NULL = không giới hạn)"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="admit_quota">Quota trúng tuyển</Label>
          <Input
            id="admit_quota"
            type="number"
            min="0"
            value={form.admit_quota}
            onChange={(e) => setForm({ ...form, admit_quota: e.target.value })}
            placeholder="NULL = inherit từ round_quota"
          />
        </div>
      </div>

      <div className="flex items-center space-x-2">
        <Checkbox
          id="is_active"
          checked={form.is_active}
          onCheckedChange={(c) => setForm({ ...form, is_active: Boolean(c) })}
        />
        <Label htmlFor="is_active">Active</Label>
      </div>
    </div>
  )
}
