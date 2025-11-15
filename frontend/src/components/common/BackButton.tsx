/**
 * Smart Back Button Component
 * Automatically determines back navigation based on route configuration
 */

"use client";

import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNavigation } from "@/hooks/useNavigation";
import { cn } from "@/lib/utils";

interface BackButtonProps {
  variant?: "default" | "ghost" | "outline";
  size?: "default" | "sm" | "lg" | "icon";
  className?: string;
  showLabel?: boolean;
  label?: string;
}

export function BackButton({
  variant = "ghost",
  size = "default",
  className,
  showLabel = true,
  label,
}: BackButtonProps) {
  const { goBack, canGoBack, breadcrumbs } = useNavigation();

  if (!canGoBack) {
    return null;
  }

  // Get parent label for button text
  const parentLabel = breadcrumbs.length > 1
    ? breadcrumbs[breadcrumbs.length - 2].label
    : "Back";

  const buttonLabel = label || (showLabel ? `Back to ${parentLabel}` : "");

  return (
    <Button
      variant={variant}
      size={size}
      onClick={goBack}
      className={cn("gap-2", className)}
    >
      <ArrowLeft className="h-4 w-4" />
      {buttonLabel && <span>{buttonLabel}</span>}
    </Button>
  );
}
