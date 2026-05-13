"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Day 8 — ChoiceScoreCard.
 *
 * Per-choice score input renderer.
 *
 * Consumes 1 BE-1 endpoint:
 *   - PATCH /api/v2/admissions/{profile_id}/choices/{choice_id}/scores
 *     (idempotent set semantics — replaces all scores in one shot)
 *
 * Renders existing `choice.scores[]` rows; each subject input is bounded
 * by its `max_score_snapshot` + `min_possible_score_snapshot` (BE-frozen
 * at choice-create time per snapshot pattern). Range hint via Tooltip.
 *
 * onBlur save:
 *   1. Validate input within [min, max]
 *   2. Build full replacement payload from current local state
 *   3. PATCH /scores (idempotent — server clears + re-inserts)
 *   4. Revert local state to server response on error (axios message)
 *
 * Optimistic UI: input visible state updates immediately; mutation
 * settles in background. Local state diverges from props during edit
 * then re-syncs from server response onSettled.
 */
import { useEffect, useState } from "react"
import { Info, Loader2 } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useReplaceChoiceScores } from "@/hooks/admissions/useAdmissionChoices"
import { parseApiError } from "@/lib/utils/api-errors"
import type {
  AdmissionProfileChoiceResponse,
  ChoiceScoreInput,
  ChoiceScoreSummary,
} from "@/lib/zod/admission-choices"

export interface ChoiceScoreCardProps {
  profileId: number
  choice: AdmissionProfileChoiceResponse
  /** BE-driven flag — backend tells FE whether mutation is allowed. */
  canEdit: boolean
}

interface EditableScore extends ChoiceScoreSummary {
  /** Local input string — empty string allowed mid-edit before parse. */
  inputValue: string
  /** Validation error message (null = valid). */
  error: string | null
}

function toEditable(s: ChoiceScoreSummary): EditableScore {
  return {
    ...s,
    inputValue: String(s.score),
    error: null,
  }
}

function validateScore(
  raw: string,
  min: number | null,
  max: number,
): string | null {
  const trimmed = raw.trim()
  if (trimmed === "") return "Bắt buộc nhập điểm"
  const parsed = Number(trimmed)
  if (Number.isNaN(parsed)) return "Điểm phải là số hợp lệ"
  const floor = min ?? 0
  if (parsed < floor) return `Điểm tối thiểu là ${floor}`
  if (parsed > max) return `Điểm tối đa là ${max}`
  return null
}

export function ChoiceScoreCard({
  profileId,
  choice,
  canEdit,
}: ChoiceScoreCardProps) {
  const [editedScores, setEditedScores] = useState<EditableScore[]>(() =>
    choice.scores.map(toEditable),
  )
  const [serverError, setServerError] = useState<string | null>(null)

  const mutation = useReplaceChoiceScores(profileId)

  // Re-sync from props when the parent re-fetches (after another mutation
  // succeeds or socket data_updated invalidates). Local edits in flight
  // will be overwritten — acceptable per onBlur-save pattern (no long-lived
  // unsaved drafts).
  useEffect(() => {
    setEditedScores(choice.scores.map(toEditable))
  }, [choice.scores])

  const handleChange = (subjectId: number, raw: string) => {
    setEditedScores((prev) =>
      prev.map((s) =>
        s.subject_id === subjectId
          ? {
              ...s,
              inputValue: raw,
              error: validateScore(
                raw,
                s.min_possible_score_snapshot,
                s.max_score_snapshot,
              ),
            }
          : s,
      ),
    )
  }

  const handleBlur = (subjectId: number) => {
    const current = editedScores.find((s) => s.subject_id === subjectId)
    if (!current) return
    if (current.error !== null) return // Don't save while invalid

    const parsed = Number(current.inputValue)
    if (Number.isNaN(parsed)) return
    if (parsed === current.score) return // No-op when unchanged

    const payload: { scores: ChoiceScoreInput[] } = {
      scores: editedScores.map((s) => ({
        subject_id: s.subject_id,
        score: s.subject_id === subjectId ? parsed : s.score,
      })),
    }

    setServerError(null)
    mutation.mutate(
      { choiceId: choice.id, payload },
      {
        onError: (err) => {
          // Revert local row to server value on error
          setEditedScores((prev) =>
            prev.map((s) =>
              s.subject_id === subjectId
                ? {
                    ...s,
                    inputValue: String(s.score),
                    error: null,
                  }
                : s,
            ),
          )
          setServerError(
            parseApiError(err, "Không thể lưu điểm. Vui lòng thử lại."),
          )
        },
      },
    )
  }

  if (choice.scores.length === 0) {
    return (
      <p
        className="rounded-md border border-dashed p-3 text-sm text-muted-foreground"
        data-testid="choice-score-card-empty"
      >
        Chưa có môn nào ghi điểm cho nguyện vọng này.
      </p>
    )
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div
        className="space-y-2"
        data-testid={`choice-score-card-${choice.id}`}
      >
        <header className="flex items-center justify-between">
          <h4 className="text-sm font-medium">
            Điểm NV{choice.display_order}
            {choice.display_subject_group_name
              ? ` — ${choice.display_subject_group_name}`
              : ""}
          </h4>
          {mutation.isPending && (
            <span
              className="inline-flex items-center gap-1 text-xs text-muted-foreground"
              data-testid="score-saving-indicator"
            >
              <Loader2 className="h-3 w-3 animate-spin" />
              Đang lưu…
            </span>
          )}
        </header>

        <ul className="space-y-2">
          {editedScores.map((s) => {
            const min = s.min_possible_score_snapshot ?? 0
            const inputId = `score-${choice.id}-${s.subject_id}`
            return (
              <li
                key={s.subject_id}
                className="flex items-start gap-3"
                data-testid={`score-row-${s.subject_id}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <Label htmlFor={inputId} className="text-sm">
                      {s.subject_code} — {s.subject_name}
                    </Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label={`Khoảng điểm ${min}–${s.max_score_snapshot}, hệ số ${s.weight_snapshot}`}
                          className="text-muted-foreground"
                        >
                          <Info className="h-3 w-3" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Khoảng điểm: {min} – {s.max_score_snapshot} · Hệ số:{" "}
                        {s.weight_snapshot}
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <Input
                      id={inputId}
                      type="number"
                      step="0.01"
                      min={min}
                      max={s.max_score_snapshot}
                      value={s.inputValue}
                      disabled={!canEdit}
                      onChange={(e) =>
                        handleChange(s.subject_id, e.target.value)
                      }
                      onBlur={() => handleBlur(s.subject_id)}
                      aria-invalid={s.error !== null}
                      aria-describedby={
                        s.error ? `${inputId}-error` : undefined
                      }
                      className="w-32"
                      data-testid={`score-input-${s.subject_id}`}
                    />
                    <span className="text-xs text-muted-foreground">
                      / {s.max_score_snapshot}
                    </span>
                  </div>
                  {s.error && (
                    <p
                      id={`${inputId}-error`}
                      role="alert"
                      className="mt-0.5 text-xs text-destructive"
                      data-testid={`score-error-${s.subject_id}`}
                    >
                      {s.error}
                    </p>
                  )}
                </div>
              </li>
            )
          })}
        </ul>

        {serverError && (
          <p
            role="alert"
            className="text-xs text-destructive"
            data-testid="score-server-error"
          >
            {serverError}
          </p>
        )}
      </div>
    </TooltipProvider>
  )
}
