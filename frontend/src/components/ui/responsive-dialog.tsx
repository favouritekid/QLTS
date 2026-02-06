// src/components/ui/responsive-dialog.tsx
/**
 * ResponsiveDialog - Automatically switches between Dialog and bottom Sheet
 *
 * On desktop (≥768px): Renders as centered Dialog
 * On mobile (<768px): Renders as bottom Sheet for better touch experience
 *
 * Usage:
 * ```tsx
 * <ResponsiveDialog open={open} onOpenChange={setOpen}>
 *   <ResponsiveDialogContent>
 *     <ResponsiveDialogHeader>
 *       <ResponsiveDialogTitle>Title</ResponsiveDialogTitle>
 *       <ResponsiveDialogDescription>Description</ResponsiveDialogDescription>
 *     </ResponsiveDialogHeader>
 *     <div>Content here</div>
 *     <ResponsiveDialogFooter>
 *       <Button onClick={() => setOpen(false)}>Cancel</Button>
 *       <Button>Confirm</Button>
 *     </ResponsiveDialogFooter>
 *   </ResponsiveDialogContent>
 * </ResponsiveDialog>
 * ```
 */
"use client";

import * as React from "react";
import { useIsMobile } from "@/hooks/useMediaQuery";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface ResponsiveDialogProps {
  /** Controlled open state */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Children */
  children: React.ReactNode;
}

interface ResponsiveDialogContentProps {
  /** Content children */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface ResponsiveDialogHeaderProps {
  /** Header children */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface ResponsiveDialogFooterProps {
  /** Footer children */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface ResponsiveDialogTitleProps {
  /** Title text */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface ResponsiveDialogDescriptionProps {
  /** Description text */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// CONTEXT
// =============================================================================

const ResponsiveDialogContext = React.createContext<{
  isMobile: boolean;
}>({
  isMobile: false,
});

function useResponsiveDialogContext() {
  return React.useContext(ResponsiveDialogContext);
}

// =============================================================================
// ROOT COMPONENT
// =============================================================================

function ResponsiveDialog({
  open,
  onOpenChange,
  children,
}: ResponsiveDialogProps) {
  const isMobile = useIsMobile();

  return (
    <ResponsiveDialogContext.Provider value={{ isMobile }}>
      {isMobile ? (
        <Sheet open={open} onOpenChange={onOpenChange}>
          {children}
        </Sheet>
      ) : (
        <Dialog open={open} onOpenChange={onOpenChange}>
          {children}
        </Dialog>
      )}
    </ResponsiveDialogContext.Provider>
  );
}

// =============================================================================
// CONTENT
// =============================================================================

function ResponsiveDialogContent({
  children,
  className,
}: ResponsiveDialogContentProps) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return (
      <SheetContent
        side="bottom"
        className={cn(
          // Override default padding for mobile sheet
          "p-0",
          // Rounded top corners
          "rounded-t-2xl",
          // Max height with safe area
          "max-h-[90vh]",
          "pb-[env(safe-area-inset-bottom)]",
          className
        )}
      >
        {/* Drag Handle */}
        <div className="flex justify-center pt-3 pb-2">
          <div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
        </div>
        {/* Content with padding and scroll */}
        <div className="px-4 pb-4 overflow-y-auto max-h-[calc(90vh-40px)]">
          {children}
        </div>
      </SheetContent>
    );
  }

  return (
    <DialogContent className={className}>
      {children}
    </DialogContent>
  );
}

// =============================================================================
// HEADER
// =============================================================================

function ResponsiveDialogHeader({
  children,
  className,
}: ResponsiveDialogHeaderProps) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return (
      <SheetHeader className={cn("text-left pb-4", className)}>
        {children}
      </SheetHeader>
    );
  }

  return <DialogHeader className={className}>{children}</DialogHeader>;
}

// =============================================================================
// FOOTER
// =============================================================================

function ResponsiveDialogFooter({
  children,
  className,
}: ResponsiveDialogFooterProps) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return (
      <SheetFooter
        className={cn(
          // Stack buttons on mobile with touch-friendly sizing
          "flex flex-col gap-2 pt-4",
          className
        )}
      >
        {children}
      </SheetFooter>
    );
  }

  return <DialogFooter className={className}>{children}</DialogFooter>;
}

// =============================================================================
// TITLE
// =============================================================================

function ResponsiveDialogTitle({
  children,
  className,
}: ResponsiveDialogTitleProps) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return <SheetTitle className={className}>{children}</SheetTitle>;
  }

  return <DialogTitle className={className}>{children}</DialogTitle>;
}

// =============================================================================
// DESCRIPTION
// =============================================================================

function ResponsiveDialogDescription({
  children,
  className,
}: ResponsiveDialogDescriptionProps) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return (
      <SheetDescription className={className}>{children}</SheetDescription>
    );
  }

  return <DialogDescription className={className}>{children}</DialogDescription>;
}

// =============================================================================
// CLOSE
// =============================================================================

function ResponsiveDialogClose({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  const { isMobile } = useResponsiveDialogContext();

  if (isMobile) {
    return <SheetClose className={className}>{children}</SheetClose>;
  }

  return <DialogClose className={className}>{children}</DialogClose>;
}

// =============================================================================
// EXPORTS
// =============================================================================

export {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogHeader,
  ResponsiveDialogFooter,
  ResponsiveDialogTitle,
  ResponsiveDialogDescription,
  ResponsiveDialogClose,
  useResponsiveDialogContext,
};
