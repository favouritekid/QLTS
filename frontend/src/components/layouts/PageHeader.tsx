// src/components/layouts/PageHeader.tsx
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type PageHeaderVariant = "default" | "sticky";

interface PageHeaderProps {
  title: string;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  backButton?: {
    href: string;
    label?: string;
  };
  actions?: React.ReactNode;
  className?: string;
  /**
   * Header variant:
   * - `default`: Standard header for content pages (Dashboard, Settings)
   * - `sticky`: Sticky header with backdrop-blur for long lists (Leads)
   */
  variant?: PageHeaderVariant;
  /**
   * Compact mode reduces padding and title size (useful for sticky variant)
   */
  compact?: boolean;
}

/**
 * PageHeader - Standardized page header component
 *
 * Supports multiple patterns:
 * - Standard: Title + Description
 * - With Icon: Icon + Title
 * - With Back Button: Back Arrow + Title
 * - With Actions: Title + Action Button(s)
 *
 * Variants:
 * - `default`: For content pages (Dashboard, Settings)
 * - `sticky`: For long lists (Leads), with backdrop-blur and sticky positioning
 *
 * @example
 * ```tsx
 * // Standard header (default variant)
 * <PageHeader
 *   title="Dashboard"
 *   description="Welcome back!"
 *   actions={<Button>Export</Button>}
 * />
 *
 * // Sticky header for lists
 * <PageHeader
 *   variant="sticky"
 *   title="Lead Management"
 *   icon={<Command className="h-5 w-5" />}
 *   description="1,234 leads"
 *   actions={<Button size="sm">Import</Button>}
 *   compact
 * />
 *
 * // With back button
 * <PageHeader
 *   title="Lead Details"
 *   backButton={{ href: "/leads", label: "Back to Leads" }}
 * />
 * ```
 */
export function PageHeader({
  title,
  description,
  icon,
  backButton,
  actions,
  className,
  variant = "default",
  compact = false,
}: PageHeaderProps) {
  const isSticky = variant === "sticky";

  return (
    <header
      className={cn(
        "flex items-center justify-between",
        // Sticky variant styles
        isSticky && [
          "sticky top-0 z-10",
          "bg-background/95 supports-[backdrop-filter]:bg-background/60",
          "backdrop-blur border-b",
          "px-4 py-3",
        ],
        // Compact mode
        compact && "py-2",
        className
      )}
    >
      <div className="flex items-center gap-3">
        {/* Back Button */}
        {backButton && (
          <Button variant="ghost" size="icon" asChild>
            <Link href={backButton.href} aria-label={backButton.label || "Go back"}>
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
        )}

        {/* Icon (separate from title for sticky variant) */}
        {icon && isSticky && (
          <div className="bg-primary/10 rounded-lg p-2">
            {icon}
          </div>
        )}

        {/* Title Section */}
        <div>
          <h1
            className={cn(
              "font-bold tracking-tight font-display",
              // Size based on variant/compact
              compact || isSticky ? "text-xl" : "text-2xl md:text-3xl",
              // Icon inline for default variant
              icon && !isSticky && "flex items-center gap-2"
            )}
          >
            {icon && !isSticky && icon}
            {title}
          </h1>
          {description && (
            <p className={cn(
              "text-muted-foreground",
              compact || isSticky ? "text-xs" : "text-sm mt-1"
            )}>
              {description}
            </p>
          )}
        </div>
      </div>

      {/* Actions Area */}
      {actions && (
        <div className="flex items-center gap-2">
          {actions}
        </div>
      )}
    </header>
  );
}
