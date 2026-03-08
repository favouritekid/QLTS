// src/components/leads/LossReasonQuickSelect.tsx
/**
 * LossReasonQuickSelect - Quick-select buttons for loss reasons
 *
 * SPEC: LOSS_REASON_UX_SPEC.md
 * - Shows when officer selects a final negative status
 * - 1-click selection for common reasons
 * - "Other" option expands input for custom reason
 * - Touch-friendly (min 44px touch targets)
 */

"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { AlertCircle } from "lucide-react";

// =============================================================================
// LOSS REASON DEFINITIONS
// =============================================================================

export interface LossReason {
  code: string;
  label: string;
  icon: string;
  category: "price" | "logistics" | "competitor" | "contact" | "timing" | "quality" | "financial" | "other";
  isRecoverable: boolean;
}

export const LOSS_REASONS: LossReason[] = [
  { code: "PRICE_HIGH", label: "Học phí", icon: "💰", category: "price", isRecoverable: true },
  { code: "LOCATION_FAR", label: "Xa nhà", icon: "📍", category: "logistics", isRecoverable: true },
  { code: "CHOSE_COMPETITOR", label: "Trường khác", icon: "🎓", category: "competitor", isRecoverable: false },
  { code: "NO_CONTACT", label: "K.liên lạc", icon: "📞", category: "contact", isRecoverable: true },
  { code: "TIMING_BAD", label: "Chưa sẵn sàng", icon: "⏰", category: "timing", isRecoverable: true },
  { code: "OTHER", label: "Khác", icon: "❓", category: "other", isRecoverable: true },
];

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

      {/* Quick-select buttons grid */}
      <div className="grid grid-cols-3 gap-2">
        {LOSS_REASONS.map((reason) => {
          const isSelected = value === reason.code;

          return (
            <button
              key={reason.code}
              type="button"
              onClick={() => handleSelect(reason.code)}
              disabled={disabled}
              className={cn(
                // Base styles
                "flex flex-col items-center justify-center gap-1",
                "rounded-lg border-2 p-3",
                "min-h-[64px] transition-colors duration-150",
                // Touch target
                "min-h-[48px] md:min-h-[64px]",
                // Hover/Focus states
                "hover:border-primary/50 hover:bg-primary/5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
                // Selected state
                isSelected
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-muted bg-background",
                // Disabled state
                disabled && "cursor-not-allowed opacity-50"
              )}
              aria-pressed={isSelected}
              aria-label={`${reason.label}: ${isSelected ? "đã chọn" : "chưa chọn"}`}
            >
              <span className="text-lg md:text-xl" role="img" aria-hidden="true">
                {reason.icon}
              </span>
              <span className={cn(
                "text-xs font-medium leading-tight text-center",
                isSelected ? "text-primary" : "text-muted-foreground"
              )}>
                {reason.label}
              </span>
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
// HELPER: Check if status requires loss reason
// =============================================================================

export function requiresLossReason(status: {
  is_final?: boolean;
  outcome_type?: string;
} | null | undefined): boolean {
  if (!status) return false;
  return status.is_final === true && status.outcome_type === "negative";
}

// =============================================================================
// HELPER: Get loss reason label by code
// =============================================================================

export function getLossReasonLabel(code: string | null | undefined): string {
  if (!code) return "";
  const reason = LOSS_REASONS.find((r) => r.code === code);
  return reason ? `${reason.icon} ${reason.label}` : code;
}

export default LossReasonQuickSelect;
