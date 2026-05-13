"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — Retroactive add-choice gate button.
 *
 * Per Plan v0.7: retroactive add-choice button conditional via
 * `hasAction(profile, 'add_choice')` typed; backend populates `add_choice`
 * action ONLY when status ∈ (draft, revision_requested) + round.allow_multi_nv
 * + count < system_config.max_choices_per_profile.
 *
 * UX:
 *   - Backend present `add_choice` → enabled button + tooltip "Thêm nguyện vọng mới"
 *   - Backend absent (status, max, round) → disabled button + tooltip reason
 *
 * Thin client: FE NEVER computes the precheck — only renders BE-driven flag.
 * If precheck fails on BE side (post-submit race), the POST /choices
 * endpoint returns 400 BusinessRuleViolation handled by parent mutation.
 */
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { hasAction } from "@/lib/admission/permissions"

export interface AddChoiceGateProps {
  /** Profile object containing available_actions_v2 (or legacy list). */
  profile:
    | {
        available_actions?: string[]
        available_actions_v2?: { action: string; target?: number; endpoint?: string }[]
      }
    | null
    | undefined
  /**
   * Click handler — fires only when gate allows. Parent typically opens an
   * AddChoiceDialog (Bundle 4 candidate) that POSTs /choices.
   */
  onAdd: () => void
  /**
   * Optional hint shown when disabled. Defaults to a generic message — caller
   * can override with context-specific reason (e.g. "Hồ sơ đã nộp, không thể
   * thêm nguyện vọng" or "Đã đạt tối đa 5 nguyện vọng").
   */
  disabledReason?: string
}

const DEFAULT_DISABLED_HINT =
  "Không thể thêm nguyện vọng ở trạng thái hiện tại (hồ sơ đã nộp hoặc đã đạt giới hạn nguyện vọng)."

export function AddChoiceGate({
  profile,
  onAdd,
  disabledReason,
}: AddChoiceGateProps) {
  const allowed = hasAction(profile, "add_choice")
  const hint = disabledReason ?? DEFAULT_DISABLED_HINT

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          {/* Wrap disabled button in span — pointer-events lost on disabled
              button means tooltip wouldn't fire otherwise. */}
          <span className={!allowed ? "inline-block" : undefined}>
            <Button
              type="button"
              size="sm"
              onClick={onAdd}
              disabled={!allowed}
              aria-disabled={!allowed}
              data-testid="add-choice-gate-button"
            >
              <Plus className="mr-1 h-4 w-4" />
              Thêm nguyện vọng
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>
          {allowed ? "Thêm nguyện vọng mới vào hồ sơ" : hint}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
