// src/components/common/form/FormTextarea.tsx
"use client";

import * as React from "react";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface FormTextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Field label */
  label?: string;
  /** Helper text shown below textarea */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Container class name */
  containerClassName?: string;
  /** Show character count */
  showCharCount?: boolean;
  /** Auto-resize to fit content */
  autoResize?: boolean;
  /** Minimum rows for auto-resize */
  minRows?: number;
  /** Maximum rows for auto-resize */
  maxRows?: number;
}

// =============================================================================
// HELPER HOOK
// =============================================================================

function useAutoResize(
  ref: React.RefObject<HTMLTextAreaElement>,
  value: string | number | readonly string[] | undefined,
  enabled: boolean,
  minRows: number,
  maxRows: number
) {
  React.useEffect(() => {
    const textarea = ref.current;
    if (!textarea || !enabled) return;

    // Reset height to auto to get the correct scrollHeight
    textarea.style.height = "auto";

    // Calculate line height
    const computedStyle = window.getComputedStyle(textarea);
    const lineHeight = parseInt(computedStyle.lineHeight) || 20;
    const paddingTop = parseInt(computedStyle.paddingTop) || 0;
    const paddingBottom = parseInt(computedStyle.paddingBottom) || 0;
    const borderTop = parseInt(computedStyle.borderTopWidth) || 0;
    const borderBottom = parseInt(computedStyle.borderBottomWidth) || 0;

    const minHeight = lineHeight * minRows + paddingTop + paddingBottom + borderTop + borderBottom;
    const maxHeight = lineHeight * maxRows + paddingTop + paddingBottom + borderTop + borderBottom;

    // Set the height based on scrollHeight
    const newHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    textarea.style.height = `${newHeight}px`;
  }, [ref, value, enabled, minRows, maxRows]);
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const FormTextarea = React.forwardRef<HTMLTextAreaElement, FormTextareaProps>(
  (
    {
      label,
      description,
      error,
      required,
      containerClassName,
      className,
      id,
      maxLength,
      showCharCount = false,
      autoResize = false,
      minRows = 3,
      maxRows = 10,
      value,
      disabled,
      ...props
    },
    ref
  ) => {
    const inputId = id || React.useId();
    const internalRef = React.useRef<HTMLTextAreaElement>(null);
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) || internalRef;

    // Auto-resize functionality
    useAutoResize(textareaRef, value, autoResize, minRows, maxRows);

    const hasError = !!error;
    const currentLength = typeof value === "string" ? value.length : 0;
    const showCount = showCharCount && maxLength;

    return (
      <div className={cn("space-y-2", containerClassName)}>
        {/* Label */}
        {label && (
          <Label
            htmlFor={inputId}
            className={cn(hasError && "text-destructive")}
          >
            {label}
            {required && <span className="text-destructive ml-1">*</span>}
          </Label>
        )}

        {/* Textarea */}
        <Textarea
          ref={textareaRef}
          id={inputId}
          value={value}
          disabled={disabled}
          maxLength={maxLength}
          className={cn(
            hasError && "border-destructive focus-visible:ring-destructive",
            autoResize && "resize-none overflow-hidden",
            className
          )}
          aria-invalid={hasError}
          aria-describedby={
            error ? `${inputId}-error` : description ? `${inputId}-description` : undefined
          }
          rows={autoResize ? minRows : undefined}
          {...props}
        />

        {/* Footer row */}
        <div className="flex items-center justify-between">
          {/* Description / Error */}
          <div className="flex-1">
            {description && !error && (
              <p
                id={`${inputId}-description`}
                className="text-sm text-muted-foreground"
              >
                {description}
              </p>
            )}

            {error && (
              <p
                id={`${inputId}-error`}
                className="text-sm font-medium text-destructive"
                role="alert"
              >
                {error}
              </p>
            )}
          </div>

          {/* Character count */}
          {showCount && (
            <p
              className={cn(
                "text-sm text-muted-foreground ml-2",
                maxLength && currentLength >= maxLength && "text-destructive"
              )}
            >
              {currentLength}/{maxLength}
            </p>
          )}
        </div>
      </div>
    );
  }
);

FormTextarea.displayName = "FormTextarea";

export default FormTextarea;
