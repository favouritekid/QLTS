/**
 * ClonePathsDialog — bulk clone paths source_round → target_round (Q6 deep-copy).
 *
 * Phase 2 v8.2 PR-2D.1 v4a — wrap BE endpoint
 * POST /api/v2/admin/rounds/{target}/clone-paths-from/{source}.
 *
 * Atomic transaction server-side: deep-copy criteria + criteria_subject_group
 * + admission_path + path_subject_group_config + items. ON CONFLICT skip.
 */
"use client"

import { CheckCircle2, Loader2 } from "lucide-react"
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
import { useAdmissionRounds } from "@/hooks/admissions/useAdmissionRounds"
import { useClonePathsFromRound } from "@/hooks/admissions/useClonePathsFromRound"
import { parseApiError } from "@/lib/utils/api-errors"

interface AdmissionRound {
  id: number
  round_code: string
  round_name: string
}

interface Props {
  academicYear: number
  onClose: () => void
}

export function ClonePathsDialog({ academicYear, onClose }: Props) {
  const { data: roundsData, isLoading: loadingRounds } = useAdmissionRounds(academicYear)
  const [sourceRoundId, setSourceRoundId] = useState<number | null>(null)
  const [targetRoundId, setTargetRoundId] = useState<number | null>(null)
  const [template, setTemplate] = useState("{source_code}_{round_code}")
  const cloneMutation = useClonePathsFromRound()

  const rounds: AdmissionRound[] = roundsData?.items ?? []

  const handleClone = async () => {
    if (!sourceRoundId || !targetRoundId) {
      toast.error("Vui lòng chọn cả đợt nguồn và đợt đích.")
      return
    }
    if (sourceRoundId === targetRoundId) {
      toast.error("Đợt nguồn và đợt đích phải khác nhau.")
      return
    }
    try {
      const result = await cloneMutation.mutateAsync({
        targetRoundId,
        sourceRoundId,
        payload: {
          academic_info_ids: null,
          criteria_code_template: template.trim() || null,
        },
      })
      toast.success(
        `Đã sao chép ${result.cloned_count} đường (bỏ qua ${result.skipped_count} đường đã tồn tại).`,
      )
      onClose()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi sao chép — kiểm tra dữ liệu và thử lại."))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-pretty">Sao chép đường tuyển sinh giữa các đợt</DialogTitle>
          <DialogDescription>
            Sao chép sâu toàn bộ đường tuyển sinh từ đợt nguồn sang đợt đích cùng năm {academicYear}.
            Đường đã tồn tại ở đợt đích sẽ tự động bỏ qua (ràng buộc 3-cột duy nhất).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="source-round">
              Đợt nguồn{" "}
              <span className="text-destructive" aria-hidden="true">*</span>
              <span className="sr-only"> (bắt buộc)</span>
            </Label>
            <Select
              value={sourceRoundId?.toString() ?? ""}
              onValueChange={(v) => setSourceRoundId(Number(v))}
              disabled={loadingRounds}
            >
              <SelectTrigger id="source-round">
                <SelectValue placeholder="Chọn đợt nguồn…" />
              </SelectTrigger>
              <SelectContent>
                {rounds.map((r) => (
                  <SelectItem key={r.id} value={r.id.toString()}>
                    <span translate="no">{r.round_code}</span> — {r.round_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="target-round">
              Đợt đích{" "}
              <span className="text-destructive" aria-hidden="true">*</span>
              <span className="sr-only"> (bắt buộc)</span>
            </Label>
            <Select
              value={targetRoundId?.toString() ?? ""}
              onValueChange={(v) => setTargetRoundId(Number(v))}
              disabled={loadingRounds}
            >
              <SelectTrigger id="target-round">
                <SelectValue placeholder="Chọn đợt đích…" />
              </SelectTrigger>
              <SelectContent>
                {rounds
                  .filter((r) => r.id !== sourceRoundId)
                  .map((r) => (
                    <SelectItem key={r.id} value={r.id.toString()}>
                      <span translate="no">{r.round_code}</span> — {r.round_name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="template">Mẫu mã tiêu chí</Label>
            <Input
              id="template"
              name="criteria_code_template"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              placeholder="{source_code}_{round_code}"
              className="font-mono text-xs"
              autoComplete="off"
              spellCheck={false}
              translate="no"
            />
            <p className="text-[11px] text-muted-foreground">
              Biến thay thế:{" "}
              <code translate="no">{`{source_code}`}</code>,{" "}
              <code translate="no">{`{round_code}`}</code>. Bỏ trống = dùng mẫu mặc định.
            </p>
          </div>

          <div className="rounded-md border bg-emerald-500/5 border-emerald-500/30 p-3 text-xs flex gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <div className="font-medium">Sao chép sâu, nguyên vẹn</div>
              <p className="text-muted-foreground mt-0.5">
                Máy chủ sao chép đầy đủ: tiêu chí, tổ hợp môn, cấu hình đường tuyển sinh.
                Chỉ tiêu (trần submit/admit) reset rỗng — admin tự đặt lại trên ma trận.
              </p>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={cloneMutation.isPending}
          >
            Huỷ
          </Button>
          <Button
            onClick={handleClone}
            disabled={cloneMutation.isPending}
            aria-busy={cloneMutation.isPending}
          >
            {cloneMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            )}
            Sao chép
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
