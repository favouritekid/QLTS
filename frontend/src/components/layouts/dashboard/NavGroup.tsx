// src/components/layouts/dashboard/NavGroup.tsx
"use client";

import type { NavigationLink } from "@/types/layout.types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NavItem } from "./NavItem";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useNavigationState } from "@/hooks/useNavigationState";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

type NavGroupProps = {
  links: NavigationLink[];
  isCollapsed: boolean;
  title?: string;
};

export function NavGroup({ links, isCollapsed, title }: NavGroupProps) {
  const { isCollapsed: isGroupCollapsed, toggleGroup } = useNavigationState();

  // Don't render if no links
  if (links.length === 0) return null;

  // If sidebar is collapsed, don't show group titles or collapse functionality
  if (isCollapsed) {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="flex flex-col gap-0.5">
          {links.map((link) => (
            <NavItem key={link.href} link={link} isCollapsed={isCollapsed} />
          ))}
        </div>
      </TooltipProvider>
    );
  }

  // If no title, render as flat list (no collapsible)
  if (!title) {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="flex flex-col gap-0.5">
          {links.map((link) => (
            <NavItem key={link.href} link={link} isCollapsed={isCollapsed} />
          ))}
        </div>
      </TooltipProvider>
    );
  }

  // Full sidebar with collapsible groups
  const groupCollapsed = isGroupCollapsed(title);

  return (
    <TooltipProvider delayDuration={0}>
      <Collapsible open={!groupCollapsed} onOpenChange={() => toggleGroup(title)}>
        <div className="flex flex-col gap-0.5">
          {/* Group Header - Clickable to toggle collapse */}
          <CollapsibleTrigger asChild>
            <button
              className={cn(
                "text-muted-foreground hover:text-foreground flex items-center justify-between",
                "mt-3 mb-1 px-4 py-1.5 rounded-md transition-colors",
                "hover:bg-muted/50 group w-full text-left",
                "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              )}
              aria-expanded={!groupCollapsed}
              aria-label={`Toggle ${title} group`}
            >
              <h4 className="text-xs font-semibold uppercase tracking-wider">{title}</h4>
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform duration-200 opacity-70 group-hover:opacity-100",
                  !groupCollapsed && "rotate-180"
                )}
                aria-hidden="true"
              />
            </button>
          </CollapsibleTrigger>

          {/* Group Items - Collapsible */}
          <CollapsibleContent className="space-y-0.5">
            {links.map((link) => (
              <NavItem key={link.href} link={link} isCollapsed={false} />
            ))}
          </CollapsibleContent>
        </div>
      </Collapsible>
    </TooltipProvider>
  );
}
