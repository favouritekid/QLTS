"use client"

/**
 * Phase 3 multi-NV — AddChoiceDialog.
 *
 * Cascading form cho candidate/officer thêm nguyện vọng mới:
 *   1. Dropdown ngành/method (paths trong cùng round với current NV1)
 *   2. Dropdown tổ hợp môn (sg_config thuộc path đã chọn)
 *   3. Score inputs per subject của tổ hợp
 *   4. Submit → POST /api/v2/admissions/{profile_id}/choices
 *
 * Round derive:
 *   - From `currentPathId` prop → fetch path detail → admission_round_id.
 *
 * Validation:
 *   - All scores required
 *   - Each score in [min_possible_score, max_score]
 *
 * BE gates (BusinessRuleViolation 400 surface qua toast):
 *   - profile.uses_choice_engine == True
 *   - profile.status IN (draft, revision_requested)
 *   - round.allow_multi_nv == True
 *   - existing_count < system_config.max_choices_per_profile
 */
import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  getAdmissionPath,
  getPathSubjectGroupConfigs,
  getPathsByRound,
} from "@/lib/api/admission-paths"
import { useCreateChoice } from "@/hooks/admissions/useAdmissionChoices"
import { parseApiError } from "@/lib/utils/api-errors"

export interface AddChoiceDialogProps {
  profileId: number
  open: boolean
  onClose: () => void
  /** Display order số NV mới (current count + 1; UNIQUE constraint enforce). */
  nextDisplayOrder: number
  /** Path ID của 1 NV hiện có để derive round_id; nếu không có (profile
   * chưa NV nào), parent phải pass round_id explicit qua roundIdOverride. */
  currentPathId: number | null
  /** Optional fallback nếu profile chưa có NV nào — truyền round_id đã biết. */
  roundIdOverride?: number
}

interface ScoreState {
  subject_id: number
  value: string
  error: string | null
}

export function AddChoiceDialog({
  profileId,
  open,
  onClose,
  nextDisplayOrder,
  currentPathId,
  roundIdOverride,
}: AddChoiceDialogProps) {
  const [selectedPathId, setSelectedPathId] = useState<number | null>(null)
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null)
  const [scores, setScores] = useState<ScoreState[]>([])
  const [serverError, setServerError] = useState<string | null>(null)

  const createChoice = useCreateChoice(profileId)

  // Step 1: Resolve round_id (from currentPathId nếu available, else override)
  const { data: currentPathDetail, isLoading: loadingCurrentPath } = useQuery({
    queryKey: ["admission-path", currentPathId],
    queryFn: () => getAdmissionPath(currentPathId as number),
    enabled: open && currentPathId !== null && roundIdOverride === undefined,
  })

  const roundId = useMemo(() => {
    if (roundIdOverride !== undefined) return roundIdOverride
    return currentPathDetail?.admission_round_id ?? null
  }, [roundIdOverride, currentPathDetail])

  // Step 2: Load list paths in round
  const { data: pathsData, isLoading: loadingPaths } = useQuery({
    queryKey: ["paths-by-round", roundId],
    queryFn: () => getPathsByRound(roundId as number),
    enabled: open && roundId !== null,
  })

  // Step 3: Load sg_configs khi user picks path
  const { data: configsData, isLoading: loadingConfigs } = useQuery({
    queryKey: ["path-sg-configs", selectedPathId],
    queryFn: () => getPathSubjectGroupConfigs(selectedPathId as number),
    enabled: open && selectedPathId !== null,
  })

  const selectedConfig = useMemo(() => {
    return configsData?.items.find((c) => c.id === selectedConfigId) ?? null
  }, [configsData, selectedConfigId])

  // Reset selections when dialog reopens
  useEffect(() => {
    if (open) {
      setSelectedPathId(null)
      setSelectedConfigId(null)
      setScores([])
      setServerError(null)
    }
  }, [open])

  // Initialize scores rows when sg_config selected
  useEffect(() => {
    if (selectedConfig) {
      setScores(
        selectedConfig.subjects.map((s) => ({
          subject_id: s.subject_id,
          value: "",
          error: null,
        })),
      )
    } else {
      setScores([])
    }
  }, [selectedConfig])

  const validateScore = (
    raw: string,
    min: number,
    max: number,
  ): string | null => {
    const trimmed = raw.trim()
    if (trimmed === "") return "Bắt buộc nhập điểm"
    const parsed = Number(trimmed)
    if (Number.isNaN(parsed)) return "Điểm phải là số hợp lệ"
    if (parsed < min) return `Điểm tối thiểu là ${min}`
    if (parsed > max) return `Điểm tối đa là ${max}`
    return null
  }

  const handleScoreChange = (subjectId: number, value: string) => {
    if (!selectedConfig) return
    const subj = selectedConfig.subjects.find((s) => s.subject_id === subjectId)
    if (!subj) return
    const error = validateScore(value, subj.min_possible_score, subj.max_score)
    setScores((prev) =>
      prev.map((s) =>
        s.subject_id === subjectId ? { ...s, value, error } : s,
      ),
    )
  }

  const allValid =
    scores.length > 0 &&
    scores.every((s) => s.error === null && s.value.trim() !== "") &&
    selectedPathId !== null &&
    selectedConfigId !== null

  const handleSubmit = () => {
    if (!allValid || !selectedPathId || !selectedConfigId) return
    setServerError(null)
    createChoice.mutate(
      {
        admission_path_id: selectedPathId,
        path_subject_group_config_id: selectedConfigId,
        display_order: nextDisplayOrder,
        scores: scores.map((s) => ({
          subject_id: s.subject_id,
          score: Number(s.value),
        })),
      },
      {
        onSuccess: () => {
          toast.success(`Đã thêm NV${nextDisplayOrder}`)
          onClose()
        },
        onError: (err) => {
          setServerError(
            parseApiError(err, "Không thể thêm nguyện vọng. Vui lòng thử lại."),
          )
        },
      },
    )
  }

  const isLoading = loadingCurrentPath || loadingPaths
  const isSubmitting = createChoice.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Thêm nguyện vọng NV{nextDisplayOrder}</DialogTitle>
          <DialogDescription>
            Chọn ngành đăng ký, tổ hợp môn xét tuyển và nhập điểm các môn.
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Đang tải dữ liệu…
          </div>
        )}

        {!isLoading && roundId === null && (
          <Alert variant="destructive">
            <AlertDescription>
              Không xác định được đợt xét tuyển hiện tại của hồ sơ. Liên hệ
              quản trị viên.
            </AlertDescription>
          </Alert>
        )}

        {!isLoading && roundId !== null && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="select-path">Ngành / Phương thức xét tuyển</Label>
              <Select
                value={selectedPathId?.toString() ?? ""}
                onValueChange={(v) => {
                  setSelectedPathId(Number(v))
                  setSelectedConfigId(null)
                }}
                disabled={loadingPaths || isSubmitting}
              >
                <SelectTrigger id="select-path">
                  <SelectValue
                    placeholder={
                      loadingPaths ? "Đang tải…" : "Chọn ngành + phương thức"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {pathsData?.items.map((p) => (
                    <SelectItem key={p.id} value={p.id.toString()}>
                      {p.display_name || `Path ${p.id}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selectedPathId !== null && (
              <div className="space-y-2">
                <Label htmlFor="select-config">Tổ hợp môn</Label>
                <Select
                  value={selectedConfigId?.toString() ?? ""}
                  onValueChange={(v) => setSelectedConfigId(Number(v))}
                  disabled={loadingConfigs || isSubmitting}
                >
                  <SelectTrigger id="select-config">
                    <SelectValue
                      placeholder={
                        loadingConfigs ? "Đang tải…" : "Chọn tổ hợp môn"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {configsData?.items.map((c) => (
                      <SelectItem key={c.id} value={c.id.toString()}>
                        {c.subject_group_code ?? `SG ${c.subject_group_id}`}
                        {c.subject_group_name ? ` — ${c.subject_group_name}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {selectedConfig && scores.length > 0 && (
              <div className="space-y-3">
                <Label>Nhập điểm các môn</Label>
                <ul className="space-y-2">
                  {selectedConfig.subjects.map((subj) => {
                    const scoreState = scores.find(
                      (s) => s.subject_id === subj.subject_id,
                    )
                    const inputId = `add-score-${subj.subject_id}`
                    return (
                      <li
                        key={subj.subject_id}
                        className="flex items-start gap-3"
                      >
                        <div className="flex-1 min-w-0">
                          <Label htmlFor={inputId} className="text-sm">
                            {subj.subject_code} — {subj.subject_name}
                          </Label>
                          <div className="mt-1 flex items-center gap-2">
                            <Input
                              id={inputId}
                              type="number"
                              step="0.01"
                              min={subj.min_possible_score}
                              max={subj.max_score}
                              value={scoreState?.value ?? ""}
                              disabled={isSubmitting}
                              onChange={(e) =>
                                handleScoreChange(subj.subject_id, e.target.value)
                              }
                              aria-invalid={scoreState?.error !== null}
                              className="w-32"
                            />
                            <span className="text-xs text-muted-foreground">
                              / {subj.max_score}
                            </span>
                          </div>
                          {scoreState?.error && (
                            <p className="mt-1 text-xs text-destructive">
                              {scoreState.error}
                            </p>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {serverError && (
              <Alert variant="destructive">
                <AlertDescription>{serverError}</AlertDescription>
              </Alert>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Huỷ
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!allValid || isSubmitting}
          >
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Thêm nguyện vọng
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
