// src/components/layouts/PageContainer.tsx
import { cn } from "@/lib/utils";

interface PageContainerProps {
  children: React.ReactNode;
  maxWidth?: "sm" | "md" | "lg" | "xl" | "full";
  className?: string;
}

/**
 * PageContainer - Standardized wrapper for page content
 *
 * Provides consistent container, padding, and spacing across all pages.
 *
 * @param maxWidth - Controls the maximum width of the container
 *   - sm: max-w-2xl (672px) - Best for forms, settings
 *   - md: max-w-4xl (896px) - Best for content-focused pages
 *   - lg: max-w-6xl (1152px) - Best for dashboards
 *   - xl: max-w-7xl (1280px) - Best for wide tables
 *   - full: No max-width constraint - Best for full-width layouts
 *
 * @example
 * ```tsx
 * <PageContainer maxWidth="md">
 *   <PageHeader title="Settings" />
 *   <SettingsForm />
 * </PageContainer>
 * ```
 */
export function PageContainer({
  children,
  maxWidth = "full",
  className
}: PageContainerProps) {
  const maxWidthClasses = {
    sm: "max-w-2xl",
    md: "max-w-4xl",
    lg: "max-w-6xl",
    xl: "max-w-7xl",
    full: ""
  };

  return (
    <div className={cn(
      // Uses CSS vars: --page-padding-y and --section-gap for consistency
      "container mx-auto py-[var(--page-padding-y)] space-y-[var(--section-gap)]",
      maxWidthClasses[maxWidth],
      className
    )}>
      {children}
    </div>
  );
}
