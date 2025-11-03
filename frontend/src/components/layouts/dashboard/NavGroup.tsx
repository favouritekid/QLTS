// src/components/layouts/dashboard/NavGroup.tsx
"use client";

import { cn } from "@/lib/utils";
import type { NavigationLink } from "@/types/layout.types.ts";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

type NavGroupProps = {
  links: NavigationLink[];
  isCollapsed: boolean;
  title?: string;
};

export function NavGroup({ links, isCollapsed, title }: NavGroupProps) {
  const pathname = usePathname();

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex flex-col gap-0.5">
        {/* Hiển thị tiêu đề nhóm khi mở rộng */}
        {title && !isCollapsed && (
          <h4 className="text-muted-foreground mt-3 mb-1 ml-4 text-xs font-medium">{title}</h4>
        )}
        {links.map((link) => {
          const isActive =
            pathname === link.href || (link.href !== "/" && pathname.startsWith(link.href));

          // Giao diện khi THU GỌN
          if (isCollapsed) {
            return (
              <Tooltip key={link.href}>
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

          // Giao diện khi Mở RỘNG
          return (
            <Link
              key={link.href}
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
        })}
      </div>
    </TooltipProvider>
  );
}
