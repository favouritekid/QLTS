// src/components/layouts/dashboard/NavItem.tsx
"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { NavigationLink } from "@/types/layout.types";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { ChevronDown } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type NavItemProps = {
  link: NavigationLink;
  isCollapsed: boolean;
};

export function NavItem({ link, isCollapsed }: NavItemProps) {
  const pathname = usePathname();
  const [isExpanded, setIsExpanded] = useState(true);

  const hasChildren = link.children && link.children.length > 0;

  // Helper function to check if a path matches the current pathname
  // Only matches exact path or child paths (with trailing slash check)
  const isPathActive = (href: string) => {
    if (pathname === href) return true;
    if (href === "/") return false; // Never match root with startsWith
    // Only match if pathname starts with href followed by a slash
    return pathname.startsWith(href + "/");
  };

  // Check if current path matches this link or any of its children
  const isActive = hasChildren
    ? link.children?.some(child => isPathActive(child.href))
    : isPathActive(link.href);

  // If collapsed, show icon with tooltip
  if (isCollapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Link
            href={link.href}
            className={cn(
              "text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 w-9 items-center justify-center rounded-lg transition-colors",
              isActive &&
                "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
            )}
          >
            {link.icon && <link.icon className="h-5 w-5" />}
            <span className="sr-only">{link.label}</span>
          </Link>
        </TooltipTrigger>
        <TooltipContent
          side="right"
          className="bg-popover text-popover-foreground border shadow-md"
        >
          {link.label}
          {link.badge && (
            <Badge className="ml-2" variant="secondary">
              {link.badge}
            </Badge>
          )}
        </TooltipContent>
      </Tooltip>
    );
  }

  // If has children, render as collapsible group
  if (hasChildren) {
    return (
      <div className="flex flex-col gap-0.5">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className={cn(
            "text-muted-foreground hover:bg-muted hover:text-primary flex items-center gap-3 rounded-lg px-3 py-2 transition-all w-full",
            isActive && "text-primary font-medium"
          )}
        >
          {link.icon && <link.icon className="h-4 w-4" />}
          <span className="flex-1 text-left">{link.label}</span>
          {link.badge && (
            <Badge className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
              {link.badge}
            </Badge>
          )}
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform",
              isExpanded && "transform rotate-180"
            )}
          />
        </button>

        {/* Children - Improved mobile hierarchy */}
        {isExpanded && (
          <div className="ml-4 lg:ml-6 flex flex-col gap-0.5 mt-1 border-l-2 border-border pl-2 lg:pl-4">
            {link.children?.map((child) => {
              const isChildActive = isPathActive(child.href);
              return (
                <Link
                  key={child.href}
                  href={child.href}
                  className={cn(
                    "text-muted-foreground hover:bg-muted hover:text-primary flex items-center gap-2 lg:gap-3 rounded-lg px-2 lg:px-3 py-2 transition-all text-sm",
                    isChildActive &&
                      "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground font-medium"
                  )}
                >
                  {child.icon && <child.icon className="h-3.5 w-3.5 flex-shrink-0" />}
                  <span className="flex-1 truncate">{child.label}</span>
                  {child.badge && (
                    <Badge className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs">
                      {child.badge}
                    </Badge>
                  )}
                </Link>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // Regular link without children
  return (
    <Link
      href={link.href}
      className={cn(
        "text-muted-foreground hover:bg-muted hover:text-primary flex items-center gap-3 rounded-lg px-3 py-2 transition-all",
        isActive &&
          "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
      )}
    >
      {link.icon && <link.icon className="h-4 w-4" />}
      <span className="flex-1">{link.label}</span>
      {link.badge && (
        <Badge className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
          {link.badge}
        </Badge>
      )}
    </Link>
  );
}
