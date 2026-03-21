// src/components/leads/LossReasonQuickSelect.tsx
/**
 * LossReasonQuickSelect - Quick-select buttons for loss reasons
 *
 * SPEC: LOSS_REASON_UX_SPEC.md
 * - Shows for all negative outcomes (showsLossReason)
 * - Required only for final negative (requiresLossReason)
 * - 1-click selection for common reasons
 * - "Other" option expands input for custom reason
 */

"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { AlertCircle } from "lucide-react";
import { LOSS_REASONS as FALLBACK_LOSS_REASONS } from "@/lib/loss-reasons";
import { useLossReasons } from "@/hooks/usePipeline";

// Re-export for backward compatibility (other components import from here)
export type { LossReason } from "@/lib/loss-reasons";
export { getLossReasonLabel } from "@/lib/loss-reasons";
export const LOSS_REASONS = FALLBACK_LOSS_REASONS;

// =============================================================================
// COMPONENT
// =============================================================================

interface LossReasonQuickSelectProps {
  /** Currently selected reason code */
  value: string | null;
  /** Callback when reason is selected */
  onChange: (code: string | null, note?: string) => void;
  /** Additional note (for "OTHER" case) */
  note?: string;
  /** Called when note changes */
  onNoteChange?: (note: string) => void;
  /** Show validation error */
  error?: string;
  /** Label text */
  label?: string;
  /** Whether selection is required */
  required?: boolean;
  /** Disable all interactions */
  disabled?: boolean;
  /** Custom class name */
  className?: string;
}

export function LossReasonQuickSelect({
  value,
  onChange,
  note = "",
  onNoteChange,
  error,
  label = "Lý do không tiếp tục?",
  required = true,
  disabled = false,
  className,
}: LossReasonQuickSelectProps) {
  const { data: apiLossReasons } = useLossReasons();
  const lossReasons = apiLossReasons ?? FALLBACK_LOSS_REASONS;
  const [localNote, setLocalNote] = useState(note);

  // Sync localNote when parent resets note prop (e.g., switching between statuses)
  useEffect(() => {
    setLocalNote(note);
  }, [note]);

  const handleSelect = (code: string) => {
    if (disabled) return;

    // Toggle selection if same code clicked
    if (value === code) {
      onChange(null);
    } else {
      onChange(code);
    }
  };

  const handleNoteChange = (newNote: string) => {
    setLocalNote(newNote);
    onNoteChange?.(newNote);
  };

  const showNoteInput = value === "OTHER";

  return (
    <div className={cn("space-y-3", className)}>
      {/* Label */}
      <Label className="flex items-center gap-1.5">
        {label}
        {required && <span className="text-destructive">*</span>}
      </Label>

      {/* Quick-select buttons */}
      <div className="flex flex-wrap gap-1.5">
        {lossReasons.map((reason) => {
          const isSelected = value === reason.code;

          return (
            <button
              key={reason.code}
              type="button"
              onClick={() => handleSelect(reason.code)}
              disabled={disabled}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
                "hover:border-primary/50 hover:bg-primary/5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1",
                isSelected
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-muted bg-background text-muted-foreground",
                disabled && "cursor-not-allowed opacity-50"
              )}
              aria-pressed={isSelected}
              aria-label={`${reason.label}: ${isSelected ? "đã chọn" : "chưa chọn"}`}
            >
              <span className="text-sm" role="img" aria-hidden="true">
                {reason.icon}
              </span>
              {reason.label}
            </button>
          );
        })}
      </div>

      {/* Note input for "OTHER" */}
      {showNoteInput && (
        <div className="animate-in slide-in-from-top-1 fade-in-50 duration-200">
          <Input
            placeholder="Mô tả ngắn gọn lý do..."
            value={localNote}
            onChange={(e) => handleNoteChange(e.target.value)}
            disabled={disabled}
            className="mt-2"
            maxLength={200}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Tùy chọn - giúp phân tích sau này
          </p>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="flex items-center gap-1.5 text-sm text-destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// HELPERS: Loss reason visibility & requirement
// =============================================================================

/**
 * Show loss reason picker for all negative outcomes.
 * Officer can optionally provide a reason even for non-final statuses.
 */
export function showsLossReason(status: {
  outcome_type?: string;
} | null | undefined): boolean {
  if (!status) return false;
  return status.outcome_type === "negative";
}

/**
 * Block save until loss reason is selected.
 * Only for final + negative statuses (matching backend validation).
 */
export function requiresLossReason(status: {
  is_final?: boolean;
  outcome_type?: string;
} | null | undefined): boolean {
  if (!status) return false;
  return status.is_final === true && status.outcome_type === "negative";
}

export default LossReasonQuickSelect;
