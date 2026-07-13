// src/components/common/MobileActionSheet.tsx
/**
 * MobileActionSheet - Mobile-optimized bottom sheet for actions
 *
 * A bottom sheet pattern for displaying action menus on mobile devices.
 * Features:
 * - Drag handle for visual affordance
 * - Safe area padding for notched devices
 * - Smooth animations
 * - Touch-friendly action items
 *
 * Usage:
 * ```tsx
 * <MobileActionSheet
 *   open={open}
 *   onOpenChange={setOpen}
 *   title="Lead Actions"
 * >
 *   <MobileActionSheet.Item icon={Edit} onClick={handleEdit}>
 *     Edit Lead
 *   </MobileActionSheet.Item>
 *   <MobileActionSheet.Item icon={Trash2} variant="destructive" onClick={handleDelete}>
 *     Delete Lead
 *   </MobileActionSheet.Item>
 * </MobileActionSheet>
 * ```
 */
"use client";

import * as React from "react";
import { LucideIcon } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface MobileActionSheetProps {
  /** Controlled open state */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Sheet title */
  title?: string;
  /** Sheet description */
  description?: string;
  /** Children (ActionItem components) */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface ActionItemProps {
  /** Action icon */
  icon?: LucideIcon;
  /** Action label */
  children: React.ReactNode;
  /** Click handler */
  onClick?: () => void;
  /** Disabled state */
  disabled?: boolean;
  /** Variant */
  variant?: "default" | "destructive";
  /** Render as a real anchor (tel:/mailto:/https) instead of a button. */
  href?: string;
  /** Anchor target (e.g. "_blank" for external links). Only with href. */
  target?: string;
  /** Additional class name */
  className?: string;
}

interface ActionGroupProps {
  /** Group label */
  label?: string;
  /** Group children */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function MobileActionSheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: MobileActionSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className={cn(
          // Override default padding
          "p-0",
          // Rounded top corners
          "rounded-t-2xl",
          // Max height with safe area
          "max-h-[85vh]",
          "pb-[env(safe-area-inset-bottom)]",
          className
        )}
      >
        {/* Drag Handle */}
        <div className="flex justify-center pt-3 pb-2">
          <div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
        </div>

        {/* Header */}
        {(title || description) && (
          <SheetHeader className="px-4 pb-2 text-left">
            {title && <SheetTitle className="text-base">{title}</SheetTitle>}
            {description && (
              <SheetDescription className="text-sm">
                {description}
              </SheetDescription>
            )}
          </SheetHeader>
        )}

        {/* Actions */}
        <div className="overflow-y-auto overscroll-contain px-2 pb-4 space-y-1">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

// =============================================================================
// ACTION ITEM
// =============================================================================

function ActionItem({
  icon: Icon,
  children,
  onClick,
  disabled,
  variant = "default",
  href,
  target,
  className,
}: ActionItemProps) {
  const itemClass = cn(
    // Base styles
    "w-full flex items-center gap-3 px-4 py-3 rounded-lg",
    "text-left text-sm font-medium",
    "transition-colors",
    // Touch target
    "min-h-[48px]",
    // States
    "hover:bg-accent active:bg-accent/80",
    "disabled:opacity-50 disabled:cursor-not-allowed",
    // Variants
    variant === "destructive" && [
      "text-destructive",
      "hover:bg-destructive/10",
      "active:bg-destructive/20",
    ],
    className
  );

  const inner = (
    <>
      {Icon && (
        <Icon
          className={cn(
            "h-5 w-5 shrink-0",
            variant === "destructive" ? "text-destructive" : "text-muted-foreground"
          )}
        />
      )}
      <span className="flex-1">{children}</span>
    </>
  );

  // href → anchor thật (tel:/mailto:/https) theo link semantics, tránh
  // window.open('tel:', '_blank') mở tab trắng trên mobile. onClick vẫn chạy
  // (đóng sheet) trước khi trình duyệt xử lý href.
  if (href) {
    return (
      <a
        href={href}
        target={target}
        rel={target === "_blank" ? "noopener noreferrer" : undefined}
        onClick={onClick}
        className={itemClass}
      >
        {inner}
      </a>
    );
  }

  return (
    <button type="button" onClick={onClick} disabled={disabled} className={itemClass}>
      {inner}
    </button>
  );
}

// =============================================================================
// ACTION GROUP
// =============================================================================

function ActionGroup({ label, children, className }: ActionGroupProps) {
  return (
    <div className={cn("", className)}>
      {label && (
        <div className="px-4 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </div>
      )}
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

// =============================================================================
// DIVIDER
// =============================================================================

function ActionDivider({ className }: { className?: string }) {
  return <div className={cn("my-2 border-t", className)} />;
}

// =============================================================================
// CANCEL BUTTON
// =============================================================================

interface CancelButtonProps {
  /** Button label */
  children?: React.ReactNode;
  /** Click handler */
  onClick?: () => void;
  /** Additional class name */
  className?: string;
}

function CancelButton({
  children = "Hủy",
  onClick,
  className,
}: CancelButtonProps) {
  return (
    <div className={cn("px-2 pt-2 border-t", className)}>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "w-full flex items-center justify-center px-4 py-3 rounded-lg",
          "text-sm font-semibold text-primary",
          "bg-accent hover:bg-accent/80 active:bg-accent/60",
          "transition-colors",
          "min-h-[48px]"
        )}
      >
        {children}
      </button>
    </div>
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

// Attach subcomponents
MobileActionSheet.Item = ActionItem;
MobileActionSheet.Group = ActionGroup;
MobileActionSheet.Divider = ActionDivider;
MobileActionSheet.Cancel = CancelButton;

export { MobileActionSheet };
export type { MobileActionSheetProps, ActionItemProps, ActionGroupProps };
export default MobileActionSheet;
