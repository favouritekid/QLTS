// src/components/layouts/dashboard/NavGroup.tsx
"use client";

import type { NavigationLink } from "@/types/layout.types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NavItem } from "./NavItem";

type NavGroupProps = {
  links: NavigationLink[];
  isCollapsed: boolean;
  title?: string;
};

export function NavGroup({ links, isCollapsed, title }: NavGroupProps) {
  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex flex-col gap-0.5">
        {/* Hiển thị tiêu đề nhóm khi mở rộng */}
        {title && !isCollapsed && (
          <h4 className="text-muted-foreground mt-3 mb-1 ml-4 text-xs font-medium">{title}</h4>
        )}
        {links.map((link) => (
          <NavItem key={link.href} link={link} isCollapsed={isCollapsed} />
        ))}
      </div>
    </TooltipProvider>
  );
}
