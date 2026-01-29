// src/components/common/form/ResponsiveFormLayout.tsx
/**
 * ResponsiveFormLayout - Standardized responsive form layout components
 *
 * Provides consistent form layouts that work well on mobile and desktop.
 * Follows mobile-first design principles.
 *
 * Usage:
 * ```tsx
 * <FormContainer>
 *   <FormSection title="Personal Info">
 *     <FormRow columns={2}>
 *       <FormField name="firstName" />
 *       <FormField name="lastName" />
 *     </FormRow>
 *     <FormField name="email" />
 *   </FormSection>
 *   <FormActions>
 *     <Button variant="outline">Cancel</Button>
 *     <Button type="submit">Save</Button>
 *   </FormActions>
 * </FormContainer>
 * ```
 */
"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

// =============================================================================
// FORM CONTAINER
// =============================================================================

interface FormContainerProps extends React.HTMLAttributes<HTMLFormElement> {
  /** Max width on larger screens */
  maxWidth?: "sm" | "md" | "lg" | "xl" | "full";
  /** Spacing between sections */
  spacing?: "tight" | "normal" | "loose";
  /** As div instead of form */
  asDiv?: boolean;
}

const maxWidthClasses = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
  full: "max-w-full",
};

const spacingClasses = {
  tight: "space-y-4",
  normal: "space-y-6",
  loose: "space-y-8",
};

export function FormContainer({
  children,
  className,
  maxWidth = "lg",
  spacing = "normal",
  asDiv = false,
  ...props
}: FormContainerProps) {
  const Component = asDiv ? "div" : "form";

  return (
    <Component
      className={cn(
        "w-full",
        maxWidthClasses[maxWidth],
        spacingClasses[spacing],
        className
      )}
      {...(props as React.HTMLAttributes<HTMLElement>)}
    >
      {children}
    </Component>
  );
}

// =============================================================================
// FORM SECTION
// =============================================================================

interface FormSectionProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Section title */
  title?: string;
  /** Section description */
  description?: string;
  /** Spacing within section */
  spacing?: "tight" | "normal" | "loose";
}

export function FormSection({
  children,
  title,
  description,
  className,
  spacing = "normal",
  ...props
}: FormSectionProps) {
  return (
    <div className={cn("", className)} {...props}>
      {(title || description) && (
        <div className="mb-4">
          {title && (
            <h3 className="text-base font-semibold leading-7">{title}</h3>
          )}
          {description && (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      )}
      <div className={spacingClasses[spacing]}>{children}</div>
    </div>
  );
}

// =============================================================================
// FORM ROW - Responsive grid for form fields
// =============================================================================

interface FormRowProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Number of columns on larger screens */
  columns?: 1 | 2 | 3 | 4;
  /** Gap between fields */
  gap?: "sm" | "md" | "lg";
  /** Breakpoint to start multi-column */
  breakAt?: "sm" | "md" | "lg";
}

const columnClasses = {
  1: "",
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-4",
};

const gapClasses = {
  sm: "gap-3",
  md: "gap-4",
  lg: "gap-6",
};

export function FormRow({
  children,
  columns = 2,
  gap = "md",
  className,
  ...props
}: FormRowProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-1",
        columnClasses[columns],
        gapClasses[gap],
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

// =============================================================================
// FORM ACTIONS - Responsive action buttons
// =============================================================================

interface FormActionsProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Alignment of buttons */
  align?: "left" | "center" | "right" | "between";
  /** Stack buttons on mobile */
  stackOnMobile?: boolean;
  /** Show divider above */
  showDivider?: boolean;
  /** Sticky at bottom on mobile */
  stickyOnMobile?: boolean;
}

const alignClasses = {
  left: "justify-start",
  center: "justify-center",
  right: "justify-end",
  between: "justify-between",
};

export function FormActions({
  children,
  align = "right",
  stackOnMobile = true,
  showDivider = false,
  stickyOnMobile = false,
  className,
  ...props
}: FormActionsProps) {
  return (
    <div
      className={cn(
        showDivider && "border-t pt-4 mt-4",
        stickyOnMobile && "sticky bottom-0 bg-background py-4 -mx-4 px-4 border-t sm:static sm:mx-0 sm:px-0 sm:border-0 sm:py-0",
        className
      )}
      {...props}
    >
      <div
        className={cn(
          "flex gap-3",
          stackOnMobile
            ? "flex-col-reverse sm:flex-row"
            : "flex-row",
          alignClasses[align],
          // Full width buttons on mobile when stacked
          stackOnMobile && "[&>*]:w-full [&>*]:sm:w-auto"
        )}
      >
        {children}
      </div>
    </div>
  );
}

// =============================================================================
// FORM DIVIDER
// =============================================================================

interface FormDividerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Label in the middle of divider */
  label?: string;
}

export function FormDivider({ label, className, ...props }: FormDividerProps) {
  if (label) {
    return (
      <div className={cn("relative my-6", className)} {...props}>
        <div className="absolute inset-0 flex items-center">
          <span className="w-full border-t" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-background px-2 text-muted-foreground">
            {label}
          </span>
        </div>
      </div>
    );
  }

  return <div className={cn("border-t my-6", className)} {...props} />;
}

// =============================================================================
// FORM FIELD WRAPPER - For consistent spacing and labels
// =============================================================================

interface FormFieldWrapperProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Field label */
  label?: string;
  /** Required indicator */
  required?: boolean;
  /** Help text */
  helpText?: string;
  /** Error message */
  error?: string;
  /** Full width */
  fullWidth?: boolean;
}

export function FormFieldWrapper({
  children,
  label,
  required,
  helpText,
  error,
  fullWidth,
  className,
  ...props
}: FormFieldWrapperProps) {
  return (
    <div
      className={cn("space-y-2", fullWidth && "col-span-full", className)}
      {...props}
    >
      {label && (
        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
        </label>
      )}
      {children}
      {helpText && !error && (
        <p className="text-xs text-muted-foreground">{helpText}</p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

export default {
  Container: FormContainer,
  Section: FormSection,
  Row: FormRow,
  Actions: FormActions,
  Divider: FormDivider,
  FieldWrapper: FormFieldWrapper,
};
