// src/components/layouts/PageHeader.tsx
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  backButton?: {
    href: string;
    label?: string;
  };
  actions?: React.ReactNode;
  className?: string;
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
 * @example
 * ```tsx
 * // Standard header
 * <PageHeader
 *   title="Notifications"
 *   description="Stay updated with your latest notifications"
 * />
 *
 * // With icon
 * <PageHeader
 *   title="Distribution Rules"
 *   icon={<Share2 className="h-8 w-8" />}
 *   description="Configure lead distribution"
 * />
 *
 * // With back button
 * <PageHeader
 *   title="Lead Details"
 *   backButton={{ href: "/leads", label: "Back to Leads" }}
 * />
 *
 * // With actions
 * <PageHeader
 *   title="Policies"
 *   description="Manage policies"
 *   actions={
 *     <Button><Plus /> Add Policy</Button>
 *   }
 * />
 * ```
 */
export function PageHeader({
  title,
  description,
  icon,
  backButton,
  actions,
  className
}: PageHeaderProps) {
  return (
    <header className={cn("flex items-center justify-between", className)}>
      <div className="flex items-center gap-4">
        {/* Back Button */}
        {backButton && (
          <Button variant="ghost" size="icon" asChild>
            <Link href={backButton.href} aria-label={backButton.label || "Go back"}>
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
        )}

        {/* Title Section */}
        <div>
          <h1 className={cn(
            "text-3xl font-bold tracking-tight",
            icon && "flex items-center gap-2"
          )}>
            {icon}
            {title}
          </h1>
          {description && (
            <p className="text-muted-foreground mt-1">{description}</p>
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
