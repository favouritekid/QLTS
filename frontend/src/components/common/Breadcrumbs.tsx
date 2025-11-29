/**
 * Breadcrumbs Component
 * Displays navigation breadcrumb trail based on current route
 */

"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useNavigation } from "@/hooks/useNavigation";

interface BreadcrumbsProps {
  className?: string;
}

export function Breadcrumbs({ className }: BreadcrumbsProps) {
  const { breadcrumbs } = useNavigation();

  if (breadcrumbs.length === 0) {
    return null;
  }

  return (
    <nav
      className={cn(
        "flex items-center space-x-1 text-sm",
        "animate-in fade-in-0 slide-in-from-top-2 duration-500",
        className
      )}
      aria-label="Breadcrumb"
    >
      {breadcrumbs.map((crumb, index) => {
        const isLast = index === breadcrumbs.length - 1;

        return (
          <div
            key={crumb.path}
            className="flex items-center animate-in fade-in-0 slide-in-from-left-1 duration-300"
            style={{ animationDelay: `${index * 50}ms` }}
          >
            {index > 0 && (
              <ChevronRight className="mx-1 h-4 w-4 text-muted-foreground opacity-60" />
            )}
            {isLast ? (
              <span className="font-semibold text-foreground px-2 py-1 rounded-md bg-muted/50">
                {crumb.label}
              </span>
            ) : (
              <Link
                href={crumb.path}
                className={cn(
                  "text-muted-foreground hover:text-foreground",
                  "transition-all duration-200 ease-in-out",
                  "px-2 py-1 rounded-md hover:bg-muted/50",
                  "hover:scale-105 active:scale-95"
                )}
              >
                {crumb.label}
              </Link>
            )}
          </div>
        );
      })}
    </nav>
  );
}
