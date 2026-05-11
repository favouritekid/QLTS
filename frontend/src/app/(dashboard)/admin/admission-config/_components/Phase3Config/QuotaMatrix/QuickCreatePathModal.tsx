/**
 * QuickCreatePathModal — tạo path trống tối thiểu cho cell empty `—`.
 *
 * Phase 2 v8.2 PR-2D.1 v4a — quick create flow.
 * Preset (round_id, academic_info_id, method_id) từ vị trí cell. Admin
 * vẫn có thể edit method nếu cần (case Theo ngành click "+ Tạo path mới").
 * Sau create → admin tiếp tục cấu hình tiêu chí/giấy tờ qua PathDetailDrawer.
 */
"use client"

import { Loader2 } from "lucide-react"
import { useState } from "react"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCreateAdmissionPath } from "@/hooks/admissions/useAdmissionPaths"
import { useAdmissionMethods } from "@/hooks/admissions/useMasterData"
import type { AdmissionMethod } from "../../shared/types"

interface Props {
  academicInfoId: number
  /** Preset round (cell vị trí). Optional — null → BE auto-resolve DOT_1 */
  admissionRoundId?: number | null
  /** Preset method nếu cell là vị trí (method × round) cụ thể */
  admissionMethodId?: number | null
  /** Title hiển thị context (vd "CNTT × DOT_1 × Học bạ") */
  contextLabel?: string
  onClose: () => void
  onCreated: (pathId: number) => void
}

export function QuickCreatePathModal({
  academicInfoId,
  admissionRoundId,
  admissionMethodId,
  contextLabel,
  onClose,
  onCreated,
}: Props) {
  const { data: methods = [], isLoading: loadingMethods } = useAdmissionMethods()
  const [methodId, setMethodId] = useState<number | null>(admissionMethodId ?? null)
  const [displayName, setDisplayName] = useState("")
  const [displayOrder, setDisplayOrder] = useState("1")
  const createMutation = useCreateAdmissionPath()

  const handleCreate = async () => {
    if (!methodId) {
      toast.error("Vui lòng chọn phương thức trước khi tạo.")
      return
    }
    try {
      const created = await createMutation.mutateAsync({
        academic_info_id: academicInfoId,
        admission_method_id: methodId,
        admission_round_id: admissionRoundId ?? null,
        display_name: displayName.trim() || null,
        display_order: Number(displayOrder) || 1,
        visibility: "internal",
        allow_unverified_submission: false,
        minor_correction_allowed_fields: [],
      })
      toast.success("Đã tạo đường tuyển sinh. Mở chi tiết để cấu hình tiêu chí &amp; giấy tờ.")
      onCreated(created.id)
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (e instanceof Error ? e.message : "Lỗi tạo — kiểm tra dữ liệu và thử lại.")
      toast.error(msg)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-pretty">Tạo đường tuyển sinh mới</DialogTitle>
          <DialogDescription>
            {contextLabel ?? "Tạo tối thiểu — cấu hình chi tiết sau ở trang chi tiết."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="method">
              Phương thức{" "}
              <span className="text-destructive" aria-hidden="true">*</span>
              <span className="sr-only"> (bắt buộc)</span>
            </Label>
            <Select
              value={methodId?.toString() ?? ""}
              onValueChange={(v) => setMethodId(Number(v))}
              disabled={!!admissionMethodId || loadingMethods}
            >
              <SelectTrigger id="method">
                <SelectValue placeholder="Chọn phương thức…" />
              </SelectTrigger>
              <SelectContent>
                {methods.map((m: AdmissionMethod) => (
                  <SelectItem key={m.id} value={m.id.toString()}>
                    {m.name}{" "}
                    <span className="text-muted-foreground" translate="no">
                      ({m.code})
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {admissionMethodId && (
              <p className="text-[11px] text-muted-foreground">
                Phương thức đã chọn theo vị trí ô — không đổi được.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="display-name">Tên hiển thị (tuỳ chọn)</Label>
            <Input
              id="display-name"
              name="display_name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="VD: CNTT 2026 — Học bạ…"
              autoComplete="off"
              spellCheck={false}
            />
            <p className="text-[11px] text-muted-foreground">
              Bỏ trống = hệ thống tự sinh từ tên ngành &amp; phương thức.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="order">Thứ tự hiển thị</Label>
            <Input
              id="order"
              name="display_order"
              type="number"
              inputMode="numeric"
              min="0"
              value={displayOrder}
              onChange={(e) => setDisplayOrder(e.target.value)}
              autoComplete="off"
            />
          </div>

          {!admissionRoundId && (
            <div className="rounded-md border bg-muted/40 p-2 text-[11px] text-muted-foreground">
              Đợt không chọn trước — máy chủ tự gán Đợt 1 của năm tương ứng.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            Huỷ
          </Button>
          <Button
            onClick={handleCreate}
            disabled={createMutation.isPending}
            aria-busy={createMutation.isPending}
          >
            {createMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            )}
            Tạo đường tuyển sinh
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
