// src/components/common/form/FormInput.tsx
"use client";

import * as React from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export type InputType = "text" | "email" | "password" | "tel" | "url" | "number";

export interface FormInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Input type */
  type?: InputType;
  /** Field label */
  label?: string;
  /** Helper text shown below input */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Container class name */
  containerClassName?: string;
  /** Show password toggle for password type */
  showPasswordToggle?: boolean;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const FormInput = React.forwardRef<HTMLInputElement, FormInputProps>(
  (
    {
      type = "text",
      label,
      description,
      error,
      required,
      containerClassName,
      className,
      id,
      showPasswordToggle = true,
      disabled,
      ...props
    },
    ref
  ) => {
    const [showPassword, setShowPassword] = React.useState(false);
    const inputId = id || React.useId();

    // Determine actual input type (for password toggle)
    const actualType = type === "password" && showPassword ? "text" : type;

    // Handle password visibility toggle
    const togglePassword = React.useCallback(() => {
      setShowPassword((prev) => !prev);
    }, []);

    const hasError = !!error;
    const isPassword = type === "password";

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

        {/* Input wrapper */}
        <div className="relative">
          <Input
            ref={ref}
            id={inputId}
            type={actualType}
            disabled={disabled}
            className={cn(
              hasError && "border-destructive focus-visible:ring-destructive",
              isPassword && showPasswordToggle && "pr-10",
              className
            )}
            aria-invalid={hasError}
            aria-describedby={
              error ? `${inputId}-error` : description ? `${inputId}-description` : undefined
            }
            {...props}
          />

          {/* Password toggle button */}
          {isPassword && showPasswordToggle && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
              onClick={togglePassword}
              disabled={disabled}
              aria-label={showPassword ? "An mat khau" : "Hien mat khau"}
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4 text-muted-foreground" />
              ) : (
                <Eye className="h-4 w-4 text-muted-foreground" />
              )}
            </Button>
          )}
        </div>

        {/* Description */}
        {description && !error && (
          <p
            id={`${inputId}-description`}
            className="text-sm text-muted-foreground"
          >
            {description}
          </p>
        )}

        {/* Error message */}
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
    );
  }
);

FormInput.displayName = "FormInput";

export default FormInput;
