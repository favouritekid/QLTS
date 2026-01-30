// src/components/common/ResponsiveActionMenu.tsx
/**
 * ResponsiveActionMenu - Automatically switches between DropdownMenu and MobileActionSheet
 *
 * On desktop (≥768px): Renders as DropdownMenu
 * On mobile (<768px): Renders as MobileActionSheet (bottom sheet)
 *
 * Usage:
 * ```tsx
 * const [open, setOpen] = useState(false);
 *
 * <ResponsiveActionMenu
 *   open={open}
 *   onOpenChange={setOpen}
 *   trigger={
 *     <Button variant="ghost" size="icon">
 *       <MoreVertical className="h-4 w-4" />
 *     </Button>
 *   }
 *   title="Actions"
 * >
 *   <ResponsiveActionMenu.Item icon={Edit} onClick={handleEdit}>
 *     Edit
 *   </ResponsiveActionMenu.Item>
 *   <ResponsiveActionMenu.Separator />
 *   <ResponsiveActionMenu.Item icon={Trash2} variant="destructive" onClick={handleDelete}>
 *     Delete
 *   </ResponsiveActionMenu.Item>
 * </ResponsiveActionMenu>
 * ```
 */
"use client";

import * as React from "react";
import { LucideIcon } from "lucide-react";
import { useIsMobile } from "@/hooks/useMediaQuery";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface ResponsiveActionMenuProps {
  /** Controlled open state */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Trigger element (button) */
  trigger: React.ReactNode;
  /** Menu title (shown in mobile sheet header) */
  title?: string;
  /** Menu description (shown in mobile sheet) */
  description?: string;
  /** Menu items */
  children: React.ReactNode;
  /** Dropdown content alignment (desktop only) */
  align?: "start" | "center" | "end";
  /** Additional class for dropdown content */
  contentClassName?: string;
}

interface ActionMenuItemProps {
  /** Item icon */
  icon?: LucideIcon;
  /** Item label */
  children: React.ReactNode;
  /** Click handler */
  onClick?: () => void;
  /** Disabled state */
  disabled?: boolean;
  /** Variant */
  variant?: "default" | "destructive";
  /** Additional class name */
  className?: string;
}

interface ActionMenuSeparatorProps {
  className?: string;
}

interface ActionMenuLabelProps {
  children: React.ReactNode;
  className?: string;
}

// =============================================================================
// CONTEXT
// =============================================================================

const ResponsiveActionMenuContext = React.createContext<{
  isMobile: boolean;
  onOpenChange: (open: boolean) => void;
}>({
  isMobile: false,
  onOpenChange: () => {},
});

function useResponsiveActionMenuContext() {
  return React.useContext(ResponsiveActionMenuContext);
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function ResponsiveActionMenu({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  align = "end",
  contentClassName,
}: ResponsiveActionMenuProps) {
  const isMobile = useIsMobile();

  return (
    <ResponsiveActionMenuContext.Provider value={{ isMobile, onOpenChange }}>
      {isMobile ? (
        <>
          {/* Mobile: Trigger opens the sheet */}
          <div onClick={() => onOpenChange(true)}>{trigger}</div>
          <MobileActionSheet
            open={open}
            onOpenChange={onOpenChange}
            title={title}
            description={description}
          >
            {children}
          </MobileActionSheet>
        </>
      ) : (
        <DropdownMenu open={open} onOpenChange={onOpenChange}>
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
          <DropdownMenuContent align={align} className={contentClassName}>
            {title && <DropdownMenuLabel>{title}</DropdownMenuLabel>}
            {title && <DropdownMenuSeparator />}
            {children}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </ResponsiveActionMenuContext.Provider>
  );
}

// =============================================================================
// MENU ITEM
// =============================================================================

function ActionMenuItem({
  icon: Icon,
  children,
  onClick,
  disabled,
  variant = "default",
  className,
}: ActionMenuItemProps) {
  const { isMobile, onOpenChange } = useResponsiveActionMenuContext();

  const handleClick = () => {
    onClick?.();
    onOpenChange(false);
  };

  if (isMobile) {
    return (
      <MobileActionSheet.Item
        icon={Icon}
        onClick={handleClick}
        disabled={disabled}
        variant={variant}
        className={className}
      >
        {children}
      </MobileActionSheet.Item>
    );
  }

  return (
    <DropdownMenuItem
      onClick={handleClick}
      disabled={disabled}
      className={cn(
        variant === "destructive" && "text-destructive focus:text-destructive",
        className
      )}
    >
      {Icon && <Icon className="mr-2 h-4 w-4" />}
      {children}
    </DropdownMenuItem>
  );
}

// =============================================================================
// SEPARATOR
// =============================================================================

function ActionMenuSeparator({ className }: ActionMenuSeparatorProps) {
  const { isMobile } = useResponsiveActionMenuContext();

  if (isMobile) {
    return <MobileActionSheet.Divider className={className} />;
  }

  return <DropdownMenuSeparator className={className} />;
}

// =============================================================================
// LABEL
// =============================================================================

function ActionMenuLabel({ children, className }: ActionMenuLabelProps) {
  const { isMobile } = useResponsiveActionMenuContext();

  if (isMobile) {
    return (
      <div
        className={cn(
          "px-4 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider",
          className
        )}
      >
        {children}
      </div>
    );
  }

  return <DropdownMenuLabel className={className}>{children}</DropdownMenuLabel>;
}

// =============================================================================
// EXPORTS
// =============================================================================

// Attach subcomponents
ResponsiveActionMenu.Item = ActionMenuItem;
ResponsiveActionMenu.Separator = ActionMenuSeparator;
ResponsiveActionMenu.Label = ActionMenuLabel;

export { ResponsiveActionMenu };
export type {
  ResponsiveActionMenuProps,
  ActionMenuItemProps,
  ActionMenuSeparatorProps,
  ActionMenuLabelProps,
};
